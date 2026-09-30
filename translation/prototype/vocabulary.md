# GEF 0.1 vocabulary (generated from translation/gef_schema.py; do not edit)

Every object is closed: only the fields listed here are allowed. `*` = required. Types refer to the sections below.
Every ability also takes `text` (the Oracle line it translates).

## Card

- `gef`*: '0.1'
- `name`*: the Oracle name
- `abilities`: [Ability]  (or `faces`: [{`name`*, `abilities`*}] for cards whose faces both have text)
- `notes`: string (anything a reviewer should know)
- `source`: llm | hand | override | parser_export

## Abilities (`kind`)

- **keyword**: `keyword*`: flying | reach | trample | vigilance | haste | lifelink | deathtouch | menace | first strike | double strike | indestructible | hexproof | shroud | defender | infect | wither | fear | intimidate | shadow | horsemanship | skulk | prowess | exalted | unblockable | protection | ward | flash | changeling | myriad | melee | battle cry | training | dethrone | annihilator | toxic | poisonous | flanking | bushido | rampage | afflict | mentor | persist | undying | kicker | multikicker | flashback | cycling | landcycling | typecycling | transmute | rebound | cascade | storm | convoke | improvise | delve | affinity | evoke | buyback | entwine | madness | suspend | foretell | escape | jump-start | retrace | unearth | harmonize | emerge | overload | spree | dash | blitz | prowl | ninjutsu | miracle | split second | splice | replicate | casualty | offering | bargain | plot | warp | echo | cumulative upkeep | sunburst | equip | reconfigure | crew | saddle | station | level up | partner | partner with | companion | choose a background | friends forever | enchant | living weapon | morph | megamorph | disguise | mutate | bestow | eternalize | embalm | encore | disturb | aftermath | fuse | dredge | hideaway | exploit | devour | evolve | riot | fabricate | afterlife | extort | landwalk | gift | offspring | squad | mobilize | decayed | prototype | read ahead | backup | craft | impending | exhaust | soulshift | outlast | renown | spectacle | surge | cipher | transfigure | vanishing | fading | phasing | banding | umbra armor, `n`: integer, `cost`: ManaCost or Cost, `detail`: string
- **spell**: `effects*`: [Effect]
- **triggered**: `event*`: Event, `if`: Cond, `effects*`: [Effect], `optional`: boolean, `once_per_turn`: boolean
- **activated**: `cost*`: Cost, `effects*`: [Effect], `sorcery_speed`: boolean, `once_per_turn`: boolean, `if`: Cond, `from_zone`: battlefield | graveyard | hand | command_zone
- **mana**: `cost*`: Cost, `produce*`: Mana, `if`: Cond
- **static**: `effect*`: Static, `if`: Cond
- **loyalty**: `cost*`: integer or '+X' or '-X', `effects*`: [Effect]
- **chapter**: `chapters*`: [integer], `effects*`: [Effect]
- **class_level**: `level*`: integer, `cost*`: ManaCost, `abilities`: [Ability]
- **additional_cost**: `cost*`: Cost, `optional`: boolean
- **alt_cost**: `cost*`: Cost, `if`: Cond
- **self_cost_reduction**: `amount*`: Amount, `if`: Cond
- **unexpressible**: `reason*`: string, `scope*`: out_of_scope | format_gap | unclear

## Effects (`do`)

