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

## 2026-10-17: phase 3, first measurement (`threat_p58pair_20261017`, `threat_p58pair_v08_20261017`)

Same pods and seeds as the paired p57 run.

| Pod | p57 (paired) | p58 |
|---|---|---|
| V05 | Heliod 12, Xyris 2, Lumra 1 | Heliod 11, Xyris 3, Lumra 1 |
| V06 | Niv 7, Xyris 6, Yusri 1, Omnath 1 | Niv 7, Xyris 5, Omnath 2, Yusri 1 |
| V08 | Witherbloom 6, Klauth 4, Chulane 3, Zur 2 | Witherbloom 6, Chulane 3, Klauth 3, Zur 2, 1 capped |

Mean game 139 s -> 142 s. 42 hold episodes (a seat refusing spells until its next turn); the held answer was cast in 7; the
threat won during the hold in 3. Not good enough:
- **Holds refused the deck's own plan.** Yusri refused Nexus of Fate 113 times, Jin-Gitaxias 68, Enter the Infinite (a key
  card) 18; Zur refused Triskaidekaphile, Astral Drift and Zur itself (all key cards), and cycling Wander in Death with
  Astral Drift out (66). Only cast-plan level 3 (combo) was exempt.
- **Ephemerate counted as an answer**: targeted exile from the battlefield read as removal, though it targets your own
  creature and returns it. Zur kept W up for it four turns running.
- **Holds rarely paid off**: 7 of 42 answers cast; "one combo piece away" (the weak 9% signal) started 15 of the holds.
- One V08 game ran to the cap (78 turns) with 13 lookahead fallbacks (the known GameCopier "couldn't map" crash class): a
  long stall, likely helped by Zur holding.

Fixes (same day): the seat's key cards, its commander, cast-plan level 2+ (combo, key card, engine pieces) and spells of 6+ mana
are never refused; cycling is never refused with a cycling payoff out; own-target blinks (ValidTgts YouCtrl/YouOwn, or exile
then return) are not answers (puzzle `hold_mana_not_for_blink`); a hold for a weak reason (combo a piece away, payoffs, mana
lead) lasts one round per opponent and reason; while a seat holds against an opponent, that opponent's spells get +20 spell
threat, so the mana held is spent on them (in `hold_mana_for_counter` the AI now counters the Serra Angel it held UU for,
instead of letting it resolve).

## 2026-10-17: phase 3, refined (`threat_p58bpair_20261017`, `threat_p58bpair_v08_20261017`)

| Pod | p57 (paired) | p58 first | p58 refined |
|---|---|---|---|
| V05 | Heliod 12, Xyris 2, Lumra 1 | Heliod 11, Xyris 3, Lumra 1 | Heliod 10, Xyris 4, Lumra 1 |
| V06 | Niv 7, Xyris 6, Yusri 1, Omnath 1 | Niv 7, Xyris 5, Omnath 2, Yusri 1 | Niv 7, Xyris 5, Omnath 2, Yusri 1 |
| V08 | Witherbloom 6, Klauth 4, Chulane 3, Zur 2 | Witherbloom 6, Chulane 3, Klauth 3, Zur 2, 1 capped | Witherbloom 5, Klauth 4, Zur 3, Chulane 3 |

Hold episodes 42 -> 24, answers cast in them 7 -> 4, the threat winning during a hold 3 -> 2. No key card, commander or win
card refused; V08 back to 0 lookahead fallbacks and no capped game (Zur 7 holds -> 2). Mean game time per pod 133/157/127 s
(p57) vs 147/168/123 s. Wins move within noise everywhere.

What's still weak, from the episodes: Yusri held Pongify against Omnath's completed combo for two turns (the pieces aren't
creatures), and counterspells counted as fitting a combo already on the battlefield. Refined again: removal fits only if it
can legally target one of the threat's permanents at removal threat 40+ (`hitsWhatMatters`); counterspells fit a combo a piece
away, not a completed one.

