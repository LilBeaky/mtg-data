# T2 review sheet: GEF translation vs regex parser

## Klauth, Unrivaled Ancient

**Oracle:** Flying, haste
Whenever Klauth attacks, add X mana in any combination of colors, where X is the total power of attacking creatures. Spend this mana only to cast spells. Until end of turn, you don't lose this mana as steps and phases end.

**Parser (modeled):** on attack_self: mana X (total power of attackers); 4/4 flying, haste

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"flying"}
  - keyword {"keyword":"haste"}
  - unexpressible {"reason":"X is total power of attacking creatures (no count key); mana also persists through steps and phases","scope":"format_gap"}

**Signature diff:** fx: parser-only ['mana'], gef-only []; ev: parser-only ['attacks'], gef-only []

## Become the Avalanche

**Oracle:** Draw a card for each creature you control with power 4 or greater. Then creatures you control get +X/+X until end of turn, where X is the number of cards in your hand.

**Parser (blank):** body only  [unmodeled: Draw a card for each creature you control with power 4 or greater. Then ]

**GEF (today modeled, expressed modeled):**
  - spell  => draw {"n":{"count":"permanents_you_control","filter":{"types":["creature"],"controller":"you","power":{"min":4}}}}; pump_team {"filter":{"types":["creature"],"controller":"you"},"power":{"count":"cards_in_hand"},"toughness":{"count":"cards_in_hand"},"duration":"end_of_turn"}

**Signature diff:** fx: parser-only [], gef-only ['draw', 'pump_team']

## Biorhythm

**Oracle:** Each player's life total becomes the number of creatures they control.

**Parser (modeled):** life totals become creature counts ~opp; pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"each player's life set to their own creature count; counts only cover your permanents","scope":"format_gap"}

**Signature diff:** fx: parser-only ['set_life'], gef-only []

## Bower Passage

**Oracle:** Creatures with flying can't block creatures you control.

**Parser (blank):** body only  [unmodeled: Creatures with flying can't block creatures you control.]

**GEF (today vacuum, expressed vacuum):**
  - unexpressible {"reason":"restricts what opposing creatures can block","scope":"out_of_scope"}

**Signature diff:** 

## Breaching Dragonstorm

**Oracle:** When this enchantment enters, exile cards from the top of your library until you exile a nonland card. You may cast it without paying its mana cost if that spell's mana value is 8 or less. If you don't, put that card into your hand.
When a Dragon you control enters, return this enchantment to its owner's hand.

**Parser (partial):** ETB free cast of the next nonland card (MV <= 8); on etb(Dragon ): return ~ to hand  [unread part: If you don't, put that card into your hand.]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"conditional free cast (mana value 8 or less) with hand fallback on the exiled card","scope":"format_gap"}
  - triggered {"event":{"on":"enters","subject":{"subtypes":["Dragon"],"controller":"you"}}} => bounce_self

**Signature diff:** fx: parser-only ['cast_free'], gef-only []

## Cinder Glade

**Oracle:** ({T}: Add {R} or {G}.)
This land enters tapped unless you control two or more basic lands.

**Parser (land*):** land RG; tapped  [conditional enters-tapped read as always tapped]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["land"],"supertypes":["basic"],"controller":"you"},"min":2}}}

**Signature diff:** 

## Exotic Orchard

**Oracle:** {T}: Add one mana of any color that a land an opponent controls could produce.

**Parser (land*):** land WUBRG  [assumes opponents' lands cover your colors]

**GEF (today land*, expressed land*):**
  - unexpressible {"reason":"mana colors depend on what opponents' lands could produce","scope":"format_gap"}

**Signature diff:** fx: parser-only ['mana'], gef-only []

## Finale of Devastation

**Oracle:** Search your library and/or graveyard for a creature card with mana value X or less and put it onto the battlefield. If you search your library this way, shuffle. If X is 10 or more, creatures you control get +X/+X and gain haste until end of turn.

**Parser (partial):** tutor->bf: creature ~mana value x or less  [unread part: If X is 10 or more, creatures you control get +X/+X and gain has]

**GEF (today blank, expressed modeled):**
  - spell  => tutor {"filter":{"types":["creature"],"mana_value":{"max":"X"}},"n":1,"from":["library","graveyard"],"to":"battlefield"}; if {"cond":{"if":"x_at_least","n":10},"then":[{"do":"pump_team","filter":{"types":["creature"],"controller":"you"},"power":"X","toughness":"X","keywords":["haste"],"duration":"end_of_turn"}]}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Goreclaw, Terror of Qal Sisma

**Oracle:** Creature spells you cast with power 4 or greater cost {2} less to cast.
Whenever Goreclaw attacks, each creature you control with power 4 or greater gets +1/+1 and gains trample until end of turn.

**Parser (partial):** reduce {2}: Creature power>=4; 4/3  [unmodeled: Whenever ~ attacks, each creature you control with power 4 or greater ge]

**GEF (today modeled, expressed modeled):**
  - static {"effect":{"static":"cost_reduction","spells":{"types":["creature"],"power":{"min":4}},"amount":2,"applies_to":"spells"}}
  - triggered {"event":{"on":"attacks","subject":"self"}} => pump_team {"filter":{"types":["creature"],"controller":"you","power":{"min":4}},"power":1,"toughness":1,"keywords":["trample"],"duration":"end_of_turn"}

**Signature diff:** fx: parser-only [], gef-only ['pump_team']; ev: parser-only [], gef-only ['attacks']

## Green Sun's Zenith

**Oracle:** Search your library for a green creature card with mana value X or less, put it onto the battlefield, then shuffle. Shuffle Green Sun's Zenith into its owner's library.

**Parser (modeled):** tutor->bf: G creature ~mana value x or less

**GEF (today modeled, expressed modeled):**
  - spell  => tutor {"filter":{"types":["creature"],"colors":["G"],"mana_value":{"max":"X"}},"n":1,"from":["library"],"to":"battlefield"}; self_to_library {"where":"shuffle"}

**Signature diff:** fx: parser-only [], gef-only ['self_to_library']

## Invasion of Ikoria // Zilortha, Apex of Ikoria

**Oracle:** (As a Siege enters, choose an opponent to protect it. You and others can attack it. When it's defeated, exile it, then cast it transformed.)
When this Siege enters, search your library and/or graveyard for a non-Human creature card with mana value X or less and put it onto the battlefield. If you search your library this way, shuffle. // Reach
For each non-Human creature you control, you may have that creature assign its combat damage as though it weren't blocked.

**Parser (modeled):** ETB tutor->bf: non-Human creature ~mana value x or less

**GEF (today partial, expressed partial):**
  - triggered {"event":{"on":"enters","subject":"self"}} => tutor {"filter":{"types":["creature"],"non_subtypes":["Human"],"mana_value":{"max":"X"}},"n":1,"from":["library","graveyard"],"to":"battlefield"}
  - keyword {"keyword":"reach"}
  - unexpressible {"reason":"combat damage assignment as though unblocked; no construct","scope":"format_gap"}

**Signature diff:** kw: parser-only [], gef-only ['reach']

## Jeska's Will

**Oracle:** Choose one. If you control a commander as you cast this spell, you may choose both instead.
• Add {R} for each card in target opponent's hand.
• Exile the top three cards of your library. You may play them this turn.

**Parser (modeled):** draw 3, mana RRRR

**GEF (today blank, expressed modeled):**
  - spell  => if {"cond":{"if":"you_control_commander"},"then":[{"do":"choose","n":2,"up_to":true,"modes":[[{"do":"mana","produce":{"units":["R"],"amount":{"count":"cards_in_opponent_hand"}}}],[{"do":"impulse","n":3,"until":"end_of_turn"}]]}],"else":[{"do":"choose","n":1,"modes":[[{"do":"mana","produce":{"units":["R"],"amount":{"count":"cards_in_opponent_hand"}}}],[{"do":"impulse","n":3,"until":"end_of_turn"}]]}]}

**Signature diff:** fx: parser-only ['draw', 'mana'], gef-only []

## Kessig Wolf Run

**Oracle:** {T}: Add {C}.
{X}{R}{G}, {T}: Target creature gets +X/+0 and gains trample until end of turn.

**Parser (land*):** land C  [unmodeled: {X}{R}{G}, {T}: Target creature gets +X/+0 and gains trample until end o]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{X}{R}{G}","tap":true}} => pump {"target":{"ref":"target","filter":{"types":["creature"]}},"power":"X","keywords":["trample"],"duration":"end_of_turn"}

**Signature diff:** fx: parser-only [], gef-only ['pump']

## Klauth's Will

**Oracle:** Choose one. If you control a commander as you cast this spell, you may choose both instead.
• Breathe Flame — Klauth's Will deals X damage to each creature without flying.
• Smash Relics — Destroy up to X target artifacts and/or enchantments.

**Parser (held):** held (interaction)  [unmodeled modes: ~ deals X damage to each creat / Destroy up to X target artifac]

**GEF (today blank, expressed held):**
  - spell  => if {"cond":{"if":"you_control_commander"},"then":[{"do":"choose","n":2,"up_to":true,"modes":[[{"do":"wipe","how":"damage","filter":{"types":["creature"],"without_keywords":["flying"]},"amount":"X"}],[{"do":"remove","how":"destroy","target":{"ref":"target","n":"X","up_to":true,"filter":{"types":["artifact","enchantment"]}}}]]}],"else":[{"do":"choose","n":1,"modes":[[{"do":"wipe","how":"damage","filter":{"types":["creature"],"without_keywords":["flying"]},"amount":"X"}],[{"do":"remove","how":"destroy","target":{"ref":"target","n":"X","up_to":true,"filter":{"types":["artifact","enchantment"]}}}]]}]}

**Signature diff:** 

## Knollspine Dragon

**Oracle:** Flying
When this creature enters, you may discard your hand and draw cards equal to the damage dealt to target opponent this turn.

**Parser (partial):** 7/5 flying  [unmodeled: When ~ enters, you may discard your hand and draw cards equal to the dam]

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"flying"}
  - triggered {"event":{"on":"enters","subject":"self"},"optional":true} => discard {"n":"hand"}; unexpressible {"reason":"no count for damage dealt to a target opponent this turn","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['discard']; ev: parser-only [], gef-only ['enters']

## Maelstrom of the Spirit Dragon

**Oracle:** {T}: Add {C}.
{T}: Add one mana of any color. Spend this mana only to cast a Dragon spell or an Omen spell.
{4}, {T}, Sacrifice this land: Search your library for a Dragon card, reveal it, put it into your hand, then shuffle.

**Parser (land*):** land WUBRGC; act [T 4 sac]: tutor->hand: Dragon  [mana restriction not recognized; treated as unrestricted]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - mana {"cost":{"tap":true},"produce":{"units":["any"],"restrict":"Spend this mana only to cast a Dragon spell or an Omen spell."}}
  - activated {"cost":{"mana":"{4}","tap":true,"sacrifice":"self"}} => tutor {"filter":{"subtypes":["Dragon"]},"n":1,"from":["library"],"to":"hand","reveal":true}

**Signature diff:** 

## Mossfire Valley

**Oracle:** {1}, {T}: Add {R}{G}.

**Parser (land*):** land RG; filter 1->2  [mana read from produced_mana]

**GEF (today land, expressed land):**
  - mana {"cost":{"mana":"{1}","tap":true},"produce":{"units":["R","G"]}}

**Signature diff:** 

## Return of the Wildspeaker

**Oracle:** Choose one —
• Draw cards equal to the greatest power among non-Human creatures you control.
• Non-Human creatures you control get +3/+3 until end of turn.

**Parser (modeled):** draw greatest power (non-Human)

**GEF (today modeled, expressed modeled):**
  - spell  => choose {"n":1,"modes":[[{"do":"draw","n":{"count":"greatest_power","filter":{"types":["creature"],"non_subtypes":["Human"],"controller":"you"}}}],[{"do":"pump_team","filter":{"types":["creature"],"non_subtypes":["Human"],"controller":"you"},"power":3,"toughness":3,"duration":"end_of_turn"}]]}

**Signature diff:** fx: parser-only [], gef-only ['pump_team']

## Rhythm of the Wild

**Oracle:** Creature spells you control can't be countered.
Nontoken creatures you control have riot. (They enter with your choice of a +1/+1 counter or haste.)

**Parser (modeled):** anthem creatures haste

**GEF (today blank, expressed modeled):**
  - unexpressible {"reason":"only matters against opponents' counterspells, which a goldfish never has","scope":"out_of_scope"}
  - static {"effect":{"static":"grant_abilities","filter":{"types":["creature"],"nontoken":true,"controller":"you"},"abilities":[{"kind":"keyword","text":"Riot","keyword":"riot"}]}}

**Signature diff:** 

## Savage Ventmaw

**Oracle:** Flying
Whenever this creature attacks, add {R}{R}{R}{G}{G}{G}. Until end of turn, you don't lose this mana as steps and phases end.

**Parser (modeled):** on attack_self: mana RRRGGG; 4/4 flying

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"flying"}
  - triggered {"event":{"on":"attacks","subject":"self"}} => mana {"produce":{"units":["R","R","R","G","G","G"]}}; unexpressible {"reason":"mana persisting through steps and phases has no construct","scope":"format_gap"}

**Signature diff:** 

## Shamanic Revelation

**Oracle:** Draw a card for each creature you control.
Ferocious — You gain 4 life for each creature you control with power 4 or greater.

**Parser (partial):** draw per creatures  [unmodeled: Ferocious — You gain 4 life for each creature you control with power 4 o]

**GEF (today modeled, expressed modeled):**
  - spell  => draw {"n":{"count":"permanents_you_control","filter":{"types":["creature"],"controller":"you"}}}
  - spell  => gain_life {"n":{"count":"permanents_you_control","filter":{"types":["creature"],"controller":"you","power":{"min":4}},"times":4},"who":"you"}

**Signature diff:** fx: parser-only [], gef-only ['gain_life']

## Shared Animosity

**Oracle:** Whenever a creature you control attacks, it gets +1/+0 until end of turn for each other attacking creature that shares a creature type with it.

**Parser (modeled):** on attack(creature): pump obj +1 per atk_share/+0 per atk_share EOT

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"no count of attacking creatures sharing a creature type with the pumped creature","scope":"format_gap"}