- **draw**: `n*`: Amount, `who`: Player
- **discard**: `n*`: Amount or 'hand', `who`: Player, `random`: boolean, `filter`: CardFilter
- **mill**: `n*`: Amount or 'half_library', `who`: Player
- **scry**: `n*`: Amount
- **surveil**: `n*`: Amount
- **look**: `n*`: Amount, `take*`: integer or 'any' or 'all', `filter`: CardFilter, `to*`: Zone, `rest`: bottom | graveyard | top | top_or_bottom | hand | exile | shuffle, `reveal`: boolean, `from`: library | graveyard
- **reveal_until**: `filter*`: CardFilter, `then`: [Effect], `rest`: bottom | graveyard | hand | exile | shuffle
- **tutor**: `filter*`: CardFilter, `n`: Amount, `to*`: Zone, `from`: [library | graveyard | hand | exile], `reveal`: boolean
- **recur**: `filter*`: CardFilter, `n`: Amount or 'all', `to*`: Zone, `from`: your_graveyard | any_graveyard | exile
- **wheel**: `n*`: Amount, `who`: Player, `shuffle_graveyard`: boolean
- **put_back**: `n*`: Amount, `to*`: library_top | library_bottom
- **impulse**: `n*`: Amount, `until*`: end_of_turn | end_of_next_turn | permanent, `filter`: CardFilter, `free`: boolean
- **cast_free**: `filter*`: CardFilter, `from*`: Zone, `n`: Amount
- **put_from_hand**: `filter*`: CardFilter, `n`: Amount or 'any', `symmetric`: boolean, `until`: permanent | end_of_turn_sacrifice
- **mana**: `produce*`: Mana
- **extra_land**: `n*`: integer
- **land_from_hand**: `n*`: integer, `tapped`: boolean
- **untap**: `what*`: Target
- **token**: `n*`: Amount, `token*`: Token, `tapped`: boolean, `attacking`: boolean, `for_each_player`: boolean, `at_end_step`: sacrifice | exile
- **copy_token**: `of*`: Target, `n*`: Amount, `haste`: boolean, `nonlegendary`: boolean, `at_end_step`: sacrifice | exile
- **counters**: `kind*`: string, `n*`: Amount, `on*`: Target, `remove`: boolean
- **proliferate**: `n`: integer
- **pump**: `target*`: Target, `power`: Amount, `toughness`: Amount, `keywords`: [string], `duration*`: Duration
- **pump_team**: `filter`: PermFilter, `power`: Amount, `toughness`: Amount, `keywords`: [string], `duration*`: Duration
- **sacrifice**: `what*`: Target, `who`: Player
- **bounce_own**: `what*`: Target
- **flicker**: `what*`: Target, `returns*`: immediately | next_end_step | when_source_leaves, `tapped`: boolean
- **animate**: `what*`: Target, `power`: Amount, `toughness`: Amount, `types`: [string], `subtypes`: [string], `keywords`: [string], `duration*`: Duration
- **attach**: `what*`: Target, `to*`: Target
- **grant**: `what*`: Target, `abilities*`: [Ability], `duration*`: Duration
- **free_cast_permission**: `spells`: CardFilter, `from*`: Zone, `duration*`: Duration
- **level**: `to*`: integer
- **self_to_library**: `where*`: top | bottom | shuffle
- **bounce_self**: (no fields)
- **damage**: `n*`: Amount, `to*`: each_opponent | target_opponent | any_target | target_player | each_player | defending_player | that_player | you | target_creature | each_creature | each_opposing_creature | target_creature_or_planeswalker | each_other_opponent, `divided`: boolean, `source`: self | that_creature | equipped | enchanted
- **lose_life**: `n*`: Amount, `who*`: Player
- **gain_life**: `n*`: Amount, `who`: Player
- **set_life**: `n*`: Amount, `who`: Player
- **poison**: `n*`: Amount, `who`: Player
- **win_game**: (no fields)
- **lose_game**: `who`: Player
- **extra_turn**: `n`: integer
- **extra_combat**: `n`: integer, `untap`: attackers | all_creatures | none, `then_main`: boolean
- **skip**: `what*`: draw_step | untap_step | upkeep | combat | turn, `who`: Player
- **monarch**: (no fields)
- **initiative**: (no fields)
- **venture**: (no fields)
- **remove**: `how*`: destroy | exile | bounce | tuck | damage | minus | edict | tap | cant_block | cant_attack | cant_attack_or_block, `target*`: Target, `amount`: Amount, `controller_compensation`: string, `duration`: Duration
- **wipe**: `how*`: destroy | exile | bounce | damage | minus | tuck, `filter`: PermFilter, `amount`: Amount, `one_sided`: boolean
- **counter_spell**: `filter`: CardFilter, `unless_pays`: string, `abilities`: boolean
- **protect**: `target*`: Target, `grant*`: [string], `duration`: Duration
- **prevent_damage**: `text`: string
- **gain_control**: `target*`: Target, `duration`: Duration
- **opponent_discards**: `n*`: Amount, `who`: Player, `chooser`: you | them, `random`: boolean
- **if**: `cond*`: Cond, `then*`: [Effect], `else`: [Effect]
- **may_pay**: `cost*`: Cost, `then*`: [Effect], `else`: [Effect], `who`: you | opponent
- **choose**: `n*`: integer, `up_to`: boolean, `same_mode_twice`: boolean, `modes*`: [[Effect]]
- **flip_coins**: `n`: Amount, `until_lose`: boolean, `on_win`: [Effect], `on_lose`: [Effect]
- **roll_die**: `sides*`: integer, `table`: [{min*, max*, effects*}]
- **choose_number**: `min*`: integer, `max*`: integer
- **delayed**: `when*`: next_end_step | next_upkeep | end_of_combat | this_turn_event | next_turn, `event`: Event, `effects*`: [Effect]
- **copy_spell**: `of*`: that_spell | target_spell | self | each_other, `n`: Amount, `filter`: CardFilter
- **unless_opponent_pays**: `cost*`: ManaCost, `effects*`: [Effect]
- **unexpressible**: `text*`: string, `reason*`: string, `scope*`: out_of_scope | format_gap | unclear

