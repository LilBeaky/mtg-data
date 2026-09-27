#!/usr/bin/env python3
"""
trim.py — shrink the bulk data exports down to repo-friendly files.

Two independent tools in one file. They share nothing but this entry point.

  python3 trim.py scryfall  ORACLE_CARDS OUTPUT [--prices DEFAULT_CARDS]
      Scryfall "Oracle Cards" bulk download -> trimmed_scryfall_v2.json.
      --prices cross-references the separate "Default Cards" bulk file
      (all printings) to attach each card's cheapest legal price.

  python3 trim.py spellbook INPUT OUTPUT [--all] [--max-cards N]
      Commander Spellbook variants export -> spellbook_combos.json.gz

Run `python3 trim.py scryfall` or `python3 trim.py spellbook` with no files
for that tool's full notes.
"""

import gzip
import json
import sys


# =============================================================================
# SCRYFALL — oracle cards bulk export -> trimmed_scryfall_v2.json
# =============================================================================

SCRYFALL_DOC = """
trim.py scryfall — reduce Scryfall oracle_cards bulk JSON to a GitHub-friendly size.

Keeps gameplay-relevant fields only, strips all legalities except Commander,
and drops non-card layouts (tokens, art cards, Jumpstart fronts, planes, etc.).

Accepts either JSONL (one card per line — Scryfall's current bulk format)
or a legacy JSON array. Output is always a minified JSON array.

Usage:
    python3 trim.py scryfall oracle-cards.jsonl trimmed_scryfall_v2.json
    python3 trim.py scryfall oracle-cards.jsonl trimmed_scryfall_v2.json --prices default-cards.jsonl

--prices takes a path to Scryfall's separate "Default Cards" bulk export
(every printing, not just one per card). Oracle Cards' own "prices" field is
a single arbitrarily-chosen printing — usually not the cheapest — so real
price data has to come from scanning every printing instead. For each card,
this keeps the single cheapest legal price found across all its printings:
nonfoil preferred, falling back to foil only for cards with no nonfoil
printing at all. Non-paper printings (digital-only) and non-deckable layouts
are excluded from consideration.

SCHEMA NOTES (read these before querying the output):
  * Empty/false values are OMITTED. A missing key means "no/none":
      - no "game_changer" key  -> not a Game Changer
      - no "reserved" key      -> not on the Reserved List
  * legalities.commander is "legal", "not_legal", or "banned".
  * Multi-face cards (split, MDFC, transform, adventure, prepare, etc.) carry
    per-face text in "card_faces"; top-level oracle_text may be absent.
  * --prices adds "usd" — the cheapest legal printing found, USD. If that
    cheapest printing was foil-only (no nonfoil printing exists at all),
    "usd_foil_only" is also set to true, since that price can't be beaten
    by ordering a plain copy. Prices are a snapshot of the Default Cards
    file's date — treat anything older than ~2 weeks as stale. A card
    absent from the price file entirely (e.g. brand new, or the two bulk
    files were pulled at different times) simply has no "usd" key.
"""

# Top-level fields worth keeping for gameplay/deckbuilding questions
SCRYFALL_KEEP = [
    "id", "oracle_id", "name", "mana_cost", "cmc", "type_line", "oracle_text",
    "power", "toughness", "loyalty", "defense", "colors", "color_identity",
    "produced_mana", "keywords", "layout", "set", "rarity", "reserved",
    "game_changer", "edhrec_rank",
]

# Same field set, applied per-face for split/MDFC/transform cards
SCRYFALL_FACE_KEEP = [
    "name", "mana_cost", "type_line", "oracle_text", "power", "toughness",
    "loyalty", "defense", "colors",
]

# Layouts that are not real, deckable Magic cards.
# (host/augment Un-cards are kept: they're real cards, just not_legal.)
SCRYFALL_DROP_LAYOUTS = {
    "art_series",          # art cards — caused the phantom "not_legal" duplicates
    "token",
    "double_faced_token",
    "emblem",
    "front_card",          # Jumpstart theme/front cards
    "planar",              # Planechase planes/phenomena
    "scheme",              # Archenemy schemes
    "vanguard",
}


def scryfall_is_empty(v):
    return v is None or v == [] or v == "" or v is False


def scryfall_trim_card(card, price_map=None):
    out = {k: card[k] for k in SCRYFALL_KEEP if k in card and not scryfall_is_empty(card[k])}

    # Commander legality only
    leg = card.get("legalities", {})
    if "commander" in leg:
        out["legalities"] = {"commander": leg["commander"]}

    faces = card.get("card_faces")
    if faces:
        out["card_faces"] = [
            {k: f[k] for k in SCRYFALL_FACE_KEEP if k in f and not scryfall_is_empty(f[k])}
            for f in faces
        ]

    if price_map is not None:
        entry = price_map.get(card.get("oracle_id"))
        if entry:
            out["usd"] = entry["usd"]
            if entry["foil_only"]:
                out["usd_foil_only"] = True

    return out


