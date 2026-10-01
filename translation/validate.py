#!/usr/bin/env python3
"""Validate GEF translations and derive their goldfish statuses. Stdlib only.

  python3 translation/validate.py FILE.json [FILE.json ...] [--status] [--quiet]

A file holds one GEF card object or a JSON array of them. A translation is ACCEPTED only if:
  1. it satisfies translation/gef.schema.json (a built-in validator for the JSON Schema subset the schema uses;
     when the `jsonschema` package is installed it also runs, and any disagreement is reported), and
  2. its `text` fields account for every Oracle line of the card, in the card's own words, and cite no line the
     card doesn't have (a translator can't skip a line silently; unrepresentable lines are `unexpressible`).
  3. it passes the lint: rules the schema can't state (`detail` only on silent keywords, a tutor names one
     destination or a split, `position` only on the library top, a damage-dealt count names its player, ...).
Anything else is REJECTED with the reasons; nothing is repaired or guessed.

--status adds the derived goldfish status twice: as expressed (if the engine ran every GEF construct) and today
(constructs goldfish.py doesn't execute yet count as unread). See docs/GOLDFISH_EFFECT_FORMAT.md.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = json.load(open(os.path.join(HERE, "gef.schema.json"), encoding="utf-8"))
sys.path.insert(0, HERE)
from gef_schema import SILENT_KEYWORDS as _SILENT     # noqa: E402  (one list for the format rule and the status)

# ---------------------------------------------------------------- JSON Schema subset
def _resolve(ref):
    node = SCHEMA
    for part in ref.lstrip("#/").split("/"): node = node[part]
    return node

TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}

def _type_ok(v, t):
    if t == "integer": return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, TYPES[t]) and not (t != "boolean" and isinstance(v, bool))

def check(v, s, path="$"):
    """Errors (list of strings) for value v against schema s."""
    errs = []
    if "$ref" in s:
        errs += check(v, _resolve(s["$ref"]), path)
    if "type" in s and not _type_ok(v, s["type"]):
        return errs + [f"{path}: expected {s['type']}, got {type(v).__name__}"]
    if "const" in s and v != s["const"]: errs.append(f"{path}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} is not one of {', '.join(map(str, s['enum'][:12]))}{'...' if len(s['enum']) > 12 else ''}")
    if "pattern" in s and isinstance(v, str) and not re.search(s["pattern"], v): errs.append(f"{path}: {v!r} doesn't match {s['pattern']}")
    if isinstance(v, dict):
        props = s.get("properties", {})
        for r in s.get("required", []):
            if r not in v: errs.append(f"{path}: missing required '{r}'")
        for k, x in v.items():
            if k in props: errs += check(x, props[k], f"{path}.{k}")
            elif s.get("additionalProperties") is False: errs.append(f"{path}: unknown field '{k}'")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0): errs.append(f"{path}: needs at least {s['minItems']} item(s)")
        if "items" in s:
            for i, x in enumerate(v): errs += check(x, s["items"], f"{path}[{i}]")
    for sub in s.get("allOf", []):
        if "if" in sub:
            if not check(v, sub["if"], path): errs += check(v, sub["then"], path)
        else: errs += check(v, sub, path)
    if "anyOf" in s:
        opts = [check(v, o, path) for o in s["anyOf"]]
        if all(opts): errs.append(f"{path}: matches none of the allowed forms ({'; '.join(min(opts, key=len)[:2])})")
    if "oneOf" in s:
        ok = sum(1 for o in s["oneOf"] if not check(v, o, path))
        if ok != 1: errs.append(f"{path}: must match exactly one of {len(s['oneOf'])} forms (matched {ok})")
    return errs

# ---------------------------------------------------------------- Oracle line coverage
def _norm(t, names):
    t = re.sub(r"\s*\([^()]*\)", "", t or "")
    t = t.replace("’", "'").replace("—", "-").replace("−", "-")
    for n in sorted({n for n in names if n and len(n) > 2}, key=len, reverse=True):
        t = re.sub(re.escape(n), "~", t, flags=re.I)
    t = re.sub(r"\bthis (?:creature|artifact|enchantment|land|permanent|card|spell|aura|equipment|vehicle|planeswalker|saga|class|token)\b", "~", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip().strip(".").lower()

def oracle_blocks(face):
    """A face's Oracle text as blocks: a line, a 'choose ... —' line with its bullets, or a Class level with its lines."""
    lines = [l.strip() for l in re.sub(r"\([^()]*\)", "", face.get("oracle_text") or "").split("\n") if l.strip()]
    out = []
    for l in lines:
        if l.startswith("•") and out: out[-1].append(l)
        else: out.append([l])
    return out

