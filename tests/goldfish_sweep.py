#!/usr/bin/env python3
"""Runtime crash net for goldfish.py (run by tests/smoke.py, ~35s).

Every Commander-legal card is compiled, then its parsed effects are executed in a small live game: it enters (or
resolves), each trigger, activated ability and loyalty ability runs once, then an upkeep, main phase, end step and a
combat. It asserts nothing about numbers (goldfish_units.py does that); it only proves no card's reading crashes the
simulator. A parser change that produces an effect the sim can't execute shows up here as a named card.

  python3 tests/goldfish_sweep.py          # prints "sweep: N cards, 0 errors" or the failing cards; exit 1 on errors
"""
import argparse, os, random, sys, traceback
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.chdir(REPO)
import mtg, goldfish as g

BASE = ["Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears", "Llanowar Elves", "Sol Ring", "Mulldrifter",
        "Lightning Bolt", "Craw Wurm"]

def main():
    idx = mtg.index()
    bk = {n: g.compile_card(idx[mtg.norm(n)], g.ALL5) for n in BASE}
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    seen, errs, ex, n = set(), Counter(), {}, 0
    for i, c in enumerate(mtg.cards()):
        if mtg.legal(c) != "legal" or c["name"] in seen: continue
        seen.add(c["name"]); n += 1
        try:
            k = g.compile_card(c, g.ALL5)
            cache = dict(bk); cache[c["name"]] = k
            sim = g.Sim([b for b in BASE if b != "Grizzly Bears"] + [c["name"]], ["Grizzly Bears"], args, [], cache, g.ALL5)
            G = g.Game(sim, [bk["Mulldrifter"], bk["Lightning Bolt"], bk["Forest"]], [bk[b] for b in BASE] * 3, random.Random(i))
            G.turn, G.phase, G.turns_left, G.cmd = 4, 3, 3, []
            G.lands = [g.Perm(bk[b]) for b in ("Forest", "Island", "Swamp", "Mountain", "Plains")]
            G.perms = [g.Perm(bk[b]) for b in ("Grizzly Bears", "Llanowar Elves", "Sol Ring")]
            G.gy = [bk["Craw Wurm"], bk["Mulldrifter"]]; G._st = None
            G.build_pool()
            if k.types & g.PERMANENT: p = G.land_enters(k) if k.is_land else G.enter(k)
            else: p = None; G.do(k.spell, k, None, 2)
            p = p if isinstance(p, g.Perm) else None
            for t in k.trig: G.do(t[2], k, p, 1)
            for a in k.acts: G.do(a["fx"], k, p, 1)
            for _, fx in k.pw: G.do(fx, k, p, 1)
            G.fire("upkeep"); G.fire("main1"); G.fire("end"); G.combat()
        except Exception as e:
            key = f"{type(e).__name__}: {str(e)[:70]}"
            errs[key] += 1
            ex.setdefault(key, (c["name"], traceback.format_exc().splitlines()[-3:]))
    for key, cnt in errs.most_common():
        print(f"FAIL  {cnt} x {key}  e.g. {ex[key][0]}\n      " + "\n      ".join(ex[key][1]))
    print(f"sweep: {n} cards, {sum(errs.values())} errors")
    sys.exit(1 if errs else 0)

if __name__ == "__main__":
    main()
