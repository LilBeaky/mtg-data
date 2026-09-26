#!/usr/bin/env python3
"""
mtg.py — query helper for the LilBeaky/mtg-data repo.
Run from the repo root. Output is compact text, never raw JSON dumps.

COMMANDS
  card   NAME [NAME ...]        exact lookup (then case-insensitive, then partial)
  card   -f LIST.txt            batch lookup from a file (one name per line)
         --brief                strip (reminder text) — use for big batches of
                                familiar cards; skip it for new/unfamiliar mechanics
  rulings NAME [NAME ...]       rulings for card(s)
         --grep WORD            only rulings mentioning WORD
  tags   NAME                   oracle tags on a card
  search [filters]              find cards; see filters below
  deck   DECKLIST.txt [--commander NAME] [--all-combos]
                                audit: missing/illegal/banned, color identity,
                                singleton, Game Changers, curve, land count,
                                combos (shows 2-card + bracket 3+; --all-combos for rest);
                                Companion section: excluded from count, checked for
                                legality/CI, odd/even condition auto-checked, combos included
  gc                            list all Game Changers
  combos NAME [NAME ...]        Spellbook combos using ALL named cards
                                (--bracket N: only tag >= N; --limit N)
  rule   702.62 | --grep WORD   Comprehensive Rules by number or keyword

SEARCH FILTERS (combine freely)
  --ci UBR        color identity is a subset of these colors (C = colorless)
  --text REGEX    oracle text (all faces), case-insensitive
  --type REGEX    type line, case-insensitive
  --name REGEX    name, case-insensitive
  --cmc 2-4       mana value exact (3) or range (2-4)
  --tag LABEL     has this Scryfall oracle tag (e.g. ramp, removal)
  --gc | --no-gc  Game Changers only / exclude them
  --all           include not-legal cards (default: Commander-legal only)
  --limit N       max results (default 20)
  --full          print full oracle text (default: names + mana cost only)
  Results sorted by EDHREC card rank (popular first).
  TOKEN TIP: search for names, then `card` only the shortlist you care about.

EDHREC comparisons live in edhrec_diff.py (see USE_INSTRUCTIONS.md section 7).

SCHEMA REMINDER: missing "game_changer" key = not a Game Changer.
"""
import glob, json, os, re, signal, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet when piped to head
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
def latest(pattern):
    hits = sorted(glob.glob(os.path.join(ROOT, pattern)))
    return hits[-1] if hits else None

CARDS_FILE = os.path.join(ROOT, "trimmed_scryfall_v2.json")
RULINGS_FILE = latest("rulings-*.jsonl") or latest("*rulings*.json*")
TAGS_FILE = latest("oracle-tags-*.jsonl")
RULES_FILE = latest("MagicCompRules*.txt")
COMBOS_FILE = latest("spellbook_combos*.json*")
TAG_NAMES = {"R": "Ruthless", "S": "Spicy", "P": "Powerful", "O": "Oddball",
             "C": "Core", "E": "Exhibition", "B": "Banned"}

# ---------- loading ----------
_cards = None
def cards():
    global _cards
    if _cards is None:
        _cards = json.load(open(CARDS_FILE, encoding="utf-8"))
    return _cards

def legal(c):
    return (c.get("legalities") or {}).get("commander", "?")

_index = None
def index():
    """name/face-name (lowercased) -> card, preferring Commander-legal printings."""
    global _index
    if _index is None:
        _index = {}
        def put(k, c):
            k = k.lower()
            if k not in _index or (legal(_index[k]) != "legal" and legal(c) == "legal"):
                _index[k] = c
        for c in cards():
            put(c["name"], c)
            for f in c.get("card_faces") or []:
                if f.get("name"):
                    put(f["name"], c)
    return _index

def norm(s):
    s = s.strip().lower()
    s = re.sub(r"[’`]", "'", s)
    return s

def find(name):
    """Returns (card, how). how = exact | partial:<n matches> | None."""
    idx = index()
    n = norm(name)
    if n in idx:
        return idx[n], "exact"
    # front face only, e.g. "Search for Azcanta // Azcanta..." typed partially
    if " // " in n and n.split(" // ")[0] in idx:
        return idx[n.split(" // ")[0]], "exact"
    hits = [k for k in idx if n in k]
    if len(hits) == 1:
        return idx[hits[0]], "partial"
    if hits:
        return None, "ambiguous: " + "; ".join(sorted(hits)[:8])
    return None, None

