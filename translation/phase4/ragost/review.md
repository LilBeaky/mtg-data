# T2 review sheet: GEF translation vs regex parser

## Ragost, Deft Gastronaut

**Oracle:** Artifacts you control are Foods in addition to their other types and have "{2}, {T}, Sacrifice this artifact: You gain 3 life."
{1}, {T}, Sacrifice a Food: Ragost deals 3 damage to each opponent.
At the beginning of each end step, if you gained life this turn, untap Ragost.

**Parser (modeled):** on end +opp turns: if you gained life this turn: untap ~; act [T 1 sac Food]: each opponent loses 3; artifacts you control are also Food; they have act [T 2 sac]: you gain 3 life; 2/2

**GEF (today partial, expressed modeled):**
  - static {"effect":{"static":"type_grant","filter":{"types":["artifact"],"controller":"you"},"add_types":["Food"],"abilities":[{"kind":"activated","text":"{2}, {T}, Sacrifice this artifact: You gain 3 life.","cost":{"mana":"{2}","tap":true,"sacrifice":"self"},"effects":[{"do":"gain_life","n":3}]}]}}
  - activated {"cost":{"mana":"{1}","tap":true,"sacrifice":{"filter":{"subtypes":["Food"]},"n":1}}} => damage {"n":3,"to":"each_opponent","source":"self"}
  - triggered {"event":{"on":"end_step","whose":"each"},"if":{"if":"gained_life_this_turn"}} => untap {"what":{"ref":"self"}}

**Signature diff:** fx: parser-only ['untap'], gef-only []; ev: parser-only ['end_step'], gef-only []

## Academy Manufactor

**Oracle:** If you would create a Clue, Food, or Treasure token, instead create one of each.

**Parser (modeled):** a Clue, Food or Treasure token -> one of each; 1/3

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"replaces creating one of those tokens with creating one each of Clue, Food and Treasure; token_doubler can only multiply the count of the same token","scope":"format_gap"}

**Signature diff:** 

## Bender's Waterskin

**Oracle:** Untap this artifact during each other player's untap step.
{T}: Add one mana of any color.

**Parser (modeled):** mana BGRUW  [needs opponents: Untap ~ during each other player's untap step.]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"untaps my permanent in other players' untap steps; no construct or event says an untap-step effect","scope":"format_gap"}
  - mana {"cost":{"tap":true},"produce":{"units":["any"]}}

**Signature diff:** 

## Fateful Showdown

**Oracle:** Fateful Showdown deals damage to any target equal to the number of cards in your hand. Discard all the cards in your hand, then draw that many cards.

**Parser (partial):** an opponent loses per hand  [unread part: discard all the cards in your hand, then draw that many cards.]

**GEF (today modeled, expressed modeled):**
  - spell  => damage {"n":{"count":"cards_in_hand"},"to":"any_target","source":"self"}; discard {"n":"hand"}; draw {"n":{"count":"that_much"}}

**Signature diff:** fx: parser-only [], gef-only ['discard', 'draw']

## Humble Defector

**Oracle:** {T}: Draw two cards. Target opponent gains control of this creature. Activate only during your turn.

**Parser (modeled):** act [T]: draw 2; 2/1

**GEF (today partial, expressed partial):**
  - activated {"cost":{"tap":true},"if":{"if":"your_turn"}} => draw {"n":2}; unexpressible {"reason":"hands my creature to an opponent; gain_control only takes control for me","scope":"format_gap"}

**Signature diff:** 

## Ichor Wellspring

**Oracle:** When this artifact enters or is put into a graveyard from the battlefield, draw a card.

**Parser (modeled):** ETB draw 1; on gy_self: draw 1

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"}} => draw {"n":1}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"}} => draw {"n":1}

**Signature diff:** ev: parser-only ['dies'], gef-only ['put_into_graveyard']

## Ishgard, the Holy See // Faith & Grief

**Oracle:** This land enters tapped.
{T}: Add {W}. // Return up to two target artifact and/or enchantment cards from your graveyard to your hand. (Then exile this card. You may play the land later from exile.)