**Signature diff:** fx: parser-only ['pump'], gef-only []; ev: parser-only ['attacks'], gef-only []

## Signal the Clans

**Oracle:** Search your library for three creature cards and reveal them. If you reveal three cards with different names, choose one of them at random and put that card into your hand. Shuffle the rest into your library.

**Parser (partial):** tutor->hand: 3x creature  [unread part: If you reveal three cards with different names, choose one of th]

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"random pick of one of three revealed cards conditional on different names, rest shuffled back","scope":"format_gap"}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Thrakkus the Butcher

**Oracle:** Trample
Whenever Thrakkus attacks, double the power of each Dragon you control until end of turn.

**Parser (modeled):** on attack_self: double power of each Dragon EOT; 3/4 trample

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"trample"}
  - unexpressible {"reason":"doubling each Dragon's own power; pump cannot take a per-creature amount","scope":"format_gap"}

**Signature diff:** fx: parser-only ['pump'], gef-only []; ev: parser-only ['attacks'], gef-only []

## Unnatural Growth

**Oracle:** At the beginning of each combat, double the power and toughness of each creature you control until end of turn.

**Parser (modeled):** on combat_begin: double power and toughness of each creature EOT

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"doubling each creature's own power and toughness; pump cannot take a per-creature amount","scope":"format_gap"}

**Signature diff:** fx: parser-only ['pump'], gef-only []; ev: parser-only ['combat_begin'], gef-only []

## Valakut Awakening // Valakut Stoneforge

**Oracle:** Put any number of cards from your hand on the bottom of your library, then draw that many cards plus one. // This land enters tapped.
{T}: Add {R}.

**Parser (blank):** MDFC land back  [unmodeled: Put any number of cards from your hand on the bottom of your library, th]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"draw count depends on the number of cards chosen from hand; no such count","scope":"format_gap"}
  - static {"effect":{"static":"enters_tapped"}}
  - mana {"cost":{"tap":true},"produce":{"units":["R"]}}

**Signature diff:** fx: parser-only [], gef-only ['mana']

## Vorinclex, Voice of Hunger

**Oracle:** Trample
Whenever you tap a land for mana, add one mana of any type that land produced.
Whenever an opponent taps a land for mana, that land doesn't untap during its controller's next untap step.

**Parser (modeled):** mana +1 per tap (lands); 7/6 trample  [needs opponents: Whenever an opponent taps a land for mana, that land doesn't untap durin]

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"trample"}
  - unexpressible {"reason":"adds one extra mana of the type the land produced; no construct for matching the produced type","scope":"format_gap"}
  - unexpressible {"reason":"only concerns opponents' lands","scope":"out_of_scope"}

**Signature diff:** 

## Yusri, Fortune's Flame

**Oracle:** Flying
Whenever Yusri attacks, choose a number between 1 and 5. Flip that many coins. For each flip you win, draw a card. For each flip you lose, Yusri deals 2 damage to you. If you won five flips this way, you may cast spells from your hand this turn without paying their mana costs.

**Parser (partial):** on attack_self: draw 1; 2/3 flying  [unread part: for each flip you lose, ~ deals 2 damage to you.]

**GEF (today partial, expressed modeled):**
  - keyword {"keyword":"flying"}
  - triggered {"event":{"on":"attacks","subject":"self"}} => choose_number {"min":1,"max":5}; flip_coins {"n":{"count":"number_chosen"},"on_win":[{"do":"draw","n":1}],"on_lose":[{"do":"damage","n":2,"to":"you","source":"self"}]}; if {"cond":{"if":"amount_at_least","amount":{"count":"coin_flips_won"},"n":5},"then":[{"do":"free_cast_permission","spells":{"any":true},"from":"hand","duration":"end_of_turn"}]}

**Signature diff:** fx: parser-only ['draw'], gef-only []; ev: parser-only ['attacks'], gef-only []

## Academy Ruins

**Oracle:** {T}: Add {C}.
{1}{U}, {T}: Put target artifact card from your graveyard on top of your library.

**Parser (land*):** land C  [unmodeled: {1}{U}, {T}: Put target artifact card from your graveyard on top of your]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{1}{U}","tap":true}} => recur {"filter":{"types":["artifact"]},"n":1,"to":"library_top","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['recur']

## Aetherflux Reservoir

**Oracle:** Whenever you cast a spell, you gain 1 life for each spell you've cast this turn.
Pay 50 life: This artifact deals 50 damage to any target.

