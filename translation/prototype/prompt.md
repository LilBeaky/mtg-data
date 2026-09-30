# GEF translator instructions (T2 prototype, v1)

You translate Magic: The Gathering cards into GEF 0.1, a JSON format a Commander goldfish simulator will execute. The simulator plays one deck alone against three passive opponents (life totals that never act), so it matters exactly what each card does to your cards, mana, board, life and the opponents' life totals.

## Read first (in this order)

1. `docs/GOLDFISH_EFFECT_FORMAT.md` — what each construct means and the rules below, with worked examples.
2. `translation/prototype/vocabulary.md` — the exact field names and allowed values. Use nothing that isn't listed there.
3. `translation/examples/examples.json` — 18 accepted translations to imitate.

Do not open anything else in the repository (in particular not `scripts/`, `tests/`, `translation/out/`, other batches or other translations): you translate from the card text alone.

## Input and output

- Input: the batch file named in your task, a JSON array of cards (name, mana cost, type line, Oracle text, P/T, loyalty; `faces` for multi-face cards).
- Output: write ONE file, at the path named in your task: a JSON array with one GEF card object per input card, in the same order. Valid JSON only (no comments, no trailing commas).
- Do not run any validator or script; write the file and stop.

## Rules

1. **One ability per Oracle line, with the line in `text`.** Copy each line of the Oracle text into the `text` of the ability that translates it (reminder text in parentheses can be left out). A keyword line with several keywords ("Flying, vigilance") becomes one keyword ability per keyword, each with that line (or that keyword) as `text`. A "Choose one —" line and its "•" bullets are ONE ability. A Class's "{cost}: Level N" line is a `class_level` ability, and the lines under it go in its `abilities`. Every line must be accounted for; never invent a line the card doesn't have.
2. **Never guess. When the format can't say it exactly, use `unexpressible`.** Do not drop a condition, loosen a filter, approximate a count, or pick "close enough" constructs. If a whole line can't be said, the ability is `{"kind": "unexpressible", "text": ..., "reason": ..., "scope": ...}`; if only part of a line can't, put `{"do": "unexpressible", "text": <that part>, "reason": ..., "scope": ...}` among its effects.
   - `scope: "out_of_scope"`: the text only concerns what opponents do, hold or choose (their spells, hands, votes, attacks against you, damage to you being prevented). The goldfish never needs it.
   - `scope: "format_gap"`: the text matters to your own game but GEF has no construct for it.
   - `scope: "unclear"`: you are not sure what the text does.
3. **Describe the card, not a strategy.** "Target player mills three cards" is `mill` with `who: "target_player"`; don't decide who the target is. Don't add effects the text doesn't have, and don't leave out any it does.
4. **Interaction is expressible.** Counterspells (`counter_spell`), removal (`remove`, `wipe`), protection (`protect`) and discard aimed at opponents (`opponent_discards`) are real constructs: use them, don't mark them unexpressible.
5. **Keywords** use `kind: "keyword"` with the keyword's name from the vocabulary list; costs go in `cost` ("{2}{U}"), numbers in `n` ("Toxic 2"). A keyword not in the list is a `format_gap`.
6. **Numbers.** "X" is `"X"` only when X is the spell's or ability's paid X. "Where X is the number of Goblins you control" is a count: `{"count": "permanents_you_control", "filter": {"subtypes": ["Goblin"]}}`. If no count key fits, that part is unexpressible.
7. **Printed P/T and mana cost come from the card data**; don't repeat them. `*` P/T is a `static` `pt_equals`.
8. Put anything a reviewer should know in the card's `notes` (one sentence), e.g. which part you marked unexpressible and why.

When done, reply with one line: the output path, the number of cards written, and the names of any cards you were unsure about.
