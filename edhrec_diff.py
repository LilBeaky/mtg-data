#!/usr/bin/env python3
"""edhrec_diff.py — compare a decklist against an EDHREC commander-page snapshot.

Claude can't reach EDHREC from the sandbox, so it fetches the page with web_fetch
and transcribes it into a compact snapshot file. This tool validates that
snapshot against the repo, then diffs a deck against it.

USAGE
  python3 edhrec_diff.py check SNAPSHOT            validate a snapshot (run after every transcription)
  python3 edhrec_diff.py diff SNAPSHOT DECK [opts]  compare a deck to the snapshot

  diff options:
    --commander "Name"   if the deck file has no Commander section
    --min N              inclusion % threshold for "skipped" (default 30)
    --limit N            max rows per section (default 25)
    --mv odd|even        companion filter (Obosh = odd, Gyruda = even): hide illegal
                         nonland cards from SKIPPED

SNAPSHOT FORMAT (edhrec_snapshots/<commander-slug>__<variant>__<YYYY-MM-DD>.txt)
  # commander: Smaug the Impenetrable      (partner/background: "# commander: A + B")
  # variant: all            (all | exhibition | core | upgraded | optimized | cedh | budget | a theme tag)
  # url: https://edhrec.com/commanders/smaug-the-impenetrable
  # decks: 6141
  # fetched: 2026-09-25
  Card Name|inclusion%|synergy%[|eligible decks]

  Only write the 4th field when a card's eligible-deck count differs from the page total
  (new cards). Skip basic lands. Duplicates across page sections are fine; they get merged.
"""
import os, re, sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtg

# ---------------- snapshot parsing ----------------
def parse_snapshot(path):
    meta, rows, seen, dupes, bad = {}, [], {}, [], []
    for i, raw in enumerate(open(path, encoding="utf-8"), 1):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            m = re.match(r"#\s*(\w+)\s*:\s*(.+)", s)
            if m:
                meta[m.group(1).lower()] = m.group(2).strip()
            continue
        parts = [p.strip() for p in s.split("|")]
        try:
            name, incl, syn = parts[0], float(parts[1]), float(parts[2])
            elig = int(parts[3]) if len(parts) > 3 and parts[3] else None
        except (IndexError, ValueError):
            bad.append((i, s)); continue
        key = mtg.norm(name)
        if key in seen:
            first = seen[key]
            if abs(first["incl"] - incl) > 0.1 or abs(first["syn"] - syn) > 0.1:
                bad.append((i, f"{s}  (conflicts with L{first['line']}: {first['incl']:g}|{first['syn']:g})"))
            else:
                dupes.append(name)
            continue
        row = {"name": name, "incl": incl, "syn": syn, "elig": elig, "line": i}
        seen[key] = row
        rows.append(row)
    meta["decks"] = int(meta.get("decks", 0) or 0)
    return meta, rows, dupes, bad

def ci_of(c):
    return set(c.get("color_identity") or [])

def resolve(meta, rows):
    """Attach repo cards; return list of problems found."""
    problems = []
    # Partner/background pairs: "# commander: A + B" (color identity = union)
    names = [n.strip() for n in meta.get("commander", "").split(" + ") if n.strip()]
    found = [mtg.find(n)[0] for n in names]
    cmdr = found[0] if found and all(found) else None
    cmdr_ci = set().union(*(ci_of(c) for c in found)) if cmdr else None
    if not cmdr:
        problems.append(f"commander '{meta.get('commander')}' not found in repo")
    total = meta["decks"]
    for r in rows:
        c, how = mtg.find(r["name"])
        r["card"] = c
        if c is None:
            problems.append(f"L{r['line']} NOT FOUND: {r['name']}" + (f" ({how})" if how else ""))
            continue
        if how != "exact":
            problems.append(f"L{r['line']} fuzzy match: '{r['name']}' -> {c['name']} (confirm)")
        if cmdr_ci is not None and not ci_of(c) <= cmdr_ci:
            problems.append(f"L{r['line']} outside color identity: {c['name']} {sorted(ci_of(c))}")
        if r["syn"] > r["incl"] + 0.5:
            problems.append(f"L{r['line']} synergy > inclusion (swapped?): {r['name']} {r['incl']}|{r['syn']}")
        if not 0 <= r["incl"] <= 100:
            problems.append(f"L{r['line']} inclusion out of range: {r['name']} {r['incl']}")
        if r["elig"] and total and r["elig"] > total:
            problems.append(f"L{r['line']} eligible > page total: {r['name']} {r['elig']}")
    return cmdr, problems

