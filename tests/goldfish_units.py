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
         "Dragonstorm", "Tireless Tracker", "Chord of Calling", "Hamza, Guardian of Arashin",
         "Triumph of the Hordes", "Tromp the Domains", "Rites of Initiation"]

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
# ---- team pumps (2026-09-30 coverage pass)
@check("Duration-first team pump compiles and reads (Triumph of the Hordes crashed compile_card)")
def _():
    e = K["Triumph of the Hordes"].spell
    return len(e) == 1 and e[0][0] == "pump_team" and e[0][1:3] == (1, 1) and {"infect", "trample"} <= set(e[0][3])
@check("Team pump 'for each' scales, never flat: Tromp the Domains = +2/+2 with Forest, Mountain, Forest")
def _():
    e = K["Tromp the Domains"].spell[0]
    return e[0] == "pump_team" and e[1] == ("per", 1, ("domain",)) and game(lands=["Forest", "Mountain", "Forest"]).val(e[1][2], None, 0) == 2
@check("Team pump with an unreadable 'for each' stays unread (Rites of Initiation, was read as a flat +1/+0)")
def _(): return not any(x[0] == "pump_team" for x in K["Rites of Initiation"].spell) and K["Rites of Initiation"].status != "modeled"

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
          "Castle Garenbrig", "Encroaching Dragonstorm", "Lathliss, Dragon Queen", "Biorhythm", "Jeska's Will", "Animist's Awakening",
          "Questing Beast", "Ichorclaw Myr", "Samurai of the Pale Curtain", "Neheb, the Eternal", "Wolverine Pack", "Artful Dodge",
          "Falter", "Suq'Ata Lancer", "Swords to Plowshares", "Frenzied Goblin",
          "Ravenous Chupacabra", "Shock", "Doom Blade", "Plague Wind", "Skinrender", "Swamp",
          "Psychosis Crawler", "Steel Overseer", "Rosie Cotton of South Lane", "Ponder", "Kinnan, Bonder Prodigy", "Managorger Hydra",
          "Deadly Dispute", "Skullclamp", "Fling", "Mana Vault"]
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
@check("blocks: nobody blocks a first striker that kills first (Baneslayer vs a 5/5 flyer: 5 through)")
def _():
    G = cgame(perms=["Baneslayer Angel"])
    for o in G.opps: o["board"] = [blocker(5, 5, "flying")]
    G.combat(); return G.dmg == 5 and sum(len(o["board"]) for o in G.opps) == 3
@check("blocks: facing lethal it chumps anyway; first strike kills the blocker and Baneslayer lives")
def _():
    G = cgame(perms=["Baneslayer Angel"])
    for o in G.opps: o["life"] = 5; o["board"] = [blocker(5, 5, "flying")]
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

# ---- opposing boards: --blockers, blocks, denial
def board(G, *bl, seats=(0, 1, 2)):
    for i in seats: G.opps[i]["board"] = [dict(x, kw=set(x["kw"])) for x in bl]
def deny(G, code, seat=0): G.opps[seat]["deny"].append({"code": code, "until": None})

@check("--blockers parses creatures, seats, copies, ranges and denial; bad tokens are refused")
def _():
    sp = g.parse_blockers("2/2 flying@3x2; 1:prop@4-6; each:fog@5; 1/4 first_strike reach@2")
    bad = 0
    for tok in ("2/2 banana@3", "fog@0", "3/3@5-4", "4:2/2@3"):
        try: g.parse_blockers(tok)
        except ValueError: bad += 1
    return len(sp) == 5 and sp[0] == sp[1] == (3, None, None, {"p": 2, "t": 2, "kw": frozenset({"flying"})}) \
        and sp[2] == (4, 6, [0], {"deny": "prop"}) and sp[3] == (5, None, None, {"deny": "fog"}) \
        and sp[4][3]["kw"] == {"first strike", "reach"} and bad == 4
@check("arrival and expiry: a 2/2@2-3 reaches every board for T2 and leaves before T4; a seat-2 fog only there")
def _():
    G = cgame(); G.bspec = g.parse_blockers("2/2@2-3; 2:fog@2"); G.arrive(2)
    a = all(len(o["board"]) == 1 for o in G.opps) and [len(o["deny"]) for o in G.opps] == [0, 1, 0]
    G.expire(3); b = all(len(o["board"]) == 1 for o in G.opps); G.expire(4)
    return a and b and not any(o["board"] for o in G.opps)
@check("gang block: two 2/3 flyers kill Serra Angel and lose one (a trade)")
def _():
    G = cgame(perms=["Serra Angel"]); board(G, blocker(2, 3, "flying"), blocker(2, 3, "flying")); G.combat()
    return not G.perms and G.lost == 1 and G.bstat["trade"] == 1 and sorted(len(o["board"]) for o in G.opps) == [1, 2, 2]
@check("the commander isn't sent into a blocker that kills it; Bears trade with a 2/2")
def _():
    G = cgame(); p = G.enter(CK["Najeela, the Blade-Blossom"]); p.sick = False; board(G, blocker(2, 2)); G.combat()
    H = cgame(perms=["Grizzly Bears"]); board(H, blocker(2, 2)); H.combat()
    return G.dmg == 0 and G.bstat["held_back"] == 1 and H.bstat["trade"] == 1 and not H.perms
@check("bushido: Samurai (2/2, bushido 1) trades with a 3/3 instead of dying to it")
def _():
    G = cgame(perms=["Samurai of the Pale Curtain"]); board(G, blocker(3, 3)); G.combat()
    return not G.perms and G.bstat["trade"] == 1
@check("rampage: Wolverine Pack gang-blocked by two 2/2s grows to 4/6, kills both and lives")
def _():
    G = cgame(perms=["Wolverine Pack"]); board(G, blocker(2, 2), blocker(2, 2), seats=(0,))
    G.opps[1]["life"] = G.opps[2]["life"] = 40; G.opps[0]["life"] = 39; G.combat()
    return G.perms and not G.opps[0]["board"] and G.bstat["blk_killed"] == 2
@check("flanking: a chump 1/1 dies before damage; the Lancer stays blocked (no damage)")
def _():
    G = cgame(perms=["Suq'Ata Lancer"]); board(G, blocker(1, 1))
    for o in G.opps: o["life"] = 2
    G.combat(); return G.dmg == 0 and G.bstat["blk_killed"] == 1 and G.perms
@check("afflict: Neheb walled by a 5/7 still makes that player lose 3")
def _():
    G = cgame(perms=["Neheb, the Eternal"]); board(G, blocker(5, 7)); G.combat()
    return sorted(lives(G)) == [37, 40, 40] and G.bstat["stalled"] == 1
@check("becomes-blocked trigger: Ichorclaw Myr gets +2/+2")
def _():
    G = cgame(perms=["Ichorclaw Myr"]); p = G.perms[0]; G.attackers = {p: 0}
    G.block_triggers({p: [blocker(2, 2)]}); return G.stats(p)[:2] == (3, 3)