def _texts(abilities):
    for a in abilities:
        yield a
        if a.get("kind") == "class_level": yield from _texts(a.get("abilities", []))

def coverage(gef, card):
    """Errors: Oracle lines no ability accounts for, and ability texts that aren't the card's."""
    faces = card.get("card_faces") if card.get("card_faces") and gef.get("faces") else [card]
    gfaces = gef.get("faces") or [{"name": card["name"], "abilities": gef.get("abilities", [])}]
    errs = []
    if len(gfaces) != len(faces):
        return [f"card has {len(faces)} face(s) with text, translation has {len(gfaces)}"]
    for face, gface in zip(faces, gfaces):
        names = [card["name"], face.get("name", ""), card["name"].split(",")[0], card["name"].split(" // ")[0],
                 face.get("name", "").split(",")[0]]
        blocks = oracle_blocks(face)
        want = [[_norm(x, names) for x in b] for b in blocks]
        fulls = [_norm("\n".join(b), names) for b in blocks]   # a modal block as one text (keeps inner periods)
        got = [(_norm(a.get("text", ""), names), a) for a in _texts(gface.get("abilities", []))]
        used = [False] * len(want)
        for t, a in got:
            if not t:
                errs.append(f"{face.get('name', card['name'])}: an ability of kind '{a.get('kind')}' has no text"); continue
            hit = False
            for i, b in enumerate(want):
                full = fulls[i]
                parts = [p.strip() for p in re.split(r"[,;]", b[0])]
                if t == full or t in b or t in parts or (len(t) >= 30 and (full.startswith(t) or t.startswith(full[:max(30, len(full) - 2)]))):
                    used[i] = True; hit = True
            if not hit: errs.append(f"{face.get('name', card['name'])}: text not on the card: {a.get('text', '')[:70]!r}")
        for i, u in enumerate(used):
            if not u: errs.append(f"{face.get('name', card['name'])}: Oracle line not accounted for: {' '.join(blocks[i])[:80]!r}")
    return errs

# ---------------------------------------------------------------- lint: format rules the schema can't state
KW_FILTER = {"equip", "offering"}                  # keyword `filter`: what it targets or needs
KW_CARD_FILTER = {"typecycling", "landcycling"}    # keyword `card_filter`: what it finds
PLAYER_COUNTS = {"damage_dealt_this_turn"}         # counts that need Amount.player
PLAYER_OPTIONAL = {"cards_in_opponent_hand"}       # counts that may name it ("the number of cards in their hand")
PHASE_EVENTS = {"upkeep", "draw_step", "precombat_main", "combat_begin", "end_of_combat", "postcombat_main", "end_step"}

def _nodes(x, path="$"):
    if isinstance(x, dict):
        yield x, path
        for k, v in x.items(): yield from _nodes(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x): yield from _nodes(v, f"{path}[{i}]")

