"""Puzzles: one board state each, to test how Forge's AI plays one mechanic (docs/FORGE_PLAN.md, "Pilot policy", Part 2).

A puzzle is fishpond/puzzles/NAME.pzl: header lines, then Forge GameState lines (p0... = seat 1, the player under test;
p1... = seat 2; both are Forge's AI). The harness's PuzzleRunner loads the state at the first turn, lets the AI play
TURNS turns and prints the game log; the puzzle passes when every 'expect' regex matches a log line and no 'forbid'
regex does.

  # title: Astral Slide: the AI cycles with Slide out and exiles an attacker
  # turns: 2            (turns to play after the state is loaded, default 2)
  # seed: 1
  # expect: REGEX       (repeatable)
  # forbid: REGEX       (repeatable)
  # card: NAME          (the card or mechanic under test, for the summary)
  p0life=20
  p0battlefield=Astral Slide;Plains;Plains;Plains
  ...
"""
import glob, os, re, subprocess, sys

from . import forge, runner

PUZZLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "puzzles")

def load(path):
    meta = {"title": os.path.basename(path), "turns": 2, "seed": 1, "expect": [], "forbid": [], "card": ""}
    state = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = re.match(r"#\s*(\w+):\s*(.*)$", line)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k in ("expect", "forbid"): meta[k].append(v)
            elif k in ("turns", "seed"): meta[k] = int(v)
            else: meta[k] = v
        elif line.strip() and not line.startswith("#"):
            state.append(line)
    return meta, state

def run_one(path, quiet=True):
    """(passed, meta, log lines, failures) for one puzzle."""
    meta, state = load(path)
    classes = runner.harness_classes(quiet)
    patched = forge.patched_classes(quiet=quiet)
    sf = path + ".state.tmp"
    open(sf, "w", encoding="utf-8").write("\n".join(state) + "\n")
    cmd = ["java", "-Xmx1500m", "-Djava.awt.headless=true", "-Dfile.encoding=UTF-8",
           "-cp", os.pathsep.join(([patched] if patched else []) + [forge.jar(), classes]), "PuzzleRunner", os.path.abspath(sf),
           str(meta["turns"]), str(meta["seed"])]
    try:
        r = subprocess.run(cmd, cwd=forge.run_home(quiet=quiet), capture_output=True, text=True, timeout=400)
        out = r.stdout
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    finally:
        os.remove(sf)
    lines = out.splitlines()
    fails = []
    for rx in meta["expect"]:
        if not any(re.search(rx, l) for l in lines): fails.append(f"expected, not seen: {rx}")
    for rx in meta["forbid"]:
        hit = [l for l in lines if re.search(rx, l)]
        if hit: fails.append(f"forbidden, seen: {rx} ({hit[0].strip()[:120]})")
    if any(l.startswith("#FP-PUZZLE error") for l in lines): fails.append(next(l for l in lines if l.startswith("#FP-PUZZLE error")))
    return not fails, meta, lines, fails

def run_all(names=None, verbose=False):
    files = sorted(glob.glob(os.path.join(PUZZLE_DIR, "*.pzl")))
    if names: files = [f for f in files if any(n.lower() in os.path.basename(f).lower() for n in names)]
    forge.ensure(quiet=True)
    ok = gaps = 0
    for f in files:
        passed, meta, lines, fails = run_one(f)
        gap = str(meta.get("known_gap", "")).lower() in ("yes", "true", "1")
        if gap and not passed:
            gaps += 1
            print(f"GAP   {os.path.basename(f)}: {meta['title']}")
            continue
        ok += passed
        print(f"{'PASS' if passed else 'FAIL'}  {os.path.basename(f)}: {meta['title']}" + ("  (marked known_gap but passes now: unmark it)" if gap and passed else ""))
        for x in fails: print(f"      {x}")
        if verbose or not passed:
            for l in lines:
                if re.match(r"(Turn|Phase|Add To Stack|Resolve Stack|Damage|Life|Land|Combat|Zone|Discard|#FP-PUZZLE)", l.strip()): print("        | " + l.strip()[:160])
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
    lands = [COLOR_LAND[x] for x in cols]
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
