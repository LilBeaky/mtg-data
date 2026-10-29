"""`fishpond check`: the checks a change needs before a push, picked from the files changed since the last push.

The user, 2026-10-29: "if you're waiting 30 minutes to run a couple hundred irrelevant puzzles, we should probably not do that."
The puzzles test Forge's AI (patches, card overrides, the harness's decision code); the repo's smoke test covers the whole repo
(deck tools, mana sim, goldfish, explorer, and five fishpond checks). What runs, by what changed:

  docs, markdown                                  nothing
  page, report and analysis code, win lines      fishpond units + a live 2-game run (it writes the game page)
  a card override, a puzzle, a deck list          the puzzles that name that card, that puzzle, the deck's puzzles + the live run
  Forge patches, harness Java, pilot policy,
  the build and run code                          every puzzle (batched) + the live run
  anything else (scripts, goldfish, data, tests)  the repo's full smoke test

`--full` runs everything; `--dry-run` only prints the plan; `--since REF` compares with REF instead of the branch's upstream.
The rule (docs/FISHPOND.md): `fishpond check` before every push, and the full puzzle suite before a long study.
"""
import glob, os, re, subprocess, sys, tempfile

from . import puzzles as pz

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FULL_PUZZLES = (r"fishpond/forge_patches/", r"fishpond/harness/", r"fishpond/policy\.py$", r"fishpond/forge\.py$",
                r"fishpond/runner\.py$", r"fishpond/puzzles\.py$", r"fishpond/decks\.py$")
LIVE_RUN = (r"fishpond/[a-z_]+\.py$", r"fishpond/win_lines\.txt$", r"fishpond/opponents/", r"fishpond/pods/")
UNITS_ONLY = (r"tests/fishpond_units\.py$", r"tests/fishpond/")
NOTHING = (r"\.md$", r"^docs/", r"^\.gitignore$")


def _git(*a):
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout


def changed(since=None):
    """Files this branch's own commits changed since REF (default: the branch's upstream; else origin/main), and anything not
    committed yet. Merges are left out: what a merge of main brings (the automated data refresh) was checked where it was made."""
    ref = since or (_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").strip() or "origin/main")
    base = _git("merge-base", "HEAD", ref).strip() or ref
    files = set(_git("log", "--first-parent", "--no-merges", "--name-only", "--pretty=format:", f"{base}..HEAD").split())
    files |= set(_git("diff", "--name-only", "HEAD").split())
    files |= {l[3:].strip() for l in _git("status", "--porcelain").splitlines() if l.startswith("??")}
    return ref, sorted(f for f in files if f)


def _puzzles_naming(text):
    """Puzzles whose file mentions TEXT (a card or deck name) in their header or state."""
    out = []
    for f in pz.select():
        try:
            if text.lower() in open(f, encoding="utf-8").read().lower(): out.append(f)
        except OSError:
            pass
    return out


def plan(files):
    """{"units": bool, "live": bool, "smoke": bool, "puzzles": "all" | set(paths), "why": [lines]}."""
    p = dict(units=False, live=False, smoke=False, puzzles=set(), why=[])
    for f in files:
        if any(re.search(r, f) for r in NOTHING):
            p["why"].append(f"{f}: docs, nothing to run"); continue
        if any(re.search(r, f) for r in FULL_PUZZLES):
            p["puzzles"] = "all"; p["units"] = p["live"] = True
            p["why"].append(f"{f}: can change how the AI plays or how puzzles run: every puzzle + the live run"); continue
        if f.startswith("fishpond/forge_card_overrides/"):
            path = os.path.join(REPO, f)
            name = None
            if os.path.exists(path):
                m = re.search(r"^Name:(.+)$", open(path, encoding="utf-8").read(), re.M)
                name = m.group(1).strip() if m else None
            hit = _puzzles_naming(name) if name else []
            if p["puzzles"] != "all": p["puzzles"] |= set(hit)
            p["units"] = p["live"] = True
            p["why"].append(f"{f}: {name or 'a card'}'s {len(hit)} puzzle(s) + the live run"); continue
        if f.startswith("fishpond/puzzles/") and f.endswith(".pzl"):
            if p["puzzles"] != "all" and os.path.exists(os.path.join(REPO, f)): p["puzzles"].add(os.path.join(REPO, f))
            p["why"].append(f"{f}: that puzzle"); continue
        if f.startswith("decks/") and f.endswith(".txt"):
            deck = os.path.basename(f)[:-4]
            hit = [x for x in pz.select() if re.search(r"^#\s*deck2?:\s*" + re.escape(deck) + r"\s*$", open(x, encoding="utf-8").read(), re.M)]
            if p["puzzles"] != "all": p["puzzles"] |= set(hit)
            p["live"] = True
            p["why"].append(f"{f}: the {len(hit)} puzzle(s) that play this deck + the live run"); continue
        if any(re.search(r, f) for r in UNITS_ONLY):
            p["units"] = True; p["why"].append(f"{f}: fishpond units"); continue
        if any(re.search(r, f) for r in LIVE_RUN):
            p["units"] = p["live"] = True; p["why"].append(f"{f}: fishpond units + the live run"); continue
        p["smoke"] = True
        p["why"].append(f"{f}: outside fishpond: the repo's full smoke test")
    return p


def live_run():
    """A 2-game run (Chulane vs dummies, 3 turns), as the smoke test's: games recorded and the game page written."""
    out = tempfile.mkdtemp(prefix="fp-check-")
    r = subprocess.run([sys.executable, "-m", "fishpond", "run", "tests/forge/chulane.txt", "--trials", "2", "--cap", "3", "--turns", "3",
                        "--jobs", "2", "--quiet", "--out", os.path.join(out, "run")], cwd=REPO, capture_output=True, text=True, timeout=900)
    run = os.path.join(out, "run")
    games = sum(1 for _ in open(os.path.join(run, "games.jsonl"))) if os.path.exists(os.path.join(run, "games.jsonl")) else 0
    page = os.path.exists(os.path.join(run, "games.html"))
    ok = r.returncode == 0 and games == 2 and page
    print(f"{'PASS' if ok else 'FAIL'}  live run: {games} of 2 games recorded, game page {'written' if page else 'missing'}")
    if not ok: print((r.stdout + r.stderr)[-2000:])
    return ok


def cmd(args):
    if args.full:
        ref, files = "(--full)", []
        p = dict(units=True, live=True, smoke=True, puzzles="all", why=["--full: everything"])
    else:
        ref, files = changed(args.since)
        p = plan(files)
    print(f"fishpond check: {len(files)} file(s) changed since {ref}")
    for w in p["why"]: print("  " + w)
    n = len(pz.select()) if p["puzzles"] == "all" else len(p["puzzles"])
    steps = (["fishpond units"] if p["units"] else []) + ([f"{n} puzzle(s)"] if n else []) + (["the live run"] if p["live"] else []) \
        + (["the repo's smoke test"] if p["smoke"] else [])
    print("  runs: " + (", ".join(steps) if steps else "nothing"))
    if args.dry_run or not steps: return
    ok = True
    if p["units"]:
        r = subprocess.run([sys.executable, "tests/fishpond_units.py"], cwd=REPO, capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "units: no output"); ok &= r.returncode == 0
        if r.returncode: print(r.stdout[-2000:])
    if n:
        files_ = None if p["puzzles"] == "all" else sorted(p["puzzles"])
        ok &= pz.run_all(files=files_ if files_ is not None else pz.select(), jobs=args.jobs)
    if p["live"]: ok &= live_run()
    if p["smoke"]:
        r = subprocess.run([sys.executable, "tests/smoke.py"], cwd=REPO, capture_output=True, text=True)
        print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "smoke: no output"); ok &= r.returncode == 0
    print("fishpond check: " + ("all clear" if ok else "FAILED"))
    if not ok: sys.exit(1)
