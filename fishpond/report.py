"""Fishpond report: goldfish's layout (scripts/sim_report.py) first, then Fishpond's own sections."""
import os, re, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import sim_report as sr  # noqa: E402
from . import metrics as mx  # noqa: E402

PILOT_ERRORS = {"surge_trap", "oracle_trap"}      # tags that mark a pilot decision, not the deck or the rules
DEATH_LABELS = {"decked": "drew from an empty library", "life": "life total reached 0", "poison": "poison",
                "commander damage": "commander damage", "conceded": "conceded", "opponent alternate win": "an opponent's alternate win",
                "spell effect": "a spell's lose-the-game effect", "unknown": "unknown"}

def pct(v): return sr.pct(v).strip()
def share(k, n): return pct(k / n) if n else "-"
def ci(k, n):
    lo, hi = sr.ci95(k, n)
    return f"95% CI {100 * lo:.0f}-{100 * hi:.0f}%"

def pod_line(records, engine="harness"):
    pods = Counter(" | ".join(f"seat {p['seat']} {p['deck']}" + (f" (B{p['bracket']})" if p.get("bracket") else "") +
                              (f" [{p['ai']}]" if p.get("ai") and p["ai"] != "Default" else "") for p in r["pod"]) for r in records)
    if len(pods) == 1: return "pod: " + next(iter(pods))
    return f"pods ({len(pods)} different seat orders/lineups, sampled per {'game' if engine == 'harness' else 'chunk of 5'}): " + "; ".join(f"{k} ×{v}" for k, v in pods.most_common(4)) + ("; ..." if len(pods) > 4 else "")

def mode_of(records):
    kinds = {p["kind"] for r in records for p in r["pod"]}
    if kinds == {"dummy"}: return "vacuum: 3 dummies"
    if "dummy" in kinds: return "mixed pod: real decks + dummies"
    return "real pod: 3 opponent decks"

def groups_for(meta_track, extra_track, key, hero):
    groups, seen = [], set()
    for t in list(dict.fromkeys(list(meta_track or []) + list(extra_track or []))):
        label, sep, rx = t.partition("=")
        if not sep: label, rx = t, "^" + re.escape(t) + "$"
        try: groups.append((label, re.compile(rx, re.I)))
        except re.error as ex: sys.exit(f"fishpond: --track {t!r}: bad pattern ({ex})")
    for k in key:
        ln = hero.forge.get(k, k)
        if not any(rx.search(ln) for _, rx in groups) and k in hero.names():
            groups.append((k, re.compile("^" + re.escape(ln) + "$")))
    return groups