**Parser (land):** land W; tapped

**GEF (today modeled, expressed modeled):**
  - static {"effect":{"static":"enters_tapped"}}
  - mana {"cost":{"tap":true},"produce":{"units":["W"]}}
  - spell  => recur {"filter":{"types":["artifact","enchantment"]},"n":2,"to":"hand","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['recur']

## Lembas

**Oracle:** When this artifact enters, scry 1, then draw a card.
{2}, {T}, Sacrifice this artifact: You gain 3 life.
When this artifact is put into a graveyard from the battlefield, its owner shuffles it into their library.

**Parser (partial):** ETB scry 1, draw 1; act [T 2 sac]: you gain 3 life  [unmodeled: When ~ is put into a graveyard from the battlefield, its owner shuffles ]

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"}} => scry {"n":1}; draw {"n":1}
  - activated {"cost":{"mana":"{2}","tap":true,"sacrifice":"self"}} => gain_life {"n":3}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"}} => self_to_library {"where":"shuffle"}

**Signature diff:** fx: parser-only [], gef-only ['self_to_library']; ev: parser-only [], gef-only ['put_into_graveyard']

## Mines of Moria

**Oracle:** Mines of Moria enters tapped unless you control a legendary creature.
{T}: Add {R}.
{3}{R}, {T}, Exile three cards from your graveyard: Create two Treasure tokens.

**Parser (land*):** land R; tapped  [conditional enters-tapped read as always tapped; unmodeled: {3}{R}, {T}, Exile three cards from your graveyard: Create two Treasure ]

**GEF (today land*, expressed land):**
  - static {"effect":{"static":"enters_tapped","unless":{"if":"control","filter":{"types":["creature"],"supertypes":["legendary"],"controller":"you"}}}}
  - mana {"cost":{"tap":true},"produce":{"units":["R"]}}
  - activated {"cost":{"mana":"{3}{R}","tap":true,"exile_from_graveyard":{"n":3}}} => token {"n":2,"token":{"preset":"treasure"}}

**Signature diff:** fx: parser-only [], gef-only ['token']

## Molten Psyche

**Oracle:** Each player shuffles the cards from their hand into their library, then draws that many cards.
Metalcraft — If you control three or more artifacts, Molten Psyche deals damage to each opponent equal to the number of cards that player has drawn this turn.

**Parser (blank):** body only  [needs opponents: Each player shuffles the cards from their hand into their library, then ; unmodeled: Metalcraft — If you control three or more artifacts, ~ deals damage to e]

**GEF (today held, expressed held):**
  - unexpressible {"reason":"shuffles each hand into its library (wheel discards the hand instead) and draws as many as were shuffled in; no construct says it","scope":"format_gap"}
  - spell  => if {"cond":{"if":"control","filter":{"types":["artifact"],"controller":"you"},"min":3},"then":[{"do":"unexpressible","text":"Molten Psyche deals damage to each opponent equal to the number of cards that player has drawn this turn","reason":"the amount is the number of cards each opponent has drawn this turn, and cards_drawn_this_turn counts only mine","scope":"format_gap"}]}

**Signature diff:** 

## Mycosynth Wellspring

**Oracle:** When this artifact enters or is put into a graveyard from the battlefield, you may search your library for a basic land card, reveal it, put it into your hand, then shuffle.

**Parser (modeled):** ETB land x1->hand; on gy_self: land x1->hand

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"},"optional":true} => tutor {"filter":{"types":["land"],"supertypes":["basic"]},"n":1,"to":"hand","reveal":true}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"},"optional":true} => tutor {"filter":{"types":["land"],"supertypes":["basic"]},"n":1,"to":"hand","reveal":true}

**Signature diff:** ev: parser-only ['dies'], gef-only ['put_into_graveyard']

## Needleverge Pathway // Pillarverge Pathway

**Oracle:** {T}: Add {R}. // {T}: Add {W}.

**Parser (land):** land R

