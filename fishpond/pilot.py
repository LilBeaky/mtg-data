"""Pilot-failure report: what the pilots got wrong, every seat, per 100 seat-games, across runs.

  python -m fishpond pilot RUN_DIR [RUN_DIR...] [--vs OLD_DIR...] [--examples N] [--json]

The overnight review of 2026-10-28 as a command (the user: "review the data and report trends in pilot failure"), so every
study ends with the same table and a before/after is one flag. A run folder or a study folder (searched for games.jsonl).
Read from each pod's games.jsonl and its worker logs (#FP-PLAN, #FP-SEQ, #FP-MULL, #FP-REMOVAL, #FP-COUNTER, #FP-WIPE,
#FP-BOARD, the Forge game log); every seat counts, so a deck's numbers come from all its seats in every pod.

Failures, each counted per 100 seat-games (events, so a seat can add several), with up to --examples games to replay
(`POD gGAME sSEAT tTURN`: the pod's folder name, the game, the seat, the table turn; `fishpond replay POD_DIR GAME`):
  cmd_waits      own main 1 before the commander's first cast, affordable in the plan's budget, left out of the plan,
                 and not cast that turn (patch 112's target; a recast isn't counted: its value diminishes on purpose, patch 116)
  cmd_never      the seat's game ended without its commander ever resolving (of them, how many played 5+ own turns:
                 early deaths are most of the rest)
  closer_miss    a closer or engine line (fishpond/win_lines.txt) available in the game and never played (per line)
  engine_miss
  decked         lost to an empty library
  self_kill      lost to its own life loss or damage (the killer is the seat itself)
  removal_held   removal held against a permanent ("hold" in #FP-REMOVAL), then the seat killed by that permanent's owner
                 within 3 rounds
  counter_kept   a counter kept ("save" in #FP-COUNTER) against a spell, then the seat killed by its caster within 3 rounds
  wipe_refused   a wipe refused ("refuse" in #FP-WIPE), then the seat dead within 2 rounds (of them, how many the wipe
                 would have hit the killer's board); the refusal doesn't say whether it was affordable
  held_3         a castable card held 3+ own turns running with its mana left unused (`fishpond held`'s "idle"; all such
                 streaks, mana spent elsewhere or not, in brackets)
  loops_short    a loop stopped short of its end (stalled, at the goal or at the cap; #FP-LOOP)
Then rates: land drops missed on own turns 1-4 (% of those turns), kept hands of 5 or fewer and 2-land sevens kept
(% of seat-games, #FP-MULL), and each deck's usable mana at main 1 by own turn 1-6 (median, #FP-SEQ; docs/LANDBASE_TEMPO_PLAN.md
step 3). A run without a log line a failure needs shows "-" for it, not 0 (#FP-BOARD from 2026-10-29: before it, a death's
turn comes from the Forge log, exact for life, decking and the game's end, else the seat's last own turn + 1).

Not covered (the 2026-10-28 pass read them by hand): attack-trigger commanders that stayed home, and why a commander never
resolved (removed, off-color, died first). Numbers can differ a little from that scratch pass's.
"""
import json, os, re, statistics as st
from collections import Counter, defaultdict

from . import logparse as lp
from .held import runs_under, seat_decks

ROUND = 4                       # table turns in a round, for the "within N rounds" windows
SEAT = re.compile(r"Ai\((\d)\)")
TURN = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d)\)")
LIFE = re.compile(r"^Life: Life: Ai\((\d)\)\S* -?\d+ > (-?\d+)")
TAGS = ("#FP-PLAN ", "#FP-MULL ", "#FP-REMOVAL ", "#FP-COUNTER ", "#FP-WIPE ", "#FP-BOARD ", "#FP-END ")

