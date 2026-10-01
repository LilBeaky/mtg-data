#!/usr/bin/env python3
"""Parity harness for the GEF adapter (T3 step 2): every card in data/gef/ through the parser path and the GEF path.

  python3 tests/gef_parity.py [--trials N] [--turns T] [--seed S] [--show] [NAME ...]

Per card, two comparisons:
  structure  the compiled engine fields (spell, etb, trig, acts, statics, units, keywords, hold ...) of both paths;
  games      a probe deck (copies of the card, basics of its colors, vanilla filler) played on the same seeds through
             both paths; the per-game stats at the last turn (mana, casts, cards, damage, board, life ...) are compared.
Identical structure means identical games (the sim is deterministic per seed), so only differing cards are played.
Every card that differs needs a cause in tests/gef_parity_causes.json ({name: why}); the run fails (exit 1) on any
unexplained diff, and lists causes recorded for cards that no longer differ.
"""
import argparse, json, os, random, sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.chdir(REPO)
import mtg, goldfish as g, gef_compile as gc

CAUSES = os.path.join(REPO, "tests", "gef_parity_causes.json")
FIELDS = ("units", "convs", "spell", "etb", "castfx", "trig", "acts", "pw", "statics", "hand_acts", "gycast", "kw", "kwn", "equip",
          "attach", "etap", "kicker", "ctr_enter", "hold", "answer", "kill", "burn_blk", "pain", "labman", "no_untap", "addsac",
          "addlife", "sac_outlets", "life_per_mv", "sac_mana", "rebound", "cum_upkeep", "requires", "alpha", "ritual")
STATS = ("lands", "mana", "casts", "spent", "extra", "hand", "gy", "board", "dmg", "cdmg", "life", "kills", "recur", "cycled")
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
FILLER = [("Grizzly Bears", 26), ("Ornithopter", 12)]

def norm(v):
    """A comparable form of an engine value (Targets by description, filters and sets sorted)."""
    if isinstance(v, g.tu.Target): return "Target(" + v.describe() + (" ~" + ",".join(v.approx) if v.approx else "") + ")"
    if isinstance(v, dict): return "{" + ", ".join(f"{k}: {norm(x)}" for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))
                                                 if x not in (False, None, 0, (), frozenset(), set(), []) or k in ("type",)) + "}"
    if isinstance(v, (set, frozenset)): return "{" + ", ".join(sorted(map(norm, v))) + "}"
    if isinstance(v, (list, tuple)): return "(" + ", ".join(map(norm, v)) + ")"
    return repr(v)

def structure(k): return {f: norm(getattr(k, f)) for f in FIELDS}

def args_ns():
    return argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False, no_mulligan=True,
                              trace=0, disruption_trace="")

def probe(c, k, idx, trials, turns, seed, base):
    """Mean per-game stats at the last turn of a probe deck built around card k."""
    ci = c.get("color_identity") or []
    lands = [BASICS[x] for x in ci] or ["Wastes"]
    names = [c["name"]] * 12 + [lands[i % len(lands)] for i in range(38)] + [n for n, q in FILLER for _ in range(q)]
    anyc = frozenset(ci) or g.ALL5
    cache = {n: base.get((n, anyc)) or base.setdefault((n, anyc), g.compile_card(idx[mtg.norm(n)], anyc)) for n in set(names) - {c["name"]}}
    cache[c["name"]] = k
    sim = g.Sim(names, [], args_ns(), [], cache, anyc)
    res = sim.run(trials, turns, seed)
    return {m: round(sum(res["rec"][m][turns]) / max(1, len(res["rec"][m][turns])), 3) for m in STATS}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*"); ap.add_argument("--trials", type=int, default=12)
    ap.add_argument("--turns", type=int, default=8); ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--show", action="store_true", help="print the differing fields and stats of every differing card")
    a = ap.parse_args()
    gefs, rejects = gc.load()
    idx = mtg.index()
    causes = {k: v for k, v in (json.load(open(CAUSES, encoding="utf-8")) if os.path.exists(CAUSES) else {}).items() if not k.startswith("_")}
    todo = [mtg.norm(n) for n in a.names] if a.names else sorted(gefs)
    base, tally, unexplained, differ = {}, Counter(), [], set()
    for nm in todo:
        c = idx[nm]
        anyc = frozenset(c.get("color_identity") or []) or g.ALL5
        kp = g.compile_card(c, anyc)
        kg = gc.compile_gef(c, gefs[nm], anyc)
        sp, sg = structure(kp), structure(kg)
        fields = [f for f in FIELDS if sp[f] != sg[f]]
        if not fields: tally["same structure"] += 1; continue
        differ.add(c["name"])
        stp = probe(c, kp, idx, a.trials, a.turns, a.seed, base)
        stg = probe(c, kg, idx, a.trials, a.turns, a.seed, base)
        dstats = {m: (stp[m], stg[m]) for m in STATS if stp[m] != stg[m]}
        tally["different structure, same games" if not dstats else "different games"] += 1
        why = causes.get(c["name"])
        if not why: unexplained.append(c["name"])
        if a.show or (not why and a.names):
            print(f"\n{c['name']}  [{kp.status} -> {kg.status}]  {'cause: ' + why if why else 'UNEXPLAINED'}")
            for f in fields: print(f"   {f}:\n     parser {sp[f][:200]}\n     gef    {sg[f][:200]}")
            if dstats: print("   games (parser -> gef): " + ", ".join(f"{m} {x} -> {y}" for m, (x, y) in dstats.items()))
            for n_ in kg.notes:
                if n_.startswith("gef refused"): print("   " + n_[:150])
    stale = sorted(n for n in causes if n not in differ and mtg.norm(n) in todo)
    print(f"\nparity: {len(todo)} GEF cards; " + ", ".join(f"{k} {v}" for k, v in tally.items()))
    if rejects: print(f"  {len(rejects)} translations rejected by the validator (parser used): " + ", ".join(n for n, _ in rejects))
    if unexplained: print(f"  UNEXPLAINED ({len(unexplained)}): " + "; ".join(unexplained))
    if stale: print(f"  causes recorded for cards that no longer differ ({len(stale)}): " + "; ".join(stale))
    sys.exit(1 if unexplained else 0)

if __name__ == "__main__":
    main()
