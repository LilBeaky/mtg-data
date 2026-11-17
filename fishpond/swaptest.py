"""Swap-list tester, stage 1: the goldfish screen (docs/FORGE_PLAN.md Backlog, the user's design of 2026-10-30).

"Test combinations of swaps from this cut list and this add list over ~1500 games and give me the data." Not one card
against one card: each game plays a different random build against 3 dummies on real Forge rules, and every flex card is in
about half the games, so each card's effect on each metric is estimated over all the games at once (a factorial design).
Splitting the same 1500 games evenly over 100+ fixed combinations would leave each one about ±12 points of noise.

The spec file (one per question; '#' lines other than '# lock:' are comments):

    deck: decks/Ians_Zur_Wizardcycling.txt
    cut: Ponder
    cut: Brainstorm
    add: Preordain
    add: Consider
    # lock: Consider          a locked add is always in, a locked cut always out (a rework's core); ';' separates names

How a build is made: the deck minus every cut, then each slot a cut leaves is filled again: by the locked adds first, then
by a random draw from the flex cards (the unlocked cuts and adds), so a build always has 100 cards. Lands swap only for
lands (the land count stays fixed; mana bases are a later tool's job), so lands and nonlands are two separate pools. With as
many flex cuts as flex adds, each flex card is in half the games. Two fixed builds run beside the mixes on the same seeds:
'current' (the list as it is) and 'full' (every cut out, every add in), when the counts allow it.

What is estimated: for each metric, a least-squares fit of the game's value on which flex cards were in, per pool. A card's
effect is against the average flex card of its pool: "with this card in one of the flex slots instead of a typical flex
card, the commander comes down 0.3 turns sooner". Two cards' effects subtract to the swap of one for the other. Intervals
are 95% (robust standard errors); a card marked * keeps its effect after the Holm correction over all the cards of that
metric. Interaction (removal, wipes, counters: Scryfall role tags) can't be judged against dummies: those cards still
vary, so the other estimates stay sound, but they are marked and left to stage 3 (the chosen builds against real pods,
with `fishpond run --variant`).

Per-card win-rate effects are near noise even at 1500 games; the per-card signal is speed, mana and dead cards. Win rate
compares whole builds at stage 3.

  python -m fishpond swaptest SPEC --out DIR [--games N] [--fixed M] [--seed S] [--jobs J] [--cap C]
  python -m fishpond swaptest --report DIR          the report alone (also finishes a cut-off run's report)
  python -m fishpond swaptest SPEC --out DIR ...    again on the same DIR: resumes, playing only the missing games
"""
import json, math, os, random, re, sys, time
from collections import Counter, defaultdict

from . import decks as dk, forge, runner

INTERACTION = ("removal", "wipe", "counter")

# metric key, label, lower is better, what it counts
METRICS = [
    ("kill", "kill turn", True, "your turn the last dummy died; no kill by the cap counts as cap+1"),
    ("cmd", "commander turn", True, "your turn of the first commander cast; never cast counts as cap+1"),
    ("mull", "mulligans", True, "mulligans taken"),
    ("miss", "missed land drops T1-6", True, "your turns 1-6 without a land drop"),
    ("mana4", "mana T4", False, "mana you could make at your turn-4 main phase (with that turn's land drop)"),
    ("mana6", "mana T6", False, "mana you could make at your turn-6 main phase"),
    ("spent", "mana spent T1-6", False, "mana your mana abilities made on turns 1-6"),
    ("casts", "spells cast T1-6", False, "spells you cast on your turns 1-6"),
    ("drawn", "cards drawn T1-6", False, "cards drawn on your own turns 1-6"),
    ("held", "held 3+ turns", True, "your cards held castable 3+ turns running (the dead-card meter)"),
]
SIX = 6

# ---------------------------------------------------------------------------------------------------------- the spec

