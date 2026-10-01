"""Running pods on Forge and collecting parsed game records.

Engine 'cli' (Phase A): Forge's stock `sim` mode. Games run in chunks of CHUNK games per JVM; chunk c of a run with
--seed S uses Forge seed S*1000003+c, so results depend only on (seed, games), not on --jobs. Within a chunk Forge's
RNG runs on from game to game and the previous game's loser goes first, so a game can't be replayed alone, and a game
cut by the wall clock (-c) changes the rest of its chunk: keep the clock generous. When the hero dies the other seats
play on until someone wins or the clock runs out; the record stops at the hero's death either way.
"""
import concurrent.futures as cf
import json, os, random, subprocess, sys, time

from . import decks as dk, forge, logparse as lp

CHUNK = 5

def chunk_seed(seed, c): return seed * 1000003 + c

def default_jobs():
    return max(1, min(os.cpu_count() or 1, forge.memory_mb() // 1700, 8))

def xmx_for(jobs):
    return max(1200, min(3000, forge.memory_mb() // max(1, jobs) - 400))

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
                subprocess.run(p["cmd"], cwd=forge.home(), stdout=fh, stderr=subprocess.STDOUT, timeout=p["n"] * (clock + 60) + 180)
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
HARNESS_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness", "ForgeRunner.java")

def game_seed(seed, i): return seed * 1000003 + i

def harness_available():
    return bool(forge.java_major("javac")) or os.path.exists(os.path.join(_harness_dir(), "ForgeRunner.class"))

def _harness_dir():
    import hashlib
    h = hashlib.sha1((open(HARNESS_SRC, encoding="utf-8").read() + forge.FORGE_VERSION).encode()).hexdigest()[:12]
    return os.path.join(forge.home(), "fishpond-harness", h)

def harness_classes(quiet=False):
    """Compile ForgeRunner.java against the cached jar once per (source, Forge version); returns the class dir."""
    d = _harness_dir()
    if os.path.exists(os.path.join(d, "ForgeRunner.class")): return d
    if not forge.java_major("javac") and not forge.install_jdk(quiet=quiet):
        sys.exit("fishpond: the harness needs javac (python3 -m fishpond setup --jdk), or use --engine cli")
    os.makedirs(d, exist_ok=True)
    r = subprocess.run(["javac", "-nowarn", "-encoding", "UTF-8", "-cp", forge.jar(), "-d", d, HARNESS_SRC], capture_output=True, text=True)
    if r.returncode or not os.path.exists(os.path.join(d, "ForgeRunner.class")):
        sys.exit("fishpond: compiling the harness failed:\n" + "\n".join(l for l in (r.stderr + r.stdout).splitlines() if "Picked up" not in l)[-2000:])
    return d

def run_harness(builds, pods, games, seed, cap, timeout, jobs, run_dir, hero_ai="Default", opp_ai=("Default",) * 3, quiet=False):
    """Phase B: every game reseeded (game i uses seed*1000003+i, so any game replays alone and --jobs never changes
    results), stopped at the end of your turn `cap` or when you've lost (real opponents left: played out to get the pod
    result, up to 4*cap more turns), with snapshots at your main phase and cleanup."""
    forge.ensure(quiet=quiet)
    classes = harness_classes(quiet)
    deck_dir = os.path.join(run_dir, "decks"); log_dir = os.path.join(run_dir, "logs")
    os.makedirs(deck_dir, exist_ok=True); os.makedirs(log_dir, exist_ok=True)
    files = {}
    def dck_file(d, stem):
        if id(d) not in files:
            fn = f"{stem}.dck"
            with open(os.path.join(deck_dir, fn), "w", encoding="utf-8") as fh: fh.write(d.dck(d.tag))
            files[id(d)] = fn
        return files[id(d)]
    plan = []
    for i in range(games):                          # builds interleaved per game: paired games land in the same worker
        s = game_seed(seed, i)
        opps = pods.seats(s)
        of = [dck_file(d, f"opp{len(files)}_{d.tag}") for d in opps]
        play_out = int(any(d.kind != "dummy" for d in opps))
        for b, (label, hero) in enumerate(builds):
            hf = dck_file(hero, f"hero{b}_{hero.tag}")
            gid = len(plan)
            line = "\t".join(map(str, [gid, s, cap, timeout, hero.identity or "C", play_out, hf, *of, ",".join([hero_ai, *opp_ai])]))
            plan.append({"id": gid, "build": b, "label": label, "game": i, "seed": s, "hero": hero, "opps": opps, "line": line})
    jobs = max(1, min(jobs, len(plan)))
    chunks = [plan[j::jobs] for j in range(jobs)] if len(builds) == 1 else \
        [[p for k, p in enumerate(plan) if (k // len(builds)) % jobs == j] for j in range(jobs)]
    procs = []
    t0 = time.time()
    for j, chunk in enumerate(chunks):
        pf = os.path.join(log_dir, f"plan_{j}.tsv")
        with open(pf, "w", encoding="utf-8") as fh: fh.write("\n".join(p["line"] for p in chunk) + "\n")
        lf = os.path.join(log_dir, f"worker_{j}.log")
        cmd = ["java", f"-Xmx{xmx_for(jobs)}m", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
               "-cp", os.pathsep.join([forge.jar(), classes]), "ForgeRunner", os.path.join(deck_dir, ""), pf]
        fh = open(lf, "w", encoding="utf-8")
        procs.append((subprocess.Popen(cmd, cwd=forge.home(), stdout=fh, stderr=subprocess.STDOUT), fh, lf, chunk))
    last = -1
    while any(p.poll() is None for p, *_ in procs):
        time.sleep(3)
        done = sum(open(lf, encoding="utf-8", errors="replace").read().count("\nGame Result:") for _, _, lf, _ in procs)
        if not quiet and done != last:
            print(f"fishpond: {done}/{len(plan)} games ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True); last = done
    for p, fh, lf, chunk in procs: fh.close()
    by_id = {p["id"]: p for p in plan}
    records = []
    for _, _, lf, chunk in procs:
        for block in lp.split_games(open(lf, encoding="utf-8", errors="replace").read()):
            snaps, end = lp.harness_lines(block)
            if not end or end.get("id") not in by_id:
                print(f"fishpond: warning: a game in {lf} has no #FP-END line; skipped", file=sys.stderr); continue
            p = by_id.pop(end["id"])
            r = lp.parse_game([l for l in block if not l.startswith("#FP")], seat_objs(p["hero"], p["opps"]))
            r.update({"v": 1, "engine": "harness", "forge": forge.FORGE_VERSION, "build": p["label"], "game": p["game"],
                      "seed": p["seed"], "pod": pod_info(p["opps"], opp_ai), "hero_ai": hero_ai, "snaps": snaps, "stop": end.get("stop"),
                      "end": end, "log": os.path.relpath(lf, run_dir), "log_id": end["id"]})
            if end.get("stop") in ("cap", "timeout") and r["result"] != "loss": r["result"], r["route"] = "draw", None
            r["stopped"] = end.get("stop") in ("timeout",)
            records.append(r)
    for p in by_id.values():
        print(f"fishpond: warning: game {p['game']} ({p['label']}) produced no result", file=sys.stderr)
    records.sort(key=lambda r: ([b for b, _ in builds].index(r["build"]), r["game"]))
    return records, time.time() - t0

def save(run_dir, meta, records):
    with open(os.path.join(run_dir, "games.jsonl"), "w", encoding="utf-8") as fh:
        for r in records: fh.write(json.dumps(r) + "\n")
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fh: json.dump(meta, fh, indent=1)

def load_run(run_dir):
    meta = json.load(open(os.path.join(run_dir, "meta.json"), encoding="utf-8"))
    records = [json.loads(l) for l in open(os.path.join(run_dir, "games.jsonl"), encoding="utf-8")]
    return meta, records