**GEF (today modeled, expressed modeled):**
  - mana {"cost":{"tap":true},"produce":{"units":["R"]}}
  - mana {"cost":{"tap":true},"produce":{"units":["W"]}}

**Signature diff:** 

## Prized Statue

**Oracle:** When this artifact enters or is put into a graveyard from the battlefield, create a Treasure token. (It's an artifact with "{T}, Sacrifice this token: Add one mana of any color.")

**Parser (modeled):** ETB treasure 1; on gy_self: treasure 1

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"}} => token {"n":1,"token":{"preset":"treasure"}}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"}} => token {"n":1,"token":{"preset":"treasure"}}

**Signature diff:** ev: parser-only ['dies'], gef-only ['put_into_graveyard']

## Ratchet, Field Medic // Ratchet, Rescue Racer

**Oracle:** More Than Meets the Eye {1}{W} (You may cast this card converted for {1}{W}.)
Lifelink
Whenever you gain life, you may convert Ratchet. When you do, return target artifact card with mana value less than or equal to the amount of life you gained this turn from your graveyard to the battlefield tapped. // Living metal (During your turn, this Vehicle is also a creature.)
Lifelink
Whenever one or more nontoken artifacts you control are put into a graveyard from the battlefield, convert Ratchet. This ability triggers only once each turn.

**Parser (partial):** on gain: recur->bf: artifact ~mana value less than or equal to the amount of life you gained this turn; 2/4 lifelink  [keyword not modeled: more than meets the eye]

**GEF (today partial, expressed partial):**
  - unexpressible {"reason":"keyword not in the vocabulary: lets you cast this card converted (as its back face) for {1}{W}","scope":"format_gap"}
  - keyword {"keyword":"lifelink"}
  - triggered {"event":{"on":"gain_life","who":"you"},"optional":true} => unexpressible {"reason":"no effect converts (transforms) a permanent, and a mana_value filter can't be bounded by the life gained this turn","scope":"format_gap"}
  - unexpressible {"reason":"keyword not in the vocabulary: during your turn this Vehicle is also a creature","scope":"format_gap"}
  - keyword {"keyword":"lifelink"}
  - triggered {"event":{"on":"put_into_graveyard","subject":{"types":["artifact"],"nontoken":true,"controller":"you"},"one_or_more":true},"once_per_turn":true} => unexpressible {"reason":"no effect converts (transforms) a permanent","scope":"format_gap"}

**Signature diff:** fx: parser-only ['recur'], gef-only []; ev: parser-only ['gain_life'], gef-only []

## Roadside Reliquary

**Oracle:** {T}: Add {C}.
{2}, {T}, Sacrifice this land: Draw a card if you control an artifact. Draw a card if you control an enchantment.

**Parser (land*):** land C; act [T 2 sac]: draw 1, draw 1  [unread part: … if you control an artifact.]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{2}","tap":true,"sacrifice":"self"}} => if {"cond":{"if":"control","filter":{"types":["artifact"],"controller":"you"}},"then":[{"do":"draw","n":1}]}; if {"cond":{"if":"control","filter":{"types":["enchantment"],"controller":"you"}},"then":[{"do":"draw","n":1}]}

**Signature diff:** 

## Scourge of the Nobilis

**Oracle:** Enchant creature
As long as enchanted creature is red, it gets +1/+1 and has "{R/W}: This creature gets +1/+0 until end of turn."
As long as enchanted creature is white, it gets +1/+1 and has lifelink. (Damage dealt by the creature also causes its controller to gain that much life.)

**Parser (partial):** needs a creature; enchanted creature +0/+0; if it's W: +1/+1 lifelink  [unmodeled: As long as enchanted creature is red, it gets +1/+1 and has "{R/W}: ~ ge]

**GEF (today blank, expressed blank):**
  - keyword {"keyword":"enchant","detail":"creature"}
  - unexpressible {"reason":"the bonus and granted ability apply only while the enchanted creature is red; no condition can test the enchanted creature's color","scope":"format_gap"}
  - unexpressible {"reason":"the bonus and lifelink apply only while the enchanted creature is white; no condition can test the enchanted creature's color","scope":"format_gap"}