Where phase 3 stands: the hold is now principled and cheap (it no longer costs the deck its own plan, and games aren't
slower), and when a seat holds it now spends the mana on the seat it held for. Whether it changes win rates can't be read
from 15-game pods: the effect per game is a handful of decisions, and half of paired games split on Forge noise first. It
needs volume (an overnight batch on a few interaction-heavy pods, paired seeds, hold on vs `-Dfishpond.holdMana=false`).

## 2026-10-17: phase 3, targeting fit measured (`threat_p58cpair_20261017`, `threat_p58cpair_v08_20261017`)

| Pod | p57 (paired) | p58 refined + targeting fit |
|---|---|---|
| V05 | Heliod 12, Xyris 2, Lumra 1 | Heliod 10, Xyris 4, Lumra 1 |
| V06 | Niv 7, Xyris 6, Yusri 1, Omnath 1 | Niv 7, Xyris 5, Omnath 2, Yusri 1 |
| V08 | Witherbloom 6, Klauth 4, Chulane 3, Zur 2 | Witherbloom 5, Klauth 5, Chulane 3, Zur 2 |

23 hold episodes (24 before), 3 answers cast. Mean game time 146/147/118 s per pod (p57 133/157/127). Yusri held 9 times and
cast the answer 0 times; what the threat cast during those holds shows why: Yusri's counters are narrow. It held Muddle the
Mixture (instants and sorceries only) while Niv cast Niv-Mizzet, Vito, Sheoldred and Rest in Peace, and Swan Song while Xyris
cast Xyris (the one legal target it saw was Reforge the Soul). Refined: a counterspell with a target restriction fits only if
35%+ of the threat's nonland cards (its whole list: deck knowledge) are legal targets (`counterShare`; puzzle
`hold_mana_not_for_narrow_counter`: Negate against a creature deck sets no hold).

## 2026-10-17: phase 3, final measurement (`threat_p58dpair_20261017`, `threat_p58dpair_v08_20261017`)

With the narrow-counter fit, same seeds: wins identical to the previous version (V05 Heliod 10, Xyris 4, Lumra 1; V06 Niv 7,
Xyris 5, Omnath 2, Yusri 1; V08 Witherbloom 5, Klauth 5, Chulane 3, Zur 2), 0 AI timeouts, mean game time 146/164/119 s per pod.

Hold episodes across the iterations on these 45 games:

| Version | Episodes | Answer cast | Threat won during the hold |
|---|---|---|---|
| first (5f29171) | 42 | 7 | 3 |
| own plan exempt (e9a57bf) | 24 | 4 | 2 |
| + removal must hit what matters | 23 | 3 | 2 |
| + narrow counters fit the deck (4ba263d) | 17 | 3 | 1 |

Summary of phase 3: the hold no longer costs a deck its own plan, holds only with an answer that can hit the threat's deck or
board, and spends held mana on the seat it held for. It is cheap (no slower games) and rare (17 holds in 45 games). Its effect
on win rates is below what 15-game pods can show. Next, if wanted: an overnight A/B on interaction-heavy pods (Zur, Yusri,
Niv, plus the decks they face), paired seeds, hold on vs `-Dfishpond.holdMana=false`, a few hundred games; and the open gap
from the first puzzle: spell threat doesn't count what a spell feeds (a creature entering into Soul Warden).

## 2026-10-17: counters see what a spell feeds; commander counters weighed like removal

The user's two calls after phase 3:
- **Commander spells as counter targets** are weighed like removal: the flat +25 for a commander spell is gone, and the
  spell threat loses the same 12 / 7 / 3 points by how cheaply the commander comes back (none when it completes a combo, closes
  an engine cycle, or its board kills within two turns).
