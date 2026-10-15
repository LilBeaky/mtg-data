"""Win-line audit: how often each deck's win lines were there to play, and how often the AI played them.

The lines live in fishpond/win_lines.txt (per commander: closers, engines, fair plans). The harness (LineTracker.java) checks
every seat's lines at the start of its first main phase; a line whose pieces are there is "available" that turn, and "did"
when the seat makes the line's play before its next turn. Each game prints one #FP-LINE per seat and line.

  python -m fishpond lines RUN_DIR [RUN_DIR...]    per deck and line across runs (a folder of runs is searched)

Then reach, per deck: how often the seat got to any of its lines at all (not counting the trivial "Yusri attacks") before
the game ended for it, when its commander was first out at a main phase, and how many
turns it had. Most losses come before a deck's lines are ever there; the per-line table can't show that. Runs from
2026-10-15 on carry the commander and turn counts; older runs show "-" there.

Columns: games the line was available in / games the seat played it / turns available / turns played (the rate is per turn),
the seat's win rate in games the line was available and in games it was played, and up to 5 games where it was available
and never played (POD gGAME, for `fishpond show` or a log review).
"""
import json
import os
from collections import defaultdict

from .held import runs_under


def tally(paths):
    """{(commander, kind, line): stats} over every game with the audit (runs before 2026-10-14 have none)."""
    out = {}
    for run in runs_under(paths):
        tag = os.path.basename(os.path.normpath(run))[:3]
        for l in open(os.path.join(run, "games.jsonl"), encoding="utf-8"):
            if not l.strip(): continue
            r = json.loads(l)
            for x in r.get("lines") or []:
                if x["kind"] == "reach": continue
                k = (x["commander"], x["kind"], x["line"])
                a = out.setdefault(k, {"games": 0, "avail_games": 0, "did_games": 0, "avail_turns": 0, "did_turns": 0,
                                       "won_avail": 0, "won_did": 0, "misses": []})
                a["games"] += 1
                if not x["avail"]: continue
                a["avail_games"] += 1; a["avail_turns"] += len(x["avail"]); a["did_turns"] += len(x["did"])
                a["won_avail"] += x["won"]
                if x["did"]:
                    a["did_games"] += 1; a["won_did"] += x["won"]
                elif len(a["misses"]) < 5:
                    a["misses"].append(f"{tag} g{r['game']} s{x['seat']}")
    return out


def reach(paths):
    """{commander: counts} per seat-game: lines reached before the seat's game ended, commander first out, turns."""
    out = {}
    for run in runs_under(paths):
        for l in open(os.path.join(run, "games.jsonl"), encoding="utf-8"):
            if not l.strip(): continue
            r = json.loads(l)
            seats = defaultdict(list)
            for x in r.get("lines") or []:
                seats[x["seat"]].append(x)
            for seat, xs in seats.items():
                info = next((x for x in xs if x["kind"] == "reach"), None)
                ls = [x for x in xs if x["kind"] != "reach"]
                cmd = (info or ls[0] if ls else info)["commander"] if (info or ls) else "?"
                a = out.setdefault(cmd, {"games": 0, "won": 0, "reached": 0, "reached_won": 0, "first": [], "cmd_first": [],
                                         "cmd_never": 0, "turns": [], "has_reach": 0})
                a["games"] += 1
                won = any(x["won"] for x in xs)
                a["won"] += won
                hard = [x for x in ls if not x["line"].startswith("Yusri attacks (free")]   # every line but the trivial one
                first = min((t for x in hard for t in x["avail"]), default=None)
                if first is not None:
                    a["reached"] += 1; a["reached_won"] += won; a["first"].append(first)
                if info is not None:
                    a["has_reach"] += 1
                    a["turns"].append(info["turns"])
                    if info["cmd_first"] < 0: a["cmd_never"] += 1
                    else: a["cmd_first"].append(info["cmd_first"])
    return out


def _med(v): return f"{sorted(v)[len(v) // 2]:4d}" if v else "   -"


def reach_rows(stats):
    rows = [f"{'reach':38s} games  won | line reached (won)  first turn | commander out: median turn, never | turns played (median)"]
    for cmd, a in sorted(stats.items(), key=lambda kv: kv[1]["reached"] / kv[1]["games"]):
        never = f"{pct(a['cmd_never'], a['has_reach'])}" if a["has_reach"] else "  - "
        rows.append(f"  {cmd[:36]:36s} {a['games']:5d} {a['won']:4d} | {a['reached']:4d} {pct(a['reached'], a['games'])} ({a['reached_won']:3d})"
                    f"  {_med(a['first'])}     | {_med(a['cmd_first'])}, {never}           | {_med(a['turns'])}")
    return rows


def pct(a, b): return f"{100 * a / b:3.0f}%" if b else "  - "


def lines(stats):
    rows, by_cmd = [], defaultdict(list)
    for k, a in stats.items(): by_cmd[k[0]].append((k, a))
    order = {"closer": 0, "engine": 1, "plan": 2}
    for cmd in sorted(by_cmd):
        g = max(a["games"] for _, a in by_cmd[cmd])
        rows.append(f"{cmd} ({g} seat-games)")
        for (c, kind, line), a in sorted(by_cmd[cmd], key=lambda kv: (order.get(kv[0][1], 9), kv[0][2])):
            rows.append(f"  {kind:6s} {line[:46]:46s} available {a['avail_games']:3d} g, played {a['did_games']:3d} g | "
                        f"turns {a['did_turns']:3d}/{a['avail_turns']:3d} {pct(a['did_turns'], a['avail_turns'])} | "
                        f"won {pct(a['won_avail'], a['avail_games'])} when available, {pct(a['won_did'], a['did_games'])} when played"
                        + (f" | missed: {', '.join(a['misses'])}" if a["misses"] and a["did_games"] < a["avail_games"] else ""))
    return rows


def cmd(paths):
    s = tally(paths)
    if not s:
        print("no win-line data in these runs (the audit starts with runs from 2026-10-14)")
        return
    print("win lines (fishpond/win_lines.txt): available = pieces there at the start of the seat's main phase; "
          "played = the line's play before its next turn")
    for r in lines(s): print(r)
    print()
    for r in reach_rows(reach(paths)): print(r)
