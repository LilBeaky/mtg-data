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

## 2026-10-17: what orders a turn today (inventory, patches 01-63)

Forge plays a turn one decision at a time: at each priority `chooseSpellAbilityToPlayFromList` sorts the playable abilities and
takes the first one `canPlaySa` accepts, then asks again. For pilot seats the order is built by a chain of stable sorts, each
later sort the stronger:

| Order (weakest first) | Rule | Patch |
|---|---|---|
| 1 | Forge's `saEvaluator` (highest cost first, +1 for creatures), then creature spells sorted | stock |
| 2 | ramp first (mana dorks, rocks, cost reducers, land fetch; under 7 lands, own turn) | 25 |
| 3 | encore activations first | 37 |
| 4 | commander first when affordable | 24 |
| 5 | trigger payoffs: spells that fire the seat's own payoff triggers, by how many | 54 |
| 6 | the deck's plan: completes a combo 3, key card or engine piece 2, feeds an engine 1 | 54 |
| 7 | board wipes first | 62 |
| 8 | a wheel with draw payoffs out | 53 |
| 9 | cheats in a big threat | 50 |
| 10 | wins now | 49 |

Then `canPlaySa` vetoes or forces, in this order: a loop that already ran this turn (15, veto), the mana hold for an answer (58,
veto), an overloaded wipe judged across the table (61), the commander (24, force), a wheel with payoffs (53, force), cycling with
mana that would go unused (55, force), Jarad eating something big (53, force), payoff spells skipping their card logic's timing
(54), then the card's own AI (with patch 40 lifting "wait for main 2" for permanents, 57 and 60 judging counters, removal and
wipes). Lands are chosen separately (26 tapped/untapped, 29 most mana now, 14 City of Traitors, 27/56 cycling lands).

What the chain can't do: weigh the turn as a whole. Each rule moves one kind of play up the order, and conflicts are settled by
which sort runs last (a key card ranks above ramp; a wipe above both; nothing weighs a Talisman now against removal held up).
Mana is never budgeted across the turn, information (draws, tutors) isn't put before commitments except by accident of cost, and
removal never asks what it opens for combat. The planner absorbs rules 2-7 as value terms and the order rules; 8-10 (wheels,
cheats, wins) and the vetoes stay as they are.

## 2026-10-17: the turn plan (patch 64) and setup value (harness `SetupModel`)

