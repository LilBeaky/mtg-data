#!/usr/bin/env python3
"""
landbase.py — land count and land swaps for a Commander deck (mtg-data).

  python3 scripts/landbase.py DECK [options]           (run from the repo root)

  --commander NAME    if the list has no Commander section
  --draw              odds on the draw (default: on the play)
  --turn T            development target: T mana by turn T (default 3)
  --develop P         target odds for that, in % (default 80)
  --screw P           cap on "2 or fewer lands by T4", in % (default 20)
  --flood P           cap on "8+ mana sources in the first 12 cards", in % (default 25)
  --lands N           skip the count search and plan for N lands
  --swaps N           most land-for-land swaps to suggest (default 4)
  --max-price N       candidate lands at most $N (unpriced lands are left out)
  --cut-utility       allow cutting lands that do more than make mana (default: never)
                      Candidates are always plain mana lands (duals, tri-lands, painlands, fetches,
                      any-color lands); utility lands are the user's call, not a color fix
  --no-count          keep the current land count
  --no-swaps          land count only

REPORT
  1 Land count   every count from 4 under to 4 over: T mana by turn T (lands, MDFC land backs,
                 ramp of MV 2 or less), commander on curve, screw, flood, keepable openers;
                 the recommendation is the smallest count meeting --develop and --screw
  2 Colors now   land sources per color and the cards under their on-curve threshold
                 (audit section 2's numbers: 90% for the commander and package pieces, 80% otherwise)
  3 Plan         lands to add or cut to reach the count, then swaps, chosen greedily by how
                 much they lift the color odds; untapped beats tapped, and cheap beats expensive
                 (about $30 weighs the same as "conditionally tapped"), at equal colors
  4 Before → after   the whole plan at once: count metrics and every flagged card's odds

Adding lands means cutting nonlands; which ones is the user's call, so the plan only says how many.
Lands that do more than make mana (cycling, creature lands, utility) are never cut unless
--cut-utility. A land that is the deck's only source of a color is never cut.
A fetch already in the deck counts every color it can find (as in the audit); a suggested fetch counts
only the basics it can find, since several fetches can't all find the same typed dual.
Static draws only, as in the audit: no card draw, cycling, fetch thinning or land tutoring.
Color odds are lands only and assume enough lands (the count section covers running out).
"""
import argparse, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import mtg
import stats_math as sm
from audit import is_land, tapped_kind, pct

gf = sm._gf()
TAP_COST = {"always": 0.004, "conditional": 0.0015, None: 0.0}   # tie-breakers, in odds units
PRICE_COST = 0.00005          # per dollar on a land being bought: ~$30 weighs like "conditionally tapped"; unpriced = $50
MIN_GAIN = 0.005                                                    # a swap must improve the score by this much
# A land is "plain" (safe to cut) only if every line of its text is one of these: a simple colored tap
# (painland damage allowed), any-color tap, entering tapped (with the usual conditions), or a basic fetch.
# Everything else (cycling, sacrifice outlets, {C}{C}, conditional colors, creature lands...) is utility.
SYM = r"\{[WUBRG]\}"
PLAIN_LINE_RX = re.compile(
    r"^\(.*\)$"
    rf"|^\{{T\}}: Add {SYM}(?:(?:,| or)(?: or)? {SYM})*\.(?: [^.]+ deals 1 damage to you\.)?$"
    r"|^\{T\}: Add \{C\}\.$"
    r"|^\{T\}: Add one mana of any color(?: in your commander's color identity| that a land an opponent controls could produce)?\.$"
    r"|^When this land enters, scry 1\.(?: \(.*\))?$"
    r"|^Whenever this land becomes tapped, it deals 1 damage to you\.$"
    r"|^[^.]* enters(?: the battlefield)? tapped(?: unless [^.]+)?\.$"
    r"|^As [^,]+ enters,? you may (?:pay 2 life|reveal [^.]+)\. If you (?:don't|do not)[^.]*, (?:it|this land) enters tapped\.$"
    r"|^\{T\}, (?:Pay 1 life, )?Sacrifice [^:]+: Search your library for an? (?:basic land|[A-Z][a-z]+(?: or [A-Z][a-z]+)?) card,? "
    r"(?:and )?put it onto the battlefield(?: tapped)?, then shuffle\.(?: Then if you control four or more lands, untap that land\.)?$")


