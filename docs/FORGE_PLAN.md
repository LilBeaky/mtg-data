# FORGE PLAN: Fishpond, the Forge-backed simulator for mtg-data

Working doc for Claude (chat or Claude Code) implementing this. Not user-facing (that's `docs/FISHPOND.md`). Update the Status table as work lands. Written 2026-10-01.

**Name and layout (user, 2026-10-01):** the tool is **Fishpond**, a folder `fishpond/` run as `python3 -m fishpond`. The `forge_setup.py` / `forge_deck.py` / `forge_sim.py` names below are the original plan; the "Architecture" section maps them to the real files.

## Start here (fresh session, no prior chat context needed)

This doc is self-contained. Everything learned in the feasibility chat is below; don't ask the user to re-explain it.

1. Clone the repo and read `docs/USE_INSTRUCTIONS.md` once (it's the general workflow), then this file. You don't need GOLDFISH.md, GOLDFISH_ROADMAP.md, UPGRADE_PLAN.md or the TRANSLATION_* docs; they describe the frozen legacy path. Read `scripts/goldfish.py` lines ~6000–6320 (stats + report printers) only when you do the `sim_report.py` extraction.
2. Set up the environment exactly as in "Environment recipe" below.
3. Check the Status table, then work **"Pilot study 2026-10-04" → "Priority order (difficulty vs payoff, 2026-10-05)"** top down (that's the active plan; the 2026-10-01 Roadmap below is kept for its open leftovers). Phases A/B, pilot policy and patches 01-11 are built. Acceptance runs use `tests/forge/chulane.txt` (the user's Chulane list, 100 cards, B3, plan Primal Surge, keys Shrieking Drake / Primal Surge / Thassa's Oracle).
4. Push straight to main, one commit per step; run `python3 tests/smoke.py` before each push. The GitHub token is in the project instructions, not in the repo. Never commit it. (A Claude Code session pinned to a branch pushes there instead; the user merges.)

### Environment recipe (all verified 2026-10-01 in the chat sandbox unless marked untested)

Now automated: `python3 -m fishpond setup [--jdk]` downloads and unpacks the pinned release into `~/forge-cache/<ver>/` (override with `FISHPOND_CACHE`), indexes the card scripts, and reports Java/javac. The manual recipe below is kept for reference. Corrections found while building (2026-10-01, Claude Code container, 4 CPUs / 16 GB):
- The JVM must run with **cwd = the Forge install dir**: Forge reads `res/` relative to the working directory (from elsewhere it crashes on the missing language bundle).
- `sim -D <absolute dir>/` loads decks by file name (`-d hero.dck ...`) in Commander too, so runs keep their `.dck` files in the run folder instead of `~/.forge/decks/commander/`.
- The mono-W dummy (Isamaru, Hound of Konda + 99 Wastes) **verified**: it loads and never casts or attacks (checked in every run).
- Real-deck opponents **verified**; Forge's sim does **not** enforce 100 cards (the user's Klauth list has 101 and plays).

```bash
# Forge (pinned). ~1 min download, ~600 MB unpacked; outside the repo.
mkdir -p ~/forge && cd ~/forge
curl -sL https://github.com/Card-Forge/forge/releases/download/forge-2.0.15/forge-installer-2.0.15.tar.bz2 -o f.tbz && tar -xjf f.tbz && rm f.tbz
# JDK only for Phase B (javac); the runtime is preinstalled
apt-get update -q && apt-get install -y -q openjdk-21-jdk-headless
# Decks must live here and be referenced by deck *name* (Name= in [metadata]), not by path
mkdir -p ~/.forge/decks/commander
# Run (the stdout game log is the data; don't use -q)
java -Xmx3500m -Djava.awt.headless=true -Dfile.encoding=UTF-8 -jar ~/forge/forge-gui-desktop-2.0.15-jar-with-dependencies.jar \
  sim -d Hero Opp1 Opp2 Opp3 -f commander -n N -s SEED -c CLOCK_SECONDS > run.log 2>&1
```
- The sandbox has 1 CPU and ~4 GB RAM. ~15 s of startup per JVM. Forge also writes `~/.forge/forge.log`.
- The hero is whichever deck is listed first; in the log it appears as `Ai(1)-<Name>`.
- The `.dck` written for the test: `[metadata]` / `Name=Chulane` / `[Commander]` / `1 Chulane, Teller of Tales` / `[Main]` / the other 99 lines as `1 Card Name` (basics as `12 Forest`). Forge loaded the Chulane list as written (the DFC "Studious First-Year" was written as its front name).
- Dummy actually tested: `Kozilek, Butcher of Truth` + 99 Wastes. Bad choice (castable on turn 10). The planned replacement (mono-W legendary + 99 Wastes) is **untested**: verify it loads and never casts.
- **Untested:** real-deck opponents; deck names with spaces in `-d` (quote them, or use slug names); whether Forge enforces 100-card/color-identity legality in sim; per-game wall time in 4p pods.

### Governance (the user's standing rule, 2026-10-01)

The user is tired of structural rewrites of the simulator. No change to the engine choice or the overall architecture without (1) a written case, (2) a cheap test with evidence, and (3) the user's go-ahead. Before building any new capability, check first whether an existing tool already does it. Iteration inside this plan (parsers, reports, harness) is fine.

## Why

The user's goal: analyze decks *while they build them*. The tool must read and play **any** deck mechanically; the pilot may be imperfect. The goldfish engine can't get there: ~44% of the pool fully read, every mechanic hand-built, and GEF only moves the problem into "build the engine feature". Forge is a mature GPL-3.0 rules engine with ~34k card scripts and a headless sim mode. Decision (user, 2026-10-01): **Forge is the primary simulator.** The user expects to rarely use goldfish.py. What he wants to keep is **goldfish's report format**, plus the new data in Phase D.

- goldfish.py is **frozen** (legacy). No new engine features, no GEF work, no parser work. It stays in the repo, still working and still in smoke, as a fast cross-check and for quick "what-if" ladders. Don't delete it unless the user asks.
- Mark GEF/T3 and the goldfish parser roadmap frozen in GOLDFISH_ROADMAP.md and UPGRADE_PLAN.md when Phase A lands.
- **Report layer = goldfish's layout.** Extract goldfish's stats/report code (`pct`, `q`, `mean`, `by_turn`, `summary`, `print_report`, `print_combat`, and the variant side-by-side) into `scripts/sim_report.py`; goldfish imports it back unchanged, so its output stays byte-identical (check with smoke plus a diff of a seeded run before/after). forge_sim.py fills the same `res` bundle (`rec[metric][turn]` lists, `cmd_first`, `first`, `finals` with `deaths`/`won`/`how`, `attr`, `tut`, `trigs`, `dsrc`, `kept`, `mulliganed`, ...) from Forge data, then appends its new sections. A metric Forge computes differently from goldfish keeps its row but gets a `≈` marker and a footnote; a metric Forge can't produce is omitted, never faked.

## Verified facts (sandbox, 2026-10-01)

- Release: `https://github.com/Card-Forge/forge/releases/download/forge-2.0.15/forge-installer-2.0.15.tar.bz2` (297 MB; ~1 min download; github release assets are reachable from the chat sandbox). Get the URL from `api.github.com/repos/Card-Forge/forge/releases/latest`; pin a version, don't float.
- Unpacked: `forge-gui-desktop-2.0.15-jar-with-dependencies.jar` + `res/` (card scripts in `res/cardsfolder/cardsfolder.zip`, 34,010 files). Nothing to build.
- Runtime: Java 21 is preinstalled. `javac` is not: `apt-get update && apt-get install -y openjdk-21-jdk-headless` works (run `update` first or the install 404s). Maven Central is blocked; never plan on building Forge from source.
- Run: `java -Xmx3500m -Djava.awt.headless=true -Dfile.encoding=UTF-8 -jar <jar> sim -d A B [C D] -f commander -n N -s SEED -c CLOCK [-a PROFILE...] [-q]`
  - Decks are looked up by name in `~/.forge/decks/commander/` (a file path is rejected for commander format). Copy `.dck` files there.
  - `-s` RNG seed, `-c` clock in seconds before the match is called a draw (default 120), `-a` AI profiles per player: `Default`, `Cautious`, `Experimental`, `Reckless` (`res/ai/*.ai`).
- `.dck` format: `[metadata]\nName=X\n[Commander]\n1 Card\n[Main]\n1 Card...`
- Speed: 1 sandbox CPU, ~15 s JVM + card-load startup per invocation. 1v1 vs dummy: 5 games in 88 s total (2.8–40 s per game, avg ~15 s). 4-player: one game 136 s, mostly wasted (see 4-player problem).
- Log (stdout, no `-q`): one event per line with prefixes `Turn:`, `Phase:`, `Land:`, `Mana:`, `Add To Stack:` (cast/triggered/activated), `Resolve Stack:`, `Damage:`, `Life:`, `Replacement Effect:`, `Mulligan:`, `Game Outcome:`, `Game Result:`. `Turn: Turn N (Ai(k)-Deck)` is a global turn counter across all players. Outcome lines carry the reason: `has won due to effect of 'Thassa's Oracle'`, `has lost trying to draw cards from empty library`, `lost because life total reached 0`. The `Game Outcome: Turn N` value doesn't obviously match the log's global counter (4p game: log reached 167, outcome said 84). Work out the convention before reporting turns from it; prefer counting the hero's own `Turn:` lines.
- AI coverage signal: card scripts carry `AI:RemoveDeck:All` (the AI can't use the card sensibly; 2,500 of 33,978 scripts) and `AI:RemoveDeck:Random` (random-deck exclusion, mostly ignorable). `NonCommander` = irrelevant here. Chulane test: all 79 unique cards scripted; `All` on Selvala, Explorer Returned and Sungrass Prairie.
- Forge API (for Phase B), from javap: `forge.view.SimulateMatch` (reference implementation), `forge.game.Match(GameRules, List<RegisteredPlayer>, String)`, `Match.createGame()/startGame(Game)`, `RegisteredPlayer.forCommander(Deck)`, `RegisteredPlayer.setStartingLife(int)`, `Game.subscribeToEvents(Object)` (Guava-style bus; events are records in `forge.game.event`, 61 classes incl. `GameEventTurnBegan`, `GameEventTurnPhase`, `GameEventCardChangeZone`, `GameEventSpellResolved`, `GameEventManaPool`, `GameEventGameOutcome`), `Game.setGameOver(GameEndReason)`, `Game.getPhaseHandler()`, `Game.getGameLog()`, `GameRules.setSimTimeout(int)`. Check the record fields with `javap -p` before coding against them.

### Verified while building Fishpond (2026-10-01, Forge 2.0.15)

- `sim -s SEED` seeds `MyRandom` **once per JVM**: game k depends on games 1..k-1, and within a `-n N` match the previous game's loser goes first. The harness reseeds per game in a fresh `Match`.
- Forge prints a game's whole log **after** the game ends. A wall-clock stop (`-c`) prints "Stopping slow match as draw" before that log, and its `Game Outcome` lines mark **every surviving player** "has won because all opponents have lost"; `Game Result` then names an arbitrary winner. Treat more than one winner as unfinished.
- Players lost mid-game are skipped in the turn order, so the log's global turn counter isn't 4x the hero's turns. Count the hero's own `Turn:` lines.
- Noncombat damage is logged as `deals N non-combat damage` (hyphen); combat as `deals N combat damage`; damage to a permanent as `deals N damage to Card (id)`.
- Card ids are roughly per-player blocks of ~100 but not exactly (seat 4 reached 402): attribute damage by the source's decklist first, ids second.
- **AI decision timeout:** `AiController` chooses spells on a "Game AI Eval" thread and gives up after `Game.AI_TIMEOUT` = 5 s (no setter). Under CPU load this happens (11 times in one 5-game real-pod CLI run), making results load-dependent. The harness sets the field by reflection (default 120 s, `-Dfishpond.aiTimeout`); the parser counts "AI eval thread at timeout" lines and the report warns. The stock CLI can't change it.
- Memory: ~1.1 GB RSS per JVM. Speed (4 CPUs, 4 workers): ~1 to 2 min per Chulane vacuum game per worker at cap 20; the Primal Surge turns (100+ triggers) dominate.

## First-run findings (Chulane, the reason this plan exists)

- 1v1 vs dummy, seed 7, 5 games: 3 combat wins, 1 Thassa's Oracle win, 1 loss by drawing from an empty library.
- 4p game: Chulane cast on its 5th turn, went off on its 8th (~400 events), Primal Surge resolved correctly, then the AI cast Thassa's Oracle **from hand** with Chulane + Beast Whisperer out. The cast triggers (CR 601.2i) drew from an empty library before Oracle could enter (603.6a), so it lost (704.5b). This is a **pilot error inside a real rules trap**: a human stops Surge early (it's a "may") or removes the draw triggers first. If Surge *flips* Oracle, its ETB is ordered with the other triggers (603.3b) and wins. The user confirmed this line.
- Lesson for every report: **separate "rules outcome" from "pilot decision"**, and tag known AI traps.

## Problems to design around

1. **4-player games don't end** when the hero dies: dummies play on until the clock. Fix in Phase B by ending the game on hero loss (`setGameOver`). Phase A workaround: a short `-c` clock plus parsing the hero's loss line as the real end; never fall back to 1v1. With real opponents, the hero losing still ends *our* measurement (record who/what killed the hero), but the pod result is kept too.
2. **Dummies must never act.** Kozilek + 99 Wastes is wrong: Kozilek is castable on turn 10. Use a commander the deck can't cast: a mono-W legendary (e.g. Isamaru, Hound of Konda) + 99 Wastes. Wastes make only {C}; the identity is legal. Check that no dummy `Add To Stack` lines exist in any run.
3. **Opponent model (DECIDED by the user 2026-10-01): always 3 opponents, 4-player pod, 40 life each.** No 1v1 mode as a default and no "1 dummy at 120" shortcut. Each of the 3 seats is independently either a **dummy** (vacuum) or a **real deck** (the user's own lists, tester lists we build, or anything else). Mixed pods (e.g. 1 real + 2 dummies) must work. This is a hard requirement: **never simplify the opponent seats down to dummies-only**, in any phase, tool, flag or default. The user will test both "into a vacuum" and "into real lists"; every metric and report must work in both modes and say which mode produced it.
4. **Startup cost.** 15 s per JVM. Phase A batches with `-n N` in one invocation. Phase B runs every game in one JVM.
5. **AI quality.** Forge AI is decent at fair Magic and weak at combo sequencing. Never present a win rate without the loss-reason breakdown and the AI-flag list.
6. **Version drift.** New sets land in Forge releases. Pin `FORGE_VERSION` in `forge_setup.py`, bump deliberately, and log the version in every report.
7. **Licence.** Never vendor Forge into the repo (size limits, GPL redistribution, re-clone cost). Download it at runtime.

## Architecture

As built (2026-10-01):

```
scripts/sim_report.py           shared stats + report printers, extracted from goldfish.py (goldfish output byte-identical)
fishpond/forge.py               (plan: forge_setup.py) pinned release + cache, Java/javac, card-name index + AI flags, CLI sim command
fishpond/decks.py               (plan: forge_deck.py) deck file -> .dck, dummies, opponent SPECs, gauntlet sampling, --variant swaps
fishpond/logparse.py            Forge game log -> per-game record (both engines)
fishpond/runner.py              (plan: forge_sim.py driver) engine 'cli' (stock sim, chunks of 5) and 'harness' (Phase B), parallel JVMs
fishpond/harness/ForgeRunner.java   Phase B harness, compiled at runtime into ~/forge-cache/<ver>/fishpond-harness/<hash>/
fishpond/metrics.py, report.py  records -> sim_report bundle + Fishpond's sections
fishpond/cli.py                 setup | deck | run | report [--reparse] | show
fishpond/opponents/<gauntlet>/  (plan: decks/opponents/) committed opponent lists; first gauntlet 'own' = Yusri, Zur, Klauth
tests/fishpond_units.py + tests/fishpond/*.log   offline parser checks on real Forge logs (smoke runs them; live checks only if Forge is cached)
data/fishpond/<run>/            (gitignored; plan: data/forge/) meta.json, games.jsonl, report.txt, decks/, logs/
```

Decisions made while building (iteration inside the plan, flagged for the user):
- `--cap` (default 20 hero turns) is separate from the report horizon `--turns` (default 10): with one flag, Chulane's typical T12-T19 wins would all read "unfinished".
- Harness lands are counted at end of turn and mana/colors at the start of main phase plus that turn's land drop, to match goldfish's sense ("after the land drop").
- The harness raises Forge's AI decision timeout (see Verified facts) so results don't depend on machine load.

**Opponent spec (all tools, all phases):** `--opp SPEC` given 1–3 times, or `--opp-set FILE`; missing seats are filled with dummies, always 3 seats. SPEC = `dummy` | a deck file path | a name in `decks/opponents/` | `gauntlet:<name>` (a folder or list file of decks; each game samples 3 seats from it, seeded, with an option to fix the pairings). Per-seat AI profile: `--opp-ai Default,Reckless,...`. Each opponent deck is validated with `mtg.py deck` before the run, and Forge-unknown cards are warned about. Reports always print the pod: seat, deck, bracket, AI profile.

Reuse `mtg.py`'s deck parsing (headers: `bracket`, `plan`, `key`, `track`, `package`, `pets`). Same CLI flags as goldfish.py where they mean the same thing (`--turns`, `--trials`, `--seed`, `--track`, `--variant`, `--json`).

## Phase A: MVP on the stock CLI (target: 1 session)

1. `forge_setup.py`: idempotent; prints the version and paths.
2. `forge_deck.py`: convert; warn on any card name Forge doesn't know. Build a name index from `cardsfolder.zip` once and cache it; handle DFC/split names (`A // B`). Emit the deck's `AI:RemoveDeck:All` list.
3. `forge_sim.py run DECK --games N --seed S [--opp SPEC]x3`: always a 4-player pod; invokes the CLI, captures stdout, splits it per game on `Game Result:`. Opponent decks go into `~/.forge/decks/commander/` under unique names (avoid name collisions with the hero).
4. Log parser -> per game JSON: winner, reason (normalized: `combat`, `alt_win:<card>`, `decked`, `life`, `poison`, `cmdr_dmg`, `draw/clock`), hero's turn count, per hero-turn: lands played, spells cast (names), triggers, damage dealt, life totals; first turn each `track`/`key` card is cast or enters; commander casts; mulligans.
5. Report via `sim_report.py` (goldfish layout first, then the new sections): win %, kill-turn P10/median/P90, wins by route, losses by reason, commander turn distribution, tracked/key card turns, top cast cards, AI-flag list, Forge version, seeds, games, wall time.
6. Acceptance (deck: `tests/forge/chulane.txt`): Chulane 50 games in a vacuum (3 dummies) **and** 20 games into 3 real lists (the user's own decks are fine as the first gauntlet); numbers reproduce with the same seed; dummies never cast; hand-audit 3 game logs against the parsed JSON, including at least one with real opponents.

## Phase B: Java harness (target: 1–2 sessions)

- `ForgeRunner.java` compiled with `javac -cp <jar>`; run with `java -cp <jar>:tools/forge ForgeRunner ...`. Model it on `SimulateMatch` (javap it; don't decompile into the repo).
- One JVM, card DB loaded once; loop N games with seeds `S..S+N-1`.
- Subscribe to events; at each hero `TurnBegan` / main phase snapshot: lands, untapped mana sources and producible mana (best effort: count untapped lands + creatures/artifacts with mana abilities), hand size, library size, graveyard size, board creatures/power, commander zone and tax. Record mana actually spent from `Mana:`/ManaPool events.
- End the game on hero loss or all opponents dead; turn cap (`--turns`, default 10 hero turns) ends the game as "unfinished" (not a draw).
- Output: one JSONL line per game.
- Acceptance: parity with Phase A results on the same seeds (win/route/turns within noise); throughput measured and logged (target ≥ 4 games/min on 1 CPU, ≥ 30/min on the user's desktop with parallel JVMs).

## Phase C: goldfish parity metrics

Map each goldfish report section to Forge data:

| goldfish | Forge source |
|---|---|
| development table (lands/mana/all colors/cmdr out/spells/mana spent, P10/med/P90) | Phase B snapshots |
| card flow (extra cards, hand, stranded, graveyard) | snapshots + draw events |
| combat and damage, opps dead, kill turn | Damage/Life events, outcome |
| `--track`, tutor targets | cast/zone-change events; tutor = card moved library->hand/battlefield by an effect |
| `--variant` same shuffles | same seed list on both builds. **Verify** that the seed fixes the library order identically when the decklist differs (it probably won't: a different card list means a different shuffle). If not, accept paired-seed noise and use more games |
| `--explain` | Forge has every card scripted; replace with an "AI can't play" (RemoveDeck:All) + "never cast in N games" list |
| disruption ladder | Phase D (real opponents), not dummies |
| mulligans | `Mulligan:` lines (Forge AI's own keep logic, not ours; note that) |

## Phase D: new data Forge makes possible

Priority order:
1. **Win routes and loss reasons** (already in Phase A). Losses by own action (decking, Oracle trap, life paid) are the most useful thing the user has never had.
2. **Card impact:** per card, the cast rate, average cast turn, win rate in games it resolved vs not (confounded: label it "association"), and dead-card rate (in hand at game end, never castable).
3. **Combo/line detection:** sequences that preceded wins (e.g. Surge -> Oracle ETB). Count how often each key package assembles and fires.
4. **Known-AI-trap tagging:** pattern rules over the log, e.g. `oracle_trap` = Oracle cast from hand while library ≤ pending cast-draw triggers. Report "losses attributable to pilot error" separately and offer an "excluding tagged pilot errors" win rate.
5. **Real-opponent analysis** (the seats already support real decks from Phase A; this item is the *reporting*): win rate by pod and by opponent deck, which opponent killed the hero and how, the turn the hero's plan was first disrupted (removal/counter/wipe hitting the hero's key cards), and how the hero's interaction was spent. Build tester gauntlets in `decks/opponents/` by bracket (the user's own decks first, then purpose-built testers, e.g. "B3 interaction-heavy", "B3 fast combo", "B2 battlecruiser"). This replaces the goldfish disruption ladder with real interaction; keep the ladder in goldfish.py for fast what-ifs.
6. **AI-profile sensitivity:** run Default vs Reckless/Cautious; if results swing a lot, the deck is pilot-sensitive (that's a finding).
7. **Mana analysis:** flood/screw rate by turn, color-screw (castable-in-hand vs held), commander-tax cost over a game.
8. **Interaction stats** (with real opponents): how often the deck's removal/counters were used, and what they hit.

## Validation and accuracy

- **Rules correctness:** trust Forge by default; spot-check 1 game log per new deck by hand, especially key cards. Log suspected Forge bugs in `docs/FORGE_ISSUES.md` (card, version, log excerpt) rather than working around them silently.
- **Cross-check with goldfish** on what both read well: commander turn, lands, and mana by turn should agree within ~0.5 turn at the median. Chulane: goldfish 57.6% Chulane by T4 / 83.8% by T5; the first Forge game cast it on hero turn 5. Do this check on 3 decks before trusting either one.
- **Sampling error:** report counts with 95% intervals; a win rate from 200 games is ±~7 pts, from 1,000 games ±~3 pts.
- **Pilot error:** report the tagged-trap share. If more than ~20% of losses are tagged, say the deck is pilot-sensitive and treat the win rate as a floor.

## Docs and housekeeping (done)

All done; the user-facing doc is `docs/FISHPOND.md` (not `FORGE.md`), the tool row is in USE_INSTRUCTIONS §2, `data/fishpond/` is gitignored, and the frozen notes are in place.

- When Phase A lands: add `docs/FORGE.md` (user-facing usage, like GOLDFISH.md), a row in USE_INSTRUCTIONS §2 ("How a deck plays out → forge_sim.py; fast mana/curve/variants → goldfish.py"), and a smoke test that runs 2 seeded games if Forge is cached (skip cleanly if not).
- Mark GEF/T3 frozen in GOLDFISH_ROADMAP.md and UPGRADE_PLAN.md, with a pointer here.
- `.gitignore` `data/forge/`.
- Commit straight to main, one commit per step, smoke before push.

## Status

| Step | Status |
|---|---|
| Feasibility (download, run, parse by hand) | Done 2026-10-01 (chat sandbox) |
| Opponent model decided (3 seats, each dummy or real deck) | Done 2026-10-01 |
| sim_report.py extraction | Done 2026-10-01 (goldfish byte-identical on 6 seeded runs; smoke 74/74) |
| Phase A (setup, deck, cli engine, parser, report) | Done 2026-10-01: vacuum 50 + real 20 run, seed reproducibility, 3 hand audits, dummies never acted (see "Acceptance log") |
| Phase B (harness) | Built 2026-10-01: per-game seeds (same seed = identical game mid-JVM, verified), hero-loss end (plays on with real opponents left), turn cap, snapshots |
| Phase C | Partly: development (lands, mana, colors, cmdr out, casts), card flow (extra draws, hand, graveyard), combat tables filled from snapshots + log; `--variant` works (paired by seed and pod). Not yet: mana spent, stranded, discarded, recursion |
| Phase D | Partly: win routes/loss reasons with killer seat (1), cast rates + association win rates + never-cast (2, partial), pilot tags self_decked/surge_trap/oracle_trap (4), real-opponent pods (5, reporting partial) |
| Resumable runs, Windows support | Done 2026-10-01 / 2026-10-03 (`run --resume`; override home via junctions/hard links) |
| Pilot policy Part 1 + Part 2 (patches 07-09, card overrides, puzzles) | Built 2026-10-02 (see "Pilot policy") |
| Patches 10 (empty-library wins) and 11 (large-board blocks) | Built 2026-10-03 (FORGE_ISSUES #6, #7) |
| Pilot study (16 bracketed decks, 100 games) | Done 2026-10-04; power-matched run 2026-10-05 added N1-N5; priority items 1-3 and 8 done 2026-10-06 (patches 12-14, overrides); item 9, loop shortcut, done 2026-10-07 (patches 15-16; puzzles 55/55, 3 known gaps); **next**: item 6 (life budget, N4: cause of the last timeout), then item 4 (commander timing) |
| Landbase tempo validation logging | Planned: `docs/LANDBASE_TEMPO_PLAN.md` step 3 |

## Lookahead and tutoring (2026-10-01, the user: enable lookahead, moderate/low setting)

- Forge's AI has an optional lookahead (`forge.ai.simulation`, per player via `AIOption`): `USE_HYBRID_SIMULATION` = the heuristic AI picks, `OnePlaySafetyChecker` simulates each play one move ahead and vetoes it if it scores worse; `USE_FULL_SIMULATION` = plays chosen by `SpellAbilityPicker` search (`SimulationController.DEFAULT_MAX_DEPTH` = 3, a constant, not a setting) and library searches decided by simulating each candidate (`chooseCardToHiddenOriginChangeZone`). No depth or strength knob exists. The user's rule (none/low/high -> low): **default `--sim hybrid`** for the user's seat and real-deck opponents (`--opp-sim`); dummies always off. The harness reads back each controller's mode and records it per game.
- The AI timeout also exists as a preference (`MATCH_AI_TIMEOUT`); the harness keeps setting the field directly.
- Forge 2.0.15's lookahead crashes on prepared cards: `docs/FORGE_ISSUES.md` #1 (pause + replay workaround, both reported).
- Tutoring: the plain AI picks library-search targets with generic pickers (`ComputerUtilCard.getBestAI`, `getMostExpensivePermanentAI`, `getBestCreatureAI`; Forge's own Demonic Tutor script: "will generally look for the most expensive castable thing"). Hybrid doesn't change that; full does (board-score simulation, so value picks, not combo pieces). Deck-level `AiHints` only drive sideboarding; card hints are global. The harness logs every library search/dig of the user's seat into hand or play (`#FP-TUTOR`: source, card, land, key card, key cards left) and the report prints tutor targets per tutor and key-card fetches. Superseded 2026-10-02 by "Pilot policy" below (general, on by default, all seats).
- **Measured (Chulane vacuum, the same 12 seeds, 2026-10-01):** lookahead off won 4 / lost 8 (7 `surge_trap`), median game 77 s, 15 CPU-minutes; hybrid won 8 / lost 3 (3 `surge_trap`) / 1 cut by the then 600 s per-game limit (now 1800 s), median game 152 s, 41 CPU-minutes (about 2.7x). Lookahead paused on 3 of 141 hero turns (prepared cards), 0 fallbacks. Zur vacuum, 8 games, hybrid: won 5, lost 0, 3 at the cap; median game 61 s (about 53 s without). Zur's tutor picks (now logged): Words of Worship 7, Astral Drift 5, Solitary Confinement 5, Rule of Law 5 (defensive or hate pieces that do nothing against dummies): value-blind, as the code says; Solve the Equation fetched Approach of the Second Sun both times.
- Pilot watch: known blind spots are tagged (`surge_trap`, `oracle_trap`) or listed (win-condition cards cast vs won with, never-cast, AI-flagged, dead cards, tutor targets). Add tags/lines as new ones appear.

## Pilot policy (plan, 2026-10-02; the user approved the direction, implementation waits until the active sims finish)

**Why.** 25-game Zur runs (same seed and pod: Chulane / Niv / Omnath, hybrid) went 3-22 under both Default and Cautious, every win Approach of the Second Sun. The profile barely matters (18 of 25 paired games ended alike); the pilot does. Zur's tutors fetch by generic "best card" pickers: Grasp of Fate was Default's top Zur fetch (10/25 games), while the deck is built to fetch Astral Slide (the engine) and fire it with its 27 cycling cards (Step Through among them). Zur was cast in only ~75% of games, and the core enchantments are AI-flagged (`AI:RemoveDeck:All`: Astral Slide, Necrodominance, Solitary Confinement, Words of Worship...). The user's direction: **systematic pilot changes over deck-specific ones**, on by default for every seat, with deck-specific overrides only where the general rules provably miss.

### Part 1: tutor policy in the harness (`fishpond/harness`)

- **Hook.** `SafeControllerAi` already subclasses `PlayerControllerAi`; it also overrides the library-search choice. First step: confirm which controller/AI methods Zur, Solve the Equation, Spellseeker, Wishclaw, Step Through (wizardcycling) and dig effects reach in 2.0.15. Unhooked paths defer to Forge, so nothing breaks.
- **Static intel, built once per deck in Python** (a JSON file passed to the harness): for every card in the deck, roles from Scryfall oracle tags (`data/oracle-tags-*.jsonl`: `draw engine`, `removal-*`, `pillowfort`, `synergy-cycling`, `tutor-*`...), mechanic counts (how many deck cards each card pays off: Astral Slide sees 27 cyclers), Commander Spellbook combos restricted to the deck (`data/spellbook_combos.json.gz`; Zur has 3 complete ones, all Approach + a tutor, and 10 one-card-away), the Forge AI flag, and optional `# package:` / `# key:` header boosts.
- **Dynamic scoring in Java** per candidate, highest layer wins, ties fall through:
  1. completes a Spellbook combo with cards in hand or on the battlefield;
  2. survival: facing lethal or a board that's beating you raises removal, wipes, fogs, protection;
  3. **engine graph**: a payoff whose enablers are dense in the deck ranks high until one is on the battlefield; then enablers that fire it rise (Zur: Astral Slide first, then cyclers like Step Through). Spellbook doesn't list engines like Slide + cycling (0 entries), so this layer is the one that has to carry decks like Zur;
  4. role gap: what the board lacks against what the deck is built around (mana, card flow, answers, win-con);
  5. deck synergy count;
  6. playability: AI-flagged cards discounted until Part 2 fixes their mechanic (otherwise the policy just fetches cards that rot in hand);
  7. Forge's own pick as the tiebreak.
- **Deck overrides** (`# priority:` header, later if needed): only when an audit shows the general layers miss a line on purpose. Zur is the acid test: if the engine graph doesn't fetch Slide then fire it, fix the layer before reaching for an override.
- **Audit log.** Every decision prints `#FP-POLICY`: source, chosen card, Forge's pick, deciding layer and reason. The report gets "policy vs Forge" counts and the top disagreements.
- **Cost.** Scoring is table lookups plus one pass over the board per candidate: well under a millisecond, the same order as Forge's own pickers and negligible next to hybrid's per-play simulation. It's far cheaper than `--sim full`'s per-candidate simulation; full mode could use the policy to shortlist 2-3 candidates and simulate only those, which would speed it up.
- **Acceptance.** Same seeds and pods, policy vs no policy: Zur, Chulane, Yusri (tutor-heavy) plus one low-tutor control deck that must not move. Hand-audit 10 decisions per deck. On by default for all seats once accepted; keep an internal switch for A/B runs only.

### Part 2: AI fixes by mechanic (Forge patches and card-script overrides)

1. **Measure:** rank AI-flagged cards across every deck in the repo and the gauntlets by frequency x damage (left in hand, never cast, cast rate). Some flags may be overcautious.
2. **Group by mechanic**, not card: optional life/discard upkeep costs (Solitary Confinement), draw replacement and skipping draws (Necrodominance, Words of Worship), cycling-triggered flicker (Astral Slide/Drift), and so on. One fix per decision pattern.
3. **Cheapest fix first:** card-script AI hints (`AILogic`, SVars) shipped as override files in `fishpond/forge_card_overrides/`, applied at setup like `forge_patches/`; Java patches to the AI classes only when hints can't express it.
4. **Tests are Forge puzzles** (`.pzl` board states): "Slide on the battlefield, a cycler in hand at end of an opponent's turn: does the AI cycle with a creature to flicker?" Fast, deterministic, re-run on every Forge bump.
5. **Upstream:** Forge (Card-Forge/forge, GPL-3) takes contributions. Before sending anything: read its CONTRIBUTING notes and any stance on AI-assisted code, open an issue or discussion first, keep PRs small with puzzle tests, and disclose that Claude helped write them. The user submits under their account and owns the review. Accepted patches drop out of our patch set.

### Status (2026-10-02, built)

- Part 1 built: `fishpond/policy.py` (intel), `harness/PilotPolicy.java` (layers combo, survival, engine, role, synergy, boost, forge; playability discounts flagged cards fetched to hand x0.1), `#FP-POLICY` log, report lines, `fishpond deck` summary, `fishpond compare`. All seats by default.
- Part 2 built: puzzles (`fishpond puzzles`, `harness/PuzzleRunner.java`), pilot patches 07 (cycling payoffs), 08 (blink attackers out of combat), 09 (per-seat overrides), card overrides (`fishpond/forge_card_overrides/`, 26 cards; `fishpond flags`). Key finding: Forge's AI never casts `AI:RemoveDeck:All` cards (AiController drops them), which made Necrodominance, Solitary Confinement and Cole's Omnath commander dead cards. Known gaps kept flagged: Biorhythm, City of Traitors, Words of Worship; 9 cards untested.
- A/B (pilot at all seats vs stock, seed 1): Zur 2-23 vs 3-22 (25 games), Yusri 1-14 vs 4-11, Chulane 0-15 both (15 games). Zur's tutoring moved as intended (Grasp of Fate 10 -> 0 fetches, Astral Drift 4 -> 13, Escape Protocol 1 -> 7); Niv's pod wins rose (72 -> 80% in Zur's pod, 47 -> 73% in Yusri's), since the pilot strengthens every seat. Yusri's combo layer fetched the still-flagged Squee's Revenge (fixed: playability now covers every layer). `--pilot-seats you` (pilot for the hero only) added to separate the two effects; those runs were in progress at the merge.

### Order (as planned)

1. Instrumentation: `#FP-POLICY`-style log of every library search with Forge's pick and the candidate list; flagged-card ranking for Part 2.
2. Static intel builder (Python) + layers 1, 3 and 7 (combos, engine graph, fallback); Zur and Chulane A/B.
3. Layers 2, 4-6; full acceptance; flip on by default.
4. Part 2 in ranked order, each with puzzles; remove the layer-6 discount per fixed mechanic.

## Acceptance log

Phase A/B acceptance, 2026-10-01, Claude Code container (4 CPUs), Forge 2.0.15, harness engine unless noted, `tests/forge/chulane.txt`:

- **Vacuum, 50 games, seed 1** (788 s on 4 workers = 3.8 games/min): won 13 (26%, 95% CI 16-40%), lost 36, 1 at the turn cap. Every loss is Chulane decking itself; 32 are `surge_trap` (the AI takes every Primal Surge put until the library is empty; 29 were decked the turn Surge was cast). Excluding tagged pilot errors: 13 of 18 (72%). Wins: 12 combat, 1 Thassa's Oracle; median win on hero turn 13. Dummies never cast or attacked; 0 AI timeouts.
- **Reproducibility:** the first 12 games re-run with 2 workers instead of 4 (and a newer harness build) give identical records 12/12 and identical Forge logs apart from the `Match Result` line (Forge credits an arbitrary survivor when the harness stops a game; the parser ignores that line). Same seed = same game, independent of `--jobs`.
- **Hand audits:** (1) stock-CLI vacuum game, Chulane loses on T7 to the Primal Surge deck-out: turns, casts, attacks, combat damage 1/1/3/6/5, land drops and the Whitemane Lion bounce match the log; (2) harness vacuum game 44, the Thassa's Oracle win: Chulane on T7, the 17-spell T8, seat 4 killed in combat on T9 then Oracle cast from hand wins; route, deaths and turn all match. (3) real-pod game 0 (seed 1000003): Chulane killed by Klauth's combat after hero turn 7 (the final 4-damage hit is the killing blow; recorded as T8 by the "opponents' turns count toward your next turn" rule), then Zur won the pod with Approach of the Second Sun; record matches.
- **Real pod, 20 games into gauntlet `own`** (Yusri / Zur / Klauth, seat order sampled per game; 2 workers, about 30 min): won 0 (95% CI 0-16%), lost 18, 2 hit the 600 s per-game safety timeout. Klauth killed Chulane 9 times and won 10 pods (Yusri 5, Zur 3). 4 losses were `surge_trap` deck-outs. Losses median hero turn 8. 0 AI decision timeouts with the raised limit.
- **Cross-check with goldfish** (Chulane only so far; the plan asks for 3 decks): lands agree at the median on every turn T1-T8; all colors close (T3 81% vs 72%, T4 91.5% vs 92%); Forge's mana estimate runs 1-2 higher from T3; **the commander comes about a turn later on Forge** (goldfish 62.5% by T4 / 91% by T5; Forge 36% / 68%): Forge's AI doesn't prioritise the commander the way goldfish's pilot does. Spells cast by T8: median 13 vs 10. **Zur** (16 vacuum games vs goldfish 1,000; goldfish leaves 18 of 61 nonland cards blank): lands within one at the median (T8 6 vs 7), commander again about a turn later on Forge (25% by T4 / 56% by T5 vs goldfish 57% / 78%). Fishpond Zur: won 9 (56%), lost 0, 7 hit the turn cap (slow combat into 120 life); wins 5 combat, 4 Approach of the Second Sun. The commander-timing gap is consistent across both decks: treat it as a known pilot difference, not a bug. Third deck still to do.
- **Stock CLI engine** (10 vacuum games, chunks of 5): same picture (6 of 10 lost to `surge_trap`); about 70 s per game per JVM because the dummies play on to the clock after the hero dies. 5 real-pod games: 11 AI decision timeouts under load, which is what led to the harness raising the limit.

- **Yusri vacuum, after patches 10-11 (2026-10-03):** 25 games, 3 dummies, hybrid, `--cap 12`, seed 1 (7 min on 4 workers). Won 17 (68%, CI 48-83%), lost 2, 6 hit the cap. Wins median T10 (P10 T7). Routes: combat 6, Toad 3, Laboratory Maniac 3, noncombat 3, Jace 2. Yusri cast median T4. The 6 capped games were mostly mana screw (game 18 stuck on 2 lands T3-T7; game 21 never cast Yusri). Both losses were pilot errors (Yusri follow-ups below).

### Yusri follow-ups (open; from the 2026-10-03 vacuum run)

1. **Yusri's coin count.** Forge's script is `AILogic$ Max` (always 5). The user plays it the same way: always 5 unless the flips can kill them outright, so the only change wanted is a buffer of 1: choose 5 unless 2 x (flips lost in the worst case) >= life (at 11 life, flip 5; at 10, take fewer). Krark's Thumb doesn't change the worst case. Game 20 (seed 1000023) died to 5 flips at 8 life on T8.
2. **Enter the Infinite -> Thassa's Oracle.** Game 16 (seed 1000019, T11): won 5 flips, cast Enter the Infinite free *after* the Toad's attack trigger, never cast Thassa's Oracle, then cast Edgar and decked to his enter-the-battlefield draw. The user: Enter the Infinite is right even without the win in hand, since drawing the library finds the Oracle; the miss is sequencing. To check: was the Oracle the card Enter the Infinite put back on top (Forge's choice of card to put back), or did patch 10's hold-the-Oracle check refuse a winning cast? Then: never put back a win card, cast the Oracle before any further draw, and don't cast a forced draw into an empty library with no win card out. `--sim full` likely won't fix it (its search scores board value; it doesn't value an empty library with the Oracle in hand and doesn't make the put-back choice).
3. **Mystical Tutor: Enter the Infinite -> Show and Tell (3 times).** Show and Tell was cast in 5 games and won 4; it put out big threats (Ancient Silver Dragon in game 0) and led into wide attacks. The user prefers Enter the Infinite unless Show and Tell sets up a play now. Options: a combo-layer rule (Show and Tell only when the hand holds a big permanent), or a `# priority: Enter the Infinite` header (cheap, but it would also move early tutors off ramp).

## Pilot study 2026-10-04 (draft; the user: plan only, no patches yet)

**What ran.** Every 4-deck pod within each bracket of the 16 bracketed lists in `decks/`, 4 games a pod, hybrid at every seat, Default AI, `--cap 20`: B2 5 pods, B3 15, B4 5 = 100 games (`data/fishpond/pilot_study_20261004/`, `pods.json`; seeds 7319044 + 100 x pod index). Seat 1 rotated across pods. 89 games ended with a single winner. 11 didn't: 5 timeouts and 1 out-of-memory crash, all from the Balancer loop (FORGE_ISSUES #8); 3 games voided when that crash killed the worker's JVM; 1 NPE (#9); 1 at the turn cap.

**Results** (single-winner games won / decided; 25% is par): B2 Wilson 7/15, Erebos 6/15, Jarad 3/16, Araumi 2/15, Ragost 1/15. B3 Zhulodok 16/30, Heliod 14/28, Klauth 5/28, Balancer 3/23, Chulane 2/28, Zur 1/27. B4 Niv 9/16, Xyris 5/16, Lumra 3/16, Omnath 2/16, Yusri 1/16.

**Read.** Zhulodok, Heliod, Niv, Wilson and Erebos win on lines the AI plays well (big creatures, lifegain plus combat, damage triggers), mostly with their own kills. Ragost looks genuinely weak in its bracket (no stranded key cards). Pilot failures:
- **Balancer:** assembles its infinite and never cashes it in (#8). Its rate is a floor.
- **Zur:** attacked with Zur on 79 of 372 turns (21%), so its engine rarely fires; 2 kills in 40 games; Approach of the Second Sun cast 9 times, won once.
- **Chulane:** attacked on 14 of 306 turns; Primal Surge cast 5 times in 40 games and in hand at game end in half its hero games.
- **Yusri:** Enter the Infinite cast 0 times in 16 games (in hand at game end in 75% of its hero games), even after patch 10.
- **Araumi:** the commander was never cast in 16 games: Araumi of the Dead Tide is `AI:RemoveDeck:All` in Forge 2.0.15, so the deck never encored anything (its whole plan). Its self-mill ran (Ripples of Undeath 46 triggers, Hedron Crab, Riverchurn Monument) with nothing to cash it in; Rakshasa Debaser's printed encore was considered 8 times, never paid. Its 2 wins were long games won with Archon of Cruelty. Also flagged in the list: Dakmor Salvage, Darkwater Catacombs, Lim-Dûl's Vault, Toxic Deluge.
- **Omnath:** one 21-minute game with 33 failed casts of Return of the Wildspeaker (the known hybrid "AI failed to play" noise); a drag, not the whole story.

**Upgrade plan, in order:**

1. **Loop shortcut (Comprehensive Rules "Taking Shortcuts" and "Handling Infinite Loops"), fixes #8.** The user's idea: once a loop starts and nobody responds, let it run many times without re-checking the board each time.
   - *Detect:* a pilot seat casts or activates the same ability from the same card 3 times in one priority sequence, the stack resolves empty between, and the card returns to where it started (Sprout Swarm back to hand).
   - *Offer the response window once:* every other seat gets one real priority pass, with its normal AI and lookahead, as the shortcut rules allow ("accept the shortcut or say where you'll stop it").
   - *Run it fast:* if nobody responds, the next iterations run with lookahead off for every seat, opponents auto-pass, and the looping AI skips its decision step (the harness casts the same ability directly). Each iteration still really resolves, so triggers stay correct (Soul Warden, Parallel Lives, Suture Priest); that costs milliseconds, not the seconds each hybrid check costs now.
   - *Stop:* when a cheap goal check passes (opponents' total life covered by the looping seat's attack power with a margin for blockers, or by a drain counter), or at a cap (`-Dfishpond.loopMax`, default 1000, the user 2026-10-04). Then mark the ability done for the turn so the AI moves on to combat. Log `#FP-LOOP`: seat, card, iterations, stop reason. The report counts them.
   - *Not doing:* applying N iterations in one bulk step (making 1000 tokens at once). That skips triggers and differs per card; real iterations without lookahead are fast enough.
   - *Tests:* puzzles `sprout_swarm_loop` (Witherbloom + Sprout Swarm + enough mana: loops, stops, attacks for lethal) and `sprout_swarm_loop_soul_warden` (triggers counted), plus a guard puzzle where a looping seat can't win and must stop at the cap and pass. Acceptance: replay the 6 #8 seeds; all finish well under the 30-minute limit, deterministic on replay.
2. **Harness hardening** (FORGE_ISSUES "Harness safety net" gaps): unwrap `ExecutionException` in `SafeControllerAi` so lookahead exceptions are remade without lookahead; restart a worker's JVM after `OutOfMemoryError` and replay its remaining games from their seeds.
3. **#9 root cause:** replay seed 7320765962232, find the null-source card state, fix the copy in Forge.
4. **Commander combat safety (the user's rules, 2026-10-04),** a pilot patch in `AiAttackController` / `AiBlockController`. Symmetrical: applies to every pilot seat's commander, never the hero alone (user, 2026-10-04: pilot logic is always symmetrical):
   - *Attack* with the commander only into a player whose untapped potential blockers can't kill it (first strike, deathtouch, and pump or removal the AI can see count as able to kill it). If every opponent can kill it, it stays home. Indestructible, protection and similar count as survivable.
   - *Block* with the commander only an attacker that won't kill it. If every incoming attacker would kill it, don't block with it, unless the damage left unblocked would be lethal to its controller (life or commander damage); then block as Forge would.
   - *Exception, attack triggers (user, 2026-10-04):* the attack safeguard is skipped for a commander with an attack trigger when attacking gets value now (Yusri's coin flips, Zur's fetch, Klauth's mana; read from the card's `Attacks` triggers). It still swings at the least problematic opponent (check that Forge's defender choice already does this, and fix it if not), and stays home if attacking would leave its controller dead on the swing back. Blocking rules have no exception. Chulane isn't one (its value is casting creatures).
   - *Also check* why `AiAttackController` kept Zur (21% of turns) and Chulane (5%) home in the study.
   - *Puzzles:* commander into three boards that can kill it (stays home); into one safe opponent (attacks that one); blocks the small attacker, not the lethal one; must chump because unblocked is lethal; Zur attacks into risk for a fetch; Zur stays home when the swing back kills its controller.
5. **Finisher misses:** Primal Surge (held now? check whether the `surge_trap` handling over-corrected), Enter the Infinite (0 casts after patch 10: replay a Yusri hero game where it rotted in hand), Approach of the Second Sun's second cast. One puzzle each.
5a. **Araumi encore:** (1) un-flag override `araumi_of_the_dead_tide.txt` plus puzzles: Araumi out with a full graveyard and Gray Merchant / Archon of Cruelty / Gyruda in it, enough mana (activates at sorcery speed, encores the best enter- or leave-the-battlefield creature it can pay for); one where it can't pay the encore (doesn't activate). (2) If the un-flagged AI misplays it, a pilot patch: pick the target by the creature's ETB/LTB value per opponent within the mana left, and make sure encore costs get paid (Rakshasa Debaser's printed encore was never paid either). (3) Rank the deck's other flags (Dakmor Salvage, Lim-Dûl's Vault, Toxic Deluge) under Pilot policy Part 2. (4) Re-run Araumi's 4 B2 pods.
5b. **Ragost engine under pressure:** vacuum, 10 games (`data/fishpond/ragost_vacuum_20261004`, seed 8810427): won 10/10, Ragost's ability fired 30 times in 65 Ragost turns (31 damage a game, its top source) and the AI sacrificed non-token artifacts too (Solemn Simulacrum, Servo Schematic, Great Furnace). In the B2 pods it fired 6 times in about 76 turns. So the AI can run the engine but stops against real opponents. Replay a pod game where Ragost had a Food and {1} up and didn't activate, find which check said no (keeping blockers? danger checks? the untap needing lifegain?), and fix that logic for every seat.
5c. **Commander timing (policy level, every seat and deck):** Klauth's seat-1 games had a median of 8 mana available on turn 4 and 9-10 on turn 5, yet Klauth was out by turn 5 in 0% / 25% of games (the user: it should land on 4 or 5; attacking on turn 5 instead of 7 matters a lot, same for Wilson). The AI spends the mana on other spells first. Forge already ran about a turn behind goldfish on commanders (Acceptance log).
   - *Default (user, 2026-10-04):* most decks just want their commander, combat-relevant or not, so cast it as soon as it's affordable unless something more urgent (survival layer) is in hand. A general policy rule, not a per-card fix.
   - *Careful with exceptions:* some commanders are worse early or help the table (the user's example: a Grothama list; Grothama's leave-the-battlefield draw rewards opponents who damaged it), and some decks hold the commander for a protected or combo turn. Before shipping: list such patterns (symmetric or opponent-benefiting commander text, commanders that need setup on the battlefield, decks whose plan or key line says to hold it), give the rule a deck-header opt-out (e.g. `# commander: hold`), and don't guess. Ask the user about any deck the heuristics flag.
   - *Acceptance:* commander-out-by-turn and win rate on the same seeds before and after, for every deck in `decks/`. No deck may get worse without an explanation; Klauth and Wilson puzzles on curve.
6. **`fishpond study` command:** automate this run: pods by bracket, chunked so no process outlives Claude's 2-hour background-task limit (this run's driver was killed at 24/25 pods). Long studies are meant to run locally from the user's own terminal (no limit) as runs get longer; the command prints the line to run and Claude reads the results folder afterwards. It must be resumable and print a per-deck table (wins over decided games, undecided, kills, deaths, how it won). Win attribution must use the single surviving winner; on draws, cap and timeout games Forge marks every seat "has won", which the first count of this study got wrong.
7. **Re-run** the 15 B3 pods after 1-2 (Balancer's real rate), then the whole study at 8 games a pod for tighter numbers.

### Power-matched run 2026-10-05: new pilot failures

**What ran.** 6 pods of 4, grouped by the pilot study's win rates (strongest decks together, weakest together, two mixed pods), 5 games each, hybrid at every seat, seed 1 (`data/fishpond/powermatch_20261005/`, G1-G6). 29 games had a single winner, 1 timed out. Every game was reviewed turn by turn (all seats' lands, casts, attacks, blocks, deaths; the hero's hand and mana) and suspects were checked in the raw logs.

**Known failures seen again:** Araumi never cast (0/5; item 5a); commanders late with mana up (Niv with 9-23 mana and Niv-Mizzet uncast for turns, Klauth on its turns 5-8, Wilson on 3-5; item 5c); commanders blocking a token or trading (item 4). Balancer's Sprout Swarm loop ran once and finished (no new data for #8).

**New** (N1-N5; each applies to every pilot seat):
- **N1. Wheel of Misfortune number.** G2 game 4: Lumra picked 25 at 40 life and took 25 on turn 6. Forge's choose-number logic ignores the damage. Fix: a card override (or a `ChooseNumber` AI patch) that caps the number well below life, plus a puzzle.
- **N2. Felidar Sovereign at 4 life.** G5 game 2: Heliod cast it facing a lethal swarm, instead of holding mana or a blocker. Fix: a `NeedsToPlay`-style hint so it's cast only when the life total can plausibly reach 40 (the same class as "cast an alt-win card only when it can win"; check Test of Endurance too).
- **N3. City of Traitors stops land drops.** Lumra played City of Traitors, then played no land again in two games: G2 game 4 (discarded Yavimaya, Forest, Mirrorpool to hand size) and G6 game 3 (no land after its turn 2). The AI treats "sacrifice when you play another land" as never play another land. Fix: play the land when it would otherwise be discarded, or when the land drop is worth more than City's two mana (fetch/landfall/utility lands), with a puzzle.
- **N4. Paying life into a lethal board.** G1 game 4: Niv went 22 -> 12 through Bolas's Citadel, Vampiric Tutor and Sensei's Top with Zhulodok's Kozilek board out, then took 19 and died (at 22 it lives on 3); it cracked Tainted Sigil on the opponent's turn, when life lost "this turn" was near zero. Erebos also paid for draws under pressure (not game-deciding). Fix: a life budget (life minus the biggest attack the table can make next round, from the existing danger checks) applied to optional life payments (Citadel, Erebos, Ad Nauseam, shocklands, Yusri's flips), and Tainted Sigil only in the turn the life was lost. Merge with Yusri follow-up 1 (coin-count buffer), which is the same rule.
- **N5. A 30-minute land-drop turn.** G2 game 0: Lumra with Mirrorpool copies of Icetill Explorer (extra land drops, lands from the graveyard) chained City of Traitors through hundreds of land plays, each firing landfall triggers, until the per-game timeout. Not yet known whether it is an unbounded loop or a finite turn made slow by hybrid on a big board (#7 class). Item 1's detector (same ability cast or activated 3 times) would not see land plays. Next: replay seed 1000003 of that run, then either widen loop detection to repeated land plays or add a cost cap.
  - **Diagnosed 2026-10-06 (replay of seed 1000003 with patches 01-11, identical turn by turn, run to a 60-minute cap): an unbounded loop.** Springheart Nantuko is bestowed on an Icetill Explorer: each land Lumra plays fires Nantuko's landfall ({1}{G}: a token copy of the enchanted Icetill), so every land play adds one more land drop. City of Traitors replays from the graveyard (Icetill) for {C}{C} and Tireless Provisioner's Treasures cover the {G}, so each iteration pays for itself. Icetill triggers per land grow by one each time (2, 7, 13 ... 43 over 43 land plays in 60 minutes); the library was milled out early (845 empty mills). Each iteration is slower than the last because the AI's danger checks (`aiLifeInDanger` -> `predictNextCombatsRemainingLife` -> gang-block planning) re-plan every seat's blocks on the growing board for each trigger choice. So item 9 must widen its detector to repeated land plays (the same land replayed from the graveyard, or land plays past N in one turn) and stop at the cap; a cheaper danger check on huge boards (#7 class) helps every big board but doesn't end this loop. (An earlier note here called it a finite turn: wrong, the land-drop count was never bounded.)

**Seen once, not filed:** Chulane holding 8 cards with 13-20 mana for several turns (G4 game 1; hand contents aren't logged, needs a replay); Swords to Plowshares on Ajani's Pridemate gave Heliod about 50 life (defensible, it was the biggest threat); nobody answered Felidar Sovereign at 59 life (G1 game 1; hands unknown).

### Re-run after patches 12-14 (2026-10-06)

The 6 power-matched pods again, same decks, seed 1, 5 games, hybrid (`data/fishpond/powermatch_20261006_p14/`; G5b = G5 with the final 40/50 Felidar/Test thresholds). 4 of 30 paired results changed. Hero results: Niv 2 -> 1 (game 2: patch 14's first rule traded City of Traitors for City of Brass on a pain trigger; fixed in ff99a22 with a puzzle), Erebos 1 -> 2 (game 4: Lumra no longer takes 25 from Wheel of Misfortune, makes its land drops and discards no lands), Araumi 1 -> 0 (game 1 lost, game 4 cut by the Balancer loop), Chulane, Heliod, Wilson unchanged.
- **Araumi:** commander cast 5 times in 5 games (0 before), 8 activations, 7 encores (Gray Merchant, Kairi x2, Peregrine Drake, Sphinx Ambassador, Vindictive Lich, Wurmcoil Engine). One miss: it granted encore to Archon of Cruelty, then spent the mana on Singularity Rupture (its own board wipe). Follow-up: hold the encore mana once the grant resolves.
- **Felidar / Test:** Felidar no longer cast at low life (G5 game 2); Test of Endurance at 50 life still won G5 game 4.
- **Timeouts: 2 of 30, both loops.** G2 game 0 (Lumra's Nantuko/Icetill land loop, N5) and G3 game 4 (Balancer's Sprout Swarm loop, #8, on Araumi's turn 25). Item 9 is now the main source of void games.
- Game times about doubled tonight: two pods plus a replay shared the CPU; results are seed-determined, not time-determined.

### Final regression after patches 15-16 (2026-10-07)

The same 6 pods, seed 1, 5 games, with patches 01-16 (`data/fishpond/powermatch_20261007_p16/`; `_v1` and `_invalid` are superseded runs of earlier versions of 15/16, each with a README). The overwritten patch-14 pods were regenerated from worktrees at 02bb02f/7cbe3a4 and match the records above game for game.
- **Timeouts: 1 of 30** (baseline 1, patch 14 2). Both loop games now end naturally: G2 game 0 (Lumra's land loop) in 5 minutes, G3 game 4 (Witherbloom's Sprout Swarm) in under 5. Loop stops: Witherbloom 13 and 40 on `goal`; Omnath's Staff of Domination twice at 10 (harmless).
- **The remaining timeout is N4, not a loop:** G2 game 4, Erebos activates Vilis, Broker of Blood 13 times (24 -> 4 life) and ends with a 36-card hand; every priority then evaluates that hand. Alone the game ends at 25.8 minutes; with 10 games running at once it passes 30. The fix is the life budget (item 6), now the most useful next step for run validity too. Puzzle `vilis_life_payments` (known gap) is its test.
- **Paired comparisons no longer line up with older runs:** patch 16 shifts Forge's random stream (the block planner draws random numbers), so 3-5 games a pod take different paths. Compare distributions, not paired games, across the patch-16 boundary.
- **Araumi:** 8 commander casts and 9 encores in 5 games (baseline 0 and 0), first win (G3 game 3).

### Priority order (difficulty vs payoff, 2026-10-05; supersedes "in order" above)

Payoff = how many decks and games the failure costs and how badly; difficulty = card override < pilot patch < engine/harness work. Item numbers refer to the lists above; each keeps its own puzzles and acceptance.

| # | Item | Difficulty | Payoff | Why here |
|---|---|---|---|---|
| 1 | **Done 2026-10-06** (patch 14, City un-flagged, 4 puzzles) N3 City of Traitors land drops | Low-medium (pilot patch + puzzle) | Medium-high: crippled Lumra in 2 of 10 games | Cheap, game-deciding, any deck with City or similar sacrifice lands |
| 2 | **Done 2026-10-06** (patch 12 for Wheel; overrides: Felidar Sovereign and Test of Endurance cast only at their winning life total (user, 2026-10-06); 7 puzzles) N1 Wheel of Misfortune + N2 Felidar Sovereign | Low (card overrides + puzzles) | Low-medium: one deck each, game-losing when it happens | One small batch of overrides |
| 3 | **Done 2026-10-06**, steps (1) and (2) (un-flag override + patch 13; 2 puzzles; step (4), the B2 re-run, still to do) 5a Araumi un-flag | Low (override + puzzles) | High for Araumi: 0 commander casts in 21 games | The deck can't run its plan at all; step (2) only if the AI misplays it |
| 4 | 5c Commander timing | Medium (policy rule + opt-out header) | Very high: every deck, about a turn of tempo | Biggest across-the-board gain; acceptance re-runs every deck |
| 5 | 4 Commander combat safety | Medium (attack/block patch + 6 puzzles) | High: every deck's commander | Pairs with 5c (a commander cast earlier must also survive) |
| 6 | N4 Life budget (with Yusri follow-up 1) | Medium (one rule over optional life payments) | Medium: Niv, Erebos, Yusri, any Citadel/Ad Nauseam deck | One rule fixes several known losses |
| 7 | 2 Harness hardening | Medium | Medium: keeps runs valid (voided games, OOM) | Protects every later measurement; needed before the big re-runs |
| 8 | **Done 2026-10-06**: an unbounded loop (Springheart Nantuko on Icetill Explorer + City of Traitors; see N5) N5 replay (diagnosis only) | Low | Decides how 9 is built | Do before 9 |
| 9 | **Done 2026-10-07** (patches 15 and 16; FORGE_ISSUES #8; final regression: loop games all finish) 1 Loop shortcut, widened to repeated land plays (N5 is a land loop) | High | High: Balancer's real rate, no timed-out games | Most work; the cheaper fixes above shouldn't wait for it |
| 10 | 5 Finisher misses (Primal Surge, Enter the Infinite, Approach) | Medium-high (one puzzle and fix each) | Medium: Chulane, Yusri, Zur | Per-card; do after the general rules |
| 11 | 5b Ragost under pressure | Medium-high (find the check that says no) | Low-medium: one deck | Diagnosis-heavy |
| 12 | 3 #9 null-source NPE | High (Forge copy internals) | Low: one game in 130 | Rare; the item 2 safety net covers it meanwhile |
| 13 | 6 `fishpond study` command | Medium (tooling) | Medium: makes 14 cheap and repeatable | Build right before the re-run |
| 14 | 7 Re-run (B3 pods, then the whole study at 8 a pod) | Run time only | Measures 1-13 | Last |

## Roadmap (2026-10-01, after the merge to main)

Superseded as the priority list by the pilot study's upgrade plan above; kept for the items still open (3, 4, 5, 7, 8). Fishpond works end to end but isn't "set". In the original order:

1. **Run it where the user runs it.** Everything so far ran in a 4-CPU Claude Code container. The chat sandbox has 1 CPU, ~4 GB and no javac by default: test `setup --jdk`, memory with lookahead, and a real "Launch Fishpond" form round trip there.
   - *Chat sandbox, 2026-10-02:* `setup --jdk` works (65 s: Forge download, JDK install, 9 patches built). Hybrid lookahead at every real seat runs about 10 min per 4-player game on 1 CPU (Zur vs Chulane/Niv/Omnath, game 1: 590 s, 13 hero turns), so a 25-game read is ~4 h: fine for small checks, home machine for A/B batches. Background runs must be started with `setsid nohup ... < /dev/null &` or they die when the tool call returns; `--resume` picks them back up.
2. ~~Resumable runs~~ Done 2026-10-01: `run --resume RUN_DIR [--trials N]` replays cut-off games from their seeds and adds new ones; `report` shows partial runs. Mulligan line added to the report.
3. **Re-baseline with lookahead on.** The acceptance numbers (Chulane vacuum 26%, 0/20 into the gauntlet) were measured with lookahead off. Re-run Chulane, and each of Yusri, Zur, Klauth as the hero (vacuum + gauntlet), which also completes the 3-deck goldfish cross-check.
4. **A headline block** at the top of the report (5-6 lines: win rate and interval, how it wins, how it loses, pilot-error share, the user's field-9 questions answered), with the tables below as detail. Combined report when a run uses both a vacuum and a gauntlet pod.
5. **Validate `--variant` at scale** (code path exists, never run on a real swap question).
6. ~~**Pilot modes:**~~ Done 2026-10-02 (pilot policy built, see above). profiles measured on Zur 2026-10-02 (Default vs Cautious, 25 games each: no real difference, see "Pilot policy"); `--sim full` runs in progress in another session. Next: the pilot policy plan.
7. **Gauntlet growth:** tester decks by bracket beyond the user's own lists (Phase D 5).
8. **Leftovers:** stranded and cycled columns, combo/line detection, card impact beyond association; Forge version-bump procedure (re-test FORGE_ISSUES entries).

## Open questions for the user

- ~~The brackets, plans and key cards of the saved decks.~~ Done 2026-10-04: all 16 lists in `decks/` carry a bracket header; Ragost is in the repo.
- ~~Klauth's list has 101 cards.~~ Fixed 2026-10-02: Vorinclex, Voice of Hunger out (d190686).

- Which decks form the first real-opponent gauntlet, and at what bracket?
- ~~Pilot-error losses in the headline?~~ The user, 2026-10-02: show them beside the headline win rate, never excluded, and say which game and which turn each one happened (so it can be replayed by seed).
