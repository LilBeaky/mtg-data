# USE INSTRUCTIONS — LilBeaky/mtg-data

For the assistant. This repo is the source of truth for card text, rulings, tags, combos, legality, and rules. Answer card questions from it, never from memory. Section numbers are referenced by the scripts; keep them stable.

## 1. Session start

```bash
git clone -q --depth 1 https://github.com/LilBeaky/mtg-data.git && cd mtg-data
```
Re-clone every session (sandbox resets). Use git, not the GitHub API, for reading. No `jq`; use the scripts or plain Python. Run everything from the repo root as `python3 scripts/<name>.py` (Fishpond: `python3 -m fishpond`). Each script prints usage with no args (tutors.py: `-h`). Read this file once per session.

## 2. Which tool

| Task | Tool |
|---|---|
| Deck audit (always first) | `audit.py DECK` (§5) |
| Card text, rulings, tags, search, deck check, GCs, combos, combos one card away, rules | `mtg.py` |
| Draw odds beyond the audit | `stats_math.py` (§6) |
| Tutor chains / access odds | `tutors.py` (§6) |
| Land count and land swaps | `landbase.py` (§6) |
| Ramp: when the commander / key cards can be cast, what the ramp is worth | `manasim.py` (§6) |
| How much of a deck the simulation tools play (fidelity) | `fidelity.py` (`docs/FIDELITY_PLAN.md`) |
| Which tutors in the card pool can find a card | `tutor_index.py "Card"` (also explorer.py section 5b) |
| How a deck plays out (win rate, how it wins and loses, real opponents) | `python3 -m fishpond` (§6 → `docs/FISHPOND.md`) |
| Fast mana/curve reads, swap ladders, disruption ladder | `goldfish.py` (§6 → `docs/GOLDFISH.md`; frozen legacy, still maintained in smoke) |
| Goldfish parser coverage / regression diff | `goldfish_coverage.py` (`docs/GOLDFISH_ROADMAP.md`) |
| EDHREC comparison | `edhrec_diff.py` (§9); audit runs it if a snapshot exists |
| One card: who plays it, combos, strategies, build-arounds (not part of audits) | `explorer.py "Card"` (`docs/EXPLORER.md`) |
| Data refresh | automatic (§12); `trim.py` is the manual fallback |

Custom queries only when no tool answers; respect §7. Suggest folding useful ones into a tool.

## 3. Layout

`scripts/` (code) · `fishpond/` (Forge-backed simulator; `fishpond/opponents/` holds opponent gauntlets) · `data/` (bulk data + `aliases.txt`, `goldfish_overrides.json`; `data/fishpond/` = saved runs, `data/explorer_cache/` = EDHREC responses, both gitignored) · `docs/` (index and plan status in `docs/README.md`) · `snapshots/` (EDHREC transcriptions) · `tests/` (edge-case test deck, goldfish and Fishpond fixtures, `goldfish_units.py`, `fishpond_units.py` + `smoke.py`; run `python3 tests/smoke.py` after changing any script, before pushing). Scripts pick the newest dated rulings/tags/rules files automatically.

## 4. mtg.py and deck files

