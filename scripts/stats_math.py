"""
stats_math.py — probability tooling for mtg-data. Full docs: STATS_MATH.md.

CLI
  python3 stats_math.py report DECKLIST [category ...]
      Population N plus, per category (categories.py), the count K AND the
      matched card names. Eyeball the names before trusting any K.
  python3 stats_math.py colors DECKLIST
      Every colored card's odds of having its colors on curve (lands only / with
      cheap rocks, dorks and MDFCs), plus per-color source counts.
  python3 stats_math.py packages DECKLIST
      Spellbook combos and '# package:' lines: odds by T4/T6, natural vs. with tutors.
  python3 stats_math.py N K n k
      P(at least k of K hits among n cards from N) — a quick one-off number.
For a whole deck, run audit.py; it calls everything below with the standard battery.

Import from the repo root:  python3 -c "import stats_math as sm; ..."
Imports mtg.py for decklist parsing, name lookup, and Oracle Tag access so this
module never drifts from the repo's schema/format conventions (USE_INSTRUCTIONS.md §7).
"""
import math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtg  # the repo's own query helper

EXCLUDED_FROM_POPULATION = {"sideboard", "maybeboard", "considering",
                            "commander", "commanders", "companion"}

# ---------- Population counting ----------

def count_population(decklist_path, commander_override=None):
    """
    N = cards that actually sit in the library (draw-eligible), by counting --
    never assumed. Reuses mtg.parse_deck so section handling (Commander,
    Companion, Sideboard, Maybeboard) always matches the repo's own parser.
    Returns (N, commander_names, companion_names).
    """
    entries = mtg.parse_deck(decklist_path)
    commander_names = [n for s, q, n in entries if s in ("commander", "commanders")]
    if commander_override:
        commander_names = [commander_override]
    companion_names = [n for s, q, n in entries if s == "companion"]
    N = sum(q for s, q, n in entries if s not in EXCLUDED_FROM_POPULATION)
    return N, commander_names, companion_names

def cards_seen(turn, on_play=True, hand=7):
    """Cards seen by your draw step on `turn` (7-card hand, London mulligan)."""
    return hand + (turn - 1 if on_play else turn)

# ---------- Exact hypergeometric ----------

def hyper_pmf(N, K, n, k):
    n = min(n, N)   # can't draw more cards than the library holds (tiny/partial lists)
    if k > K or k > n or (n - k) > (N - K) or k < 0:
        return 0.0
    return math.comb(K, k) * math.comb(N - K, n - k) / math.comb(N, n)

def hyper_at_least(N, K, n, k):
    n = min(n, N)
    top = min(K, n)
    return sum(hyper_pmf(N, K, n, i) for i in range(k, top + 1))

def multivariate_at_least(N, cats, n):
    """cats: [(K_i, min_needed_i), ...] disjoint categories."""
    n = min(n, N)   # can't draw more cards than the library holds (tiny/partial lists)
    if N <= 0:
        return 0.0
    K_total = sum(k for k, _ in cats)
    other = N - K_total
    total = math.comb(N, n)
    def rec(idx, remaining_n, ways):
        if idx == len(cats):
            rest = remaining_n
            return 0 if rest < 0 or rest > other else ways * math.comb(other, rest)
        K_i, min_i = cats[idx]
        return sum(rec(idx + 1, remaining_n - i, ways * math.comb(K_i, i))
                   for i in range(min_i, min(K_i, remaining_n) + 1))
    return rec(0, n, 1) / total

def turn_curve(N, K, min_k, turns, on_play=True, hand=7):
    """Standard Commander convention: 7-card hand, London mulligan (bottoming
    doesn't change draw odds for cards kept)."""
    return {t: hyper_at_least(N, K, cards_seen(t, on_play, hand), min_k) for t in turns}

# ---------- Monte Carlo ----------

def simulate_at_least(N, K, n, k, trials=200000, seed=42):
    rng = random.Random(seed)
    deck = [1]*K + [0]*(N-K)
    hits = sum(1 for _ in range(trials) if sum(rng.sample(deck, n)) >= k)
    p = hits / trials
    se = (p*(1-p)/trials) ** 0.5
    return p, se

