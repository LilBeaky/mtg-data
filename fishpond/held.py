"""Dead-card meter: cards a seat could cast but held for several turns running.

The harness (ForgeRunner.Watcher) checks every seat's hand at the start of its first main phase: a nonland card it could
cast right then (mana, timing and legal targets; that turn's land drop not counted) that is still in hand at its cleanup
was held that turn. A run of consecutive held turns of one card is a streak (#FP-HELD, streaks of 2+ printed). The meter
counts streaks of 3+ turns: for most cards, a pilot that sat on a castable card that long missed a play. Instants and
flash cards are shown apart, since holding up an answer can be right.

  python -m fishpond held RUN_DIR [RUN_DIR...]    per deck across runs (a folder of runs is searched for games.jsonl)
"""
import glob
import json
import os
from collections import Counter, defaultdict

MIN_TURNS = 3


def seat_decks(r, hero_name):
    d = {1: hero_name}
    for p in r.get("pod") or []:
        if p.get("kind") != "dummy": d[p["seat"]] = p["deck"]
    return d


def tally(records, hero_name, out=None, min_turns=MIN_TURNS):
    """Add one run's games to out: {deck: {"games", "games_dead", "streaks", "instant", "cards": Counter, "inst_cards": Counter}}.
    Games without the meter (runs before 2026-10-12) are skipped."""
    out = out if out is not None else {}
    for r in records:
        if r.get("held") is None: continue
        decks = seat_decks(r, hero_name)
        by_seat = defaultdict(list)
        for h in r["held"]:
            if h["turns"] >= min_turns: by_seat[int(h["seat"])].append(h)
        for seat, deck in decks.items():
            a = out.setdefault(deck, {"games": 0, "games_dead": 0, "streaks": 0, "instant": 0, "cards": Counter(), "inst_cards": Counter()})
            a["games"] += 1
            hs = by_seat.get(seat, [])
            if any(not h["instant"] for h in hs): a["games_dead"] += 1
            for h in hs:
                if h["instant"]: a["instant"] += 1; a["inst_cards"][h["card"]] += 1
                else: a["streaks"] += 1; a["cards"][h["card"]] += 1
    return out


def lines(agg, top=6):
    rows = []
    for deck, a in sorted(agg.items(), key=lambda kv: -(kv[1]["streaks"] / max(1, kv[1]["games"]))):
        n = a["games"]
        s = (f"{deck}: {a['streaks'] / n:.2f} per game, in {100 * a['games_dead'] / n:.0f}% of {n} games"
             + (": " + ", ".join(f"{c} {k}" for c, k in a["cards"].most_common(top)) if a["cards"] else ""))
        if a["instant"]:
            s += f" | instants/flash held {a['instant']}: " + ", ".join(f"{c} {k}" for c, k in a["inst_cards"].most_common(3))
        rows.append(s)
    return rows


def print_section(records, hero_name):
    agg = tally(records, hero_name)
    if not agg: return
    print(f"\n## held while castable, every seat ({MIN_TURNS}+ turns running; castable at the start of main 1 and still in hand "
          f"at cleanup; per game = such streaks per seat-game; card counts = streaks)")
    for s in lines(agg): print("  " + s)


def runs_under(paths):
    for p in paths:
        if os.path.exists(os.path.join(p, "games.jsonl")): yield p
        else:
            for g in sorted(glob.glob(os.path.join(p, "**", "games.jsonl"), recursive=True)): yield os.path.dirname(g)


def cmd(paths):
    agg, n_runs, skipped = {}, 0, 0
    for run in runs_under(paths):
        meta = json.load(open(os.path.join(run, "meta.json"), encoding="utf-8"))
        recs = [json.loads(l) for l in open(os.path.join(run, "games.jsonl"), encoding="utf-8") if l.strip()]
        skipped += sum(1 for r in recs if r.get("held") is None)
        tally(recs, meta.get("commander") or os.path.basename(meta.get("deck", "you")), agg)
        n_runs += 1
    print(f"held while castable ({MIN_TURNS}+ turns running), {n_runs} run(s)" + (f"; {skipped} games without the meter skipped" if skipped else ""))
    for s in lines(agg, top=10): print("  " + s)
