#!/usr/bin/env python3
"""T2 numbers: reject rate, hand-audit verdicts for translator and parser, and fully-read counts on the 300 cards.

  python3 translation/t2_report.py     # needs translation/prototype/compare.json (t2_compare.py) and audit_batch*.json

The second half reports GEF 0.2 (T3 step 1): translation/gef02/t2_cards.json (python3 translation/gef02.py merge) and its
audit translation/gef02/audit.json (rows: name, pass, translation verdict, format_gap, note; pass = first | retry).
Its engine ranking is the one T3 step 3 re-runs after each engine feature.

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
        print(f"  fully read: parser {fr(ps)}, GEF today {fr(gt)} (freetext demoted, current validator: {fr(gdt)}), "
              f"GEF expressed {fr(ge)} (freetext demoted, current validator: {fr(gd)})")
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
    if "kind" in x: out.update(V._field_lacks(x))
    if "if" in x and isinstance(x["if"], str) and x["if"] not in V.ENGINE_CONDS: out.add("cond " + x["if"])
    for v in x.values(): features(v, out)
    return out

def engine_work(gefs=None, label=""):
    """Greedy: which missing engine features unlock the most deck cards from 'not fully read today' to fully read."""
    src = {r["name"]: r["from"] for r in json.load(open(os.path.join(P, "cards.json"), encoding="utf-8"))}
    if gefs is None:
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
        print(f"\nengine work to reach 'expressed'{label} ({scope}): {len(todo)} cards blocked only by missing engine features")
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

P2 = os.path.join(HERE, "gef02")

def deck_names():
    out = {}
    for d in sorted(glob.glob(os.path.join(HERE, "decks", "*.txt"))):
        names = []
        for sec, q, n in mtg.parse_deck(d):
            c, _ = mtg.find(n)
            if c["name"] not in names: names.append(c["name"])
        out[os.path.basename(d)] = names
    return out

def gef02():
    """GEF 0.2 on the T2 cards: validation, free text, audit of the re-translations, fully read per deck."""
    path = os.path.join(P2, "t2_cards.json")
    if not os.path.exists(path): return print("\n(no translation/gef02/t2_cards.json: run translation/gef02.py merge)")
    g2 = {x["name"]: x for x in json.load(open(path, encoding="utf-8"))}
    rows = {r["name"]: r for r in json.load(open(os.path.join(P, "compare.json"), encoding="utf-8"))}
    src = {r["name"]: r["from"] for r in json.load(open(os.path.join(P, "cards.json"), encoding="utf-8"))}
    a1 = {}
    for f in sorted(glob.glob(os.path.join(P, "audit_batch*.json"))):
        for n, t, p, gap, note in json.load(open(f, encoding="utf-8")): a1[n] = (t, p, gap)
    from gef02 import RETRY_OK                            # audited wrong on T2's first pass; the retry in the set is correct
    for n in RETRY_OK: a1[n] = ("correct",) + a1[n][1:]
    a2 = {}
    for n, ps, t, gap, note in json.load(open(os.path.join(P2, "audit.json"), encoding="utf-8")):
        a2.setdefault(n, {})[ps] = (t, gap)
    idx, m = mtg.index(), V.load_cards()
    print("\n\n==== GEF 0.2 (T3 step 1): translation/gef02/t2_cards.json")
    bad = [n for n, x in g2.items() if V.validate(x, m)[0]]
    ex = json.load(open(os.path.join(HERE, "examples", "examples.json"), encoding="utf-8"))
    exbad = [x["name"] for x in ex if V.validate(x, m)[0]]
    ft = sum(1 for x in g2.values() for o, _ in V._nodes(x) if o.get("static") in ("replacement", "restriction", "hand_ability"))
    print(f"  validates: {len(g2) - len(bad)}/{len(g2)}{' rejected: ' + ', '.join(bad) if bad else ''}; T1 examples {len(ex) - len(exbad)}/{len(ex)}; "
          f"free-text statics: {ft}")
    first = Counter(v["first"][0] for v in a2.values() if "first" in v)
    final = Counter((v.get("retry") or v["first"])[0] for v in a2.values())
    print(f"  re-translated: {len(a2)} cards; audit first pass {dict(first)}; after retry {dict(final)}")
    def verdict(n): return (a2[n].get("retry") or a2[n]["first"])[0] if n in a2 else a1[n][0]
    def gap(n): return (a2[n].get("retry") or a2[n]["first"])[1] if n in a2 else a1[n][2]
    wrong = {n for n in g2 if verdict(n) == "wrong"}
    print(f"  translations audit-wrong in the 0.2 set: {len(wrong)}{' (' + ', '.join(sorted(wrong)) + ')' if wrong else ''}; "
          f"cards with a real format gap: {sum(1 for n in g2 if gap(n))} (T2: {sum(1 for n in g2 if a1[n][2])})")
    st = {n: (V.status(x, idx[n.lower()]), V.status(x, idx[n.lower()], today=False)) for n, x in g2.items()}
    for scope in ("all", "deck", "pool"):
        names = [n for n in g2 if scope == "all" or src.get(n) == scope]
        print(f"  {scope:4s} {len(names)}: fully read parser {sum(full(rows[n]['parser_status']) for n in names)}, "
              f"GEF 0.1 today {sum(full(rows[n]['gef_today']) for n in names)} -> 0.2 today {sum(full(st[n][0]) for n in names)}, "
              f"0.1 expressed {sum(full(rows[n]['gef_expressed']) for n in names)} -> 0.2 expressed {sum(full(st[n][1]) for n in names)}")
    print("\n  per deck: cards | parser (audit-wrong) | GEF 0.1 today -> 0.2 today | GEF 0.1 expressed -> 0.2 expressed (audit-wrong) | real gaps 0.1 -> 0.2")
    for d, names in deck_names().items():
        names = [n for n in names if n in g2]
        pct = lambda k: f"{k} ({100 * k / len(names):.1f}%)"
        pf = [n for n in names if full(rows[n]["parser_status"])]
        e2 = [n for n in names if full(st[n][1])]
        print(f"  {d:12s} {len(names)} | {pct(len(pf))} ({sum(a1[n][1] == 'wrong' for n in pf)}) | "
              f"{pct(sum(full(rows[n]['gef_today']) for n in names))} -> {pct(sum(full(st[n][0]) for n in names))} | "
              f"{pct(sum(full(rows[n]['gef_expressed']) for n in names))} -> {pct(len(e2))} ({sum(n in wrong for n in e2)}) | "
              f"{sum(1 for n in names if a1[n][2])} -> {sum(1 for n in names if gap(n))}")
    moved = [(n, rows[n]["gef_today"], st[n][0], rows[n]["gef_expressed"], st[n][1]) for n in g2
             if full(rows[n]["gef_expressed"]) != full(st[n][1]) or full(rows[n]["gef_today"]) != full(st[n][0])]
    print(f"\n  fully-read changes 0.1 -> 0.2 ({len(moved)}; today, expressed):")
    for n, a, b, c, d in sorted(moved, key=lambda r: r[0]): print(f"    {n:40s} today {a} -> {b}; expressed {c} -> {d}")
    engine_work(g2, " [GEF 0.2]")

if __name__ == "__main__":
    main()
    per_deck()
    engine_work(label=" [GEF 0.1, as in T2]")
    gef02()

