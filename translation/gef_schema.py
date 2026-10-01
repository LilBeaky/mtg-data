#!/usr/bin/env python3
"""GEF (Goldfish Effect Format) v0.2: the JSON Schema a card translation must satisfy.

  python3 translation/gef_schema.py      # writes translation/gef.schema.json

GEF describes what a card does in rules terms (who draws, what gets searched for, which event triggers what), not how
goldfish.py pilots it: whether to self-mill, when to hold a pump, which blocker to kill stay engine decisions.
Every object is closed (additionalProperties: false) so an unknown field is a rejection, never a guess. Text the
format can't say goes in an `unexpressible` ability or effect with a reason; see docs/GOLDFISH_EFFECT_FORMAT.md.
v0.2 (T3 step 1): no free-text statics (replacement, restriction, hand_ability are gone, each replaced by a construct
or left unexpressible), keywords are an enum everywhere, `detail` only on silent keywords, and the cheap T2 gaps.
"""
import json, os

VERSION = "0.2"
HERE = os.path.dirname(os.path.abspath(__file__))

def ref(n): return {"$ref": f"#/$defs/{n}"}
def arr(item, mn=0): return {"type": "array", "items": item, **({"minItems": mn} if mn else {})}
def enum(*v): return {"enum": list(v)}
def obj(props, req=(), **kw):
    return {"type": "object", "properties": props, "required": list(req), "additionalProperties": False, **kw}
STR, INT, BOOL = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
MANA_COST = {"type": "string", "pattern": r"^(\{(?:[0-9]+|[WUBRGCSX]|[WUBRG]/[WUBRGP]|[0-9]/[WUBRG]|[WUBRG]/P)\})+$"}

def union(tag, cases, common=None):
    """Discriminated union on field `tag`: {case: {field: schema}} -> an object schema whose tag picks the case.
    Every case is closed: only the tag, the common fields and its own fields are allowed."""
    common = common or {}
    out = {"type": "object", "required": [tag], "properties": {tag: enum(*cases)}, "allOf": []}
    for name, spec in cases.items():
        props, req = spec if isinstance(spec, tuple) else (spec, [])
        allp = {tag: {"const": name}, **common, **props}
        out["allOf"].append({"if": {"properties": {tag: {"const": name}}, "required": [tag]},
                             "then": {"properties": allp, "required": [tag] + list(req), "additionalProperties": False}})
    return out

# ---------------------------------------------------------------- vocabulary
PLAYER = enum("you", "target_player", "target_opponent", "each_opponent", "each_player", "defending_player",
              "that_player", "its_controller", "an_opponent")
ZONE = enum("hand", "battlefield", "battlefield_tapped", "library_top", "library_bottom", "library_shuffled",
            "graveyard", "exile", "exile_castable", "command_zone")
DURATION = enum("end_of_turn", "until_your_next_turn", "permanent", "as_long_as_source")
COLORSET = {"type": "string", "pattern": r"^(?:[WUBRGC]+|any|any_one_color|commander_colors|chosen_color)$"}
COMBAT_KWS = ["flying", "reach", "trample", "vigilance", "haste", "lifelink", "deathtouch", "menace", "first strike",
              "double strike", "indestructible", "hexproof", "shroud", "defender", "infect", "wither", "fear",
              "intimidate", "shadow", "horsemanship", "skulk", "prowess", "exalted", "unblockable", "protection",
              "ward", "flash", "changeling", "myriad", "melee", "battle cry", "training", "dethrone", "annihilator",
              "toxic", "poisonous", "flanking", "bushido", "rampage", "afflict", "mentor", "persist", "undying"]
