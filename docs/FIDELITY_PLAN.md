# Fidelity plan

Status: **started** (written 2026-10-08). Goal: make the simulation tools' numbers as usable as we
reasonably can, and make every number say how far to trust it.

## Why

manasim.py, landbase.py's count table, land-or-ramp and swaps, and tutors.py's played columns all run on
goldfish.py's card reading. In those games only lands, ramp and card flow play; everything else is inert
on purpose. So an unread threat changes nothing, but an unread **ramp, card-draw or tutor card** does: it
sits inert and the numbers run low where it should have played.

Measured 2026-10-08 against an independent answer key (Scryfall's oracle tags for each role, plus
tutors.py's reader for tutors), across the 16 lists in `decks/`:

| Role | Played | |
|---|---:|---|
| Ramp | 152/201 | 76% |
| Card draw | 84/125 | 67% |
| Tutors | 119/155 | 77% (Erebos's 24 Shadowborn Apostles are most of the gap) |

Per deck it swings from nearly complete (Wilson, Niv, Klauth tutors) to badly short (Zur's card draw 2/14,
Erebos's tutors 7/32). Separately, 20% of all nonland cards in those decks are unread ("blank") by
goldfish.py; most are threats or interaction and don't matter for these tools.

Recognising tutors is a different, solid layer (tutors.py's reader, what phase 3 of TUTOR_PLAN builds on):
95.7% of Scryfall-tagged tutors in the whole card pool, 100% of transmute, landcycling and typecycling; the
rest are deliberate skips (opponent's library, an opponent's compensating basic, anti-tutor cards) and ~13
oddities (Lim-Dûl's Vault, Natural Balance, Opposition Agent).

## Rule: every number carries its fidelity

- manasim.py (section 3), landbase.py (section 1) and tutors.py (section 5, under the played columns) print
  a `fidelity` line: played / total per role for that deck, and the cards not played with their goldfish.py
  status. Done 2026-10-08.
- `scripts/fidelity.py` is the tracker: the per-deck table and the unplayed cards ranked by copies across
  the decks (`--md` for tables). Run it before and after a fix; quote it when a number rests on a weak deck.

## How to raise it (cheapest first)

1. **Category fixes.** Cards goldfish.py reads fine but doesn't file as ramp or card flow, so the games
   leave them inert: Lotus Cobra (landfall mana, "modeled", 3 decks), Well of Lost Dreams (2), Awaken the
   Woods, Beledros Witherbloom. A rule in `categorize`, one family at a time.
2. **Overrides** in `data/goldfish_overrides.json` for single cards whose text is one of a kind
   (Shadowborn Apostle's "sacrifice six: search for a Demon", Deep Gnome Terramancer). Each needs a unit
   check like any other read.
3. **Parser families** where several cards share a wording: flicker your own creature (Zur's Astral Slide,
   Astral Drift, Ephemerate, Flickering Hound, Escape Protocol; a session card exists), "skip your draw step,
   pay life to draw" engines (Necrodominance), sacrifice-and-draw (Greater Good), X-land spells (Genesis
   Wave), wheels on MDFC backs (Naktamun Lorespinner // Wheel of Fortune), Demonic Tutor on an MDFC back
   (Emeritus of Woe). Fix at the root, unit checks per family, sweep the pool for the same wording.
4. **Held cards that are also card flow** (Complicate, Forsake the Worldly cycle; Path to Exile ramps the
   opponent, correctly not ours): let hand abilities such as cycling run while the spell stays held.
5. **Full fidelity is Fishpond** (Forge scripts every card, real opponents). These tools stay the fast
   approximation; when a deck's fidelity line is weak, say so and cross-check a key number in Fishpond.

## Targets

- Every role at 90%+ played in each of the 16 decks, or the gap named on the report.
- Zur's card draw and Erebos's tutors first: they are the two decks whose played numbers are weakest today.

## Log

- 2026-10-08: tracker and fidelity lines added; baseline above. tutors.py reader: partner pairs, "graveyard,
  hand, and/or library", "each player may search", own-creature-dies searches, Maralen, names with commas.