def scryfall_build_price_map(default_cards_path):
    """
    Streams a Scryfall "Default Cards" bulk export (every printing) and
    returns {oracle_id: {"usd": cheapest_price_str, "foil_only": bool}}.

    Nonfoil prices are preferred; a card's cheapest foil printing is only
    used as a fallback when it has NO nonfoil printing at all. Digital-only
    printings and non-deckable layouts (see SCRYFALL_DROP_LAYOUTS) are
    ignored since they don't reflect a paper price.
    """
    min_nonfoil = {}   # oracle_id -> float
    min_foil = {}      # oracle_id -> float

    def entries_in(path):
        with open(path, "r", encoding="utf-8") as fh:
            first = fh.read(1)
            fh.seek(0)
            if first == "[":
                yield from json.load(fh)
            else:
                for l in fh:
                    if l.strip():
                        yield json.loads(l)

    n_scanned = 0
    for c in entries_in(default_cards_path):
        n_scanned += 1
        if c.get("digital"):
            continue
        if c.get("layout") in SCRYFALL_DROP_LAYOUTS:
            continue
        oid = c.get("oracle_id")
        if not oid:
            continue
        p = c.get("prices") or {}
        if p.get("usd"):
            v = float(p["usd"])
            if oid not in min_nonfoil or v < min_nonfoil[oid]:
                min_nonfoil[oid] = v
        if p.get("usd_foil"):
            v = float(p["usd_foil"])
            if oid not in min_foil or v < min_foil[oid]:
                min_foil[oid] = v

    price_map = {}
    for oid, v in min_nonfoil.items():
        price_map[oid] = {"usd": f"{v:.2f}", "foil_only": False}
    for oid, v in min_foil.items():
        if oid not in price_map:                 # no nonfoil printing exists at all
            price_map[oid] = {"usd": f"{v:.2f}", "foil_only": True}

    n_foil_only = sum(1 for e in price_map.values() if e["foil_only"])
    print(f"price file: {n_scanned:,} printings scanned, "
          f"{len(price_map):,} cards priced "
          f"({len(min_nonfoil):,} nonfoil, {n_foil_only:,} foil-only)")
    return price_map


def scryfall_main(argv):
    price_src = None
    if "--prices" in argv:
        i = argv.index("--prices")
        price_src = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(SCRYFALL_DOC)
        sys.exit(1)

    src, dst = args
    price_map = scryfall_build_price_map(price_src) if price_src else None

    def cards_in():
        """Streams cards one at a time — low memory even on the ~200 MB bulk file."""
        with open(src, "r", encoding="utf-8") as fh:
            first = fh.read(1)
            fh.seek(0)
            if first == "[":
                yield from json.load(fh)                   # legacy JSON array
            else:
                for l in fh:                               # JSONL
                    if l.strip():
                        yield json.loads(l)

    dropped, n_in, n_out = {}, 0, 0
    with open(dst, "w", encoding="utf-8") as out:
        out.write("[")
        for c in cards_in():
            n_in += 1
            lay = c.get("layout")
            if lay in SCRYFALL_DROP_LAYOUTS:
                dropped[lay] = dropped.get(lay, 0) + 1
                continue
            if n_out:
                out.write(",")
            # Minified, no ASCII escaping — smallest possible output
            json.dump(scryfall_trim_card(c, price_map), out, ensure_ascii=False, separators=(",", ":"))
            n_out += 1
        out.write("]")

    print(f"cards in:  {n_in:,}")
    print(f"cards out: {n_out:,}")
    for lay, n in sorted(dropped.items(), key=lambda x: -x[1]):
        print(f"  dropped {lay:<20} {n:,}")
    if price_map is not None:
        print("prices included — cheapest legal printing per card, "
              "snapshot date = the Default Cards file's date")


# =============================================================================
# SPELLBOOK — Commander Spellbook variants export -> spellbook_combos.json.gz
# =============================================================================

SPELLBOOK_DOC = """
trim.py spellbook — reduce Commander Spellbook's bulk combo export for the repo.

Download with curl (the sandbox can't reach this host, and a browser crashes
trying to display the ~660 MB file):
    curl -o variants.json.gz https://json.commanderspellbook.com/variants.json.gz

Requires: pip install ijson   (streams the file instead of loading it all into
          memory; falls back to a full load if ijson is missing)

Usage:
    python3 trim.py spellbook variants.json.gz spellbook_combos.json.gz   (recommended)
    python3 trim.py spellbook variants.json.gz spellbook_combos.json --max-cards 4
    python3 trim.py spellbook variants.json.gz spellbook_combos.json --all

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

SPELLBOOK_TAG_TO_BRACKET = {"R": 4, "S": 3, "P": 3, "O": 2, "C": 2, "E": 1}
SPELLBOOK_PUBLIC = {"OK", "E"}


def spellbook_get(d, *keys):
    """Get first present key — tolerates camelCase or snake_case."""
    for k in keys:
        if k in d:
            return d[k]
    return None


def spellbook_trim(v):
    g = spellbook_get
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
        "bracket": SPELLBOOK_TAG_TO_BRACKET.get(tag),
        "pop": g(v, "popularity"),
        "prereq": (g(v, "notablePrerequisites", "notable_prerequisites") or "").strip(),
    }
    return {k: val for k, val in out.items() if val not in (None, [], "")}


def spellbook_main(argv):
    max_cards = None
    if "--max-cards" in argv:
        i = argv.index("--max-cards")
        max_cards = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    keep_all = "--all" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(SPELLBOOK_DOC); sys.exit(1)
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
            if v.get("status") and v["status"] not in SPELLBOOK_PUBLIC:
                skipped["not_public"] += 1; continue
            leg = v.get("legalities") or {}
            if leg and not leg.get("commander", True):
                skipped["not_legal"] += 1; continue
        t = spellbook_trim(v)
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


# =============================================================================
# entry point
# =============================================================================

TOOLS = {"scryfall": scryfall_main, "spellbook": spellbook_main}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        print(__doc__)
        sys.exit(1)
    TOOLS[sys.argv[1]](sys.argv[2:])