KEYWORDS = COMBAT_KWS + [
    # casting and cost keywords
    "kicker", "multikicker", "flashback", "cycling", "landcycling", "typecycling", "transmute", "rebound", "cascade",
    "storm", "convoke", "improvise", "delve", "affinity", "evoke", "buyback", "entwine", "madness", "suspend",
    "foretell", "escape", "jump-start", "retrace", "unearth", "harmonize", "emerge", "overload", "spree", "dash",
    "blitz", "prowl", "ninjutsu", "miracle", "split second", "splice", "replicate", "casualty", "offering", "bargain",
    "plot", "warp", "echo", "cumulative upkeep", "sunburst", "equip", "reconfigure", "crew", "saddle", "station",
    "level up", "partner", "partner with", "companion", "choose a background", "friends forever", "enchant",
    "living weapon", "morph", "megamorph", "disguise", "mutate", "bestow", "eternalize", "embalm", "encore",
    "disturb", "aftermath", "fuse", "dredge", "hideaway", "exploit", "devour", "evolve", "riot", "fabricate",
    "afterlife", "extort", "landwalk", "gift", "offspring", "squad", "mobilize", "decayed", "prototype", "read ahead",
    "backup", "craft", "impending", "exhaust", "soulshift", "outlast", "renown", "spectacle", "surge", "cipher",
    "transfigure", "vanishing", "fading", "phasing", "banding", "umbra armor"]
# Keywords the engine ignores on purpose (opponent-facing or bookkeeping). Only these may carry a free-string `detail`
# (protection's quality, enchant's object, partner with's name): nothing executes it, so it can't hide a read.
SILENT_KEYWORDS = ["hexproof", "shroud", "protection", "ward", "flash", "changeling", "partner", "partner with",
                   "companion", "choose a background", "friends forever", "enchant", "split second", "umbra armor",
                   "banding", "phasing", "crew", "reconfigure", "landwalk"]
assert set(SILENT_KEYWORDS) <= set(KEYWORDS)
KEYWORD = enum(*KEYWORDS)
# A keyword a pump/anthem/token/filter gives or checks: the keyword's name, or {keyword, detail} for a silent keyword
# whose quality is part of the text ("protection from red" = {"keyword": "protection", "detail": "red"}).
KW_ITEM = {"anyOf": [KEYWORD, obj({"keyword": enum(*SILENT_KEYWORDS), "detail": STR}, ["keyword", "detail"])]}

# Amounts: a number, the spell's X, or a count the sim reads at resolution
COUNT = enum(
    "permanents_you_control",      # with filter: creatures, artifacts, Elves, lands...
    "cards_in_hand", "cards_in_graveyard", "cards_in_library", "cards_in_opponent_hand",
    "devotion", "domain", "converge", "times_kicked", "opponents", "your_life_total", "starting_life_total",
    "power_of_self", "toughness_of_self", "power_of_that", "greatest_power", "greatest_toughness", "greatest_mana_value",
    "counters_on_self", "counters_on_that", "colors_among_permanents", "creature_types_among",
    "spells_cast_this_turn", "cards_drawn_this_turn", "creatures_died_this_turn", "life_gained_this_turn",
    "damage_dealt_this_way", "life_lost_this_way", "that_much", "mana_value_of_that", "x_paid",
    "attacking_creatures", "equipment_and_auras_attached", "number_chosen", "coin_flips_won",
    # v0.2
    "total_power",                 # total power of creatures you control matching the filter (Klauth: {attacking: true})
    "permanents_on_battlefield",   # every player's permanents matching the filter (Blasphemous Act: creatures)
    "commander_identity_colors",   # colors in your commander's (commanders') color identity (War Room)
    "damage_dealt_this_turn")      # damage dealt this turn to `player` (Knollspine Dragon: target_opponent)
AMOUNT = {"anyOf": [INT, {"const": "X"}, obj({
    "count": COUNT, "filter": ref("PermFilter"), "card_filter": ref("CardFilter"), "colors": COLORSET,
    "kind": STR, "times": INT, "plus": INT, "divide": INT, "round": enum("down", "up"), "max": INT,
    "player": PLAYER},
    ["count"])]}

