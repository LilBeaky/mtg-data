"""Puzzles: one board state each, to test how Forge's AI plays one mechanic (docs/FORGE_PLAN.md, "Pilot policy", Part 2).

A puzzle is fishpond/puzzles/NAME.pzl: header lines, then Forge GameState lines (p0... = seat 1, the player under test;
p1... = seat 2; both are Forge's AI). The harness's PuzzleRunner loads the state at the first turn, lets the AI play
TURNS turns and prints the game log; the puzzle passes when every 'expect' regex matches a log line and no 'forbid'
regex does.

  # title: Astral Slide: the AI cycles with Slide out and exiles an attacker
  # turns: 2            (turns to play after the state is loaded, default 2)
  # seed: 1
  # sim: hybrid         (seat 1's lookahead: off, the default, or hybrid as in a run)
  # expect: REGEX       (repeatable)
  # forbid: REGEX       (repeatable)
  # jvm: -Dname=value   (optional: system properties for this puzzle, e.g. a small -Dfishpond.loopMax)
  # card: NAME          (the card or mechanic under test, for the summary)
  # deck: NAME          (optional: seat 1 plays with decks/NAME.txt's pilot policy; '# deck2:' gives seat 2 one)
  p0life=20
  p0battlefield=Astral Slide;Plains;Plains;Plains
  ...
"""
import glob, os, re, subprocess, sys, threading

from . import forge, runner

PUZZLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "puzzles")

def load(path):
    meta = {"title": os.path.basename(path), "turns": 2, "seed": 1, "sim": "off", "expect": [], "forbid": [], "order": [], "card": ""}
    state = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = re.match(r"#\s*(\w+):\s*(.*)$", line)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k in ("expect", "forbid"): meta[k].append(v)
            elif k == "order": meta[k].append(tuple(x.strip() for x in v.split("<<", 1)))   # "A << B": A seen, and before any B
            elif k in ("turns", "seed"): meta[k] = int(v)
            else: meta[k] = v
        elif line.strip() and not line.startswith("#"):
            state.append(line)
    return meta, state

_POLICY_LOCK = threading.Lock()   # puzzles run in threads; the card lookup loads lazily and two builds at once came out empty

def _policy_dck(name):
    """A .dck path whose <dck>.policy.json holds deck NAME's pilot policy (decks/NAME.txt), rewritten when the list changes."""
    from . import decks as dk, policy
    src = os.path.join(os.path.dirname(PUZZLE_DIR), "..", "decks", name + ".txt")
    out = os.path.join(forge.run_home(quiet=True), "puzzle_decks"); os.makedirs(out, exist_ok=True)
    fp = os.path.join(out, name + ".dck")
    with _POLICY_LOCK:
        if not os.path.exists(fp + ".policy.json") or os.path.getmtime(fp + ".policy.json") < os.path.getmtime(src):
            policy.write_for(dk.load(src), fp)
    return os.path.abspath(fp)

def evaluate(meta, lines):
    """(passed, failures) for a puzzle's game log."""
    fails = []
    for rx in meta["expect"]:
        if not any(re.search(rx, l) for l in lines): fails.append(f"expected, not seen: {rx}")
    for rx in meta["forbid"]:
        hit = [l for l in lines if re.search(rx, l)]
        if hit: fails.append(f"forbidden, seen: {rx} ({hit[0].strip()[:120]})")
    for a, b in meta["order"]:
        ia = next((i for i, l in enumerate(lines) if re.search(a, l)), None)
        ib = next((i for i, l in enumerate(lines) if re.search(b, l)), None)
        if ia is None: fails.append(f"order: not seen: {a}")
        elif ib is not None and ib < ia: fails.append(f"order: {b} came before {a}")
    if any(l.startswith("#FP-PUZZLE error") for l in lines): fails.append(next(l for l in lines if l.startswith("#FP-PUZZLE error")))
    return not fails, fails

def _java(meta, quiet=True):
    classes = runner.harness_classes(quiet)
    patched = forge.patched_classes(quiet=quiet)
    return ["java", "-Xmx1500m", "-XX:-OmitStackTraceInFastThrow", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8", *meta.get("jvm", "").split(),
            "-cp", os.pathsep.join(([patched] if patched else []) + [forge.jar(), classes]), "PuzzleRunner"]

def _decks(meta):
    """The deck arguments: seat 1's policy .dck (or "-") and seat 2's, as PuzzleRunner reads them."""
    d1 = _policy_dck(meta["deck"]) if meta.get("deck") else "-"
    d2 = _policy_dck(meta["deck2"]) if meta.get("deck2") else "-"
    return d1, d2