- **Pattern recognition on counterspells:** `resolveEvents` lists what a spell makes happen as it resolves (a permanent
  entering, landfall, its own enter trigger's effects; a nonpermanent's draws, tokens, life, damage, counters, sacrifices; a
  draw of 3+ counts 3, and a wheel's "each player draws" feeds opponents'-draw payoffs like Xyris's Snakes). `fedTriggers`
  counts the caster's permanents that feed on those events (each at the most its event happens), and spell threat adds 10 per
  fed trigger, up to 40. Same vocabulary as the engine graph; board and deck knowledge only.

Puzzles: `threat_counter_fed_wheel` (Reforge the Soul into Xyris and Psychosis Crawler: countered; the previous build let it
resolve on both seeds, spell threat 15, under the keep-the-counter line) and `threat_counter_fed_enters` (Grizzly Bears into
four lifegain-on-enter creatures: countered on both seeds; the previous build countered on one of two, Forge's own roll).

## 2026-10-17: 100-game study (`study100_20261017_p58e`, commit f202764)

Pods V05-V09 at 20 games each, every pod on its p56 seed (games 0-14 pair with `study150_20261016_p56`). 100 of 100 ended
naturally, 0 AI timeouts; 10 per-decision lookahead fallbacks in 8 games (p56: 1 game on these pods): 6 are a Forge crash in
the lookahead's game copy (`CopyPermanentEffect.getProtoType` -> `CardFactory.readCard`: a copied token has no card data, so
copying it inside a simulation throws; Xyris games), 2 are GameCopier "couldn't map" (a Snake token, Decorum Dissertation).
Each fallback remakes that one decision without lookahead; p57/p58 runs on these pods showed the same count.

Win rate per deck, p56 (15 games a pod) -> now (20 a pod):

| Deck | p56 | now |
|---|---|---|
| Heliod | 20/30 (67%) | 29/40 (72%) |
| Niv-Mizzet | 9/15 (60%) | 8/20 (40%) |
| Witherbloom | 7/15 (47%) | 8/20 (40%) |
| Xyris | 9/30 (30%) | 13/40 (32%) |
| Klauth | 5/15 (33%) | 6/20 (30%) |
| Erebos | 7/15 (47%) | 6/20 (30%) |
| Wilson | 3/15 (20%) | 5/20 (25%) |
| Zhulodok | 3/15 (20%) | 5/20 (25%) |
| Yusri | 2/30 (7%) | 7/40 (18%) |
| Chulane | 3/15 (20%) | 3/20 (15%) |
| Lumra | 4/30 (13%) | 4/40 (10%) |
| Omnath | 1/15 (7%) | 2/20 (10%) |
| Zur | 1/30 (3%) | 3/40 (8%) |
| Ragost | 0/15 | 1/20 (5%) |
| Jarad | 1/15 (7%) | 0/20 |

The interaction decks moved up (Yusri 7% -> 18%, Zur 3% -> 8%) and Niv and Erebos down; at these sizes each of those is one or
two standard errors, so a direction, not a result. Heliod is still the strongest deck by far (it wins V05 and V07 three games in
four).

Counterspells: Zur 8 (2 of 6 traceable at the top threat), Yusri 5 (2 of 2), Witherbloom 2, Wilson 1, Zhulodok 1; p56 on the
same pods: Zur 7 (2 of 5), Yusri 4 (2 of 2), Zhulodok 4, Witherbloom 3, Heliod 1. Holds: 32 episodes in 100 games, the held
answer cast in 9, the threat winning during a hold in 2; "a combo piece away" still starts most holds (14 of 32).

Found: Zur's hold refused wizardcycling Step Through 9 times. Step Through is a key card that is only ever wizardcycled (the
user's override), and the key-card exemption covered casting it, not its cycling.

## 2026-10-17: board wipes (patches 59-63)

The user's rules for wipes: refuse when the caster loses as much or more than anyone; cast when every opponent loses a little
more, or one loses a lot more; weigh what the caster keeps afterwards (Wilson wiping around himself); get card types and
modal choices right (Austere Command, Farewell). Wilson is the yardstick: a deck built to wipe and capitalize.

Found first: Forge's mass-removal logic returned on the **first opponent in seat order**, so in a pod a wipe never weighed the
other two boards; Farewell picked modes one at a time and exiled its caster's artifacts; overloaded Cyclonic Rift was never cast
(17 Rifts in 100 games, all single-target). Patch 60 judges every wipe across the table by each player's real loss, patch 61
judges overloaded spells as wipes.

`study100_20261017_p61` (patches 60-61, same pods and seeds as `study100_20261017_p58e`): 100 of 100 natural, 0 AI timeouts.
Heliod 29/40 -> 27/40, Wilson 5/20 -> 7/20, Klauth 6/20 -> 9/20, the rest within a game or two. Zur's Cyclonic Rift 10 -> 15
casts (overloads now). Three problems surfaced, fixed the same day:
- Wilson's wipes were judged worth casting on 26 turns and cast on 5: the mana went first to the cards the cast plan ranks high
  (patch 62: wipes are considered first).
- Edicts misread as wipes: Flare of Malice refused 82 times, Archfiend of Depravity's trigger 39 (patch 62: table-wide effects
  only).
