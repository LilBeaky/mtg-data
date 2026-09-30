# USE INSTRUCTIONS — LilBeaky/mtg-data

For the assistant. This repo is the source of truth for card text, rulings, tags, combos, legality, and rules. Answer card questions from it, never from memory. Section numbers are referenced by the scripts; keep them stable.

## 1. Session start

```bash
git clone -q --depth 1 https://github.com/LilBeaky/mtg-data.git && cd mtg-data
```
Re-clone every session (sandbox resets). Use git, not the GitHub API, for reading. No `jq`; use the scripts or plain Python. Run everything from the repo root as `python3 scripts/<name>.py`. Each script prints usage with no args (tutors.py: `-h`). Read this file once per session.

## 2. Which tool

| Task | Tool |
|---|---|
| Deck audit (always first) | `audit.py DECK` (§5) |
| Card text, rulings, tags, search, deck check, GCs, combos, rules | `mtg.py` |
| Draw odds beyond the audit | `stats_math.py` (§6) |
| Tutor chains / access odds | `tutors.py` (§6) |
| How a deck plays out (timing, mana, swaps) | `goldfish.py` (§6 → `docs/GOLDFISH.md`) |
| EDHREC comparison | `edhrec_diff.py` (§9); audit runs it if a snapshot exists |
| Data refresh | automatic (§12); `trim.py` is the manual fallback |

Custom queries only when no tool answers; respect §7. Suggest folding useful ones into a tool.

## 3. Layout

`scripts/` (code) · `data/` (bulk data + `aliases.txt`, `goldfish_overrides.json`) · `docs/` · `snapshots/` (EDHREC transcriptions) · `tests/` (edge-case test deck, goldfish fixtures, `goldfish_units.py` + `smoke.py`; run `python3 tests/smoke.py` after changing any script, before pushing). Scripts pick the newest dated rulings/tags/rules files automatically.

## 4. mtg.py and deck files

**Commands:** `card NAME...` · `card -f FILE [--brief]` · `rulings NAME [--grep WORD]` · `tags NAME` · `search [filters] [--full]` · `deck FILE [--all-combos]` · `combos NAME... [--bracket N]` (combos containing all named cards) · `gc` · `rule 702.62a` / `rule --grep WORD`.

**Search filters:** `--ci UBR` (subset; `C` = colorless) `--text/--type/--name REGEX` `--cmc 3|2-4` `--tag LABEL` `--gc/--no-gc` `--max-price/--min-price N` `--sort price` `--all` (include non-legal) `--limit N`. Default output is names only: search → shortlist → `card`.

**`--brief`** strips reminder text; skip it for unfamiliar mechanics.

**Name matching:** exact → case-insensitive → `aliases.txt` → partial; ambiguous partials list candidates. Either DFC face and Moxfield's single-slash DFC export work. Full names beat face names (prepare cards reuse classic spell names as faces; `mtg.py` handles it, naive queries don't). A reskin prints `NOT FOUND`: web-search it, confirm the Oracle card, add `Printed Name => Oracle Name` to `data/aliases.txt`, push.

**Deck files** (all tools): Moxfield lines (`1 Name (SET) 123 *F*`, `1x Name`, bare names). Headers `Commander`, `Companion`, `Deck`, `Sideboard`, `Maybeboard` recognized; the last two excluded. No Commander section → `--commander "Name"`. Trailing `#tags` are the user's role labels (leading `!` dropped); use them when present.

**Optional header lines** (`# key: value`; bare `bracket:`/`plan:`/`pets:`/`notes:`/`target:`/`budget:` also work):
- `bracket` — audit target; `3 (high)` is kept as "B3 (high)".
- `plan` — the deck's stated direction; judge suggestions against it.
- `pets` — kept on purpose. Separate with `;` or ` + ` (never commas). Never suggest cutting a pet on efficiency alone; raise conflicts as a question.
- `package` (repeatable) — `Name = Part + Part`; parts are exact names, `^pattern`, `text:<regex>`, or `tag:<tag>`; parts must not share cards. Reported in audit §4b and tutors.py.
- `track` (repeatable) — goldfish group, `Label=pattern`.
- `key` — single important cards (`;`-separated) for tutors.py access odds.
- `budget` — adds a budget check to the cost line.
- No header: get bracket and plan from memory/past chats or ask. Never guess the bracket.