# ---------- Oracle Tags -> categories ----------
# A category's tag_label is one Scryfall label or a tuple of labels (union), as in
# categories.py. Everything reads the tag file through mtg.load_tags_multi: one pass.

def _as_labels(tag_label):
    return [tag_label] if isinstance(tag_label, str) else list(tag_label)

def tag_tree(tag_label, _trees=None):
    """{sub_label: set(oracle_id)} for the label(s), each walked to its full subtree.
    _trees: output of mtg.load_tags_multi covering these labels, to skip re-reading."""
    labels = _as_labels(tag_label)
    trees = _trees if _trees is not None else mtg.load_tags_multi(labels)
    out = {}
    for lab in labels:
        for sub, oids in trees.get(lab, {}).items():
            out.setdefault(sub, set()).update(oids)
    return out

def tag_oids(tag_label, _trees=None):
    """All oracle_ids under the label(s)."""
    return set().union(*tag_tree(tag_label, _trees).values()) if tag_label else set()

def tag_labels(tag_label, _trees=None):
    """Every label in the subtree(s) — maps a user's own #tags onto categories."""
    return set(tag_tree(tag_label, _trees))

def category_members(decklist_path, tag_label, commander_override=None, _tree=None):
    """
    Library cards (population, not commander/companion) under the tag subtree(s),
    as [(qty, oracle name)], plus unmatched deck names (review those by hand).
    _tree: a pre-built tree from tag_tree() to skip re-reading the tag file.
    """
    entries = mtg.parse_deck(decklist_path)
    library_entries = [(q, n) for s, q, n in entries if s not in EXCLUDED_FROM_POPULATION]
    tree = _tree if _tree is not None else tag_tree(tag_label)
    all_oids = set().union(*tree.values()) if tree else set()
    members, unmatched = [], []
    for q, name in library_entries:
        c, how = mtg.find(name)
        if not c:
            unmatched.append(name); continue
        if c.get("oracle_id") in all_oids:
            members.append((q, c["name"]))
    return members, unmatched

def category_count_from_tag(decklist_path, tag_label, commander_override=None):
    """(K, unmatched_names). Thin wrapper over category_members, so the count
    and the name list can't drift."""
    members, unmatched = category_members(decklist_path, tag_label, commander_override)
    return sum(q for q, _ in members), unmatched

def category_report(decklist_path, categories=None, show=True):
    """
    K and matched names for each category in categories.py (or the given
    subset), from ONE pass over the tag file. Tags are a starting point, not
    a verdict: they miss things (`ramp` doesn't include cost reducers like the
    Medallions), include judgment calls (Okaun/Zndrsplt count as tutors via
    "partner with"), and broad ones overcount (see STATS_MATH.md §7).
    Read the names, then adjust K. Returns {category: {"label", "K", "cards"}}.
    """
    from categories import CATEGORIES
    cats = categories or list(CATEGORIES)
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        raise KeyError(f"unknown categories {bad}; known: {', '.join(CATEGORIES)}")
    trees = mtg.load_tags_multi(sorted({l for c in cats for l in _as_labels(CATEGORIES[c])}))
    N, _, _ = count_population(decklist_path)
    out, unmatched = {}, []
    for cat in cats:
        label = CATEGORIES[cat]
        members, unmatched = category_members(decklist_path, label, _tree=tag_tree(label, trees))
        shown = label if isinstance(label, str) else f"{len(label)} labels"
        out[cat] = {"label": shown, "K": sum(q for q, _ in members), "cards": [n for _, n in members]}
    if show:
        print(f"Population N = {N}" + (f" | NOT FOUND in repo: {', '.join(unmatched)}" if unmatched else ""))
        for cat, r in out.items():
            print(f"  {cat} [{r['label']}] K={r['K']}: {'; '.join(r['cards']) or '-'}")
        print("  (tag-derived; check the names before using a K)")
    return out

# ---------- User #tags (long-form exports) ----------

