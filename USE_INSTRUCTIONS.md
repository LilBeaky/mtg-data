# USE INSTRUCTIONS — LilBeaky/mtg-data

**Claude: read this first.** This repo is your primary source of truth for Magic card data, rulings, tags, combos, and rules. Use it every time a conversation touches card text, legality, brackets, or deckbuilding. Don't answer card questions from memory when the repo can answer them.

---

## 1. Start of every session

```bash
git clone -q --depth 1 https://github.com/LilBeaky/mtg-data.git && cd mtg-data
```

- Clone with `git`; don't use the GitHub API for reading. Unauthenticated API calls rate-limit and have failed before.
- Your sandbox resets between chats, so re-clone each session. It takes seconds.
- `jq` isn't installed in the sandbox. Use `mtg.py`, or plain Python if you truly need a custom query.
- Read this file once. Read `STATS_MATH.md` only if you need math beyond what `audit.py` prints.

## 2. The golden rules

| Task | Tool |
|---|---|
| Any deck audit | **`audit.py`** (section 5). Always the first step of an audit. |
| Card text, rulings, tags, search, rules, GCs, combos | **`mtg.py`** (section 4) |
| Draw odds beyond the audit battery | **`stats_math.py`** (section 6) |
| EDHREC comparison | **`edhrec_diff.py`** (section 9). `audit.py` runs the diff automatically when a snapshot exists. |

Only write a custom query if none of these can answer the question. If you do, respect the schema quirks in section 7. If a custom query turns out to be generally useful, suggest adding it to the right tool.

## 3. Files in this repo