`deck` also checks commander eligibility (CR 903.3), pairing (partner, partner—X, partner with, background, Doctor's companion), exactly 100 cards, and meld results listed as deck cards.

Companion: excluded from the count, checked for legality/color identity, included in combos. Obosh/Gyruda conditions verified; other companions print "review manually".

## 5. Audit procedure

The user wants audits as thorough as the tooling allows. Every step exists because an audit went wrong without it.

1. Write the list to a file exactly as given (keep `#tags`); add a header if missing (§4).
2. `python3 scripts/audit.py deck.txt` (~4s). Fix every `NOT FOUND` first (reskin → alias; new set → verify externally). Note stale pets.
3. No EDHREC snapshot → fetch and transcribe one (§9), then re-run.
4. Settle K for each role: read the printed card lists. The user's tags win when they cover ≥50% of nonlands; otherwise oracle tags, which **overcount** (candidate lists, not K). Correct with `--k role=N` and re-run. Cost reducers aren't in `ramp`. Treat anything marked ⚠ K-SENSITIVE as unsettled until confirmed. State every K correction in the write-up.
5. Run the odds that matter for *this* deck's plan (§6), not just the battery. Run tutors.py for tutor-heavy decks; goldfish after the audit if needed.
6. Pull oracle text only for cards under evaluation, in one `card -f` batch.
7. Close rules questions with `rulings --grep` / `rule` before writing them up. "I'm not certain" only after the repo can't answer.
8. Manual bracket items (§8).
9. Verify every card from EDHREC or memory with `mtg.py card` before recommending it.
10. Write-up order: findings (interactions, nonbos), then numbers, then a separate EDHREC section. Challenge pets/plan with questions, not cut lists. Push new snapshots/aliases.

**audit.py flags:** `--bracket N` `--k ROLE=N` (repeatable) `--draw` `--commander` `--snapshot PATH` / `--no-edhrec` `--min N` / `--limit N` (EDHREC diff) `--all-combos` `--no-lists` (re-runs).

**Output sections:** 1 legality/bracket (commanders, size, GCs, 2-card combos, extra turns, possible MLD) · 2 mana (lands, tapped lands, reducers, ramp, MDFC backs, colors: sources, pip odds, cards under 90%/80% on-curve with fixes; restricted-mana lands listed, not counted; multi-face cards judged by their easiest castable face) · 3 commander on curve · 4 role odds (+ custom tags) · 4b packages (with-tutor odds are a **ceiling**: ignores mana and turns) · 5 density/flood/screw · 6 EDHREC diff · 7 manual checklist.

## 6. Analysis tools

**Stats Math (`stats_math.py`)** — lean toward using it more, not less: package coherence, cut-vs-add, mulligans.
- `report DECK [cat...]` (K + matched names) · `colors DECK` · `packages DECK` · `N K n k` (P ≥k of K in n from N).
- Deeper: `import stats_math as sm` with `sys.path.insert(0,'scripts')`. Functions and conventions in `docs/STATS_MATH.md`.
- Fixed: 7-card hand, London mulligan, N counted from the list. Static draws only (no engines/untaps/cascade); colors assume land drops hit. Say so when it matters.

**Tutor analysis (`tutors.py DECK [--commander] [--draw] [--turns 4,6] [--no-lists] [--trials N]`)** — for any deck with more than a couple of tutors or questions about tutor packages. Run after the audit.
- Reads every "search your library" including typecycling, transmute, triggers; records repeatable vs one-shot, destination, and exact target filter. Graveyard-destination tutors end chains; battlefield-destination cards can't be cycled/cast onward.
- ⚠ marks approximations (MV X or less, "shares a type", opponent picks). Flag them when a conclusion rests on one.
- Report: 1 inventory (dead tutors, shallow pools) · 2 chains · 3 coverage · 4 dependencies (single points of failure) · 5 access odds for `key`/package cards (exact) · 6 package assembly (sampled). A second view sets aside find-anything tutors to expose package structure.
- NOT FOUND cards are warned about and left out. Odds ignore mana and chain time ("can you get there", not "how fast"). Commander tutoring is shown separately as a ceiling. Not tracked: searching others' libraries, tutoring from graveyard.

**Goldfish (`goldfish.py`)** — see `docs/GOLDFISH.md` before running it. Always `--explain` first on a new list and report partial/blank cards before quoting numbers. It reads `key`/`package` header lines as tutor priorities; report its "tutor targets" line when tutoring matters. It plays the deck in a vacuum: opponent-dependent cards run on fixed approximations (`~opp`) or do nothing (`vacuum`); say which matter. Its disruption section is the resilience read: with a bracket 2-4 it runs the bracket's interaction ladder (`data/goldfish_gradients.json`; 5 clean baselines + 15 rungs per shuffle). Lead with the breakpoint and "what changed at the breakpoint" (what the deck folds to), and treat any Δ inside the noise band as noise. Without a bracket it falls back to sampled events; never guess the bracket to get the ladder. Its combat section is the clock: damage by turn, commander damage and poison per opponent, when the first opponent and the whole table die (killing all three ends the game), and triggers fired by kind. Opponents have no blockers yet and never attack, so quote the clock as a ceiling.

## 7. Schema quirks

- Missing key = no/false (`game_changer`, `reserved` omitted when false).
- Commander legality: `legalities.commander` = `legal` / `not_legal` / `banned`.
- Multi-face text lives in `card_faces`; top-level `oracle_text` may be absent. Read both faces.
- `edhrec_rank` is card rank, not commander popularity. Check commander rank live.
- Parent oracle tags (`removal`, `draw`) have zero direct taggings; walk the tree (the scripts do).
- `sweeper` and `recursion` tags exist. `ramp` excludes cost reducers (`cost_reducers`).
- `prepare` is a real, legal layout; `host`/`augment` are Un-cards kept on purpose.
- `usd` = cheapest legal printing (nonfoil preferred); `usd_foil_only: true` means no nonfoil exists; no `usd` = unpriced, never $0. A floor, not the user's copies' value.
- `type_line` is the reliable field for subtypes. Brand-new cards may be absent; flag for external verification.

## 8. Bracket checks

- Audit §1 automates: GC count vs allowance (B1–2: 0, B3: ≤3, B4–5: unlimited), 2-card combos, extra-turn cards, MLD regex flags.
- Spellbook tag → bracket (Ruthless 4, Spicy/Powerful 3, Oddball/Core 2, Exhibition 1) is Spellbook's opinion; review, don't rule. Combos with "requires" need that generic piece present.
- By hand: real MLD vs regex flag, extra-turn *chains*, whether a 2-card combo can fire before T6.
- B3 forbids 2-card combos *before turn 6*; a late one can still be B3. Say so.
- When designing, run `combos` on key cards before finalizing.

## 9. EDHREC snapshots

EDHREC is meta signal, never card truth. Sandbox can't reach it; use web tools.
1. Reuse a snapshot under 30 days old (the fetch costs ~15–20K tokens).
2. Match the deck's bracket: `/exhibition`, `/core`, `/upgraded`, `/optimized`, `/cedh`. Fall back to the all-decks page only if the bracket page has under ~200 decks. `web_fetch` refuses constructed URLs: `web_search` for the bracket page, or fetch the all-decks page first (its links then become fetchable).
3. Fetch once; transcribe to `snapshots/<commander-slug>__<variant>__<YYYY-MM-DD>.txt`:
   ```
   # commander: Name   (partners/backgrounds joined with " + ")
   # variant: upgraded
   # url: ...
   # decks: 1234
   # fetched: YYYY-MM-DD
   Card Name|inclusion%|synergy%[|eligible decks if different from page total]
   ```
   Every card from every section, lands included, basics skipped; numbers exactly as shown.
4. `python3 scripts/edhrec_diff.py check <snapshot>` until `OK` (mandatory).
5. Diff runs inside the audit, or `edhrec_diff.py diff SNAP DECK [--commander] [--min N] [--limit N] [--mv odd|even]`.
6. Push the snapshot. Never paste the page or snapshot into the reply.

**Reading it:** SKIPPED = popular cards not played (candidates, not must-plays; the user often avoids the popular build on purpose). OFF-LIST = under ~5% or unplayed, not bad; often intentional divergence. NEGATIVE SYNERGY = the most interesting section; ask why the field avoids it. Mainstream index is not a quality score. Synergy = commander inclusion minus baseline. Under 50 decks = anecdotes; under 200 = trust big gaps only.

## 10. Token conservation

Never print whole data files. Batch lookups (`card -f`, `deck`, `audit.py`). Don't re-query cards already in context. Rulings only when ambiguous, narrowed with `--grep`. Summaries, never raw JSON. `--no-lists` on audit re-runs. Pipe long output through `head`. Quiet bash (`git clone -q`, don't echo written files). **Never grep `data/*.json` for arbitrary strings: the card file is one 19MB line.**

