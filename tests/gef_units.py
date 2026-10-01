#!/usr/bin/env python3
"""Unit checks for the GEF adapter (scripts/gef_compile.py): one per mapped construct, plus refusals.

  python3 tests/gef_units.py        # prints "gef units: all N passed" or the failures; exit 1 on failure

Each check compiles a small GEF card (hand-written here, on a real card's metadata) and asserts the engine
structure it becomes, or that the ability is refused (unread, the card partial) instead of approximated.
"""
import os, sys
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.chdir(REPO)
import mtg, goldfish as g, gef_compile as gc

IDX = mtg.index()
CHECKS = []
def check(name):
    def deco(fn): CHECKS.append((name, fn)); return fn
    return deco

def C(card, *abilities, anyc=g.ALL5):
    """Compile the given GEF abilities on card's metadata."""
    return gc.compile_gef(IDX[mtg.norm(card)], {"gef": "0.2", "name": card, "abilities": list(abilities)}, anyc)

def A(kind, **kw): return dict(kind=kind, text="", **kw)
def S(effect): return A("static", effect=effect)
def SP(*fx): return A("spell", effects=list(fx))
def TR(event, *fx, **kw): return A("triggered", event=event, effects=list(fx), **kw)
def refused(k): return any(n.startswith("gef refused") for n in k.notes) and k.status in ("partial", "blank", "land*")
NOF = {"non": frozenset(), "need": frozenset(), "cmp": ()}
TAP = {"tap": True}

# ---- mana
@check("mana: {T}: Add {C}{C} -> two colorless units")
def _(): return C("Sol Ring", A("mana", cost=TAP, produce={"units": ["C", "C"]})).units == [(frozenset("C"), g.NOC, None, False)] * 2
@check("mana: any color / commander colors -> the deck's colors")
def _():
    a = C("Birds of Paradise", A("mana", cost=TAP, produce={"units": ["any"]}), anyc=frozenset("RG"))
    b = C("Arcane Signet", A("mana", cost=TAP, produce={"units": ["commander_colors"]}), anyc=frozenset("UB"))
    return a.units == [(frozenset("RG"), g.NOC, None, False)] and b.units == [(frozenset("UB"), g.NOC, None, False)]
@check("mana: sacrifice ~ is sac_mana; a {1},{T} filter is a conversion, not free mana")
def _():
    p = C("Lotus Petal", A("mana", cost={"tap": True, "sacrifice": "self"}, produce={"units": ["any"]}))
    f = C("Mossfire Valley", A("mana", cost={"tap": True, "mana": "{1}"}, produce={"units": ["R", "G"]}))
    return p.sac_mana and not f.units and f.convs == [(1, [(frozenset("R"), g.NOC, None, False), (frozenset("G"), g.NOC, None, False)])]
@check("mana: 'Sacrifice a creature: Add {C}{C}' is a sac outlet")
def _():
    k = C("Ashnod's Altar", A("mana", cost={"sacrifice": {"filter": {"types": ["creature"]}}}, produce={"units": ["C", "C"]}))
    return len(k.sac_outlets) == 1 and k.sac_outlets[0][0]["any"][0]["type"] == "Creature" and k.sac_outlets[0][3] == "sac"
@check("mana: an exact restriction ('creature spells') is a restricted unit; an unknown phrasing is refused")
def _():
    a = C("Somberwald Sage", A("mana", cost=TAP, produce={"units": ["any_one_color"], "amount": 3, "restrict": "creature spells only"}), anyc=frozenset("G"))
    b = C("Maelstrom of the Spirit Dragon", A("mana", cost=TAP, produce={"units": ["any"], "restrict": "Spend this mana only on something odd"}))
    return a.units == [(g.NOC, frozenset("G"), "creature", False)] * 3 and refused(b)