# "enters tapped unless ..." graded for the early turns that matter here
EARLY_TAPPED_RX = re.compile(r"tapped unless (?:a player has 13 or less life|you control a planeswalker|"
                             r"you control a legendary (?:creature|permanent)|you control (?:three|four) or more other lands)", re.I)
EARLY_UNTAPPED_RX = re.compile(r"tapped unless you have two or more opponents", re.I)


def tap_kind(c):
    t = mtg.text_of(c)
    if EARLY_UNTAPPED_RX.search(t): return None
    if EARLY_TAPPED_RX.search(t): return "always"
    return tapped_kind(c)


def is_utility(c):
    if "Basic" in c.get("type_line", ""): return False
    lines = [l.strip() for l in mtg.text_of(c).replace(c["name"], "This").split("\n") if l.strip()]
    return any(not PLAIN_LINE_RX.search(l) for l in lines)


class Land:
    def __init__(self, card, qty, cols, in_deck):
        self.card, self.name, self.qty, self.cols = card, card["name"], qty, frozenset(cols)
        self.tapped = tap_kind(card)
        self.basic = "Basic" in card.get("type_line", "")
        self.utility = is_utility(card)
        self.in_deck = in_deck

    def desc(self):
        t = {"always": "tapped early", "conditional": "conditionally tapped", None: "untapped"}[self.tapped]
        return f"{''.join(sorted(self.cols)) or 'C'}, {t}"


def load(path, cmd_over):
    """Deck sources, compiled the same way stats_math.color_report compiles them."""
    N, lib, cmdrs, anyc = sm._deck(path, cmd_over)
    land_k = [k for q, c, k in lib if k.is_land]
    lands, mdfc, rocks = [], 0, []
    for q, c, k in lib:
        if k.is_land:
            if sm._restricted_only(k) and not sm._produced(k, land_k): continue
            lands.append(Land(c, q, sm._produced(k, land_k), True))
        elif k.mdfc is not None and getattr(k.mdfc, "is_land", False):
            mdfc += q
        elif k.units and k.cat == "ramp":
            rocks.append((q, c["name"], int(c.get("cmc", 0))))
    return N, lib, cmdrs, anyc, land_k, lands, mdfc, rocks


def candidates(deck_names, anyc, land_k, basics_k, max_price, bracket):
    """Plain mana lands not in the deck that make at least one of the deck's colors, one per (colors, tapped)
    profile: the cheapest (the model can't tell lands of one profile apart). Basics are always available."""
    pool = {}
    for c in mtg.cards():
        if c["name"] in deck_names or not is_land(c) or mtg.legal(c) != "legal": continue
        if not set(c.get("color_identity", [])) <= anyc: continue
        if "Snow" in c.get("type_line", "") and "Basic" in c.get("type_line", ""): continue
        pm = set(c.get("produced_mana") or [])
        if pm and not (pm & anyc) and "earch" not in mtg.text_of(c): continue
        if c.get("game_changer") and (bracket or 5) <= 3: continue
        if max_price is not None and (mtg.price(c) is None or mtg.price(c) > max_price): continue
        if is_utility(c): continue                  # conditional colors, filters, restrictions: not plain fixing
        k = gf.compile_card(c, anyc)
        if not k.is_land: continue
        if sm._restricted_only(k) and not sm._produced(k, land_k): continue
        # a new fetch counts only the basics it can find: several fetches can't all find the same typed dual
        cols = (sm._produced(k, basics_k) if k.fetch else sm._produced(k, land_k)) & (anyc | {"C"})
        direct = cols if k.fetch else frozenset().union(*(frozenset(u[0]) for u in k.units))
        if not direct & anyc: continue                  # filter lands need other mana to make a color: not fixing
        cols = cols & (direct | {"C"})
        L = Land(c, 0, cols, False)
        pool.setdefault((L.cols, L.tapped), []).append(L)
    out = []
    for key, ls in pool.items():
        # lands of one (colors, tapped) profile are equal to the model, so the cheapest goes first; unpriced last
        ls.sort(key=lambda L: (not L.basic, mtg.price(L.card) is None, mtg.price(L.card) or 0,
                               L.card.get("edhrec_rank") or 10**7))
        for L in ls: L.profile = key
        out.append(ls[0])
    return out, pool