## 11. Pushing

Token: fine-grained PAT in the Project instructions (ask if missing). Commit straight to `main`; no branches/PRs. Never write the token anywhere or print it. Never force-push or rewrite history; undo with `git revert`. Stage files by name. The refresh bot commits daily, so pull right before pushing. Give the user the commit link. 401/403 = permission/expiry; tell the user, don't guess.

```bash
printf '%s' 'TOKEN' > /home/claude/.gh_token && chmod 600 /home/claude/.gh_token
cd /home/claude/mtg-data && git config user.name "AI Assistant" && git config user.email "assistant@mtg-data.invalid"
git add path/one path/two && git commit -q -m "What and why"
git pull -q --rebase origin main
TOKEN=$(cat /home/claude/.gh_token)
GIT_TERMINAL_PROMPT=0 git push -q "https://x-access-token:${TOKEN}@github.com/LilBeaky/mtg-data.git" HEAD:main 2>&1 | sed -E 's/github_pat_[A-Za-z0-9_]+/***/g'
echo "https://github.com/LilBeaky/mtg-data/commit/$(git rev-parse HEAD)"; rm -f /home/claude/.gh_token
```
"shallow update not allowed" → `git fetch -q --unshallow` and push again. Set identity with `git config` (not `-c`): the rebase needs it too, and a failed rebase leaves the commit unpushed. Always confirm with `git fetch` + `git log origin/main -1`.

