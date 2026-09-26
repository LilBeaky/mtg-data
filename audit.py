#!/usr/bin/env python3
"""
audit.py — the default full deck audit for mtg-data. One command, every check.

USAGE
  python3 audit.py DECK.txt [options]

OPTIONS
  --commander NAME     if the list has no Commander section
  --bracket N          target bracket (default: read from a "bracket: N" header line)
  --draw               odds on the draw (default: on the play)
  --k ROLE=N           confirmed count for a role; overrides tags. Repeatable:
                       --k protection=7 --k ramp=11
  --snapshot PATH      EDHREC snapshot to diff (default: newest match in edhrec_snapshots/)
  --no-edhrec          skip the EDHREC section
  --min N / --limit N  passed to edhrec_diff.py diff
  --all-combos         passed to mtg.py deck
  --no-lists           hide the card list under each role (default: shown)

SECTIONS
  1 Legality & bracket  mtg.py deck + GC allowance, 2-card combos, extra-turn / MLD flags
  2 Mana base           lands, tapped lands, MDFCs, ramp, opening-hand odds
  3 Commander on curve  lands-only floor, and with 1-MV accelerants
  4 Roles & odds        K per role from YOUR #tags > --k overrides > Scryfall oracle tags.
                        Flags K-SENSITIVE roles, where the count source moves the odds >= 15 pts
  5 Density & flood     action vs mana in the first 12 cards
  6 EDHREC              edhrec_diff.py against the newest matching snapshot
  7 Manual checklist    what no script here can verify

Odds: exact hypergeometric, 7-card hand, London mulligan (see STATS_MATH.md).
"""
import os, re, sys, glob, subprocess, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import mtg
import stats_math as sm
from categories import CATEGORIES, STRICT, AUDIT_ROLES, USER_SYNONYMS

SENSITIVE_PTS = 15
STALE_DAYS = 30
GC_ALLOW = {1: 0, 2: 0, 3: 3}
MLD_RX = re.compile(
    r"(destroy|exile)s? all [\w, ]*?lands\b|sacrifices? (all|half|x|that many) (of their |nonbasic )?lands"
    r"|lands (don't|do not) untap|can't untap more than|each (player|opponent) sacrifices .{0,25}lands", re.I)
FLAG_ONLY = {"extra_turns"}          # reported in section 1, not as a role row
SUBSET_ROLES = {"spot_removal", "reanimation", "mana_producers"}   # narrower copies of removal/recursion; shown only on request


# ---------- helpers ----------
def pct(p):
    return f"{100 * p:5.1f}%"

def is_land(c):
    return "Land" in c.get("type_line", "").split("//")[0]

def is_mdfc_land(c):
    faces = c.get("card_faces") or []
    return (not is_land(c)) and len(faces) > 1 and "Land" in (faces[1].get("type_line") or "")

def tapped_kind(c):
    """'always' / 'conditional' / None, from oracle text."""
    if "Basic" in c.get("type_line", ""):
        return None
    t = mtg.text_of(c)
    if re.search(r"enters( the battlefield)? tapped", t):
        return "conditional" if re.search(r"tapped unless|if you don't|if you do not|unless you", t, re.I) else "always"
    if "onto the battlefield tapped" in t and "earch" in t:     # tapped fetches (Evolving Wilds)
        return "conditional" if "untap that land" in t else "always"
    return None

def slug(name):
    s = name.lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

PETS = set()
def names_str(items, limit=40):
    items = sorted(items)
    out = "; ".join(n + (" [pet]" if n in PETS else "") for n in items[:limit])
    return out + (f" (+{len(items) - limit} more)" if len(items) > limit else "")

def parse_args(argv):
    o, pos, i = {"k": {}}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--commander", "--bracket", "--snapshot", "--min", "--limit", "--k"):
            if i + 1 >= len(argv):
                sys.exit(f"{a} needs a value")
            v = argv[i + 1]; i += 2
            if a == "--k":
                r, _, n = v.partition("=")
                o["k"][r.strip()] = int(n)
            else:
                o[a[2:]] = v
            continue
        if a in ("--draw", "--no-edhrec", "--all-combos", "--no-lists"):
            o[a[2:]] = True; i += 1; continue
        pos.append(a); i += 1
    if not pos:
        print(__doc__); sys.exit(1)
    o["path"] = pos[0]
    return o