FAILURES = [
    ("cmd_waits", "commander affordable (first cast), left out of the plan", "PLAN"),
    ("cmd_never", "commander never resolved", "LINE"),
    ("closer_miss", "closer available, never played", "LINE"),
    ("engine_miss", "engine available, never played", "LINE"),
    ("decked", "decked itself", None),
    ("self_kill", "killed itself", None),
    ("removal_held", "removal held, then killed by the target's owner (3 rounds)", "REMOVAL"),
    ("counter_kept", "counter kept, then killed by the spell's caster (3 rounds)", "COUNTER"),
    ("wipe_refused", "wipe refused, then dead within 2 rounds", "WIPE"),
    ("held_3", "castable card held 3+ turns, mana left idle", "HELD"),
    ("loops_short", "loop stopped short (stalled, goal, cap)", None),
]
RATES = [
    ("no_land", "land drop missed, own turns 1-4", "SEQ"),
    ("keep_small", "kept a hand of 5 or fewer", "MULL"),
    ("keep_2land7", "kept a 2-land seven", "MULL"),
]


def _seat(name):
    m = SEAT.search(str(name))
    return m.group(1) if m else str(name)


def _js(line, tag):
    try: return json.loads(line[len(tag):])
    except ValueError: return None


def game_logs(run):
    """{FP-END id: {tag: [records], "turns": [(table turn, seat)], "life0": {seat: table turn}}} for one pod's worker logs."""
    import glob
    out = {}
    for lf in sorted(glob.glob(os.path.join(run, "logs", "worker_*.log"))):
        for block in lp.split_games(open(lf, encoding="utf-8", errors="replace").read()):
            g = defaultdict(list); g["life0"] = {}
            cur = 0
            for line in block:
                if line.startswith("#FP-"):
                    for tag in TAGS:
                        if line.startswith(tag):
                            x = _js(line, tag)
                            if x is not None: g[tag[4:-1]].append(x)
                            break
                    continue
                m = TURN.match(line)
                if m:
                    cur = int(m.group(1)); g["turns"].append((cur, m.group(2)))
                    continue
                m = LIFE.match(line)
                if m and int(m.group(2)) <= 0: g["life0"].setdefault(m.group(1), cur)
            if g["END"]: out.setdefault(g["END"][-1].get("id"), g)
    return out


def _deaths(r, g):
    """{seat: (table turn, why, killer seat or None)} for every seat that lost before the game's end, or at it."""
    why = {}
    for d in r.get("deaths") or []: why[str(d["seat"])] = (d["why"], d.get("by"))
    if r.get("loss"): why["1"] = (r["loss"]["why"], r["loss"].get("by"))
    last_t = max((t for t, _ in g["turns"]), default=0)
    out_at = {}
    for b in g.get("BOARD", []):
        for s, x in (b.get("seats") or {}).items():
            if x.get("out"): out_at.setdefault(s, b["t"])
    own_last = {}
    for t, s in g["turns"]: own_last[s] = t
    res = {}
    for s, (w, by) in why.items():
        if s in out_at: t = out_at[s]
        elif s in g["life0"]: t = g["life0"][s]
        elif w == "decked": t = own_last.get(s, last_t)
        elif w == "opponent alternate win": t = last_t
        else: t = min(last_t, own_last.get(s, last_t) + 1)
        res[s] = (t, w, str(by) if by is not None else None)
    return res


def seat_games(paths):
    """One dict per seat and game: deck, the facts the failures need, and examples' tags."""
    for run in runs_under(paths):
        meta = json.load(open(os.path.join(run, "meta.json"), encoding="utf-8"))
        hero = meta.get("commander") or os.path.basename(meta.get("deck", "you"))
        tag = os.path.basename(os.path.normpath(run))
        logs = game_logs(run)
        for l in open(os.path.join(run, "games.jsonl"), encoding="utf-8"):
            if not l.strip(): continue
            r = json.loads(l)
            g = logs.get(r.get("log_id"), defaultdict(list, life0={}))
            yield from _seats_of(r, g, hero, tag)


