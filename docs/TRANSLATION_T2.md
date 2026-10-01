# T2: translating 300 cards to GEF, and what it says about the full pool

Track: T0 measured coverage (`docs/TRANSLATION_T0.md`), T1 defined the format (`docs/GOLDFISH_EFFECT_FORMAT.md`), and T2 is this prototype. The files, prompt and run manifest are in `translation/prototype/` (see its README). Every number below comes from `python3 translation/t2_report.py` (saved as `translation/prototype/t2_report.txt`) unless it says otherwise.

## Decision: partly

**Yes to translation as the way cards get read, but on demand per deck, not for the full pool. Not yet, either: the schema needs one more revision first, and translation only pays off once the engine can execute it.**

The numbers behind it (300 cards, every one audited by hand against its Oracle text):

| | Translator (GEF) | Parser (goldfish.py) |
|---|---|---|
| Misreads: says something the card doesn't do | **3 / 300 (1.0%, 95% CI 0.3–2.9%)**; 1 of the 3 was also caught by the validator | **10 / 300 (3.3%, CI 1.8–6.0%)**; 9 of them on cards it calls fully read |
| Right meaning, but hidden in free text nothing can execute | 13 / 300 (4.3%): a schema hole, now closed in the validator | n/a |
| Too cautious: marked a gap the format could have said | 11 / 300 (3.7%) | n/a |
| Declared or harmless approximations | n/a (the format forbids them) | 25 / 300 (8.3%) |
| Cards hitting a real format gap (something GEF 0.1 can't say) | 69 / 300 (23%) | |

Fully read on the three test decks (T0's denominator: each deck's cards minus plain lands):

| Deck | Parser today | GEF, engine as is | GEF once the engine runs everything GEF expressed | Real format gaps |
|---|---|---|---|---|
| Klauth | 37/73 (50.7%) | 34 (46.6%) | 47 (64.4%) | 24 cards |
| Yusri | 36/69 (52.2%), of which 4 are misreads | 35 (50.7%) | 46 (66.7%) | 17 cards |
| Zur | 40/68 (58.8%), of which 5 are misreads | 44 (64.7%) | 51 (75.0%), of which 2 are misreads | 11 cards |

Why "partly", and not yes or no:
- **The reads are better.** The translator misread about a third as often as the parser. The parser's misreads are also the silent kind: 6 of 142 `modeled` cards (4.2%) drop a material sentence and still say `modeled`.
- **Translation alone buys nothing.** Plugged into today's engine, GEF reads 178 of the 300 cards fully against the parser's 195, and 107 vs 105 on the deck cards. GEF refuses the parser's approximations (Klauth's own mana, Cultivate, Chrome Mox, Fellwar Stone), so it gives back what it gains. The gain (deck cards 53% → 69%) only arrives with an adapter from GEF into the engine plus about 15 engine features. That's engine work, not translation work.
- **The format isn't done.** 23% of the cards hit something GEF 0.1 can't say, including the commander of the Klauth deck (no count for "total power of attacking creatures") and Cultivate/Kodama's Reach (one search, two destinations). Full-pool translation now would have to be redone after GEF 0.2.
- **Full pool is 35–100× this run** (see cost below). It buys cards nobody plays yet. Per deck it's about 3 subagent runs.

## What was done

1. **Selection** (`translation/t2_select.py`): all 198 non-basic cards in the three test decks, except plain lands the parser already reads (status `land`), then the 102 most-played Commander cards outside the decks (by EDHREC rank, same exclusion). 300 cards in 12 batches of 25. Default choice: "most-played across decks" = every deck card, since the three decks share almost nothing.
2. **Translation**: 12 Claude Code subagents (Sonnet), one per batch, in parallel, using `translation/prototype/prompt.md` v1 unchanged. Translators saw only the card text, the format doc, the generated vocabulary and the 18 T1 examples. No parser readings, no validator.
3. **Validation**: `translation/validate.py` (schema + Oracle line coverage).
4. **Comparison**: `translation/t2_compare.py`. Parser status and reading vs GEF status and effect/event/keyword signature, for every card.
5. **Audit**: every card by hand, not a sample (`audit_batchNN.json`). The comparator's "agree" set also hid errors (below), so a stratified sample alone would have under-counted. Rulings in `data/` weren't needed for any verdict. Where a parser reading string looked incomplete, I checked the compiled card in the engine: the Talismans' pain looked dropped but is charged via `k.pain`, while Idol of Oblivion's missing condition is real.

