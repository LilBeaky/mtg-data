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
OWN = os.path.join(REPO, "decks")
REAL = {1: HERO, 2: seat_from(os.path.join(OWN, "Ians_Yusri_Omni.txt"), 2, "opponent", "Yusri"),
        3: seat_from(os.path.join(OWN, "Ians_Zur_Wizardcycling.txt"), 3, "opponent", "Zur"), 4: seat_from(os.path.join(OWN, "Ians_Klauth_Dragons.txt"), 4, "opponent", "Klauth")}

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

# ---- pilot policy intel (fishpond/policy.py): pure functions, no Forge needed
from fishpond import policy as po  # noqa: E402
slide = {"name": "Astral Slide", "type_line": "Enchantment", "oracle_text": "Whenever a player cycles a card, you may exile target creature."}
steppe = {"name": "Secluded Steppe", "type_line": "Land", "oracle_text": "Cycling {W} ({W}, Discard this card: Draw a card.)", "colors": []}
step = {"name": "Step Through", "type_line": "Sorcery", "oracle_text": "Return two target creatures to their owners' hands.\nWizardcycling {2}", "colors": ["U"]}
bear = {"name": "Grizzly Bears", "type_line": "Creature — Bear", "oracle_text": "", "colors": ["G"]}
check("policy payoff from synergy tag", po.payoffs_of({"synergy-cycling", "cycle-ons-cycling-matters", "synergy-white"}), {"cycling"})
check("policy 'X matters' payoff", po.payoffs_of({"coin flips matter", "coin flip"}), {"coin flip"})
check("policy activated-only card", (po.activated_only({"oracle_text": "{1}: The next time you would draw a card this turn, you gain 5 life instead."}),
                                     po.activated_only(slide)), (True, False))
check("policy cycling enablers", [po.is_enabler("cycling", c, set()) for c in (steppe, step, bear)], [True, True, False])
check("policy typal enabler", po.is_enabler("typal-bear", bear, set()), True)
check("policy engine strength: specific beats broad", (po.strength(27, 100), po.strength(62, 100)), (1.0, 0.15))
check("policy roles from tags", po.roles_of(slide, {"protection", "repeatable crime"}), ["engine", "protection"])
check("policy roles from text", po.roles_of({"name": "x", "type_line": "Sorcery", "oracle_text": "Search your library for a card"}, set()), ["tutor"])
check("policy priority header", po.priority_list({"priority": ["Astral Slide > Step Through", "Necrodominance; Approach of the Second Sun"]}),
      ["Astral Slide", "Step Through", "Necrodominance", "Approach of the Second Sun"])
_s, _e = lp.harness_lines(['#FP-POLICY {"seat": 1, "gt": 9, "kind": "search", "src": "Zur the Enchanter", "pick": "Astral Slide", "forge": "Grasp of Fate", "layer": "engine", "mode": "policy", "top": []}',
                           '#FP-END {"id": 0, "seed": 1, "stop": "cap", "ms": 1, "hero_turns": 3, "global_turns": 12, "players": {}, "hand": [], "lib": 50}'])
check("policy log parsed", [(p["pick"], p["layer"]) for p in _e["policy_log"]], [("Astral Slide", "engine")])
_s, _e = lp.harness_lines(['#FP-LINE {"seat": "1", "commander": "Heliod, Sun-Crowned", "kind": "closer", "line": "Heliod + Triskelion", "avail": [8, 9], "did": [], "won": true}',
                           '#FP-END {"id": 0, "seed": 1, "stop": "natural", "ms": 1, "hero_turns": 3, "global_turns": 12, "players": {}, "hand": [], "lib": 50}'])
check("win-line audit parsed", [(x["line"], x["avail"], x["did"]) for x in _e["lines"]], [("Heliod + Triskelion", [8, 9], [])])
_s, _e = lp.harness_lines(['#FP-CASTPLAN {"deck": "Xyris, the Writhing Storm", "levels": [40, 3, 2, 0]}',
                           '#FP-END {"id": 0, "seed": 1, "stop": "natural", "ms": 1, "hero_turns": 3, "global_turns": 12, "players": {}, "hand": [], "lib": 50}'])
