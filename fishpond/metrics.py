"""Game records -> the shared result bundle (sim_report's `res`) plus Fishpond's own stats."""
from collections import Counter, defaultdict

# metric -> how the stock-CLI log measures it when that differs from goldfish (printed under the report as '≈' notes)
APPROX_CLI = {
    "lands": "lands = land drops so far (the stock log doesn't show lands put onto the battlefield by effects, or lands that leave)",
    "cmd_out": "cmdr out = your commander has resolved and the log hasn't shown it leaving the battlefield",
    "spent": "mana spent = mana made by your mana abilities, from the log (variable-amount abilities count 1; rituals aren't mana abilities)",
}

def _turn_value(g, t, key, cum=False, fill_last=True):
    rows = g["turns"]
    if cum:
        return sum(r[key] if not isinstance(r[key], list) else len(r[key]) for r in rows if r["t"] <= t)
    vals = [r[key] for r in rows if r["t"] <= t and r[key] is not None]
    return vals[-1] if vals else None

APPROX_HARNESS = {
    "mana": "mana = Forge's own AI estimate of the mana you could make at the start of your main phase (ComputerUtilMana) plus this turn's land drop; unusual sources can be undercounted",
    "colors": "all colors = your untapped mana sources at the start of your main phase plus this turn's land drop can make every color of your commander's identity",
    "extra": "extra = cards drawn during your own turns beyond one a turn (draws on opponents' turns, tutors and other card advantage aren't counted)",
    "spent": "mana spent = mana made by your mana abilities, from the log (variable-amount abilities count 1; rituals aren't mana abilities)",
    "disc": "discarded = your cards put from hand into the graveyard (cleanup and discard effects, and cycling, which goldfish counts apart)",
}

def snap_at(g, t, kind):
    """Latest harness snapshot of `kind` ('main' or 'end') at or before your turn t (None before the first)."""
    sn = g.get("snaps") or {}
    for tt in range(t, 0, -1):
        s = (sn.get(str(tt)) or {}).get(kind)
        if s: return s
    return None

def bundle(games, T, groups, commanders, opp_n=3, produced=None, identity=""):
    """games: parsed records. groups: [(label, compiled regex)]. Returns the sim_report bundle."""
    n = len(games)
    snaps = n and all(g.get("snaps") for g in games)
    if snaps:
        metrics = ("lands", "mana", "colors", "cmd_out", "casts", "spent", "extra", "hand", "gy", "atk", "cdmg", "dmg", "cmdmax", "poison", "kills", "life")
        if all("disc" in s_ for g in games for v in g["snaps"].values() for s_ in v.values()): metrics += ("disc", "recur")
    else:
        metrics = ("lands", "cmd_out", "casts", "spent", "atk", "cdmg", "dmg", "cmdmax", "poison", "kills", "life")
    rec = {m: {t: [] for t in range(1, T + 1)} for m in metrics}
    for g in games:
        last = max([r["t"] for r in g["turns"]] or [1])
        extra = 0
        for t in range(1, T + 1):
            tt = min(t, last)
            row = next((r for r in g["turns"] if r["t"] == tt), None) or {}
            vals = {
                "lands": _turn_value(g, tt, "lands", cum=True),
                "cmd_out": 1 if row.get("cmd_out") else 0,
                "casts": _turn_value(g, tt, "casts", cum=True),
                "spent": sum(r.get("spent", 0) for r in g["turns"] if r["t"] <= tt),
                "atk": row.get("atk", 0),
                "cdmg": _turn_value(g, tt, "cdmg", cum=True),
                "dmg": _turn_value(g, tt, "dmg", cum=True),
                "cmdmax": max([r.get("cmd", 0) for r in g["turns"] if r["t"] <= tt] or [0]),
                "poison": max([r.get("poison", 0) for r in g["turns"] if r["t"] <= tt] or [0]),
                "kills": row.get("dead", 0),
                "life": _turn_value(g, tt, "life") or 40,
            }
            if snaps:
                m_, e_ = snap_at(g, tt, "main"), snap_at(g, tt, "end") or snap_at(g, tt, "main")
                se = (g["snaps"].get(str(tt)) or {}).get("end")
                if se and t <= last: extra += max(0, se.get("drawn", 0) - 1)
                drop = row.get("land_names") or []
                cols = set((m_ or {}).get("producible") or "")
                for ln in drop: cols |= set((produced or {}).get(ln, ""))
                vals.update({"lands": e_["lands"] if e_ and "lands" in e_ else (m_["lands"] + len(drop) if m_ else len(drop)),
                             "mana": (max(0, m_["mana"]) if m_ else 0) + min(1, len(drop)),
                             "colors": 1 if set(identity or "") <= cols else 0, "cmd_out": 1 if m_ and m_["cmd_out"] else 0,
                             "extra": extra, "hand": e_["hand"] if e_ else 7, "gy": e_["gy"] if e_ else 0,
                             "disc": (e_ or {}).get("disc", 0), "recur": (e_ or {}).get("recur", 0),
                             "life": e_["life"] if e_ else vals["life"]})
            for m in metrics: rec[m][t].append(vals[m])
    cmd_first = {c: [g["first_in"].get(c) for g in games] for c in commanders}
    first = {}
    for gi, (label, rx) in enumerate(groups):
        first[gi] = []
        for g in games:
            ts = [t for name, t in list(g["first_cast"].items()) + list(g["first_in"].items()) if rx.search(name)]
            first[gi].append(min(ts) if ts else None)
    finals = []
    for g in games:
        f = {"deaths": sorted(d["t"] for d in g["deaths"]), "won": g["end_t"] if g["result"] == "win" else None,
             "how": [d["route"] for d in g["deaths"]], "life": (g["turns"][-1]["life"] if g["turns"] and g["turns"][-1]["life"] is not None else 40)}
        if g["result"] == "loss":
            f["died"], f["death"] = g["loss"]["t"], g["loss"]["why"]
        finals.append(f)
    kept = Counter(g["kept"] for g in games if g.get("kept"))
    dsrc = Counter()
    for g in games: dsrc.update(g.get("dmg_src") or {})
    atk_turns = sum(sum(1 for r in g["turns"] if r["t"] <= T and r["atk"]) for g in games) / max(1, n)
    return {"rec": rec, "turns": T, "trials": n, "cmd_first": cmd_first, "first": first, "finals": finals,
            "kept": kept, "mulliganed": sum(1 for g in games if (g.get("kept") or 7) < 7 or g.get("mulligans")) / max(1, n),
            "dsrc": dsrc, "atk_turns": atk_turns}

