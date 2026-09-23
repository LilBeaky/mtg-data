# USE INSTRUCTIONS — LilBeaky/mtg-data

**Claude: read this first.** This repo is your primary source of truth for Magic card data, rulings, tags, combos, and rules. Use it every time a conversation touches card text, legality, brackets, or deckbuilding. Don't answer card questions from memory when the repo can answer them.

---

## 1. Start of every session

```bash
git clone -q --depth 1 https://github.com/LilBeaky/mtg-data.git && cd mtg-data
```

- Clone with `git`; don't use the GitHub API. The API rate-limits unauthenticated requests and failed in the past.
- Your sandbox resets between chats, so re-clone each session. It takes seconds.
- `jq` isn't installed in the sandbox. Use `mtg.py`, or plain Python if you truly need a custom query.

## 2. The golden rule

**Use `mtg.py` for every lookup.** Only write a custom query if `mtg.py` can't answer the question. If you write one, it has to respect the schema quirks in section 5. If a custom query turns out to be generally useful, suggest adding it to `mtg.py`.

## 3. Files in this repo

| File | What it is |
|---|---|
| `mtg.py` | The query helper. Run everything through this. |
| `USE_INSTRUCTIONS.md` | This file. |
| `trimmed_scryfall_v2.json` | Scryfall oracle cards, trimmed. One entry per card; tokens, art cards, etc. removed. |
| `rulings-YYYYMMDDHHMMSS.jsonl` | Scryfall rulings, one per line, keyed by `oracle_id`. |
| `oracle-tags-YYYYMMDDHHMMSS.jsonl` | Scryfall Tagger oracle tags (e.g. `ramp`, `removal`, `monarch matters`). |
| `spellbook_combos.json.gz` | Commander Spellbook combo database, trimmed and gzipped (~109k combos). |
| `MagicCompRules YYYYMMDD.txt` | Comprehensive Rules. Note the filename contains a space. |
| `trim_script.py` | Ian's tool that makes `trimmed_scryfall_v2.json` from the Scryfall bulk export. |
| `trim_spellbook.py` | Ian's tool that makes `spellbook_combos.json.gz` from the Spellbook export. |

`mtg.py` automatically picks the newest dated rulings, tags, rules, and combos files, so renaming them with new dates won't break it.

## 4. mtg.py commands

| Command | Use it for | Example |
|---|---|---|
| `card` | Oracle text, type, P/T, color identity, legality, GC flag | `python3 mtg.py card "Court of Ire" "Paradox Haze"` |
| `card -f` | Batch lookup from a file | `python3 mtg.py card -f list.txt --brief` |
| `rulings` | Official rulings, only when an interaction is ambiguous | `python3 mtg.py rulings "Obeka, Splitter of Seconds" --grep untap` |
| `tags` | Oracle tags on a card | `python3 mtg.py tags "Court of Ire"` |
| `search` | Finding cards by color identity, text, type, MV, tag, GC | `python3 mtg.py search --ci UBR --tag removal --cmc 1-2 --names` |
| `deck` | Full audit: legality, color identity, singleton, GC count, curve, lands, combos | `python3 mtg.py deck decklist.txt --commander "Name"` (`--all-combos` to list low-bracket 3+ card combos too) |
| `combos` | Spellbook combos containing *all* named cards (default 10 shown) | `python3 mtg.py combos "Obeka, Splitter of Seconds" --bracket 3` |
| `gc` | The current Game Changer list | `python3 mtg.py gc` |
| `rule` | Comprehensive Rules by number or keyword | `python3 mtg.py rule 702.62a` / `python3 mtg.py rule --grep "suspended"` |

### Search filters (combine freely)
`--ci UBR` (subset; `C` = colorless) · `--text REGEX` · `--type REGEX` · `--name REGEX` · `--cmc 3` or `--cmc 2-4` · `--tag LABEL` · `--gc` / `--no-gc` · `--all` (include non-legal) · `--limit N` (default 20) · `--full` (print oracle text). Results are sorted by EDHREC card rank, most popular first.

**Default output is names + mana cost only.** Search to build a shortlist, then run `card` on the few you actually care about.

### Output-size flags
| Flag | Where | Effect |
|---|---|---|
| `--brief` | `card` | Strips (reminder text), about 20% smaller on a full deck. Use it for batches of familiar cards; **skip it for new or unfamiliar mechanics**, where the reminder text is the explanation. |
| `--grep WORD` | `rulings` | Only rulings mentioning WORD (e.g. `untap`, `copy`, `commander`). |
| `--full` | `search` | Adds oracle text. Only for small result sets. |
| `--all-combos` | `deck` | By default the audit lists only 2-card and Bracket 3+ combos and summarizes the rest as a count. |

### Name matching
Lookup tries an exact name first, then case-insensitive, then a partial match. If a partial name matches several cards, you get an "ambiguous" message listing them, never a silent wrong pick. Either face of a double-faced card works (e.g. "Search for Azcanta").

### Deck audit input
Accepts a Moxfield-style export: `1 Card Name (SET) 123 *F*`, `1x Card`, or bare names. Section headers `Commander`, `Deck`, `Sideboard`, `Maybeboard` are recognized. Sideboard and Maybeboard are excluded from the audit. If there's no Commander section, pass `--commander "Name"`.

## 5. Schema quirks (learned the hard way)