def run_one(path, quiet=True):
    """(passed, meta, log lines, failures) for one puzzle in its own JVM."""
    meta, state = load(path)
    sf = path + ".state.tmp"
    open(sf, "w", encoding="utf-8").write("\n".join(state) + "\n")
    cmd = _java(meta, quiet) + [os.path.abspath(sf), str(meta["turns"]), str(meta["seed"]), meta["sim"]]
    d1, d2 = _decks(meta)
    if d1 != "-" or d2 != "-": cmd.append(d1)   # '# deck: NAME': seat 1 plays with that deck's pilot policy (key cards,
    if d2 != "-": cmd.append(d2)                   # combos, tutor picks); '# deck2: NAME' gives seat 2 one
    try:
        r = subprocess.run(cmd, cwd=forge.run_home(quiet=quiet), capture_output=True, text=True, timeout=400)
        out = r.stdout
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    finally:
        os.remove(sf)
    lines = out.splitlines()
    passed, fails = evaluate(meta, lines)
    return passed, meta, lines, fails

BATCH = 20   # puzzles a JVM

def run_batch(paths, workers=3, quiet=True, on_result=None):
    """Run puzzles a few JVMs at a time, many puzzles a JVM (PuzzleRunner --batch: Forge loads once a JVM, not once a puzzle).
    A JVM holds puzzles with the same '# jvm:' switches and the same policy hooks (a deck or none), so each plays as it would
    alone. Returns {path: (passed, meta, lines, failures)}; on_result(path, result) is called as each finishes."""
    import concurrent.futures, tempfile
    forge.ensure(quiet=True); runner.harness_classes(quiet); forge.patched_classes(quiet=quiet)
    items = []
    for p in paths:
        meta, state = load(p)
        d1, d2 = _decks(meta)
        items.append((p, meta, state, d1, d2))
    groups = {}
    for it in items:
        groups.setdefault((it[1].get("jvm", ""), it[3] != "-" or it[4] != "-"), []).append(it)
    chunks = [g[i:i + BATCH] for g in groups.values() for i in range(0, len(g), BATCH)]
    results = {}
    tmp = tempfile.mkdtemp(prefix="fp-puzzles-")

    def one(k, chunk):
        man = os.path.join(tmp, f"batch{k}.tsv")
        with open(man, "w", encoding="utf-8") as fh:
            for p, meta, state, d1, d2 in chunk:
                sf = os.path.join(tmp, os.path.basename(p) + ".state")
                open(sf, "w", encoding="utf-8").write("\n".join(state) + "\n")
                fh.write("\t".join([os.path.basename(p), sf, str(meta["turns"]), str(meta["seed"]), meta["sim"], d1, d2]) + "\n")
        try:
            r = subprocess.run(_java(chunk[0][1], quiet) + ["--batch", man], cwd=forge.run_home(quiet=True), capture_output=True,
                               text=True, timeout=300 * len(chunk) + 120)
            out = r.stdout
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        cur, buf = None, {}
        for l in out.splitlines():
            if l.startswith("#FP-PUZZLE begin "): cur = l[17:].strip(); buf[cur] = []; continue
            if l.startswith("#FP-PUZZLE done "): cur = None; continue
            if cur is not None: buf[cur].append(l)
        done = []
        for p, meta, state, d1, d2 in chunk:
            name = os.path.basename(p)
            if name in buf:
                passed, fails = evaluate(meta, buf[name])
                done.append((p, (passed, meta, buf[name], fails)))
            else:   # the batch died before this one: run it alone
                done.append((p, run_one(p, quiet)))
        return done

    with concurrent.futures.ThreadPoolExecutor(max(1, workers)) as ex:
        for fut in concurrent.futures.as_completed([ex.submit(one, k, c) for k, c in enumerate(chunks)]):
            for p, res in fut.result():
                results[p] = res
                if on_result: on_result(p, res)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return results

def select(names=None):
    files = sorted(glob.glob(os.path.join(PUZZLE_DIR, "*.pzl")))
    if names: files = [f for f in files if any(n.lower() in os.path.basename(f).lower() for n in names)]
    return files

def run_all(names=None, verbose=False, jobs=3, single=False, files=None):
    """Run the puzzles (all, those whose file name contains one of NAMES, or FILES), print each result and a summary;
    True when every one passed (known gaps aside). Batched by default (run_batch); single=True gives each its own JVM."""
    files = files if files is not None else select(names)
    forge.ensure(quiet=True)
    tally = {"ok": 0, "gaps": 0}
    lock = threading.Lock()

    def show(f, res):
        passed, meta, lines, fails = res
        gap = str(meta.get("known_gap", "")).lower() in ("yes", "true", "1")
        with lock:
            if gap and not passed:
                tally["gaps"] += 1
                print(f"GAP   {os.path.basename(f)}: {meta['title']}", flush=True)
                return
            tally["ok"] += passed
            print(f"{'PASS' if passed else 'FAIL'}  {os.path.basename(f)}: {meta['title']}" + ("  (marked known_gap but passes now: unmark it)" if gap and passed else ""), flush=True)
            for x in fails: print(f"      {x}")
            if verbose or not passed:
                for l in lines:
                    if re.match(r"(Turn|Phase|Add To Stack|Resolve Stack|Damage|Life|Land|Combat|Zone|Discard|#FP-PUZZLE)", l.strip()): print("        | " + l.strip()[:160])

    if single:
        for f in files: show(f, run_one(f))
    else:
        run_batch(files, workers=jobs, on_result=show)
    ok, gaps = tally["ok"], tally["gaps"]
    print(f"puzzles: {ok}/{len(files) - gaps} passed" + (f", {gaps} known gap(s)" if gaps else ""))
    return ok == len(files) - gaps

