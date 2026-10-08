# Landbase tempo plan

Status: **step 1 partly covered by `scripts/manasim.py`** (2026-10-08). Written 2026-10-04.

manasim.py (built for ramp, not tempo) plays lands turn by turn with tapped lands, mulligans and
color-aware land drops, and landbase.py's count table now reads "T mana by T" and "cmdr on T(MV)"
from it. That covers step 1's "usable mana by T" and "commander on curve, colors + untapped".
It departs from this plan's step 0: it runs on goldfish.py's engine (its card reading and land
handling, conditional lands included) instead of a new sim in landbase.py. Still open: "mana lost
per game", "costly tapped turns", the unrecognized-land list, step 2 (swap scoring still uses
`TAP_COST`) and step 3.

## Problem

`scripts/landbase.py` treats a tapped land as making mana the turn it's played. Tapped status only
shows up as a swap tie-breaker (`TAP_COST`, `PRICE_COST`) and a count line ("lands tapped early 13 → 14").
So "3 mana by T3", "cmdr on T4" and every color percentage overstate how fast a list with many
tapped lands is. Example: Zur runs 13 tapped-early lands of 38 and none of that touches the numbers.

## Decision

- **Measure in landbase.py** (fast, isolates the lands, can rank swaps across 100k+ hands).
- **Validate in Fishpond** with logging only, no new sim logic. Fishpond is too slow and noisy to
  resolve a few-percent land effect directly, and it mixes in Forge AI land-sequencing quality.

## Step 0 — check before building (cheap)

- ~~Should the sim live in goldfish.py instead?~~ Decided: no. goldfish.py is frozen (no new engine
  features, `docs/FORGE_PLAN.md`), so build it in landbase.py. Read goldfish's land-drop code only
  as a reference for edge cases.
- Reuse `audit.tapped_kind` and landbase's `tap_kind` (early-turn grading) — don't re-parse oracle text.

## Step 1 — turn-by-turn sim in landbase.py

New report section "5 Tempo" (and a `--no-tempo` flag). Monte Carlo, on the play/draw per `--draw`,
turns 1–5, static draws (same limits as today: no draw/cycling/fetch thinning/land tutors).

Per hand, each turn: draw, pick a land drop, count **usable** mana (untapped lands + ramp in play).
Land-drop policy (must be symmetric and simple):
1. If a tapped land is in hand and this turn's mana need is already met without the drop
   (or nothing castable needs it), play the tapped land.
2. Otherwise play an untapped land that best fixes colors.
3. "Mana need" = the cheapest castable plan for that turn from the hand: commander on its curve turn,
   else the highest-MV castable spell. Keep it crude; document it.

Conditional lands graded against the sim state at that turn:
- "unless you control two or more other lands" (fastlands inverse), "unless you control a [basic type]"
  (check lands), shocklands (assume pay 2 life early → untapped), verges/slowlands per text,
  "two or more opponents" → untapped (already handled by `EARLY_UNTAPPED_RX`).
- Anything not recognized → treat as tapped and list it in the output so gaps are visible.

Metrics (before → after alongside existing section 4):
- **Usable mana by T** (T1–T5): the tempo-adjusted version of "3 mana by T3".
- **Commander on curve, colors + untapped**.
- **Mana lost per game**: expected mana given up to tapped lands over T1–T4 (one number per deck).
- **Costly tapped turns**: % of games where a tapped drop cost mana that was needed, vs. free ones.

## Step 2 — use it in the swap scoring

Replace the flat `TAP_COST` tie-breaker with the mana-lost-per-game delta (weighted against color
gains; keep price weighting). Recheck that recommendations still prefer untapped at equal colors.
Watch runtime: score with a small sample, confirm the final plan with a large one.

## Step 3 — Fishpond logging (validation only)

Per seat, per turn T1–T6: lands in play, untapped mana available at the start of main phase 1, and
whether a tapped land was played. Write to the existing game logs/report; add a summary line per
deck (mean usable mana by turn, commander cast turn). Applies to every seat (pilot symmetry).
No change to how Forge plays. Compare with landbase step 1 numbers for the same list; a big gap
means either a model gap (draw/cycling — expected for Zur) or a Forge land-sequencing problem
(log it in `docs/FORGE_ISSUES.md`, fix at the root per the usual rule).

## Done when

- landbase.py prints section 5 for all decks without errors; unrecognized conditional lands listed.
- Zur before/after on the suggested swaps shows tempo deltas, not just color deltas.
- One Fishpond run logs per-turn mana; numbers roughly agree with step 1 or the gap is explained.

## Budget notes

Steps are independent slices; push after each. Step 1 is the only one with real value alone.
Step 3 can wait for the next Fishpond run that's happening anyway.
