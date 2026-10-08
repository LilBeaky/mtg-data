#!/usr/bin/env python3
"""
tutor_index.py — every tutor in the card pool, and which tutors can find a given card (TUTOR_PLAN phase 3).

Reads every Commander-legal card with tutors.py's reader once (the same reader the tutor report uses:
spells, ETB/attack/activated abilities, typecycling, landcycling, transmute, partner pairs, ...) and
caches the list of tutors in data/explorer_cache/ (gitignored), keyed to the card data's date and the
reader's source, so a data refresh or a reader fix rebuilds it.

  python3 scripts/tutor_index.py "Card Name" [--ci WUBRG] [--md] [--all]
  python3 scripts/tutor_index.py --build          (force a rebuild; prints the counts)

REPORT for a card: every tutor that can fetch it, in its colors (or --ci), excluding land-only and
graveyard-only tutors (--all shows them), with how it's used, where the card lands, price, Game Changer
flag and EDHREC rank; most played first.

Used by explorer.py ("findable by") and tutors.py (best tutor to add).
"""
import argparse, hashlib, json, os, re, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import mtg
import tutors as tu

CACHE = os.path.join(mtg.DATA_DIR, "explorer_cache", "tutor_index.json")
PREFILTER = re.compile(r"search|cycling|transmute|partner with", re.I)
_MEM = {}


def _key():
    """The cache key: the card data's date and the tutor reader's source (a reader fix rebuilds the index)."""
    info = {}
    try:
        info = json.load(open(os.path.join(mtg.DATA_DIR, "data_info.json"), encoding="utf-8"))
    except Exception:
        pass
    src = open(os.path.join(ROOT, "tutors.py"), "rb").read()
    return f"{info.get('cards_as_of', '?')}|{hashlib.sha1(src).hexdigest()[:12]}"


def tutor_names(rebuild=False):
    """Names of every Commander-legal card with at least one tutor effect (cached)."""
    key = _key()
    if not rebuild and os.path.exists(CACHE):
        try:
            d = json.load(open(CACHE, encoding="utf-8"))
            if d.get("key") == key: return d["names"]
        except Exception:
            pass
    names = []
    for c in mtg.cards():
        if mtg.legal(c) != "legal" or not PREFILTER.search(mtg.text_of(c)): continue
        try:
            if tu.card_tutors(c): names.append(c["name"])
        except Exception:
            continue
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"key": key, "built": time.strftime("%Y-%m-%d %H:%M"), "names": sorted(names)}, open(CACHE, "w", encoding="utf-8"))
    return sorted(names)


def index(rebuild=False):
    """[(card, [Tutor])] for every tutor card in the pool, parsed once per process."""
    if "idx" not in _MEM or rebuild:
        out = []
        for n in tutor_names(rebuild):
            c = mtg.find(n)[0]
            if not c: continue
            ts = tu.card_tutors(c)
            if ts: out.append((c, ts))
        _MEM["idx"] = out
    return _MEM["idx"]


def land_only(ts):
    """Every effect finds only lands (a basic-land fetcher): not a tutor for spells."""
    lands = re.compile(r"\bland\b", re.I)
    return all(lands.search(t.target.describe()) and not t.target.any for t in ts)


def findable_by(card, ci=None, include_all=False):
    """[(tutor card, [matching Tutor effects])] that can fetch `card` (a card dict), tutors inside color identity
    ci (a set of WUBRG; None = the card's own identity, colorless always allowed), not the card itself. Land-only
    and graveyard/no-access destinations are left out unless include_all."""
    ci = set(card.get("color_identity") or []) if ci is None else set(ci)
    out = []
    for c, ts in index():
        if c["name"] == card["name"]: continue
        if not set(c.get("color_identity") or []) <= ci: continue
        hits = [t for t in ts if t.target.matches(card) and (include_all or t.dest not in tu.NO_ACCESS)]
        if not hits: continue
        if not include_all and land_only(ts) and not tu.type_parts(card)[1] & {"land"}: continue
        out.append((c, hits))
    out.sort(key=lambda x: (x[0].get("edhrec_rank") or 10**7, x[0]["name"]))
    return out


def main():
    ap = argparse.ArgumentParser(description="Tutors in the card pool, and which can find a card (see module docstring)")
    ap.add_argument("card", nargs="?"); ap.add_argument("--ci"); ap.add_argument("--md", action="store_true")
    ap.add_argument("--all", action="store_true"); ap.add_argument("--build", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()
    if a.build or not a.card:
        t0 = time.time(); names = tutor_names(rebuild=a.build)
        print(f"tutor index: {len(names)} tutor cards ({time.time() - t0:.1f}s; cache {CACHE})")
        if not a.card: return
    c, how = mtg.find(a.card)
    if not c: sys.exit(f"card not found: {a.card}")
    ci = set(a.ci.upper()) if a.ci else None
    o = tu.Out(a.md)
    found = findable_by(c, ci, a.all)
    o.title(f"FINDABLE BY: {c['name']} | {len(found)} tutor(s) in {''.join(sorted(ci)) if ci else ''.join(c.get('color_identity') or []) or 'colorless'}")
    rows = []
    for t, hits in found[:a.limit]:
        h = hits[0]
        rows.append([t["name"], int(t.get("cmc") or 0), tu.how_used(h), "repeatable" if h.repeatable else "one-shot",
                     h.dest, h.target.describe() + (" ⚠" if h.target.approx else ""),
                     mtg.price_str(t) or "—", "GC" if t.get("game_changer") else "", t.get("edhrec_rank") or "—"])
    o.table(["Tutor", "MV", "How", "Uses", "Puts it", "Finds", "Price", "GC", "EDHREC rank"], rows, right=(1, 8))
    if len(found) > a.limit: o.note(f"+{len(found) - a.limit} more (--limit)")
    o.note("⚠: the tutor's filter is read approximately (MV X, 'shares a type', an opponent picks...). Land-only and")
    o.note("graveyard-destination tutors are left out (--all shows them).")


if __name__ == "__main__":
    main()
