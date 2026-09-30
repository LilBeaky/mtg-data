#!/usr/bin/env python3
"""T2 numbers: reject rate, hand-audit verdicts for translator and parser, and fully-read counts on the 300 cards.

  python3 translation/t2_report.py     # needs translation/prototype/compare.json (t2_compare.py) and audit_batch*.json

Audit verdicts (one row per card, translation/prototype/audit_batchNN.json: name, translation, parser, format_gap, note):
  translation: correct | conservative (marked a gap the format could say, or labeled out-of-scope text format_gap)
               | freetext (right meaning, but hidden in a free-text construct the engine can't execute) | wrong
  parser:      correct (what it reads is right; what it doesn't read it says so) | approx (reads it with an approximation
               it declares or that is harmless-ish) | wrong (reads something the card doesn't do, or silently drops a
               material part while calling the card modeled/held/vacuum)
"""
import glob, json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import validate as V                                     # noqa: E402
import mtg                                               # noqa: E402

P = os.path.join(HERE, "prototype")
FULL = {"modeled", "held", "vacuum", "override"}         # 'fully read' (nonland); lands: land vs land*

def demote_freetext(x):
    """Replace the free-text statics (replacement, restriction) with an unexpressible escape: what the card would say
    if the schema didn't allow them."""
    if isinstance(x, list): return [demote_freetext(v) for v in x]
    if not isinstance(x, dict): return x
    if x.get("kind") == "static" and isinstance(x.get("effect"), dict) and x["effect"].get("static") in ("replacement", "restriction"):
        return {"kind": "unexpressible", "text": x.get("text", ""), "reason": "free-text static", "scope": "format_gap"}
    return {k: demote_freetext(v) for k, v in x.items()}

def full(s): return s in FULL or s == "land"

def main():
    rows = {r["name"]: r for r in json.load(open(os.path.join(P, "compare.json"), encoding="utf-8"))}
    src = {r["name"]: r["from"] for r in json.load(open(os.path.join(P, "cards.json"), encoding="utf-8"))}
    audit = {}
    for f in sorted(glob.glob(os.path.join(P, "audit_batch*.json"))):
        for n, t, p, gap, note in json.load(open(f, encoding="utf-8")): audit[n] = (t, p, gap, note)
    missing = [n for n in rows if n not in audit]
    print(f"audited {len(audit)} of {len(rows)} cards" + (f"; missing: {missing}" if missing else ""))

    gefs = {}
    for f in sorted(glob.glob(os.path.join(P, "out", "batch_*.json"))) + [os.path.join(P, "out", "retry_01.json")]:
        for x in json.load(open(f, encoding="utf-8")): gefs[x["name"]] = x
    idx = mtg.index()

    for scope in ("all", "deck", "pool"):
        names = [n for n in rows if scope == "all" or src.get(n) == scope]
        tv = Counter(audit[n][0] for n in names if n in audit)
        pv = Counter(audit[n][1] for n in names if n in audit)
        cross = Counter((audit[n][0], audit[n][1]) for n in names if n in audit)
        gaps = sum(1 for n in names if n in audit and audit[n][2])
        print(f"\n== {scope}: {len(names)} cards")
        print("  translation:", dict(tv))
        print("  parser:     ", dict(pv))
        print("  cards with a real format gap:", gaps)
        print("  cross (translation, parser):", dict(cross))
        ps = Counter(rows[n]["parser_status"] for n in names)
        gt = Counter(rows[n].get("gef_today") for n in names)
        ge = Counter(rows[n].get("gef_expressed") for n in names)
        gd = Counter(V.status(demote_freetext(gefs[n]), idx[n.lower()], today=False) for n in names)
        gdt = Counter(V.status(demote_freetext(gefs[n]), idx[n.lower()]) for n in names)
        def fr(c): return sum(v for k, v in c.items() if full(k))
        print(f"  fully read: parser {fr(ps)}, GEF today {fr(gt)} (freetext demoted {fr(gdt)}), "
              f"GEF expressed {fr(ge)} (freetext demoted {fr(gd)})")
        print("  parser statuses:", dict(ps))
        print("  GEF today:      ", dict(gt))
        print("  GEF expressed (freetext demoted):", dict(gd))

    agree = [n for n in rows if rows[n].get("agree")]
    dis = [n for n in rows if not rows[n].get("agree")]
    def bad(n): return audit[n][0] in ("wrong", "freetext") or audit[n][1] == "wrong"
    print(f"\ncomparator: {len(agree)} agree, {len(dis)} flagged; "
          f"errors (translation wrong/freetext or parser wrong) among agree {sum(bad(n) for n in agree)}, among flagged {sum(bad(n) for n in dis)}")
    for n in agree:
        if bad(n): print("   missed by comparator:", n, audit[n][:2])


