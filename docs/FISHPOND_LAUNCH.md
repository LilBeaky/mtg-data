# Launch Fishpond — intake form

When the user says **"Launch Fishpond"**, reply with the form below (fenced, ready to copy), wait for it back, then: clone/setup, save the list with `python3 -m fishpond save LIST --name "NAME"` (re-save if it changed; write bracket/plan/key into its header), then (`python3 -m fishpond setup --jdk`), run `deck` on every list and report problems before running, give a time estimate (about 2-3 min per game per CPU with lookahead), run, and report per docs/FISHPOND.md "Reading the report". Blank fields take the default in brackets.

```
FISHPOND RUN
0. Deck name (Owner Commander Strategy, e.g. Ians Zur Cycling; saved to decks/):
1. My deck (paste the list, or the name of a deck already in decks/):

2. Bracket [required, 1-5]:
3. Plan (one line, how it's meant to win):
4. Key cards (; separated, what tutors should find / what I care about):
5. Track (optional, Label=Card or Label=regex, one per line):

6. Opponents [3 dummies]:
   a) vacuum (3 dummies)
   b) my gauntlet (Yusri, Zur, Klauth)
   c) specific decks (paste or name up to 3; empty seats = dummies)
   d) both a) and b)  ← recommended for a full read
7. Games per pod [20] (20 = ±22 pts, 50 = ±14, 100 = ±10):
8. Swap test (optional, Out => In; one swap per line):

9. Questions I want answered (free text, e.g. "how often does it win by T10", "is X dead weight"):

Advanced (leave blank unless testing):
10. My lookahead [hybrid] (off / hybrid / full; full also improves tutoring, slower):
11. Opponent lookahead [hybrid]:
12. AI profile [Default] (Default / Cautious / Reckless / Experimental):
13. Game length cap in my turns [20]:
14. Seed [1] (same seed = same games; change it for a fresh sample):
```