PERM_FILTER = obj({
    "types": arr(enum("creature", "artifact", "enchantment", "land", "planeswalker", "battle", "permanent",
                      "instant", "sorcery", "kindred")),
    "all_types": {"type": "boolean", "description": "true: every listed type (artifact creature); default: any of them"},
    "non_types": arr(STR), "subtypes": arr(STR), "non_subtypes": arr(STR),
    "supertypes": arr(enum("legendary", "basic", "snow", "nonlegendary", "nonbasic")),
    "colors": arr(enum("W", "U", "B", "R", "G")), "colorless": BOOL, "multicolored": BOOL, "monocolored": BOOL,
    "controller": enum("you", "opponent", "any", "that_player"), "another": BOOL, "token": BOOL, "nontoken": BOOL,
    "power": obj({"min": INT, "max": INT}), "toughness": obj({"min": INT, "max": INT}),
    "mana_value": obj({"min": INT, "max": {"anyOf": [INT, {"const": "X"}]}, "eq": INT}),
    "keywords": arr(KW_ITEM), "without_keywords": arr(KW_ITEM), "with_counters": STR, "tapped": BOOL, "untapped": BOOL,
    "attacking": BOOL, "blocking": BOOL, "equipped": BOOL, "enchanted": BOOL, "modified": BOOL, "historic": BOOL,
    "commander": BOOL, "chosen_type": BOOL, "entered_this_turn": BOOL, "name": STR,
    "any_of": arr(ref("PermFilter"), 2)})
CARD_FILTER = obj({
    "types": arr(STR), "all_types": BOOL, "non_types": arr(STR), "subtypes": arr(STR), "non_subtypes": arr(STR),
    "supertypes": arr(STR), "colors": arr(enum("W", "U", "B", "R", "G")), "colorless": BOOL, "multicolored": BOOL,
    "mana_value": obj({"min": INT, "max": {"anyOf": [INT, {"const": "X"}, {"const": "sacrificed_plus_1"}]}, "eq": INT}),
    "power": obj({"min": INT, "max": INT}), "toughness": obj({"min": INT, "max": INT}), "name": STR, "not_name": STR,
    "any": BOOL, "permanent": BOOL, "same_name_as_self": BOOL, "different_names": BOOL, "chosen_type": BOOL,
    "any_of": arr(ref("CardFilter"), 2), "keywords": arr(KW_ITEM), "has_x": BOOL,
    "mana_cost_any_of": arr({"anyOf": [MANA_COST, {"const": ""}]}, 1)})
SPELL_FILTER = CARD_FILTER
TARGET = obj({
    "ref": enum("self", "target", "each", "that", "equipped", "enchanted", "attached", "sacrificed", "commander",
                "attackers", "blockers", "it"),
    "n": {"anyOf": [INT, {"const": "X"}, {"const": "any"}]}, "up_to": BOOL, "filter": ref("PermFilter"),
    "for_each": enum("opponent", "player")}, ["ref"])     # "for each opponent, up to one target ... that player controls"
TOKEN = obj({
    "preset": enum("treasure", "clue", "food", "gold", "blood", "map", "powerstone", "shard", "junk", "incubator",
                   "lander", "mutagen", "role", "walker", "eldrazi_spawn", "eldrazi_scion", "servo", "thopter"),
    "name": STR, "types": arr(STR), "subtypes": arr(STR), "colors": arr(STR),
    "power": {"anyOf": [INT, {"const": "X"}]}, "toughness": {"anyOf": [INT, {"const": "X"}]},
    "keywords": arr(KW_ITEM), "abilities": arr(ref("Ability")), "legendary": BOOL})
MANA = obj({"units": arr(COLORSET, 1), "amount": AMOUNT, "restrict": STR, "any_combination": BOOL}, ["units"])
COST = obj({
    "mana": MANA_COST, "tap": BOOL, "untap": BOOL, "sacrifice": {"anyOf": [{"const": "self"}, obj({"filter": ref("PermFilter"), "n": INT}, ["filter"])]},
    "discard": {"anyOf": [{"const": "hand"}, obj({"n": INT, "filter": ref("CardFilter"), "random": BOOL}, ["n"])]},
    "pay_life": AMOUNT, "remove_counters": obj({"kind": STR, "n": {"anyOf": [INT, {"const": "X"}, {"const": "any"}]}, "from": enum("self", "any")}, ["kind", "n"]),
    "put_counters": obj({"kind": STR, "n": INT}, ["kind", "n"]),
    "exile_from_graveyard": {"anyOf": [{"const": "self"}, obj({"n": {"anyOf": [INT, {"const": "X"}]}, "filter": ref("CardFilter")}, ["n"])]},
    "exile_from_hand": {"anyOf": [{"const": "self"}, obj({"n": INT, "filter": ref("CardFilter")}, ["n"])]},
    "exile_self": BOOL, "tap_untapped": obj({"n": INT, "filter": ref("PermFilter")}, ["n"]),
    "return_to_hand": obj({"n": INT, "filter": ref("PermFilter")}, ["filter"]), "exert": BOOL, "energy": INT,
    "loyalty": {"anyOf": [INT, {"const": "X"}, {"const": "-X"}]}, "mill": INT, "reveal": ref("CardFilter")})

