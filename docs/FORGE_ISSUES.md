# FORGE ISSUES — suspected Forge bugs met by Fishpond

One entry per issue: card(s), Forge version, how to reproduce, evidence, and what Fishpond does about it. Never work around a Forge bug silently: the workaround is reported in Fishpond's output too. Remove an entry when a newer pinned Forge release fixes it (re-test first).

Fixes Fishpond makes to Forge itself are listed under **Patches** below; everything else is a harness workaround.

## 1. Lookahead crashes on prepared cards (prepare mechanic)

- **Forge:** 2.0.15. **Cards:** any card with the prepare mechanic once it is prepared (seen with Studious First-Year // Rampant Growth in `tests/forge/chulane.txt`).
- **When:** only with the AI's lookahead on (`AIOption.USE_HYBRID_SIMULATION` or `USE_FULL_SIMULATION`; Fishpond `--sim hybrid|full`). The plain AI is fine.
- **What:** the lookahead copies the game (`ai.simulation.GameCopier.makeCopy`); in the copy, the prepared card's "you may cast a copy of its spell" permission (a `MayPlay` static added at run time by `AlterAttributeEffect`) resolves its `MayPlayPlayer` to an empty player list, and `StaticAbilityContinuous.applyContinuousAbility` (line 903) calls `get(0)` on it: `java.lang.IndexOutOfBoundsException: Index 0 out of bounds for length 0`. The exception escapes the AI's decision and ends the real game.
- **Evidence (2026-10-01):** 12 Chulane vacuum games, seeds 1000003..1000014, hybrid lookahead on seat 1: 6 crashed, every one in a game where Studious First-Year had been prepared; none of the 5 clean games had it. Replays exactly from its seed (game 7, seed 1000010). Stack: `GameAction.checkStateEffects < GameCopier.makeCopy:175 < GameSimulator.<init> < OnePlaySafetyChecker.isAcceptable < AiController.saSideEffects < AiController.filterLandsToPlay`.
- **Fishpond's workaround (harness):** lookahead is paused for every seat while any prepared card is on the battlefield and resumed when none is (`ForgeRunner.Watcher.checkSimSafe`); each game record counts the pauses and the user's turns played paused, and the report prints them. Verified on seed 1000010: completes with one pause. Not patched yet.

## 2. Lookahead crashes on objects the game copy can't map (eliminated players, defeated battles) — patched

- **Forge:** 2.0.15 (unchanged on `master` 2026-10-02). **Cards:** none in particular; 4-player pods after a player is eliminated, and any battle defeated in combat (seen with Invasion of Ikoria in `decks/Ians_Klauth_Dragons.txt`).
- **When:** only with the AI's lookahead on (`--sim hybrid|full`).
- **What:** `GameCopier` maps every player and card into the copy, and throws on anything it can't find:
  - **Eliminated owner.** The copy is built from the match's registered players, but `GameCopier` only maps and copies the players still in the game, so after an elimination every copy also holds a phantom of the departed player: alive, at the starting life total, with empty zones (the AI scores and plans against an opponent who isn't there). `Game.onPlayerLost` (CR 800.4) moves the loser's effect cards into the next player's command zone "so they continue to work", with the loser still the owner, so `GameCopier.addCard` gets a null owner: `NullPointerException ... because "zoneOwner" is null` at `GameCopier.addCard:465`. Seen with Omnath's Mosswort Bridge hideaway effect left in Klauth's command zone after Omnath died.
  - **Eliminated defender.** A combat declared before a defender died still lists that player: `RuntimeException: Couldn't map` at `GameCopier.find:516 < Combat.<init>:101 < GameCopier.makeCopy:172`. Inside full lookahead the same happens one level down, in a copy of a copy where a simulated play killed a player (`Combat.<init>:85`).
  - **Defeated battle.** When a battle is defeated in combat damage it is exiled and its controller may cast the back face. The AI weighs that cast with lookahead (`PlayAi.chooseSingleCard < AiController.canPlayFromEffectAI`) while the combat's attacking band still holds the battle's old object (a zone change makes a new `Card` object): same `Couldn't map` at `Combat.<init>:101`.

  The exception escapes the AI's decision and ends the real game.
