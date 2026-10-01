#!/usr/bin/env python3
"""T2 step 4: compare GEF translations with goldfish.py's regex parser on the same cards.

  python3 translation/t2_compare.py GEF.json [GEF.json ...] [--out DIR]   # writes DIR (default translation/prototype)/compare.json + review.md

Both sides are reduced to a signature: the card's status (the parser's as goldfish_coverage reports it, GEF's as it
would compile against today's engine), effect families, trigger events and combat keywords. A card whose signatures
differ is a disagreement to review by hand against Oracle text; review.md lays each one out side by side.
"""
import contextlib, io, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, HERE)
import mtg, goldfish as g, goldfish_coverage as gc            # noqa: E402
import validate as V                                          # noqa: E402

PFX = {"draw": "draw", "wheel": "wheel", "look": "look", "look_f": "look", "peek": "look", "arrange": "look",
       "scry": "scry", "surveil": "surveil", "land_search": "tutor", "tutor": "tutor", "tutor_multi": "tutor",
       "recur": "recur", "regrow_self": "recur", "dig_gy": "recur", "mill": "mill", "putback": "put_back",
       "discard": "discard", "extra_land": "extra_land", "land_from_hand": "land_from_hand", "token": "token",
       "treasure": "token", "amass": "token", "copy_token": "copy_token", "mana": "mana", "mana_n": "mana",
       "mana_x": "mana", "mana_dmg": "mana", "prolif": "proliferate", "ctr": "counters", "ctr_on": "counters",
       "double_ctr": "counters", "free_cast": "cast_free", "cascade": "reveal_until", "free_top": "cast_free",
       "face": "drain", "life_dmg": "gain_life", "life_lost": "gain_life", "pump": "pump", "double_pow": "pump",
       "pump_team": "pump_team", "kill_blk": "remove", "kill_perm": "remove", "noblock": "remove", "unblock": "pump",
       "extra_combat": "extra_combat", "untap_self": "untap", "untap_lands": "untap", "untap_n_lands": "untap",
       "untap_cr": "untap", "win": "win_game", "oracle": "win_game", "level": "level", "bounce_self": "bounce_self",
       "self_top": "self_to_library", "bob": "draw", "sylvan": "draw", "pay_x_draw": "draw", "biorhythm": "set_life",
       "reveal_lands": "look", "lose": "lose_life"}
PEV = {"etb": "enters", "landfall": "enters", "dies": "dies", "dies_self": "dies", "dies_att": "dies", "gy_self": "dies",
       "leave_self": "leaves", "attack": "attacks", "attack_self": "attacks", "attack_any": "attacks", "attack_att": "attacks",
       "cdmg": "combat_damage_to_player", "cdmg_self": "combat_damage_to_player", "cdmg_any": "combat_damage_to_player",
       "cdmg_att": "combat_damage_to_player", "dmg_self": "deals_damage", "dmg_att": "deals_damage",
       "unblocked_self": "attacks_unblocked", "blocked": "becomes_blocked", "blocked_self": "becomes_blocked",
       "combat_begin": "combat_begin", "upkeep": "upkeep", "end": "end_step", "drawstep": "draw_step", "main1": "precombat_main",
       "cast": "cast", "opp_cast": "opponent_casts", "opp_draw": "opponent_draws", "opp_second": "opponent_second_spell",
       "opp_land": "opponent_landfall", "gain": "gain_life", "draw_card": "draw_card", "cycle": "cycle", "sac": "sacrifice",
       "prolif": "proliferate"}
GEV = {"cast_self": "cast", "you_attack": "attacks", "cycle_self": "cycle"}
KW = set(V.ENGINE_KEYWORDS) & {"flying", "reach", "trample", "vigilance", "haste", "lifelink", "deathtouch", "menace",
                                "first strike", "double strike", "indestructible", "defender", "infect"}

