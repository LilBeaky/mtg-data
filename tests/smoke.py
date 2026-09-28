#!/usr/bin/env python3
"""Smoke test for mtg-data: runs every tool against tests/test_deck.txt (plus a few tiny
throwaway decks) and checks exit codes, crashes, and expected output.

  python3 tests/smoke.py                 # report only; exit 1 on any failure
  python3 tests/smoke.py --status FILE   # also record pass/fail in FILE (written only when
                                         # the result changes, so passing days commit nothing)

Each check lists `must` / `must_not` substrings. Checks marked `data=True` depend on the
card data (bans, Game Changer list, Spellbook). A failure there may be a real-world change
rather than a bug: confirm, then update this file. mtg.py prints a warning in every session
while the recorded status is "fail".
"""
import datetime, json, os, subprocess, sys, tempfile

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
                                       "stroke of genius", "Thassa’s Oracle", "Westvale Abbey / Ormendahl, Profane Prince", "--brief"),
             must=["Rampant Growth {1}{G}", "Brainstorm {U}", "Aether Vial {1}", "Stroke of Genius {X}{2}{U}",
                   "Thassa's Oracle {U}{U}", "Westvale Abbey // Ormendahl"],
             must_not=["NOT FOUND", "ambiguous", "Studious", "Harmonized"]),
        dict(name="rules", cmd=S("mtg.py", "rule", "702.124h"), must=["Partner"]),
        dict(name="rules current", cmd=S("mtg.py", "rule", "--grep", "prepare spell"), must=["722."]),
        dict(name="search", cmd=S("mtg.py", "search", "--ci", "UB", "--tag", "removal", "--cmc", "1-2", "--limit", "3")),
        dict(name="gc list", cmd=S("mtg.py", "gc")),
        dict(name="combos", cmd=S("mtg.py", "combos", "Thassa's Oracle")),
        dict(name="rulings", cmd=S("mtg.py", "rulings", "Plaza of Heroes")),
        dict(name="tags", cmd=S("mtg.py", "tags", "Sol Ring")),
        # ---- audit
        dict(name="audit", cmd=S("audit.py", DECK, "--no-edhrec"),
             must=["## 7. Manual checklist", "MDFC land backs (2", "not counted (restricted mana", "Cavern of Souls",
                   "extra-turn cards", "Time Warp", "possible MLD", "Armageddon", "parts share cards",
                   "Comprehensive Rules file is dated"],
             must_not=["Colors aren't modeled", "Traceback"]),
        dict(name="audit + EDHREC", cmd=S("audit.py", DECK, "--snapshot", "snapshots/yusri-fortunes-flame__all__2026-09-25.txt"),
             must=["## 6. EDHREC", "EDHREC snapshot: Yusri"]),
        # ---- stats_math
        dict(name="exact odds", cmd=S("stats_math.py", "99", "10", "7", "1"), must=["= 53.7%"]),
        dict(name="colors per face", cmd=S("stats_math.py", "colors", DECK),
             must=["Wear // Tear {W}", "Bonecrusher Giant // Stomp {2}{R}", "Harmonized Trio // Brainstorm {U} "]),
        dict(name="packages", cmd=S("stats_math.py", "packages", DECK), must=["Oracle combo", "Prepared pair"]),
        dict(name="category report", cmd=S("stats_math.py", "report", DECK)),
        # ---- tutors
        dict(name="tutors", cmd=S("tutors.py", DECK, "--trials", "2000", "--no-lists"),
             must=["NOT FOUND, left out", "Dimir House Guard [transmute", "Step Through [cycling",
                   "Entomb [spell, one-shot] → graveyard", "parts share cards"],
             must_not=["Lim-Dûl's Vault ["]),
        # ---- EDHREC snapshots still resolve against today's data
        *[dict(name=f"snapshot {os.path.basename(f)[:30]}", data=True, cmd=S("edhrec_diff.py", "check", "snapshots/" + os.path.basename(f)), must=["OK"])
          for f in sorted(os.listdir(os.path.join(REPO, "snapshots"))) if f.endswith(".txt")],
        dict(name="edhrec diff", cmd=S("edhrec_diff.py", "diff", "snapshots/erebos-god-of-the-dead__all__2026-09-26.txt", DECK)),
        # ---- goldfish: crash check only (its own test battery comes later). It stops on NOT FOUND,
        #      so it gets the deck without the fake card.
        dict(name="goldfish explain", cmd=S("goldfish.py", nofake, "--explain")),
        dict(name="goldfish run", cmd=S("goldfish.py", nofake, "--trials", "300")),
    ]

def run(c):
    try:
        p = subprocess.run([PY] + c["cmd"], cwd=REPO, capture_output=True, text=True, timeout=300)
        out, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        return ["timed out after 300s"]
    fails = []
    if rc != 0: fails.append(f"exit code {rc}: {out.strip().splitlines()[-1][:160] if out.strip() else ''}")
    if "Traceback" in out: fails.append("Python traceback: " + out.strip().splitlines()[-1][:160])
    fails += [f"missing: {m!r}" for m in c.get("must", []) if m not in out]
    fails += [f"unexpected: {m!r}" for m in c.get("must_not", []) if m in out]
    return fails

def main():
    status_path = sys.argv[sys.argv.index("--status") + 1] if "--status" in sys.argv else None
    failures = []
    for c in checks():
        f = run(c)
        tag = " [data-dependent: may be a real change, confirm before editing]" if c.get("data") else ""
        print(f"{'PASS' if not f else 'FAIL'}  {c['name']}" + ("" if not f else tag))
        for x in f:
            print(f"      {x}")
            failures.append(f"{c['name']}: {x}" + (" (data-dependent)" if c.get("data") else ""))
    ok = not failures
    print(f"\n{'ALL PASSED' if ok else f'{len(failures)} FAILURE(S)'}")
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
