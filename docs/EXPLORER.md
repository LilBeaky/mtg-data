# EXPLORER — explorer.py

Companion to `USE_INSTRUCTIONS.md` §2. Read this only when running `explorer.py`. It's a standalone research tool for one card at a time. It is not part of the audit, and the audit never calls it.

Use it when the user names a card and asks what to do with it: who plays it, how, what it combos with, and where it could go that the field hasn't tried.

```
python3 scripts/explorer.py "Card Name" [--commanders 8] [--themes 6] [--ci WUBRG] [--limit 10]
    [--offline] [--refresh] [--out FILE]
```

## Sources

- **Local** (always): oracle text, price, Game Changer, legality, oracle tags, and Commander Spellbook combos from `data/`. Same name matching as `mtg.py` (aliases, DFC faces, partials).
- **EDHREC** (live): the page JSON at `json.edhrec.com/pages/...`. One card page, then up to `--commanders` commander pages and `--themes` theme pages, about 15 requests spaced 0.4s apart. Responses are cached in `data/explorer_cache/` (gitignored) for 7 days; `--refresh` refetches. The endpoint is undocumented and can change or block scripted traffic. Any failure leaves the local sections intact and prints `! EDHREC ...` in NOTES. When EDHREC is unreachable (the chat sandbox may block it, §13), read the card page with web tools instead.

## Sections

1. **Card**: oracle line, EDHREC card rank, decks playing it out of eligible decks, and salt. If the card can be a commander, it also shows that page's deck count and themes (solo page only; partner pairs have their own pages).
2. **Combos**: every Spellbook combo containing the card (filtered by `--ci`). Shows counts by size and by Spellbook tag, the most common outcomes, the generic pieces (`requires`) it needs, recurring partner cards, 2-card combos with no generic piece, the most played combos (outcomes cut to 3; `mtg.py combos` has the rest), and **combo commanders**: commander-legal pieces whose colors cover the card.
3. **Commanders**: EDHREC's top commanders by decks playing the card. Inclusion is the share of that commander's decks. Synergy comes from the commander page, so it's shown only for the first `--commanders`, and reads "not on its page" when the card falls below that page's cutoff. Also lists the **most committed** commanders (highest inclusion, 200+ decks) and the new commanders picking it up.
4. **Strategies**: themes from the opened commander pages, weighted by how many decks play the card under each commander. This is a ranking, not a count: it assumes the card is spread evenly across each commander's themes. Then the card's inclusion and synergy on each top theme page, which is the real test. A theme can rank high only because a popular commander runs it, while the card has no synergy there.
5. **Build-around**: high-lift cards (played with it far more than their base rate), EDHREC's similar cards, **untapped commanders** (legal commanders whose colors fit, that share the card's rarer oracle tags and aren't on EDHREC's top list, ranked by how rare the shared tags are), and the combo commanders from §2.
6. **Prompt**: a short reasoning prompt (`REASONING_PROMPT`, the last thing in `explorer.py`). After the report prints, follow it.

## Reading it

- **High inclusion, near-zero synergy** means a staple (Sol Ring). Strategy and theme numbers say little about a staple; skip ahead to combos and the off-label angle.
- **High synergy on a few commanders** means a build-around. The most-committed list and the theme-page synergy are the signal.
- Untapped commanders come from oracle-tag overlap, so they do *similar* things. That often means doubled-up triggers, not a guaranteed fit. Tags lag new sets, and a few tags are trivia (`inscryption achievement`); ignore those.
- Spellbook popularity (`pop`) is how often the combo shows up in decks Spellbook has indexed. It is not a quality score.
- EDHREC is meta signal, never card truth (§9). Verify every card you recommend with `mtg.py card` and check combos with `mtg.py combos`.

## Section 5b: findable by (added 2026-10-08)

Tutors in the card's colors (or `--ci`) that can fetch it, from tutors.py's reader run over the whole card pool
(`scripts/tutor_index.py`, cached per card-data date). Specific tutors first, then find-anything ones, most played
first; each with its mana value, one-shot or repeatable, where the card lands, price, Game Changer flag and how
often it's played next to this card on the card's EDHREC page. Land-only and graveyard-destination tutors are
left out. Same lookup from the command line: `python3 scripts/tutor_index.py "Card" [--ci WUB] [--md]`.