def header(meta, n_rows):
    out = [f"EDHREC snapshot: {meta.get('commander','?')} [{meta.get('variant','all')}] "
           f"- {meta['decks']:,} decks, {n_rows} cards listed"]
    fetched = meta.get("fetched")
    if fetched:
        try:
            age = (date.today() - datetime.strptime(fetched, "%Y-%m-%d").date()).days
            out.append(f"fetched {fetched} ({age}d ago)" + ("  ! STALE (>30d), refetch" if age > 30 else ""))
        except ValueError:
            out.append(f"fetched {fetched} (unparsed date)")
    d = meta["decks"]
    if d < 50:
        out.append(f"! SMALL SAMPLE ({d} decks): percentages are noise, treat as anecdotes")
    elif d < 200:
        out.append(f"! modest sample ({d} decks): trust big gaps, not small ones")
    return out

# ---------------- helpers ----------------
TYPE_ORDER = ["Creature", "Planeswalker", "Battle", "Instant", "Sorcery", "Artifact", "Enchantment", "Land"]
def bucket(c):
    tl = (c.get("type_line") or "").split(" // ")[0]
    for t in TYPE_ORDER:
        if t in tl:
            return t
    return "Other"

def is_basic(c):
    return "Basic" in (c.get("type_line") or "") and "Land" in (c.get("type_line") or "")

def adj_incl(r, total):
    """Inclusion among decks that could have played it (EDHREC already does this; flag new cards)."""
    return r["elig"] is not None and total and r["elig"] < 0.95 * total

def tags_for(r, total):
    t = []
    c = r["card"]
    if c and c.get("game_changer"): t.append("GC")
    if r["syn"] >= 40: t.append("signature")
    elif r["syn"] <= 10: t.append("generic staple")
    if adj_incl(r, total): t.append(f"new: {r['elig']:,} eligible")
    return ("  [" + ", ".join(t) + "]") if t else ""

# ---------------- commands ----------------
def cmd_check(args):
    if not args:
        print(__doc__); sys.exit(1)
    meta, rows, dupes, bad = parse_snapshot(args[0])
    cmdr, problems = resolve(meta, rows)
    for l in header(meta, len(rows)): print(l)
    if bad: problems += [f"L{i} unparseable/conflicting: {s}" for i, s in bad]
    if dupes: print(f"merged {len(dupes)} duplicate line(s): {', '.join(dupes[:10])}")
    if problems:
        print(f"\n{len(problems)} PROBLEM(S) - fix before diffing:")
        for p in problems: print("  " + p)
        sys.exit(2)
    print("OK - all names resolved exactly, within color identity, values sane.")