def features(x, out):
    """Engine features a GEF card uses that the engine lacks today (by the validator's support tables)."""
    if isinstance(x, list):
        for v in x: features(v, out)
        return out
    if not isinstance(x, dict): return out
    if "do" in x and x["do"] not in V.ENGINE_EFFECTS | {"unexpressible"}: out.add("effect " + x["do"])
    if x.get("kind") == "keyword" and x["keyword"] not in V.ENGINE_KEYWORDS | V.SILENT_KEYWORDS: out.add("keyword " + x["keyword"])
    if x.get("kind") == "static" and x["effect"]["static"] not in V.ENGINE_STATICS: out.add("static " + x["effect"]["static"])
    if isinstance(x.get("event"), dict) and x["event"].get("on") not in V.ENGINE_EVENTS: out.add("event " + x["event"]["on"])
    if "if" in x and isinstance(x["if"], str) and x["if"] not in V.ENGINE_CONDS: out.add("cond " + x["if"])
    for v in x.values(): features(v, out)
    return out

def engine_work():
    """Greedy: which missing engine features unlock the most deck cards from 'not fully read today' to fully read."""
    rows = {r["name"]: r for r in json.load(open(os.path.join(P, "compare.json"), encoding="utf-8"))}
    src = {r["name"]: r["from"] for r in json.load(open(os.path.join(P, "cards.json"), encoding="utf-8"))}
    gefs = {}
    for f in sorted(glob.glob(os.path.join(P, "out", "batch_*.json"))) + [os.path.join(P, "out", "retry_01.json")]:
        for x in json.load(open(f, encoding="utf-8")): gefs[x["name"]] = x
    idx = mtg.index()
    need = {}
    for n, g in gefs.items():
        d = demote_freetext(g); card = idx[n.lower()]
        if full(V.status(d, card, today=False)) and not full(V.status(d, card)):
            need[n] = features(d, set())
    for scope in ("deck", "all"):
        todo = {n: set(f) for n, f in need.items() if scope == "all" or src.get(n) == scope}
        print(f"\nengine work to reach 'expressed' ({scope}): {len(todo)} cards blocked only by missing engine features")
        done, step = 0, 0
        while todo and step < 15:
            cnt = Counter(f for fs in todo.values() for f in fs)
            best = max(cnt, key=lambda f: (sum(1 for fs in todo.values() if fs <= {f}), cnt[f]))
            for fs in todo.values(): fs.discard(best)
            freed = [n for n, fs in todo.items() if not fs]
            for n in freed: del todo[n]
            done += len(freed); step += 1
            print(f"  +{best:32s} unlocks {len(freed):2d} (cumulative {done})")
        if todo: print(f"  ... {len(todo)} more cards need {len(Counter(f for fs in todo.values() for f in fs))} further features")

def per_deck():
    """Fully read per test deck (same denominator as T0: the deck's cards except plain lands), with audit-wrong reads removed."""
    rows = {r["name"]: r for r in json.load(open(os.path.join(P, "compare.json"), encoding="utf-8"))}
    audit = {}
    for f in sorted(glob.glob(os.path.join(P, "audit_batch*.json"))):
        for n, t, p, gap, note in json.load(open(f, encoding="utf-8")): audit[n] = (t, p, gap)
    print("\nper deck: cards | parser fully read (of which audit-wrong) | GEF today | GEF expressed (of which audit-wrong) | cards with a real format gap")
    for d in sorted(glob.glob(os.path.join(HERE, "decks", "*.txt"))):
        names = []
        for sec, q, n in mtg.parse_deck(d):
            c, _ = mtg.find(n)
            if c["name"] in rows and c["name"] not in names: names.append(c["name"])
        pf = [n for n in names if full(rows[n]["parser_status"])]
        gt = [n for n in names if full(rows[n]["gef_today"])]
        ge = [n for n in names if full(rows[n]["gef_expressed"])]
        pct = lambda k: f"{k} ({100 * k / len(names):.1f}%)"
        print(f"  {os.path.basename(d):12s} {len(names)} | {pct(len(pf))} ({sum(audit[n][1] == 'wrong' for n in pf)}) | {pct(len(gt))} | "
              f"{pct(len(ge))} ({sum(audit[n][0] == 'wrong' for n in ge)}) | {sum(1 for n in names if audit[n][2])}")

if __name__ == "__main__":
    main()
    per_deck()
    engine_work()