def norm_label(s):
    """'Removal-Creature' / 'removal_creature' / 'Removal  Creature' -> 'removal creature'"""
    return " ".join(s.lower().replace("-", " ").replace("_", " ").split())

def user_tag_map(decklist_path):
    """{card name: [normalized user tags]} for LIBRARY cards (commander/companion excluded)."""
    out = {}
    for s, q, n, tags in mtg.parse_deck(decklist_path, with_tags=True):
        if s not in EXCLUDED_FROM_POPULATION and tags:
            out[n] = [norm_label(t) for t in tags]
    return out


# ---------- Colors: castability on curve ----------
# Card behavior (what mana a land makes, what a fetch can find, what a tutor can
# find) comes from goldfish.py's Oracle-text compiler, so every tool reads a card
# the same way. Imported lazily: plain draw-odds calls don't pay for it.

KEY_THRESHOLD, OTHER_THRESHOLD = 0.90, 0.80    # flag levels: commander/package pieces, everything else
_PIP_RX = __import__("re").compile(r"\{([^}]+)\}")

def _gf():
    import goldfish
    return goldfish

def color_pips(card):
    """Colored requirements of a card's front-face cost, as a list of frozensets
    (one per pip; hybrid {G/W} -> {'G','W'}). Skipped: generic, X, Phyrexian {U/P}
    (payable with life), twobrid {2/W} (payable with generic), snow {S}."""
    cost = card.get("mana_cost") or ((card.get("card_faces") or [{}])[0].get("mana_cost") or "")
    out = []
    for sym in _PIP_RX.findall(cost):
        parts = sym.upper().split("/")
        if any(x in ("P", "2") or x.isdigit() for x in parts) or sym.upper() in ("X", "Y", "Z", "S"):
            continue
        cols = frozenset(x for x in parts if x in "WUBRGC")
        if cols: out.append(cols)
    return out

def _deck(decklist_path, commander_override=None):
    """Library entries (qty, card, compiled) + commanders (card, compiled) + color identity."""
    gf = _gf()
    entries = mtg.parse_deck(decklist_path)
    N, cmd_names, _ = count_population(decklist_path, commander_override)
    cmdrs = [c for c in (mtg.find(n)[0] for n in cmd_names) if c]
    lib = []
    for s, q, n in entries:
        if s in EXCLUDED_FROM_POPULATION: continue
        c = mtg.find(n)[0]
        if c: lib.append((q, c))
    ci = set().union(*((c.get("color_identity") or []) for c in cmdrs)) if cmdrs else \
         set().union(*((c.get("color_identity") or []) for q, c in lib))
    anyc = frozenset(ci) or gf.ALL5
    cache = {}
    def comp(c):
        if c["name"] not in cache: cache[c["name"]] = gf.compile_card(c, anyc)
        return cache[c["name"]]
    return N, [(q, c, comp(c)) for q, c in lib], [(c, comp(c)) for c in cmdrs], anyc

def _produced(k, deck_lands):
    """Colors (incl. 'C') a land or mana source can make. Fetches make whatever the
    deck's lands they can find make; filter lands count their filter outputs."""
    gf = _gf()
    if k.fetch:
        filt = k.fetch[0]
        return frozenset().union(*(_produced(x, ()) for x in deck_lands if gf.land_ok(x, filt) and not x.fetch))
    cols = set()
    for u in k.units: cols |= set(u[0]) | set(u[1])
    for conv in k.convs:
        for u in conv[1]: cols |= set(u[0]) | set(u[1])
    return frozenset(cols)

def mana_sources(decklist_path, commander_override=None):
    """Source profile of the library: [(qty, name, colors, kind)] with kind 'land',
    'mdfc' (land back) or 'rock' (nonland mana: rocks and dorks) and its MV."""
    N, lib, cmdrs, anyc = _deck(decklist_path, commander_override)
    lands = [k for q, c, k in lib if k.is_land]
    out = []
    for q, c, k in lib:
        if k.is_land:
            out.append((q, c["name"], _produced(k, lands), "land", 0))
        elif k.mdfc is not None and getattr(k.mdfc, "is_land", False):
            out.append((q, c["name"], _produced(k.mdfc, lands), "mdfc", 0))
        elif k.units and k.cat == "ramp":
            out.append((q, c["name"], _produced(k, lands), "rock", int(c.get("cmc", 0))))
    return N, out, lib, cmdrs, anyc

