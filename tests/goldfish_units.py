#!/usr/bin/env python3
"""Deterministic unit checks for goldfish.py mechanics (run by tests/smoke.py).

Each check builds an exact board state and asserts a number, so nothing here depends on the
shuffle, the RNG or the pilot's choices. Add one whenever a mechanic is added or a parse bug is fixed.

  python3 tests/goldfish_units.py            # prints failures + "units: all N passed"; exit 1 on failure
"""
import argparse, json, os, random, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.chdir(REPO)
import goldfish as g
import tutors as tu

NAMES = ["Klauth, Unrivaled Ancient", "Forest", "Mountain", "Sol Ring", "Llanowar Elves", "Nyxbloom Ancient",
         "Mana Reflection", "Vorinclex, Voice of Hunger", "Selvala, Heart of the Wilds", "Priest of Titania",
         "Goreclaw, Terror of Qal Sisma", "Shadow in the Warp", "Dragonspeaker Shaman", "Dracogenesis", "Omniscience",
         "Lathliss, Dragon Queen", "Deranged Hermit", "Young Pyromancer", "Awakening Zone", "Nature's Rhythm",
         "Unbounded Potential", "Return of the Wildspeaker", "Sire of Stagnation", "Kalitas, Bloodchief of Ghet",
         "Glen Elendra's Answer", "Syndicate Heavy", "Embercleave", "Valiant Changeling", "Frogmite", "Ghoultree",
         "Emerald Medallion", "Lightning Bolt", "Tolarian Terror", "Invasion of Ikoria // Zilortha, Apex of Ikoria",
         "Dragonstorm", "Tireless Tracker", "Chord of Calling", "Hamza, Guardian of Arashin"]

RAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(NAMES)}
ANYC = frozenset("RG")
K = {n: g.compile_card(RAW[n], ANYC) for n in NAMES}