EVENTS = [
    # the engine reads these today (see docs/GOLDFISH_EFFECT_FORMAT.md, engine support)
    "enters", "dies", "leaves", "put_into_graveyard", "attacks", "you_attack", "combat_damage_to_player",
    "deals_damage", "attacks_unblocked", "becomes_blocked", "cast", "cast_self", "upkeep", "end_step",
    "draw_step", "precombat_main", "combat_begin", "gain_life", "draw_card", "cycle", "cycle_self", "sacrifice",
    "proliferate", "opponent_casts", "opponent_draws", "opponent_second_spell", "opponent_landfall",
    "tapped_for_mana", "class_level",
    # not read today
    "discard", "blocks", "dealt_damage", "becomes_target", "becomes_tapped", "becomes_untapped", "counters_put",
    "activate_ability", "coin_flip_won", "coin_flip", "die_rolled", "token_created", "lose_life", "mill",
    "scry", "surveil", "exiled", "transform", "turned_face_up", "mutates", "end_of_combat", "postcombat_main",
    "spell_copied", "attacks_player", "leaves_graveyard", "expend", "crime", "chapter", "saddled", "crewed",
    "unlock_door", "venture", "ring_tempts", "monarch", "initiative", "explores", "search_library",
    "play_land"]                                          # v0.2: "whenever you play a land" (not landfall: a fetched land isn't played)
EVENT = obj({
    "on": enum(*EVENTS),
    "subject": {"anyOf": [enum("self", "self_or_another", "equipped", "enchanted", "any"), ref("PermFilter")]},
    "spell": ref("CardFilter"), "who": PLAYER, "whose": enum("your", "each", "opponents", "each_player"),
    "alone": BOOL, "min_attackers": INT, "first_each_turn": BOOL, "nth": INT, "one_or_more": BOOL,
    "min_damage": INT, "level": INT, "event_text": STR}, ["on"])

