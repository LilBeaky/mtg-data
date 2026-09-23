#!/usr/bin/env python3
"""
trim_scryfall.py — reduce Scryfall oracle_cards bulk JSON to a GitHub-friendly size.

Keeps gameplay-relevant fields only, strips all legalities except Commander,
and drops non-card layouts (tokens, art cards, Jumpstart fronts, planes, etc.).

Accepts either JSONL (one card per line — Scryfall's current bulk format)
or a legacy JSON array. Output is always a minified JSON array.

Usage:
    python3 trim_scryfall.py input.jsonl output.json
    python3 trim_scryfall.py input.jsonl output.json --prices   # keep USD prices

SCHEMA NOTES (read these before querying the output):
  * Empty/false values are OMITTED. A missing key means "no/none":
      - no "game_changer" key  -> not a Game Changer
      - no "reserved" key      -> not on the Reserved List
  * legalities.commander is "legal", "not_legal", or "banned".
  * Multi-face cards (split, MDFC, transform, adventure, prepare, etc.) carry
    per-face text in "card_faces"; top-level oracle_text may be absent.
  * --prices adds "usd" (nonfoil) and "usd_foil". Prices are a snapshot of
    the bulk file's date — treat anything older than ~2 weeks as stale.
"""

import json
import sys

# Top-level fields worth keeping for gameplay/deckbuilding questions
KEEP = [
    "id", "oracle_id", "name", "mana_cost", "cmc", "type_line", "oracle_text",
    "power", "toughness", "loyalty", "defense", "colors", "color_identity",
    "produced_mana", "keywords", "layout", "set", "rarity", "reserved",
    "game_changer", "edhrec_rank",
]

# Same field set, applied per-face for split/MDFC/transform cards
FACE_KEEP = [
    "name", "mana_cost", "type_line", "oracle_text", "power", "toughness",
    "loyalty", "defense", "colors",
]

# Layouts that are not real, deckable Magic cards.
# (host/augment Un-cards are kept: they're real cards, just not_legal.)
DROP_LAYOUTS = {
    "art_series",          # art cards — caused the phantom "not_legal" duplicates
    "token",
    "double_faced_token",
    "emblem",
    "front_card",          # Jumpstart theme/front cards
    "planar",              # Planechase planes/phenomena
    "scheme",              # Archenemy schemes
    "vanguard",
}


def is_empty(v):
    return v is None or v == [] or v == "" or v is False


def trim_card(card, prices=False):
    out = {k: card[k] for k in KEEP if k in card and not is_empty(card[k])}

    # Commander legality only
    leg = card.get("legalities", {})
    if "commander" in leg:
        out["legalities"] = {"commander": leg["commander"]}

    faces = card.get("card_faces")
    if faces:
        out["card_faces"] = [
            {k: f[k] for k in FACE_KEEP if k in f and not is_empty(f[k])}
            for f in faces
        ]

    if prices:
        p = card.get("prices") or {}
        if p.get("usd"):
            out["usd"] = p["usd"]
        if p.get("usd_foil"):
            out["usd_foil"] = p["usd_foil"]

    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)

    src, dst = args
    prices = "--prices" in flags

    with open(src, "r", encoding="utf-8") as fh:
        first = fh.read(1)
        fh.seek(0)
        if first == "[":
            cards = json.load(fh)                              # legacy JSON array
        else:
            cards = [json.loads(l) for l in fh if l.strip()]   # JSONL

    dropped = {}
    trimmed = []
    for c in cards:
        lay = c.get("layout")
        if lay in DROP_LAYOUTS:
            dropped[lay] = dropped.get(lay, 0) + 1
            continue
        trimmed.append(trim_card(c, prices))

    # Minified, no ASCII escaping — smallest possible output
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(trimmed, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"cards in:  {len(cards):,}")
    print(f"cards out: {len(trimmed):,}")
    for lay, n in sorted(dropped.items(), key=lambda x: -x[1]):
        print(f"  dropped {lay:<20} {n:,}")
    if prices:
        print("prices included — snapshot date = your bulk file's date")


if __name__ == "__main__":
    main()