def read_spec(path):
    spec = {"path": path, "deck": None, "cut": [], "add": [], "lock": [], "title": os.path.splitext(os.path.basename(path))[0]}
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line: continue
        m = re.match(r"#\s*lock\s*:\s*(.+)$", line, re.I)
        if m:
            spec["lock"] += [n.strip() for n in m.group(1).split(";") if n.strip()]
            continue
        if line.startswith("#"): continue
        m = re.match(r"(deck|cut|add|title)\s*:\s*(.+)$", line, re.I)
        if not m: sys.exit(f"fishpond swaptest: {path}: can't read '{line}' (deck:, cut:, add:, title: or '# lock:')")
        k, v = m.group(1).lower(), m.group(2).strip()
        if k in ("deck", "title"): spec[k] = v
        else: spec[k].append(v)
    if not spec["deck"]: sys.exit(f"fishpond swaptest: {path} names no deck (a 'deck: PATH' line)")
    if not spec["cut"] and not spec["add"]: sys.exit(f"fishpond swaptest: {path} has no cut: or add: lines")
    return spec

def resolve(spec, idx=None):
    """The hero deck and the swap design: pools (land, nonland) with their slots, locked and flex cards. Exits on problems."""
    import mtg
    idx = idx if idx is not None else forge.index()
    dpath = spec["deck"] if os.path.isabs(spec["deck"]) else os.path.join(dk.REPO, spec["deck"])
    hero = dk.load(dpath, "hero", idx=idx)
    probs = [p for p in dk.validate(hero) if not p.startswith("partial")]
    if hero.not_found or not hero.commanders: sys.exit("fishpond swaptest: fix the deck first:\n  " + "\n  ".join(probs))
    in_deck = {n for _, n in hero.main}
    cards, problems = {}, []
    def card(name, want_in):
        c, how = mtg.find(name)
        if not c or (how or "").startswith("ambiguous"): problems.append(f"{name}: not found"); return None
        n = c["name"]
        if want_in and n not in in_deck: problems.append(f"cut {n}: not in the deck"); return None
        if not want_in and n in in_deck: problems.append(f"add {n}: already in the deck"); return None
        fn, flags = forge.forge_name(c, idx)
        if not fn: problems.append(f"{n}: Forge has no script for it"); return None
        if fn in dk._overridden(): flags = [f for f in flags if f != "All"]
        if "All" in flags and not want_in: problems.append(f"add {n}: Forge's AI never casts it (AI:RemoveDeck:All); "
                                                          "fishpond flags --smoke can test an override first")
        tl = " ".join(f.get("type_line") or "" for f in (c.get("card_faces") or [c])) or c.get("type_line") or ""
        cards[n] = {"name": n, "forge": fn, "flags": flags, "land": "Land" in tl.split("//")[0] and "Creature" not in tl.split("//")[0],
                    "side": "cut" if want_in else "add", "produced": "".join(x for x in (c.get("produced_mana") or []) if x in "WUBRG"),
                    "roles": _roles(c)}
        return n
    cut = [n for n in (card(x, True) for x in spec["cut"]) if n]
    add = [n for n in (card(x, False) for x in spec["add"]) if n]
    for dup in [n for n, k in Counter(cut + add).items() if k > 1]: problems.append(f"{dup} is listed twice")
    locked = set()
    for x in spec["lock"]:
        c, _ = mtg.find(x)
        n = c["name"] if c else x
        if n not in cards: problems.append(f"lock {x}: not on the cut or add list")
        else: locked.add(n)
    if problems: sys.exit("fishpond swaptest: fix the spec first:\n  " + "\n  ".join(problems))
    pools = {}
    for land in (False, True):
        key = "land" if land else "nonland"
        pc = [n for n in cut if cards[n]["land"] == land]
        pa = [n for n in add if cards[n]["land"] == land]
        lock_add = [n for n in pa if n in locked]
        flex = [n for n in pc + pa if n not in locked]
        slots = len(pc) - len(lock_add)                      # slots the flex cards fill after the locked adds
        if slots < 0: sys.exit(f"fishpond swaptest: {len(lock_add)} locked {key} adds but only {len(pc)} {key} cuts: "
                               "lands swap for lands and nonlands for nonlands, and a build keeps 100 cards")
        if slots > len(flex): sys.exit(f"fishpond swaptest: the {key} pool has {slots} slots to fill but {len(flex)} flex cards")
        pools[key] = {"cut": pc, "add": pa, "lock_add": lock_add, "lock_cut": [n for n in pc if n in locked], "flex": flex,
                      "slots": slots}
    return hero, cards, pools

