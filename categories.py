"""
categories.py — curated category -> Oracle Tag label mapping for mtg-data.

Every entry below was validated against oracle-tags-20260922090032.jsonl via
mtg.load_tags() before being included -- these aren't guessed slugs, each one
returned real card coverage. Card counts are commander-legal + non-legal
combined (load_tags doesn't filter by legality); mtg.py's own search does
that filtering separately.

Use with stats_math.category_count_from_tag(decklist_path, CATEGORIES["ramp"]).
"""

CATEGORIES = {
    "ramp":            "ramp",              # 2,455 cards, 23 sub-tags
    "removal":         "removal",           # 6,738 cards, 55 sub-tags (all removal)
    "spot_removal":    "removal-creature",  # 5,763 cards, 19 sub-tags
    "card_draw":       "draw",              # 4,540 cards, 36 sub-tags
    "tutors":          "tutor",             # 1,226 cards, 147 sub-tags
    "protection":      "protection",        # 1,379 cards, 23 sub-tags
    "recursion":       "reanimate",         # 1,119 cards -- creature reanimation
                                             #   specifically, not hand/card recursion broadly
    "graveyard_hate":  "hate-graveyard",    # 436 cards, 4 sub-tags
    "counterspells":   "counterspell",      # 563 cards, 24 sub-tags
    "extra_turns":     "extra turn",        # 64 cards -- note the literal label has a space
    "sac_outlets":     "sacrifice outlet",  # 1,549 cards, 23 sub-tags -- also a space, not a hyphen
    "monarch":         "monarch matters",   # 49 cards
    "stax_ish":        "tax",               # 487 cards -- APPROXIMATION ONLY. Real stax covers
                                             #   more than tax effects (hatebears, prison pieces);
                                             #   no clean single-tag umbrella exists for "stax" itself.
}

# Searched for (including broadened regex passes over every raw label in the
# tags file) -- no clean single-tag umbrella exists in this dataset for these.
# Deliberately left unmapped rather than forced onto a misleading substitute.
NOT_MAPPED = [
    "board wipe / mass removal",   # no umbrella tag; removal-permanent-adjacent
                                    #   tags exist but don't cleanly isolate "wipes all"
    "land destruction / MLD",      # no matching label found under any tried phrasing
]
