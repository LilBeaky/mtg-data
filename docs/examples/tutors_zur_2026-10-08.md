<!-- Saved 2026-11-17: the tutor-network report for Zur (tutors, tutor-to-tutor chains, routes, coverage, dependencies, key-card odds), kept as a model for other decks. Regenerate any deck with: python scripts/tutors.py decks/Ians_Zur_Wizardcycling.txt --md -->

# TUTORS: Zur the Enchanter | 99 cards in library | on the play
Odds ignore mana and the turns a chain takes ("can you get there", not "how fast"); goldfish.py is the mana check.  

## 1. Tutors (11 effects on 11 cards; 3 land-only effects listed separately)


| Tutor | How | Uses | Puts it | Finds | Targets here |
|---|---|---|---|---|---:|
| Zur the Enchanter (commander) | zur attacks | repeatable | battlefield | enchantment MV<=3 | 11 |
| Brainspoil | transmute | one-shot | hand | card MV=5 | 5 |
| Long-Term Plans | spell | one-shot | top | any card | 62 + 31 lands |
| Mystical Tutor | spell | one-shot | top | instant/sorcery | 21 |
| Personal Tutor | spell | one-shot | top | sorcery | 8 |
| Solve the Equation | spell | one-shot | hand | instant/sorcery | 21 |
| Spellseeker | enters | one-shot, re-buyable | hand | instant/sorcery MV<=2 | 11 |
| Step Through | wizardcycling | one-shot | hand | Wizard | 14 |
| Tribute Mage | enters | one-shot, re-buyable | hand | artifact MV=2 | 11 |
| Vedalken Aethermage | wizardcycling | one-shot | hand | Wizard | 13 |
| Wishclaw Talisman | activated | one-shot | hand | any card | 62 + 31 lands |

land-only (mana, not analyzed further): Ash Barrens; Flooded Strand; Land Tax  
flicker engines: Astral Slide (creature, repeatable); Flickering Hound (creature, repeatable); Astral Drift (creature, repeatable); Ephemerate (creature, one-shot); Escape Protocol (artifact, repeatable)  
re-buyable ETB tutors: Spellseeker via Astral Slide; Flickering Hound; Astral Drift | Tribute Mage via Astral Slide; Flickering Hound; Astral Drift  
find-anything tutors: Long-Term Plans; Wishclaw Talisman (the 'specific only' columns set them aside)  
targets:  
  - Zur the Enchanter: Astral Drift; Astral Slide; Escape Protocol; Grasp of Fate; Greater Auramancy; Land Tax; Necrodominance; Rule of Law; Solitary Confinement; Unquestioned Authority; Words of Worship
  - Brainspoil: Archfiend of Ifnir; Bloodline Necromancer; Disciple of Caelus Nin; Emeritus of Ideation // Ancestral Recall; Step Through
  - Long-Term Plans: Aether Channeler; Approach of the Second Sun; Arcane Signet; Archaeomancer; Archfiend of Ifnir; Astral Drift; Astral Slide; Auramancer; Azorius Signet; Bloodline Necromancer; Brainspoil; Complicate; Cyclonic Rift; Dark Ritual … (+48)
  - Mystical Tutor: Approach of the Second Sun; Brainspoil; Complicate; Cyclonic Rift; Dark Ritual; Ephemerate; Feed the Swarm; Forsake the Worldly; Fracture; Ghostway; Long-Term Plans; Mana Sculpt; Miscalculation; Neutralize … (+7)
  - Personal Tutor: Approach of the Second Sun; Brainspoil; Feed the Swarm; Pest Control; Solve the Equation; Step Through; Unearth; Wander in Death
  - Solve the Equation: Approach of the Second Sun; Brainspoil; Complicate; Cyclonic Rift; Dark Ritual; Ephemerate; Feed the Swarm; Forsake the Worldly; Fracture; Ghostway; Long-Term Plans; Mana Sculpt; Miscalculation; Mystical Tutor … (+7)
  - Spellseeker: Cyclonic Rift; Dark Ritual; Ephemerate; Feed the Swarm; Fracture; Miscalculation; Mystical Tutor; Personal Tutor; Pest Control; Swords to Plowshares; Unearth
  - Step Through: Aether Channeler; Archaeomancer; Auramancer; Bloodline Necromancer; Disciple of Caelus Nin; Dour Port-Mage; Drannith Magistrate; Emeritus of Ideation // Ancestral Recall; Glen Elendra Archmage; Naban, Dean of Iteration; Spellseeker; Tribute Mage; Triskaidekaphile; Vedalken Aethermage
  - Tribute Mage: Arcane Signet; Azorius Signet; Dimir Signet; Fellwar Stone; Fluctuator; Orzhov Signet; Talisman of Dominance; Talisman of Hierarchy; Talisman of Progress; Thought Vessel; Wishclaw Talisman
  - Vedalken Aethermage: Aether Channeler; Archaeomancer; Auramancer; Bloodline Necromancer; Disciple of Caelus Nin; Dour Port-Mage; Drannith Magistrate; Emeritus of Ideation // Ancestral Recall; Glen Elendra Archmage; Naban, Dean of Iteration; Spellseeker; Tribute Mage; Triskaidekaphile
  - Wishclaw Talisman: Aether Channeler; Approach of the Second Sun; Arcane Signet; Archaeomancer; Archfiend of Ifnir; Astral Drift; Astral Slide; Auramancer; Azorius Signet; Bloodline Necromancer; Brainspoil; Complicate; Cyclonic Rift; Dark Ritual … (+48)