**Parser (partial):** act [50 life]: an opponent loses 50  [unmodeled: Whenever you cast a spell, you gain 1 life for each spell you've cast th]

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"cast","who":"you"}} => gain_life {"n":{"count":"spells_cast_this_turn"},"who":"you"}
  - activated {"cost":{"pay_life":50}} => damage {"n":50,"to":"any_target","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['gain_life']; ev: parser-only [], gef-only ['cast']

## Ancient Silver Dragon

**Oracle:** Flying
Whenever this creature deals combat damage to a player, roll a d20. Draw cards equal to the result. You have no maximum hand size for the rest of the game.

**Parser (modeled):** no_max_hand; 8/8 flying

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"flying"}
  - triggered {"event":{"on":"combat_damage_to_player","subject":"self"}} => roll_die {"sides":20,"table":[{"min":1,"max":1,"effects":[{"do":"draw","n":1}]},{"min":2,"max":2,"effects":[{"do":"draw","n":2}]},{"min":3,"max":3,"effects":[{"do":"draw","n":3}]},{"min":4,"max":4,"effects":[{"do":"draw","n":4}]},{"min":5,"max":5,"effects":[{"do":"draw","n":5}]},{"min":6,"max":6,"effects":[{"do":"draw","n":6}]},{"min":7,"max":7,"effects":[{"do":"draw","n":7}]},{"min":8,"max":8,"effects":[{"do":"draw","n":8}]},{"min":9,"max":9,"effects":[{"do":"draw","n":9}]},{"min":10,"max":10,"effects":[{"do":"draw","n":10}]},{"min":11,"max":11,"effects":[{"do":"draw","n":11}]},{"min":12,"max":12,"effects":[{"do":"draw","n":12}]},{"min":13,"max":13,"effects":[{"do":"draw","n":13}]},{"min":14,"max":14,"effects":[{"do":"draw","n":14}]},{"min":15,"max":15,"effects":[{"do":"draw","n":15}]},{"min":16,"max":16,"effects":[{"do":"draw","n":16}]},{"min":17,"max":17,"effects":[{"do":"draw","n":17}]},{"min":18,"max":18,"effects":[{"do":"draw","n":18}]},{"min":19,"max":19,"effects":[{"do":"draw","n":19}]},{"min":20,"max":20,"effects":[{"do":"draw","n":20}]}]}; unexpressible {"reason":"permanent no-max-hand-size granted as an effect has no construct (only a static)","scope":"format_gap"}

**Signature diff:** 

## Chaos Warp

**Oracle:** The owner of target permanent shuffles it into their library, then reveals the top card of their library. If it's a permanent card, they put it onto the battlefield.

**Parser (held):** removal: exile an opposing creature; held (interaction); can kill tax/lock pieces: artifact/creature/enchantment

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"shuffle into library followed by a conditional reveal-and-put-onto-battlefield for the owner; no construct","scope":"format_gap"}

**Signature diff:** fx: parser-only ['remove'], gef-only []

## Enter the Infinite

**Oracle:** Draw cards equal to the number of cards in your library, then put a card from your hand on top of your library. You have no maximum hand size until your next turn.

**Parser (modeled):** no_max_hand