def _roles(c):
    from . import policy
    try: return policy.roles_of(c, policy._tags().get(c.get("oracle_id"), set()))
    except Exception: return []

def build_deck(hero, cards, pools, flex_in, label):
    """The hero deck with every cut out, the locked adds and flex_in (a set of flex card names) in."""
    d = dk.Deck(hero.path, hero.kind)
    d.__dict__.update({k: (list(x) if isinstance(x, list) else dict(x) if isinstance(x, dict) else x) for k, x in hero.__dict__.items()})
    outs = {n for p in pools.values() for n in p["cut"]}
    ins = [n for p in pools.values() for n in p["lock_add"]] + [n for p in pools.values() for n in p["flex"] if n in flex_in and cards[n]["side"] == "add"]
    keep_cuts = {n for n in flex_in if cards[n]["side"] == "cut"}
    main = []
    for q, n in d.main:
        if n in outs and n not in keep_cuts: continue
        main.append((q, n))
    for n in ins:
        main.append((1, n))
        d.forge[n] = cards[n]["forge"]
        if cards[n]["flags"]: d.flags[n] = cards[n]["flags"]
        if cards[n]["produced"]: d.produced[cards[n]["forge"]] = cards[n]["produced"]
    d.main = main
    d.label = hero.label
    d.tag = re.sub(r"[^A-Za-z0-9]", "", f"{hero.tag}{label}")
    if d.size != hero.size: sys.exit(f"fishpond swaptest: build {label} has {d.size} cards, the list {hero.size} (a bug)")
    return d

def design(pools, games, seed):
    """Per mix game, the flex cards in: each pool draws its slots from its flex cards at random (seeded by the game)."""
    out = []
    for i in range(games):
        rng = random.Random(runner.game_seed(seed, i) * 7 + 3)
        flex_in = []
        for key in ("nonland", "land"):
            p = pools[key]
            flex_in += sorted(rng.sample(p["flex"], p["slots"]))
        out.append(flex_in)
    return out

def fixed_builds(pools):
    """The two builds that run as themselves beside the mixes: 'current' (the list as it is) and 'full' (every cut out, every
    add in), the latter only when each pool has as many adds as cuts. Returns ([(label, flex cards in, or None for the list
    as it is)], notes)."""
    out, notes = [("current", None)], []
    full = []
    for key, p in pools.items():
        fa = [n for n in p["add"] if n in p["flex"]]
        if len(p["add"]) != len(p["cut"]):
            notes.append(f"{key}: {len(p['add'])} adds for {len(p['cut'])} cuts, so there is no 'full' build")
            full = None
            break
        full += fa
    if full is not None: out.append(("full", sorted(full)))
    return out, notes

# ---------------------------------------------------------------------------------------------------------- running

def _paths(out): return {k: os.path.join(out, f) for k, f in (("design", "design.json"), ("plan", "plan.json"), ("games", "games.jsonl"), ("html", "swaptest.html"))}