def _hall_ok(pip_types, counts):
    """pip_types: [(colors, needed)]; counts: {profile(frozenset): n seen}. True if the
    seen sources can pay every pip with a distinct source (Hall's condition)."""
    from itertools import combinations
    for r in range(1, len(pip_types) + 1):
        for S in combinations(pip_types, r):
            need = sum(n for _, n in S)
            union = frozenset().union(*(cols for cols, _ in S))
            if sum(v for prof, v in counts.items() if prof & union) < need:
                return False
    return True

def _enumerate(N, cats, n, limit=400_000):
    """Exact multivariate hypergeometric over categories [(K_i, key_i)] plus 'other'.
    Yields (probability, {key: seen}). Returns None if the state space is too big."""
    n = min(n, N)                        # partial lists can be smaller than the cards seen
    if N <= 0: return [(1.0, {key: 0 for _, key in cats})]
    size = 1
    for K, _ in cats: size *= min(K, n) + 1
    if size > limit: return None
    other = N - sum(K for K, _ in cats)
    total = math.comb(N, n)
    out = []
    def rec(i, left, w, seen):
        if i == len(cats):
            if left <= other: out.append((w * math.comb(other, left) / total, dict(seen)))
            return
        K, key = cats[i]
        for x in range(0, min(K, left) + 1):
            seen[key] = x
            rec(i + 1, left - x, w * math.comb(K, x), seen)
        del seen[key]
    rec(0, n, 1, {})
    return out

def castable_on_curve(N, sources, pips, mv, n, trials=40_000, seed=7):
    """P(the seen sources can pay `pips` with distinct sources | at least `mv` sources
    seen). sources: [(qty, colors)]. The condition makes this a *color* number:
    running out of lands is section 3's job, not this one's."""
    need = {}
    for cols in pips: need[cols] = need.get(cols, 0) + 1
    pip_types = list(need.items())
    relevant = frozenset().union(*need) if need else frozenset()
    prof = {}
    for q, cols in sources:
        key = frozenset(cols) & relevant
        prof[key] = prof.get(key, 0) + q
    cats = [(K, key) for key, K in prof.items() if K > 0]
    mv = max(mv, sum(need.values()))
    states = _enumerate(N, cats, n)
    if states is None:                                   # huge 5-color profiles: sample instead
        rng = random.Random(seed); pool = []
        for K, key in cats: pool += [key] * K
        pool += [None] * (N - len(pool)); ok = cond = 0
        for _ in range(trials):
            cnt = {}
            for x in rng.sample(pool, n):
                if x is not None: cnt[x] = cnt.get(x, 0) + 1
            if sum(cnt.values()) >= mv:
                cond += 1; ok += _hall_ok(pip_types, cnt)
        return ok / cond if cond else 0.0
    p_cond = p_ok = 0.0
    for w, cnt in states:
        if sum(cnt.values()) >= mv:
            p_cond += w
            if _hall_ok(pip_types, cnt): p_ok += w
    return p_ok / p_cond if p_cond else 0.0