**GEF (today partial, expressed partial):**
  - spell  => draw {"n":{"count":"cards_in_library"}}; put_back {"n":1,"to":"library_top"}; unexpressible {"reason":"temporary no-max-hand-size effect has no construct","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['draw', 'put_back']

## Full Throttle

**Oracle:** After this main phase, there are two additional combat phases.
At the beginning of each combat this turn, untap all creatures that attacked this turn.

**Parser (blank):** body only  [unmodeled: After this main phase, there are two additional combat phases.; unmodeled: At the beginning of each combat this turn, untap all creatures that atta]

**GEF (today partial, expressed partial):**
  - spell  => extra_combat {"n":2,"untap":"none","then_main":false}
  - unexpressible {"reason":"delayed per-combat untap of creatures that attacked this turn; no filter for 'attacked this turn'","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['extra_combat']

## Fury of the Horde

**Oracle:** You may exile two red cards from your hand rather than pay this spell's mana cost.
Untap all creatures that attacked this turn. After this main phase, there is an additional combat phase followed by an additional main phase.

**Parser (partial):** untap attacked creatures, additional combat; pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage  [unmodeled: You may exile two red cards from your hand rather than pay ~'s mana cost]

**GEF (today modeled, expressed modeled):**
  - alt_cost {"cost":{"exile_from_hand":{"n":2,"filter":{"colors":["R"]}}}}
  - spell  => extra_combat {"n":1,"untap":"attackers","then_main":true}

**Signature diff:** fx: parser-only ['untap'], gef-only []

## Gifts Ungiven

**Oracle:** Search your library for up to four cards with different names and reveal them. Target opponent chooses two of those cards. Put the chosen cards into your graveyard and the rest into your hand. Then shuffle.

**Parser (partial):** tutor->hand: 4x any card  [unread part: put the chosen cards into your graveyard and the rest into your ]

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"an opponent picks which two of the four you keep; needs an opponent-choice stand-in","scope":"format_gap"}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Long-Term Plans

**Oracle:** Search your library for a card, then shuffle and put that card third from the top.

**Parser (modeled):** tutor->top: any card

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"puts the found card third from the top of the library; GEF only has library_top, library_bottom and library_shuffled","scope":"format_gap"}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Reality Shift

**Oracle:** Exile target creature. Its controller manifests the top card of their library. (That player puts the top card of their library onto the battlefield face down as a 2/2 creature. If it's a creature card, it can be turned face up any time for its mana cost.)

**Parser (held):** held (interaction); can kill tax/lock pieces: creature  [unmodeled: Exile target creature. Its controller manifests the top card of their li]

**GEF (today held, expressed held):**
  - spell  => remove {"how":"exile","target":{"ref":"target","filter":{"types":["creature"]}}}; unexpressible {"reason":"manifest (a face-down 2/2 from the top of a library) has no construct","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Reckless Handling

**Oracle:** Search your library for an artifact card, reveal it, put it into your hand, shuffle, then discard a card at random. If an artifact card was discarded this way, Reckless Handling deals 2 damage to each opponent.

**Parser (modeled):** tutor->hand: artifact, discard 1

**GEF (today partial, expressed partial):**
  - spell  => tutor {"filter":{"types":["artifact"]},"n":1,"to":"hand","reveal":true}; discard {"n":1,"who":"you","random":true}; unexpressible {"reason":"conditional on the type of the randomly discarded card; no condition for it","scope":"format_gap"}

**Signature diff:** 

## Seize the Day

**Oracle:** Untap target creature. After this main phase, there is an additional combat phase followed by an additional main phase.
Flashback {2}{R} (You may cast this card from your graveyard for its flashback cost. Then exile it.)

**Parser (partial):** additional combat; flashback from graveyard (3); pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage  [unread part: untap target creature.]

**GEF (today partial, expressed modeled):**
  - spell  => untap {"what":{"ref":"target","filter":{"types":["creature"]}}}; extra_combat {"n":1,"untap":"none","then_main":true}
  - keyword {"keyword":"flashback","cost":"{2}{R}"}

**Signature diff:** fx: parser-only ['extra_combat'], gef-only []

## Simian Spirit Guide

**Oracle:** Exile this card from your hand: Add {R}.

**Parser (blank):** 2/2  [unmodeled: Exile ~ from your hand: Add {R}.]

**GEF (today modeled, expressed modeled):**
  - activated {"from_zone":"hand","cost":{"exile_from_hand":"self"}} => mana {"produce":{"units":["R"]}}

**Signature diff:** fx: parser-only [], gef-only ['mana']

## Sword of War and Peace

**Oracle:** Equipped creature gets +2/+2 and has protection from red and from white.
Whenever equipped creature deals combat damage to a player, this Equipment deals damage to that player equal to the number of cards in their hand and you gain 1 life for each card in your hand.
Equip {2}

**Parser (partial):** equipped creature +2/+2; equip 2  [unmodeled: Whenever equipped creature deals combat damage to a player, ~ deals dama]

**GEF (today modeled, expressed modeled):**
  - static {"effect":{"static":"attached_bonus","power":2,"toughness":2,"keywords":["protection from red","protection from white"]}}
  - triggered {"event":{"on":"combat_damage_to_player","subject":"equipped"}} => damage {"n":{"count":"cards_in_opponent_hand"},"to":"that_player","source":"self"}; gain_life {"n":{"count":"cards_in_hand"},"who":"you"}
  - keyword {"keyword":"equip","cost":"{2}"}

**Signature diff:** fx: parser-only [], gef-only ['drain', 'gain_life']; ev: parser-only [], gef-only ['combat_damage_to_player']

## Thassa's Oracle

**Oracle:** When this creature enters, look at the top X cards of your library, where X is your devotion to blue. Put up to one of them on top of your library and the rest on the bottom of your library in a random order. If X is greater than or equal to the number of cards in your library, you win the game. (Each {U} in the mana costs of permanents you control counts toward your devotion to blue.)

**Parser (modeled):** ETB win if devotion to U >= library (held until it wins); needs a oracle; 1/3

**GEF (today partial, expressed partial):**
  - triggered {"event":{"on":"enters","subject":"self"}} => look {"n":{"count":"devotion","colors":"U"},"take":1,"to":"library_top","rest":"bottom","from":"library"}; unexpressible {"reason":"comparing devotion X to library size has no condition construct","scope":"format_gap"}

**Signature diff:** fx: parser-only ['win_game'], gef-only ['look']

## Twenty-Toed Toad

**Oracle:** Your maximum hand size is twenty.
Whenever you attack with two or more creatures, put a +1/+1 counter on this creature and draw a card.
Whenever this creature attacks, you win the game if there are twenty or more counters on it or you have twenty or more cards in hand.

**Parser (blank):** 3/3  [unmodeled: Your maximum hand size is twenty.; unmodeled: Whenever you attack with two or more creatures, put a +1/+1 counter on ~; unmodeled: Whenever ~ attacks, you win the game if there are twenty or more counter]

**GEF (today partial, expressed modeled):**
  - static {"effect":{"static":"max_hand_size","n":20}}
  - triggered {"event":{"on":"you_attack","min_attackers":2}} => counters {"kind":"+1/+1","n":1,"on":{"ref":"self"}}; draw {"n":1}
  - triggered {"event":{"on":"attacks","subject":"self"}} => if {"cond":{"if":"or","conds":[{"if":"amount_at_least","amount":{"count":"counters_on_self"},"n":20},{"if":"hand_at_least","n":20}]},"then":[{"do":"win_game"}]}

**Signature diff:** fx: parser-only [], gef-only ['counters', 'draw']; ev: parser-only [], gef-only ['attacks']

## Witch's Clinic

**Oracle:** {T}: Add {C}.
{2}, {T}: Target commander gains lifelink until end of turn.

**Parser (land*):** land C  [unmodeled: {2}, {T}: Target commander gains lifelink until end of turn.]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{2}","tap":true}} => pump {"target":{"ref":"target","filter":{"commander":true}},"keywords":["lifelink"],"duration":"end_of_turn"}

**Signature diff:** fx: parser-only [], gef-only ['pump']

## Aether Channeler

**Oracle:** When this creature enters, choose one —
• Create a 1/1 white Bird creature token with flying.
• Return another target nonland permanent to its owner's hand.
• Draw a card.

**Parser (modeled):** ETB draw 1; 2/1

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"}} => choose {"n":1,"modes":[[{"do":"token","n":1,"token":{"name":"Bird","types":["creature"],"subtypes":["Bird"],"colors":["W"],"power":1,"toughness":1,"keywords":["flying"]}}],[{"do":"remove","how":"bounce","target":{"ref":"target","filter":{"types":["permanent"],"non_types":["land"],"another":true}}}],[{"do":"draw","n":1}]]}

**Signature diff:** fx: parser-only [], gef-only ['remove', 'token']

## Azami, Lady of Scrolls

**Oracle:** Tap an untapped Wizard you control: Draw a card.

**Parser (blank):** 0/2  [unmodeled: Tap an untapped Wizard you control: Draw a card.]

**GEF (today modeled, expressed modeled):**
  - activated {"cost":{"tap_untapped":{"n":1,"filter":{"subtypes":["Wizard"],"controller":"you"}}}} => draw {"n":1}

**Signature diff:** fx: parser-only [], gef-only ['draw']

## Brainspoil

**Oracle:** Destroy target creature that isn't enchanted. It can't be regenerated.
Transmute {1}{B}{B} ({1}{B}{B}, Discard this card: Search your library for a card with the same mana value as this card, reveal it, put it into your hand, then shuffle. Transmute only as a sorcery.)

**Parser (held):** held (interaction); can kill tax/lock pieces: creature; transmute {3}: tutor->hand: card MV=5  [unmodeled: Destroy target creature that isn't enchanted. It can't be regenerated.]

**GEF (today held, expressed held):**
  - spell  => remove {"how":"destroy","target":{"ref":"target","filter":{"types":["creature"],"enchanted":false}}}; unexpressible {"reason":"regeneration restriction on the target; only matters for opposing permanents","scope":"out_of_scope"}
  - keyword {"keyword":"transmute","cost":"{1}{B}{B}"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Complicate

**Oracle:** Counter target spell unless its controller pays {3}.
Cycling {2}{U} ({2}{U}, Discard this card: Draw a card.)
When you cycle this card, you may counter target spell unless its controller pays {1}.

**Parser (held):** held (interaction); answers disruption: counter; cycling {3}: draw 1  [unmodeled: When you cycle ~, you may counter target spell unless its controller pay]

**GEF (today held, expressed held):**
  - spell  => counter_spell {"unless_pays":"{3}"}
  - keyword {"keyword":"cycling","cost":"{2}{U}"}
  - triggered {"event":{"on":"cycle_self"},"optional":true} => counter_spell {"unless_pays":"{1}"}

**Signature diff:** ev: parser-only [], gef-only ['cycle']

## Deafening Silence

**Oracle:** Each player can't cast more than one noncreature spell each turn.

**Parser (vacuum):** body only  [needs opponents: Each player can't cast more than one noncreature spell each turn.]

**GEF (today blank, expressed blank):**
  - static {"effect":{"static":"restriction","who":"each_player","text":"Each player can't cast more than one noncreature spell each turn."}}

**Signature diff:** 

## Emeritus of Ideation // Ancestral Recall

**Oracle:** Flying, ward {2}
This creature enters prepared.
Whenever this creature attacks, you may exile eight cards from your graveyard. If you do, this creature becomes prepared. // Target player draws three cards.

**Parser (partial):** 5/5 flying  [unmodeled: ~ enters prepared.; unmodeled: Whenever ~ attacks, you may exile eight cards from your graveyard. If yo]

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"flying"}
  - keyword {"keyword":"ward","cost":"{2}"}
  - unexpressible {"reason":"the prepared mechanic has no GEF construct","scope":"format_gap"}
  - triggered {"event":{"on":"attacks","subject":"self"}} => may_pay {"cost":{"exile_from_graveyard":{"n":8}},"then":[{"do":"unexpressible","text":"this creature becomes prepared","reason":"the prepared mechanic has no GEF construct","scope":"format_gap"}]}
  - spell  => draw {"n":3,"who":"target_player"}

**Signature diff:** fx: parser-only [], gef-only ['draw']; ev: parser-only [], gef-only ['attacks']

## Ephemerate

**Oracle:** Exile target creature you control, then return it to the battlefield under its owner's control.
Rebound (If you cast this spell from your hand, exile it as it resolves. At the beginning of your next upkeep, you may cast this card from exile without paying its mana cost.)

**Parser (held):** held (interaction); can kill tax/lock pieces: creature; rebound  [unmodeled: Exile target creature you control, then return it to the battlefield und]

**GEF (today partial, expressed modeled):**
  - spell  => flicker {"what":{"ref":"target","filter":{"types":["creature"],"controller":"you"}},"returns":"immediately"}
  - keyword {"keyword":"rebound"}

**Signature diff:** 

## Ertai Resurrected

**Oracle:** Flash
When Ertai Resurrected enters, choose up to one —
• Counter target spell, activated ability, or triggered ability. Its controller draws a card.
• Destroy another target creature or planeswalker. Its controller draws a card.

**Parser (blank):** answers disruption: counter; 3/2  [unmodeled: When ~ enters, choose up to one —; unmodeled: • Counter target spell, activated ability, or triggered ability. Its con; unmodeled: • Destroy another target creature or planeswalker. Its controller draws ]

**GEF (today modeled, expressed modeled):**
  - keyword {"keyword":"flash"}
  - triggered {"event":{"on":"enters","subject":"self"}} => choose {"n":1,"up_to":true,"modes":[[{"do":"counter_spell","abilities":true},{"do":"draw","n":1,"who":"its_controller"}],[{"do":"remove","how":"destroy","target":{"ref":"target","filter":{"types":["creature","planeswalker"],"another":true}}},{"do":"draw","n":1,"who":"its_controller"}]]}

**Signature diff:** fx: parser-only [], gef-only ['draw', 'remove']; ev: parser-only [], gef-only ['enters']

## Escape Protocol

**Oracle:** Whenever you cycle a card, you may pay {1}. When you do, exile target artifact or creature you control, then return it to the battlefield under its owner's control.

**Parser (partial):** on cycle: remove an artifact stax piece  [unread part: when you do, … or creature you control, then return it to the ba]

**GEF (today blank, expressed modeled):**
  - triggered {"event":{"on":"cycle","who":"you"},"optional":true} => may_pay {"cost":{"mana":"{1}"},"then":[{"do":"flicker","what":{"ref":"target","filter":{"types":["artifact","creature"],"controller":"you"}},"returns":"immediately"}]}

**Signature diff:** fx: parser-only ['remove'], gef-only []; ev: parser-only ['cycle'], gef-only []

## Feed the Swarm

**Oracle:** Destroy target creature or enchantment an opponent controls. You lose life equal to that permanent's mana value.

**Parser (held):** removal: destroy an opposing creature; held (interaction); can kill tax/lock pieces: creature/enchantment

**GEF (today modeled, expressed modeled):**
  - spell  => remove {"how":"destroy","target":{"ref":"target","filter":{"types":["creature","enchantment"],"controller":"opponent"}}}; lose_life {"n":{"count":"mana_value_of_that"},"who":"you"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Fluctuator

**Oracle:** Cycling abilities you activate cost {2} less to activate.

**Parser (blank):** body only  [unmodeled: Cycling abilities you activate cost {2} less to activate.]

**GEF (today modeled, expressed modeled):**
  - static {"effect":{"static":"cost_reduction","amount":2,"applies_to":"cycling"}}

**Signature diff:** 

## Ghostway

**Oracle:** Exile each creature you control. Return those cards to the battlefield under their owner's control at the beginning of the next end step.

**Parser (held):** held (interaction)  [unmodeled: Exile each creature you control. Return those cards to the battlefield u]

**GEF (today blank, expressed modeled):**
  - spell  => flicker {"what":{"ref":"each","filter":{"types":["creature"],"controller":"you"}},"returns":"next_end_step"}

**Signature diff:** 

## Hall of Heliod's Generosity

**Oracle:** {T}: Add {C}.
{1}{W}, {T}: Put target enchantment card from your graveyard on top of your library.

**Parser (land*):** land C  [unmodeled: {1}{W}, {T}: Put target enchantment card from your graveyard on top of y]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{1}{W}","tap":true}} => recur {"filter":{"types":["enchantment"]},"n":1,"to":"library_top","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['recur']

## Locust Spray

**Oracle:** Target creature gets -1/-1 until end of turn.
Cycling {B} ({B}, Discard this card: Draw a card.)

**Parser (held):** removal: -1/-1 on an opposing creature; held (interaction); can kill tax/lock pieces: creature; cycling {1}: draw 1

**GEF (today modeled, expressed modeled):**
  - spell  => pump {"target":{"ref":"target","filter":{"types":["creature"]}},"power":-1,"toughness":-1,"duration":"end_of_turn"}
  - keyword {"keyword":"cycling","cost":"{B}"}

**Signature diff:** fx: parser-only ['remove'], gef-only ['pump']

## Mistveil Plains

**Oracle:** ({T}: Add {W}.)
This land enters tapped.
{W}, {T}: Put target card from your graveyard on the bottom of your library. Activate only if you control two or more white permanents.

**Parser (land*):** land W; tapped  [unmodeled: {W}, {T}: Put target card from your graveyard on the bottom of your libr]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped"}}
  - activated {"cost":{"mana":"{W}","tap":true},"if":{"if":"control","filter":{"colors":["W"]},"min":2}} => recur {"filter":{"any":true},"n":1,"to":"library_bottom","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['recur']

## Patron Wizard

**Oracle:** Tap an untapped Wizard you control: Counter target spell unless its controller pays {1}.

**Parser (blank):** 2/2  [unmodeled: Tap an untapped Wizard you control: Counter target spell unless its cont]

**GEF (today modeled, expressed modeled):**
  - activated {"cost":{"tap_untapped":{"n":1,"filter":{"subtypes":["Wizard"],"controller":"you"}}}} => counter_spell {"unless_pays":"{1}"}

**Signature diff:** 

## Pest Control

**Oracle:** Destroy all nonland permanents with mana value 1 or less.
Cycling {2} ({2}, Discard this card: Draw a card.)

**Parser (held):** held (interaction); cycling {2}: draw 1  [held wipe (symmetric, never cast): Destroy all nonland permanents with mana value 1 or less.]

**GEF (today held, expressed held):**
  - spell  => wipe {"how":"destroy","filter":{"non_types":["land"],"mana_value":{"max":1}}}
  - keyword {"keyword":"cycling","cost":"{2}"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Prairie Stream

**Oracle:** ({T}: Add {W} or {U}.)
This land enters tapped unless you control two or more basic lands.

**Parser (land*):** land WU; tapped  [conditional enters-tapped read as always tapped]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["land"],"supertypes":["basic"],"controller":"you"},"min":2}}}

**Signature diff:** 

## Requisition Raid

**Oracle:** Spree (Choose one or more additional costs.)
+ {1} — Destroy target artifact.
+ {1} — Destroy target enchantment.
+ {1} — Put a +1/+1 counter on each creature target player controls.

**Parser (held):** remove an artifact stax piece, remove an enchantment stax piece; held (interaction); can kill tax/lock pieces: artifact/enchantment  [keyword not modeled: spree; needs opponents: + {1} — Put a +1/+1 counter on each creature target player controls.]

**GEF (today blank, expressed partial):**
  - keyword {"keyword":"spree"}
  - unexpressible {"reason":"spree mode with its own {1} additional cost, chosen optionally with other modes; GEF has no per-mode cost","scope":"format_gap"}
  - unexpressible {"reason":"spree mode with its own {1} additional cost, chosen optionally with other modes; GEF has no per-mode cost","scope":"format_gap"}
  - unexpressible {"reason":"spree mode with its own {1} additional cost, chosen optionally with other modes; GEF has no per-mode cost","scope":"format_gap"}

**Signature diff:** fx: parser-only ['remove'], gef-only []

## Rule of Law

**Oracle:** Each player can't cast more than one spell each turn.

**Parser (vacuum):** body only  [needs opponents: Each player can't cast more than one spell each turn.]

**GEF (today blank, expressed blank):**
  - static {"effect":{"static":"restriction","who":"each_player","text":"can't cast more than one spell each turn"}}

**Signature diff:** 

## Skycloud Expanse

**Oracle:** {1}, {T}: Add {W}{U}.

**Parser (land*):** land WU; filter 1->2  [mana read from produced_mana]

**GEF (today land, expressed land):**
  - mana {"cost":{"mana":"{1}","tap":true},"produce":{"units":["W","U"]}}

**Signature diff:** 

## Solitary Confinement

**Oracle:** At the beginning of your upkeep, sacrifice this enchantment unless you discard a card.
Skip your draw step.
You have shroud. (You can't be the target of spells or abilities.)
Prevent all damage that would be dealt to you.

**Parser (blank):** body only  [unmodeled: At the beginning of your upkeep, sacrifice ~ unless you discard a card.; unmodeled: Skip your draw step.; unmodeled: Prevent all damage that would be dealt to you.]

**GEF (today partial, expressed partial):**
  - triggered {"event":{"on":"upkeep","whose":"your"}} => may_pay {"cost":{"discard":{"n":1}},"then":[],"else":[{"do":"sacrifice","what":{"ref":"self"}}],"who":"you"}
  - static {"effect":{"static":"restriction","who":"you","text":"Skip your draw step."}}
  - unexpressible {"reason":"only stops opponents from targeting you","scope":"out_of_scope"}
  - unexpressible {"reason":"damage to you is only dealt by opponents","scope":"out_of_scope"}

**Signature diff:** fx: parser-only [], gef-only ['sacrifice']; ev: parser-only [], gef-only ['upkeep']

## Step Through

**Oracle:** Return two target creatures to their owners' hands.
Wizardcycling {2} ({2}, Discard this card: Search your library for a Wizard card, reveal it, put it into your hand, then shuffle.)

**Parser (partial):** wizardcycling {2}: tutor->hand: Wizard  [unmodeled: Return two target creatures to their owners' hands.]

**GEF (today held, expressed held):**
  - spell  => remove {"how":"bounce","target":{"ref":"target","n":2,"filter":{"types":["creature"]}}}
  - keyword {"keyword":"typecycling","cost":"{2}","detail":"Wizard"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Sunken Hollow

**Oracle:** ({T}: Add {U} or {B}.)
This land enters tapped unless you control two or more basic lands.

**Parser (land*):** land UB; tapped  [conditional enters-tapped read as always tapped]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["land"],"supertypes":["basic"],"controller":"you"},"min":2}}}

**Signature diff:** 

## Talisman of Dominance

**Oracle:** {T}: Add {C}.
{T}: Add {U} or {B}. This artifact deals 1 damage to you.

**Parser (modeled):** mana BCU

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["UB"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Talisman of Progress

**Oracle:** {T}: Add {C}.
{T}: Add {W} or {U}. This artifact deals 1 damage to you.

**Parser (modeled):** mana CUW

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["WU"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Vedalken Aethermage

**Oracle:** Flash (You may cast this spell any time you could cast an instant.)
When this creature enters, return target Sliver to its owner's hand.
Wizardcycling {3} ({3}, Discard this card: Search your library for a Wizard card, reveal it, put it into your hand, then shuffle.)

**Parser (partial):** wizardcycling {3}: tutor->hand: Wizard; 1/2  [unmodeled: When ~ enters, return target Sliver to its owner's hand.]

**GEF (today modeled, expressed modeled):**
  - keyword {"keyword":"flash"}
  - triggered {"event":{"on":"enters","subject":"self"}} => remove {"how":"bounce","target":{"ref":"target","filter":{"subtypes":["Sliver"]}}}
  - keyword {"keyword":"typecycling","cost":"{3}","detail":"Wizard"}

**Signature diff:** fx: parser-only [], gef-only ['remove']; ev: parser-only [], gef-only ['enters']

## Wishclaw Talisman

**Oracle:** This artifact enters with three wish counters on it.
{1}, {T}, Remove a wish counter from this artifact: Search your library for a card, put it into your hand, then shuffle. An opponent gains control of this artifact. Activate only during your turn.

**Parser (modeled):** act [T 1 -1 wish]: tutor->hand: any card; enters with 3 wish

**GEF (today partial, expressed partial):**
  - static {"effect":{"static":"enters_with_counters","kind":"wish","n":3}}
  - activated {"cost":{"mana":"{1}","tap":true,"remove_counters":{"kind":"wish","n":1,"from":"self"}},"if":{"if":"your_turn"}} => tutor {"filter":{"any":true},"n":1,"to":"hand"}; unexpressible {"reason":"control of your own permanent passes to an opponent","scope":"format_gap"}

**Signature diff:** 

## Fellwar Stone

**Oracle:** {T}: Add one mana of any color that a land an opponent controls could produce.

**Parser (modeled):** mana BGRUW  [assumes opponents' lands cover your colors]

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"mana color depends on the colors opponents' lands could produce; no construct for it","scope":"format_gap"}

**Signature diff:** fx: parser-only ['mana'], gef-only []

## Cultivate

**Oracle:** Search your library for up to two basic land cards, reveal those cards, put one onto the battlefield tapped and the other into your hand, then shuffle.

**Parser (modeled):** land x2->split

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"one search whose two found cards go to different zones; tutor has one destination","scope":"format_gap"}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Blasphemous Act

**Oracle:** This spell costs {1} less to cast for each creature on the battlefield.
Blasphemous Act deals 13 damage to each creature.

**Parser (held):** held (interaction)  [unmodeled: ~ costs {1} less to cast for each creature on the battlefield.; held wipe (symmetric, never cast): ~ deals 13 damage to each creature.]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"counts creatures controlled by all players; permanents_you_control only counts yours","scope":"format_gap"}
  - spell  => damage {"n":13,"to":"each_creature","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Beast Within

**Oracle:** Destroy target permanent. Its controller creates a 3/3 green Beast creature token.

**Parser (held):** held (interaction); can kill tax/lock pieces: artifact/creature/enchantment  [unmodeled: Destroy target permanent. Its controller creates a 3/3 green Beast creat]

**GEF (today held, expressed held):**
  - spell  => remove {"how":"destroy","target":{"ref":"target","filter":{"types":["permanent"]}},"controller_compensation":"its controller creates a 3/3 green Beast creature token"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Kodama's Reach

**Oracle:** Search your library for up to two basic land cards, reveal those cards, put one onto the battlefield tapped and the other into your hand, then shuffle.

**Parser (modeled):** land x2->split

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"one search whose two found cards go to different zones; tutor has one destination","scope":"format_gap"}

**Signature diff:** fx: parser-only ['tutor'], gef-only []

## Arcane Denial

**Oracle:** Counter target spell. Its controller may draw up to two cards at the beginning of the next turn's upkeep.
You draw a card at the beginning of the next turn's upkeep.

**Parser (held):** draw 1; held (interaction); answers disruption: counter

**GEF (today held, expressed held):**
  - spell  => counter_spell; unexpressible {"reason":"the opponent draws cards","scope":"out_of_scope"}
  - spell  => delayed {"when":"next_upkeep","effects":[{"do":"draw","n":1,"who":"you"}]}

**Signature diff:** fx: parser-only ['draw'], gef-only []

## Reanimate

**Oracle:** Put target creature card from a graveyard onto the battlefield under your control. You lose life equal to that card's mana value.

**Parser (modeled):** recur->bf: creature ~only your own graveyard is modeled; needs a target in your graveyard

**GEF (today modeled, expressed modeled):**
  - spell  => recur {"filter":{"types":["creature"]},"n":1,"to":"battlefield","from":"any_graveyard"}; lose_life {"n":{"count":"mana_value_of_that"},"who":"you"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Generous Gift

**Oracle:** Destroy target permanent. Its controller creates a 3/3 green Elephant creature token.

**Parser (held):** held (interaction); can kill tax/lock pieces: artifact/creature/enchantment  [unmodeled: Destroy target permanent. Its controller creates a 3/3 green Elephant cr]

**GEF (today held, expressed held):**
  - spell  => remove {"how":"destroy","target":{"ref":"target","filter":{"types":["permanent"]}},"controller_compensation":"its controller creates a 3/3 green Elephant creature token"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Toxic Deluge

**Oracle:** As an additional cost to cast this spell, pay X life.
All creatures get -X/-X until end of turn.

**Parser (held):** held (interaction)  [unmodeled: As an additional cost to cast ~, pay X life.; held wipe (symmetric, never cast): All creatures get -X/-X until end of turn.]

**GEF (today held, expressed held):**
  - additional_cost {"cost":{"pay_life":"X"}}
  - spell  => wipe {"how":"minus","filter":{"types":["creature"],"controller":"any"},"amount":"X"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Deflecting Swat

**Oracle:** If you control a commander, you may cast this spell without paying its mana cost.
You may choose new targets for target spell or ability.

**Parser (held):** held (interaction); answers disruption: redirect (free with a commander out)

**GEF (today blank, expressed partial):**
  - alt_cost {"cost":{"mana":"{0}"},"if":{"if":"you_control_commander"}}
  - unexpressible {"reason":"changing targets of a spell or ability has no construct","scope":"format_gap"}

**Signature diff:** 

## Urborg, Tomb of Yawgmoth

**Oracle:** Each land is a Swamp in addition to its other land types.

**Parser (land*):** land B  [unmodeled: Each land is a Swamp in addition to its other land types.; mana read from produced_mana]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"type_grant","filter":{"types":["land"],"controller":"any"},"add_types":["Swamp"]}}

**Signature diff:** fx: parser-only ['mana'], gef-only []

## Boseiju, Who Endures

**Oracle:** {T}: Add {G}.
Channel — {1}{G}, Discard this card: Destroy target artifact, enchantment, or nonbasic land an opponent controls. That player may search their library for a land card with a basic land type, put it onto the battlefield, then shuffle. This ability costs {1} less to activate for each legendary creature you control.

**Parser (land*):** land G  [unmodeled: Channel — {1}{G}, Discard ~: Destroy target artifact, enchantment, or no]

**GEF (today land*, expressed land*):**
  - mana {"cost":{"tap":true},"produce":{"units":["G"]}}
  - activated {"from_zone":"hand","cost":{"mana":"{1}{G}","discard":{"n":1,"filter":{"name":"Boseiju, Who Endures"}}}} => remove {"how":"destroy","target":{"ref":"target","filter":{"controller":"opponent","any_of":[{"types":["artifact"]},{"types":["enchantment"]},{"types":["land"],"supertypes":["nonbasic"]}]}}}; unexpressible {"reason":"the opponent's own library search","scope":"out_of_scope"}; unexpressible {"reason":"no construct for an activated ability's cost reduction by a count","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Yavimaya, Cradle of Growth

**Oracle:** Each land is a Forest in addition to its other land types.

**Parser (land*):** land G  [unmodeled: Each land is a Forest in addition to its other land types.; mana read from produced_mana]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"type_grant","filter":{"types":["land"],"controller":"any"},"add_types":["Forest"]}}

**Signature diff:** fx: parser-only ['mana'], gef-only []

## Esper Sentinel

**Oracle:** Whenever an opponent casts their first noncreature spell each turn, draw a card unless that player pays {X}, where X is this creature's power.

**Parser (modeled):** on opp_cast(noncreature) 1/turn taxed: draw 1; ~opp; 1/1

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"the payment amount is this creature's power, but unless_opponent_pays only takes a fixed mana cost","scope":"format_gap"}

**Signature diff:** fx: parser-only ['draw'], gef-only []; ev: parser-only ['opponent_casts'], gef-only []

## Otawara, Soaring City

**Oracle:** {T}: Add {U}.
Channel — {3}{U}, Discard this card: Return target artifact, creature, enchantment, or planeswalker to its owner's hand. This ability costs {1} less to activate for each legendary creature you control.

**Parser (land*):** land U  [unmodeled: Channel — {3}{U}, Discard ~: Return target artifact, creature, enchantme]

**GEF (today land*, expressed land*):**
  - mana {"cost":{"tap":true},"produce":{"units":["U"]}}
  - activated {"from_zone":"hand","cost":{"mana":"{3}{U}","discard":{"n":1,"filter":{"name":"Otawara, Soaring City"}}}} => remove {"how":"bounce","target":{"ref":"target","filter":{"any_of":[{"types":["artifact"]},{"types":["creature"]},{"types":["enchantment"]},{"types":["planeswalker"]}]}}}; unexpressible {"reason":"no construct for an activated ability's cost reduction by a count","scope":"format_gap"}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Smoldering Marsh

**Oracle:** ({T}: Add {B} or {R}.)
This land enters tapped unless you control two or more basic lands.

**Parser (land*):** land BR; tapped  [conditional enters-tapped read as always tapped]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["land"],"supertypes":["basic"],"controller":"you"},"min":2}}}

