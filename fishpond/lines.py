"""Win-line audit: how often each deck's win lines were there to play, and how often the AI played them.

The lines live in fishpond/win_lines.txt (per commander: closers, engines, fair plans). The harness (LineTracker.java) checks
every seat's lines at the start of its first main phase; a line whose pieces are there is "available" that turn, and "did"
when the seat makes the line's play before its next turn. Each game prints one #FP-LINE per seat and line.

  python -m fishpond lines RUN_DIR [RUN_DIR...]    per deck and line across runs (a folder of runs is searched)

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