**Signature diff:** 

## Servo Schematic

**Oracle:** When this artifact enters or is put into a graveyard from the battlefield, create a 1/1 colorless Servo artifact creature token.

**Parser (modeled):** ETB token 1x Servo 1/1 artifact; on gy_self: token 1x Servo 1/1 artifact

**GEF (today modeled, expressed modeled):**
  - triggered {"event":{"on":"enters","subject":"self"}} => token {"n":1,"token":{"preset":"servo"}}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"}} => token {"n":1,"token":{"preset":"servo"}}

**Signature diff:** ev: parser-only ['dies'], gef-only ['put_into_graveyard']

## Spirit Loop

**Oracle:** Enchant creature you control
Whenever enchanted creature deals damage, you gain that much life.
When this Aura is put into a graveyard from the battlefield, return it to its owner's hand.

**Parser (modeled):** on dmg_att: you gain life equal to the damage; on gy_self: return ~ to hand; needs a creature

**GEF (today modeled, expressed modeled):**
  - keyword {"keyword":"enchant","detail":"creature you control"}
  - triggered {"event":{"on":"deals_damage","subject":"enchanted"}} => gain_life {"n":{"count":"that_much"},"who":"you"}
  - triggered {"event":{"on":"put_into_graveyard","subject":"self"}} => recur {"filter":{"same_name_as_self":true},"n":1,"to":"hand","from":"your_graveyard"}

**Signature diff:** ev: parser-only ['dies'], gef-only ['put_into_graveyard']

## Stridehangar Automaton

**Oracle:** Thopters you control get +1/+1.
If one or more artifact tokens would be created under your control, those tokens plus an additional 1/1 colorless Thopter artifact creature token with flying are created instead.

**Parser (modeled):** anthem Thopter creatures +1/+1; artifact tokens: +1 Thopter 1/1 flying each time; 1/4

**GEF (today partial, expressed partial):**
  - static {"effect":{"static":"anthem","filter":{"subtypes":["Thopter"],"controller":"you"},"power":1,"toughness":1}}
  - unexpressible {"reason":"a replacement effect that adds an extra Thopter whenever artifact tokens would be created; token_doubler only multiplies","scope":"format_gap"}

**Signature diff:** 

## Test of Endurance

**Oracle:** At the beginning of your upkeep, if you have 50 or more life, you win the game.

**Parser (modeled):** on upkeep: if you have 50+ life: you win the game

**GEF (today blank, expressed modeled):**
  - triggered {"event":{"on":"upkeep","whose":"your"},"if":{"if":"life_at_least","n":50}} => win_game

**Signature diff:** fx: parser-only ['win_game'], gef-only []; ev: parser-only ['upkeep'], gef-only []

## The Battle of Bywater