def _seats_of(r, g, hero, tag):
    reach = {str(x["seat"]): x for x in r.get("lines") or [] if x["kind"] == "reach"}
    lines = defaultdict(list)
    for x in r.get("lines") or []:
        if x["kind"] != "reach": lines[str(x["seat"])].append(x)
    decks = {str(k): v for k, v in seat_decks(r, hero).items()}
    deaths = _deaths(r, g)
    own = {}                                    # table turn -> (seat, own turn number)
    n_own = Counter()
    for t, s in g["turns"]:
        n_own[s] += 1; own[t] = (s, n_own[s])
    boards = {b["t"]: b.get("seats") or {} for b in g.get("BOARD", [])}
    have = {k for k in ("PLAN", "MULL", "REMOVAL", "COUNTER", "WIPE", "BOARD") if g.get(k)}
    if r.get("lines"): have.add("LINE")
    if r.get("held") is not None: have.add("HELD")
    if r.get("seq"): have.add("SEQ")
    kept = {}
    for m in g.get("MULL", []):
        if not m.get("mulligan"): kept[_seat(m["player"])] = m
    seats = sorted(set(decks) | set(reach))
    for s in seats:
        deck = (reach.get(s) or {}).get("commander") or decks.get(s, f"seat {s}")
        ex = lambda t: f"{tag} g{r['game']} s{s} t{t}" + (f" (own {own[t][1]})" if t in own and own[t][0] == s else "")
        f = {"deck": deck, "won": str(r.get("winner")) == s, "have": have, "ev": defaultdict(list), "n": {}}
        ev = f["ev"]
        d = deaths.get(s)
        # commander affordable and left out of the plan, not cast that turn
        cmd_names = set()
        for b in boards.values():
            for c in (b.get(s) or {}).get("cmd") or []: cmd_names.add(c["n"])
        if not cmd_names: cmd_names.add(deck)
        plans = [p for p in g.get("PLAN", []) if _seat(p["seat"]) == s]
        planned = {p["t"] for p in plans if any(x["card"] in cmd_names for x in p.get("steps") or [])}
        first_out = (reach.get(s) or {}).get("cmd_first", -1)
        seen = set()
        for p in plans:
            if p.get("phase") != "MAIN1" or p["t"] in seen or p["t"] in planned: continue
            lo = [x for x in p.get("left_out") or [] if x["card"] in cmd_names and x.get("cost", 99) <= p.get("budget", 0)]
            if not lo: continue
            seen.add(p["t"])
            b0, b1 = boards.get(p["t"] - 1, {}).get(s), boards.get(p["t"], {}).get(s)
            # the first cast only: a recast keeps its diminishing value on purpose (patch 116, the user's rule)
            if b0 is not None:
                if any(c.get("casts", 0) for c in b0.get("cmd") or [] if c["n"] == lo[0]["card"]): continue
            elif first_out >= 0 and own.get(p["t"], (s, 0))[1] > first_out: continue
            if b1 is not None:
                zone = {c["n"]: c for c in b1.get("cmd") or []}.get(lo[0]["card"], {})
                before = {c["n"]: c for c in (b0 or {}).get("cmd") or []}.get(lo[0]["card"], {})
                if zone.get("zone") == "Battlefield" or zone.get("casts", 0) > before.get("casts", 0): continue
            ev["cmd_waits"].append(ex(p["t"]))
        x = reach.get(s)
        if x is not None and x.get("cmd_first", 0) < 0:
            ev["cmd_never"].append(ex(own_t(own, s, x.get("turns", 0))) if x.get("turns") else f"{tag} g{r['game']} s{s}")
            f["n"]["cmd_never_5"] = int(x.get("turns", 0) >= 5)
        for y in lines.get(s, []):
            if y["kind"] in ("closer", "engine") and y["avail"] and not y["did"]:
                ev[y["kind"] + "_miss"].append(f"{tag} g{r['game']} s{s} {y['line'][:40]}")
        if d:
            t, why, by = d
            if why == "decked": ev["decked"].append(ex(t))
            elif by == s: ev["self_kill"].append(ex(t))
        # answers kept, then killed by the one they were kept against
        if d and d[2] and d[2] != s:
            t_dead, killer = d[0], d[2]
            for q in g.get("REMOVAL", []):
                if _seat(q["seat"]) == s and q.get("verdict") == "hold" and _seat(q.get("owner")) == killer and 0 <= t_dead - q["t"] <= 3 * ROUND:
                    ev["removal_held"].append(ex(q["t"]) + f" {q['card']} vs {q['target']}"); break
            for q in g.get("COUNTER", []):
                if _seat(q["seat"]) == s and q.get("verdict") == "save" and _seat(q.get("caster")) == killer and 0 <= t_dead - q["turn"] <= 3 * ROUND:
                    ev["counter_kept"].append(ex(q["turn"]) + f" {q['counter']} vs {q['spell']}"); break
        if d:
            t_dead, killer = d[0], d[2]
            for q in g.get("WIPE", []):
                if _seat(q["seat"]) == s and str(q.get("verdict", "")).startswith("refuse") and 0 <= t_dead - q["t"] <= 2 * ROUND:
                    hit = any(_seat(k) == killer and v > 0 for k, v in (q.get("opp") or {}).items())
                    ev["wipe_refused"].append(ex(q["t"]) + f" {q['card']}" + (" (hit the killer)" if hit else ""))
                    f["n"]["wipe_hit"] = f["n"].get("wipe_hit", 0) + hit
                    break
        for h in r.get("held") or []:
            if str(h["seat"]) == s and h["turns"] >= 3 and not h["instant"]:
                f["n"]["held_all"] = f["n"].get("held_all", 0) + 1
                if h.get("unspent"):
                    ev["held_3"].append(f"{tag} g{r['game']} s{s} {h['card']} own {h['from']}-{h['from'] + h['turns'] - 1}")
        for lo in r.get("loops") or []:
            if lo.get("event") == "stop" and _seat(lo.get("player")) == s and lo.get("reason") in ("stalled", "goal", "cap"):
                ev["loops_short"].append(f"{tag} g{r['game']} s{s} t{lo.get('turn')} {lo.get('play')} x{lo.get('iterations')} {lo['reason']}")
        # rates
        early = [q for q in r.get("seq") or [] if str(q["seat"]) == s and q["turn"] <= 4]
        f["n"]["early_turns"] = len(early)
        f["n"]["no_land"] = sum(1 for q in early if not q["land"])
        f["mana"] = {q["turn"]: q["mana"] for q in r.get("seq") or [] if str(q["seat"]) == s and q["turn"] <= 6}
        k = kept.get(s)
        if k is not None:
            f["n"]["keep_small"] = int(k.get("cards", 7) <= 5)
            f["n"]["keep_2land7"] = int(k.get("cards") == 7 and k.get("lands") == 2)
        yield f