## Statics (`static`)

- **anthem**: `filter`: PermFilter, `power`: Amount, `toughness`: Amount, `keywords`: [string]
- **attached_bonus**: `power`: Amount, `toughness`: Amount, `keywords`: [string], `abilities`: [Ability]
- **grant_abilities**: `filter`: PermFilter, `abilities*`: [Ability]
- **cost_reduction**: `spells`: CardFilter, `amount*`: Amount, `first_each_turn`: boolean, `applies_to`: spells | abilities | cycling | equip
- **cost_increase**: `spells`: CardFilter, `amount*`: Amount, `who`: opponents | each_player
- **extra_land**: `n*`: integer
- **no_max_hand_size**: (no fields)
- **max_hand_size**: `n*`: integer
- **token_doubler**: `factor`: integer, `filter`: string
- **counter_doubler**: `factor`: integer, `kind`: string
- **trigger_doubler**: `cause`: enters | dies | attacks | any, `filter`: PermFilter
- **mana_multiplier**: `factor`: integer, `sources`: string
- **damage_multiplier**: `factor`: integer
- **type_grant**: `filter*`: PermFilter, `add_types`: [string], `abilities`: [Ability]
- **enters_tapped**: `unless`: Cond
- **enters_with_counters**: `kind*`: string, `n*`: Amount, `if`: Cond
- **evasion**: `rule*`: string
- **cant_attack**: (no fields)
- **cant_block**: (no fields)
- **free_cast**: `spells`: CardFilter, `from`: Zone
- **alt_cost_all**: `spells`: CardFilter, `cost*`: Cost
- **play_from_top**: `filter`: CardFilter, `cast`: boolean
- **lab_man**: (no fields)
- **doesnt_untap**: (no fields)
- **pt_equals**: `power`: Amount, `toughness`: Amount
- **spend_mana_as_any**: (no fields)
- **lands_tap_any**: (no fields)
- **restriction**: `who`: Player, `text*`: string
- **replacement**: `text*`: string, `kind*`: draw | discard | graveyard | life_gain | damage | tokens | counters | other
- **hand_ability**: `text`: string

## Conditions (`if`)