@check("mana: a Talisman's '{T}: Add {U} or {B}, 1 damage to you' is a mana ability with pain")
def _():
    k = C("Talisman of Dominance", A("mana", cost=TAP, produce={"units": ["C"]}),
          A("activated", cost=TAP, effects=[{"do": "mana", "produce": {"units": ["UB"]}}, {"do": "damage", "n": 1, "to": "you", "source": "self"}]))
    return k.pain == 1 and k.pain_col and k.units == [(frozenset("CUB"), g.NOC, None, False)]

# ---- keywords
@check("keywords: combat ones join kw (haste too), numbered ones kwn, prowess a trigger, silent ones nothing")
def _():
    k = C("Grizzly Bears", A("keyword", keyword="flying"), A("keyword", keyword="haste"), A("keyword", keyword="toxic", n=2),
          A("keyword", keyword="prowess"), A("keyword", keyword="ward", cost="{2}"))
    return {"flying", "haste", "prowess"} <= k.kw and k.haste and k.kwn == {"toxic": 2} and k.trig[0][0] == "cast" and k.status == "modeled"
@check("keywords: equip, kicker, cycling, typecycling (card_filter), transmute, flashback, cascade")
def _():
    eq = C("Skullclamp", A("keyword", keyword="equip", cost="{1}")).equip == (1, [])
    kk = C("Grizzly Bears", A("keyword", keyword="multikicker", cost="{1}{G}")).kicker == (1, [frozenset("G")], True)
    cy = C("Grizzly Bears", A("keyword", keyword="cycling", cost="{2}")).hand_acts[0]["fx"] == [("draw", 1)]
    tc = C("Step Through", A("keyword", keyword="typecycling", cost="{2}", card_filter={"subtypes": ["Wizard"]})).hand_acts[0]
    tm = C("Ethereal Usher", A("keyword", keyword="transmute", cost="{1}{U}{U}")).hand_acts[0]["fx"][0][1].mv == ("==", 6)
    fb = C("Seize the Day", A("keyword", keyword="flashback", cost="{2}{R}")).gycast["kw"] == "flashback"
    ca = C("Bloodbraid Elf", A("keyword", keyword="cascade")).castfx == [("cascade", 4, 1)]
    return eq and kk and cy and tc["label"] == "wizardcycling" and tc["fx"][0][1].subs == {"wizard"} and tm and fb and ca
@check("keywords: 'equip commander' (a filter) and an unknown keyword are refused")
def _():
    return refused(C("Commander's Plate", A("keyword", keyword="equip", cost="{3}", filter={"commander": True}))) and \
        refused(C("Grizzly Bears", A("keyword", keyword="storm")))
@check("keywords: enchant creature sets what the Aura needs")
def _(): return C("Unquestioned Authority", A("keyword", keyword="enchant", detail="creature")).requires == "creature"

# ---- statics
@check("statics: anthem (other, attacking), attached bonus, keyword grants, lands tap for any color")
def _():
    an = C("Glorious Anthem", S({"static": "anthem", "filter": {"types": ["creature"], "controller": "you", "another": True}, "power": 1, "toughness": 1})).statics[0]
    at = C("Blast-Furnace Hellkite", S({"static": "anthem", "filter": {"types": ["creature"], "attacking": True}, "keywords": ["double strike"]})).statics[0]
    ab = C("Lightning Greaves", S({"static": "attached_bonus", "keywords": ["haste", "shroud"]})).attach
    gr = C("Garruk's Uprising", S({"static": "grant_abilities", "filter": {"types": ["creature"], "controller": "you"},
                                  "abilities": [A("keyword", keyword="trample")]})).statics[0]
    la = C("Chromatic Lantern", S({"static": "grant_abilities", "filter": {"types": ["land"], "controller": "you"},
                                  "abilities": [A("mana", cost=TAP, produce={"units": ["any"]})]})).statics
    return an[0] == "anthem" and an[5] and an[2:4] == (1, 1) and at[6] and at[4] == frozenset({"double strike"}) and \
        ab == (0, 0, frozenset({"haste", "shroud"})) and gr[4] == frozenset({"trample"}) and la == [("lands_any",)]