@check("partial evasion: Questing Beast can't be blocked by power 2 or less")
def _():
    G = cgame(perms=["Questing Beast"]); p = G.perms[0]; kws = G.stats(p)[2]
    return not G.can_block(blocker(2, 5), kws, 4, p) and G.can_block(blocker(3, 3), kws, 4, p)
@check("Falter: ground creatures can't block, flyers still can; Artful Dodge makes Bears unblockable")
def _():
    G = cgame(perms=["Grizzly Bears"]); p = G.perms[0]; G.do(CK["Falter"].spell, CK["Falter"])
    a = not G.can_block(blocker(3, 3), set(), 2, p) and G.can_block(blocker(1, 1, "flying"), set(), 2, p)
    H = cgame(perms=["Grizzly Bears"]); q = H.perms[0]; H.do(CK["Artful Dodge"].spell, CK["Artful Dodge"])
    return a and "unblockable" in H.stats(q)[2]
@check("fog: the opponent being attacked fogs; no damage, the fog is spent")
def _():
    G = cgame(perms=["Grizzly Bears"]); deny(G, "fog"); G.combat()
    return G.dmg == 0 and G.bstat["fog"] == 1 and not G.opps[0]["deny"]
@check("Settle the Wreckage: two attackers are exiled, you fetch two tapped basics")
def _():
    G = cgame(perms=["Grizzly Bears", "Serra Angel"])
    for i in (1, 2): G.opps[i]["life"] = 40
    G.opps[0]["life"] = 10; deny(G, "settle"); G.combat()
    return not G.perms and G.bstat["settled"] == 2 and len(G.lands) == 2 and all(l.tapped for l in G.lands) and G.dmg == 0
@check("attack tax: with no mana Bears go around Propaganda; with 2 lands they pay and hit its owner")
def _():
    G = cgame(perms=["Grizzly Bears"]); deny(G, "prop"); G.build_pool(); G.combat()
    H = cgame(perms=["Grizzly Bears"], lands=["Forest", "Forest"]); deny(H, "prop"); H.build_pool(); H.combat()
    return G.opps[0]["life"] == 40 and G.dmg == 2 and H.opps[0]["life"] == 38 and H.bstat["prop_paid"] == 2
@check("Silent Arbiter (on a board) lets one attacker through (Serra, not Bears); Moat keeps Bears home")
def _():
    G = cgame(perms=["Serra Angel", "Grizzly Bears"])
    G.opps[0]["board"] = [{"name": "Silent Arbiter", "p": 1, "t": 5, "kw": {"artifact"}, "mv": 4, "deny": "arb"}]; G.combat()
    H = cgame(perms=["Serra Angel", "Grizzly Bears"]); deny(H, "moat"); H.combat()
    return G.dmg == 4 and G.bstat["deny_stop"] == 1 and H.dmg == 4 and H.bstat["deny_stop"] == 1
@check("Ensnaring Bridge: Bears stay home with an empty hand, attack holding two cards")
def _():
    G = cgame(perms=["Grizzly Bears"]); deny(G, "bridge"); G.combat()
    H = cgame(perms=["Grizzly Bears"], hand=["Opt", "Opt"]); deny(H, "bridge"); H.combat()
    return G.dmg == 0 and H.dmg == 2
@check("Maze of Ith untaps the attacker: no damage, Serra untapped")
def _():
    G = cgame(perms=["Serra Angel"]); deny(G, "maze"); G.combat()
    return G.dmg == 0 and not G.perms[0].tapped and G.bstat["mazed"] == 1
@check("an opponent who dies takes its board; a wipe event clears boards but not indestructible blockers")
def _():
    G = cgame(perms=["Serra Angel"]); board(G, blocker(1, 5)); G.opps[0]["life"] = 4; G.opps[1]["life"] = G.opps[2]["life"] = 40
    G.combat(); a = G.opps[0]["dead"] and not G.opps[0]["board"]
    H = cgame(); board(H, blocker(2, 2), blocker(3, 3, "indestructible")); H.disrupt({"kind": "wipe"})
    return a and all(len(o["board"]) == 1 and "indestructible" in o["board"][0]["kw"] for o in H.opps)
@check("clear path: Swords on the only blocker between Serra and a kill")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Plains"], hand=["Swords to Plowshares"])
    G.opps[0]["life"] = 4; G.opps[0]["board"] = [blocker(0, 2, "flying")]      # 0 power: Swords gives them no life
    G.build_pool(); G.clear_path(); G.combat()
    return G.opps[0]["dead"] and G.bstat["removed_blk"] == 1 and CK["Swords to Plowshares"] in G.gy
@check("clear path holds Swords when its life gain means no kill (4 life, 2/2 blocker: they'd go to 6)")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Plains"], hand=["Swords to Plowshares"])
    G.opps[0]["life"] = 4; G.opps[0]["board"] = [blocker(2, 2, "flying")]
    G.build_pool(); G.clear_path()
    return CK["Swords to Plowshares"] in G.hand and G.bstat["removed_blk"] == 0
@check("held removal isn't fired when no kill follows (Doom Blade stays in hand at 20 life)")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Swamp", "Swamp"], hand=["Doom Blade"])
    G.opps[0]["life"] = 20; G.opps[0]["board"] = [blocker(2, 2, "flying")]
    G.build_pool(); G.clear_path()
    return CK["Doom Blade"] in G.hand
@check("Doom Blade can't target a black blocker; Shock can't kill a 3-toughness one")
def _():
    db = CK["Doom Blade"].spell[0]; sh = CK["Shock"].burn_blk
    return not g.can_kill(db, blocker(2, 2, "black")) and g.can_kill(db, blocker(2, 2)) \
        and not g.can_kill(sh, blocker(1, 3)) and g.can_kill(sh, blocker(5, 2))
@check("Shock clears a 2-toughness blocker for lethal (held any-target burn)")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Mountain"], hand=["Shock"])
    G.opps[0]["life"] = 4; G.opps[0]["board"] = [blocker(1, 2, "flying")]
    G.build_pool(); G.clear_path(); G.combat()
    return G.opps[0]["dead"] and CK["Shock"] in G.gy
@check("Plague Wind clears two blockers when that's lethal; one-sided, so your Serra survives")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Swamp"] * 9, hand=["Plague Wind"])
    G.opps[0]["life"] = 4; G.opps[0]["board"] = [blocker(2, 2, "flying"), blocker(1, 4, "reach")]
    G.build_pool(); G.clear_path(); G.combat()
    return G.opps[0]["dead"] and CK["Plague Wind"] in G.gy and any(p.k.name == "Serra Angel" for p in G.perms)
