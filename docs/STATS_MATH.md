# Stats Math — probability tooling for mtg-data

Companion reference to `USE_INSTRUCTIONS.md`. This doc covers draw-probability
math: exact hypergeometric calculations, Monte Carlo simulation, and using
Scryfall Oracle Tags to build category counts straight from a decklist.

**Default use is automatic:** `audit.py` runs the standard battery (lands,
commander on curve, every role, density/flood) on every deck audit. The user's
standing preference is to lean toward over-using this tooling, not under-using
it, so reach for it for any draw-odds question beyond that battery too.
USE_INSTRUCTIONS.md §6 has the short version; this doc is the engine.

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

*(Resolved: an earlier note here flagged that `mtg.py deck` counted a
Companion section in its total. It now excludes companions too, so both
counts agree.)* Long-form exports with trailing `#tags` parse cleanly; tags
are stripped from names by `mtg.parse_deck`.

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

## 5. Oracle Tags → category counts (and your own #tags)

`mtg.py`'s Oracle Tags handling already walks the parent/child tag tree
(parent tags like `ramp`/`removal` hold zero direct taggings; their cards
live in child tags -- see USE_INSTRUCTIONS.md §7). Everything here reuses
`mtg.load_tags()` and `mtg.find()` rather than re-implementing that walk, so
it can't drift out of sync with the repo's own tag logic.

| Function | Returns |
|---|---|
| `tag_tree(label_or_tuple)` | `{sub_label: oracle_ids}` for one label or a tuple (union), from one pass via `mtg.load_tags_multi` |
| `tag_oids(...)` / `tag_labels(...)` | The oracle_ids / sub-labels in that tree (labels map the user's #tags onto categories) |
| `category_members(deck, tag_label)` | `([(qty, name), ...], unmatched)`: library cards under the tag subtree |
| `category_count_from_tag(deck, tag_label)` | `(K, unmatched)`, a thin wrapper over `category_members`, so count and names can't disagree |
| `category_report(deck, categories=None)` | `{category: {"label", "K", "cards"}}` for every `categories.py` entry (or a subset), from **one** pass over the tag file; prints by default |
| `user_tag_map(deck)` / `norm_label(s)` | The user's own `#tags` from a long-form export, normalized (`Removal-Creature` → `removal creature`) |

Standalone category check (audit.py prints the same lists per role):
```
python3 scripts/stats_math.py report DECKLIST [category ...]
```
It prints N, then each category's K **and the matched card names**. Read the
names before using any K. Tags are a starting point, not a verdict (section 7).

`categories.py` holds the curated category → label mapping. Some categories
come in **broad/strict pairs** (`card_draw`/`draw_engine`,
`ramp`/`mana_producers`), because broad tags answer "does the card have this
effect?" rather than "does it fill this role here?". See §7 for the numbers.

**Which K wins** (implemented in `audit.py`): the user's own `#tags` when they
cover ≥50% of nonland cards → a `--k ROLE=N` confirmed count → oracle tags.
Whenever another source's K would move the odds by ≥15 points, the audit
prints both and flags the role K-SENSITIVE.

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

## 6b. Colors — castability on curve

`color_report(deck)` (printed by `audit.py` in sections 2 and 3). For every colored
card it asks: *given you've seen enough lands to cast it on curve (MV lands by turn
MV), do those lands include a distinct source for every colored pip?* Conditioning on
land count makes this a pure **color** number; running out of lands is section 3's job.

- **Exact.** Lands are grouped by which of the card's colors they make, and the
  multivariate hypergeometric is enumerated over those groups. A dual counts for both
  colors but can only pay one pip, which is checked with Hall's matching condition, so
  `{U}{G}` off 8 duals, 6 Islands and 6 Forests is computed correctly rather than as
  two independent odds. Validated against closed-form math (`{U}{U}` on T2: identical to
  3 decimals) and brute-force simulation (duals, hybrid).
- **Sources** come from goldfish.py's Oracle compiler, so every tool reads a land the same
  way: fetches count as every color among the deck's lands they can find; filter lands
  count their outputs; "any color" lands count every color in the identity (Exotic
  Orchard assumes opponents cover your colors; Plaza of Heroes is treated as unrestricted).
- **Pips** are read from the front face's cost: hybrid `{G/W}` is paid by either;
  Phyrexian `{U/P}` and twobrid `{2/W}` are skipped (payable with life or generic);
  `{C}` needs a colorless source.
