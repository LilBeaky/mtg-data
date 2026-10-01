#!/usr/bin/env python3
"""GEF -> goldfish.py engine structures (T3 step 2 of the translation track; docs/GOLDFISH_EFFECT_FORMAT.md).

  python3 scripts/gef_compile.py [NAME ...]        # compile cards from data/gef/*.json and show what each became
  python3 scripts/gef_compile.py --report          # every GEF card: status, and why each refused ability was refused

A validated GEF translation compiles into the same Card fields compile_card fills from Oracle text (spell, etb, trig,
acts, statics, units, kw ...). It maps only constructs the engine runs exactly; anything else raises Refuse, and that
ability is unread (the card says partial or blank with a 'gef refused' note), never approximated. The card's
metadata (types, cost, P/T, colors) still comes from the card data, through compile_card on the card with no rules
text. Precedence in goldfish.py (--gef): override > GEF > parser.
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mtg                                               # noqa: E402
import goldfish as g                                     # noqa: E402
import tutors as tu                                      # noqa: E402

GEF_DIR = os.path.join(REPO, "data", "gef")

class Refuse(Exception):
    pass

def refuse(why): raise Refuse(why)

def load(path=GEF_DIR, validate=True):
    """norm(name) -> GEF card, from every *.json in path (a card or a list of cards). With validate, a translation the
    validator rejects is skipped (its card falls back to the parser) and listed in the returned rejects."""
    out, rejects = {}, []
    files = sorted(glob.glob(os.path.join(path, "*.json")))
    V = None
    if validate and files:
        sys.path.insert(0, os.path.join(REPO, "translation"))
        import validate as V                             # noqa: F811
    for f in files:
        data = json.load(open(f, encoding="utf-8"))
        for x in (data if isinstance(data, list) else [data]):
            if V:
                errs, _ = V.validate(x, mtg)
                if errs: rejects.append((x.get("name"), errs[0])); continue
            out[mtg.norm(x["name"])] = x
    return out, rejects

# ---------------------------------------------------------------- values
TYPE_CAP = {t.lower(): t for t in g.TYPES}

def zone(z, ok=("hand", "bf", "bf_t", "top", "graveyard")):
    d = {"hand": "hand", "battlefield": "bf", "battlefield_tapped": "bf_t", "library_top": "top", "graveyard": "graveyard"}.get(z)
    if d not in ok: refuse(f"zone {z}")
    return d

def colors(s, anyc):
    """A GEF color set ('G', 'WU', 'any', 'commander_colors', 'C') -> engine unit colors."""
    if s in ("any", "any_one_color", "commander_colors"): return anyc
    if s == "chosen_color": refuse("chosen color")
    return frozenset(s)

def perm_filter(f, allow_controller=("you", "any", None)):
    """GEF PermFilter -> the engine's permanent filter (perm_filt's shape, read by Game.pmatch)."""
    f = dict(f or {})
    if f.get("controller") not in allow_controller: refuse(f"filter controller {f.get('controller')}")
    if f.get("any_of"):
        rest = {k: v for k, v in f.items() if k not in ("any_of", "controller")}
        if rest: refuse("any_of with other fields")
        return {"any": [perm_filter(x, allow_controller) for x in f["any_of"]]}
    known = {"types", "all_types", "subtypes", "non_types", "non_subtypes", "supertypes", "colors", "colorless", "controller",
             "another", "token", "nontoken", "power", "equipped", "enchanted", "modified", "historic", "commander", "chosen_type",
             "with_counters", "keywords"}
    extra = set(f) - known
    if extra: refuse("filter " + ", ".join(sorted(extra)))
    types = [TYPE_CAP.get(t) for t in f.get("types", []) if t != "permanent"]
    if None in types: refuse("filter type")
    out = {"type": "Permanent", "another": bool(f.get("another")), "power": 0, "sub": set(f.get("subtypes", [])),
           "nontoken": bool(f.get("nontoken")), "token": bool(f.get("token")), "colors": set(f.get("colors", [])),
           "legendary": "legendary" in f.get("supertypes", [])}
    if len(types) > 1:
        if f.get("all_types"): out["alltypes"] = frozenset(types); out["type"] = types[0]
        else:
            return {"any": [perm_filter(dict(f, types=[t.lower()]), allow_controller) for t in types]}
    elif types: out["type"] = types[0]
    if f.get("chosen_type"): out["sub"] |= {g.CHOSEN_TYPE or "Chosen"}
    sup = set(f.get("supertypes", [])) - {"legendary"}
    if sup - {"basic", "nonlegendary"}: refuse("filter supertype")
    if "basic" in sup: out["basic"] = True
    if "nonlegendary" in sup: out["nonleg"] = True
    non = [TYPE_CAP.get(t) for t in f.get("non_types", [])]
    if len(non) > 1 or None in non: refuse("filter non_types")
    if non: out["nontype"] = non[0]
    if len(f.get("non_subtypes", [])) > 1: refuse("filter non_subtypes")
    if f.get("non_subtypes"): out["nonsub"] = f["non_subtypes"][0]
    pw = f.get("power")
    if pw:
        if set(pw) - {"min", "max"} or ("min" in pw and "max" in pw): refuse("filter power range")
        if "min" in pw: out["power"] = pw["min"]
        else: out["pow_max"] = pw["max"]
    for q in ("equipped", "enchanted", "modified", "historic", "colorless", "commander"):
        if f.get(q): out[q] = True
    if f.get("with_counters"): out["ctr"] = "+1/+1" if f["with_counters"] == "+1/+1" else "any"
    kws = f.get("keywords", [])
    if kws:
        if len(kws) > 1 or not isinstance(kws[0], str) or kws[0] not in g.COMBAT_KW: refuse("filter keywords")
        out["kw"] = kws[0]
    return out

def spell_filter(f):
    """GEF CardFilter -> the engine's spell filter (parse_filter's shape, read by spell_ok)."""
    f = dict(f or {})
    if f.get("any"):
        if len(f) > 1: refuse("any with other fields")
        return None
    extra = set(f) - {"types", "non_types", "subtypes", "supertypes", "colors", "multicolored", "historic", "mana_value", "chosen_type", "power"}
    if extra: refuse("spell filter " + ", ".join(sorted(extra)))
    out = {"types": set(), "non": set(), "legendary": False, "colors": set(f.get("colors", [])), "multi": bool(f.get("multicolored")),
           "historic": bool(f.get("historic")), "mv_max": None, "unknown": False, "sub": set(f.get("subtypes", []))}
    for t in f.get("types", []):
        if t == "permanent": out["types"] |= g.PERMANENT
        elif TYPE_CAP.get(t): out["types"].add(TYPE_CAP[t])
        else: refuse("spell type " + t)
    for t in f.get("non_types", []):
        if not TYPE_CAP.get(t): refuse("spell non_type " + t)
        out["non"].add(TYPE_CAP[t])
    sup = set(f.get("supertypes", []))
    if sup - {"legendary"}: refuse("spell supertype")
    out["legendary"] = "legendary" in sup
    if f.get("chosen_type"): out["sub"] |= {g.CHOSEN_TYPE or "Chosen"}
    mv = f.get("mana_value")
    if mv:
        if set(mv) != {"max"} or not isinstance(mv["max"], int): refuse("spell mana value")
        out["mv_max"] = mv["max"]
    pw = f.get("power")
    if pw:
        if set(pw) != {"min"}: refuse("spell power range")
        out["pow_min"] = pw["min"]
    return out

def target(f, self_mv=None):
    """GEF CardFilter -> tutors.Target (what a search or recursion can find)."""
    f = dict(f or {})
    t = tu.Target()
    if f.get("any_of"):                                  # shared fields go into each alternative
        shared = {k: v for k, v in f.items() if k != "any_of"}
        if any(set(x) & set(shared) for x in f["any_of"]): refuse("any_of overlapping fields")
        for key in ("types", "subtypes"):
            if all(set(x) == {key} for x in f["any_of"]):
                return target({**shared, key: [v for x in f["any_of"] for v in x[key]]})
        t.alts = [target({**shared, **x}) for x in f["any_of"]]; return t
    extra = set(f) - {"any", "types", "non_types", "subtypes", "non_subtypes", "supertypes", "colors", "colorless", "multicolored",
                      "mana_value", "power", "toughness", "name", "not_name", "permanent", "historic"}
    if extra: refuse("card filter " + ", ".join(sorted(extra)))
    t.any = bool(f.get("any"))
    t.types = {x for x in f.get("types", []) if x != "permanent"}
    if "permanent" in f.get("types", []) or f.get("permanent"): t.permanent = True
    t.non = set(f.get("non_types", []))
    sup = set(f.get("supertypes", []))
    if sup - {"legendary", "basic", "snow"}: refuse("card supertype")
    t.supers = sup
    t.subs = {s.lower() for s in f.get("subtypes", [])}
    t.non_subs = {s.lower() for s in f.get("non_subtypes", [])}
    t.colors = set(f.get("colors", [])); t.colorless = bool(f.get("colorless")); t.multicolored = bool(f.get("multicolored"))
    t.historic = bool(f.get("historic"))
    for key, attr in (("mana_value", "mv"), ("power", "power"), ("toughness", "tough")):
        r = f.get(key)
        if not r: continue
        if key == "mana_value" and r == {"max": "X"}: t.approx.append("mana value x or less"); continue   # Green Sun's Zenith: X caps it
        if len(r) != 1 or not isinstance(next(iter(r.values())), int): refuse(f"card {key} range")
        op = {"max": "<=", "min": ">=", "eq": "=="}[next(iter(r))]
        setattr(t, attr, (op, next(iter(r.values()))))
    if f.get("name"): t.named = f["name"].lower()
    if f.get("not_name"): t.not_named = {f["not_name"].lower()}
    return t

def land_search(f):
    """A search for lands only (basic / basic types) -> land_search's filter, else None."""
    if f.get("any_of") and all(set(x) == {"subtypes"} for x in f["any_of"]):
        f = {**{k: v for k, v in f.items() if k != "any_of"}, "subtypes": [v for x in f["any_of"] for v in x["subtypes"]]}
    if set(f) - {"types", "supertypes", "subtypes"} or f.get("types") not in (["land"], None) or set(f.get("supertypes", [])) - {"basic"}:
        return None
    if not f.get("types") and not f.get("subtypes"): return None
    subs = {s.lower() for s in f.get("subtypes", [])}
    if subs - set(g.BASIC): return None
    return ("basic" in f.get("supertypes", []), frozenset(subs))