def lint(gef):
    errs = []
    for o, path in _nodes(gef):
        if o.get("kind") == "keyword":
            w = o.get("keyword")
            if "detail" in o and w not in _SILENT:
                errs.append(f"{path}: 'detail' is only for silent keywords ({w!r} isn't one): say it with filter/card_filter/cost/n, or mark it unexpressible")
            if "filter" in o and w not in KW_FILTER: errs.append(f"{path}: keyword 'filter' is only for {sorted(KW_FILTER)}")
            if "card_filter" in o and w not in KW_CARD_FILTER: errs.append(f"{path}: keyword 'card_filter' is only for {sorted(KW_CARD_FILTER)}")
        d = o.get("do")
        if d == "tutor":
            if ("to" in o) == ("split" in o): errs.append(f"{path}: tutor needs exactly one of 'to' or 'split'")
            if "position" in o and o.get("to") != "library_top": errs.append(f"{path}: 'position' needs to: library_top")
            if "split" in o and isinstance(o.get("n"), int) and sum(x["n"] for x in o["split"]) != o["n"]:
                errs.append(f"{path}: split counts don't add up to n")
        if d == "self_to_library" and "position" in o and o.get("where") != "top":
            errs.append(f"{path}: 'position' needs where: top")
        if d == "damage" and "filter" in o and o.get("to") not in ("each_creature", "each_opposing_creature"):
            errs.append(f"{path}: damage 'filter' only narrows each_creature / each_opposing_creature")
        if "count" in o and isinstance(o.get("count"), str):
            if (o["count"] in PLAYER_COUNTS and "player" not in o) or ("player" in o and o["count"] not in PLAYER_COUNTS | PLAYER_OPTIONAL):
                errs.append(f"{path}: 'player' is required for {sorted(PLAYER_COUNTS)}, allowed for {sorted(PLAYER_OPTIONAL)}, and nothing else")
        if isinstance(o.get("on"), str) and o["on"] in PHASE_EVENTS and "whose" not in o:
            errs.append(f"{path}: a beginning-of-phase event needs 'whose' (\"your upkeep\" is whose: your)")
        if o.get("static") == "type_grant" and ("filter" in o) == bool(o.get("self")):
            errs.append(f"{path}: type_grant needs exactly one of 'filter' or self: true")
        if "for_each" in o and "ref" in o and o["ref"] != "target":
            errs.append(f"{path}: 'for_each' is only for ref: target")
    return errs

# ---------------------------------------------------------------- status (GEF -> goldfish status)
# What goldfish.py executes today, by construct. 'lacks' constructs make the line unread for the today-status.
ENGINE_EFFECTS = {"draw", "discard", "mill", "scry", "surveil", "look", "tutor", "recur", "wheel", "put_back", "mana",
                  "extra_land", "land_from_hand", "token", "copy_token", "counters", "proliferate", "pump", "pump_team",
                  "damage", "lose_life", "gain_life", "poison", "extra_combat", "remove", "wipe", "counter_spell",
                  "protect", "level", "self_to_library", "bounce_self", "if", "may_pay", "choose", "unless_opponent_pays",
                  "cast_free", "sacrifice"}
ENGINE_EVENTS = {"enters", "dies", "leaves", "put_into_graveyard", "attacks", "you_attack", "combat_damage_to_player",
                 "deals_damage", "attacks_unblocked", "becomes_blocked", "cast", "cast_self", "upkeep", "end_step",
                 "draw_step", "precombat_main", "combat_begin", "gain_life", "draw_card", "cycle", "cycle_self",
                 "sacrifice", "proliferate", "opponent_casts", "opponent_draws", "opponent_second_spell",
                 "opponent_landfall", "tapped_for_mana", "class_level"}
ENGINE_CONDS = {"control", "life_at_least", "life_at_most", "hand_at_most", "hand_at_least", "graveyard_at_least",
                "attacked_this_turn", "gained_life_this_turn", "your_turn", "not_your_turn", "main_phase", "kicked",
                "cast_from_hand", "self_tapped", "self_untapped", "opponent_more_lands", "unique_name", "not", "and",
                "coin_flip_won"}
ENGINE_STATICS = {"anthem", "attached_bonus", "grant_abilities", "cost_reduction", "extra_land", "no_max_hand_size",
                  "token_doubler", "counter_doubler", "trigger_doubler", "mana_multiplier", "damage_multiplier",
                  "type_grant", "enters_tapped", "enters_with_counters", "evasion", "free_cast", "alt_cost_all",
                  "draw_from_empty_library_wins", "doesnt_untap", "pt_equals", "spend_mana_as_any", "lands_tap_any",
                  "cant_attack", "cant_block",
                  "extra_counters",       # Hardened Scales ('ctr_plus')
                  "choose_on_enter"}      # creature type: read as the deck's tribe (CHOSEN_TYPE); color: see _field_lacks