## 2. Chains (tutors that find other tutors; a fetched tutor must land where it still works)


| Tutor | Can find these tutors |
|---|---|
| Brainspoil | Step Through |
| Long-Term Plans | Brainspoil; Mystical Tutor; Personal Tutor; Solve the Equation; Spellseeker; Step Through; Tribute Mage; Vedalken Aethermage; Wishclaw Talisman |
| Mystical Tutor | Brainspoil; Long-Term Plans; Personal Tutor; Solve the Equation; Step Through |
| Personal Tutor | Brainspoil; Solve the Equation; Step Through |
| Solve the Equation | Brainspoil; Long-Term Plans; Mystical Tutor; Personal Tutor; Step Through |
| Spellseeker | Mystical Tutor; Personal Tutor |
| Step Through | Spellseeker; Tribute Mage; Vedalken Aethermage |
| Tribute Mage | Wishclaw Talisman |
| Vedalken Aethermage | Spellseeker; Tribute Mage |
| Wishclaw Talisman | Brainspoil; Long-Term Plans; Mystical Tutor; Personal Tutor; Solve the Equation; Spellseeker; Step Through; Tribute Mage; Vedalken Aethermage |

routes a tutor only gets through another tutor (shortest route to each card):  
  - Brainspoil → Step Through → Spellseeker → Mystical Tutor → Approach of the Second Sun; Complicate; Forsake the Worldly; Ghostway; Long-Term Plans; Mana Sculpt; Neutralize; Solve the Equation … (+1)
  - Brainspoil → Step Through → Tribute Mage → Wishclaw Talisman → Astral Drift; Astral Slide; Escape Protocol; Flickering Hound; Grasp of Fate; Greater Auramancy; Land Tax; Mage's Attendant … (+7)
  - Brainspoil → Step Through → Spellseeker → Cyclonic Rift; Dark Ritual; Ephemerate; Feed the Swarm; Fracture; Miscalculation; Mystical Tutor; Personal Tutor … (+3)
  - Brainspoil → Step Through → Tribute Mage → Arcane Signet; Azorius Signet; Dimir Signet; Fellwar Stone; Fluctuator; Orzhov Signet; Talisman of Dominance; Talisman of Hierarchy … (+3)
  - Personal Tutor → Solve the Equation → Long-Term Plans → Arcane Signet; Astral Drift; Astral Slide; Azorius Signet; Dimir Signet; Escape Protocol; Fellwar Stone; Flickering Hound … (+18)
  - Spellseeker → Mystical Tutor → Brainspoil → Archfiend of Ifnir; Bloodline Necromancer; Disciple of Caelus Nin; Emeritus of Ideation // Ancestral Recall
  - Spellseeker → Mystical Tutor → Long-Term Plans → Aether Channeler; Arcane Signet; Archaeomancer; Astral Drift; Astral Slide; Auramancer; Azorius Signet; Dimir Signet … (+28)
  - Step Through → Spellseeker → Mystical Tutor → Approach of the Second Sun; Brainspoil; Complicate; Forsake the Worldly; Ghostway; Long-Term Plans; Mana Sculpt; Neutralize … (+2)
  - Step Through → Tribute Mage → Wishclaw Talisman → Archfiend of Ifnir; Astral Drift; Astral Slide; Escape Protocol; Flickering Hound; Grasp of Fate; Greater Auramancy; Land Tax … (+8)
  - Vedalken Aethermage → Spellseeker → Mystical Tutor → Approach of the Second Sun; Brainspoil; Complicate; Forsake the Worldly; Ghostway; Long-Term Plans; Mana Sculpt; Neutralize … (+3)
  - Vedalken Aethermage → Tribute Mage → Wishclaw Talisman → Archfiend of Ifnir; Astral Drift; Astral Slide; Escape Protocol; Flickering Hound; Grasp of Fate; Greater Auramancy; Land Tax … (+8)
  - Brainspoil → Step Through → Aether Channeler; Archaeomancer; Auramancer; Dour Port-Mage; Drannith Magistrate; Glen Elendra Archmage; Naban, Dean of Iteration; Spellseeker … (+3)
  - … more omitted