def amount(a, allow_x=True):
    """GEF Amount -> an engine amount: an int, 'X', or a dyn key Game.val reads."""
    if isinstance(a, int): return a
    if a == "X":
        if not allow_x: refuse("X")
        return "X"
    if not isinstance(a, dict): refuse("amount")
    if set(a) - {"count", "filter", "card_filter", "colors", "times", "kind", "player"}: refuse("amount " + ", ".join(sorted(set(a) - {"count"})))
    if "player" in a and a["count"] != "cards_in_opponent_hand": refuse("count of another player")
    key = count_key(a)
    return ("per", a["times"], key) if a.get("times") else key

def count_key(a):
    c, f, cf = a["count"], a.get("filter") or {}, a.get("card_filter") or {}
    if c == "permanents_you_control":
        if f.get("controller") not in (None, "you"): refuse("count controller")
        simple = {k: v for k, v in f.items() if k != "controller"}
        if set(simple) <= {"types"} and len(simple.get("types", [])) <= 1:
            t = (simple.get("types") or ["permanent"])[0]
            key = {"creature": "creatures", "land": "lands", "artifact": "artifacts", "enchantment": "enchantments", "permanent": "permanents"}.get(t)
            if key: return (key,)
        if set(simple) == {"subtypes"} and len(simple["subtypes"]) == 1: return ("sub", simple["subtypes"][0])
        return ("pcount", perm_filter(f))
    if c == "cards_in_hand": return ("hand",)
    if c == "cards_in_graveyard":
        if not cf: return ("gy",)
        if cf == {"types": ["creature"]}: return ("gy_creature",)
        if cf == {"types": ["land"]}: return ("gy_land",)
        if cf == {"types": ["instant", "sorcery"]}: return ("gy_instsorc",)
        refuse("graveyard count filter")
    if c == "devotion":
        cols = a.get("colors") or ""
        if not re.fullmatch(r"[WUBRG]{1,2}", cols): refuse("devotion colors")
        return ("devotion",) + tuple(cols)
    if c == "coin_flips_won": return ("flips_won",)
    if c == "toughness_of_self" and not f: return ("tgh",)
    if c == "spells_cast_this_turn" and not cf: return ("tcast_n",)
    if c == "greatest_toughness" and (not f or {k: v for k, v in f.items() if k != "controller" or v != "you"} in ({}, {"types": ["creature"]})):
        return ("tough_max",)
    if c == "number_chosen": return ("num_chosen",)
    simple = {"domain": ("domain",), "converge": ("converge",), "times_kicked": ("kicks",), "opponents": ("opps",),
              "your_life_total": ("life",), "power_of_self": ("pow",), "power_of_that": ("objpow",),
              "cards_in_opponent_hand": ("opp_hand",)}
    if c in simple and not f and not cf: return simple[c]
    if c == "counters_on_self" and a.get("kind"): return ("ctr", a["kind"])
    if c == "total_power" and f == {"attacking": True}: return ("atkpow",)
    if c == "greatest_power":
        f2 = {k: v for k, v in f.items() if k != "controller" or v != "you"}
        if not f2 or f2 == {"types": ["creature"]}: return ("power",)
        if set(f2) == {"types", "non_subtypes"} and f2["types"] == ["creature"] and len(f2["non_subtypes"]) == 1: return ("power", f2["non_subtypes"][0])
    refuse("count " + c)

# ---------------------------------------------------------------- effects
OPP = ("each_opponent", "target_opponent", "an_opponent", "defending_player", "that_player", "each_other_opponent")

def effects(fx, ctx):
    out = []
    for i, e in enumerate(fx or []):
        nxt = (fx[i + 1] if i + 1 < len(fx) else {}) if e["do"] == "choose_number" else {}
        ctx.next_loss = sum(x["n"] for x in nxt.get("on_lose", []) if x["do"] in ("damage", "lose_life") and isinstance(x.get("n"), int)
                            and (x.get("to") == "you" or x.get("who") == "you")) if nxt.get("do") == "flip_coins" else 0
        out += effect(e, ctx)
        ctx.last = e["do"]
    return out