def run(args):
    spec = read_spec(args.spec)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    P = _paths(out)
    idx = forge.index()
    hero, cards, pools = resolve(spec, idx)
    if os.path.exists(P["design"]):
        old = json.load(open(P["design"], encoding="utf-8"))
        if old["spec_lines"] != _spec_lines(spec) or old["seed"] != args.seed or old["cap"] != args.cap:
            sys.exit(f"fishpond swaptest: {out} holds a run of a different spec, seed or cap; pick a new --out")
        games, fixed = max(old["games"], args.games), max(old["fixed"], args.fixed)
    else:
        games, fixed = args.games, args.fixed
    mixes = design(pools, games, args.seed)
    fb, notes = fixed_builds(pools)
    builds = [(f"m{i}", build_deck(hero, cards, pools, set(fi), f"m{i}"), i) for i, fi in enumerate(mixes)]
    for label, fi in fb:
        if fi is None:
            d = dk.Deck(hero.path, hero.kind)
            d.__dict__.update(hero.__dict__)
            d.tag = re.sub(r"[^A-Za-z0-9]", "", f"{hero.tag}{label}")
        else:
            d = build_deck(hero, cards, pools, set(fi), label)
        builds += [(label, d, i) for i in range(min(fixed, games))]
    fixed_pods, pool = dk.seat_plan(["dummy"] * 3)
    pods = runner.Pods(fixed_pods, pool, False, idx=idx)
    meta = {"spec": os.path.relpath(os.path.abspath(args.spec), dk.REPO), "spec_lines": _spec_lines(spec), "title": spec["title"],
            "deck": spec["deck"], "commander": hero.label, "seed": args.seed, "cap": args.cap, "games": games, "fixed": fixed,
            "pools": pools, "cards": cards, "mixes": mixes, "fixed_builds": fb, "notes": notes, "forge": forge.FORGE_VERSION,
            "patches": len(forge.patch_files()), "started": time.strftime("%Y-%m-%d %H:%M")}
    plan = runner.load_plan(out) or []
    have = {(e["label"], e["game"]) for e in plan}
    first_id = max([e["id"] for e in plan] or [-1]) + 1
    t0 = time.time()
    for label, d, i in builds:
        if (label, i) in have: continue
        e = runner.plan_harness([(label, d)], pods, i, 1, args.seed, args.cap, args.timeout, out, hero_sim=args.sim, opp_sim="off",
                                first_id=first_id)
        plan += e; first_id += len(e)
    runner.save_plan(out, plan)
    with open(P["design"], "w", encoding="utf-8") as fh: json.dump(meta, fh, indent=1)
    deck_of = {label: d for label, d, _ in builds}
    records, missing = runner.collect(out, plan, list(deck_of.items()), pods)
    print(f"fishpond swaptest: {spec['title']}: {len(mixes)} mixed builds + {len(fb)} fixed x {min(fixed, games)} games; "
          f"{len(records)} played, {len(missing)} to play; planned in {time.time() - t0:.0f}s -> {out}", file=sys.stderr)
    for n in notes: print(f"  note: {n}", file=sys.stderr)
    if missing:
        import glob
        session = f"s{len({os.path.basename(f).split('_')[1] for f in glob.glob(os.path.join(out, 'logs', 'plan_*_*.tsv'))}) + 1}"
        runner.execute(missing, args.jobs or runner.default_jobs(), out, session, args.quiet)
        records, missing = runner.collect(out, plan, list(deck_of.items()), pods)
    runner.save(out, {"swaptest": True, **{k: meta[k] for k in ("spec", "title", "games", "fixed", "seed", "cap")}}, records)
    report(out)

def _spec_lines(spec): return {"deck": spec["deck"], "cut": spec["cut"], "add": spec["add"], "lock": spec["lock"]}

# ---------------------------------------------------------------------------------------------------------- metrics

def game_metrics(r, cap):
    """The goldfish metrics of one game's record (hero = seat 1)."""
    rows = {t["t"]: t for t in r.get("turns") or []}
    last = max(rows or [0])
    sn = r.get("snaps") or {}
    def snap(t, kind):
        for tt in range(t, 0, -1):
            s = (sn.get(str(tt)) or {}).get(kind)
            if s: return s
        return None
    m = {}
    m["kill"] = r["end_t"] if r.get("result") == "win" and r.get("end_t") else cap + 1
    m["cmd"] = (r.get("cmd_casts") or [cap + 1])[0]
    m["mull"] = r.get("mulligans") or 0
    upto = [t for t in range(1, SIX + 1) if t <= last]
    m["miss"] = sum(1 for t in upto if not rows[t].get("lands")) if upto else 0
    for t in (4, 6):
        s = snap(t, "main")
        m[f"mana{t}"] = (s.get("usable", s.get("mana")) or 0) if s else 0
    m["spent"] = sum(rows[t].get("spent", 0) for t in upto)
    m["casts"] = sum(len(rows[t].get("casts") or []) for t in upto)
    m["drawn"] = sum((((sn.get(str(t)) or {}).get("end") or {}).get("drawn") or 0) for t in upto)
    m["held"] = sum(1 for h in r.get("held") or [] if str(h.get("seat")) == "1" and h.get("turns", 0) >= 3)
    return m

