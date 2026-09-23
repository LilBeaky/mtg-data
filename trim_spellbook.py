#!/usr/bin/env python3
"""
trim_spellbook.py — reduce Commander Spellbook's bulk combo export for the repo.

Download (sandbox can't reach this host — grab it in a browser):
    https://json.commanderspellbook.com/variants.json.gz   (smaller)
    https://json.commanderspellbook.com/variants.json

Requires: pip install ijson   (streams the ~660 MB file instead of loading it
          all into memory; falls back to a full load if ijson is missing)

Usage:
    python3 trim_spellbook.py variants.json.gz spellbook_combos.json.gz   (recommended)
    python3 trim_spellbook.py variants.json.gz spellbook_combos.json --max-cards 4
    python3 trim_spellbook.py variants.json.gz spellbook_combos.json --all

Default keeps only Commander-legal, public (OK/Example) combos. --all keeps
everything. --max-cards N drops combos that need more than N cards (shrinks
the file; bracket rules only care about small combos anyway).

OUTPUT: {"timestamp": <export time>, "source": ..., "variants": [ ... ]}
Each variant (empty fields omitted):
    id        Spellbook variant id (link: commanderspellbook.com/combo/<id>)
    cards     card names used
    cmdr      subset of cards that must be your commander
    templates generic requirements ("a sacrifice outlet") — not specific cards
    produces  results, e.g. "Infinite mana", "Win the game"
    ci        color identity, e.g. "UB"
    mv        total mana value needed to assemble
    tag       Spellbook bracket tag: R/S/P/O/C/E/B
    bracket   their mapping: R=4, S=3, P=3, O=2, C=2, E=1 (B = banned card)
    pop       popularity (deck count on EDHREC, per Spellbook)
    prereq    notable prerequisites (short text)

Data by Commander Spellbook — https://commanderspellbook.com — please credit.
"""
import gzip, json, sys

TAG_TO_BRACKET = {"R": 4, "S": 3, "P": 3, "O": 2, "C": 2, "E": 1}
PUBLIC = {"OK", "E"}

def g(d, *keys):
    """Get first present key — tolerates camelCase or snake_case."""
    for k in keys:
        if k in d:
            return d[k]
    return None

def trim(v):
    uses = g(v, "uses") or []
    cards = [u["card"]["name"] for u in uses if u.get("card")]
    cmdr = [u["card"]["name"] for u in uses
            if u.get("card") and g(u, "mustBeCommander", "must_be_commander")]
    templates = [r["template"]["name"] for r in (g(v, "requires") or []) if r.get("template")]
    produces = [p["feature"]["name"] for p in (g(v, "produces") or []) if p.get("feature")]
    tag = g(v, "bracketTag", "bracket_tag")
    out = {
        "id": v.get("id"),
        "cards": cards,
        "cmdr": cmdr,
        "templates": templates,
        "produces": produces,
        "ci": g(v, "identity") or "",
        "mv": g(v, "manaValueNeeded", "mana_value_needed"),
        "tag": tag,
        "bracket": TAG_TO_BRACKET.get(tag),
        "pop": g(v, "popularity"),
        "prereq": (g(v, "notablePrerequisites", "notable_prerequisites") or "").strip(),
    }
    return {k: val for k, val in out.items() if val not in (None, [], "")}

def main():
    argv = sys.argv[1:]
    max_cards = None
    if "--max-cards" in argv:
        i = argv.index("--max-cards")
        max_cards = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    keep_all = "--all" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__); sys.exit(1)
    src, dst = args
    opener = gzip.open if src.endswith(".gz") else open
    try:
        import ijson
        with opener(src, "rb") as fh:          # grab the header timestamp cheaply
            ts = next((v for p, e, v in ijson.parse(fh) if p == "timestamp"), None)
        def stream():
            with opener(src, "rb") as fh:
                yield from ijson.items(fh, "variants.item", use_float=True)
        variants = stream()
    except ImportError:
        print("ijson not installed — loading whole file (needs several GB of RAM)")
        with opener(src, "rt", encoding="utf-8") as fh:
            doc = json.load(fh)
        ts = doc.get("timestamp") if isinstance(doc, dict) else None
        variants = doc["variants"] if isinstance(doc, dict) else doc
    kept, skipped = [], {"not_public": 0, "not_legal": 0, "too_many_cards": 0}
    n_in = 0
    for v in variants:
        n_in += 1
        if not keep_all:
            if v.get("status") and v["status"] not in PUBLIC:
                skipped["not_public"] += 1; continue
            leg = v.get("legalities") or {}
            if leg and not leg.get("commander", True):
                skipped["not_legal"] += 1; continue
        t = trim(v)
        if max_cards is not None and len(t.get("cards", [])) > max_cards:
            skipped["too_many_cards"] += 1; continue
        kept.append(t)
    out = {"timestamp": ts,
           "source": "Commander Spellbook — https://commanderspellbook.com",
           "variants": kept}
    wopen = gzip.open if dst.endswith(".gz") else open   # .gz output: ~3 MB vs ~40 MB
    with wopen(dst, "wt", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"export timestamp: {out['timestamp']}")
    print(f"variants in:  {n_in:,}")
    print(f"variants out: {len(kept):,}")
    for k, n in skipped.items():
        if n: print(f"  skipped {k:<15} {n:,}")

if __name__ == "__main__":
    main()
