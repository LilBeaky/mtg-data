# T0: how big is the gap, and what is it made of?

New track (T0–T2): should goldfish.py stop reading cards with regexes and instead execute a structured effect format that an LLM writes once per card? T0 measures before anything is built. All numbers are reproducible with the scripts in `translation/` (see the end). Measured on `main` at `139c128`, 2026-09-30.

## The answer, first

**The gap is mostly engine mechanics, not parsing, and its wording is a long tail.**
- **Wording is overwhelmingly one-off.** The 25,981 unread lines normalize to 19,646 distinct templates. 71% of the unread weight sits in templates that occur exactly once. This is why cluster-by-cluster regex work stalls: every new regex reads a few dozen lines.
- **Mechanics have a head and a tail.** Grouped by the engine feature they need, about 25 mechanic families would take the pool from 44.5% to roughly 68–71% fully read, and 50 families to 76–81%. After that it is a long tail: 100 families give 84–91%, and the last 10% needs hundreds to thousands of one-offs. The ranges come from splitting mechanics coarsely or finely.
- **Translation by itself adds little coverage.** Closing only the pure parse gaps (lines whose every part the engine already executes) is worth roughly +2 to +4 points. A further +3.9 points comes from lines that are simply out of scope for a goldfish: that is a status rule the parser could adopt today, with or without translation.

**Recommendation: go ahead with T1 and T2, with the expectation set correctly.** Translation is not a coverage jump. Its value is that it turns engine work from *mechanic × every wording* into *mechanic × once*. With 71% of the unread weight in unique wordings, the regex route has to rediscover every mechanic in hundreds of phrasings; the translation route pays that once, in a prompt. Whether that trade is worth it depends on one number T0 can't give: how often the translator is wrong compared with the parser. T2 measures that.

## 1. The 44.5% figure, reproduced

`python3 scripts/goldfish_coverage.py report` (29 s):

```
32116 Commander-legal cards (689 lands), 0 compile errors

status     cards   share  weighted
modeled     9850   31.3%     33.1%
partial     9119   29.0%     28.5%
blank       8711   27.7%     24.3%
held        2888    9.2%     10.1%
land*        441    1.4%      2.7%
vacuum       413    1.3%      1.2%
override       5    0.0%      0.1%

fully read (modeled + held + vacuum + override), weighted: 44.5%
```

Same as the roadmap. Weight is 1/√edhrec_rank. Plain lands are left out; land* (a land with an unread line) counts as not fully read. `translation/t0_extract.py` recompiles every card the same way and matches coverage's status on all 32,116 cards (0 mismatches).

## 2. Per-deck coverage

The same definition of fully read, for your three lists (`translation/decks/`). "Unmodeled" is goldfish's `blank`.

| Deck | Cards | Plain lands | Nonland + land* | Fully read | Partial | Unmodeled (blank) | land* | Share fully read | Popularity-weighted |
|---|---|---|---|---|---|---|---|---|---|
| Yusri, Fortune's Flame | 100 | 31 | 69 | 36 (28 modeled, 7 held, 1 override) | 13 | 17 | 3 | **52.2%** | 82.8% |
| Zur the Enchanter | 100 | 32 | 68 | 40 (25 modeled, 12 held, 3 vacuum) | 9 | 13 | 6 | **58.8%** | 74.4% |
| Klauth, Unrivaled Ancient | 101 | 28 | 73 | 37 (36 modeled, 1 held) | 22 | 5 | 9 | **50.7%** | 65.6% |

- Counting the plain lands as read, the decks are 67%, 72% and 64% read.
- The weighted share is higher than the card share because the staples in these lists read better than their tails.
- The Klauth list has 101 cards (88 singles, 8 Forest, 5 Mountain).
- **Read, but approximate.** Vivi Ornitier (Yusri) is `modeled`, yet "{0}: Add X mana in any combination of {U} and/or {R}, where X is Vivi's power" is counted as one mana. goldfish.py notes the approximation, but it doesn't change the status. The land* entries in Zur and Klauth (Exotic Orchard, the check and slow lands) are land* only because of approximation notes, not unread lines.

## 3. What the unread cards need

Every unread line in the three decks was labeled by hand against Oracle text (`translation/t0_handlabels.json`). "Unlocks" means the card becomes fully read once the mechanic exists, taking translation as given for pure parse gaps.