**Commands:** `card NAME...` · `card -f FILE [--brief]` · `rulings NAME [--grep WORD]` · `tags NAME` · `search [filters] [--full]` · `deck FILE [--all-combos]` · `combos NAME... [--bracket N]` (combos containing all named cards) · `near DECK [--max-price N] [--limit N]` (cards one away from completing a combo: legal, in CI, 2-card completions and over-target brackets flagged; audit §1 lists them all) · `gc` · `rule 702.62a` / `rule --grep WORD`.

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
2. `python3 scripts/audit.py deck.txt` (a few minutes: manasim.py and tutors.py games; `--no-sim --no-tutors` for a ~10s pass). Fix every `NOT FOUND` first (reskin → alias; new set → verify externally). Note stale pets.
3. No EDHREC snapshot → fetch and transcribe one (§9), then re-run.
4. Settle K for each role: read the printed card lists. The user's tags win when they cover ≥50% of nonlands; otherwise oracle tags, which **overcount** (candidate lists, not K). Correct with `--k role=N` and re-run. Cost reducers aren't in `ramp`. Treat anything marked ⚠ K-SENSITIVE as unsettled until confirmed. State every K correction in the write-up.
5. Run the odds that matter for *this* deck's plan (§6), not just the battery. The audit's §4c already carries tutors.py's whole report; re-run tutors.py alone for `--md`, `--max-price` or other turns.
6. Pull oracle text only for cards under evaluation, in one `card -f` batch.
7. Close rules questions with `rulings --grep` / `rule` before writing them up. "I'm not certain" only after the repo can't answer.
8. Manual bracket items (§8).
9. Verify every card from EDHREC or memory with `mtg.py card` before recommending it.
10. Write-up order: findings (interactions, nonbos), then numbers, then a separate EDHREC section. Challenge pets/plan with questions, not cut lists. Push new snapshots/aliases.

**audit.py flags:** `--no-landbase` (skip the land-base run) `--no-sim` (no manasim.py games: exact land-only formulas in §3 and the land-count table; §4c best case only) `--no-tutors` (skip §4c) `--bracket N` `--k ROLE=N` (repeatable) `--draw` `--commander` `--snapshot PATH` / `--no-edhrec` `--min N` / `--limit N` (EDHREC diff) `--all-combos` `--no-lists` (re-runs).

**Output sections:** 1 legality/bracket (commanders, size, GCs, 2-card combos, extra turns, possible MLD, combos one card away) · 2 mana (landbase.py summary: recommended land count, swap plan, before → after; lands, tapped lands, reducers, ramp, MDFC backs, colors: sources, pip odds, cards under 90%/80% on-curve with fixes; restricted-mana lands listed, not counted; multi-face cards judged by their easiest castable face) · 3 commander on curve (exact land-only floor, then manasim.py games with every accelerant: on curve, a turn early, median turn) · 4 role odds (+ custom tags) · 4b packages, a table (with-tutor odds are a **ceiling**: ignores mana and turns) · 4c tutors & key cards: a headline (key cards yours + inferred, best case → played, the biggest dependency, strongest and weakest tutor in games, best tutor to add and the swap, fidelity), a best-vs-played table for every key card, then tutors.py's full report as 4c.1–4c.8 · 5 density/flood/screw · 6 EDHREC diff · 7 manual checklist.

## 6. Analysis tools

**Stats Math (`stats_math.py`)** — lean toward using it more, not less: package coherence, cut-vs-add, mulligans.
- `report DECK [cat...]` (K + matched names) · `colors DECK` · `packages DECK` · `N K n k` (P ≥k of K in n from N).
- Deeper: `import stats_math as sm` with `sys.path.insert(0,'scripts')`. Functions and conventions in `docs/STATS_MATH.md`.
- Fixed: 7-card hand, London mulligan, N counted from the list. Static draws only (no engines/untaps/cascade); colors assume land drops hit. Say so when it matters.

