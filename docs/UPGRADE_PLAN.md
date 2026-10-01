# Goldfish upgrade plan (for the assistant)

State on 2026-10-01 (`main` at 4bf2f97):
- Weighted fully-read is 44.4%. The T2 parser misreads are now marked honestly instead of read wrong.
- GEF 0.1 is prototyped on 300 cards. The translator misread 1.0% of them; the parser misread 3.3%.
- Background: `docs/TRANSLATION_T2.md`, `docs/GOLDFISH_ROADMAP.md`.
- Goal: the test decks go from about 53% fully read to about 69%, then the tail. Never trade correct reads for coverage.

Rules for every step:
- Run units, smoke and sweep before and after each change.
- Commit one step at a time.
- Any change to the headline number gets an explanation in the roadmap.
- Stop and report when a step's exit check fails.

## Step 1: GEF 0.2 (≈1 session)
- Replace the free-text `replacement` and `restriction` statics with real constructs, or remove them:
  - skip draw step
  - +N counters
  - graveyard → exile
  - discard → top of library
  - shock entry
  - spell limit per turn
  - draw-from-empty-library win
- Make pump/grant `keywords` an enum. Allow `detail` only on silent keywords.
- Add the cheap gaps:
  - counts: total power of attacking creatures, creatures on the whole battlefield, colors in commander identity, damage dealt to a player this turn
  - a tutor that sends found cards to two zones (Cultivate)
  - choose a creature type
  - a "play a land" event
  - an owner-relative filter ("that player's creatures")
  - library position N
- Prompt v2: the out_of_scope vs format_gap rule, with examples from the 11 over-cautious cards.
- Fix the validator's per-field support tables: recursion to library top/bottom, conditional enters-tapped, land type grants.
- Re-translate only the cards affected.
- **Exit:** the T2 cards re-validate, the free-text count is 0, and the T1 examples still pass.

## Step 2: GEF-to-engine adapter (≈2–3 sessions)
- New module `scripts/gef_compile.py`: GEF → the existing `k.spell` / `k.trig` / `k.acts` / `k.statics` tuples, for the constructs the engine already supports. It refuses anything else, and those abilities count as unread.
- Precedence: override > GEF > parser. Load GEF from `data/gef/*.json`.
- Harness `tests/gef_parity.py`: play the 300 cards through the parser path and the GEF path on fixed seeds, and diff game stats per card. Investigate every diff and record its cause.
- Unit tests for each mapped construct.
- **Exit:**
  - sweep shows 0 errors on both paths
  - every parity diff is explained
  - the deck numbers match T2's "GEF today" column, or the gap is explained

## Step 3: Engine features, greedy order (≈2–3 sessions)
- Order: flicker, untap, coin flips plus the coin-flip-won event, storm, put-from-hand, "you control your commander", X≥N, impulse, extra turn, riot, convoke, improvise.
- Each feature gets a unit test, and its cards get a parity or behavior check.
- Re-rank after each feature with `translation/t2_report.py`.
- **Exit:** the decks reach about 64/67/75% (Klauth/Yusri/Zur) with 0 audit-wrong reads.

## Step 4: Per-deck workflow (ongoing, cheap)
- For each new deck: translate the untranslated cards with subagents, 1–3 runs.
- Validate, compare, then hand-audit the cards the comparator flags, plus 10% of the ones it calls "agree".
- Log the deck's error rate in the roadmap.
- **Gate for full-pool translation:** two to three decks in a row at ≤1% misreads, and GEF 0.2 stable. Then run it in batches of 100 and audit a stratified 2% sample.

## Step 5: The tail (open-ended)
- Phasing, redirect, opponent choices (use stand-in policies), manifest, mana that persists through phases.
- Do each one only when a deck you actually play needs it.

## Parallel housekeeping
- A new sampled parser audit each session, with a new seed.
- Add unit tests that pin the 20 `t2_misreads` cards.
- Retire `t2_misreads` entries as GEF reads take those cards over.
