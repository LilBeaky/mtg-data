#!/usr/bin/env python3
"""Smoke test for mtg-data: runs every tool against tests/test_deck.txt (plus a few tiny
throwaway decks) and checks exit codes, crashes, and expected output.

  python3 tests/smoke.py                 # failures + one-line summary; exit 1 on any failure
  python3 tests/smoke.py --verbose       # also list every passing check
  python3 tests/smoke.py --status FILE   # also record pass/fail in FILE (written only when
                                         # the result changes, so passing days commit nothing)

Each check lists `must` / `must_not` substrings. Checks marked `data=True` depend on the
card data (bans, Game Changer list, Spellbook). A failure there may be a real-world change
rather than a bug: confirm, then update this file. mtg.py prints a warning in every session
while the recorded status is "fail".
"""
import datetime, json, os, subprocess, sys, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECK = "tests/test_deck.txt"
PY = sys.executable
TMP = tempfile.mkdtemp(prefix="smoke-")

def tmp_deck(name, commanders, deck):
    p = os.path.join(TMP, name + ".txt")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("Commander\n" + "".join(f"1 {c}\n" for c in commanders) + "Deck\n" + deck + "\n")
    return p

def deck_without_fake():
    p = os.path.join(TMP, "no_fake.txt")
    with open(os.path.join(REPO, DECK), encoding="utf-8") as src, open(p, "w", encoding="utf-8") as out:
        out.writelines(l for l in src if "Totally Fake Card Name" not in l)
    return p

def S(*args): return ["scripts/" + args[0]] + list(args[1:])

MECH = "tests/goldfish_mech_deck.txt"
COMBAT = "tests/goldfish_combat_deck.txt"
FOOD = "tests/goldfish_food_deck.txt"