- **control**: `filter*`: PermFilter, `min`: integer, `max`: integer
- **life_at_least**: `n*`: integer
- **life_at_most**: `n*`: integer
- **hand_at_most**: `n*`: integer
- **hand_at_least**: `n*`: integer
- **hand_exactly**: `n*`: integer
- **graveyard_at_least**: `n*`: integer, `filter`: CardFilter, `card_types`: boolean
- **library_empty**: (no fields)
- **attacked_this_turn**: `min`: integer
- **gained_life_this_turn**: `min`: integer
- **creature_died_this_turn**: (no fields)
- **permanent_left_this_turn**: (no fields)
- **spells_cast_this_turn**: `min`: integer, `max`: integer
- **cards_drawn_this_turn**: `min`: integer
- **your_turn**: (no fields)
- **not_your_turn**: (no fields)
- **main_phase**: (no fields)
- **kicked**: `min`: integer
- **cast_from_hand**: (no fields)
- **cast_from**: `zone*`: Zone
- **self_tapped**: (no fields)
- **self_untapped**: (no fields)
- **self_attacking**: (no fields)
- **self_has_counters**: `kind`: string, `min`: integer
- **x_at_least**: `n*`: integer
- **mana_spent**: `color*`: string, `min`: integer
- **opponent_more_lands**: (no fields)
- **opponent_state**: `text*`: string
- **coin_flip_won**: (no fields)
- **die_result**: `min`: integer, `max`: integer
- **unique_name**: (no fields)
- **you_control_commander**: (no fields)
- **monarch**: (no fields)
- **delirium**: (no fields)
- **amount_at_least**: `amount*`: Amount, `n*`: integer
- **not**: `cond*`: Cond
- **and**: `conds*`: [Cond]
- **or**: `conds*`: [Cond]

## Event

- `on*`: enters | dies | leaves | put_into_graveyard | attacks | you_attack | combat_damage_to_player | deals_damage | attacks_unblocked | becomes_blocked | cast | cast_self | upkeep | end_step | draw_step | precombat_main | combat_begin | gain_life | draw_card | cycle | cycle_self | sacrifice | proliferate | opponent_casts | opponent_draws | opponent_second_spell | opponent_landfall | tapped_for_mana | class_level | discard | blocks | dealt_damage | becomes_target | becomes_tapped | becomes_untapped | counters_put | activate_ability | coin_flip_won | coin_flip | die_rolled | token_created | lose_life | mill | scry | surveil | exiled | transform | turned_face_up | mutates | end_of_combat | postcombat_main | spell_copied | attacks_player | leaves_graveyard | expend | crime | chapter | saddled | crewed | unlock_door | venture | ring_tempts | monarch | initiative | explores | search_library
- `subject`: self | self_or_another | equipped | enchanted | any or PermFilter
- `spell`: CardFilter
- `who`: Player
- `whose`: your | each | opponents | each_player
- `alone`: boolean
- `min_attackers`: integer
- `first_each_turn`: boolean
- `nth`: integer
- `one_or_more`: boolean
- `min_damage`: integer
- `level`: integer
- `event_text`: string

Event `on` values: enters, dies, leaves, put_into_graveyard, attacks, you_attack, combat_damage_to_player, deals_damage, attacks_unblocked, becomes_blocked, cast, cast_self, upkeep, end_step, draw_step, precombat_main, combat_begin, gain_life, draw_card, cycle, cycle_self, sacrifice, proliferate, opponent_casts, opponent_draws, opponent_second_spell, opponent_landfall, tapped_for_mana, class_level, discard, blocks, dealt_damage, becomes_target, becomes_tapped, becomes_untapped, counters_put, activate_ability, coin_flip_won, coin_flip, die_rolled, token_created, lose_life, mill, scry, surveil, exiled, transform, turned_face_up, mutates, end_of_combat, postcombat_main, spell_copied, attacks_player, leaves_graveyard, expend, crime, chapter, saddled, crewed, unlock_door, venture, ring_tempts, monarch, initiative, explores, search_library

