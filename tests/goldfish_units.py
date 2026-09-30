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

# ---- combat (opponents have no boards in real runs; the blocker checks set one by hand)
CNAMES = ["Najeela, the Blade-Blossom", "Forest", "Mountain", "Grizzly Bears", "Serra Angel", "Baneslayer Angel",
          "Boros Swiftblade", "Vampire Nighthawk", "Glistener Elf", "Bloated Contaminator", "Hero of Bladehold",
          "Glorious Anthem", "Bonesplitter", "Impact Tremors", "Blood Artist", "Guttersnipe", "Lightning Bolt",
          "Sword of Fire and Ice", "Purphoros, God of the Forge", "Crusader of Odric", "Overrun", "Rafiq of the Many",
          "Exsanguinate", "Llanowar Elves", "Professional Face-Breaker", "Invisible Stalker", "Craterhoof Behemoth",
          "Goblin Rabblemaster", "Ophidian", "Intangible Virtue", "Monastery Swiftspear", "Opt", "Relentless Assault",
          "Aurelia, the Warleader", "Karlach, Fury of Avernus", "Moraug, Fury of Akoum", "Hellrider", "Plains", "Island", "Swamp",
          "Castle Garenbrig", "Encroaching Dragonstorm", "Lathliss, Dragon Queen", "Biorhythm", "Jeska's Will", "Animist's Awakening"]
CRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(CNAMES)}
CK = {n: g.compile_card(CRAW[n], g.ALL5) for n in CNAMES}