**Oracle:** Destroy all creatures with power 3 or greater. Then create a Food token for each creature you control. (It's an artifact with "{2}, {T}, Sacrifice this token: You gain 3 life.")

**Parser (held):** token (per creatures)x Food; held (interaction)

**GEF (today modeled, expressed modeled):**
  - spell  => wipe {"how":"destroy","filter":{"types":["creature"],"power":{"min":3}}}; token {"n":{"count":"permanents_you_control","filter":{"types":["creature"]}},"token":{"preset":"food"}}

**Signature diff:** fx: parser-only [], gef-only ['remove']

## The Underworld Cookbook

**Oracle:** {T}, Discard a card: Create a Food token. (It's an artifact with "{2}, {T}, Sacrifice this token: You gain 3 life.")
{4}, {T}, Sacrifice this artifact: Return target creature card from your graveyard to your hand.

**Parser (partial):** act [T 4 sac]: recur->hand: creature  [unmodeled: {T}, Discard a card: Create a Food token.]

**GEF (today modeled, expressed modeled):**
  - activated {"cost":{"tap":true,"discard":{"n":1}}} => token {"n":1,"token":{"preset":"food"}}
  - activated {"cost":{"mana":"{4}","tap":true,"sacrifice":"self"}} => recur {"filter":{"types":["creature"]},"n":1,"to":"hand","from":"your_graveyard"}

**Signature diff:** fx: parser-only [], gef-only ['token']

## Thopter Assembly

**Oracle:** Flying
At the beginning of your upkeep, if you control no Thopters other than this creature, return this creature to its owner's hand and create five 1/1 colorless Thopter artifact creature tokens with flying.

**Parser (partial):** 5/5 flying  [conditional trigger (intervening 'if') not modeled; unmodeled: At the beginning of your upkeep, if you control no Thopters other than ~]

**GEF (today modeled, expressed modeled):**
  - keyword {"keyword":"flying"}
  - triggered {"event":{"on":"upkeep","whose":"your"},"if":{"if":"control","filter":{"subtypes":["Thopter"],"controller":"you","another":true},"max":0}} => bounce_self; token {"n":5,"token":{"preset":"thopter"}}

**Signature diff:** fx: parser-only [], gef-only ['bounce_self', 'token']; ev: parser-only [], gef-only ['upkeep']

## Toggo, Goblin Weaponsmith

**Oracle:** Landfall — Whenever a land you control enters, create a colorless Equipment artifact token named Rock with "Equipped creature has '{1}, {T}, Sacrifice Rock: This creature deals 2 damage to any target'" and equip {1}.
Partner (You can have two commanders if both have partner.)

**Parser (modeled):** on landfall: token 1x Rock (has an ability); 2/2

**GEF (today partial, expressed partial):**
  - triggered {"event":{"on":"enters","subject":{"types":["land"],"controller":"you"}}} => token {"n":1,"token":{"name":"Rock","types":["artifact"],"subtypes":["Equipment"],"abilities":[{"kind":"keyword","text":"equip {1}","keyword":"equip","cost":"{1}"}]}}; unexpressible {"reason":"the granted ability sacrifices the Equipment that grants it, which a Cost can't name (sacrifice takes only self or a filter)","scope":"format_gap"}
  - keyword {"keyword":"partner"}

**Signature diff:** 

## Treasure Vault

**Oracle:** {T}: Add {C}.
{X}{X}, {T}, Sacrifice this land: Create X Treasure tokens.

**Parser (land*):** land C  [unread (audit): X has no value here (only a {X} mana cost gives the spell and its ETB one)]

**GEF (today land, expressed land):**
  - mana {"cost":{"tap":true},"produce":{"units":["C"]}}
  - activated {"cost":{"mana":"{X}{X}","tap":true,"sacrifice":"self"}} => token {"n":"X","token":{"preset":"treasure"}}

**Signature diff:** fx: parser-only [], gef-only ['token']

## Wake the Past

**Oracle:** Return all artifact cards from your graveyard to the battlefield. They gain haste until end of turn.

**Parser (modeled):** recur->bf: 7x artifact, pump attackers haste EOT; needs a target in your graveyard; pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage

**GEF (today partial, expressed partial):**
  - spell  => recur {"filter":{"types":["artifact"]},"n":"all","to":"battlefield","from":"your_graveyard"}; unexpressible {"reason":"haste goes only to the cards just returned; no construct names that set (entered_this_turn would also catch other artifacts)","scope":"format_gap"}

**Signature diff:** fx: parser-only ['pump'], gef-only []

## Well of Lost Dreams

**Oracle:** Whenever you gain life, you may pay {X}, where X is less than or equal to the amount of life you gained. If you do, draw X cards.

**Parser (modeled):** on gain: pay X (up to the life gained): draw X

**GEF (today blank, expressed blank):**
  - unexpressible {"reason":"the paid X is capped by the amount of life just gained, and no construct bounds a paid X by an amount","scope":"format_gap"}

**Signature diff:** fx: parser-only ['draw'], gef-only []; ev: parser-only ['gain_life'], gef-only []
