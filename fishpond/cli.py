"""Fishpond command line. Run from the repo root:

  python3 -m fishpond setup [--jdk]               download/cache the pinned Forge release; print versions and paths
  python3 -m fishpond deck DECK [--opp SPEC]...    check a deck (and opponents) against Forge: unknown cards, AI flags
  python3 -m fishpond save DECK --name "Ians Zur Cycling"   store the list in decks/ (.txt source + Forge .dck)
  python3 -m fishpond run DECK [options]           play DECK in 4-player pods on Forge and report (goldfish's layout + more)
  python3 -m fishpond run --resume RUN_DIR [--trials N]   finish a cut-off run (unfinished games replay from their seeds)
                                                    and/or add N more games to it; results accumulate in the same run
  python3 -m fishpond report RUN_DIR [--reparse]   reprint a saved run's report (--reparse: parse its logs again)
  python3 -m fishpond show RUN_DIR GAME [--log]    one game's parsed record (and its Forge log) for hand audits

run options:
  --trials N (--games)   games per build (default 20)
  --seed N               seed (default 1); the same seed and game count replay the same games and pods
  --turns N              report horizon in your turns (default 10)
  --opp SPEC             an opponent seat, up to 3 times: 'dummy', a deck file, a name in fishpond/opponents/, or
                         'gauntlet:NAME' (fills the remaining seats from fishpond/opponents/NAME/, sampled per game).
                         Seats not given are dummies. --opp-set FILE lists the seats one per line.
  --fixed-pod            with a gauntlet: the same sampled seats for every game
  --ai PROFILE           your AI profile: Default, Cautious, Experimental, Reckless (Forge's res/ai)
  --opp-ai A,B,C         the opponents' AI profiles, by seat
  --sim MODE             your seat's lookahead (harness): off, hybrid (default: a one-move simulation vetoes bad plays),
                         full (plays chosen by a 3-deep search; also decides library searches). Slower as it goes up.
  --opp-sim MODE         the same for real-deck opponents (default hybrid; dummies never need it)
  --track "Label=REGEX"  first turn a matching card is cast or enters (repeatable; '# track:' header lines are added)
  --variant "Label|Out=>In;Out=>In"  also run a swapped build on the same seeds and pods (repeatable)
  --commander NAME       when the list has no Commander section
  --engine E             harness (default when javac is available: one JVM per worker, every game reseeded, stops when
                         you've lost or at --cap, per-turn snapshots) or cli (Forge's stock sim; no javac needed)
  --cap N                harness: end a game after your turn N as unfinished (default 20)
  --timeout S            harness: wall-clock safety limit per game (default 1800; lookahead games can run long)
  --clock S              cli: wall-clock seconds before Forge calls a game a draw (default 120)
  --jobs N               parallel JVMs (default: CPUs and memory allow)
  --out DIR              where to save the run (default data/fishpond/<time>-<deck>/, gitignored)
  --json                 machine-readable summary instead of the report
"""
import argparse, json, os, re, sys, time

from . import decks as dk, forge, report as rp, runner

def cmd_setup(args):
    h = forge.ensure()
    idx = forge.index()
    jv, jc = forge.java_major(), forge.java_major("javac")
    if args.jdk and not jc: jc = forge.java_major("javac") if forge.install_jdk() else 0
    print(f"Forge {forge.FORGE_VERSION}: {h}")
    print(f"card scripts indexed: {len(idx)} names ({os.path.join(h, 'fishpond_names.json')})")
    print(f"java {jv or 'MISSING'} | javac {jc or 'not installed (only the harness needs it: setup --jdk)'}")
    print(f"memory available {forge.memory_mb()} MB | CPUs {os.cpu_count()} | default --jobs {runner.default_jobs()}")
    if not jv: sys.exit("fishpond: install Java 17+ (the Forge runtime)")
    pd = forge.patched_classes() if jc else None
    print(f"Forge patches: {len(forge.patch_files())} applied ({pd})" if pd else "Forge patches: none built (needs javac)")
    latest = forge.latest_release()
    if latest is None: print("Forge release check: offline, skipped")
    elif forge._vkey(latest) > forge._vkey(forge.FORGE_VERSION):
        print(f"Forge release check: {latest} is out (pinned {forge.FORGE_VERSION}); to move up, follow docs/FORGE_ISSUES.md 'Bumping Forge'")
    else: print(f"Forge release check: {forge.FORGE_VERSION} is the latest release")