def cgame(perms=(), lands=(), hand=(), lib=("Forest",) * 10):
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in CNAMES if n != "Najeela, the Blade-Blossom"], ["Najeela, the Blade-Blossom"], args, [], CK, g.ALL5)
    G = g.Game(sim, [CK[n] for n in hand], [CK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3
    G.lands = [g.Perm(CK[n]) for n in lands]
    G.perms = [g.Perm(CK[n]) for n in perms]
    G._st = None
    return G

def lives(G): return [o["life"] for o in G.opps]
def blocker(p, t, *kw): return {"name": f"{p}/{t}", "p": p, "t": t, "kw": set(kw)}

@check("combat keywords read (Baneslayer, Glistener infect, Contaminator toxic 1 + trample)")
def _():
    return {"flying", "first strike", "lifelink"} <= CK["Baneslayer Angel"].kw and "infect" in CK["Glistener Elf"].kw \
        and CK["Bloated Contaminator"].kwn.get("toxic") == 1 and "trample" in CK["Bloated Contaminator"].kw
@check("unblocked attack: Grizzly Bears deals 2 to one opponent")
def _():
    G = cgame(perms=["Grizzly Bears"]); G.combat()
    return sorted(lives(G)) == [38, 40, 40] and G.dmg == 2 and G.cdmg == 2
@check("summoning-sick creature doesn't attack; haste does (Swiftspear)")
def _():
    G = cgame(); G.enter(CK["Grizzly Bears"]); G.enter(CK["Monastery Swiftspear"]); G.combat()
    return G.dmg == 1
@check("double strike deals damage twice (Boros Swiftblade: 2)")
def _():
    G = cgame(perms=["Boros Swiftblade"]); G.combat(); return G.dmg == 2
@check("lifelink gains you life (Vampire Nighthawk: 42)")
def _():
    G = cgame(perms=["Vampire Nighthawk"]); G.combat(); return G.life == 42
@check("infect deals poison, not life loss")
def _():
    G = cgame(perms=["Glistener Elf"]); G.combat()
    return lives(G) == [40, 40, 40] and max(o["poison"] for o in G.opps) == 1
@check("toxic 1 + its proliferate trigger: 4 damage, 2 poison")
def _():
    G = cgame(perms=["Bloated Contaminator"]); G.combat()
    o = [o for o in G.opps if o["life"] < 40][0]
    return o["life"] == 36 and o["poison"] == 2
@check("10 poison kills")
def _():
    G = cgame(perms=["Glistener Elf"]); G.opps[0]["poison"] = 9; G.opps[1]["life"] = 30; G.opps[2]["life"] = 30
    G.combat(); return G.opps[0]["dead"] == 3 and G.opps[0]["how"] == "poison"
@check("commander damage is tallied per opponent; 21 kills")
def _():
    G = cgame(); p = G.enter(CK["Najeela, the Blade-Blossom"]); p.sick = False
    G.opps[1]["cmd"]["Najeela, the Blade-Blossom"] = 19; G.combat()
    return G.opps[1]["dead"] and G.opps[1]["how"] == "commander damage" and G.opps[1]["life"] == 40 - 3 - 1   # + its Warrior token
@check("focus fire: an attack that kills one opponent spills the rest onto the next")
def _():
    G = cgame(perms=["Serra Angel", "Grizzly Bears"]); G.opps[0]["life"] = 3; G.combat()
    return G.opps[0]["dead"] and sorted(lives(G)[1:]) == [38, 40]
@check("killing all three opponents ends the game (won = turn)")
def _():
    G = cgame(perms=["Serra Angel", "Grizzly Bears", "Boros Swiftblade"])
    for o in G.opps: o["life"] = 2
    G.combat(); return G.won == 3 and not G.alive()
@check("anthem: Glorious Anthem makes Bears 3/3")
def _():
    G = cgame(perms=["Grizzly Bears", "Glorious Anthem"]); b = G.perms[0]
    return G.stats(b)[:2] == (3, 3)
@check("Intangible Virtue pumps tokens only")
def _():
    G = cgame(perms=["Grizzly Bears", "Intangible Virtue", "Hero of Bladehold"]); G.combat()
    return G.dmg == 3 + 3 + 2 * 3                  # Bears 2+1 battle cry, Hero 3, two Soldiers 1 +1 Virtue +1 battle cry
@check("equip: Bonesplitter moves onto the attacker and adds 2")
def _():
    G = cgame(perms=["Grizzly Bears", "Bonesplitter"], lands=["Mountain"]); G.build_pool(); G.equip_step(); G.combat()
    return G.perms[1].att is G.perms[0] and G.dmg == 4
@check("Hero of Bladehold: two Soldiers enter attacking, battle cry pumps them (3 + 2x2 = 7)")
def _():
    G = cgame(perms=["Hero of Bladehold"]); G.combat()
    return G.dmg == 7 and sum(p.k.token for p in G.perms) == 2
@check("blocks: flying goes over a ground blocker; a 3/3 blocker keeps Bears home")
def _():
    G = cgame(perms=["Serra Angel", "Grizzly Bears"])
    for o in G.opps: o["board"] = [blocker(3, 3)]
    G.combat(); return G.dmg == 4
@check("blocks: first strike kills the blocker first (Baneslayer vs a 5/5); the attacker survives")
def _():
    G = cgame(perms=["Baneslayer Angel"])
    for o in G.opps: o["board"] = [blocker(5, 5, "flying")]
    G.combat()
    return G.perms and G.perms[0].k.name == "Baneslayer Angel" and sum(len(o["board"]) for o in G.opps) == 2 and G.dmg == 0
@check("blocks: a lethal attack draws a chump; trample carries the excess (Contaminator 4 over a 1/1 = 3)")
def _():
    G = cgame(perms=["Bloated Contaminator"])
    for o in G.opps: o["life"] = 4; o["board"] = [blocker(1, 1)]
    G.combat(); o = [o for o in G.opps if o["life"] < 4][0]
    return o["life"] == 1 and len(o["board"]) == 0
@check("blocks: menace can't be blocked by one creature; deathtouch blocker kills")
def _():
    G = cgame(perms=["Professional Face-Breaker"])
    for o in G.opps: o["board"] = [blocker(0, 1)]
    G.combat(); menace_ok = G.dmg == 2
    H = cgame(perms=["Grizzly Bears"])
    for o in H.opps: o["life"] = 2; o["board"] = [blocker(1, 1, "deathtouch")]
    H.combat()
    return menace_ok and not H.perms and H.lost == 1
@check("noncombat triggers: Impact Tremors on enter, Guttersnipe on cast, Blood Artist on a death")
def _():
    G = cgame(perms=["Impact Tremors"]); G.enter(CK["Grizzly Bears"]); a = lives(G) == [39, 39, 39]
    H = cgame(perms=["Guttersnipe"]); H.fire("cast", CK["Opt"]); b = lives(H) == [38, 38, 38]
    I = cgame(perms=["Blood Artist", "Grizzly Bears"]); I.leave(I.perms[1], "dies"); c = sum(lives(I)) == 119 and I.life == 41
    return a and b and c and G.trigs[("Impact Tremors", "enter")] == 1
@check("Sword of Fire and Ice triggers off its equipped creature (2 damage + a card)")
def _():
    G = cgame(perms=["Grizzly Bears", "Sword of Fire and Ice"]); G.perms[1].att = G.perms[0]; G.combat()
    return G.dmg == 4 + 2 and len(G.hand) == 1
@check("Purphoros isn't a creature below devotion 5; Crusader of Odric counts creatures")
def _():
    G = cgame(perms=["Purphoros, God of the Forge", "Crusader of Odric", "Grizzly Bears"])
    return not G.can_attack(G.perms[0]) and G.stats(G.perms[1])[:2] == (2, 2)
@check("Overrun waits for a board: not with 1 creature, yes with 4")
def _():
    G = cgame(perms=["Grizzly Bears"]); H = cgame(perms=["Grizzly Bears"] * 4)
    return not G.alpha_ok(CK["Overrun"]) and H.alpha_ok(CK["Overrun"])
@check("Rafiq: exalted +1/+1 and double strike when a creature attacks alone (3/3 -> 4 x 2 = 8)")
def _():
    G = cgame(perms=["Rafiq of the Many"]); G.combat(); return G.dmg == 8
@check("Najeela: an attacking Warrior makes a 1/1 Warrior attacking (3 + 1)")
def _():
    G = cgame(); p = G.enter(CK["Najeela, the Blade-Blossom"]); p.sick = False; G.combat()
    return G.dmg == 4
@check("Exsanguinate drains each opponent for X")
def _():
    G = cgame(); G.do(CK["Exsanguinate"].spell, CK["Exsanguinate"], None, 5); return lives(G) == [35, 35, 35]
@check("Ophidian draws when it attacks and isn't blocked")
def _():
    G = cgame(perms=["Ophidian"]); G.combat(); return len(G.hand) == 1
@check("mana: a land pays before a would-be attacker (Forest, not Llanowar Elves)")
def _():
    G = cgame(perms=["Llanowar Elves"], lands=["Forest"]); G.build_pool(); G.pay(None, 1, [])
    return not G.perms[0].tapped and G.lands[0].tapped
@check("subtype list has no rule-text words ('Creatures', 'The')")
def _(): return not ({"Creatures", "The", "Artifacts"} & g.SUBTYPES)

# ---- additional combat phases
def turn_combat(G):
    """The turn loop's combat block: combat, then each additional combat after its main phase."""
    G.combat(); n = 0
    while G.xcombat and G.alive() and n < g.XCOMBAT_CAP:
        G.xcombat -= 1; n += 1; G.xcombats += 1
        for sc in G.pending_untap: G.untap_cr(sc)
        G.pending_untap = []; G.combat()
    return n

@check("Relentless Assault cast before combat: its untap waits, Bears attack twice and Hellrider triggers twice")
def _():
    G = cgame(perms=["Grizzly Bears", "Hellrider"])
    G.do(CK["Relentless Assault"].spell, CK["Relentless Assault"])
    return turn_combat(G) == 1 and G.dmg == 2 * (2 + 3 + 2)    # each combat: Bears 2, Hellrider 3, two Hellrider pings
@check("Aurelia: untap and one extra combat, and only on her first attack each turn")
def _():
    G = cgame(perms=["Aurelia, the Warleader", "Grizzly Bears"]); G.phase = 7
    return turn_combat(G) == 1 and G.dmg == 2 * (3 + 2)
@check("Karlach: first combat only, attackers untap and gain first strike")
def _():
    G = cgame(perms=["Karlach, Fury of Avernus"]); G.phase = 7
    return turn_combat(G) == 1 and G.dmg == 2 * 5
@check("Najeela's combat ability: paid from the pool, another combat (Warriors trigger again)")
def _():
    G = cgame(lands=["Plains", "Island", "Swamp", "Mountain", "Forest"]); p = G.enter(CK["Najeela, the Blade-Blossom"]); p.sick = False
    G.build_pool(); n = turn_combat(G)
    return n == 1 and G.dmg == (3 + 1) + (3 + 1 + 1 + 1)    # 2nd combat: Najeela + first token + a token each for both
@check("extra combats stop at the cap")
def _():
    G = cgame(perms=["Grizzly Bears"]); G.xcombat = 50; return turn_combat(G) == g.XCOMBAT_CAP
@check("Relentless Assault waits: not with Bears alone, yes when attacking twice kills")
def _():
    G = cgame(perms=["Grizzly Bears"]); H = cgame(perms=["Grizzly Bears"] * 3); H.opps[0]["life"] = 10
    return not G.alpha_ok(CK["Relentless Assault"]) and H.alpha_ok(CK["Relentless Assault"])

# ---- ramp reads found by the Klauth test deck
@check("Castle Garenbrig filters 4 into six G (creature-only)")
def _(): return CK["Castle Garenbrig"].convs[0][0] == 4 and len(CK["Castle Garenbrig"].convs[0][1]) == 6
@check("Encroaching Dragonstorm returns to hand when a Dragon enters")
def _():
    G = cgame(lib=["Forest"] * 10); G.enter(CK["Encroaching Dragonstorm"]); G.enter(CK["Lathliss, Dragon Queen"])
    return CK["Encroaching Dragonstorm"] in G.hand and len(G.lands) == 2
@check("Jeska's Will: both modes, R per card in an opponent's hand (~opp 4) and three impulse cards")
def _(): return [e[0] for e in CK["Jeska's Will"].spell] == ["draw", "mana"] and len(CK["Jeska's Will"].spell[1][1]) == g.OPP_HAND
@check("Animist's Awakening X=4 puts the lands among the top 4 onto the battlefield")
def _():
    G = cgame(lib=["Opt", "Forest", "Opt", "Forest"]); G.do(CK["Animist's Awakening"].spell, CK["Animist's Awakening"], None, 4)
    return len(G.lands) == 2 and all(l.tapped for l in G.lands)
@check("Biorhythm: opponents drop to their estimated creature count, you to yours")
def _():
    G = cgame(perms=["Grizzly Bears"] * 2); G.turn = 6; G.do(CK["Biorhythm"].spell, CK["Biorhythm"])
    return lives(G) == [G.opp_creatures()] * 3 and G.life == 2

# ---- voltron / enchantress reads found by the Wilson + Flaming Fist deck
VNAMES = ["Wilson, Refined Grizzly", "Flaming Fist", "Forest", "Plains", "Grizzly Bears", "Mark of Sakiko", "Bear Umbra",
          "Snake Umbra", "Strong Back", "Pearl-Ear, Imperial Advisor", "Kor Spiritdancer", "Shield of the Oversoul",
          "Face of Divinity", "Alpha Authority", "Arbor Elf", "Gift of Paradise", "Season of Growth", "Phalanx Leader",
          "Kudo, King Among Bears", "Silent Arbiter", "Kenrith's Transformation", "Cryptolith Rite", "Calix, Guided by Fate",
          "Sage's Reverie", "Sol Ring", "Blacksmith's Skill", "Karametra's Blessing"]
VRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(VNAMES)}
VK = {n: g.compile_card(VRAW[n], frozenset("GW")) for n in VNAMES}

def vgame(perms=(), lands=(), hand=(), lib=("Forest",) * 10, auras=()):
    """Wilson is the commander. perms enter untapped and unsick; auras = [(aura, index of the perm it's on)]."""
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in VNAMES if n != "Wilson, Refined Grizzly"], ["Wilson, Refined Grizzly"], args, [], VK, frozenset("GW"))
    G = g.Game(sim, [VK[n] for n in hand], [VK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3
    G.lands = [g.Perm(VK[n]) for n in lands]
    G.perms = [g.Perm(VK[n]) for n in perms]
    for a, i in auras:
        q = g.Perm(VK[a]); q.att = G.perms[i]; G.perms.append(q)
    G._st = None
    return G

@check("Flaming Fist: the commander gains double strike when it attacks (Wilson 2 x 2 = 4 commander damage)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly", "Flaming Fist"]); G.combat()
    return G.dmg == 4 and max(v for o in G.opps for v in o["cmd"].values()) == 4
@check("Flaming Fist grants nothing to a non-commander (Grizzly Bears deal 2)")
def _():
    G = vgame(perms=["Grizzly Bears", "Flaming Fist"]); G.combat(); return G.dmg == 2
@check("Mark of Sakiko: combat damage adds that much G for main phase 2")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"], auras=[("Mark of Sakiko", 0)]); G.build_pool(); G.combat()
    return free_units(G) == 2 and G.dmg == 2
@check("Bear Umbra: +2/+2, and attacking untaps your lands (two tapped Forests -> 2 mana)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"], lands=["Forest", "Forest"], auras=[("Bear Umbra", 0)]); G.build_pool()
    for u in G.pool: g_ = G.use_unit(G.pool.index(u))
    G.combat(); return G.dmg == 4 and free_units(G) == 2
