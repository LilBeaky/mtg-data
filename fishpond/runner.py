"""Running pods on Forge and collecting parsed game records.

Engine 'cli' (Phase A): Forge's stock `sim` mode. Games run in chunks of CHUNK games per JVM; chunk c of a run with
--seed S uses Forge seed S*1000003+c, so results depend only on (seed, games), not on --jobs. Within a chunk Forge's
RNG runs on from game to game and the previous game's loser goes first, so a game can't be replayed alone, and a game
cut by the wall clock (-c) changes the rest of its chunk: keep the clock generous. When the hero dies the other seats
play on until someone wins or the clock runs out; the record stops at the hero's death either way.
"""
import concurrent.futures as cf
import json, os, random, subprocess, sys, time

from . import policy, decks as dk, forge, logparse as lp

CHUNK = 5

def chunk_seed(seed, c): return seed * 1000003 + c

# Full lookahead holds a few full game copies per search level (peak ~1.6 GB a game measured on the Niv pod with the
# AiCache patch), so it gets a bigger heap and fewer workers per GB than off/hybrid.
def default_jobs(full=False):
    return max(1, min(os.cpu_count() or 1, forge.memory_mb() // (3400 if full else 1700), 8))

def xmx_for(jobs, full=False):
    if os.environ.get("FISHPOND_XMX"): return int(os.environ["FISHPOND_XMX"])
    return max(3000 if full else 1200, min(4000 if full else 3000, forge.memory_mb() // max(1, jobs) - 400))

def uses_full(entries):
    return any("full" in e["line"].split("	")[11].split(",") for e in entries if len(e["line"].split("	")) > 11)

class Pods:
    """Opponent seats per chunk: fixed seats + gauntlet samples (seeded), decks loaded once per path."""
    def __init__(self, fixed, pool, fixed_pod=False, idx=None):
        self.fixed, self.pool, self.idx, self.cache = fixed, pool, idx, {}
        self.fixed_pod = None
        if pool and fixed_pod:
            self.fixed_pod = random.Random(0).sample(pool, min(3 - len(fixed), len(pool)))
    def deck(self, kind, path):
        key = (kind, path)
        if key not in self.cache:
            self.cache[key] = dk.dummy() if kind == "dummy" else dk.load(path, "opponent", idx=self.idx)
        return self.cache[key]
    def seats(self, seed):
        return [self.deck(k, p) for k, p in dk.pod_for(self.fixed, self.pool, random.Random(seed), self.fixed_pod)]
    def all_decks(self):
        out = [self.deck("deck", p) for k, p in self.fixed if k == "deck"]
        out += [self.deck("deck", p) for p in (self.pool or [])]
        return out

def seat_objs(hero, opps):
    seats = {1: lp.Seat(1, hero.tag, "hero", hero.log_names(), [hero.forge.get(c, c) for c in hero.commanders], hero.label)}
    for k, d in enumerate(opps, start=2):
        seats[k] = lp.Seat(k, d.tag, d.kind, d.log_names(), [d.forge.get(c, c) for c in d.commanders], d.label)
    return seats

def pod_info(opps, opp_ai):
    return [{"seat": k, "deck": d.label, "kind": d.kind, "bracket": d.bracket, "ai": opp_ai[k - 2],
             "path": os.path.relpath(d.path, dk.REPO) if d.path else None} for k, d in enumerate(opps, start=2)]

def run_cli(builds, pods, games, seed, clock, jobs, run_dir, hero_ai="Default", opp_ai=("Default",) * 3, quiet=False):
    """builds: [(label, hero Deck)]. Returns game records (one per game per build), in order."""
    forge.ensure(quiet=quiet)
    deck_dir = os.path.join(run_dir, "decks"); log_dir = os.path.join(run_dir, "logs")
    os.makedirs(deck_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    nchunks = (games + CHUNK - 1) // CHUNK
    files = {}
    def dck_file(d, stem):
        if id(d) not in files:
            fn = f"{stem}.dck"
            with open(os.path.join(deck_dir, fn), "w", encoding="utf-8") as fh: fh.write(d.dck(d.tag))
            files[id(d)] = fn
        return files[id(d)]
    plans = []
    for b, (label, hero) in enumerate(builds):
        hf = dck_file(hero, f"hero{b}_{hero.tag}")
        for c in range(nchunks):
            s = chunk_seed(seed, c)
            opps = pods.seats(s)
            of = [dck_file(d, f"opp{len(files)}_{d.tag}") for d in opps]
            n = min(CHUNK, games - c * CHUNK)
            ai = [hero_ai] + list(opp_ai) if (hero_ai, *opp_ai) != ("Default",) * 4 else None
            cmd = forge.sim_cmd(deck_dir, [hf] + of, n, s, clock, ai=ai, xmx=xmx_for(jobs))
            plans.append({"build": b, "label": label, "chunk": c, "seed": s, "n": n, "hero": hero, "opps": opps, "cmd": cmd,
                          "log": os.path.join(log_dir, f"b{b}_c{c:03d}.log")})
    t0 = time.time()
    def go(p):
        with open(p["log"], "w", encoding="utf-8") as fh:
            try:
                subprocess.run(p["cmd"], cwd=forge.run_home(quiet=True), stdout=fh, stderr=subprocess.STDOUT, timeout=p["n"] * (clock + 60) + 180)
            except subprocess.TimeoutExpired:
                fh.write("\nfishpond: JVM timed out\n")
        return p
    done = 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        for p in ex.map(go, plans):
            done += 1
            if not quiet:
                print(f"fishpond: chunk {done}/{len(plans)} done ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    records = []
    for p in plans:
        text = open(p["log"], encoding="utf-8", errors="replace").read()
        blocks = lp.split_games(text)
        if len(blocks) != p["n"]:
            print(f"fishpond: warning: chunk {p['chunk']} ({p['label']}) produced {len(blocks)} of {p['n']} games; see {p['log']}", file=sys.stderr)
        seats = seat_objs(p["hero"], p["opps"])
        for j, block in enumerate(blocks):
            r = lp.parse_game(block, seats)
            r.update({"v": 1, "engine": "cli", "forge": forge.FORGE_VERSION, "build": p["label"], "game": p["chunk"] * CHUNK + j,
                      "chunk": p["chunk"], "seed": p["seed"], "pos": j, "pod": pod_info(p["opps"], opp_ai), "hero_ai": hero_ai,
                      "log": os.path.relpath(p["log"], run_dir), "log_game": j})
            records.append(r)
    return records, time.time() - t0

# ---------------------------------------------------------------- engine 'harness' (Phase B)
HARNESS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness")
HARNESS_SRC = os.path.join(HARNESS_DIR, "ForgeRunner.java")
def _harness_sources(): return sorted(os.path.join(HARNESS_DIR, f) for f in os.listdir(HARNESS_DIR) if f.endswith(".java"))

def game_seed(seed, i): return seed * 1000003 + i

def harness_available():
    return bool(forge.java_major("javac")) or os.path.exists(os.path.join(_harness_dir(), "ForgeRunner.class"))

def _harness_dir():
    import hashlib
    h = hashlib.sha1(("".join(open(f, encoding="utf-8").read() for f in _harness_sources()) + forge.FORGE_VERSION).encode()).hexdigest()[:12]
    return os.path.join(forge.home(), "fishpond-harness", h)

def harness_classes(quiet=False):
    """Compile ForgeRunner.java against the cached jar once per (source, Forge version); returns the class dir."""
    d = _harness_dir()
    if os.path.exists(os.path.join(d, "ForgeRunner.class")): return d
    if not forge.java_major("javac") and not forge.install_jdk(quiet=quiet):
        sys.exit("fishpond: the harness needs javac (python3 -m fishpond setup --jdk), or use --engine cli")
    tmp = f"{d}.tmp{os.getpid()}"                  # compile privately, then rename: parallel runs may compile at once
    os.makedirs(tmp, exist_ok=True)
    r = subprocess.run(["javac", "-nowarn", "-encoding", "UTF-8", "-cp", forge.jar(), "-d", tmp, *_harness_sources()], capture_output=True, text=True)
    if r.returncode or not os.path.exists(os.path.join(tmp, "ForgeRunner.class")):
        sys.exit("fishpond: compiling the harness failed:\n" + "\n".join(l for l in (r.stderr + r.stdout).splitlines() if "Picked up" not in l)[-2000:])
    try: os.rename(tmp, d)
    except OSError: import shutil; shutil.rmtree(tmp, ignore_errors=True)   # another run got there first
    return d

SIM_MODES = ("off", "hybrid", "full")

def _dck_name(d, b=None):
    """Stable .dck file name for a seat across sessions of one run (resume needs the same names)."""
    import hashlib
    if b is not None: return f"hero{b}_{d.tag}.dck"
    if d.kind == "dummy": return "dummy.dck"
    return f"opp_{d.tag}_{hashlib.sha1(os.path.abspath(d.path).encode()).hexdigest()[:6]}.dck"

def plan_harness(builds, pods, first_game, games, seed, cap, timeout, run_dir, hero_ai="Default", opp_ai=("Default",) * 3,
                 hero_sim="hybrid", opp_sim="hybrid", keys=(), first_id=0):
    """Plan entries for games first_game..first_game+games-1 (every build per game, same seed and pod), writing their .dck files.
    Entries are JSON-safe (opponents as [kind, path]) so plan.json can rebuild them for --resume."""
    deck_dir = os.path.join(run_dir, "decks"); os.makedirs(deck_dir, exist_ok=True)
    def dck(d, b=None):
        fn = _dck_name(d, b)
        fp = os.path.join(deck_dir, fn)
        if not os.path.exists(fp):
            with open(fp, "w", encoding="utf-8") as fh: fh.write(d.dck(d.tag))
        if forge.pilot_on() and not os.path.exists(fp + ".policy.json"): policy.write_for(d, fp)   # the harness's tutor policy (fishpond/policy.py)
        return fn
    plan = []
    for i in range(first_game, first_game + games):
        s = game_seed(seed, i)
        opps = pods.seats(s)
        of = [dck(d) for d in opps]
        play_out = int(any(d.kind != "dummy" for d in opps))
        for b, (label, hero) in enumerate(builds):
            gid = first_id + len(plan)
            sims = [hero_sim] + [opp_sim if d.kind != "dummy" else "off" for d in opps]     # a dummy has nothing to decide
            kl = "|".join(hero.forge.get(k, k) for k in keys) or "-"
            line = "\t".join(map(str, [gid, s, cap, timeout, hero.identity or "C", play_out, dck(hero, b), *of,
                                        ",".join([hero_ai, *opp_ai]), ",".join(sims), kl]))
            plan.append({"id": gid, "build": b, "label": label, "game": i, "seed": s,
                         "opps": [[d.kind, os.path.abspath(d.path) if d.path else None] for d in opps], "line": line})
    return plan

def save_plan(run_dir, plan):
    with open(os.path.join(run_dir, "plan.json"), "w", encoding="utf-8") as fh: json.dump(plan, fh)

def load_plan(run_dir):
    p = os.path.join(run_dir, "plan.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None

def _pilot_seat_props(run_dir):
    """JVM properties for --pilot-seats you: only seat 1 gets the policy and the '-pilot-' patches, and the other seats treat
    fishpond's un-flagged cards as still flagged (patch 09 reads the list from a file in the run)."""
    seats = os.environ.get("FISHPOND_PILOT_SEATS", "all")
    if seats == "all" or not forge.pilot_on(): return []
    import re as _re
    names = []
    for f in forge.override_files():
        m = _re.search(r"^Name:(.+)$", open(f, encoding="utf-8").read(), _re.M)
        if m: names.append(m.group(1).strip())
    p = os.path.join(run_dir, "overridden.txt")
    with open(p, "w", encoding="utf-8") as fh: fh.write("\n".join(names) + "\n")
    return [f"-Dfishpond.pilotSeats={seats}", f"-Dfishpond.overriddenFile={os.path.abspath(p)}"]

def execute(entries, jobs, run_dir, session, quiet=False):
    """Run plan entries on `jobs` harness JVMs; each writes logs/worker_<session>_<j>.log, one game at a time (a cut-off
    session keeps every finished game). Returns wall seconds."""
    if not entries: return 0.0
    forge.ensure(quiet=quiet)
    classes = harness_classes(quiet)
    patched = forge.patched_classes(quiet=quiet)       # Forge fixes (fishpond/forge_patches), ahead of the jar
    deck_dir = os.path.join(run_dir, "decks"); log_dir = os.path.join(run_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    nb = len({e["build"] for e in entries})
    jobs = max(1, min(jobs, len(entries)))
    chunks = [[e for k, e in enumerate(entries) if (k // nb) % jobs == j] for j in range(jobs)]   # paired builds share a worker
    procs, t0 = [], time.time()
    for j, chunk in enumerate(chunks):
        pf = os.path.join(log_dir, f"plan_{session}_{j}.tsv")
        with open(pf, "w", encoding="utf-8") as fh: fh.write("\n".join(e["line"] for e in chunk) + "\n")
        lf = os.path.join(log_dir, f"worker_{session}_{j}.log")
        cmd = ["java", f"-Xmx{xmx_for(jobs, uses_full(entries))}m", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
               *([] if forge.pilot_on() else ["-Dfishpond.policy=off"]), *_pilot_seat_props(run_dir),
               "-cp", os.pathsep.join(([patched] if patched else []) + [forge.jar(), classes]), "ForgeRunner", os.path.join(deck_dir, ""), pf]
        fh = open(lf, "w", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, cwd=forge.run_home(quiet=True), stdout=fh, stderr=subprocess.STDOUT), fh, lf))
    last = -1
    while any(p.poll() is None for p, *_ in procs):
        time.sleep(3)
        done = sum(open(lf, encoding="utf-8", errors="replace").read().count("\nGame Result:") for _, _, lf in procs)
        if not quiet and done != last:
            print(f"fishpond: {done}/{len(entries)} games this session ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True); last = done
    for p, fh, lf in procs: fh.close()
    return time.time() - t0

def collect(run_dir, plan, builds, pods, hero_ai="Default", opp_ai=("Default",) * 3):
    """Every finished game of the run, from all worker logs (any session), matched to plan entries by game id.
    Returns (records sorted by build and game, plan entries with no finished game)."""
    import glob
    by_id = {e["id"]: e for e in plan}
    heroes = {label: d for label, d in builds}
    done = {}
    for lf in sorted(glob.glob(os.path.join(run_dir, "logs", "worker_*.log"))):
        for block in lp.split_games(open(lf, encoding="utf-8", errors="replace").read()):
            snaps, end = lp.harness_lines(block)
            if not end or end.get("id") not in by_id or end["id"] in done: continue
            e = by_id[end["id"]]
            opps = [pods.deck(k, p) for k, p in e["opps"]]
            r = lp.parse_game([l for l in block if not l.startswith("#FP")], seat_objs(heroes[e["label"]], opps))
            r.update({"v": 1, "engine": "harness", "forge": forge.FORGE_VERSION, "build": e["label"], "game": e["game"],
                      "seed": e["seed"], "pod": pod_info(opps, opp_ai), "hero_ai": hero_ai, "snaps": snaps, "stop": end.get("stop"),
                      "end": end, "log": os.path.relpath(lf, run_dir), "log_id": end["id"], "tutors": end.get("tutors", []), "policy_log": end.get("policy_log", []),
                      "sim": end.get("sim")})
            if end.get("stop") not in ("natural", "hero_lost") and r["result"] != "loss": r["result"], r["route"] = "draw", None
            r["stopped"] = end.get("stop") in ("timeout",)
            done[end["id"]] = r
    labels = [b for b, _ in builds]
    records = sorted(done.values(), key=lambda r: (labels.index(r["build"]), r["game"]))
    missing = [e for e in plan if e["id"] not in done]
    return records, missing

def run_harness(builds, pods, games, seed, cap, timeout, jobs, run_dir, hero_ai="Default", opp_ai=("Default",) * 3, quiet=False,
                hero_sim="hybrid", opp_sim="hybrid", keys=()):
    """Phase B, one session: plan (saved to plan.json first, so a cut-off run can be resumed), execute, collect.
    Every game is reseeded (game i uses seed*1000003+i: any game replays alone and --jobs never changes results), stopped
    at the end of your turn `cap` or when you've lost (real opponents left: played out for the pod result), with
    snapshots at your main phase and cleanup."""
    plan = plan_harness(builds, pods, 0, games, seed, cap, timeout, run_dir, hero_ai, opp_ai, hero_sim, opp_sim, keys)
    save_plan(run_dir, plan)
    wall = execute(plan, jobs, run_dir, "s1", quiet)
    records, missing = collect(run_dir, plan, builds, pods, hero_ai, opp_ai)
    for e in missing: print(f"fishpond: warning: game {e['game']} ({e['label']}) produced no result", file=sys.stderr)
    return records, wall

def save(run_dir, meta, records):
    with open(os.path.join(run_dir, "games.jsonl"), "w", encoding="utf-8") as fh:
        for r in records: fh.write(json.dumps(r) + "\n")
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fh: json.dump(meta, fh, indent=1)

def load_run(run_dir):
    meta = json.load(open(os.path.join(run_dir, "meta.json"), encoding="utf-8"))
    gp = os.path.join(run_dir, "games.jsonl")
    records = [json.loads(l) for l in open(gp, encoding="utf-8")] if os.path.exists(gp) else []
    return meta, records
