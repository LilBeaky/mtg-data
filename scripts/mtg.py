#!/usr/bin/env python3
"""
mtg.py — query helper for the LilBeaky/mtg-data repo.
Run from the repo root. Output is compact text, never raw JSON dumps.

COMMANDS
  card   NAME [NAME ...]        exact lookup (then case-insensitive, then partial);
                                shows the cheapest printing's USD price when known
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
                                Cost: deck total at cheapest printings, most expensive
                                cards, unpriced cards; checked against a '# budget:' header
                                Long-form exports with trailing #tags are accepted
                                (tags are stripped here; audit.py uses them as roles)
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
  --max-price 5   cheapest printing at most $5 (unpriced cards are excluded)
  --min-price 20  cheapest printing at least $20
  --sort price    cheapest first (default sort: EDHREC popularity)
  --all           include not-legal cards (default: Commander-legal only)
  --limit N       max results (default 20)
  --full          print full oracle text (default: names + mana cost only)
  Results sorted by EDHREC card rank (popular first) unless --sort price.
  Prices are shown on results whenever a price filter or --sort price is used.
  TOKEN TIP: search for names, then `card` only the shortlist you care about.

DECKLIST HEADER (optional, see USE_INSTRUCTIONS §4)
  # bracket: 4      # plan: free text      # pets: Card A; Card B
  Bare "bracket: / plan: / pets:" lines (no #) work too. Pets split on ';' or ' + ',
  never on commas (card names contain commas).
TRAILING #TAGS on card lines (long-form exports) are stripped from names here;
  audit.py reads them as roles.

RESKINS: names in aliases.txt ("Printed => Oracle") resolve automatically.

EDHREC comparisons live in edhrec_diff.py (see USE_INSTRUCTIONS.md section 9).

SCHEMA REMINDER: missing "game_changer" key = not a Game Changer.
"""
import glob, json, os, re, signal, sys
signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # quiet when piped to head
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))       # .../scripts
REPO_ROOT = os.path.dirname(ROOT)                        # repo root
DATA_DIR = os.path.join(REPO_ROOT, "data")
def latest(pattern):
    hits = sorted(glob.glob(os.path.join(DATA_DIR, pattern)))
    return hits[-1] if hits else None

CARDS_FILE = os.path.join(DATA_DIR, "trimmed_scryfall_v2.json")
RULINGS_FILE = latest("rulings-*.jsonl") or latest("*rulings*.json*")
TAGS_FILE = latest("oracle-tags-*.jsonl")
RULES_FILE = latest("MagicCompRules*.txt")
COMBOS_FILE = latest("spellbook_combos*.json*")
ALIASES_FILE = os.path.join(DATA_DIR, "aliases.txt")
INFO_FILE = os.path.join(DATA_DIR, "data_info.json")   # written by the daily refresh workflow
STALE_DAYS = 3
TAG_NAMES = {"R": "Ruthless", "S": "Spicy", "P": "Powerful", "O": "Oddball",
             "C": "Core", "E": "Exhibition", "B": "Banned"}

# ---------- data freshness ----------
_info = None
def data_info():
    """{'refreshed_at', 'prices_as_of', ...} from the refresh workflow, or {} if absent."""
    global _info
    if _info is None:
        try:
            _info = json.load(open(INFO_FILE, encoding="utf-8"))
        except (OSError, ValueError):
            _info = {}
    return _info

def _age_days(iso):
    import datetime
    try:
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - t).days
    except (AttributeError, ValueError):
        return None

def price_date_note():
    d = data_info().get("prices_as_of")
    if not d: return "price date unknown"
    age = _age_days(d)
    return f"prices as of {d[:10]}" + (f" ({age}d old)" if age else "")

def stale_warning():
    """One line if the daily refresh looks stopped, else None. Silent when healthy."""
    age = _age_days(data_info().get("refreshed_at", ""))
    if age is not None and age > STALE_DAYS:
        return (f"! data last refreshed {age} days ago; the daily refresh may have stopped "
                f"(see USE_INSTRUCTIONS section 12)")
    return None

def price(c):
    """Cheapest printing's USD price as float, or None if unpriced."""
    try:
        return float(c["usd"])
    except (KeyError, TypeError, ValueError):
        return None