@check("statics: cost reduction, extra land, no max hand size, lab man, doesn't untap, enters with counters")
def _():
    cr = C("Dragonspeaker Shaman", S({"static": "cost_reduction", "spells": {"subtypes": ["Dragon"]}, "amount": 2})).statics[0]
    k = C("Grizzly Bears", S({"static": "extra_land", "n": 1}), S({"static": "no_max_hand_size"}), S({"static": "draw_from_empty_library_wins"}),
          S({"static": "doesnt_untap"}), S({"static": "enters_with_counters", "kind": "charge", "n": 3}))
    return cr[0] == "reduce" and cr[1]["sub"] == {"Dragon"} and cr[2] == 2 and ("extra_land", 1) in k.statics and ("no_max_hand",) in k.statics \
        and k.labman and k.no_untap and k.ctr_enter == ("charge", 3, False)
@check("statics: enters tapped (always / pay 3 life / unless a Mountain); another condition is read as always tapped and unread")
def _():
    a = C("Mosswort Bridge", S({"static": "enters_tapped"})).etap == ("always",)
    b = C("Fell the Profane // Fell Mire", S({"static": "enters_tapped", "unless_pay": {"pay_life": 3}})).etap == ("shock", 3)
    c = C("Arena of Glory", S({"static": "enters_tapped", "unless": {"if": "control", "filter": {"subtypes": ["Mountain"]}}})).etap == ("check", frozenset({"mountain"}))
    d = C("Cinder Glade", S({"static": "enters_tapped", "unless": {"if": "control", "filter": {"types": ["land"], "supertypes": ["basic"]}, "min": 2}}))
    return a and b and c and d.etap == ("always", "conditional") and refused(d)
@check("statics: doublers (tokens, counters, triggers by cause and by source), +1 counters, mana multiplier, free casting")
def _():
    k = C("Grizzly Bears", S({"static": "token_doubler", "factor": 2}), S({"static": "counter_doubler", "factor": 2}),
          S({"static": "trigger_doubler", "cause": "enters", "filter": {"subtypes": ["Wizard"]}}),
          S({"static": "trigger_doubler", "cause": "any", "filter": {"types": ["creature"], "another": True}}),
          S({"static": "extra_counters", "n": 1, "kind": "+1/+1", "on": {"types": ["creature"], "controller": "you"}}),
          S({"static": "mana_multiplier", "factor": 3, "sources": "permanents you tap for mana"}),
          S({"static": "free_cast", "spells": {"subtypes": ["Dragon"]}}))
    kinds = [s[0] for s in k.statics]
    tx = [s for s in k.statics if s[0] == "trig_x"]
    return kinds == ["token_mult", "ctr_times", "trig_x", "trig_x", "ctr_plus", "mana_mult", "free"] and tx[0][1] == "enter" and tx[1][1] == "src" \
        and ("ctr_plus", frozenset({"Creature"}), frozenset({"+1/+1"})) in k.statics
@check("statics: choose a creature type, ~ is the chosen type, +1/+0 per artifact (self anthem), Urborg makes itself a Swamp")
def _():
    g.CHOSEN_TYPE = "Elf"
    try:
        rt = C("Roaming Throne", S({"static": "choose_on_enter", "choice": "creature_type"}), S({"static": "type_grant", "self": True, "add_chosen_type": True}))
    finally: g.CHOSEN_TYPE = None
    sk = C("Storm-Kiln Artist", S({"static": "pt_equals", "power": {"count": "permanents_you_control", "filter": {"types": ["artifact"]}, "plus": 2}, "toughness": 2}))
    ub = C("Urborg, Tomb of Yawgmoth", S({"static": "type_grant", "filter": {"types": ["land"], "controller": "any"}, "add_types": ["Swamp"]}))
    return "Elf" in rt.subtypes and rt.status == "modeled" and sk.statics[0][1] == {"self": True} and sk.statics[0][2] == ("per", 1, ("artifacts",)) \
        and ub.units == [(frozenset("B"), g.NOC, None, False)] and refused(ub)