def print_header(meta, records, ex):
    n = ex["n"]
    print(f"=== FISHPOND: {meta['commander']} | {meta['cards']} cards | {n} games | {mode_of(records)} | Forge {meta['forge']} | "
          f"engine {meta['engine']} | seed {meta['seed']} ===")
    sim = f", lookahead {meta.get('sim', 'off')}" if meta.get("engine") == "harness" else ", no lookahead (cli engine)"
    osim = f"; real opponents' lookahead {meta.get('opp_sim', 'off')}" if any(p["kind"] != "dummy" for r_ in records for p in r_["pod"]) else ""
    print(pod_line(records, meta.get("engine", "harness")) + f"  (you: seat 1, AI {meta.get('hero_ai', 'Default')}{sim}{osim}; every player at 40 life)")
    if meta.get("engine") == "harness" and meta.get("sim", "off") != "off":
        pt = sum((r_.get("end") or {}).get("sim_paused_turns", 0) for r_ in records)
        pg = sum(1 for r_ in records if (r_.get("end") or {}).get("sim_pauses"))
        fb = sum(1 for r_ in records if (r_.get("end") or {}).get("sim_fallback"))
        ht = sum(r_.get("hero_turns", 0) for r_ in records)
        why = {}
        for r_ in records:
            for k, v in ((r_.get("end") or {}).get("sim_pause_why") or {}).items(): why[k] = why.get(k, 0) + v
        labels = {"prepared": "a prepared card on the battlefield, #1",      # older runs also paused for #2 (now patched)
                  "eliminated_owner": "an eliminated player's leftover object, #2", "eliminated_in_combat": "a combat naming an eliminated player, #2",
                  "stale_combat_card": "a combat holding a card that has moved, #2"}
        whys = "; ".join(f"{labels.get(k, k)}: {v}" for k, v in sorted(why.items())) or "Forge states its lookahead can't copy"
        dfb = sum((r_.get("end") or {}).get("sim_decision_fallbacks", 0) for r_ in records)
        dfg = sum(1 for r_ in records if (r_.get("end") or {}).get("sim_decision_fallbacks"))
        print(f"lookahead: paused in {pg} game(s), {pt} of {ht} of your turns ({whys}; docs/FORGE_ISSUES.md); "
              f"{dfb} decision(s) in {dfg} game(s) remade without lookahead after Forge's search threw; "
              f"{fb} game(s) replayed without lookahead after a crash in Forge's simulation code")
        kinds = {}
        for r_ in records:
            for d in (r_.get("end") or {}).get("sim_decision_log") or []:
                at = (d.get("at") or "").split(" < ")
                key = (d.get("exc", "").split(":")[0].split(".")[-1] + " at " + (at[0] if at else "?"))
                k = kinds.setdefault(key, {"n": 0, "seats": {}, "ex": d, "game": r_.get("game")})
                k["n"] += 1; k["seats"][d.get("seat", "?")] = k["seats"].get(d.get("seat", "?"), 0) + 1
        for key, k in sorted(kinds.items(), key=lambda x: -x[1]["n"]):
            eg = k["ex"]
            seats = ", ".join(f"{s.split('-', 1)[-1]} {n}" for s, n in k["seats"].items())
            print(f"  search fallback x{k['n']} ({seats}): {key}; e.g. game {k['game']} table turn {eg.get('t')} {eg.get('phase')}, "
                  f"stack [{eg.get('stack') or 'empty'}], played {eg.get('played')}")
    gm = [m / 1000 for m in ex["game_ms"] if m]
    if gm:
        print(f"game time (one CPU per game): median {sr.q(gm, .5):.0f}s, P90 {sr.q(gm, .9):.0f}s, max {max(gm):.0f}s; "
              f"{len(gm)} games = {sum(gm) / 60:.0f} CPU-minutes, {meta.get('wall', 0) / 60:.1f} min wall on {meta.get('jobs', 1)} worker(s)")
    r = ex["results"]
    w, l, d = r.get("win", 0), r.get("loss", 0), r.get("draw", 0)
    print(f"results: won {w} ({share(w, n)}, {ci(w, n)}) | lost {l} ({share(l, n)}) | unfinished {d} ({share(d, n)}"
          + (": " + ", ".join(f"{k} {v}" for k, v in ex["draws"].items()) if d else "") + ")")
    if ex["routes"]: print("wins by route: " + " | ".join(f"{k} {v}" for k, v in ex["routes"].most_common()))
    if ex["losses"]: print("losses by reason: " + " | ".join(f"{k} {v}" for k, v in ex["losses"].most_common()))
    dl = Counter(r_["loss"].get("last_cast") or "-" for r_ in records if r_["result"] == "loss" and r_["loss"]["why"] == "decked")
    if dl: print("decked after casting (your last spell before the loss): " + " | ".join(f"{k} {v}" for k, v in dl.most_common(6)))
    wt = sorted(r_["end_t"] for r_ in records if r_["result"] == "win")
    lt = sorted(r_["loss"]["t"] for r_ in records if r_["result"] == "loss")
    if wt or lt:
        print("game length in your turns: " + (f"wins P10 T{sr.q(wt, .1)} / median T{sr.q(wt, .5)} / P90 T{sr.q(wt, .9)}" if wt else "no wins")
              + (f" | losses P10 T{sr.q(lt, .1)} / median T{sr.q(lt, .5)} / P90 T{sr.q(lt, .9)}" if lt else ""))
    mg = [r_.get("mulligans", 0) for r_ in records]
    if mg:
        ks = Counter(r_.get("kept") or 7 for r_ in records)
        print(f"mulligans: took at least one in {share(sum(1 for x in mg if x), n)} of games (the first is free in multiplayer, rule "
              f"103.5c; Forge's own keep logic); kept " + ", ".join(f"{k}: {share(v, n)}" for k, v in sorted(ks.items(), reverse=True)))
    order = ex["order"]
    if order:
        print("turn order: " + " | ".join(f"{('1st', '2nd', '3rd', '4th')[o - 1]} {v[0]} games (won {share(v[1], v[0])})"
                                          for o, v in sorted(order.items())))
    tags = ex["tags"]
    if tags:
        print("pilot tags: " + " | ".join(f"{k} {v}" for k, v in tags.most_common())
              + "  (self_decked = you drew from an empty library; surge_trap = decked in the turn Primal Surge resolved: the AI "
                "takes every optional put until the library is empty; oracle_trap = an empty-library win card was cast while draw "
                "triggers decked you first. Tagged losses are pilot decisions inside real rules, not rules errors)")
    pilot = sum(1 for r_ in records if r_["result"] == "loss" and set(r_.get("tags", [])) & PILOT_ERRORS)
    if pilot:
        rest = n - pilot
        print(f"excluding {pilot} loss(es) tagged as pilot errors ({', '.join(sorted(PILOT_ERRORS))}): won {w} of {rest} "
              f"({share(w, rest)}, {ci(w, rest)})" + (f". {share(pilot, l)} of losses are pilot errors: the deck is pilot-sensitive, "
              "read the headline win rate as a floor" if l and pilot / l > 0.2 else ""))
    to = [r_.get("ai_timeouts", 0) for r_ in records]
    if any(to):
        print(f"WARNING: Forge's AI gave up on {sum(to)} decision(s) after its 5 s limit in {sum(1 for x in to if x)} game(s): those "
              "games depend on machine load and won't replay exactly (the harness raises the limit; the cli engine can't)")
    if ex["dummy"]:
        print(f"WARNING: dummies acted in {len(ex['dummy'])} game(s), e.g. game {ex['dummy'][0][0]}: {ex['dummy'][0][1][:3]}. "
              "A dummy must never cast; check the dummy deck.")
    elif "dummy" in {p["kind"] for r_ in records for p in r_["pod"]}:
        print("dummies: never cast or attacked (checked every game)")