def price_str(c):
    p = price(c)
    if p is None: return ""
    return f"${p:,.2f}" + (" foil-only" if c.get("usd_foil_only") else "")

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
    """name/face-name (lowercased) -> card, preferring Commander-legal printings.
    Full card names always beat face names."""
    global _index
    if _index is None:
        _index = {}
        def put(k, c):
            k = k.lower()
            if k not in _index or (legal(_index[k]) != "legal" and legal(c) == "legal"):
                _index[k] = c
        # Pass 1: full card names. Pass 2: face names, only where no full name
        # already owns the key. Prepare/adventure reprints reuse classic spell
        # names as a face (e.g. "Studious First-Year // Rampant Growth"). 25 face
        # names collide with real cards; with a single pass, 12 of them resolved
        # to the wrong card (Rampant Growth, Reanimate, Regrowth, Replenish,
        # Channel, Exsanguinate, Sign in Blood, ...). Fixed Sept 2026.
        for c in cards():
            put(c["name"], c)
        full = set(_index)
        for c in cards():
            for f in c.get("card_faces") or []:
                if f.get("name") and f["name"].lower() not in full:
                    put(f["name"], c)
    return _index

def norm(s):
    s = s.strip().lower()
    s = re.sub(r"[’`]", "'", s)
    # Moxfield exports double-faced cards with ONE slash ("Westvale Abbey / Ormendahl,
    # Profane Prince"); Oracle names use " // ". No Oracle name contains " / ", so
    # normalizing is safe. Found in the Sept 2026 Erebos audit (2 DFCs NOT FOUND).
    s = re.sub(r"\s+/{1,2}\s+", " // ", s)
    return s

_aliases = None
def aliases():
    """aliases.txt: 'Printed Name => Oracle Name' per line, # comments.
    For reskins (Secret Lair / Universes Beyond / Universes Within names) that
    Scryfall's oracle bulk file doesn't carry."""
    global _aliases
    if _aliases is None:
        _aliases = {}
        if os.path.exists(ALIASES_FILE):
            for raw in open(ALIASES_FILE, encoding="utf-8"):
                s = raw.split("#", 1)[0].strip()
                if "=>" in s:
                    printed, oracle = (p.strip() for p in s.split("=>", 1))
                    if printed and oracle:
                        _aliases[norm(printed)] = oracle
    return _aliases

def find(name):
    """Returns (card, how). how = exact | alias | partial | ambiguous: ... | None.
    exact and alias are both trustworthy; alias means the name was a known reskin."""
    idx = index()
    n = norm(name)
    if n in idx:
        return idx[n], "exact"
    # front face only, e.g. "Search for Azcanta // Azcanta..." typed partially
    if " // " in n and n.split(" // ")[0] in idx:
        return idx[n.split(" // ")[0]], "exact"
    al = aliases().get(n)
    if al and norm(al) in idx:
        return idx[norm(al)], "alias"
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
    if price_str(c): head += f" | {price_str(c)}"
    if not full: return head
    body = text_of(c).replace("\n", " / ")
    if BRIEF:
        body = REMINDER_RX.sub("", body)
        # a line that was only reminder text (hybrid, basic land types) leaves an empty " / " slot
        body = re.sub(r"(?:^|(?<=: ))\s*/\s*|\s*/\s*(?= / |$)", "", body).strip()
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
            note = {"exact": "", "alias": f"\n    (reskin: '{nm}' is this card)"}.get(
                how, f"\n    (matched partially from '{nm}')")
            print(line(c) + note)
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
    return load_tags_multi([only_label]).get(only_label, {})

def load_tags_multi(labels):
    """One pass over the tag file for several labels.
    Returns {label: {sub_label: set(oracle_id)}} with each label's full child
    subtree (same walk as load_tags). Missing labels map to {}."""
    wanted = set(labels)
    by_id, roots = {}, {}
    with open(TAGS_FILE, encoding="utf-8") as fh:
        for l in fh:
            t = json.loads(l)
            by_id[t["id"]] = (t["label"], {x.get("oracle_id") for x in t.get("taggings", [])},
                              t.get("child_ids", []))
            for name in (t.get("label"), *t.get("aliases", [])):
                if name in wanted:
                    roots[name] = t["id"]
    result = {}
    for label in labels:
        out, stack, seen = {}, [roots[label]] if label in roots else [], set()
        while stack:
            i = stack.pop()
            if i in seen or i not in by_id: continue
            seen.add(i)
            lab, oids, kids = by_id[i]
            out[lab] = oids
            stack.extend(kids)
        result[label] = out
    return result

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
            if i + 1 >= len(args):
                sys.exit(f"option {a} needs a value")
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
    pmin = float(o["--min-price"]) if "--min-price" in o else None
    pmax = float(o["--max-price"]) if "--max-price" in o else None
    by_price = o.get("--sort") == "price"
    show_price = by_price or pmin is not None or pmax is not None
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
        if show_price:
            p = price(c)
            if p is None: continue          # unpriced: can't satisfy a price filter
            if pmin is not None and p < pmin: continue
            if pmax is not None and p > pmax: continue
        res.append(c)
    if by_price:
        res.sort(key=lambda c: (price(c), c.get("edhrec_rank") or 10**7))
    else:
        res.sort(key=lambda c: c.get("edhrec_rank") or 10**7)
    lim = int(o.get("--limit", 20))
    print(f"{len(res)} match(es){' (showing ' + str(lim) + ')' if len(res) > lim else ''}"
          + (f" | {price_date_note()}; unpriced cards excluded" if show_price else ""))
    if "--full" in o:
        for c in res[:lim]:
            print(line(c))
    else:   # default: names + cost only — run `card` on the shortlist for text
        print("; ".join(f"{c['name']} {c.get('mana_cost','')}".strip()
                        + (f" {price_str(c)}" if show_price else "") for c in res[:lim]))