# ---- effects
@check("effects: draw (yours; an opponent's is nothing), discard, mill (yours / target player / an opponent's is nothing), scry, surveil")
def _():
    k = C("Opt", SP({"do": "draw", "n": 2}, {"do": "draw", "n": 1, "who": "target_opponent"}, {"do": "discard", "n": 1},
                    {"do": "mill", "n": 3}, {"do": "mill", "n": 2, "who": "target_player"}, {"do": "mill", "n": 9, "who": "each_opponent"},
                    {"do": "scry", "n": 1}, {"do": "surveil", "n": 2}))
    return k.spell == [("draw", 2), ("discard", 1), ("mill", 3), ("mill", 2, "target"), ("scry", 1), ("surveil", 2)]
@check("effects: look (take to hand / arrange on top / peek a match / dig a match / all lands onto the battlefield)")
def _():
    k = C("Opt", SP({"do": "look", "n": 3, "take": 1, "to": "hand", "rest": "bottom"}, {"do": "look", "n": 3, "take": 0, "to": "hand", "rest": "top"},
                    {"do": "look", "n": 1, "take": 1, "filter": {"types": ["creature"]}, "to": "hand", "rest": "top"},
                    {"do": "look", "n": 6, "take": 1, "filter": {"types": ["creature"]}, "to": "battlefield", "rest": "bottom"},
                    {"do": "look", "n": "X", "take": "all", "filter": {"types": ["land"]}, "to": "battlefield_tapped", "rest": "bottom"}))
    t = [e[0] for e in k.spell]
    return t == ["look", "arrange", "peek", "look_f", "reveal_lands"] and k.spell[0] == ("look", 3, 1) and k.spell[3][3] == "bf" and k.spell[4] == ("reveal_lands", "X")
@check("effects: tutor (Target), land search (basic / types / Cultivate's split), recur, wheel, put back")
def _():
    k = C("Opt", SP({"do": "tutor", "filter": {"types": ["artifact", "enchantment"]}, "to": "library_top"},
                    {"do": "tutor", "filter": {"types": ["land"], "supertypes": ["basic"]}, "n": 2, "split": [{"n": 1, "to": "battlefield_tapped"}, {"n": 1, "to": "hand"}]},
                    {"do": "tutor", "filter": {"types": ["land"], "any_of": [{"subtypes": ["Island"]}, {"subtypes": ["Swamp"]}]}, "to": "battlefield_tapped"},
                    {"do": "recur", "filter": {"types": ["creature"]}, "n": 1, "to": "battlefield"},
                    {"do": "wheel", "n": 7}, {"do": "put_back", "n": 2, "to": "library_top"}))
    s = k.spell
    return s[0][0] == "tutor" and s[0][1].types == {"artifact", "enchantment"} and s[0][2] == "top" and s[1] == ("land_search", 2, (True, frozenset()), "split") \
        and s[2] == ("land_search", 1, (False, frozenset({"island", "swamp"})), "bf_t") and s[3][0] == "recur" and s[3][2] == "bf" \
        and s[4] == ("wheel", 7, False) and s[5] == ("putback", 2, False)
@check("effects: a tutor of the library and/or graveyard, or to a position in the library, is refused")
def _():
    return refused(C("Opt", SP({"do": "tutor", "filter": {"any": True}, "to": "hand", "from": ["library", "graveyard"]}))) and \
        refused(C("Opt", SP({"do": "tutor", "filter": {"any": True}, "to": "library_top", "position": 3})))
