# FORGE PLAN: Fishpond's working plan

Working doc for Claude: where Fishpond stands, what is open, and in what order. Usage is in `docs/FISHPOND.md`; every Forge bug,
patch and card override is in `docs/FORGE_ISSUES.md`. Finished work and old run write-ups live in git history, not here: this doc
before the 2026-10-30 prune (`git show 9d60724:docs/FORGE_PLAN.md`) holds every study from 2026-10-07 to 2026-10-28, the dummy
study's D1-D9, the priority list 1-11 and their measurements; before 2026-10-07, the original build plan. Keep it short: when an
item is done, move its numbers into the commit and FORGE_ISSUES and delete it here.

## Standing rules (the user's)

- **Governance (2026-10-01).** No change to the engine choice or the overall architecture without a written case, a cheap test with evidence, and the user's go-ahead. Check whether an existing tool already does something before building it. Iteration inside the plan is fine.
- **Forge is the simulator.** goldfish.py is frozen (no new engine features), kept as a fast cross-check. Forge is downloaded at run time, never vendored.
- **Pods are always 4 players at 40 life.** Each opponent seat is a dummy or a real deck; never simplify to fewer seats or to dummies only when real opponents were asked for.
- **Pilot logic is symmetric and general.** Every pilot rule applies to every pilot seat, never the hero alone; prefer policy-level rules over per-card fixes, with explicit opt-outs; ask about exceptions instead of guessing. `--pilot-seats you` is an A/B switch only.
- **Fix Forge bugs at the root.** A search fallback, replay or pause is a bug to fix with a patch and an evidence seed in FORGE_ISSUES, not a count to live with. `--sim full` must work.
- **Pilot-error losses are shown beside the headline win rate,** never excluded, with the game and turn of each (so it can be replayed by seed).
- **Upstream:** nothing goes to Card-Forge/forge without the user's go-ahead on the exact diff (they submit under their account; disclose that Claude helped). Not on the backlog (the user, 2026-10-30): if it happens,
  it's one substantial batch once the work settles, not a stream of contributions.
- **New decks get a trial first (2026-10-30).** A deck new to the lineup plays a small group of pods to see how it plays before it joins the gauntlet or a round-robin. Claudes Baral Control stays out of the lineup for now.

## How to work here (Windows box)

