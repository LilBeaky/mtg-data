#!/usr/bin/env python3
"""
trim_scryfall.py — reduce Scryfall oracle_cards bulk JSON to a GitHub-friendly size.

Keeps gameplay-relevant fields only, strips all legalities except Commander.
Original run: ~172MB -> ~17MB (clears GitHub's ~25MB web upload cap).

Accepts either JSONL (one card per line — Scryfall's current bulk format)
or a legacy JSON array. Output is always a minified JSON array.

Usage:
    python3 trim_scryfall.py input.jsonl output.json
"""

import json
import sys

# Top-level fields worth keeping for gameplay/deckbuilding questions
KEEP = [
    "id",
    "oracle_id",
    "name",
    "mana_cost",
    "cmc",
    "type_line",
    "oracle_text",
    "power",
    "toughness",
    "loyalty",
    "defense",
    "colors",
    "color_identity",
    "produced_mana",
    "keywords",
    "layout",
    "set",
    "rarity",
    "reserved",
    "game_changer",
    "edhrec_rank",
]

# Same field set, applied per-face for split/MDFC/transform cards
FACE_KEEP = [
    "name",
    "mana_cost",
    "type_line",
    "oracle_text",
    "power",
    "toughness",
    "loyalty",
    "defense",
    "colors",
]


def trim_card(card):
    # Omit empty AND false values — absent is unambiguously "no" for these fields
    out = {
        k: card[k]
        for k in KEEP
        if k in card and card[k] not in (None, [], "", False)
    }

    # Commander legality only
    leg = card.get("legalities", {})
    if "commander" in leg:
        out["legalities"] = {"commander": leg["commander"]}

    faces = card.get("card_faces")
    if faces:
        out["card_faces"] = [
            {k: f[k] for k in FACE_KEEP if k in f and f[k] not in (None, [], "")}
            for f in faces
        ]

    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    src, dst = sys.argv[1], sys.argv[2]

    with open(src, "r", encoding="utf-8") as fh:
        first = fh.read(1)
        fh.seek(0)
        if first == "[":
            cards = json.load(fh)          # legacy JSON array
        else:
            cards = [json.loads(l) for l in fh if l.strip()]   # JSONL

    trimmed = [trim_card(c) for c in cards]

    # Minified, no ASCII escaping — smallest possible output
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(trimmed, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"cards in:  {len(cards):,}")
    print(f"cards out: {len(trimmed):,}")


if __name__ == "__main__":
    main()
