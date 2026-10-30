# docs/

Index of the docs, what each is for, and whether it's live. Keep it current when a doc is added, frozen or finished. Working
docs hold the current state and the rules still in force; history belongs in git (each condensed doc names the commit that
holds its full log).

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

## Active plan

**`FORGE_PLAN.md`** — Fishpond's working plan: standing rules, how to work on the Windows box, where things stand, open pilot
failures, open engine and harness work, the pilot's design rules, and the backlog (user tools first: the swap-list tester, the report,
gauntlet growth).

## Design references (live; condensed from findings logs 2026-10-30)

| Doc | What it holds |
|---|---|
| `THREAT_FINDINGS.md` | The threat model: what it scores, its calibration, the user's rules for counters, removal, holds, wipes and attacks. |
| `SEQUENCING.md` | The turn plan: how a pilot seat orders its turn, setup value, the user's calls, lessons for measuring it. |
| `DECK_YARDSTICK.md` | The user's read on their decks (rank, win turn, commander target); `fishpond sequencing` measures against it. |

## Paused or partly done

| Doc | State |
|---|---|
| `LANDBASE_TEMPO_PLAN.md` | Steps 1-2 covered by `manasim.py`; step 3's logging exists (`#FP-SEQ`); the comparison and a few landbase.py metrics are left. |
| `FIDELITY_PLAN.md` | Paused since 2026-10-10: how much of each deck the goldfish-based tools play; `scripts/fidelity.py` and the fidelity lines are live. |

## Finished (reference)

| Doc | What it was |
|---|---|
| `TUTOR_PLAN.md` | Tutor math in tutors.py, manasim.py and the audit (phases 0-4 done 2026-10-08). |

## Frozen (2026-10-01; simulation moved to Forge)

Reference only. Don't continue these plans.

| Doc | What it was |
|---|---|
| `GOLDFISH_ROADMAP.md` | goldfish.py parser coverage roadmap and audit log. |
| `UPGRADE_PLAN.md` | GEF translation + engine upgrade, steps 1-5 status. |
| `GOLDFISH_EFFECT_FORMAT.md` | GEF, the card-effect JSON format. |
| `TRANSLATION_T0.md`, `TRANSLATION_T2.md` | Translation measurement and the 300-card prototype (incl. T3 sections). |