CONDS = {
    "control": ({"filter": ref("PermFilter"), "min": INT, "max": INT}, ["filter"]),
    "life_at_least": ({"n": INT}, ["n"]), "life_at_most": ({"n": INT}, ["n"]),
    "hand_at_most": ({"n": INT}, ["n"]), "hand_at_least": ({"n": INT}, ["n"]), "hand_exactly": ({"n": INT}, ["n"]),
    "graveyard_at_least": ({"n": INT, "filter": ref("CardFilter"), "card_types": BOOL}, ["n"]),
    "library_empty": {}, "attacked_this_turn": {"min": INT}, "gained_life_this_turn": {"min": INT},
    "creature_died_this_turn": {}, "permanent_left_this_turn": {}, "spells_cast_this_turn": ({"min": INT, "max": INT}, []),
    "cards_drawn_this_turn": ({"min": INT}, []), "your_turn": {}, "not_your_turn": {}, "main_phase": {},
    "kicked": {"min": INT}, "cast_from_hand": {}, "cast_from": ({"zone": ZONE}, ["zone"]), "self_tapped": {},
    "self_untapped": {}, "self_attacking": {}, "self_has_counters": ({"kind": STR, "min": INT}, []),
    "x_at_least": ({"n": INT}, ["n"]), "mana_spent": ({"color": STR, "min": INT}, ["color"]),
    "opponent_more_lands": {}, "opponent_state": ({"text": STR}, ["text"]), "coin_flip_won": {}, "die_result": ({"min": INT, "max": INT}, []),
    "unique_name": {}, "you_control_commander": {}, "monarch": {}, "delirium": {},
    "amount_at_least": ({"amount": AMOUNT, "n": INT}, ["amount", "n"]),
    "not": ({"cond": ref("Cond")}, ["cond"]), "and": ({"conds": arr(ref("Cond"), 2)}, ["conds"]),
    "or": ({"conds": arr(ref("Cond"), 2)}, ["conds"]),
}
EFFECT_CASES = {
    # --- card flow
    "draw": ({"n": AMOUNT, "who": PLAYER}, ["n"]),
    "discard": ({"n": {"anyOf": [AMOUNT, {"const": "hand"}]}, "who": PLAYER, "random": BOOL, "filter": ref("CardFilter")}, ["n"]),
    "mill": ({"n": {"anyOf": [AMOUNT, {"const": "half_library"}]}, "who": PLAYER}, ["n"]),
    "scry": ({"n": AMOUNT}, ["n"]), "surveil": ({"n": AMOUNT}, ["n"]),
    "look": ({"n": AMOUNT, "take": {"anyOf": [INT, {"const": "any"}, {"const": "all"}]}, "filter": ref("CardFilter"),
              "to": ZONE, "rest": enum("bottom", "graveyard", "top", "top_or_bottom", "hand", "exile", "shuffle"),
              "reveal": BOOL, "from": enum("library", "graveyard")}, ["n", "take", "to"]),
    "reveal_until": ({"filter": ref("CardFilter"), "then": arr(ref("Effect")), "rest": enum("bottom", "graveyard", "hand", "exile", "shuffle")}, ["filter"]),
    "tutor": ({"filter": ref("CardFilter"), "n": AMOUNT, "to": ZONE, "from": arr(enum("library", "graveyard", "hand", "exile")), "reveal": BOOL,
               "split": arr(obj({"n": INT, "to": ZONE}, ["n", "to"]), 2),     # one search, found cards to several zones (Cultivate)
               "position": INT}, ["filter"]),                                  # with to library_top: Nth from the top (Long-Term Plans: 3)
    "recur": ({"filter": ref("CardFilter"), "n": {"anyOf": [AMOUNT, {"const": "all"}]}, "to": ZONE, "from": enum("your_graveyard", "any_graveyard", "exile")}, ["filter", "to"]),
    "wheel": ({"n": AMOUNT, "who": PLAYER, "shuffle_graveyard": BOOL}, ["n"]),
    "put_back": ({"n": AMOUNT, "to": enum("library_top", "library_bottom")}, ["n", "to"]),
    "impulse": ({"n": AMOUNT, "until": enum("end_of_turn", "end_of_next_turn", "permanent"), "filter": ref("CardFilter"), "free": BOOL}, ["n", "until"]),
    "cast_free": ({"filter": ref("CardFilter"), "from": ZONE, "n": AMOUNT}, ["filter", "from"]),
    "put_from_hand": ({"filter": ref("CardFilter"), "n": {"anyOf": [AMOUNT, {"const": "any"}]}, "symmetric": BOOL, "until": enum("permanent", "end_of_turn_sacrifice")}, ["filter"]),
    # --- mana and lands
    "mana": ({"produce": MANA}, ["produce"]),
    "extra_land": ({"n": INT}, ["n"]),
    "land_from_hand": ({"n": INT, "tapped": BOOL}, ["n"]),
    "untap": ({"what": TARGET}, ["what"]),
    # --- board
    "token": ({"n": AMOUNT, "token": TOKEN, "tapped": BOOL, "attacking": BOOL, "for_each_player": BOOL, "at_end_step": enum("sacrifice", "exile")}, ["n", "token"]),
    "copy_token": ({"of": TARGET, "n": AMOUNT, "haste": BOOL, "nonlegendary": BOOL, "at_end_step": enum("sacrifice", "exile")}, ["of", "n"]),
    "counters": ({"kind": STR, "n": AMOUNT, "on": TARGET, "remove": BOOL}, ["kind", "n", "on"]),
    "proliferate": ({"n": INT}, []),
    "pump": ({"target": TARGET, "power": AMOUNT, "toughness": AMOUNT, "keywords": arr(KW_ITEM), "duration": DURATION}, ["target", "duration"]),
    "pump_team": ({"filter": ref("PermFilter"), "power": AMOUNT, "toughness": AMOUNT, "keywords": arr(KW_ITEM), "duration": DURATION}, ["duration"]),
    "sacrifice": ({"what": TARGET, "who": PLAYER}, ["what"]),
    "bounce_own": ({"what": TARGET}, ["what"]),
    "flicker": ({"what": TARGET, "returns": enum("immediately", "next_end_step", "when_source_leaves"), "tapped": BOOL}, ["what", "returns"]),
    "animate": ({"what": TARGET, "power": AMOUNT, "toughness": AMOUNT, "types": arr(STR), "subtypes": arr(STR), "keywords": arr(KW_ITEM), "duration": DURATION}, ["what", "duration"]),
    "attach": ({"what": TARGET, "to": TARGET}, ["what", "to"]),
    "grant": ({"what": TARGET, "abilities": arr(ref("Ability"), 1), "duration": DURATION}, ["what", "abilities", "duration"]),
    "free_cast_permission": ({"spells": ref("CardFilter"), "from": ZONE, "duration": DURATION}, ["from", "duration"]),
    "level": ({"to": INT}, ["to"]),
    "self_to_library": ({"where": enum("top", "bottom", "shuffle"), "position": INT}, ["where"]),   # position: Nth from the top
    "bounce_self": {},
    # --- players and life
    "damage": ({"n": AMOUNT, "to": enum("each_opponent", "target_opponent", "any_target", "target_player", "each_player",
                                        "defending_player", "that_player", "you", "target_creature", "each_creature",
                                        "each_opposing_creature", "target_creature_or_planeswalker", "each_other_opponent"),
                "divided": BOOL, "source": enum("self", "that_creature", "equipped", "enchanted"),
                "filter": ref("PermFilter")}, ["n", "to"]),      # narrows each_creature (Balefire Dragon: controller that_player)
    "lose_life": ({"n": AMOUNT, "who": PLAYER}, ["n", "who"]),
    "gain_life": ({"n": AMOUNT, "who": PLAYER}, ["n"]),
    "set_life": ({"n": AMOUNT, "who": PLAYER}, ["n"]),
    "poison": ({"n": AMOUNT, "who": PLAYER}, ["n"]),
    "win_game": {}, "lose_game": ({"who": PLAYER}, []),
    "extra_turn": ({"n": INT}, []), "extra_combat": ({"n": INT, "untap": enum("attackers", "all_creatures", "none"), "then_main": BOOL}, []),
    "skip": ({"what": enum("draw_step", "untap_step", "upkeep", "combat", "turn"), "who": PLAYER}, ["what"]),
    "monarch": {}, "initiative": {}, "venture": {},
    # --- interaction (held or vs --blockers; out of scope in a clean goldfish game)
    "remove": ({"how": enum("destroy", "exile", "bounce", "tuck", "damage", "minus", "edict", "tap", "cant_block", "cant_attack", "cant_attack_or_block"),
                "target": TARGET, "amount": AMOUNT, "controller_compensation": STR, "duration": DURATION}, ["how", "target"]),
    "wipe": ({"how": enum("destroy", "exile", "bounce", "damage", "minus", "tuck"), "filter": ref("PermFilter"), "amount": AMOUNT, "one_sided": BOOL}, ["how"]),
    "counter_spell": ({"filter": ref("CardFilter"), "unless_pays": MANA_COST, "abilities": BOOL}, []),
    "protect": ({"target": TARGET, "grant": arr(KW_ITEM, 1), "duration": DURATION}, ["target", "grant"]),
    "prevent_damage": ({"text": STR}, []),
    "gain_control": ({"target": TARGET, "duration": DURATION}, ["target"]),
    "opponent_discards": ({"n": AMOUNT, "who": PLAYER, "chooser": enum("you", "them"), "random": BOOL}, ["n"]),
    # --- structure within an effect list
    "if": ({"cond": ref("Cond"), "then": arr(ref("Effect")), "else": arr(ref("Effect"))}, ["cond", "then"]),
    "may_pay": ({"cost": COST, "then": arr(ref("Effect")), "else": arr(ref("Effect")), "who": enum("you", "opponent")}, ["cost", "then"]),
    "choose": ({"n": INT, "up_to": BOOL, "same_mode_twice": BOOL, "modes": arr(arr(ref("Effect")), 2)}, ["n", "modes"]),
    "flip_coins": ({"n": AMOUNT, "until_lose": BOOL, "on_win": arr(ref("Effect")), "on_lose": arr(ref("Effect"))}, []),
    "roll_die": ({"sides": INT, "table": arr(obj({"min": INT, "max": INT, "effects": arr(ref("Effect"))}, ["min", "max", "effects"]))}, ["sides"]),
    "choose_number": ({"min": INT, "max": INT}, ["min", "max"]),
    "delayed": ({"when": enum("next_end_step", "next_upkeep", "end_of_combat", "this_turn_event", "next_turn"),
                 "event": ref("Event"), "effects": arr(ref("Effect"), 1)}, ["when", "effects"]),
    "copy_spell": ({"of": enum("that_spell", "target_spell", "self", "each_other"), "n": AMOUNT, "filter": ref("CardFilter")}, ["of"]),
    "unless_opponent_pays": ({"cost": MANA_COST, "effects": arr(ref("Effect"), 1)}, ["cost", "effects"]),
    "unexpressible": ({"text": STR, "reason": STR, "scope": enum("out_of_scope", "format_gap", "unclear")}, ["text", "reason", "scope"]),
}
STATIC_CASES = {
    "anthem": ({"filter": ref("PermFilter"), "power": AMOUNT, "toughness": AMOUNT, "keywords": arr(KW_ITEM)}, []),
    "attached_bonus": ({"power": AMOUNT, "toughness": AMOUNT, "keywords": arr(KW_ITEM), "abilities": arr(ref("Ability"))}, []),
    "grant_abilities": ({"filter": ref("PermFilter"), "abilities": arr(ref("Ability"), 1)}, ["abilities"]),
    "cost_reduction": ({"spells": ref("CardFilter"), "amount": AMOUNT, "first_each_turn": BOOL, "applies_to": enum("spells", "abilities", "cycling", "equip")}, ["amount"]),
    "cost_increase": ({"spells": ref("CardFilter"), "amount": AMOUNT, "who": enum("opponents", "each_player")}, ["amount"]),
    "extra_land": ({"n": INT}, ["n"]), "no_max_hand_size": {}, "max_hand_size": ({"n": INT}, ["n"]),
    "token_doubler": ({"factor": INT, "filter": STR}, []), "counter_doubler": ({"factor": INT, "kind": STR}, []),
    "trigger_doubler": ({"cause": enum("enters", "dies", "attacks", "any"), "filter": ref("PermFilter")}, []),
    "mana_multiplier": ({"factor": INT, "sources": STR}, []), "damage_multiplier": ({"factor": INT}, []),
    "type_grant": ({"filter": ref("PermFilter"), "self": BOOL, "add_types": arr(STR), "add_chosen_type": BOOL,
                    "abilities": arr(ref("Ability"))}, []),           # exactly one of filter / self
    "enters_tapped": ({"unless": ref("Cond"), "unless_pay": COST}, []),  # unless_pay: "you may pay 3 life. If you don't, ..."
    "enters_with_counters": ({"kind": STR, "n": AMOUNT, "if": ref("Cond")}, ["kind", "n"]),
    "evasion": ({"rule": STR}, ["rule"]), "cant_attack": {}, "cant_block": {},
    "free_cast": ({"spells": ref("CardFilter"), "from": ZONE}, []),
    "alt_cost_all": ({"spells": ref("CardFilter"), "cost": COST}, ["cost"]),
    "play_from_top": ({"filter": ref("CardFilter"), "cast": BOOL}, []),
    "draw_from_empty_library_wins": {}, "doesnt_untap": {}, "pt_equals": ({"power": AMOUNT, "toughness": AMOUNT}, []),
    "spend_mana_as_any": {}, "lands_tap_any": {},
    # v0.2: the constructs that replace the free-text `replacement` / `restriction` / `hand_ability` statics
    "skip_step": ({"what": enum("draw_step", "untap_step", "upkeep", "combat"), "who": PLAYER}, ["what"]),
    "extra_counters": ({"n": INT, "kind": STR, "on": ref("PermFilter")}, ["n", "on"]),   # "that many plus N" (Hardened Scales)
    "graveyard_replacement": ({"whose": enum("self", "yours", "opponents", "each_player"), "to": ZONE}, ["whose", "to"]),
    "discard_to_top": ({"optional": BOOL, "effects_only": BOOL}, []),       # Library of Leng
    "spell_limit": ({"n": INT, "spells": ref("CardFilter"), "who": enum("you", "opponents", "each_player")}, ["n", "who"]),
    "coin_flip_rule": ({"rule": enum("flip_two_ignore_one", "first_flips_each_turn_win")}, ["rule"]),
    "choose_on_enter": ({"choice": enum("creature_type", "color")}, ["choice"]),        # "As ~ enters, choose a creature type."
}
ABILITY_CASES = {
    "keyword": ({"keyword": KEYWORD, "n": INT, "cost": {"anyOf": [MANA_COST, COST]},
                 "filter": ref("PermFilter"),        # what it may target or needs: equip [commander], [Artifact] offering
                 "card_filter": ref("CardFilter"),   # what it finds: [Wizard]cycling, [Forest]cycling
                 "detail": STR}, ["keyword"]),       # silent keywords only (see SILENT_KEYWORDS)
    "spell": ({"effects": arr(ref("Effect"), 1)}, ["effects"]),
    "triggered": ({"event": ref("Event"), "if": ref("Cond"), "effects": arr(ref("Effect"), 1), "optional": BOOL,
                   "once_per_turn": BOOL}, ["event", "effects"]),
    "activated": ({"cost": COST, "effects": arr(ref("Effect"), 1), "sorcery_speed": BOOL, "once_per_turn": BOOL,
                   "if": ref("Cond"), "from_zone": enum("battlefield", "graveyard", "hand", "command_zone")}, ["cost", "effects"]),
    "mana": ({"cost": COST, "produce": MANA, "if": ref("Cond")}, ["cost", "produce"]),
    "static": ({"effect": ref("Static"), "if": ref("Cond")}, ["effect"]),
    "loyalty": ({"cost": {"anyOf": [INT, {"const": "+X"}, {"const": "-X"}]}, "effects": arr(ref("Effect"), 1)}, ["cost", "effects"]),
    "chapter": ({"chapters": arr(INT, 1), "effects": arr(ref("Effect"), 1)}, ["chapters", "effects"]),
    "class_level": ({"level": INT, "cost": MANA_COST, "abilities": arr(ref("Ability"))}, ["level", "cost"]),
    "additional_cost": ({"cost": COST, "optional": BOOL}, ["cost"]),
    "alt_cost": ({"cost": COST, "if": ref("Cond")}, ["cost"]),
    "self_cost_reduction": ({"amount": AMOUNT, "if": ref("Cond")}, ["amount"]),
    "unexpressible": ({"reason": STR, "scope": enum("out_of_scope", "format_gap", "unclear")}, ["reason", "scope"]),
}

