#!/usr/bin/env python3
"""T3 step 4: the per-deck translation workflow (docs/TRANSLATION_T2.md, step 4).

  python3 translation/deck_workflow.py select DECK.txt NAME [--batch 34]   # cards to translate -> translation/phase4/NAME/batches/
  python3 translation/deck_workflow.py merge NAME                           # out/*.json (+ retry_*.json) -> NAME/gef.json, validated
  python3 translation/deck_workflow.py report DECK.txt NAME                 # fully read (parser vs GEF adapter) and the audit's error rate

select: every card in the deck except basic lands and plain lands the parser already reads fully (status 'land'), minus
cards that already have a translation in data/gef/. The batch inputs carry only what a translator may see (as T2).
merge: translator outputs in NAME/out/ (later files win), each validated; NAME/gef.json is what goes to data/gef/NAME.json
once audited. report: the deck's cards through the parser and through the adapter (data/gef/ plus this deck's
translations), and NAME/audit.json: [name, pass, verdict (correct | conservative | freetext | wrong), real format gap,
note]; the error rate is wrong / audited, as T2 counts it.
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, HERE)
import mtg                                               # noqa: E402

P4 = os.path.join(HERE, "phase4")
BASIC = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}
FULL = {"modeled", "held", "vacuum", "override"}

def card_view(c):
    keep = ("name", "mana_cost", "type_line", "oracle_text", "power", "toughness", "loyalty")
    v = {k: c[k] for k in keep if c.get(k)}
    if c.get("card_faces"):
        v["faces"] = [{k: f[k] for k in keep if f.get(k)} for f in c["card_faces"]]
    return v

def deck_cards(deck):
    out = []
    for sec, q, n in mtg.parse_deck(deck):
        if sec in ("sideboard", "maybeboard", "considering"): continue
        c, how = mtg.find(n)
        if c and c["name"] not in [x["name"] for x in out]: out.append(c)
    return out

def select(deck, name, size=34):
    import goldfish as g, gef_compile as gc
    have, _ = gc.load(validate=False)
    todo, skipped = [], []
    for c in deck_cards(deck):
        if c["name"] in BASIC: continue
        if mtg.norm(c["name"]) in have: skipped.append(c["name"]); continue
        k = g.compile_card(c, g.ALL5)
        if "Land" in c.get("type_line", "").split("—")[0] and "//" not in c["name"] and k.is_land \
                and not any(n.startswith(("unmodeled", "keyword not modeled", "unread")) for n in k.notes) and k.status != "partial":
            skipped.append(c["name"] + " (plain land)"); continue
        todo.append(c)
    d = os.path.join(P4, name, "batches"); os.makedirs(d, exist_ok=True)
    for i in range(0, len(todo), size):
        p = os.path.join(d, f"batch_{i // size + 1:02d}.json")
        json.dump([card_view(c) for c in todo[i:i + size]], open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    json.dump({"to_translate": [c["name"] for c in todo], "skipped": skipped},
              open(os.path.join(P4, name, "selection.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{len(todo)} cards to translate in {(len(todo) + size - 1) // size} batch(es); {len(skipped)} skipped (translated already or plain lands)")

def merge(name):
    import validate as V
    d = os.path.join(P4, name)
    gefs = {}
    for f in sorted(glob.glob(os.path.join(d, "out", "batch_*.json"))) + sorted(glob.glob(os.path.join(d, "out", "retry_*.json"))):
        for x in json.load(open(f, encoding="utf-8")): gefs[x["name"]] = x
    bad = {}
    for n, x in gefs.items():
        errs, _ = V.validate(x, mtg)
        if errs: bad[n] = errs[:3]
    json.dump(list(gefs.values()), open(os.path.join(d, "gef.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{len(gefs)} translations -> translation/phase4/{name}/gef.json; {len(bad)} rejected")
    for n, e in bad.items(): print(f"  REJECT {n}: " + " | ".join(e))
    return bad

def report(deck, name):
    import goldfish as g, gef_compile as gc
    d = os.path.join(P4, name)
    gefs, _ = gc.load(validate=False)
    for x in json.load(open(os.path.join(d, "gef.json"), encoding="utf-8")): gefs[mtg.norm(x["name"])] = x
    ov = g.load_overrides()
    cards = [c for c in deck_cards(deck) if c["name"] not in BASIC]
    def land(c): return "Land" in c.get("type_line", "").split("—")[0] and "//" not in c["name"]
    pf = af = 0
    for c in cards:
        k = g.compile_card(c, g.ALL5)
        o = ov.get(mtg.norm(c["name"]))
        if o: g.apply_override(k, o, g.ALL5)
        p_full = (k.status != "partial" and not any(n.startswith(("unmodeled", "keyword not modeled", "unread")) for n in k.notes)) \
            if land(c) else k.status in FULL
        gef = gefs.get(mtg.norm(c["name"]))
        if o or not gef: a_full = p_full
        else:
            ka = gc.compile_gef(c, gef, g.ALL5)
            a_full = not any(n.startswith("gef refused") for n in ka.notes) if land(c) else ka.status in FULL
        pf += p_full; af += a_full
    n = len(cards)
    print(f"{name}: {n} cards (basics left out): parser fully read {pf} ({100 * pf / n:.1f}%), GEF adapter {af} ({100 * af / n:.1f}%)")
    ap = os.path.join(d, "audit.json")
    if os.path.exists(ap):
        rows = json.load(open(ap, encoding="utf-8"))
        final = {}
        for r in rows: final[r[0]] = r                   # the last pass per card
        first = {}
        for r in rows: first.setdefault(r[0], r)
        from collections import Counter
        fv, lv = Counter(r[2] for r in first.values()), Counter(r[2] for r in final.values())
        print(f"  audited {len(final)}: first pass {dict(fv)}; final {dict(lv)}; "
              f"misread rate first pass {fv['wrong']}/{len(first)} = {100 * fv['wrong'] / max(1, len(first)):.1f}%")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["select"]: select(a[1], a[2], int(a[a.index("--batch") + 1]) if "--batch" in a else 34)
    elif a[:1] == ["merge"]: merge(a[1])
    elif a[:1] == ["report"]: report(a[1], a[2])
    else: print(__doc__); sys.exit(2)