@check("umbra armor: a creature wipe destroys the Aura instead; the creature stays")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly", "Grizzly Bears"], auras=[("Snake Umbra", 0)]); G.disrupt({"kind": "wipe"})
    return [p.k.name for p in G.perms] == ["Wilson, Refined Grizzly"]
@check("Shield of the Oversoul on a green creature: +1/+1 indestructible, survives spot removal (not the white bonus)")
def _():
    G = vgame(perms=["Grizzly Bears"], auras=[("Shield of the Oversoul", 0)])
    pw, tg, kws = G.stats(G.perms[0])
    return (pw, tg) == (3, 3) and "indestructible" in kws and "flying" not in kws and G.survives(G.perms[0], True) and len(G.perms) == 2
@check("Face of Divinity: first strike and lifelink only with another Aura on the creature")
def _():
    a = vgame(perms=["Grizzly Bears"], auras=[("Face of Divinity", 0)])
    b = vgame(perms=["Grizzly Bears"], auras=[("Face of Divinity", 0), ("Snake Umbra", 0)])
    return "lifelink" not in a.stats(a.perms[0])[2] and {"lifelink", "first strike"} <= b.stats(b.perms[0])[2]
@check("Alpha Authority: hexproof commander can't be targeted by commander removal (answered, stays)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"], auras=[("Alpha Authority", 0)]); G.disrupt({"kind": "cmd"})
    return len(G.perms) == 2 and G.dis[-1] == ("cmd", "answered")