def own_t(own, s, n):
    for t, (seat, k) in own.items():
        if seat == s and k == n: return t
    return 0


def tally(paths):
    """{deck: {"seats", "wins", "ev": {failure: count}, "n": Counter, "mana": {own turn: [usable]}, "ex": {failure: [..]}},
    "(all)": the same over every deck, "_have": {source: seat-games that had it}}."""
    agg = {}
    def bucket(k):
        return agg.setdefault(k, {"seats": 0, "wins": 0, "ev": Counter(), "n": Counter(), "mana": defaultdict(list),
                                  "ex": defaultdict(list), "have": Counter()})
    for f in seat_games(paths):
        for k in (f["deck"], "(all)"):
            a = bucket(k)
            a["seats"] += 1; a["wins"] += f["won"]
            for src in f["have"]: a["have"][src] += 1
            for name, xs in f["ev"].items():
                a["ev"][name] += len(xs)
                a["ex"][name].extend(xs)
            a["n"].update(f["n"])
            a["n"]["mull_seen"] += "keep_small" in f["n"]
            for t, m in f["mana"].items(): a["mana"][t].append(m)
    return agg


def _src_ok(a, src):
    return src is None or a["have"].get(src, 0) > 0 or (src in ("REMOVAL", "COUNTER", "WIPE") and a["have"].get("PLAN", 0) > 0)


def per100(a, name, src):
    if not _src_ok(a, src) or not a["seats"]: return None
    return 100 * a["ev"][name] / a["seats"]


def rate(a, name, src):
    n = a["n"]
    if name == "no_land":
        return 100 * n["no_land"] / n["early_turns"] if n["early_turns"] else None
    return 100 * n[name] / n["mull_seen"] if n["mull_seen"] else None