def _opp_specs(args):
    specs = list(args.opp or [])
    if args.opp_set: specs += dk.read_opp_set(args.opp_set)
    return specs

def _print_problems(label, d):
    probs = dk.validate(d)
    for p in probs: print(f"  {label}: {p}")
    return probs

def cmd_deck(args):
    forge.ensure()
    idx = forge.index()
    hero = dk.load(args.deck, "hero", idx=idx, commander=args.commander)
    print(f"hero: {hero.label} | {hero.size} cards | bracket {hero.bracket or '?'}")
    _print_problems("hero", hero)
    ai = sorted(c for c, f in hero.flags.items() if "All" in f)
    print("  Forge AI can't play well (AI:RemoveDeck:All): " + ("; ".join(ai) if ai else "none"))
    fixed, pool = dk.seat_plan(_opp_specs(args))
    for kind, path in fixed + [("deck", p) for p in (pool or [])]:
        if kind == "dummy": continue
        d = dk.load(path, "opponent", idx=idx)
        print(f"opponent: {d.label} ({os.path.relpath(path)}) | {d.size} cards | bracket {d.bracket or '?'}")
        _print_problems(d.label, d)

def cmd_save(args):
    """Save a list into decks/ as NAME.txt (source, headers kept) + NAME.dck (Forge-ready)."""
    forge.ensure()
    d = dk.load(args.deck, "hero", idx=forge.index(), commander=args.commander)
    for p in dk.validate(d): print(f"  warning: {p}")
    stem = re.sub(r"[^A-Za-z0-9]+", "_", args.name.strip()).strip("_")
    out = os.path.join(dk.REPO, "decks"); os.makedirs(out, exist_ok=True)
    src = open(args.deck, encoding="utf-8").read()
    if not src.startswith("# name:"): src = f"# name: {args.name.strip()}\n" + src
    open(os.path.join(out, stem + ".txt"), "w", encoding="utf-8").write(src)
    open(os.path.join(out, stem + ".dck"), "w", encoding="utf-8").write(d.dck(args.name.strip()))
    print(f"saved decks/{stem}.txt and decks/{stem}.dck ({d.label}, {d.size} cards, bracket {d.bracket or '?'})")

