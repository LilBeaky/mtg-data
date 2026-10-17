"""Sequencing report (docs/SEQUENCING.md): per deck, against the user's yardstick (fishpond/yardstick.json).

    python -m fishpond sequencing RUN [RUN...]

From the game records: win rate, the winner's own turn at the win, the commander's first cast (own turn) against its target;
from the per-turn sequencing records (#FP-SEQ, runs from 2026-10-17 on): in the seat's own turns 1-6, how often a land was
missed, how often it ended the turn with 2+ mana unused while a castable spell sat in hand, and the mana it left on average."""
import glob, json, os, statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EARLY = 6


def records(runs):
    for run in runs:
        base = run if os.path.isdir(run) else os.path.join("data", "fishpond", run)
        for f in sorted(glob.glob(os.path.join(base, "**", "games.jsonl"), recursive=True)):
            for line in open(f, encoding="utf-8"):
                yield json.loads(line)


def summarize(runs):
    deck = defaultdict(lambda: {"seats": 0, "wins": 0, "win_turns": [], "cmd": [], "early": 0, "no_land": 0, "idle": 0, "left": []})
    for r in records(runs):
        reach = {str(x["seat"]): x for x in r.get("lines", []) if x.get("kind") == "reach"}
        seq = defaultdict(list)
        for s in r.get("seq") or []:
            seq[s["seat"]].append(s)
        for seat, x in reach.items():
            d = deck[x["commander"]]
            d["seats"] += 1
            if x.get("cmd_first") is not None:
                d["cmd"].append(x["cmd_first"])
            if str(r.get("winner")) == seat:
                d["wins"] += 1
                if x.get("turns"):
                    d["win_turns"].append(x["turns"])
            for s in seq.get(seat, []):
                if s["turn"] > EARLY:
                    continue
                d["early"] += 1
                d["no_land"] += not s["land"]
                d["idle"] += s["left"] >= 2 and bool(s["castable_left"])
                d["left"].append(s["left"])
    return deck


def report(runs):
    yard = {k: v for k, v in json.load(open(os.path.join(HERE, "yardstick.json"), encoding="utf-8")).items() if not k.startswith("_")}
    deck = summarize(runs)
    order = sorted(deck, key=lambda k: (yard.get(k, {}).get("rank", 99), -deck[k]["wins"] / max(1, deck[k]["seats"])))
    print(f"{'deck':28s} {'rank':>4s} {'win rate':>12s} {'win turn':>13s} {'target':>6s} {'commander turn':>15s} {'target':>6s} "
          f"{'turns 1-' + str(EARLY) + ': no land / idle 2+ / mana left':>40s}")
    for k in order:
        d, y = deck[k], yard.get(k, {})
        wt = f"{st.median(d['win_turns']):.0f} ({min(d['win_turns'])})" if d["win_turns"] else "-"
        ct = d["cmd"]
        cts = f"{st.median(ct):.0f}" + (f", {sum(1 for t in ct if t <= y['cmd_turn'])}/{d['seats']} on time" if y.get("cmd_turn") else "") if ct else "-"
        early = (f"{100 * d['no_land'] / d['early']:.0f}% / {100 * d['idle'] / d['early']:.0f}% / {st.mean(d['left']):.1f}"
                 if d["early"] else "(no sequencing records)")
        print(f"{k[:28]:28s} {str(y.get('rank', '')):>4s} {d['wins']:4d}/{d['seats']:<4d}{100 * d['wins'] / max(1, d['seats']):3.0f}% "
              f"{wt:>13s} {str(y.get('win_turn', '')):>6s} {cts:>15s} {str(y.get('cmd_turn', '')):>6s} {early:>40s}")


def cmd(runs):
    report(runs)