| File | What it is |
|---|---|
| `USE_INSTRUCTIONS.md` | This file. |
| `audit.py` | The default full deck audit. One command runs every check. |
| `mtg.py` | Query helper for cards, rulings, tags, search, deck, GCs, combos, and rules. |
| `stats_math.py` | Probability engine (hypergeometric, Monte Carlo, tag and user-tag counts). |
| `STATS_MATH.md` | Docs for `stats_math.py`: conventions, functions, known limits. |
| `categories.py` | Curated role → Scryfall tag mapping (broad/strict pairs, synonyms for Ian's #tags). |
| `edhrec_diff.py` | Validates an EDHREC snapshot and diffs a deck against it. |
| `edhrec_snapshots/` | Transcribed EDHREC pages, one file per commander + variant + date. |
| `trim.py` | Ian's data-refresh tool (`scryfall` and `spellbook` subcommands). See section 12. |
| `trimmed_scryfall_v2.json` | Scryfall oracle cards, trimmed. One entry per card; tokens, art cards, etc. removed. |
| `rulings-YYYYMMDDHHMMSS.jsonl` | Scryfall rulings, one per line, keyed by `oracle_id`. |
| `oracle-tags-YYYYMMDDHHMMSS.jsonl` | Scryfall Tagger oracle tags (e.g. `ramp`, `sweeper`, `monarch matters`). |
| `spellbook_combos.json.gz` | Commander Spellbook combo database, trimmed and gzipped (~109k combos). |
| `MagicCompRules YYYYMMDD.txt` | Comprehensive Rules. Note the filename contains a space. |

`mtg.py` automatically picks the newest dated rulings, tags, rules, and combos files, so renaming them with new dates won't break it.

## 4. mtg.py commands

| Command | Use it for | Example |
|---|---|---|
| `card` | Oracle text, type, P/T, color identity, legality, GC flag | `python3 mtg.py card "Court of Ire" "Paradox Haze"` |
| `card -f` | Batch lookup from a file | `python3 mtg.py card -f list.txt --brief` |
| `rulings` | Official rulings, only when an interaction is ambiguous | `python3 mtg.py rulings "Obeka, Splitter of Seconds" --grep untap` |
| `tags` | Oracle tags on a card | `python3 mtg.py tags "Court of Ire"` |
| `search` | Finding cards by color identity, text, type, MV, tag, GC | `python3 mtg.py search --ci UBR --tag removal --cmc 1-2 --names` |
| `deck` | Legality, color identity, singleton, GC count, curve, lands, combos | `python3 mtg.py deck decklist.txt` (`audit.py` runs this for you) |
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

**Full card names always beat face names.** *(Fixed Sept 2026: prepare-card back faces used to take over real cards with the same name. "Rampant Growth" resolved to Studious First-Year // Rampant Growth. 12 cards were affected, including Reanimate, Regrowth, Replenish, Channel, Exsanguinate, and Sign in Blood.)*

### Deck file input (mtg.py, audit.py, edhrec_diff.py, stats_math.py)
- Accepts Moxfield-style lines: `1 Card Name (SET) 123 *F*`, `1x Card`, or bare names.
- Section headers `Commander`, `Companion`, `Deck`, `Sideboard`, and `Maybeboard` are recognized. Sideboard and Maybeboard are excluded.
- **Trailing `#tags` are Ian's roles.** In a long-form export like `1 Sol Ring (C21) 263 *F* #Ramp #!Mana Rock`, the tags are stripped from the card name and `audit.py` uses them as role labels. Multi-word tags survive, and a leading `!` is dropped. Ian doesn't always tag; use them when they're there.
- **Header lines** like `bracket: 3 (high)`, `plan: creature storm`, `pets: ...`, `notes:`, `target:`, and `budget:` (with or without a leading `#`) are read as metadata, not as cards. `audit.py` takes the bracket target from `bracket:`.
- **Companion** is excluded from the card count but still checked for legality and color identity, and it's included in the combo check (it can be put into hand for {3}, so its combos are live). Odd/even conditions (Obosh, Gyruda) are verified automatically; the other 10 companions print "review manually".
- If there's no Commander section, pass `--commander "Name"`.

## 5. Deck audits — `audit.py` (the default)

**Every deck audit starts here.** Ian wants audits as thorough as the tooling allows by default, so don't skip sections to save a step.

1. Write Ian's list to a file exactly as given (keep his `#tags` and header lines).
2. Run `python3 audit.py deck.txt`. It takes about 10 seconds.
3. Read the output, then do the judgment work: gameplan, table feel, cuts, adds. Pull oracle text (`mtg.py card -f --brief`) only for cards you're actually evaluating.
4. If there's no EDHREC snapshot, fetch one (section 9) and re-run with `--snapshot` or plain.

### Options
| Flag | Effect |
|---|---|
| `--bracket N` | Target bracket (default: the `bracket:` header line) |
| `--k ROLE=N` | Confirmed count for a role; overrides tags. Repeatable: `--k protection=7 --k ramp=11` |
| `--draw` | Odds on the draw (default: on the play) |
| `--commander "Name"` | If the list has no Commander section |
| `--snapshot PATH` / `--no-edhrec` | Pick an EDHREC snapshot, or skip the section |
| `--min N` / `--limit N` | Passed to `edhrec_diff.py diff` |
| `--all-combos` | Passed to `mtg.py deck` |
| `--no-lists` | Hide the card list under each role (saves tokens on a re-run) |

### What it prints
| Section | Contents |
|---|---|
| 1 Legality & bracket | `mtg.py deck` output, GC count vs the bracket allowance, 2-card combos, extra-turn cards, possible MLD (regex flag for review) |
| 2 Mana base | Lands, always- and conditionally-tapped lands (auto-detected), MDFC land backs, ramp, opener land odds, one-MV accelerants |
| 3 Commander on curve | Lands-only floor and with a 1-MV accelerant, per commander |
| 4 Roles & odds | K and odds (opener, T3, T4, T6 ≥2) for ramp, draw, draw engines, removal, wipes, protection, tutors, counterspells, recursion, graveyard hate, plus any other category present and every custom #tag |
| 5 Density & flood | ≥4 non-mana cards in the first 12, flood odds, screw odds, with ramp-count alternatives |
| 6 EDHREC | `edhrec_diff.py diff` against the newest snapshot for this commander (bracket variant preferred, then `all`) |
| 7 Manual checklist | What no script here verifies |

### Roles: where K comes from (this matters)
Hypergeometric odds are only as good as K, the number of cards that actually do the job. The sources, in priority order:

1. **Ian's `#tags`**, when they cover ≥50% of the nonland cards. His labels are his intent, so they're the truth. Labels under a category's Scryfall subtree (e.g. `mana rock`, `removal-creature`, `draw engine`) and plain-English synonyms (`wipe`, `tutor`, `counter`) map automatically. Any other label becomes its own row (e.g. `#pump`, `#pet`).
2. **`--k ROLE=N`**, a count you confirmed with Ian or by reading the card list.
3. **Scryfall oracle tags.** These are broad. They answer "does this card have the effect?" rather than "does it fill this role in this deck?" In the Sept 2026 Wilson spot check, tags said 11 protection pieces against ~7 real ones, which moved "2 protection by T6" from 20% to 40%.

The audit prints the alternative counts under each role and marks **⚠ K-SENSITIVE** when switching sources moves the odds by 15 points or more. For those roles, don't quote the number as settled. Confirm the count from the card list (or ask Ian), re-run with `--k`, and say which K you used. When Ian's tags are primary, the audit also lists cards the oracle tags flag that he didn't tag, and the reverse. Those are worth a sentence, since he may have mis-tagged or may disagree with the tag on purpose.

## 6. Stats Math — `stats_math.py`

`audit.py` covers the standard battery. **Lean toward using Stats Math more, not less**, for anything else a draw-odds question touches: package coherence ("both halves by T4"), comparing a cut against an add, or mulligan decisions. Ian prefers it be too willing rather than not willing enough.

- Quick number: `python3 stats_math.py N K n k` → P(at least k of K in n cards from N).
- Anything more: `python3 -c "import stats_math as sm; ..."` from the repo root. Key functions: `count_population`, `cards_seen`, `hyper_at_least`, `multivariate_at_least` (disjoint categories at once), `turn_curve`, `category_count_from_tag`, `user_tag_map`.
- Conventions are fixed: 7-card hand, London mulligan, N counted from the list (never assumed).
- Limits to state out loud: static draws only (no draw engines, untaps, cascade), and colors aren't modeled. Details are in `STATS_MATH.md` §7.
- A goldfish simulation for card-effect questions (like the Wilson ramp package) isn't in the repo yet. If you build one ad hoc, say so and offer to save it.

## 7. Schema quirks (learned the hard way)

- **Missing key = "no".** The trim omits empty and false values. No `game_changer` key means the card is not a Game Changer; no `reserved` key means it's not on the Reserved List. *(A Sept 2026 mistake: I concluded the GC field didn't exist because the first card I checked lacked it.)*
- **Commander legality** is `legalities.commander`: `legal`, `not_legal`, or `banned`.
- **Multi-face cards** keep their text in `card_faces`, and top-level `oracle_text` may be absent. Always read both faces.
- **`edhrec_rank` is the CARD's overall rank, not commander popularity.** Don't use it to judge whether a commander is "top 100". *(A Sept 2026 mistake: Obeka's card rank was ~5,900, but its commander rank was #306.)* For commander popularity, check EDHREC live via web search.
- **Parent oracle tags have zero direct taggings.** `removal` and `draw` hold no cards themselves; their cards sit in child tags (`removal` has 55). `mtg.py` and `stats_math.py` walk the tag tree for you. A naive custom query would silently return nothing.
- **Tags that do exist** (despite earlier notes saying otherwise): `sweeper` for board wipes, and the `recursion` umbrella, which covers regrowth as well as `reanimate`.
- **Layouts:** `prepare` is a real mechanic (46 legal cards). Keep it. `host`/`augment` are Un-cards (not legal) and are kept on purpose.
- **Prices** exist only if the trim was run with `--prices` (fields `usd`, `usd_foil`). Treat prices older than ~2 weeks as stale.

## 8. Bracket checks — how to verify a Bracket claim

1. `audit.py` section 1 does the automated part: GC count vs the allowance (B1–B2: 0, B3: up to 3, B4–B5: unlimited), 2-card combos, extra-turn cards, and possible-MLD flags.
2. **Combos** come from Commander Spellbook, most dangerous first, with 2-card combos counted separately.
   - Spellbook's own tag → bracket mapping: Ruthless = 4, Spicy / Powerful = 3, Oddball / Core = 2, Exhibition = 1, Banned = B.
   - These tags are **Spellbook's judgment, not the official rules.** Treat them as flags to review, not verdicts.
   - Combos with **"requires"** need a generic piece (e.g. "a sacrifice outlet"). Confirm the deck actually has one.
3. **Still by hand:** whether flagged MLD cards really are MLD (the flag is a regex), extra-turn *chains* (e.g. Panoptic Mirror + an extra-turn spell), and whether a 2-card combo can fire before turn 6.
4. Remember the official Bracket 3 wording: no MLD, no chained extra turns, no 2-card combos *before turn 6*. A late-game 2-card combo can still be Bracket 3. Say so rather than auto-disqualifying.
5. When designing, run `mtg.py combos` on key cards **before** finalizing. (Example: Obeka + Descent into Avernus is a 2-card Ruthless combo; it only stayed out of a Bracket 3 build by luck.)

## 9. EDHREC comparisons — `edhrec_diff.py`

Every deck audit gets its own EDHREC section. EDHREC is **meta signal, never card truth**: it tells you what the field plays, not what cards do. Verify any card it surfaces with `mtg.py card` before recommending it.

The sandbox can't reach EDHREC, so you fetch the page yourself with the web tools, transcribe it into a snapshot file, and let the script do the math. Ian chose this on purpose so it works without him.

### Workflow

1. **Reuse before you fetch.** `audit.py` looks for a snapshot automatically. If there's one for the same commander under 30 days old, you're done. The fetch is the most expensive step (~15–20K tokens).
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
   - **Partner or background pairs:** `# commander: Wilson, Refined Grizzly + Flaming Fist` (joined with ` + `; color identity is the union). The slug is EDHREC's URL slug, e.g. `wilson-refined-grizzly-flaming-fist`.
   - Include every card from every section, lands too. Skip basics.
   - Copy inclusion and synergy exactly as shown.
   - Add the 4th field **only** when a card's eligible-deck count differs from the page total (new cards, e.g. `4.65K decks / 5.22K decks` → `5220`).
   - A card appearing in two sections is fine; identical duplicates get merged.
5. **`check` is mandatory** after every transcription:
   `python3 edhrec_diff.py check edhrec_snapshots/<file>.txt`
   It flags names not in the repo, fuzzy matches, cards outside the commander's color identity, synergy above inclusion (swapped numbers), out-of-range values, and duplicate lines with conflicting numbers. It exits with code 2 on problems. Fix every one and re-run until it prints `OK`.
6. **Diff:** `audit.py` runs it for you, or run `python3 edhrec_diff.py diff <snapshot> <decklist> [options]` directly.
7. **Save the snapshot.** Push it (section 11) if you have a token. If not, copy it to outputs and tell Ian so he can commit it and future audits can skip the fetch.

### Options (`diff`)

| Flag | Effect |
|---|---|
| `--commander "Name"` | Use if the decklist has no Commander section |
| `--min N` | Inclusion % threshold for the SKIPPED list (default 30). Lower it for small or niche decks. |
| `--limit N` | Max rows per section (default 25) |
| `--mv odd\|even` | Companion filter: hides nonland SKIPPED cards the companion makes illegal (Obosh = odd, Gyruda = even) |

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

## 10. Token conservation (Ian's standing rules)

**Rules:**
- Never load or print whole data files into the conversation. Query for only what you need.
- Exact name match first; fuzzy only as a fallback (`mtg.py` does this).
- **Batch** lookups in one pass (`card -f`, `deck`, `audit.py`). Don't query card by card.
- Don't re-query a card whose text is already in the conversation.
- Pull rulings only when an interaction is genuinely ambiguous or rules-dependent, and narrow them with `--grep`.
- Report a short summary of what the data says, never raw JSON dumps.
- For full deck audits, run one batch query for the whole list up front: that's `audit.py`.

**Workflow habits that save tokens without losing accuracy:**
- **Auditing a deck? `audit.py` first.** It prints no oracle text, just results. Pull text only for the cards you're actually evaluating. On a re-run after changes, add `--no-lists`.
- **Search → shortlist → card.** Never read full text for 20+ search results.
- **Don't re-read this file or the help screen mid-session.** Read this file once at session start.
- **Pipe long outputs through `head`** when you only need the top of a list.
- **EDHREC:** reuse a fresh snapshot instead of refetching. Fetch one page per audit, not every bracket variant. Never paste the fetched page or snapshot back into the reply; report the diff's findings.
- **Keep bash output quiet:** `git clone -q`, and don't echo file contents you've just written.
- Measured savings (Sept 2026): search 7,856 → 512 chars; combos 3,983 → 2,024; full-deck `card -f --brief` 18,803 → 14,584.

## 11. Pushing changes to GitHub (Claude)

Ian keeps a **fine-grained personal access token** (starts with `github_pat_`) in the Project instructions, scoped to this repo only. If it isn't there, ask. This is a personal project, so **commit straight to `main`**: no branches, no pull requests. Ian only wants the current version, and git history is the undo button.

**Rules:**
- The token is a password. **Never** write it into the repo, memory, outputs, a commit, or a reply. Never print it; mask command output.
- **Never force-push and never rewrite history.** History is how a bad commit gets undone. To undo, `git revert <sha>` and push; never `reset`.
- Start from a fresh clone (section 1) so you commit on top of the current `main`. If the push is rejected because `main` moved, run `git pull -q --rebase` and push again.
- Commit only what the session produced and Ian approved. Stage files by name, never `git add -A`.
- Write a clear commit message (what and why), and give Ian the commit link.
- On a 401/403, the token is missing a permission or has expired. Tell Ian; don't retry with guesses.

```bash
# sandbox-only file, outside the repo, deleted at the end
printf '%s' 'TOKEN_FROM_PROJECT_INSTRUCTIONS' > /home/claude/.gh_token && chmod 600 /home/claude/.gh_token
cd /home/claude/mtg-data
git add path/to/file1 path/to/file2                       # by name
git -c user.name="Claude (for Ian)" -c user.email="claude@mtg-data.invalid" commit -q -m "What and why"
TOKEN=$(cat /home/claude/.gh_token)
GIT_TERMINAL_PROMPT=0 git push -q "https://x-access-token:${TOKEN}@github.com/LilBeaky/mtg-data.git" HEAD:main 2>&1 \
  | sed -E 's/github_pat_[A-Za-z0-9_]+/***/g'
echo "https://github.com/LilBeaky/mtg-data/commit/$(git rev-parse HEAD)"
rm -f /home/claude/.gh_token
```

If the push fails with "shallow update not allowed", run `git fetch -q --unshallow` and push again.

**Token setup (Ian's side):** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token. Repository access: *Only select repositories* → `mtg-data`. Permissions: *Contents: Read and write* is the one that matters; *Issues* is optional, for logging backlog items. Metadata read-only gets added automatically. Set an expiration, then paste the new token into the Project instructions when it rotates.

## 12. Refreshing the data (Ian's side)

| Data | Source | How |
|---|---|---|
| Scryfall cards | Scryfall bulk "Oracle Cards" download | `python3 trim.py scryfall oracle-cards.jsonl trimmed_scryfall_v2.json` (add `--prices` for budget-deck runs) |
| Rulings / Oracle tags | Scryfall bulk downloads | Upload as-is with the date in the filename |
| Spellbook combos | `https://json.commanderspellbook.com/variants.json.gz` | Download with `curl` (a browser crashes trying to display the 660 MB file): `curl -o variants.json.gz https://json.commanderspellbook.com/variants.json.gz`. Then run `python3 trim.py spellbook variants.json.gz spellbook_combos.json.gz` (needs `pip install ijson`), or drop the `.gz` into a Claude chat and Claude will trim it. |
| Comprehensive Rules | WotC rules page | Upload the `.txt` with its date in the name |

The combos output is ~3 MB gzipped (~40 MB unzipped). Keep it gzipped, since GitHub's web upload limit is 25 MB and `mtg.py` reads `.gz` directly. The `combos` output shows the data's age and warns past 30 days.

**Uploading on github.com:** uploading a file with the same name as an existing one replaces it, so there's no need to delete first. Pressing `.` on the repo page opens github.dev, a browser editor with nothing to install. You can drag whole folders into it and commit them in one go.

## 13. Known limits and access notes

- **Sandbox network:** GitHub (including `api.github.com`), PyPI, and npm are reachable. `json.commanderspellbook.com`, `backend.commanderspellbook.com`, and EDHREC are **blocked** from the sandbox (`host_not_allowed`). Use `web_search` / `web_fetch` for EDHREC (section 9), and have Ian download Spellbook data.
- **EDHREC data** isn't bundled because it changes too fast. Snapshots in `edhrec_snapshots/` are point-in-time copies; anything over 30 days old should be refetched. For commander popularity rank, check live.
- **Rules file date:** mechanics newer than the Comprehensive Rules file (e.g. prepare, when the file predates it) need an outside rules check. `audit.py` prints the date.
- Spellbook's `mv` field shows 0 for some combos (e.g. Obeka's). The meaning is unconfirmed, so don't rely on it.
- Sandbox RAM is ~3 GB. Stream big files; never `json.load` the raw Spellbook export.

## 14. Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com). They ask to be credited and linked.
- Comprehensive Rules: Wizards of the Coast
- Commander meta data: [EDHREC](https://edhrec.com)