def pflat(fx):
    for e in fx or []:
        if not isinstance(e, tuple) or not e: continue
        t = e[0]
        if t == "cond": yield from pflat(e[2])
        elif t == "ifdo": yield from pflat(e[2]); yield from pflat(e[3])
        elif t == "paid": yield from pflat(e[3])
        elif t == "opt": yield from pflat([x for m in e[1] for x in (m if isinstance(m, list) else [m])] if isinstance(e[1], (list, tuple)) else [])
        elif t == "life":
            v = e[1]; neg = isinstance(v, int) and v < 0 or (isinstance(v, tuple) and v[0] == "per" and v[1] < 0)
            yield "lose_life" if neg else "gain_life"
        else: yield PFX.get(t, "other:" + t)

def parser_sig(k, seen=None):
    seen = seen if seen is not None else set()
    seen.add(id(k))
    fx = set(pflat(k.spell)) | set(pflat(k.etb)) | set(pflat(k.castfx))
    ev = set()
    if k.etb: ev.add("enters")
    for t in k.trig: fx |= set(pflat(t[2])); ev.add(PEV.get(t[0], "other:" + t[0]))
    for a in k.acts: fx |= set(pflat(a["fx"]))
    for _, f in k.pw: fx |= set(pflat(f))
    for c in k.chapters.values(): fx |= set(pflat(c))
    for lv, (_, _, kk, up) in k.levels.items():
        fx.add("level"); fx |= set(pflat(up))
        if id(kk) not in seen:
            sub = parser_sig(kk, seen)
            fx |= set(sub["fx"]); ev |= set(sub["ev"])
    if k.units or k.cond_units or k.dyn_mana or k.convs or k.sac_outlets: fx.add("mana")
    return {"fx": sorted(x for x in fx if x), "ev": sorted(ev), "kw": sorted(set(k.kw) & KW)}

def gflat(effects):
    for e in V._walk(effects):
        d = e.get("do")
        if d in ("if", "may_pay", "choose", "unexpressible", "choose_number", "flip_coins", "roll_die", "delayed", "unless_opponent_pays"):
            if d in ("flip_coins", "roll_die", "delayed"): yield d
            continue
        if d in ("damage", "lose_life"):
            who = e.get("to") or e.get("who")
            if who in ("you",): yield "lose_life"
            elif who in ("target_creature", "each_creature", "each_opposing_creature", "target_creature_or_planeswalker"): yield "remove"
            else: yield "drain"
        elif d in ("remove", "wipe"): yield "remove"
        elif d in ("counter_spell", "protect", "prevent_damage", "gain_control", "opponent_discards"): continue   # status 'held' carries it
        elif d == "grant":
            for a in e.get("abilities", []):
                if a.get("kind") == "mana": yield "mana"
                yield from gflat(a.get("effects"))
        elif d in ("mill",) and e.get("who") in ("target_opponent", "each_opponent"): continue
        else: yield d

def gef_sig(gef, card=None):
    fx, ev, kw = set(), set(), set()
    def walk(abilities):
        for a in abilities:
            k = a.get("kind")
            if k != "class_level" and V.ability_state(a, True)[0] not in ("read", "part"): continue   # unread today: no signature
            if k == "keyword" and a["keyword"] in KW: kw.add(a["keyword"])
            if k == "triggered":
                if a["event"]["on"] != "class_level": ev.add(GEV.get(a["event"]["on"], a["event"]["on"]))
                fx.update(gflat(a["effects"]))
            if k in ("spell", "activated", "loyalty", "chapter"): fx.update(gflat(a["effects"]))
            if k == "mana": fx.add("mana")
            if k == "class_level": fx.add("level"); walk(a.get("abilities", []))
            if k == "static" and a["effect"].get("abilities"): pass
    for f in (gef.get("faces") or [gef]): walk(f.get("abilities", []))
    if card is not None and re.search(r"\b(?:Plains|Island|Swamp|Mountain|Forest)\b", (card.get("type_line") or "").split("—")[-1]):
        fx.add("mana")                                   # a basic land type's mana comes from the type line, not the text
    return {"fx": sorted(fx), "ev": sorted(ev), "kw": sorted(kw)}