def _f(v, w=6, d=1):
    return f"{'-':>{w}s}" if v is None else f"{v:{w}.{d}f}"


def report(now, before=None, examples=3, min_seats=5):
    rows = []
    al = now.get("(all)")
    if not al:
        return ["no games in these runs"]
    decks = {k: v for k, v in now.items() if k != "(all)"}
    min_seats = min(min_seats, max(a["seats"] for a in decks.values()))
    b_al = (before or {}).get("(all)")
    head = f"pilot failures, every seat: {al['seats']} seat-games, {len(decks)} decks" + (
        f" (before: {b_al['seats']} seat-games)" if b_al else "")
    rows.append(head)
    rows.append(f"  {'per 100 seat-games':58s} {'now':>6s}" + (f" {'before':>6s}" if b_al else "") + "   most (per 100 of the deck's seats)")
    for name, label, src in FAILURES:
        v = per100(al, name, src)
        tops = sorted(((per100(a, name, src) or 0, k) for k, a in decks.items() if a["seats"] >= min_seats), reverse=True)
        tops = ", ".join(f"{k.split(',')[0]} {x:.0f}" for x, k in tops[:4] if x > 0)
        extra = ""
        if name == "cmd_never" and al["ev"][name]: extra = f" [{al['n']['cmd_never_5']} played 5+ own turns]"
        if name == "wipe_refused" and al["ev"][name]: extra = f" [{al['n']['wipe_hit']} would have hit the killer]"
        if name == "held_3" and al["n"]["held_all"]: extra = f" [{al['n']['held_all']} streaks in all, mana spent or not]"
        rows.append(f"  {label[:58]:58s} {_f(v)}" + (f" {_f(per100(b_al, name, src))}" if b_al else "") + f"   {tops}{extra}")
    rows.append(f"  {'rates (%)':58s}")
    for name, label, src in RATES:
        rows.append(f"  {label[:58]:58s} {_f(rate(al, name, src))}" + (f" {_f(rate(b_al, name, src))}" if b_al else ""))
    if examples:
        rows.append("")
        rows.append("examples (POD gGAME sSEAT tTABLE-TURN; replay: fishpond replay POD_DIR GAME)")
        for name, label, _ in FAILURES:
            xs = al["ex"].get(name)
            if xs: rows.append(f"  {label}: " + "; ".join(xs[:examples]))
    rows.append("")
    rows.append(f"per deck (per 100 of its seats): {'seats':>5s} {'won':>4s} | " + " ".join(f"{n[:7]:>7s}" for n, _, _ in FAILURES)
                + " | no land T1-4 | mana at main 1, own turns 1-6 (median)")
    for k, a in sorted(decks.items(), key=lambda kv: -kv[1]["wins"] / max(1, kv[1]["seats"])):
        mana = " ".join(f"{st.median(a['mana'][t]):.0f}" if a["mana"].get(t) else "-" for t in range(1, 7))
        rows.append(f"  {k[:30]:30s} {a['seats']:5d} {a['wins']:4d} | " + " ".join(_f(per100(a, n, s), 7, 0) for n, _, s in FAILURES)
                    + f" | {_f(rate(a, 'no_land', 'SEQ'), 11, 0)}% | {mana}")
    return rows


def to_json(agg):
    return {k: {"seats": a["seats"], "wins": a["wins"], "events": dict(a["ev"]), "counts": dict(a["n"]),
                "per100": {n: per100(a, n, s) for n, _, s in FAILURES},
                "rates": {n: rate(a, n, s) for n, _, s in RATES},
                "mana_median": {t: st.median(v) for t, v in sorted(a["mana"].items())},
                "examples": {n: xs[:10] for n, xs in a["ex"].items()}} for k, a in agg.items()}


def cmd(args):
    now = tally(args.runs)
    before = tally(args.vs) if args.vs else None
    if args.json:
        print(json.dumps({"now": to_json(now), "before": to_json(before) if before else None}, indent=1))
        return
    for row in report(now, before, examples=args.examples): print(row)