- Repo is local (`C:\Users\ianfr\Desktop\mtg-data`); use `python -m fishpond`. 20 CPUs, 32 GB. Java: a 32-bit Java 8 is first on PATH; fishpond picks JDK 25 itself (`%LOCALAPPDATA%\Programs\Eclipse Adoptium\jdk-25*`), but anything run by hand (ForgeRunner, `jfr`) must use JDK 25.
- **Before a run:** `git fetch` and compare with origin/main (other sessions push to this tree); print the `--out` folder and make sure it doesn't exist (`run` refuses one with results). Two 5-game pods at a time with `--jobs 5` each is a good load: hybrid games take 1-10 min, 50 games about 50 minutes.
- **Claude's background tasks die at 2 hours.** Split batches into resumable chunks under that (`run --resume` finishes a cut-off pod), or hand the user the command for long studies (the user's preference as runs grow).
- **Seeds replay exactly.** One game replays alone from one line of a run's `logs/plan_*.tsv` with ForgeRunner (the command line is in `runner.execute`; `fishpond replay POD GAME` does it for a study pod); the game log is printed only when the game ends. Profile with `-XX:StartFlightRecording=...,settings=profile` and dump mid-turn with `jcmd <pid> JFR.dump`; add `-XX:FlightRecorderOptions:stackdepth=2048` and read it with `jfr print --stack-depth 2048` (the defaults, 64 and 5 frames, hide which caller is slow). Time an A/B as a pair run side by side: load alone changes a big game's time 1.5-2x, and past about 6 busy JVMs a 90 s decision can cross the 120 s AI limit and change the game. A patch that changes play makes games diverge from older runs on the same seed: compare distributions, not paired games, across it.
- **Writing a patch:** `~/forge-cache/forge-src-2.0.15` is CRLF and doesn't match the tag; fetch the files with `forge.FORGE_SRC_URL` into a scratch git repo, apply 01..NN, edit, `git diff` > the next patch; procedure and table in FORGE_ISSUES "Patches". To see a debug println, call `fishpond.puzzles.run_one(path)` and grep its lines. Before a Forge perf or crash patch from scratch, check Manabrew's fork (github.com/witchesofthehill/forge, branch `manabrew`) for new commits.
- **Before pushing:** `python -m fishpond check` (the checks the branch's changes need; FISHPOND.md "Before a push"), and the full suite (`fishpond check --full`: 361 puzzles, 356 pass, 5 known gaps on patches 01-123) before a long study. Stage only your own files, fetch/rebase, never force. Write findings into this doc as soon as they're known.
- `--sim hybrid` prints hundreds of "AI failed to play" lines a game (lookahead test-casts unaffordable spells): noise, not a stuck card.
- **Why did the AI not cast X?** Replay the game with a debug copy of one class first on the classpath: copy the file from the scratch source tree (or `forge-src-2.0.15` if no patch touches it), add a println, `javac -cp <patched classes>;<forge jar>` into a folder, prepend that folder to `-cp`. Nothing in the repo changes. `AiController.canPlayAndPayFor` printing its `AiPlayDecision` per spell and `OnePlaySafetyChecker.isAcceptable` printing scores is the usual start.
- **After a study:** `fishpond pilot STUDY_DIR` (the pilot-failure table, per 100 seat-games; `--vs OLD_DIR` for before/after), `fishpond lines` (win lines), `fishpond held` (dead cards), and the study's `index.html` for reading games.

## Where things stand (2026-10-30)

- **Build:** Forge 2.0.15 + patches 01-125 (crash fixes, speed, and the pilot), 93 card overrides, 369 puzzles. The pilot, at every
  pilot seat: the tutor policy (`policy.py`, `PilotPolicy.java`), the turn plan (patch 64 on, with the commander in the plan,
  patch 112), the threat model (counters, removal, wipes and holding mana, `ThreatModel.java`), mulligans by hand score, loop
  shortcuts and jumps, library reserves. Each patch's why and evidence is its FORGE_ISSUES row.
- **Last measured at scale:** `pilot_20261028c` (01-116; the round-robin's 20 pods x 18 games, 360 games, 356 natural, 0 AI
  timeouts, 0 lookahead fallbacks). Against the same pods and seeds on 01-111, per 100 seat-games: commander affordable and left
  out of the plan 19.0 (39.0), engines available and not played 1.5 (3.9), decked itself 0.8 (1.2), killed itself 0.5 (0.9),
  removal held then killed by its target's owner 0.8 (1.4). Not moved: castable cards held 3+ turns 43.7 (41.5), missed land
  drops on turns 1-4 7.0% (6.9%), loops stopped 3.5 (3.0), commander never resolved 18.1 (20.1; mostly early deaths and removal,
  not the pilot).
- **Since, not yet measured at scale:** 117 (attack-trigger commander attacks only with an affordable recast), 118 (failed casts
  return to their zone), 119 (Sphinx's Approach pays its exile-five), 120 (per-game state: the tutored top card and combo step
  count leaked from game to game inside a worker JVM, so every multi-game study before it could be touched), 121-123 (Manabrew
  ports: -24% game time on six same-seed replays, identical play), 124 (the decking guard counts reveals, searched-in
  entries and the round ahead, and runs on the turn plan's forced casts: Baral decked in 15 of 50), 125 (Jace and Laboratory Maniac are closers
  near the library's end: the plan held Jace in 39 of 150 games).
- **Measurement fix (2026-10-30):** held cards under a spell limit (Zur's Rule of Law) no longer read as idle mana in the
  dead-card meter or `#FP-SEQ` (10 of 12 streaks in one sample game were false). Idle counts from earlier runs, including
  `pilot_20261028c`'s "castable cards held 3+ turns", run high in any pod with Zur; compare them with care.
- **Next:** the baseline on 01-123 (the user runs it; the round-robin, `fishpond/pods/roundrobin16.txt`), read with `fishpond
  pilot --vs pilot_20261028c`. It also answers whether decisions still cross the 120 s AI limit (open question below).
- **Direction (the user, 2026-10-30):** most decks play reasonably now; pilot tuning winds down and the focus moves to tools the
  user runs through the simulator, starting with the swap-list tester (Backlog). Pilot fixes from here are for failures the baseline
  measures, not new tuning.
- **Reference runs** (`data/fishpond/` on the Windows box, gitignored): `trends_20261027` (the round-robin, 01-106, 80 games),
  `pilot_20261028` + `pilot_20261028b` (01-111, 500 games), `pilot_20261028c` (01-116, 360 games), `bracket1000_20261021` (its
  slowest games are the speed replays), `study150_20261014*` (the win-line runs).

## Open: pilot failures still measured

From `pilot_20261028c` and the miss reviews; each is a candidate only if the 01-123 baseline still shows it.
- **Castable cards held 3+ turns with mana idle** (43.7 per 100 seat-games, flat). Mostly cards Forge has no good moment for:
  Perpetual Timepiece (flagged; needs logic for its exile-and-shuffle ability), Shadowborn Apostle (Erebos casts one at a time
  instead of building to six), Diplomatic Immunity, Regrowth and Soul's Majesty (Omnath), Wander in Death (Zur), Toxic Deluge and
  Black Sun's Zenith (Witherbloom). Some holds are right; Apostles and the modal spells look like AI gaps. The user (2026-10-30):
  chase out every dead card eventually; not started (start from the baseline's `fishpond pilot` and `held` lists).
- **Missed land drops on turns 1-4** (7%, flat after the free-mulligan rule): the seats that sent a 2-land seven back won no more
  often than 2-land keeps did. Monitor (the user, 2026-10-30): could be no land in hand, or luck, as much as land counts.
- **Loops stopped as stalled or at the goal** (3.5): Sprout Swarm and Walking Ballista mostly.
- **Lines with real misses:** Niv's Citadel (6 of 16 available), Zur's Approach (8 of 31).
- **Removal against noncreature engines** (Flaming Fist, Krark's Thumb, Lightning Greaves, Astral Drift held against all game):
  measured cost weak (the target's controller won 29% vs a 25% base rate). The removal floor is the user's design; the idea if it
  grows: judge an attachment by its host's value against the creature floor, and give engines a fixed place above the
  noncreature floor. Monitor (the user, 2026-10-30).
- **The free hold in decks not built to counter** (Wilson's Mana Tithe, Heliod's Rebuff the Wicked): 5 clear misses in 80 games.
  If it grows, a 5+ counter-role gate in `ThreatModel.freeHold` leaves Zur and Yusri as they are.
- **Logging noise:** `#FP-DIG` prints at every priority (2,458 "none" lines in 500 games); print only real digs.

## Open: engine and harness

- **Decisions over Forge's 120 s AI limit on the biggest boards** (Heliod/Xyris/Lumra/Zur boards): all in the block planner's
  pair and gang search (`makeGangBlocks`, `reinforceBlockersToKill`, `makeGoodBlocks`) under `notNeededAsBlockers` and
  `choosePreferredDefenderPlayer`. A timed-out decision is a pass, and whether it times out depends on machine load. Options, all
  changing play: (a) tighter patch-11 caps for predicted combats only (`maxBlockPairs` 400, `maxReleaseSteps` 12 today), the real
  block declaration left exact; (b) no gang blocks in predictions past a board size; (c) on a timeout, remake the decision without
  lookahead instead of passing; (d) leave it; (e) raise the AI limit and let the sim take what it needs. The user (2026-10-30):
  leans to (e), decided on the 01-123 baseline's count.
- **Held back from Manabrew's fork:** d7334e07b374, caching the CR 613 dependency order between static-ability passes (65% of
  `checkStaticAbilities` on its wide boards). It keys on every Tracker view change and reuses the real pass's order for the AI's
  LKI passes, a small approximation. Profile a big board on 01-123 first; port it only if dependency ordering is still hot, then
  check it on same-seed replays like 121. Not ported on purpose: its token-flood draw caps, per-game AiCache, AI eval deadlines
  and combat budgets (they change play), concurrency patches.
- **Harness gaps** (FORGE_ISSUES "Harness safety net"; there too, 2026-10-30: the meters' `canPayManaCost` calls at cleanup
  have side effects the games depend on, so a meter change must replay identically before it's pushed):
  - an exception wrapped in the AI's timeout `FutureTask` (`ExecutionException`) used to get past `SafeControllerAi` (#9);
    `fromSim` walks causes now: confirm on #9's seed (7320765962232) that it's closed;
  - a crash inside the AI's own eval task in `AiController.chooseSpellAbilityToPlayFromList` is caught by `AiController` and the
    seat passes that priority, uncounted (seen once: `CopyPermanentEffect.getProtoType` NPE inside the one-move check);
  - after an AI timeout the eval thread keeps running (JDK 20+ has no `Thread.stop`), reading the live game while the next
    decision runs: CPU and a determinism risk. Count and log leftover threads first, then have the eval loop check for
    interruption.
- **Copier bugs still open:** prepared cards crash the lookahead copy (#1; lookahead pauses around them, which also switched off
  hybrid's one-move check in Chulane's Primal Surge turns); #9 (null-source card state copying a cascaded, copied spell, about 1
  game in 200); a token copying a token (counted fallback).

## Pilot policy (as built; design rules)

On by default at every pilot seat (FISHPOND.md "The pilot" has the user-facing description):
- **Tutor policy** (`fishpond/policy.py`, `harness/PilotPolicy.java`): library searches and digs scored by layer: completes a Commander Spellbook combo, survival, engine graph (payoffs the deck is built around, then their enablers), role gap, synergy, playability (AI-flagged cards nearly worthless fetched to hand), Forge's pick as tiebreak. A pick that completes a combo skips the commander gate (2026-10-21); a damage lock (Solitary Confinement: prevent all damage to you) outranks key engines when the table's creatures are set to kill (survival 1300 at full danger, 2026-10-22). Every decision logs `#FP-POLICY`. Deck overrides (`# priority:`) only where an audit shows the layers miss on purpose.
- **Repeatable engines and holding up answers** (2026-10-23, `harness/PilotPolicy.java`, `harness/ThreatModel.java`): loops from the deck's `# loop:` lines and from card text (`#FP-LOOPS`); a tutor pick that completes one scores like a combo, casting a missing piece adds to the turn plan. Once a loop runs, a second loop counts a ninth, engine and synergy a quarter, answer roles double; a tutor creature is worth its best findable pick (80%); removal counts only by what it can hit (a real threat in reach most); a phase-out-all card counts as a wipe. Free hold: a seat with a counterspell in hand (or a counter ability out, Glen Elendra) whose held mana has an instant-speed use (cycling, typecycling, non-sorcery activations, other instants) keeps that mana up through the opponents' turns and spends the rest at the last end step before its turn (`#FP-HOLD` why `free`). The free hold steps aside on a turn the seat can cast its commander, a key card, a 6+ spell or removal that reaches a real threat. A commander whose own attack or upkeep trigger searches the library is a tutor every turn: +700 turn-plan value while it waits in the command zone.
- **The commander** (patches 24, 112-117, the user's rules): cast as soon as affordable unless the seat's life is in danger (+1000 in the turn plan for the first cast only; a recast keeps its diminishing value, "mission critical once, and diminishes from there"); a commander buff counts only a commander on the battlefield; an attack-trigger commander attacks unless it's a needed blocker and the seat is in danger, and into a killer only with an affordable recast.
- **AI fixes by mechanic, not by card:** card-script overrides first (`fishpond/forge_card_overrides/`), Java pilot patches (`-pilot-`) when hints can't express it; each with a puzzle in `fishpond/puzzles/`. Forge's AI never casts an `AI:RemoveDeck:All` card, so an un-flag override is kept only when a puzzle shows the AI then plays it sensibly.

## Backlog (not scheduled; tools for the user first)

- **Swap-list tester** (next focus, after the 01-123 baseline; the user's design, 2026-10-30). Not one card against one card:
  "test combinations of swaps from this cut list and this add list over ~1500 games and give me the data". The user reworks
  more than tinkers: lists of 5-20 cuts and 5-20 adds, no card-to-card pairing, a build is the list minus k cuts plus k adds
  (100 cards). "Works best" is the user's call per question, so the output is every metric, sortable, not one score.
  - **Funnel:** (1) goldfish screen: Fishpond against 3 dummies (real rules; not goldfish.py), each game a random mix with each
    flex card in about half the games, so every card's effect on every metric is estimated over all games (a factorial design;
    an even split of 1500 games over 100+ combinations would leave each one ±12 points of noise); (2) the user picks 2-4 builds,
    and anything that drags in the goldfish stops there; (3) those builds and the current list against a blend of real pods,
    large samples each: win rate with interval, win routes, deaths, `fishpond pilot` per build.
  - **Guards:** interaction (removal, counters, wipes: Scryfall role tags) can't be judged against dummies: tagged and kept out
    of the goldfish verdict, judged at stage 3. Reworks change plans, and random half-mixes play hybrids nobody would build: a
    rework's core is locked in (only the flex slots vary), and the old list and the full rework always run as their own builds.
  - **Metrics (per build, and per card in vs out):** goldfish kill turn, commander turn, key cards' first seen and cast turns;
    mulligans and keep size, missed land drops, usable mana by turn, color misses, flood and screw; cards drawn and cast per turn,
    lines reached and played, tutor finds; each card's cast rate, turns held while castable, idle mana, never cast. Per-card
    goldfish win-rate effects are near noise even at 1500 games: the per-card signal is speed, mana and dead-card metrics; win
    rate compares whole builds at stage 3.
  - **Output:** an HTML page like the study index, builds and cards sortable by any metric, with intervals.
  - **Land count stays fixed** (the user, 2026-10-30): a build swaps lands for lands; mana bases are the next tool's job.
  - **Open:** how locked cards are marked (a `# lock:` list header or a flag). The existing `--variant` (named builds on the
    same seeds and pods) is the stage-3 path; it has never answered a real question yet.
- **Mana-base optimizer** (after the swap-list tester; the user, 2026-10-30): the same process over the land section, a
  separate tool, using what the other tools measure (landbase.py, manasim.py, the swap tester's mana metrics).
- **Report:** a headline block (win rate and interval, how it wins and loses, pilot errors beside it with game and turn); combined
  vacuum + gauntlet report; stranded and cycled columns; mana analysis (flood/screw, color-screw); interaction stats (what removal
  and counters hit).
- **Gauntlet growth:** more decks by bracket beyond the user's own lists (e.g. B3 interaction-heavy, B3 fast combo, B2
  battlecruiser), each through a trial pod first. The round-robin's structure (an affine plane of order 4) needs exactly 16
  decks: a broader lineup needs a new design (order 5 takes 25 decks in 5-deck groups, so not a direct fit for 4-seat pods).
- **`--sim full` usable** (the user wants it working): share the node budget across top-level options, stop free repeatable
  abilities (equip {0}) repeating inside the search, cheaper late-game positions (FORGE_ISSUES #5 "Open").
- **Remaining AI-flagged cards:** known gap Biorhythm (puzzle marked `known_gap`); untested flagged cards (`fishpond flags
  --smoke`); Araumi's other flags (Dakmor Salvage, Lim-Dûl's Vault, Toxic Deluge).
- **Landbase tempo validation logging:** `docs/LANDBASE_TEMPO_PLAN.md` step 3.

## Watch list (seen once, not filed)

- Firebreathing stops short: Shivan Dragon with 14 Mountains against 18 life pumped 11 times (16 damage) and kept 3 mana (puzzle `pump_not_loop_firebreathing`, stock Forge and patched alike): PumpAi's stopping rule.
- Return of the Wildspeaker: with a 9-power creature and 5 cards left the AI picks the pump mode or doesn't cast it (vacuum, 3 seeds); Klauth decked once off its draw (`dummy25_20261007` g14, 35 cards left), not reproduced.
- Hybrid's one-move check often returns "could not simulate" and lets the play through (Spirit Mantle, Heliod's Pilgrim): worth a count.
- Nobody answered Felidar Sovereign at 59 life (`powermatch_20261005` G1 game 1).
- Yusri's game 3 in the G4 pod logs "cast Enter the Infinite" 11 times in one game, on every build (`finishers_20261007_p20/G4...` worker 3): a recursion loop or a log artifact; check once.
- JVM crash in a G1 GC thread (once, 2026-10-12; FORGE_ISSUES "Harness safety net"): not ours; watch for a repeat.

## Open questions for the user

- **Big-board decisions over 120 s:** options (a)-(e) above (the user leans to raising the limit), decided after the 01-123
  baseline counts AI timeouts.
- **Gauntlet beyond 16 decks:** when new decks pass their trial, a round-robin of more than 16 needs a different pod design (or
  two 16-deck lineups). Which decks are in is the user's call.