## 3. Coverage (nonland cards; ways = cards that can start a path to it)


| View | 2+ ways | 1 way | No tutor | Of |
|---|---:|---:|---:|---:|
| all tutors | 63 | 0 | 0 | 63 |
| specific tutors only | 48 | 11 | 4 | 63 |

specific tutors only, draw-only: Flickering Hound; Mage's Attendant; Monument to Endurance; Sol Ring  
specific tutors only, only via Zur the Enchanter: Astral Drift; Astral Slide; Escape Protocol; Grasp of Fate; Greater Auramancy; Land Tax; Necrodominance; Rule of Law; Solitary Confinement; Unquestioned Authority; Words of Worship  
nonbasic lands a tutor can find: 28 of 28  

## 4. Dependencies (cards that lose ALL tutor access without this one)


| View | Without | Cards cut off | Which |
|---|---|---:|---|
| all tutors | none | 0 | every tutorable card has two independent starting points |
| specific tutors only | Zur the Enchanter (commander) | 11 | Astral Drift; Astral Slide; Escape Protocol; Grasp of Fate; Greater Auramancy; Land Tax; Necrodominance; Rule of Law … (+3) |
| specific tutors only | Tribute Mage | 11 | Arcane Signet; Azorius Signet; Dimir Signet; Fellwar Stone; Fluctuator; Orzhov Signet; Talisman of Dominance; Talisman of Hierarchy … (+3) |
| specific tutors only | Brainspoil | 1 | Archfiend of Ifnir |
| specific tutors only | Step Through | 1 | Vedalken Aethermage |


## 5. Key cards (drawn, or a card with a path to it, by T4, T6)

yours (8, from the header lines): Astral Slide; Astral Drift; Step Through; Archaeomancer; Words of Worship; Necrodominance; Triskaidekaphile; Approach of the Second Sun  
inference also picks 5 of your 8; it misses Archaeomancer; Words of Worship; Necrodominance (how far to trust the inferred list on this deck)  
inferred beyond yours (5):  

| Inferred card | Score | Why |
|---|---:|---|
| Bloodline Necromancer | 2.8 | wizard package (14 cards); narrow tutors converge on it (0.31) |
| Emeritus of Ideation // Ancestral Recall | 2.3 | draw engine; narrow tutors converge on it (0.31) |
| Archfiend of Ifnir | 2.0 | payoff for cycling (15 cards) |
| Escape Protocol | 2.0 | payoff for cycling (15 cards) |
| Fluctuator | 2.0 | payoff for cycling (15 cards) |


