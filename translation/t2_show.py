#!/usr/bin/env python3
"""Print Oracle text, the parser's reading and the GEF translation side by side, for hand review.
  python3 translation/t2_show.py GEF.json [NAME ...]      # no names: every card in the file"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import t2_compare as C, validate as V, mtg
gefs = {x["name"]: x for x in json.load(open(sys.argv[1], encoding="utf-8"))}
names = sys.argv[2:] or list(gefs)
cache, read = C.readings(names)
idx = mtg.index()
for n in names:
    card = idx[n.lower()]
    text = card.get("oracle_text") or " // ".join(f.get("oracle_text", "") for f in card.get("card_faces", []))
    ps, pr = read.get(n, ("?", ""))
    print(f"=== {n}\nORACLE: {text}\nPARSER [{ps}]: {pr}\nGEF [today {V.status(gefs[n], card)} / expr {V.status(gefs[n], card, today=False)}]:")
    print(C.compact(gefs[n]))
    if gefs[n].get("notes"): print("  notes:", gefs[n]["notes"])
    print()