check("cast-plan counts parsed", _e["castplan"], [{"deck": "Xyris, the Writhing Storm", "levels": [40, 3, 2, 0]}])
import tempfile as _tf, json as _js
from fishpond import lines as _ln
with _tf.TemporaryDirectory() as _d:
    _run = os.path.join(_d, "V05_test"); os.makedirs(_run)
    with open(os.path.join(_run, "games.jsonl"), "w", encoding="utf-8") as _fh:
        for _g, (_av, _did, _won) in enumerate([([8, 9], [], True), ([5], [5], True), ([], [], False)]):
            _fh.write(_js.dumps({"game": _g, "lines": [{"seat": "1", "commander": "Heliod, Sun-Crowned", "kind": "closer",
                                                       "line": "Heliod + Triskelion", "avail": _av, "did": _did, "won": _won}]}) + chr(10))
    _a = _ln.tally([_d])[("Heliod, Sun-Crowned", "closer", "Heliod + Triskelion")]
check("win-line audit tally", (_a["games"], _a["avail_games"], _a["did_games"], _a["avail_turns"], _a["did_turns"], _a["won_did"], _a["misses"]),
      (3, 2, 1, 3, 1, 1, ["V05 g0 s1"]))
with _tf.TemporaryDirectory() as _d:
    _run = os.path.join(_d, "V05_test"); os.makedirs(_run)
    with open(os.path.join(_run, "games.jsonl"), "w", encoding="utf-8") as _fh:
        for _g, (_av, _won, _cf, _t) in enumerate([([8], True, 4, 9), ([], False, -1, 6), ([], False, 5, 7)]):
            _fh.write(_js.dumps({"game": _g, "lines": [
                {"seat": "1", "commander": "Heliod, Sun-Crowned", "kind": "closer", "line": "Heliod + Triskelion", "avail": _av, "did": [], "won": _won},
                {"seat": "1", "commander": "Heliod, Sun-Crowned", "kind": "reach", "line": "reach", "avail": [], "did": [], "won": _won,
                 "cmd_first": _cf, "turns": _t}]}) + chr(10))
    _r = _ln.reach([_d])["Heliod, Sun-Crowned"]
    _t = _ln.tally([_d])
check("reach: lines reached, commander out, turns", (_r["games"], _r["reached"], _r["reached_won"], _r["first"], _r["cmd_first"], _r["cmd_never"], _r["turns"]),
      (3, 1, 1, [8], [4, 5], 1, [9, 6, 7]))
check("reach records stay out of the line tally", sorted(k[1] for k in _t), ["closer"])