| Card | Key | Ways | T4 best | T4 specific | T4 +cmdr | T4 played | T6 best | T6 specific | T6 +cmdr | T6 played | Drawn T4/T6 | Copies T6 (played) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Astral Slide | yours | 11 | 71.0% | 10.1% | 81.6% | 17.2% | 77.8% | 12.1% | 97.4% | 59.1% | 10.1% / 12.1% | 6.7 |
| Astral Drift | yours | 11 | 71.0% | 10.1% | 81.6% | 17.0% | 77.8% | 12.1% | 97.4% | 59.9% | 10.1% / 12.1% | 6.8 |
| Step Through | yours | 9 | 67.4% | 53.7% | — | 24.1% | 74.3% | 60.7% | — | 39.8% | 10.1% / 12.1% | 3.9 |
| Archaeomancer | yours | 10 | 71.0% | 58.7% | — | 18.0% | 77.8% | 65.9% | — | 36.6% | 10.1% / 12.1% | 3.5 |
| Words of Worship | yours | 11 | 71.0% | 10.1% | 81.6% | 19.6% | 77.8% | 12.1% | 97.4% | 60.3% | 10.1% / 12.1% | 6.9 |
| Necrodominance | yours | 11 | 71.0% | 10.1% | 81.6% | 17.3% | 77.8% | 12.1% | 97.4% | 59.7% | 10.1% / 12.1% | 6.8 |
| Triskaidekaphile | yours | 10 | 71.0% | 58.7% | — | 22.5% | 77.8% | 65.9% | — | 40.6% | 10.1% / 12.1% | 4.0 |
| Approach of the Second Sun | yours | 10 | 71.0% | 58.7% | — | 9.2% | 77.8% | 65.9% | — | 23.1% | 10.1% / 12.1% | 2.0 |
| Bloodline Necromancer | inferred | 10 | 71.0% | 58.7% | — | 8.5% | 77.8% | 65.9% | — | 12.2% | 10.1% / 12.1% | 1.0 |
| Emeritus of Ideation // Ancestral Recall | inferred | 10 | 71.0% | 58.7% | — | 8.6% | 77.8% | 65.9% | — | 12.3% | 10.1% / 12.1% | 1.0 |
| Archfiend of Ifnir | inferred | 10 | 71.0% | 58.7% | — | 7.7% | 77.8% | 65.9% | — | 10.2% | 10.1% / 12.1% | 0.8 |
| Escape Protocol | inferred | 11 | 71.0% | 10.1% | 81.6% | 8.5% | 77.8% | 12.1% | 97.4% | 12.1% | 10.1% / 12.1% | 1.0 |
| Fluctuator | inferred | 10 | 71.0% | 63.3% | — | 10.4% | 77.8% | 70.4% | — | 17.2% | 10.1% / 12.1% | 1.5 |

best: the card, or a library card that leads to it, every chain free. specific: without find-anything tutors.  
+cmdr: also the commander's own tutor once manasim.py games have it out long enough to use it (a ceiling).  
played: found (out of the library) by that turn in 2,000 manasim.py games with lands, ramp, tutors  
and draw played and the mana paid; your keys are fetched first, then package pieces, then inferred keys.  
Copies: how many copies of the card would give the same odds by that turn (from played).  

## 6. Packages (every piece drawn, or reached by a different tutor chain; a repeatable tutor can cover several)

none: no Spellbook combo of ≤3 cards here and no '# package:' lines (3 Spellbook 'combo(s)' that are only a tutor and its target left out)  

## 7. Tutor worth (each library tutor taken out, by T6: played, then best case)


| Tutor | Played: key cards per 100 games | Key cards (best) | Specific only | Whole deck (best) | Only it reaches |
|---|---:|---:|---:|---:|---|
| Step Through | +40 | +5.9 | +11.6 | +7.1 | — |
| Solve the Equation | +14 | +3.5 | +3.2 | +3.5 | — |
| Wishclaw Talisman | +13 | +7.2 | find-anything | +6.7 | — |
| Brainspoil | +12 | +3.5 | +6.9 | +3.5 | — |
| Personal Tutor | +8 | +3.5 | +3.2 | +3.5 | — |
| Tribute Mage | +8 | +3.5 | +4.5 | +3.5 | — |
| Vedalken Aethermage | +5 | +3.5 | +3.2 | +3.5 | — |
| Mystical Tutor | +4 | +3.5 | +3.2 | +3.5 | — |
| Spellseeker | +4 | +3.5 | +6.1 | +3.5 | — |
| Long-Term Plans | -3 | +3.5 | find-anything | +3.5 | — |

Played: key cards found by T6 per 100 games that this tutor adds (the same 2,000 games with the tutor  
inert, compared one by one; ≈: within noise or under 1 per 100). This is the number for 'is it worth its slot'.  
Best-case columns: points of mean access lost over the key cards and the whole deck.  
Best case: mean access over the 13 key cards and the 63 nonland cards, the commander's own tutoring  
left out, every chain free (so tutors look alike); 'specific only' sets the find-anything tutors aside.  