@check("Chupacabra ETB kills the blocker in the way; Skinrender's -1/-1 counters go on their creature, not yours")
def _():
    G = cgame(perms=["Serra Angel"]); G.opps[0]["life"] = 4
    G.opps[0]["board"] = [blocker(2, 2, "flying"), blocker(3, 3)]
    G.do(CK["Ravenous Chupacabra"].etb, CK["Ravenous Chupacabra"])
    first = [b["name"] for b in G.opps[0]["board"]] == ["3/3"]       # the flier was the one stopping Serra
    H = cgame(perms=["Serra Angel"]); H.opps[0]["board"] = [blocker(3, 3)]
    H.do(CK["Skinrender"].etb, CK["Skinrender"])
    serra = next(p for p in H.perms if p.k.name == "Serra Angel")
    return first and not H.opps[0]["board"] and not (serra.ctr or {}).get("-1/-1")
@check("'Whenever you draw a card': Psychosis Crawler drains each opponent once per card drawn")
def _():
    G = cgame(perms=["Psychosis Crawler"]); G.draw(2)
    return lives(G) == [g.START_LIFE - 2] * 3
@check("Steel Overseer counts only artifact creatures (Serra Angel gets none)")
def _():
    G = cgame(perms=["Steel Overseer", "Serra Angel"])
    ov = next(p for p in G.perms if p.k.name == "Steel Overseer"); sa = next(p for p in G.perms if p.k.name == "Serra Angel")
    G.do(CK["Steel Overseer"].acts[0]["fx"], CK["Steel Overseer"], ov)
    return (ov.ctr or {}).get("+1/+1") == 1 and not (sa.ctr or {}).get("+1/+1")
@check("'Whenever a player casts a spell' listens to your casts and opponents' (Managorger Hydra)")
def _(): return {t[0] for t in CK["Managorger Hydra"].trig} == {"cast", "opp_cast"}
@check("Legendary names shorten at ' of ': Rosie Cotton's 'When Rosie Cotton enters' is her ETB")
def _(): return any(e[0] == "token" and "Food" in e[3] for e in CK["Rosie Cotton of South Lane"].etb)
@check("Ponder arranges the top 3 (no bottoming) then draws; Kinnan digs 5 for a non-Human creature onto the battlefield")
def _():
    kin = CK["Kinnan, Bonder Prodigy"].acts
    return [e[0] for e in CK["Ponder"].spell] == ["arrange", "draw"] and CK["Ponder"].spell[0][1] == 3 \
        and any(e[0] == "look_f" and e[1] == 5 and e[3] == "bf" for a in kin for e in a["fx"])

TOK = ("token", 1, 1, ("Soldier",), None, "creature", 1, frozenset(), False)     # a 1/1 creature token
@check("Deadly Dispute sacrifices the Treasure, never Serra Angel; with only Serra it can't be cast")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Swamp", "Swamp"], hand=["Deadly Dispute"])
    G.do([("treasure", 1, False)], CK["Deadly Dispute"]); G.build_pool()
    h = len(G.hand); ok = G.try_cast(CK["Deadly Dispute"], "hand")
    serra = any(p.k.name == "Serra Angel" for p in G.perms)
    H = cgame(perms=["Serra Angel"], lands=["Swamp", "Swamp"], hand=["Deadly Dispute"]); H.build_pool()
    return ok and serra and len(G.hand) == h - 1 + 2 and not H.options(CK["Deadly Dispute"], "hand")
@check("Skullclamp kills 1/1 tokens for 2 cards each while mana lasts; Serra Angel is never clamped")
def _():
    G = cgame(perms=["Skullclamp", "Serra Angel"], lands=["Plains", "Plains"])
    G.do([TOK, TOK], CK["Skullclamp"]); G.build_pool(); h = len(G.hand)
    G.clamp_step()
    return len(G.hand) == h + 4 and any(p.k.name == "Serra Angel" for p in G.perms) \
        and not any(p.k.token for p in G.perms)
@check("Fling waits for lethal: Serra (4) is flung at 4 life, not at 10")
def _():
    G = cgame(perms=["Serra Angel"], lands=["Mountain", "Mountain"], hand=["Fling"])
    for o in G.opps: o["life"] = 10
    G.build_pool(); held = not G.options(CK["Fling"], "hand")
    H = cgame(perms=["Serra Angel"], lands=["Mountain", "Mountain"], hand=["Fling"])
    H.opps[0]["life"] = 4; H.build_pool(); H.try_cast(CK["Fling"], "hand")
    return held and H.opps[0]["dead"]

@check("Mana Vault doesn't untap and is spent last: a 1-mana payment taps the Plains, not the Vault")
def _():
    G = cgame(perms=["Mana Vault"], lands=["Plains"]); G.build_pool(); G.pay(None, 1, [])
    vault = next(p for p in G.perms if p.k.name == "Mana Vault")
    return CK["Mana Vault"].no_untap and not vault.tapped and G.lands[0].tapped

@check("ETB removal with no --blockers does nothing and costs nothing")
def _():
    G = cgame(perms=["Serra Angel"]); G.do(CK["Ravenous Chupacabra"].etb, CK["Ravenous Chupacabra"])
    return G.bstat["removed_blk"] == 0 and len(G.perms) == 1

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
@check("Experimental Confectioner: sacrificing a Food makes a Rat; guard: Food Chain ('exile a creature' cost) stays unread")
def _():
    G = fgame(perms=["Experimental Confectioner"]); G.make_tokens(g.FOOD_E, 1)
    G.leave(tokens(G, "Food")[0], "is sacrificed", sac=True)
    return len(tokens(G, "Rat")) == 1 and FK["Food Chain"].status == "blank"
@check("Ashnod's Altar: two Servo tokens are 4 extra mana, spent only after the lands; real creatures are never fodder")
def _():
    G = fgame(perms=["Ashnod's Altar", "Grizzly Bears"], lands=["Mountain"] * 2)
    for _ in range(2): G.enter(G.sim.token_card(("token", 1, 1, ("Servo",), "", "artifact creature", 1, frozenset(), False)))
    G.build_pool(); n = sum(1 for u in G.pool if not u[5])
    ok2 = G.pay(None, 2, [])                             # lands cover it: no token dies
    alive = len(tokens(G, "Servo"))
    ok3 = G.pay(None, 3, [])                             # now both Servos go (CC each, one C left over)
    return n == 6 and ok2 and alive == 2 and ok3 and not tokens(G, "Servo") and any(p.k.name == "Grizzly Bears" for p in G.perms)
@check("Phyrexian Tower: one creature per tap; its own {C} and the sacrifice exclude each other")
def _():
    k = g.compile_card(next(c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] == "Phyrexian Tower"), g.ALL5)
    G = fgame(perms=[])
    G.lands = [g.Perm(k)]
    for _ in range(2): G.enter(G.sim.token_card(("token", 1, 1, ("Servo",), "", "artifact creature", 1, frozenset(), False)))
    G.build_pool(); ok = G.pay(None, 0, [frozenset("B"), frozenset("B")])
    return ok and len(tokens(G, "Servo")) == 1 and G.lands[0].tapped and not G.pay(None, 1, [])