- 57 lookahead fallbacks, 51 in one V08 game: a static effect listing a card that had left the game (patch 63). The token-copy
  crash (patch 59) is gone from this run's traces.

### Wilson's pods on patches 59-63 (`wilson_20261017_p63_V04/V07/V10`, 20 games each on p56's pod seeds)

60 games, all natural, 0 AI timeouts, **0 lookahead fallbacks**. Wilson's wipes cast: V04 + V10 13 in 30 games on p56 (0.43 a
game) -> 34 in 40 (0.85); V07 6 (p58e) -> 5 (p61, before wipes-first) -> 13 (p63). Wilson wins: V04 8/15 -> 10/20, V07 3/15
(p56), 5/20 (p58e), 7/20 (p61), 5/20 (p63), V10 10/15 -> 11/20: 21/45 (47%) -> 26/60 (43%). Heliod on V07: 11/15, 14/20,
11/20, 12/20. So Wilson now wipes twice as often, and that hasn't turned into wins at this sample size.

## 2026-10-18: Wilson's clock (commander damage, double strike)

From `pod300_20261018` (Yusri, Wilson, Erebos, Zur; 292 natural games): Wilson won the pod 143 times (48%) but was the top threat
one round before his win in 61 (43%), and his clock read 2 turns or less in 51. The clock counted damage against life only and
read a creature's power once: Wilson with Flaming Fist (double strike when he attacks, a granted trigger the board doesn't show)
at 6 power read 6 a turn against 40 life, 7 turns, where he deals 12 commander damage a turn and kills in 2. Removal rated
creatures by power the same way (a 9/9 vanilla over that Wilson). The user, 2026-10-18: "Wilson can jumpscare people";
"we really do need to fix the threat analysis on him".

Fixed in `ThreatModel`: the clock doubles double strike (the keyword, or an attack trigger that grants it to the attacker) and a
commander kills at 21 commander damage less what it has dealt that player; removal's creature weight uses the same damage
(`killDamage`: a commander's scaled by the viewer's life over the commander damage it still needs). Puzzle
`threat_clock_commander_double_strike` (Swords to Plowshares: Wilson 6/6 with Flaming Fist over an Ancient Brontodon; the old
model exiled the Brontodon).

`pod80_clock_20261018` (games 0-79 on the same seeds as `pod300_20261018`): Wilson top threat one round before his win 16/39 ->
18/33, his clock 2 turns or less then 11/39 -> 19/33; his share of top-threat rows on global turns 17-24 5% -> 19%, 25+ 24% ->
32%. Pod wins Wilson 39 -> 33, Erebos 14 -> 16, Zur 5 -> 7, Yusri 22 -> 21 (80 games: inside the noise). Spells and abilities
aimed at Wilson 81 -> 83, attacks on him 230 -> 255: the table sees him sooner; its answers didn't grow. Still open: on turns 1-16
Wilson is almost never the top threat (Yusri and Zur carry a 15-point combo floor from their lists, two pieces missing), and a
burst from hand (game 141: a 2/2 to 41 damage in one turn off Ancestral Mask and Calix) can't be read off the board.
