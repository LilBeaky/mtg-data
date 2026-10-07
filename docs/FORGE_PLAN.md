# FORGE PLAN: Fishpond's working plan

Working doc for Claude: what is left to build in Fishpond and in what order. Usage is in `docs/FISHPOND.md`; every Forge bug and patch is in `docs/FORGE_ISSUES.md`. Finished work and old run write-ups are not kept here (git history has them: this doc before 2026-10-07 holds the original build plan, the pilot study and every run since). Reorganised 2026-10-07.

## Standing rules (the user's)

- **Governance (2026-10-01).** No change to the engine choice or the overall architecture without a written case, a cheap test with evidence, and the user's go-ahead. Check whether an existing tool already does something before building it. Iteration inside the plan is fine.
- **Forge is the simulator.** goldfish.py is frozen (no new engine features), kept as a fast cross-check. Forge is downloaded at run time, never vendored.
- **Pods are always 4 players at 40 life.** Each opponent seat is a dummy or a real deck; never simplify to fewer seats or to dummies only when real opponents were asked for.
- **Pilot logic is symmetric and general.** Every pilot rule applies to every pilot seat, never the hero alone; prefer policy-level rules over per-card fixes, with explicit opt-outs; ask about exceptions instead of guessing. `--pilot-seats you` is an A/B switch only.
- **Fix Forge bugs at the root.** A search fallback, replay or pause is a bug to fix with a patch and an evidence seed in FORGE_ISSUES, not a count to live with. `--sim full` must work.
- **Pilot-error losses are shown beside the headline win rate,** never excluded, with the game and turn of each (so it can be replayed by seed).
- **Upstream:** nothing goes to Card-Forge/forge without the user's go-ahead on the exact diff (they submit under their account; disclose that Claude helped).

## How to work here (Windows box)

- Repo is local (`C:\Users\ianfr\Desktop\mtg-data`); use `python -m fishpond`. 20 CPUs, 32 GB. Java: a 32-bit Java 8 is first on PATH; fishpond picks JDK 25 itself (`%LOCALAPPDATA%\Programs\Eclipse Adoptium\jdk-25*`), but anything run by hand (ForgeRunner, `jfr`) must use JDK 25.
- **Before a run:** `git fetch` and compare with origin/main (other sessions push to this tree); print the `--out` folder and make sure it doesn't exist (`run` refuses one with results). Two 5-game pods at a time with `--jobs 5` each is a good load: hybrid games take 1-10 min, 50 games about 50 minutes.
- **Claude's background tasks die at 2 hours.** Split batches into resumable chunks under that (`run --resume` finishes a cut-off pod), or hand the user the command for long studies (the user's preference as runs grow).
- **Seeds replay exactly.** One game replays alone from one line of a run's `logs/plan_*.tsv` with ForgeRunner (the command line is in `runner.execute`); the game log is printed only when the game ends. Profile with `-XX:StartFlightRecording=...,settings=profile` and dump mid-turn with `jcmd <pid> JFR.dump`. Since patch 16 games diverge from pre-16 runs on the same seed: compare distributions, not paired games, across that boundary.
- **Writing a patch:** `~/forge-cache/forge-src-2.0.15` is CRLF and doesn't match the tag; fetch the files with `forge.FORGE_SRC_URL` into a scratch git repo, apply 01..NN, edit, `git diff` > the next patch; procedure and table in FORGE_ISSUES "Patches". To see a debug println, call `fishpond.puzzles.run_one(path)` and grep its lines.
- **Before pushing:** `python -m fishpond puzzles` (80: 78 pass, 2 known gaps) and `python tests/smoke.py`. Stage only your own files, fetch/rebase, never force. Write findings into this doc as soon as they're known.
- `--sim hybrid` prints hundreds of "AI failed to play" lines a game (lookahead test-casts unaffordable spells): noise, not a stuck card.

## Where things stand (2026-10-07)

