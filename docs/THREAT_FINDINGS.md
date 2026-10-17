# Threat assessment: findings log

A running log of what was built and measured for threat assessment: phase 1 (log only), phase 2 (counterspells and removal),
phase 3 (mana posture). Newest entries at the bottom. Code: `fishpond/harness/ThreatModel.java`, Forge patches 57 and 58
(`fishpond/forge_patches/`). Run sizes follow the targeted-pod rule: 2-3 pods at 15 games, the same seed as the run compared
against. Numbers at that size are directional; a gap under ~3 wins per 15-game pod is noise.

## 2026-10-16: phase 2 (patch 57) on the interaction pods

Pods V05 (Heliod, Xyris, Lumra, Zur), V06 (Niv, Xyris, Omnath, Yusri), V08 (Witherbloom, Klauth, Chulane, Zur), seed 20261014,
15 games each, against p56 on the same pods (`threat_p57_20261016` vs `study150_20261016_p56`).

Counterspells cast, and the share whose target spell came from the caster's top-threat opponent:

| Deck | p56 | p57 |
|---|---|---|
| Zur | 7 counters, 2 of 5 traceable at the top threat | 4 counters, 3 of 4 |
| Yusri | 0 | 2, 0 of 2 |
| Witherbloom | 3, 0 of 1 | 1, 0 of 1 |
| Heliod | 1 | 0 |

Wins per pod:

| Pod | p56 | p57 |
|---|---|---|
| V05 | Heliod 9, Xyris 4, Lumra 1, Zur 1 | Xyris 7, Heliod 7, Lumra 1 |
| V06 | Niv 9, Xyris 5, Omnath 1 | Niv 7, Omnath 3, Xyris 3, Yusri 2 |
| V08 | Witherbloom 7, Klauth 5, Chulane 3 | Witherbloom 6, Klauth 4, Chulane 4, Zur 1 |

Read: counters are spent less often and more of them at the leader, as intended; the sample is too small to measure. Yusri's
two counters went at non-leaders (spells that targeted Yusri, which the save rule lets through). Niv still casts no counters.
Win shifts are within noise; Zur stays at 1/30, so interaction choices alone don't fix Zur.