def effect(e, ctx):
    d = e["do"]
    who = e.get("who")
    if d == "unexpressible":
        if e.get("scope") == "out_of_scope": return []
        refuse("unexpressible part: " + e.get("reason", "")[:60])
    if d == "draw":
        if who in OPP + ("its_controller",): return []           # an opponent draws: nothing in a goldfish
        if who not in (None, "you"): refuse(f"draw who {who}")
        return [("draw", amount(e["n"]))]
    if d == "discard":
        if who not in (None, "you") or e.get("filter") or not isinstance(e["n"], int): refuse("discard form")
        return [("discard_rand" if e.get("random") else "discard", e["n"])]
    if d == "mill":
        if who in OPP: return []                                  # an opponent's library: nothing in a goldfish
        if who == "target_player": return [("mill", amount(e["n"]), "target")]
        if who in (None, "you") and isinstance(e["n"], int): return [("mill", e["n"])]
        refuse("mill form")
    if d in ("scry", "surveil"): return [(d, amount(e["n"]))]
    if d == "look":
        if e.get("from", "library") != "library": refuse("look form")
        take, to, rest, f = e["take"], e["to"], e.get("rest"), e.get("filter")
        if not isinstance(e["n"], int) and not (take == "all" and f == {"types": ["land"]}): refuse("look count")
        if take == "all" and f == {"types": ["land"]} and to == "battlefield_tapped" and rest == "bottom": return [("reveal_lands", amount(e["n"]))]
        if take == 0 and rest == "top": return [("arrange", e["n"])]
        if not f and isinstance(take, int) and to == "hand" and rest in ("bottom", "graveyard", "shuffle", None): return [("look", e["n"], take)]
        if f and take == 1 and e["n"] == 1 and to == "hand" and rest == "top": return [("peek", spell_filter(f))]
        if f and take == 1 and to in ("hand", "battlefield") and rest in ("bottom", "shuffle"):
            return [("look_f", e["n"], target(f), "bf" if to == "battlefield" else "hand")]
        refuse("look form")
    if d == "tutor":
        if set(e.get("from", ["library"])) != {"library"}: refuse("tutor from " + "/".join(e["from"]))
        if "position" in e and e.get("to") != "library_top": refuse("library position")
        n = e.get("n", 1)
        if not isinstance(n, int): refuse("tutor count")
        ls = land_search(e["filter"])
        if "split" in e:
            sp = sorted((x["to"], x["n"]) for x in e["split"])
            if ls and sp == [("battlefield_tapped", 1), ("hand", 1)]: return [("land_search", 2, ls, "split")]
            refuse("split tutor")
        dest = zone(e["to"])
        if e.get("position", 1) > 1: dest = f"top{e['position']}"
        if ls and dest != "graveyard": return [("land_search", n, ls, dest)]
        return [("tutor", target(e["filter"]), dest, n)]
    if d == "recur":
        if e.get("from", "your_graveyard") not in ("your_graveyard", "any_graveyard") or not isinstance(e.get("n", 1), int): refuse("recur form")
        return [("recur", target(e["filter"]), zone(e["to"], ("hand", "bf", "top")), e.get("n", 1))]
    if d == "wheel":
        if who not in (None, "you", "each_player") or not isinstance(e["n"], int): refuse("wheel form")
        return [("wheel", e["n"], bool(e.get("shuffle_graveyard")))]
    if d == "put_back":
        if not isinstance(e["n"], int): refuse("put_back count")
        return [("putback", e["n"], e["to"] == "library_bottom")]
    if d == "mana":
        p = e["produce"]
        if set(p) - {"units", "amount", "any_combination"}: refuse("mana " + ", ".join(sorted(set(p) - {"units"})))
        units = [colors(u, ctx.anyc) for u in p["units"]]
        if "amount" in p:
            a = amount(p["amount"], allow_x=False)
            if len(units) != 1: refuse("mana amount with several units")
            if p.get("any_combination") and units[0] == ctx.anyc: return [("mana_x", a)]
            return [("mana_n", units, a)]
        return [("mana", units)]
    if d == "extra_land": return [("extra_land", e["n"])]
    if d == "cast_free":
        f = e["filter"]
        if e["from"] != "hand" or e.get("n", 1) != 1 or set(f) != {"mana_value"} or set(f["mana_value"]) != {"max"}: refuse("cast_free form")
        return [("free_cast", amount(f["mana_value"]["max"]))]
    if d == "token": return [token(e, ctx)]
    if d == "counters":
        on = e["on"]
        if e.get("remove"): refuse("remove counters")
        if on.get("ref") == "self" and not on.get("filter"): return [("ctr", e["kind"], amount(e["n"]))]
        refuse("counters on " + on.get("ref", "?"))
    if d == "proliferate": return [("prolif", e.get("n", 1))]
    if d == "pump":
        if e["duration"] != "end_of_turn": refuse("pump duration " + e["duration"])
        tg = e["target"]
        who_ = {"self": "self", "that": "obj", "it": "obj", "equipped": "attach", "enchanted": "attach", "attached": "attach",
                "attackers": "attackers"}.get(tg["ref"])
        if tg["ref"] == "target":
            if tg.get("n", 1) != 1 or (tg.get("filter") or {}).get("controller") not in (None, "you", "any"): refuse("pump target form")
            who_ = "target"
        if not who_: refuse("pump target " + tg["ref"])
        pw, tg_ = pump_amt(e.get("power", 0)), pump_amt(e.get("toughness", 0))
        kws = keywords(e.get("keywords"))
        if who_ == "target" and isinstance(pw, int) and isinstance(tg_, int) and tg_ < 0 and pw <= 0 and not kws:
            ctx.interaction = True
            return [("kill_blk", "minus", 1, -tg_, {"non": frozenset(), "need": frozenset(), "cmp": ()}, False, False)]
        if pw == 0 and tg_ == 0 and kws == frozenset({"unblockable"}) and who_ in ("self", "obj", "target"): return [("unblock", who_)]
        return [("pump", who_, pw, tg_, kws)]
    if d == "pump_team":
        if e["duration"] != "end_of_turn": refuse("pump_team duration")
        f = dict(e.get("filter") or {"types": ["creature"]})
        if f.get("controller") not in (None, "you"): refuse("pump_team controller")
        other, atk = bool(f.pop("another", False)), bool(f.pop("attacking", False))
        f.pop("controller", None)
        if f.get("power"): refuse("pump_team power filter")       # the engine checks printed power, not current
        if not f.get("types"): f["types"] = ["creature"]
        sf = spell_filter({k: v for k, v in f.items()})
        return [("pump_team", pump_amt(e.get("power", 0)), pump_amt(e.get("toughness", 0)), keywords(e.get("keywords")), sf, other, atk)]
    if d == "damage":
        to = e["to"]
        if e.get("divided") or e.get("filter"): refuse("damage form")
        if to in ("each_opponent", "target_opponent", "target_player", "defending_player", "that_player"):
            return [("face", amount(e["n"]), "each" if to == "each_opponent" else "one", True)]
        if to == "you": return [("life", -e["n"])] if isinstance(e["n"], int) else [("lose", amount(e["n"]))]
        if to == "any_target":
            ctx.burn = e["n"]
            if ctx.kind == "spell": ctx.interaction = True
            return [("face", amount(e["n"]), "one", True)]
        if to in ("target_creature", "target_creature_or_planeswalker") and isinstance(e["n"], int):
            ctx.interaction = True
            return [("kill_blk", "dmg", 1, e["n"], {"non": frozenset(), "need": frozenset(), "cmp": ()}, False, False)]
        refuse("damage to " + to)
    if d == "lose_life":
        if who == "you" and e["n"] == {"count": "mana_value_of_that"} and ctx.last == "recur":
            ctx.k.life_per_mv = True; return []          # Reanimate: lose life equal to the returned card's mana value
        if who in ("each_opponent", "target_opponent", "an_opponent", "defending_player", "that_player", "target_player"):
            return [("face", amount(e["n"]), "each" if who == "each_opponent" else "one", False)]
        if who == "you": return [("life", -e["n"])] if isinstance(e["n"], int) else [("lose", amount(e["n"]))]
        refuse("lose_life who " + str(who))
    if d == "gain_life":
        if who not in (None, "you"): return []                    # an opponent gaining life is their business
        return [("life", amount(e["n"]))]
    if d == "win_game": return [("win",)]
    if d == "bounce_self": return [("bounce_self",)]
    if d == "self_to_library":
        if e["where"] == "top" and "position" not in e: return [("self_top",)]
        refuse("self_to_library form")
    if d == "extra_combat":
        if e.get("n", 1) != 1: refuse("extra_combat count")
        u = e.get("untap", "none")
        if u not in ("none", "all_creatures", "attackers"): refuse("extra_combat untap")
        return ([("untap_cr", {"all_creatures": "all", "attackers": "attacked"}[u])] if u != "none" else []) + [("extra_combat",)]
    if d == "reveal_until":
        then = e.get("then") or []
        if e.get("filter") == {"non_types": ["land"]} and e.get("rest") == "exile" and len(then) == 1 and then[0]["do"] == "if":
            c, t1, t0 = then[0]["cond"], then[0].get("then"), then[0].get("else")
            inner = c.get("cond") if c.get("if") == "not" else None
            if inner and inner.get("if") == "amount_at_least" and inner.get("amount") == {"count": "mana_value_of_that"} \
                    and t1 == [{"do": "cast_free", "filter": {"any": True}, "from": "exile"}] \
                    and t0 == [{"do": "recur", "filter": {"any": True}, "n": 1, "to": "hand", "from": "exile"}]:
                return [("free_top", inner["n"] - 1)]
        refuse("reveal_until form")
    if d == "flip_coins":
        n = 1 if e.get("until_lose") else amount(e.get("n", 1))
        return [("flip", n, effects(e.get("on_win"), ctx), effects(e.get("on_lose"), ctx), bool(e.get("until_lose")))]
    if d == "choose_number":
        loss = ctx.next_loss
        return [("choose_num", e["min"], e["max"], loss)]
    if d == "free_cast_permission":
        if e["from"] != "hand" or e["duration"] != "end_of_turn": refuse("free cast permission form")
        return [("free_eot", spell_filter(e.get("spells")) or g.parse_filter(""))]
    if d == "sacrifice":
        if e["what"] == {"ref": "self"} and e.get("who", "you") == "you": return [("sac_self",)]
        refuse("sacrifice form")
    if d == "flicker":                                   # a target: the pilot flickers its own permanent (an opponent's is its choice too)
        w = e["what"]; f = w.get("filter") or {}
        types = f.get("types") or ["creature"]
        if e["returns"] not in ("immediately", "next_end_step") or f.get("controller") not in ("you", None) \
                or set(f) - {"types", "controller"} or set(types) - {"creature", "artifact"} or e.get("tapped"): refuse("flicker form")
        if w.get("ref") == "target" and w.get("n", 1) == 1: n = 1
        elif w.get("ref") == "each" and f.get("controller") == "you": n = "all"
        else: refuse("flicker target")
        if n == "all" and ctx.kind == "spell": ctx.answer = ctx.answer or "protect"; ctx.spell_interaction = True   # Ghostway: held as protection
        return [("flicker", n, e["returns"] == "next_end_step", frozenset(TYPE_CAP[t] for t in types))]
    if d == "untap":
        w = e["what"]
        if w == {"ref": "self"}: return [("untap_self",)]
        if w.get("ref") == "target" and isinstance(w.get("n"), int) and w.get("filter") == {"types": ["land"]}: return [("untap_n_lands", w["n"])]
        if w.get("ref") == "target" and w.get("n", 1) == 1 and (w.get("filter") or {}).get("types") == ["creature"] \
                and set(w.get("filter") or {}) <= {"types", "controller"}: return [("untap_cr", "one")]
        refuse("untap form")
    if d == "remove": return removal(e, ctx)
    if d == "counter_spell":
        ctx.interaction = True; ctx.answer = ctx.answer or "counter"; return []
    if d == "protect":
        ctx.interaction = True; ctx.answer = ctx.answer or "protect"; return []
    if d == "wipe":
        ctx.interaction = True
        if e.get("one_sided"): refuse("one-sided wipe")
        return []                                                 # a symmetric wipe is held, never cast (as the parser reads it)
    if d == "if":
        c = cond(e["cond"])
        out = [("cond", c, effects(e["then"], ctx))]
        if e.get("else"): out.append(("cond", ("not", c), effects(e["else"], ctx)))
        return out
    if d == "choose":
        compiled = []
        for m in e["modes"]:
            try: compiled.append(effects(m, ctx))
            except Refuse as ex: ctx.mode_misses.append(str(ex))
        def rank(fx): return min((g.MODE_RANK.index(x[0]) for x in fx if x[0] in g.MODE_RANK), default=99)
        if e.get("up_to") and e["n"] >= len(e["modes"]) and ctx.kind == "triggered":
            return [("opt", fx) for fx in sorted((fx for fx in compiled if fx), key=rank)]
        for fx in compiled:
            for x in fx:
                if x[0] == "kill_perm": ctx.kill |= set(x[1])
                if x[0] == "kill_blk": ctx.kill.add("creature")
        chosen = sorted((fx for fx in compiled if fx), key=rank)[:e["n"]]
        return [x for fx in chosen for x in fx]
    if d == "may_pay":
        if e.get("who", "you") != "you": refuse("may_pay who")
        return [may_pay(e, ctx)]
    refuse("effect " + d)