def print_opponents(label, records):
    """Real-opponent pods: who won the pod, and per opponent deck how the user's deck did against it."""
    if all(p["kind"] == "dummy" for r in records for p in r["pod"]): return
    n = len(records)
    seat_deck = lambda r, k: next((p["deck"] for p in r["pod"] if p["seat"] == k), "?")
    win = Counter("you" if r.get("winner") == 1 else seat_deck(r, r["winner"]) if r.get("winner") else "nobody (cap or clock)" for r in records)
    print(f"\n## {label}: opponents (real decks play on after you die, so the pod winner is known when one emerged)")
    print("pod won by: " + " | ".join(f"{k} {v} ({share(v, n)})" for k, v in win.most_common()))
    decks = sorted({p["deck"] for r in records for p in r["pod"] if p["kind"] != "dummy"})
    rows = []
    for d in decks:
        rs = [r for r in records if any(p["deck"] == d for p in r["pod"])]
        seats = lambda r: {p["seat"] for p in r["pod"] if p["deck"] == d}
        killed = sum(1 for r in rs if r["result"] == "loss" and r["loss"].get("by") in seats(r))
        killed_by_you = sum(1 for r in rs for x in r["deaths"] if x["seat"] in seats(r) and x["by"] == 1)
        won = sum(1 for r in rs if r.get("winner") in seats(r))
        bk = next((p.get("bracket") for r in rs for p in r["pod"] if p["deck"] == d), None)
        rows.append(f"{d}" + (f" (B{bk})" if bk else "") + f": in {len(rs)} games, you won {share(sum(1 for r in rs if r['result'] == 'win'), len(rs))}, "
                    f"it killed you {killed}, you killed it {killed_by_you}, it won the pod {won}")
    print("by opponent deck: " + " | ".join(rows))
    how = Counter(f"{r['loss']['route']}" + (f" ({seat_deck(r, r['loss']['by'])})" if r["loss"].get("by") not in (None, 1) else "")
                  for r in records if r["result"] == "loss")
    if how: print("how you died: " + " | ".join(f"{k} {v}" for k, v in how.most_common(8)))
    src = Counter(r["loss"]["src"] for r in records if r["result"] == "loss" and r["loss"].get("by") not in (None, 1) and r["loss"].get("src"))
    if src: print("killing blow (biggest share of the final life change): " + " | ".join(f"{k} {v}" for k, v in src.most_common(8)))