def card_usage(r, names, cards):
    """Per flex card in this game's build: cast at all, first cast turn, held castable 3+ turns. The log names a card by its
    Forge name or, for a double-faced card, its front face."""
    fc = r.get("first_cast") or {}
    held = {h["card"] for h in r.get("held") or [] if str(h.get("seat")) == "1" and h.get("turns", 0) >= 3}
    out = {}
    for n in names:
        al = {n, cards[n]["forge"], n.split(" // ")[0]}
        t = min((fc[a] for a in al if a in fc), default=None)
        out[n] = (t is not None, t, bool(al & held))
    return out

# ---------------------------------------------------------------------------------------------------------- estimation

def _solve(A, b):
    """Gauss-Jordan with partial pivoting; A is square (list of lists). Returns x, or None when singular."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12: return None
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]

def _inverse(A):
    n = len(A)
    cols = [_solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    if any(c is None for c in cols): return None
    return [[cols[j][i] for j in range(n)] for i in range(n)]

def fit(rows, ys, pools):
    """OLS of ys on flex-card indicators, one reference card dropped per pool (each pool's count is fixed, so the intercept
    and a full set of a pool's indicators are collinear). Returns {card: (effect vs the pool's average flex card, se)} with
    HC1 robust standard errors."""
    cols, groups = [], []
    for key in ("nonland", "land"):
        flex = pools[key]["flex"]
        if pools[key]["slots"] == 0 or pools[key]["slots"] == len(flex) or len(flex) < 2: continue
        groups.append((flex, len(cols)))
        cols += flex[1:]                                       # flex[0] is the reference (coefficient 0)
    if not groups: return {}
    pos = {c: 1 + k for k, c in enumerate(cols)}
    act = [[0] + [pos[c] for c in row if c in pos] for row in rows]       # the row's nonzero columns (all ones)
    n, p = len(act), 1 + len(cols)
    if n <= p + 1: return {}
    XtX = [[0.0] * p for _ in range(p)]
    Xty = [0.0] * p
    for a, y in zip(act, ys):
        for i in a:
            Xty[i] += y
            for j in a: XtX[i][j] += 1.0
    inv = _inverse(XtX)
    if inv is None: return {}
    beta = [sum(inv[i][j] * Xty[j] for j in range(p)) for i in range(p)]
    meat = [[0.0] * p for _ in range(p)]
    for a, y in zip(act, ys):
        e2 = (y - sum(beta[i] for i in a)) ** 2
        for i in a:
            for j in a: meat[i][j] += e2
    tmp = [[sum(inv[i][a] * meat[a][j] for a in range(p)) for j in range(p)] for i in range(p)]
    V = [[sum(tmp[i][a] * inv[a][j] for a in range(p)) * n / (n - p) for j in range(p)] for i in range(p)]
    out = {}
    for flex, start in groups:
        m = len(flex)
        idx = [None] + [1 + start + k for k in range(m - 1)]   # position of each card's coefficient in beta (None: reference)
        b = [0.0 if j is None else beta[j] for j in idx]
        mean = sum(b) / m
        for a, card in enumerate(flex):
            # effect_a = sum_j w_j b_j with w_j = [j == a] - 1/m; its variance is w' V w over the non-reference coefficients
            w = {j: ((1.0 if k == a else 0.0) - 1.0 / m) for k, j in enumerate(idx) if j is not None}
            var = sum(w[i] * w[j] * V[i][j] for i in w for j in w)
            out[card] = (b[a] - mean, math.sqrt(max(var, 0.0)))
    return out

def _p(z): return math.erfc(abs(z) / math.sqrt(2))

def holm(pvals):
    """Cards whose effect survives the Holm correction at 5% (pvals: {card: p})."""
    order = sorted(pvals, key=pvals.get)
    keep, m = set(), len(order)
    for k, c in enumerate(order):
        if pvals[c] > 0.05 / (m - k): break
        keep.add(c)
    return keep

def mean_ci(xs):
    n = len(xs)
    if not n: return None, None
    mu = sum(xs) / n
    if n < 2: return mu, None
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return mu, 1.96 * sd / math.sqrt(n)

def analyse(out):
    P = _paths(out)
    meta = json.load(open(P["design"], encoding="utf-8"))
    recs = [json.loads(l) for l in open(P["games"], encoding="utf-8")] if os.path.exists(P["games"]) else []
    cap, pools, cards = meta["cap"], meta["pools"], meta["cards"]
    flex = [n for k in ("nonland", "land") for n in pools[k]["flex"]]
    fixed = [label for label, _ in meta["fixed_builds"]]
    mix = [r for r in recs if re.fullmatch(r"m\d+", r["build"])]
    rows = [set(meta["mixes"][int(r["build"][1:])]) for r in mix]
    gm = [game_metrics(r, cap) for r in mix]
    effects = {}
    for key, *_ in METRICS:
        ys = [g[key] for g in gm]
        f = fit(rows, ys, pools)
        surv = holm({c: _p(e / se) if se else 1.0 for c, (e, se) in f.items() if not _interaction(cards[c])})
        effects[key] = {c: {"eff": e, "se": se, "holm": c in surv} for c, (e, se) in f.items()}
    builds = {}
    for label in ["mixes"] + list(fixed):
        rs = mix if label == "mixes" else [r for r in recs if r["build"] == label]
        ms = [game_metrics(r, cap) for r in rs]
        b = {"games": len(rs), "wins": sum(1 for r in rs if r.get("result") == "win")}
        for key, *_ in METRICS: b[key] = mean_ci([m[key] for m in ms])
        builds[label] = b
    paired = {}
    if "current" in fixed and "full" in fixed:
        by = defaultdict(dict)
        for r in recs:
            if r["build"] in ("current", "full"): by[r["game"]][r["build"]] = game_metrics(r, cap)
        both = [v for v in by.values() if len(v) == 2]
        for key, *_ in METRICS: paired[key] = mean_ci([v["full"][key] - v["current"][key] for v in both]) + (len(both),)
    usage = {}
    for n in flex:
        ins = [r for r, s in zip(mix, rows) if n in s]
        u = [card_usage(r, [n], cards)[n] for r in ins]
        casts = [t for c, t, _ in u if c and t]
        usage[n] = {"games_in": len(ins), "cast": sum(1 for c, _, _ in u if c) / len(u) if u else None,
                    "first": sum(casts) / len(casts) if casts else None, "held": sum(1 for *_, h in u if h) / len(u) if u else None}
    return meta, {"n": len(mix), "effects": effects, "builds": builds, "paired": paired, "usage": usage, "flex": flex}

def _interaction(c): return bool(set(c.get("roles") or []) & set(INTERACTION))

# ---------------------------------------------------------------------------------------------------------- report

def report(out):
    out = os.path.abspath(out)
    meta, a = analyse(out)
    P = _paths(out)
    txt = text_report(meta, a)
    print(txt)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as fh: fh.write(txt + "\n")
    with open(P["html"], "w", encoding="utf-8") as fh: fh.write(html_report(meta, a))
    print(f"\nfishpond swaptest: page -> {P['html']}")

def _f(v, d=2): return "-" if v is None else f"{v:.{d}f}"

def text_report(meta, a):
    L = [f"Swap test: {meta['title']} ({meta['commander']}), {a['n']} mixed builds against 3 dummies, cap {meta['cap']}, seed {meta['seed']}"]
    for k in ("nonland", "land"):
        p = meta["pools"][k]
        if p["cut"] or p["add"]:
            L.append(f"  {k}: {len(p['cut'])} cuts, {len(p['add'])} adds, {len(p['lock_add'])} locked adds, "
                     f"{len(p['lock_cut'])} locked cuts; {p['slots']} slots from {len(p['flex'])} flex cards")
    for n in meta.get("notes") or []: L.append(f"  note: {n}")
    L.append("")
    L.append("Builds (mean, 95% interval):")
    hdr = ["build", "games", "wins"] + [lab for _, lab, *_ in METRICS]
    L.append("  " + " | ".join(hdr))
    for label, b in a["builds"].items():
        L.append("  " + " | ".join([label, str(b["games"]), str(b["wins"])] +
                                   [("-" if b[k][0] is None else f"{b[k][0]:.2f}" + (f"±{b[k][1]:.2f}" if b[k][1] else "")) for k, *_ in METRICS]))
    if a["paired"]:
        n = next(iter(a["paired"].values()))[2]
        L.append(f"  full - current, same seeds ({n} pairs): " + ", ".join(
            f"{lab} {v[0]:+.2f}±{v[1]:.2f}" for (k, lab, *_), v in ((m, a["paired"][m[0]]) for m in METRICS) if v[0] is not None and v[1] is not None))
    L.append("")
    L.append("Card effects against the pool's average flex card (95% interval; * survives Holm over the metric's cards;")
    L.append("lower is better for kill turn, commander turn, mulligans, missed drops and held; I = interaction, judged at stage 3):")
    for key, lab, low, _ in METRICS:
        e = a["effects"].get(key) or {}
        if not e: continue
        L.append(f"  {lab}:")
        for c in sorted(e, key=lambda c: e[c]["eff"] * (1 if low else -1)):
            v = e[c]
            tag = ("I " if _interaction(meta["cards"][c]) else "  ") + ("*" if v["holm"] else " ")
            L.append(f"    {tag} {meta['cards'][c]['side']:3} {c:32} {v['eff']:+.2f} ± {1.96 * v['se']:.2f}")
    L.append("")
    L.append("Flex cards when in the build: games in, cast at all, first cast turn, held castable 3+ turns")
    for c in a["flex"]:
        u = a["usage"][c]
        L.append(f"  {c:32} {u['games_in']:5}  {_pct(u['cast'])}  {_f(u['first'], 1):>5}  {_pct(u['held'])}")
    return "\n".join(L)

def _pct(v): return "   -" if v is None else f"{100 * v:3.0f}%"

def html_report(meta, a):
    import html as H
    esc = H.escape
    met = [(k, lab, low, why) for k, lab, low, why in METRICS if a["effects"].get(k)]
    rows = []
    for c in a["flex"]:
        card = meta["cards"][c]
        u = a["usage"][c]
        cells = [f"<td>{esc(c)}</td>", f"<td>{card['side']}</td>", f"<td>{'land' if card['land'] else ''}</td>",
                 f"<td>{'yes' if _interaction(card) else ''}</td>", f"<td class=n data-v='{u['games_in']}'>{u['games_in']}</td>",
                 f"<td class=n data-v='{u['cast'] if u['cast'] is not None else ''}'>{_pct(u['cast']).strip()}</td>",
                 f"<td class=n data-v='{u['first'] if u['first'] is not None else ''}'>{_f(u['first'], 1)}</td>",
                 f"<td class=n data-v='{u['held'] if u['held'] is not None else ''}'>{_pct(u['held']).strip()}</td>"]
        for k, lab, low, _ in met:
            v = a["effects"][k].get(c)
            if not v: cells.append("<td class=n data-v=''>-</td>"); continue
            good = (v["eff"] < 0) == low
            cls = ("good" if good else "bad") if v["holm"] and not _interaction(card) else ""
            cells.append(f"<td class='n {cls}' data-v='{v['eff']:.4f}' title='95%: {v['eff'] - 1.96 * v['se']:+.2f} to {v['eff'] + 1.96 * v['se']:+.2f}'>"
                         f"{v['eff']:+.2f}<small> ±{1.96 * v['se']:.2f}</small>{'*' if v['holm'] else ''}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    brows = []
    for label, b in a["builds"].items():
        cells = [f"<td>{esc(label)}</td>", f"<td class=n data-v='{b['games']}'>{b['games']}</td>", f"<td class=n data-v='{b['wins']}'>{b['wins']}</td>"]
        for k, *_ in METRICS:
            mu, hw = b[k]
            cells.append("<td class=n data-v=''>-</td>" if mu is None else f"<td class=n data-v='{mu:.4f}'>{mu:.2f}<small>{f' ±{hw:.2f}' if hw else ''}</small></td>")
        brows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f"<th title='{esc(why)}{' (lower is better)' if low else ''}'>{esc(lab)}</th>" for k, lab, low, why in met)
    bhead = "".join(f"<th title='{esc(why)}'>{esc(lab)}</th>" for k, lab, low, why in METRICS)
    pools = "; ".join(f"{k}: {p['slots']} slots from {len(p['flex'])} flex cards" + (f", locked in: {', '.join(p['lock_add'])}" if p["lock_add"] else "")
                      + (f", locked out: {', '.join(p['lock_cut'])}" if p["lock_cut"] else "") for k, p in meta["pools"].items() if p["cut"] or p["add"])
    paired = ""
    if a["paired"]:
        n = next(iter(a["paired"].values()))[2]
        paired = f"<p>Full rework minus current list on the same seeds ({n} pairs): " + ", ".join(
            f"{esc(lab)} {a['paired'][k][0]:+.2f} ±{a['paired'][k][1]:.2f}" for k, lab, *_ in METRICS if a['paired'][k][0] is not None and a['paired'][k][1] is not None) + ".</p>"
    notes = "".join(f"<li>{esc(n)}</li>" for n in meta.get("notes") or [])
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Swap test: {esc(meta['title'])}</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e2dfd8;--good:#1f7a4d;--bad:#b2412f;--head:#f1eee7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#181816;--fg:#ecebe6;--mut:#a3a19a;--line:#34332f;--good:#5cc28e;--bad:#ec7a66;--head:#23221f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1400px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}} p,li{{color:var(--mut);max-width:900px}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;font-variant-numeric:tabular-nums}}
th,td{{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{background:var(--head);cursor:pointer;position:sticky;top:0;font-weight:600}} td.n{{text-align:right}}
small{{color:var(--mut)}} .good{{color:var(--good);font-weight:600}} .bad{{color:var(--bad);font-weight:600}}
</style></head><body>
<h1>Swap test: {esc(meta['title'])}</h1>
<p>{esc(meta['commander'])}, {a['n']} mixed builds against 3 dummies (Forge {esc(meta['forge'])}, {meta['patches']} patches, cap {meta['cap']}, seed {meta['seed']}). {esc(pools)}.</p>
<ul>{notes}</ul>
<h2>Builds</h2><p>Mean and 95% interval. "mixes" is every random build pooled.</p>
<div class=wrap><table class=sort><thead><tr><th>build</th><th>games</th><th>wins</th>{bhead}</tr></thead><tbody>{''.join(brows)}</tbody></table></div>
{paired}
<h2>Cards</h2>
<p>Effects are against the pool's average flex card: with this card in a flex slot instead of a typical flex card. Two cards' effects
subtract to the swap of one for the other. The ± is the 95% interval (hover for its ends); * survives the Holm correction over that
metric's cards, and only those are colored (green helps, red hurts). Interaction can't be judged against dummies: it is shown but
left to stage 3. Click a column to sort.</p>
<div class=wrap><table class=sort><thead><tr><th>card</th><th>side</th><th>land</th><th>interaction</th><th>games in</th><th>cast</th><th>first cast</th><th>held 3+</th>{head}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<script>
document.querySelectorAll('table.sort').forEach(t=>t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{{
 const b=t.tBodies[0],rs=[...b.rows],asc=th.dataset.d!=='a';th.dataset.d=asc?'a':'d';
 const key=r=>{{const c=r.cells[i],v=c.dataset.v;return v===undefined?c.textContent:v===''?null:+v}};
 rs.sort((x,y)=>{{const a=key(x),c=key(y);if(a===null)return 1;if(c===null)return -1;return (a>c?1:a<c?-1:0)*(asc?1:-1)}});
 rs.forEach(r=>b.appendChild(r))}})));
</script></body></html>
"""

def cmd(args):
    if args.report: return report(args.report)
    if not args.spec or not args.out: sys.exit("fishpond swaptest: needs SPEC and --out DIR (or --report DIR)")
    run(args)