@check("effects: mana (ritual, X in any combination of attackers' power), extra land, free cast up to mana value 5, free_top")
def _():
    r = C("Dark Ritual", SP({"do": "mana", "produce": {"units": ["B", "B", "B"]}})).spell == [("mana", [frozenset("B")] * 3)]
    x = C("Opt", SP({"do": "mana", "produce": {"units": ["any"], "amount": {"count": "total_power", "filter": {"attacking": True}}, "any_combination": True}}))
    f = C("Opt", SP({"do": "extra_land", "n": 1}, {"do": "cast_free", "filter": {"mana_value": {"max": 5}}, "from": "hand"}))
    ft = C("Opt", SP({"do": "reveal_until", "filter": {"non_types": ["land"]}, "rest": "exile", "then": [{"do": "if",
        "cond": {"if": "not", "cond": {"if": "amount_at_least", "amount": {"count": "mana_value_of_that"}, "n": 9}},
        "then": [{"do": "cast_free", "filter": {"any": True}, "from": "exile"}], "else": [{"do": "recur", "filter": {"any": True}, "n": 1, "to": "hand", "from": "exile"}]}]}))
    return r and x.spell == [("mana_x", ("atkpow",))] and f.spell == [("extra_land", 1), ("free_cast", 5)] and ft.spell == [("free_top", 8)]
@check("effects: tokens (creature, Treasure, Clue, Food); a token with its own abilities is refused")
def _():
    k = C("Opt", SP({"do": "token", "n": 2, "token": {"types": ["creature"], "subtypes": ["Soldier"], "power": 1, "toughness": 1}},
                    {"do": "token", "n": 1, "token": {"preset": "treasure"}}, {"do": "token", "n": 1, "token": {"preset": "clue"}},
                    {"do": "token", "n": 1, "token": {"preset": "food"}}))
    bad = C("Opt", SP({"do": "token", "n": 1, "token": {"types": ["creature"], "power": 1, "toughness": 1, "abilities": [A("keyword", keyword="flying")]}}))
    return k.spell[0] == ("token", 2, 1, ("Soldier",), "", "creature", 1, frozenset(), False) and k.spell[1] == ("treasure", 1, False) \
        and k.spell[2][3] == ("Clue",) and k.spell[3][3] == ("Food",) and refused(bad)
@check("effects: counters on ~, proliferate, pumps (~, target, the trigger's object, team with filters), -N/-N on a target is removal")
def _():
    k = C("Opt", SP({"do": "counters", "kind": "+1/+1", "n": 2, "on": {"ref": "self"}}, {"do": "proliferate"},
                    {"do": "pump", "target": {"ref": "target", "filter": {"types": ["creature"]}}, "power": 3, "toughness": 3, "duration": "end_of_turn"},
                    {"do": "pump", "target": {"ref": "it"}, "keywords": ["haste"], "duration": "end_of_turn"},
                    {"do": "pump_team", "filter": {"types": ["creature"], "controller": "you", "another": True}, "power": 1, "toughness": 0,
                     "keywords": ["trample"], "duration": "end_of_turn"},
                    {"do": "pump", "target": {"ref": "target", "filter": {"types": ["creature"]}}, "power": -1, "toughness": -1, "duration": "end_of_turn"}))
    s = k.spell
    return s[0] == ("ctr", "+1/+1", 2) and s[1] == ("prolif", 1) and s[2] == ("pump", "target", 3, 3, frozenset()) and s[3] == ("pump", "obj", 0, 0, frozenset({"haste"})) \
        and s[4][0] == "pump_team" and s[4][5] is True and s[5] == ("kill_blk", "minus", 1, 1, NOF, False, False)
@check("effects: a team pump by power is refused (the engine checks printed power)")
def _():
    return refused(C("Opt", SP({"do": "pump_team", "filter": {"types": ["creature"], "power": {"min": 4}}, "power": 1, "toughness": 1, "duration": "end_of_turn"})))
@check("effects: damage and life (each / one opponent, you, life costs as ('life', -n)), win, ~ back to hand / on top")
def _():
    k = C("Opt", SP({"do": "damage", "n": 2, "to": "each_opponent"}, {"do": "lose_life", "n": 3, "who": "target_player"},
                    {"do": "lose_life", "n": 2, "who": "you"}, {"do": "gain_life", "n": 4}, {"do": "win_game"}, {"do": "bounce_self"},
                    {"do": "self_to_library", "where": "top"}))
    return k.spell == [("face", 2, "each", True), ("face", 3, "one", False), ("life", -2), ("life", 4), ("win",), ("bounce_self",), ("self_top",)]