def cmd_run(args):
    if args.resume: return cmd_resume(args)
    if not args.deck: sys.exit("fishpond: run needs a deck file (or --resume RUN_DIR)")
    args.trials = 20 if args.trials is None else args.trials
    if args.trials < 1: sys.exit("fishpond: --trials must be at least 1")
    if args.turns < 1: sys.exit("fishpond: --turns must be at least 1")
    forge.ensure(quiet=args.quiet)
    idx = forge.index()
    hero = dk.load(args.deck, "hero", idx=idx, commander=args.commander)
    probs = dk.validate(hero)
    if hero.not_found or not hero.commanders:
        sys.exit("fishpond: fix the deck first:\n  " + "\n  ".join(probs))
    for p in probs: print(f"fishpond: hero: {p}", file=sys.stderr)
    fixed, pool = dk.seat_plan(_opp_specs(args))
    pods = runner.Pods(fixed, pool, args.fixed_pod, idx=idx)
    for d in pods.all_decks():
        for p in dk.validate(d):
            if not p.startswith("partial"): print(f"fishpond: opponent {d.label}: {p}", file=sys.stderr)
    opp_ai = (args.opp_ai.split(",") + ["Default"] * 3)[:3] if args.opp_ai else ["Default"] * 3
    builds = [("base", hero)]
    for v in args.variant:
        label, _, swaps = v.rpartition("|")
        pairs = [tuple(x.strip() for x in s.split("=>")) for s in swaps.split(";") if "=>" in s]
        vd, vp = dk.swapped(hero, pairs, idx=idx)
        if vp: sys.exit("fishpond: --variant " + v + ": " + "; ".join(vp))
        builds.append((label or f"variant {len(builds)}", vd))
    jobs = args.jobs or runner.default_jobs(full="full" in (args.sim, args.opp_sim))
    if args.timeout is None: args.timeout = 7200 if "full" in (args.sim, args.opp_sim) else 1800
    engine = args.engine
    if engine == "auto":
        engine = "harness" if runner.harness_available() or forge.install_jdk(quiet=True) else "cli"
        if engine == "cli": print("fishpond: no javac, so using --engine cli (setup --jdk enables the faster harness)", file=sys.stderr)
    run_dir = args.out or os.path.join(dk.REPO, "data", "fishpond", time.strftime("%Y%m%d-%H%M%S") + "-" + hero.tag)
    os.makedirs(run_dir, exist_ok=True)
    if not args.quiet:
        print(f"fishpond: {len(builds)} build(s) x {args.trials} games, {jobs} JVM(s), engine {engine}; saving to {run_dir}",
              file=sys.stderr)
    meta = {"deck": _rel(args.deck) if os.path.exists(args.deck) else args.deck, "commander": hero.label,
            "cards": hero.size, "trials": args.trials, "seed": args.seed, "turns": args.turns, "engine": engine, "cap": args.cap,
            "timeout": args.timeout, "forge": forge.FORGE_VERSION, "jobs": jobs, "wall": 0, "clock": args.clock, "hero_ai": args.ai,
            "opp_ai": opp_ai, "sim": args.sim if engine == "harness" else "off", "opp_sim": args.opp_sim if engine == "harness" else "off",
            "track": hero.meta.get("track", []), "extra_track": args.track, "key": _keys(hero),
            "variants": args.variant, "opp": _opp_specs(args), "fixed_pod": args.fixed_pod, "run_dir": _rel(run_dir),
            "commander_opt": args.commander, "complete": False}
    runner.save(run_dir, meta, [])                  # written first: a cut-off run can be reported on and resumed
    if engine == "harness":
        if not args.quiet: print(f"fishpond: if this session ends early: python3 -m fishpond run --resume {_rel(run_dir)}", file=sys.stderr)
        records, wall = runner.run_harness(builds, pods, args.trials, args.seed, args.cap, args.timeout, jobs, run_dir, hero_ai=args.ai,
                                           opp_ai=opp_ai, quiet=args.quiet, hero_sim=args.sim, opp_sim=args.opp_sim, keys=_keys(hero))
    else:
        records, wall = runner.run_cli(builds, pods, args.trials, args.seed, args.clock, jobs, run_dir, hero_ai=args.ai,
                                       opp_ai=opp_ai, quiet=args.quiet)
    meta.update(wall=wall, complete=True)
    runner.save(run_dir, meta, records)
    _report(meta, records, builds, args.json, run_dir)

def _pods_from_meta(meta, idx):
    fixed, pool = dk.seat_plan(meta.get("opp") or [])
    return runner.Pods(fixed, pool, meta.get("fixed_pod"), idx=idx)

