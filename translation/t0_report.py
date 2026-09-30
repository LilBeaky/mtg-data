#!/usr/bin/env python3
"""T0 numbers: per-deck coverage, the card-level effect of translation (parse gaps closed), and the mechanics ranked
by the card weight they unlock (greedy), for the pool and for the decks in translation/decks/.

  python3 translation/t0_extract.py && python3 translation/t0_decompose.py && python3 translation/t0_report.py
"""
import collections, glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mtg                                                  # noqa: E402

OUT = os.path.join(ROOT, "translation", "out")
READ = ("modeled", "held", "vacuum", "override")

def load():
    cards = {}
    for ln in open(os.path.join(OUT, "t0_cards.jsonl"), encoding="utf-8"):
        r = json.loads(ln); cards[r["name"]] = r
    lines = collections.defaultdict(list)
    for ln in open(os.path.join(OUT, "t0_lines.jsonl"), encoding="utf-8"):
        x = json.loads(ln); lines[x["name"]].append(x)
    return cards, lines

def mechanics(name, cards, lines, scopes=("sim", "approx", "disr")):
    """What a not-fully-read card still needs once parse gaps are closed: a set of mechanic labels, or None when a
    line needs something outside scopes (the card can't be completed within them)."""
    need = set()
    for x in lines.get(name, []):
        if x["verdict"] == "oos": continue
        if x["verdict"] == "parse gap": continue
        if x["verdict"] == "unclassified":
            need.add("unclassified: " + name + " / " + x["text"][:40]); continue
        for comp, lab, sc, en in x["parts"]:
            if en == "has": continue
            if sc not in scopes: return None
            need.add(lab)
    return need

def greedy(pop, cards, lines, scopes, steps=40):
    """pop: names of cards not fully read. Returns (fixed_by_translation_weight, [(mechanic, gained_weight, n_cards)])."""
    need = {n: mechanics(n, cards, lines, scopes) for n in pop}
    w = {n: cards[n]["weight"] for n in pop}
    base = [n for n, s in need.items() if s == set()]
    left = {n: s for n, s in need.items() if s}
    chosen, curve = set(), []
    for _ in range(steps):
        gain = collections.Counter(); cnt = collections.Counter()
        for n, s in left.items():
            rest = s - chosen
            if len(rest) == 1:
                m = next(iter(rest)); gain[m] += w[n]; cnt[m] += 1
        if not gain: break
        m, gw = max(gain.items(), key=lambda kv: (kv[1], cnt[kv[0]]))
        chosen.add(m)
        done = [n for n, s in left.items() if s <= chosen]
        for n in done: del left[n]
        curve.append((m, gw, cnt[m]))
    blocked = sum(1 for s in need.values() if s is None)
    return base, curve, need, blocked

def deck_names(path):
    out = []
    for sec, q, name in mtg.parse_deck(path):
        c, how = mtg.find(name)
        out.append((sec, q, c["name"] if c else name))
    return out

