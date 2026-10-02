"""Forge game log -> one record per game (Fishpond schema v1).

Forge prints a game's log when the game ends, one entry per line ('Turn:', 'Phase:', 'Land:', 'Mana:', 'Add To Stack:',
'Resolve Stack:', 'Damage:', 'Life:', 'Combat:', 'Zone Change:', 'Mulligan:', 'Game Outcome:', ...); entries that span
lines continue without a prefix. Players are 'Ai(k)-<tag>', the hero is seat 1.

Turns are hero turns: event e belongs to hero turn H if it happens during the hero's H-th turn, or in the opponents'
turns before it (so "by T5" means "before the end of your 5th turn"). Forge's 'Game Outcome: Turn N' is not used;
it doesn't match the log's own counter.

Attribution (who dealt damage) uses the seat whose list holds the source card's name; when several do, the seats
seen controlling that card id (lands played, attackers, activations). Tokens and shared names fall back to the id;
unknown sources stay unattributed. A vacuum pod has nothing else that deals damage, so there it is exact.
"""
import re
from collections import Counter

P = r"Ai\((\d+)\)-\S+"
RX_TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d+)\)-")
RX_LAND = re.compile(rf"^Land: {P} played (.+?) \((\d+)\)$")
RX_STACK = re.compile(rf"^Add To Stack: {P} (cast|triggered|activated) (.+?)(?: targeting (.+))?$")
RX_RESOLVE = re.compile(r"^Resolve Stack: (.+?)(?: \((\d+)\))?(?: - (.*))?$")
RX_ACTIVATOR = re.compile(rf"\[Card: (.+?) \((\d+)\), Activator: {P}")
RX_ZCHANGER = re.compile(r"\[Zone Changer: (.+?) \((\d+)\)\]")
RX_DAMAGE = re.compile(r"^(?:Damage: )?(.+?) \((\d+)\) deals (\d+) (?:([\w-]+) )?\s*damage to (.+?)( \(as poison counters\))?\.$")
RX_LIFE = re.compile(rf"^Life: Life: {P} (-?\d+) > (-?\d+)$")
RX_POISON = re.compile(rf"{P} receives (\d+) poison counters? from (.+?)$")
RX_ATTACK = re.compile(rf"{P} assigned (.+) to attack (.+?)\.$")
RX_KEPT = re.compile(rf"^Mulligan: {P} has kept a hand of (\d+) cards")
RX_MULL = re.compile(rf"{P} has mulliganed down to (\d+) cards")
RX_ZONE = re.compile(r"^Zone Change: (.+?) \((\d+)\) was put into (\w+) from (\w+)\.$")
RX_OUTCOME = re.compile(rf"^Game Outcome: {P} (has won|has lost|has conceded|accepted)(.*)$")
RX_RESULT = re.compile(r"^Game Result: Game (\d+) ended in (?:(\d+) ms\.|a Draw! Took (\d+) ms\.)")
RX_PLAYER_TARGET = re.compile(rf"^{P}$")
RX_MANA = re.compile(r"^Mana: (.+?) \((\d+)\) - (.*)$")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

def mana_amount(text):
    """Mana an ability line makes: 'Add {C}{C}' = 2, 'Add {G} or {U}' / 'one mana of any color' = 1; variable amounts = 1."""
    seg = text.split("Add", 1)[1] if "Add" in text else text
    seg = seg.split(".")[0]
    m = re.search(r"\b(one|two|three|four|five) mana\b", seg)
    if m: return WORDS[m.group(1)]
    if " or " in seg: return 1
    return max(1, len(re.findall(r"\{[WUBRGCS]\}", seg)))
RX_CARD_IDS = re.compile(r"\((\d+)\)")
PREFIXES = ("Turn:", "Phase:", "Land:", "Mana:", "Add To Stack:", "Resolve Stack:", "Damage:", "Life:", "Combat:", "Zone Change:",
            "Mulligan:", "Game Outcome:", "Game Result:", "Match Result:", "Replacement Effect:", "Player Control:", "Stopping slow match")

# cards that win with an empty library when their trigger resolves: casting one into pending draw triggers can deck you first
EMPTY_LIBRARY_WINS = {"Thassa's Oracle", "Laboratory Maniac", "Jace, Wielder of Mysteries"}
# "may ... repeat" library dumps: Forge's AI accepts every optional put, so it can empty its own library
LIBRARY_DUMPS = {"Primal Surge"}

