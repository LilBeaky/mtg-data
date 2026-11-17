"""Running pods on Forge and collecting parsed game records.

Engine 'cli' (Phase A): Forge's stock `sim` mode. Games run in chunks of CHUNK games per JVM; chunk c of a run with
--seed S uses Forge seed S*1000003+c, so results depend only on (seed, games), not on --jobs. Within a chunk Forge's
RNG runs on from game to game and the previous game's loser goes first, so a game can't be replayed alone, and a game
cut by the wall clock (-c) changes the rest of its chunk: keep the clock generous. When the hero dies the other seats
play on until someone wins or the clock runs out; the record stops at the hero's death either way.
"""
import concurrent.futures as cf
import json, os, random, re, subprocess, sys, threading, time

from . import policy, decks as dk, forge, logparse as lp

CHUNK = 5

def chunk_seed(seed, c): return seed * 1000003 + c

# Full lookahead holds a few full game copies per search level (peak ~1.6 GB a game measured on the Niv pod with the
# AiCache patch), so it gets a bigger heap and fewer workers per GB than off/hybrid.
# Hybrid games peak near 1.9 GB of heap (pod1500_20261018, Yusri's pod): at --jobs 12 each JVM got 1.4 GB, games ground in GC
# until one timed out, then the rest of that worker ran out of memory. A JVM gets at least 2 GB (3 GB full) and --jobs is cut
# to what free memory holds.
JOB_MB = {False: 2400, True: 3400}

