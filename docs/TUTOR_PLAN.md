# Tutor plan

Status: **phases 0 and 1 done** (2026-10-08); phase 2 next. Written 2026-10-08.

## Goal

Better math about tutors: how likely a deck is to find its key cards and assemble its packages, counting
the mana and turns tutoring costs, the commander's own tutoring, and which tutors are actually worth
their slot. Then put that where it gets used: the audit, the explorer, and swap suggestions.

## Where things stand

`scripts/tutors.py` already reads every tutor form (spells, ETB/attack/dies/upkeep triggers, activated
abilities, typecycling, landcycling, transmute, commander abilities), builds the "this card can fetch that
card" graph, follows chains, and reports coverage, dependencies, access odds for `# key:` cards (exact) and
package odds with chains (sampled). Its own header says the gap: odds "ignore mana and the turns a chain
takes".

What that misses, seen on Zur (2026-10-07):
- **Everything is free and instant.** Astral Slide reads 71% by T4 against 10% drawn, but a route like
  Brainspoil → Step Through → Spellseeker → Mystical Tutor counts the same as holding the card.
- **The commander is left out.** Zur is the real Slide engine; its routes are listed, not added.
- **One-shot tutors are counted more than once.** Each key card's odds assume every tutor points at it.
  (Section 6's package matching handles this; section 5 doesn't.)
- No answer to "which tutor is worth its slot" or "which tutor should I add".
- tutors.py reads a Forge `.dck` file's header lines as cards (manasim.py refuses `.dck`; do the same).

What exists to build on:
- **goldfish.py plays tutors**: pays their mana, respects timing (sorcery speed, cycling, transmute,
  triggers), and picks targets with tutors.py's reader: `# key:` cards first (+80), the missing piece of a
  `# package:` (+70-90, more when the rest is assembled), then a tutor that reaches a missing piece (+50:
  one hop of chaining), lands only when short.
- **manasim.py** (2026-10-08) runs goldfish.py's engine with chosen cards real and the rest inert, probes
  targets each turn, runs variants in parallel on the same shuffles (`build` changes cards slot by slot),
  and compares them game by game (`paired`, `real`: beyond 2 standard errors and at least 1 point). Its
  land-or-ramp section is the template for "rank candidate cards by playing them in the deck".

## Approach

Two layers, shown side by side:
1. **Ceiling (exact, fast):** tutors.py's graph odds, fixed where they're wrong (commander folded in, one-shot
   contention). "Can you get there."
2. **Played (games):** manasim.py with tutors (and the draw that digs) real: "do you get there by turn T,
   having paid for it". The gap between the two is the information: big gap = tutors that cost too much or
   chains too long to matter by then.

## Phase 0: check goldfish.py's tutoring before relying on it (small)

Trace a handful of Zur and Ragost games (`goldfish.py --trace N`) and list where tutoring goes wrong:
- chains longer than one hop (it only values "a tutor that reaches a missing piece"),
- commander tutor triggers (Zur's attack trigger: does Zur attack, does it fetch Slide),
- transmute / wizardcycling into the right card, re-buyable ETB tutors (Spellseeker with Astral Slide),
- tutoring to the top of the library (Mystical Tutor, Long-Term Plans) then drawing it.

Fix what's wrong in goldfish.py itself (it's ours to change now; every seat, no hero-only logic).
Done when: the traces read like a reasonable pilot for those cases, and fixes have unit tests.

**Done 2026-10-08.** Traced 6 Zur and 8 Klauth games. Working as intended: Zur's attack trigger (Slide,
Drift, Words of Worship, Necrodominance in priority order), chains of two and three hops (Spellseeker →
Personal Tutor → Step Through), tutor-to-top then draw, Klauth's X tutors (ramp creatures early, dragons
later). Fixed in goldfish.py, with unit tests:
- **Typecycling was never used on purpose.** Outside a missed land drop, the pilot only cycled near-worthless
  cards at end of turn, so Step Through never wizardcycled. Now typecycling with a tutor is used in the main
  phase when the best card it finds is wanted (key, missing package piece, or a tutor toward one) and worth
  more than casting the cycler, like transmute already was.
- **Tutoring from hand came after everything else**, so main phase 1 spent the mana first. It now comes after
  the commander, tracked cards and ramp, before draw and the rest.
- **A tutor to the top was cast before Zur's attack**, whose search shuffled the card away (games 4 and 6).
  While an attack-trigger search is still to come, tutors to the top wait for main phase 2.
- **Long-Term Plans** was read as no tutor (the T2 audit removed a wrong "to the top"); it now tutors to third
  from the top (the engine already had `topN`).
Effect on Zur (1,000 games, same shuffles, by T8): Archaeomancer cast 20.7% → 36.8%, Triskaidekaphile
21.9% → 43.7%, Approach 27.0% → 31.7%; Zur itself unchanged.
Still unread, out of this plan's scope: Zur's flicker engines (Astral Slide, Astral Drift, Ephemerate,
Flickering Hound, Escape Protocol), so re-buying Spellseeker / Tribute Mage isn't played. Judgment call left
as is: stuck on lands, a find-anything tutor takes a key card (80) over a land (75).
**For the next phases:** Ragost has no tutors and no `# package:` lines, and Klauth has no `# key:` lines.
Ragost's packages (its assembly problem) need header lines before phase 2 can measure them.