def pump_amt(a):
    v = amount(a, allow_x=False)
    return ("per", 1, v) if isinstance(v, tuple) and v[0] != "per" else v

def keywords(kws):
    out = set()
    for w in kws or []:
        if isinstance(w, dict): continue                      # protection from red...: nothing in a goldfish
        if w in SILENT and w not in g.COMBAT_KW: continue
        if w not in g.COMBAT_KW and w != "unblockable": refuse("keyword " + w)
        out.add(w)
    return frozenset(out)

def token(e, ctx):
    t = e["token"]
    if set(e) - {"do", "n", "token", "tapped"}: refuse("token " + ", ".join(sorted(set(e) - {"do", "n", "token", "tapped"})))
    n = amount(e["n"])
    if t.get("preset") == "treasure": return ("treasure", n, bool(e.get("tapped")))
    if t.get("preset") in ("clue", "food") and set(t) == {"preset"}:
        base = g.CLUE_E if t["preset"] == "clue" else g.FOOD_E
        return base[:1] + (n,) + base[2:8] + (bool(e.get("tapped")),)
    if t.get("preset") or t.get("abilities") or t.get("legendary"): refuse("token " + (t.get("preset") or "with abilities"))
    types = [x.lower() for x in t.get("types", [])]
    if "creature" not in types or set(types) - {"creature", "artifact", "enchantment"}: refuse("token types")
    p, q = t.get("power"), t.get("toughness")
    if not isinstance(p, int) or not isinstance(q, int): refuse("token P/T")
    tl = " ".join(x for x in ("artifact", "enchantment") if x in types) + (" " if len(types) > 1 else "") + "creature"
    return ("token", n, p, tuple(t.get("subtypes", [])), "", tl, q, keywords(t.get("keywords")), bool(e.get("tapped")))

RM_HOW = {"destroy": "destroy", "exile": "exile", "bounce": "bounce", "tuck": "exile", "damage": "dmg"}

def removal(e, ctx):
    ctx.interaction = True
    tg = e["target"]
    f = dict(tg.get("filter") or {})
    if f.get("controller") not in (None, "opponent", "any") or e.get("duration") not in (None, "permanent"): refuse("removal form")
    types = f.get("types", [])
    if tg.get("ref") != "target" or not isinstance(tg.get("n", 1), int): refuse("removal target")
    if "creature" in types or "permanent" in types:
        ctx.kill |= {t for t in types if t in ("creature", "artifact", "enchantment")} | ({"creature", "artifact", "enchantment"} if "permanent" in types else set())
    creatureish = types and set(types) <= {"creature", "planeswalker", "permanent", "artifact", "enchantment"} and \
        ("creature" in types or "permanent" in types) and set(f) <= {"types", "controller", "non_types"} and set(f.get("non_types", [])) <= {"land"}
    if re.search(r"\bcreates?\b|\bmanifests?\b", e.get("controller_compensation") or ""): creatureish = False   # they get a body back (Beast Within)
    if creatureish and e["how"] in RM_HOW:
        if e["how"] == "damage":
            if not isinstance(e.get("amount"), int): refuse("removal damage amount")
            lim = e["amount"]
        else: lim = None
        return [("kill_blk", RM_HOW[e["how"]], tg.get("n", 1), lim, {"non": frozenset(), "need": frozenset(), "cmp": ()},
                 bool(re.search(r"gains life equal to its power", e.get("controller_compensation") or "")), False)]
    kinds = {t for t in types if t in ("artifact", "enchantment")}
    if e["how"] in ("destroy", "exile") and types and set(types) == kinds and set(f) <= {"types", "controller"}:
        return [("kill_perm", frozenset(kinds))]
    ctx.kill |= {t for t in types if t in ("creature", "artifact", "enchantment")} | (
        {"creature", "artifact", "enchantment"} if "permanent" in types or not types else set())
    return []                                                     # held: kill types only (clears tax/lock pieces)

def cond(c):
    k = c["if"]
    simple = {"life_at_least": ("life", "n"), "life_at_most": ("life_le", "n"), "hand_at_most": ("hand_le", "n"),
              "hand_at_least": ("hand_ge", "n")}
    if k in simple: return (simple[k][0], c[simple[k][1]])
    if k == "attacked_this_turn": return ("attacked", c.get("min", 1))
    if k == "gained_life_this_turn" and c.get("min", 1) == 1: return "gained"
    if k in ("self_tapped", "self_untapped", "your_turn", "not_your_turn", "unique_name"): return (k,)
    if k == "main_phase": return ("main",)
    if k == "kicked" and c.get("min", 1) == 1: return ("kicked",)
    if k == "opponent_more_lands": return "opp_lands"
    if k == "you_control_commander": return ("cmdr_out",)
    if k == "hand_exactly": return ("hand_eq", c["n"])
    if k == "amount_at_least": return ("amt", amount(c["amount"], allow_x=False), c["n"])
    if k == "graveyard_at_least" and not c.get("card_types"):
        f = c.get("filter") or {}
        kind = {(): None, ("creature",): "creature", ("land",): "land", ("instant", "sorcery"): "instant"}.get(tuple(f.get("types", [])), 0)
        if kind == 0 or set(f) - {"types"}: refuse("graveyard condition filter")
        return ("gy_ge", c["n"], kind or "")
    if k == "control":
        if "min" in c and "max" in c: refuse("control range")
        if "max" in c: return ("pcount_le", perm_filter(c["filter"]), c["max"])
        return ("pcount", perm_filter(c["filter"]), c.get("min", 1))
    if k == "not": return ("not", cond(c["cond"]))
    if k == "and" and len(c["conds"]) == 2: return ("and", cond(c["conds"][0]), cond(c["conds"][1]))
    refuse("condition " + k)

def may_pay(e, ctx):
    c = e["cost"]
    then, els = effects(e["then"], ctx), effects(e.get("else"), ctx)
    if list(c) == ["mana"]:
        if els: refuse("may_pay mana with else")
        gen, pips, x, life = g.parse_cost(c["mana"])
        if x or life: refuse("may_pay mana form")
        return ("paid", gen, pips, then)
    if list(c) == ["discard"] and isinstance(c["discard"], dict) and not c["discard"].get("random"):
        f = c["discard"].get("filter")
        return ("ifdo", ("discard", c["discard"]["n"], spell_filter(f) if f else None), then, els)
    if c == {"sacrifice": "self"}: return ("ifdo", ("sac_self",), then, els)
    if list(c) == ["pay_life"] and isinstance(c["pay_life"], int): return ("ifdo", ("life", c["pay_life"]), then, els)
    refuse("may_pay cost " + ", ".join(sorted(c)))