def checks():
    nofake = deck_without_fake()
    return [
        # ---- mtg.py deck: parsing, legality, identity, commanders
        dict(name="deck check", cmd=S("mtg.py", "deck", DECK),
             must=["99 found + 1 NOT FOUND", "CI BRUW", "NOT FOUND: Totally Fake Card Name",
                   "COLOR IDENTITY: Kitchen Finks [GW]", "COLOR IDENTITY: Forest [G]",
                   "NOT_LEGAL: Knight of the Kitchen Sink", "MELD RESULT: Brisela",
                   "SINGLETON: 2x Sol Ring", "COMPANION (Obosh", "Card That Is Not In The Deck",
                   "Ghal Maraz, the Great Shatterer -> Loxodon Warhammer", "lands: 31"],
             must_not=["COMMANDER:", "COMMANDER PAIR", "DECK SIZE", "Falling Star", "Lutri",
                       "Relentless Rats", "SINGLETON: 2x Seven", "SINGLETON: 2x Persistent",
                       "SINGLETON: 2x Snow", "COLOR IDENTITY: Pontiff", "COLOR IDENTITY: Phyrexian Infiltrator",
                       "partial match", "Traceback"]),
        dict(name="deck check (data)", data=True, cmd=S("mtg.py", "deck", DECK),
             must=["BANNED: Mana Crypt", "Game Changers (3)", "Demonic Consultation + Thassa's Oracle"]),
        # ---- commander rules on throwaway decks
        dict(name="bad partner pair", cmd=S("mtg.py", "deck", tmp_deck("pair_bad", ["Kraum, Ludevic's Opus", "Halsin, Emerald Archdruid"], "98 Island")),
             must=["COMMANDER PAIR"]),
        dict(name="background pair", cmd=S("mtg.py", "deck", tmp_deck("pair_bg", ["Halsin, Emerald Archdruid", "Dungeon Delver"], "98 Forest")),
             must_not=["COMMANDER", "DECK SIZE"]),
        dict(name="partner-with pair", cmd=S("mtg.py", "deck", tmp_deck("pair_with", ["Pir, Imaginative Rascal", "Toothy, Imaginary Friend"], "98 Island")),
             must_not=["COMMANDER", "DECK SIZE"]),
        dict(name="doctor pair", cmd=S("mtg.py", "deck", tmp_deck("pair_doc", ["Nyssa of Traken", "The Eighth Doctor"], "98 Island")),
             must_not=["COMMANDER", "DECK SIZE"]),
        dict(name="ineligible commander", cmd=S("mtg.py", "deck", tmp_deck("inelig", ["Sol Ring"], "99 Wastes")),
             must=["can't be a commander"]),
        dict(name="three commanders + size", cmd=S("mtg.py", "deck", tmp_deck("three", ["Kraum, Ludevic's Opus", "Tymna the Weaver", "Thrasios, Triton Hero"], "96 Island")),
             must=["maximum is 2", "DECK SIZE: 99"]),
        # ---- name lookups that have broken before
        dict(name="name traps", cmd=S("mtg.py", "card", "Rampant Growth", "Brainstorm", "Æther Vial",
                                       "stroke of genius", "Thassa’s Oracle", "Westvale Abbey / Ormendahl, Profane Prince", "The Cloudsea Djinn", "--brief"),
             must=["Rampant Growth {1}{G}", "Brainstorm {U}", "Aether Vial {1}", "Stroke of Genius {X}{2}{U}",
                   "Thassa's Oracle {U}{U}", "Westvale Abbey // Ormendahl", "Nyxbloom Ancient {4}{G}{G}{G}",
                   "reskin: 'The Cloudsea Djinn' is this card"],
             must_not=["NOT FOUND", "ambiguous", "Studious", "Harmonized"]),
        dict(name="rules", cmd=S("mtg.py", "rule", "702.124h"), must=["Partner"]),
        dict(name="rules current", cmd=S("mtg.py", "rule", "--grep", "prepare spell"), must=["722."]),
        dict(name="search", cmd=S("mtg.py", "search", "--ci", "UB", "--tag", "removal", "--cmc", "1-2", "--limit", "3")),
        dict(name="gc list", cmd=S("mtg.py", "gc")),
        dict(name="search gc + price", cmd=S("mtg.py", "search", "--gc", "--max-price", "5", "--limit", "3"), must=["prices as of"]),
        dict(name="combos by bracket", cmd=S("mtg.py", "combos", "Thassa's Oracle", "--bracket", "3"), must=["Ruthless→B4"]),
        dict(name="rulings grep", cmd=S("mtg.py", "rulings", "Plaza of Heroes", "--grep", "legendary")),
        dict(name="card -f batch", cmd=S("mtg.py", "card", "-f", MECH, "--brief"),
             must=["Nyxbloom Ancient", "Dracogenesis", "reskin: 'The Cloudsea Djinn' is this card"],
             must_not=["NOT FOUND"]),
        dict(name="combos", cmd=S("mtg.py", "combos", "Thassa's Oracle")),
        dict(name="rulings", cmd=S("mtg.py", "rulings", "Plaza of Heroes")),
        dict(name="tags", cmd=S("mtg.py", "tags", "Sol Ring")),
        # ---- audit
        dict(name="audit", cmd=S("audit.py", DECK, "--no-edhrec"),
             must=["## 2. Mana base", "on-curve colors flagged", "## 3. Commander on curve", "## 4b. Packages", "K-SENSITIVE",
                   "## 7. Manual checklist", "MDFC land backs (2", "not counted (restricted mana", "Cavern of Souls",
                   "extra-turn cards", "Time Warp", "possible MLD", "Armageddon", "parts share cards",
                   "Comprehensive Rules file is dated", "T6 with tutors", "each package's pieces and the tutors",
                   "## 4c. Tutors & key cards", "headline:", "Biggest dependency", "Weakest tutor, played (4c.7)",
                   "best case vs played by T6", "### 4c.1 Tutors", "### 4c.5 Key cards", "### 4c.8 Tutors to add"],
             must_not=["Colors aren't modeled", "Traceback", "more under threshold", "tutors.py failed"]),
        dict(name="audit flags", cmd=S("audit.py", DECK, "--no-edhrec", "--no-lists", "--k", "ramp=9", "--bracket", "4", "--no-tutors"),
             must=["skipped (--no-tutors)", "confirmed overrides: ramp=9", "bracket target 4", "one card away:", "full list: mtg.py near", "land base (landbase.py", "recommendation: ", "cards under their color threshold"]),
        dict(name="audit + EDHREC", cmd=S("audit.py", DECK, "--snapshot", "snapshots/yusri-fortunes-flame__all__2026-09-25.txt"),
             must=["## 6. EDHREC", "EDHREC snapshot: Yusri"]),
        # ---- one card away (mtg.py near; Hermit Druid is green, off the Kraum + Tymna identity)
        dict(name="near combos", data=True, cmd=S("mtg.py", "near", DECK, "--limit", "60"),
             must=["Tainted Pact $", "completes a 2-card combo ⚠ above target B3", "CI BRUW"],
             must_not=["Hermit Druid", "Traceback"]),
        dict(name="near price cap", data=True, cmd=S("mtg.py", "near", DECK, "--max-price", "1"),
             must=["over price"], must_not=["Tainted Pact $"]),
        # ---- landbase (utility lands are never cut; candidates are plain mana lands only)
        dict(name="landbase", data=True, cmd=S("landbase.py", DECK, "--max-price", "2", "--swaps", "2"),
             must=["## 1. Land count", "← current", "recommendation: 35 lands (+4 from now)", "+ Command Tower $",
                   "never cut (utility lands", "Cavern of Souls", "## 4. Before → after", "cards under their color threshold: 47 →"],
             must_not=["+ Plaza of Heroes", "→ Shimmering Grotto", "Traceback"]),
        dict(name="landbase cuts", cmd=S("landbase.py", DECK, "--lands", "29", "--no-swaps"),
             must=["planning for 29 lands", "cut 2 land(s), and add 2 nonland card(s)", "lands 31 → 29"],
             must_not=["− Cavern of Souls", "− Mystic Gate", "swaps (", "Traceback"]),
        dict(name="landbase with-draw", cmd=S("landbase.py", DECK, "--with-draw", "--no-swaps", "--no-ramp-pick", "--trials", "300"),
             must=["## 1. Land count", "recommendation: "], must_not=["Traceback"]),
        dict(name="landbase no-sim", cmd=S("landbase.py", DECK, "--no-sim", "--no-swaps"),
             must=["ramp counted (--no-sim)", "recommendation: "], must_not=["Traceback"]),
        # ---- manasim (ramp turn by turn; a cost reducer counts for the commander it matches)
        dict(name="manasim", cmd=S("manasim.py", DECK, "--trials", "300"),
             must=["## 1. Development", "## 2. Castable by", "with ramp", "lands only", "+draw, tutors", "## 3. Coverage",
                   "Sol Ring: +2 C"],
             must_not=["Traceback"]),
        dict(name="manasim line", cmd=S("manasim.py", tmp_deck("klauth_line", ["Klauth, Unrivaled Ancient"],
                                                             "1 Rampant Growth\n1 Dragonspeaker Shaman\n1 Terror of the Peaks\n"
                                                             "1 Shamanic Revelation\n30 Forest\n30 Mountain"),
                                        "--turns", "5", "--hand", "Forest; Mountain; Forest; Rampant Growth; Dragonspeaker Shaman; "
                                        "Terror of the Peaks; Shamanic Revelation", "--draws", "Mountain; Forest; Mountain; Forest"),
             must=["cast Rampant Growth", "cast Dragonspeaker Shaman", "Klauth, Unrivaled Ancient: first castable T4"],
             must_not=["Traceback"]),
        dict(name="manasim land or ramp", cmd=S("manasim.py", tmp_deck("klauth_lr", ["Klauth, Unrivaled Ancient"],
                                                                   "1 Rampant Growth\n1 Dragonspeaker Shaman\n1 Terror of the Peaks\n"
                                                                   "1 Shamanic Revelation\n30 Forest\n30 Mountain\n35 Grizzly Bears"),
                                                "--land-or-ramp", "--max-price", "3"),
             must=["+1 land (", "verdict, Klauth: ", "best for Klauth: ", "Ramp tried: "], must_not=["Traceback"]),
        # ---- stats_math
        dict(name="exact odds", cmd=S("stats_math.py", "99", "10", "7", "1"), must=["= 53.7%"]),
        dict(name="colors per face", cmd=S("stats_math.py", "colors", DECK),
             must=["Wear // Tear {W}", "Bonecrusher Giant // Stomp {2}{R}", "Harmonized Trio // Brainstorm {U} "]),
        dict(name="packages", cmd=S("stats_math.py", "packages", DECK), must=["Oracle combo", "Prepared pair"]),
        dict(name="category report", cmd=S("stats_math.py", "report", DECK)),
        # ---- tutors
        dict(name="tutors", cmd=S("tutors.py", DECK, "--trials", "2000", "--no-lists", "--md"),
             must=["NOT FOUND, left out", "| Dimir House Guard | transmute |", "| Step Through | wizardcycling |",
                   "| Entomb | spell | one-shot | graveyard (no access) |", "parts share cards"],
             must_not=["| Lim-Dûl's Vault |"]),
        dict(name="tutors options", cmd=S("tutors.py", DECK, "--trials", "300", "--no-lists", "--commander", "Kraum, Ludevic's Opus",
                                          "--turns", "4,6", "--draw", "--md"),
             must=["on the draw", "## 5. Key cards", "by T4, T6", "| Demonic Tutor | yours |", "inferred beyond yours",
                   "T4 played", "Copies T6 (played)", "## 7. Tutor worth", "| Played: key cards per 100 games |",
                   "| Only it reaches |", "T4 played |"]),
        dict(name="tutors text tables", cmd=S("tutors.py", DECK, "--trials", "300", "--no-lists"),
             must=["=== TUTORS:", "Puts it", "Targets here", "-----", "Copies T6 (played)", "Only it reaches"],
             must_not=["| Tutor |", "Traceback", "…"]),
        dict(name="tutors reader wordings", cmd=S("tutors.py", tmp_deck("tutor_words", ["Lore Weaver", "Ley Weaver"],
                                                   "1 Boonweaver Giant\n1 Bear Umbra\n1 Ajani's Aid\n1 Ajani, Valiant Protector\n"
                                                   "1 Jungle Wayfinder\n1 Pattern of Rebirth\n1 Grizzly Bears\n40 Island\n20 Forest\n20 Plains"),
                                         "--trials", "200", "--no-lists", "--md", "--no-played"),
             must=["| Boonweaver Giant | enters |", "| Lore Weaver (commander) | enters |", "cards named Ley Weaver",
                   "cards named Ajani, Valiant Protector", "land-only (mana, not analyzed further): Jungle Wayfinder", "| Pattern of Rebirth |"],
             must_not=["Traceback"]),
        dict(name="fidelity", cmd=S("fidelity.py", DECK, "decks/Ians_Zur_Wizardcycling.txt", "--md"),
             must=["# FIDELITY:", "| Deck | Ramp | Card draw | Tutors |", "overall: ramp", "To fix first", "| Card | Copies |"],
             must_not=["Traceback", "| error |"]),
        dict(name="tutor index", cmd=S("tutor_index.py", "Astral Slide", "--ci", "WUB", "--md"),
             must=["# FINDABLE BY: Astral Slide", "| Idyllic Tutor |", "| Zur the Enchanter |", "find-anything tutors (",
                   "| Find-anything tutor |", "| Demonic Tutor |"], must_not=["Traceback", "| Mask of the Mimic |", "| Grozoth |"]),
        dict(name="explorer findable by", cmd=S("explorer.py", "Astral Slide", "--offline", "--ci", "WUB"),
             must=["== 5b FINDABLE BY", "Idyllic Tutor (MV 3, one-shot, to hand): enchantment", "specific, most played first:",
                   "find-anything (they find every card"], must_not=["Traceback", "Demonic Tutor (MV"]),
        dict(name="tutors to add", cmd=S("tutors.py", "decks/Ians_Zur_Wizardcycling.txt", "--no-lists", "--md", "--played-trials", "300",
                                         "--suggest", "6"),
             must=["## 8. Tutors to add", "| Tutor | Played: key cards per 100 games | Finds (your keys; via: tutors it can fetch) |", "transmute (card MV=2)", "swap: Long-Term Plans",
                   "| Find-anything tutor | Played: key cards per 100 games |", "| everything |"],
             must_not=["Traceback", "| Profane Tutor |", "| Inventors' Fair |", "| Mask of the Mimic |", "| Remembrance |"]),
        dict(name="tutors no-infer", cmd=S("tutors.py", DECK, "--trials", "300", "--no-lists", "--no-infer"),
             must=["## 5. Key cards", "yours ("], must_not=["inferred beyond yours", "Traceback"]),
        # ---- EDHREC snapshots still resolve against today's data
        *[dict(name=f"snapshot {os.path.basename(f)[:30]}", data=True, cmd=S("edhrec_diff.py", "check", "snapshots/" + os.path.basename(f)), must=["OK"])
          for f in sorted(os.listdir(os.path.join(REPO, "snapshots"))) if f.endswith(".txt")],
        dict(name="edhrec diff", cmd=S("edhrec_diff.py", "diff", "snapshots/erebos-god-of-the-dead__all__2026-09-26.txt", DECK)),
        dict(name="edhrec diff flags", cmd=S("edhrec_diff.py", "diff", "snapshots/erebos-god-of-the-dead__all__2026-09-26.txt", DECK,
                                             "--min", "20", "--limit", "5", "--mv", "odd"),
             must=["EDHREC snapshot: Erebos", "deck names not found in repo: Totally Fake Card Name"]),
        # ---- goldfish. It stops on NOT FOUND, so it gets the deck without the fake card.
        dict(name="goldfish explain", cmd=S("goldfish.py", nofake, "--explain"),
             must=["Entomb — tutor->graveyard", "Step Through — wizardcycling {2}: tutor->hand: Wizard",
                   "Dimir House Guard — transmute {3}: tutor->hand: card MV=4", "Demonic Tutor — tutor->hand: any card",
                   "Kraum, Ludevic's Opus — on opp_second: draw 1; ~opp", "vacuum   other  Nezumi Graverobber",
                   "partial  other  Tymna the Weaver — 2/2 lifelink"],
             must_not=["Barrage Tyrant — act"]),               # 'another colorless creature': a qualified fodder cost stays unread
        dict(name="goldfish run", cmd=S("goldfish.py", nofake, "--trials", "300"),
             must=["tutor priorities (list header, then inferred): key: Demonic Tutor, Stroke of Genius", "tutor targets"],
             must_not=["Entomb 0."]),                       # a graveyard tutor is never card advantage
        # ---- goldfish graveyard fixture
        dict(name="goldfish gy explain", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--explain"),
             must=["Exhume — recur->bf: creature", "Street Wraith — cycling 2 life: draw 1", "Griselbrand — act [7 life]: draw 7",
                   "Krosan Tusker — cycling {3}: draw 1, land x1->hand", "Unburial Rites — recur->bf: creature",
                   "flashback from graveyard (4)", "unearth from graveyard (2)", "retrace from graveyard (mana cost, discard a land)",
                   "Satyr Wayfinder — ETB reveal 4, take land, rest to graveyard", "Buried Alive — tutor->graveyard: 3x creature",
                   "Animate Dead — ETB recur->bf: creature", "Meren of Clan Nel Toth — on end: recur->hand"]),
        dict(name="goldfish gy run", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--trials", "300",
                                           "--variant", "no Entomb|Entomb=>Swamp"),
             must=["recursion by source", "tutor targets", "Builds compared", "recursion T8"]),
        dict(name="goldfish disruption fixed", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--trials", "200",
                                                    "--disruption", "wipe@5"),
             must=["fixed scenario for every game: wipe@5", "creature wipe", "Δcmdr turns"], must_not=["table model"]),
        dict(name="goldfish ladder", cmd=S("goldfish.py", nofake, "--trials", "100", "--shuffles", "10"),
             must=["disruption ladder, Bracket 3", "10 shuffles × (5 clean + 15 rungs) = 200 games; horizon T9", "noise band",
                   "breakpoint (first rung that folds", "fold ="]),
        dict(name="goldfish ladder max + variant", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--bracket", "4", "--trials", "100",
                                                        "--shuffles", "8", "--ladder-max", "--variant", "no Entomb|Entomb=>Swamp"),
             must=["Bracket 4", "--ladder-max: every event fires", "ladder: median breakpoint", "ladder: fold at top rung"]),
        dict(name="goldfish no bracket falls back", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--trials", "100"),
             must=["no bracket in the header or --bracket", "sampled per game"]),
        dict(name="goldfish ladder needs bracket 2-4", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--disruption", "ladder", "--bracket", "5"),
             expect_rc=1, must=["needs Bracket 2, 3 or 4"]),
        dict(name="goldfish fixed new codes", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--trials", "3", "--disruption",
                                                   "lock@2;gy@3;ctrK!@3;rem+@4;nuke+gy@6", "--disruption-trace", "1"),
             must=["DISRUPTION: command zone/graveyard lock", "command zone/graveyard lock for 3 turns", "fixed scenario for every game"]),
        dict(name="goldfish disruption bad spec", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--disruption", "meteor@3"),
             expect_rc=1, must=["use KIND@TURN"]),
        dict(name="goldfish flags", cmd=S("goldfish.py", nofake, "--trials", "50", "--disruption", "off", "--track", "Rituals=Ritual$",
                                         "--kill-commander", "4"),
             must=["--kill-commander 4: every clean game loses the commander after turn 3", "tracked Rituals:"]),
        dict(name="goldfish pilot flags", cmd=S("goldfish.py", nofake, "--trials", "50", "--disruption", "off", "--draw", "--no-mulligan",
                                               "--cast-interaction", "--order", "ramp,draw,commander,track,other"),
             must=["on the draw", "0.0% of games mulligan"]),
        dict(name="goldfish json", cmd=S("goldfish.py", nofake, "--trials", "50", "--disruption", "off", "--json"), must=['"kill": 0']),
        # ---- goldfish mechanics fixture (Sept 29 2026 parser work) + deterministic unit checks
        dict(name="goldfish units", cmd=["tests/goldfish_units.py"], must=["units: all"]),
        # ---- runtime crash net: every card's parsed effects executed once in a live game
        dict(name="goldfish sweep: every card's effects run", cmd=["tests/goldfish_sweep.py"], must=[" 0 errors"]),
        # ---- GEF adapter (T3 step 2): units per construct, the sweep through the GEF path, parity with every diff explained
        dict(name="gef units", cmd=["tests/gef_units.py"], must=["gef units: all"]),
        dict(name="goldfish sweep, GEF path", cmd=["tests/goldfish_sweep.py", "--gef"], must=["GEF path", " 0 errors"]),
        dict(name="gef parity: every diff explained", cmd=["tests/gef_parity.py"], must=["parity: "], must_not=["UNEXPLAINED"]),
        dict(name="goldfish --gef", cmd=S("goldfish.py", "translation/decks/zur.txt", "--gef", "--trials", "30", "--disruption", "off"),
             must=["Zur"]),
        # ---- goldfish coverage (parser over the whole Commander pool): a parse change must never crash a card
        dict(name="goldfish coverage: every legal card compiles", cmd=S("goldfish_coverage.py", "report", "--top", "3"),
             must=[" 0 compile errors", "fully read (modeled + held + vacuum + override), weighted:"]),
        dict(name="goldfish coverage card", cmd=S("goldfish_coverage.py", "card", "Tromp the Domains", "Rites of Initiation"),
             must=["Tromp the Domains — pump team +1 per domain/+1 per domain trample EOT"],
             must_not=["Rites of Initiation — pump team"]),        # a 'for each' it can't count is never read flat
        # removal is read as removal of opponents' blockers, never aimed at your own board; opponent-only lines are vacuum
        dict(name="goldfish coverage removal + vacuum", cmd=S("goldfish_coverage.py", "card", "Ravenous Chupacabra", "Skinrender",
             "Swords to Plowshares", "Nekrataal", "Plague Wind", "Deathrite Shaman", "Flickerwisp", "Goblin Snowman", "Beast Within",
             "Propaganda", "Mind Rot", "Beacon of Tomorrows", "Thieving Amalgam"),
             must=["Ravenous Chupacabra — ETB removal: destroy an opposing creature",
                   "Skinrender — ETB removal: -3/-3 on an opposing creature",
                   "Swords to Plowshares — removal: exile an opposing creature; its controller gains life = its power",
                   "Nekrataal — ETB removal: destroy an opposing creature (nonartifact,nonblack)",
                   "Plague Wind — removal: destroy every opposing creature",
                   "vacuum   other  Propaganda", "vacuum   other  Mind Rot",
                   "blank    other  Beacon of Tomorrows", "blank    other  Thieving Amalgam"],   # its 'creature you control but don't own dies' trigger is not any creature
             must_not=["Deathrite Shaman — act [T 1]: removal", "Flickerwisp — ETB removal", "Goblin Snowman — act [T]: removal",
                       "Beast Within — removal"]),   # graveyard card, flicker, 'it's blocking', gives them a body
        dict(name="goldfish mech explain", cmd=S("goldfish.py", MECH, "--explain"),
             must=["Nyxbloom Ancient — mana x3 (permanents)",
                   "Mana Reflection — mana x2 (permanents)", "Vorinclex, Voice of Hunger — mana +1 per tap (lands)",
                   "Selvala, Heart of the Wilds — filter 1->X; X = power", "Priest of Titania — mana G; X = sub Elf",
                   "Karametra's Acolyte — mana G; X = devotion G", "Goreclaw, Terror of Qal Sisma — reduce {2}: Creature power>=4",
                   "reduce {2}: Creature (first each turn)", "Dragonspeaker Shaman — reduce {2}: Dragon",
                   "Dracogenesis — free: Dragon spells (command zone too)", "Omniscience — free: all spells from hand",
                   "Lathliss, Dragon Queen — on etb(another nontoken Dragon ): token 1x Dragon 5/5 flying",
                   "Deranged Hermit — ETB token 4x Squirrel", "Tireless Tracker — on landfall: token 1x Clue",
                   "Young Pyromancer — on cast(instant,sorcery): token 1x Elemental", "Unbounded Potential — prolif 1",
                   "Dragonstorm — tutor->bf: Dragon permanent", "non-Human creature", "Sire of Stagnation — on opp_land: draw 2; ~opp",
                   "Frogmite — costs {1} less per artifacts", "Ghoultree — costs {1} less per gy_creature",
                   "Tolarian Terror — costs {1} less per gy_instsorc", "unmodeled: Convoke",
                   "conditional trigger (intervening 'if') not modeled", "Land Tax — on upkeep: if an opponent has more lands ~opp",
                   "Smothering Tithe — on opp_draw taxed: treasure 1; ~opp"],
             must_not=["partly unread: n instant", "Kalitas, Bloodchief of Ghet — act [T 3]: removal: destroy an opposing creature, token",   # its token copies their creature: unread
                       "Glen Elendra's Answer — token",
                       "Embercleave — costs", "on opp_cast(noncreature) 1/turn: ;"]),
        dict(name="goldfish mech run", cmd=S("goldfish.py", MECH, "--trials", "200", "--shuffles", "10"),
             must=["tutor priorities (list header, then inferred): key: Nyxbloom Ancient", "disruption ladder, Bracket 3", "tutor targets"]),
        dict(name="goldfish gy trace", cmd=S("goldfish.py", "tests/goldfish_gy_deck.txt", "--trials", "2", "--trace", "2"),
             must=["Entomb finds Griselbrand -> graveyard", "Demonic Tutor finds Reanimate -> hand", "cast Reanimate"]),
        # ---- goldfish combat fixture (Sept 29 2026): keywords, anthems, equipment, combat/noncombat triggers, face damage
        dict(name="goldfish combat explain", cmd=S("goldfish.py", COMBAT, "--explain"),
             must=["Baneslayer Angel — 5/5 first strike, flying, lifelink", "Bloated Contaminator — on cdmg_self: prolif 1",
                   "Hero of Bladehold — on attack_self: token 2x Soldier 1/1 attacking", "pump others_attacking +1/+0 EOT",
                   "Hellrider — on attack(creature): an opponent loses 1", "Ophidian — on unblocked_self: draw 1",
                   "Glorious Anthem — anthem creatures +1/+1", "Intangible Virtue — anthem tokens +1/+1 vigilance",
                   "Bonesplitter — equipped creature +2/+0; equip 1", "Sword of Fire and Ice — on cdmg_att: an opponent loses 2, draw 1; equipped creature +2/+2; equip 2",
                   "Overrun — pump team +3/+3 trample EOT; pump: cast before combat only",
                   "Impact Tremors — on etb(creature): each opponent loses 1", "Blood Artist — on dies(creature): an opponent loses 1, you gain 1 life",
                   "Warstorm Surge — on etb(creature): an opponent loses that creature's power", "Crusader of Odric — X/X (X = creatures)",
                   "(a creature only at devotion 5+)", "Exsanguinate — each opponent loses X", "Rafiq of the Many — on attack(creature attacking alone): pump obj double strike EOT",
                   "Najeela, the Blade-Blossom — on attack(Warrior ): token 1x Warrior 1/1 attacking", "held     other  Lightning Bolt",
                   "act [5]: untap attacking creatures, pump attackers haste,lifelink,trample EOT, additional combat",
                   "Relentless Assault — untap attacked creatures, additional combat", "Aurelia, the Warleader — on attack_self 1/turn: untap all creatures, additional combat",
                   "Moraug, Fury of Akoum — on landfall: in your main phase: additional combat, untap all creatures"],
             must_not=["Crusader of Odric's power", "Creatures creature"]),
        dict(name="goldfish combat run", cmd=S("goldfish.py", COMBAT, "--trials", "200", "--turns", "10", "--shuffles", "10"),
             must=["combat and damage", "all opponents dead:", "additional combat phases per game", "damage by source", "triggers fired (avg per game)",
                   "disruption ladder, Bracket 3", "Δkill t"]),
        dict(name="goldfish combat trace", cmd=S("goldfish.py", COMBAT, "--trials", "3", "--trace", "3", "--turns", "10", "--disruption", "off"),
             must=["  attack: ", "combat damage: ", "opponents: 1:"]),
        dict(name="goldfish combat variant", cmd=S("goldfish.py", COMBAT, "--trials", "100", "--disruption", "off",
                                                  "--variant", "No hero|Hero of Bladehold=>Grizzly Bears"),
             must=["table killed <=T8", "damage T8 P10/med/P90"]),
        # ---- goldfish blockers (Sept 30 2026): --blockers boards, block keywords, denial
        dict(name="goldfish blocker reads explain", cmd=S("goldfish.py", tmp_deck("blk", ["Najeela, the Blade-Blossom"],
             "1 Questing Beast\n1 Ichorclaw Myr\n1 Samurai of the Pale Curtain\n1 Wolverine Pack\n1 Falter\n1 Artful Dodge\n"
             "1 Frenzied Goblin\n1 Neheb, the Eternal\n1 Suq'Ata Lancer\n40 Forest"), "--explain"),
             must=["unblockable by power 2 or less", "Ichorclaw Myr — on blocked_self: pump obj +2/+2 EOT", "2/2 bushido 1", "rampage 2",
                   "creatures without flying can't block EOT", "target creature can't be blocked EOT", "1 opposing blocker(s) can't block EOT",
                   "afflict 3", "flanking"]),
        dict(name="goldfish blockers run", cmd=S("goldfish.py", COMBAT, "--trials", "150", "--disruption", "off",
             "--blockers", "1/1@2; 2/2 flying@4; 3/3 deathtouch@6x2; 1:prop@4; 2:fog@5; 3:arb@5; each:maze@7; 1:settle@6; bridge@8; moat@8"),
             must=["boards from --blockers", "opp blockers", "blocks (avg per game): attackers blocked", "denial (avg per game): fogs"],
             must_not=["Traceback"]),
        dict(name="goldfish blockers ladder", cmd=S("goldfish.py", COMBAT, "--trials", "100", "--shuffles", "5", "--blockers", "2/2@3x2; 2:fog@6"),
             must=["disruption ladder, Bracket 3", "blocks (avg per game)"], must_not=["Traceback"]),
        dict(name="goldfish blockers bad spec", cmd=S("goldfish.py", COMBAT, "--blockers", "2/2 banana@3"), expect_rc=1,
             must=["--blockers '2/2 banana@3'"]),
        # ---- goldfish Food/sacrifice fixture (Sept 30 2026): Ragost's engine, sacrifice costs and triggers, type grants, doublers
        dict(name="goldfish food explain", cmd=S("goldfish.py", FOOD, "--explain"),
             must=["Ragost, Deft Gastronaut — on end +opp turns: if you gained life this turn: untap ~; act [T 1 sac Food]: each opponent loses 3; "
                   "artifacts you control are also Food; they have act [T 2 sac]: you gain 3 life",
                   "Nuka-Cola Vending Machine — on sac(Food ): treasure 1 tapped; act [T 1]: token 1x Food",
                   "Academy Manufactor — a Clue, Food or Treasure token -> one of each",
                   "Stridehangar Automaton — anthem Thopter creatures +1/+1; artifact tokens: +1 Thopter 1/1 flying each time",
                   "Spirit Loop — on dmg_att: you gain life equal to the damage; on gy_self: return ~ to hand",
                   "Well of Lost Dreams — on gain: pay X (up to the life gained): draw X", "Furnace of Rath — damage x2",
                   "City on Fire — damage x3 (your sources)", "Weapons Manufacturing — on etb(nontoken artifact): token 1x Munitions (has an ability)",
                   "Prized Statue — ETB treasure 1; on gy_self: treasure 1", "Servo Schematic — ETB token 1x Servo 1/1 artifact; on gy_self:",
                   "Test of Endurance — on upkeep: if you have 50+ life: you win the game", "Goblin Bombardment — act [sac creature]: an opponent loses 1",
                   "Ravenous Squirrel — on sac(artifact or creature): +1 +1/+1 ctr; act [3 sac artifact or creature]",
                   "Mayhem Devil — on sac(permanent): an opponent loses 1", "only your own sacrifices are modeled",
                   "Ashnod's Altar — sac outlet: sacrifice creature -> C+C", "blank    other  Food Chain"],
             must_not=["Ragost, Deft Gastronaut — 2/2  [", "blank    other  Nuka-Cola", "Cauldron Familiar — act"]),
        dict(name="goldfish food run", cmd=S("goldfish.py", FOOD, "--trials", "200", "--shuffles", "10"),
             must=["damage by source (avg per game): Ragost, Deft Gastronaut", "Nuka-Cola Vending Machine (other)", "disruption ladder, Bracket 2"]),
        dict(name="goldfish food trace", cmd=S("goldfish.py", FOOD, "--trials", "2", "--trace", "2", "--disruption", "off"),
             must=["opponent 1's turn (", "activate Ragost, Deft Gastronaut (sacrifice ", "Ragost, Deft Gastronaut untaps",
                   "Ragost, Deft Gastronaut: 3 to each opponent"]),
        # ---- explorer.py: offline only (EDHREC is live and changes daily; CI must not depend on it)
        dict(name="explorer offline", cmd=S("explorer.py", "Blood Artist", "--offline", "--ci", "BG", "--limit", "3"),
             must=["=== EXPLORER: Blood Artist", "include it inside BG", "== 5 BUILD-AROUND", "blood artist ability",
                   "offline: EDHREC sections skipped", "== 6 PROMPT", "Reason on Blood Artist"],
             must_not=["EDHREC: ", "! EDHREC"]),
        dict(name="explorer offline (data)", data=True, cmd=S("explorer.py", "Blood Artist", "--offline", "--limit", "3"),
             must=["Tombstone Stairwell + Blood Artist", "Junji, the Midnight Sky"]),
        dict(name="explorer not found", cmd=S("explorer.py", "Totally Fake Card Name", "--offline"), expect_rc=1,
             must=["NOT FOUND: Totally Fake Card Name"]),
        # ---- Fishpond (Forge-backed simulator). The parser units run on saved Forge logs, no Forge needed.
        dict(name="fishpond units", cmd=["tests/fishpond_units.py"], must=["units: all"]),
        dict(name="fishpond help", cmd=["-m", "fishpond"], must=["python3 -m fishpond run DECK", "gauntlet:NAME"]),
        *fishpond_live(),
    ]