- **Evidence (2026-10-01):** Niv pod (`decks/Coles_Niv_Combo.txt` vs Omnath, Klauth, Xyris; all Reckless). Seed 3 (game seed 3000009, full lookahead on seat 1): crash on table turn 22 with Niv and Omnath out; the only object whose owner had left was `Mosswort Bridge's Effect`, owner Omnath. Seed 4, 10 games, hybrid: 3 crashed (game 0 `addCard`; games 4 and 7 the defeated Invasion of Ikoria, with nobody eliminated).
- **Fix:** patch `01-gamecopier-departed-players-and-stale-cards`: the copier maps departed players and takes them out of the copy the way `onPlayerLost` does (without re-copying their commanders and effect cards, which left the game with them), puts each card in the zone it is actually in, and maps a stale card object to the card with its id. Before the patch the harness paused lookahead around these states; that workaround is gone.
- **Verified (2026-10-02, patched build):** seed 4 games 0-7, hybrid: 0 games replayed (was 3 crashes in 10). That run found two more places the copier needed departed players handled: their commanders, which left the game (189 search fallbacks in one full-lookahead game after Omnath and Xyris died), and the commander damage a living player took from them (3 fallbacks in game 6); both are in the patch now. Game 6 (seed 4000018) replayed twice on the final build: 0 fallbacks, identical game logs. Seed 5 game 1, full: 0 fallbacks, 0 pauses.

## 3. Full lookahead runs out of memory (AiCache) — patched

- **Forge:** 2.0.15 (unchanged on `master` 2026-10-02). **When:** `--sim full`, any deck, within a few turns.
- **What:** `forge.ai.AiCache` is a JVM-wide static memo whose entries keep their arguments (the `Player`s and `Game` they were computed for), and it is only cleared when a real AI decision starts (`AiController.chooseSpellAbilityToPlay`). One full-lookahead decision scores thousands of game copies (a depth-3 search, plus a copy for each combat scoring), each adding entries, so every copy stays reachable until the decision ends: `OutOfMemoryError: Java heap space` with 1.6, 6 and 7 GB heaps alike. At the spike: 589 live `Game` objects (82,000+ `Card`s) against 4-5 normally, with one `GameSimulator` alive; JFR old-object sampling traced 221 of 243 samples to `AiCache.dataMap`.
- **Evidence (2026-10-01):** seed 5, 3 games, full lookahead on Niv: all 3 replayed after an OOM between table turns 5 and 10.
- **Fix:** patch `04-aicache-bounded`: the cache empties itself once it holds 128 entries (`-Dforge.ai.cacheMaxEntries`). The trigger counts Forge's own puts, so a seed still replays exactly; a cleared entry is recomputed.
- **Verified (2026-10-02):** seed 5, full lookahead on Niv: peak heap 1.6 GB a game (1585-1653 MB over 4 games), no OOM; a 4 GB heap per worker leaves room.

## 4. Full lookahead throws "Stack isn't empty" scoring a combat — patched

- **Forge:** 2.0.15 (unchanged on `master` 2026-10-02). **When:** lookahead scores a position by fast-forwarding a copy to combat damage (`GameStateEvaluator.simulateUpcomingCombatThisTurn` < `PhaseHandler.devAdvanceToPhase`); seen on lethal turns.
- **What:** `devAdvanceToPhase` resolves the copy's stack before each phase change, but the resolver stops when the game ends with triggers still on the stack (e.g. a simulated drain killing the last opponent), and the phase change then throws `IllegalStateException: Phase.nextPhase() is called, but Stack isn't empty.` Hybrid's path catches it inside the AI's decision; full mode's doesn't, so it ended the game. Also: the resolver was handed `aiPlayer.getWeakestOpponent()` from the original game, not the copy, and `resolveStack` swaps that player's controller, i.e. a real-game player's controller while a copy resolves.
- **Evidence (2026-10-02):** seed 5 game 2 (game seed 5000017), full lookahead on Niv: 5 decisions hit it, all in Niv's main phase on table turns 17 and 21, the turns its lifegain drain killed the table; the real game's stack was empty each time. Replayed exactly from the seed.
- **Fix:** patches `02-devadvance-stop-on-game-over` (stop advancing when the game is over or the stack couldn't be cleared; the second case prints `devAdvanceToPhase: stopped ...` to the worker log) and `03-combat-sim-resolve-with-copy-players`.
- **Verified (2026-10-02):** partly. No `Stack isn't empty` and no `devAdvanceToPhase: stopped` line in any patched run (full: seed 5 games 0-2; hybrid: seed 4 games 0-7). But the patched AI plays differently, and the evidence game had not yet reached a lethal drain turn when this was written, so the patch has not yet been seen handling the case.