@check("Arbor Elf untaps a Forest: Forest + Elf = 2 mana; no land, no mana")
def _(): return pool_v(lands=["Forest"], perms=["Arbor Elf"]) == 2 and pool_v(perms=["Arbor Elf"]) == 0
@check("Gift of Paradise: its land taps for two (Forest + Gift = 2)")
def _(): return pool_v(lands=["Forest"], perms=["Gift of Paradise"]) == 2
@check("Cryptolith Rite: an unsick creature taps for mana")
def _(): return pool_v(perms=["Grizzly Bears", "Cryptolith Rite"]) == 1
@check("Strong Back: Auras cost 3 less, generic only ({2}{G}{G} -> GG); +2/+2 per Aura on it (Wilson + Strong Back + Snake Umbra = 7/7)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"], auras=[("Strong Back", 0), ("Snake Umbra", 0)])
    return min(o[0] + len(o[1]) for o in G.options(VK["Bear Umbra"], "hand")) == 2 and G.stats(G.perms[0])[:2] == (7, 7)
@check("Pearl-Ear: enchantment spells have affinity for Auras (two Auras out: Bear Umbra 4 -> 2)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly", "Pearl-Ear, Imperial Advisor"], auras=[("Snake Umbra", 0), ("Alpha Authority", 0)])
    return min(o[0] + len(o[1]) for o in G.options(VK["Bear Umbra"], "hand")) == 2
