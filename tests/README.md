# Test deck

`test_deck.txt` is a deliberately broken, edge-case-heavy decklist. It is not a real deck. Run tools against it after any script change and compare with **Expected** below; anything that crashes or differs is a regression. It is also the fixture for the goldfish test battery.

```bash
python3 scripts/audit.py tests/test_deck.txt --no-edhrec
python3 scripts/stats_math.py colors tests/test_deck.txt
python3 scripts/tutors.py tests/test_deck.txt --no-lists
```

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

## Expected (verified 2026-09-28)

- Count: 99 found + 1 NOT FOUND (`Totally Fake Card Name`) = 100 with both commanders, so no DECK SIZE problem; CI BRUW; pairing accepted; companion not counted; 31 lands (24 basic).
- Problems: 9 COLOR IDENTITY lines (all green, incl. Kitchen Finks [GW] and Forest); NOT_LEGAL Knight of the Kitchen Sink; BANNED Mana Crypt; MELD RESULT Brisela; SINGLETON 2x Sol Ring; companion violations listed. **Not** flagged: Falling Star (Maybeboard), Lutri (Sideboard), Rats/Dwarves/Petitioners, basics.
- Stale pet: Card That Is Not In The Deck. Reskin resolved: Ghal Maraz. GCs 3/3 OK. Combo: Demonic Consultation + Thassa's Oracle (Ruthless). Extra turn: Time Warp. MLD: Armageddon.
- Unpriced: Brisela, Warrior's Blades.
- Audit mana: MDFC land backs = Sink into Stupor, Valakut Awakening only (not the transform cards); Cavern of Souls listed as restricted and not counted as a color source; split/adventure cards checked by their easiest castable half (Wear // Tear by {W}), prepare cards by the creature, aftermath without the graveyard half.
- Package "Prepared pair" reports that its parts share cards (audit and tutors.py alike).
- tutors.py warns about the fake card and continues: 4 tutor effects (Demonic Tutor, Dimir House Guard, Entomb → graveyard, Step Through), 4 land-only; Lim-Dûl's Vault not a tutor.

## Known approximations (not bugs)

- Plaza of Heroes' "any color among legendary permanents you control" is read as any color. It needs a legend on the battlefield, so early-turn color odds run slightly high for decks that rely on it.
- Pairing follows CR 702.124; eligibility follows CR 903.3 (legendary creature, legendary Vehicle, legendary Spacecraft with P/T, or "can be your commander").

## Fixed by this deck (2026-09-28)

`Æther Vial` ligature; tutors.py exiting on NOT FOUND; meld results passing as deck cards; split/adventure/prepare color checks paying both halves; transform land backs counted as MDFC lands; restricted-only lands counted as full color sources; tutors.py and audit disagreeing on overlapping packages; stale "colors aren't modeled" checklist line; no commander eligibility, pairing, or deck-size checks.
