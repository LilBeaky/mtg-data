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

The one exception: **EDHREC comparisons go through `edhrec_diff.py`** (section 7).

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
| `trim.py` | Ian's data-refresh tool. Two separate subcommands: `scryfall` builds `trimmed_scryfall_v2.json`, `spellbook` builds `spellbook_combos.json.gz`. See section 9. |
| `edhrec_diff.py` | Validates an EDHREC snapshot and diffs a deck against it. See section 7. |
| `edhrec_snapshots/` | Transcribed EDHREC commander pages, one file per commander + variant + date. |

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
Accepts a Moxfield-style export: `1 Card Name (SET) 123 *F*`, `1x Card`, or bare names. Section headers `Commander`, `Companion`, `Deck`, `Sideboard`, `Maybeboard` are recognized. Sideboard and Maybeboard are excluded from the audit.

**Companion** is excluded from the card count but still checked for legality and color identity, and it's included in the combo check (it can be put into hand for {3}, so its combos are live). Odd/even conditions (Obosh, Gyruda) are verified automatically against the whole starting deck, commander included. The other 10 companions print "review manually". If there's no Commander section, pass `--commander "Name"`.

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

## 7. EDHREC comparisons — `edhrec_diff.py`

Every deck audit gets its own EDHREC section. EDHREC is **meta signal, never card truth**: it tells you what the field plays, not what cards do. Verify any card it surfaces with `mtg.py card` before recommending it.

The sandbox can't reach EDHREC, so you fetch the page yourself with the web tools, transcribe it into a snapshot file, and let the script do the math. Ian chose this on purpose so it works without him.

### Workflow

1. **Reuse before you fetch.** Run `ls edhrec_snapshots/`. If there's a snapshot for the same commander and variant under 30 days old, skip to step 5. The fetch is the most expensive step (~15–20K tokens).
2. **Pick the right page.** Match the deck's target bracket: `/exhibition`, `/core`, `/upgraded`, `/optimized`, or `/cedh`. Budget (`/budget`, `/expensive`) and theme pages (`/treasure`, etc.) also exist. Fall back to the all-decks page if the bracket page has under ~200 decks.
   - `web_fetch` refuses URLs you construct. Get the first URL from `web_search`. After one commander page is fetched, its bracket, budget, and theme links count as seen and can be fetched directly.
3. **Fetch once** with `web_fetch`. Note that `text_content_token_limit` is ignored on EDHREC pages; you get the whole page.
4. **Transcribe** to `edhrec_snapshots/<commander-slug>__<variant>__<YYYY-MM-DD>.txt`:
   ```
   # commander: Smaug the Impenetrable
   # variant: upgraded
   # url: https://edhrec.com/commanders/smaug-the-impenetrable/upgraded
   # decks: 1234
   # fetched: 2026-09-25
   Card Name|inclusion%|synergy%[|eligible decks]
   ```
   - Include every card from every section, lands too. Skip basics.
   - Copy inclusion and synergy exactly as shown.
   - Add the 4th field **only** when a card's eligible-deck count differs from the page total (new cards, e.g. `4.65K decks / 5.22K decks` → `5220`).
   - A card appearing in two sections is fine; identical duplicates get merged.
5. **`check` is mandatory** after every transcription:
   `python3 edhrec_diff.py check edhrec_snapshots/<file>.txt`
   It flags names not in the repo, fuzzy matches, cards outside the commander's color identity, synergy above inclusion (swapped numbers), out-of-range values, and duplicate lines with conflicting numbers. It exits with code 2 on problems. Fix every one and re-run until it prints `OK`.
6. **Diff:** `python3 edhrec_diff.py diff <snapshot> <decklist> [options]`
7. **Hand the snapshot to Ian.** Copy it to outputs and tell him, so he can commit it and future audits can skip the fetch.

### Options (`diff`)

| Flag | Effect |
|---|---|
| `--commander "Name"` | Use if the decklist has no Commander section |
| `--min N` | Inclusion % threshold for the SKIPPED list (default 30). Lower it for small or niche decks. |
| `--limit N` | Max rows per section (default 25) |
| `--mv odd\|even` | Companion filter: hides nonland SKIPPED cards the companion makes illegal (Obosh = odd, Gyruda = even) |

Decklist input is the same Moxfield format as `mtg.py deck`. Companion, Sideboard, and Maybeboard sections are excluded.