@check("Kor Spiritdancer gets +2/+2 per Aura on it (one Snake Umbra: 3/5)")
def _():
    G = vgame(perms=["Kor Spiritdancer"], auras=[("Snake Umbra", 0)]); return G.stats(G.perms[0])[:2] == (3, 5)
@check("Season of Growth draws for an Aura on your creature, not for Sol Ring")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly", "Season of Growth"], hand=["Snake Umbra", "Sol Ring"])
    G.resolve(VK["Snake Umbra"], "hand", 3); a = G.extra
    G.resolve(VK["Sol Ring"], "hand", 1); return a == 1 and G.extra == 1
@check("heroic: an Aura on Phalanx Leader puts a +1/+1 counter on each creature; one on another creature doesn't")
def _():
    G = vgame(perms=["Phalanx Leader"], hand=["Snake Umbra"]); G.resolve(VK["Snake Umbra"], "hand", 3)
    H = vgame(perms=["Phalanx Leader", "Wilson, Refined Grizzly"], auras=[("Bear Umbra", 1)], hand=["Snake Umbra"])
    H.resolve(VK["Snake Umbra"], "hand", 3)
    return (G.perms[0].ctr or {}).get("+1/+1") == 1 and not H.perms[0].ctr
@check("Kudo: other creatures are base 2/2 (Pearl-Ear 3/4 -> 2/2), Kudo itself 2/2")
def _():
    G = vgame(perms=["Kudo, King Among Bears", "Pearl-Ear, Imperial Advisor"])
    return G.stats(G.perms[1])[:2] == (2, 2) and G.stats(G.perms[0])[:2] == (2, 2)