ENGINE_KEYWORDS = {"flying", "reach", "trample", "vigilance", "haste", "lifelink", "deathtouch", "menace", "first strike",
                   "double strike", "indestructible", "defender", "infect", "wither", "fear", "intimidate", "shadow",
                   "horsemanship", "skulk", "prowess", "exalted", "unblockable", "myriad", "melee", "battle cry",
                   "training", "dethrone", "annihilator", "toxic", "poisonous", "flanking", "bushido", "rampage",
                   "afflict", "mentor", "kicker", "multikicker", "flashback", "cycling", "landcycling", "typecycling",
                   "transmute", "rebound", "cascade", "affinity", "escape", "jump-start", "retrace", "unearth",
                   "harmonize", "sunburst", "equip", "cumulative upkeep", "living weapon"}
SILENT_KEYWORDS = set(_SILENT)                    # goldfish.py's KW_SILENT (landwalk moved here in 0.2, as there)
INTERACTION = {"counter_spell", "protect", "remove", "wipe", "gain_control", "prevent_damage", "opponent_discards"}
LAND_TYPES = {"Land", "Plains", "Island", "Swamp", "Mountain", "Forest", "Desert", "Gate", "Cave", "Lair", "Locus",
              "Mine", "Power-Plant", "Tower", "Urza's", "Sphere", "Town"}

def _field_lacks(a):
    """Per-field support: constructs the engine runs only in some shapes (T2's 'validator optimism'). Everything in
    the ability, including granted abilities, counts."""
    out = []
    for o, _ in _nodes(a):
        d, st = o.get("do"), o.get("static")
        if d == "recur" and o.get("to") in ("library_top", "library_bottom"): out.append("recur to library top/bottom")
        if d == "tutor" and "position" in o: out.append("library position")
        if d == "tutor" and "split" in o and (o.get("filter") or {}).get("types") != ["land"]: out.append("split tutor (nonland)")
        if d == "self_to_library" and "position" in o: out.append("library position")
        if st == "enters_tapped":
            if "unless" in o: out.append("conditional enters-tapped")
            if set(o.get("unless_pay", {})) - {"pay_life"}: out.append("enters-tapped payment other than life")
        if st == "type_grant" and ("land" in ((o.get("filter") or {}).get("types") or [])
                                   or LAND_TYPES & set(o.get("add_types") or [])):
            out.append("land type grant")
        if st == "choose_on_enter" and o.get("choice") != "creature_type": out.append("choose " + o.get("choice", "?"))
        if o.get("kind") == "keyword" and o.get("keyword") == "equip" and "filter" in o: out.append("equip [quality]")
        c = o.get("count")
        if c in ("permanents_on_battlefield", "commander_identity_colors", "damage_dealt_this_turn"): out.append("count " + c)
        if c == "total_power" and o.get("filter") != {"attacking": True}: out.append("count total_power (not of attackers)")
        if o.get("controller") == "that_player": out.append("filter controller that_player")
        if "for_each" in o and "ref" in o: out.append("target for each opponent")
    return out
OPPONENT_ONLY = {"opponent_discards", "gain_control", "prevent_damage"}

def _walk(effects):
    for e in effects or []:
        yield e
        for k in ("then", "else", "effects", "on_win", "on_lose"):
            yield from _walk(e.get(k))
        for m in e.get("modes", []): yield from _walk(m)
        for row in e.get("table", []): yield from _walk(row.get("effects"))