- **Missing key = "no".** The trim omits empty and false values. No `game_changer` key means the card is not a Game Changer; no `reserved` key means it's not on the Reserved List. *(A Sept 2026 mistake: I concluded the GC field didn't exist because the first card I checked lacked it.)*
- **Commander legality** is `legalities.commander`: `legal`, `not_legal`, or `banned`.
- **Multi-face cards** keep their text in `card_faces`, and top-level `oracle_text` may be absent. Always read both faces.
- **`edhrec_rank` is the CARD's overall rank, not commander popularity.** Don't use it to judge whether a commander is "top 100". *(A Sept 2026 mistake: Obeka's card rank was ~5,900, but its commander rank was #306.)* For commander popularity, check EDHREC live via web search.
- **Parent oracle tags have zero direct taggings.** `removal` and `draw` hold no cards themselves; their cards sit in child tags (`removal` has 55). `mtg.py` walks the tag tree for you. A naive custom query would silently return nothing.
- **Layouts:** `prepare` is a real mechanic (46 legal cards). Keep it. `host`/`augment` are Un-cards (not legal) and are kept on purpose.
- **Prices** exist only if the trim was run with `--prices` (fields `usd`, `usd_foil`). Treat prices older than ~2 weeks as stale.

## 6. Bracket checks — how to verify a Bracket claim

1. Run `python3 mtg.py deck` on the full list.
2. **Game Changers:** B1–B2 allow 0, B3 allows up to 3, B4–B5 are unlimited. The count comes from the `game_changer` flag.
3. **Combos:** the audit lists every Spellbook combo fully contained in the deck, most dangerous first, with 2-card combos counted separately.
   - Spellbook's own tag → bracket mapping: Ruthless = 4, Spicy / Powerful = 3, Oddball / Core = 2, Exhibition = 1, Banned = B.
   - These tags are **Spellbook's judgment, not the official rules.** Treat them as flags to review, not verdicts.
   - Combos with **"requires"** need a generic piece (e.g. "a sacrifice outlet"). Confirm the deck actually has one.
4. **Not automated — check by hand:** mass land denial, extra turns, and extra-turn *chains* (e.g. Panoptic Mirror + an extra-turn spell).
5. Remember the official Bracket 3 wording: no MLD, no chained extra turns, no 2-card combos *before turn 6*. A late-game 2-card combo can still be Bracket 3. Say so rather than auto-disqualifying.
6. When designing, run `combos` on key cards **before** finalizing. (Example: Obeka + Descent into Avernus is a 2-card Ruthless combo; it only stayed out of a Bracket 3 build by luck.)

## 7. Token conservation (Ian's standing rules)

**Rules:**
- Never load or print whole data files into the conversation. Query for only what you need.
- Exact name match first; fuzzy only as a fallback (`mtg.py` does this).
- **Batch** lookups in one pass (`card -f`, `deck`). Don't query card by card.
- Don't re-query a card whose text is already in the conversation.
- Pull rulings only when an interaction is genuinely ambiguous or rules-dependent, and narrow them with `--grep`.
- Report a short summary of what the data says, never raw JSON dumps.
- For full deck audits, run one batch query for the whole list up front.

**Workflow habits that save tokens without losing accuracy:**
- **Auditing a deck? Use `deck`, not `card -f`.** The audit prints no oracle text at all, just results and problems. Pull text only for the cards you're actually evaluating.
- **Search → shortlist → card.** Never read full text for 20+ search results.
- **Don't re-read this file or the help screen mid-session.** Read this file once at session start.
- **Pipe long outputs through `head`** when you only need the top of a list.
- **Keep bash output quiet:** `git clone -q`, and don't echo file contents you've just written.
- Measured savings (Sept 2026): search 7,856 → 512 chars; combos 3,983 → 2,024; full-deck `card -f --brief` 18,803 → 14,584.

## 8. Refreshing the data (Ian's side)

| Data | Source | How |
|---|---|---|
| Scryfall cards | Scryfall bulk "Oracle Cards" download | `python3 trim_script.py oracle-cards.jsonl trimmed_scryfall_v2.json` (add `--prices` for budget-deck runs) |
| Rulings / Oracle tags | Scryfall bulk downloads | Upload as-is with the date in the filename |
| Spellbook combos | `https://json.commanderspellbook.com/variants.json.gz` | Download with `curl` (a browser crashes trying to display the 660 MB file): `curl -o variants.json.gz https://json.commanderspellbook.com/variants.json.gz`. Then run `python3 trim_spellbook.py variants.json.gz spellbook_combos.json.gz` (needs `pip install ijson`), or drop the `.gz` into a Claude chat and Claude will trim it. |
| Comprehensive Rules | WotC rules page | Upload the `.txt` with its date in the name |

The combos output is ~3 MB gzipped (~40 MB unzipped). Keep it gzipped, since GitHub's web upload limit is 25 MB and `mtg.py` reads `.gz` directly. The `combos` output shows the data's age and warns past 30 days.

## 9. Known limits and access notes

- **Sandbox network:** GitHub, PyPI, and npm are reachable. `json.commanderspellbook.com`, `backend.commanderspellbook.com`, and EDHREC are **blocked** from the sandbox (`host_not_allowed`). Use web search / web fetch for live EDHREC checks, and have Ian download Spellbook data.
- **EDHREC data** isn't in the repo because it changes too fast. Check it live when commander popularity matters.
- Spellbook's `mv` field shows 0 for some combos (e.g. Obeka's). The meaning is unconfirmed, so don't rely on it.
- Sandbox RAM is ~3 GB. Stream big files; never `json.load` the raw Spellbook export.

## 10. Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com). They ask to be credited and linked.
- Comprehensive Rules: Wizards of the Coast