def _more_needed(N, sources, pips, mv, n, target, max_swaps=8):
    """Fewest non-source lands to swap for sources of one pip color to reach `target`.
    Returns (n_swaps, color) or None if no single-color swap of <= max_swaps gets there.
    More swaps never hurt, so check the max first, then binary-search."""
    def odds_after(col, k):
        donors = sorted((i for i, (q, cols, kind) in enumerate(sources) if kind == "land" and col not in cols),
                        key=lambda i: -sources[i][0])
        src = [[q, cols] for q, cols, kind in sources if kind != "rock"]
        idx_map = [i for i, (q, cols, kind) in enumerate(sources) if kind != "rock"]
        left = k
        for i in donors:
            j = idx_map.index(i); take = min(left, src[j][0])
            if take:
                src[j][0] -= take; src.append([take, frozenset(src[j][1]) | {col}]); left -= take
            if not left: break
        if left: return None                     # not enough lands to swap
        return castable_on_curve(N, [(q, c) for q, c in src if q], pips, mv, n)
    best = None
    for col in sorted({c for p in pips for c in p}):
        top = odds_after(col, max_swaps)
        if top is None or top < target: continue
        lo, hi = 1, max_swaps
        while lo < hi:
            mid = (lo + hi) // 2
            o = odds_after(col, mid)
            if o is not None and o >= target: hi = mid
            else: lo = mid + 1
        if best is None or lo < best[0]: best = (lo, col)
    return best

def color_report(decklist_path, commander_override=None, on_play=True, key_names=(), max_rows=10):
    """Castability of every colored card on curve, lands only and with cheap rocks,
    dorks and MDFC land backs. Returns a dict the audit prints."""
    N, srcs, lib, cmdrs, anyc = mana_sources(decklist_path, commander_override)
    land_src = [(q, cols, kind) for q, name, cols, kind, mvv in srcs if kind == "land"]
    def with_rocks(T):
        return [(q, cols) for q, name, cols, kind, mvv in srcs
                if kind in ("land", "mdfc") or (kind == "rock" and mvv < T)]
    per_color = {}
    for col in sorted(anyc | ({"C"} if any("C" in p for q, c, k in lib for p in color_pips(c)) else set())):
        lands_n = sum(q for q, name, cols, kind, m in srcs if kind == "land" and col in cols)
        all_n = sum(q for q, name, cols, kind, m in srcs if col in cols)
        ref = [(T, castable_on_curve(N, [(q, c) for q, c, _ in land_src], [frozenset(col)] * T, T, cards_seen(T, on_play)))
               for T in (1, 2, 3)]
        per_color[col] = (lands_n, all_n, ref)
    cache, rows = {}, []
    key_set = set(key_names) | {c["name"] for c, k in cmdrs}
    items = [(c, 1, True) for c, k in cmdrs] + [(c, q, False) for q, c, k in lib if not k.is_land]
    for c, q, is_cmdr in items:
        pips = color_pips(c)
        if not pips: continue
        mv = max(1, int(c.get("cmc", 0)))
        n = cards_seen(mv, on_play)
        sig = (tuple(sorted(tuple(sorted(p)) for p in pips)), mv)
        if sig not in cache:
            lo = castable_on_curve(N, [(q2, c2) for q2, c2, _ in land_src], pips, mv, n)
            hi = castable_on_curve(N, with_rocks(mv), pips, mv, n)
            cache[sig] = (lo, hi)
        lo, hi = cache[sig]
        key = c["name"] in key_set
        thr = KEY_THRESHOLD if key else OTHER_THRESHOLD
        rows.append({"name": c["name"], "cost": c.get("mana_cost") or (c.get("card_faces") or [{}])[0].get("mana_cost", ""),
                     "mv": mv, "lands": lo, "rocks": hi, "key": key, "cmdr": is_cmdr, "threshold": thr,
                     "multi": len({x for p in pips for x in p}) > 1, "pips": pips, "flag": lo < thr})
    flagged = sorted((r for r in rows if r["flag"]), key=lambda r: r["lands"])
    for r in flagged[:max_rows]:
        r["fix"] = _more_needed(N, land_src, r["pips"], r["mv"], cards_seen(r["mv"], on_play), r["threshold"])
    return {"N": N, "per_color": per_color, "rows": rows, "flagged": flagged,
            "rocks": [(name, cols, m) for q, name, cols, kind, m in srcs if kind == "rock"],
            "mdfc": [name for q, name, cols, kind, m in srcs if kind == "mdfc"]}

# ---------- Packages: natural draws vs. with tutors ----------

TUTOR_KINDS = ("tutor", "tutor_multi", "land_search")