# ---- life you pay yourself (docs/GOLDFISH.md "Life")
LNAMES = ["Kenrith, the Returned King", "Llanowar Wastes", "City of Brass", "Ancient Tomb", "Mana Confluence", "Horizon Canopy",
          "Talisman of Dominance", "Polluted Delta", "Watery Grave", "Island", "Swamp", "Gitaxian Probe", "Dark Confidant",
          "Sylvan Library", "Birthing Pod", "Laboratory Maniac", "Thassa's Oracle", "Snuff Out", "Night's Whisper", "Phyrexian Arena", "Wastes"]
LRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(LNAMES)}
LK = {n: g.compile_card(LRAW[n], g.ALL5) for n in LNAMES}
_OV = g.load_overrides()
for _n in LK:
    if g.mtg.norm(_n) in _OV: g.apply_override(LK[_n], _OV[g.mtg.norm(_n)], g.ALL5)
KEN = "Kenrith, the Returned King"

def lgame(lands=(), perms=(), hand=(), lib=("Wastes",) * 10, life=40):
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in LNAMES if n != KEN], [KEN], args, [], LK, g.ALL5)
    G = g.Game(sim, [LK[n] for n in hand], [LK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3; G.turns_left = g.OPP_N; G.life = life
    G.lands = [g.Perm(LK[n]) for n in lands]; G.perms = [g.Perm(LK[n]) for n in perms]; G._st = None
    return G

@check("Pain reads: painland colored only, City of Brass / Ancient Tomb / Confluence / Horizon always, fetch 1, shock 2")
def _():
    k = LK
    return (k["Llanowar Wastes"].pain, k["Llanowar Wastes"].pain_col) == (1, True) and (k["City of Brass"].pain, k["City of Brass"].pain_col) == (1, False) \
        and k["City of Brass"].status != "blank" and not any("becomes tapped" in n for n in k["City of Brass"].notes) \
        and k["Ancient Tomb"].pain == 2 and k["Mana Confluence"].pain == 1 and k["Horizon Canopy"].pain == 1 \
        and (k["Talisman of Dominance"].pain, k["Talisman of Dominance"].pain_col) == (1, True) \
        and k["Polluted Delta"].fetch_life == 1 and k["Watery Grave"].etap == ("shock", 2)
@check("Painland: generic from {C} is free, a colored pip costs 1")
def _():
    G = lgame(lands=["Llanowar Wastes"]); G.build_pool(); G.pay(None, 1, [])
    H = lgame(lands=["Llanowar Wastes"]); H.build_pool(); H.pay(None, 0, [frozenset("B")])
    return G.life == 40 and H.life == 39 and H.life_paid["mana"] == 1
@check("Painless sources are tapped before painful ones; Ancient Tomb costs 2 once per tap")
def _():
    G = lgame(lands=["City of Brass", "Island"]); G.build_pool(); G.pay(None, 1, [])
    H = lgame(lands=["Ancient Tomb"]); H.build_pool(); H.pay(None, 2, [])
    return G.life == 40 and H.life == 38
@check("A painful source that would kill you is never tapped")
def _():
    G = lgame(lands=["City of Brass"], life=1); G.build_pool()
    return not G.pay(None, 1, []) and G.life == 1
@check("Shockland: pays 2 above the floor, enters tapped at it; fetch pays 1")
def _():
    G = lgame(); G.land_enters(LK["Watery Grave"]); H = lgame(life=21); H.land_enters(LK["Watery Grave"])
    F = lgame(lib=("Island",) * 3); F.land_enters(LK["Polluted Delta"])
    return G.life == 38 and not G.lands[0].tapped and H.life == 21 and H.lands[0].tapped and F.life == 39 and F.lands[0].k.name == "Island"
@check("Phyrexian mana: 2 life above the floor, the colored pip at it")
def _():
    G = lgame(hand=["Gitaxian Probe"]); G.build_pool(); ok1 = G.try_cast(LK["Gitaxian Probe"], "hand")
    H = lgame(hand=["Gitaxian Probe"], life=21); H.build_pool(); ok2 = not H.try_cast(LK["Gitaxian Probe"], "hand")
    J = lgame(hand=["Gitaxian Probe"], lands=["Island"], life=21); J.build_pool(); ok3 = J.try_cast(LK["Gitaxian Probe"], "hand")
    return ok1 and G.life == 38 and G.life_paid["phyrexian"] == 2 and ok2 and ok3 and J.life == 21
@check("Birthing Pod's Phyrexian activation cost counts 2 life")
def _(): return LK["Birthing Pod"].acts and LK["Birthing Pod"].acts[0]["life"] == 2 or LK["Birthing Pod"].status != "modeled"
@check("Dark Confidant: draws the top card and loses its mana value (Arena, MV 3); Night's Whisper's \"and lose 2 life\" is read")
def _():
    G = lgame(perms=["Dark Confidant"], lib=("Wastes", "Phyrexian Arena")); G.fire("upkeep")
    H = lgame(hand=["Night's Whisper"], lands=["Swamp", "Swamp"]); H.build_pool(); H.try_cast(LK["Night's Whisper"], "hand")
    return G.life == 37 and G.hand[-1].name == "Phyrexian Arena" and H.life == 38
@check("Sylvan Library: keeps one extra for 4 life above the floor, none at it")
def _():
    G = lgame(perms=["Sylvan Library"], lib=("Wastes",) * 5); G.fire("drawstep")
    H = lgame(perms=["Sylvan Library"], lib=("Wastes",) * 5, life=23); H.fire("drawstep")
    return G.life == 36 and len(G.hand) == 1 and len(G.lib) == 4 and H.life == 23 and len(H.hand) == 0 and len(H.lib) == 5
@check("Dying to your own payments ends the game as a loss")
def _():
    G = lgame(perms=["Dark Confidant"], lib=("Wastes", "Phyrexian Arena"), life=3); G.fire("upkeep")
    return G.died == 3 and G.life <= 0
@check("Bracket 4 floor 10: shockland pays at 12, Phyrexian life at 12; the floor resets to 20")
def _():
    g.LIFE_FLOOR = 10
    try:
        G = lgame(life=12); G.land_enters(LK["Watery Grave"])
        H = lgame(hand=["Gitaxian Probe"], life=12); H.build_pool(); ok = H.try_cast(LK["Gitaxian Probe"], "hand")
        return G.life == 10 and not G.lands[0].tapped and ok and H.life == 10
    finally: g.LIFE_FLOOR = 20
@check("Drawing from an empty library loses; Laboratory Maniac wins instead")
def _():
    G = lgame(lib=()); G.draw(1)
    H = lgame(perms=["Laboratory Maniac"], lib=()); H.draw(1)
    return G.died == 3 and G.death == "decked" and not G.won and LK["Laboratory Maniac"].labman and H.won == 3 and not H.died
@check("A draw that fits the library is fine; drawing 2 from 1 still loses")
def _():
    G = lgame(lib=("Wastes",)); G.draw(1); H = lgame(lib=("Wastes",)); H.draw(2)
    return not G.died and H.death == "decked"
@check("Thassa's Oracle: held until devotion covers the library, then wins on entering")
def _():
    k = LK["Thassa's Oracle"]
    G = lgame(hand=["Thassa's Oracle"], lands=["Island"] * 2, lib=("Wastes",) * 5); G.build_pool(); held = not G.try_cast(k, "hand")
    H = lgame(hand=["Thassa's Oracle"], lands=["Island"] * 2, lib=("Wastes",) * 2); H.build_pool(); ok = H.try_cast(k, "hand")
    return k.status == "modeled" and k.requires == "oracle" and held and ok and H.won == 3

# ---- correctness pass (2026-09-30, session 2): costs before 'If you do', pod searches, converge, keywords, leftovers
XNAMES = ["Formidable Speaker", "Birthing Pod", "Eldritch Evolution", "Grizzly Bears", "Centaur Courser", "Craw Wurm", "Hill Giant",
          "Suntouched Myr", "Painful Truths", "Bloodbraid Elf", "Forest", "Mountain", "Plains", "Wastes", "Island", "Swamp",
          "Kenrith's Transformation", "Tear Asunder", "Aegis Sculptor", "Frantic Search", "Swords to Plowshares",
          "Gray Merchant of Asphodel", "Mox Opal", "Sol Ring", "Soulstinger", "Etched Oracle", "Glen Elendra Guardian",
          "Thought Scour", "Riveteers Overlook", "Mask of Memory", "Sign in Blood", "Pippin's Bravery", "Stargaze",
          "Culling Ritual", "Everflowing Chalice", "Brain Freeze", "Tezzeret, Master of the Bridge", "Exotic Disease", "Storm the Citadel",
          "Casting of Bones", "Liliana's Specter", "Cabal Coffers", "Elvish Archdruid", "Llanowar Elves", "Enigmatic Incarnation",
          "Krenko, Mob Boss", "Brightstone Ritual", "Relic of Sauron", "Return of the Wildspeaker", "Goblin Instigator",
          "Earthshaker Dreadmaw", "Orcish Lumberjack", "Kozilek, the Great Distortion"]
XRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(XNAMES)}
XK = {n: g.compile_card(XRAW[n], g.ALL5) for n in XNAMES}

def xgame(lands=(), perms=(), hand=(), lib=(), life=40):
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in XNAMES if n != "Grizzly Bears"], ["Grizzly Bears"], args, [], XK, g.ALL5)
    G = g.Game(sim, [XK[n] for n in hand], [XK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3; G.turns_left = g.OPP_N; G.life = life; G.cmd = []
    G.lands = [g.Perm(XK[n]) for n in lands]; G.perms = [g.Perm(XK[n]) for n in perms]; G._st = None
    return G

@check("'You may discard a card. If you do, search': no card in hand, no tutor; with one, the worst card goes (Formidable Speaker)")
def _():
    e = XK["Formidable Speaker"].etb
    G = xgame(lib=["Craw Wurm", "Hill Giant"]); G.do(e, XK["Formidable Speaker"])
    H = xgame(hand=["Wastes"], lib=["Craw Wurm", "Hill Giant"]); H.do(e, XK["Formidable Speaker"])
    return e[0][0] == "ifdo" and e[0][1][0] == "discard" and G.hand == [] and len(G.lib) == 2 \
        and len(H.hand) == 1 and H.hand[0].name in ("Craw Wurm", "Hill Giant") and [c.name for c in H.gy] == ["Wastes"]
@check("An unread cost before 'If you do' drops the effect instead of making it free (Aegis Sculptor's upkeep counter)")
def _(): return not XK["Aegis Sculptor"].trig and XK["Aegis Sculptor"].status == "partial"
@check("'If you do ... Otherwise': the unpaid branch only when the cost isn't paid (Pippin's Bravery)")
def _():
    e = XK["Pippin's Bravery"].spell[0]
    return e[0] == "ifdo" and e[2][0][:4] == ("pump", "target", 4, 4) and e[3][0][2:4] == (2, 2)
@check("Birthing Pod: a 2-drop finds only a 3-drop (never the 4- or 6-drop), onto the battlefield")
def _():
    G = xgame(perms=["Birthing Pod", "Grizzly Bears"], lands=["Forest"] * 3, lib=["Craw Wurm", "Centaur Courser", "Hill Giant"])
    G.sim.commanders = []; G.build_pool(); ok = G.try_act(G.perms[0], XK["Birthing Pod"].acts[0], False, 0, False)
    return ok and sorted(p.k.name for p in G.perms) == ["Birthing Pod", "Centaur Courser"] and len(G.lib) == 2
@check("Pod fodder needs a target one MV up: Centaur Courser (3) is podded into nothing when the library has no 4")
def _():
    G = xgame(perms=["Birthing Pod", "Centaur Courser"], lands=["Forest"] * 3, lib=["Craw Wurm", "Grizzly Bears"]); G.sim.commanders = []
    return G.pick_fodder(XK["Birthing Pod"].acts[0]["fodder"], G.perms[0], XK["Birthing Pod"].acts[0]["fx"]) is None
@check("Eldritch Evolution: sacrifice a 2-drop, the creature (MV <= 4) enters the battlefield, the 6-drop stays")
def _():
    k = XK["Eldritch Evolution"]; t = k.spell[0]
    G = xgame(perms=["Centaur Courser"], lib=["Craw Wurm", "Hill Giant"]); G.sim.commanders = []
    G.ctx_obj = G.perms[0]; G.do(k.spell, k)
    return t[2] == "bf" and g.rel_mv(t[1]) == ("<=", 2) and any(p.k.name == "Hill Giant" for p in G.perms) and len(G.lib) == 1
@check("Sunburst: three colors -> a 3/3 Suntouched Myr; colorless only -> 0 counters, it dies (CR 704.5f)")
def _():
    k = XK["Suntouched Myr"]
    G = xgame(hand=["Suntouched Myr"], lands=["Forest", "Mountain", "Plains"]); G.build_pool(); G.try_cast(k, "hand")
    H = xgame(hand=["Suntouched Myr"], lands=["Wastes"] * 3); H.build_pool(); H.try_cast(k, "hand")
    m = [p for p in G.perms if p.k is k]
    return len(m) == 1 and G.stats(m[0])[:2] == (3, 3) and not any(p.k is k for p in H.perms) and k in H.gy
@check("Converge counts colors spent: Painful Truths paid B+G+R draws 3 and loses 3; B+C+C draws 1")
def _():
    k = XK["Painful Truths"]
    G = xgame(hand=["Painful Truths"], lands=["Swamp", "Forest", "Mountain"], lib=["Wastes"] * 5); G.build_pool(); G.try_cast(k, "hand")
    H = xgame(hand=["Painful Truths"], lands=["Swamp", "Wastes", "Wastes"], lib=["Wastes"] * 5); H.build_pool(); H.try_cast(k, "hand")
    return len(G.hand) == 3 and G.life == 37 and len(H.hand) == 1 and H.life == 39
@check("Cascade: Bloodbraid Elf skips lands and the 6-drop, casts the first nonland card with MV < 4 free")
def _():
    k = XK["Bloodbraid Elf"]
    G = xgame(hand=["Bloodbraid Elf"], lands=["Forest", "Mountain", "Forest", "Mountain"], lib=["Hill Giant", "Centaur Courser", "Forest", "Craw Wurm"])
    G.build_pool(); G.try_cast(k, "hand")
    return sorted(p.k.name for p in G.perms) == ["Bloodbraid Elf", "Centaur Courser"] and len(G.lib) == 3
@check("Keywords aren't silently read: Brain Freeze notes storm; Kenrith's Transformation's 'Enchanted creature' line is unmodeled")
def _():
    return any("storm" in n for n in XK["Brain Freeze"].notes) and XK["Kenrith's Transformation"].status == "partial"
@check("Leftover detector: Stargaze's dig is an unread part; Swords' 'its controller gains' isn't; Frantic Search's untap is read now")
def _():
    return XK["Frantic Search"].status == "modeled" and XK["Stargaze"].status == "partial" and XK["Swords to Plowshares"].status == "held" \
        and not any(n.startswith("unread part") for n in XK["Swords to Plowshares"].notes)
@check("Gray Merchant: devotion to black counts its own pips and Liliana's Specter's (4); you gain the 12 life lost")
def _():
    G = xgame(perms=["Liliana's Specter"]); G.enter(XK["Gray Merchant of Asphodel"])
    return lives(G) == [36] * 3 and G.life == 52
@check("Mox Opal: no mana with two artifacts, one with three")
def _():
    G = xgame(perms=["Mox Opal", "Sol Ring"]); G.build_pool(); a = free_units(G)
    H = xgame(perms=["Mox Opal", "Sol Ring", "Everflowing Chalice"]); H.build_pool(); b = free_units(H)
    return a == 2 and b == 3
@check("Soulstinger's -1/-1 counters on your own creature go where they hurt least (Soulstinger itself over a 2/2)")
def _():
    G = xgame(perms=["Grizzly Bears"]); G.sim.commanders = []; p = G.enter(XK["Soulstinger"])
    return G.stats(p)[:2] == (2, 3) and G.stats(G.perms[0])[:2] == (2, 2)
@check("Counter costs read past 'three': Etched Oracle removes four +1/+1 counters; 'Its controller draws' isn't yours (Glen Elendra)")
def _():
    a = XK["Etched Oracle"].acts[0]
    return a["rm"] == ("+1/+1", 4) and not any(e[0] == "draw" for e in g.all_fx(XK["Glen Elendra Guardian"]))
@check("'Target player mills': yourself only with a graveyard payoff (none here: Thought Scour mills nobody)")
def _():
    G = xgame(lib=["Wastes"] * 20); G.do(XK["Thought Scour"].spell, XK["Thought Scour"])
    return len(G.gy) == 0 and len(G.hand) == 1
@check("Riveteers Overlook fetches a basic of its types, tapped, and leaves")
def _():
    G = xgame(lib=["Swamp", "Island"]); G.land_enters(XK["Riveteers Overlook"])
    return [p.k.name for p in G.lands] == ["Swamp"] and G.lands[0].tapped and XK["Riveteers Overlook"] in G.gy
@check("Reads fixed: Sign in Blood loses 2; Tezzeret's +2 gains X = artifacts; Exotic Disease gains domain; Casting of Bones discards")
def _():
    return ("life", -2) in XK["Sign in Blood"].spell and any(e == ("life", ("artifacts",)) for _, fx in XK["Tezzeret, Master of the Bridge"].pw for e in fx) \
        and ("life", ("domain",)) in XK["Exotic Disease"].spell and ("discard", 1) in XK["Casting of Bones"].trig[0][2]
@check("Quoted granted text isn't the card's interaction: Storm the Citadel is a pump, not held removal")
def _(): return not XK["Storm the Citadel"].hold and XK["Storm the Citadel"].alpha
@check("'For each Swamp / Elf you control' counts lands and creatures of the subtype (Cabal Coffers, Elvish Archdruid)")
def _():
    G = xgame(lands=["Cabal Coffers", "Swamp", "Swamp"], perms=["Elvish Archdruid", "Llanowar Elves"])
    return G.val(XK["Cabal Coffers"].dyn_mana, G.lands[0], 0) == 2 and G.val(XK["Elvish Archdruid"].dyn_mana, G.perms[0], 0) == 2
@check("Culling Ritual's mana 'for each permanent destroyed' is never read as one {B}")
def _(): return not any(e[0] == "mana" for e in XK["Culling Ritual"].spell)

@check("'X, where X is ...' reads the clause, not the ability's X: Krenko makes one Goblin per Goblin (3 with 2 others)")
def _():
    G = xgame(perms=["Krenko, Mob Boss", "Goblin Instigator"])
    G.make_tokens(XK["Krenko, Mob Boss"].acts[0]["fx"][0], 1)
    G.do(XK["Krenko, Mob Boss"].acts[0]["fx"], XK["Krenko, Mob Boss"], G.perms[0])
    return sum(1 for p in G.perms if p.k.token) == 1 + 3
@check("Rituals that count: Brightstone Ritual adds R per Goblin; 'two mana in any combination of {U}, {B}, and/or {R}' is two")
def _():
    e = XK["Brightstone Ritual"].spell[0]
    G = xgame(perms=["Krenko, Mob Boss", "Goblin Instigator"]); G.build_pool(); G.do([e], XK["Brightstone Ritual"])
    return e[0] == "mana_n" and XK["Brightstone Ritual"].ritual and free_units(G) == 2 and len(XK["Relic of Sauron"].units) == 2
@check("Counts keep their qualifiers: non-Human greatest power (Wildspeaker), other Dinosaurs (Dreadmaw); unreadable ones stay unread (Kozilek)")
def _():
    return XK["Return of the Wildspeaker"].spell == [("draw", ("power", "Human"))] and XK["Earthshaker Dreadmaw"].etb == [("draw", ("sub_other", "Dinosaur"))] \
        and not XK["Kozilek, the Great Distortion"].castfx
@check("Land fodder isn't read as a sac outlet (Orcish Lumberjack stays unread rather than never firing)")
def _(): return not XK["Orcish Lumberjack"].sac_outlets and XK["Orcish Lumberjack"].status == "blank"

# ---- priority cards (2026-09-30, session 2): token/trigger doublers, chosen type, moxen, BMC, land fodder
PNAMES = ["Krenko, Mob Boss", "Goblin Instigator", "Goblin Warchief", "Mountain", "Forest", "Swamp", "Island", "Plains",
          "Doubling Season", "Parallel Lives", "Panharmonicon", "Teysa Karlov", "Blood Artist", "Herald's Horn", "Chrome Mox",
          "Mox Diamond", "Black Market Connections", "Harrow", "Chaos Warp", "Morbid Opportunist", "Grizzly Bears",
          "Lightning Bolt", "Mulldrifter", "Sol Ring", "Siege-Gang Commander", "Llanowar Elves", "Welcoming Vampire",
          "Windreader Sphinx", "Serra Angel", "Craw Wurm", "Trespasser's Curse", "History of Benalia", "Urza's Saga",
          "Mox Opal", "Sol Ring", "Everflowing Chalice", "Ophiomancer", "Gorehorn Raider", "Garruk's Uprising", "Valakut, the Molten Pinnacle",
          "Helm of the Host", "Kiki-Jiki, Mirror Breaker", "Skyclave Relic", "Second Harvest", "Smothering Tithe",
          "Oko, the Ringleader", "Dwynen's Elite", "Approach of the Second Sun", "Frantic Search", "Mana Vault",
          "Sensei's Divining Top", "Orcish Bowmasters", "Reclamation Sage", "Guardian Project"]
PRAW = {c["name"]: c for c in json.load(open("data/trimmed_scryfall_v2.json", encoding="utf-8")) if c["name"] in set(PNAMES)}
g.CHOSEN_TYPE = g.chosen_type([PRAW["Krenko, Mob Boss"]], [PRAW[n] for n in ("Goblin Instigator", "Goblin Warchief", "Siege-Gang Commander")])
PK = {n: g.compile_card(PRAW[n], g.ALL5) for n in PNAMES}
g.CHOSEN_TYPE = None

def pgame(lands=(), perms=(), hand=(), lib=("Mountain",) * 10, life=40):
    args = argparse.Namespace(order=g.ORDER_DEFAULT, draw=False, kill_commander=0, cast_interaction=False)
    sim = g.Sim([n for n in PNAMES if n != "Krenko, Mob Boss"], ["Krenko, Mob Boss"], args, [], PK, g.ALL5)
    G = g.Game(sim, [PK[n] for n in hand], [PK[n] for n in lib], random.Random(1))
    G.turn = 3; G.phase = 3; G.turns_left = g.OPP_N; G.life = life; G.cmd = []
    G.lands = [g.Perm(PK[n]) for n in lands]; G.perms = [g.Perm(PK[n]) for n in perms]; G._st = None
    return G

@check("Token doublers stack: Doubling Season + Parallel Lives turn one Goblin into four")
def _():
    G = pgame(perms=["Doubling Season", "Parallel Lives"]); G.make_tokens(PK["Krenko, Mob Boss"].acts[0]["fx"][0], 1)
    return sum(1 for p in G.perms if p.k.token) == 4
@check("Panharmonicon doubles a creature's ETB (Mulldrifter draws 4); Teysa doubles dies triggers (Blood Artist drains twice)")
def _():
    G = pgame(perms=["Panharmonicon"]); G.enter(PK["Mulldrifter"])
    H = pgame(perms=["Teysa Karlov", "Blood Artist", "Grizzly Bears"]); H.leave(H.perms[2], "dies")
    return len(G.hand) == 4 and sorted(o["life"] for o in H.opps) == [38, 40, 40]
@check("The chosen type is the deck's tribe: Herald's Horn reduces Goblins and takes a Goblin off the top")
def _():
    k = PK["Herald's Horn"]
    G = pgame(perms=["Herald's Horn"], lib=["Mountain", "Goblin Instigator"]); G.fire("upkeep")
    return g.CHOSEN_TYPE is None and any(s_[0] == "reduce" and "Goblin" in s_[1]["sub"] for s_ in k.statics) \
        and [c.name for c in G.hand] == ["Goblin Instigator"]
@check("Chrome Mox imprints the least useful colored card and taps for its colors; with no card it makes nothing")
def _():
    G = pgame(hand=["Lightning Bolt", "Mulldrifter"], lands=["Island"]); p = G.enter(PK["Chrome Mox"])
    H = pgame(hand=["Sol Ring"]); q = H.enter(PK["Chrome Mox"])
    return p.imp == frozenset("R") and [c.name for c in G.exile] == ["Lightning Bolt"] and q.imp is None
@check("Mox Diamond: castable only with a spare land, which it discards; one land and a drop left: not cast")
def _():
    G = pgame(hand=["Mox Diamond", "Forest", "Island"]); G.drops = 1
    H = pgame(hand=["Mox Diamond", "Forest"]); H.drops = 1
    ok = G.has("spare_land", PK["Mox Diamond"]); G.enter(PK["Mox Diamond"])
    return ok and not H.has("spare_land", PK["Mox Diamond"]) and len(G.hand) == 2 and any(c.is_land for c in G.gy)
@check("Black Market Connections: each mode on its own, skipped when its life cost crosses the floor")
def _():
    fx = PK["Black Market Connections"].trig[0][2]
    G = pgame(life=40); G.do(fx, PK["Black Market Connections"])
    H = pgame(life=22); H.do(fx, PK["Black Market Connections"])
    return G.life == 34 and len(G.hand) == 1 and H.life == 20 and len(H.hand) == 1 and PK["Black Market Connections"].trig[0][0] == "main1"
@check("Harrow sacrifices a tapped land as its cost and fetches two basics untapped")
def _():
    G = pgame(lands=["Forest", "Forest", "Swamp"], hand=["Harrow"], lib=["Island", "Plains", "Mountain"])
    G.build_pool(); ok = G.try_cast(PK["Harrow"], "hand")
    return ok and len(G.lands) == 4 and sum(not q.tapped for q in G.lands) == 2 and any(c.name in ("Forest", "Swamp") for c in G.gy)
@check("Chaos Warp is held removal of any permanent; Morbid Opportunist draws once per batch")
def _():
    k = PK["Chaos Warp"]
    G = pgame(perms=["Morbid Opportunist", "Grizzly Bears", "Llanowar Elves"]); G.leave(G.perms[1], "dies"); G.leave(G.perms[1], "dies")
    return k.hold and k.kill >= {"artifact", "creature", "enchantment"} and len(G.hand) == 1

@check("Trigger filters keep their qualifiers: Welcoming Vampire (power 2 or less, once a turn), Windreader Sphinx (with flying); an 'enchanted player' curse is unread")
def _():
    G = pgame(perms=["Welcoming Vampire"]); G.enter(PK["Llanowar Elves"]); G.enter(PK["Grizzly Bears"]); G.enter(PK["Craw Wurm"])
    H = pgame(perms=["Windreader Sphinx", "Serra Angel", "Grizzly Bears"]); H.fire("attack", H.perms[2]); H.fire("attack", H.perms[1])
    return len(G.hand) == 1 and len(H.hand) == 1 and not PK["Trespasser's Curse"].trig

@check("Sagas (CR 714): History of Benalia makes a Knight on entering and next turn, pumps on III and is sacrificed; Doubling Season skips a chapter")
def _():
    G = pgame(); p = G.enter(PK["History of Benalia"]); a = sum(1 for q in G.perms if q.k.token)
    G.add_lore(p, 1); b = sum(1 for q in G.perms if q.k.token)
    G.add_lore(p, 1); gone = p not in G.perms and PK["History of Benalia"] in G.gy
    H = pgame(perms=["Doubling Season"]); q = H.enter(PK["History of Benalia"])
    return (a, b) == (1, 2) and gone and q.ctr["lore"] == 2 and sum(1 for r in H.perms if r.k.token) == 2 * 2
@check("Urza's Saga: taps for {C}, finds a 0-1 MV artifact on III onto the battlefield, then it's gone (a land lost)")
def _():
    G = pgame(lib=["Mountain", "Sol Ring", "Mountain"]); G.land_enters(PK["Urza's Saga"])
    p = G.lands[0]; G.add_lore(p, 1); G.add_lore(p, 1)
    return PK["Urza's Saga"].units and any(q.k.name == "Sol Ring" for q in G.perms) and not G.lands and PK["Urza's Saga"] in G.gy

@check("Intervening 'if' read: Ophiomancer only without a Snake; raid only after attacking; Garruk's Uprising needs power 4; Valakut counts 'other'")
def _():
    G = pgame(perms=["Ophiomancer"]); G.fire("upkeep"); G.fire("upkeep")
    a = sum(1 for q in G.perms if "Snake" in q.k.subtypes)
    H = pgame(); H.enter(PK["Gorehorn Raider"]); b = [o["life"] for o in H.opps]
    I = pgame(perms=["Grizzly Bears"]); I.attacked.add(I.perms[0]); I.enter(PK["Gorehorn Raider"]); c = sum(o["life"] for o in I.opps)
    J = pgame(perms=["Grizzly Bears"]); J.enter(PK["Garruk's Uprising"]); K_ = pgame(perms=["Craw Wurm"]); K_.enter(PK["Garruk's Uprising"])
    v = [t for t in PK["Valakut, the Molten Pinnacle"].trig if t[0] == "etb"][0][2][0][1]
    return a == 1 and b == [40] * 3 and c == 118 and len(J.hand) == 0 and len(K_.hand) == 1 and v[0] == "pcount" and v[2] == 6

@check("Token copies: Helm of the Host copies the equipped Mulldrifter (its ETB draws 2); Kiki-Jiki's copy has haste and is sacrificed at end step")
def _():
    G = pgame(perms=["Mulldrifter"]); q = g.Perm(PK["Helm of the Host"]); q.att = G.perms[0]; G.perms.append(q); G._st = None
    G.fire("combat_begin")
    H = pgame(perms=["Kiki-Jiki, Mirror Breaker", "Mulldrifter"], lands=["Mountain"] * 2); H.sim.commanders = []
    H.build_pool(); ok = H.try_act(H.perms[0], PK["Kiki-Jiki, Mirror Breaker"].acts[0], False, 0, False)
    cp = [p for p in H.perms if p.k.token]
    tok = cp[0] if cp else None
    H.pool = None; H.fire("end")
    for q_, fate in H.eot:
        if q_ in H.perms: H.leave(q_, "end", sac=True)
    return len(G.hand) == 2 and sum(1 for p in G.perms if p.k.token) == 1 and ok and tok is not None and tok.k.haste \
        and len(H.hand) == 2 and tok not in H.perms

@check("An unreadable 'If' drops its effect (Approach of the Second Sun never wins; Oko's 'Otherwise' goes with it); the tax clause stays (Smothering Tithe)")
def _():
    oko = [fx for c_, fx in PK["Oko, the Ringleader"].pw if c_ == 1][0]
    return not any(e[0] == "win" for e in g.all_fx(PK["Approach of the Second Sun"])) and PK["Approach of the Second Sun"].status != "modeled" \
        and oko == [("draw", 2)] and PK["Smothering Tithe"].trig and PK["Smothering Tithe"].status == "modeled"
@check("Kicker: paid when the pool covers it (Skyclave Relic makes its copies only kicked); multikicker counts (Everflowing Chalice x2 at 4 mana)")
def _():
    G = pgame(hand=["Skyclave Relic"], lands=["Mountain"] * 3); G.build_pool(); G.try_cast(PK["Skyclave Relic"], "hand")
    H = pgame(hand=["Skyclave Relic"], lands=["Mountain"] * 6); H.build_pool(); H.try_cast(PK["Skyclave Relic"], "hand")
    I = pgame(hand=["Everflowing Chalice"], lands=["Mountain"] * 4); I.build_pool(); I.try_cast(PK["Everflowing Chalice"], "hand")
    ch = [q for q in I.perms if q.k.name == "Everflowing Chalice"]
    return sum(1 for q in G.perms if "Skyclave" in q.k.name) == 1 and sum(1 for q in H.perms if "Skyclave" in q.k.name) == 3 \
        and ch and ch[0].ctr.get("charge") == 2
@check("Second Harvest copies each token; Dwynen's Elite needs another Elf; 'if you cast it' is false for a creature put onto the battlefield")
def _():
    G = pgame(perms=["Grizzly Bears"]); G.make_tokens(PK["Krenko, Mob Boss"].acts[0]["fx"][0], 2); G.do(PK["Second Harvest"].spell, PK["Second Harvest"])
    H = pgame(); H.enter(PK["Dwynen's Elite"]); I = pgame(perms=["Llanowar Elves"]); I.enter(PK["Dwynen's Elite"])
    return sum(1 for q in G.perms if q.k.token) == 4 and sum(1 for q in H.perms if q.k.token) == 0 and sum(1 for q in I.perms if q.k.token) == 1

@check("Frantic Search untaps 3 lands; Mana Vault pings only while tapped; Top goes back on top; Bowmasters amasses a 1/1 Army")
def _():
    G = pgame(lands=["Island"] * 3); G.build_pool(); G.pay(None, 3, []); G.do(PK["Frantic Search"].spell, PK["Frantic Search"])
    H = pgame(perms=["Mana Vault"]); H.perms[0].tapped = True; H.fire("drawstep"); I = pgame(perms=["Mana Vault"]); I.fire("drawstep")
    J = pgame(perms=["Sensei's Divining Top"]); J.do(PK["Sensei's Divining Top"].acts[1]["fx"], PK["Sensei's Divining Top"], J.perms[0])
    K_ = pgame(); K_.enter(PK["Orcish Bowmasters"]); arm = [q for q in K_.perms if "Army" in q.k.subtypes]
    return sum(1 for q in G.lands if not q.tapped) == 3 and H.life == 39 and I.life == 40 and J.lib[-1].name == "Sensei's Divining Top" \
        and not J.perms and len(arm) == 1 and K_.stats(arm[0])[:2] == (1, 1)
@check("Reclamation Sage's ETB removes a live artifact tax piece; Guardian Project draws only for a new name")
def _():
    G = pgame(); G.turn = 5; G.stax = [{"kind": "taxall", "start": 4, "until": 7, "on": True}]; G.enter(PK["Reclamation Sage"])
    H = pgame(perms=["Guardian Project"]); H.enter(PK["Grizzly Bears"]); H.enter(PK["Grizzly Bears"])
    return not G.stax[0]["on"] and len(H.hand) == 1

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