def cmd_resume(args):
    """Finish a cut-off harness run (replaying unfinished games from their seeds) and/or add --trials more games to it."""
    run_dir = args.resume
    meta = json.load(open(os.path.join(run_dir, "meta.json"), encoding="utf-8"))
    if meta.get("engine") != "harness": sys.exit("fishpond: --resume needs a harness run (the cli engine chains games and can't resume)")
    plan = runner.load_plan(run_dir)
    if plan is None: sys.exit(f"fishpond: {run_dir} has no plan.json (made before resume support); start a new run")
    idx = forge.index()
    builds, pods = _builds_from_meta(meta), _pods_from_meta(meta, idx)
    records, missing = runner.collect(run_dir, plan, builds, pods, meta.get("hero_ai", "Default"), meta.get("opp_ai", ["Default"] * 3))
    new = []
    if args.trials:
        first_game, first_id = max(e["game"] for e in plan) + 1, max(e["id"] for e in plan) + 1
        new = runner.plan_harness(builds, pods, first_game, args.trials, meta["seed"], meta["cap"], meta.get("timeout", args.timeout or 1800), run_dir,
                                  meta.get("hero_ai", "Default"), meta.get("opp_ai", ["Default"] * 3), meta.get("sim", "hybrid"),
                                  meta.get("opp_sim", "hybrid"), meta.get("key") or [], first_id)
        plan += new
        runner.save_plan(run_dir, plan)
    games_done = len({(r["build"], r["game"]) for r in records})
    print(f"fishpond: {run_dir}: {games_done} game(s) finished, {len(missing)} unfinished to replay, {len(new)} new", file=sys.stderr)
    todo = missing + new
    import glob
    session = f"s{len({os.path.basename(f).split('_')[1] for f in glob.glob(os.path.join(run_dir, 'logs', 'plan_*_*.tsv'))}) + 1}"
    full = "full" in (meta.get("sim"), meta.get("opp_sim"))
    wall = runner.execute(todo, args.jobs or runner.default_jobs(full), run_dir, session, args.quiet)
    records, missing = runner.collect(run_dir, plan, builds, pods, meta.get("hero_ai", "Default"), meta.get("opp_ai", ["Default"] * 3))
    meta.update(wall=meta.get("wall", 0) + wall, trials=len({e["game"] for e in plan}), complete=not missing,
                jobs=args.jobs or runner.default_jobs(full))
    runner.save(run_dir, meta, records)
    _report(meta, records, builds, args.json, run_dir)

def _rel(p):
    r = os.path.relpath(os.path.abspath(p), dk.REPO)
    return os.path.abspath(p) if r.startswith("..") else r

def _keys(hero):
    out = []
    for v in (hero.meta.get("key") or "").replace(" + ", ";").split(";"):
        v = v.strip()
        if not v: continue
        import mtg
        c, _ = mtg.find(v)
        out.append(c["name"] if c else v)
    return out

def _report(meta, records, builds, as_json, run_dir):
    by = [(label, [r for r in records if r["build"] == label], deck) for label, deck in builds]
    if as_json:
        from . import metrics as mx
        import sim_report as sr
        out = {"meta": meta, "builds": {}}
        for label, recs, deck in by:
            groups = rp.groups_for(meta.get("track"), meta.get("extra_track"), meta.get("key") or [], deck)
            sm = sr.summary(mx.bundle(recs, meta["turns"], groups, [deck.forge.get(c, c) for c in deck.commanders], produced=deck.produced, identity=deck.identity), groups)
            ex = mx.extras(recs, deck, meta["turns"])
            out["builds"][label] = {"summary": sm, "results": dict(ex["results"]), "routes": dict(ex["routes"]),
                                    "losses": dict(ex["losses"]), "tags": dict(ex["tags"]), "order": ex["order"],
                                    "cast_share": {c: round(k / ex["n"], 3) for c, k in ex["cast_games"].most_common()}}
        print(json.dumps(out, indent=1, default=str)); return
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rp.print_all(meta, by)
    text = buf.getvalue()
    print(text, end="")
    with open(os.path.join(run_dir, "report.txt"), "w", encoding="utf-8") as fh: fh.write(text)

