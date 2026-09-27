# mtg-data

Magic: The Gathering card data, rulings, tags, combos, and rules — trimmed
down to GitHub-friendly sizes, plus the tooling to query them for Commander
deckbuilding and deck audits.

**Start here → [`docs/USE_INSTRUCTIONS.md`](docs/USE_INSTRUCTIONS.md).** It
covers setup, every script's usage, and the schema quirks worth knowing
before you write a custom query.

## Layout

```
mtg-data/
├── scripts/     # everything you execute (mtg.py, audit.py, etc.)
├── data/        # everything the scripts read (bulk data + your customizations)
├── docs/        # everything you read (start with USE_INSTRUCTIONS.md)
└── snapshots/   # EDHREC page transcriptions, one per commander/variant/date
```

## Writing conventions

`docs/USE_INSTRUCTIONS.md` and `docs/STATS_MATH.md` are written to work for
any deck owner and any AI assistant, not one specific pairing of the two —
so when editing them:

- Address the assistant directly, in second person ("you") — it's who's
  reading these docs to do the work.
- Call the deck owner **"the user"**, never a name.
- No product names either (e.g. "Claude") — keep it assistant-agnostic.

## Quick example

```bash
git clone --depth 1 https://github.com/LilBeaky/mtg-data.git
cd mtg-data
python3 scripts/mtg.py card "Sol Ring"
python3 scripts/audit.py your_decklist.txt --commander "Your Commander"
```

## Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com)
- Comprehensive Rules: Wizards of the Coast
- Commander meta data: [EDHREC](https://edhrec.com)
