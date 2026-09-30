# Goldfish parser coverage roadmap

For the assistant. Goal: goldfish.py reads as much of the Commander card pool as regex parsing reasonably allows, without reading anything *wrong*. Every number below is measured with `scripts/goldfish_coverage.py report` (weight = 1/√edhrec_rank, so staples count far more than draft chaff).

## Where it stands (2026-09-30, end of the second session)

| Status | Cards | Share | Popularity-weighted |
|---|---|---|---|
| modeled | 9,878 | 31.4% | 33.1% |
| partial | 9,105 | 28.9% | 28.4% |
| blank | 8,697 | 27.6% | 24.2% |
| held | 2,888 | 9.2% | 10.1% |
| vacuum | 413 | 1.3% | 1.2% |
| land* | 486 | 1.5% | 3.0% |

**Fully read (modeled + held + vacuum + override), weighted: 44.4%.**

### The honesty reset (read this before comparing numbers)

The first session ended at 50.9% weighted "fully read". That number was inflated: the second session found that `modeled` was being claimed for text the parser never read.
- Keyword lines nothing reads (kicker, morph, storm, echo, sunburst, ...) were skipped silently. The same fallback's `startswith` also swallowed every unparsed "Enchanted/Equipped creature ..." line.
- "[You may] COST. If you do, EFFECT" ran the effect without paying the cost (326 abilities).
- Any "If COND, EFFECT" whose condition wasn't read ran unconditionally (Skyclave Relic made kicked copies for free).
- A line read in part (Frantic Search's untap, Sensei's Top going back on top) still counted as read.
- Trigger filters ignored words they didn't know: "a creature with power 2 or less", "face-down", "enchanted player controls" all read as "any creature".
- Counts read flat ("for each ...", "where X is ..." read as 1 or as the spell's X).

Making those honest dropped the number to ~42%. Everything since is real reading: 42.3% → 44.4% over the rest of the session, while the misread fixes kept landing.

## The rules that govern everything

**Coverage is worthless if the read is wrong.** `modeled` means every line matched something *and* nothing substantive was left over. A regex that matches a line and produces the wrong effect is worse than an honest "unmodeled", because it silently corrupts the numbers.
- An unreadable cost, condition, count or filter drops the effect (the line is partial/blank). Never make it free or unconditional, and never treat a filter as "any creature".
- Keyword lines are either read, listed as silent (`KW_SILENT`: ward, partner, enchant, landwalk...) or reported as `keyword not modeled`.
- The leftover detector (`_leftover`) marks a line partial when an effect verb or a condition survives the effect regexes. Opponent-directed text doesn't count against it.

**Every change passes three nets before it's pushed:**
1. `goldfish_coverage.py diff HEAD --all`: read every changed reading. Group them with a scratch script by what changed, read the most-played first, and fix misreads before anything else.
2. `tests/goldfish_units.py` (210 checks, deterministic board states) and `tests/goldfish_sweep.py`: every card's effects executed once in a live game, which fails on any exception. The sweep found crashes the fixtures never hit.
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

## Next (by weight in `report`, re-rank each session)

1. **"put N" (3.1%):** mostly "+1/+1 counter" riders on new trigger frames and "put a card from among them into your hand" digs. Also "put a creature card from your hand onto the battlefield" (Sneak Attack, Stoneforge Mystic: a `cheat` effect with the end-step list already built for copies).
2. **"create N" (1.9%):** Treasures on odd triggers, Curse of Opulence (~opp), Caretaker's Talent (level-up classes).
3. **"~ deals" / "it deals" (2.6%):** damage to any target with counted amounts, pingers.
4. **"target creature gets" / pumps on activated abilities (1.8%):** Kessig Wolf Run and friends in `combat_acts`.
5. **Conditions still unread (3.2%: "if you", "if N", "if ~"):** the land conditions (Field of the Dead), "as long as" statics (Anger), counts of cards drawn, spells cast this turn.
6. **Auras on your creatures ("enchanted creature", 1.2%).**
7. **Clones (Phyrexian Metamorph, Spark Double):** enter as a copy; `copy_card` exists.
8. **Phase 3 correctness audit:** ~40 `modeled` cards stratified by popularity, reading compared to Oracle; log the misread rate.

## Working conventions

- Load only the goldfish.py section being changed (grep -n / sed -n), never the whole file.
- One cluster per commit; the message names the cluster and the diff counts.
- Patches that touch many places go in a scratchpad script with an assert per replacement, so a missed anchor aborts before writing anything.
- Update GOLDFISH.md's feature notes and "Not modeled" list whenever something leaves it; update pinned smoke strings when a reading legitimately changes (say why in the commit).
