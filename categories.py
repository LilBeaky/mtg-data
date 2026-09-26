"""
categories.py — curated category -> Scryfall Oracle Tag mapping for mtg-data.

Every label below was validated against oracle-tags-20260922090032.jsonl via
mtg.load_tags() — these aren't guessed slugs; each returned real card coverage.
Card counts are commander-legal + non-legal combined (load_tags doesn't filter
by legality). A value can be one label or a tuple of labels (union).

Used by audit.py (default role battery), `python3 stats_math.py report DECK`, and
stats_math.category_count_from_tag(decklist_path, CATEGORIES["ramp"]).

RELIABILITY — two real-deck checks, Sept 2026. Always read the matched names
(audit.py lists them; so does `python3 stats_math.py report DECK`).
  Yusri (99-card library):
    ramp misses cost reducers entirely (Ruby/Sapphire Medallion) -> cost_reducers
    tutor includes judgment calls (Okaun/Zndrsplt "partner with", Enter the Infinite)
    removal, counterspell, protection, extra turn matched cleanly
  Wilson (vs hand counts):
  Oracle tags answer "does this card have the effect?", not "does it fill this
  role in THIS deck?". Broad categories overcount:
    card_draw   15 vs 9 real engines (cantrips + cycling lands counted)
    protection  11 vs ~7 (Darksteel Mutation, Your Temple Is Under Attack counted)
    ramp        14 vs 11 (Bear Umbra, Krosan Verge, Mark of Sakiko counted)
  Strict mappings fix some of it: draw_engine matched the hand count exactly (9/9).
  Treat broad counts as candidate lists; Ian's own #tags or a confirmed --k
  override are the real K. audit.py flags when the difference changes the odds.
"""

CATEGORIES = {
    "ramp":            "ramp",              # 2,455 cards, 23 sub-tags — BROAD (extra land drops,
                                            #   cost reducers/increasers, combat ramp)
    "mana_producers":  ("mana dork", "mana dork egg", "mana rock", "utility mana rock", "moxen",
                        "mana rock with set's mechanic", "land ramp", "multi land ramp", "ritual"),
                                            # STRICT ramp: things that actually make or fetch mana.
                                            #   Chulane: 23 strict vs 26 broad vs ~19 by hand
    "card_draw":       "draw",              # 4,540 cards, 36 sub-tags — BROAD (cantrips, cycling, loot)
    "draw_engine":     ("draw engine", "repeatable draw", "repeatable pure draw",
                        "enchantment engine", "repeatable loot", "repeatable rummage",
                        "repeatable clues", "repeatable plunder", "repeatable blood"),
                                            # 2,065 cards — STRICT: repeatable draw only
    "removal":         "removal",           # 6,738 cards, 55 sub-tags (all removal, wipes included)
    "spot_removal":    "removal-creature",  # 5,763 cards, 19 sub-tags. NOTE: includes creature sweepers,
                                            #   so it's "creature removal", not strictly spot
    "board_wipes":     "sweeper",           # 984 cards (sweeper + sweeper-one-sided). Added Sept 2026;
                                            #   caught all 4 Wilson wipes + Fraying Line
    "tutors":          "tutor",             # 1,226 cards, 147 sub-tags (land tutors included)
    "protection":      "protection",        # 1,379 cards, 23 sub-tags — BROAD
    "recursion":       "recursion",         # 2,354 cards, 97 sub-tags. Was "reanimate" (creatures to
                                            #   battlefield only) — that missed Eternal Witness-style
                                            #   regrowth, which is why Chulane read "zero recursion"
    "reanimation":     "reanimate",         # 1,119 cards — the narrow version, kept for reanimator decks
    "graveyard_hate":  "hate-graveyard",    # 436 cards, 4 sub-tags
    "counterspells":   "counterspell",      # 563 cards, 24 sub-tags
    "extra_turns":     "extra turn",        # 64 cards -- note the literal label has a space
    "sac_outlets":     "sacrifice outlet",  # 1,549 cards, 23 sub-tags -- also a space, not a hyphen
    "cost_reducers":   "cost reducer",      # 387 cards, 25 sub-tags -- the Medallions etc.
                                             #   `ramp` does NOT include these; count both
                                             #   when judging a deck's mana (Yusri audit, Sept 2026)
    "monarch":         "monarch matters",   # 49 cards
    "stax_ish":        "tax",               # 487 cards -- APPROXIMATION ONLY. Real stax covers
                                            #   more than tax effects (hatebears, prison pieces);
                                            #   no clean single-tag umbrella exists for "stax" itself.
}

# Broad -> strict pairs. audit.py shows both and flags when they disagree enough
# to change a conclusion.
STRICT = {"card_draw": "draw_engine", "ramp": "mana_producers"}

# Reported by audit.py on every deck, in this order. Categories not listed here
# are still reported when the deck has at least one card in them.
AUDIT_ROLES = ["ramp", "card_draw", "draw_engine", "removal", "board_wipes", "protection",
               "tutors", "counterspells", "recursion", "graveyard_hate"]

# Common human labels -> category, for Ian's own #tags. Anything under the
# category's Scryfall subtree also matches automatically (e.g. "mana rock",
# "removal-creature", "draw engine"), so this only needs plain-English extras.
USER_SYNONYMS = {
    "ramp":           {"ramp", "mana", "mana rock", "rock", "mana dork", "dork", "land ramp", "ritual"},
    "mana_producers": {"mana rock", "rock", "mana dork", "dork", "land ramp", "ritual"},
    "card_draw":      {"draw", "card draw", "card advantage", "cantrip"},
    "draw_engine":    {"draw engine", "engine", "card draw engine", "enchantress"},
    "removal":        {"removal", "spot removal", "targeted removal"},
    "board_wipes":    {"board wipe", "boardwipe", "wipe", "wrath", "sweeper", "mass removal"},
    "protection":     {"protection", "protect"},
    "tutors":         {"tutor", "tutors"},
    "counterspells":  {"counter", "counterspell", "counterspells", "counters"},
    "recursion":      {"recursion", "regrowth", "reanimation", "reanimate"},
    "graveyard_hate": {"graveyard hate", "gy hate", "grave hate"},
    "cost_reducers":  {"cost reducer", "cost reduction", "reducer", "medallion"},
}

# Searched for (including broadened regex passes over every raw label in the
# tags file) -- no clean single-tag umbrella exists in this dataset for these.
# audit.py uses an oracle-text regex for MLD instead, as a review flag only.
NOT_MAPPED = [
    "land destruction / MLD",      # no matching label found under any tried phrasing
]