def pool_all(pool, cols):
    return [L for (c2, t), ls in pool.items() if c2 == cols for L in ls]


def castable(N, sources, pips, mv, n):
    """sm.castable_on_curve, same exact answer, with Hall's condition precomputed per pip subset
    (the scorer calls it hundreds of times). Falls back to stats_math's sampler for huge profiles."""
    from itertools import combinations
    import math
    need = {}
    for cols in pips: need[cols] = need.get(cols, 0) + 1
    types = list(need.items())
    cats = [(K, key) for K, key in sources if K > 0]
    mv = max(mv, sum(need.values()))
    size = 1
    for K, _ in cats: size *= min(K, n) + 1
    if size > 400_000: return sm.castable_on_curve(N, sources, pips, mv, n)
    checks = []
    for r in range(1, len(types) + 1):
        for S in combinations(types, r):
            union = frozenset().union(*(c for c, _ in S))
            checks.append((sum(k for _, k in S), [i for i, (K, key) in enumerate(cats) if key & union]))
    other = N - sum(K for K, _ in cats)
    p_cond = p_ok = 0.0
    seen = [0] * len(cats)
    def rec(i, left, w):
        nonlocal p_cond, p_ok
        if i == len(cats):
            if left > other or n - left < mv: return
            p = w * math.comb(other, left)
            p_cond += p
            if all(sum(seen[j] for j in idx) >= k for k, idx in checks): p_ok += p
            return
        K = cats[i][0]
        for x in range(0, min(K, left) + 1):
            seen[i] = x
            rec(i + 1, left - x, w * math.comb(K, x))
        seen[i] = 0
    rec(0, min(n, N), 1)
    return p_ok / p_cond if p_cond else 0.0


class Scorer:
    """Weighted shortfall of every colored card below its on-curve threshold, lands only."""
    def __init__(self, N, rows, on_play):
        self.N, self.rows, self.on_play, self.cache = N, rows, on_play, {}

    def odds(self, row, lands):
        rel = frozenset().union(*row["pips"])
        prof = {}
        for L in lands:
            if L.qty: prof[L.cols & rel] = prof.get(L.cols & rel, 0) + L.qty
        sig = (tuple(sorted(tuple(sorted(p)) for p in row["pips"])), row["mv"], tuple(sorted((tuple(sorted(k)), v) for k, v in prof.items())))
        if sig not in self.cache:
            self.cache[sig] = castable(self.N, list((v, k) for k, v in prof.items()), row["pips"], row["mv"],
                                                   sm.cards_seen(row["mv"], self.on_play))
        return self.cache[sig]

    def score(self, lands):
        s = 0.0
        for r in self.rows:
            w = 3 if r["cmdr"] else 2 if r["key"] else 1
            s += w * r["q"] * max(0.0, r["threshold"] - self.odds(r, lands))
        return s + sum(L.qty * TAP_COST[L.tapped] for L in lands) +             sum(L.qty * PRICE_COST * (50 if mtg.price(L.card) is None else mtg.price(L.card)) for L in lands if not L.in_deck)


def count_metrics(N, L, mdfc, cheap, rocks_all, turn, cmd_mv, on_play):
    LL = L + mdfc
    def by(T, need):          # need mana by turn T: lands, or one short plus a cheap ramp piece
        n = sm.cards_seen(T, on_play)
        p = sm.hyper_at_least(N, LL, n, need)
        if cheap and need >= 2:
            p += sm.multivariate_at_least(N, [(LL, need - 1), (cheap, 1)], n) - sm.multivariate_at_least(N, [(LL, need), (cheap, 1)], n)
        return p
    return {"develop": by(turn, turn),
            "cmdr": by(cmd_mv, cmd_mv) if cmd_mv else None,
            "screw": 1 - sm.hyper_at_least(N, LL, sm.cards_seen(4, on_play), 3),
            "flood": sm.hyper_at_least(N, LL + rocks_all, 12, 8),
            "keep": sum(sm.hyper_pmf(N, LL, 7, k) for k in (2, 3, 4))}