# ---------- formatting ----------
def text_of(c):
    if c.get("card_faces"):
        return " // ".join(
            f"{f.get('name','')} {f.get('mana_cost','')} — {f.get('type_line','')}: {f.get('oracle_text','')}"
            for f in c["card_faces"])
    return c.get("oracle_text", "")

REMINDER_RX = re.compile(r"\s*\([^()]*\)")
BRIEF = False   # set by --brief: strips (reminder text) to save tokens

def line(c, full=True):
    ci = "".join(c.get("color_identity", [])) or "C"
    tags = []
    if legal(c) != "legal": tags.append(legal(c).upper())
    if c.get("game_changer"): tags.append("GC")
    pt = f" {c['power']}/{c['toughness']}" if c.get("power") is not None else ""
    head = f"{c['name']} {c.get('mana_cost','')} [{ci}]{pt} {c.get('type_line','')}"
    if tags: head += " {" + ",".join(tags) + "}"
    if not full: return head
    body = text_of(c).replace("\n", " / ")
    if BRIEF:
        body = REMINDER_RX.sub("", body)
    return f"{head}\n    {body}"

# ---------- commands ----------
def cmd_card(args):
    global BRIEF
    if "--brief" in args:
        BRIEF = True; args = [a for a in args if a != "--brief"]
    names = []
    if args[:1] == ["-f"]:
        names = [l.strip() for l in open(args[1]) if l.strip()]
    else:
        names = args
    for nm in names:
        c, how = find(nm)
        if c:
            print(line(c) + ("" if how == "exact" else f"\n    (matched partially from '{nm}')"))
        else:
            print(f"NOT FOUND: {nm}" + (f" — {how}" if how else ""))

def cmd_rulings(args):
    rx = None
    if "--grep" in args:
        i = args.index("--grep"); rx = re.compile(args[i + 1], re.I); args = args[:i] + args[i + 2:]
    want = {}
    for nm in args:
        c, _ = find(nm)
        if c: want[c["oracle_id"]] = c["name"]
        else: print(f"NOT FOUND: {nm}")
    got = {k: [] for k in want}
    with open(RULINGS_FILE, encoding="utf-8") as fh:
        for l in fh:
            if '"oracle_id"' not in l: continue
            r = json.loads(l)
            if r.get("oracle_id") in got:
                got[r["oracle_id"]].append(r.get("comment", ""))
    for oid, nm in want.items():
        rs = [r for r in got[oid] if not rx or rx.search(r)]
        print(f"{nm}: {len(rs)} ruling(s)" + (f" matching (of {len(got[oid])})" if rx else ""))
        for r in rs:
            print("  - " + r.replace("\n", " "))

def load_tags(only_label=None, only_oid=None):
    """Streams the tag file.
    only_label: returns {label: set(oracle_id)} for that tag INCLUDING all child
                tags (parent tags like 'removal'/'draw' have no direct taggings).
    only_oid:   returns {label: description} for tags directly on that card."""
    if only_oid:
        out = {}
        with open(TAGS_FILE, encoding="utf-8") as fh:
            for l in fh:
                t = json.loads(l)
                if any(x.get("oracle_id") == only_oid for x in t.get("taggings", [])):
                    out[t["label"]] = t.get("description", "")
        return out
    by_id, root = {}, None
    with open(TAGS_FILE, encoding="utf-8") as fh:
        for l in fh:
            t = json.loads(l)
            by_id[t["id"]] = (t["label"], {x.get("oracle_id") for x in t.get("taggings", [])},
                              t.get("child_ids", []))
            if only_label in (t.get("label"), *t.get("aliases", [])):
                root = t["id"]
    if root is None:
        return {}
    out, stack, seen = {}, [root], set()
    while stack:
        i = stack.pop()
        if i in seen or i not in by_id: continue
        seen.add(i)
        lab, oids, kids = by_id[i]
        out[lab] = oids
        stack.extend(kids)
    return out

def cmd_tags(args):
    c, _ = find(" ".join(args))
    if not c: return print("NOT FOUND")
    tags = load_tags(only_oid=c["oracle_id"])
    print(f"{c['name']}: {len(tags)} tag(s)")
    print("  " + ", ".join(sorted(tags)))

