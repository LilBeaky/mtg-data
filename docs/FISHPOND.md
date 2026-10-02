# FISHPOND — Forge-backed deck simulation (`python3 -m fishpond`)

Companion to `USE_INSTRUCTIONS.md` §6. Read this before running Fishpond. Design history and the build plan: `docs/FORGE_PLAN.md`.

Fishpond plays the user's deck on [Forge](https://github.com/Card-Forge/forge), an open-source (GPL-3.0) rules engine with about 34,000 scripted cards, in 4-player Commander pods. Forge's AI pilots every seat. **Every card is played by real rules**: no card is "blank" or "partial" the way goldfish.py reads them. The limits are the pilot (Forge's AI is decent at fair Magic and weak at combo sequencing) and sample size. Use Fishpond for "how does this deck actually play out": win rate and how it wins, how it loses (including losing to itself), commander timing, development, which cards get cast, and how it does into real decks. goldfish.py stays as a fast, frozen cross-check for mana/curve questions and its disruption ladder.

```
python3 -m fishpond setup [--jdk]                     # once per session: downloads Forge (~300 MB, about a minute) to ~/forge-cache/
python3 -m fishpond deck DECK [--opp SPEC]...          # check the list against Forge first
python3 -m fishpond run DECK [--trials 20] [--seed 1] [--turns 10] [--cap 20] [--opp SPEC]... [--opp-set FILE] [--fixed-pod]
    [--ai PROFILE] [--opp-ai A,B,C] [--sim off|hybrid|full] [--opp-sim off|hybrid|full] [--track "Label=REGEX"] [--variant "Label|Out=>In;Out=>In"] [--commander NAME]
    [--engine auto|harness|cli] [--jobs N] [--timeout S] [--clock S] [--out DIR] [--json]
python3 -m fishpond run --resume RUN_DIR [--trials N] [--jobs N]   # finish a cut-off run and/or add N games to it
python3 -m fishpond save LIST --name "Ians Zur Cycling"              # store a list in decks/ (.txt + Forge .dck)
python3 -m fishpond report RUN_DIR [--reparse] [--turns N] [--json]
python3 -m fishpond show RUN_DIR GAME [--build LABEL] [--log] [--phases]
```

## Before a run

1. `setup` (idempotent). It prints the Forge version, Java and javac, memory, and the default `--jobs`. With no `javac`, `setup --jdk` installs it (needed for the harness engine; apt-get, root).
2. `deck DECK` with the same `--opp` specs you'll run. Fix every NOT FOUND first (as for the audit). Report to the user:
   - cards Forge has no script for (left out of the game; a brand-new set can lag a Forge release),
   - **AI-flagged cards** (`AI:RemoveDeck:All`: Forge's AI can't play them sensibly). Numbers that depend on them are a floor.
   - a deck size other than 100. Forge's sim does not enforce legality, so an illegal list still plays.

## Opponents (the pod)

A pod is **always 4 players**: the user's deck in seat 1 plus 3 opponent seats. Each seat is either a **dummy** (a vacuum seat: Isamaru, Hound of Konda + 99 Wastes, which can never cast anything; it only plays lands) or a **real deck**. Never reduce a test to fewer seats or to dummies only when the user asked for real opponents.

- `--opp SPEC`, up to 3 times; seats not given are dummies. SPEC = `dummy` | a deck file | a name in `fishpond/opponents/` | `gauntlet:NAME`.
- `gauntlet:NAME` fills every seat not given from `fishpond/opponents/NAME/` (or any folder or list file of deck paths), sampled per game from the seed. `--fixed-pod` uses one sample for every game. `--opp-set FILE` lists up to 3 specs, one per line.
- Gauntlets so far: `own` (the user's own lists). Build more as `fishpond/opponents/<name>/*.txt` in the usual deck format, with `# bracket:` headers.
- Every report prints the pod and says whether it was a vacuum, mixed or real pod. Say which mode produced a number when you quote it.

## The pilot

Forge's AI plays every seat. By default it is a heuristic AI: a rule set per ability type decides "should I play this now?" one card at a time, tuned by the profile (`--ai`: Default, Cautious, Experimental, Reckless; 121 knobs such as the chance to counter a spell by its cost). It plays fair Magic like a decent casual player and handles complicated rules correctly, but it has no plan: it doesn't set up combos or alternate wins, takes every optional "may" (Primal Surge), and tutors for "the most expensive castable thing" (Forge's own note on its tutoring logic; Fishpond's tutor policy replaces that, below).

**Lookahead (`--sim`, harness only; default `hybrid` for the user's seat and for real-deck opponents, never for dummies).** Forge's simulation AI copies the game and plays candidate moves out to score them:
- `hybrid` (the default, the "low" setting): the heuristic AI still chooses; every play it picks is simulated one move ahead and vetoed if it leaves the position worse.
- `full`: plays are chosen by a search (depth 3, fixed in Forge) and library searches ("search your library for...") are chosen by simulating each candidate. The only mode that changes tutoring, scoring board value, so it still won't find a combo piece whose value comes later.
- `off`: the plain heuristic AI.
Each game record says which mode every seat actually ran (checked on the live controllers). Lookahead costs run time; the header's "game time" line reports it. Fishpond runs Forge with a few fixes to its lookahead code (`fishpond/forge_patches`, built by `setup`; `docs/FORGE_ISSUES.md` "Patches"): without them lookahead crashed after an elimination or on a defeated battle (#2), and `full` ran out of memory (#3) or threw on lethal turns (#4). Still unpatched: prepared cards crash the copy (#1), so lookahead pauses while one is on the battlefield. If Forge's search still throws inside a decision, that one decision is remade without lookahead and logged (the header's "search fallback" lines say where it was thrown); a crash outside a decision replays the game from its seed without lookahead. Both should be zero: quote them when they aren't, and treat each one as a Forge bug to root out (FORGE_ISSUES).

**Pilot improvements (on for every seat; docs/FORGE_PLAN.md "Pilot policy").** Three general layers on top of Forge's AI:
- *Tutor policy* (`fishpond/policy.py` + `harness/PilotPolicy.java`): every library search and dig picks its card from what the deck is built to do, not Forge's "most expensive" pick. Per deck, `policy.py` reads each card's roles and payoff -> enabler engines from Scryfall's oracle tags, the Commander Spellbook combos inside the list, and Forge's AI flags; at decision time the harness scores each candidate by layer: completes a combo, survival (facing lethal), engine (a payoff the deck is built around first, then the cards that fire it), role gap (ramp early, draw on an empty hand, a win-con late), synergy, playability; Forge's own pick breaks ties. With `--sim full`, Forge's search chooses among the policy's top three. `fishpond deck` prints the engines, combos and roles it found. The report's tutoring lines say how often the policy overrode Forge, why (by layer) and the biggest swaps; every decision is in the game record (`policy_log`) with the top three scores per layer. An optional `# priority: Card A; Card B` deck header boosts cards (support only; no deck ships one).
- *AI patches* (`fishpond/forge_patches/*-pilot-*`): mechanic-level fixes, each with a puzzle: with a cycling payoff out (Astral Slide, Drift, Escape Protocol...) the AI cycles during opponents' attacks, at the end of the turn before its own and in its main 2 while it holds a spare cycler (05); blink effects may target opponents' creatures that are attacking it, which takes them out of combat (06).
- *Card overrides* (`fishpond/forge_card_overrides/`): Forge's AI never casts or activates a card whose script says `AI:RemoveDeck:All` (AiController drops it), so those cards were dead in hand. An override is the release's script without that line, kept only for cards a puzzle shows the AI then plays sensibly. `python3 -m fishpond flags` lists the flagged cards in the repo's decks and their status; `flags --smoke --unflag` tests the untested ones and keeps the passing overrides. Cards the AI still can't play stay flagged (puzzles marked `known_gap`).
- `python3 -m fishpond puzzles [-v]` runs every board-state test in `fishpond/puzzles/` (seconds each). `FISHPOND_PILOT=off` turns all three layers off for an A/B run against stock Forge (crash-fix patches stay on); the report header says which. `python3 -m fishpond compare RUN_A RUN_B` prints two runs side by side (results, paired games that changed, tutor targets, cards whose cast rate moved most).

**Pilot watch.** Known blind spots are tagged (`surge_trap`, `oracle_trap`) or listed (win-condition cards cast vs won with, never-cast cards, AI-flagged cards, dead cards, tutor targets). New ones will appear with new decks: when a number looks odd, audit a game (`show --log`) and add a tag or a report line rather than trusting the number.

## Engines

- **harness** (default when `javac` exists): `fishpond/harness/ForgeRunner.java`, compiled at run time against the cached Forge jar. Every game is its own Forge match with its own seed (game i of `--seed S` uses `S*1000003+i`), so any game replays alone and `--jobs` never changes results. A game ends when the table dies, when the user's deck has lost (with real opponents left it plays on to get the pod's winner), or after the user's turn `--cap` (default 20: "unfinished: turn cap"). Snapshots at the user's main phase and cleanup give real lands, Forge's mana estimate, colors, hand and graveyard.
- **cli**: Forge's stock `sim` mode, no javac needed. Games are chained 5 per JVM (one can't be replayed alone; a game cut by the wall clock changes the rest of its chunk), the other seats play on to the clock after the user's deck dies, and the development table has fewer columns (land drops instead of lands; no mana, hand or graveyard).
- Speed: a game costs 30 s to 2 min of one CPU (about 15 s of JVM startup per worker on top). Turns with huge trigger stacks (a Primal Surge turn resolves 100+) are the slow part, and real opponents are slower than dummies. Measured on 4 CPUs with 4 workers and no lookahead: about 4 Chulane vacuum games a minute. Hybrid lookahead (the default) costs about 2 to 3 times the CPU on a busy deck like Chulane (median game 77 s -> 152 s on the same seeds) and about 15% on Zur. The chat sandbox (1 CPU, ~4 GB) runs one worker: budget about 2 to 3 minutes a game with lookahead, so 20 games is about an hour; say so before starting a big one. `--jobs` defaults to what CPUs and memory allow (about 1.7 GB per JVM; 3.4 GB with `full`). `full` lookahead is far slower and its cost is unbounded: Forge's search has no time or node limit, and every position it tries is a full copy of the 4-player game, so a decision costs roughly (candidate plays)^3 copies. On the Niv pod the other seats' turns stayed about a second, while the user's turns took 20 s to 6 min on small boards and over 45 min on a busy one (games took 5 min, 15 min, and more than an hour). The per-game limit (`--timeout`) defaults to 2 h with `full` instead of 30 min. Use `full` for a few games on a question that needs it, not for a big sample; a deterministic cap on positions per decision is the planned fix.
- Forge's AI gives up on a decision after 5 s by default, which makes results depend on machine load. The harness raises that limit (120 s; `-Dfishpond.aiTimeout` on the JVM) and the report warns when any decision still timed out. The cli engine can't change it, so busy machines get load-dependent cli results.

## Reading the report

**Header.** Lookahead mode (with pauses and crash replays), game time, win rate with a 95% interval, mulligans (the first is free in multiplayer; Forge's own keep logic), losses, unfinished games and why; **wins by route** (combat, noncombat, commander damage, poison, alternate win: CARD); **losses by reason** with the killing seat (decked, life, poison, commander damage, an opponent's alternate win); for decking losses, the last spell the user's deck cast; game length in the user's turns for wins and losses; turn order (1st to 4th) with the win rate in each; pilot tags; the dummy check.

**Pilot tags** separate rules outcomes from pilot decisions. Always report them next to the win rate:
- `self_decked`: drew from an empty library.
- `surge_trap`: decked in the turn Primal Surge resolved. Forge's AI takes every optional put until the library is empty; a human stops early or has the win in place.
- `oracle_trap`: an empty-library win card (Thassa's Oracle, Laboratory Maniac, Jace, Wielder of Mysteries) was cast while draw triggers decked the user first (CR 601.2i, 603.3b).
The header also prints the win rate with tagged pilot-error losses (`surge_trap`, `oracle_trap`) left out, and says "pilot-sensitive" when more than 20% of losses are tagged: then treat the headline win rate as a floor and quote both.

**goldfish's layout** follows (`scripts/sim_report.py`): development, card flow, combat and damage, by the user's turn, to `--turns` (default 10). A game that ended earlier repeats its final state. A column marked `≈` is measured differently from goldfish; the notes at the bottom say how. A metric Fishpond can't measure is left out, never faked. Tracked groups come from `# track:` headers and `--track`, and every `# key:` card is tracked too ("first cast or seen entering").

**Tutoring** (harness): library searches that put a card into hand or play, per game (and how many were for lands), digs, the most-fetched cards, what each tutor fetched, and how often a `# key:` card was fetched (or still in the library when something else was). Draws, mills and Primal Surge-style exiles don't count.

**Win-condition cards**: every card in the list whose Oracle text says "win the game", with games cast vs games won with it (Thassa's Oracle is often cast for its body).

On the harness the card-flow table also has `discarded` (hand to graveyard, cycling included) and `recursion` (graveyard to hand, battlefield or stack), and `mana spent` is counted from the log on both engines.

**Opponents section** (pods with real decks): who won the pod (real seats play on after the user's deck dies, so a winner usually emerges), and per opponent deck: games it sat in, the user's win rate in those games, how often it killed the user's deck, how often the user's deck killed it, and how often it won the pod. Then how the user's deck died (route and killing deck) and the killing blows (the card that dealt the biggest share of the final life change). This is the real-opponent replacement for goldfish's disruption ladder.

**Cards section.** Cast rate, median first-cast turn and casts per game for the most-cast cards; key cards with the win rate of games they were cast or entered (an association, not cause); on the harness, cards most often left in hand when the game ended (dead-card candidates); cards never cast, played or seen entering; AI-flagged cards; trigger counts; commander casts per game.

**Sampling.** A win rate from 20 games is ±22 points at worst; from 50, ±14; from 200, ±7. Quote the interval. For a cut-vs-add question use `--variant` (same seeds and same pods); Forge reshuffles a different list differently, so variant games are paired by seed and pod, not by shuffle. Expect more noise than goldfish's variants and run more games.

## Hand audits

`show RUN_DIR GAME` prints a game's parsed record and per-turn summary (with snapshots on the harness); `--log` adds Forge's log for that game (`--phases` keeps phase and mana lines). Audit one game per new deck, especially games involving the key cards, before trusting the numbers. Suspected Forge bugs go in `docs/FORGE_ISSUES.md` (card, Forge version, log excerpt), never worked around silently.

## Long runs: resume

With lookahead a game costs 2-3 CPU-minutes, so a full read can outlast a session. Harness runs are resumable: the run folder gets `meta.json` and `plan.json` before the first game, each worker writes every game to its log the moment it ends, and results are always collected from all logs. If a session ends mid-run:
- `report RUN_DIR` prints the finished games as a PARTIAL RUN with the resume command;
- `run --resume RUN_DIR` replays the unfinished games from their seeds (identical games) and finalizes the run;
- `run --resume RUN_DIR --trials N` also adds N new games (the next seeds, same pods and settings), so a big read can be built 10 games at a time.
On a 1-CPU sandbox, plan reads in chunks: start with 10 games, report, then add more. Wall time counts the sessions that finished.

## Runs and game records

A run is saved in `data/fishpond/<time>-<deck>/` (gitignored): `meta.json`, `games.jsonl` (one record per game), `report.txt`, `decks/` (the `.dck` files Forge read), `logs/`. `report --reparse` re-runs the log parser over the saved logs after a parser fix. A game record holds: `result` (win, loss, draw = unfinished), `route`, `loss` (`why`, `route`, `by` seat, `src` card, `t`, `last_cast`), `end_t`, `hero_turns`, `order`, `kept`, `deaths` (per opponent: `seat`, `t`, `why`, `route`, `by`, `src`), `turns` (per user turn: lands played, casts, triggers, activations, attackers, damage, combat damage, life, opponents dead), `first_cast`, `first_in`, `casts`, commander casts, `tags`, `pod`, `seed`, and on the harness `snaps` and `stop`.

Turns are the user's turns: an event belongs to turn T if it happens during the user's T-th turn or in the opponents' turns before it. Damage is credited to the seat whose list holds the source card (by card id when several do); in a vacuum pod that is exact.

## Known limits

- The pilot is Forge's AI, in every seat. Mulligans use Forge's own keep logic.
- No companion seat (companions are left out and reported).
- Card coverage follows the pinned Forge release (`FORGE_VERSION` in `fishpond/forge.py`, printed in every report). Bump it deliberately.
- Forge is downloaded at run time and never committed (size and GPL). Runs need GitHub release downloads (the chat sandbox reaches them).