# ---------- main ----------
def main():
    o = parse_args(sys.argv[1:])
    path = o["path"]
    on_play = not o.get("draw")
    seen = lambda t: sm.cards_seen(t, on_play)
    lists = not o.get("no-lists")

    entries = mtg.parse_deck(path, with_tags=True)
    meta = mtg.parse_deck_meta(path)
    N, cmd_names, comp_names = sm.count_population(path, o.get("commander"))
    cmdrs = [c for c in (mtg.find(n)[0] for n in cmd_names) if c]

    lib, notfound = [], []          # lib: (qty, name, card, [normalized user tags])
    for s, q, n, tags in entries:
        if s in sm.EXCLUDED_FROM_POPULATION:
            continue
        c, how = mtg.find(n)
        if not c:
            notfound.append(n); continue
        lib.append((q, c["name"], c, [sm.norm_label(t) for t in tags]))
    qty_of = {}
    for q, n, c, t in lib:
        qty_of[n] = qty_of.get(n, 0) + q
    K_of = lambda names: sum(qty_of[n] for n in names)

    bracket = int(o["bracket"]) if o.get("bracket") else meta.get("bracket")
    pets = {c["name"] for c in (mtg.find(p)[0] for p in meta.get("pets", [])) if c}
    PETS.update(pets)

    # ----- roles: oracle sets, user sets, label mapping -----
    trees = mtg.load_tags_multi(sorted({l for v in CATEGORIES.values() for l in sm._as_labels(v)}))
    oids = {r: sm.tag_oids(v, trees) for r, v in CATEGORIES.items()}
    subtree = {r: {sm.norm_label(l) for l in sm.tag_labels(v, trees)} for r, v in CATEGORIES.items()}
    roots = {r: {sm.norm_label(l) for l in ((v,) if isinstance(v, str) else v)} for r, v in CATEGORIES.items()}
    role_labels = {r: subtree[r] | {sm.norm_label(r)} | USER_SYNONYMS.get(r, set()) for r in CATEGORIES}
    for r in CATEGORIES:                       # nested categories inherit synonyms (wipe -> removal too)
        for r2 in CATEGORIES:
            if r2 != r and roots[r2] <= subtree[r]:
                role_labels[r] |= USER_SYNONYMS.get(r2, set())

    def in_scope(r, c):
        return not (r == "ramp" and is_land(c))    # land ramp is counted in the mana base, not here
    oset = {r: {n for q, n, c, t in lib if c.get("oracle_id") in oids[r] and in_scope(r, c)} for r in CATEGORIES}
    uset = {r: {n for q, n, c, t in lib if set(t) & role_labels[r] and in_scope(r, c)} for r in CATEGORIES}

    nonland = [(q, n, c, t) for q, n, c, t in lib if not is_land(c)]
    nl_total = sum(q for q, *_ in nonland) or 1
    tagged_nl = sum(q for q, n, c, t in nonland if t)
    any_user = any(t for *_, t in lib)
    coverage = tagged_nl / nl_total
    user_primary = coverage >= 0.5

    def primary(r):
        if r in o["k"]:
            return o["k"][r], "confirmed", oset[r]
        if user_primary:
            return K_of(uset[r]), "your tags", uset[r]
        return K_of(oset[r]), "oracle tags", oset[r]

    def alt_ks(r, K, src):
        """Other plausible counts for role r: oracle tags, your tags, the strict mapping."""
        alts = []
        if src != "oracle tags": alts.append(("oracle tags", K_of(oset[r])))
        if any_user and src != "your tags": alts.append(("your tags", K_of(uset[r])))
        if r in STRICT and src != "confirmed": alts.append((f"strict {STRICT[r]}", K_of(oset[STRICT[r]])))
        seen_k, out = {K}, []
        for lab, K2 in alts:
            if K2 not in seen_k:
                seen_k.add(K2); out.append((lab, K2))
        return out

    def odds(K):
        return (sm.hyper_at_least(N, K, 7, 1), sm.hyper_at_least(N, K, seen(3), 1),
                sm.hyper_at_least(N, K, seen(4), 1), sm.hyper_at_least(N, K, seen(6), 2))

    # ----- header -----
    today = datetime.date.today()
    print(f"=== AUDIT: {' + '.join(c['name'] for c in cmdrs) or 'no commander'} | N={N} library cards | "
          f"{'on the play' if on_play else 'on the draw'} | {today} ===")
    if any_user:
        print(f"role source: {'YOUR TAGS' if user_primary else 'oracle tags'} "
              f"(#tags on {100 * coverage:.0f}% of nonland cards"
              f"{'' if user_primary else '; under 50%, so shown for comparison only'})")
    else:
        print("role source: Scryfall oracle tags (no #tags in this list) — broad counts are candidates, not truth")
    if o["k"]:
        print("confirmed overrides: " + ", ".join(f"{r}={k}" for r, k in o["k"].items()))

    # ----- 1. legality & bracket -----
    print("\n## 1. Legality & bracket")
    cmd = [sys.executable, os.path.join(ROOT, "mtg.py"), "deck", path]
    if o.get("commander"): cmd += ["--commander", o["commander"]]
    if o.get("all-combos"): cmd += ["--all-combos"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    for line in (r.stdout + r.stderr).strip().splitlines():
        if not line.startswith("note: MLD and extra-turn"):     # audit.py flags these itself below
            print("  " + line)
    gcs = sorted({c["name"] for c in cmdrs if c.get("game_changer")} |
                 {n for q, n, c, t in lib if c.get("game_changer")})
    comp_cards = [c for c in (mtg.find(n)[0] for n in comp_names) if c]
    ts, dc = mtg.deck_combos([n for q, n, c, t in lib] + [c["name"] for c in cmdrs + comp_cards])
    two = [v for v in (dc or []) if len(v["cards"]) == 2]
    xturn = sorted(oset["extra_turns"])
    mld = sorted(n for q, n, c, t in lib if MLD_RX.search(mtg.text_of(c)))
    if bracket:
        allow = GC_ALLOW.get(bracket)
        gc_v = "unlimited" if allow is None else ("OK" if len(gcs) <= allow else f"OVER by {len(gcs) - allow}")
        print(f"  bracket target {bracket}: Game Changers {len(gcs)}/{'∞' if allow is None else allow} — {gc_v}")
        if bracket <= 2 and two:
            print(f"  ⚠ {len(two)} two-card combo(s) — not allowed at B{bracket}")
        elif bracket == 3 and two:
            print(f"  ⚠ {len(two)} two-card combo(s) — B3 allows them only if they can't win before T6; confirm")
        if xturn:
            rule = "B1 allows none" if bracket == 1 else "no chaining at B2–3" if bracket <= 3 else "fine at B4+"
            print(f"  extra-turn cards ({rule}): {'; '.join(xturn)}")
        if mld and bracket <= 3:
            print(f"  ⚠ possible MLD (B1–3 allow none) — review: {'; '.join(mld)}")
    else:
        print(f"  no target bracket (add 'bracket: N' to the list or pass --bracket) — "
              f"GCs {len(gcs)}, two-card combos {len(two)}, extra turns {len(xturn)}, MLD flags {len(mld)}")
        if xturn: print(f"  extra-turn cards: {'; '.join(xturn)}")
        if mld: print(f"  possible MLD — review: {'; '.join(mld)}")

    # ----- 2. mana base -----
    print("\n## 2. Mana base")
    lands = [(q, n, c) for q, n, c, t in lib if is_land(c)]
    L = sum(q for q, *_ in lands)
    basics = sum(q for q, n, c in lands if "Basic" in c.get("type_line", ""))
    always = sorted(n for q, n, c in lands if tapped_kind(c) == "always")
    cond = sorted(n for q, n, c in lands if tapped_kind(c) == "conditional")
    mdfc = sorted(n for q, n, c, t in lib if is_mdfc_land(c))
    RK, rsrc, rset = primary("ramp")
    accel = sorted(n for n in (rset or oset["ramp"]) if mtg.find(n)[0].get("cmc", 99) <= 1)
    A = K_of(accel)
    M = L + RK
    ramp_alts = alt_ks("ramp", RK, rsrc)
    print(f"  lands {L} ({basics} basic) | nonland ramp {RK} ({rsrc}) | mana sources ~{M} of {N}"
          + ("".join(f" | alt ramp {K2} ({lab})" for lab, K2 in ramp_alts)))
    print(f"  always tapped ({len(always)}): {'; '.join(always) or 'none'}")
    if cond: print(f"  conditionally tapped ({len(cond)}): {'; '.join(cond)}")
    cr = sorted(oset["cost_reducers"])
    if cr: print(f"  cost reducers ({K_of(cr)}, not counted as ramp — they still speed the deck up): {'; '.join(cr)}")
    if mdfc: print(f"  MDFC land backs ({len(mdfc)}, not counted as lands): {'; '.join(mdfc)}")
    p01 = sm.hyper_pmf(N, L, 7, 0) + sm.hyper_pmf(N, L, 7, 1)
    p24 = sum(sm.hyper_pmf(N, L, 7, k) for k in (2, 3, 4))
    line = f"  opener: 0–1 lands {pct(p01)} | 2–4 lands {pct(p24)} | 5+ lands {pct(sm.hyper_at_least(N, L, 7, 5))}"
    if mdfc:
        line += f" | 2–4 counting MDFCs {pct(sum(sm.hyper_pmf(N, L + len(mdfc), 7, k) for k in (2, 3, 4)))}"
    print(line)
    print(f"  opener: ≤2 non-mana cards {pct(sm.hyper_at_least(N, M, 7, 5))} | "
          f"≥1 one-MV accelerant ({A}: {'; '.join(accel) or 'none'}) {pct(sm.hyper_at_least(N, A, 7, 1))}")

    # ----- 3. commander on curve -----
    if cmdrs:
        print(f"\n## 3. Commander on curve (treats every land as untapped; {len(always)} always-tapped lands make this slightly optimistic)")
        for c in cmdrs:
            m = int(c.get("cmc", 0))
            if m < 1:
                print(f"  {c['name']}: MV 0 — n/a"); continue
            n = seen(m)
            floor = sm.hyper_at_least(N, L, n, m)
            msg = f"  {c['name']} (MV {m}) on T{m}: lands only {pct(floor)}"
            if m >= 2 and A:
                extra = sm.multivariate_at_least(N, [(L, m - 1), (A, 1)], n) - sm.multivariate_at_least(N, [(L, m), (A, 1)], n)
                msg += f" | with a 1-MV accelerant {pct(floor + extra)}"
            print(msg)

    # ----- 4. roles & odds -----
    t = "play" if on_play else "draw"
    print(f"\n## 4. Roles & odds (on the {t}: opener = 7 cards, T3 = {seen(3)}, T4 = {seen(4)}, T6 = {seen(6)})")
    report = AUDIT_ROLES + [r for r in CATEGORIES if r not in AUDIT_ROLES and r not in FLAG_ONLY
                            and (r not in SUBSET_ROLES or uset[r] or r in o["k"])
                            and (oset[r] or uset[r] or r in o["k"])]
    flagged = []
    for r in report:
        K, src, names = primary(r)
        a = odds(K)
        print(f"  {r:<15} K={K:<3} {src:<11} | opener ≥1 {pct(a[0])} | T3 ≥1 {pct(a[1])} | "
              f"T4 ≥1 {pct(a[2])} | T6 ≥2 {pct(a[3])}")
        if lists and names:
            label = "candidates" if src == "confirmed" else "cards"
            print(f"      {label}: {names_str(names)}")
        if any_user and src != "confirmed":
            extra_o, extra_u = oset[r] - uset[r], uset[r] - oset[r]
            if user_primary and extra_o: print(f"      oracle tags also flag: {names_str(extra_o, 15)}")
            if user_primary and extra_u: print(f"      only your tags: {names_str(extra_u, 15)}")
        for lab, K2 in alt_ks(r, K, src):
            b = odds(K2)
            swing = 100 * max(abs(a[2] - b[2]), abs(a[3] - b[3]))
            warn = "  ⚠ K-SENSITIVE — confirm the real count" if swing >= SENSITIVE_PTS and src != "confirmed" else ""
            if warn: flagged.append(r)
            print(f"      alt K={K2} ({lab}): T4 ≥1 {pct(b[2])} | T6 ≥2 {pct(b[3])}{warn}")
    known = set().union(*role_labels.values())
    custom = {}
    for q, n, c, tags in lib:
        for tg in tags:
            if tg not in known: custom.setdefault(tg, set()).add(n)
    if custom:
        print("  your custom tags:")
        for tg, names in sorted(custom.items(), key=lambda kv: -K_of(kv[1])):
            a = odds(K_of(names))
            print(f"  #{tg:<14} K={K_of(names):<3} | opener ≥1 {pct(a[0])} | T4 ≥1 {pct(a[2])} | T6 ≥2 {pct(a[3])}"
                  + (f"  — {names_str(names, 12)}" if lists else ""))

    # ----- 5. density & flood -----
    print("\n## 5. Density & flood (first 12 cards ≈ T6 on the play)")
    def density(Mx):
        return sm.hyper_at_least(N, N - Mx, 12, 4), sm.hyper_at_least(N, Mx, 12, 8)
    d = density(M)
    print(f"  ≥4 non-mana cards in 12: {pct(d[0])} | 8+ mana sources in 12 (flood): {pct(d[1])} | "
          f"expected mana cards in 12: {12 * M / N:.1f}  [ramp K={RK}, {rsrc}]")
    for lab, K2 in ramp_alts:
        d2 = density(L + K2)
        swing = 100 * max(abs(d[0] - d2[0]), abs(d[1] - d2[1]))
        warn = "  ⚠ K-SENSITIVE — confirm the ramp count" if swing >= SENSITIVE_PTS and rsrc != "confirmed" else ""
        if warn: flagged.append("ramp")
        print(f"      alt ramp K={K2} ({lab}): ≥4 non-mana in 12 {pct(d2[0])} | flood {pct(d2[1])}{warn}")
    print(f"  ≤2 lands by T4 (screw): {pct(1 - sm.hyper_at_least(N, L, seen(4), 3))} | "
          f"opener ≤1 non-mana card: {pct(sm.hyper_at_least(N, M, 7, 6))}")

    # ----- 6. EDHREC -----
    print("\n## 6. EDHREC")
    if o.get("no-edhrec"):
        print("  skipped (--no-edhrec)")
    elif not cmdrs:
        print("  no commander — skipped")
    else:
        slugs = {"-".join(slug(c["name"]) for c in cmdrs)}
        if len(cmdrs) == 2:
            slugs.add("-".join(slug(c["name"]) for c in reversed(cmdrs)))
        snap = o.get("snapshot")
        if not snap:
            found = []
            for f in glob.glob(os.path.join(ROOT, "edhrec_snapshots", "*.txt")):
                parts = os.path.basename(f)[:-4].split("__")
                if len(parts) == 3 and parts[0] in slugs:
                    found.append((parts[1], parts[2], f))
            want = mtg.BRACKET_VARIANT.get(bracket)
            for pick in ([v for v in found if v[0] == want], [v for v in found if v[0] == "all"], found):
                if pick:
                    snap = max(pick, key=lambda v: v[1])[2]; break
        if not snap:
            v = mtg.BRACKET_VARIANT.get(bracket, "all")
            print(f"  NO SNAPSHOT for {' / '.join(sorted(slugs))}. Fetch per USE_INSTRUCTIONS §9 "
                  f"(try /{v}; fall back to the all-decks page under ~200 decks), transcribe, run "
                  f"`edhrec_diff.py check`, then re-run this audit.")
        else:
            m = re.search(r"(\d{4}-\d{2}-\d{2})\.txt$", snap)
            if m:
                age = (today - datetime.date.fromisoformat(m.group(1))).days
                print(f"  snapshot: {os.path.basename(snap)} ({age} days old"
                      + (" — STALE, refetch recommended)" if age > STALE_DAYS else ")"))
            cmd = [sys.executable, os.path.join(ROOT, "edhrec_diff.py"), "diff", snap, path]
            for k in ("min", "limit", "commander"):
                if o.get(k): cmd += [f"--{k}", o[k]]
            r = subprocess.run(cmd, capture_output=True, text=True)
            for line in (r.stdout + r.stderr).strip().splitlines():
                print("  " + line)

    # ----- 7. manual checklist -----
    print("\n## 7. Manual checklist")
    if notfound:
        print(f"  - NOT FOUND in repo (new set? typo? reskin?): {'; '.join(notfound)} — verify externally")
    if flagged:
        print(f"  - K-SENSITIVE roles: {', '.join(dict.fromkeys(flagged))}. Confirm which cards really do the job, "
              f"then re-run with --k ROLE=N (or tag them in Moxfield)")
    elif not any_user:
        print("  - Role counts come from oracle tags. Skim each role's card list for cards that don't fill "
              "that role in THIS deck; re-run with --k if any are off")
    print("  - Bracket items no script sees: chained extra turns, whether 2-card combos can fire before T6, "
          "and 'requires' pieces on listed combos")
    rules_date = re.search(r"(\d{8})", os.path.basename(mtg.RULES_FILE or ""))
    print(f"  - Comprehensive Rules file is dated {rules_date.group(1) if rules_date else '?'} — "
          f"mechanics newer than that need an outside rules check")
    print("  - These odds are static draws. They don't model draw engines, untaps, cascade, or tutor chains, "
          "so engine decks run higher than shown after T3. Use a goldfish sim for package questions")
    print("  - Colors aren't modeled: ask Ian for Moxfield's pip distribution if color requirements matter")


if __name__ == "__main__":
    main()