def parse_opts(args):
    o, i = {}, 0
    while i < len(args):
        a = args[i]
        if a in ("--gc", "--no-gc", "--all", "--names", "--full", "--brief", "--all-combos"):
            o[a] = True; i += 1
        else:
            o[a] = args[i + 1]; i += 2
    return o

def cmd_search(args):
    o = parse_opts(args)
    ci = set(o["--ci"].upper().replace("C", "")) if "--ci" in o else None
    rx = lambda k: re.compile(o[k], re.I) if k in o else None
    text, typ, name = rx("--text"), rx("--type"), rx("--name")
    lo = hi = None
    if "--cmc" in o:
        parts = o["--cmc"].split("-")
        lo, hi = float(parts[0]), float(parts[-1])
    tag_ids = None
    if "--tag" in o:
        t = load_tags(only_label=o["--tag"])
        if not t: return print(f"no tag named '{o['--tag']}'")
        tag_ids = set().union(*t.values())
        print(f"tag '{o['--tag']}' covers {len(t)} tag(s) incl. children")
    res = []
    for c in cards():
        if "--all" not in o and legal(c) != "legal": continue
        if ci is not None and not set(c.get("color_identity", [])) <= ci: continue
        if lo is not None and not (lo <= c.get("cmc", 0) <= hi): continue
        if "--gc" in o and not c.get("game_changer"): continue
        if "--no-gc" in o and c.get("game_changer"): continue
        if typ and not typ.search(c.get("type_line", "")): continue
        if name and not name.search(c["name"]): continue
        if text and not text.search(text_of(c)): continue
        if tag_ids is not None and c.get("oracle_id") not in tag_ids: continue
        res.append(c)
    res.sort(key=lambda c: c.get("edhrec_rank") or 10**7)
    lim = int(o.get("--limit", 20))
    print(f"{len(res)} match(es){' (showing ' + str(lim) + ')' if len(res) > lim else ''}")
    if "--full" in o:
        for c in res[:lim]:
            print(line(c))
    else:   # default: names + cost only — run `card` on the shortlist for text
        print("; ".join(f"{c['name']} {c.get('mana_cost','')}".strip() for c in res[:lim]))

LINE_RX = re.compile(r"^\s*(\d+)?x?\s*(.+?)\s*(\([A-Za-z0-9]+\).*)?(\*F\*)?\s*$")
SECTIONS = {"commander", "commanders", "deck", "mainboard", "main", "sideboard",
            "companion", "maybeboard", "considering"}

def parse_deck(path):
    entries, section = [], "deck"
    for raw in open(path, encoding="utf-8"):
        s = raw.strip()
        if not s or s.startswith(("//", "#")): continue
        if s.lower().rstrip(":") in SECTIONS:
            section = s.lower().rstrip(":"); continue
        m = LINE_RX.match(s)
        if not m: continue
        qty = int(m.group(1) or 1)
        entries.append((section, qty, m.group(2)))
    return entries