## 12. Data refresh

`.github/workflows/refresh-data.yml` runs twice daily (~22:23 UTC after Scryfall's export, ~10:47 UTC backup) and refreshes cards, prices, rulings, oracle tags, Spellbook combos, and the Comprehensive Rules (scraped from magic.wizards.com/en/rules; only replaced when WotC posts a newer date). Manual run: Actions → Refresh MTG data → Run workflow, or dispatch via API. A Scryfall failure commits nothing (previous data stays); a Spellbook or rules failure only skips that file (check the run's warnings).

A second workflow, `smoke-test.yml`, runs `tests/smoke.py` after every refresh and on every push touching scripts/tests/snapshots/aliases/overrides, and records the result in `tests/smoke_status.json`.

If `mtg.py` or `audit.py` prints `! smoke test failing`, tell the user and read `tests/smoke_status.json`: data-dependent failures may be real-world changes (a ban, a Game Changer update) that need the test updated, not a code fix. If they print `! data last refreshed N days ago`, tell the user. Causes: scheduled jobs paused (re-enable in Actions) or the workflow failing. Diagnose via job annotations (`/repos/LilBeaky/mtg-data/check-runs/<job_id>/annotations`); raw logs aren't reachable from the sandbox.

Manual fallback: `trim.py scryfall ORACLE_CARDS OUT [--prices DEFAULT_CARDS]` and `trim.py spellbook variants.json.gz data/spellbook_combos.json.gz` (needs `ijson`). Keep combos gzipped.

## 13. Known limits

- Sandbox blocks EDHREC and Commander Spellbook hosts; GitHub/PyPI/npm are reachable.
- Rules for a brand-new mechanic may lag until WotC posts an update; audit prints the rules file date. Use `rulings` to fill gaps.
- Spellbook lists prepare cards as stand-ins for their spell; treat those combos as conditional (castable only as a copy while prepared).
- Spellbook `mv` shows 0 on some combos; meaning unconfirmed, don't rely on it.
- Sandbox RAM ~3 GB: stream big files, never `json.load` the raw Spellbook export.
- Non-Commander formats (e.g. Dandan) only smoke-tested; tools skip commander and EDHREC sections without a Commander.