## PermFilter (a permanent)

- `types`: [creature | artifact | enchantment | land | planeswalker | battle | permanent | instant | sorcery | kindred]
- `all_types`: boolean
- `non_types`: [string]
- `subtypes`: [string]
- `non_subtypes`: [string]
- `supertypes`: [legendary | basic | snow | nonlegendary | nonbasic]
- `colors`: [W | U | B | R | G]
- `colorless`: boolean
- `multicolored`: boolean
- `monocolored`: boolean
- `controller`: you | opponent | any
- `another`: boolean
- `token`: boolean
- `nontoken`: boolean
- `power`: {min, max}
- `toughness`: {min, max}
- `mana_value`: {min, max, eq}
- `keywords`: [string]
- `without_keywords`: [string]
- `with_counters`: string
- `tapped`: boolean
- `untapped`: boolean
- `attacking`: boolean
- `blocking`: boolean
- `equipped`: boolean
- `enchanted`: boolean
- `modified`: boolean
- `historic`: boolean
- `commander`: boolean
- `chosen_type`: boolean
- `entered_this_turn`: boolean
- `name`: string
- `any_of`: [PermFilter]

## CardFilter (a card in a zone, or a spell)

- `types`: [string]
- `all_types`: boolean
- `non_types`: [string]
- `subtypes`: [string]
- `non_subtypes`: [string]
- `supertypes`: [string]
- `colors`: [W | U | B | R | G]
- `colorless`: boolean
- `multicolored`: boolean
- `mana_value`: {min, max, eq}
- `power`: {min, max}
- `toughness`: {min, max}
- `name`: string
- `not_name`: string
- `any`: boolean
- `permanent`: boolean
- `same_name_as_self`: boolean
- `different_names`: boolean
- `chosen_type`: boolean
- `any_of`: [CardFilter]
- `keywords`: [string]
- `has_x`: boolean
- `mana_cost_any_of`: [ManaCost or '']

## Target

- `ref*`: self | target | each | that | equipped | enchanted | attached | sacrificed | commander | attackers | blockers | it
- `n`: integer or 'X' or 'any'
- `up_to`: boolean
- `filter`: PermFilter

## Token

- `preset`: treasure | clue | food | gold | blood | map | powerstone | shard | junk | incubator | lander | mutagen | role | walker | eldrazi_spawn | eldrazi_scion | servo | thopter
- `name`: string
- `types`: [string]
- `subtypes`: [string]
- `colors`: [string]
- `power`: integer or 'X'
- `toughness`: integer or 'X'
- `keywords`: [string]
- `abilities`: [Ability]
- `legendary`: boolean

## Mana (what a mana ability or ritual produces)

- `units*`: [ColorSet]
- `amount`: Amount
- `restrict`: string
- `any_combination`: boolean

## Cost (every part the ability needs paid)

- `mana`: ManaCost
- `tap`: boolean
- `untap`: boolean
- `sacrifice`: 'self' or {filter*, n}
- `discard`: 'hand' or {n*, filter, random}
- `pay_life`: integer or 'X'
- `remove_counters`: {kind*, n*, from}
- `put_counters`: {kind*, n*}
- `exile_from_graveyard`: 'self' or {n*, filter}
- `exile_from_hand`: 'self' or {n*, filter}
- `exile_self`: boolean
- `tap_untapped`: {n*, filter}
- `return_to_hand`: {n, filter*}
- `exert`: boolean
- `energy`: integer
- `loyalty`: integer or 'X' or '-X'
- `mill`: integer
- `reveal`: CardFilter

- Player: you, target_player, target_opponent, each_opponent, each_player, defending_player, that_player, its_controller, an_opponent

## Amount

An integer, "X" (the spell's or ability's X), or an object:


## Amount object