## Reject rate

- **First pass, as run: 14 / 300 rejected (4.7%).** 11 of those were a validator bug, not translator errors. A "Choose one —" block translated as one ability (as the rules say) never matched, because each bullet was normalized separately. Fixed in `validate.py`, and the T1 examples still pass.
- **First pass, with the fixed validator: 3 / 300 (1.0%).** Prairie Stream and Sunken Hollow kept their reminder-only mana line as an ability, which has no text once reminder text is stripped. Requisition Raid joined its three spree lines into one ability and dropped the {1} mode costs. That last one is a real rule-2 violation.
- **Retry with the validator's messages: 3 / 3 accepted.** Requisition Raid came back honest (each mode a format gap).

## Where they disagree, and who was right

The comparator flagged 124 cards. After the audit:
- **Most flags are the translator reading more.** 55 cards the parser doesn't fully read are fully expressed by a correct translation (37 of them nonland): Become the Avalanche, Goreclaw, Aetherflux Reservoir, Twenty-Toed Toad, Ertai Resurrected, Show and Tell, Simian Spirit Guide, Tavern Scoundrel and more.
- **Format can't express it, parser reads it:** Cultivate, Kodama's Reach, Chrome Mox, Thrakkus, Unnatural Growth, Thassa's Oracle's win, Herald's Horn/Roaming Throne/Patchwork Banner (choose a creature type).
- **Parser wrong:** 10 cards (list below).
- **Translation wrong:** 3 cards. Plus 13 free-text reads and 11 over-cautious ones.
- **Status mapping only:** removal like Abrade and Lightning Bolt is `held` for the parser and `modeled` for GEF. Same read, different bookkeeping.

**The comparator misses errors.** Of the 176 cards it called "agree", 10 had an error: 8 free-text reads (now caught by the validator fix) and 2 translator misreads (Astral Drift, Grasp of Fate). So "agree" ≠ "right": about 1% of agreeing cards are still wrong after the fix.

### Translator misreads (3)
- **Astral Drift:** "whenever you cycle this card or cycle another card while this is on the battlefield" became a battlefield-only cycle trigger. Cycling Astral Drift itself from hand no longer triggers. Minor.
- **Grasp of Fate:** "for each opponent, up to one target" became "any number of targets". The notes admit the loosening, which the rules say should have been `unexpressible`.
- **Requisition Raid** (first pass, rejected): dropped the spree costs.

### Free-text reads (13): the schema's fault
`static replacement {text}` and `static restriction {text}` let a translator paste the Oracle sentence and count it as expressed. Cards: Edgar, King of Figaro; Krark's Thumb; Library of Leng; Nexus of Fate; Jace, Wielder of Mysteries; Necrodominance; Hardened Scales; Soporific Springs; Deafening Silence; Rule of Law; Solitary Confinement. Commander's Plate and Ethereal Usher did the same thing through free-string `detail` and pump `keywords`. The meaning is right every time, but nothing can execute it. T1 listed replacement effects as a known limit, yet its status mapping still counted them as expressed. That was my mistake. `validate.py` now counts both statics as unread, and every number in this doc uses that.

### Over-cautious (11)
Chaos Warp (`remove how=tuck` exists), Victimize (`may_pay` sacrifice then recur fits), Ponder, Breaching Dragonstorm, Blast-Furnace Hellkite, Delighted Halfling, Boros Charm and Gemstone Caverns were marked as gaps though the format could say them. Counterbalance, Invert Polarity and Archfiend of Ifnir are opponent-only text labeled `format_gap` instead of `out_of_scope`. These cost coverage, not correctness.

