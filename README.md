# mtg-data

Magic: The Gathering card data (Scryfall cards, prices, rulings, tags), Commander Spellbook combos, and the Comprehensive Rules, plus deckbuilding and deck-audit tools, built to be used **by an AI assistant**, not run by hand.

## How to use it

You don't need to run anything. Give your AI assistant (one that can run code, like Claude with code execution turned on) the link to this repo and tell it:

> Clone https://github.com/LilBeaky/mtg-data and follow docs/USE_INSTRUCTIONS.md before answering any card or deck question.

Then paste a decklist (a Moxfield export works) and ask for an audit, card lookups, combo checks, bracket checks, or draw odds.

Card data, prices, rulings, tags, combos, and the Comprehensive Rules refresh automatically every day.

## Letting the assistant save changes (optional)

Only needed if you want the assistant to push updates (new EDHREC snapshots, reskin aliases, fixes). GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token. Repository access: *Only select repositories* → this repo. Permissions: *Contents*, *Workflows*, and *Actions* all Read and write. Set an expiration, then paste the token into your assistant's project instructions. Treat it like a password.

## For editors of `docs/`

The docs are written for the assistant: second person ("you"), the deck owner is "the user", no product or personal names. Keep `USE_INSTRUCTIONS.md` minimal; tool-specific detail goes in its own doc (`STATS_MATH.md`, `GOLDFISH.md`). Scripts reference its section numbers, so keep them stable.

## Credits

- Card data, rulings, and tags: [Scryfall](https://scryfall.com)
- Combo data: [Commander Spellbook](https://commanderspellbook.com)
- Comprehensive Rules: Wizards of the Coast
- Commander meta data: [EDHREC](https://edhrec.com)