## Phase 1: tutors.py quick wins (exact layer)

**Done 2026-10-08, revised on the way:** key cards no longer depend on header lines.
- **Key cards, yours and inferred in parallel.** `# key:` / `# package:` lines are always used; inference runs
  alongside and adds cards beyond them; with no lines, inference alone (`key_cards`, `infer_keys`). Signals:
  wins the game (oracle tag `alternate win condition`), payoff for a mechanic or creature type the deck has 8+ of
  (`synergy-*` / `*-matters` tags against the deck's keywords and subtypes), typal package, repeatable draw/token/
  mana engine, EDHREC synergy >= 30% for this commander, narrow tutors converging on it (each specific tutor
  spreads 1 over its nonland targets, repeatable x2), Spellbook combo pieces (not the tutor in "tutor + target").
  Score >= 2 to count, at most 10 shown. The report says how many of your keys inference also picks.
  Results: Zur 5 of 8 (misses Archaeomancer, Words of Worship, Necrodominance: a deck-specific loop and combo no
  tag describes); Ragost 0 of 5 (artifact synergy is everywhere; only Test of Endurance inferred); Klauth (no
  lines) gets Dragon Tempest and the dragons its tutors converge on.
- **goldfish.py fetch priority:** inferred keys at 60 (yours 80, a missing package piece 70-90), and only once
  the deck has developed (commander out or 5 lands); before that gate, inferred dragons slowed Klauth (by T5
  56.0% -> 52.4%), with it 57.3%.
- **Commander folded in:** "+ commander" = 1 - (1 - library odds)(1 - P(commander out long enough to use its
  tutor)), from manasim.py's castable-by curve; attack triggers and {T} abilities wait a turn unless haste.
  Zur: Astral Slide by T4 71.0% -> 81.6%, by T6 77.8% -> 97.4%. Independence between the two is assumed.
- **Plays like N copies** per key card. **Tutor worth (section 7):** drop-one on key cards and the whole deck,
  plus a specific-only view and "only it reaches". As expected the ceiling flattens it (every chain is free):
  Zur all +3.5 except Wishclaw +7.2 and Step Through +5.9; specific-only separates (Step Through +11.6,
  Brainspoil +6.9, Spellseeker +6.1, the instant/sorcery tutors +3.2). The played version is phase 2's.
- `.dck` refused.
- Not done: one-shot contention for key cards together in section 5 (section 6's matching covers packages);
  partial dependencies. Both fold into phase 2, where play handles contention directly.

## Phase 2: played access (the mana-and-turns layer)

- **manasim.py "tutor mode":** tutors, draw and filtering real on top of lands and ramp; targets = key cards
  and package pieces; metrics per target: in hand or on the battlefield by T, castable by T; per package:
  assembled by T. One-shot contention and chain cost come out of play, not formulas.
- **This is where item 2 from the ramp work lands:** draw and tutors that dig for lands or ramp. Run
  landbase.py's commander and development numbers with them real (flag to compare), since draw-heavy decks
  like Zur (13 such cards) are read low today.
- **Tutor worth (played):** drop-one in games, paired against the full deck (same shuffles). This is the
  number that answers "is Personal Tutor worth its slot".
- **tutors.py sections 5 and 6:** show ceiling and played side by side, with the gap.

Done when: Zur's Astral Slide shows ceiling vs played by T4/T6 with the commander's share; Ragost's
packages show assembled-by-turn (it's an assembly deck: this is its main read); the worth ranking from games
roughly agrees with the ceiling ranking or the disagreements are explained; runtime reported.

## Phase 3: a tutor index for the whole card pool

- Run tutors.py's reader over every card once (cache keyed to the card data's date, regenerated with the
  daily refresh or lazily): for each tutor, what it can find; inverted, for each card, which tutors can
  find it.
- **explorer.py:** a "findable by" section (tutors in the card's colors that can fetch it, with how often
  they're played next to it from the EDHREC card page's co-played lists we already download).
- **Best tutor to add:** the land-or-ramp machinery pointed at tutors: candidates in the colors, Game
  Changers within the bracket allowance, under `--max-price`; shortlist by what reaches the deck's key and
  package cards; ranked by played package/key access, paired. In tutors.py and summarized by the audit.

Done when: the explorer shows "findable by" for Step Through and a Klauth key card; tutors.py suggests
tutors for Zur and Ragost with their played gain.

## Phase 4: audit layering

- Audit 4b gets tutors.py's summary: ceiling vs played for key cards, the top dependency, the weakest
  tutor, the best tutor to add.
- Later, separately: a priorities block at the top of the audit (the few findings that matter most across
  sections). Its own plan when we get there.

## Test decks

- **Zur** (`Ians_Zur_Wizardcycling.txt`): commander tutor, layered tutor chains, flicker re-buys, 9 key cards.
- **Ragost** (`Ians_Ragost_Burn.txt`): mana is fine, assembly is the problem; packages are the read.
- **Klauth** (`Ians_Klauth_Dragons.txt`): green tutors (Worldly Tutor and others) that also fetch ramp.

## Out of scope here

- Mining the explorer's unused EDHREC co-played lists for packages (worth its own plan).
- Card downside flags (the user makes those calls).