- `count*`: permanents_you_control | cards_in_hand | cards_in_graveyard | cards_in_library | cards_in_opponent_hand | devotion | domain | converge | times_kicked | opponents | your_life_total | starting_life_total | power_of_self | toughness_of_self | power_of_that | greatest_power | greatest_toughness | greatest_mana_value | counters_on_self | counters_on_that | colors_among_permanents | creature_types_among | spells_cast_this_turn | cards_drawn_this_turn | creatures_died_this_turn | life_gained_this_turn | damage_dealt_this_way | life_lost_this_way | that_much | mana_value_of_that | x_paid | attacking_creatures | equipment_and_auras_attached | number_chosen | coin_flips_won
- `filter`: PermFilter
- `card_filter`: CardFilter
- `colors`: ColorSet
- `kind`: string
- `times`: integer
- `plus`: integer
- `divide`: integer
- `round`: down | up
- `max`: integer

Amount `count` keys: permanents_you_control, cards_in_hand, cards_in_graveyard, cards_in_library, cards_in_opponent_hand, devotion, domain, converge, times_kicked, opponents, your_life_total, starting_life_total, power_of_self, toughness_of_self, power_of_that, greatest_power, greatest_toughness, greatest_mana_value, counters_on_self, counters_on_that, colors_among_permanents, creature_types_among, spells_cast_this_turn, cards_drawn_this_turn, creatures_died_this_turn, life_gained_this_turn, damage_dealt_this_way, life_lost_this_way, that_much, mana_value_of_that, x_paid, attacking_creatures, equipment_and_auras_attached, number_chosen, coin_flips_won

## Shared value lists

- Player (`who`): you, target_player, target_opponent, each_opponent, each_player, defending_player, that_player, its_controller, an_opponent
- Zone (`to`, `from`): hand, battlefield, battlefield_tapped, library_top, library_bottom, library_shuffled, graveyard, exile, exile_castable, command_zone
- Duration: end_of_turn, until_your_next_turn, permanent, as_long_as_source
- Color set (mana `units`, `colors`): ^(?:[WUBRGC]+|any|any_one_color|commander_colors|chosen_color)$  (e.g. "C", "G", "WU" = W or U, "any")
- Mana cost strings: ^(\{(?:[0-9]+|[WUBRGCSX]|[WUBRG]/[WUBRGP]|[0-9]/[WUBRG]|[WUBRG]/P)\})+$  (e.g. "{2}{U}", "{X}{R}", "{G/P}")
- Keywords (`keyword`): flying, reach, trample, vigilance, haste, lifelink, deathtouch, menace, first strike, double strike, indestructible, hexproof, shroud, defender, infect, wither, fear, intimidate, shadow, horsemanship, skulk, prowess, exalted, unblockable, protection, ward, flash, changeling, myriad, melee, battle cry, training, dethrone, annihilator, toxic, poisonous, flanking, bushido, rampage, afflict, mentor, persist, undying, kicker, multikicker, flashback, cycling, landcycling, typecycling, transmute, rebound, cascade, storm, convoke, improvise, delve, affinity, evoke, buyback, entwine, madness, suspend, foretell, escape, jump-start, retrace, unearth, harmonize, emerge, overload, spree, dash, blitz, prowl, ninjutsu, miracle, split second, splice, replicate, casualty, offering, bargain, plot, warp, echo, cumulative upkeep, sunburst, equip, reconfigure, crew, saddle, station, level up, partner, partner with, companion, choose a background, friends forever, enchant, living weapon, morph, megamorph, disguise, mutate, bestow, eternalize, embalm, encore, disturb, aftermath, fuse, dredge, hideaway, exploit, devour, evolve, riot, fabricate, afterlife, extort, landwalk, gift, offspring, squad, mobilize, decayed, prototype, read ahead, backup, craft, impending, exhaust, soulshift, outlast, renown, spectacle, surge, cipher, transfigure, vanishing, fading, phasing, banding, umbra armor