def build():
    ability = union("kind", ABILITY_CASES, common={"text": STR})
    face = obj({"name": STR, "abilities": arr(ref("Ability")), "pt": obj({"power": {"anyOf": [INT, STR]}, "toughness": {"anyOf": [INT, STR]}})}, ["name", "abilities"])
    card = obj({
        "gef": {"const": VERSION}, "name": STR, "abilities": arr(ref("Ability")), "faces": arr(ref("Face"), 2),
        "pt": obj({"power": {"anyOf": [INT, AMOUNT, STR]}, "toughness": {"anyOf": [INT, AMOUNT, STR]}}),
        "source": enum("llm", "hand", "override", "parser_export"), "notes": STR}, ["gef", "name"])
    card["oneOf"] = [{"required": ["abilities"]}, {"required": ["faces"]}]
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"gef-{VERSION}",
            "title": f"Goldfish Effect Format {VERSION}", "$ref": "#/$defs/Card",
            "$defs": {"Card": card, "Face": face, "Ability": ability, "Effect": union("do", EFFECT_CASES),
                      "Static": union("static", STATIC_CASES), "Cond": union("if", CONDS), "Event": EVENT,
                      "PermFilter": PERM_FILTER, "CardFilter": CARD_FILTER, "Target": TARGET, "Token": TOKEN,
                      "Mana": MANA, "Cost": COST, "Amount": AMOUNT}}

if __name__ == "__main__":
    s = build()
    with open(os.path.join(HERE, "gef.schema.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, ensure_ascii=False); f.write("\n")
    print(f"wrote translation/gef.schema.json: {len(ABILITY_CASES)} ability kinds, {len(EFFECT_CASES)} effects, "
          f"{len(STATIC_CASES)} statics, {len(CONDS)} conditions, {len(EVENTS)} events, {len(KEYWORDS)} keywords")