- **Built:** harness and cli engines, goldfish-layout reports with Fishpond's sections, resumable runs, puzzles, `compare`, `flags`. Pilot: tutor policy at every seat, Forge patches 01-25 (crash fixes, big-board blocks, loop shortcut, combat-prediction memo, and pilot patches for cycling, blink, empty-library wins, Wheel, Araumi, City of Traitors, draw-the-library and Approach, Primal Surge, sacrifice fodder, no decking casts, life budget, commander timing and combat safety, ramp first), 31 card overrides.
- **Run validity:** the last 80 games (`powermatch_20261007_p16`, `varied_20261007`) had 1 timeout (a Vilis life-payment spiral, item 2), 0 per-decision search fallbacks, and 4 games replayed whole without lookahead after a crash in it (item 7; an earlier count here said 0 because it only looked at per-decision fallbacks); lookahead pauses on prepared cards (#1) about once per 7 games.
- **Reference runs** (`data/fishpond/`, gitignored): `varied_20261007` (10 pods x 5, every deck 2-3 times, seeds 20261007 + 100 x pod; `pods.txt`, `lane.sh`) is the current baseline; `powermatch_20261007_p16` (6 power-matched pods, seed 1); `pilot_study_20261004` (100 games by bracket, before patches 12-16).
- **Current single-winner record** (varied, 50 games): Heliod 9/15, Niv 5/10, Klauth 5/15, Ragost 5/15, Witherbloom 5/15, Wilson 4/15, Araumi 3/10, Lumra 3/15, Zhulodok 3/10, Erebos 2/10, Omnath 2/15, Xyris 2/10, Yusri 1/10, Zur 1/10, Chulane 0/10, Jarad 0/15. Small samples: signals, not rates.

## Priority list

Ordered by payoff over difficulty (items 5 and 6 done 2026-10-07, worked first at the user's request): run validity first (every later number depends on it), then rules that help every deck, then single decks. Each item gets puzzles first (failing), then the fix, then its acceptance. N-numbers are the failure IDs used in earlier write-ups and commits.

| # | Item | Difficulty | Payoff |
|---|---|---|---|
| 1 | **Done 2026-10-07** (patch 21; repeats gone, the rest is item 1b) Combat-prediction memo on lookahead copies (N8) | Low-medium: one patch, diagnosed | High: slow turns, AI timeouts, every big board |
| 2 | **Done 2026-10-07** (patch 23) Life budget (N4, Yusri coin buffer) | Medium: one rule over optional life payments | High: self-kills in Niv, Erebos, Yusri; the last timeout |
| 3 | **Done 2026-10-07** (patch 24; hold list pending the user) Commander timing, with cumulative upkeep (5c, N7) | Medium: policy rule + opt-out header | Very high: every deck, about a turn of tempo |
| 4 | **Done 2026-10-07** (patch 24) Commander combat safety | Medium: attack/block patch + 6 puzzles | High: every deck's commander |
| 5 | **Done 2026-10-07** (patches 17, 18, 20) Finisher misses (Primal Surge, Enter the Infinite, Approach) | Medium-high: one fix each | Medium: Chulane 0/10, Yusri 1/10, Zur 1/10 |
| 6 | **Done 2026-10-07** (patch 19) Sacrifice-cost damage and drains (N10: Jarad, Ragost) | Medium | Medium-high: two decks' whole engine |
| 7 | Harness hardening | Medium | Medium: protects the big re-runs |
| 8 | Symmetric self-mill and wipe (N6) + Araumi encore mana | Low-medium | Low-medium: Araumi, any self-mill deck |
| 9 | Pump abilities in loop detection (N9) | Low | Low: a guard |
| 10 | `fishpond study` command | Medium (tooling) | Makes 11 cheap and repeatable |
| 11 | Re-run: whole study at 8 games a pod; bigger Araumi study | Run time | Measures 1-9 |

### 1. Done 2026-10-07: combat-prediction memo on lookahead copies (N8, patch 21)

- **Problem:** turns of 10-12 minutes on big boards with AI decisions hitting the 120 s limit (`varied_20261007` V04 game 3, V05 game 4). JFR: 76% of the turn under hybrid's one-move check, 66% in the uncached combat prediction; patch 16's memo was per `Game` and every candidate play runs on a fresh copy, so it never hit there.
- **Fix (patch 21):** copies record the game they came from and share its memo; the key also covers combat keywords and noncreature permanents with static abilities, so a play that grants flying or taxes attacks never reuses a stale answer.
- **Measured** (`-Dfishpond.memoStats`): replays of V05 game 4 and V04 game 3 with the old memo computed 2,114 and 1,923 predictions, of which 908 (43%) and 964 (50%) were exact repeats of a board already predicted that turn, costing 27 of 51 s and 40 of 78 s of prediction time. With patch 21: 0 repeats; 46-47% of requests answered from the memo. Fixed-board benchmarks (scratch puzzles, two runs each, identical results): 30 creatures a side with a 10-card hand, predictions 47 -> 32, prediction time 49.6 -> 36.5 s (-26%), puzzle wall 107 -> 91 s; 120 a side, predictions 8 -> 4, 28.2 -> 17.0 s (-40%), wall 92.5 -> 73.5 s. Games diverge from older runs (the block planner draws random numbers): compare distributions.
- **1b (2026-10-07, patch 22):** profiled one prediction on the 30-a-side board: 66% in the block planner's pair search (`makeGoodBlocks`, `canDestroyBlocker/Attacker`), with every pair check rebuilding the list of every trigger on the board. Patch 22 builds that list once per combat plan; decisions are unchanged (same-seed games identical action for action), prediction time -8 to -10%, whole replays V05 game 4 1,053 -> 960 s and V04 game 3 367 -> 348 s. **Left:** the pair search itself. Cutting it means changing how Forge plans blocks (fewer pairings tried, cheaper kill checks), which changes play: a design question, not a free cache. Parked unless big-board time becomes the bottleneck again.

### 2. Done 2026-10-07: life budget (N4, patch 23)

A pilot seat refuses a play whose life cost (paid as a cost, or "you lose N life" in its own effect) leaves it dead to the next combat the table can make (`aiLifeInDanger`, serious); Yusri-style flips are capped so the worst case leaves 1 life (the user's rule: 5 flips at 11 life, 4 at 10). Puzzles: `vilis_life_payments` (no longer a known gap), `erebos_draws_life_budget` and its guard, `yusri_flips_at_10/11`. **Not covered:** life loss that isn't the AI's own play cost or effect (Ad Nauseam's reveal loop, shocklands' "pay 2 or enter tapped" choice) and Tainted Sigil's timing.

### 3 and 4. Done 2026-10-07: commander timing, cumulative upkeep, commander combat safety (patch 24)

- **Rules (every pilot seat; `-Dfishpond.commanderRules=false` turns them off):** the commander is cast as soon as it's affordable in its controller's main phase, ahead of other spells and past the "cast later" checks and hybrid's veto, unless the seat faces lethal, its cost has X, or its list says `# commander: hold`. A cumulative upkeep is let go when paying it would stop the commander being cast this turn or takes more than half the available mana (Mystic Remora). The commander attacks only a player none of whose untapped creatures can kill it in a block (moving to a safe opponent, else staying home) unless it has an attack trigger (Yusri, Zur, Klauth); it doesn't block an attacker that would kill it unless the damage would be lethal. The harness passes `# commander: hold` commanders to Forge (`policy.json` `commander_hold` -> `-Dfishpond.commanderHold`).
- **A/B** (`data/fishpond/cmdrules_20261007/off` vs `on`: varied pods V02 V06 V07 V08 V10 on their seeds, 25 games each, all 110 commander seats): commanders out by their own turn 4 **48 -> 66**, by turn 5 63 -> 78, cast at all 96 -> 101, median first cast turn 4.5 -> 4; commander attacks 137 -> 158, commander blocks 16 -> 10, commanders leaving the battlefield 43 -> 46 (more commanders out, earlier, for about the same losses). Biggest movers: Ragost 5 -> 2, Wilson's Flaming Fist 7 -> 3, Yusri 4 -> 3, Niv 9 -> 7. Klauth (7 mana) is gated by mana, not the rule: in both runs it came down when its controller reached 7 mana; the two games it never came down in the `on` run it died on 4-5 lands. All 50 games ended naturally.
- **Puzzles:** `mystic_remora_upkeep_commander` (fails without the patch); `commander_on_curve_klauth`, `commander_attack_*`, `commander_block_*` are regression guards (stock Forge already passes those simple boards; the gain shows only in games).
- **Open:** the user to name decks that should hold their commander (the example was Grothama; none of the 16 lists in `decks/` is marked yet). Niv-Mizzet is still late (median turn 7, cast in 4 of 5 games): check its mana (colors, rocks) before calling it a pilot issue.

### Klauth diagnosis (2026-10-07; the user: one of the strongest lists, should deploy turns 4-5)

- **Vacuum, 40 games** (`data/fishpond/klauth_ramp_20261007/`, seed 77, three dummies, so no removal): Klauth out by its own turn 5 in 35% (patch 25 off) / 40% (on), turn 6 57-60%, turn 7 75-80%.
- **Not the commander decision:** a debug build logged every look at Klauth: each of the 21 times Forge could pay for it, the AI cast it at once (patch 24 works); the other 578 checks it couldn't pay.
- **"8 mana on turn 4" was a measuring error:** the snapshot's `mana` is Forge's estimate (`getAvailableManaEstimate`), which counts Castle Garenbrig's activated ability as 6 and similar; 3 lands read as 7 mana. The report's `≈mana` column overstates any deck with such lands. Fix: report usable mana (untapped producers that can pay now) instead, or alongside.
- **What actually limits it:** early mana. About 1 ramp card per opening hand (13 accelerants and cost reducers among 63 nonland cards), no ramp cast by turn 4 in 12-13 of 40 games; up to a third of land drops on turns 1-5 have an enters-tapped clause (64 of 171), and several lands make only colorless. Land sequencing is mostly fine (14 of 106 early drops put a tapped land down while holding a basic, mostly on turns with nothing to cast).
- **Pilot fix made (patch 25, ramp first):** Forge cast mana dorks, rocks and cost reducers only in main 2, after spending the mana on the best-rated spell; a pilot seat with under 7 lands now casts them in main 1 and first (puzzle `ramp_first_elves`). Held-but-affordable ramp on turns 1-4: 27 -> 21; Klauth by turn 5 35% -> 40% (small: the ramp mostly isn't in hand).
- **Open:** early tutors (Worldly Tutor fetched Savage Ventmaw and Broodcaller Scourge on early turns; rare here, 5 early tutor decisions in 40 games) should prefer ramp or a cost reducer while the commander is uncast and mana is short (tutor policy role layer); Forge's mulligans keep every 7 (no ramp-light mulligans); deck construction is the user's call (tapped and colorless lands, ramp density).

### 5 and 6. Done 2026-10-07: finishers, sacrifice-cost engines (patches 17-20)

What each patch does is in FORGE_ISSUES "Patches" and FISHPOND.md "The pilot"; puzzles 67/67 (3 known gaps). Re-runs on the varied seeds (`data/fishpond/finishers_20261007/`, V03, V07, V08, V09 and the power-matched G4 at seed 1; `finishers_20261007_p20/` = G4 and V08 on the final build):
- **Primal Surge (Chulane):** every recent cast had decked Chulane, two ways: Surge took every put while draw triggers waited on it (18), and the pilot then cast creature spells whose cast and enter triggers drew the rest (20; lookahead was paused on a prepared card, #1, so no one-move check caught it). Final build: 6 Surge casts in G4 and V08, 6 wins with Thassa's Oracle, 0 deck-outs. Chulane in G4: 0/5 -> 3/5.
- **Approach of the Second Sun (Zur):** Zur's attack search (and any tutor) shuffled the first Approach away from 7th place (17). V08 game 4 on the patch-17-19 build: no searches after the first Approach, second cast won. On the final build Chulane wins that pod first more often, so Zur is 1/5 there again: the table got stronger, not Zur weaker.
- **Enter the Infinite (Yusri):** now cast with the Oracle still in the library and never puts the win card back (17; puzzles). In games it still needs 12 mana or five won flips: 1 cast in V09's 5 games.
- **Ragost and Jarad:** sacrifice costs were paid only with SacMe cards (the Default profile turns Forge's fodder rule off), and Forge plays sacrifice-cost damage or drains only when nearly lethal (19). V03 + V07: Ragost activations 6 -> 14, Jarad 0 -> 2 (and its first win); G4: Ragost 3 -> 11.
- **Still open:** Mystical Tutor's Show and Tell vs Enter the Infinite preference (the user prefers Enter the Infinite unless Show and Tell sets up a play now); Yusri's 2026-10-03 sequencing miss (seed 1000019) should be replayed on the new build.

### 7. Harness hardening

Gaps found 2026-10-04 (FORGE_ISSUES "Harness safety net"): (a) an exception wrapped in the AI's timeout `FutureTask` (`ExecutionException`) got past `SafeControllerAi` and ended the game (#9); `fromSim` now walks causes, so confirm on #9's seed whether it is still a gap; (b) an `OutOfMemoryError` kills the worker's JVM and every remaining game in its queue is recorded as an error at turn 0: restart the JVM and replay those games from their seeds. Also #9's root cause (null-source card state copying a cascaded, copied spell; seed 7320765962232): rare (1 game in about 200), fix in the copier when convenient.
- **Found 2026-10-07: whole-game replays without lookahead are not rare.** 4 of 85 games today (`varied_20261007` 2, `finishers_20261007` 2) and 2 of 30 in `powermatch_20261007_p16` crashed inside lookahead and were replayed from their seed with lookahead off (`sim_fallback`; the reports' header says so, the per-decision count doesn't). All went through lookahead checking a card cast from another effect (`PlayAi.chooseSingleCard` -> `AiController.canPlayFromEffectAI` -> `OnePlaySafetyChecker`), where `SafeControllerAi` doesn't catch: #9 (`CardState.copyFrom` null source, twice), `KeywordInstance.createTraits` copying a token in `GameCopier`, and `MagicStack.getInstanceMatchingSpellAbilityID` in a simulated `onPlayerLost`. Fix: catch on that path too (remake that one decision without lookahead), then root-fix each copier bug.


### 8. Symmetric self-mill and wipe (N6), Araumi encore mana

- `varied_20261007` V04 game 0: Araumi cast its own Singularity Rupture at library 76 (-> 37), then at 28 (-> 8) with its commander and 3 creatures out, wiping its own board, and decked on turn 18 in a 1v1. Earlier: it granted encore to Archon of Cruelty, then spent the encore mana on Singularity Rupture.
- **Fix:** don't cast an effect that mills you below a few turns of draws (unless it wins), weigh your own losses on a symmetric wipe, and hold the encore mana once Araumi's grant resolves.

### 9. Pump abilities in loop detection (N9)

`varied_20261007` V08 game 2: Klauth's Lathliss, Dragon Queen pump counted as a loop at 10 activations and stopped on `goal`. Harmless there, but a goal-stopped play stays off in later turns while the lethal estimate (one chump per creature) holds, and that estimate can be optimistic. Keep pump abilities out of patch 15's detection; a puzzle where pumping past the estimate is needed.

### 10. `fishpond study` command

Automate a bracket study: pods by bracket (or a pod list like `varied_20261007/pods.txt`), chunked under 2 hours, resumable, printing the line for the user to run locally. Per-deck table: wins over decided games, undecided, kills, deaths, how it won. Win attribution uses the single surviving winner (on draws, caps and timeouts Forge marks every seat "has won").

### 11. Re-runs

After 1-9: the whole bracket study at 8 games a pod; a bigger Araumi study (the user, 2026-10-07: Araumi plays correctly now, study it at scale later).

## Pilot policy (as built; design rules)

On by default at every pilot seat (FISHPOND.md "The pilot" has the user-facing description):
- **Tutor policy** (`fishpond/policy.py`, `harness/PilotPolicy.java`): library searches and digs scored by layer: completes a Commander Spellbook combo, survival, engine graph (payoffs the deck is built around, then their enablers), role gap, synergy, playability (AI-flagged cards nearly worthless fetched to hand), Forge's pick as tiebreak. Every decision logs `#FP-POLICY`. Deck overrides (`# priority:`) only where an audit shows the layers miss on purpose.
- **AI fixes by mechanic, not by card:** card-script overrides first (`fishpond/forge_card_overrides/`), Java pilot patches (`-pilot-`) when hints can't express it; each with a puzzle in `fishpond/puzzles/`. Forge's AI never casts an `AI:RemoveDeck:All` card, so an un-flag override is kept only when a puzzle shows the AI then plays it sensibly.

## Backlog (not scheduled)

- **`--sim full` usable** (the user wants it working): share the node budget across top-level options, stop free repeatable abilities (equip {0}) repeating inside the search, cheaper late-game positions (FORGE_ISSUES #5 "Open").
- **Prepared cards crash the lookahead copy (#1):** still paused around, not patched; root-fix in the copier. It matters more than it looked: the pause switched off hybrid's one-move check in Chulane's Primal Surge turns (Studious First-Year enters prepared), which is how the decking casts got through before patch 20.
- **Remaining AI-flagged cards:** known gaps Biorhythm and Words of Worship (puzzles marked `known_gap`); untested flagged cards (`fishpond flags --smoke`); Araumi's other flags (Dakmor Salvage, Lim-Dûl's Vault, Toxic Deluge).
- **Upstream the patches** to Card-Forge/forge (needs the user's go-ahead; `gh` isn't installed).
- **Report:** a headline block (win rate and interval, how it wins and loses, pilot errors beside it with game and turn); combined vacuum + gauntlet report; stranded and cycled columns; combo/line detection (what preceded wins, how often key packages assemble); mana analysis (flood/screw, color-screw); interaction stats (what removal and counters hit).
- **`--variant` at scale:** the code path works but has never answered a real swap question.
- **Gauntlet growth:** tester decks by bracket beyond the user's own lists (e.g. B3 interaction-heavy, B3 fast combo, B2 battlecruiser).
- **Landbase tempo validation logging:** `docs/LANDBASE_TEMPO_PLAN.md` step 3.

## Watch list (seen once, not filed)

- Chulane holding 8 cards with 13-20 mana for several turns (`powermatch_20261005` G4 game 1; hand contents aren't logged, needs a replay).
- Nobody answered Felidar Sovereign at 59 life (`powermatch_20261005` G1 game 1).
- Yusri's game 3 in the G4 pod logs "cast Enter the Infinite" 11 times in one game, on every build (`finishers_20261007_p20/G4...` worker 3): a recursion loop or a log artifact; check once.

## Open questions for the user

- Commander timing (3): which decks should hold their commander (opt-out header)?