LINE_RX = re.compile(r"^\s*(\d+)?x?\s*(.+?)\s*(\([A-Za-z0-9]+\).*)?(\*F\*)?\s*$")
SECTIONS = {"commander", "commanders", "deck", "mainboard", "main", "sideboard",
            "companion", "maybeboard", "considering"}

# Trailing user tags in long-form exports, e.g. "1 Sol Ring (C21) 263 *F* #Ramp #!Mana Rock".
# Split only on whitespace followed by '#', so multi-word tags ("Mana Rock") survive.
TAG_SPLIT_RX = re.compile(r"\s+#(?=\S)")
# Header lines above a list: "# key: value" (any key), or bare known keys without '#'
# ("bracket: 3 (high)", "plan: ...", "pets: ..."). parse_deck skips both; parse_deck_meta reads them.
META_RX = re.compile(r"^#\s*([A-Za-z_]+)\s*:\s*(.*?)\s*$")
BARE_META_RX = re.compile(r"^(bracket|plan|pets?|notes?|target|budget)\s*:\s*(.*?)\s*$", re.I)
BRACKET_VARIANT = {1: "exhibition", 2: "core", 3: "upgraded", 4: "optimized", 5: "cedh"}

def split_tags(s):
    """'1 Card (SET) 12 #Ramp #!Mana Rock' -> ('1 Card (SET) 12', ['Ramp', 'Mana Rock'])"""
    parts = TAG_SPLIT_RX.split(s)
    tags = [p.strip().lstrip("!").strip() for p in parts[1:]]
    return parts[0], [t for t in tags if t]

def parse_deck(path, with_tags=False):
    """[(section, qty, name)], or [(section, qty, name, tags)] with with_tags=True.
    Trailing #tags are always stripped from the name, so tagged exports audit cleanly."""
    entries, section = [], "deck"
    for raw in open(path, encoding="utf-8"):
        s = raw.strip()
        if not s or s.startswith(("//", "#")) or BARE_META_RX.match(s): continue
        if s.lower().rstrip(":") in SECTIONS:
            section = s.lower().rstrip(":"); continue
        s, tags = split_tags(s)
        m = LINE_RX.match(s)
        if not m: continue
        qty = int(m.group(1) or 1)
        entries.append((section, qty, m.group(2), tags) if with_tags else (section, qty, m.group(2)))
    return entries

def parse_deck_meta(path):
    """Optional header lines in a decklist (parse_deck skips them):
    '# key: value' (any key), or bare 'bracket: / plan: / pets: / notes: / target: /
    budget:' lines. 'bracket' -> int 1-5 (full text kept as 'bracket_text' when it
    says more, e.g. '3 (high)'); 'pets' -> list of card names split on ';' or ' + '
    (never commas, since names contain them). Other keys stay plain strings."""
    meta = {}
    for raw in open(path, encoding="utf-8"):
        s = raw.strip()
        m = META_RX.match(s) or BARE_META_RX.match(s)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        k = {"pet": "pets", "note": "notes"}.get(k, k)
        if k == "bracket":
            d = re.search(r"[1-5]", v)
            if d:
                meta[k] = int(d.group())
                if v != d.group(): meta["bracket_text"] = v
        elif k == "pets":
            meta[k] = [x.strip() for x in re.split(r"\s*;\s*|\s+\+\s+", v) if x.strip()]
        else:
            meta[k] = v
    return meta

