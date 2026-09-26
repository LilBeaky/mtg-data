"""
stats_math.py — probability tooling for mtg-data.
Import mtg.py for decklist parsing, name lookup, and Oracle Tag access so this
module never drifts from the repo's schema/format conventions (per USE_INSTRUCTIONS.md
section 5). Run this from a location where `import mtg` resolves to the repo's mtg.py
(e.g. drop this file in the repo root, or sys.path.insert the repo root first).
"""
import math, random
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
    commander_names = [o["--commander"]] if False else \
        [n for s, q, n in entries if s in ("commander", "commanders")]
    if commander_override:
        commander_names = [commander_override]
    companion_names = [n for s, q, n in entries if s == "companion"]
    N = sum(q for s, q, n in entries if s not in EXCLUDED_FROM_POPULATION)
    return N, commander_names, companion_names

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
    out = {}
    for t in turns:
        draws = (t - 1) if on_play else t
        out[t] = hyper_at_least(N, K, hand + draws, min_k)
    return out

# ---------- Monte Carlo ----------

def simulate_at_least(N, K, n, k, trials=200000, seed=42):
    rng = random.Random(seed)
    deck = [1]*K + [0]*(N-K)
    hits = sum(1 for _ in range(trials) if sum(rng.sample(deck, n)) >= k)
    p = hits / trials
    se = (p*(1-p)/trials) ** 0.5
    return p, se

# ---------- Oracle Tags -> category counts ----------

def category_count_from_tag(decklist_path, tag_label, commander_override=None):
    """
    K = cards IN THE LIBRARY (population, not commander/companion) whose oracle_id
    falls under tag_label's Scryfall tag subtree. Walks parent/child tags via
    mtg.load_tags, exactly like `mtg.py search --tag` does internally.
    Returns (K, unmatched_names).
    """
    entries = mtg.parse_deck(decklist_path)
    commander_names = [commander_override] if commander_override else \
        [n for s, q, n in entries if s in ("commander", "commanders")]
    library_entries = [(q, n) for s, q, n in entries if s not in EXCLUDED_FROM_POPULATION]

    tag_tree = mtg.load_tags(only_label=tag_label)
    all_oids = set()
    for oids in tag_tree.values():
        all_oids |= oids

    K, unmatched = 0, []
    for q, name in library_entries:
        c, how = mtg.find(name)
        if not c:
            unmatched.append(name); continue
        if c.get("oracle_id") in all_oids:
            K += q
    return K, unmatched

if __name__ == "__main__":
    N, cmdrs, comps = count_population("/home/claude/test_decklist.txt")
    print(f"Population N = {N} | commander(s): {cmdrs} | companion(s): {comps}")

    K, unmatched = category_count_from_tag("/home/claude/test_decklist.txt", "ramp")
    print(f"Ramp category: K = {K} (unmatched: {unmatched})")

    print(f"P(>=1 ramp in opening 7): {hyper_at_least(N, K, 7, 1)*100:.1f}%")
    p, se = simulate_at_least(N, K, 7, 1, trials=100000)
    print(f"Simulated check: {p*100:.1f}% (should track the exact value above)")