**Signature diff:** 

## Frantic Search

**Oracle:** Draw two cards, then discard two cards. Untap up to three lands.

**Parser (modeled):** draw 2, discard 2, untap 3 lands

**GEF (today blank, expressed modeled):**
  - spell  => draw {"n":2}; discard {"n":2}; untap {"what":{"ref":"target","n":3,"up_to":true,"filter":{"types":["land"]}}}

**Signature diff:** fx: parser-only ['discard', 'draw', 'untap'], gef-only []

## Canopy Vista

**Oracle:** ({T}: Add {G} or {W}.)
This land enters tapped unless you control two or more basic lands.

**Parser (land*):** land WG; tapped  [conditional enters-tapped read as always tapped]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["land"],"supertypes":["basic"],"controller":"you"},"min":2}}}

**Signature diff:** 

## Teferi's Protection

**Oracle:** Until your next turn, your life total can't change and you gain protection from everything. All permanents you control phase out. (While they're phased out, they're treated as though they don't exist. They phase in before you untap during your untap step.)
Exile Teferi's Protection.

**Parser (held):** held (interaction); answers disruption: protect  [unmodeled: Exile ~.]

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"locks your own life total and phases out your permanents; GEF has no construct for either","scope":"format_gap"}
  - spell  => unexpressible {"reason":"no construct for exiling the resolving spell itself","scope":"format_gap"}