def _walk_effects(obj):
    if isinstance(obj, tuple) and obj and isinstance(obj[0], str) and obj[0] in TUTOR_KINDS:
        yield obj; return
    if isinstance(obj, dict):
        for v in obj.values(): yield from _walk_effects(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj: yield from _walk_effects(v)

def tutor_effects(k):
    """Every tutor effect a compiled card has: spell, ETB, cast, triggers, activations, loyalty."""
    found = []
    for field in (k.spell, k.etb, k.castfx, k.trig, k.acts, k.pw):
        found += list(_walk_effects(field))
    return found

def can_fetch(effect, target_k):
    gf = _gf(); t = effect[0]
    if t == "land_search":
        return target_k.is_land and effect[3] != "top" and gf.land_ok(target_k, effect[2])
    filts = [effect[1]] if t == "tutor" else effect[1]
    return any(not f.get("unknown") and gf.spell_ok(target_k, f) for f in filts) and not target_k.is_land

def parse_package(spec):
    """'Name = A + B' (name optional). Parts: exact card name, a name regex (starts
    with ^ or wrapped in /.../), text:<regex on Oracle text>, or tag:<oracle tag>.
    Prefer text: for mechanics; Tagger names vary (Evolution Sage is tagged
    'repeatable-proliferate', not 'proliferate')."""
    name, sep, rest = spec.partition("=")
    if not sep: name, rest = "", spec
    parts = [x.strip() for x in __import__("re").split(r"\s+\+\s+", rest.strip()) if x.strip()]
    return (name.strip() or " + ".join(parts)), parts

def _part_members(part, names, trees):
    import re as _re
    if part.lower().startswith("text:"):
        rx = _re.compile(part[5:].strip(), _re.I)
        return {n for n in names if rx.search(mtg.text_of(mtg.find(n)[0] or {}))}
    if part.lower().startswith("tag:"):
        oids = tag_oids(part[4:].strip(), trees)
        return {n for n in names if (mtg.find(n)[0] or {}).get("oracle_id") in oids}
    if part.startswith("^") or (part.startswith("/") and part.endswith("/") and len(part) > 1):
        rx = _re.compile(part.strip("/"), _re.I)
        return {n for n in names if rx.search(n)}
    c = mtg.find(part)[0]
    return {c["name"]} if c and c["name"] in names else set()

def package_odds(N, parts, tutors, n):
    """parts: [K_i] copies per piece; tutors: [(K_j, frozenset(part indices it can find))].
    Returns (natural, with_tutors): P(every piece in hand or tutorable by distinct tutors)."""
    from itertools import combinations
    cats = [(K, ("p", i)) for i, K in enumerate(parts) if K > 0] + \
           [(K, ("t", caps)) for K, caps in tutors if K > 0 and caps]
    states = _enumerate(N, cats, n)
    if states is None: return None, None
    nat = wt = 0.0
    for w, seen in states:
        missing = [i for i, K in enumerate(parts) if seen.get(("p", i), 0) == 0]
        if not missing: nat += w; wt += w; continue
        ok = True
        for r in range(1, len(missing) + 1):
            for S in combinations(missing, r):
                have = sum(v for key, v in seen.items() if key[0] == "t" and key[1] & set(S))
                if have < len(S): ok = False; break
            if not ok: break
        if ok: wt += w
    return nat, wt

def packages_report(decklist_path, commander_override=None, on_play=True, turns=(4, 6), max_combos=8):
    """Packages from Spellbook combos (up to 3 cards, all in the deck) plus '# package:'
    header lines. A commander piece is always available. Tutor odds are a ceiling:
    tutors are counted as the piece they find, ignoring their mana and the turn spent."""
    N, lib, cmdrs, anyc = _deck(decklist_path, commander_override)
    meta = mtg.parse_deck_meta(decklist_path)
    lib_names = {c["name"] for q, c, k in lib}
    cmd_names = {c["name"] for c, k in cmdrs}
    qty = {}
    for q, c, k in lib: qty[c["name"]] = qty.get(c["name"], 0) + q
    comp = {c["name"]: k for q, c, k in lib}
    comp.update({c["name"]: k for c, k in cmdrs})
    tut_eff = {n: tutor_effects(k) for n, k in comp.items() if n in lib_names}
    tut_eff = {n: e for n, e in tut_eff.items() if e}
    specs = []
    for v in (meta.get("package") or []):
        specs.append(("header",) + parse_package(v))
    ts, dc = mtg.deck_combos(sorted(lib_names | cmd_names))
    combos = sorted((v for v in (dc or []) if len(v["cards"]) <= 3),
                    key=lambda v: (len(v["cards"]), -v.get("pop", 0)))
    extra_combos = max(0, len(combos) - max_combos)
    for v in combos[:max_combos]:
        specs.append(("combo", " + ".join(v["cards"]), v["cards"], v))
    trees = None
    if any(p.lower().startswith("tag:") for s in specs for p in s[2]):
        labels = sorted({p[4:].strip() for s in specs for p in s[2] if p.lower().startswith("tag:")})
        trees = mtg.load_tags_multi(labels)
    out = []
    for spec in specs:
        src, label, parts = spec[0], spec[1], spec[2]
        members = [_part_members(p, lib_names | cmd_names, trees) for p in parts]
        unresolved = [p for p, m in zip(parts, members) if not m]
        in_cmd = [bool(m & cmd_names) for m in members]
        lib_members = [m - cmd_names for m in members]
        overlap = any(lib_members[i] & lib_members[j] for i in range(len(parts)) for j in range(i + 1, len(parts)))
        idx = [i for i in range(len(parts)) if not in_cmd[i] and lib_members[i]]
        piece_K = [sum(qty[x] for x in lib_members[i]) for i in idx]
        caps = {}
        who = {i: [] for i in idx}
        for tname, effs in tut_eff.items():
            if any(tname in lib_members[i] for i in idx): continue      # a piece isn't its own tutor
            can = frozenset(j for j, i in enumerate(idx)
                            if any(can_fetch(e, comp[m]) for e in effs for m in lib_members[i]))
            if can:
                caps[can] = caps.get(can, 0) + qty[tname]
                for j in can: who[idx[j]].append(tname)
        res = {}
        for T in turns:
            if unresolved or overlap:
                res[T] = (None, None); continue
            if not idx:
                res[T] = (1.0, 1.0); continue
            res[T] = package_odds(N, piece_K, [(K, c) for c, K in caps.items()], cards_seen(T, on_play))
        out.append({"source": src, "label": label, "parts": parts, "members": members, "in_cmd": in_cmd,
                    "unresolved": unresolved, "overlap": overlap, "odds": res,
                    "tutors": {parts[i]: sorted(who[i]) for i in idx},
                    "combo": spec[3] if src == "combo" else None})
    return {"packages": out, "extra_combos": extra_combos, "tutors_in_deck": sorted(tut_eff)}

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "report":
        category_report(a[1], a[2:] or None)
    elif len(a) >= 2 and a[0] == "colors":
        r = color_report(a[1])
        for col, (ln, alln, ref) in r["per_color"].items():
            print(f"{col}: {ln} land sources ({alln} counting rocks/dorks/MDFCs) | " + " | ".join(f"{T} pip{'s' if T > 1 else ''} on T{T} {100 * p:.1f}%" for T, p in ref))
        for row in sorted(r["rows"], key=lambda x: x["lands"]):
            print(f"  {row['lands'] * 100:5.1f}% / {row['rocks'] * 100:5.1f}%  {row['name']} {row['cost']} on T{row['mv']}" + ("  FLAG" if row["flag"] else ""))
    elif len(a) >= 2 and a[0] == "packages":
        r = packages_report(a[1])
        for pk in r["packages"]:
            print(pk["label"], {T: tuple(None if v is None else round(100 * v, 1) for v in o) for T, o in pk["odds"].items()}, pk["tutors"])
    elif len(a) == 4 and all(x.isdigit() for x in a):
        N, K, n, k = map(int, a)
        print(f"P(>= {k} of {K} hits in {n} cards from {N}) = {100 * hyper_at_least(N, K, n, k):.1f}%")
    else:
        print(__doc__)
