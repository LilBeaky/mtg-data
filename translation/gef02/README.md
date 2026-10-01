# GEF 0.2 on the T2 cards (T3 step 1)

GEF 0.2 replaces the free-text statics with real constructs and adds the cheap T2 gaps (`docs/GOLDFISH_EFFECT_FORMAT.md`, "Changes in 0.2"). Only the T2 cards that 0.2 affects were re-translated. The rest moved over mechanically. The write-up is the T3 section of `docs/TRANSLATION_T2.md`.

| File | What |
|---|---|
| `affected.json` | The 46 cards re-translated, and why: 0.2 rejects the 0.1 translation, the T2 audit called it freetext/conservative/wrong, or a new construct targets its gap. Made by `translation/gef02.py affected`. |
| `batches/batch_NN.json`, `batches/retry_01.json` | Translator input, the same format as T2's. |
| `out/batch_NN.json` | First-pass translations, as the translators wrote them. |
| `out/retry_01.json` | Retry of 4 cards: Herald's Horn (a lint reject) and Mosswort Bridge / Spinerock Knoll (audit-wrong), with the validator's or reviewer's note in the task; War Room after `pay_life` became an Amount. |
| `audit.json` | Hand audit of every re-translation against its Oracle text: `[name, pass, verdict, real format gap, note]`. |
| `t2_cards.json` | All 300 T2 cards in GEF 0.2: the re-translation where there is one, otherwise the 0.1 translation migrated by `gef02.py migrate` (version bump and `lab_man` renamed, nothing else). Made by `translation/gef02.py merge`. |

## Run manifest

- Date: 2026-09-30 (session 5).
- Translators: Claude Code subagents (general-purpose, Sonnet), the same setup as T2. Three batches of 16/16/14 ran in parallel, then one retry of 4.
- Prompt: `translation/prompt.md` v2, with the vocabulary at `translation/vocabulary.md`. The retry task added one line per card (the validator error, the reviewer's note, or the schema change).
- **Not a blind measurement of prompt v2.** The format doc's "Which scope?" section and the 0.2 change list use T2 cards as examples (Chaos Warp, Victimize, Cultivate, Roaming Throne...), and the plan asked for that. So the re-translations of those cards had their answers in the docs. The first independent test of 0.2 and prompt v2 is the next new deck (T3 step 4).
- Usage: about 91k, 96k and 92k subagent tokens for the three batches, and 80k for the retry.

## Reproduce

```
python3 translation/gef02.py merge
python3 translation/validate.py translation/gef02/t2_cards.json --quiet
python3 translation/t2_report.py > translation/prototype/t2_report.txt     # GEF 0.2 section at the end
```