def cmd_deck(args):
    o = parse_opts(args[1:])
    entries = parse_deck(args[0])
    main_ = [(q, n) for s, q, n in entries if s not in ("sideboard", "maybeboard", "considering", "companion")]
    comp_names = [n for s, q, n in entries if s == "companion"]
    cmd_names = [n for s, q, n in entries if s in ("commander", "commanders")]
    if "--commander" in o: cmd_names = [o["--commander"]]
    found, problems = [], []
    for q, n in main_:
        c, how = find(n)
        if not c: problems.append(f"NOT FOUND: {n}" + (f" — {how}" if how else "")); continue
        if how != "exact": problems.append(f"partial match: '{n}' -> {c['name']}")
        found.append((q, c))
    # commander & color identity
    ci = None
    if cmd_names:
        ci = set()
        for n in cmd_names:
            c, _ = find(n)
            if c: ci |= set(c.get("color_identity", []))
    else:
        problems.append("no commander given (use a 'Commander' section or --commander NAME); CI check skipped")
    total = sum(q for q, _ in found)
    counts = Counter()
    for q, c in found:
        counts[c["name"]] += q
        if legal(c) != "legal": problems.append(f"{legal(c).upper()}: {c['name']}")
        if ci is not None and not set(c.get("color_identity", [])) <= ci:
            problems.append(f"COLOR IDENTITY: {c['name']} [{''.join(c.get('color_identity', []))}]")
    # companion: outside the deck, but must be legal, in CI, and its condition met
    comp_cards, comp_notes = [], []
    for n in comp_names:
        c, how = find(n)
        if not c: problems.append(f"NOT FOUND (companion): {n}"); continue
        comp_cards.append(c)
        if legal(c) != "legal": problems.append(f"{legal(c).upper()} (companion): {c['name']}")
        if ci is not None and not set(c.get("color_identity", [])) <= ci:
            problems.append(f"COLOR IDENTITY (companion): {c['name']} [{''.join(c.get('color_identity', []))}]")
        t = text_of(c)
        if "Companion —" not in t:
            problems.append(f"NOT A COMPANION: {c['name']}"); continue
        parity = 1 if "only cards with odd mana values" in t else 0 if "only cards with even mana values" in t else None
        if parity is None:
            comp_notes.append(f"{c['name']}: condition not auto-checked — review manually")
            continue
        # starting deck includes the commander; lands are exempt for Obosh and MV 0 (even) for Gyruda
        bad = sorted({c2["name"] for _, c2 in found
                      if "Land" not in c2.get("type_line", "").split("//")[0]
                      and int(c2.get("cmc", 0)) % 2 != parity})
        want = "odd" if parity else "even"
        if bad:
            problems.append(f"COMPANION ({c['name']}, {want} MV only): {len(bad)} violation(s): {', '.join(bad)}")
        else:
            comp_notes.append(f"{c['name']}: {want}-MV condition met")
    for nm, q in counts.items():
        c, _ = find(nm)
        t = text_of(c)
        basic = "Basic" in c.get("type_line", "")
        anynum = "any number of cards named" in t
        m = re.search(r"up to (\w+) cards named", t)
        if q > 1 and not (basic or anynum or m):
            problems.append(f"SINGLETON: {q}x {nm}")
    gcs = [c["name"] for _, c in found if c.get("game_changer")]
    lands = sum(q for q, c in found if "Land" in c.get("type_line", "").split("//")[0])
    nonland = [(q, c) for q, c in found if "Land" not in c.get("type_line", "").split("//")[0]]
    curve = Counter()
    for q, c in nonland: curve[int(c.get("cmc", 0))] += q
    nl = sum(q for q, _ in nonland)
    avg = sum(q * c.get("cmc", 0) for q, c in nonland) / nl if nl else 0
    print(f"cards: {total} (commander(s): {', '.join(cmd_names) or 'none'}; "
          f"CI {''.join(sorted(ci)) if ci else '?'})")
    if comp_names:
        print(f"companion (not counted): {', '.join(c['name'] for c in comp_cards) or ', '.join(comp_names)}"
              + (f" — {'; '.join(comp_notes)}" if comp_notes else ""))
    print(f"lands: {lands} | nonland: {nl} | avg MV (nonland): {avg:.2f}")
    print("curve: " + "  ".join(f"{k}:{v}" for k, v in sorted(curve.items())))
    print(f"Game Changers ({len(gcs)}): {', '.join(gcs) or 'none'}")
    print("problems: " + ("none" if not problems else ""))
    for p in problems: print("  - " + p)
    global BRIEF
    # companion included: it can be put into hand for {3}, so its combos are live
    names_in_deck = ([c["name"] for _, c in found] + [find(n)[0]["name"] for n in cmd_names if find(n)[0]]
                     + [c["name"] for c in comp_cards])
    ts, dc = deck_combos(names_in_deck)
    if dc is None:
        print("combos: no spellbook_combos file — 2-card combo check NOT done")
    else:
        dc.sort(key=lambda v: (-(v.get("bracket") or 0), len(v["cards"])))
        two = [v for v in dc if len(v["cards"]) == 2]
        top = max((v.get("bracket") or 0 for v in dc), default=0)
        print(f"combos: {len(dc)} complete in deck ({len(two)} two-card) | highest Spellbook tag bracket: {top or 'n/a'} | {combo_age_note(ts)}")
        show = dc if "--all-combos" in o else [v for v in dc if (v.get("bracket") or 0) >= 3 or len(v["cards"]) == 2]
        for v in show: print("  " + combo_line(v))
        if len(show) < len(dc):
            print(f"  + {len(dc) - len(show)} lower-bracket combo(s) of 3+ cards hidden (--all-combos to list)")
        if any(v.get("templates") for v in dc):
            print("  note: combos with 'requires' need a generic piece — confirm you actually have one")
    print("note: MLD and extra-turn cards are not auto-flagged — review manually.")