### Yusri (52.2% → 59.4% with translation alone)

| Mechanic | Cards it's the last blocker for | Cards |
|---|---|---|
| **coin flips** | **9** | Yusri, Edgar, Frenetic Efreet, Krark's Thumb, Okaun, Planar Chaos, Squee's Revenge, Tavern Scoundrel, Zndrsplt (plus Stitch in Time with extra turns) |
| delayed triggers | 2 | Full Throttle, Resurrection Orb |
| alternative costs (pitch / discard) | 2 | Dream Halls, Fury of the Horde |
| extra turn | 2 | Nexus of Fate, Stitch in Time |
| one each | 1 each | untap target creature (Seize the Day), storm (Prismari), set life total (The Endstone), replacement effects (Library of Leng), recursion to library top (Academy Ruins), opponent chooses (Gifts Ungiven), mana from a card in hand (Simian Spirit Guide), storm count (Aetherflux Reservoir), improvise (Whir of Invention), cheat from hand (Show and Tell), alt win (Jace, Wielder of Mysteries) |

- Coin flips alone take the deck from 59% to 73%.
- Still blocked after all of those: Arena of Glory (exert and a mana-spend haste rider) and Twenty-Toed Toad (maximum hand size 20, "attack with two or more", alt win).
- Out of scope, and correctly so: Counterbalance, Invert Polarity, the "Partner with" lines.

### Zur (58.8% → 66.2%)

| Mechanic | Unlocks | Cards |
|---|---|---|
| land approximations (check lands etc.) | 4 | the land* entries |
| removal vs `--blockers` | 3 | Step Through, Vedalken Aethermage, Archfiend of Ifnir |
| flicker | 3 | Astral Drift, Astral Slide, Escape Protocol |
| recursion to library top/bottom | 2 | Hall of Heliod's Generosity, Mistveil Plains |
| cycling cost reduction | 2 | Fluctuator, New Perspectives |
| alt win conditions | 2 | Approach of the Second Sun, Triskaidekaphile |
| one each | 1 each | tap-a-Wizard costs (Azami), replacement effects (Words of Worship), prepare (Emeritus of Ideation), symmetric phasing (Disciple of Caelus Nin) |

- Still blocked after all of those:
  - Dour Port-Mage: a "leaves without dying" trigger and bouncing your own creature;
  - Necrodominance: skip draw, pay any amount of life, maximum hand size 5, and an exile replacement;
  - Solitary Confinement: an upkeep discard cost and skip draw.
- 15 of Zur's 68 are held interaction or vacuum. That share is out of scope for a goldfish by design (see §4).

### Klauth (50.7% → 53.4%)

| Mechanic | Unlocks | Cards |
|---|---|---|
| land approximations | 4 | land* entries |
| storm | 2 | Dragonstorm, Stormscale Scion |
| hideaway | 2 | Mosswort Bridge, Spinerock Knoll |
| qualified counts ("creatures with power 4 or greater") | 2 | Shamanic Revelation, Become the Avalanche (and Dragonhawk) |
| cheat from hand | 2 | Last March of the Ents, Broodcaller Scourge |
| one each (18 more) | 1 each | untap lands, "is dealt damage" trigger, damage-threshold trigger, spell-power trigger filter, symmetric ETB draw, station, cascade-like reveal, one-sided creature damage, random choice, offering, multikicker targets, conditional extra combat, "can't be blocked by" vs blockers, eternalize, d20, delayed triggers, impulse draw, damage-this-turn count, convoke, condition on X, activated pumps |

Klauth is the most tail-shaped deck: almost every unread card needs its own mechanic.

### Across the three decks

- **Needed by 3 or more cards:**
  - coin flips (10 cards);
  - removal vs blockers, delayed triggers, alt wins, replacement effects (4 each);
  - qualified counts, cheat from hand, storm / copy spells, recursion to library top, flicker (3 each).
- **Needed by one or two cards:** everything else, 38 mechanics.

### Across the pool

Greedy ranking of mechanic families by weighted fully-read coverage they unlock (translation closing parse gaps is taken as given; `translation/out/t0_report.txt` has the full list):

