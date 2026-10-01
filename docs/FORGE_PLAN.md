# FORGE PLAN: Forge-backed simulation for mtg-data

Working doc for Claude (chat or Claude Code) implementing this. Not user-facing. Update the Status table as work lands. Written 2026-10-01.

## Why

Ian's goal: analyze decks *while he builds them*. The tool must read and play **any** deck mechanically; the pilot may be imperfect. The goldfish engine can't get there: ~44% of the pool fully read, every mechanic hand-built, and GEF only moves the problem into "build the engine feature". Forge is a mature GPL-3.0 rules engine with ~34k card scripts and a headless sim mode. Decision: **Forge becomes the engine for "does the deck work, and how".** goldfish.py stays for fast mana/curve/variant/ladder stats on cards it reads well.

Freeze: the GEF translation track (T3 step 4+, step 5) and new goldfish engine features for exotic mechanics. Keep: goldfish parser maintenance for mana/draw/land cards only. Don't delete GEF code yet; mark it frozen in GOLDFISH_ROADMAP.md when Phase A lands.

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

## First-run findings (Chulane, the reason this plan exists)

- 1v1 vs dummy, seed 7, 5 games: 3 combat wins, 1 Thassa's Oracle win, 1 loss by drawing from an empty library.
- 4p game: Chulane cast on its 5th turn, went off on its 8th (~400 events), Primal Surge resolved correctly, then the AI cast Thassa's Oracle **from hand** with Chulane + Beast Whisperer out. The cast triggers (CR 601.2i) drew from an empty library before Oracle could enter (603.6a), so it lost (704.5b). This is a **pilot error inside a real rules trap**: a human stops Surge early (it's a "may") or removes the draw triggers first. If Surge *flips* Oracle, its ETB is ordered with the other triggers (603.3b) and wins. Ian confirmed this line.
- Lesson for every report: **separate "rules outcome" from "pilot decision"**, and tag known AI traps.

## Problems to design around

1. **4-player games don't end** when the hero dies: dummies play on until the clock. Fix in Phase B by ending the game on hero loss (`setGameOver`). Phase A workaround: 1v1, or a short `-c`.
2. **Dummies must never act.** Kozilek + 99 Wastes is wrong: Kozilek is castable on turn 10. Use a commander the deck can't cast: a mono-W legendary (e.g. Isamaru, Hound of Konda) + 99 Wastes. Wastes make only {C}; the identity is legal. Check that no dummy `Add To Stack` lines exist in any run.
3. **Opponent life model.** Goldfish uses 3 opponents at 40. Phase A 1v1 at 40 understates kill time (one opponent). Report 1v1 numbers as "single-opponent". Phase B: 4p with 3 dummies at 40 (parity), or 1v1 with the dummy at 120 via `setStartingLife` (cheaper, same total life, but per-player effects differ: Oracle and alt-wins don't care; "each opponent" drains do. Prefer true 4p for parity).
4. **Startup cost.** 15 s per JVM. Phase A batches with `-n N` in one invocation. Phase B runs every game in one JVM.
5. **AI quality.** Forge AI is decent at fair Magic and weak at combo sequencing. Never present a win rate without the loss-reason breakdown and the AI-flag list.
6. **Version drift.** New sets land in Forge releases. Pin `FORGE_VERSION` in `forge_setup.py`, bump deliberately, and log the version in every report.
7. **Licence.** Never vendor Forge into the repo (size limits, GPL redistribution, re-clone cost). Download it at runtime.

## Architecture

```
scripts/forge_setup.py   download + cache pinned release (~/forge-cache/<ver>/), install JDK if javac needed, write ~/.forge prefs
scripts/forge_deck.py    deck file (mtg.py parser, same headers) -> .dck; dummy decks; copies into ~/.forge/decks/commander/
scripts/forge_sim.py     driver: run N games (Phase A: CLI sim; Phase B: harness), parse logs -> JSONL per game, then report
tools/forge/ForgeRunner.java   Phase B harness: one JVM, N seeded games, event subscriber, per-turn snapshots, hero-loss end, JSONL out
data/forge/              (gitignored) raw logs, JSONL
```

Reuse `mtg.py`'s deck parsing (headers: `bracket`, `plan`, `key`, `track`, `package`, `pets`). Same CLI flags as goldfish.py where they mean the same thing (`--turns`, `--trials`, `--seed`, `--track`, `--variant`, `--json`).

## Phase A: MVP on the stock CLI (target: 1 session)

1. `forge_setup.py`: idempotent; prints the version and paths.
2. `forge_deck.py`: convert; warn on any card name Forge doesn't know. Build a name index from `cardsfolder.zip` once and cache it; handle DFC/split names (`A // B`). Emit the deck's `AI:RemoveDeck:All` list.
3. `forge_sim.py run DECK --games N --seed S [--opp 1|3]`: invokes the CLI, captures stdout, splits it per game on `Game Result:`.
4. Log parser -> per game JSON: winner, reason (normalized: `combat`, `alt_win:<card>`, `decked`, `life`, `poison`, `cmdr_dmg`, `draw/clock`), hero's turn count, per hero-turn: lands played, spells cast (names), triggers, damage dealt, life totals; first turn each `track`/`key` card is cast or enters; commander casts; mulligans.
5. Report (text, goldfish-style): win %, kill-turn P10/median/P90, wins by route, losses by reason, commander turn distribution, tracked/key card turns, top cast cards, AI-flag list, Forge version, seeds, games, wall time.
6. Acceptance: Chulane 50 games; numbers reproduce with the same seed; dummies never cast; hand-audit 3 game logs against the parsed JSON.

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
5. **Real opponents (matchup/bracket mode):** gauntlet folders of real Commander decks by bracket (Ian's own decks first, then precons). Win rate and the turn the deck's plan is disrupted. This replaces the disruption ladder with actual interaction. Use 4p pods with 3 real decks.
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
| Phase A | Not started |
| Phase B | Not started |
| Phase C | Not started |
| Phase D | Not started |

## Open questions for Ian

- Default opponent model: 3 dummies at 40 (goldfish parity) or 1v1?
- Which decks form the first real-opponent gauntlet, and at what bracket?
- Should tagged pilot-error losses be excluded from the headline win rate or only shown beside it?