**Tutor analysis (`tutors.py DECK [--commander] [--draw] [--turns 4,6] [--no-lists] [--trials N] [--no-infer] [--md] [--no-played] [--played-trials N] [--no-suggest] [--max-price N] [--suggest N]`)** — for any deck with more than a couple of tutors or questions about tutor packages. Run after the audit.
- Reads every "search your library" including typecycling, transmute, triggers; records repeatable vs one-shot, destination, and exact target filter. Graveyard-destination tutors end chains; battlefield-destination cards can't be cycled/cast onward.
- ⚠ marks approximations (MV X or less, "shares a type", opponent picks). Flag them when a conclusion rests on one.
- Report: 1 inventory (dead tutors, shallow pools; find-anything tutors in their own table, their targets "everything", and the same split in chains, tutors to add, tutor_index.py and explorer 5b) · 2 chains · 3 coverage · 4 dependencies (single points of failure) · 5 key cards: yours (`key`/`package` lines) and inferred beyond them, side by side, each inferred card with its reasons (wins the game, payoff for a mechanic or creature type the deck is full of, typal package, draw engine, EDHREC synergy, narrow tutors converging on it, Spellbook combo piece), a line saying how many of yours inference also picks (how far to trust it on this deck); access odds for both: best case (exact, every chain free), with the commander's own tutoring added once manasim.py games have it out long enough to use it, and **played**: found (out of the library) by each turn in manasim.py tutor-mode games, with lands, ramp, tutors and card draw played and the mana paid; "copies" from the played number · 6 package assembly (sampled best case, and played: every part found by that turn) · 7 tutor worth: **played** first, key cards found per 100 games that the tutor adds (the same games with the tutor inert, compared one by one; ≈ within noise), then the best-case drop-one columns, a specific-only view and the cards only it reaches. Lead with the played columns: the best case counts every chain as free. 8 tutors to add: tutors from the whole card pool (tutor_index.py) in the deck's colors that reach its key cards (Game Changers within the bracket allowance, `--max-price`), each played in the deck on the same games and ranked by key cards found per 100 games it adds, then the best one swapped for your weakest tutor; a ⚠ means goldfish.py reads that tutor only partly. A second view sets aside find-anything tutors to expose package structure. Header lines are optional: with none, inference alone; `--no-infer` turns inference off. Refuses a Forge `.dck`. Every section that lists rows prints as a table; `--md` prints the same report with Markdown tables: use it when showing the report in chat.
- NOT FOUND cards are warned about and left out. Odds ignore mana and chain time ("can you get there", not "how fast"). Every chain counts as free, so the worth ranking flattens out; read the specific-only column. Not tracked: searching others' libraries, tutoring from graveyard. Played worth counts key cards only, so a tutor the pilot points at ramp early (Chord of Calling for a mana creature) can read ≈0.