def _builds_from_meta(meta):
    idx = forge.index()
    hero = dk.load(os.path.join(dk.REPO, meta["deck"]) if not os.path.isabs(meta["deck"]) else meta["deck"], "hero", idx=idx,
                   commander=meta.get("commander_opt"))
    builds = [("base", hero)]
    for v in meta.get("variants") or []:
        label, _, swaps = v.rpartition("|")
        pairs = [tuple(x.strip() for x in s.split("=>")) for s in swaps.split(";") if "=>" in s]
        builds.append((label or f"variant {len(builds)}", dk.swapped(hero, pairs, idx=idx)[0]))
    return builds

def _block(blocks, r):
    """The log block of record r: by position (cli) or by the harness's game id."""
    if "log_id" not in r: return blocks[r["log_game"]]
    for b in blocks:
        if any(l.startswith("#FP-END ") and json.loads(l[8:]).get("id") == r["log_id"] for l in b): return b
    sys.exit(f"fishpond: game id {r['log_id']} not found in {r['log']}")

def reparse(run_dir, meta, records, builds):
    """Re-run the log parser over a saved run's logs (after a parser fix); updates games.jsonl."""
    from . import logparse as lp
    heroes = dict(builds)
    pods = runner.Pods([], None, idx=forge.index())
    logs = {}
    for r in records:
        opps = [pods.deck("dummy", None) if p["kind"] == "dummy" else pods.deck("deck", os.path.join(dk.REPO, p["path"])) for p in r["pod"]]
        seats = runner.seat_objs(heroes[r["build"]], opps)
        if r["log"] not in logs:
            logs[r["log"]] = lp.split_games(open(os.path.join(run_dir, r["log"]), encoding="utf-8", errors="replace").read())
        keys = ("v", "engine", "forge", "build", "game", "chunk", "seed", "pos", "pod", "hero_ai", "log", "log_game", "log_id", "snaps", "stop", "end",
                "tutors", "sim")
        keep = {k: r[k] for k in keys if k in r}
        block = _block(logs[keep["log"]], keep)
        r.clear(); r.update(lp.parse_game([l for l in block if not l.startswith("#FP")], seats)); r.update(keep)
        if r.get("engine") == "harness" and r.get("stop") not in ("natural", "hero_lost") and r["result"] != "loss": r["result"], r["route"] = "draw", None
        if r.get("engine") == "harness": r["stopped"] = r.get("stop") == "timeout"
    runner.save(run_dir, meta, records)

def cmd_report(args):
    meta, records = runner.load_run(args.run)
    if args.turns: meta["turns"] = args.turns
    builds = _builds_from_meta(meta)
    plan = runner.load_plan(args.run)
    if plan is not None and not meta.get("complete", True):
        records, missing = runner.collect(args.run, plan, builds, _pods_from_meta(meta, forge.index()),
                                          meta.get("hero_ai", "Default"), meta.get("opp_ai", ["Default"] * 3))
        print(f"PARTIAL RUN: {len(plan) - len(missing)} of {len(plan)} planned games finished so far. Finish it with: "
              f"python3 -m fishpond run --resume {args.run}\n")
        if not records: return
    if args.reparse: reparse(args.run, meta, records, builds)
    _report(meta, records, builds, args.json, args.run)

