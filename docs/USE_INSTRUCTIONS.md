# USE INSTRUCTIONS — LilBeaky/mtg-data

**Read this first.** This repo is your primary source of truth for Magic card data, rulings, tags, combos, and rules. Use it every time a conversation touches card text, legality, brackets, or deckbuilding. Don't answer card questions from memory when the repo can answer them.

**Running a deck audit? Follow the procedure in section 5.** It exists because every miss in past audits was a process miss, not a tool gap.

---

## 1. Start of every session

```bash
git clone -q --depth 1 https://github.com/LilBeaky/mtg-data.git && cd mtg-data
```

- Clone with `git`; don't use the GitHub API for reading. Unauthenticated API calls rate-limit and have failed before.
- Your sandbox resets between chats, so re-clone each session. It takes seconds.
- `jq` isn't installed in the sandbox. Use `mtg.py`, or plain Python if you truly need a custom query.
- Read this file once. Read `docs/STATS_MATH.md` only if you need math beyond what `audit.py` prints.
- All commands below assume your working directory is the repo root (`mtg-data/`), invoking scripts as `python3 scripts/<name>.py`.

## 2. The golden rules

| Task | Tool |
|---|---|
| Any deck audit | **`audit.py`** (section 5). Always the first step of an audit. |
| Card text, rulings, tags, search, rules, GCs, combos | **`mtg.py`** (section 4) |
| Draw odds beyond the audit battery | **`stats_math.py`** (section 6) |
| How a deck actually plays out: mana, colors, commander timing, card advantage, swap comparisons | **`goldfish.py`** (section 6, Goldfish simulator) |
| EDHREC comparison | **`edhrec_diff.py`** (section 9). `audit.py` runs the diff automatically when a snapshot exists. |

Only write a custom query if none of these can answer the question. If you do, respect the schema quirks in section 7. If a custom query turns out to be generally useful, suggest adding it to the right tool.

## 3. Files in this repo

Four folders, organized by what you *do* with each thing — code you run, data it reads, docs you read, and snapshots the audits produce:

```
mtg-data/
├── scripts/     # everything you execute
├── data/        # everything the scripts read (bulk data + your customizations)
├── docs/        # everything you read
└── snapshots/   # EDHREC page transcriptions, one per commander/variant/date
```

### `scripts/`