@check("effects: burn to any target is held (Lightning Bolt); damage to a target creature is a blocker kill")
def _():
    b = C("Lightning Bolt", SP({"do": "damage", "n": 3, "to": "any_target"}))
    m = C("Opt", SP({"do": "damage", "n": 4, "to": "target_creature"}))
    return b.hold and b.burn_blk and "creature" in b.kill and m.spell == [("kill_blk", "dmg", 1, 4, NOF, False, False)]
@check("effects: removal (creature / permanent -> blocker kill; artifact -> kill_perm; StP's life; a body back is no blocker kill)")
def _():
    sw = C("Swords to Plowshares", SP({"do": "remove", "how": "exile", "target": {"ref": "target", "filter": {"types": ["creature"]}},
                                       "controller_compensation": "its controller gains life equal to its power"}))
    at = C("Assassin's Trophy", SP({"do": "remove", "how": "destroy", "target": {"ref": "target", "filter": {"types": ["permanent"], "controller": "opponent"}}}))
    va = C("Vandalblast", SP({"do": "remove", "how": "destroy", "target": {"ref": "target", "filter": {"types": ["artifact"]}}}))
    bw = C("Beast Within", SP({"do": "remove", "how": "destroy", "target": {"ref": "target", "filter": {"types": ["permanent"]}},
                               "controller_compensation": "its controller creates a 3/3 green Beast creature token"}))
    return sw.spell == [("kill_blk", "exile", 1, None, NOF, True, False)] and sw.hold and at.spell[0][0] == "kill_blk" \
        and at.kill == frozenset({"creature", "artifact", "enchantment"}) and va.spell == [("kill_perm", frozenset({"artifact"}))] and bw.spell == [] and bw.hold
@check("effects: a counterspell / protection is a held answer; an instant giving indestructible is a protect answer")
def _():
    cs = C("Counterspell", SP({"do": "counter_spell"}))
    hi = C("Heroic Intervention", SP({"do": "protect", "target": {"ref": "each", "filter": {"types": ["permanent"], "controller": "you"}},
                                      "grant": ["hexproof", "indestructible"], "duration": "end_of_turn"}))
    fm = C("Flawless Maneuver", SP({"do": "pump_team", "filter": {"types": ["creature"], "controller": "you"}, "keywords": ["indestructible"], "duration": "end_of_turn"}))
    return cs.answer == "counter" and cs.hold and hi.answer == "protect" and fm.answer == "protect" and fm.hold
@check("effects: untap (~ / up to three lands), extra combat (with untapping the attackers)")
def _():
    k = C("Opt", SP({"do": "untap", "what": {"ref": "self"}}, {"do": "untap", "what": {"ref": "target", "n": 3, "up_to": True, "filter": {"types": ["land"]}}},
                    {"do": "extra_combat", "n": 1, "untap": "attackers", "then_main": True}))
    return k.spell == [("untap_self",), ("untap_n_lands", 3), ("untap_cr", "attacked"), ("extra_combat",)]
@check("effects: if (a condition the engine reads), may pay (mana / discard / sacrifice ~ / life), if/else refused")
def _():
    k = C("Opt", SP({"do": "if", "cond": {"if": "life_at_least", "n": 30}, "then": [{"do": "draw", "n": 1}]},
                    {"do": "may_pay", "cost": {"mana": "{4}"}, "then": [{"do": "untap", "what": {"ref": "self"}}]},
                    {"do": "may_pay", "cost": {"discard": {"n": 1}}, "then": [{"do": "draw", "n": 2}]},
                    {"do": "may_pay", "cost": {"sacrifice": "self"}, "then": [{"do": "draw", "n": 1}], "else": [{"do": "gain_life", "n": 1}]}))
    e = C("Opt", SP({"do": "if", "cond": {"if": "your_turn"}, "then": [{"do": "draw", "n": 1}], "else": [{"do": "scry", "n": 1}]}))
    s = k.spell
    return s[0] == ("cond", ("life", 30), [("draw", 1)]) and s[1] == ("paid", 4, [], [("untap_self",)]) and s[2] == ("ifdo", ("discard", 1, None), [("draw", 2)], []) \
        and s[3] == ("ifdo", ("sac_self",), [("draw", 1)], [("life", 1)]) and refused(e)
