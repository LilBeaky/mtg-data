# Stats Math — probability tooling for mtg-data

Companion reference to `USE_INSTRUCTIONS.md`. This doc covers draw-probability
math: exact hypergeometric calculations, Monte Carlo simulation, and using
Scryfall Oracle Tags to build category counts straight from a decklist.

**Trigger conditions (when this should be reached for automatically during an
audit, without being asked) are intentionally not included here.** That's a
separate document Ian is writing; this doc is the engine, not the policy for
using it.

---

## 1. Conventions

- **Mulligan rule is fixed: standard Commander (London mulligan, 7-card
  opening hand).** Not a parameter, not configurable per-query. If a
  non-Commander format ever needs different mulligan math, that's a deliberate
  future addition, not something this doc guesses at.
- **Population size (N) is never assumed.** It is always *counted* from the
  actual decklist via `count_population()` below, which reuses `mtg.py`'s own
  `parse_deck()` so it never drifts from the repo's accepted decklist format
  or section-handling rules. In the overwhelming majority of cases this comes
  out to 99, but partner commanders, companions, and non-standard lists all
  fall out of the same counting logic instead of needing special-cased
  assumptions.

## 2. Population counting

`count_population()` sums every decklist line **except** `sideboard`,
`maybeboard`, `considering`, `commander`/`commanders`, and `companion`
sections — those cards don't sit in the library, so they're not part of the
draw population.

**Worth flagging:** `mtg.py`'s own `cmd_deck()` total (the `cards: N` line
printed by `python3 mtg.py deck ...`) currently excludes sideboard/maybeboard/
considering but does **not** exclude a `Companion` section from its total —
meaning a companion card would inflate that printed total by however many
companion lines exist. `count_population()` here excludes companion
correctly, since your Obosh build makes this a real case, not a hypothetical
one. This is just a note for stats_math's own counting, not a change to
`mtg.py` itself — flagging it in case it's worth fixing there too at some
point.

```python
EXCLUDED_FROM_POPULATION = {"sideboard", "maybeboard", "considering",
                             "commander", "commanders", "companion"}

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
```

## 3. Exact hypergeometric engine

Pure combinatorics via `math.comb` — no external dependencies, exact (not
approximate) results, effectively instant.

```python
import math

def hyper_pmf(N, K, n, k):
    """P(exactly k successes) drawing n cards from N with K successes in the population."""
    if k > K or k > n or (n - k) > (N - K) or k < 0:
        return 0.0
    return math.comb(K, k) * math.comb(N - K, n - k) / math.comb(N, n)

def hyper_at_least(N, K, n, k):
    """P(at least k successes)."""
    top = min(K, n)
    return sum(hyper_pmf(N, K, n, i) for i in range(k, top + 1))

def multivariate_at_least(N, cats, n):
    """
    cats: [(K_i, min_needed_i), ...] for disjoint categories.
    P(every category meets its minimum simultaneously), drawing n cards.
    Exact via enumeration -- fast at Commander-scale category counts/hand sizes.
    """
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
    """P(>= min_k copies of a K-count category seen) by each turn. Standard
    Commander convention: 7-card hand, one draw per turn from turn 2 on the
    play (or every turn on the draw)."""
    out = {}
    for t in turns:
        draws = (t - 1) if on_play else t
        out[t] = hyper_at_least(N, K, hand + draws, min_k)
    return out
```

## 4. Monte Carlo engine

Reach for this once a question involves card *effects* changing the
population mid-draw (a ramp spell that digs, scry/surveil, tutors) rather
than a static category count -- the exact engine above can't model that
without hand-deriving conditional cases per card. Card-accurate effect rules
aren't built yet (see Known limits); today this engine reproduces the exact
math for static categories, which also serves as its own validation.

```python
import random

def simulate_at_least(N, K, n, k, trials=200000, seed=42):
    rng = random.Random(seed)
    deck = [1]*K + [0]*(N-K)
    hits = sum(1 for _ in range(trials) if sum(rng.sample(deck, n)) >= k)
    p = hits / trials
    se = (p*(1-p)/trials) ** 0.5
    return p, se  # se = standard error; multiply by 1.96 for a 95% CI
```

## 5. Oracle Tags → category counts

`mtg.py`'s Oracle Tags handling already walks the parent/child tag tree
(parent tags like `ramp`/`removal` hold zero direct taggings; their cards
live in child tags -- see USE_INSTRUCTIONS.md section 5). `category_count_from_tag()`
reuses `mtg.load_tags()` and `mtg.find()` directly rather than re-implementing
that walk, so it can't drift out of sync with the repo's own tag logic.

```python
def category_count_from_tag(decklist_path, tag_label, commander_override=None):
    """
    K = cards IN THE LIBRARY (population -- commander/companion excluded)
    whose oracle_id falls under tag_label's Scryfall tag subtree.
    Returns (K, unmatched_names) -- unmatched names should be reviewed by hand,
    not silently dropped.
    """
    entries = mtg.parse_deck(decklist_path)
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
```

## 6. Putting it together — validated example

Run against a small real decklist (Sol Ring, Arcane Signet, Command Tower,
10x Swamp, commander Obeka, Splitter of Seconds), using the actual repo data
-- not illustrative/hypothetical numbers:

```
Population N = 13 | commander(s): ['Obeka, Splitter of Seconds'] | companion(s): []
Ramp category: K = 2 (unmatched: [])
P(>=1 ramp in opening 7): 80.8%
Simulated check: 81.0% (tracks the exact value, as expected for a static category)
```

`count_population` correctly excluded the commander line (14 total lines in
the file → N = 13). `category_count_from_tag` found 2 cards under the `ramp`
tag tree (Sol Ring, Arcane Signet — Command Tower is fixing, not ramp, so
correctly excluded). The Monte Carlo run lands within noise of the exact
answer, as it should for a static category.

## 7. Known limits / open items

- **No card-effect modeling yet.** The Monte Carlo engine handles static
  categories only; a ramp spell that digs for a land, or a scry/surveil
  effect, isn't represented. Building that out means mapping real oracle text
  per relevant card to simple rule logic — a real project, not a small
  addition.
- **Oracle Tag reliability isn't vetted at scale.** The `ramp` example above
  looked sane on a 4-card sample. Worth spot-checking a few more categories
  (removal, card draw, tutors) against a real decklist before leaning on tags
  as the default category source for anything unfamiliar.
- **Non-Commander formats (e.g. Dandan) aren't tested.** Population counting
  should work automatically for a decklist with no `Commander` section
  (N = full count), but this hasn't been run against a real Dandan list yet.
- **Not yet wired into `mtg.py`.** This lives as a standalone module for now,
  per the "separate doc" plan. If it proves solid, folding the population/tag
  helpers into `mtg.py` itself (as a new subcommand) is a reasonable later
  step, not a decision made here.

## 8. Where the code lives

The functions in sections 2–5 above aren't just excerpts — concatenated in
order, with the two import lines (`math, random` and `mtg`), they're the
entire content of `stats_math.py`. That file now ships as its own artifact in
the repo root rather than being duplicated here: one executable copy, not two
copies that could quietly drift apart if either gets edited without the
other. If a function's behavior ever needs to change, edit `stats_math.py`
and update the matching section above to match — not the reverse.
