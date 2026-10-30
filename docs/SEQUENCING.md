# Turn sequencing: design rules and lessons

How the pilot executes its own turn (the user, 2026-10-17): plan the current turn and the removal around it, with a light weight
on setup pieces that pay off turn over turn (mana rocks, ramp, card-flow engines). Judged against the user's deck yardstick
(`docs/DECK_YARDSTICK.md`). Code: `forge.ai.TurnPlan` (Forge patch 64 and its follow-ups: 79, 84, 112, 116 and others, each row in
`docs/FORGE_ISSUES.md`), harness `SetupModel`. This was a dated findings log (2026-10-17); the run-by-run entries are in git
history (`git show 9d60724:docs/SEQUENCING.md`). Condensed 2026-10-30.

## Reproducibility

- The same build and seeds play the same game action for action. Paired games that split "on noise" split because one random
  stream drives both the game (shuffles, mills, coin flips) and the AI's random choices: a change that makes the AI draw one
  more random number shifts every later shuffle of that game. So any patch that changes play makes later games diverge:
  compare distributions, not paired games, across it.
- `python -m fishpond replay POD_DIR GAME` plays one game again with its worker's exact JVM switches and says whether it
  matches the original action for action. Use it before any per-decision debugging.

## How a turn is ordered

At each priority Forge sorts the playable abilities and takes the first that `canPlaySa` accepts. In a pilot seat's own main
phase (stack empty, real games only) the **turn plan** decides instead:
- candidates: the castable spells in hand and the commander (counterspells and X spells left to their own logic);
- mana: what the seat can make now (usable, colors counted), an untapped land drop, rocks that pay themselves back, rituals'
  mana back in the budget, cost reducers and creature-only mana counted, less the mana held for an answer;
- value: the card's value, the deck's plan (combo, key or engine card, feeders), payoff triggers it fires, removal's best target
  by threat, a wipe's margin, the commander (large on the first cast only, patches 112/116), setup value;
- a card from hand spent costs a little (a held card can be cast later; the turn's unspent mana can't), so mana goes to fewer,
  bigger spells; a cheat (Show and Tell) is worth what it would put out;
- the best set within the mana, ordered by tier: combo, information (draws, tutors), mana, wipes, removal, engines, feeders,
  creatures and the commander, the rest;
- followed loosely: the plan's next step goes first; a spell outside the plan is refused only when it would leave too little
  mana for the rest of the plan and the answer reserve; a step Forge's own logic passes on is dropped and the turn re-planned.
  Each plan is logged as `#FP-PLAN` (budget, reserve, steps with tier and value, the best left out).

Still outside the plan and outranking it: encore activations (37), wheels with draw payoffs (53), cheats into a big threat (50),
wins now (49); the vetoes (a loop that already ran, the answer hold) apply as before. Lands are chosen separately (tapped or
untapped, the most mana now, City of Traitors, cycling lands last). `-Dfishpond.turnPlan=false` restores the old sort chain.

**Setup value** (`SetupModel`, derived from card scripts and the deck, not hand-scored): mana a turn and cards a turn, times the
turns left in a nominal 10-turn game, times how much the seat needs mana or cards right now. A turn-2 Talisman is worth about 20
times a turn-9 one. Each deck's setup cards and yields are logged per game as `#FP-SETUP`.

## The user's calls

- Accuracy over speed, as long as the sim keeps moving (the planner made games about 12% longer).
- Wilson: "weigh Flaming Fist very very highly ... it's not hard to get him into 1 shot territory"; a turn-3 Strong Back was
  right (its early value is ramp-like). A commander buff counts only a commander on the battlefield (patch 112).
- The commander is "mission critical once, and diminishes from there" (patch 116).
- A Talisman before held removal (`plan_talisman_over_held_removal`, the user's example).

## Lessons

- The planner's first measured effect was on development, not win rate: across three paired 100-game runs the user's decks won
  32 / 32 / 28 (noise), while Zur's commander on time went 3/40 -> 9/40 and Klauth's 5/20 -> 8/20. Judge sequencing changes by
  commander turn and mana left unused (`fishpond sequencing`, `fishpond pilot`), not win rate, at that size.
- Budget with usable mana, never Forge's estimate: the estimate counts tapped sources and each color of a Talisman (a Talisman
  read as 3, five tapped Mountains as 5).
- Lapsed: a 2026-10-17 fix to re-try a dropped plan step after the board changes (two Chulane Oracle misses) was never committed
  and its scratch tree is gone. Chulane's closers have measured well since; rebuild it only if a miss review points there again.
