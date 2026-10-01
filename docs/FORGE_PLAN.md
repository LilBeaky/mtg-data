# FORGE PLAN: Fishpond, the Forge-backed simulator for mtg-data

Working doc for Claude (chat or Claude Code) implementing this. Not user-facing (that's `docs/FISHPOND.md`). Update the Status table as work lands. Written 2026-10-01.

**Name and layout (Ian, 2026-10-01):** the tool is **Fishpond**, a folder `fishpond/` run as `python3 -m fishpond`. The `forge_setup.py` / `forge_deck.py` / `forge_sim.py` names below are the original plan; the "Architecture" section maps them to the real files.

## Start here (fresh session, no prior chat context needed)

This doc is self-contained. Everything learned in the feasibility chat is below; don't ask Ian to re-explain it.

1. Clone the repo and read `docs/USE_INSTRUCTIONS.md` once (it's the general workflow), then this file. You don't need GOLDFISH.md, GOLDFISH_ROADMAP.md, UPGRADE_PLAN.md or the TRANSLATION_* docs; they describe the frozen legacy path. Read `scripts/goldfish.py` lines ~6000–6320 (stats + report printers) only when you do the `sim_report.py` extraction.
2. Set up the environment exactly as in "Environment recipe" below.
3. Work the Status table top to bottom. Phases A and B are built; Phase C/D items are next. Acceptance runs use `tests/forge/chulane.txt` (Ian's Chulane list, 100 cards, B3, plan Primal Surge, keys Shrieking Drake / Primal Surge / Thassa's Oracle).
4. Push straight to main, one commit per step; run `python3 tests/smoke.py` before each push. The GitHub token is in the project instructions, not in the repo. Never commit it. (A Claude Code session pinned to a branch pushes there instead; Ian merges.)

### Environment recipe (all verified 2026-10-01 in the chat sandbox unless marked untested)

Now automated: `python3 -m fishpond setup [--jdk]` downloads and unpacks the pinned release into `~/forge-cache/<ver>/` (override with `FISHPOND_CACHE`), indexes the card scripts, and reports Java/javac. The manual recipe below is kept for reference. Corrections found while building (2026-10-01, Claude Code container, 4 CPUs / 16 GB):
- The JVM must run with **cwd = the Forge install dir**: Forge reads `res/` relative to the working directory (from elsewhere it crashes on the missing language bundle).
- `sim -D <absolute dir>/` loads decks by file name (`-d hero.dck ...`) in Commander too, so runs keep their `.dck` files in the run folder instead of `~/.forge/decks/commander/`.
- The mono-W dummy (Isamaru, Hound of Konda + 99 Wastes) **verified**: it loads and never casts or attacks (checked in every run).
- Real-deck opponents **verified**; Forge's sim does **not** enforce 100 cards (Ian's Klauth list has 101 and plays).

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

### Governance (Ian's standing rule, 2026-10-01)

Ian is tired of structural rewrites of the simulator. No change to the engine choice or the overall architecture without (1) a written case, (2) a cheap test with evidence, and (3) Ian's go-ahead. Before building any new capability, check first whether an existing tool already does it. Iteration inside this plan (parsers, reports, harness) is fine.

## Why

Ian's goal: analyze decks *while he builds them*. The tool must read and play **any** deck mechanically; the pilot may be imperfect. The goldfish engine can't get there: ~44% of the pool fully read, every mechanic hand-built, and GEF only moves the problem into "build the engine feature". Forge is a mature GPL-3.0 rules engine with ~34k card scripts and a headless sim mode. Decision (Ian, 2026-10-01): **Forge is the primary simulator.** Ian expects to rarely use goldfish.py. What he wants to keep is **goldfish's report format**, plus the new data in Phase D.

- goldfish.py is **frozen** (legacy). No new engine features, no GEF work, no parser work. It stays in the repo, still working and still in smoke, as a fast cross-check and for quick "what-if" ladders. Don't delete it unless Ian asks.
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
- 4p game: Chulane cast on its 5th turn, went off on its 8th (~400 events), Primal Surge resolved correctly, then the AI cast Thassa's Oracle **from hand** with Chulane + Beast Whisperer out. The cast triggers (CR 601.2i) drew from an empty library before Oracle could enter (603.6a), so it lost (704.5b). This is a **pilot error inside a real rules trap**: a human stops Surge early (it's a "may") or removes the draw triggers first. If Surge *flips* Oracle, its ETB is ordered with the other triggers (603.3b) and wins. Ian confirmed this line.
- Lesson for every report: **separate "rules outcome" from "pilot decision"**, and tag known AI traps.

