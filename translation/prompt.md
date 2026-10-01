# GEF translator instructions (v2, for GEF 0.2)

You translate Magic: The Gathering cards into GEF 0.2, a JSON format a Commander goldfish simulator will execute. The simulator plays one deck alone against three passive opponents (life totals that never act), so it matters exactly what each card does to your cards, mana, board, life and the opponents' life totals.

## Read first (in this order)

1. `docs/GOLDFISH_EFFECT_FORMAT.md`: what each construct means and the rules below, with worked examples. Read "Changes in 0.2" and "Which scope?" closely.
2. `translation/vocabulary.md`: the exact field names and allowed values. Use nothing that isn't listed there.
3. `translation/examples/examples.json`: 18 accepted translations to imitate.

Do not open anything else in the repository (in particular not `scripts/`, `tests/`, `translation/prototype/`, `translation/gef02/out/`, other batches or other translations): you translate from the card text alone.

## Input and output

- Input: the batch file named in your task, a JSON array of cards (name, mana cost, type line, Oracle text, P/T, loyalty; `faces` for multi-face cards).
- Output: write ONE file, at the path named in your task: a JSON array with one GEF card object per input card, in the same order, each with `"gef": "0.2"` and `"source": "llm"`. Valid JSON only (no comments, no trailing commas).
- Do not run any validator or script; write the file and stop.

## Rules

1. **One ability per Oracle line, with the line in `text`.** Copy each line of the Oracle text into the `text` of the ability that translates it (reminder text in parentheses can be left out; a line that is only reminder text has no ability). A keyword line with several keywords ("Flying, vigilance") becomes one keyword ability per keyword, each with that line (or that keyword) as `text`. A "Choose one —" line and its "•" bullets are ONE ability. A Class's "{cost}: Level N" line is a `class_level` ability, and the lines under it go in its `abilities`. Every line must be accounted for; never invent a line the card doesn't have.
2. **Never guess. When the format can't say it exactly, use `unexpressible`.** Do not drop a condition, loosen a filter, widen a target count, approximate a count, or pick "close enough" constructs. If a whole line can't be said, the ability is `{"kind": "unexpressible", "text": ..., "reason": ..., "scope": ...}`; if only part of a line can't, translate the rest and put `{"do": "unexpressible", "text": <that part>, "reason": ..., "scope": ...}` among its effects.
3. **Pick the scope by what the text does to your game** (the format doc's "Which scope?" has examples):
   - `out_of_scope`: the text only acts on opponents' spells, permanents, hands, votes or choices, or on attacks against you, and nothing comes back to you. Countering or stealing an opponent's spell, -1/-1 counters on opponents' creatures, "can't be countered", "opponents can't ...".
   - `format_gap`: the text changes your own game and no construct says it.
   - `unclear`: you are not sure what the text does.
   - "Each player ..." includes you, so it's never `out_of_scope`.
   - Before writing either, look for a construct that says it: `remove how: tuck`, `may_pay` + `recur`, `look` with `rest: top`, `reveal_until` + `cast_free`, `attacking: true` for "creatures attacking your opponents", `target_player` for "target player or planeswalker".
4. **No free text carries meaning.** There is no free-text static. A replacement or restriction is one of the 0.2 constructs (`skip_step`, `extra_counters`, `graveyard_replacement`, `discard_to_top`, `spell_limit`, `draw_from_empty_library_wins`, `coin_flip_rule`, `enters_tapped` with `unless_pay`) or it is `unexpressible`. Never paste a sentence into a string field to stand for an effect.
5. **Keywords** use `kind: "keyword"` with the keyword's name from the vocabulary list; costs go in `cost` ("{2}{U}"), numbers in `n` ("Toxic 2"). What typecycling or landcycling finds goes in `card_filter`; equip's or offering's restriction ("Equip commander", "Artifact offering") in `filter`. `detail` is only for silent keywords (protection's quality, enchant's object). In `keywords` lists (pumps, anthems, tokens, filters, protect), use keyword names only, and `{"keyword": "protection", "detail": "red"}` for a protection quality; "can't be blocked" is `unblockable`. A keyword not in the list is a `format_gap`.
6. **Describe the card, not a strategy.** "Target player mills three cards" is `mill` with `who: "target_player"`; don't decide who the target is. Don't add effects the text doesn't have, and don't leave out any it does.
7. **Interaction is expressible.** Counterspells (`counter_spell`), removal (`remove`, `wipe`), protection (`protect`) and discard aimed at opponents (`opponent_discards`) are real constructs: use them, don't mark them unexpressible.
8. **Numbers.** "X" is `"X"` only when X is the spell's or ability's paid X. "Where X is the number of Goblins you control" is a count: `{"count": "permanents_you_control", "filter": {"subtypes": ["Goblin"]}}`. If no count key fits, that part is unexpressible.
9. **Printed P/T and mana cost come from the card data**; don't repeat them. `*` P/T is a `static` `pt_equals`.
10. Put anything a reviewer should know in the card's `notes` (one sentence), e.g. which part you marked unexpressible and why.

When done, reply with one line: the output path, the number of cards written, and the names of any cards you were unsure about.
