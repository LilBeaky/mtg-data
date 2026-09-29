# Test deck

`test_deck.txt` is a deliberately broken, edge-case-heavy decklist. It is not a real deck.

`smoke.py` runs every tool against it (plus a few throwaway commander decks) and checks exit codes, tracebacks, and expected output. **smoke.py is the source of truth for expected results**; read it for the exact strings. It runs automatically after every daily data refresh and on every push that changes scripts, tests, snapshots, aliases, or goldfish overrides (`.github/workflows/smoke-test.yml`) and records the result in `smoke_status.json`. While that says `fail`, mtg.py and audit.py print a warning in every session.

```bash
python3 tests/smoke.py          # ~40s; prints only failures + a summary. --verbose lists every check
```

Adding an edge case: add the card to `test_deck.txt` (keep the total at 100 with both commanders), add its expectation to `smoke.py`, run it, push both.

## What each group exercises

| Group | Cards / lines |
|---|---|
| Layouts | split (Fire // Ice), fuse (Wear // Tear), aftermath (Commit // Memory), room (Bottomless Pool // Locker Room), flip (Nezumi Graverobber, front name only), transform (Delver, Search for Azcanta land back, Treasure Map), battle (Invasion of Zendikar), MDFC (Sink into Stupor, Valakut Awakening single-slash), meld pair (Bruna, Gisela), adventure (Bonecrusher Giant), saga + read ahead (History of Benalia, The World Spell), class, case, leveler, mutate, prototype |
| Name traps | prepare card whose face shares a classic name (Studious First-Year // Rampant Growth **and** Rampant Growth; Harmonized Trio **and** Brainstorm), meld result that isn't a deck card (Brisela), reskin (Ghal Maraz → Loxodon Warhammer), `Æther Vial` ligature, `stroke of genius` lowercase, `Thassa’s Oracle` curly apostrophe, accents (Mjölnir, Lim-Dûl's Vault), fake card |
| Formatting | `1x`, set/collector/`*F*`/`*E*`, trailing `#tags` incl. multi-word `#!Mana Rock`, duplicate lines, Sideboard + Maybeboard sections, full header (bracket, plan, pets with a comma name + a stale pet, two packages, track, key) |
| Commanders | partner pair (Kraum + Tymna, WUBR). Green is deliberately off-identity so every green card, the Forests, and hybrid Kitchen Finks {G/W} must be flagged |
| Legality | banned (Mana Crypt; Falling Star only in Maybeboard), not legal (Un-card), duplicate (2 Sol Ring), any-number cards (3 Relentless Rats, 2 Seven Dwarves, 2 Persistent Petitioners), Wastes, snow basics, companion with a violated condition (Obosh) |
| Color identity | devoid, color indicator / no mana cost (Ancestral Vision), hybrid, Phyrexian, identity from an ability (Phyrexian Infiltrator), reminder-text hybrid that must NOT count (Pontiff of Blight = B only) |
| Bracket | 3 Game Changers, 2-card combo (Oracle + Consultation), extra turn (Time Warp), MLD (Armageddon) |
| Mana | fetch, bounce, filter land, conditional any-color (Plaza of Heroes), truly restricted mana (Cavern of Souls), always-tapped, land creature (Dryad Arbor), rituals, Leyline, cost reducer, X spell, no price (Warrior's Blades) |
| Tutors | find-anything, transmute (Dimir House Guard), typecycling (Step Through), graveyard destination (Entomb), library manipulation that isn't a search (Lim-Dûl's Vault) |
| Goldfish-only | banding (Benalish Hero), initiative (Feywild Caretaker), Dracogenesis (free-cast) — nothing else reads these yet |

## Known approximations (not bugs)

- goldfish.py stops on NOT FOUND cards (tutors.py and the audit warn and continue), so the smoke test runs goldfish on the deck without the fake card. `goldfish_gy_deck.txt` is a second fixture for goldfish's graveyard, tutor and cycling model; the gy trace check pins the pilot's Entomb → Demonic Tutor → Reanimate line on a fixed seed, so a pilot change that moves it will show up there first.

- Plaza of Heroes' "any color among legendary permanents you control" is read as any color. It needs a legend on the battlefield, so early-turn color odds run slightly high for decks that rely on it.
- Pairing follows CR 702.124; eligibility follows CR 903.3 (legendary creature, legendary Vehicle, legendary Spacecraft with P/T, or "can be your commander").

## Fixed by this deck (2026-09-28)

`Æther Vial` ligature; tutors.py exiting on NOT FOUND; meld results passing as deck cards; split/adventure/prepare color checks paying both halves; transform land backs counted as MDFC lands; restricted-only lands counted as full color sources; tutors.py and audit disagreeing on overlapping packages; stale "colors aren't modeled" checklist line; no commander eligibility, pairing, or deck-size checks.