# ---------------------------------------------------------------- abilities
class Ctx:
    def __init__(self, k, anyc):
        self.k, self.anyc = k, anyc
        self.interaction = False; self.answer = None; self.kill = set(); self.burn = None
        self.abil = []           # mana abilities: (units, restriction, colored only, cost) as compile_card collects them
        self.last = None; self.kind = None; self.mode_misses = []; self.pre_spell = []; self.spell_interaction = False
        self.self_land_types = set()

EVENTS = {"upkeep": "upkeep", "end_step": "end", "draw_step": "drawstep", "precombat_main": "main1", "combat_begin": "combat_begin",
          "coin_flip_won": "coin_won", "coin_flip": "coin_flip",
          "gain_life": "gain", "draw_card": "draw_card", "cycle": "cycle", "proliferate": "prolif", "opponent_draws": "opp_draw",
          "opponent_second_spell": "opp_second", "opponent_landfall": "opp_land"}

ctx_types = [set()]                                       # the compiling card's types (event() reads them)

def event(ev):
    """GEF Event -> (engine event, filter); 'etb_self' / 'cast_self' mean the ability goes on k.etb / k.castfx."""
    on, subj = ev["on"], ev.get("subject")
    extra = set(ev) - {"on", "subject", "whose", "who", "one_or_more", "spell"}
    if extra: refuse("event " + ", ".join(sorted(extra)))
    if on in EVENTS:
        if on in ("upkeep", "end_step", "draw_step", "precombat_main", "combat_begin") and ev.get("whose") != "your": refuse(f"{on} whose {ev.get('whose')}")
        if on in ("gain_life", "draw_card") and ev.get("who") not in (None, "you"): refuse(f"{on} who")
        if on == "cycle" and ev.get("who") not in (None, "you", "each_player"): refuse("cycle who")   # only you cycle in a goldfish
        if on in ("coin_flip_won", "coin_flip") and ev.get("who") not in (None, "you", "each_player"): refuse(f"{on} who")
        return EVENTS[on], None
    if on == "cast_self": return "cast_self", None
    if on == "cycle_self": return "cycle_self", None
    if on == "cast":
        if ev.get("who") not in (None, "you"): refuse("cast who")
        return "cast", spell_filter(ev.get("spell"))
    if on == "opponent_casts": return "opp_cast", spell_filter(ev.get("spell")) if ev.get("spell") else None
    if on == "enters":
        if subj == "self": return "etb_self", None
        if isinstance(subj, dict):
            if subj.get("types") == ["land"] and set(subj) <= {"types", "controller"}: return "landfall", None
            return "etb", perm_filter(subj)
        refuse("enters subject")
    if on in ("dies", "attacks", "combat_damage_to_player"):
        base = {"dies": "dies", "attacks": "attack", "combat_damage_to_player": "cdmg"}[on]
        if subj == "self": return base + "_self", None
        if subj == "self_or_another" and on == "dies" and "Creature" in ctx_types[0]:
            return "dies", perm_filter({"types": ["creature"]})
        if subj == "equipped": return {"dies": "dies_att", "attacks": "attack_att", "combat_damage_to_player": "cdmg_att"}[on], None
        if isinstance(subj, dict):
            if ev.get("one_or_more") and on != "dies": return base + "_any", perm_filter(subj)
            return base, perm_filter(subj)
        refuse(f"{on} subject")
    if on == "you_attack": return "attack_any", None
    if on == "sacrifice" and isinstance(subj, dict): return "sac", perm_filter(subj)
    if on in ("becomes_blocked", "attacks_unblocked", "deals_damage", "leaves", "put_into_graveyard") and subj == "self":
        return {"becomes_blocked": "blocked_self", "attacks_unblocked": "unblocked_self", "deals_damage": "dmg_self",
                "leaves": "leave_self", "put_into_graveyard": "gy_self"}[on], None
    refuse("event " + on)

def cost(c, ctx, mana_ok=True):
    """GEF Cost -> an acts dict's cost fields."""
    out = {"tap": bool(c.get("tap")), "gen": 0, "pips": [], "sac": False, "rm": None, "life": 0, "fodder": None}
    extra = set(c) - {"mana", "tap", "sacrifice", "remove_counters", "pay_life"}
    if extra: refuse("cost " + ", ".join(sorted(extra)))
    if c.get("mana"):
        gen, pips, x, life = g.parse_cost(c["mana"])
        if x: refuse("X cost")
        out["gen"], out["pips"], out["life"] = gen, pips, life
    if c.get("sacrifice") == "self": out["sac"] = True
    elif isinstance(c.get("sacrifice"), dict) and c["sacrifice"].get("n", 1) == 1: out["fodder"] = fodder(c["sacrifice"]["filter"])
    elif c.get("sacrifice"): refuse("sacrifice cost form")
    rm = c.get("remove_counters")
    if rm:
        if rm.get("from", "self") != "self" or not isinstance(rm["n"], int): refuse("remove_counters form")
        out["rm"] = (rm["kind"], rm["n"])
    if c.get("pay_life"):
        if not isinstance(c["pay_life"], int): refuse("pay_life amount")
        out["life"] += c["pay_life"]
    return out

COMBAT_KW = set(g.COMBAT_KW)
NUMBERED = set(g.COMBAT_KWN)

def keyword_ability(a, ctx):
    k, w = ctx.k, a["keyword"]
    if w in COMBAT_KW:
        if w in NUMBERED: refuse(f"{w} without a number")
        k.kw.add(w)
        if w == "exalted": k.kwn["exalted"] = k.kwn.get("exalted", 0) + 1
        if w == "haste": k.haste = True
        return "read"
    if w in NUMBERED:
        k.kwn[w] = k.kwn.get(w, 0) + int(a.get("n") or 1); return "read"
    if w == "equip":
        if a.get("filter"): refuse("equip [quality]")
        gen, pips, x, life = g.parse_cost(a["cost"] if isinstance(a.get("cost"), str) else "")
        if x or life or not isinstance(a.get("cost"), str): refuse("equip cost")
        k.equip = (gen, pips); return "read"
    if w in ("kicker", "multikicker"):
        if not isinstance(a.get("cost"), str): refuse("kicker cost")
        gen, pips, x, life = g.parse_cost(a["cost"])
        if x or life: refuse("kicker cost")
        k.kicker = (gen, pips, w == "multikicker"); return "read"
    if w in ("cycling", "typecycling", "landcycling"):
        cst = a.get("cost")
        if isinstance(cst, str): gen, pips, x, life = g.parse_cost(cst)
        elif isinstance(cst, dict) and set(cst) == {"pay_life"} and isinstance(cst["pay_life"], int): gen, pips, x, life = 0, [], False, cst["pay_life"]
        else: refuse("cycling cost")
        if x: refuse("cycling X")
        if w == "cycling":
            k.hand_acts.append({"kind": "cycle", "label": "cycling", "gen": gen, "pips": pips, "fx": [("draw", 1)], "life": life}); return "read"
        if not a.get("card_filter"): refuse(w + " without what it finds")
        cf = a["card_filter"]
        label = (cf["subtypes"][0].lower() + "cycling") if len(cf.get("subtypes", [])) == 1 else w
        k.hand_acts.append({"kind": "typecycle", "label": label, "gen": gen, "pips": pips, "fx": [("tutor", target(cf), "hand", 1)], "life": life})
        return "read"
    if w == "transmute":
        if not isinstance(a.get("cost"), str): refuse("transmute cost")
        gen, pips, _, _ = g.parse_cost(a["cost"])
        t = tu.Target(); t.mv = ("==", k.mv)
        k.hand_acts.append({"kind": "transmute", "label": "transmute", "gen": gen, "pips": pips, "fx": [("tutor", t, "hand", 1)]}); return "read"
    if w in ("flashback", "unearth", "escape", "retrace", "jump-start", "harmonize") and w in g.GY_KW:
        gc = {"kw": w, "gen": None, "pips": None, "discard": None, "exile_n": 0}
        if w == "jump-start": gc["discard"] = "card"
        elif w == "retrace": gc["discard"] = "land"
        else:
            if not isinstance(a.get("cost"), str): refuse(w + " cost")
            gc["gen"], gc["pips"], x, _ = g.parse_cost(a["cost"])
            if x or w == "escape": refuse(w + " cost")
        if w == "unearth" and "Creature" not in k.types: refuse("unearth on a noncreature")
        gc["exile_after"] = w != "retrace"
        k.gycast = gc; return "read"
    if w == "cascade": k.castfx.append(("cascade", k.mv, 1)); return "read"
    if w == "storm":
        if not k.types & {"Instant", "Sorcery"}: refuse("storm on a permanent")
        k.castfx.append(("storm",)); return "read"
    if w == "sunburst": k.ctr_enter = ("+1/+1" if "Creature" in k.types else "charge", ("converge",), False); return "read"
    if w == "cumulative upkeep": k.cum_upkeep = True; return "read"
    if w == "rebound": k.rebound = True; return "read"
    if w == "living weapon": refuse("living weapon")
    refuse("keyword " + w)