### Reading the output

| Section | What it means | How to use it |
|---|---|---|
| SUMMARY | % of the deck on EDHREC's list, average inclusion, mainstream index, signature cards run, GC count | Mainstream index 100% = the deck runs the N most-played cards (a netdeck). **Not a quality score**; low can be good. |
| SKIPPED | Popular cards not in the deck, tagged `signature` (synergy ≥ 40, commander-specific), `generic staple` (synergy ≤ 10), `GC`, `new` | Candidates to *consider*, not must-plays. Check them against the deck's stated direction first; Ian often avoids the popular build on purpose. |
| OFF-LIST | Deck cards EDHREC doesn't show | Means under ~5% or unplayed, **not** bad. Often where Ian's intentional divergence lives. Report it; don't recommend cuts just for being off-list. |
| NEGATIVE SYNERGY | Deck cards this commander's players run *less* than the general population does | The most interesting section. Ask why the field avoids it: it may be a real weakness with this commander, or an edge the field missed. |
| ON-LIST | Overlap with the field, most to least played | Quick sense of where the deck agrees with consensus |

### Interpretation rules

- **Synergy** = this commander's inclusion minus the card's baseline inclusion among decks that could play it. High = commander-specific; ~0 = goes in everything; negative = avoided here.
- **Sample size:** the header warns under 50 decks (treat as anecdotes) and under 200 (trust big gaps only).
- **Staleness:** the header warns past 30 days. Refetch rather than audit on old data.
- **Blind spots:** numbers are rounded ("4.65K"), cards under ~5% inclusion aren't listed, and charts, combos, salt, and individual decklists aren't visible (JS-rendered or login-only). Use `mtg.py deck` for combos.

## 8. Token conservation (Ian's standing rules)

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
- **EDHREC:** reuse a fresh snapshot instead of refetching. Fetch one page per audit, not every bracket variant. Never paste the fetched page or snapshot back into the reply; report the diff's findings.
- **Keep bash output quiet:** `git clone -q`, and don't echo file contents you've just written.
- Measured savings (Sept 2026): search 7,856 → 512 chars; combos 3,983 → 2,024; full-deck `card -f --brief` 18,803 → 14,584.

## 9. Refreshing the data (Ian's side)

| Data | Source | How |
|---|---|---|
| Scryfall cards | Scryfall bulk "Oracle Cards" download | `python3 trim.py scryfall oracle-cards.jsonl trimmed_scryfall_v2.json` (add `--prices` for budget-deck runs) |
| Rulings / Oracle tags | Scryfall bulk downloads | Upload as-is with the date in the filename |
| Spellbook combos | `https://json.commanderspellbook.com/variants.json.gz` | Download with `curl` (a browser crashes trying to display the 660 MB file): `curl -o variants.json.gz https://json.commanderspellbook.com/variants.json.gz`. Then run `python3 trim.py spellbook variants.json.gz spellbook_combos.json.gz` (needs `pip install ijson`), or drop the `.gz` into a Claude chat and Claude will trim it. |
| Comprehensive Rules | WotC rules page | Upload the `.txt` with its date in the name |

The combos output is ~3 MB gzipped (~40 MB unzipped). Keep it gzipped, since GitHub's web upload limit is 25 MB and `mtg.py` reads `.gz` directly. The `combos` output shows the data's age and warns past 30 days.

## 10. Known limits and access notes

- **Sandbox network:** GitHub, PyPI, and npm are reachable. `json.commanderspellbook.com`, `backend.commanderspellbook.com`, and EDHREC are **blocked** from the sandbox (`host_not_allowed`). Use `web_search` / `web_fetch` for EDHREC (see section 7), and have Ian download Spellbook data.
- **EDHREC data** isn't bundled because it changes too fast. Snapshots in `edhrec_snapshots/` are point-in-time copies; anything over 30 days old should be refetched. For commander popularity rank, check live.
- Spellbook's `mv` field shows 0 for some combos (e.g. Obeka's). The meaning is unconfirmed, so don't rely on it.
- Sandbox RAM is ~3 GB. Stream big files; never `json.load` the raw Spellbook export.

## 11. Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com). They ask to be credited and linked.
- Comprehensive Rules: Wizards of the Coast
- Commander meta data: [EDHREC](https://edhrec.com)