COLOR_LAND = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}

def write_smoke(name, turns=3):
    """A generic puzzle for one card: it sits in hand with mana for it (plus spare), filler cards and a library; the opponent
    has nothing that attacks (so life changes are the AI's own doing). Passes when the AI casts or plays the card and doesn't lose. The question it answers: once the card
    is unflagged, does Forge's AI use it at all, and without hurting itself?"""
    import mtg
    c, _ = mtg.find(name)
    if not c: sys.exit(f"fishpond: no card {name!r}")
    cost = c.get("mana_cost") or (c.get("card_faces") or [{}])[0].get("mana_cost", "")
    cols = re.findall(r"\{([WUBRG])", cost) or []
    lands = [COLOR_LAND[x] for x in cols] + ["Wastes"] * cost.count("{C}")    # {C} needs colorless mana (Eldrazi): Plains can't pay it
    ci = [x for x in (c.get("color_identity") or []) if x in COLOR_LAND] or ["W"]
    while len(lands) < int(c.get("cmc") or 0) + 3: lands.append(COLOR_LAND[ci[len(lands) % len(ci)]])
    is_land = "Land" in (c.get("type_line") or "")
    lib = ";".join([COLOR_LAND[ci[k % len(ci)]] for k in range(14)])
    verb = "played" if is_land else "(cast|activated)"
    fn = os.path.join(PUZZLE_DIR, "smoke_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".pzl")
    open(fn, "w", encoding="utf-8").write(f"""# title: {name}: unflagged, the AI uses it and doesn't hurt itself (smoke test)
# card: {name}
# turns: {turns}
# expect: Ai\\(1\\)-P1 {verb} {re.escape(c['name'])}
# forbid: Ai\\(1\\)-P1 (has lost|loses the game)
# forbid: Life: Ai\\(1\\)-P1 \\d+ > (-?\\d)$
p0life=20
p1life=20
turn=1
activeplayer=p0
activephase=MAIN1
p0battlefield={";".join(lands)}
p0hand={c['name']};{COLOR_LAND[ci[0]]};{COLOR_LAND[ci[-1]]}
p0library={lib}
p1battlefield=Forest;Forest;Mountain
p1library=Forest;Forest;Forest;Forest;Forest;Forest;Forest;Forest
""")
    return fn


def deck_files():
    """Every deck list in the repo Fishpond might play: saved decks, gauntlets, test lists, snapshots."""
    from . import decks as dk
    pats = ["decks/*.txt", "fishpond/opponents/**/*.txt", "tests/forge/*.txt", "snapshots/*.txt"]
    out = set()
    for p in pats: out |= set(glob.glob(os.path.join(dk.REPO, p), recursive=True))
    return sorted(f for f in out if not os.path.basename(f).lower().startswith("readme"))

def flagged_cards():
    """{card: [deck files]} for cards Forge flags AI:RemoveDeck:All (before fishpond's overrides) across deck_files()."""
    from . import decks as dk
    idx = forge.index()
    out = {}
    for f in deck_files():
        try:
            d = dk.load(f, idx=idx)
        except SystemExit:
            continue
        for n in [x for x in d.commanders] + [x for _, x in d.main]:
            fn = d.forge.get(n, n)
            hit = idx.get(forge._norm(fn))
            if hit and "All" in hit[1]: out.setdefault(fn, []).append(os.path.relpath(f, dk.REPO))
    return out

def status(card):
    """'unflagged' (override present), 'known gap' (a puzzle marks it), 'smoke passed'/'smoke failed' or 'untested'."""
    ovr = {re.search(r"^Name:(.+)$", open(f, encoding="utf-8").read(), re.M).group(1).strip() for f in forge.override_files()}
    if card in ovr: return "unflagged"
    for f in glob.glob(os.path.join(PUZZLE_DIR, "*.pzl")):
        meta, _ = load(f)
        if meta.get("card") == card and str(meta.get("known_gap", "")).lower() in ("yes", "true", "1"): return "known gap"
    return "untested"