def game(lands=(), perms=(), hand=(), lib=(), gy=()):
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([K[n] for n in ()] and [] or [n for n in NAMES if n != "Klauth, Unrivaled Ancient"],
                ["Klauth, Unrivaled Ancient"], args, [], K, ANYC)
    G = g.Game(sim, [K[n] for n in hand], [K[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3
    G.lands = [g.Perm(K[n]) for n in lands]
    G.perms = [g.Perm(K[n]) for n in perms]
    G.gy = [K[n] for n in gy]
    G._st = None
    return G

def free_units(G): return sum(1 for u in G.pool if not u[5])

def pool(**kw):
    G = game(**kw); G.build_pool(); return free_units(G)

def base_cost(G, name, zone="hand"):
    return min(o[0] + len(o[1]) for o in G.options(K[name], zone))

CHECKS = []
def check(name):
    def deco(fn): CHECKS.append((name, fn)); return fn
    return deco

# ---- mana
@check("Nyxbloom triples a land")
def _(): return pool(lands=["Forest"], perms=["Nyxbloom Ancient"]) == 3
@check("Nyxbloom triples Sol Ring (2 -> 6)")
def _(): return pool(perms=["Sol Ring", "Nyxbloom Ancient"]) == 6
@check("Mana Reflection x2 + Vorinclex +1 on one land = 3")
def _(): return pool(lands=["Forest"], perms=["Mana Reflection", "Vorinclex, Voice of Hunger"]) == 3
@check("Vorinclex adds to lands only, not dorks")
def _(): return pool(perms=["Llanowar Elves", "Vorinclex, Voice of Hunger"]) == 1
@check("Nyxbloom entering mid-turn rescales untapped lands")
def _():
    G = game(lands=["Forest", "Forest"]); G.build_pool(); G.enter(K["Nyxbloom Ancient"])
    return free_units(G) == 6
@check("Priest of Titania counts Elves (3 Elves -> 3)")
def _(): return pool(perms=["Priest of Titania", "Llanowar Elves", "Llanowar Elves"]) == 1 + 1 + 3
@check("Selvala makes X = greatest power (Nyxbloom 5 on board, tripled)")
def _():
    # Forest pays Selvala's {G}; Selvala's X (5) is tripled by Nyxbloom -> 15, plus the Forest's other 2
    return pool(lands=["Forest"], perms=["Selvala, Heart of the Wilds", "Nyxbloom Ancient"]) == 15 + 2

# ---- reducers and free casting
@check("Goreclaw: power>=4 creature costs 2 less, a 1-power one doesn't")
def _():
    a, b = game(), game(perms=["Goreclaw, Terror of Qal Sisma"])
    return base_cost(b, "Lathliss, Dragon Queen") == base_cost(a, "Lathliss, Dragon Queen") - 2 \
        and base_cost(b, "Llanowar Elves") == base_cost(a, "Llanowar Elves")
@check("Shadow in the Warp: first creature spell only")
def _():
    G = game(perms=["Shadow in the Warp"]); first = base_cost(G, "Deranged Hermit")
    G.tcast = (K["Llanowar Elves"],); second = base_cost(G, "Deranged Hermit")
    return first == second - 2
@check("Dragonspeaker Shaman reduces Dragons only")
def _():
    a, b = game(), game(perms=["Dragonspeaker Shaman"])
    return base_cost(b, "Lathliss, Dragon Queen") == base_cost(a, "Lathliss, Dragon Queen") - 2 \
        and base_cost(b, "Deranged Hermit") == base_cost(a, "Deranged Hermit")
@check("Dracogenesis casts a Dragon commander free (tax only)")
def _(): return base_cost(game(perms=["Dracogenesis"]), "Klauth, Unrivaled Ancient", "cmd") == 0
@check("Omniscience is hand-only (commander still costs full)")
def _():
    G = game(perms=["Omniscience"])
    return base_cost(G, "Klauth, Unrivaled Ancient", "cmd") == 7 and base_cost(G, "Deranged Hermit") == 0
@check("Affinity: Frogmite costs 2 less with two artifacts")
def _(): return base_cost(game(perms=["Sol Ring", "Emerald Medallion"]), "Frogmite") == 4 - 2
@check("Ghoultree counts creature cards in the graveyard only")
def _():
    G = game(gy=["Llanowar Elves", "Deranged Hermit", "Lightning Bolt"])
    return base_cost(G, "Ghoultree") == 8 - 2
@check("Tolarian Terror counts instants/sorceries in the graveyard")
def _(): return base_cost(game(gy=["Lightning Bolt", "Llanowar Elves"]), "Tolarian Terror") == 7 - 1
@check("Qualified self-reducers stay unread (Embercleave, Valiant Changeling, Hamza)")
def _(): return not any(K[n].self_red for n in ("Embercleave", "Valiant Changeling", "Hamza, Guardian of Arashin"))

# ---- tokens
@check("Deranged Hermit makes 4 Squirrel tokens")
def _():
    G = game(); G.enter(K["Deranged Hermit"])
    toks = [p for p in G.perms if p.k.token]
    return len(toks) == 4 and all("Squirrel" in p.k.subtypes for p in toks)
@check("tokens vanish when they leave (never reach the graveyard)")
def _():
    G = game(); G.enter(K["Deranged Hermit"])
    for p in [p for p in G.perms if p.k.token]: G.leave(p, "dies")
    return not any(c.token for c in G.gy) and len(G.perms) == 1
@check("Lathliss: nontoken Dragon makes a 5/5 Dragon token; the token doesn't retrigger")
def _():
    G = game(perms=["Lathliss, Dragon Queen"]); G.enter(K["Klauth, Unrivaled Ancient"])
    toks = [p for p in G.perms if p.k.token]
    return len(toks) == 1 and "Dragon" in toks[0].k.subtypes and toks[0].k.power == 5
@check("Young Pyromancer triggers on an instant (the 'an' filter reads)")
def _():
    G = game(perms=["Young Pyromancer"]); G.fire("cast", K["Lightning Bolt"])
    return sum(p.k.token for p in G.perms) == 1
@check("Eldrazi Spawn token's quoted ability is a sacrifice mana source")
def _():
    G = game(perms=["Awakening Zone"]); G.fire("upkeep")
    sp = [p for p in G.perms if p.k.token]
    return len(sp) == 1 and sp[0].k.units and sp[0].k.sac_mana
@check("guards: Kalitas/Glen Elendra make no tokens; Syndicate Heavy's 'if' trigger isn't fired")
def _():
    kinds = lambda k: {e[0] for e in g.all_fx(k)}
    return "token" not in kinds(K["Kalitas, Bloodchief of Ghet"]) and "token" not in kinds(K["Glen Elendra's Answer"]) \
        and not K["Syndicate Heavy"].trig
@check("Tireless Tracker: landfall investigates (Clue with a draw ability)")
def _():
    G = game(perms=["Tireless Tracker"]); G.land_enters(K["Forest"])
    clue = [p for p in G.perms if p.k.token]
    return len(clue) == 1 and any(e[0] == "draw" for a in clue[0].k.acts for e in a["fx"])

# ---- tutors, modal, opponents
@check("X-tutor finds only MV <= X (Nature's Rhythm X=2 can't get Nyxbloom)")
def _():
    G = game(lib=["Nyxbloom Ancient"]); G.do(K["Nature's Rhythm"].spell, K["Nature's Rhythm"], None, 2)
    H = game(lib=["Nyxbloom Ancient"]); H.do(K["Nature's Rhythm"].spell, K["Nature's Rhythm"], None, 7)
    return not G.perms and [p.k.name for p in H.perms] == ["Nyxbloom Ancient"]
@check("Dragonstorm reads its Dragon filter; Invasion of Ikoria reads non-Human")
def _():
    ds = [e for e in K["Dragonstorm"].spell if e[0] == "tutor"]
    inv = [e for e in K["Invasion of Ikoria // Zilortha, Apex of Ikoria"].etb if e[0] == "tutor"]
    return ds and not g.tutor_unread(ds[0][1]) and inv and "human" in inv[0][1].non_subs
@check("tutors.py: non-Human excludes Humans")
def _():
    t = tu.parse_target("a non-Human creature card", {})
    return not t.matches(RAW["Young Pyromancer"]) and t.matches(RAW["Llanowar Elves"])
@check("modal: best readable mode only (Unbounded Potential = proliferate; Wildspeaker = one draw)")
def _():
    return [e[0] for e in K["Unbounded Potential"].spell] == ["prolif"] \
        and [e[0] for e in K["Return of the Wildspeaker"].spell] == ["draw"]
@check("opponent landfall (~opp): Sire of Stagnation draws 2 per opponent turn")
def _():
    G = game(perms=["Sire of Stagnation"], lib=["Forest"] * 20); G.opponents()
    return len(G.hand) == 6
@check("filters: stray words aren't subtypes; real subtypes are")
def _():
    return not g.parse_filter("n instant or sorcery ")["sub"] and g.parse_filter("dragon ")["sub"] == {"Dragon"} \
        and g.parse_filter("elves ")["sub"] == {"Elf"}
@check("convoke is flagged, not silently ignored")
def _(): return K["Chord of Calling"].status == "partial"
@check("token cap stops runaway loops")
def _():
    G = game(); G.perms = [g.Perm(K["Llanowar Elves"]) for _ in range(g.TOKEN_CAP)]
    G.enter(K["Deranged Hermit"])
    return len(G.perms) == g.TOKEN_CAP + 1

def main():
    fails = 0
    for name, fn in CHECKS:
        try: ok = bool(fn())
        except Exception as e: ok = False; name += f" (raised {type(e).__name__}: {e})"
        if not ok: fails += 1; print("FAIL  " + name)
    print(f"units: all {len(CHECKS)} passed" if not fails else f"units: {fails} of {len(CHECKS)} failed")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