def safe_cut(L, lands, a):
    if L.qty <= 0 or (L.utility and not a.cut_utility) or L.name in PROTECT: return False
    for col in L.cols:
        if sum(x.qty for x in lands if col in x.cols) - 1 < 1: return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Land count and land swaps for a Commander deck.")
    ap.add_argument("deck")
    ap.add_argument("--commander"); ap.add_argument("--draw", action="store_true")
    ap.add_argument("--turn", type=int, default=3); ap.add_argument("--develop", type=float, default=80)
    ap.add_argument("--screw", type=float, default=20); ap.add_argument("--flood", type=float, default=25)
    ap.add_argument("--lands", type=int); ap.add_argument("--swaps", type=int, default=4)
    ap.add_argument("--max-price", type=float); ap.add_argument("--cut-utility", action="store_true")
    ap.add_argument("--no-count", action="store_true"); ap.add_argument("--no-swaps", action="store_true")
    a = ap.parse_args()
    _w = mtg.stale_warning()
    if _w: print(_w)
    on_play = not a.draw
    meta = mtg.parse_deck_meta(a.deck)
    PROTECT.update(c["name"] for c in (mtg.find(p)[0] for p in meta.get("pets", [])) if c)

    N, lib, cmdrs, anyc, land_k, lands, mdfc, rocks = load(a.deck, a.commander)
    cheap = sum(q for q, n, m in rocks if m <= 2)
    rocks_all = sum(q for q, n, m in rocks)
    cmd_mv = max([int(c.get("cmc", 0)) for c, k in cmdrs] or [0])
    L0 = sum(L.qty for L in lands)
    try:
        pkr = sm.packages_report(a.deck, a.commander, on_play)
        keys = set().union(*(m for pk in pkr.get("packages", []) if not pk["unresolved"] for m in pk["members"]))
    except Exception:
        keys = set()
    colr = sm.color_report(a.deck, a.commander, on_play, key_names=keys)
    qty = {}
    for q, c, k in lib: qty[c["name"]] = qty.get(c["name"], 0) + q
    rows = [dict(r, q=1 if r["cmdr"] else qty.get(r["name"], 1)) for r in colr["rows"]]
    scorer = Scorer(N, rows, on_play)

    print(f"=== LANDBASE: {' + '.join(c['name'] for c, k in cmdrs) or 'no commander'} | N={N} | {L0} lands"
          f"{f' + {mdfc} MDFC land backs' if mdfc else ''} | ramp {rocks_all} ({cheap} at MV ≤2) | "
          f"{'on the play' if on_play else 'on the draw'} ===")

    # ----- 1. land count -----
    T = a.turn
    print(f"\n## 1. Land count (targets: {T} mana by T{T} ≥ {a.develop:.0f}%, ≤2 lands by T4 ≤ {a.screw:.0f}%, "
          f"flood ≤ {a.flood:.0f}%)")
    print(f"  {'lands':>5}  {f'{T} mana by T{T}':>13}  {f'cmdr on T{cmd_mv}' if cmd_mv else '':>12}  {'screw':>6}  {'flood':>6}  {'keep 2–4':>8}")
    table = {}
    for Lx in range(max(0, L0 - 4), L0 + 5):
        m = count_metrics(N, Lx, mdfc, cheap, rocks_all, T, cmd_mv, on_play)
        table[Lx] = m
        ok = m["develop"] >= a.develop / 100 and m["screw"] <= a.screw / 100
        print(f"  {Lx:>5}  {pct(m['develop']):>13}  {pct(m['cmdr']) if m['cmdr'] is not None else '':>12}  "
              f"{pct(m['screw']):>6}  {pct(m['flood']):>6}  {pct(m['keep']):>8}"
              + ("  ← current" if Lx == L0 else "") + ("" if ok else "  (misses a target)"))
    if a.lands is not None:
        target = a.lands
        print(f"  planning for {target} lands (--lands)")
    elif a.no_count:
        target = L0
        print(f"  keeping {L0} lands (--no-count)")
    else:
        meets = [Lx for Lx in sorted(table) if table[Lx]["develop"] >= a.develop / 100 and table[Lx]["screw"] <= a.screw / 100]
        target = meets[0] if meets else L0 + 4
        if not meets:
            print(f"  no count within 4 of {L0} meets both targets; planning for {target}. More cheap ramp may be the better fix.")
        else:
            print(f"  recommendation: {target} lands ({'+' if target > L0 else ''}{target - L0} from now) — the smallest count "
                  f"that meets both targets")
        if table.get(target) and table[target]["flood"] > a.flood / 100:
            print(f"  ⚠ flood at {target} is {pct(table[target]['flood']).strip()}, over the {a.flood:.0f}% cap: "
                  f"trading lands for cheap ramp does both jobs")
    print(f"  ramp counted: {cheap} pieces at MV ≤2 as a land toward the target turn, all {rocks_all} toward flood"
          + (f"; {mdfc} MDFC land backs as lands" if mdfc else "") + ". Cost reducers and draw are not counted.")

    # ----- 2. colors now -----
    print("\n## 2. Colors now (land sources; cards under their on-curve threshold, lands only)")
    for col in sorted(anyc):
        print(f"  {col}: {sum(L.qty for L in lands if col in L.cols)} lands")
    flagged0 = [r for r in rows if scorer.odds(r, lands) < r["threshold"]]
    print(f"  under threshold: {len(flagged0)}" + (": " + "; ".join(
        f"{r['name']} {r['cost']} {pct(scorer.odds(r, lands)).strip()}" for r in sorted(flagged0, key=lambda r: scorer.odds(r, lands))[:8])
        if flagged0 else "") + (" …" if len(flagged0) > 8 else ""))

    # ----- 3. plan -----
    print("\n## 3. Plan")
    deck_names = {c["name"] for q, c, k in lib} | {c["name"] for c, k in cmdrs}
    basics_k = [k for q, c, k in lib if k.is_land and "Basic" in c.get("type_line", "")]
    cands, pool = candidates(deck_names, anyc, land_k, basics_k, a.max_price, meta.get("bracket"))
    cur = [Land(L.card, L.qty, L.cols, True) for L in lands]
    added, cut, swaps = [], [], []

    def add_land(proto):
        ex = next((x for x in cur if x.name == proto.name), None)
        if ex: ex.qty += 1
        else:
            cur.append(Land(proto.card, 1, proto.cols, False))
        if not proto.basic:
            cands.remove(proto)
            rest = [x for x in pool[proto.profile] if x is not proto and x.name not in {y.name for y in cur}]
            pool[proto.profile] = rest
            if rest: cands.append(rest[0])

    def best_add():
        base, best = scorer.score(cur), None
        for p in cands:
            x = Land(p.card, 1, p.cols, False); cur.append(x)
            s = scorer.score(cur); cur.remove(x)
            if best is None or s < best[0]: best = (s, p)
        return best[1] if best else None

    def best_cut():
        best = None
        for x in cur:
            if not safe_cut(x, cur, a): continue
            x.qty -= 1; s = scorer.score(cur); x.qty += 1
            if best is None or s < best[0]: best = (s, x)
        return best[1] if best else None

    for _ in range(max(0, target - L0)):
        p = best_add()
        if not p: break
        add_land(p); added.append(p)
    for _ in range(max(0, L0 - target)):
        x = best_cut()
        if not x: print("  ! ran out of lands that are safe to cut"); break
        x.qty -= 1; cut.append(x)

    if not a.no_swaps:
        for _ in range(a.swaps):
            base, best = scorer.score(cur), None
            for x in cur:
                if not safe_cut(x, cur, a): continue
                x.qty -= 1
                for p in cands:
                    if p.cols == x.cols and TAP_COST[p.tapped] >= TAP_COST[x.tapped]: continue
                    y = Land(p.card, 1, p.cols, False); cur.append(y)
                    s = scorer.score(cur); cur.remove(y)
                    if best is None or s < best[0]: best = (s, x, p)
                x.qty += 1
            if not best or base - best[0] < MIN_GAIN: break
            s, x, p = best
            x.qty -= 1; add_land(p); swaps.append((x, p))

    def price_of(L): return mtg.price(L.card) or 0.0
    def alt(p):
        same = [x for x in pool_all(pool, p.cols) if x.tapped == p.tapped and x.name != p.name] if not p.basic else []
        top = min(same, key=lambda x: x.card.get("edhrec_rank") or 10**7) if same else None
        if not top or (top.card.get("edhrec_rank") or 10**7) >= (p.card.get("edhrec_rank") or 10**7): return ""
        return f"  [same job, most played: {top.name} {mtg.price_str(top.card) or '(no price)'}]"
    if not (added or cut or swaps):
        print("  no change: the count meets the targets and no swap improves the color odds by enough to matter")
    if added:
        print(f"  add {len(added)} land(s), and cut {len(added)} nonland card(s) of your choice:")
        for p in added: print(f"    + {p.name} {mtg.price_str(p.card) or '(no price)'} ({p.desc()}){alt(p)}")
    if cut:
        print(f"  cut {len(cut)} land(s), and add {len(cut)} nonland card(s):")
        for x in cut: print(f"    − {x.name} ({x.desc()})")
    if swaps:
        print(f"  swaps ({len(swaps)}):")
        for x, p in swaps:
            print(f"    {x.name} ({x.desc()}) → {p.name} {mtg.price_str(p.card) or '(no price)'} ({p.desc()}){alt(p)}")
    cost = sum(price_of(p) for p in added) + sum(price_of(p) for x, p in swaps)
    if added or swaps:
        print(f"  lands bought: ${cost:,.2f} at cheapest printings"
              + (" (some unpriced)" if any(mtg.price(p.card) is None for p in added + [p for x, p in swaps]) else ""))
    utils = sorted({x.name for x in lands if x.utility})
    if utils and not a.cut_utility:
        print(f"  never cut (utility lands; --cut-utility to allow): {'; '.join(utils[:12])}" + (" …" if len(utils) > 12 else ""))

    # ----- 4. before -> after -----
    L1 = sum(x.qty for x in cur)
    m0, m1 = table.get(L0) or count_metrics(N, L0, mdfc, cheap, rocks_all, T, cmd_mv, on_play), \
             table.get(L1) or count_metrics(N, L1, mdfc, cheap, rocks_all, T, cmd_mv, on_play)
    print("\n## 4. Before → after")
    print(f"  lands {L0} → {L1} | {T} mana by T{T} {pct(m0['develop']).strip()} → {pct(m1['develop']).strip()} | "
          f"screw {pct(m0['screw']).strip()} → {pct(m1['screw']).strip()} | flood {pct(m0['flood']).strip()} → {pct(m1['flood']).strip()}"
          + (f" | cmdr on T{cmd_mv} {pct(m0['cmdr']).strip()} → {pct(m1['cmdr']).strip()}" if cmd_mv else ""))
    for col in sorted(anyc):
        b, c2 = sum(L.qty for L in lands if col in L.cols), sum(x.qty for x in cur if col in x.cols)
        if b != c2: print(f"  {col} sources {b} → {c2}")
    tap0 = sum(L.qty for L in lands if L.tapped == "always"); tap1 = sum(x.qty for x in cur if x.tapped == "always")
    if tap0 != tap1: print(f"  lands tapped early {tap0} → {tap1}")
    flagged1 = [r for r in rows if scorer.odds(r, cur) < r["threshold"]]
    print(f"  cards under their color threshold: {len(flagged0)} → {len(flagged1)}")
    moved = sorted({r["name"]: r for r in flagged0 + flagged1}.values(), key=lambda r: scorer.odds(r, lands))
    for r in moved[:15]:
        o0, o1 = scorer.odds(r, lands), scorer.odds(r, cur)
        tag = " [commander]" if r["cmdr"] else " [package]" if r["key"] else ""
        print(f"    {r['name']} {r['cost']} on T{r['mv']}: {pct(o0).strip()} → {pct(o1).strip()}"
              + ("" if o1 >= r["threshold"] else f"  (still under {r['threshold']:.0%})") + tag)
    if len(moved) > 15: print(f"    … {len(moved) - 15} more")
    print("\nLimits: static draws (no card draw, cycling, fetch thinning or land tutors); color odds are lands only and assume "
          "enough lands; tapped lands are a tie-breaker, not modeled turn by turn. Fishpond games are the real check.")


PROTECT = set()

if __name__ == "__main__":
    main()