def split_games(text):
    """stdout of a Forge sim run -> [lines of one game], one per 'Game Result:' line (startup noise dropped)."""
    games, cur = [], []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line: continue
        cur.append(line)
        if line.startswith("Game Result:"):
            games.append(cur); cur = []
    return games

def _play(s):
    """Forge's printout of a play, without card ids: 'Imperial Seal (4) -> Search your...' -> 'Imperial Seal -> Search your...'."""
    return re.sub(r" \(\d+\)", "", s).replace(" -> <$> - ", " - ")

def harness_lines(lines):
    """The harness's own lines in a game block: (snaps {hero turn: {'main': {...}, 'end': {...}}}, end info or None)."""
    import json
    snaps, end, tutors, searches = {}, None, [], {}
    for line in lines:
        if line.startswith("#FP-SNAP "):
            s = json.loads(line[9:])
            snaps.setdefault(str(s["t"]), {})[s["at"]] = s
        elif line.startswith("#FP-TUTOR "):
            tutors.append(json.loads(line[10:]))
        elif line.startswith("#FP-SEARCH "):             # one lookahead search (patch 06): size, time, whether the budget cut it
            q = json.loads(line[11:])
            a = searches.setdefault(q.get("seat", "?"), {"n": 0, "capped": 0, "max_nodes": 0, "ms": 0, "max_ms": 0})
            a["n"] += 1; a["capped"] += bool(q.get("capped")); a["ms"] += q["ms"]
            a["max_nodes"] = max(a["max_nodes"], q["nodes"]); a["max_ms"] = max(a["max_ms"], q["ms"])
            for o in q.get("options") or []: o["play"] = _play(o["play"])
            q["chosen"] = _play(q["chosen"]); q["line"] = [_play(re.sub(r"^\[initScore=\S+(?: \(available [^)]*\))? ", "", x).rstrip("]"))
                                                        for x in q.get("line") or []]
            opts = sorted(q.get("options") or [], key=lambda o: -o["score"])
            if len(opts) >= 2:                              # a real choice: keep what it picked, the runner-up, and what the budget cut
                a.setdefault("decisions", []).append({
                    "t": q["turn"], "phase": q["phase"], "positions": q["nodes"], "capped": q["capped"], "ms": q["ms"],
                    "chosen": q["chosen"], "line": q.get("line") or [], "base": q.get("base"),
                    "best": opts[0], "runner_up": opts[1],
                    "cut": [o for o in opts if o["depth"] != "full"]})
        elif line.startswith("#FP-END "):
            end = json.loads(line[8:])
        elif line.startswith("#FP-ERROR "):
            end = dict(json.loads(line[10:]), stop="error")
    if end is not None: end["searches"] = searches       # per seat name
    if end is not None: end["tutors"] = tutors      # the hero's library searches and digs into hand or play
    return snaps, end

def outcome_kind(text):
    """The tail of a 'Game Outcome: Ai(k)-X has ...' line -> (won|lost|draw, reason, card)."""
    t = text.strip()
    m = re.search(r"due to effect of '+(.+?)'+$", t)
    if t.startswith("has won"):
        return ("won", "alternate win", m.group(1)) if m else ("won", "all opponents lost", None)
    if t.startswith("has conceded"): return ("lost", "conceded", None)
    if t.startswith("accepted"): return ("draw", "draw", None)
    if "empty library" in t: return ("lost", "decked", None)
    if "life total reached 0" in t: return ("lost", "life", None)
    if "poison" in t: return ("lost", "poison", None)
    if "21 damage from generals" in t: return ("lost", "commander damage", None)
    m2 = re.search(r"won by spell '+(.+?)'+", t)
    if m2: return ("lost", "opponent alternate win", m2.group(1))
    m3 = re.search(r"effect of spell '+(.+?)'+", t)
    if m3: return ("lost", "spell effect", m3.group(1))
    return ("lost", "unknown", None)

class Seat:
    def __init__(self, k, tag, kind, names, commanders, label=""):
        self.k, self.tag, self.kind, self.label = k, tag, kind, label
        self.names, self.commanders = set(names), set(commanders)