@check("effects: choose one -> the parser's best mode (MODE_RANK); 'one or more' in a trigger -> each mode optional")
def _():
    one = C("Opt", SP({"do": "choose", "n": 1, "modes": [[{"do": "gain_life", "n": 3}], [{"do": "draw", "n": 1}]]}))
    ttt = C("Black Market Connections", TR({"on": "precombat_main", "whose": "your"}, {"do": "choose", "n": 3, "up_to": True, "modes": [
        [{"do": "token", "n": 1, "token": {"preset": "treasure"}}, {"do": "lose_life", "n": 1, "who": "you"}],
        [{"do": "draw", "n": 1}, {"do": "lose_life", "n": 2, "who": "you"}]]}))
    return one.spell == [("draw", 1)] and ttt.trig[0][2] == [("opt", [("draw", 1), ("life", -2)]), ("opt", [("treasure", 1, False), ("life", -1)])]

# ---- triggers, activations, costs
@check("events: enters (~ -> etb, a land -> landfall, others -> etb filter), dies, attacks, combat damage, cast, phases")
def _():
    k = C("Grizzly Bears", TR({"on": "enters", "subject": "self"}, {"do": "draw", "n": 1}),
          TR({"on": "enters", "subject": {"types": ["land"], "controller": "you"}}, {"do": "gain_life", "n": 1}),
          TR({"on": "enters", "subject": {"types": ["creature"], "another": True}}, {"do": "draw", "n": 1}),
          TR({"on": "dies", "subject": "self"}, {"do": "draw", "n": 1}), TR({"on": "dies", "subject": "equipped"}, {"do": "draw", "n": 2}),
          TR({"on": "attacks", "subject": "self"}, {"do": "draw", "n": 1}), TR({"on": "you_attack"}, {"do": "draw", "n": 1}),
          TR({"on": "combat_damage_to_player", "subject": {"types": ["creature"]}, "one_or_more": True}, {"do": "draw", "n": 1}),
          TR({"on": "cast", "who": "you", "spell": {"non_types": ["creature"]}}, {"do": "scry", "n": 1}),
          TR({"on": "upkeep", "whose": "your"}, {"do": "draw", "n": 1}), TR({"on": "end_step", "whose": "your"}, {"do": "draw", "n": 1}))
    evs = [t[0] for t in k.trig]
    return k.etb == [("draw", 1)] and evs == ["landfall", "etb", "dies_self", "dies_att", "attack_self", "attack_any", "cdmg_any", "cast", "upkeep", "end"] \
        and k.trig[1][1]["another"] and k.trig[7][1]["non"] == {"Creature"}
@check("events: an opponent's turn phase, or a 'first spell each turn' trigger, is refused")
def _():
    return refused(C("Grizzly Bears", TR({"on": "upkeep", "whose": "each"}, {"do": "draw", "n": 1}))) and \
        refused(C("Grizzly Bears", TR({"on": "cast", "who": "you", "first_each_turn": True}, {"do": "draw", "n": 1})))
@check("triggers: intervening if, once per turn, an opponent's tax (Rhystic Study, Smothering Tithe)")
def _():
    k = C("Grizzly Bears", TR({"on": "end_step", "whose": "your"}, {"do": "draw", "n": 1}, **{"if": {"if": "hand_at_most", "n": 1}}),
          TR({"on": "cast", "who": "you"}, {"do": "scry", "n": 1}, once_per_turn=True),
          TR({"on": "opponent_casts"}, {"do": "unless_opponent_pays", "cost": "{1}", "effects": [{"do": "draw", "n": 1}]}),
          TR({"on": "opponent_draws"}, {"do": "unless_opponent_pays", "cost": "{2}", "effects": [{"do": "token", "n": 1, "token": {"preset": "treasure"}}]}))
    t = k.trig
    return t[0][2] == [("cond", ("hand_le", 1), [("draw", 1)])] and t[1][3] and t[2][:5] == ("opp_cast", None, [("draw", 1)], False, True) and t[3][0] == "opp_draw" and t[3][4]
