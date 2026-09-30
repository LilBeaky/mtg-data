# Goldfish parser coverage roadmap

For the assistant. Goal: goldfish.py reads as much of the Commander card pool as pattern parsing reasonably allows, without reading anything *wrong*. Measure with `scripts/goldfish_coverage.py` (usage: run it with no args).

## The rule

**Coverage is worthless if the read is wrong.** "modeled" only means every line matched something. A regex that matches and produces the wrong effect is worse than an honest "unmodeled", because it silently corrupts the numbers. Every parser change: `goldfish_coverage.py diff HEAD`, read every changed reading against Oracle text, fix misreads first, then `tests/goldfish_units.py` + `tests/smoke.py`, then push.

## Baseline (2026-09-30, after Phase 0; see the Phase 1 line below for the current figure)

32,116 Commander-legal cards (667 lands). Weight = 1/sqrt(edhrec_rank).

| Status | Share | Weighted |
|---|---|---|
| modeled | 36.4% | 36.6% |
| blank | 25.8% | 23.0% |
| partial | 23.4% | 23.7% |
| held | 9.2% | 10.0% |
| vacuum | 3.8% | 3.8% |
| land* (land with an unread line) | 1.5% | 2.8% |

**Fully read (modeled + held + vacuum + override), weighted: 50.5%.** The miss tail is flat: the biggest effect cluster is ~3.5% of weighted misses.

**Ceiling:** full coverage isn't reachable with pattern parsing. Target ~85% weighted fully read, and every card in the user's decks read via parser or override. Stop chasing a cluster under ~0.3% weighted; overrides for anything under ~5 cards.

## Decisions (user, 2026-09-30)

- **Removal aimed at opponents' creatures is modeled against `--blockers`**: it can kill a blocker. Without `--blockers` there's nothing to hit.
- **Order: biggest weighted clusters first** (`report` re-ranks after every pass).
- **File split: deferred** (assistant's call, allowed by the user). The parser and simulator share module state (`_CTX`, `_EXPLAIN_DECK`, constants); tests, smoke and docs import/reference `scripts/goldfish.py`; targeted `grep -n`/`sed -n` reads already keep token cost low. Revisit if the parser outgrows that. If split, per the user: the goldfish tool gets its own folder with everything specific to it (script, coverage tool, overrides, gradients, fixtures, docs).

## Phase 0: safety net ✅ (2026-09-30)

- Fixed the `_fx_pump_team` crash (10 cards failed to compile; any deck with one couldn't run).
- Team pumps now read "for each X" (was dropped: every scaling team pump read flat). Unreadable counts stay unread. Added a `domain` count key.
- `goldfish_coverage.py` (`report`, `diff REF`, `card NAME`), 3 unit checks, 2 smoke checks (every legal card compiles).

## Phase 1: removal vs blockers, opponent-only lines ✅ (2026-09-30)

Decision rule from the user for every pilot choice from here on: **model the decision a player is most likely to make, without over-complexifying.**

- Held removal already fired at the one blocker between you and a kill (`clear_path`). Now it only uses a spell that can actually kill that blocker (filters, damage vs toughness, indestructible, edicts take the weakest, Swords' life gain counted), one-sided wipes go when clearing boards is lethal, and held any-target burn can kill a blocker.
- Removal on permanents (ETB, triggers, activated, planeswalker abilities) is read as `kill_blk` and aimed at blockers. **Fixed a real bug:** -1/-1 counters and -N/-N on "target creature" (~118 cards incl. Skinrender) used to land on your own best creature; -X/-0 debuffs used to shrink your own attacker.
- Opponent-only lines are vacuum, but only if they touch nothing the sim tracks (you, their life, their creatures).
- Reviewed by category and by a random sample of 40 new removal readings (2 misreads found and fixed via an allowlist after the target noun).
- **Fully read, weighted: 49.9%** (was 50.5%). Removal gains were offset by ~780 cards moving vacuum → blank/partial: the old vacuum rule was hiding real payoffs (drains, extra turns, recursion, "you draw" riders). The old figure was inflated; this one is honest.
- Next cheap win: counterspells/protection are modeled as held answers, yet their text still shows as "unmodeled" and pads the "counter target" cluster.

## Phase 2: cluster passes (repeat)

Per pass: `report` → top weighted cluster → pull 10-20 example cards from the repo → parser change → unit check (plus a guard card that must stay unread, where relevant) → `diff HEAD` review → units + smoke → push. One cluster per commit; the message names the cluster and the diff counts.

Current top clusters: destroy target, put N (counters), ~ deals N, create N (token variants, sagas), counter target, exile target, look at, intervening "if", target creature, "as long as". Top-played misses: Chaos Warp, Skullclamp, Propaganda, Victimize, Black Market Connections, Deadly Dispute, Roaming Throne, Ashnod's Altar, Ponder, Mana Vault, Herald's Horn, Chrome Mox, Doubling Season.

## Phase 3: correctness audit (every ~3 passes)

Sample ~40 "modeled" cards stratified by popularity; compare `card` readings to Oracle; log and fix misreads; track the misread rate.

Idea to build here: a **leftover detector**. `parse_fx` masks what it matched; if a line still has substantive words unmasked (e.g. "you gain X life" after the drain half matched), mark the card partial instead of modeled. This would catch silent clause drops automatically.

## Known misreads (found, not yet fixed)
- Soulstinger-style "-1/-1 counters on target creature you control" go on your best attacker; a player picks the weakest (usually the card itself).
- "target player mills/draws" reads as you; a player picks per deck (Necron Deathmark).
- Cast-only-during-an-opponent's-turn / only-if-fewer-creatures cards are vacuum but still take a slot; fine, but worth knowing.

- Storm the Citadel is `held`: hold detection reads the quoted granted ability's "destroy target". Hold detection should ignore quoted text.
- Exotic Disease reads "an opponent loses per domain" as modeled but drops "you gain X life" (X-valued life gain isn't read). Leftover detector would catch this class.
- Magmablood Archaic's converge counter reads as 1 (should be colors spent).
- "for each [subtype] you control" isn't a count key in `dyn_key` (Chong and Lily's Bards, Nissa, Ascended Animist's Forests).

## Out of scope

Pilot decision quality (separate track), opponent behavior (future separate script, per the user's scope rule), ML classifiers, exact-probability engines.