def ability_state(a, today):
    """'read' / 'silent' / 'oos' (out of scope, never a miss) / 'missed' / 'part' (read with a part missing),
    plus whether it's interaction."""
    k = a.get("kind")
    if k == "unexpressible": return ("oos" if a.get("scope") == "out_of_scope" else "missed"), False
    if k == "keyword":
        w = a["keyword"]
        if w in SILENT_KEYWORDS: return "silent", False
        return ("read" if (not today or (w in ENGINE_KEYWORDS and not _field_lacks(a))) else "missed"), False
    lacks = []
    fx = list(_walk(a.get("effects", [])))
    if k == "static":
        st = a["effect"]["static"]
        if today and st not in ENGINE_STATICS: lacks.append(st)
        for sub in a["effect"].get("abilities", []):
            s2, _ = ability_state(sub, today)
            if s2 in ("missed", "part"): lacks.append("granted ability")
    if k == "class_level":
        for sub in a.get("abilities", []):
            s2, _ = ability_state(sub, today)
            if s2 in ("missed", "part"): lacks.append("level ability")
    if k == "triggered" and today and a["event"]["on"] not in ENGINE_EVENTS: lacks.append("event " + a["event"]["on"])
    for c in [a.get("if")] + [e.get("cond") for e in fx if e.get("do") == "if"]:
        if c and today:
            stack = [c]
            while stack:
                x = stack.pop()
                if x["if"] not in ENGINE_CONDS: lacks.append("cond " + x["if"])
                stack += x.get("conds", []) + ([x["cond"]] if "cond" in x else [])
    unexp = [e for e in fx if e.get("do") == "unexpressible" and e.get("scope") != "out_of_scope"]
    oos_fx = [e for e in fx if e.get("do") == "unexpressible" and e.get("scope") == "out_of_scope"]
    if today: lacks += [e["do"] for e in fx if e.get("do") not in ENGINE_EFFECTS | {"unexpressible"}] + _field_lacks(a)
    real = [e for e in fx if e.get("do") != "unexpressible"]
    inter = bool(real) and all(e["do"] in INTERACTION | {"if", "choose", "may_pay"} for e in real)
    if real and all(e["do"] in OPPONENT_ONLY for e in real): return "oos", True
    if not real and oos_fx and not unexp: return "oos", False
    if lacks or unexp: return ("part" if real and len(lacks) + len(unexp) < len(real) + len(unexp) and not lacks else "missed"), inter
    return "read", inter

def status(gef, card, today=True):
    tl = card.get("type_line", "")
    abilities = [a for f in (gef.get("faces") or [gef]) for a in f.get("abilities", [])]
    states = [ability_state(a, today) for a in abilities]
    done = sum(1 for s, _ in states if s in ("read", "part"))
    missed = sum(1 for s, _ in states if s in ("missed", "part"))
    vac = sum(1 for s, _ in states if s == "oos")
    if "Land" in tl.split("—")[0] and "//" not in card.get("name", ""):
        return "land" if not missed else "land*"
    spell = re.search(r"\b(?:Instant|Sorcery)\b", tl.split("//")[0])
    if spell and any(i for s, i in states if s in ("read", "part")): return "held"
    if missed and not done: return "vacuum" if vac and missed == 0 else "blank"
    if not done and vac and not missed: return "vacuum"
    return "partial" if missed else "modeled"

# ---------------------------------------------------------------- CLI
def load_cards():
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import mtg
    return mtg

def validate(gef, mtg):
    errs = check(gef, SCHEMA)
    try:
        import jsonschema
        js = sorted(e.message[:80] for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(gef))
        if bool(js) != bool(errs): errs.append(f"(validator disagreement: jsonschema says {'invalid: ' + js[0] if js else 'valid'})")
    except ImportError:
        pass
    card = None
    if isinstance(gef, dict) and gef.get("name"):
        c, how = mtg.find(gef["name"])
        if not c or how not in ("exact", "alias"): errs.append(f"not an Oracle card name: {gef['name']!r}")
        else: card = c
    if card and not errs: errs += lint(gef) + coverage(gef, card)
    return errs, card

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_status, quiet = "--status" in sys.argv, "--quiet" in sys.argv
    mtg = load_cards()
    n = bad = 0
    for path in args:
        data = json.load(open(path, encoding="utf-8"))
        for gef in (data if isinstance(data, list) else [data]):
            n += 1
            errs, card = validate(gef, mtg)
            name = gef.get("name", "?") if isinstance(gef, dict) else "?"
            if errs:
                bad += 1
                print(f"REJECT  {name}")
                for e in errs[:8]: print(f"        {e}")
            elif not quiet or show_status:
                extra = f"  status: expressed={status(gef, card, today=False)} today={status(gef, card)}" if show_status else ""
                print(f"ACCEPT  {name}{extra}")
    print(f"\n{n} translations, {n - bad} accepted, {bad} rejected")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