def max_jobs(full=False):
    return max(1, forge.memory_mb() // JOB_MB[full])

def default_jobs(full=False):
    return max(1, min(os.cpu_count() or 1, max_jobs(full), 8))

def xmx_for(jobs, full=False):
    if os.environ.get("FISHPOND_XMX"): return int(os.environ["FISHPOND_XMX"])
    return max(3000 if full else 2000, min(4000 if full else 3000, forge.memory_mb() // max(1, jobs) - 400))

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
    import re as _re, zipfile as _zip
    names = set()
    for f in forge.override_files():
        m = _re.search(r"^Name:(.+)$", open(f, encoding="utf-8").read(), _re.M)
        if m: names.add(m.group(1).strip())
    # only the overrides that un-flag a card: an override that adds an AI hint to a card Forge plays (Thassa's Oracle)
    # must not make the other seats treat that card as flagged
    flagged = set()
    with _zip.ZipFile(forge.cards_zip()) as z:
        for fn in z.namelist():
            txt = z.read(fn).decode("utf-8", "replace") if fn.endswith(".txt") else ""
            m = _re.search(r"^Name:(.+)$", txt, _re.M)
            if m and m.group(1).strip() in names and _re.search(r"^AI:RemoveDeck:All", txt, _re.M): flagged.add(m.group(1).strip())
    names = sorted(flagged)
    p = os.path.join(run_dir, "overridden.txt")
    with open(p, "w", encoding="utf-8") as fh: fh.write("\n".join(names) + "\n")
    return [f"-Dfishpond.pilotSeats={seats}", f"-Dfishpond.overriddenFile={os.path.abspath(p)}"]

def java_cmd(run_dir, xmx, patched, classes, plan_file=None):
    """The harness JVM command: for a plan file, what a replay of one game runs to play it the way its worker did (the
    overridden-cards list and the win-line audit included); with no plan file, a pool worker that takes its games one at a
    time on standard input (ForgeRunner --queue). The switches are the same either way. run_dir None: a pool shared by the
    pods of a study (no --pilot-seats list, which is per run)."""
    return ["java", f"-Xmx{xmx}m", "-XX:-OmitStackTraceInFastThrow", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
            *([] if forge.pilot_on() else ["-Dfishpond.policy=off"]), *(_pilot_seat_props(run_dir) if run_dir else []),
            f"-Dfishpond.winLines={os.path.join(os.path.dirname(os.path.abspath(__file__)), 'win_lines.txt')}",
            *os.environ.get("FISHPOND_JVM", "").split(),   # extra -D switches for A/B runs (e.g. -Dfishpond.commanderRules=false)
            "-cp", os.pathsep.join(([patched] if patched else []) + [forge.jar(), classes]), "ForgeRunner",
            *([os.path.join(run_dir, "decks", ""), plan_file] if plan_file else ["--queue"])]

ACTION_LINE = ("Turn:", "Add To Stack:", "Resolve Stack:", "Damage:", "Life:", "Zone Change:", "Land:", "Combat:", "Mulligan:", "Discard:")

def game_actions(block):
    """The game-action lines of a game block (what two plays of the same game must share)."""
    return [l for l in block if l.startswith(ACTION_LINE)]

def replay(pod_dir, game_id, out_log, patched=None, quiet=True):
    """Play one game of a run again, exactly as its worker did (same JVM switches, same plan line), into out_log; returns
    (identical, first differing action pair or None, the replay's #FP-END dict). A run from before 2026-11-09 can differ in a
    game its worker played after others in the same JVM (docs/FORGE_ISSUES.md #10); the first game of each worker can't."""
    import glob, tempfile
    line = None
    for pf in glob.glob(os.path.join(pod_dir, "logs", "plan_*.tsv")):
        for l in open(pf, encoding="utf-8"):
            if l.split("	")[0] == str(game_id): line = l.rstrip("\n")
    if line is None: raise SystemExit(f"fishpond: no game {game_id} in {pod_dir}")
    forge.ensure(quiet=quiet)
    classes = harness_classes(quiet)
    patched = patched or forge.patched_classes(quiet=quiet)
    plan = out_log + ".plan.tsv"
    with open(plan, "w", encoding="utf-8") as fh: fh.write(line + "\n")
    with open(out_log, "w", encoding="utf-8") as fh:
        subprocess.run(java_cmd(os.path.abspath(pod_dir), 3000, patched, classes, plan), cwd=forge.run_home(quiet=True), stdout=fh, stderr=subprocess.STDOUT)
    os.remove(plan)
    orig = None
    for lf in glob.glob(os.path.join(pod_dir, "logs", "worker_*.log")):
        for b in lp.split_games(open(lf, encoding="utf-8", errors="replace").read()):
            _, end = lp.harness_lines(b)
            if end and str(end.get("id")) == str(game_id): orig = b
    new = lp.split_games(open(out_log, encoding="utf-8", errors="replace").read())
    new = new[0] if new else []
    _, end = lp.harness_lines(new)
    a, b = game_actions(orig or []), game_actions(new)
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), None)
    if i is None and len(a) != len(b): i = min(len(a), len(b))
    diff = None if i is None else (a[i] if i < len(a) else "(end)", b[i] if i < len(b) else "(end)")
    return diff is None, diff, end

class Pool:
    """Harness JVMs that share one queue of games. Each JVM (ForgeRunner --queue) is handed its next game when it finishes
    one, so a long game holds up one JVM and not the games listed behind it, and a JVM stays loaded and warm for as many
    games as the queue holds. Before, a run split its games into one fixed list per JVM: on baseline125_20261104 (300
    games, 2 lanes x 5 JVMs) the JVMs were busy 51% of the time, and a JVM's first game took a median 95 s against 59 s
    for its third.

    A job is {"id", "line" (the plan line), "run_dir", "session"}; a unit is a list of jobs that stay on one JVM, in order
    (the builds of one game). Worker j appends each game's output to its run's logs/worker_<session>_<j>.log and the plan
    line to logs/plan_<session>_<j>.tsv as before, so collect, replay and the reports read a run the same way. Every game
    has its own seed and Forge match, and the harness starts each one from the same Forge id counters and empty pilot
    state (ForgeRunner.resetGameState; docs/FORGE_ISSUES.md #10), so the games a JVM played before don't change it. Still
    open there: some games change with the garbage collector's timing, which a JVM's history and heap size move.

    A JVM stops after a game that timed out or ran out of memory (ForgeRunner's restart); the worker starts a fresh one for
    its next game. A JVM that dies mid-game gets that game one more try on a fresh JVM, then the game is left for
    --resume. A worker whose JVM won't start hands its games back and stops."""

    def __init__(self, jobs, xmx, run_dir=None, quiet=False, spawn=None):
        self.jobs, self.quiet = max(1, jobs), quiet
        self._lock = threading.Lock()
        self._procs = []
        self._spawn = spawn or self._java(xmx, run_dir)

    def _java(self, xmx, run_dir):
        forge.ensure(quiet=self.quiet)
        cmd = java_cmd(run_dir, xmx, forge.patched_classes(quiet=self.quiet), harness_classes(self.quiet))
        home = forge.run_home(quiet=True)
        return lambda: subprocess.Popen(cmd, cwd=home, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1)

    def _say(self, msg):
        if not self.quiet:
            with self._lock: print(f"fishpond: {msg}", file=sys.stderr, flush=True)

    @staticmethod
    def _read(proc, tail, want):
        """Read the JVM's protocol lines up to `want`; returns that line, or None when the JVM ended first."""
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line == want or line.startswith(want + " "): return line
            tail.append(line); del tail[:-30]
        return None

    def _start(self, j):
        tail = []
        try:
            proc = self._spawn()
        except OSError as e:
            self._say(f"worker {j}: the JVM did not start ({e})"); return None
        with self._lock: self._procs.append(proc)
        if self._read(proc, tail, "#FP-READY") is None:
            self._say(f"worker {j}: the JVM stopped before it was ready (exit {proc.wait()}):\n  " + "\n  ".join(tail[-12:]))
            return None
        return proc

    def _play(self, proc, j, job):
        """One game on worker j's JVM: 'done', 'restart' (done, and the JVM is stopping) or 'dead' (the JVM ended mid-game)."""
        log_dir = os.path.join(job["run_dir"], "logs")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, f"plan_{job['session']}_{j}.tsv"), "a", encoding="utf-8") as fh: fh.write(job["line"] + "\n")
        lf = os.path.join(log_dir, f"worker_{job['session']}_{j}.log")
        tail = []
        try:
            proc.stdin.write("\t".join([lf, os.path.join(job["run_dir"], "decks", ""), job["line"]]) + "\n"); proc.stdin.flush()
            got = self._read(proc, tail, f"#FP-DONE {job['id']}")
        except OSError:
            got = None
        if got is not None: return "restart" if got.endswith(" restart") else "done"
        rc = proc.wait()
        # close the cut-off game's block, so the log parser doesn't read its lines into the next game in this file (a block
        # with no #FP-END line is not a result)
        with open(lf, "a", encoding="utf-8") as fh:
            fh.write(f"\nGame Result: Game {job['id']} ended in a Draw! Took 0 ms. (fishpond: the JVM stopped mid-game, exit {rc})\n")
        self._say(f"worker {j}: the JVM stopped during game {job['id']} (exit {rc})" + "".join("\n  " + t for t in tail[-8:]))
        return "dead"

    def run(self, units, on_done=None):
        """Play every unit; `units` may be a generator (a study prepares its pods as the queue reaches them). on_done(job,
        finished) is called after each job, from the worker's thread. Returns the jobs that did not finish."""
        it, back, left, src = iter(units), [], [], threading.Lock()
        def take():
            with self._lock:
                if back: return back.pop(0)
            with src:
                return next(it, None)
        def work(j):
            proc = None
            while True:
                unit = take()
                if unit is None: break
                for k, job in enumerate(unit):
                    state = "dead"
                    for attempt in range(2):
                        if proc is None: proc = self._start(j)
                        if proc is None:                      # no JVM for this worker: its games go back to the others
                            with self._lock: back.append(unit[k:])
                            return
                        state = self._play(proc, j, job)
                        if state != "done":
                            if state == "restart": proc.wait()
                            proc = None
                        if state != "dead": break
                    if state == "dead":
                        with self._lock: left.append(job)
                    if on_done: on_done(job, state != "dead")
            if proc is not None:
                try: proc.stdin.close()
                except OSError: pass
                proc.wait()
        threads = [threading.Thread(target=work, args=(j,), daemon=True) for j in range(self.jobs)]
        try:
            for t in threads: t.start()
            for t in threads:
                while t.is_alive(): t.join(1)                  # short joins: Ctrl-C reaches the main thread
        finally:
            self.kill()
        # with no JVM left the queue's tail was never taken (a list is read out here; a study's feed sees the pool end)
        rest = list(it) if isinstance(units, (list, tuple)) else []
        return left + [job for unit in back + rest for job in unit]

    def kill(self):
        """Stop any JVM still running (the pool's work is over, or the session was interrupted)."""
        with self._lock: procs = list(self._procs)
        for p in procs:
            if p.poll() is None: p.kill()