**Apparent slowdown, then a correction.** Median game time read 90 s on p56 and 160 s on p57, with one AI timeout (none on
p56). I first blamed the threat hooks running inside Forge's lookahead copies of the game (ai.simulation.GameCopier keeps the
same lobby players, so the same SafeControllerAi and policy; each copy is a new Game, so the per-game cache would miss) and
made the hooks answer only for the registered real game (`ThreatModel.register`), with card and spell answers cached per
phase. The rerun on the same seed (`threat_p57b_20261016`) came out game-for-game the same as p57: same winners, same
counters, median 157 s. So the hooks were not the cost, and the comparison itself was wrong: a study seeds each pod by its
position in the pod file (base + 100 x position), so V05/V06/V08 in the 150-game p56 study (positions 5, 6, 8) played
different games than in my 3-pod file (positions 1-3). p56 vs p57 above compares different games, timing included. The
register/cache change stays (it is what patch 57's notes promised and costs nothing); the paired comparison is rerun on p56's
own pod seeds (`threat_p57pair_20261016`, `threat_p57pair_v08_20261016`). Lesson for later A/B runs: match pod seeds, not the
base seed, when the pod file differs.

## 2026-10-17: paired games, decision by decision (V05)

With p56's own pod seeds a p57 game plays the same as its p56 twin until the first decision that differs, so the split shows
the changed decision (`scratchpad diverge.py`: first differing game-action line per game). V05, 15 games: 2 identical; 8 split
first on Forge randomness the seed doesn't fix (mill order, a land choice, a Fabled Passage fetch), which says nothing about
patch 57; 5 split on a threat decision:

| Game | p56 | p57 | Winner p56 -> p57 |
|---|---|---|---|
| 8 | Xyris: Commit on Delighted Halfling | Commit on Heliod | Xyris -> Xyris |
| 9 | Xyris: Chaos Warp on Triskaidekaphile (Zur's) | Chaos Warp on Heliod | Xyris -> Heliod |
| 10 | Xyris plays a land, keeps Chaos Warp | Chaos Warp on Heliod at once | Xyris -> Xyris |
| 0 | Zur: Grasp of Fate takes Razorkin before Heliod | Heliod first | Heliod -> Heliod |
| 4 | Zur: Cyclonic Rift on Xyris | keeps the Rift | Heliod -> Heliod |

Read: removal now goes at the pod's real leader (Heliod won 9/15 on p56) and is used rather than held. Heliod's deck still
wins games where its commander is answered (the rest of the lifegain shell carries it). Divergence diffs are a good audit of
decisions; win effects still need volume, since half the games split on noise first.

## 2026-10-16: calibrating "close to winning" (for phase 3)

24,242 logged seat-turns (threat v2.1 rows from `study150_20261017_threat`, `threat_kx_20261016`, `threat_p57_20261016`).
"Wins within a round" = that seat wins within the next 4 turns. Base rate 3.0%.

| Signal | Share of seat-turns | Wins within a round | Share of all wins it flags |
|---|---|---|---|
| threat >= 60 | 25% | 10% | 85% |
| threat >= 100 | 13% | 17% | - |
| clock <= 2 turns | 8.0% | 20% | 53% |
| clock <= 3 turns | 11% | 17% | 63% |
| combo one piece away or closer (combo >= 40) | 16% | 8.9% | 47% |
| combo complete (combo >= 90) | 1.2% | 26% | 11% |
| an engine cycle | 1.6% | 22% | 12% |
| 3+ payoffs | 6.0% | 19% | 37% |
| 30+ mana lead score | 0.7% | 31% | 7% |
| clock <= 2 or combo >= 40 or a cycle | 22% | 11% | 79% |

Read: the total threat score is a weak absolute predictor (a seat at 60+ wins within a round only 1 time in 10), but its
parts separate well. "One combo piece away" is common and weak on its own (9%): many decks sit one piece away for turns.
Phase 3 holds on the specific parts, not on the total, and matches the answer to the part.

## 2026-10-17: the paired p56 vs p57 run (all three pods)

p57 on p56's own pod seeds (`threat_p57pair_20261016` for V05/V06, `threat_p57pair_v08_20261016` for V08; V08 ran alone, so on
a lighter machine).

| Pod | p56 | p57 (paired) |
|---|---|---|
| V05 | Heliod 9, Xyris 4, Lumra 1, Zur 1 | Heliod 12, Xyris 2, Lumra 1 |
| V06 | Niv 9, Xyris 5, Omnath 1 | Niv 7, Xyris 6, Yusri 1, Omnath 1 |
| V08 | Witherbloom 7, Klauth 5, Chulane 3 | Witherbloom 6, Klauth 4, Chulane 3, Zur 2 |

Game time: mean 146 s (p56) vs 139 s (p57), AI timeouts 0 and 0. There is no slowdown; the earlier "regression" was the seed
mismatch. Counterspells: Zur 5 (2 of 5 at the top threat), Witherbloom 1, against Zur 7 (2 of 5), Witherbloom 3, Heliod 1 on p56.
Win shifts are within noise at 15 games a pod.

## 2026-10-17: phase 3 (patch 58) built

The hold, as built (`ThreatModel.posture`, `holdBlocks`; Forge asks in `canPlaySa` through the `HOLD_MANA` hook):
- **When:** the seat holds an instant-speed answer (a counterspell, or targeted removal: destroy, exile, bounce, sacrifice,
  damage to a creature); its top-threat opponent is close (a 1-2 turn clock, a combo one piece away or complete, an engine
  cycle, 3+ payoffs, a 30+ mana lead score); the seat isn't the leader itself; and no other opponent is set to answer it (a
  deck with 6+ instant-speed answers, counted over its whole list, with 2+ mana up), unless the threat is very close (1-turn
  clock, completed combo, cycle).
- **Fit:** counterspells fit a combo a piece away or closer, a mana lead, an engine being built; removal fits a cycle, a 2-turn
  clock, a completed combo, an engine. The cheapest fitting answer sets the mana kept.
- **Effect:** spells and abilities that would leave less mana than that are refused; its own combo pieces (cast plan level 3)
  and win effects still go; mana abilities, lands and the answers themselves are never refused.
- **Release:** at the end of the turn before the seat's own, kept mana is free (cycling, instant draw, flash).
- **Log:** each refusal as `#FP-HOLD` (turn, seat, answer, mana kept, threat seat, why, refused card); `hold_check.py` turns them
  into episodes (until the seat's next turn) with "answer used" and "threat won during the hold".

Puzzles: `hold_mana_for_counter` passes on seeds 1-2 and fails with `-Dfishpond.holdMana=false` (Forge taps out for Air
Elemental), so it tests the hold itself; `hold_mana_guard_no_threat` and `hold_mana_released_end_step` are guards. A gap the
puzzle shows: holding UU against three lifegain payoffs, the AI then lets Serra Angel resolve (spellThreat under the counter
line: entering creatures feed Soul Warden, but the spell-threat score doesn't count what a spell feeds). Measured next.

Commander penalty (the user, 2026-10-17): removing a commander loses 12 / 7 / 3 threat points by how cheaply its owner recasts
it next turn (2+ mana to spare / just affordable / out of reach), none when it is necessary (it completes a combo on the
battlefield, is part of an engine cycle, or its owner's board kills within two turns); it replaces a flat +15. Forge adds
4 x threat to its target priority, so 48 points at most against a 5/5's ~200. Puzzle `threat_removal_skips_commander`: Reave
Soul on the vanilla 3/3, not the recastable 3/3 commander (seed 3: the AI holds Reave Soul altogether, Forge's own hold-removal
roll). A first version marked every commander "necessary" (an unset combo field read as "complete"); the puzzle caught it.