def cmd_deck(args):
    o = parse_opts(args[1:])
    entries = parse_deck(args[0])
    main_ = [(q, n) for s, q, n in entries if s not in ("sideboard", "maybeboard", "considering", "companion")]
    comp_names = [n for s, q, n in entries if s == "companion"]
    cmd_names = [n for s, q, n in entries if s in ("commander", "commanders")]
    if "--commander" in o: cmd_names = [o["--commander"]]
    found, problems, alias_notes = [], [], []
    for q, n in main_:
        c, how = find(n)
        if not c: problems.append(f"NOT FOUND: {n}" + (f" — {how}" if how else "")); continue
        if how == "alias": alias_notes.append(f"{n} -> {c['name']}")
        elif how != "exact": problems.append(f"partial match: '{n}' -> {c['name']}")
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
    missing = sum(q for q, n in main_) - total
    print(f"cards: {total}{f' found + {missing} NOT FOUND (excluded from every count below)' if missing > 0 else ''} "
          f"(commander(s): {', '.join(cmd_names) or 'none'}; "
          f"CI {''.join(sorted(ci)) if ci else '?'})")
    meta = parse_deck_meta(args[0])
    if meta:
        bits = []
        if "bracket" in meta: bits.append(f"target B{meta['bracket']}" + (" " + re.sub(r"^\s*[1-5]\s*", "", meta["bracket_text"]) if meta.get("bracket_text") else ""))
        if meta.get("plan"): bits.append(f"plan: {meta['plan']}")
        if meta.get("pets"): bits.append(f"pets: {'; '.join(meta['pets'])}")
        print("header: " + " | ".join(bits))
        in_deck = {c["name"] for _, c in found} | {c["name"] for c in (find(n)[0] for n in cmd_names) if c}
        stale = []
        for p in meta.get("pets", []):
            c, _ = find(p)
            if not c or c["name"] not in in_deck:
                stale.append(p)
        if stale:
            print("  ! stale pets (not in this list — update the header): " + ", ".join(stale))
    else:
        print("header: none (add '# bracket:', '# plan:', '# pets:' lines — see USE_INSTRUCTIONS §4)")
    if alias_notes:
        print("reskins resolved: " + "; ".join(alias_notes))
    if comp_names:
        print(f"companion (not counted): {', '.join(c['name'] for c in comp_cards) or ', '.join(comp_names)}"
              + (f" — {'; '.join(comp_notes)}" if comp_notes else ""))
    print(f"lands: {lands} | nonland: {nl} | avg MV (nonland): {avg:.2f}")
    print("curve: " + "  ".join(f"{k}:{v}" for k, v in sorted(curve.items())))
    print(f"Game Changers ({len(gcs)}): {', '.join(gcs) or 'none'}")
    print("problems: " + ("none" if not problems else ""))
    for p in problems: print("  - " + p)
    deck_cost(found, cmd_names, comp_cards, meta)
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


def deck_cost(found, cmd_names, comp_cards, meta):
    """Deck cost at each card's cheapest printing. The commander is already in
    `found` when it's listed in the deck; it's added from cmd_names only if not."""
    rows = [(q, c) for q, c in found]
    listed = {c["name"] for _, c in found}
    for n in cmd_names:
        c, _ = find(n)
        if c and c["name"] not in listed: rows.append((1, c))
    rows += [(1, c) for c in comp_cards]
    priced = [(q, c, price(c)) for q, c in rows if price(c) is not None]
    unpriced = sorted({c["name"] for q, c in rows if price(c) is None})
    if not priced:
        print("cost: no price data (repo trimmed without --prices?)")
        return
    total = sum(q * p for q, c, p in priced)
    basics = sum(q * p for q, c, p in priced if "Basic" in c.get("type_line", ""))
    line_ = f"cost: ${total:,.2f} at cheapest printings (${total - basics:,.2f} excluding basics) | {price_date_note()}"
    b = re.search(r"\d[\d,]*(?:\.\d+)?", meta.get("budget", "")) if meta else None
    if b:
        cap = float(b.group().replace(",", ""))
        line_ += f" | budget ${cap:,.2f}: " + ("OK" if total <= cap else f"OVER by ${total - cap:,.2f}")
    print(line_)
    top = sorted(priced, key=lambda x: -x[2])[:5]
    print("  priciest: " + "; ".join(f"{c['name']} ${p:,.2f}" + (" (foil-only)" if c.get("usd_foil_only") else "")
                                     for q, c, p in top))
    if unpriced:
        print(f"  no price ({len(unpriced)}, excluded from total): {', '.join(unpriced)}")


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
    _w = stale_warning()
    if _w: print(_w)
    CMDS[sys.argv[1]](sys.argv[2:])