def cmd_show(args):
    meta, records = runner.load_run(args.run)
    recs = [r for r in records if r["build"] == (args.build or "base")]
    if not 0 <= args.game < len(recs): sys.exit(f"fishpond: game {args.game} not in this run (0-{len(recs) - 1})")
    r = recs[args.game]
    brief = {k: r[k] for k in ("result", "route", "loss", "end_t", "hero_turns", "order", "kept", "deaths", "cmd_casts",
                               "cmd_resolved", "tags", "seed", "chunk", "pos", "ms", "stop") if k in r}
    print(json.dumps(brief, indent=1, default=str))
    print("pod: " + " | ".join(f"seat {p['seat']} {p['deck']}" for p in r["pod"]))
    for t in r["turns"]:
        print(f"T{t['t']}: lands {t['lands']} | casts {', '.join(t['casts']) or '-'} | trig {t['trig']} act {t['act']} | "
              f"attackers {t['atk']} | dmg {t['dmg']} (combat {t['cdmg']}) | life {t['life']} | opps dead {t['dead']}"
              + (" | cmdr out" if t.get("cmd_out") else ""))
        sn = (r.get("snaps") or {}).get(str(t["t"])) or {}
        if sn.get("main"): print(f"    main phase: lands {sn['main']['lands']} | mana {sn['main']['mana']} ({sn['main']['producible'] or '-'}) | hand {sn['main']['hand']}")
        if sn.get("end"): print(f"    end of turn: hand {sn['end']['hand']} | library {sn['end']['lib']} | graveyard {sn['end']['gy']} | "
                                f"creatures {sn['end']['creatures']} (power {sn['end']['power']}) | drawn this turn {sn['end']['drawn']}")
    if args.log:
        from . import logparse as lp
        blocks = lp.split_games(open(os.path.join(args.run, r["log"]), encoding="utf-8", errors="replace").read())
        lines = [l for l in _block(blocks, r) if not l.startswith("#FP-SNAP")]
        if not args.phases: lines = [l for l in lines if not l.startswith(("Phase:", "Mana:"))]
        print("\n".join(lines))

def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m fishpond", description="Fishpond: Commander decks played on Forge (docs/FISHPOND.md)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup"); s.add_argument("--jdk", action="store_true", help="also install javac (harness)")
    d = sub.add_parser("deck"); d.add_argument("deck"); d.add_argument("--opp", action="append"); d.add_argument("--opp-set")
    d.add_argument("--commander")
    v = sub.add_parser("save"); v.add_argument("deck"); v.add_argument("--name", required=True); v.add_argument("--commander")
    r = sub.add_parser("run")
    r.add_argument("deck", nargs="?")
    r.add_argument("--resume", metavar="RUN_DIR", help="finish a cut-off harness run and/or add --trials more games to it")
    r.add_argument("--trials", "--games", type=int, default=None); r.add_argument("--seed", type=int, default=1)
    r.add_argument("--turns", type=int, default=10); r.add_argument("--opp", action="append"); r.add_argument("--opp-set")
    r.add_argument("--fixed-pod", action="store_true"); r.add_argument("--ai", default="Default"); r.add_argument("--opp-ai")
    r.add_argument("--sim", choices=runner.SIM_MODES, default="hybrid"); r.add_argument("--opp-sim", choices=runner.SIM_MODES, default="hybrid")
    r.add_argument("--track", action="append", default=[]); r.add_argument("--variant", action="append", default=[])
    r.add_argument("--commander"); r.add_argument("--clock", type=int, default=120); r.add_argument("--jobs", type=int, default=0)
    r.add_argument("--engine", choices=["auto", "harness", "cli"], default="auto"); r.add_argument("--cap", type=int, default=20)
    r.add_argument("--timeout", type=int, default=None, help="per-game wall-clock limit in seconds (default 1800; 7200 with full lookahead)"); r.add_argument("--out"); r.add_argument("--json", action="store_true")
    r.add_argument("--quiet", action="store_true")
    p = sub.add_parser("report"); p.add_argument("run"); p.add_argument("--turns", type=int, default=0); p.add_argument("--json", action="store_true")
    p.add_argument("--reparse", action="store_true", help="re-run the log parser over the saved logs first")
    w = sub.add_parser("show"); w.add_argument("run"); w.add_argument("game", type=int); w.add_argument("--build")
    w.add_argument("--log", action="store_true"); w.add_argument("--phases", action="store_true")
    args = ap.parse_args(argv)
    if not args.cmd: ap.print_help(); return
    {"setup": cmd_setup, "deck": cmd_deck, "save": cmd_save, "run": cmd_run, "report": cmd_report, "show": cmd_show}[args.cmd](args)