def fishpond_live():
    """Live Fishpond checks, only when the pinned Forge release is already cached (CI never downloads it)."""
    sys.path.insert(0, REPO)
    from fishpond import forge
    if not forge.installed(): return []
    return [
        dict(name="fishpond deck", cmd=["-m", "fishpond", "deck", "tests/forge/chulane.txt", "--opp", "gauntlet:own"],
             must=["hero: Chulane, Teller of Tales | 100 cards | bracket 3", "AI:RemoveDeck:All): none",   # both un-flagged by overrides
                   "policy engines (strength 0-1): land 1.00",
                   "Klauth_Dragons.txt) | 100 cards"], must_not=["Klauth, Unrivaled Ancient: 101 cards"]),
        dict(name="fishpond run (2 games, live Forge)", cmd=["-m", "fishpond", "run", "tests/forge/chulane.txt", "--trials", "2",
                                                             "--cap", "3", "--turns", "3", "--jobs", "2", "--quiet", "--out", os.path.join(TMP, "fp")],
             must=["=== FISHPOND: Chulane, Teller of Tales", "vacuum: 3 dummies", "dummies: never cast or attacked", "## base: combat and damage"],
             must_not=["WARNING"]),
        dict(name="fishpond resume (+1 game, live Forge)", cmd=["-m", "fishpond", "run", "--resume", os.path.join(TMP, "fp"), "--trials", "1",
                                                                "--jobs", "1", "--quiet"],
             must=["2 game(s) finished, 0 unfinished to replay, 1 new", "| 3 games |", "mulligans:"]),
    ]