### Parser misreads (10)
Found on cards the parser reads as fully read (`modeled`/`vacuum`/`held`) unless noted:
- **A trailing sentence dropped silently** (the leftover detector misses these): Ancient Silver Dragon (the d20 draw, the card's whole point), Enter the Infinite (the draw-your-library), Reckless Handling (conditional 2 damage), Wishclaw Talisman (the opponent gains control, so the engine tutors three times instead of once), Idol of Oblivion ("activate only if you created a token this turn", so the engine draws off it every turn).
- **Wrong destination:** Long-Term Plans puts the card on top, not third from the top.
- **"Each player can't …" read as opponent-only** (`vacuum`), though it limits you too: Deafening Silence, Rule of Law. This is the same family as the open Maralen/Mornsong entry in the roadmap.
- **Your own blink read as interaction:** Ephemerate (`held`), and Escape Protocol (`partial`, read as "remove an artifact stax piece").

None of these is fixed here. T0–T2 don't change engine behavior. They're listed in the roadmap as open misreads.

## What GEF 0.1 can't say (the 69 cards with a real gap), grouped
- **Counts:** total power of attacking creatures (Klauth), creatures on the whole battlefield (Blasphemous Act), damage dealt to a player this turn (Knollspine Dragon, Broodcaller Scourge), colors in commander identity (War Room), greatest number discarded (Windfall), an amount as a tax (Esper Sentinel), a d20 result as an amount.
- **Destinations and memory:** one search to two zones (Cultivate, Kodama's Reach), third/seventh from the top (Long-Term Plans, Approach), the imprinted card (Chrome Mox), the card that died (Resurrection Orb), graveyard exile (Bojuka Bog), command zone to hand (Command Beacon).
- **Combat and P/T:** double power (Thrakkus, Unnatural Growth), per-creature pump by shared type (Shared Animosity), "creatures that attacked this turn" (Full Throttle), unblocked damage assignment (Zilortha).
- **Choices:** choose a creature type (Herald's Horn, Roaming Throne, Patchwork Banner), opponent chooses (Gifts Ungiven, Signal the Clans, Selvala).
- **Events:** "play a land", either-of-two events (The Endstone), leave without dying (Dour Port-Mage), a source dealing 5+ damage.
- **Rules objects:** phasing (Teferi's Protection, Disciple of Caelus Nin, Frenetic Efreet), manifest, prepared, mana that persists through phases (Klauth, Savage Ventmaw), redirect (Deflecting Swat), start-of-game actions (Gemstone Caverns).

These are the GEF 0.2 candidates, with the free-text statics replaced by real constructs or removed. Several are cheap (counts, split destination, chosen type, play-land event). Phasing and redirect aren't.

## Validator optimism still left
The "today" column uses the validator's engine-support tables, which work per construct, not per field. It is an upper bound. The audit found it too kind on lands: recursion to the library top or bottom (Academy Ruins, Hall of Heliod's Generosity, Mistveil Plains), conditional enters-tapped (the Cinder Glade family, Mystic Sanctuary) and land type grants (Urborg, Yavimaya) count as supported today. They aren't. About 15 cards move from `land*` to `land` on this. It doesn't change the decision, since the "today" column already loses to the parser.

## Cost

- **This run:** 13 subagent runs, about 1.05M subagent tokens in all. About 70k of each run is fixed: reading the format doc, vocabulary and examples. So a batch of 25 costs about the same as a batch of 3. The hand audit of 300 cards took most of this session's own time.
- **Full pool** (about 31,400 non-land cards): 1,260 runs at 25 cards (~100M subagent tokens), or about 315 runs at 100 cards (~35M), if the translators keep the same quality on bigger batches (untested). That's 35–100× this run, before any audit. At the measured 1% misread rate it would import about 300 wrong cards, found only by sampling.
- **Per new deck:** about 60–70 cards not yet translated, so 1–3 runs (0.1–0.25M subagent tokens), plus a hand check of the cards the comparator flags. That's cheap.
- **Engine work to cash it in** (my estimate, not measured):
  - A GEF-to-engine adapter for the constructs the engine already has: 2–3 sessions like this one. It compiles GEF into the same `k.spell` / `k.trig` / `k.acts` tuples, with units per construct and a harness that plays the 300 cards both ways.
  - The engine features the greedy ranking says unlock the most deck cards: flicker, untap, storm, put-from-hand, coin flips and the coin-flip event, "you control your commander", X≥N, impulse, extra turns, riot, convoke, improvise. About 15 features for 25 of the 30 deck cards blocked only by the engine: 2–3 sessions.
  - GEF 0.2 and re-translating the affected cards: 1 session.
  - In all, 5–8 sessions for the deck numbers above (≈53% → ≈69%). The 23% real-gap tail comes after that.

## Contradictions with the roadmap and with T0
- **Roadmap: "`modeled` means every line matched something and nothing substantive was left over."** Not true for 6 of 142 `modeled` cards here (4.2%, CI 2.0–8.9%). Each drops a whole sentence. The leftover detector doesn't catch a final sentence whose verb it treats as already read. This is a second measurement of the misread rate the roadmap calls "unmeasured until the next sample". It's inside the earlier 3–24% interval, and the family is different from Phase 3's.
- **Roadmap: `vacuum` is opponent-only text.** Deafening Silence and Rule of Law are `vacuum`, but they restrict you.
- **T0 predicted translation alone would lift the decks to 53.4 / 59.4 / 66.2%** (Klauth / Yusri / Zur). Measured "GEF on today's engine" is 46.6 / 50.7 / 64.7%. T0 counted parse gaps a translation would fill. It didn't count parser approximations the format refuses, or gaps the format has.
- **T0's modelable ceiling for the decks (Klauth ~94%, Yusri ~88%, Zur ~72%)** assumed every sim-scoped mechanic could be expressed. GEF 0.1 reaches 64 / 67 / 75%. For Klauth and Yusri the ceiling is a claim about a format that doesn't exist yet. Zur's is already reached.
- **T1 status mapping** counted free-text statics as expressed (fixed now, see above).

## Recommendation for T3
1. **GEF 0.2:** replace the free-text statics, fix the pump-keyword and `detail` free strings, and add the cheap gaps (the counts above, split destination, chosen type, play-land event, an owner-relative filter). Tighten the prompt on `out_of_scope` vs `format_gap`. Re-translate only the cards that change.
2. **The adapter,** gated on a harness that plays the 300 cards through both paths and diffs the games.
3. **Engine features in greedy order,** each with a unit.
4. **Fix the 10 parser misreads** in the meantime. They are wrong today whether or not GEF ever ships.
5. **Translate per deck as decks are built.** Revisit full-pool translation only if the per-deck error rate stays at or below 1% over two or three more decks.

## T3 step 1: GEF 0.2 (session 5)

What changed is in `docs/GOLDFISH_EFFECT_FORMAT.md` ("Changes in 0.2"). The run is in `translation/gef02/` (see its README). Every number below comes from the GEF 0.2 section of `translation/t2_report.py`.

**Exit check: passed.** All 300 T2 cards validate as 0.2, the free-text count is 0 (the free-text statics no longer exist in the schema), and the 18 T1 examples still pass.

**What was re-translated.** 46 cards, chosen by `translation/gef02.py affected`:
- the 18 whose 0.1 translations 0.2 rejects (free-text statics, non-enum pump keywords, `detail` on equip/typecycling/offering);
- the cards T2's audit called freetext, conservative or wrong;
- the gap cards a new construct targets.

The other 254 moved over mechanically: version bump, and `lab_man` renamed. The run is three Sonnet subagents with prompt v2, then a 4-card retry.

**Audit of all 46 by hand:**
- **First pass: 44 correct, 2 wrong.** Mosswort Bridge and Spinerock Knoll wrote "play the exiled card" as `cast_free` of any card in exile. That loosens the hideaway card to any exiled card, and "play" to "cast".
- **Two validator changes during the run**, both reported here rather than hidden:
  - The new lint was too narrow. It rejected Sword of War and Peace's `player` on `cards_in_opponent_hand`, which is the precise reading, so the lint now allows it.
  - Herald's Horn left `whose` off its upkeep trigger. All 300 T2 cards write it, but nothing required it. A beginning-of-phase event now needs `whose`, and Herald's Horn was the only card that failed.
- **Retry:** those 4 plus War Room, after `pay_life` became an Amount. All 46 correct after the retry. 0 audit-wrong translations remain in the 0.2 set; T2's three are fixed (Astral Drift, Grasp of Fate) or were already fixed by T2's retry (Requisition Raid).
- **All 11 over-cautious cards now read** as the T2 audit said they should. Caveat: the format doc's new "Which scope?" section uses those same cards as its examples, as the plan asked, so this isn't a blind test of prompt v2. The 4.3% first-pass misread rate is also not comparable with T2's 1.0%. These 46 were picked for being the hard cards. The next new deck is the first clean measurement.

**Results** (fully read = modeled/held/vacuum/override, or `land`):

| | GEF 0.1 (T2) | GEF 0.2 |
|---|---|---|
| Cards with a real format gap | 69 | 57 |
| Fully read, expressed (all 300) | 213 | 244 |
| Fully read, today (all 300) | 178 | 180 |
| Klauth, expressed | 47/73 (64.4%) | 51 (69.9%) |
| Yusri, expressed | 46/69 (66.7%) | 56 (81.2%) |
| Zur, expressed | 51/68 (75.0%) | 58 (85.3%) |
| Klauth / Yusri / Zur, today | 34 / 35 / 44 | 33 / 36 / 41 |

- **Expressed** passes the plan's ≈69% target on all three decks, with 0 audit-wrong reads among those cards. That is still what the engine *would* read once the adapter and features exist (steps 2–3).
- **Today went down on two decks, and that's the honesty fix, not a regression:**
  - The validator's support tables now work per field, so 11 lands moved `land` → `land*`: battle lands, Cinder Glade, Mystic Sanctuary, recursion to the library top, Urborg/Yavimaya. That's the "validator optimism" this doc flagged.
  - Grasp of Fate's 0.1 misread used to count as `modeled`. Its honest read needs an engine feature (a target for each opponent).
  - Commander's Plate's equip-commander is now a field the engine doesn't run.
- **Greedy engine ranking for step 3** (deck cards, 0.2): flicker 5, untap 3, conditional enters-tapped 3, recursion to the library top 3, storm 2, put-from-hand 2, coin-flip rule 2, spell limit 2, then coin flips (4 with the coin-flip-won event). The 0.2 constructs and the per-field rows (enters-tapped, library-top recursion) now show up in it. The plan's step-3 order should be re-ranked from this list.

**Parser misreads.** The 20 `t2_misreads` cards are pinned by three unit checks in `tests/goldfish_units.py`, which fail with `t2_misreads` turned off. The parser headline is unchanged: goldfish.py wasn't touched.

## T3 step 2: the GEF-to-engine adapter (session 5)

`scripts/gef_compile.py` compiles a validated GEF translation into the same Card fields `compile_card` fills from Oracle text. `goldfish.py --gef` uses it for every card with a translation in `data/gef/` (now the 300 T2 cards in 0.2): override > GEF > parser.
- **Exact or refused.** Each GEF ability maps to engine structures, or raises a refusal. A refused ability is unread, and the card says partial or blank with `gef refused: LINE (why)`. Nothing is approximated.
- **One exception, and it errs the other way.** A conditional enters-tapped the engine can't check is compiled as always tapped and still counts as unread (the parser's `('always', 'conditional')`). Dropping a drawback would make the land better than it is.
- **Metadata** (types, cost, P/T, colors) comes from the card data, via `compile_card` on the card with no rules text.

**Exit check: passed, with the deck gap explained.**

| | Result |
|---|---|
| Sweep, parser path / GEF path | 0 errors / 0 errors (32,116 cards; the 300 GEF cards through the adapter) |
| Parity (`tests/gef_parity.py`, 300 cards) | 237 compile identically; 15 differ in structure but play the same games; 48 play differently. **All 63 differences have a recorded cause** (`tests/gef_parity_causes.json`); 0 unexplained. |
| Unit checks per mapped construct (`tests/gef_units.py`) | 37, all passing |
| Fully read today, Klauth / Yusri / Zur | **adapter 27 / 30 / 36** (37.0 / 43.5 / 52.9%) vs the validator's estimate 33 / 36 / 41 and T2's column 34 / 35 / 44 |

**The parity differences, by kind.** Each cause leads with its main kind; many ENGINE and FORMAT-GAP causes also name the parser approximation on the other side.
- **ENGINE (26).** GEF says it, the adapter or the engine can't run it yet. Examples:
  - flicker;
  - if/else on "you control a commander" (Akroma's, Jeska's and Klauth's Will);
  - coin flips and choose-a-number (Yusri);
  - delayed triggers;
  - a library-and/or-graveyard search;
  - a random discard;
  - restricted mana that has to persist (Klauth);
  - an {X} harmonize cost.
- **FORMAT-GAP (18).** Gifts Ungiven, Thrakkus, Unnatural Growth, Teferi's Protection, Esper Sentinel's power-sized tax, Exotic Orchard, Fellwar Stone, Mox Amber, ...
- **PARSER-APPROX (12).** The parser reads an approximation GEF refuses:
  - Sakura-Tribe Elder's sacrifice as an ETB search;
  - The One Ring's flat 1 life;
  - Mossfire Valley and Skycloud Expanse's {1} filters as free mana;
  - Cabal Coffers' extra unconditional {B};
  - riot as haste;
  - Pongify as a clean kill though they get a 3/3.
- **GEF-MORE (6, plus part of Gwenna).** Sword of War and Peace's trigger, Become the Avalanche, Step Through's bounce, The Endstone's cast trigger, Witch's Clinic, Shamanic Revelation.
- **EQUIVALENT (1).** Reanimate: an approximation note on the parser's Target, same games.

**Why "today" is lower than T2's column.** The validator's support tables are per construct, so they called these executable:
- 19 deck cards whose shape the engine can't run: an {X} cost (Kessig Wolf Run), mana restrictions in other words (Maelstrom), "tap an untapped Wizard" (Azami, Patron Wizard), a random discard (Gamble), hand-zone mana (Simian Spirit Guide), a token with abilities (Mage's Attendant), a non-Human team pump mode (Return of the Wildspeaker), a library shuffle (Green Sun's Zenith), and others listed by `t2_report.py`.
- The adapter refuses them instead.

So GEF on today's engine reads fewer of the deck cards than the parser (53%). That's because GEF won't make the parser's approximations, and the engine can't yet run what GEF says. That is step 3's job. The plan's prediction that the adapter alone would reach T2's "today" column was itself an estimate from the same optimistic tables.

**Step 3 ranking** (`t2_report.py`, by adapter refusals; deck cards that reach "expressed" once these are in):
- flicker 3, conditional enters-tapped 3;
- untap one target 2, storm 2, mana restrictions 2, if/else 2, random discard 2, "first spell each turn" 2, the library top as a destination 2, the coin-flip rule 2, activation restrictions 2, tap-an-untapped-creature costs 2, spell limits 2;
- then coin flips with the coin-flip-won event (4).

Several of those are adapter work on constructs the engine already has, not new engine features. 70 deck cards are blocked only by refusals.

## T3 step 3: engine features, in the adapter's order (session 5, in progress)

Six slices, each with unit checks (`tests/gef_units.py`, now 44), the parity causes updated, and units, sweeps and smoke green before its commit:
1. Enters tapped unless you control N lands of a kind (battle lands, Mystic Sanctuary); recursion to the library top; random discard; flicker of your own permanent.
2. if/else; the condition "you control a commander"; untap one target creature; abilities activated only during your turn.
3. Coin flips: flip N or until you lose, with win/lose effects; won-flip triggers; Krark's Thumb (a 3-in-4 win); Edgar (the first flips each turn win); Yusri's chosen number and free casting. The number chosen is pilot policy: the highest that keeps life 5 above the floor.
4. Storm; your own spell limits (Rule of Law, Deafening Silence bind the pilot); skip your draw step.
5. Nth from the top of the library; the counts greatest toughness, this creature's toughness and spells cast this turn; "exactly N cards in hand".
6. Flicker until the next end step, and of all your creatures (Ghostway held as protection); cycle triggers; "when you cycle ~" as a cycling rider.

These engine features run only from GEF: the regex parser never produces them, so the parser path and its headline (44.3%) are unchanged.

**Where the decks stand** (fully read today, measured by the adapter; 0 audit-wrong reads among them):

| Deck | Parser | GEF, after step 2 | GEF, now | Plan's step-3 target |
|---|---|---|---|---|
| Klauth | 50.7% (0 wrong) | 37.0% | **41.1%** | ~64% |
| Yusri | 52.2% (4 wrong) | 43.5% | **59.4%** | ~67% |
| Zur | 58.8% (5 wrong) | 52.9% | **72.1%** | ~75% |

GEF now reads more of Yusri and Zur than the parser, and it reads nothing wrong. **The exit target isn't reached yet,** and Klauth is the gap.

**Why Klauth lags.** Its remaining cards are one-offs:
- mana restrictions (Gwenna, Maelstrom);
- "first spell each turn" triggers (Scourge of the Throne, Shadow in the Warp);
- an {X} activation (Kessig Wolf Run);
- convoke, offering, eternalize, harmonize with {X};
- library-and/or-graveyard searches (Finale of Devastation);
- a team pump filtered by power (Goreclaw);
- put-from-hand (Last March of the Ents).

**The rest of the tail** (`translation/t2_report.py`, 44 deck cards):
- 2 cards each: mana restrictions, put-from-hand (Show and Tell), "first each turn" events, activation restrictions other than your turn, tap-an-untapped-creature costs (Azami, Patron Wizard);
- 1 card each: extra turns (Nexus of Fate, Stitch in Time), graveyard replacement, and about 25 more.

None of them unlocks more than two deck cards. The 64/67/75 targets came from T2's "expressed" column, which assumed every expressed construct gets built. Reaching them means most of that tail, which is about two more sessions at this pace.

