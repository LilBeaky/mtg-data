# Threat model: design rules and lessons

How the pilot judges who is winning and spends its interaction, the user's rules for it, and what measuring it taught. Code:
`fishpond/harness/ThreatModel.java`; Forge patches 57 (counters and removal), 58 (holding mana), 60-63 and 114 (wipes), 69 (whom
to attack, blockers), 105 (the removal floor), 108 (plan pieces): each patch's row in `docs/FORGE_ISSUES.md` has its evidence.
User-facing description: `docs/FISHPOND.md` "Threat model". This was a dated findings log (2026-10-16 to 2026-10-18); the run-by-run
entries are in git history (`git show 9d60724:docs/THREAT_FINDINGS.md`). Condensed 2026-10-30.

## What it scores

Every player, every turn, logged as `#FP-THREAT`: combo proximity (Commander Spellbook combos and the deck's `# loop:` lines,
pieces in hand, on the battlefield and findable), the clock (damage against life and commander damage, double strike counted),
engines and their payoffs, resources and a mana lead, alternate wins, enabler -> payoff links and cycles read from the card
scripts, and self-feeding permanents. It feeds counterspell and removal targeting, the mana hold for answers, wipes judged across
the table, whom to attack and which blockers to keep back, and the turn plan's removal value.

## Calibration (2026-10-16)

24,242 seat-turns (v2.1); "wins within a round" = that seat wins within the next 4 turns, base rate 3.0%.

| Signal | Share of seat-turns | Wins within a round | Share of all wins it flags |
|---|---|---|---|
| threat >= 60 | 25% | 10% | 85% |
| threat >= 100 | 13% | 17% | - |
| clock <= 2 turns | 8.0% | 20% | 53% |
| clock <= 3 turns | 11% | 17% | 63% |
| combo one piece away or closer (combo >= 40) | 16% | 8.9% | 47% |
| combo complete (combo >= 90) | 1.2% | 26% | 11% |
| an engine cycle | 1.6% | 22% | 12% |
| 3+ payoffs | 6.0% | 19% | 37% |
| 30+ mana lead score | 0.7% | 31% | 7% |
| clock <= 2 or combo >= 40 or a cycle | 22% | 11% | 79% |

The total score is a weak absolute predictor; its parts separate well. "One combo piece away" is common and weak alone: many
decks sit one piece away for turns. So decisions act on the parts, not the total, and match the answer to the part. The eventual
winner is ranked first the round before the end in about 63% of decided games (rechecked 2026-10-27). Heavier link weighting
(v2) scored worse than v1; every lighter weighting landed within noise.

## The user's rules

- **Commander penalty:** removing (or countering) a commander loses 12 / 7 / 3 threat points by how cheaply its owner recasts it
  next turn (2+ mana to spare / just affordable / out of reach); none when it's necessary (it completes a combo on the
  battlefield, closes an engine cycle, or its owner's board kills within two turns).
- **Counters see what a spell feeds:** a spell's threat adds 10 per trigger of the caster's it would feed (an entering creature
  into Soul Warden, a wheel into Xyris's Snakes), up to 40, from the same vocabulary as the engine graph. Board and deck
  knowledge only, never the hidden hand.
- **Holding mana for an answer** (patch 58): only with an instant-speed answer that can hit the threat's deck or board, against an
  opponent that is close (1-2 turn clock, a combo a piece away or complete, an engine cycle, 3+ payoffs, a mana lead), when the
  seat isn't the leader and no other opponent is set to answer it. The hold never refuses the seat's own combo pieces, win
  effects, lands, mana abilities or the answers; held mana is released at the end of the turn before the seat's own. The free
  hold (2026-10-23, FORGE_PLAN "Pilot policy") extends this to counterspell decks with an instant-speed use for the mana.
- **Wipes:** refuse when the caster loses as much as anyone or more; cast when every opponent loses a little more, or one loses a
  lot more; weigh what the caster keeps (Wilson wiping around himself); card types and modes right (Austere Command, Farewell).
  Wilson is the yardstick: a deck built to wipe and capitalize. When the seat's life is in danger, a wipe that defuses the next
  combat is cast (patch 114); auras that fall off a wiped or bounced creature count as removed.
- **Wilson's clock:** double strike (the keyword, or granted by an attack trigger like Flaming Fist) doubles; a commander kills
  at 21 commander damage less what it has dealt that player. "Wilson can jumpscare people."
- **The combo floor:** no flat bonus for a combo two pieces away (at most 5, by the deck's tutor share); no projection of a
  voltron burst from hand ("don't overcorrect ... tempo is an aspect of Voltron"): the board-based clock is the reading.
- **Whom to attack:** a kill this turn first, else pressure the threat leader, and hold blockers up against a combat threat.
- **The removal floor** (patch 105) is the user's design: removal is held against every noncreature target except combo pieces,
  3+ mana sources and must-answers, with a floor that moves with the situation. Not changed without the user (FORGE_PLAN "Open:
  pilot failures").

## Lessons for measuring it

- **Match pod seeds, not the base seed.** A study seeds each pod by its position in the pod file (base + 100 x position), so the
  same pod in a different pod file plays different games. An A/B with a different pod file must set each pod's seed to match.
- **Size:** 15-game pods are directional; a gap under about 3 wins per pod is noise. Interaction changes (holds, counter
  targeting) move win rates less than such pods can show; judge them by decisions (who was targeted, holds that paid off)
  and by paired games.
- **Check the cost before blaming new code:** a "slowdown" from the first counters patch was the mismatched seeds above; the
  same seed replayed game for game.
- **Holds measured by episodes** (until the seat's next turn: answer used, threat won during the hold), not refusals: an
  instant is re-asked at every priority, so raw `#FP-HOLD` counts overstate.