| File | What it is |
|---|---|
| `audit.py` | The default full deck audit. One command runs every check. |
| `mtg.py` | Query helper for cards, rulings, tags, search, deck, GCs, combos, and rules. |
| `stats_math.py` | Probability engine (hypergeometric, Monte Carlo, tag and user-tag counts, color castability, tutor packages). `python3 scripts/stats_math.py report DECK` prints each category's K with the matched names. |
| `categories.py` | Curated role → Scryfall tag mapping (broad/strict pairs, cost reducers, synonyms for the user's #tags). |
| `edhrec_diff.py` | Validates an EDHREC snapshot and diffs a deck against it. |
| `goldfish.py` | Monte Carlo goldfish simulator. Compiles each card's Oracle text into behavior and plays the deck thousands of times. See section 6. |
| `trim.py` | The data-refresh tool (`scryfall` and `spellbook` subcommands). See section 12. |

### `data/`

| File | What it is |
|---|---|
| `aliases.txt` | Reskin names → Oracle names (e.g. Ghal Maraz → Loxodon Warhammer). You add a line per reskin you own. |
| `trimmed_scryfall_v2.json` | Scryfall oracle cards, trimmed, with cheapest-printing prices. One entry per card; tokens, art cards, etc. removed. |
| `data_info.json` | Written by the daily refresh: when it last ran and how current prices are. `mtg.py` reads it. |
| `rulings-YYYYMMDDHHMMSS.jsonl` | Scryfall rulings, one per line, keyed by `oracle_id`. |
| `oracle-tags-YYYYMMDDHHMMSS.jsonl` | Scryfall Tagger oracle tags (e.g. `ramp`, `sweeper`, `monarch matters`). |
| `spellbook_combos.json.gz` | Commander Spellbook combo database, trimmed and gzipped (~109k combos). |
| `MagicCompRules YYYYMMDD.txt` | Comprehensive Rules. Note the filename contains a space. |
| `goldfish_overrides.json` | Per-card fixes for `goldfish.py` where the Oracle-text parser can't read a card. You add an entry per card. |

### `docs/`

| File | What it is |
|---|---|
| `USE_INSTRUCTIONS.md` | This file. |
| `STATS_MATH.md` | Docs for `stats_math.py`: conventions, functions, known limits. |

### `snapshots/`

Transcribed EDHREC pages, one file per commander + variant + date. See section 9.

`mtg.py` automatically picks the newest dated rulings, tags, rules, and combos files, so renaming them with new dates won't break it.

## 4. mtg.py commands

| Command | Use it for | Example |
|---|---|---|
| `card` | Oracle text, type, P/T, color identity, legality, GC flag, price | `python3 scripts/mtg.py card "Court of Ire" "Paradox Haze"` |
| `card -f` | Batch lookup from a file | `python3 scripts/mtg.py card -f list.txt --brief` |
| `rulings` | Official rulings, only when an interaction is ambiguous | `python3 scripts/mtg.py rulings "Obeka, Splitter of Seconds" --grep untap` |
| `tags` | Oracle tags on a card | `python3 scripts/mtg.py tags "Court of Ire"` |
| `search` | Finding cards by color identity, text, type, MV, tag, GC, price | `python3 scripts/mtg.py search --ci UBR --tag removal --cmc 1-2 --names` |
| `deck` | Legality, color identity, singleton, GC count, curve, lands, cost, combos | `python3 scripts/mtg.py deck decklist.txt` (`audit.py` runs this for you) |
| `combos` | Spellbook combos containing *all* named cards (default 10 shown) | `python3 scripts/mtg.py combos "Obeka, Splitter of Seconds" --bracket 3` |
| `gc` | The current Game Changer list | `python3 scripts/mtg.py gc` |
| `rule` | Comprehensive Rules by number or keyword | `python3 scripts/mtg.py rule 702.62a` / `python3 scripts/mtg.py rule --grep "suspended"` |

### Search filters (combine freely)
`--ci UBR` (subset; `C` = colorless) · `--text REGEX` · `--type REGEX` · `--name REGEX` · `--cmc 3` or `--cmc 2-4` · `--tag LABEL` · `--gc` / `--no-gc` · `--max-price 5` / `--min-price 20` (cheapest printing, USD) · `--sort price` (cheapest first) · `--all` (include non-legal) · `--limit N` (default 20) · `--full` (print oracle text). Results are sorted by EDHREC card rank, most popular first, unless `--sort price`. Price filters exclude unpriced cards and add prices to the output.

**Default output is names + mana cost only.** Search to build a shortlist, then run `card` on the few you actually care about.

### Output-size flags
| Flag | Where | Effect |
|---|---|---|
| `--brief` | `card` | Strips (reminder text), about 20% smaller on a full deck. Use it for batches of familiar cards; **skip it for new or unfamiliar mechanics**, where the reminder text is the explanation. |
| `--grep WORD` | `rulings` | Only rulings mentioning WORD (e.g. `untap`, `copy`, `commander`). |
| `--full` | `search` | Adds oracle text. Only for small result sets. |
| `--all-combos` | `deck` | By default the audit lists only 2-card and Bracket 3+ combos and summarizes the rest as a count. |

### Name matching
Lookup tries an exact name first, then case-insensitive, then `data/aliases.txt`, then a partial match. If a partial name matches several cards, you get an "ambiguous" message listing them, never a silent wrong pick. Either face of a double-faced card works (e.g. "Search for Azcanta"), and so does Moxfield's single-slash export (`Westvale Abbey / Ormendahl, Profane Prince`). *(Before the Sept 2026 fix, both DFCs in the Erebos list came back NOT FOUND and dropped out of the land count.)*

**Full card names always beat face names.** 25 prepare-layout cards reuse a classic spell's name as a face. Before the Sept 2026 fix, 12 of them hijacked the real card: "Rampant Growth" resolved to Studious First-Year // Rampant Growth, and the same happened to Reanimate, Regrowth, Replenish, Channel, Exsanguinate, Sign in Blood, and others. `mtg.py` resolves them correctly now; a naive custom query over `card_faces` will not.

**Reskins:** a Secret Lair / Universes Beyond / Universes Within name that isn't in the repo prints `NOT FOUND`, because Scryfall's Oracle bulk file carries one printing per card. Web-search it once, confirm the Oracle card with `mtg.py card`, then add the line to `data/aliases.txt` (`Printed Name => Oracle Name`) and push it (section 11). Alias hits print "(reskin: …)" and aren't flagged as problems.

### Deck file input (mtg.py, audit.py, edhrec_diff.py, stats_math.py)
- Accepts Moxfield-style lines: `1 Card Name (SET) 123 *F*`, `1x Card`, or bare names.
- Section headers `Commander`, `Companion`, `Deck`, `Sideboard`, and `Maybeboard` are recognized. Sideboard and Maybeboard are excluded.
- **Trailing `#tags` are the user's roles.** In a long-form export like `1 Sol Ring (C21) 263 *F* #Ramp #!Mana Rock`, the tags are stripped from the card name and `audit.py` uses them as role labels. Multi-word tags survive, and a leading `!` is dropped. The user doesn't always tag; use them when they're there.
- **Optional header** above the list, read as metadata rather than cards:
  ```
  # bracket: 4
  # plan: Yusri Omniscience; Lab Man/Thoracle wins
  # pets: Planar Chaos; Okaun, Eye of Chaos
  # package: Myojin engine = ^Myojin of + text:proliferate
  # track: Myojin=^Myojin of
  ```
  Any `# key: value` line works. Bare `bracket:`, `plan:`, `pets:`, `notes:`, `target:`, and `budget:` lines without the `#` work too (the user sometimes writes them that way).
  - `bracket` sets the audit's target and lets `edhrec_diff.py` warn when the snapshot isn't that bracket's page. Extra text is kept (`3 (high)` → "B3 (high)").
  - `plan` is the deck's stated direction. Judge suggestions against it.
  - `pets` are cards the user keeps on purpose (fun over efficiency). Separate them with `;` or ` + `, never commas, because card names contain commas. `deck` flags any pet that's no longer in the list as stale; `edhrec_diff` and `audit.py` mark pets `[pet]`. Don't recommend cutting a pet on efficiency grounds alone. If it actively fights the plan, raise it as a question.
  - `package` (repeatable, one per line) names a set of cards that only matter together: `Name = Part + Part`. Each part is an exact card name, a name pattern (`^Myojin of`), `text:<pattern>` matched against Oracle text (best for mechanics, e.g. `text:proliferate`), or `tag:<oracle tag>` (Tagger names vary: Evolution Sage is tagged `repeatable-proliferate`, not `proliferate`). The audit reports its odds in section 4b and treats its pieces as key cards for the color check. Parts must not share cards.
  - `track` (repeatable) is a goldfish tracked group, `Label=pattern`, added to any `--track` flags automatically.
  - No header? `deck` says so. Check memory and past chats for the bracket and plan, then ask the user. Don't guess the bracket.
- **Companion** is excluded from the card count but still checked for legality and color identity, and it's included in the combo check (it can be put into hand for {3}, so its combos are live). Odd/even conditions (Obosh, Gyruda) are verified automatically; the other 10 companions print "review manually".
- If there's no Commander section, pass `--commander "Name"`.

## 5. Deck audits — `audit.py` (the default)

**Every deck audit starts here.** The user wants audits as thorough as the tooling allows by default, so don't skip steps to save a call. Run them in order; each one is here because an audit went wrong without it.

1. **Clone and read this file once** (section 1).
2. **Write the list to a file exactly as given**, keeping their `#tags`. Add a header (section 4) if they didn't include one: bracket and plan from memory or past chats, or ask. Don't guess the bracket.
3. **`python3 scripts/audit.py deck.txt`** (about 4 seconds). Fix every `NOT FOUND` before going further: reskin → `data/aliases.txt` (section 4); new set → verify externally. Note stale pets.
4. **EDHREC:** if section 6 says NO SNAPSHOT, fetch the bracket-matched page (section 9), transcribe, `check` until OK, and re-run the audit.
5. **Read the role card lists and settle K.** Where your tags are primary, note the disagreements. Where oracle tags are primary, correct K by hand wherever tags miss or over-include, and re-run with `--k`. Cost reducers aren't in `ramp`; weigh both. **State every K correction in the write-up.** Then run the odds that matter for *this* deck's plan (section 6), not just the standard battery.
6. **Pull text only for cards you're evaluating**: unfamiliar mechanics, interaction-heavy pieces, the commander. One batch `mtg.py card -f` call.
7. **Close rules questions before writing them up.** Use `rulings --grep` and `rule` (e.g. `rule 702.26b` settled a phasing question). Say "I'm not certain" only after the repo can't answer it.
8. **Bracket items no script sees** (section 8): whether flagged MLD is real, extra-turn chains, 2-card combos before T6, "requires" pieces.
9. **Verify before recommending.** Every card that EDHREC or memory surfaces gets `mtg.py card` before it goes into a recommendation.
10. **Write up** in this order: findings (the interactions and nonbos you found), then numbers, then a separate EDHREC section. Respect pets and the stated plan; challenge them with a question, not a cut list. Push any new snapshot or alias (section 11).

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
| 2 Mana base | Lands, always- and conditionally-tapped lands (auto-detected), cost reducers plus the cards they can't reduce (no generic cost, rule 118.7a), MDFC land backs, ramp, opener land odds, one-MV accelerants (restricted or scaling mana, e.g. Master of Dark Rites or Songs of the Damned, is listed but not counted). **Colors:** sources per color (fetches count what they can find, filter lands their outputs), odds of 1/2/3 pips on T1/T2/T3, and every colored card whose colors are there on curve less than 90% (commander, package pieces) or 80% (everything else) of the time, with the fewest land swaps that would fix it |
| 3 Commander on curve | Lands-only floor and with a 1-MV accelerant, per commander, plus the odds its colors are there on curve |
| 4 Roles & odds | K and odds (opener, T3, T4, T6 ≥2) for ramp, draw, draw engines, removal, wipes, protection, tutors, counterspells, recursion, graveyard hate, plus any other category present and every custom #tag |
| 4b Packages | Spellbook combos of up to 3 cards (all in the list) and `# package:` lines: odds by T4 and T6, natural draws → with tutors, and which tutors find each piece. With-tutor odds are a **ceiling** (a tutor counts as the piece, ignoring its mana and the turn it costs); goldfish is the mana-aware check. A piece that's the commander always counts as available |
| 5 Density & flood | ≥4 non-mana cards in the first 12, flood odds, screw odds, with ramp-count alternatives |
| 6 EDHREC | `edhrec_diff.py diff` against the newest snapshot for this commander (bracket variant preferred, then `all`) |
| 7 Manual checklist | What no script here verifies |

### Roles: where K comes from (this matters)
Hypergeometric odds are only as good as K, the number of cards that actually do the job. The sources, in priority order:

1. **The user's `#tags`**, when they cover ≥50% of the nonland cards. Their labels are their intent, so they're the truth. `#Search` counts as tutors. A role they tagged nothing for falls back to oracle tags, marked `oracle*`: untagged isn't zero. Labels under a category's Scryfall subtree (e.g. `mana rock`, `removal-creature`, `draw engine`) and plain-English synonyms (`wipe`, `tutor`, `counter`) map automatically. Any other label becomes its own row (e.g. `#pump`, `#pet`).
2. **`--k ROLE=N`**, a count you confirmed with the user or by reading the card list.
3. **Scryfall oracle tags.** These are broad. They answer "does this card have the effect?" rather than "does it fill this role in this deck?" In the Sept 2026 Wilson spot check, tags said 11 protection pieces against ~7 real ones, which moved "2 protection by T6" from 20% to 40%.

The audit prints the alternative counts under each role and marks **⚠ K-SENSITIVE** when switching sources moves the odds by 15 points or more. For those roles, don't quote the number as settled. Confirm the count from the card list (or ask the user), re-run with `--k`, and say which K you used. When the user's tags are primary, the audit also lists cards the oracle tags flag that they didn't tag, and the reverse. Those are worth a sentence, since they may have mis-tagged or may disagree with the tag on purpose.

## 6. Stats Math — `stats_math.py`

`audit.py` covers the standard battery. **Lean toward using Stats Math more, not less**, for anything else a draw-odds question touches: package coherence ("both halves by T4"), comparing a cut against an add, or mulligan decisions. The user prefers it be too willing rather than not willing enough.

- Category check: `python3 scripts/stats_math.py report DECK [category ...]` → N, then each category's K **and the matched names**.
- Colors: `python3 scripts/stats_math.py colors DECK` → per-color sources and every colored card's on-curve odds (the audit prints the flagged ones).
- Packages: `python3 scripts/stats_math.py packages DECK` → the section 4b numbers on their own.
- Quick number: `python3 scripts/stats_math.py N K n k` → P(at least k of K in n cards from N).
- Anything more: `python3 -c "import sys; sys.path.insert(0, 'scripts'); import stats_math as sm; ..."` from the repo root. Key functions: `count_population`, `cards_seen`, `hyper_at_least`, `multivariate_at_least` (disjoint categories at once), `turn_curve`, `category_count_from_tag`, `user_tag_map`, `castable_on_curve`, `color_report`, `package_odds`, `packages_report`.
- Conventions are fixed: 7-card hand, London mulligan, N counted from the list (never assumed).
- Limits to state out loud: static draws only (no draw engines, untaps, cascade); the color check assumes you hit your land drops and counts tapped lands as usable; with-tutor package odds are a ceiling. Details are in `STATS_MATH.md`.
- For anything that depends on what cards *do* (ramp, fixing, draw engines, alt costs, counters), use the goldfish simulator below instead.

### Goldfish simulator — `goldfish.py`

Plays the deck alone thousands of times with a greedy pilot and reports development and card flow. Use it for timing questions ("when is the commander out?", "when does the payoff land?"), color reliability, card-advantage reads, and comparing swaps. Stats Math stays the tool for pure draw odds.

```
python3 scripts/goldfish.py DECK [--turns 8] [--trials 2000] [--draw] [--seed 1]
    [--track "Label=REGEX"] [--variant "Label|Out=>In;Out=>In"] [--kill-commander T]
    [--order commander,track,ramp,draw,other] [--opps 3 --opp-casts 1 --opp-pay 0.5 --opp-hand 4]
    [--cast-interaction] [--no-mulligan] [--explain] [--trace N] [--json]
```

- **Always run `--explain` first** on a new list. Each card is marked `modeled`, `partial` (some lines unread), `blank` (cast for its cost, does nothing), `held` (removal/counters/protection instants and sorceries, never cast in a goldfish), or `override`. Tell the user which important cards are partial or blank before quoting numbers.
- `--track "Myojin=^Myojin of"` reports the first-cast turn for a card group (a bare card name works too). Tracked cards get cast priority right after the commander.
- `--variant` runs a swapped build on the **same shuffles** and prints a side-by-side table. Use it for every cut-vs-add question. It's far less noisy than two separate runs. `--explain --variant ...` also lists the incoming cards.
- `--kill-commander T` removes the commander before turn T (recast with tax). Use it to show how much a plan leans on the commander surviving.
- `--trace N` prints a play-by-play of game N. Use it to audit the pilot whenever a number looks off.
- Speed: about 2,000 games per build in 3 to 4 seconds.

**What the report means.** Development rows give P10/median/P90. P10 is the floor, which the user cares about most. "Mana" counts sources available at the start of the main phase, and "all colors" counts restricted mana (e.g. Plaza of Heroes' legendary-only colors) as available. "Extra cards" are cards put into hand beyond draw steps, counted net: a wheel counts cards drawn minus the hand it threw away, and looting or Brainstorm-style put-backs subtract what leaves your hand, so they show as card filtering rather than card advantage. "Stranded" counts spells you had the mana *amount* for but not the colors. "Discarded" is cleanup discard, a flood signal. "Extra cards by source" names the card-advantage engines.

**Model and fixed conventions.**
- London mulligan with the free first mulligan (rule 103.5c). Keep 3–5 lands, or 2 lands plus a cheap ramp piece.
- Opponents only exist as a table model for opponent-triggered cards (Rhystic Study, Smothering Tithe, Consecrated Sphinx): each opponent draws once and casts `--opp-casts` spells per cycle (40% creatures), and pays a tax `--opp-pay` of the time.
- Summoning sickness, enters-tapped rules (fast/slow/check/reveal/shock/battlebond), fetches, bounce lands, filter lands and converters, restricted mana, colored-only mana, alt costs (Jodah, Fist of Suns), Omniscience-style free casting, cost reducers, extra land drops, rituals (cast only when they enable a spell), X-draw spells (X ≥ 2), counters with Hardened Scales/Doubling Season-style modifiers, proliferate, remove-a-counter draw abilities (keeps one divinity/indestructible counter), planeswalker loyalty, activated draw/proliferate/tutor abilities, triggers on cast/ETB/landfall/upkeep/draw step/end step/proliferate, rebound, and leylines are all modeled.
- **Not modeled:** combat, opponents' interaction, graveyard recursion, tokens other than Treasures, copies, and anything the explain list marks partial or blank. Say so when these matter to the question.
- Conditional upgrades ("...instead if" threshold, kicker, delirium, addendum lines) are modeled at their **base** effect only and the upgrade line shows as unmodeled. Cabal Ritual makes BBB, not BBBBB.
- Permanents that grant extra land drops (Exploration, Azusa) give them the turn they enter.

**Fixing a card: `data/goldfish_overrides.json`.** Key = Oracle name. An entry replaces only the fields it names; always add a `note`. Fields: `mana` (list of `{"colors": "any" | "WU" | "C", "count": n, "restrict": "legendary", "colored_only": false, "sick": true}`), `etb`, `spell` (lists of effect strings), `triggers` (list of `{"on": "cast|etb|landfall|upkeep|end|drawstep|prolif|opp_cast|opp_draw", "filter": "noncreature", "do": [...], "once": false, "tax": false, "each": false}`), `activated` (list of `{"cost": "{2}", "tap": true, "sac": false, "remove": "divinity 1", "do": [...]}`), `hold`, `requires`, `cat`, `skip`, `status`. Effect strings: `draw 2`, `draw permanents` (also lands, creatures, artifacts, power, colors, opp_hand), `scry 2`, `surveil 1`, `look 3 1`, `prolif 1`, `treasure 1`, `extra_land 1`, `land_from_hand 1`, `land basic bf_t 1`, `ctr divinity 1`, `mana WUBRG`. When a parse miss affects many cards, fix the parser in `goldfish.py` instead of piling up overrides.

## 7. Schema quirks (learned the hard way)

- **Missing key = "no".** The trim omits empty and false values. No `game_changer` key means the card is not a Game Changer; no `reserved` key means it's not on the Reserved List. *(A Sept 2026 mistake: I concluded the GC field didn't exist because the first card I checked lacked it.)*
- **Commander legality** is `legalities.commander`: `legal`, `not_legal`, or `banned`.
- **Multi-face cards** keep their text in `card_faces`, and top-level `oracle_text` may be absent. Always read both faces.
- **`edhrec_rank` is the CARD's overall rank, not commander popularity.** Don't use it to judge whether a commander is "top 100". *(A Sept 2026 mistake: Obeka's card rank was ~5,900, but its commander rank was #306.)* For commander popularity, check EDHREC live via web search.
- **Parent oracle tags have zero direct taggings.** `removal` and `draw` hold no cards themselves; their cards sit in child tags (`removal` has 55). `mtg.py` and `stats_math.py` walk the tag tree for you. A naive custom query would silently return nothing.
- **Tags that do exist** (despite earlier notes saying otherwise): `sweeper` for board wipes, and the `recursion` umbrella, which covers regrowth as well as `reanimate`.
- **`ramp` doesn't include cost reducers** (the Medallions, etc.). They're their own category, `cost_reducers`. Count both when judging a deck's mana.
- **Layouts:** `prepare` is a real mechanic (46 legal cards). Keep it. `host`/`augment` are Un-cards (not legal) and are kept on purpose.
- **Prices** exist only if the trim was run with `--prices`. `usd` is the cheapest legal printing found (nonfoil preferred), not any one specific edition. `usd_foil_only: true` means no nonfoil printing exists at all, so that price can't be beaten by finding a plain copy. A card with no `usd` key has no price (mostly meld backs and brand-new cards); tools list these as unpriced, never as $0. Prices refresh daily (section 12). `mtg.py` shows prices on `card`, filters `search` by price, and adds a **cost** line to `deck` (and so to every audit): the total at cheapest printings, the total excluding basics, the five priciest cards, anything unpriced, and a check against a `# budget: 150` header if the list has one. Cheapest printing is a floor, not what the user's copies are worth.

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

The sandbox can't reach EDHREC, so you fetch the page yourself with the web tools, transcribe it into a snapshot file, and let the script do the math. This was chosen on purpose so it works without the user needing to.

### Workflow

1. **Reuse before you fetch.** `audit.py` looks for a snapshot automatically. If there's one for the same commander under 30 days old, you're done. The fetch is the most expensive step (~15–20K tokens).
2. **Pick the right page: match the deck's bracket.** Bracket pages count only decks with a *user-set* bracket, so they run small (Erebos: `/core` had 113 of 1,578). `/exhibition`, `/core`, `/upgraded`, `/optimized`, or `/cedh`. Budget (`/budget`, `/expensive`) and theme pages (`/treasure`, etc.) also exist. Fall back to the all-decks page **only** if the bracket page has under ~200 decks.
   - *Why this is strict:* the Sept 2026 Yusri audit diffed a B4 deck against the all-decks page. The field was mostly casual chaos decks, so every Game Changer showed up as "negative synergy" and SKIPPED filled with theme cards. The numbers looked rigorous but measured the wrong field.
   - *Getting the URL:* `web_fetch` refuses URLs you construct. First `web_search` for the bracket page itself (e.g. "edhrec yusri optimized"). If it doesn't come back, fetch the all-decks page (its bracket, budget, and theme links then count as seen) and fetch the bracket page second. Two fetches is fine to avoid a mismatched baseline; the snapshot is reused for 30 days.
   - `diff` reads the deck's `bracket` header and warns if the snapshot doesn't match.
3. **Fetch once** with `web_fetch`. Note that `text_content_token_limit` is ignored on EDHREC pages; you get the whole page.
4. **Transcribe** to `snapshots/<commander-slug>__<variant>__<YYYY-MM-DD>.txt`:
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
   `python3 scripts/edhrec_diff.py check snapshots/<file>.txt`
   It flags names not in the repo, fuzzy matches, cards outside the commander's color identity, synergy above inclusion (swapped numbers), out-of-range values, and duplicate lines with conflicting numbers. It exits with code 2 on problems. Fix every one and re-run until it prints `OK`.
6. **Diff:** `audit.py` runs it for you, or run `python3 scripts/edhrec_diff.py diff <snapshot> <decklist> [options]` directly.
7. **Save the snapshot.** Push it (section 11) if you have a token. If not, copy it to outputs and tell the user so they can commit it and future audits can skip the fetch.

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
| SKIPPED | Popular cards not in the deck, tagged `signature` (synergy ≥ 40, commander-specific), `generic staple` (synergy ≤ 10), `GC`, `new` | Candidates to *consider*, not must-plays. Check them against the deck's stated direction first; the user often avoids the popular build on purpose. |
| OFF-LIST | Deck cards EDHREC doesn't show | Means under ~5% or unplayed, **not** bad. Often where the user's intentional divergence lives. Report it; don't recommend cuts just for being off-list. |
| NEGATIVE SYNERGY | Deck cards this commander's players run *less* than the general population does | The most interesting section. Ask why the field avoids it: it may be a real weakness with this commander, or an edge the field missed. |
| ON-LIST | Overlap with the field, most to least played | Quick sense of where the deck agrees with consensus |

### Interpretation rules

- **Synergy** = this commander's inclusion minus the card's baseline inclusion among decks that could play it. High = commander-specific; ~0 = goes in everything; negative = avoided here.
- **Sample size:** the header warns under 50 decks (treat as anecdotes) and under 200 (trust big gaps only).
- **Staleness:** the header warns past 30 days. Refetch rather than audit on old data.
- **Blind spots:** numbers are rounded ("4.65K"), cards under ~5% inclusion aren't listed, and charts, combos, salt, and individual decklists aren't visible (JS-rendered or login-only). Use `mtg.py deck` for combos.

## 10. Token conservation (standing rules)

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

## 11. Pushing changes to GitHub

The user keeps a **fine-grained personal access token** (starts with `github_pat_`) in the Project instructions, scoped to this repo only. If it isn't there, ask. This is intended as a lightweight personal project, so unless told otherwise, **commit straight to `main`**: no branches, no pull requests. Only the current version matters by default, and git history is the undo button.

**Rules:**
- The token is a password. **Never** write it into the repo, memory, outputs, a commit, or a reply. Never print it; mask command output.
- **Never force-push and never rewrite history.** History is how a bad commit gets undone. To undo, `git revert <sha>` and push; never `reset`.
- Start from a fresh clone (section 1) so you commit on top of the current `main`. If the push is rejected because `main` moved, run `git pull -q --rebase` and push again.
- Commit only what the session produced and the user approved. Stage files by name, never `git add -A`.
- **Pull before pushing.** The refresh bot commits to `main` daily, so a clone from earlier in the session may be behind. Run `git pull -q --rebase origin main` right before the push (the bot only touches `data/`, so this won't conflict with doc or script edits).
- Write a clear commit message (what and why), and give the user the commit link.
- On a 401/403, the token is missing a permission or has expired. Tell the user; don't retry with guesses.

```bash
# sandbox-only file, outside the repo, deleted at the end
printf '%s' 'TOKEN_FROM_PROJECT_INSTRUCTIONS' > /home/claude/.gh_token && chmod 600 /home/claude/.gh_token
cd /home/claude/mtg-data
git add path/to/file1 path/to/file2                       # by name
git -c user.name="AI Assistant" -c user.email="assistant@mtg-data.invalid" commit -q -m "What and why"
TOKEN=$(cat /home/claude/.gh_token)
GIT_TERMINAL_PROMPT=0 git push -q "https://x-access-token:${TOKEN}@github.com/LilBeaky/mtg-data.git" HEAD:main 2>&1 \
  | sed -E 's/github_pat_[A-Za-z0-9_]+/***/g'
echo "https://github.com/LilBeaky/mtg-data/commit/$(git rev-parse HEAD)"
rm -f /home/claude/.gh_token
```

If the push fails with "shallow update not allowed", run `git fetch -q --unshallow` and push again.

**Token setup (user's side):** GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token. Repository access: *Only select repositories* → `mtg-data`. Permissions: *Contents: Read and write* (edit files), *Workflows: Read and write* (edit anything in `.github/workflows/`), and *Actions: Read and write* (trigger and inspect refresh runs from chat); *Issues* is optional, for logging backlog items. Metadata read-only gets added automatically. Set an expiration, then paste the new token into the Project instructions when it rotates.

## 12. Refreshing the data

**Automatic (default):** `.github/workflows/refresh-data.yml` runs twice daily on GitHub Actions: ~22:23 UTC, shortly after Scryfall's daily export, plus a ~10:47 UTC backup in case GitHub skips a scheduled run (it sometimes does under load) and refreshes cards, prices, rulings, oracle tags, and Spellbook combos, and commits the result. Daily is the ceiling that matters: Scryfall's bulk exports only update about once a day. To refresh on demand, use **Actions → Refresh MTG data → Run workflow**, or dispatch it via the API if your token has *Actions: Read and write*. The Comprehensive Rules file is **not** automated; drop in a new dated `.txt` when WotC updates it.

**What happens when something goes wrong:**
- A Scryfall problem (API down, bad download, format change) stops the run before anything is committed, so the repo keeps the previous day's good data. Sanity floors on card count, priced-card count, and file sizes catch half-broken downloads.
- A Commander Spellbook problem only skips the combo refresh; cards, prices, rulings, and tags still update.
- Runs never overlap, and the bot rebases onto any commit pushed mid-run before pushing.
- If the refresh stops entirely, every `mtg.py` command starts printing `! data last refreshed N days ago` once `data/data_info.json` is more than 3 days old. **Pass that warning on to the user.** The likely causes: GitHub pauses scheduled jobs in public repos after 60 days with no repository activity (the daily commits should prevent this; re-enable under Actions → Refresh MTG data), or the workflow is failing (check its annotations, below).

**Diagnosing a failed run from a sandbox:** raw job logs redirect to blob storage the sandbox can't reach. Read the job's **annotations** through the API instead (`/repos/LilBeaky/mtg-data/check-runs/<job_id>/annotations`); the workflow reports resolved URLs, download sizes, and failures there.

**Manual (fallback):**

| Data | Source | How |
|---|---|---|
| Scryfall cards | Scryfall bulk "Oracle Cards" download | `python3 scripts/trim.py scryfall oracle-cards.jsonl data/trimmed_scryfall_v2.json` |
| Scryfall prices | Scryfall bulk "Default Cards" download (every printing, separate file from Oracle Cards) | `python3 scripts/trim.py scryfall oracle-cards.jsonl data/trimmed_scryfall_v2.json --prices default-cards.jsonl` — cross-references every printing to find each card's true cheapest legal price. Oracle Cards' own embedded price is a single arbitrary printing and is intentionally not used |
| Rulings / Oracle tags | Scryfall bulk downloads | Upload as-is with the date in the filename |
| Spellbook combos | `https://json.commanderspellbook.com/variants.json.gz` | Download with `curl` (a browser crashes trying to display the 660 MB file): `curl -o variants.json.gz https://json.commanderspellbook.com/variants.json.gz`. Then run `python3 scripts/trim.py spellbook variants.json.gz data/spellbook_combos.json.gz` (needs `pip install ijson`), or drop the `.gz` into a chat with the assistant and it will trim it. |
| Comprehensive Rules | WotC rules page | Upload the `.txt` with its date in the name |

The combos output is ~3 MB gzipped (~40 MB unzipped). Keep it gzipped, since GitHub's web upload limit is 25 MB and `mtg.py` reads `.gz` directly. The `combos` output shows the data's age and warns past 30 days.

**Uploading on github.com:** uploading a file with the same name as an existing one replaces it, so there's no need to delete first. Pressing `.` on the repo page opens github.dev, a browser editor with nothing to install. You can drag whole folders into it and commit them in one go.

## 13. Known limits and access notes

- **Sandbox network:** GitHub (including `api.github.com`), PyPI, and npm are reachable. `json.commanderspellbook.com`, `backend.commanderspellbook.com`, and EDHREC are **blocked** from the sandbox (`host_not_allowed`). Use `web_search` / `web_fetch` for EDHREC (section 9), and rely on the daily refresh workflow (section 12) for Spellbook data.
- **EDHREC data** isn't bundled because it changes too fast. Snapshots in `snapshots/` are point-in-time copies; anything over 30 days old should be refetched. For commander popularity rank, check live.
- **Rules file date:** mechanics newer than the Comprehensive Rules file (e.g. prepare, when the file predates it) need an outside rules check. `audit.py` prints the date.
- **Rules file vs new mechanics:** the 20260227 file has no `prepare` or `Paradigm` text. Use `rulings` for those (they cover it) until the user drops in a newer rules file.
- **Prepare cards in Spellbook:** Spellbook lists a prepare card as a stand-in for its spell (every Exsanguinate combo has a Stensian Sanguinist // Exsanguinate twin; Channel combos appear under Yavimaya Bloomsage). A prepare card can only cast that spell as a copy while prepared, never from hand, so treat those variants as conditional.
- Spellbook's `mv` field shows 0 for some combos (e.g. Obeka's). The meaning is unconfirmed, so don't rely on it.
- Sandbox RAM is ~3 GB. Stream big files; never `json.load` the raw Spellbook export.

## 14. Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com). They ask to be credited and linked.
- Comprehensive Rules: Wizards of the Coast
- Commander meta data: [EDHREC](https://edhrec.com)