def parse_game(lines, seats, hero=1):
    """lines: one game's log. seats: {k: Seat}. Returns the game record (see docs/FISHPOND.md 'Game records')."""
    by_name = {}
    for k, s in seats.items():
        for n in s.names: by_name.setdefault(n, set()).add(k)
    owner_id = {}                       # card id -> seat seen controlling it
    def owner(name, cid):
        ks = by_name.get(name)
        if ks and len(ks) == 1: return next(iter(ks))
        if cid is not None and cid in owner_id: return owner_id[cid]
        if ks and hero in ks and cid is not None and cid <= 100: return hero
        return None

    H, active, gturn, first = 0, None, 0, None
    turns = {}                          # hero turn -> stats
    def T(t):
        if t not in turns:
            turns[t] = {"lands": 0, "land_names": [], "spent": 0, "casts": [], "trig": 0, "act": 0, "dmg": 0, "cdmg": 0, "atk": 0, "life": None,
                        "poison": 0, "cmd": 0, "dead": 0, "cmd_out": None}
        return turns[t]
    def idx(): return H if active == hero else H + 1

    life = {k: 40 for k in seats}
    poison = {k: 0 for k in seats}
    cmd_dmg = Counter()                 # (source seat, target seat) -> commander combat damage from source's commander(s)
    poison_by = Counter()               # (source seat, target seat) -> poison counters
    pending = {k: [] for k in seats}    # damage events awaiting their Life line: (amount, combat, src seat, src name)
    last_res = None                     # (name, seat) of the latest resolving object, for life loss without damage
    stack = []                          # (seat, card) per 'Add To Stack', popped by 'Resolve Stack' (by name, else the top)
    kill = {}                           # seat -> (hero turn, route, killer seat, source) when life first hit 0
    last_seen = {k: 0 for k in seats}   # seat -> last hero-turn index the seat appears in the log
    first_cast, first_in, cast_n = {}, {}, Counter()
    cast_turns, last_cast = {}, None
    cmd_casts, cmd_res = [], []
    cmd_out = False
    dsrc, trig_src, act_src = Counter(), Counter(), Counter()
    kept, mulls, mull_to = {}, Counter(), {}      # Forge logs "kept a hand of 7" even after a mulligan; the size is in "mulliganed down to N"
    stack_casts = []                    # hero casts not yet resolved, in order: [hero turn, name]
    dummy_acts = []
    outcomes, result_ms, stopped, outcome_lines = {}, None, False, []
    tags = []
    events = 0
    prev_kind = None

    hero_cmds = seats[hero].commanders
    ai_timeouts = 0
    for line in lines:
        if line.startswith("AI eval thread at timeout"): ai_timeouts += 1; continue
        kind = next((p for p in PREFIXES if line.startswith(p)), None)
        if kind is None: kind = prev_kind if prev_kind in ("Combat:", "Damage:") else None
        else: prev_kind = kind
        if kind not in (None, "Phase:", "Mana:"): events += 1
        for m in re.finditer(r"Ai\((\d+)\)-", line):
            k = int(m.group(1))
            if k in last_seen and not line.startswith(("Game Outcome:", "Match Result:", "Player Control:", "Game Result:")):
                last_seen[k] = idx()
        if line.startswith("Stopping slow match"): stopped = True; continue
        m = RX_TURN.match(line)
        if m:
            stack = []
            gturn, active = int(m.group(1)), int(m.group(2))
            if first is None: first = active
            if active == hero:
                H += 1; t = T(H); t["cmd_out"] = cmd_out
                if t["life"] is None: t["life"] = life[hero]
            continue
        m = RX_MANA.match(line)
        if m:
            if owner(m.group(1), int(m.group(2))) == hero: T(idx())["spent"] += mana_amount(m.group(3))
            continue
        m = RX_KEPT.match(line)
        if m: kept[int(m.group(1))] = int(m.group(2)); continue
        m = RX_MULL.search(line)
        if m: mulls[int(m.group(1))] += 1; mull_to[int(m.group(1))] = int(m.group(2)); continue
        m = RX_LAND.match(line)
        if m:
            k, name, cid = int(m.group(1)), m.group(2), int(m.group(3))
            owner_id[cid] = k
            if k == hero:
                T(idx())["lands"] += 1; T(idx())["land_names"].append(name)
                first_in.setdefault(name, idx())
            continue
        m = RX_STACK.match(line)
        if m:
            k, verb, name = int(m.group(1)), m.group(2), m.group(3)
            stack.append((k, name))
            if seats[k].kind == "dummy": dummy_acts.append(f"{verb} {name}")
            if k == hero:
                t = T(idx())
                if verb == "cast":
                    t["casts"].append(name); cast_n[name] += 1; last_cast = name; cast_turns.setdefault(name, []).append(idx())
                    first_cast.setdefault(name, idx())
                    stack_casts.append([idx(), name])
                    if name in hero_cmds: cmd_casts.append(idx())
                elif verb == "triggered": t["trig"] += 1; trig_src[name] += 1
                else: t["act"] += 1; act_src[name] += 1
            continue
        m = RX_RESOLVE.match(line)
        if m:
            name = m.group(1)
            a = RX_ACTIVATOR.search(line)
            if a: owner_id[int(a.group(2))] = int(a.group(3))
            z = RX_ZCHANGER.search(line)
            if z:
                zk = owner(z.group(1), int(z.group(2)))
                if zk == hero: first_in.setdefault(z.group(1), idx())
            for j, (_, cname) in enumerate(stack_casts):
                if cname == name:
                    first_in.setdefault(name, idx()); del stack_casts[j]
                    if name in hero_cmds:
                        cmd_res.append(idx()); cmd_out = True
                    break
            j = next((j for j in range(len(stack) - 1, -1, -1) if stack[j][1] == name), len(stack) - 1)
            if stack:
                sk, sname = stack.pop(j)
                last_res = (sname, sk)
            else:
                last_res = (name, owner(name, int(m.group(2)) if m.group(2) else None))
            continue
        m = RX_ZONE.match(line)
        if m:
            name, cid, to, frm = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            if name in hero_cmds and frm == "Battlefield" and to != "Battlefield" and owner(name, cid) == hero: cmd_out = False
            if to == "Battlefield" and owner(name, cid) == hero: first_in.setdefault(name, idx())
            continue
        m = RX_ATTACK.search(line) if kind == "Combat:" else None
        if m:
            k, who = int(m.group(1)), m.group(2)
            ids = [int(x) for x in RX_CARD_IDS.findall(who)]
            for cid in ids: owner_id[cid] = k
            if seats[k].kind == "dummy": dummy_acts.append("attacked")
            if k == hero: T(idx())["atk"] += len(ids)
            continue
        m = RX_DAMAGE.match(line) if kind == "Damage:" else None
        if m:
            src, cid, n, dtype, tgt, inf = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4), m.group(5), m.group(6)
            pt = RX_PLAYER_TARGET.match(tgt)
            if not pt: continue
            tk, sk, combat = int(pt.group(1)), owner(src, int(cid)), dtype == "combat"
            if inf:
                poison[tk] += n; poison_by[(sk, tk)] += n
                if sk == hero and tk != hero: T(idx())["poison"] = max(v for (a, b), v in poison_by.items() if a == hero)
                if sk == hero and tk != hero: T(idx())["dmg"] += n
                continue
            pending[tk].append((n, combat, sk, src))
            if sk is not None and src in seats[sk].commanders and combat and sk != tk:
                cmd_dmg[(sk, tk)] += n
                if sk == hero: T(idx())["cmd"] = max(v for (a, b), v in cmd_dmg.items() if a == hero)
            continue
        m = RX_POISON.search(line)
        if m:
            tk, n = int(m.group(1)), int(m.group(2))
            pk = owner(m.group(3).split(" (")[0], None)
            poison[tk] += n; poison_by[(pk, tk)] += n
            if pk == hero and tk != hero: T(idx())["poison"] = max(v for (a, b), v in poison_by.items() if a == hero)
            continue
        m = RX_LIFE.match(line)
        if m:
            k, a, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
            life[k] = b
            if k == hero: T(idx())["life"] = b
            lost = a - b
            pend, pending[k] = pending[k], []
            if lost <= 0: continue
            parts, left = [], lost
            for n, combat, sk, src in pend:
                use = min(n, left)
                if use > 0: parts.append((use, "combat" if combat else "noncombat", sk, src)); left -= use
            if left > 0:
                parts.append((left, "life loss", last_res[1] if last_res else None, last_res[0] if last_res else "?"))
            for n, route, sk, src in parts:
                if sk == hero and k != hero:
                    t = T(idx()); t["dmg"] += n
                    if route == "combat": t["cdmg"] += n
                    dsrc[src] += n
            if b <= 0 and k not in kill:              # the killing blow: the biggest share of the final life change
                n, route, sk, src = max(parts, key=lambda x: x[0])
                kill[k] = (idx(), route, sk, src)
            continue
        m = RX_OUTCOME.match(line)
        if m:
            k = int(m.group(1))
            outcome_lines.append(line)
            outcomes[k] = outcome_kind(m.group(2) + m.group(3))
            continue
        m = RX_RESULT.match(line)
        if m: result_ms = int(m.group(2) or m.group(3) or 0); continue

    # ---------------------------------------------------------------- outcome
    winners = [k for k, o in outcomes.items() if o[0] == "won"]
    ho = outcomes.get(hero, ("draw", "no outcome", None))
    if ho[0] == "lost": result = "loss"
    elif ho[0] == "won" and len(winners) == 1: result = "win"
    else: result = "draw"           # a clock-out marks every survivor as a winner; that is an unfinished game
    deaths = []
    alt_winner = next((k for k, o in outcomes.items() if o[0] == "won" and o[1] == "alternate win"), None)
    def killer_for(k, why):
        if why == "commander damage": return next((sk for (sk, tk), v in cmd_dmg.items() if tk == k and v >= 21), None)
        if why == "poison":
            src = Counter({sk: v for (sk, tk), v in poison_by.items() if tk == k})
            return src.most_common(1)[0][0] if src else None
        if why == "opponent alternate win": return alt_winner
        return None
    for k, s in seats.items():
        if k == hero or outcomes.get(k, ("",))[0] != "lost": continue
        why, card = outcomes[k][1], outcomes[k][2]
        if why == "life" and k in kill:
            t, route, killer, src = kill[k]
        else:
            t, killer, src = last_seen[k] or 1, killer_for(k, why), card
            route = {"opponent alternate win": "alternate win"}.get(why, why)
        deaths.append({"seat": k, "t": t, "why": why, "route": route, "by": killer, "src": src})
    deaths.sort(key=lambda d: d["t"])
    hero_death = None
    if result == "loss":
        why, card = ho[1], ho[2]
        if why == "life" and hero in kill:
            t, route, killer, src = kill[hero]
        else:
            t, route, killer, src = (last_seen[hero] or H or 1), {"opponent alternate win": "alternate win"}.get(why, why), killer_for(hero, why), card
        hero_death = {"t": t, "why": why, "route": route, "by": killer, "src": src}
        hero_death["last_cast"] = last_cast
        if why == "decked":
            unresolved = [c for c in stack_casts if c[1] in EMPTY_LIBRARY_WINS and c[0] >= t - 1]
            if unresolved: tags.append("oracle_trap")
            if any(first_cast.get(c) is not None and cast_turns[c] and cast_turns[c][-1] == t for c in LIBRARY_DUMPS): tags.append("surge_trap")
            tags.append("self_decked")
    route = None
    if result == "win":
        ho_card = ho[2]
        if ho[1] == "alternate win": route = f"alternate win: {ho_card}"
        elif deaths: route = deaths[-1]["route"] + (f": {deaths[-1]['src']}" if deaths[-1]["route"] == "alternate win" else "")
    end_t = H if result == "win" else (hero_death["t"] if hero_death else H)
    if result == "win" and deaths: end_t = max(d["t"] for d in deaths)
    for t in range(1, max(turns) + 1 if turns else 1): T(t)
    # per-turn cumulative opponent state at the end of each hero turn
    for t, st in turns.items():
        st["dead"] = sum(1 for d in deaths if d["t"] <= t)
    order = None
    if first is not None:
        n = len(seats)
        order = ((hero - first) % n) + 1
    return {
        "result": result, "route": route, "winner": winners[0] if len(winners) == 1 else None,
        "loss": ({"why": hero_death["why"], "route": hero_death["route"], "by": hero_death["by"], "src": hero_death["src"], "t": hero_death["t"],
                  "last_cast": hero_death["last_cast"]} if hero_death else None),
        "end_t": end_t, "hero_turns": H, "global_turns": gturn, "order": order, "first": first,
        "kept": mull_to.get(hero, kept.get(hero)), "mulligans": mulls.get(hero, 0), "kept_all": kept,
        "deaths": deaths,
        "turns": [dict(turns[t], t=t) for t in sorted(turns)],
        "first_cast": first_cast, "first_in": first_in, "casts": dict(cast_n),
        "cmd_casts": cmd_casts, "cmd_resolved": cmd_res,
        "cmd_dmg": {f"{a}>{b}": v for (a, b), v in cmd_dmg.items()},
        "poison": {str(k): v for k, v in poison.items() if v},
        "final_life": {str(k): v for k, v in life.items()},
        "dmg_src": dict(dsrc), "trig_src": dict(trig_src), "act_src": dict(act_src),
        "dummy_acts": dummy_acts[:10], "tags": tags, "stopped": stopped, "ai_timeouts": ai_timeouts,
        "outcomes": outcome_lines, "ms": result_ms, "events": events,
    }
