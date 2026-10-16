"""A pod study: many pods, run in parallel lanes, resumable, with one per-deck report.

  python -m fishpond study PODS --out DIR [--games 5] [--seed 1] [--lanes 2] [--jobs 5] [--sim hybrid] [--max-minutes M]
  python -m fishpond study --report DIR

PODS lists one pod a line, 'ID|HERO|OPP1|OPP2|OPP3' (deck names in decks/ without .txt, or paths; '#' starts a comment),
as data/fishpond/varied_20261007/pods.txt. Pod k (1-based, in file order) plays --games games on seed SEED + 100*k into
DIR/<ID>_<HERO>, so a study is the same games however it is split. Lanes run pods side by side (each pod uses --jobs JVMs;
two lanes of 5 suit this machine). Running the same command again skips finished pods and resumes cut-off ones (run
--resume). --max-minutes stops starting new pods after that long (finished pods stay; a running pod is completed), for
sessions with a time limit: rerun to continue. The report follows the last pod; --report prints it alone.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict

from . import decks as dk


def read_pods(path):
    pods = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line: continue
        f = [x.strip() for x in line.split("|")]
        if len(f) < 2: sys.exit(f"fishpond: bad pod line {line!r} (ID|HERO|OPP1|OPP2|OPP3)")
        pods.append((f[0], f[1], f[2:5]))
    return pods


def deck_path(name):
    if os.path.exists(name): return name
    p = os.path.join(dk.REPO, "decks", name if name.endswith(".txt") else name + ".txt")
    if not os.path.exists(p): sys.exit(f"fishpond: no deck {name!r} (looked for {p})")
    return p


def pod_dir(out, pid, hero):
    return os.path.join(out, f"{pid}_{os.path.splitext(os.path.basename(hero))[0]}")


def pod_state(d):
    """'done', 'partial' (a cut-off run to resume) or 'new'."""
    m = os.path.join(d, "meta.json")
    if not os.path.exists(m): return "new"
    try:
        return "done" if json.load(open(m, encoding="utf-8")).get("complete") else "partial"
    except ValueError:
        return "partial"


def run_study(args):
    pods = read_pods(args.pods)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    todo = queue.Queue()
    for k, (pid, hero, opps) in enumerate(pods, 1):
        d = pod_dir(out, pid, hero)
        st = pod_state(d)
        if st == "done": continue
        if st == "new":
            cmd = [sys.executable, "-m", "fishpond", "run", deck_path(hero), *sum((["--opp", deck_path(o)] for o in opps), []),
                   "--trials", str(args.games), "--seed", str(args.seed + 100 * k), "--sim", args.sim, "--opp-sim", args.sim,
                   "--jobs", str(args.jobs), "--quiet", "--out", d]
        else:
            cmd = [sys.executable, "-m", "fishpond", "run", "--resume", d, "--jobs", str(args.jobs)]   # same JVMs (and heap) as a start
        todo.put((pid, d, cmd, st))
    n = todo.qsize()
    print(f"fishpond study: {len(pods)} pods, {len(pods) - n} done, {n} to run on {args.lanes} lane(s) x {args.jobs} JVMs -> {out}")
    print(f"  to continue later (or locally): python -m fishpond study {args.pods} --out {out} --games {args.games} --seed {args.seed} "
          f"--lanes {args.lanes} --jobs {args.jobs} --sim {args.sim}")
    t0 = time.time()
    lock = threading.Lock()

    def lane():
        while True:
            if args.max_minutes and time.time() - t0 > args.max_minutes * 60: return
            try: pid, d, cmd, st = todo.get_nowait()
            except queue.Empty: return
            with lock: print(f"  {time.strftime('%H:%M:%S')} {pid} {'resume' if st == 'partial' else 'start'}", flush=True)
            os.makedirs(d, exist_ok=True)
            with open(d + ".log", "a", encoding="utf-8") as fh:
                rc = subprocess.run(cmd, cwd=dk.REPO, stdout=fh, stderr=subprocess.STDOUT).returncode
            with lock: print(f"  {time.strftime('%H:%M:%S')} {pid} {'done' if rc == 0 else f'exit {rc} (see {d}.log)'}", flush=True)

    threads = [threading.Thread(target=lane) for _ in range(max(1, args.lanes))]
    for t in threads: t.start()
    for t in threads: t.join()
    left = sum(1 for k, (pid, hero, _) in enumerate(pods, 1) if pod_state(pod_dir(out, pid, hero)) != "done")
    if left:
        print(f"fishpond study: {left} pod(s) not finished; rerun the line above to continue")
    report(out)


def load(out):
    recs = []
    for name in sorted(os.listdir(out)):
        d = os.path.join(out, name)
        g = os.path.join(d, "games.jsonl")
        if not os.path.isfile(g): continue
        meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
        for l in open(g, encoding="utf-8"):
            if l.strip():
                r = json.loads(l); r["_hero"] = meta.get("commander") or name; r["_pod"] = name; recs.append(r)
    return recs


def seats_of(r):
    s = {1: r["_hero"]}
    s.update({p["seat"]: p["deck"] for p in r.get("pod") or [] if p.get("kind") != "dummy"})
    return s


def report(out):
    from . import held
    recs = load(out)
    if not recs: print("fishpond study: no finished games yet"); return
    pods = sorted({r["_pod"] for r in recs})
    ends = [r.get("end") or {} for r in recs]
    stops = Counter(r.get("stop") for r in recs if r.get("stop") != "natural")
    print(f"\n## study {os.path.basename(out)}: {len(recs)} games in {len(pods)} pods "
          f"({sum(r.get('ms', 0) for r in recs) / 3.6e6:.1f} h of game time)")
    print(f"run validity: ended naturally {len(recs) - sum(stops.values())}" + "".join(f", {k} {v}" for k, v in stops.items())
          + f"; AI timeouts {sum(r.get('ai_timeouts', 0) for r in recs)} ({sum(r.get('ai_hurried', 0) for r in recs)} finished in hurry mode)"
          + f"; per-decision lookahead fallbacks "
          f"{sum(e.get('sim_decision_fallbacks', 0) for e in ends)}; games replayed without lookahead "
          f"{sum(1 for e in ends if e.get('sim_fallback'))}; games with lookahead paused (prepared cards or a 150+ permanent board) {sum(1 for e in ends if e.get('sim_pauses'))}")
    # per deck: seat-games, single-survivor wins over decided games, kills, deaths, how it won
    a = defaultdict(lambda: {"games": 0, "decided": 0, "wins": 0, "kills": 0, "deaths": 0, "how": Counter()})
    for r in recs:
        seats = seats_of(r)
        decided = bool(r.get("winner")) and r.get("stop") == "natural"
        for seat, deck in seats.items():
            x = a[deck]; x["games"] += 1; x["decided"] += decided
            x["kills"] += sum(1 for dth in r.get("deaths") or [] if dth.get("by") == seat and dth.get("seat") != seat)
            x["deaths"] += sum(1 for dth in r.get("deaths") or [] if dth.get("seat") == seat)
        if r.get("result") == "loss" and not any(dth.get("seat") == 1 for dth in r.get("deaths") or []):   # the hero's death is in r["loss"]
            a[seats[1]]["deaths"] += 1
            by = (r.get("loss") or {}).get("by")
            if by and by != 1 and by in seats: a[seats[by]]["kills"] += 1
        if decided:
            w = seats.get(r["winner"], "?"); a[w]["wins"] += 1
            a[w]["how"][(r.get("route") if r["winner"] == 1 else None) or _route(r, r["winner"])] += 1
    print("\nper deck (single surviving winner; wins over decided games; kills and deaths count every seat):")
    for deck, x in sorted(a.items(), key=lambda kv: -kv[1]["wins"] / max(1, kv[1]["decided"])):
        how = ", ".join(f"{k} {v}" for k, v in x["how"].most_common(3))
        print(f"  {deck[:38]:38} won {x['wins']}/{x['decided']} decided ({x['games'] - x['decided']} undecided of {x['games']}) | "
              f"kills {x['kills']}, deaths {x['deaths']}" + (f" | {how}" if how else ""))
    agg = {}
    for p in pods:
        held.tally([r for r in recs if r["_pod"] == p], next(r["_hero"] for r in recs if r["_pod"] == p), agg)
    if agg:
        print(f"\nheld while castable ({held.MIN_TURNS}+ turns running; per seat-game):")
        for s in held.lines(agg): print("  " + s)


def _route(r, seat):
    """How a non-hero seat won, from its game outcome line (alt win card, else the last opponent's loss reason)."""
    pl = ((r.get("end") or {}).get("players") or {}).get(str(seat)) or {}
    if pl.get("alt"): return pl["alt"]
    losses = Counter(p.get("loss") for k, p in ((r.get("end") or {}).get("players") or {}).items() if k != str(seat) and p.get("loss"))
    return {"LifeReachedZero": "life", "Poisoned": "poison", "CommanderDamage": "commander damage",
            "Milled": "decked"}.get(losses.most_common(1)[0][0], losses.most_common(1)[0][0]) if losses else "?"