def main():
    cards, lines = load()
    nonland = {n: r for n, r in cards.items() if r["status"] != "land"}
    totw = sum(r["weight"] for r in nonland.values())
    readw = sum(r["weight"] for r in nonland.values() if r["status"] in READ)
    pop = [n for n, r in nonland.items() if r["status"] not in READ]
    print(f"pool: {len(nonland)} nonland cards (incl. land*), fully read weighted {100 * readw / totw:.1f}%")

    for label, scopes in (("all in-scope mechanics (sim + approx + disr)", ("sim", "approx", "disr")),
                          ("sim only (no opponent stand-ins, no disruption-only)", ("sim",))):
        base, curve, need, blocked = greedy(pop, cards, lines, scopes, steps=200)
        bw = sum(cards[n]["weight"] for n in base)
        print(f"\n== {label}")
        print(f"translation alone (parse gaps closed, out-of-scope lines honest): +{100 * bw / totw:.1f} pts "
              f"-> {100 * (readw + bw) / totw:.1f}% ({len(base)} cards)")
        cum = readw + bw
        marks = {5, 10, 20, 30, 40, 50, 75, 100, 150, 200}
        for i, (m, gw, n) in enumerate(curve, 1):
            cum += gw
            if i <= 25 or i in marks:
                print(f"  {i:3} +{100 * gw / totw:4.2f} pts ({n:4} cards) -> {100 * cum / totw:5.1f}%  {m}")
        nm = sum(1 for s in need.values() if s)
        distinct = set().union(*[s for s in need.values() if s]) if nm else set()
        print(f"  cards still needing mechanics after translation: {nm}; distinct mechanic labels among them: {len(distinct)}; "
              f"cards needing an out-of-scope stand-in: {blocked}")
        tail = sum(cards[n]["weight"] for n, s in need.items() if s and any(x.startswith("unclassified") for x in s))
        print(f"  weight on cards with an unclassified line: {100 * tail / totw:.2f} pts")

    # ---- oos-only vs parse-gap split of 'translation alone'
    base, _, need, _ = greedy(pop, cards, lines, ("sim", "approx", "disr"), steps=0)
    oos_only = [n for n in base if all(x["verdict"] == "oos" for x in lines.get(n, []))]
    print(f"\nof the translation-alone cards: {len(oos_only)} have only out-of-scope unread lines "
          f"(+{100 * sum(cards[n]['weight'] for n in oos_only) / totw:.2f} pts: a status rule, not translation); "
          f"{len(base) - len(oos_only)} need parse gaps closed "
          f"(+{100 * sum(cards[n]['weight'] for n in base if n not in oos_only) / totw:.2f} pts)")

    # ---- pessimistic granularity: catch-all labels become one mechanic per line template
    vague = lambda lab: "(other)" in lab or lab.endswith(": other") or lab.startswith("unclassified") or lab.startswith("static rules")
    import re as _re
    def norm(t):
        t = t.lower(); t = _re.sub(r"\{[^}]+\}", "{M}", t)
        return _re.sub(r"\b(\d+|x|a|an|one|two|three|four|five)\b", "N", t)
    lines2 = {}
    for n, xs in lines.items():
        ys = []
        for x in xs:
            x = dict(x); x["parts"] = [(c, (norm(x["text"])[:90] if vague(l) else l), sc, en) for c, l, sc, en in x["parts"]]
            ys.append(x)
        lines2[n] = ys
    base, curve, need, _ = greedy(pop, cards, lines2, ("sim", "approx", "disr"), steps=400)
    cum = readw + sum(cards[n]["weight"] for n in base)
    pts = {}
    for i, (m, gw, k) in enumerate(curve, 1):
        cum += gw
        if i in (10, 25, 50, 100, 200, 300, 400): pts[i] = 100 * cum / totw
    print("pessimistic (catch-alls split per line template): after N mechanics ->",
          ", ".join(f"{k}: {v:.1f}%" for k, v in pts.items()),
          f"; distinct labels needed by the remaining cards: {len(set().union(*[s for s in need.values() if s]))}")

    # ---- decks (hand labels for every unread line)
    hl = json.load(open(os.path.join(ROOT, "translation", "t0_handlabels.json"), encoding="utf-8"))
    deckmech = collections.Counter(); deckcards = collections.defaultdict(set)
    for path in sorted(glob.glob(os.path.join(ROOT, "translation", "decks", "*.txt"))):
        ents = deck_names(path)
        dn = os.path.basename(path)[:-4]
        tot = sum(q for _, q, _ in ents)
        st = collections.Counter(); wsum = collections.Counter()
        for sec, q, n in ents:
            r = cards[n]; st[r["status"]] += q; wsum[r["status"]] += r["weight"] * q
        nl = {s: v for s, v in st.items() if s != "land"}
        nlc = sum(nl.values()); nlw = sum(v for s, v in wsum.items() if s != "land")
        fr = sum(nl.get(s, 0) for s in READ); frw = sum(wsum.get(s, 0) for s in READ)
        print(f"\n######## {dn}: {tot} cards ({st['land']} lands fully read, {nlc} nonland or land*)")
        print("  status (copies):", ", ".join(f"{s} {v}" for s, v in st.most_common()))
        print(f"  fully read, nonland+land*: {fr}/{nlc} = {100 * fr / nlc:.1f}% (popularity-weighted {100 * frw / nlw:.1f}%); "
              f"all 100 incl. plain lands: {100 * (fr + st['land']) / tot:.1f}%")
        after = fr; unlock = collections.defaultdict(list); left = {}
        for sec, q, n in ents:
            r = cards[n]
            if r["status"] in READ or r["status"] == "land": continue
            labs = hl["deck"].get(n)
            if labs is None: left[n] = {"(approximation notes only)"}; continue
            ms = {m for _, v, mm, _ in labs if v == "engine" for m in mm}
            if not ms: after += q; continue
            left[n] = ms
            for m in ms: deckmech[m] += 1; deckcards[m].add(n)
        print(f"  after translation (parse gaps closed, out-of-scope lines honest): {after}/{nlc} = {100 * after / nlc:.1f}%")
        chosen, curve = set(), []
        while True:
            gain = collections.Counter()
            for n, ms in left.items():
                rest = ms - chosen
                if len(rest) == 1: gain[next(iter(rest))] += 1
            if not gain: break
            m, k = max(gain.items(), key=lambda kv: (kv[1], kv[0]))
            chosen.add(m); curve.append((m, k)); after += k
            left = {n: ms for n, ms in left.items() if not ms <= chosen}
        c2 = after - sum(k for _, k in curve)
        for m, k in curve:
            c2 += k
            print(f"    + {m:<58} unlocks {k} -> {100 * c2 / nlc:.1f}%")
        print(f"  still blocked: {sorted(left)}")
    # ---- modelable ceiling (pool, classifier; decks, hand labels)
    def ceiling_pool():
        agg = collections.Counter()
        for n, r in nonland.items():
            st = r["status"]
            if st in ("held", "vacuum"): agg["read, out of scope: held interaction / vacuum"] += r["weight"]; continue
            if st in ("modeled", "override"): agg["read and simulated"] += r["weight"]; continue
            sc = set()
            for x in lines.get(n, []):
                if x["verdict"] in ("oos", "parse gap"): continue
                if x["verdict"] == "unclassified": sc.add("sim"); continue
                sc |= {p[2] for p in x["parts"] if p[3] != "has"}
            k = ("unread: parse gaps / out-of-scope lines only" if not sc else
                 "unread: needs an opponent stand-in (approx)" if "approx" in sc else
                 "unread: disruption-only extras" if "disr" in sc else "unread: needs sim-scope mechanics only")
            agg[k] += r["weight"]
        return agg
    print("\nmodelable ceiling, pool (weighted):")
    for k, v in ceiling_pool().most_common(): print(f"  {100 * v / totw:5.1f}%  {k}")
    for path in sorted(glob.glob(os.path.join(ROOT, "translation", "decks", "*.txt"))):
        agg = collections.Counter(); tot = 0
        for sec, q, n in deck_names(path):
            r = cards[n]; st = r["status"]
            if st == "land": continue
            tot += q
            if st in ("held", "vacuum"): agg["read, out of scope: held / vacuum"] += q; continue
            if st in ("modeled", "override"): agg["read and simulated"] += q; continue
            labs = hl["deck"].get(n)
            if labs is None: agg["land*: approximation notes only"] += q; continue
            sc = {x[3] for x in labs if x[1] == "engine"}
            agg["unread: parse gaps / out-of-scope only" if not sc else "unread: needs a stand-in (approx)" if "approx" in sc
                else "unread: disruption-only" if "disr" in sc else "unread: sim-scope mechanics only"] += q
        print(f"  {os.path.basename(path)[:-4]}: " + "; ".join(f"{k} {v} ({100 * v / tot:.0f}%)" for k, v in agg.most_common()))

    # ---- classifier validation against hand labels
    conf = collections.Counter()
    for name, clf, hand, _ in hl["pool_sample"]:
        if hand == "skip": continue
        conf[(clf.replace(" gap", ""), hand)] += 1
    dconf = collections.Counter()
    for name, labs in hl["deck"].items():
        for pre, verdict, mm, sc in labs:
            x = next((x for x in lines.get(name, []) if x["text"].lower().startswith(pre.lower()[:25])), None)
            if x: dconf[(x["verdict"].replace(" gap", ""), verdict)] += 1
    for title, cc in (("pool sample (100 weighted lines)", conf), ("deck lines", dconf)):
        n = sum(cc.values()); agree = sum(v for (a, b), v in cc.items() if a == b)
        print(f"\nclassifier vs hand, {title}: {agree}/{n} verdicts agree ({100 * agree / n:.0f}%)")
        for (a, b), v in sorted(cc.items()): print(f"    classifier {a:<12} hand {b:<7} {v}")
        pp = sum(v for (a, b), v in cc.items() if a == "parse"); tp = cc[("parse", "parse")]
        hp = sum(v for (a, b), v in cc.items() if b == "parse")
        print(f"    parse-gap precision {tp}/{pp}, recall {tp}/{hp}")

    print("\nmechanics across the three decks (cards needing each):")
    for m, k in deckmech.most_common(): print(f"  {k:2}  {m:<58} {sorted(deckcards[m])[:6]}")

if __name__ == "__main__":
    main()