def cmd_diff(args):
    opts = {"--commander": None, "--min": "30", "--limit": "25", "--mv": None}
    pos, i = [], 0
    while i < len(args):
        if args[i] in opts: opts[args[i]] = args[i + 1]; i += 2
        else: pos.append(args[i]); i += 1
    if len(pos) < 2:
        print(__doc__); sys.exit(1)
    snap_path, deck_path = pos
    thresh, limit = float(opts["--min"]), int(opts["--limit"])

    meta, rows, _, _ = parse_snapshot(snap_path)
    _, problems = resolve(meta, rows)
    total = meta["decks"]
    for l in header(meta, len(rows)): print(l)
    if problems:
        print(f"! {len(problems)} snapshot problem(s); run `check` first. Unresolved rows are ignored.")
    rows = [r for r in rows if r["card"]]
    by_name = {r["card"]["name"]: r for r in rows}

    # deck
    entries = mtg.parse_deck(deck_path)
    cmdr_names = [n for s, q, n in entries if s in ("commander", "commanders")]
    if opts["--commander"]: cmdr_names = [opts["--commander"]]
    deck, missing, basics = [], [], 0
    for s, q, n in entries:
        if s in ("sideboard", "maybeboard", "considering", "companion"): continue
        c, how = mtg.find(n)
        if c is None: missing.append(n); continue
        deck.append(c)
        if is_basic(c): basics += q
    cmdr_set = {mtg.find(n)[0]["name"] for n in cmdr_names if mtg.find(n)[0]}
    for _n in [n.strip() for n in meta.get("commander", "").split(" + ") if n.strip()]:
        if mtg.find(_n)[0]:
            cmdr_set.add(mtg.find(_n)[0]["name"])
    if missing:
        print(f"! deck names not found in repo: {', '.join(missing)}")
    mine = {c["name"]: c for c in deck if not is_basic(c) and c["name"] not in cmdr_set}

    on = [n for n in mine if n in by_name]
    off = [n for n in mine if n not in by_name]
    n_mine = len(mine)

    # mainstream index: your summed inclusion vs the top-N most-played listed cards
    listed = sorted((r for r in rows if r["card"]["name"] not in cmdr_set), key=lambda r: -r["incl"])
    your_sum = sum(by_name[n]["incl"] for n in on)
    top_sum = sum(r["incl"] for r in listed[:n_mine]) or 1
    sig = [r for r in listed if r["syn"] >= 40]
    sig_have = [r for r in sig if r["card"]["name"] in mine]

    print(f"\nSUMMARY  ({n_mine} nonbasic non-commander cards, {basics} basics)")
    print(f"  on EDHREC list: {len(on)} ({100*len(on)/max(n_mine,1):.0f}%)   off-list: {len(off)}")
    print(f"  avg inclusion of your cards: {your_sum/max(n_mine,1):.1f}%  (off-list counted as 0; real value <~5%)")
    print(f"  mainstream index: {100*your_sum/top_sum:.0f}%  (100% = you run the {n_mine} most-played cards)")
    print(f"  signature cards (synergy >= 40): you run {len(sig_have)}/{len(sig)}")
    gc_mine = [n for n, c in mine.items() if c.get("game_changer")]
    print(f"  Game Changers: yours {len(gc_mine)}" + (f" ({', '.join(gc_mine)})" if gc_mine else ""))

    skipped = [r for r in listed if r["incl"] >= thresh and r["card"]["name"] not in mine]
    hidden = 0
    if opts["--mv"] in ("odd", "even"):
        want = 1 if opts["--mv"] == "odd" else 0
        keep = [r for r in skipped if "Land" in (r["card"].get("type_line") or "").split(" // ")[0]
                or int(r["card"].get("cmc", 0)) % 2 == want]
        hidden, skipped = len(skipped) - len(keep), keep
    print(f"\nSKIPPED - played in >= {thresh:g}% of decks, not in yours ({len(skipped)})"
          + (f"  [{hidden} hidden by --mv {opts['--mv']}]" if hidden else ""))
    for r in skipped[:limit]:
        print(f"  {r['incl']:>4g}% syn {r['syn']:>+4g}  {r['card']['name']}{tags_for(r, total)}")
    if len(skipped) > limit: print(f"  ... +{len(skipped)-limit} more (raise --limit)")

    print(f"\nOFF-LIST - your cards EDHREC doesn't show (under ~5% or unplayed) ({len(off)})")
    groups = {}
    for n in off: groups.setdefault(bucket(mine[n]), []).append(n)
    for t in TYPE_ORDER + ["Other"]:
        if t in groups: print(f"  {t}: {', '.join(sorted(groups[t]))}")

    neg = sorted((by_name[n] for n in on if by_name[n]["syn"] < 0), key=lambda r: r["syn"])
    print(f"\nNEGATIVE SYNERGY - you run these; this commander's decks play them LESS than average ({len(neg)})")
    for r in neg[:limit]:
        print(f"  {r['incl']:>4g}% syn {r['syn']:>+4g}  {r['card']['name']}")

    agree = sorted((by_name[n] for n in on), key=lambda r: -r["incl"])
    print(f"\nON-LIST - your cards, most to least played ({len(agree)})")
    print("  " + "; ".join(f"{r['card']['name']} {r['incl']:g}" for r in agree[:limit * 2]))
    if len(agree) > limit * 2: print(f"  ... +{len(agree)-limit*2} more")

CMDS = {"check": cmd_check, "diff": cmd_diff}
if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__); sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
