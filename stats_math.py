"""
stats_math.py — probability tooling for mtg-data. Full docs: STATS_MATH.md.

Import it from the repo root:
    python3 -c "import stats_math as sm; print(sm.hyper_at_least(99, 10, 10, 1))"
Quick CLI for a one-off number:
    python3 stats_math.py N K n k      -> P(at least k of K hits among n cards from N)
For a whole deck, run audit.py — it calls everything below with the standard battery.

Imports mtg.py for decklist parsing, name lookup, and Oracle Tag access so this
module never drifts from the repo's schema/format conventions (USE_INSTRUCTIONS.md §7).
"""
import math, random, sys
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
    commander_names = [commander_override] if commander_override else \
        [n for s, q, n in entries if s in ("commander", "commanders")]
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

# ---------- Oracle Tags -> category counts ----------

def tag_oids(labels):
    """Union of oracle_ids under one or more Scryfall tag labels, each walked to its
    full subtree via mtg.load_tags (parent tags hold no direct taggings)."""
    if isinstance(labels, str):
        labels = [labels]
    oids = set()
    for lab in labels:
        for s in mtg.load_tags(only_label=lab).values():
            oids |= s
    return oids

def tag_labels(labels):
    """Every label in the subtree(s) — used to map a user's own #tags onto categories."""
    if isinstance(labels, str):
        labels = [labels]
    out = set()
    for lab in labels:
        out |= set(mtg.load_tags(only_label=lab))
    return out

def category_count_from_tag(decklist_path, tag_label, commander_override=None):
    """
    K = cards IN THE LIBRARY (commander/companion excluded) whose oracle_id falls
    under tag_label's Scryfall tag subtree. tag_label may be a string or a
    list/tuple of labels (union). Returns (K, unmatched_names) -- review unmatched
    names by hand; they're never silently dropped.
    """
    entries = mtg.parse_deck(decklist_path)
    library_entries = [(q, n) for s, q, n in entries if s not in EXCLUDED_FROM_POPULATION]
    all_oids = tag_oids(tag_label)
    K, unmatched = 0, []
    for q, name in library_entries:
        c, how = mtg.find(name)
        if not c:
            unmatched.append(name); continue
        if c.get("oracle_id") in all_oids:
            K += q
    return K, unmatched

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
    if len(a) == 4 and all(x.isdigit() for x in a):
        N, K, n, k = map(int, a)
        print(f"P(>= {k} of {K} hits in {n} cards from {N}) = {100 * hyper_at_least(N, K, n, k):.1f}%")
    else:
        print(__doc__)
