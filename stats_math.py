"""
stats_math.py — probability tooling for mtg-data. Full docs: STATS_MATH.md.

CLI
  python3 stats_math.py report DECKLIST [category ...]
      Population N plus, per category (categories.py), the count K AND the
      matched card names. Eyeball the names before trusting any K.
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
    if k > K or k > n or (n - k) > (N - K) or k < 0:
        return 0.0
    return math.comb(K, k) * math.comb(N - K, n - k) / math.comb(N, n)

def hyper_at_least(N, K, n, k):
    top = min(K, n)
    return sum(hyper_pmf(N, K, n, i) for i in range(k, top + 1))

def multivariate_at_least(N, cats, n):
    """cats: [(K_i, min_needed_i), ...] disjoint categories."""
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

if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "report":
        category_report(a[1], a[2:] or None)
    elif len(a) == 4 and all(x.isdigit() for x in a):
        N, K, n, k = map(int, a)
        print(f"P(>= {k} of {K} hits in {n} cards from {N}) = {100 * hyper_at_least(N, K, n, k):.1f}%")
    else:
        print(__doc__)