# ---------- Commander Spellbook combos ----------
_combos = None
def combos():
    """Loads spellbook_combos*.json(.gz). Returns (timestamp, variants) or (None, None)."""
    global _combos
    if _combos is None:
        if not COMBOS_FILE:
            _combos = (None, None)
        else:
            import gzip
            op = gzip.open if COMBOS_FILE.endswith(".gz") else open
            with op(COMBOS_FILE, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            _combos = (d.get("timestamp"), d.get("variants", []))
    return _combos

def combo_age_note(ts):
    if not ts: return ""
    try:
        from datetime import datetime, timezone
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - t).days
        return f"combo data from {ts[:10]} ({days} days old)" + (" — consider refreshing" if days > 30 else "")
    except Exception:
        return f"combo data from {ts}"

def combo_line(v):
    b = v.get("bracket")
    tag = TAG_NAMES.get(v.get("tag"), v.get("tag", "?"))
    req = f" +req: {'; '.join(v['templates'])}" if v.get("templates") else ""
    cm = " [cmdr]" if v.get("cmdr") else ""
    return (f"[{tag}{'→B' + str(b) if b else ''}] {' + '.join(v['cards'])}{cm}{req} "
            f"→ {'; '.join(v.get('produces', [])) or '?'} | pop {v.get('pop', 0)} | id {v['id']}")

def cmd_combos(args):
    o = {}
    names = []
    i = 0
    while i < len(args):
        if args[i] in ("--bracket", "--limit"):
            o[args[i]] = int(args[i + 1]); i += 2
        else:
            names.append(args[i]); i += 1
    ts, vs = combos()
    if vs is None: return print("no spellbook_combos file in repo")
    want = set()
    for n in names:
        c, how = find(n)
        if not c:
            return print(f"can't resolve '{n}'" + (f" — {how}" if how else " — not found"))
        want.add(c["name"].lower())
    hits = [v for v in vs if want <= {x.lower() for x in v.get("cards", [])}]
    if "--bracket" in o:
        hits = [v for v in hits if (v.get("bracket") or 0) >= o["--bracket"]]
    hits.sort(key=lambda v: -(v.get("pop") or 0))
    lim = o.get("--limit", 10)
    print(f"{len(hits)} combo(s)" + (f" (showing {lim})" if len(hits) > lim else "") + " | " + combo_age_note(ts))
    for v in hits[:lim]: print(combo_line(v))

def deck_combos(deck_names):
    """Combos whose every named card is in the deck."""
    ts, vs = combos()
    if vs is None: return None, None
    dn = {n.lower() for n in deck_names}
    return ts, [v for v in vs if v.get("cards") and {x.lower() for x in v["cards"]} <= dn]

def cmd_gc(args):
    g = sorted((c for c in cards() if c.get("game_changer")), key=lambda c: c["name"])
    print(f"{len(g)} Game Changers")
    print("; ".join(c["name"] for c in g))

def cmd_rule(args):
    txt = open(RULES_FILE, encoding="utf-8-sig").read().splitlines()
    if args[0] == "--grep":
        rx = re.compile(" ".join(args[1:]), re.I)
        hits = [l for l in txt if re.match(r"^\d{3}\.\d+", l) and rx.search(l)]
        print(f"{len(hits)} rule line(s)")
        lim = 15
        for l in hits[:lim]: print("  " + l)
        if len(hits) > lim: print(f"  ... {len(hits) - lim} more — narrow the pattern or look up a rule number")
    else:
        num = args[0].rstrip(".")
        pat = re.compile(rf"^{re.escape(num)}(?:[.a-z ]|$)")
        hits = [l for l in txt if pat.match(l)]
        # de-dupe table-of-contents vs body: keep body (last occurrence block)
        seen, out = set(), []
        for l in hits:
            if l not in seen: seen.add(l); out.append(l)
        for l in out[:40]: print(l)
        if len(out) > 40: print(f"... {len(out) - 40} more")

CMDS = {"card": cmd_card, "rulings": cmd_rulings, "tags": cmd_tags, "search": cmd_search,
        "deck": cmd_deck, "gc": cmd_gc, "combos": cmd_combos, "rule": cmd_rule}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__); sys.exit(1)
    CMDS[sys.argv[1]](sys.argv[2:])