def wincons(hero):
    """The hero's cards whose Oracle text can win the game outright (watch list for pilot blind spots)."""
    import mtg
    out = []
    for n in sorted(hero.names()):
        c = mtg.find(n)[0]
        if c and "win the game" in mtg.text_of(c).lower(): out.append(c["name"])
    return out

def print_cards(label, ex, hero, meta, T):
    n = ex["n"]
    print(f"\n## {label}: cards (share of games cast; median first cast turn; avg casts per game)")
    top = sorted(ex["cast_games"].items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    print("cast most: " + " | ".join(f"{c} {share(k, n)} T{sr.q(ex['cast_turn'][c], .5)} ×{ex['cast_n'][c] / n:.1f}" for c, k in top))
    keys = meta.get("key") or []
    if keys:
        L = lambda c: hero.forge.get(c, c)
        print("key cards: " + " | ".join(f"{c} cast {share(ex['cast_games'][L(c)], n)}" + (f" (median T{sr.q(ex['cast_turn'][L(c)], .5)})" if ex['cast_turn'][L(c)] else "")
                                         + (f", won {share(ex['win_with'][L(c)], ex['games_with'][L(c)])} of games it was cast or entered"
                                            if ex['games_with'][L(c)] else "") for c in keys))
    tu = ex.get("tutor") or {}
    if tu.get("games"):
        print(f"tutoring (your library searches that put a card into hand or play; avg per game): {tu['searches'] / n:.2f} searches "
              f"({tu['lands'] / n:.2f} for lands), {tu['digs'] / n:.2f} digs")
        if tu["nonland"]:
            print("  tutor targets (times fetched, avg per game): " + " | ".join(f"{c} {k / n:.2f}" for c, k in tu["nonland"].most_common(10)))
            top = sorted(tu["by_src"].items(), key=lambda kv: -sum(kv[1].values()))[:4]
            print("  by tutor: " + "; ".join(f"{src}: " + ", ".join(f"{c} {k}" for c, k in picks.most_common(4)) for src, picks in top))
        if meta.get("key"):
            print(f"  '# key:' cards fetched in {tu['key_picked']} of {tu['searches']} searches; {tu['key_left']} other searches happened "
                  "while a key card was still in the library (it may not have been a legal target for that tutor)")
    wc = wincons(hero)
    if wc:
        print("win-condition cards (Oracle text says 'win the game'): " + " | ".join(
            f"{c}: cast in {ex['cast_games'][hero.forge.get(c, c)]} games, won with it in "
            f"{sum(1 for r in ex.get('records', []) if r.get('route') and hero.forge.get(c, c) in r['route'])}" for c in wc))
    eh = ex.get("end_hand")
    if eh: print("left in hand when the game ended (share of games; dead-card candidates): "
                  + " | ".join(f"{c} {share(k, n)}" for c, k in eh.most_common(10) if k / n >= 0.1))
    never = sorted(c for c in hero.names() if not ({c, hero.forge.get(c, c)} | {f.strip() for f in c.split(" // ")}) & ex["seen"])
    if never: print(f"never cast, played or seen entering in {n} games ({len(never)}): " + "; ".join(never))
    ai = sorted(c for c, f in hero.flags.items() if "All" in f)
    print("Forge AI can't play well (card script AI:RemoveDeck:All): " + ("; ".join(ai) if ai else "none")
          + ". Numbers involving these cards are a floor.")
    if ex["trig"]:
        print("your triggers (avg per game): " + " | ".join(f"{c} {v / n:.2f}" for c, v in ex["trig"].most_common(10) if v / n >= 0.05))
    cc = ex["cmd_casts"]
    if cc: print(f"commander casts per game: avg {sr.mean(cc):.2f}, max {max(cc)} (recasts pay tax)")

def print_all(meta, builds, approx_notes=None):
    """builds: [(label, records, hero Deck)]."""
    T = meta["turns"]
    approx_notes = approx_notes if approx_notes is not None else (mx.APPROX_CLI if meta["engine"] == "cli" else mx.APPROX_HARNESS)
    summaries = []
    for i, (label, records, hero) in enumerate(builds):
        groups = groups_for(meta.get("track"), meta.get("extra_track"), meta.get("key") or [], hero)
        res = mx.bundle(records, T, groups, [hero.forge.get(c, c) for c in hero.commanders], produced=hero.produced, identity=hero.identity)
        ex = mx.extras(records, hero, T)
        ex["records"] = records
        sm = sr.summary(res, groups)
        if "hand" in res["rec"]:
            for t in sm["turns"]: sm["turns"][t]["hand"]["leq1"] = round(sr.mean([1 if h <= 1 else 0 for h in res["rec"]["hand"][t]]), 4)
        summaries.append((label, sm, ex))
        if i == 0: print_header(meta, records, ex)
        else:
            r = ex["results"]
            print(f"\n=== {label}: won {r.get('win', 0)} of {ex['n']} ({share(r.get('win', 0), ex['n'])}, {ci(r.get('win', 0), ex['n'])}) ===")
            if ex["routes"]: print("wins by route: " + " | ".join(f"{k} {v}" for k, v in ex["routes"].most_common()))
            if ex["losses"]: print("losses by reason: " + " | ".join(f"{k} {v}" for k, v in ex["losses"].most_common()))
        pod = mode_of(records)
        sr.print_report(label, sm, T, groups, approx=set(approx_notes),
                        dev_title="development (P10/median/P90 over games; your turns; lands at end of turn, mana/colors/cmdr out "
                                  "at the start of your main phase with this turn's land drop, the rest cumulative; ≈ = see notes)",
                        opp_n=3, start_life=40,
                        title=f"combat and damage (3 opponents at 40 life; {pod}; cumulative, end of your turn)",
                        tail=f"attacked on {res['atk_turns']:.1f} of your turns per game (T1-T{T}). Opponents dead counts every "
                             f"opponent death (by you or another seat). A game that ended before T{T} repeats its final state.",
                        death_labels=DEATH_LABELS)
        kb = ex["kills_by"]
        if kb: print("opponent deaths by killer: " + " | ".join(f"{k} {v}" for k, v in kb.most_common()))
        print_opponents(label, records)
        print_cards(label, ex, hero, meta, T)
    if len(summaries) > 1:
        extra = []
        def row(name, f): extra.append((name, [f(sm, ex) for _, sm, ex in summaries]))
        row("won", lambda sm, ex: share(ex["results"].get("win", 0), ex["n"]))
        row("lost: decked", lambda sm, ex: share(sum(v for k, v in ex["losses"].items() if k.startswith("decked")), ex["n"]))
        row("unfinished", lambda sm, ex: share(ex["results"].get("draw", 0), ex["n"]))
        sr.compare_table([(l, sm) for l, sm, _ in summaries], groups, T, title="Builds compared (same seeds and pods)", extra=extra)
    print("\nnotes:")
    for m, note in approx_notes.items(): print(f"  ≈ {note}")
    print(f"  pilot: Forge's AI plays every seat (decent at fair Magic, weak at combo sequencing). Read win rates with the loss "
          f"reasons and the AI-flag list; a win rate from {len(builds[0][1])} games is ±{50 * 1.96 / max(1, len(builds[0][1])) ** .5:.0f} pts at worst.")
    if meta["engine"] == "harness":
        print(f"  engine harness: every game is its own Forge match with its own seed (replayable alone); a game ends when the table "
              f"dies, when you've lost (with real opponents left it plays on for the pod result), or after your turn {meta.get('cap')} "
              "(unfinished: turn cap). Mulligans are Forge's own keep logic.")
    if meta["engine"] == "cli":
        print("  engine cli: Forge's stock sim, games chained in chunks of 5 per JVM (a game can't be replayed alone); "
              "when you die the other seats play on to the clock; mulligans are Forge's own keep logic.")
    total = sum(len(b[1]) for b in builds)
    print(f"  Forge {meta['forge']} | {total} games in {meta['wall']:.0f}s on {meta['jobs']} JVM(s) = {60 * total / max(1, meta['wall']):.1f} games/min "
          f"| seed {meta['seed']} | run saved in {meta['run_dir']} "
          f"(python3 -m fishpond show {meta['run_dir']} GAME --log)")
