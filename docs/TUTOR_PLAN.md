# Tutor plan

Status: **phase 0 done** (2026-10-08); phase 1 next. Written 2026-10-08.

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

- **Commander folded in.** For each key card, odds = drawn, or reached through the library, or reached
  through the commander once it's out and its tutor has fired. "Out by T" comes from manasim.py's
  castable-by curve; the trigger condition (cast = ETB, attack = the next turn unless haste) shifts it.
  Shown as its own column so the ceiling and the commander's share stay visible.
- **One-shot contention in section 5:** single-card odds already exact; add a "key cards together" line
  using section 6's matching (each one-shot tutor serves one card).
- **What each tutor is worth (ceiling):** take each tutor out, recompute key-card and package odds, report
  the points lost. Ranks dead weight (Personal Tutor reaching 8 sorceries) against load-bearing tutors.
- **Equivalent copies:** state access as "plays like about N copies" of the card.
- **Partial dependencies:** besides "loses all access", list cards that lose most of their routes.
- `.dck` guard.

Done when: Zur shows Zur's own tutoring in the odds, the tutor-worth ranking, and no `.dck` misread; Ragost
(not a tutoring commander) is unchanged except the new lines; smoke checks added.

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
