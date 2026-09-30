#!/usr/bin/env python3
"""T0 extraction: every Commander-legal card's goldfish status plus its unread lines in FULL (the --explain notes cut
them at 72 characters), written to translation/out/t0_cards.jsonl. Read-only: compiles cards exactly as
goldfish_coverage.py does (same overrides, same statuses) and checks its statuses against coverage's readings().

  python3 translation/t0_extract.py            # ~40 s
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mtg, goldfish as g, goldfish_coverage as gc          # noqa: E402

OUT = os.path.join(ROOT, "translation", "out")
ANYC = frozenset("WUBRG")

_lines = {}                                                   # card name -> the tildified lines compile_card walked
_cur = [None]
_orig_modal = g.modal_lines
def _spy(lines):
    _lines.setdefault(_cur[0], []).extend(x for x in lines if x)
    return _orig_modal(lines)
g.modal_lines = _spy

def status_of(k):
    """The status column explain() prints (goldfish.py explain: override / land / land* / k.status)."""
    return ("override" if k.override else k.status) if not k.is_land else ("land" if not k.notes else "land*")

def full_line(lines, frag):
    """The full line a note fragment came from: prefix match for 'unmodeled: L[:72]', substring for 'unread part'."""
    frag = frag.strip()
    for L in lines:
        if L.startswith(frag) or L[:72] == frag: return L
    parts = [p.strip() for p in frag.split("…") if p.strip(" ,.")]
    for L in lines:
        low = L.lower()
        if parts and all(p.lower().strip(" ,.") in low for p in parts): return L
    return None

def notes_to_items(k, lines):
    """k.notes -> [{kind, text, line}] where line is the full Oracle line (tildified) when it can be found."""
    items = []
    for n in k.notes:
        kind, _, body = n.partition(": ")
        if not body: items.append({"kind": n, "text": "", "line": None}); continue
        if kind == "unmodeled modes":
            first = body.split(" / ")[0]
            L = next((x for x in lines if first and first in x), None)
            items.append({"kind": kind, "text": body, "line": L}); continue
        if kind == "keyword not modeled":
            for w in body.split(", "): items.append({"kind": kind, "text": w, "line": None})
            continue
        if kind == "held wipe (symmetric, never cast)":
            items.append({"kind": kind, "text": body, "line": full_line(lines, body)}); continue
        items.append({"kind": kind, "text": body, "line": full_line(lines, body)})
    return items

def main():
    ov = g.load_overrides()
    seen, rows = set(), []
    for c in mtg.cards():
        if mtg.legal(c) != "legal" or c["name"] in seen: continue
        seen.add(c["name"])
        _cur[0] = c["name"]
        k = g.compile_card(c, ANYC)
        o = ov.get(mtg.norm(c["name"]))
        if o: g.apply_override(k, o, ANYC)
        lines = _lines.get(c["name"], [])
        rows.append({"name": c["name"], "rank": c.get("edhrec_rank"), "weight": gc.weight(c.get("edhrec_rank")),
                     "status": status_of(k), "type_line": c.get("type_line", ""), "is_land": k.is_land,
                     "lines": lines, "unread": notes_to_items(k, lines)})
    # cross-check against goldfish_coverage's own readings (the 44.5% source)
    ref, errs = gc.readings()
    bad = [r["name"] for r in rows if r["name"] in ref and ref[r["name"]][0] != r["status"]]
    missing = [r["name"] for r in rows if r["name"] not in ref]
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "t0_cards.jsonl"), "w", encoding="utf-8") as f:
        for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    nf = sum(1 for r in rows for it in r["unread"] if it["line"] is None and it["kind"] not in ("keyword not modeled",)
             and not it["kind"].startswith(("conditional", "landwalk", "granted ability")))
    print(f"{len(rows)} cards; status mismatches vs coverage readings: {len(bad)} {bad[:5]}; not in readings: {len(missing)}; "
          f"compile errors: {len(errs)}; notes without a full line: {nf}")

if __name__ == "__main__":
    main()
