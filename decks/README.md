# decks/

The user's decks, one per list: `Owner_Commander_Strategy.txt` (the source list with `# key: value` headers, mtg.py format) and the matching `.dck` (Forge-ready). Save new lists with `python3 -m fishpond save LIST --name "Ians Zur Wizardcycling"`; the user supplies the name. Re-save after edits. Opponent gauntlets point here (`fishpond/opponents/own.txt`).

`paper_decks.txt` lists the decks Ian physically owns (one path per line). Set reviews and anything else that should only touch real, built decks read this list; everything else in this folder is a saved list, not necessarily a deck he owns.