def execute(entries, jobs, run_dir, session, quiet=False):
    """Run plan entries on `jobs` harness JVMs sharing one queue (Pool); each JVM appends its games to
    logs/worker_<session>_<j>.log one at a time (a cut-off session keeps every finished game). Returns wall seconds."""
    if not entries: return 0.0
    full = uses_full(entries)
    if jobs > max_jobs(full) and not os.environ.get("FISHPOND_XMX"):
        if not quiet: print(f"fishpond: --jobs {jobs} cut to {max_jobs(full)}: {forge.memory_mb()} MB free holds that many JVMs at {JOB_MB[full]} MB", file=sys.stderr)
        jobs = max_jobs(full)
    units = {}
    for e in entries:                                          # paired builds of a game share a JVM
        units.setdefault(e["game"], []).append({"id": e["id"], "line": e["line"], "run_dir": run_dir, "session": session})
    jobs = max(1, min(jobs, len(units)))
    t0 = time.time()
    done = [0]
    def progress(job, ok):
        done[0] += ok
        if not quiet: print(f"fishpond: {done[0]}/{len(entries)} games this session ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
    Pool(jobs, xmx_for(jobs, full), run_dir, quiet).run(list(units.values()), progress)
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
                      "loops": end.get("loops", []), "held": end.get("held"), "lines": end.get("lines"), "castplan": end.get("castplan"), "threat": end.get("threat"), "hold": end.get("hold"), "wipe": end.get("wipe"), "seq": end.get("seq"), "plan": end.get("plan"), "setup": end.get("setup"),
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
