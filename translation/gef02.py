#!/usr/bin/env python3
"""GEF 0.1 -> 0.2 for the T2 cards (T3 step 1): migrate, pick the cards to re-translate, build their batches, merge.

  python3 translation/gef02.py migrate FILE.json        # in place: version bump + renames (lossless, mechanical)
  python3 translation/gef02.py affected                 # writes translation/gef02/affected.json (card -> why)
  python3 translation/gef02.py batches                  # writes translation/gef02/batches/batch_NN.json
  python3 translation/gef02.py merge                    # writes translation/gef02/t2_cards.json (all 300, 0.2)

Mechanical migration only bumps `gef` and renames `lab_man` to `draw_from_empty_library_wins`. Anything else 0.2
changed (free-text statics, keyword enums, detail on non-silent keywords, the new constructs) is re-translated by a
translator from the card text, never patched by script: the point is to measure what translators do with 0.2.
"""
import glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import validate as V                                     # noqa: E402

P1 = os.path.join(HERE, "prototype")
P2 = os.path.join(HERE, "gef02")
RETRY_OK = {"Requisition Raid"}                     # audited wrong on the first pass; the T2 retry is correct
RENAMES = {"lab_man": "draw_from_empty_library_wins"}

# T2 gap cards a 0.2 construct addresses (the construct named; the card may keep other gaps)
NEW_CONSTRUCTS = {
    "Klauth, Unrivaled Ancient": "count total_power (attacking)",
    "Blasphemous Act": "count permanents_on_battlefield",
    "War Room": "count commander_identity_colors",
    "Knollspine Dragon": "count damage_dealt_this_turn",
    "Spinerock Knoll": "count damage_dealt_this_turn (condition)",
    "Mosswort Bridge": "count total_power (condition)",
    "Cultivate": "tutor split",
    "Kodama's Reach": "tutor split",
    "Long-Term Plans": "tutor position",
    "Approach of the Second Sun": "self_to_library position",
    "Herald's Horn": "choose_on_enter",
    "Roaming Throne": "choose_on_enter, type_grant self + add_chosen_type",
    "Patchwork Banner": "choose_on_enter",
    "The Endstone": "event play_land",
    "Balefire Dragon": "filter controller that_player",
    "Fell the Profane // Fell Mire": "enters_tapped unless_pay",
    "Grasp of Fate": "target for_each opponent (T2 misread)",
    "Astral Drift": "T2 misread (cycle trigger from hand)",
}

def migrate(x):
    if isinstance(x, list): return [migrate(v) for v in x]
    if not isinstance(x, dict): return x
    out = {k: migrate(v) for k, v in x.items()}
    if out.get("gef") == "0.1": out["gef"] = "0.2"
    if out.get("static") in RENAMES: out["static"] = RENAMES[out["static"]]
    return out

def t2_translations():
    """The T2 translations as accepted: first pass, with the retry replacing its three rejects."""
    g = {}
    for f in sorted(glob.glob(os.path.join(P1, "out", "batch_*.json"))) + [os.path.join(P1, "out", "retry_01.json")]:
        for x in json.load(open(f, encoding="utf-8")): g[x["name"]] = x
    return g

def audit():
    a = {}
    for f in sorted(glob.glob(os.path.join(P1, "audit_batch*.json"))):
        for n, t, p, gap, note in json.load(open(f, encoding="utf-8")): a[n] = (t, p, gap, note)
    return a

def affected():
    mtg = V.load_cards()
    aud, why = audit(), {}
    for n, g in t2_translations().items():
        errs, _ = V.validate(migrate(g), mtg)
        if errs: why.setdefault(n, []).append("0.2 rejects the 0.1 translation: " + errs[0][:120])
        t = aud[n][0]
        if t in ("freetext", "conservative", "wrong") and n not in RETRY_OK: why.setdefault(n, []).append(f"T2 audit: {t}")
        if n in NEW_CONSTRUCTS: why.setdefault(n, []).append("new construct: " + NEW_CONSTRUCTS[n])
    os.makedirs(P2, exist_ok=True)
    json.dump(why, open(os.path.join(P2, "affected.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{len(why)} cards to re-translate -> translation/gef02/affected.json")
    return why

def batches(size=16):
    why = json.load(open(os.path.join(P2, "affected.json"), encoding="utf-8"))
    inputs = {}
    for f in sorted(glob.glob(os.path.join(P1, "batches", "batch_*.json"))):
        for c in json.load(open(f, encoding="utf-8")): inputs[c["name"]] = c
    cards = [inputs[n] for n in why]
    os.makedirs(os.path.join(P2, "batches"), exist_ok=True)
    for i in range(0, len(cards), size):
        p = os.path.join(P2, "batches", f"batch_{i // size + 1:02d}.json")
        json.dump(cards[i:i + size], open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("wrote", os.path.relpath(p, HERE), len(cards[i:i + size]), "cards")

def merge():
    """All 300 T2 cards in 0.2: the re-translation where there is one (out/retry_*.json after out/batch_*.json), else the
    migrated 0.1 translation."""
    cards = {n: migrate(g) for n, g in t2_translations().items()}
    redo = 0
    for f in sorted(glob.glob(os.path.join(P2, "out", "batch_*.json"))) + sorted(glob.glob(os.path.join(P2, "out", "retry_*.json"))):
        for x in json.load(open(f, encoding="utf-8")):
            assert x["name"] in cards, x["name"]
            cards[x["name"]] = x; redo += 1
    p = os.path.join(P2, "t2_cards.json")
    json.dump(list(cards.values()), open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"wrote translation/gef02/t2_cards.json: {len(cards)} cards ({redo} re-translations applied)")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "migrate":
        for path in sys.argv[2:]:
            data = migrate(json.load(open(path, encoding="utf-8")))
            with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=1, ensure_ascii=False); f.write("\n")
            print("migrated", path)
    elif cmd == "affected": affected()
    elif cmd == "batches": batches()
    elif cmd == "merge": merge()
    else: print(__doc__); sys.exit(2)