## Problems to design around

1. **4-player games don't end** when the hero dies: dummies play on until the clock. Fix in Phase B by ending the game on hero loss (`setGameOver`). Phase A workaround: a short `-c` clock plus parsing the hero's loss line as the real end; never fall back to 1v1. With real opponents, the hero losing still ends *our* measurement (record who/what killed the hero), but the pod result is kept too.
2. **Dummies must never act.** Kozilek + 99 Wastes is wrong: Kozilek is castable on turn 10. Use a commander the deck can't cast: a mono-W legendary (e.g. Isamaru, Hound of Konda) + 99 Wastes. Wastes make only {C}; the identity is legal. Check that no dummy `Add To Stack` lines exist in any run.
3. **Opponent model (DECIDED by Ian 2026-10-01): always 3 opponents, 4-player pod, 40 life each.** No 1v1 mode as a default and no "1 dummy at 120" shortcut. Each of the 3 seats is independently either a **dummy** (vacuum) or a **real deck** (Ian's own lists, tester lists we build, or anything else). Mixed pods (e.g. 1 real + 2 dummies) must work. This is a hard requirement: **never simplify the opponent seats down to dummies-only**, in any phase, tool, flag or default. Ian will test both "into a vacuum" and "into real lists"; every metric and report must work in both modes and say which mode produced it.
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

Decisions made while building (iteration inside the plan, flagged for Ian):
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
6. Acceptance (deck: `tests/forge/chulane.txt`): Chulane 50 games in a vacuum (3 dummies) **and** 20 games into 3 real lists (Ian's own decks are fine as the first gauntlet); numbers reproduce with the same seed; dummies never cast; hand-audit 3 game logs against the parsed JSON, including at least one with real opponents.

## Phase B: Java harness (target: 1–2 sessions)

- `ForgeRunner.java` compiled with `javac -cp <jar>`; run with `java -cp <jar>:tools/forge ForgeRunner ...`. Model it on `SimulateMatch` (javap it; don't decompile into the repo).
- One JVM, card DB loaded once; loop N games with seeds `S..S+N-1`.
- Subscribe to events; at each hero `TurnBegan` / main phase snapshot: lands, untapped mana sources and producible mana (best effort: count untapped lands + creatures/artifacts with mana abilities), hand size, library size, graveyard size, board creatures/power, commander zone and tax. Record mana actually spent from `Mana:`/ManaPool events.
- End the game on hero loss or all opponents dead; turn cap (`--turns`, default 10 hero turns) ends the game as "unfinished" (not a draw).
- Output: one JSONL line per game.
- Acceptance: parity with Phase A results on the same seeds (win/route/turns within noise); throughput measured and logged (target ≥ 4 games/min on 1 CPU, ≥ 30/min on Ian's desktop with parallel JVMs).

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
1. **Win routes and loss reasons** (already in Phase A). Losses by own action (decking, Oracle trap, life paid) are the most useful thing Ian has never had.
2. **Card impact:** per card, the cast rate, average cast turn, win rate in games it resolved vs not (confounded: label it "association"), and dead-card rate (in hand at game end, never castable).
3. **Combo/line detection:** sequences that preceded wins (e.g. Surge -> Oracle ETB). Count how often each key package assembles and fires.
4. **Known-AI-trap tagging:** pattern rules over the log, e.g. `oracle_trap` = Oracle cast from hand while library ≤ pending cast-draw triggers. Report "losses attributable to pilot error" separately and offer an "excluding tagged pilot errors" win rate.
5. **Real-opponent analysis** (the seats already support real decks from Phase A; this item is the *reporting*): win rate by pod and by opponent deck, which opponent killed the hero and how, the turn the hero's plan was first disrupted (removal/counter/wipe hitting the hero's key cards), and how the hero's interaction was spent. Build tester gauntlets in `decks/opponents/` by bracket (Ian's own decks first, then purpose-built testers, e.g. "B3 interaction-heavy", "B3 fast combo", "B2 battlecruiser"). This replaces the goldfish disruption ladder with real interaction; keep the ladder in goldfish.py for fast what-ifs.
6. **AI-profile sensitivity:** run Default vs Reckless/Cautious; if results swing a lot, the deck is pilot-sensitive (that's a finding).
7. **Mana analysis:** flood/screw rate by turn, color-screw (castable-in-hand vs held), commander-tax cost over a game.
8. **Interaction stats** (with real opponents): how often the deck's removal/counters were used, and what they hit.

## Validation and accuracy

- **Rules correctness:** trust Forge by default; spot-check 1 game log per new deck by hand, especially key cards. Log suspected Forge bugs in `docs/FORGE_ISSUES.md` (card, version, log excerpt) rather than working around them silently.
- **Cross-check with goldfish** on what both read well: commander turn, lands, and mana by turn should agree within ~0.5 turn at the median. Chulane: goldfish 57.6% Chulane by T4 / 83.8% by T5; the first Forge game cast it on hero turn 5. Do this check on 3 decks before trusting either one.
- **Sampling error:** report counts with 95% intervals; a win rate from 200 games is ±~7 pts, from 1,000 games ±~3 pts.
- **Pilot error:** report the tagged-trap share. If more than ~20% of losses are tagged, say the deck is pilot-sensitive and treat the win rate as a floor.

## Docs and housekeeping

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

## Lookahead and tutoring (2026-10-01, Ian: enable lookahead, moderate/low setting)

- Forge's AI has an optional lookahead (`forge.ai.simulation`, per player via `AIOption`): `USE_HYBRID_SIMULATION` = the heuristic AI picks, `OnePlaySafetyChecker` simulates each play one move ahead and vetoes it if it scores worse; `USE_FULL_SIMULATION` = plays chosen by `SpellAbilityPicker` search (`SimulationController.DEFAULT_MAX_DEPTH` = 3, a constant, not a setting) and library searches decided by simulating each candidate (`chooseCardToHiddenOriginChangeZone`). No depth or strength knob exists. Ian's rule (none/low/high -> low): **default `--sim hybrid`** for the user's seat and real-deck opponents (`--opp-sim`); dummies always off. The harness reads back each controller's mode and records it per game.
- The AI timeout also exists as a preference (`MATCH_AI_TIMEOUT`); the harness keeps setting the field directly.
- Forge 2.0.15's lookahead crashes on prepared cards: `docs/FORGE_ISSUES.md` #1 (pause + replay workaround, both reported).
- Tutoring: the plain AI picks library-search targets with generic pickers (`ComputerUtilCard.getBestAI`, `getMostExpensivePermanentAI`, `getBestCreatureAI`; Forge's own Demonic Tutor script: "will generally look for the most expensive castable thing"). Hybrid doesn't change that; full does (board-score simulation, so value picks, not combo pieces). Deck-level `AiHints` only drive sideboarding; card hints are global. The harness logs every library search/dig of the user's seat into hand or play (`#FP-TUTOR`: source, card, land, key card, key cards left) and the report prints tutor targets per tutor and key-card fetches. A key/package-driven tutor override for the user's seat is possible (~50 lines, opt-in) but is a pilot change: not built, Ian's call.
- **Measured (Chulane vacuum, the same 12 seeds, 2026-10-01):** lookahead off won 4 / lost 8 (7 `surge_trap`), median game 77 s, 15 CPU-minutes; hybrid won 8 / lost 3 (3 `surge_trap`) / 1 cut by the then 600 s per-game limit (now 1800 s), median game 152 s, 41 CPU-minutes (about 2.7x). Lookahead paused on 3 of 141 hero turns (prepared cards), 0 fallbacks. Zur vacuum, 8 games, hybrid: won 5, lost 0, 3 at the cap; median game 61 s (about 53 s without). Zur's tutor picks (now logged): Words of Worship 7, Astral Drift 5, Solitary Confinement 5, Rule of Law 5 (defensive or hate pieces that do nothing against dummies): value-blind, as the code says; Solve the Equation fetched Approach of the Second Sun both times.
- Pilot watch: known blind spots are tagged (`surge_trap`, `oracle_trap`) or listed (win-condition cards cast vs won with, never-cast, AI-flagged, dead cards, tutor targets). Add tags/lines as new ones appear.

## Acceptance log

Phase A/B acceptance, 2026-10-01, Claude Code container (4 CPUs), Forge 2.0.15, harness engine unless noted, `tests/forge/chulane.txt`:

- **Vacuum, 50 games, seed 1** (788 s on 4 workers = 3.8 games/min): won 13 (26%, 95% CI 16-40%), lost 36, 1 at the turn cap. Every loss is Chulane decking itself; 32 are `surge_trap` (the AI takes every Primal Surge put until the library is empty; 29 were decked the turn Surge was cast). Excluding tagged pilot errors: 13 of 18 (72%). Wins: 12 combat, 1 Thassa's Oracle; median win on hero turn 13. Dummies never cast or attacked; 0 AI timeouts.
- **Reproducibility:** the first 12 games re-run with 2 workers instead of 4 (and a newer harness build) give identical records 12/12 and identical Forge logs apart from the `Match Result` line (Forge credits an arbitrary survivor when the harness stops a game; the parser ignores that line). Same seed = same game, independent of `--jobs`.
- **Hand audits:** (1) stock-CLI vacuum game, Chulane loses on T7 to the Primal Surge deck-out: turns, casts, attacks, combat damage 1/1/3/6/5, land drops and the Whitemane Lion bounce match the log; (2) harness vacuum game 44, the Thassa's Oracle win: Chulane on T7, the 17-spell T8, seat 4 killed in combat on T9 then Oracle cast from hand wins; route, deaths and turn all match. (3) real-pod game 0 (seed 1000003): Chulane killed by Klauth's combat after hero turn 7 (the final 4-damage hit is the killing blow; recorded as T8 by the "opponents' turns count toward your next turn" rule), then Zur won the pod with Approach of the Second Sun; record matches.
- **Real pod, 20 games into gauntlet `own`** (Yusri / Zur / Klauth, seat order sampled per game; 2 workers, about 30 min): won 0 (95% CI 0-16%), lost 18, 2 hit the 600 s per-game safety timeout. Klauth killed Chulane 9 times and won 10 pods (Yusri 5, Zur 3). 4 losses were `surge_trap` deck-outs. Losses median hero turn 8. 0 AI decision timeouts with the raised limit.
- **Cross-check with goldfish** (Chulane only so far; the plan asks for 3 decks): lands agree at the median on every turn T1-T8; all colors close (T3 81% vs 72%, T4 91.5% vs 92%); Forge's mana estimate runs 1-2 higher from T3; **the commander comes about a turn later on Forge** (goldfish 62.5% by T4 / 91% by T5; Forge 36% / 68%): Forge's AI doesn't prioritise the commander the way goldfish's pilot does. Spells cast by T8: median 13 vs 10. **Zur** (16 vacuum games vs goldfish 1,000; goldfish leaves 18 of 61 nonland cards blank): lands within one at the median (T8 6 vs 7), commander again about a turn later on Forge (25% by T4 / 56% by T5 vs goldfish 57% / 78%). Fishpond Zur: won 9 (56%), lost 0, 7 hit the turn cap (slow combat into 120 life); wins 5 combat, 4 Approach of the Second Sun. The commander-timing gap is consistent across both decks: treat it as a known pilot difference, not a bug. Third deck still to do.
- **Stock CLI engine** (10 vacuum games, chunks of 5): same picture (6 of 10 lost to `surge_trap`); about 70 s per game per JVM because the dummies play on to the clock after the hero dies. 5 real-pod games: 11 AI decision timeouts under load, which is what led to the harness raising the limit.

## Open questions for Ian

- The brackets of the 'own' gauntlet (Yusri, Zur, Klauth). Reports print "bracket ?" until the lists carry `# bracket:` headers.
- Klauth's list has 101 cards (mtg.py agrees). Fix the list, or keep it as is for testing?

- Which decks form the first real-opponent gauntlet, and at what bracket?
- Should tagged pilot-error losses be excluded from the headline win rate or only shown beside it?