| After | Coarse families | Fine (catch-alls split per line template) |
|---|---|---|
| translation alone | 52.9% (see caveat below) | 52.9% |
| 10 mechanics | 61.9% | 60.4% |
| 25 | 70.8% | 67.5% |
| 50 | 80.9% | 75.8% |
| 100 | 91.4% | 84.1% |
| 200 | 96.7% | 88.5% |
| 400 | — | 90.8% (3,935 distinct labels still needed by the rest) |

**The first 25, in order:**
1. removal / damage to opponents' creatures (vs `--blockers`)
2. catch-all static rules
3. "as long as" statics
4. restrictions on opponents' creatures
5. Aura/Equipment grants
6. conditions not read
7. counts not read
8. sacrifice effects
9. dig / reveal
10. qualified power and mana-value counts
11. animate / type change
12. "you control" conditions
13. untap permanents
14. impulse / cast from the top
15. leave-the-battlefield triggers
16. this-permanent-state conditions
17. granted quoted abilities
18. discard costs
19. transform / DFC
20. regenerate
21. saga / case / room structure
22. modal triggers with bullet modes
23. coin / dice
24. copy a spell (storm)
25. clones

Each "family" is still real engine work with sub-variants. The coarse column is optimistic about how few mechanics there are; the fine column is pessimistic.

**Caveat on "translation alone".** The +8.4 points above 44.5% split into:
- **+3.9 from out-of-scope lines only.** These are cards whose unread lines are counterspell riders, prevention, opponents' hands and the like. That's a counting rule, not translation.
- **+4.5 from parse gaps as the classifier sees them.** Hand checks found its parse-gap calls right only 25–56% of the time, missing 29–57% of the real ones. The realistic translation-alone gain is +2 to +4 points.

## 4. The modelable ceiling

**What I counted as out of scope, and why.** A goldfish plays your deck against three life totals that never act. By design it can't represent:
- **Answers to opponents' spells and abilities:** counterspells, redirects, "can't be countered", split second. There is nothing to answer except the disruption ladder's scripted events.
- **Opponents' hands, libraries and choices:** discard, hand reveal, "an opponent may", votes, council's dilemma, goad, friend-or-foe. There are no hands and no decision-makers.
- **Protection against attacks and damage that never come:** prevention, fogs, "can't attack you", your own blockers' pumps. Opponents never attack.
- **Stealing or exchanging control of opponents' permanents.** Their boards exist only as `--blockers` stand-ins.
- **Timing permissions** (flash grants). The pilot casts in the main phase and holds interaction by rule.

