# Goldfish upgrade plan: status (updated 2026-10-01)

> **FROZEN 2026-10-01.** The user moved simulation to Forge; see `docs/FORGE_PLAN.md`. Do not continue this plan (no GEF translation, no new engine features, no parser work). goldfish.py stays as a working legacy tool.

This is the plan from `UPGRADE_PLAN.md` (the original was written 2026-10-01, at `main` 4bf2f97). Each step below shows what's done, with its commits, and what's left. The details are in `docs/TRANSLATION_T2.md` (the T3 sections) and `docs/GOLDFISH_ROADMAP.md`.

**Summary**

| Step | Status |
|---|---|
| 1. GEF 0.2 | **Done** (805a5b2) |
| 2. GEF-to-engine adapter | **Done** (5c9284c) |
| 3. Engine features, greedy order | **Done**, within a card of the target (8091a3a … 3593db5) |
| 4. Per-deck workflow | **Started:** deck 1 of the 2-3 the gate needs (Ragost: 4b8bb04, ab7c478) |
| 5. The tail | Not started (by design: only when a deck needs it) |
| Housekeeping | Partly done (below) |

Rules followed for every step:
- units, sweep (both paths) and smoke before each commit;
- one commit per step or slice, every commit pushed;
- headline changes explained in the roadmap.

The parser headline moved once, 44.4% → 44.3%, from the session-5 audit fixes (8b9bece). The GEF work never touches the parser path.

## Step 1: GEF 0.2 (done)

Done:
- **Free text removed.** The free-text `replacement`, `restriction` and `hand_ability` statics are gone. In their place:
  - skip a step, +N counters, graveyard replacement, discard → top of library;
  - shock entry (`enters_tapped unless_pay`), spell limit, draw-from-empty-library win;
  - the coin-flip rules (Krark's Thumb, Edgar).
- **Keywords** are an enum everywhere, and `detail` is allowed only on silent keywords. Equip and offering take `filter`; typecycling and landcycling take `card_filter`.
- **Cheap gaps added:**
  - counts: total power, every player's permanents, colors in commander identity, damage dealt this turn;
  - a two-zone tutor (Cultivate) and library position N;
  - choose a creature type, the play-a-land event, "that player's" filters, and a target for each opponent.
- **Prompt v2:** the out_of_scope vs format_gap rule, with the 11 over-cautious cards as examples.
- **Validator:** per-field support tables (library-top recursion, conditional enters-tapped, land type grants) and a lint for the rules the schema can't state.
- **Re-translation:** only the 46 affected T2 cards: 44/46 correct first pass, 46/46 after one retry.

**Exit check passed:** 300/300 T2 cards validate, 0 free-text statics, 18/18 T1 examples.

## Step 2: GEF-to-engine adapter (done)

Done:
- **`scripts/gef_compile.py`** compiles GEF into the engine's structures. It maps exactly or refuses; a refused ability counts as unread and is noted.
- **`goldfish.py --gef`** loads `data/gef/*.json` with precedence override > GEF > parser. It's off by default.
- **`tests/gef_parity.py`** plays every GEF card both ways, comparing structure and seeded probe games. Every difference needs a cause in `tests/gef_parity_causes.json`, or the run fails.
- **Unit checks** for each mapped construct in `tests/gef_units.py`.

**Exit check passed:**
- sweep: 0 errors on both paths;
- every parity difference explained;
- the deck gap vs T2's "GEF today" column explained card by card. The validator's per-construct tables had been optimistic.

## Step 3: Engine features, greedy order (done, within a card)

Done, in the adapter ranking's order (`translation/t2_report.py`) rather than the plan's original list. Eleven slices, each with units and parity causes:
- flicker (now and until the end step), extra turns, coin flips with the coin-flip-won event, storm (token copies for permanents);
- put-from-hand, "you control your commander", X≥N, impulse, riot (as haste, the pilot's pick);
- spell limits, skip draw, conditional enters-tapped by land count, recursion to the library top, library position, library-and/or-graveyard search;
- restricted mana (subtypes, creature sources), tap-an-untapped-creature costs, cycling cost reduction;
- damage dealt this turn, and more.

**Exit:** decks at **Klauth 63.0% / Yusri 66.7% / Zur 75.0%** with `--gef` (target ~64/67/75; the parser reads 50.7/52.2/58.8). 0 audit-wrong translations.

Not done:
- **Klauth's last card for 64%.** Its remaining cards each need a mechanic the engine doesn't have:
  - convoke (Chord of Calling), offering (Blast-Furnace Hellkite);
  - eternalize and a conditional mana ability (Fanatic of Rhonas), station (Evendo);
  - a combat policy for {X} pump activations (Kessig Wolf Run).
- **Convoke and improvise** were never built (Chord of Calling, City on Fire, Whir of Invention).

## Step 4: Per-deck workflow (started: 1 deck)

Done:
- `translation/deck_workflow.py` (select / merge / report), and the comparator's `--out`.
- **Deck 1, the user's Ragost list:**
  - 57 cards translated by two subagents, 0 rejects;
  - 30 hand-audited (the 27 flagged plus a seeded 10% of the "agree" ones): **0 misreads**;
  - translations in `data/gef/ragost.json`, all 118 parity differences explained;
  - error rate logged in the roadmap;
  - fully read: parser 71.8%, GEF 63.5%. The parser had been tuned for this deck.
- The adapter mappings the deck needed, and one adapter bug it found ("it" in a trigger with no object).

Not done:
- **Decks 2 and 3.** The gate for full-pool translation needs 2-3 decks in a row at ≤1% misreads; Ragost is the first.
- **Full-pool translation:** gated on the above.
- **Cost note:** a deck now costs about 420k subagent tokens (2 batches). That's more than T2's per-batch cost, because the format docs grew.

## Step 5: The tail (not started)

Not done, as intended. These are only for decks that need them:
- phasing, redirect, opponent choices (stand-in policies), manifest, mana that persists through phases;
- tokens with their own abilities (Skrelv's Hive, Toggo, Weapons Manufacturing, Mage's Attendant);
- the one-of-each token replacement, extra-Thopter replacement, untap during others' untap steps (format gaps from Ragost).

## Parallel housekeeping

Done:
- **Unit tests pin the 20 `t2_misreads` cards** (6002cd7).
- **Sampled parser audit, session 5** (seed 11): 3/40 misreads. Their three families were swept pool-wide (8b9bece): unknown-filter cost reductions, X with no value, and mana-spent "instead" clauses.
- **`goldfish_coverage.py diff` works on Windows** (tarfile, plus a directory junction).

Not done:
- **This session's sampled parser audit** with a new seed. Seeds 7 and 11 are used.
- **Retiring `t2_misreads` entries.** GEF now reads several of those cards exactly (Long-Term Plans, Rule of Law, Deafening Silence, Ephemerate, Escape Protocol), but only under `--gef`. Retiring them in the parser waits until `--gef` is the default for those cards.
- **Making `--gef` the default.** It isn't on the original plan, but it's the natural next decision: GEF now beats the parser on Yusri and Zur with 0 audit-wrong reads, and trails it on Klauth and Ragost.
