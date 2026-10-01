# Goldfish parser coverage roadmap

For the assistant. Goal: goldfish.py reads as much of the Commander card pool as regex parsing reasonably allows, without reading anything *wrong*. Every number below is measured with `scripts/goldfish_coverage.py report` (weight = 1/√edhrec_rank, so staples count far more than draft chaff).

## Where it stands (2026-09-30, third session, after the Phase 3 audit)

| Status | Cards | Share | Popularity-weighted |
|---|---|---|---|
| modeled | 9,850 | 31.3% | 33.1% |
| partial | 9,119 | 29.0% | 28.5% |
| blank | 8,711 | 27.7% | 24.3% |
| held | 2,888 | 9.2% | 10.1% |
| vacuum | 413 | 1.3% | 1.2% |
| land* | 441 | 1.4% | 2.7% |

**Fully read (modeled + held + vacuum + override), weighted: 44.5%.** Classes and manlands added reads after the second-session rewrite of this file. The audit then took about 100 wrongly `modeled` cards out and added about 40 correct reads, so the number held steady while getting more accurate.

### The honesty reset (read this before comparing numbers)

The first session ended at 50.9% weighted "fully read". That number was inflated: the second session found that `modeled` was being claimed for text the parser never read.
- Keyword lines nothing reads (kicker, morph, storm, echo, sunburst, ...) were skipped silently. The same fallback's `startswith` also swallowed every unparsed "Enchanted/Equipped creature ..." line.
- "[You may] COST. If you do, EFFECT" ran the effect without paying the cost (326 abilities).
- Any "If COND, EFFECT" whose condition wasn't read ran unconditionally (Skyclave Relic made kicked copies for free).
- A line read in part (Frantic Search's untap, Sensei's Top going back on top) still counted as read.
- Trigger filters ignored words they didn't know: "a creature with power 2 or less", "face-down", "enchanted player controls" all read as "any creature".
- Counts read flat ("for each ...", "where X is ..." read as 1 or as the spell's X).

Making those honest dropped the number to ~42%. Everything since is real reading: 42.3% → 44.4% over the rest of the session, while the misread fixes kept landing.

## Translation track T0–T2 (fourth session): where it stands

A separate track, not the Phase 0–3 parser work: have an LLM translate Oracle text once into a checkable format (GEF) and let the engine execute that. Write-ups: `docs/TRANSLATION_T0.md` (measurement), `docs/GOLDFISH_EFFECT_FORMAT.md` (format), `docs/TRANSLATION_T2.md` (300-card prototype). `goldfish.py` was not changed; the headline 44.5% above is untouched.

- **T0:** 44.5% reproduced. The unread weight is a long tail: 19,646 distinct line templates for 25,981 unread lines, and the top 100 templates cover 10.6% of the weight. Parser clusters can't finish it; that's the case for translation.
- **T1:** GEF 0.1, a closed JSON Schema with an explicit `unexpressible` escape and a status mapping to modeled/partial/blank/held/vacuum/land. The validator rejects instead of guessing.
- **T2:** 300 cards (all three test decks plus the top 102 of the pool), translated by subagents, every card audited by hand.
  - Rejects: 3/300 first pass after fixing a validator bug (14 as run), 0 after one retry.
  - Translator misreads: 3/300 (1.0%). Parser misreads on the same cards: 10/300 (3.3%). 13 translations hid their meaning in free-text constructs (a schema hole, now counted as unread), 11 were over-cautious, 69 hit a real format gap.
  - Deck cards fully read: parser 53%. GEF on today's engine is about the same, 54%, because it refuses the parser's approximations. GEF once the engine runs what it expresses: 69%.
  - **Decision: partly.** Translate per deck as decks are built, after GEF 0.2 and a GEF-to-engine adapter; not the full pool (35–100× the prototype's cost, and the format still has gaps). T3 plan in `docs/TRANSLATION_T2.md`.
- **T3 step 1, GEF 0.2 (fifth session, 2026-09-30):** free-text statics replaced by constructs, keywords an enum, `detail` only on silent keywords, the cheap T2 gaps, per-field validator support, prompt v2. 46 T2 cards re-translated: 44/46 right on the first pass, 46/46 after one retry. Real format gaps 69 → 57. Deck cards fully read *as expressed*: Klauth 69.9%, Yusri 81.2%, Zur 85.3% (T2: 64.4 / 66.7 / 75.0), 0 audit-wrong. *Today* is down on two decks (Klauth 34 → 33, Zur 44 → 41) because the validator stopped counting 11 lands and two 0.1 over-reads as executable. Details in the T3 section of `docs/TRANSLATION_T2.md`.
  - **Headline unchanged at 44.4%:** goldfish.py wasn't touched. The 20 `t2_misreads` cards are now pinned by unit checks.

## The rules that govern everything

**Coverage is worthless if the read is wrong.** `modeled` means every line matched something *and* nothing substantive was left over. A regex that matches a line and produces the wrong effect is worse than an honest "unmodeled", because it silently corrupts the numbers.
- An unreadable cost, condition, count or filter drops the effect (the line is partial/blank). Never make it free or unconditional, and never treat a filter as "any creature".
- Keyword lines are either read, listed as silent (`KW_SILENT`: ward, partner, enchant, landwalk...) or reported as `keyword not modeled`.
- The leftover detector (`_leftover`) marks a line partial when an effect verb or a condition survives the effect regexes. Opponent-directed text doesn't count against it.

**Every change passes three nets before it's pushed:**
1. `goldfish_coverage.py diff HEAD --all`: read every changed reading. Group them with a scratch script by what changed, read the most-played first, and fix misreads before anything else.
2. `tests/goldfish_units.py` (224 checks, deterministic board states) and `tests/goldfish_sweep.py` (all 32,116 Commander-legal cards, ~30 s): every card's effects executed once in a live game, which fails on any exception. The sweep found crashes the fixtures never hit.
3. `tests/smoke.py` (70 checks, ~2.5 min). Run it in a separate git worktree at the commit being pushed, so editing can continue. Read the result before pushing.

## Done

- **Phase 0/1 (session 1):** safety net, removal read against `--blockers`, opponent-only lines.
- **Phase 2 passes (session 1):** draw/cast triggers, counters, look-at, sacrifice-cost spells, Skullclamp.
- **Session 2, correctness:** the honesty reset above. Also:
  - pod searches tied to the sacrificed permanent; Eldritch Evolution onto the battlefield;
  - Etched Oracle's four-counter cost; "its controller draws" isn't you; "target player mills" only with a graveyard payoff;
  - quoted granted text isn't the card's own interaction; CR 704.5f toughness-0 deaths;
  - -1/-1 costs on your own creature go where they hurt least.
- **Session 2, mechanics:**
  - Mana: sac-for-mana outlets; rituals and dynamic mana; conditional mana (metalcraft); Chrome Mox / Mox Diamond.
  - Counts: converge/sunburst; cascade; devotion; "for each [subtype]"; "X, where X is ..." everywhere; kicker/multikicker.
  - Doublers and tribes: token doublers; trigger doublers (cause and source); "the chosen type" = the deck's tribe.
  - New structures: sagas (CR 714) incl. Urza's Saga; token copies; conditions (`parse_cond`); qualified trigger filters.
  - Individual cards: Black Market Connections, Harrow / Crop Rotation, Natural Order, Chaos Warp, Victimize, Animate Dead, Frantic Search, Mana Vault, Sensei's Top, amass, artifact/enchantment removal as stax answers, Krenko's tap-over-attack.
- **Session 3, mechanics:**
  - Classes (CR 716): each level is its own compiled card; level-up is a sorcery-speed act.
  - "Return ~ from your graveyard" activations (Reassembling Skeleton).
  - Tap-a-creature mana (Springleaf Drum) and "activate only if you control a Swamp or a Mountain" land mana (the Verges).
  - Manlands: Mutavault, Restless lands, Celestial Colonnade, Den of the Bugbear.
- **Session 3, correctness:** the Phase 3 audit below.

## Phase 3 audit (third session)

**Sample.** 40 `modeled` cards, seed 7, 10 from each of four popularity strata, each reading compared to Oracle text.

**Result: 4 misreads (10%).**
- Cloud Key: "the chosen type" was a card type, not the tribe.
- Descent into Avernus: "each player creates X Treasures" was dropped.
- Dwynen: "1 life for each attacking Elf" was read as a flat 1.
- Crowded Crypt: decayed tokens are treated as ordinary tokens. This one is a known approximation and was left alone.

**Reading the diff of those fixes found the same families all over the pool.** These were real misreads on cards that said `modeled`:
- "N for each X" read flat on face damage and life (Last Stand, Guiltfeeder, Aven Gagglemaster).
- A qualified count read as the generic one ("colorless creature", "artifact and/or enchantment", "basic Island", "nonland permanent", "snow lands", "permanents you control but don't own" all counted as creatures/permanents/lands). The root cause was an unanchored `re.search` in `dyn_key`, plus a pump parser gluing two clauses together ("…you controlgain trample").
- "attacks alone" and battalion dropped.
- An "except it's a 3/3 Dragon" copy read as a plain copy.
- Quoted "sacrifice this token at end step" copies kept forever: parse_fx lost the quotes in recursive calls.
- "loses that much life" read outside gain triggers.
- "artifact creature" read as any artifact; "an artifact and an enchantment" as one permanent.
- "no other" counted ~ itself.
- An ability word before "If" (adamant, spell mastery…) made the condition invisible, so the effect always applied.

All fixed or made honest, with seven audit checks in `goldfish_units.py` that fail on the old parser.

**Standing lesson.** The 10% sample rate understates the risk of a *family*. When a sampled misread is found, grep for the construction across the pool and read the diff, don't just fix the one card. Repeat the sampled audit each session (new seed) and log the rate here.

## Next (by weight in `report`, re-rank each session)

Cluster shares from `report` after the audit (share of weighted unmodeled lines).

1. **"put N" (3.2%):** mostly "+1/+1 counter" riders on new trigger frames and "put a card from among them into your hand" digs. Also "put a creature card from your hand onto the battlefield" (Sneak Attack, Stoneforge Mystic: a `cheat` effect with the end-step list already built for copies).
2. **"create N" (2.0%):** Treasures on odd triggers, Curse of Opulence (~opp).
3. **"~ deals" (1.9%):** damage to any target with counted amounts, pingers.
4. **"target creature gets" / pumps on activated abilities (1.7%):** Kessig Wolf Run and friends in `combat_acts`.
5. **Conditions still unread (4.0%: "if you" 1.7, "if N" 1.5, "if ~" 0.8) and "as long as" statics (1.4%):** the land conditions (Field of the Dead), Anger, counts of cards drawn, spells cast this turn.
6. **Auras on your creatures ("enchanted creature", 1.2%).**
7. **Clones (Phyrexian Metamorph, Spark Double):** enter as a copy; `copy_card` exists.
8. **Unread conditions worth reading next:** adamant (three mana of one color spent), delirium (card types in the graveyard), revolt, "for each other creature" (count minus ~), "1 plus the number of", "twice the number of", snow permanents.
9. **Re-run the sampled audit** with a new seed after each cluster pass.

## Known misreads still open

These readings are wrong or approximate, and the parser knows it only where the card says partial:
- **Crowded Crypt:** decayed tokens are read as normal tokens. They can block and attack every turn, which is an overcount.
- **Maralen of the Mornsong, Mornsong Aria, Gibbering Descent:** "each player's draw step/upkeep, that player ..." is read as opponent-only. On your own turn it's you. These cards are partial.
- **Graveyard Shovel, Cellar Door:** "If it's a creature card, you ..." applies unconditionally. `COND_OWN` skips "it's a", so reveal checks aren't read. These cards are partial.
- **Horrifying Revelation:** "target player ... then mills a card" is read as your own mill.
- **Search for Glory:** the tutor filter drops "a legendary card", so it finds fewer cards than it should. That's an undercount.
- **"for each X on the battlefield"** (Shepherd of Rot, Timberwatch Elf, Fruition) counts only your own permanents. Opponents' boards are unknown, so it undercounts.
- **Copies with "except it has flying"** don't add the keyword. That's an undercount.
- **Polymorph, Blessed Reincarnation:** "The player puts that card onto the battlefield" is flagged unread although it's the opponent's. The card is wrongly partial, which is harmless.
- **Found by the T2 audit (fourth session), fixed honestly** by `t2_misreads` in goldfish.py (the wrong effect is dropped or corrected and the card says partial/blank with an `unread (T2 audit)` note; 20 cards pool-wide incl. Eidolon of Rhetoric, Arcane Laboratory, Momentary Blink; headline 44.5% → 44.4%):
  - A final sentence dropped while the card says `modeled`: Ancient Silver Dragon (the d20 draw), Enter the Infinite (the draw), Reckless Handling (conditional damage), Wishclaw Talisman (the opponent gains control, so it tutors three times instead of once), Idol of Oblivion (the draw's token condition, so it draws every turn). The leftover detector misses these.
  - Long-Term Plans puts the card on top instead of third from the top.
  - Deafening Silence and Rule of Law are `vacuum`, but "each player can't" limits you too. Same family as Maralen above.
  - Ephemerate is `held` as interaction, and Escape Protocol's flicker is read as stax removal.
- **Measured again:** T2 audited every one of 142 `modeled` cards in its 300. 6 were misreads, 4.2% (95% CI 2.0–8.9%). This is a different sample from Phase 3 (deck cards plus top staples, not strata), so it isn't a trend, but it is inside the earlier interval.
- **Unsampled:** the audit was 40 cards. 4/40 gives a 95% interval of roughly 3–24% for the misread rate among `modeled` cards. The family sweep after it removed the biggest known sources, but the true rate is unmeasured until the next sample.

## Working conventions

- Load only the goldfish.py section being changed (grep -n / sed -n), never the whole file.
- One cluster per commit; the message names the cluster and the diff counts.
- Patches that touch many places go in a scratchpad script with an assert per replacement, so a missed anchor aborts before writing anything.
- Update GOLDFISH.md's feature notes and "Not modeled" list whenever something leaves it; update pinned smoke strings when a reading legitimately changes (say why in the commit).