@check("Silent Arbiter: only one creature attacks, yours included")
def _():
    G = vgame(perms=["Grizzly Bears", "Grizzly Bears", "Silent Arbiter"]); G.combat(); return G.dmg == 2
@check("removal Auras stay off your creatures; a Background-style grant doesn't count as a debuff")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"]); p = G.enter(VK["Kenrith's Transformation"]); q = G.enter(VK["Snake Umbra"])
    return p.att is None and q.att is G.perms[0] and VK["Kenrith's Transformation"].debuff and not VK["Snake Umbra"].debuff
@check("Calix constellation fires on itself and on another enchantment (+1/+1 counters)")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"]); G.enter(VK["Calix, Guided by Fate"]); G.enter(VK["Snake Umbra"])
    return sum((p.ctr or {}).get("+1/+1", 0) for p in G.perms) == 2
@check("Sage's Reverie counts itself: second Aura on a creature draws 2")
def _():
    G = vgame(perms=["Wilson, Refined Grizzly"], auras=[("Snake Umbra", 0)]); G.enter(VK["Sage's Reverie"]); return G.extra == 2
@check("protection answers: Blacksmith's Skill (target permanent gains shroud), Karametra's Blessing (it also gains hexproof)")
def _(): return VK["Blacksmith's Skill"].answer == "protect" and VK["Karametra's Blessing"].answer == "protect"
@check("override DSL: multi-word keywords with underscores (double_strike)")
def _(): return g.dsl("pump 0 0 obj double_strike")[0][4] == frozenset({"double strike"})
@check("mulligan: 2 lands + 3 cheap spells is a keep; 2 lands + expensive spells isn't")
def _():
    G = vgame(); sim = G.sim
    cheap = [VK[n] for n in ("Forest", "Plains", "Snake Umbra", "Sol Ring", "Arbor Elf", "Strong Back", "Calix, Guided by Fate")]
    dear = [VK[n] for n in ("Forest", "Plains", "Sage's Reverie", "Bear Umbra", "Calix, Guided by Fate", "Silent Arbiter", "Face of Divinity")]
    return sim.keep(cheap, 0) and not sim.keep(dear, 0)

def pool_v(**kw):
    G = vgame(**kw); G.build_pool(); return free_units(G)

# ---- sacrifice costs, type grants and the life-gain untap engine (Ragost, Deft Gastronaut deck)
FNAMES = ["Ragost, Deft Gastronaut", "Nuka-Cola Vending Machine", "Basilisk Collar", "Academy Manufactor", "Spirit Loop",
          "Well of Lost Dreams", "Furnace of Rath", "City on Fire", "Weapons Manufacturing", "Prized Statue", "Ichor Wellspring",
          "Servo Schematic", "Test of Endurance", "Stridehangar Automaton", "Goblin Bombardment", "Grizzly Bears", "Mountain",
          "Plains", "Ashnod's Altar", "Food Chain", "Experimental Confectioner"]
FRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(FNAMES)}
FK = {n: g.compile_card(FRAW[n], g.ALL5) for n in FNAMES}
RAGOST = "Ragost, Deft Gastronaut"

