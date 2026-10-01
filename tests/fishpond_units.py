#!/usr/bin/env python3
"""Offline checks for Fishpond's log parser (run by tests/smoke.py; Forge is not needed).

The fixtures in tests/fishpond/ are real Forge 2.0.15 game logs, trimmed of phase and mana lines:
  vacuum_win.log     Chulane vs 3 dummies (stock sim): combat win
  vacuum_decked.log  Chulane vs 3 dummies (stock sim): Primal Surge empties the library, a draw decks it; the dummies
                     play on to the wall clock
  real_pod.log       Chulane vs Yusri / Zur / Klauth (stock sim): Yusri's Aetherflux Reservoir kills seats 3 and 4,
                     then Yusri kills Chulane in combat
  harness_cap.log    Chulane vs 3 dummies (harness): stopped after hero turn 4 (--cap 4), with #FP snapshot and end lines

  python3 tests/fishpond_units.py     # prints failures + "units: all N passed"; exit 1 on failure
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "scripts"))
import mtg  # noqa: E402
from fishpond import logparse as lp  # noqa: E402

FIX = os.path.join(REPO, "tests", "fishpond")
fails, count = [], 0

def check(name, got, want):
    global count
    count += 1
    if got != want: fails.append(f"{name}: got {got!r}, want {want!r}")

def seat_from(path, k, kind, tag):
    names, cmds = set(), []
    for s, q, n in mtg.parse_deck(path):
        c = mtg.find(n)[0]
        if not c: continue
        names |= {c["name"]} | {f.strip() for f in c["name"].split(" // ")}
        if s in ("commander", "commanders"): cmds.append(c["name"])
    return lp.Seat(k, tag, kind, names, cmds)

HERO = seat_from(os.path.join(REPO, "tests", "forge", "chulane.txt"), 1, "hero", "Chulane")
DUMMY = lambda k: lp.Seat(k, "Dummy", "dummy", {"Isamaru, Hound of Konda", "Wastes"}, ["Isamaru, Hound of Konda"])
VAC = {1: HERO, 2: DUMMY(2), 3: DUMMY(3), 4: DUMMY(4)}
OWN = os.path.join(REPO, "fishpond", "opponents", "own")
REAL = {1: HERO, 2: seat_from(os.path.join(OWN, "yusri.txt"), 2, "opponent", "Yusri"),
        3: seat_from(os.path.join(OWN, "zur.txt"), 3, "opponent", "Zur"), 4: seat_from(os.path.join(OWN, "klauth.txt"), 4, "opponent", "Klauth")}

def load(name):
    return [l.rstrip("\n") for l in open(os.path.join(FIX, name), encoding="utf-8") if l.strip()]

# ---- vacuum win (log checked by hand: Chulane cast on hero turn 5 = global turn 17; seat 3 dies first)
r = lp.parse_game(load("vacuum_win.log"), VAC)
check("win result", (r["result"], r["route"], r["loss"]), ("win", "combat", None))
check("win order (hero took global turn 1)", r["order"], 1)
check("win commander resolved", r["cmd_resolved"], [5])
check("win first casts", [r["first_cast"].get(c) for c in ("Bloom Tender", "Esper Sentinel", "Shrieking Drake")], [2, 3, 4])
check("win deaths", [(d["seat"], d["t"], d["route"], d["by"]) for d in r["deaths"]], [(3, 11, "combat", 1), (2, 13, "combat", 1), (4, 15, "combat", 1)])
check("win damage per turn T1-T6", [t["dmg"] for t in r["turns"][:6]], [0, 0, 1, 2, 3, 5])
check("win end turn", r["end_t"], 15)
check("win dummies never acted", r["dummy_acts"], [])
check("win kept", r["kept"], 7)

# ---- decked in the Primal Surge turn, dummies play on to the clock
r = lp.parse_game(load("vacuum_decked.log"), VAC)
check("decked result", (r["result"], r["loss"]["why"], r["loss"]["t"]), ("loss", "decked", 9))
check("decked tags", sorted(r["tags"]), ["self_decked", "surge_trap"])
check("decked last cast", r["loss"]["last_cast"], "Primal Surge")
check("decked clock seen", r["stopped"], True)
check("decked order (hero 4th)", r["order"], 4)
check("decked opponents alive", r["deaths"], [])

# ---- real pod: Yusri's Aetherflux kills seats 3 and 4 (noncombat), then Chulane in combat
r = lp.parse_game(load("real_pod.log"), REAL)
check("real result", (r["result"], r["loss"]["why"], r["loss"]["route"], r["loss"]["by"]), ("loss", "life", "combat", 2))
check("real deaths", [(d["seat"], d["t"], d["route"], d["by"], d["src"]) for d in r["deaths"]],
      [(3, 4, "noncombat", 2, "Aetherflux Reservoir"), (4, 4, "noncombat", 2, "Aetherflux Reservoir")])
check("real loss turn", r["loss"]["t"], 5)
check("real killing blow = biggest share (Okaun's coin-flip doubled 12288)", r["loss"]["src"], "Okaun, Eye of Chaos")

# ---- harness: turn cap leaves every survivor marked a winner (a draw for us); snapshots and the end line parse
block = load("harness_cap.log")
snaps, end = lp.harness_lines(block)
r = lp.parse_game([l for l in block if not l.startswith("#FP")], VAC)
check("cap result", r["result"], "draw")
check("cap stop", end["stop"], "cap")
check("cap hero turns", (end["hero_turns"], r["hero_turns"]), (4, 4))
check("cap snapshots", (len(snaps), sorted(snaps["1"])), (4, ["end", "main"]))
check("cap end snapshot fields", all(k in snaps["4"]["end"] for k in ("lands", "hand", "gy", "life", "disc", "recur")), True)
check("cap T1 main phase is before the land drop", snaps["1"]["main"]["lands"], 0)
check("cap hand at the end", end["hand"], ['Drift of Phantasms', 'Silverback Elder', 'Whitemane Lion', 'Forest', 'Lotus Cobra'])
check("cap no deaths", r["deaths"], [])

# ---- outcome strings (Forge's en-US texts)
check("outcome alt win", lp.outcome_kind("has won due to effect of 'Thassa's Oracle'"), ("won", "alternate win", "Thassa's Oracle"))
check("outcome poison", lp.outcome_kind("has lost because of obtaining 10 poison counters")[1], "poison")
check("outcome generals", lp.outcome_kind("has lost due to accumulation of 21 damage from generals")[1], "commander damage")
check("outcome opp alt", lp.outcome_kind("has lost because an opponent has won by spell 'Approach of the Second Sun'"),
      ("lost", "opponent alternate win", "Approach of the Second Sun"))

for f in fails: print("FAIL", f)
print(f"units: {'all ' if not fails else ''}{count - len(fails)} of {count} passed" if fails else f"units: all {count} passed")
sys.exit(1 if fails else 0)