def fodder(f):
    """GEF PermFilter of a sacrifice cost -> fodder_filt's shape: {'any': [permanent filters], 'n': 1}."""
    pf = perm_filter(dict(f, controller=None) if f.get("controller") == "you" else f)
    return {"any": pf["any"] if "any" in pf else [pf], "n": 1}

RESTRICT = [(r"^(?:spend this mana only to cast )?creature spells?(?: only)?\.?$", "creature"),
            (r"^spend this mana only to cast (?:a )?legendary spells?\.?$", "legendary"),
            (r"^spend this mana only to cast (?:an )?(?:instant or sorcery|instant and/or sorcery) spells?\.?$", "instsorc"),
            (r"^spend this mana only to cast (?:an )?artifact spells?\.?$", "artifact")]

def restriction(r):
    for rx, key in RESTRICT:
        if re.match(rx, (r or "").strip().lower()): return key
    refuse("mana restriction")

def mana_ability(a, ctx):
    c, p = a["cost"], a["produce"]
    if a.get("if"): refuse("conditional mana ability")
    if set(p) - {"units", "restrict", "amount", "any_combination"}: refuse("mana " + ", ".join(sorted(set(p) - {"units"})))
    units = [colors(u, ctx.anyc) for u in p["units"]]
    if "amount" in p:                                    # 'three mana of any one color': a fixed count of one unit
        if not isinstance(p["amount"], int) or len(units) != 1: refuse("mana amount")
        units = units * p["amount"]
    if p.get("restrict"):
        r = restriction(p["restrict"])
        if c != {"tap": True}: refuse("restricted mana with a cost")
        ctx.abil.append((units, r, False, 0)); return "read"
    if isinstance(c.get("sacrifice"), dict) and set(c) <= {"sacrifice", "tap"} and c["sacrifice"].get("n", 1) == 1:
        ctx.k.sac_outlets.append((fodder(c["sacrifice"]["filter"]), [(u, g.NOC, None, False) for u in units], bool(c.get("tap")), "sac"))
        return "read"
    extra = set(c) - {"tap", "mana", "sacrifice"}
    if extra or not c.get("tap") and not c.get("mana"): refuse("mana ability cost " + ", ".join(sorted(extra)))
    if c.get("sacrifice") not in (None, "self"): refuse("mana ability sacrifice")
    if c.get("sacrifice") == "self": ctx.k.sac_mana = True
    conv = 0
    if c.get("mana"):
        gen, pips, x, life = g.parse_cost(c["mana"])
        if pips or x or life or not c.get("tap"): refuse("filter mana cost")
        conv = gen
    ctx.abil.append((units, None, False, conv))
    return "read"

def pain_mana(a, ctx):
    """'{T}: Add {U} or {B}. ~ deals 1 damage to you.' (Talismans, painlands) written as an activated ability with mana and
    damage to you: a mana ability with pain, as compile_card's read_life_costs reads it."""
    fx = a["effects"]
    if a["cost"] != {"tap": True} or len(fx) != 2 or fx[0]["do"] != "mana" or set(fx[0]["produce"]) != {"units"}: return False
    hurt = fx[1]
    if not ((hurt["do"] == "damage" and hurt["to"] == "you") or (hurt["do"] == "lose_life" and hurt.get("who") == "you")) or not isinstance(hurt["n"], int):
        return False
    units = [colors(u, ctx.anyc) for u in fx[0]["produce"]["units"]]
    ctx.abil.append((units, None, False, 0))
    ctx.pain.append((hurt["n"], units))
    return True

def static(a, ctx):
    k, s = ctx.k, a["effect"]
    st = s["static"]
    if a.get("if"): refuse("conditional static")
    if st == "anthem":
        f = dict(s.get("filter") or {"types": ["creature"]})
        if f.get("controller") not in (None, "you"): refuse("anthem controller")
        other = bool(f.pop("another", False)); f.pop("controller", None)
        atk = bool(f.pop("attacking", False))
        if f.get("power"): refuse("anthem power filter")
        if not f.get("types"): f["types"] = ["creature"]
        p_, t_ = s.get("power", 0), s.get("toughness", 0)
        if not isinstance(p_, int) or not isinstance(t_, int): refuse("anthem amount")
        k.statics.append(("anthem", spell_filter(f), p_, t_, keywords(s.get("keywords")), other, atk)); return "read"
    if st == "attached_bonus":
        if not all(x["kind"] == "keyword" and x["keyword"] in SILENT for x in s.get("abilities", [])): refuse("granted abilities")
        if not ({"Equipment", "Aura"} & k.subtypes): refuse("attached bonus on a non-attachment")
        p_, t_ = s.get("power", 0), s.get("toughness", 0)
        if not isinstance(p_, int) or not isinstance(t_, int): refuse("attached amount")
        kws = keywords(s.get("keywords"))
        if p_ or t_ or kws: k.attach = (p_, t_, kws)
        return "read"
    if st == "cost_reduction":
        if s.get("applies_to", "spells") != "spells" or not isinstance(s["amount"], int): refuse("cost reduction form")
        f = spell_filter(s.get("spells")) or g.parse_filter("")
        if s.get("first_each_turn"): f["first"] = True
        k.statics.append(("reduce", f, s["amount"])); return "read"
    if st == "enters_tapped":
        u = s.get("unless")
        if u:
            uf = u.get("filter") or {}
            subs = {x.lower() for x in uf.get("subtypes", [])}
            if u["if"] == "control" and u.get("min", 1) == 1 and "max" not in u and set(uf) <= {"subtypes", "controller", "types"} \
                    and uf.get("types", ["land"]) == ["land"] and subs and subs <= set(g.BASIC):
                k.etap = ("check", frozenset(subs)); return "read"
            n_ = u.get("min", 1)
            if u["if"] == "control" and "max" not in u and set(uf) <= {"types", "supertypes", "subtypes", "controller", "another"} \
                    and uf.get("types", ["land"]) == ["land"] and set(uf.get("supertypes", [])) <= {"basic"} and subs <= set(g.BASIC) \
                    and (subs or uf.get("supertypes")):
                k.etap = ("count", "basic" in uf.get("supertypes", []), frozenset(subs), n_); return "read"
            ctx.etap_fallback = True
            refuse("conditional enters-tapped")
        up = s.get("unless_pay")
        if up:
            if set(up) != {"pay_life"} or not isinstance(up["pay_life"], int): refuse("enters-tapped payment")
            k.etap = ("shock", up["pay_life"])
        else: k.etap = ("always",)
        return "read"
    if st == "grant_abilities":
        abs_ = s["abilities"]
        f = dict(s.get("filter") or {})
        if f.get("controller") not in (None, "you"): refuse("grant to others' permanents")
        if f.get("types") == ["land"] and set(f) <= {"types", "controller"} and len(abs_) == 1 and abs_[0]["kind"] == "mana" \
                and abs_[0]["cost"] == {"tap": True} and abs_[0]["produce"] == {"units": ["any"]}:
            k.statics.append(("lands_any",)); return "read"
        if not all(x["kind"] == "keyword" and (x["keyword"] in COMBAT_KW or x["keyword"] in SILENT) for x in abs_): refuse("granted abilities")
        kws = keywords([x["keyword"] for x in abs_ if x["keyword"] not in SILENT])
        if not kws: return "read"                        # shroud, hexproof, protection: nothing in a goldfish
        other, atk = bool(f.pop("another", False)), bool(f.pop("attacking", False))
        f.pop("controller", None)
        if not f.get("types"): f["types"] = ["creature"]
        if f.get("power"): refuse("grant power filter")
        k.statics.append(("anthem", spell_filter(f), 0, 0, kws, other, atk)); return "read"
    if st == "counter_doubler":
        if s.get("kind") or s.get("factor", 2) != 2: refuse("counter doubler form")
        k.statics.append(("ctr_times", None, None)); return "read"
    if st == "trigger_doubler":
        if s.get("cause") == "any":                     # 'a triggered ability of [filter] triggers an additional time'
            k.statics.append(("trig_x", "src", perm_filter(s.get("filter") or {}))); return "read"
        kind = {"enters": "enter", "dies": "dies", "attacks": "attack"}.get(s.get("cause"))
        if not kind: refuse("trigger doubler cause " + str(s.get("cause")))
        pf = perm_filter(s.get("filter") or {})
        k.statics.append(("trig_x", kind, dict(pf, n=1) if "any" in pf else {"any": [pf], "n": 1})); return "read"
    if st == "free_cast":
        if s.get("from") not in (None, "hand"): refuse("free cast from " + s["from"])
        k.statics.append(("free", spell_filter(s.get("spells")) or g.parse_filter(""), s.get("from") == "hand")); return "read"
    if st == "pt_equals":
        pw, tg = s.get("power"), s.get("toughness")
        raw_p, raw_t = str(k.raw.get("power", "")), str(k.raw.get("toughness", ""))
        if isinstance(pw, dict) and set(pw) <= {"count", "filter", "card_filter", "plus"} and str(pw.get("plus", 0)) == raw_p \
                and isinstance(tg, int) and str(tg) == raw_t:
            key = count_key(pw)
            k.statics.append(("anthem", {"self": True}, ("per", 1, key), ("per", 0, key), frozenset(), False, False)); return "read"
        refuse("pt_equals form")
    if st == "spell_limit":
        if s["who"] not in ("you", "each_player"): return "read"           # opponents only: nothing for you
        k.statics.append(("spell_limit", s["n"], spell_filter(s.get("spells")) or g.parse_filter(""))); return "read"
    if st == "skip_step":
        if s["what"] != "draw_step" or s.get("who", "you") != "you": refuse("skip " + s["what"])
        k.statics.append(("skip_draw",)); return "read"
    if st == "coin_flip_rule": k.statics.append(("coin_rule", s["rule"])); return "read"
    if st == "mana_multiplier":
        src = {"permanents you tap for mana": "permanent", "permanent": "permanent", "lands": "land", "land": "land"}.get(s.get("sources", ""))
        if not src or s.get("factor") not in (2, 3): refuse("mana multiplier form")
        k.statics.append(("mana_mult", src, s["factor"])); return "read"
    if st == "no_max_hand_size": k.statics.append(("no_max_hand",)); return "read"
    if st == "extra_land": k.statics.append(("extra_land", s["n"])); return "read"
    if st == "draw_from_empty_library_wins": k.labman = True; return "read"
    if st == "doesnt_untap": k.no_untap = True; return "read"
    if st == "extra_counters":
        on = s["on"]
        if on.get("controller") not in (None, "you") or set(on) - {"types", "controller"} or s.get("n") != 1: refuse("extra_counters form")
        scope = frozenset(TYPE_CAP[t] for t in on.get("types", [])) or None
        k.statics.append(("ctr_plus", scope, frozenset({s["kind"]}) if s.get("kind") else None)); return "read"
    if st == "choose_on_enter":
        if s["choice"] != "creature_type": refuse("choose " + s["choice"])
        return "read"                                    # the deck's tribe (CHOSEN_TYPE), as the parser reads it
    if st == "type_grant" and k.is_land and (s.get("filter") or {}).get("types") == ["land"] and s.get("add_types") \
            and {t.lower() for t in s["add_types"]} <= set(g.BASIC) and not s.get("abilities"):
        ctx.self_land_types |= {t.lower() for t in s["add_types"]}
        refuse("type grant to other lands")
    if st == "type_grant":
        if s.get("self") and s.get("add_chosen_type") and not s.get("add_types") and not s.get("abilities"):
            if g.CHOSEN_TYPE: k.subtypes = k.subtypes | {g.CHOSEN_TYPE}
            return "read"
        refuse("type grant")
    if st == "enters_with_counters":
        if s.get("if") or not isinstance(s["n"], (int, str)): refuse("enters_with_counters form")
        k.ctr_enter = (s["kind"], amount(s["n"]), False); return "read"
    if st == "token_doubler":
        if s.get("filter") or s.get("factor", 2) not in (2, 3): refuse("token doubler form")
        k.statics.append(("token_mult", s.get("factor", 2), False)); return "read"
    refuse("static " + st)

