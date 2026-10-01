# FISHPOND — Forge-backed deck simulation (`python3 -m fishpond`)

Companion to `USE_INSTRUCTIONS.md` §6. Read this before running Fishpond. Design history and the build plan: `docs/FORGE_PLAN.md`.

Fishpond plays the user's deck on [Forge](https://github.com/Card-Forge/forge), an open-source (GPL-3.0) rules engine with about 34,000 scripted cards, in 4-player Commander pods. Forge's AI pilots every seat. **Every card is played by real rules**: no card is "blank" or "partial" the way goldfish.py reads them. The limits are the pilot (Forge's AI is decent at fair Magic and weak at combo sequencing) and sample size. Use Fishpond for "how does this deck actually play out": win rate and how it wins, how it loses (including losing to itself), commander timing, development, which cards get cast, and how it does into real decks. goldfish.py stays as a fast, frozen cross-check for mana/curve questions and its disruption ladder.

```
python3 -m fishpond setup [--jdk]                     # once per session: downloads Forge (~300 MB, about a minute) to ~/forge-cache/
python3 -m fishpond deck DECK [--opp SPEC]...          # check the list against Forge first
python3 -m fishpond run DECK [--trials 20] [--seed 1] [--turns 10] [--cap 20] [--opp SPEC]... [--opp-set FILE] [--fixed-pod]
    [--ai PROFILE] [--opp-ai A,B,C] [--track "Label=REGEX"] [--variant "Label|Out=>In;Out=>In"] [--commander NAME]
    [--engine auto|harness|cli] [--jobs N] [--timeout S] [--clock S] [--out DIR] [--json]
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

## Engines

- **harness** (default when `javac` exists): `fishpond/harness/ForgeRunner.java`, compiled at run time against the cached Forge jar. Every game is its own Forge match with its own seed (game i of `--seed S` uses `S*1000003+i`), so any game replays alone and `--jobs` never changes results. A game ends when the table dies, when the user's deck has lost (with real opponents left it plays on to get the pod's winner), or after the user's turn `--cap` (default 20: "unfinished: turn cap"). Snapshots at the user's main phase and cleanup give real lands, Forge's mana estimate, colors, hand and graveyard.
- **cli**: Forge's stock `sim` mode, no javac needed. Games are chained 5 per JVM (one can't be replayed alone; a game cut by the wall clock changes the rest of its chunk), the other seats play on to the clock after the user's deck dies, and the development table has fewer columns (land drops instead of lands; no mana, hand or graveyard).
- Speed: a game costs 30 s to 2 min of one CPU (about 15 s of JVM startup per worker on top). Turns with huge trigger stacks (a Primal Surge turn resolves 100+) are the slow part, and real opponents are slower than dummies. Measured on 4 CPUs with 4 workers: about 4 Chulane vacuum games a minute. The chat sandbox (1 CPU, ~4 GB) runs one worker: budget about 1 game a minute, so 20 games is a 20-minute run; say so before starting a big one. `--jobs` defaults to what CPUs and memory allow (about 1.1 GB per JVM).
- Forge's AI gives up on a decision after 5 s by default, which makes results depend on machine load. The harness raises that limit (120 s; `-Dfishpond.aiTimeout` on the JVM) and the report warns when any decision still timed out. The cli engine can't change it, so busy machines get load-dependent cli results.

## Reading the report

**Header.** Win rate with a 95% interval, losses, unfinished games and why; **wins by route** (combat, noncombat, commander damage, poison, alternate win: CARD); **losses by reason** with the killing seat (decked, life, poison, commander damage, an opponent's alternate win); for decking losses, the last spell the user's deck cast; game length in the user's turns for wins and losses; turn order (1st to 4th) with the win rate in each; pilot tags; the dummy check.

**Pilot tags** separate rules outcomes from pilot decisions. Always report them next to the win rate:
- `self_decked`: drew from an empty library.
- `surge_trap`: decked in the turn Primal Surge resolved. Forge's AI takes every optional put until the library is empty; a human stops early or has the win in place.
- `oracle_trap`: an empty-library win card (Thassa's Oracle, Laboratory Maniac, Jace, Wielder of Mysteries) was cast while draw triggers decked the user first (CR 601.2i, 603.3b).
The header also prints the win rate with tagged pilot-error losses (`surge_trap`, `oracle_trap`) left out, and says "pilot-sensitive" when more than 20% of losses are tagged: then treat the headline win rate as a floor and quote both.

**goldfish's layout** follows (`scripts/sim_report.py`): development, card flow, combat and damage, by the user's turn, to `--turns` (default 10). A game that ended earlier repeats its final state. A column marked `≈` is measured differently from goldfish; the notes at the bottom say how. A metric Fishpond can't measure is left out, never faked. Tracked groups come from `# track:` headers and `--track`, and every `# key:` card is tracked too ("first cast or seen entering").

On the harness the card-flow table also has `discarded` (hand to graveyard, cycling included) and `recursion` (graveyard to hand, battlefield or stack), and `mana spent` is counted from the log on both engines.

**Opponents section** (pods with real decks): who won the pod (real seats play on after the user's deck dies, so a winner usually emerges), and per opponent deck: games it sat in, the user's win rate in those games, how often it killed the user's deck, how often the user's deck killed it, and how often it won the pod. Then how the user's deck died (route and killing deck) and the killing blows (the card that dealt the biggest share of the final life change). This is the real-opponent replacement for goldfish's disruption ladder.

**Cards section.** Cast rate, median first-cast turn and casts per game for the most-cast cards; key cards with the win rate of games they were cast or entered (an association, not cause); on the harness, cards most often left in hand when the game ended (dead-card candidates); cards never cast, played or seen entering; AI-flagged cards; trigger counts; commander casts per game.

**Sampling.** A win rate from 20 games is ±22 points at worst; from 50, ±14; from 200, ±7. Quote the interval. For a cut-vs-add question use `--variant` (same seeds and same pods); Forge reshuffles a different list differently, so variant games are paired by seed and pod, not by shuffle. Expect more noise than goldfish's variants and run more games.

## Hand audits

`show RUN_DIR GAME` prints a game's parsed record and per-turn summary (with snapshots on the harness); `--log` adds Forge's log for that game (`--phases` keeps phase and mana lines). Audit one game per new deck, especially games involving the key cards, before trusting the numbers. Suspected Forge bugs go in `docs/FORGE_ISSUES.md` (card, Forge version, log excerpt), never worked around silently.

## Runs and game records

A run is saved in `data/fishpond/<time>-<deck>/` (gitignored): `meta.json`, `games.jsonl` (one record per game), `report.txt`, `decks/` (the `.dck` files Forge read), `logs/`. `report --reparse` re-runs the log parser over the saved logs after a parser fix. A game record holds: `result` (win, loss, draw = unfinished), `route`, `loss` (`why`, `route`, `by` seat, `src` card, `t`, `last_cast`), `end_t`, `hero_turns`, `order`, `kept`, `deaths` (per opponent: `seat`, `t`, `why`, `route`, `by`, `src`), `turns` (per user turn: lands played, casts, triggers, activations, attackers, damage, combat damage, life, opponents dead), `first_cast`, `first_in`, `casts`, commander casts, `tags`, `pod`, `seed`, and on the harness `snaps` and `stop`.

Turns are the user's turns: an event belongs to turn T if it happens during the user's T-th turn or in the opponents' turns before it. Damage is credited to the seat whose list holds the source card (by card id when several do); in a vacuum pod that is exact.

## Known limits

- The pilot is Forge's AI, in every seat. Mulligans use Forge's own keep logic.
- No companion seat (companions are left out and reported).
- Card coverage follows the pinned Forge release (`FORGE_VERSION` in `fishpond/forge.py`, printed in every report). Bump it deliberately.
- Forge is downloaded at run time and never committed (size and GPL). Runs need GitHub release downloads (the chat sandbox reaches them).