@check("activations: mana, tap, sacrifice ~ or another (fodder), remove counters, life; loyalty abilities")
def _():
    k = C("Goblin Engineer", A("activated", cost={"mana": "{R}", "tap": True, "sacrifice": {"filter": {"types": ["artifact"]}}}, effects=[{"do": "draw", "n": 1}]),
          A("activated", cost={"mana": "{1}", "remove_counters": {"kind": "charge", "n": 1, "from": "self"}, "pay_life": 2}, effects=[{"do": "scry", "n": 1}]),
          A("activated", cost={"sacrifice": "self"}, effects=[{"do": "gain_life", "n": 3}], sorcery_speed=True))
    j = C("Jace, Wielder of Mysteries", A("loyalty", cost=1, effects=[{"do": "draw", "n": 1}]))
    a = k.acts
    return a[0]["tap"] and a[0]["pips"] == [frozenset("R")] and a[0]["fodder"]["any"][0]["type"] == "Artifact" and a[1]["rm"] == ("charge", 1) \
        and a[1]["life"] == 2 and a[2]["sac"] and a[2]["sorcery"] and j.pw == [(1, [("draw", 1)])]
@check("costs: additional costs (pay life, sacrifice -> addsac, discard first), free with a commander (alt cost)")
def _():
    dd = C("Deadly Dispute", A("additional_cost", cost={"sacrifice": {"filter": {"any_of": [{"types": ["artifact"]}, {"types": ["creature"]}]}}}),
           SP({"do": "draw", "n": 2}))
    bs = C("Big Score", A("additional_cost", cost={"discard": {"n": 1}}), SP({"do": "draw", "n": 2}))
    fg = C("Deflecting Swat", A("alt_cost", cost={"mana": "{0}"}, **{"if": {"if": "you_control_commander"}}))
    return len(dd.addsac["any"]) == 2 and bs.spell == [("discard", 1), ("draw", 2)] and fg.free_cmdr

# ---- status and refusal
@check("status: unexpressible out_of_scope is never a miss; format_gap is; a refused ability leaves the rest read")
def _():
    v = C("Counterbalance", A("unexpressible", reason="opponents' spells", scope="out_of_scope"))
    p = C("Grizzly Bears", A("keyword", keyword="flying"), A("unexpressible", reason="x", scope="format_gap"))
    r = C("Grizzly Bears", TR({"on": "enters", "subject": "self"}, {"do": "draw", "n": 1}), TR({"on": "enters", "subject": "self"}, {"do": "set_life", "n": 10}))
    return v.status == "vacuum" and p.status == "partial" and r.etb == [("draw", 1)] and r.status == "partial" and any("set_life" in n for n in r.notes)
@check("loader: data/gef/ loads and validates every translation; goldfish.py --gef reads them (override > GEF > parser)")
def _():
    cards, rejects = gc.load()
    import subprocess
    out = subprocess.run([sys.executable, "scripts/goldfish.py", "translation/decks/zur.txt", "--gef", "--explain"], capture_output=True, text=True, encoding="utf-8")
    return len(cards) >= 300 and not rejects and out.returncode == 0 and "Necrodominance" in out.stdout

def main():
    fails = 0
    for name, fn in CHECKS:
        try: ok = bool(fn())
        except Exception as e: ok = False; name += f" (raised {type(e).__name__}: {e})"
        if not ok: fails += 1; print("FAIL  " + name)
    print(f"gef units: all {len(CHECKS)} passed" if not fails else f"gef units: {fails} of {len(CHECKS)} failed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