# ---- the game page (fishpond/gamepage.py): a two-seat game in a worker log, as the harness writes it
from fishpond import gamepage as _gp  # noqa: E402
import tempfile as _tf2
with _tf2.TemporaryDirectory() as _d2:
    os.makedirs(os.path.join(_d2, "logs"))
    _brd = lambda t, k1, k2: "#FP-BOARD " + _js.dumps({"t": t, "seats": {
        "1": {"life": 40, "out": False, "hand": 6, "lib": 90, "gy": 0, "poison": 0, "lands": t, "creatures": k1, "other": [],
              "cmd": [{"n": "Klauth, Unrivaled Ancient", "zone": "Battlefield" if k1 else "Command", "casts": 1 if k1 else 0}], "cmd_dmg": {}},
        "2": {"life": 40 - 7 * (t >= 3), "out": False, "hand": 7, "lib": 90, "gy": 1 * (t >= 2), "poison": 0, "lands": t, "creatures": k2,
              "other": [], "cmd": [{"n": "Zur the Enchanter", "zone": "Command", "casts": 1 * (t >= 2)}], "cmd_dmg": {}}}})
    _kl = [{"n": "Klauth, Unrivaled Ancient", "p": 7, "t": 7, "cmd": True}]
    open(os.path.join(_d2, "logs", "worker_s1_0.log"), "w", encoding="utf-8").write(chr(10).join([
        '#FP-PLAN {"t": 1, "seat": "Ai(1)-Klauth", "phase": "MAIN1", "budget": 1, "restricted": 0, "reserve": 0, "steps": [], "left_out": [{"card": "Klauth, Unrivaled Ancient", "cost": 7, "value": 1486}]}',
        _brd(1, [], []), _brd(2, [], [{"n": "Zur the Enchanter", "p": 1, "t": 4, "cmd": True}]), _brd(3, _kl, []),
        '#FP-MOVE {"t": 2, "seat": "2", "by": "2", "src": "Step Through", "trigger": false, "card": "Archaeomancer", "from": "Library", "to": "Hand"}',
        '#FP-MOVE {"t": 2, "seat": "2", "by": "2", "src": "Show and Tell", "trigger": false, "card": "Omniscience", "from": "Hand", "to": "Battlefield"}',
        '#FP-MOVE {"t": 2, "seat": "1", "by": "2", "src": "Show and Tell", "trigger": false, "card": "Ghalta, Primal Hunger", "from": "Hand", "to": "Battlefield"}',
        '#FP-WIPE {"t": 2, "seat": "Ai(2)-Zur", "card": "Cyclonic Rift", "self": 0, "opp": {}, "keeps": false, "verdict": "refuse: not enough"}',
        "Turn: Turn 1 (Ai(1)-Klauth)", "Land: Ai(1)-Klauth played Forest (5)",
        "Turn: Turn 2 (Ai(2)-Zur)", "Add To Stack: Ai(2)-Zur cast Zur the Enchanter", "Add To Stack: Ai(2)-Zur activated Step Through",
        "Add To Stack: Ai(2)-Zur cast Show and Tell",
        "Add To Stack: Ai(1)-Klauth cast Beast Within targeting [Zur the Enchanter (60)]",
        "Zone Change: Zur the Enchanter (60) was put into Graveyard from Battlefield.",
        "Turn: Turn 3 (Ai(1)-Klauth)", "Add To Stack: Ai(1)-Klauth cast Klauth, Unrivaled Ancient",
        "Combat: Ai(1)-Klauth assigned Klauth, Unrivaled Ancient (7) to attack Ai(2)-Zur.",
        "Damage: Klauth, Unrivaled Ancient (7) deals 7 combat damage to Ai(2)-Zur.", "Life: Life: Ai(2)-Zur 40 > 33",
        "Game Outcome: Ai(2)-Zur has lost because life total reached 0",
        '#FP-END ' + _js.dumps({"id": 0, "seed": 7, "stop": "natural", "global_turns": 3, "players": {
            "1": {"name": "Ai(1)-Klauth", "outcome": "has won because all opponents have lost", "life": 40},
            "2": {"name": "Ai(2)-Zur", "outcome": "has lost because life total reached 0", "life": 0}}})]) + chr(10))
    _gs = _gp.load_run(_d2)
    _g = _gs[0]
    check("game page: seats, winner, commander first cast on own turn 2", (_g["names"], _g["winner"], _g["stats"][1]["cmd_first"], _g["stats"][2]["cmd_first"]),
          ({1: "Klauth", 2: "Zur"}, 1, 2, 1))
    check("game page: removal names its card and caster", [m["text"] for m in _g["moments"] if m["kind"] == "removed"],
          ["Zur the Enchanter dies to Beast Within (Klauth)"])
    check("game page: a turn's plan, combat damage and end-of-turn board", (_g["rows"][0]["plan"]["budget"], _g["rows"][2]["dmg"], _g["rows"][2]["board"]["creatures"][0]["p"]),
          (1, {2: 7}, 7))
    check("game page: what a tutor found and what Show and Tell put out, on the play that did it", [it[2] for it in _g["rows"][1]["items"] if len(it) > 2],
          ["found Archaeomancer", "Omniscience onto the battlefield; Klauth: Ghalta, Primal Hunger onto the battlefield"])
    check("game page: seats in turn order", _g["order"], [1, 2])
    _col = _gp.deck_colors({"Klauth": ["Klauth, Unrivaled Ancient"], "Zur": ["Zur the Enchanter"]})
    check("game page: deck colors from color identity", (_col["Klauth"]["identity"], _col["Zur"]["identity"]), ("RG", "WUB"))
    check("game page: the page is written", os.path.basename(_gp.write(_d2) or ""), "games.html")
    _st = os.path.join(_d2, "study"); os.makedirs(_st)
    os.rename(os.path.join(_d2, "logs"), os.path.join(_st, "T01_pod", "logs") if os.makedirs(os.path.join(_st, "T01_pod")) is None else None)
    _ix = _gp.study_index(_st)
    _ixd = _js.loads(open(_ix, encoding="utf-8").read().split("const DATA = ")[1].split(";\nconst esc")[0].replace("<\\/", "</"))
    check("study index: decks pooled over pods, the pod's page written", (sorted(_ixd["decks"]), _ixd["decks"]["Klauth"]["wins"],
          _ixd["pods"][0]["pod"], os.path.exists(os.path.join(_st, "T01_pod", "games.html"))), (["Klauth", "Zur"], 1, "T01_pod", True))

for f in fails: print("FAIL", f)
print(f"units: {'all ' if not fails else ''}{count - len(fails)} of {count} passed" if fails else f"units: all {count} passed")
sys.exit(1 if fails else 0)