**Setup value** (the user: a light weight on cards that pay off turn over turn, ramp first among them; derived, not hand-scored,
with the user's go-ahead). `SetupModel.yieldOf` reads a card's script and the deck: mana a turn (a rock or dork's net mana, a dork
at 0.8; land ramp's lands, +0.5 per land to hand; extra land drops 0.6; a cost reducer's reduction x the deck's share of spells it
applies to x 1.5 spells a turn) and cards a turn (draw triggers by kind: each upkeep 1, each player's upkeep 3, your spells of a
kind 1.5 x that share, opponents' spells 2, creatures entering 1.2 x the creature share, land drops 0.9, attacks 0.8; activated
draw 0.5). Value = 20 x turns left (a 10-turn game less the seat's own turns) x (mana yield x mana need + 1.5 x card yield x card
need): mana need 1 under 6 mana sources, 0.5 under 9, 0.15 after (1 again with a spell in hand it can't afford); card need 1.2 at
2 cards or fewer, 1.0 to 4, 0.6 to 6, 0.3 after. A turn-2 Talisman is worth about 160 Forge value units, a turn-9 one about 8; a
turn-3 Phyrexian Arena about 210. Each deck's setup cards and yields are logged per game as `#FP-SETUP` for review.

**The turn plan** (`forge.ai.TurnPlan`, pilot seats, own main phases, stack empty, real games only):
- candidates: the castable spells in hand and the commander (counterspells and X spells left to their own logic);
- mana: what it can make now (untapped, usable: a Talisman's color choice counts once), +1 for an untapped land drop, a mana rock
  cast now paying itself back, less the mana Phase 3 keeps up for an answer;
- value: Forge's card value (creatures) or 60 + 25 per mana, + the deck's plan (combo 500, key or engine 200, feeds 60), + 40 per
  payoff trigger it fires, + removal's best target (4 x threat + half the creature's value; no target, not planned), + a wipe's
  margin (refused wipes not planned), + 150 for the commander, + setup value;
- a card from hand spent costs 80 (a card held can be cast on a later turn; the turn's unspent mana can't), so the same mana
  goes to fewer, bigger spells; the commander isn't a card from hand and costs none. A cheat (Show and Tell) is worth the best
  permanent it would put from hand;
- the best set within the mana (every set for up to 12 candidates), ordered: combo, information (draws, tutors), mana, wipes,
  removal, engines, feeders, creatures and the commander, the rest; higher value first within a tier;
- followed: the plan's next step goes first in Forge's order; a spell outside the plan is refused only when it would leave too
  little mana for the rest of the plan and Phase 3's reserve; a step Forge's own logic passes on is dropped and the turn
  re-planned. Each plan is logged as `#FP-PLAN` (budget, reserve, steps with tier and value, the best left out).
It replaces, in the seat's own main phase, the sort keys of patches 25 (ramp first), 24 (commander first), 54 (payoffs, the
deck's plan) and 62 (wipes first); encore (37) still goes first, and wheels, cheats and wins (53, 50, 49) still outrank the plan.
`-Dfishpond.turnPlan=false` restores the old chain.

First full suite (232/237): five regressions, each a gap in the plan, fixed at the root. Klauth (7 mana, cast in 01-63 by patch 24)
lost to Elvish Mystic + Hill Giant + Grizzly Bears, three cards summing past it: the card-held cost above. Show and Tell was valued
as a 3-mana sorcery and refused for leaving too little for Prismari: the cheat value. Utopia Sprawl's extra mana wasn't counted, so
three Forests and a Sprawl read as 3 and Rumbling Baloth wasn't planned: "whenever enchanted land is tapped for mana" triggers now
count in the turn's mana (and in setup value). Araumi's encore grant (no mana cost) went behind the planned spells, which spent
the mana the encore needed: activated abilities that cost no mana and are the deck's plan or the commander's lead the plan, and the
encore sort runs after the plan's (it had run before, so the plan's order buried it).

Puzzles (two-player, so no deck plan; fail on 01-63 unless noted): `plan_uses_the_mana` (Gray Ogre + Goblin Piker with five
Mountains, not Hill Giant alone), `plan_information_first` (Preordain before Wind Drake), `plan_removal_before_creatures`
(Lightning Bolt before Gray Ogre), `plan_setup_engine_early` (Phyrexian Arena on turn 3 over a 3-mana creature); guards that pass on
01-63 too: `plan_talisman_early`, `plan_talisman_over_held_removal` (the user's example). A first version budgeted with Forge's mana
estimate, which counts tapped sources and each color of a Talisman (a Talisman read as 3, five tapped Mountains as 5).
`plan_ritual_pays_back` (Dark Ritual then Phyrexian Rager off one Swamp, in main 1): Forge's ritual logic passes on a ritual in
main 1, so a planned ritual whose mana the plan needs is cast (`TurnPlan.force`), and a ritual's mana counts back in the budget.

**Baseline before the planner** (`seqbase_20261017`: build 01-63, pods V05-V09, 20 games each, seed 20261414; 100 games, 99 ended
naturally, 1 timeout, 0 fallbacks). `python -m fishpond sequencing seqbase_20261017`, the user's decks against the yardstick:

| deck | wins | win turn median (fastest) | target | commander turn | target | turns 1-6: no land / idle 2+ / mana left |
|---|---|---|---|---|---|---|
| Yusri | 5/40 | 7 (7) | 4 | 4 | | 8% / 9% / 0.9 |
| Klauth | 7/20 | 10 (7) | 6 | 6 (5/20 on time) | 4 | 13% / 8% / 1.7 |
| Zur | 1/40 | 14 (14) | | 6 (3/40 on time) | 3 | 14% / 5% / 0.6 |
| Chulane | 6/20 | 8 (6) | 7 | 5 | | 14% / 7% / 1.4 |
| Erebos | 4/20 | 10 (9) | | 5 | | 9% / 2% / 0.4 |
| Wilson | 8/20 | 8 (7) | 7 | 3 | | 11% / 7% / 1.0 |
| Ragost | 1/20 | 12 | | 3 | | 11% / 5% / 1.1 |

(Win turn is the winner's own turn count; commander turn the seat's own turn the commander first resolved; "idle 2+" the share of
own turns 1-6 ending with 2+ usable mana unspent and a castable card in hand.) The gap the planner is aimed at: Klauth and Zur
land their commanders two to three turns late, Klauth leaves 1.7 mana a turn on the table early, Yusri wins three turns late.
Opponents for scale: Heliod 24/40, Niv-Mizzet 12/20, Xyris 11/40.

## 2026-10-17: first paired run with the planner (`plan_20261017`)

Same pods, seed and game count as the baseline (V05-V09, 20 games each, seed 20261414), build 01-64 as committed in 01e9585.

| deck | wins (base -> plan) | win turn median (fastest) | commander turn (on time) | turns 1-6 idle 2+ / mana left |
|---|---|---|---|---|
| Yusri | 5/40 -> 7/40 | 7 (7) -> 8 (4) | 4 -> 4 | 9% / 0.9 -> 14% / 1.1 |
| Klauth | 7/20 -> 6/20 | 10 (7) -> 10 (9) | 6 (5/20) -> 7 (6/20) | 8% / 1.7 -> 8% / 1.5 |
| Zur | 1/40 -> 3/40 | 14 -> 11 | 6 (3/40) -> 5 (9/40) | 5% / 0.6 -> 12% / 0.9 |
| Chulane | 6/20 -> 3/20 | 8 (6) -> 10 (9) | 5 -> 5 | 7% / 1.4 -> 6% / 1.2 |
| Erebos | 4/20 -> 1/20 | 10 (9) -> 13 | 5 -> 5 | 2% / 0.4 -> 2% / 0.5 |
| Wilson | 8/20 -> 9/20 | 8 (7) -> 8 (7) | 3 -> 3 | 7% / 1.0 -> 6% / 1.0 |
| Ragost | 1/20 -> 1/20 | 12 -> 12 | 3 -> 4 | 5% / 1.1 -> 3% / 1.1 |

Win counts at 20-40 games are inside the noise (a 20-game rate is +-22 points); the commander turns and idle shares are the
readable part. Zur's commander came down on time three times as often (3/40 -> 9/40). Idle turns went *up* for Zur and Yusri,
and the held cards said why:
- **Planned steps Forge never considers.** Zur held Words of Worship 12 times (2 in the baseline): the deck's plan rates it, the
  plan picked it, but Forge drops AI:RemoveDeck:All cards from its candidates before forming any opinion, so the step was never
  declined; the plan kept it and refused Zur's castable spells for leaving too little mana for it. Fixed: before ordering, planned
  steps missing from Forge's full candidate list are dropped and the turn re-planned (`TurnPlan.prune`; puzzle
  `plan_drops_what_forge_wont_cast`, fails before the fix).
- **Setup value on cycling.** `SetupModel` counted any activated draw as an engine, cycling included (Complicate, Miscalculation,
  Neutralize scored as 0.5 cards a turn), and gave yields to instants and sorceries. Now only abilities used from the battlefield
  count, and a spell yields only its land ramp.
- Yusri's held cards are mostly instants kept up on purpose (Swan Song, Reality Shift, Pongify; Phase 3 holds), plus Lightning
  Greaves and Aetherflux Reservoir, which the plan rates low (60 + 25 per mana, less a card held): candidates for the deck's plan
  rather than the planner.

The run also had 20 lookahead fallbacks, all from one game (Archdruid's Charm with a stale fight target; Forge patch 65) and 2 AI
timeouts finished in hurry mode. The planner run is repeated with the fixes.

## 2026-10-17: second paired run (`plan2_20261017`, build cb7079e) and what it found

| deck | wins base / plan / plan2 | commander on time base / plan / plan2 | turns 1-6 idle 2+ (plan2) |
|---|---|---|---|
| Yusri | 5/40, 7/40, 3/40 | (cmd turn 4 throughout) | 14% (deliberate holds: Swan Song, Reality Shift, Pongify; Show and Tell waiting for a 4+ permanent) |
| Klauth | 7/20, 6/20, 9/20 | 5/20, 6/20, 8/20 | 7% |
| Zur | 1/40, 3/40, 3/40 | 3/40, 9/40, 9/40 | 9% (12% in plan; 5% base, where Phase 3 holds count too) |
| Chulane | 6/20, 3/20, 3/20 | (cmd turn 5 throughout) | 5% |
| Erebos | 4/20, 1/20, 4/20 | | 3% |
| Wilson | 8/20, 9/20, 9/20 | (cmd turn 3 throughout) | 6% |
| Ragost | 1/20, 1/20, 1/20 | | 3% |

The user's seven decks won 32 games in the baseline and 32 in plan2: no measurable win-rate change at this size. What did change,
and held across both planner runs: Zur's commander on time three times as often, Klauth's more often, Klauth's early unspent mana
1.7 -> 1.3. Chulane's 6 -> 3 repeated, so it was traced rather than called noise: the win-line audit (`fishpond lines`) showed its
closers going unplayed under the plan: Oracle with a tiny library played in 2 of 5 games it was available in (4 of 4 before),
Primal Surge 5 of 7 (4 of 4), and two games lost to decking. The old order put win-now plays, cheats and wheels first; the plan
valued them as ordinary spells (Primal Surge, 510, lost to Chulane plus four cheap creatures summing past it) and its refusal
check exempted only a spell whose own effect wins (Oracle's win is a trigger). Fixed in patch 64: closers get combo tier and a
5000 bonus, a library cheat is worth 50 per permanent it would put, and closers are never refused (`plan_closer_primal_surge`,
fails before the fix).

Setup tables, reviewed per deck (`#FP-SETUP`, now made at the first turn: an eliminated player's cards leave the game, so tables made
at game end came out empty for five decks). Fixed in `SetupModel`: one card's mana a turn counts up to 3 (Selvala, Heart of the
Wilds read 11 off a late Klauth board); mana abilities used from hand don't count (Simian Spirit Guide read as a dork); a land search
counts only when its controller searches (Path to Exile and Assassin's Trophy read as ramp).

Also from plan2: 4 lookahead fallbacks, all Paradigm copies (Decorum Dissertation; Forge patch 66), and 2 AI timeouts in Forge's own
combat prediction on Xyris's Snake board (hurry mode finished both). Games run about 12% longer with the planner (median 111 s ->
124 s); the user: accuracy over speed as long as the sim keeps moving.
