#!/usr/bin/env python3
"""
fidelity.py — how much of each deck the simulation tools actually play (docs/FIDELITY_PLAN.md).

manasim.py, landbase.py and tutors.py's played numbers run on goldfish.py's card reading: a ramp,
card-draw or tutor card it doesn't read is inert in those games, and the numbers run low there.
This scores each deck against an independent answer key, Scryfall's oracle tags for those roles
(plus tutors.py's reader for tutors), and lists the cards to fix first.

  python3 scripts/fidelity.py [DECK ...] [--md] [--top N]     (default: every list in decks/)

REPORT
  per deck   played / total for ramp, card draw and tutors, and the unplayed cards
  overall    the same summed, and the unplayed cards ranked by copies across the decks: the
             to-do list for goldfish.py (an override in data/goldfish_overrides.json, a parser
             family, or a pilot fix)
"""
import argparse, contextlib, glob, io, os, sys
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import manasim as ms
from tutors import Out


def main():
    ap = argparse.ArgumentParser(description="Fidelity of the simulation tools per deck (see module docstring)")
    ap.add_argument("decks", nargs="*")
    ap.add_argument("--md", action="store_true"); ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    paths = a.decks or sorted(p for p in glob.glob(os.path.join(os.path.dirname(ROOT), "decks", "*.txt")))
    o = Out(a.md)
    o.title(f"FIDELITY: {len(paths)} deck(s) | ramp, card draw and tutors played by the simulation tools")
    o.note("Answer key: Scryfall's oracle tags for each role (and tutors.py's reader for tutors). 'Played' = goldfish.py")
    o.note("reads the card well enough for manasim.py's tutor mode to play it; unplayed cards are inert in those games.")
    rows, tot, cards, copies, decks_of = [], Counter(), Counter(), Counter(), {}
    for path in paths:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cov = ms.role_coverage(ms.load(path))
        except Exception as e:
            rows.append([os.path.basename(path), "error", "", "", f"{type(e).__name__}: {e}"]); continue
        c = cov["counts"]
        cell = lambda r: f"{c[r][0]}/{c[r][1]}" if r in c else "—"
        for r, (p, t) in c.items(): tot[r + "_p"] += p; tot[r + "_t"] += t
        qty = {}
        with contextlib.redirect_stdout(io.StringIO()):
            for q, cc, k in ms.load(path)[1]: qty[cc["name"]] = qty.get(cc["name"], 0) + q
        for n, rs, st in cov["unplayed"]:
            cards[n] += 1; copies[n] += qty.get(n, 1)
            decks_of.setdefault(n, (rs, st, []))[2].append(os.path.basename(path)[:-4])
        rows.append([os.path.basename(path)[:-4], cell("ramp"), cell("draw"), cell("tutor"),
                     "; ".join(f"{n} ({st})" for n, rs, st in cov["unplayed"][:6]) + (" …" if len(cov["unplayed"]) > 6 else "")])
    o.h2("Per deck")
    o.table(["Deck", "Ramp", "Card draw", "Tutors", "Not played (goldfish.py status)"], rows, right=(1, 2, 3))
    pct = lambda r: f"{tot[r + '_p']}/{tot[r + '_t']} ({100 * tot[r + '_p'] / tot[r + '_t']:.0f}%)" if tot[r + "_t"] else "—"
    o.note(f"overall: ramp {pct('ramp')}, card draw {pct('draw')}, tutors {pct('tutor')}")
    o.h2(f"To fix first (unplayed cards by copies across the decks, then decks; top {a.top})")
    top = sorted(cards, key=lambda n: (-copies[n], -cards[n], n))[:a.top]
    o.table(["Card", "Copies", "Decks", "Role", "goldfish.py", "In"],
            [[n, copies[n], cards[n], "/".join(ms.ROLE_NAMES[r] for r in decks_of[n][0]), decks_of[n][1],
              ", ".join(decks_of[n][2][:4])] for n in top], right=(1, 2))
    o.note("Each fix lifts every deck that runs the card. Status 'blank' = not read at all; 'partial' = read but its")
    o.note("ramp/draw/tutor part isn't; 'held' = kept as interaction; 'vacuum' = needs opponents. See FIDELITY_PLAN.md.")


if __name__ == "__main__":
    main()