def run(c):
    try:
        p = subprocess.run([PY] + c["cmd"], cwd=REPO, capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace",
                           env={**{k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"},   # scripts must set UTF-8 themselves
                                "MTG_TRIALS_CAP": os.environ.get("MTG_TRIALS_CAP", "100")})   # games per run: checks the tools run, not their precision
        out, rc = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        return ["timed out after 300s"]
    fails = []
    if rc != c.get("expect_rc", 0): fails.append(f"exit code {rc}: {out.strip().splitlines()[-1][:160] if out.strip() else ''}")
    if "Traceback" in out: fails.append("Python traceback: " + out.strip().splitlines()[-1][:160])
    fails += [f"missing: {m!r}" for m in c.get("must", []) if m not in out]
    fails += [f"unexpected: {m!r}" for m in c.get("must_not", []) if m in out]
    return fails

def main():
    status_path = sys.argv[sys.argv.index("--status") + 1] if "--status" in sys.argv else None
    verbose = "--verbose" in sys.argv
    failures, n = [], 0
    for c in checks():
        t0 = time.time(); f = run(c); n += 1; dt = time.time() - t0
        tag = " [data-dependent: may be a real change, confirm before editing]" if c.get("data") else ""
        if f or verbose: print(f"{'PASS' if not f else 'FAIL'}  {c['name']}  ({dt:.0f}s)" + ("" if not f else tag), flush=True)
        for x in f:
            print(f"      {x}")
            failures.append(f"{c['name']}: {x}" + (" (data-dependent)" if c.get("data") else ""))
    ok = not failures
    print(f"smoke: {'all ' + str(n) + ' checks passed' if ok else f'{len(failures)} failure(s) across {n} checks'}")
    if status_path:
        path = os.path.join(REPO, status_path)
        try: old = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError): old = {}
        status = "pass" if ok else "fail"
        if old.get("status") != status or old.get("failures", []) != failures:
            since = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            json.dump({"status": status, "since": since, "failures": failures}, open(path, "w", encoding="utf-8"), indent=1)
            print(f"status file updated: {status}")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
