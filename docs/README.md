# docs/

Index of the docs, what each is for, and whether it's live. Keep it current when a doc is added, frozen or finished.

## Read first

| Doc | Role |
|---|---|
| `USE_INSTRUCTIONS.md` | The workflow for every session. Scripts cite its section numbers; keep them stable. |

## Tool guides (live)

| Doc | Tool |
|---|---|
| `FISHPOND.md` | `python3 -m fishpond`: Forge-backed deck simulation. |
| `FISHPOND_LAUNCH.md` | The "Launch Fishpond" intake form. |
| `FORGE_ISSUES.md` | Forge bugs met by Fishpond, the patches and card overrides that fix them, and how to bump Forge. |
| `STATS_MATH.md` | `stats_math.py` functions and conventions. |
| `EXPLORER.md` | `explorer.py`: one card's EDHREC context. |
| `GOLDFISH.md` | `goldfish.py` (frozen legacy, still working and in smoke). |

## Active plans (in priority order)

1. **`FORGE_PLAN.md`** — Fishpond's working plan. Standing rules, how to work on the Windows box, where things stand, and the "Priority list" (memo on lookahead copies, life budget, commander timing, commander combat safety, sacrifice-cost drains, finishers, harness hardening, ...), then the backlog. Finished work lives in git history and `FORGE_ISSUES.md`.
2. **`LANDBASE_TEMPO_PLAN.md`** — tapped lands turn by turn in `landbase.py`, validated with Fishpond logging. Step 1 partly covered by `manasim.py` (see its status line).

## Frozen (2026-10-01; simulation moved to Forge)

Reference only. Don't continue these plans.

| Doc | What it was |
|---|---|
| `GOLDFISH_ROADMAP.md` | goldfish.py parser coverage roadmap and audit log. |
| `UPGRADE_PLAN.md` | GEF translation + engine upgrade, steps 1-5 status. |
| `GOLDFISH_EFFECT_FORMAT.md` | GEF, the card-effect JSON format. |
| `TRANSLATION_T0.md`, `TRANSLATION_T2.md` | Translation measurement and the 300-card prototype (incl. T3 sections). |