**Signature diff:** 

## Sakura-Tribe Elder

**Oracle:** Sacrifice this creature: Search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.

**Parser (modeled):** ETB land x1->bf_t (sacrificed); 1/1

**GEF (today modeled, expressed modeled):**
  - activated {"cost":{"sacrifice":"self"}} => tutor {"filter":{"types":["land"],"supertypes":["basic"]},"n":1,"to":"battlefield_tapped"}

**Signature diff:** ev: parser-only ['enters'], gef-only []

## Talisman of Creativity

**Oracle:** {T}: Add {C}.
{T}: Add {U} or {R}. This artifact deals 1 damage to you.

**Parser (modeled):** mana CRU

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["UR"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Talisman of Indulgence

**Oracle:** {T}: Add {C}.
{T}: Add {B} or {R}. This artifact deals 1 damage to you.

**Parser (modeled):** mana BCR

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["BR"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Victimize

**Oracle:** Choose two target creature cards in your graveyard. Sacrifice a creature. If you do, return the chosen cards to the battlefield tapped.

**Parser (modeled):** sacrifice creature -> recur->bf: 2x creature; needs a target in your graveyard

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"return of two chosen targets is conditional on a mandatory sacrifice being performed","scope":"format_gap"}

**Signature diff:** fx: parser-only ['recur'], gef-only []

## Roaming Throne

**Oracle:** Ward {2}
As this creature enters, choose a creature type.
This creature is the chosen type in addition to its other types.
If a triggered ability of another creature you control of the chosen type triggers, it triggers an additional time.

**Parser (modeled):** another Chosen creature abilities trigger twice; 4/4

**GEF (today partial, expressed partial):**
  - keyword {"keyword":"ward","cost":"{2}"}
  - unexpressible {"reason":"choosing a creature type as it enters has no construct","scope":"format_gap"}
  - unexpressible {"reason":"adds the chosen type to itself; no construct for a chosen-type grant to self","scope":"format_gap"}
  - static {"effect":{"static":"trigger_doubler","cause":"any","filter":{"types":["creature"],"controller":"you","another":true,"chosen_type":true}}}

**Signature diff:** 

## Talisman of Hierarchy

**Oracle:** {T}: Add {C}.
{T}: Add {W} or {B}. This artifact deals 1 damage to you.

**Parser (modeled):** mana BCW

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["WB"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Big Score

**Oracle:** As an additional cost to cast this spell, discard a card.
Draw two cards and create two Treasure tokens. (They're artifacts with "{T}, Sacrifice this token: Add one mana of any color.")

**Parser (modeled):** discard 1, draw 2, treasure 2

**GEF (today modeled, expressed modeled):**
  - additional_cost {"cost":{"discard":{"n":1}}}
  - spell  => draw {"n":2}; token {"n":2,"token":{"preset":"treasure"}}

**Signature diff:** fx: parser-only ['discard'], gef-only []

## Abrade

**Oracle:** Choose one —
• Abrade deals 3 damage to target creature.
• Destroy target artifact.

**Parser (held):** removal: 3 damage to an opposing creature; held (interaction); can kill tax/lock pieces: artifact/creature

**GEF (today modeled, expressed modeled):**
  - spell  => choose {"n":1,"modes":[[{"do":"damage","n":3,"to":"target_creature","source":"self"}],[{"do":"remove","how":"destroy","target":{"ref":"target","filter":{"types":["artifact"]}}}]]}

**Signature diff:** 

## Ponder

**Oracle:** Look at the top three cards of your library, then put them back in any order. You may shuffle.
Draw a card.

**Parser (modeled):** arrange top 3, draw 1

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"reordering the top three cards and optionally shuffling has no construct","scope":"format_gap"}
  - spell  => draw {"n":1}

**Signature diff:** fx: parser-only ['look'], gef-only []

## Delighted Halfling

**Oracle:** {T}: Add {C}.
{T}: Add one mana of any color. Spend this mana only to cast a legendary spell, and that spell can't be countered.

**Parser (modeled):** mana BCGRUW (restricted); 1/2

**GEF (today partial, expressed partial):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - unexpressible {"reason":"the spell made with this mana becomes uncounterable; no construct for that rider","scope":"format_gap"}

**Signature diff:** 

## Mana Vault

**Oracle:** This artifact doesn't untap during your untap step.
At the beginning of your upkeep, you may pay {4}. If you do, untap this artifact.
At the beginning of your draw step, if this artifact is tapped, it deals 1 damage to you.
{T}: Add {C}{C}{C}.

**Parser (modeled):** mana C+C+C; on upkeep: pay 4: untap ~; on drawstep: if ~ is tapped: you lose 1 life; doesn't untap (spent last)

**GEF (today partial, expressed modeled):**
  - static {"effect":{"static":"doesnt_untap"}}
  - triggered {"event":{"on":"upkeep","whose":"your"}} => may_pay {"cost":{"mana":"{4}"},"then":[{"do":"untap","what":{"ref":"self"}}]}
  - triggered {"event":{"on":"draw_step","whose":"your"},"if":{"if":"self_tapped"}} => damage {"n":1,"to":"you","source":"self"}
  - mana {"cost":{"tap":true},"produce":{"units":["C","C","C"]}}

**Signature diff:** fx: parser-only ['untap'], gef-only []; ev: parser-only ['upkeep'], gef-only []

## Talisman of Conviction

**Oracle:** {T}: Add {C}.
{T}: Add {R} or {W}. This artifact deals 1 damage to you.

**Parser (modeled):** mana CRW

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"tap":true}} => mana {"produce":{"units":["RW"]}}; damage {"n":1,"to":"you","source":"self"}

