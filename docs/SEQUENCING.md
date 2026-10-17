# Turn sequencing: findings log

How the pilot executes its own turn (the user, 2026-10-17): plan the current turn and the removal around it, with a light
weight on setup pieces that pay off turn over turn (mana rocks, ramp, card-flow engines). Judged against the user's deck
yardstick (docs/DECK_YARDSTICK.md): Yusri's win turn, Zur's and Klauth's commander turn, Chulane's chain. Newest entries at
the bottom.

## 2026-10-17: groundwork

**Games are reproducible.** The same build and seeds play the same game action for action (`threat_p57_20261016` against
`threat_p57b_20261016`: every V05/V06/V08 game identical but for its wall-clock duration). Paired games that split "on noise"
split because one shared random stream drives both the game (shuffles, mills, coin flips) and the AI's random choices: a
change that makes the AI draw one more random number shifts every later shuffle of that game.

**Exact replays:** `python -m fishpond replay POD_DIR GAME` plays one game again with its worker's exact JVM switches
(`runner.java_cmd`, shared with `execute`) and says whether it matches the original action for action. The old scratch replay
left out the overridden-cards list and the win-line audit, so its games drifted (patch 63 couldn't be checked that way). Checked:
games 1 and 17 of `wilson_20261017_p63_V10` (first and third in their worker's JVM) replay identically, so no state carries
across a worker's games.
