# Deck yardstick

The user's read on their own decks (2026-10-17): strongest first, and how fast each can win uninterrupted. The user doesn't
estimate win rates ("you get infinitely more reps on these than I do"), so the yardstick is the ordering and the speeds. Other
players' decks in the pods (Heliod, Niv-Mizzet, Xyris, Lumra, Omnath, Witherbloom, Zhulodok, Jarad) aren't covered.

| Rank | Deck | Plan | Win turn (uninterrupted) | Commander target | Weakness |
|---|---|---|---|---|---|
| 1 | Yusri | Explosive, storm-adjacent | 4 (turn 3 possible) | - | Well-placed spot removal |
| 2 | Klauth | Very rampy, aggressive, swings for big damage | 6 | Turn 4 | Board wipes (powers through instead of interacting) |
| 3 | Zur | Slow, grindy control: a position it can't lose, then search out a win | Controls the tempo, no estimate | Turn 3, consistently | Very fast decks; burning an answer it wanted to use proactively |
| 4 | Chulane | Ramp into Chulane, creature storm, dig for Primal Surge (and Shrieking Drake) | 6 possible, 7 average | - | A wipe or a well-placed counter |
| 5 | Erebos | Glass cannon: rush a demon like Valgavoth, play opponents' cards through it | Hard to estimate | - | Interaction; has some tools to bounce back |
| 6 | Wilson | Rush Wilson, keep card flow up, keep the board light, commander damage | 6-7 | - | Losing Wilson (but good at keeping him) |
| 7 | Araumi | Grindy: Self-Traumatize early, toolbox from the graveyard | 7-8 | - | (slows games down) |
| 8 | Ragost | Bracket 2, light field data | - | - | Artifact-focused wipes, light stax |

## The sim against it (2026-10-17)

Win rate and the winner's own turn number at the win; commander first cast, own turn (today's runs: `study100_20261017_p58e`,
`study100_20261017_p61`, `wilson_20261017_p63_V04/V07/V10`).

| Deck | p56 (150 games) | Today | Win turn, median (fastest) | Commander, median own turn | By turn 4 |
|---|---|---|---|---|---|
| Yusri | 2/30 (7%) | 14/80 (18%) | 9 (5) | 4 | 48/80 |
| Klauth | 11/45 (24%) | 20/60 (33%) | 11 (7) | 6 | 20/60 |
| Zur | 1/30 (3%) | 6/80 (8%) | 11 (9) | 6 | 9/80 |
| Chulane | 7/30 (23%) | 7/60 (12%) | 8 (6) | 5 | 9/60 |
| Erebos | 10/30 (33%) | 11/40 (28%) | 14 (11) | 5 | 12/40 |
| Wilson | 21/45 (47%) | 38/100 (38%) | 10 (7) | 3 | 82/100 |
| Araumi | 4/30 (13%) | 3/20 (15%) | 10 (9) | 4 | 13/20 |
| Ragost | 6/45 (13%) | 10/80 (12%) | 12 (9) | 3 | 67/80 |

Read: the sim roughly inverts the user's order for the decks that win by executing a big turn. Yusri, the strongest deck, wins
18% and on its own turn 9 against a turn-4 ballpark; Zur's and Klauth's commanders land on turn 6 against targets of 3 and 4;
Wilson, sixth by the user, is the sim's best of these decks. Four-player interaction slows every deck relative to an
uninterrupted goldfish, but not by five turns. These gaps (fast development, the explosive turn) point at turn sequencing:
the planned work on how the pilot executes its current turn should be judged first by Yusri's win turn and by Zur's and
Klauth's commander turn.
