# Test deck

`test_deck.txt` is a deliberately broken, edge-case-heavy decklist. It is not a real deck. Run tools against it after any script change and compare with **Expected** below; anything that crashes or differs is a regression. It is also the fixture for the goldfish test battery.

```bash
python3 scripts/audit.py tests/test_deck.txt --no-edhrec
python3 scripts/stats_math.py colors tests/test_deck.txt
python3 scripts/tutors.py tests/test_deck.txt --no-lists   # see open issue 1
```

## What each group exercises

| Group | Cards / lines |
|---|---|
| Layouts | split (Fire // Ice), fuse (Wear // Tear), aftermath (Commit // Memory), room (Bottomless Pool // Locker Room), flip (Nezumi Graverobber, front name only), transform (Delver, Search for Azcanta land back, Treasure Map), battle (Invasion of Zendikar), MDFC (Sink into Stupor, Valakut Awakening single-slash), meld pair (Bruna, Gisela), adventure (Bonecrusher Giant), saga + read ahead (History of Benalia, The World Spell), class, case, leveler, mutate, prototype |
| Name traps | prepare card whose face shares a classic name (Studious First-Year // Rampant Growth **and** Rampant Growth; Harmonized Trio **and** Brainstorm), meld result that isn't a deck card (Brisela), reskin (Ghal Maraz → Loxodon Warhammer), `Æther Vial` ligature, `stroke of genius` lowercase, `Thassa’s Oracle` curly apostrophe, accents (Mjölnir, Lim-Dûl's Vault), fake card |
| Formatting | `1x`, set/collector/`*F*`/`*E*`, trailing `#tags` incl. multi-word `#!Mana Rock`, duplicate lines, Sideboard + Maybeboard sections, full header (bracket, plan, pets with a comma name + a stale pet, two packages, track, key) |
| Legality | banned (Mana Crypt; Falling Star only in Maybeboard), not legal (Un-card), duplicate (2 Sol Ring), any-number cards (3 Relentless Rats, 2 Seven Dwarves, 2 Persistent Petitioners), Wastes, snow basics, companion with a violated condition (Obosh) |
| Color identity | 5-color commander (The Ur-Dragon); devoid, color indicator / no mana cost (Ancestral Vision), hybrid, Phyrexian, identity from an ability (Phyrexian Infiltrator), reminder-text hybrid that must NOT count (Pontiff of Blight = B only) |
| Bracket | 3 Game Changers, 2-card combo (Oracle + Consultation), extra turn (Time Warp), MLD (Armageddon) |
| Mana | fetch, bounce, filter land, restricted mana (Plaza of Heroes), always-tapped, land creature (Dryad Arbor), rituals, Leyline, cost reducer, X spell, no price (Warrior's Blades) |
| Tutors | find-anything, transmute (Dimir House Guard), typecycling (Step Through), graveyard destination (Entomb), library manipulation that isn't a search (Lim-Dûl's Vault) |
| Goldfish-only | banding (Benalish Hero), initiative (Feywild Caretaker), Dracogenesis (free-cast) — nothing else reads these yet |

## Expected (verified 2026-09-28)

- Count: 99 found + 1 NOT FOUND (`Totally Fake Card Name`); commander CI BGRUW; companion not counted; 32 lands (26 basic).
- Problems: NOT_LEGAL Knight of the Kitchen Sink; BANNED Mana Crypt; SINGLETON 2x Sol Ring; companion violations listed. **Not** flagged: Falling Star (Maybeboard), Lutri (Sideboard), Rats/Dwarves/Petitioners, basics.
- Stale pet: Card That Is Not In The Deck. Reskin resolved: Ghal Maraz. GCs 3/3 OK. Combo: Demonic Consultation + Thassa's Oracle (Ruthless). Extra turn: Time Warp. MLD: Armageddon.
- Unpriced: Brisela, Warrior's Blades.
- Package "Prepared pair" reports that its parts share cards.
- tutors.py (fake card removed): 4 tutor effects (Demonic Tutor, Dimir House Guard, Entomb → graveyard, Step Through), 4 land-only; Lim-Dûl's Vault not a tutor.

## Open issues found by this deck

1. `tutors.py` exits on any NOT FOUND card; every other tool warns and continues.
2. Meld results (Brisela) resolve as legal deck cards with no warning.
3. Audit colors: multi-face cards (split, adventure, prepare) are checked as if both faces' costs were paid together (Wear // Tear needs R **and** W; Harmonized Trio shows UU).
4. Audit mana: transform cards with land backs (Search for Azcanta, Treasure Map) are counted as "MDFC land backs" and added to opener land odds. Only `modal_dfc` backs can be played as land drops.
5. Audit colors: restricted mana (Plaza of Heroes) counts as a full source of every color.
6. `tutors.py` computes package odds for a package whose parts share cards; the audit refuses the same package.
7. Audit checklist still says "Colors aren't modeled" although section 2 now models them.