These lines never block a card: an honest goldfish reads them as "does nothing here" (today's held and vacuum statuses).

Between out of scope and simulatable sit two groups:
- **approx.** Simulatable only with a fixed stand-in, the way `--blockers` and the ~opp taxes work today: removal and restrictions aimed at opponents' creatures, "an opponent chooses" (Gifts Ungiven), opponents' permanents entering.
- **disr.** Matters only against the disruption ladder: regenerate, hexproof, indestructible and phasing grants.

**Chance is not out of scope.** Coins and dice have known distributions, and Monte Carlo samples them exactly. Coin flips are the single biggest mechanic in your Yusri deck.

| Pool, popularity-weighted | Share |
|---|---|
| read and simulated (modeled, override) | 33.2% |
| read as out of scope (held interaction, vacuum) | 11.3% |
| unread, only parse gaps or out-of-scope lines | 8.4% |
| unread, needs sim-scope mechanics only | 39.9% |
| unread, needs an opponent stand-in (approx) | 5.8% |
| unread, disruption-only extras | 1.5% |

- **Could be simulated faithfully:** about 81% of the weighted pool (33.2 + 8.4 + 39.9).
- **With the standard stand-ins:** 88–89%.
- **By design never simulated:** the remaining ~11% is interaction that a goldfish only holds.

For your decks (hand labels, nonland + land*):

| | Read and simulated | Needs sim mechanics | Parse / oos only | Held / vacuum (out of scope) | Needs a stand-in | Land approximations |
|---|---|---|---|---|---|---|
| Yusri | 42% | 39% | 7% | 10% | 1% | 0% |
| Zur | 37% | 22% | 7% | 22% | 6% | 6% |
| Klauth | 49% | 37% | 3% | 1% | 4% | 5% |

Simulatable ceilings: Yusri ~88%, Klauth ~94%, Zur ~72%. Zur's is lower because a fifth of that list is counterspells and removal, which a goldfish holds rather than plays.

## 5. A few mechanics or a long tail?

**Both, at different levels.** The deciding facts:
1. **At the wording level it's a long tail.** 19,646 templates for 25,981 lines; 71% of the weight in one-off templates; the top 100 templates cover 10.6%. Regex coverage grows by tens of cards per pass because each pass buys one wording.
2. **At the mechanic level there is a real head.** 25–50 engine features cover most of what's missing: +15 to +28 points past translation.
3. **The last 10–20 points really are one-offs.** Hundreds of keywords used by 2–40 cards each (squad, bestow, offering, eternalize...), plus rules text that is its own mechanic.
4. **Translation alone is +2 to +4 points.** Everything else needs engine work either way.

**Recommendation: do T1 and T2.** The head of the mechanic curve is where the value is, and it's reachable either way. What differs is the cost per mechanic:
- **Regex route:** every mechanic needs its own wording hunt across the long tail, with each new pattern risking misreads (the Phase 3 audit's families).
- **Translation route:** the wording hunt happens once, per card, in a prompt, and the engine implements "flicker" or "coin flips" once.

The case for translation stands or falls on its error rate, which T2 measures against the parser on the same cards.

**Worth doing regardless of the decision:**
- **The out-of-scope status rule.** +3.9 points of honest "fully read" without new reads. But it changes the headline, so do it as its own commit with an explanation.
- **Coin flips.** One mechanic takes Yusri from 59% to 73%.
- **Fix goldfish's own "needs opponents" tag on symmetric cards.** It fires on "each player's upkeep/draw step" cards that also affect you (Anvil of Bogardan, Ghirapur Orrery, Disciple of Caelus Nin).

## Where this contradicts the roadmap

- **`modeled` isn't approximation-free.** Approximation notes ("variable mana amount counted as one", "mana restriction not recognized; treated as unrestricted", "several mana abilities; modeled the biggest") don't change a nonland card's status. Vivi Ornitier is the example in your lists.
- **The roadmap's "Next" list ranks the wrong thing.** It ranks first-two-word clusters ("put N", "create N"), which mix many mechanics with plain parse misses. Ranked by the engine feature each line needs, the biggest families are removal vs blockers, "as long as" statics, restrictions on opponents' creatures, Aura/Equipment grants, conditions and counts.
- **"Fully read" includes 10.1 points of held interaction.** Those cards are read but not played in clean games. For simulation, the relevant number is 33.2% read-and-simulated plus approximations.

## Method and its limits

- **Extraction.** `translation/t0_extract.py` records every card's status and its unread notes, and maps each note back to its full Oracle line (the notes are cut at 72 characters).
- **Decomposition.** `translation/t0_decompose.py` splits each unread line into its parts: the trigger event or activation cost, conditions, counts and effects. It tests each part with goldfish.py's own readers (`parse_cond`, `ab_cost`, `perm_filt`, `parse_filter`, `clean_dyn`, `parse_fx`). The tables in `translation/t0_mechanics.py` then name whatever is missing.
- **Verdicts:**
  - *parse gap:* every part is a family the engine executes;
  - *engine gap:* some part needs a mechanic;
  - *oos:* out of scope.
- **Validation against hand labels:**
  - verdicts agree on 82 of 99 weighted pool lines (83%) and 85 of 110 deck lines (77%);
  - the classifier over-calls parse gaps (precision 5/9 pool, 3/12 decks);
  - the deck tables above use the hand labels, not the classifier.
- **Mechanic names are my grouping.** A different grouping moves the curve between the coarse and fine columns, but not past them.
- **Nothing in goldfish.py changed.**

## Reproduce

```
python3 translation/t0_extract.py      # ~55 s: statuses + full unread lines -> translation/out/t0_cards.jsonl
python3 translation/t0_decompose.py    # ~10 s: parts and verdicts -> translation/out/t0_lines.jsonl
python3 translation/t0_report.py       # curves, decks, ceiling, validation -> stdout (saved as translation/out/t0_report.txt)
```
`translation/out/` is generated and not committed.