**Signature diff:** fx: parser-only [], gef-only ['lose_life']

## Herald's Horn

**Oracle:** As this artifact enters, choose a creature type.
Creature spells you cast of the chosen type cost {1} less to cast.
At the beginning of your upkeep, look at the top card of your library. If it's a creature card of the chosen type, you may reveal it and put it into your hand.

**Parser (modeled):** on upkeep: take the top card if Chosen creature; reduce {1}: Creature Chosen

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"choosing a creature type as it enters has no construct","scope":"format_gap"}
  - static {"effect":{"static":"cost_reduction","spells":{"types":["creature"],"chosen_type":true},"amount":1}}
  - triggered {"event":{"on":"upkeep","whose":"your"},"optional":true} => look {"n":1,"take":1,"filter":{"types":["creature"],"chosen_type":true},"to":"hand","reveal":true,"rest":"top","from":"library"}

**Signature diff:** 

## Chrome Mox

**Oracle:** Imprint — When this artifact enters, you may exile a nonartifact, nonland card from your hand.
{T}: Add one mana of any of the exiled card's colors.

**Parser (modeled):** imprint: mana of the exiled card's colors

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"imprint: exiles a card and remembers it; no construct for remembering the exiled card","scope":"format_gap"}
  - unexpressible {"reason":"mana colors depend on the imprinted card","scope":"format_gap"}

**Signature diff:** 

## Anguished Unmaking

**Oracle:** Exile target nonland permanent. You lose 3 life.

**Parser (held):** removal: exile an opposing creature, you lose 3 life; held (interaction); can kill tax/lock pieces: artifact/creature/enchantment

**GEF (today modeled, expressed modeled):**
  - spell  => remove {"how":"exile","target":{"ref":"target","filter":{"types":["permanent"],"non_types":["land"]}}}; lose_life {"n":3,"who":"you"}

**Signature diff:** 

## Lightning Bolt

**Oracle:** Lightning Bolt deals 3 damage to any target.

**Parser (held):** an opponent loses 3; can burn a blocker (3 damage); held (interaction); can kill tax/lock pieces: creature

**GEF (today modeled, expressed modeled):**
  - spell  => damage {"n":3,"to":"any_target","source":"self"}

**Signature diff:** 

## Windfall

**Oracle:** Each player discards their hand, then draws cards equal to the greatest number of cards a player discarded this way.

**Parser (modeled):** wheel max ~opp

**GEF (today partial, expressed partial):**
  - spell  => discard {"n":"hand","who":"each_player"}; unexpressible {"reason":"greatest number of cards any player discarded has no count key","scope":"format_gap"}

**Signature diff:** fx: parser-only ['wheel'], gef-only ['discard']

## Sink into Stupor // Soporific Springs

**Oracle:** Return target spell or nonland permanent an opponent controls to its owner's hand. // As this land enters, you may pay 3 life. If you don't, it enters tapped.
{T}: Add {U}.

**Parser (held):** held (interaction); can kill tax/lock pieces: artifact/creature/enchantment; MDFC land back  [needs opponents: Return target spell or nonland permanent an opponent controls to its own]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"a single target that may be a spell or a permanent; remove.bounce targets only permanents","scope":"format_gap"}
  - static {"effect":{"static":"replacement","text":"As this land enters, you may pay 3 life. If you don't, it enters tapped.","kind":"other"}}
  - mana {"cost":{"tap":true},"produce":{"units":["U"]}}

**Signature diff:** fx: parser-only [], gef-only ['mana']

## Austere Command

**Oracle:** Choose two —
• Destroy all artifacts.
• Destroy all enchantments.
• Destroy all creatures with mana value 3 or less.
• Destroy all creatures with mana value 4 or greater.

**Parser (held):** held (interaction)  [unmodeled modes: Destroy all artifacts. / Destroy all enchantments. / Destroy all creatur]

**GEF (today held, expressed held):**
  - spell  => choose {"n":2,"modes":[[{"do":"wipe","how":"destroy","filter":{"types":["artifact"]}}],[{"do":"wipe","how":"destroy","filter":{"types":["enchantment"]}}],[{"do":"wipe","how":"destroy","filter":{"types":["creature"],"mana_value":{"max":3}}}],[{"do":"wipe","how":"destroy","filter":{"types":["creature"],"mana_value":{"min":4}}}]]}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Mystic Sanctuary