## Harness safety net (not a fix)

Anything still thrown from Forge's lookahead inside a decision is caught by the harness's controller (`ForgeRunner.SafeControllerAi`): that one decision is made again with lookahead off, and the game goes on with it back on. Every one is logged (`#FP-SIMFB` in the worker log, `sim_decision_log` in the game record: turn, phase, seat, stack, exception, where it was thrown, what was played instead) and summarised in the report's lookahead lines. It should stay at zero: a nonzero count is a new Forge bug to root out, not a result to live with. A crash outside a decision still replays the game from its seed with lookahead off (`sim_fallback`) and prints `#FP-DIAG` lines (exception, turn, departed players, orphaned objects, combat) to the worker log.

## Patches

Fishpond runs stock Forge plus the fixes in `fishpond/forge_patches/*.patch` (unified diffs against the pinned release's source). `forge.patched_classes()` fetches each patched file from the release tag on GitHub, applies the patches with `git apply`, compiles them against the release jar, and caches the classes under `~/forge-cache/<version>/fishpond-patched/<hash>/`; the harness puts that directory ahead of the jar on the classpath, so only those classes change. Forge is still downloaded at run time, never vendored. `setup` prints the patches it built. The cli engine (`--engine cli`, Forge's stock `sim` mode) runs unpatched; it has no lookahead.

| Patch | File | Fixes |
|---|---|---|
| `01-gamecopier-departed-players-and-stale-cards` | `forge-ai/.../ai/simulation/GameCopier.java` | #2 |
| `02-devadvance-stop-on-game-over` | `forge-game/.../game/phase/PhaseHandler.java` | #4 |
| `03-combat-sim-resolve-with-copy-players` | `forge-ai/.../ai/simulation/GameStateEvaluator.java` | #4 |
| `04-aicache-bounded` | `forge-ai/.../ai/AiCache.java` | #3 |
| `05-pilot-cycling-payoffs` | `forge-ai/.../ai/ability/DrawAi.java` | AI play: cycles at useful moments with a cycling payoff out (puzzle `astral_slide_cycle`) |
| `06-pilot-blink-attackers` | `forge-ai/.../ai/ability/ChangeZoneAi.java` | AI play: blinks opponents' attackers out of combat (puzzle `astral_slide_cycle`) |

`-pilot-` patches improve play rather than fix crashes; `FISHPOND_PILOT=off` leaves them out (with the tutor policy and card overrides) for A/B runs.

## Card overrides

`fishpond/forge_card_overrides/*.txt` are full card scripts that replace the release's (`forge.run_home()` builds a mirror of the install whose `res/cardsfolder/cardsfolder.zip` has them swapped in; Forge reads only the zip). Each so far is the release script minus `AI:RemoveDeck:All`: with that hint, `AiController` drops all of a card's spells and abilities, so the AI never casts it. An override is kept only when a puzzle (`fishpond/puzzles/`) shows the AI plays the card sensibly once unflagged; `python3 -m fishpond flags` shows every flagged card in the repo's decks and its status.

None of these is reported upstream yet (searched Card-Forge/forge issues and PRs 2026-10-02).

## Bumping Forge

Forge releases every 6-8 weeks (2.0.11 on 2026-03-02 through 2.0.15 on 2026-09-28); `setup` checks GitHub and says when a newer release is out. To move up:

1. Set `FORGE_VERSION` in `fishpond/forge.py` and run `python3 -m fishpond setup`. It downloads the release, builds the patches, and stops naming any patch that no longer applies.
2. For each patch: if upstream fixed the bug (compare the file on the new tag), delete the patch and its entry here; if the code moved, regenerate the patch against the new tag (`git diff --no-index` of the release file and your edited copy, with paths `a/<repo path>` and `b/<repo path>`).
3. Run `python3 -m fishpond puzzles`: every `-pilot-` patch and card override has a puzzle; a failure means the new release changed that AI path (re-derive the override from the new script with `forge.write_unflag_override`, or drop it if upstream fixed the card). A `known_gap` puzzle that now passes means upstream fixed it.
4. Re-test every entry above on its evidence seed (seeds replay exactly) and remove the entries the release fixed. Then a smoke run per mode (`--sim off`, `hybrid`, `full`) and the hand-audit decks; the report's lookahead lines should show no `sim_fallback` and no search fallbacks.
5. Note the bump and the re-test results in the commit.