def fgame(perms=(), lands=(), lib=("Mountain",) * 10, collar=False):
    """Ragost is the commander. perms enter untapped and unsick; collar: Basilisk Collar on the first perm."""
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in FNAMES if n != RAGOST], [RAGOST], args, [], FK, g.ALL5)
    G = g.Game(sim, [], [FK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3; G.turns_left = g.OPP_N
    G.lands = [g.Perm(FK[n]) for n in lands]
    G.perms = [g.Perm(FK[n]) for n in perms]
    if collar:
        q = g.Perm(FK["Basilisk Collar"]); q.att = G.perms[0]; G.perms.append(q)
    G._st = None
    return G

def rest_of_round(G):
    """The turn loop from main phase 2: activations, your end step, then each opponent's turn (instant-speed engine)."""
    G.build_pool(); G.activations()
    G.open_pool = [u for u in G.pool if not u[5]]; G.pool = None
    G.fire("end"); G.opponents()

def perm(G, name): return next(p for p in G.perms if p.k.name == name)
def ragost_act(): return FK[RAGOST].acts[0]
def tokens(G, sub): return [p for p in G.perms if p.k.token and sub in p.k.subtypes]

@check("Ragost reads: sacrifice-a-Food cost, Food grant with its quoted ability, life-gain untap on every end step")
def _():
    k = FK[RAGOST]; a = ragost_act()
    tg = [s for s in k.statics if s[0] == "type_grant"]
    return a["tap"] and a["gen"] == 1 and a["fodder"]["any"][0]["sub"] == {"Food"} and k.gain_untap and k.status == "modeled" \
        and tg and tg[0][3] == frozenset({"Food"}) and tg[0][4][0]["sac"] and tg[0][4][0]["gen"] == 2
@check("Ragost + Nuka-Cola + Basilisk Collar, 5 lands: 3 to each opponent on each of the round's 4 turns (lifelink 9 each)")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"], lands=["Mountain"] * 5, collar=True); rest_of_round(G)
    return lives(G) == [40 - 12] * 3 and G.life == 40 + 4 * 9
@check("same board, 2 lands: Nuka-Cola + one activation on your turn, nothing left open for the opponents' turns")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"], lands=["Mountain"] * 2, collar=True); rest_of_round(G)
    return lives(G) == [37] * 3
@check("no life gained, no untap: without lifelink Ragost activates once a round")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"], lands=["Mountain"] * 5); rest_of_round(G)
    return lives(G) == [37] * 3 and perm(G, RAGOST).tapped
@check("a spare Food's own life ability untaps Ragost (no lifelink, 5 lands: 2 activations)")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"], lands=["Mountain"] * 5); G.make_tokens(g.FOOD_E, 1); rest_of_round(G)
    return lives(G) == [34] * 3
@check("Nuka-Cola: a sacrificed Food makes a tapped Treasure; under Ragost a Treasure spent for mana is a Food too")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"]); G.make_tokens(g.TREASURE_E, 1); G.build_pool(); G.pay(None, 1, [])
    H = fgame(perms=["Nuka-Cola Vending Machine"]); H.make_tokens(g.TREASURE_E, 1); H.build_pool(); H.pay(None, 1, [])
    t = tokens(G, "Treasure")
    return len(t) == 1 and t[0].tapped and not tokens(H, "Treasure")
@check("fodder order: tapped Treasure, Food, Ichor Wellspring, untapped Treasure; never Nuka-Cola or the equipped Collar")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine", "Ichor Wellspring"], collar=True)
    G.make_tokens(g.TREASURE_E, 1); G.make_tokens(g.TREASURE_E, 1, tapped=True); G.make_tokens(g.FOOD_E, 1)
    order = []
    while True:
        pk = G.pick_fodder(ragost_act()["fodder"], perm(G, RAGOST), ragost_act()["fx"])
        if not pk: break
        order.append(pk[0].k.name + (" tapped" if pk[0].tapped else "")); G.perms.remove(pk[0]); G._st = None
    return order == ["Treasure token tapped", "Food token", "Ichor Wellspring", "Treasure token"]
@check("Academy Manufactor: a Food becomes a Food, a Clue and a Treasure; Stridehangar adds a Thopter per artifact-token event")
def _():
    G = fgame(perms=["Academy Manufactor", "Stridehangar Automaton"]); G.make_tokens(g.FOOD_E, 1)
    return [len(tokens(G, s)) for s in ("Food", "Clue", "Treasure", "Thopter")] == [1, 1, 1, 1]
@check("damage doublers: Furnace doubles Ragost's 3 (6 each), City on Fire + Furnace = 18; Furnace doubles combat damage")
def _():
    G = fgame(perms=[RAGOST, "Furnace of Rath"]); G.do(ragost_act()["fx"], FK[RAGOST], G.perms[0])
    H = fgame(perms=[RAGOST, "Furnace of Rath", "City on Fire"]); H.do(ragost_act()["fx"], FK[RAGOST], H.perms[0])
    I = fgame(perms=["Grizzly Bears", "Furnace of Rath"]); I.combat()
    return lives(G) == [34] * 3 and lives(H) == [22] * 3 and I.dmg == 4
@check("Spirit Loop on Ragost: one damage event gains 9; Well of Lost Dreams draws 3 of 6 open mana, holding 3 for Ragost's opponent turns")
def _():
    G = fgame(perms=[RAGOST, "Well of Lost Dreams"], lands=["Mountain"] * 6)
    q = g.Perm(FK["Spirit Loop"]); q.att = G.perms[0]; G.perms.append(q); G._st = None
    G.build_pool(); G.do(ragost_act()["fx"], FK[RAGOST], G.perms[0])
    return G.life == 49 and G.gained == 9 and len(G.hand) == 3 and G.trigs[("Well of Lost Dreams", "other")] == 1
@check("lifelink covers noncombat damage (Collar on Ragost: +9), not life loss")
def _():
    G = fgame(perms=[RAGOST], collar=True); G.do(ragost_act()["fx"], FK[RAGOST], G.perms[0])
    H = fgame(perms=[RAGOST], collar=True); H.do([("face", 3, "each", False)], FK[RAGOST], H.perms[0])
    return G.life == 49 and H.life == 40 and lives(H) == [37] * 3
@check("Weapons Manufacturing: a nontoken artifact makes Munitions; it's first fodder and deals 2 (4 with Furnace) as it leaves")
def _():
    G = fgame(perms=[RAGOST, "Weapons Manufacturing", "Furnace of Rath"]); G.enter(FK["Ichor Wellspring"])
    mu = tokens(G, "Munitions")
    pk = G.pick_fodder(ragost_act()["fodder"], perm(G, RAGOST), ragost_act()["fx"])
    G.leave(mu[0], "is sacrificed", sac=True)
    return len(mu) == 1 and pk == mu and sum(lives(G)) == 120 - 4
@check("'enters or is put into a graveyard': Prized Statue makes a Treasure both ways; Servo Schematic's Servo is an artifact (a Food under Ragost)")
def _():
    G = fgame(perms=[RAGOST]); G.enter(FK["Prized Statue"]); G.leave(perm(G, "Prized Statue"), "is sacrificed", sac=True)
    G.enter(FK["Servo Schematic"])
    sv = tokens(G, "Servo")
    return len(tokens(G, "Treasure")) == 2 and len(sv) == 1 and G.pmatch(ragost_act()["fodder"], sv[0], G.perms[0]) \
        and G.board_n() == 3                    # Ragost, Schematic, Servo: Treasures are mana, not board
@check("Test of Endurance: win at upkeep with 50 life, not with 49")
def _():
    G = fgame(perms=["Test of Endurance"]); G.life = 50; G.fire("upkeep")
    H = fgame(perms=["Test of Endurance"]); H.life = 49; H.fire("upkeep")
    return G.won == 3 and not G.alive() and not H.won
@check("Goblin Bombardment keeps a 1/1 attacker unless the ping kills; Ragost sacrifices Servo Schematic, then a Servo (9 damage is worth it)")
def _():
    G = fgame(perms=["Goblin Bombardment"]); G.enter(FK["Servo Schematic"])
    ab = FK["Goblin Bombardment"].acts[0]; bomb = perm(G, "Goblin Bombardment")
    no = G.pick_fodder(ab["fodder"], bomb, ab["fx"]); G.opps[0]["life"] = 1
    yes = G.pick_fodder(ab["fodder"], bomb, ab["fx"])
    H = fgame(perms=[RAGOST]); H.enter(FK["Servo Schematic"])
    first = H.pick_fodder(ragost_act()["fodder"], H.perms[0], ragost_act()["fx"])
    H.leave(first[0], "is sacrificed", sac=True)                  # the Schematic makes a second Servo on its way out
    second = H.pick_fodder(ragost_act()["fodder"], H.perms[0], ragost_act()["fx"])
    return no is None and yes and first[0].k.name == "Servo Schematic" and second[0].k.name == "Servo token"         and len(tokens(H, "Servo")) == 2
@check("Ragost stays home to use his ability when fodder is ready (Nuka-Cola), attacks without it")
def _():
    G = fgame(perms=[RAGOST, "Nuka-Cola Vending Machine"], lands=["Mountain"] * 3); G.build_pool(); G.combat()
    H = fgame(perms=[RAGOST], lands=["Mountain"] * 3); H.build_pool(); H.combat()
    return G.dmg == 0 and not G.perms[0].tapped and H.dmg == 2
@check("Experimental Confectioner: sacrificing a Food makes a Rat; guards: Ashnod's Altar (sacrifice for mana) and Food Chain stay unread")
def _():
    G = fgame(perms=["Experimental Confectioner"]); G.make_tokens(g.FOOD_E, 1)
    G.leave(tokens(G, "Food")[0], "is sacrificed", sac=True)
    return len(tokens(G, "Rat")) == 1 and FK["Ashnod's Altar"].status == "blank" and FK["Food Chain"].status == "blank"

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