**Land base (`landbase.py DECK [--max-price N] [--lands N] [--swaps N] [--no-count] [--no-swaps] [--turn T] [--draw]`)**: run when audit §2 flags colors or the land count is in question.
- Land count: every count ±4 from now. "T mana by T" and "cmdr on T(MV)" are manasim.py games at that count (every accelerant played turn by turn, tapped lands, mulligans; ±1.5 pts at the default `--trials 1000`), next to the same games with the ramp made inert ("lands only"), the commander's median turn, and exact screw / flood / keepable openers. Recommends the smallest count with 3 mana by T3 ≥ 80% and ≤2 lands by T4 ≤ 20% (`--develop`, `--screw`, `--flood`); the commander column isn't part of the test, so read it before cutting a land. "Worth about N lands" compares the ramp with lands-only games. `--no-sim` restores the old exact formulas (ramp only as a rough +1). Adding lands means cutting nonlands: the user picks those.
- Swaps: at each step the exact color score (audit §2's thresholds; untapped beats tapped, cheap beats expensive at equal colors) proposes its best `--swap-options` (6) swaps and manasim.py games on the same shuffles pick the one that brings the commanders down fastest; a swap that slows a commander beyond noise is never taken, and a pick that differs from the color-best is noted. Candidates are plain mana lands only; utility lands (cycling, Ancient Tomb, Cavern...) are never cut without `--cut-utility`; a suggested fetch counts only the basics it can find. `--no-sim-swaps`: color score alone. Before → after plays the whole plan in manasim.py games (T mana by T, each commander by turn) and shows every flagged card's color odds.
- 1b Land or ramp (with a commander; `--no-ramp-pick` skips it, ~15s): one slot compared four ways on the same games: now, +1 land, +1 of the best ramp cards for this deck, a basic traded for the best one. Candidates are legal, in the colors, MV ≤ 3 (reducers that apply to the commander up to 4), Game Changers within the bracket allowance, under `--max-price`; the shortlist is every reducer that applies to the commander, the commander's EDHREC snapshot ramp, then the most played; each is played in the deck and ranked for each commander independently by how fast it comes down (castable on the turn before curve, on curve, the turn after); a commander pair gets its own columns, verdict and best list per commander. "≈" means within noise or under 1 point of now, for that commander. Lead with the verdict lines; cards goldfish.py reads only partially are tagged with what it didn't read.
- `--with-draw`: the count table and the plan's games also play card draw and tutors (tutors finding ramp, draw finding lands; Klauth by T7 76% -> 89%); the lands-only baseline, land-or-ramp and swap picks stay ramp-only.
- Color odds and swaps are static draws, lands only: say so, and present the plan as options, not a cut list.

**Ramp (`manasim.py DECK [--trials N] [--turns N] [--target CARD] [--lands N] [--draw]`)**: run when the question is how fast the deck develops or when the commander comes down.
- Plays the deck's lands and acceleration through goldfish.py's engine and card reading (same mulligans and land choice), every other card inert. Acceleration = goldfish.py's ramp category (rocks, dorks, land search, extra land drops, cost reducers, free/alt casting, mana doublers, Treasure) + rituals; landcycling is kept.
- Targets: the commander(s), `# key:` cards, `--target` cards. Each turn it asks whether each target could be cast that turn by the best line: as is, after ramp that pays for itself (Sol Ring), or with a ritual. Cost reducers count only where their filter matches the target (Dragonspeaker Shaman for a Dragon). Land drops serve the commander first, then key cards.
- Report: 1 development (lands, mana, T mana by T) · 2 castable by turn: with ramp, lands only (same games, ramp inert), with card draw and tutors played too, and in games that hit every land drop (the number to check by hand) · 3 coverage: every accelerant and how it's read, partial readings named, what isn't counted (draw, tutors).
- `--land-or-ramp [--max-price N]` prints landbase.py's section 1b alone.
- `--hand "A; B; ..." --draws "X; Y; ..."` plays one scripted line with a play-by-play and the first castable turn per target, to check a claim like "Rampant Growth T2, Shaman T3, Klauth T4".
- Not modeled: card draw and tutors that dig for lands or ramp, opponents' interaction. goldfish.py's partial readings carry over: name them when a number rests on one.

**Fishpond (`python3 -m fishpond`)** — see `docs/FISHPOND.md` before running it. If the user says "Launch Fishpond", reply with the intake form in `docs/FISHPOND_LAUNCH.md`. Plays the deck on the Forge rules engine (every card scripted) in 4-player pods: 3 opponent seats, each a dummy or a real deck (`--opp`, `gauntlet:NAME`). `setup` once per session, then `deck DECK` to report cards Forge lacks or its AI can't play, then `run`. Lead with the win rate and its interval, wins by route, losses by reason, and the pilot tags (losses the AI caused inside real rules, e.g. `surge_trap`). Say which pod mode produced a number. Budget time: one game is tens of seconds per CPU.

**Goldfish (`goldfish.py`)** — see `docs/GOLDFISH.md` before running it. Always `--explain` first on a new list and report partial/blank cards before quoting numbers. It reads `key`/`package` header lines as tutor priorities, then tutors.py's inferred key cards below them (only once the deck has developed: commander out or 5 lands); report its "tutor targets" line when tutoring matters. It plays the deck in a vacuum: opponent-dependent cards run on fixed approximations (`~opp`) or do nothing (`vacuum`); say which matter. Its disruption section is the resilience read: with a bracket 2-4 it runs the bracket's interaction ladder (`data/goldfish_gradients.json`; 5 clean baselines + 15 rungs per shuffle). Lead with the breakpoint and "what changed at the breakpoint" (what the deck folds to), and treat any Δ inside the noise band as noise. Without a bracket it falls back to sampled events; never guess the bracket to get the ladder. Its combat section is the clock: damage by turn, commander damage and poison per opponent, when the first opponent and the whole table die (killing all three ends the game), and triggers fired by kind. Opponents never attack; they have creatures and combat denial only with `--blockers "SPEC"` (e.g. `"1/1@2; 2/2 flying@4; 1:prop@5; 2:fog@6"`; syntax in GOLDFISH.md "Blockers"). Without it the clock is a ceiling: say so. With it, report the blocks and denial lines (what the deck gets stuck on) alongside the clock.

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