def ability(a, ctx):
    """Compile one ability into ctx.k. -> 'read' / 'silent' / 'oos'; raises Refuse."""
    kind = a["kind"]
    k = ctx.k
    ctx.kind = kind
    if kind == "unexpressible":
        if a["scope"] == "out_of_scope": return "oos"
        refuse(f"unexpressible ({a['scope']}): {a.get('reason', '')[:60]}")
    if kind == "keyword":
        if a["keyword"] == "enchant" and "Aura" in k.subtypes:
            s_ = (a.get("detail") or "").lower()
            k.requires = "legendary creature" if "legendary creature" in s_ else "creature" if "creature" in s_ else \
                "land" if re.search(r"land|forest|plains|island|swamp|mountain", s_) else None
        if a["keyword"] in SILENT:
            if a["keyword"] in g.COMBAT_KW: k.kw.add(a["keyword"])      # hexproof, shroud: kept in the keyword set as the parser does
            return "silent"
        return keyword_ability(a, ctx)
    if kind == "mana": return mana_ability(a, ctx)
    if kind == "static": return static(a, ctx)
    if kind == "spell":
        before = ctx.interaction; ctx.interaction = False
        k.spell += effects(a["effects"], ctx)
        ctx.spell_interaction = ctx.spell_interaction or ctx.interaction
        ctx.interaction = ctx.interaction or before
        return "read"
    if kind == "triggered":
        ev, filt = event(a["event"])
        tax = False
        fx = a["effects"]
        if ev in ("opp_cast", "opp_draw") and len(fx) == 1 and fx[0]["do"] == "unless_opponent_pays":
            tax, fx = True, fx[0]["effects"]
        out = effects(fx, ctx)
        if a.get("if") and out: out = [("cond", cond(a["if"]), out)]
        if not out:
            if ctx.interaction: return "read"            # removal aimed at opponents' permanents: held, nothing to run here
            refuse("trigger with no engine effect")
        if ev == "etb_self":
            if a.get("once_per_turn"): refuse("once-per-turn enter trigger")
            k.etb += out
        elif ev == "cast_self": k.castfx += out
        elif ev == "cycle_self": k.cycle_fx += out              # 'when you cycle ~': a cycling rider, as the parser reads it
        else: k.trig.append((ev, filt, out, bool(a.get("once_per_turn")), tax, False))
        return "read"
    if kind == "activated":
        if a.get("from_zone", "battlefield") != "battlefield": refuse("activated from " + a["from_zone"])
        if (a.get("if") and a["if"] != {"if": "your_turn"}) or a.get("once_per_turn"): refuse("activation restriction")
        if pain_mana(a, ctx): return "read"
        cst = cost(a["cost"], ctx)
        out = effects(a["effects"], ctx)
        if not out: refuse("activation with no engine effect")
        k.acts.append(dict(cst, fx=out, combat=False, sorcery=bool(a.get("sorcery_speed")), your_turn=bool(a.get("if"))))
        return "read"
    if kind == "loyalty":
        if not isinstance(a["cost"], int): refuse("X loyalty cost")
        out = effects(a["effects"], ctx)
        if not out: refuse("loyalty ability with no engine effect")
        k.pw.append((a["cost"], out)); return "read"
    if kind == "alt_cost":
        if a.get("if") == {"if": "you_control_commander"} and a["cost"] in ({"mana": "{0}"}, {}): k.free_cmdr = True; return "read"
        refuse("alternative cost")
    if kind == "additional_cost":
        c = a["cost"]
        if a.get("optional"): refuse("optional additional cost")
        if list(c) == ["pay_life"] and isinstance(c["pay_life"], int): k.addlife += c["pay_life"]; return "read"
        if list(c) == ["sacrifice"] and isinstance(c["sacrifice"], dict) and c["sacrifice"].get("n", 1) == 1:
            k.addsac = fodder(c["sacrifice"]["filter"]); return "read"
        if list(c) == ["discard"] and isinstance(c["discard"], dict) and set(c["discard"]) == {"n"}:
            ctx.pre_spell.append(("discard", c["discard"]["n"])); return "read"
        refuse("additional cost " + ", ".join(sorted(c)))
    refuse("ability kind " + kind)

SILENT = {"hexproof", "shroud", "protection", "ward", "flash", "changeling", "partner", "partner with", "companion",
                   "choose a background", "friends forever", "enchant", "split second", "banding", "phasing", "crew",
                   "reconfigure", "landwalk", "umbra armor"}

# ---------------------------------------------------------------- the card
def base_card(c, anyc):
    """The card's metadata (types, cost, P/T, colors, loyalty) with no abilities: compile_card on the card with no rules
    text. Lands keep the intrinsic mana of their basic land types (CR 305.6)."""
    blank = dict(c, oracle_text="", keywords=[])
    if c.get("card_faces"): blank["card_faces"] = [dict(f, oracle_text="") for f in c["card_faces"]]
    k = g.compile_card(blank, anyc)
    k.raw, k.notes = c, []
    if not k.land_types: k.units = []
    k.mdfc = None
    return k