def readings(names):
    idx, ov, cache = mtg.index(), g.load_overrides(), {}
    for n in names:
        c = idx[n.lower()]
        k = g.compile_card(c, frozenset("WUBRG"))
        o = ov.get(mtg.norm(n))
        if o: g.apply_override(k, o, frozenset("WUBRG"))
        cache[n] = k
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): g.explain(cache, list(names), [])
    out = {}
    for ln in buf.getvalue().splitlines():
        m = gc.LINE.match(ln)
        if m and m.group(3) in cache: out[m.group(3)] = (m.group(1), re.sub(r", \d+ in list", "", m.group(4)))
    return cache, out

def compact(gef):
    """A one-line-per-ability rendering of a translation, for review."""
    def eff(es):
        out = []
        for e in es or []:
            d = e["do"]; rest = {k: v for k, v in e.items() if k not in ("do", "text")}
            out.append(d + (" " + json.dumps(rest, ensure_ascii=False, separators=(",", ":")) if rest else ""))
        return "; ".join(out)
    lines = []
    for f in (gef.get("faces") or [gef]):
        for a in f.get("abilities", []):
            k = a["kind"]; body = {x: y for x, y in a.items() if x not in ("kind", "text", "effects", "abilities")}
            lines.append(f"  - {k} {json.dumps(body, ensure_ascii=False, separators=(',', ':')) if body else ''}"
                         + (f" => {eff(a['effects'])}" if a.get("effects") else "")
                         + (f" [{len(a['abilities'])} level abilities: " + " | ".join(
                             x['kind'] + ' ' + eff(x.get('effects')) + json.dumps(x.get('effect', {}), separators=(',', ':')) for x in a['abilities']) + "]" if a.get("abilities") else ""))
    return "\n".join(lines)

def main():
    gefs = {}
    args = sys.argv[1:]
    out = os.path.join(HERE, "prototype")
    if "--out" in args:
        i = args.index("--out"); out = args[i + 1]; args = args[:i] + args[i + 2:]
    for p in args:
        for x in json.load(open(p, encoding="utf-8")): gefs[x.get("name")] = x
    idx = mtg.index()
    names = [n for n in gefs if n and n.lower() in idx]
    cache, read = readings(names)
    rows, md = [], ["# T2 review sheet: GEF translation vs regex parser\n"]
    for n in names:
        gef, card = gefs[n], idx[n.lower()]
        errs, _ = V.validate(gef, mtg)
        ps, pr = read.get(n, ("?", ""))
        psig = parser_sig(cache[n])
        if errs:
            rows.append({"name": n, "valid": False, "errors": errs[:5], "parser_status": ps}); continue
        gs_today, gs_expr = V.status(gef, card), V.status(gef, card, today=False)
        gsig = gef_sig(gef, card)
        diff = {k: {"parser_only": sorted(set(psig[k]) - set(gsig[k])), "gef_only": sorted(set(gsig[k]) - set(psig[k]))} for k in psig}
        agree = ps.replace("override", "modeled") == gs_today and not any(v["parser_only"] or v["gef_only"] for v in diff.values())
        rows.append({"name": n, "valid": True, "parser_status": ps, "gef_today": gs_today, "gef_expressed": gs_expr,
                     "agree": agree, "diff": diff})
        if not agree:
            text = card.get("oracle_text") or " // ".join(f.get("oracle_text", "") for f in card.get("card_faces", []))
            md.append(f"## {n}\n\n**Oracle:** {text}\n\n**Parser ({ps}):** {pr}\n\n**GEF (today {gs_today}, expressed {gs_expr}):**\n{compact(gef)}\n\n"
                      f"**Signature diff:** " + "; ".join(f"{k}: parser-only {v['parser_only']}, gef-only {v['gef_only']}" for k, v in diff.items() if v['parser_only'] or v['gef_only']) + "\n")
    json.dump(rows, open(os.path.join(out, "compare.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(os.path.join(out, "review.md"), "w", encoding="utf-8").write("\n".join(md))
    v = [r for r in rows if r["valid"]]
    print(f"{len(rows)} cards; {len(rows) - len(v)} invalid; {sum(r['agree'] for r in v)} agree; {sum(not r['agree'] for r in v)} to review "
          f"(status mismatches {sum(1 for r in v if r['parser_status'].replace('override', 'modeled') != r['gef_today'])})")

if __name__ == "__main__":
    main()