**Oracle:** ({T}: Add {U}.)
This land enters tapped unless you control three or more other Islands.
When this land enters untapped, you may put target instant or sorcery card from your graveyard on top of your library.

**Parser (land*):** land U; tapped  [conditional enters-tapped read as always tapped; unmodeled: When ~ enters untapped, you may put target instant or sorcery card from ]

**GEF (today land, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"subtypes":["Island"],"controller":"you","another":true},"min":3}}}
  - triggered {"event":{"on":"enters","subject":"self"},"if":{"if":"control","filter":{"subtypes":["Island"],"controller":"you","another":true},"min":3},"optional":true} => recur {"filter":{"types":["instant","sorcery"]},"n":1,"to":"library_top","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['recur']; ev: parser-only [], gef-only ['enters']

## Farewell

**Oracle:** Choose one or more —
• Exile all artifacts.
• Exile all creatures.
• Exile all enchantments.
• Exile all graveyards.

**Parser (held):** held (interaction)  [unmodeled modes: Exile all artifacts. / Exile all creatures. / Exile all enchantments. / ]

**GEF (today held, expressed held):**
  - spell  => choose {"n":4,"up_to":true,"modes":[[{"do":"wipe","how":"exile","filter":{"types":["artifact"]}}],[{"do":"wipe","how":"exile","filter":{"types":["creature"]}}],[{"do":"wipe","how":"exile","filter":{"types":["enchantment"]}}],[{"do":"unexpressible","text":"Exile all graveyards.","reason":"exiling every player's graveyard cards has no construct","scope":"format_gap"}]]}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## Flawless Maneuver

**Oracle:** If you control a commander, you may cast this spell without paying its mana cost.
Creatures you control gain indestructible until end of turn.

**Parser (held):** pump team indestructible EOT; held (interaction); answers disruption: protect (free with a commander out); pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage

**GEF (today partial, expressed modeled):**
  - alt_cost {"cost":{"mana":"{0}"},"if":{"if":"you_control_commander"}}
  - spell  => pump_team {"filter":{"types":["creature"],"controller":"you"},"keywords":["indestructible"],"duration":"end_of_turn"}

**Signature diff:** 

## Gemstone Caverns

**Oracle:** If this card is in your opening hand and you're not the starting player, you may begin the game with Gemstone Caverns on the battlefield with a luck counter on it. If you do, exile a card from your hand.
{T}: Add {C}. If Gemstone Caverns has a luck counter on it, instead add one mana of any color.

**Parser (land*):** land C  [unmodeled: If ~ is in your opening hand and you're not the starting player, you may]

**GEF (today land*, expressed land*):**
  - unexpressible {"reason":"opening-hand start-of-game action","scope":"format_gap"}
  - unexpressible {"reason":"mana ability with a replacement depending on a luck counter","scope":"format_gap"}

**Signature diff:** fx: parser-only ['mana'], gef-only []

## Boros Charm

**Oracle:** Choose one —
• Boros Charm deals 4 damage to target player or planeswalker.
• Permanents you control gain indestructible until end of turn.
• Target creature gains double strike until end of turn.

**Parser (held):** an opponent loses 4; held (interaction); answers disruption: protect

**GEF (today partial, expressed partial):**
  - spell  => choose {"n":1,"modes":[[{"do":"unexpressible","text":"Boros Charm deals 4 damage to target player or planeswalker.","reason":"damage target 'player or planeswalker' has no exact construct","scope":"format_gap"}],[{"do":"pump_team","filter":{"types":["permanent"],"controller":"you"},"keywords":["indestructible"],"duration":"end_of_turn"}],[{"do":"pump","target":{"ref":"target","filter":{"types":["creature"]}},"keywords":["double strike"],"duration":"end_of_turn"}]]}

**Signature diff:** fx: parser-only ['drain'], gef-only ['pump', 'pump_team']

## Hardened Scales

**Oracle:** If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.

**Parser (modeled):** ctr_plus

**GEF (today blank, expressed blank):**
  - static {"effect":{"static":"replacement","text":"If one or more +1/+1 counters would be put on a creature you control, that many plus one +1/+1 counters are put on it instead.","kind":"counters"}}

**Signature diff:** 

## Akroma's Will

**Oracle:** Choose one. If you control a commander as you cast this spell, you may choose both instead.
• Creatures you control gain flying, vigilance, and double strike until end of turn.
• Creatures you control gain lifelink, indestructible, and protection from each color until end of turn.

**Parser (held):** pump team double strike,flying,vigilance EOT, pump team indestructible,lifelink EOT; held (interaction); answers disruption: protect; pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage

**GEF (today blank, expressed modeled):**
  - spell  => if {"cond":{"if":"you_control_commander"},"then":[{"do":"choose","n":2,"up_to":true,"modes":[[{"do":"pump_team","filter":{"types":["creature"],"controller":"you"},"keywords":["flying","vigilance","double strike"],"duration":"end_of_turn"}],[{"do":"pump_team","filter":{"types":["creature"],"controller":"you"},"keywords":["lifelink","indestructible","protection from each color"],"duration":"end_of_turn"}]]}],"else":[{"do":"choose","n":1,"modes":[[{"do":"pump_team","filter":{"types":["creature"],"controller":"you"},"keywords":["flying","vigilance","double strike"],"duration":"end_of_turn"}],[{"do":"pump_team","filter":{"types":["creature"],"controller":"you"},"keywords":["lifelink","indestructible","protection from each color"],"duration":"end_of_turn"}]]}]}

**Signature diff:** fx: parser-only ['pump_team'], gef-only []

## Idol of Oblivion

**Oracle:** {T}: Draw a card. Activate only if you created a token this turn.
{8}, {T}, Sacrifice this artifact: Create a 10/10 colorless Eldrazi creature token.

**Parser (modeled):** act [T]: draw 1; act [T 8 sac]: token 1x Eldrazi 10/10

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"activation restriction on having created a token this turn has no condition","scope":"format_gap"}
  - activated {"cost":{"mana":"{8}","tap":true,"sacrifice":"self"}} => token {"n":1,"token":{"types":["creature"],"subtypes":["Eldrazi"],"power":10,"toughness":10}}

**Signature diff:** fx: parser-only ['draw'], gef-only []

## Cabal Coffers

**Oracle:** {2}, {T}: Add {B} for each Swamp you control.

**Parser (land*):** land B; filter 2->1  [mana read from produced_mana]

**GEF (today land, expressed land):**
  - mana {"cost":{"mana":"{2}","tap":true},"produce":{"units":["B"],"amount":{"count":"permanents_you_control","filter":{"subtypes":["Swamp"]}}}}

**Signature diff:** 

## Storm-Kiln Artist

**Oracle:** This creature gets +1/+0 for each artifact you control.
Magecraft — Whenever you cast or copy an instant or sorcery spell, create a Treasure token. (It's an artifact with "{T}, Sacrifice this token: Add one mana of any color.")

**Parser (modeled):** on cast(instant,sorcery): treasure 1; anthem ~ +1 per artifacts/+0 per artifacts; 2/2

**GEF (today partial, expressed modeled):**
  - static {"effect":{"static":"pt_equals","power":{"count":"permanents_you_control","filter":{"types":["artifact"]},"plus":2},"toughness":2}}
  - triggered {"event":{"on":"cast","who":"you","spell":{"types":["instant","sorcery"]}}} => token {"n":1,"token":{"preset":"treasure"}}
  - triggered {"event":{"on":"spell_copied","who":"you","spell":{"types":["instant","sorcery"]}}} => token {"n":1,"token":{"preset":"treasure"}}

**Signature diff:** 

## Fell the Profane // Fell Mire

**Oracle:** Destroy target creature or planeswalker. // As this land enters, you may pay 3 life. If you don't, it enters tapped.
{T}: Add {B}.

**Parser (held):** removal: destroy an opposing creature; held (interaction); can kill tax/lock pieces: creature; MDFC land back

**GEF (today held, expressed held):**
  - spell  => remove {"how":"destroy","target":{"ref":"target","filter":{"types":["creature","planeswalker"]}}}
  - unexpressible {"reason":"optional life payment on entering, else tapped","scope":"format_gap"}
  - mana {"cost":{"tap":true},"produce":{"units":["B"]}}

**Signature diff:** fx: parser-only [], gef-only ['mana']

## Patchwork Banner

**Oracle:** As this artifact enters, choose a creature type.
Creatures you control of the chosen type get +1/+1.
{T}: Add one mana of any color.

**Parser (modeled):** mana BGRUW; anthem Chosen creatures +1/+1

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"choosing a creature type as it enters has no construct","scope":"format_gap"}
  - static {"effect":{"static":"anthem","filter":{"types":["creature"],"controller":"you","chosen_type":true},"power":1,"toughness":1}}
  - mana {"cost":{"tap":true},"produce":{"units":["any"]}}

**Signature diff:** 

## Mox Amber

**Oracle:** {T}: Add one mana of any color among legendary creatures and planeswalkers you control.

**Parser (modeled):** mana BGRUW  ['any color among' approximated as any color]

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"mana colors depend on the colors among legendary creatures and planeswalkers you control; no construct","scope":"format_gap"}

**Signature diff:** fx: parser-only ['mana'], gef-only []