def compile_gef(c, gef, anyc):
    """A Card for card data c from its GEF translation."""
    k = base_card(c, anyc)
    faces = gef.get("faces")
    if faces:
        if c.get("layout") == "modal_dfc" and len(faces) == 2 and "Land" in (c["card_faces"][1].get("type_line") or "") and "Land" not in k.types:
            back = dict(c["card_faces"][1], name=c["card_faces"][1]["name"], layout="normal", cmc=0)
            k.mdfc = compile_gef(back, {"gef": gef["gef"], "name": back["name"], "abilities": faces[1]["abilities"]}, anyc)
            abils, other = faces[0]["abilities"], []
        else:
            abils, other = faces[0]["abilities"], [a for f in faces[1:] for a in f["abilities"]]
    else:
        abils, other = gef.get("abilities", []), []
    ctx = Ctx(k, anyc); ctx.pain = []
    ctx_types[0] = k.types
    done = missed = vac = 0
    for a in abils:
        before = _snapshot(k)
        try:
            ctx.mode_misses = []
            r = ability(a, ctx)
            if r == "read": done += 1
            elif r == "oos": vac += 1
            if ctx.mode_misses:
                missed += 1; k.notes.append(f"gef refused a mode of: {(a.get('text') or '')[:50]} ({'; '.join(ctx.mode_misses)})")
        except Refuse as ex:
            _restore(k, before)
            missed += 1; k.notes.append(f"gef refused: {(a.get('text') or a['kind'])[:60]} ({ex})")
    if ctx.pre_spell: k.spell = ctx.pre_spell + k.spell
    if ctx.self_land_types: k.land_types = frozenset(k.land_types | ctx.self_land_types)
    if getattr(ctx, "etap_fallback", False) and not k.etap: k.etap = ("always", "conditional")
    for a in other:                                      # adventure / split / transform faces: not the card goldfish casts
        missed += 1; k.notes.append(f"gef refused: {(a.get('text') or a['kind'])[:60]} (another face)")
    finish(k, ctx, done, missed, vac)
    return k

FIELDS = ("spell", "etb", "castfx", "trig", "acts", "statics", "hand_acts", "kw", "kwn", "subtypes", "sac_outlets", "pw")
def _snapshot(k): return {f: (set(v) if isinstance(v, set) else dict(v) if isinstance(v, dict) else list(v)) for f, v in ((f, getattr(k, f)) for f in FIELDS)} | \
    {f: getattr(k, f) for f in ("equip", "kicker", "gycast", "attach", "etap", "labman", "no_untap", "ctr_enter", "cum_upkeep", "rebound",
                             "addlife", "haste", "sac_mana", "addsac", "life_per_mv")}
def _restore(k, snap):
    for f, v in snap.items(): setattr(k, f, v)

def finish(k, ctx, done, missed, vac):
    """The bookkeeping compile_card does after reading the lines: mana units, hold, categories, status."""
    abil = ctx.abil + ([(([frozenset(g.BASIC[t] for t in k.land_types)]), None, False, 0)] if k.is_land and k.land_types else [])
    plain = [a for a in abil if not a[3]]                # the same combination compile_card makes of its mana abilities
    def unit(u, restr, co): return (g.NOC, u, restr, co) if restr else (u, g.NOC, None, co)
    for units, restr, co, cst in abil:
        if cst: k.convs.append((cst, [unit(u, restr, co) for u in units]))
    if len(plain) == 1:
        units, restr, co, _ = plain[0]
        k.units = [unit(u, restr, co) for u in units]
    elif plain:
        if all(len(a[0]) == 1 for a in plain):
            cols = frozenset().union(*(a[0][0] for a in plain if not a[1]))
            rc = [a for a in plain if a[1]]
            k.units = [(cols, frozenset().union(*(a[0][0] for a in rc)) if rc else g.NOC, rc[0][1] if rc else None, all(a[2] for a in plain))]
        else:
            units, restr, co, _ = max(plain, key=lambda a: len(a[0]))
            k.units = [(u, g.NOC, None, co) for u in units]
            k.notes.append("several mana abilities; modeled the biggest")
    if ctx.pain:
        free_c = any(all(u == frozenset("C") for u in a[0]) for a in plain if a not in [(u, None, False, 0) for _, u in ctx.pain])
        k.pain = max(n for n, _ in ctx.pain)
        k.pain_col = free_c
    if "Creature" in k.types or k.kw:
        if "prowess" in k.kw: k.trig.append(("cast", g.parse_filter("noncreature"), [("pump", "self", 1, 1, frozenset())], False, False, False))
        if "battle cry" in k.kw: k.trig.append(("attack_self", None, [("pump", "others_attacking", 1, 0, frozenset())], False, False, False))
    k.haste = k.haste or "haste" in k.kw
    if k.types & {"Instant", "Sorcery"} and any(e[0] in ("pump", "pump_team", "extra_combat") for e in g.flat(k.spell)) \
            or any(e[0] == "pump_team" for e in k.etb):
        k.alpha = True
    if k.types & {"Instant", "Sorcery"}:
        k.ritual = bool(k.spell) and all(e[0] in ("mana", "mana_n") for e in k.spell)
        k.hold = ctx.spell_interaction and not k.ritual
    PROTECT = {"indestructible", "hexproof", "shroud"}
    if not ctx.answer and any((e[0] == "pump_team" and set(e[3]) & PROTECT) or (e[0] == "pump" and set(e[4]) & PROTECT) for e in g.flat(k.spell)):
        ctx.answer = "protect"
    if ctx.answer and ("Instant" in k.types or "flash" in (k.raw.get("keywords") or []) or "Flash" in (k.raw.get("keywords") or [])):
        k.answer = ctx.answer
        if "Creature" not in k.types: k.hold = True
    if k.hold and not k.answer:
        k.kill = frozenset(ctx.kill | ({"creature"} if any(e[0] == "kill_blk" for e in k.spell) or isinstance(ctx.burn, int) else set())
                           | {t for e in k.spell if e[0] == "kill_perm" for t in e[1]})
    if k.hold and isinstance(ctx.burn, int) and ctx.burn > 0 and not any(e[0] == "kill_blk" for e in k.spell):
        k.burn_blk = ("kill_blk", "dmg", 1, ctx.burn, {"non": frozenset(), "need": frozenset(), "cmp": ()}, False, False)
    for a in k.hand_acts:
        if a["kind"] != "transmute": a["fx"] = a["fx"] + k.cycle_fx
    k.trig = [t for t in k.trig if t[2]]
    allfx = g.all_fx(k)
    k.recur_fx = [e for e in allfx if e[0] == "recur"]
    k.gain_untap = False
    if k.types & {"Instant", "Sorcery"} and k.spell:
        rec = [e for e in g.flat(k.spell) if e[0] == "recur"]
        if rec and not k.requires: k.requires, k.gy_need = "gy", rec[0][1]
    g.categorize(k)
    k.status = "blank" if missed and not done and not k.units else "partial" if missed else "modeled"
    if not done and not missed and vac: k.status = "vacuum"
    if k.hold: k.status = "held"
    k.gef = True
    return k

# ---------------------------------------------------------------- CLI
def main():
    cards, rejects = load()
    idx = mtg.index()
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    todo = [mtg.norm(n) for n in names] if names else sorted(cards)
    from collections import Counter
    st, why = Counter(), Counter()
    for nm in todo:
        gef = cards.get(nm)
        if not gef: print("no GEF for", nm); continue
        k = compile_gef(idx[nm], gef, g.ALL5)
        st[k.status] += 1
        for n_ in k.notes:
            m = re.search(r"\(([^()]*)\)$", n_)
            if n_.startswith("gef refused") and m: why[re.sub(r"[: ].*", "", m.group(1)) if "unexpressible" in m.group(1) else m.group(1)] += 1
        if names or "--verbose" in sys.argv:
            print(f"{k.name}: {k.status}")
            for f in ("units", "spell", "etb", "castfx", "trig", "acts", "statics", "hand_acts", "kw", "kwn", "equip", "attach", "etap",
                      "kicker", "gycast", "hold", "answer", "kill", "pain", "notes"):
                v = getattr(k, f)
                if v: print(f"   {f}: {v!r}"[:240])
    if rejects: print(f"{len(rejects)} translations rejected by the validator: " + "; ".join(f"{n} ({e[:60]})" for n, e in rejects[:5]))
    if not names:
        print(f"{sum(st.values())} GEF cards: {dict(st)}")
        print("refusals by reason:")
        for r, n in why.most_common(60): print(f"  {n:4d}  {r}")

if __name__ == "__main__":
    main()
