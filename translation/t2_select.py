#!/usr/bin/env python3
"""T2 step 1: pick the prototype cards and write the translator's batch inputs.

  python3 translation/t2_select.py        # needs translation/out/t0_cards.jsonl (t0_extract.py)

Selection (a stated default): every non-basic card in translation/decks/*.txt except plain lands goldfish already
reads fully (status 'land': duals, fetches), then the most-played Commander cards (by EDHREC rank) outside the decks,
also skipping plain lands, until there are 300. Batch inputs carry only what a translator may see: name, mana cost,
type line, Oracle text, P/T, loyalty, per face. No parser readings.
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mtg                                                  # noqa: E402

PROTO = os.path.join(ROOT, "translation", "prototype")
TOTAL, BATCH = 300, 25
BASIC = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

def card_view(c):
    keep = ("name", "mana_cost", "type_line", "oracle_text", "power", "toughness", "loyalty")
    v = {k: c[k] for k in keep if c.get(k)}
    if c.get("card_faces"):
        v["faces"] = [{k: f[k] for k in keep if f.get(k)} for f in c["card_faces"]]
        v.pop("oracle_text", None)
    return v

def main():
    status = {}
    for ln in open(os.path.join(ROOT, "translation", "out", "t0_cards.jsonl"), encoding="utf-8"):
        r = json.loads(ln); status[r["name"]] = r["status"]
    picked, seen = [], set()
    for path in sorted(glob.glob(os.path.join(ROOT, "translation", "decks", "*.txt"))):
        for sec, q, name in mtg.parse_deck(path):
            c, _ = mtg.find(name)
            if c["name"] in seen or c["name"] in BASIC or status.get(c["name"]) == "land": continue
            seen.add(c["name"]); picked.append((c["name"], "deck"))
    n_deck = len(picked)
    pool = sorted((c for c in mtg.cards() if mtg.legal(c) == "legal" and c.get("edhrec_rank")),
                  key=lambda c: c["edhrec_rank"])
    for c in pool:
        if len(picked) >= TOTAL: break
        if c["name"] in seen or c["name"] in BASIC or status.get(c["name"]) == "land": continue
        seen.add(c["name"]); picked.append((c["name"], "pool"))
    idx = mtg.index()
    os.makedirs(os.path.join(PROTO, "batches"), exist_ok=True)
    with open(os.path.join(PROTO, "cards.json"), "w", encoding="utf-8") as f:
        json.dump([{"name": n, "from": s, "parser_status": status.get(n)} for n, s in picked], f, indent=1, ensure_ascii=False)
    for i in range(0, len(picked), BATCH):
        batch = [card_view(idx[n.lower()]) for n, _ in picked[i:i + BATCH]]
        with open(os.path.join(PROTO, "batches", f"batch_{i // BATCH + 1:02d}.json"), "w", encoding="utf-8") as f:
            json.dump(batch, f, indent=1, ensure_ascii=False)
    print(f"{len(picked)} cards: {n_deck} from the decks, {len(picked) - n_deck} from the pool; "
          f"{(len(picked) + BATCH - 1) // BATCH} batches of {BATCH}")

if __name__ == "__main__":
    main()
