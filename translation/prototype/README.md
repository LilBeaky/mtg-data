# T2 prototype: 300 cards translated to GEF 0.1

What is here, and how it was made. The write-up is `docs/TRANSLATION_T2.md`.

| File | What |
|---|---|
| `cards.json` | The 300 cards, in order, with where each came from (`deck` / `pool`) and the parser's status at selection time. Made by `translation/t2_select.py`. |
| `batches/batch_NN.json` | Translator input: name, mana cost, type line, Oracle text, P/T, loyalty, faces. No parser readings. |
| `prompt.md` | The translator instructions (v1), used unchanged for all 12 batches. |
| `vocabulary.md` | Every construct and allowed value, generated from the schema by `translation/make_vocab.py`. |
| `out/batch_NN.json` | First-pass translations, exactly as the translators wrote them. |
| `out/retry_01.json` | Retry of the 3 genuine rejects, with the validator's errors in the task. |
| `compare.json`, `review.md` | `translation/t2_compare.py`: parser reading vs translation per card (status + effect/event/keyword signatures). `review.md` is the side-by-side sheet for the 124 flagged cards. |
| `audit_batchNN.json` | Hand audit of every card: `[name, translation verdict, parser verdict, real format gap?, note]`. Verdicts are defined in `translation/t2_report.py`. |
| `t2_report.txt` | Output of `translation/t2_report.py`: all the numbers in the write-up. |

## Run manifest

- Date: 2026-09-30.
- Translator: Claude Code subagents (general-purpose agent, Sonnet model), one per batch of 25 cards, run in parallel inside the session. No API pipeline, no paid calls.
- Each translator read `docs/GOLDFISH_EFFECT_FORMAT.md`, `vocabulary.md`, `translation/examples/examples.json`, then its batch, and was told not to open anything else and not to run the validator.
- Prompt: `prompt.md` v1 for batches 01-12. The retry prompt was the same instructions plus the validator's error lines for the three cards.
- Usage: about 80k subagent tokens per 25-card batch (79.7k, 81.5k, 81.0k where reported), about 70k of it fixed reading of the format docs. The 3-card retry used 69.7k. So it's roughly 1.05M subagent tokens for the whole run.

## Reproduce

```
python3 translation/validate.py translation/prototype/out/batch_*.json --quiet             # reject rate
python3 translation/t2_compare.py translation/prototype/out/batch_*.json translation/prototype/out/retry_01.json
python3 translation/t2_report.py > translation/prototype/t2_report.txt
python3 translation/t2_show.py translation/prototype/out/batch_05.json "Krark's Thumb"      # side by side for one card
```