def _deck(g, seat):
    """The deck label in seat `seat` of game g (dummies read 'dummy (seat N)')."""
    p = next((p for p in g.get("pod", []) if p["seat"] == seat), None)
    if not p: return f"seat {seat}"
    return f"dummy (seat {seat})" if p["kind"] == "dummy" else p["deck"]

def extras(games, hero, T):
    """Fishpond's own numbers: results, routes, losses, seat order, card stats, pilot tags."""
    n = len(games)
    res = Counter(g["result"] for g in games)
    routes = Counter(g["route"] or "?" for g in games if g["result"] == "win")
    losses = Counter()
    for g in games:
        if g["result"] == "loss":
            l = g["loss"]
            who = "" if l["by"] in (None, 1) else f" ({_deck(g, l['by'])})"
            src = f": {l['src']}" if l.get("src") and l["why"] in ("alternate win", "spell effect", "opponent alternate win") else ""
            losses[l["route"] + src + who] += 1
    draws = Counter({"cap": "turn cap"}.get(g.get("stop"), g.get("stop")) if g.get("stop") not in (None, "natural")
                    else "clock" if g.get("stopped") else "no winner" for g in games if g["result"] == "draw")
    order = defaultdict(lambda: [0, 0])
    for g in games:
        if g.get("order"):
            order[g["order"]][0] += 1
            order[g["order"]][1] += g["result"] == "win"
    cast_games, cast_turn, cast_n = Counter(), defaultdict(list), Counter()
    win_with, games_with = Counter(), Counter()
    for g in games:
        for c, t in g["first_cast"].items():
            cast_games[c] += 1; cast_turn[c].append(t)
        for c, k in g["casts"].items(): cast_n[c] += k
        for c in set(g["first_cast"]) | {x for x in g["first_in"]}:
            games_with[c] += 1; win_with[c] += g["result"] == "win"
    seen = set()
    for g in games: seen |= set(g["first_cast"]) | set(g["first_in"])
    tags = Counter(t for g in games for t in g.get("tags", []))
    dummy = [(i, g["dummy_acts"]) for i, g in enumerate(games) if g.get("dummy_acts")]
    kills_by = Counter()
    for g in games:
        for d in g["deaths"]:
            kills_by["you" if d["by"] == 1 else _deck(g, d["by"]) if d["by"] else "unattributed/self"] += 1
    cmd_casts = [len(g["cmd_casts"]) for g in games]
    trig = Counter()
    for g in games: trig.update(g.get("trig_src") or {})
    ms = [g.get("ms") or 0 for g in games]
    end_hand = Counter()
    for g in games:
        for c in set(((g.get("end") or {}).get("hand")) or []): end_hand[c] += 1
    tut = [t for g in games for t in g.get("tutors") or []]
    searches = [t for t in tut if t["kind"] == "search"]
    tutor = {"games": sum(1 for g in games if g.get("tutors") is not None), "searches": len(searches),
             "digs": sum(1 for t in tut if t["kind"] == "dig"),
             "nonland": Counter(t["card"] for t in searches if not t["land"]), "lands": sum(1 for t in searches if t["land"]),
             "by_src": defaultdict(Counter), "key_picked": sum(1 for t in searches if t["key"]),
             "key_left": sum(1 for t in searches if not t["key"] and t["keys_left"])}
    for t in searches:
        if not t["land"]: tutor["by_src"][t["src"]][t["card"]] += 1
    ms_all = sorted((g.get("end") or {}).get("ms") or g.get("ms") or 0 for g in games)
    return {"n": n, "results": res, "tutor": tutor, "game_ms": ms_all, "routes": routes, "losses": losses, "draws": draws, "order": dict(order),
            "cast_games": cast_games, "cast_turn": cast_turn, "cast_n": cast_n, "games_with": games_with, "win_with": win_with,
            "seen": seen, "tags": tags, "dummy": dummy, "kills_by": kills_by, "cmd_casts": cmd_casts, "trig": trig, "ms": ms, "end_hand": end_hand,
            "hero_turns": [g["hero_turns"] for g in games]}