- **Two columns:** lands only, and with cheap rocks, dorks (MV below the card's) and MDFC
  land backs also counted as sources.
- **Flags:** under 90% for the commander and package pieces, under 80% otherwise
  (`KEY_THRESHOLD`, `OTHER_THRESHOLD`). Each flag gets the fewest land swaps (non-sources
  of that color turned into sources, up to 8) that reach its threshold, or says none does.
- **Per color:** land sources, and the odds of 1 pip on T1, 2 on T2, 3 on T3.
- **Limits:** tapped lands count as usable on the turn they're played (goldfish handles
  tapped timing); alternative costs (Jodah's WUBRG) and cost reducers aren't considered.

## 6c. Packages — natural draws vs. with tutors

`packages_report(deck)` (audit section 4b). A package is a set of pieces that only matter
together: every Spellbook combo of up to 3 cards whose cards are all in the list (8 shown,
the rest counted), plus each `# package:` header line (`Name = Part + Part`; parts are a
card name, a name pattern `^Myojin of`, `text:<pattern>`, or `tag:<oracle tag>`).

- **Natural:** every piece is among the cards seen by T4 / T6.
- **With tutors:** each missing piece is covered by a *different* tutor that can find it,
  checked with Hall's condition. What a tutor can find comes from goldfish's compiler
  (Demonic any card, Eladamri's Call creatures, Enlightened Tutor artifacts and
  enchantments, land tutors lands). Tutors whose filter can't be read are left out.
- **This is a ceiling.** A tutor counts as the piece, ignoring its mana and the turn it
  costs. Use goldfish for the mana-aware version.
- A piece that is the commander is always available. A card that's a piece isn't counted
  as its own tutor. Parts that share cards aren't computed (make them distinct).
- Exact enumeration; validated against brute-force simulation (10.01% vs 9.95%).

## 7. Known limits / open items

- **Tag reliability: checked on two real decks (Sept 2026).** Always read the
  names that `category_report` / `audit.py` print, and state any
  hand-corrections to K in the write-up.
  - *Yusri (99-card library):* `ramp` misses cost reducers entirely
    (Ruby/Sapphire Medallion), so they're now their own category,
    `cost_reducers`; count both when judging mana. `tutor` includes judgment
    calls: Okaun/Zndrsplt (their "partner with" search) and Enter the
    Infinite. `removal`, `counterspell`, `protection`, and `extra turn`
    matched cleanly.
  - *Wilson (vs hand counts):* broad tags overcount. `draw` found 15 vs 9
    real engines (cantrips, cycling lands), `protection` 11 vs ~7 (Darksteel
    Mutation, Your Temple Is Under Attack), `ramp` 14 vs 11 (Bear Umbra,
    Krosan Verge, Mark of Sakiko). Not cosmetic: at K=11 "2 protection
    pieces by T6" reads 40%; at K=7 it reads 20%, which flips the
    conclusion. Strict mappings help: `draw_engine` matched the hand count
    exactly (9/9).
  - *The two disagree on purpose:* `protection` was clean on Yusri and
    overcounted on Wilson. Reliability depends on the deck (an aura deck is
    full of cards that incidentally grant keywords), which is why the names
    get read every time. **Treat broad tag counts as candidate lists, not
    K.** The user's `#tags` or a confirmed `--k` are the real K.
- **Static draws only.** The Monte Carlo engine handles static categories.
  Draw engines, untappers, cascade, and ramp that digs are goldfish.py's job
  (USE_INSTRUCTIONS §6), so engine decks run better than these odds after ~T3.
- **Colors** are covered by §6b under a hit-your-land-drops assumption; the
  interaction between color screw and land screw is goldfish.py's territory.
- **Non-Commander formats (e.g. Dandan) aren't tested** beyond a smoke test.
  Population counting works with no `Commander` section (N = full count), and
  `audit.py` skips the commander and EDHREC sections.
- **Wiring:** `audit.py` is now the front end. Folding the population/tag
  helpers into `mtg.py` as a subcommand is still optional, not decided.

## 8. Where the code lives

`scripts/stats_math.py` is the single executable copy; the snippets
above are summaries, not the source. It holds: population counting
(`count_population`, `cards_seen`), the exact engine (`hyper_pmf`,
`hyper_at_least`, `multivariate_at_least`, `turn_curve`), Monte Carlo
(`simulate_at_least`), tag helpers (`tag_tree`, `tag_oids`, `tag_labels`,
`category_members`, `category_count_from_tag`, `category_report`), and
user-tag helpers (`norm_label`, `user_tag_map`). If behavior changes, edit `stats_math.py` and update the
matching section here.

- Import it: `python3 -c "import sys; sys.path.insert(0, 'scripts'); import stats_math as sm; ..."` from the repo root.
- Category check: `python3 scripts/stats_math.py report DECK [category ...]`.
- Quick one-off: `python3 scripts/stats_math.py N K n k` prints P(≥k of K in n cards).
- Running it with no arguments prints usage. There is no self-test anymore;
  the old one pointed at a hardcoded path and printed noise.
- Full-deck battery: `audit.py`.
