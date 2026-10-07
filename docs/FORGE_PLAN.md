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
- **Before pushing:** `python -m fishpond puzzles` (70: 67 pass, 3 known gaps) and `python tests/smoke.py`. Stage only your own files, fetch/rebase, never force. Write findings into this doc as soon as they're known.
- `--sim hybrid` prints hundreds of "AI failed to play" lines a game (lookahead test-casts unaffordable spells): noise, not a stuck card.

## Where things stand (2026-10-07)

- **Built:** harness and cli engines, goldfish-layout reports with Fishpond's sections, resumable runs, puzzles, `compare`, `flags`. Pilot: tutor policy at every seat, Forge patches 01-20 (crash fixes, big-board blocks, loop shortcut, combat-prediction memo, and pilot patches for cycling, blink, empty-library wins, Wheel, Araumi, City of Traitors, draw-the-library and Approach, Primal Surge, sacrifice fodder, no decking casts), 31 card overrides.
- **Run validity:** the last 80 games (`powermatch_20261007_p16`, `varied_20261007`) had 1 timeout (a Vilis life-payment spiral, item 2), 0 search fallbacks, 0 replays; lookahead pauses on prepared cards (#1) about once per 7 games.
- **Reference runs** (`data/fishpond/`, gitignored): `varied_20261007` (10 pods x 5, every deck 2-3 times, seeds 20261007 + 100 x pod; `pods.txt`, `lane.sh`) is the current baseline; `powermatch_20261007_p16` (6 power-matched pods, seed 1); `pilot_study_20261004` (100 games by bracket, before patches 12-16).
- **Current single-winner record** (varied, 50 games): Heliod 9/15, Niv 5/10, Klauth 5/15, Ragost 5/15, Witherbloom 5/15, Wilson 4/15, Araumi 3/10, Lumra 3/15, Zhulodok 3/10, Erebos 2/10, Omnath 2/15, Xyris 2/10, Yusri 1/10, Zur 1/10, Chulane 0/10, Jarad 0/15. Small samples: signals, not rates.

## Priority list

Ordered by payoff over difficulty (items 5 and 6 done 2026-10-07, worked first at the user's request): run validity first (every later number depends on it), then rules that help every deck, then single decks. Each item gets puzzles first (failing), then the fix, then its acceptance. N-numbers are the failure IDs used in earlier write-ups and commits.

| # | Item | Difficulty | Payoff |
|---|---|---|---|
| 1 | Combat-prediction memo on lookahead copies (N8) | Low-medium: one patch, diagnosed | High: slow turns, AI timeouts, every big board |
| 2 | Life budget (N4, Yusri coin buffer) | Medium: one rule over optional life payments | High: self-kills in Niv, Erebos, Yusri; the last timeout |
| 3 | Commander timing, with cumulative upkeep (5c, N7) | Medium: policy rule + opt-out header | Very high: every deck, about a turn of tempo |
| 4 | Commander combat safety | Medium: attack/block patch + 6 puzzles | High: every deck's commander |
| 5 | **Done 2026-10-07** (patches 17, 18, 20) Finisher misses (Primal Surge, Enter the Infinite, Approach) | Medium-high: one fix each | Medium: Chulane 0/10, Yusri 1/10, Zur 1/10 |
| 6 | **Done 2026-10-07** (patch 19) Sacrifice-cost damage and drains (N10: Jarad, Ragost) | Medium | Medium-high: two decks' whole engine |
| 7 | Harness hardening | Medium | Medium: protects the big re-runs |
| 8 | Symmetric self-mill and wipe (N6) + Araumi encore mana | Low-medium | Low-medium: Araumi, any self-mill deck |
| 9 | Pump abilities in loop detection (N9) | Low | Low: a guard |
| 10 | `fishpond study` command | Medium (tooling) | Makes 11 cheap and repeatable |
| 11 | Re-run: whole study at 8 games a pod; bigger Araumi study | Run time | Measures 1-9 |

### 1. Combat-prediction memo on lookahead copies (N8)

- **Problem:** turns of 10-12 minutes on big boards, with AI decisions hitting the 120 s limit (results then depend on machine load). `varied_20261007` V04 game 3 (a Chulane turn, 618 s) and V05 game 4 (Lumra's Ashaya/landfall turn 33: 684 s even replayed alone, 2 AI timeouts; replays line for line).
- **Cause (JFR, V05 game 4, plan `logs/plan_s1_4.tsv` line 0, seed 20261567784525):** 76% of samples under `OnePlaySafetyChecker.isAcceptable`, 66% in `predictNextCombatsRemainingLife0` (the uncached body). Patch 16's memo is keyed on the `Game` object; hybrid builds a new `GameSimulator` (a fresh copy) per candidate play, rescores the unchanged board (38% of misses) and scores the post-play board (37%), so the memo never hits on copies.
- **Fix:** key the memo on board contents within a match instead of the `Game` object (copies keep card ids; the key must cover everything the prediction reads), so the unchanged board is predicted once per decision and plays that change no creature reuse it. Smaller fallback: cache the original-board score per decision in `OnePlaySafetyChecker`.
- **Acceptance:** that replay's turn 33 well under a minute with the same game result; puzzles green; V04 and V05 pods re-run with no AI timeouts.

### 2. Life budget (N4, with the Yusri coin buffer)

- **Problem:** the AI pays optional life into a lethal board. Niv 22 -> 12 via Bolas's Citadel, Vampiric Tutor, Sensei's Top, then died to 19 (`powermatch_20261005` G1 game 4); Erebos paid Vilis, Broker of Blood 13 times (24 -> 4, a 36-card hand; the last timeout, `powermatch_20261007_p16` G2 game 4); Yusri dealt itself 22 with its own flips and died (`varied_20261007` V09 game 2); Erebos paid 8 for draws and died to exactly 20 (V03 game 4). Tainted Sigil cracked on an opponent's turn when "life lost this turn" was near zero.
- **Fix:** one rule for every optional life payment (Citadel, Erebos, Vilis, Ad Nauseam, shocklands, Yusri's flips): budget = life minus the biggest attack the table can make before your next turn (the existing danger checks); never pay past it. Tainted Sigil only in the turn the life was lost. Yusri's coin count (the user, 2026-10-03): 5 unless 2 x (flips lost in the worst case) >= life, i.e. keep a buffer of 1 (at 11 life flip 5, at 10 fewer); Krark's Thumb doesn't change the worst case.
- **Acceptance:** puzzle `vilis_life_payments` (known gap) passes; new puzzles for Citadel into a lethal board and Yusri at 10 life; replays of the evidence games.

### 3. Commander timing (5c), with cumulative upkeep (N7)

- **Problem:** the AI spends mana on other spells and casts the commander late. Klauth had a median of 8 mana on turn 4 yet was out by turn 4 in 0% of its seat-1 games and by turn 5 in 25% (pilot study); Niv first cast on turns 5-10 with 9-23 mana up; Wilson late on 3-5. Forge runs about a turn behind goldfish on commanders. N7: Yusri paid Mystic Remora's cumulative upkeep for 5 turns (1+2+3+4+5 = 15 mana on 3-5 lands) and never cast its 3-mana commander in 9 turns (`varied_20261007` V09 game 4).
- **Fix (the user, 2026-10-04):** cast the commander as soon as it's affordable unless something more urgent (the survival layer) is in hand; a general policy rule. Cumulative upkeep is paid only while it leaves the mana the turn's plan needs (the commander first).
- **Exceptions, carefully:** some commanders are worse early or help the table (the user's example: Grothama, whose leave-the-battlefield draw rewards opponents who damaged it); some decks hold the commander for a protected or combo turn. List those patterns, add a deck-header opt-out (e.g. `# commander: hold`), and ask the user about every deck the heuristics flag.
- **Acceptance:** commander-out-by-turn and win rate before and after on the same seeds for every deck in `decks/`; no deck worse without an explanation; Klauth and Wilson puzzles on curve; a Mystic Remora puzzle.

### 4. Commander combat safety

The user's rules (2026-10-04), a pilot patch in `AiAttackController` / `AiBlockController`, for every pilot seat's commander:
- **Attack** only into a player whose untapped potential blockers can't kill it (first strike, deathtouch, visible pump or removal count). If every opponent can kill it, it stays home. Indestructible, protection and similar count as survivable.
- **Block** only an attacker that won't kill it, unless the unblocked damage would be lethal to its controller (life or commander damage); then block as Forge would.
- **Exception, attack triggers:** skip the attack safeguard for a commander whose attack trigger gets value now (Yusri's flips, Zur's fetch, Klauth's mana; read from its `Attacks` triggers). It still swings at the least problematic opponent (check Forge's defender choice) and stays home if attacking leaves its controller dead on the swing back. Blocking rules have no exception. Chulane isn't one.
- **Also:** find why `AiAttackController` kept Zur (21% of turns) and Chulane (5%) home in the pilot study.
- **Puzzles:** three boards that can kill it (stays home); one safe opponent (attacks that one); blocks the small attacker, not the lethal one; must chump because unblocked is lethal; Zur attacks into risk for a fetch; Zur stays home when the swing back kills its controller.

### 5 and 6. Done 2026-10-07: finishers, sacrifice-cost engines (patches 17-20)

What each patch does is in FORGE_ISSUES "Patches" and FISHPOND.md "The pilot"; puzzles 67/67 (3 known gaps). Re-runs on the varied seeds (`data/fishpond/finishers_20261007/`, V03, V07, V08, V09 and the power-matched G4 at seed 1; `finishers_20261007_p20/` = G4 and V08 on the final build):
- **Primal Surge (Chulane):** every recent cast had decked Chulane, two ways: Surge took every put while draw triggers waited on it (18), and the pilot then cast creature spells whose cast and enter triggers drew the rest (20; lookahead was paused on a prepared card, #1, so no one-move check caught it). Final build: 6 Surge casts in G4 and V08, 6 wins with Thassa's Oracle, 0 deck-outs. Chulane in G4: 0/5 -> 3/5.
- **Approach of the Second Sun (Zur):** Zur's attack search (and any tutor) shuffled the first Approach away from 7th place (17). V08 game 4 on the patch-17-19 build: no searches after the first Approach, second cast won. On the final build Chulane wins that pod first more often, so Zur is 1/5 there again: the table got stronger, not Zur weaker.
- **Enter the Infinite (Yusri):** now cast with the Oracle still in the library and never puts the win card back (17; puzzles). In games it still needs 12 mana or five won flips: 1 cast in V09's 5 games.
- **Ragost and Jarad:** sacrifice costs were paid only with SacMe cards (the Default profile turns Forge's fodder rule off), and Forge plays sacrifice-cost damage or drains only when nearly lethal (19). V03 + V07: Ragost activations 6 -> 14, Jarad 0 -> 2 (and its first win); G4: Ragost 3 -> 11.
- **Still open:** Mystical Tutor's Show and Tell vs Enter the Infinite preference (the user prefers Enter the Infinite unless Show and Tell sets up a play now); Yusri's 2026-10-03 sequencing miss (seed 1000019) should be replayed on the new build.

### 7. Harness hardening

Gaps found 2026-10-04 (FORGE_ISSUES "Harness safety net"): (a) an exception wrapped in the AI's timeout `FutureTask` (`ExecutionException`) got past `SafeControllerAi` and ended the game (#9); `fromSim` now walks causes, so confirm on #9's seed whether it is still a gap; (b) an `OutOfMemoryError` kills the worker's JVM and every remaining game in its queue is recorded as an error at turn 0: restart the JVM and replay those games from their seeds. Also #9's root cause (null-source card state copying a cascaded, copied spell; seed 7320765962232): rare (1 game in about 200), fix in the copier when convenient.

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
