"""The game page: every game of a run, turn by turn for all four seats, as one HTML file (games.html in the run directory).

It's the standard output of `fishpond run` (and so of each pod of a `fishpond study`); `python3 -m fishpond page RUN_DIR...`
writes it for runs made before (a study directory: one page per pod). The user, 2026-10-28: "I'd actually like to make it the
standard output format".

Read from the run's worker logs: Forge's game log (lands, casts, activations, attacks, blocks, combat damage, life), the turn
plan's main-1 line (#FP-PLAN: mana budget, what it left out), the sequencing meter (#FP-SEQ: mana left unused), the harness's
end-of-turn board (#FP-BOARD, from 2026-10-29: creatures, other permanents, commander zone, commander damage taken) and the
wipe judge (#FP-WIPE: which cast cards were wipes). A run from before #FP-BOARD gets the page without the board lines.

Page: the decks across all games; a tab per game with the result, each deck's summary and the game's key moments (commanders
cast and removed, wipes, big combat turns, eliminations, the win); then one row per round (each deck's own turn N), a column
per deck: mana, plays, combat, what the plan left out, the board at the end of that turn, and plays on other decks' turns.
Each deck's color comes from its commander's color identity.
"""
import glob, html, json, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

SEAT = re.compile(r"Ai\((\d)\)-([^\s']+)")
BIG_COMBAT = 15          # combat damage to players in one turn that makes a key moment


def _seat(s):
    m = SEAT.search(str(s))
    return int(m.group(1)) if m else None


def _short(card):
    return re.sub(r" \(\d+\)", "", card).strip()


# ---------------------------------------------------------------------------------------------------------------- parsing
def _games_in(log):
    """(Forge log lines, plans, seq, boards, wipes, moves, end record) per game in one worker log."""
    lines, plans, seqs, boards, wipes, moves = [], {}, {}, {}, [], []
    for raw in open(log, encoding="utf-8", errors="replace"):
        line = raw.rstrip("\n")
        try:
            if line.startswith("#FP-PLAN "):
                p = json.loads(line[9:])
                if p.get("phase") == "MAIN1": plans.setdefault((p["t"], _seat(p["seat"])), p)
            elif line.startswith("#FP-SEQ "):
                q = json.loads(line[8:]); seqs[(int(q["seat"]), q["turn"])] = q
            elif line.startswith("#FP-BOARD "):
                b = json.loads(line[10:]); boards[b["t"]] = b["seats"]
            elif line.startswith("#FP-WIPE "):
                wipes.append(json.loads(line[9:]))
            elif line.startswith("#FP-MOVE "):
                moves.append(json.loads(line[9:]))
            elif line.startswith("#FP-END "):
                yield lines, plans, seqs, boards, wipes, moves, json.loads(line[8:])
                lines, plans, seqs, boards, wipes, moves = [], {}, {}, {}, [], []
            elif not line.startswith("#"):
                lines.append(line)
        except ValueError:
            continue


def _parse(lines):
    names, turns, cur, own = {}, [], None, defaultdict(int)
    life = {}
    for ln in lines:
        m = re.match(r"Turn: Turn (\d+) \((Ai\((\d)\)-(\S+))\)", ln)
        if m:
            s = int(m.group(3)); names[s] = m.group(4); own[s] += 1
            cur = dict(t=int(m.group(1)), seat=s, own=own[s], ev=defaultdict(list), dmg=defaultdict(int))
            turns.append(cur)
            continue
        if cur is None: continue
        ev = cur["ev"]
        if ln.startswith("Land: "):
            m = re.match(r"Land: (Ai\(\d\)-\S+) played (.+)", ln)
            if m: ev[_seat(m.group(1))].append(["land", _short(m.group(2))])
        elif ln.startswith("Add To Stack: "):
            m = re.match(r"Add To Stack: (Ai\(\d\)-\S+) (cast|activated) (.+?)(?: targeting \[(.*)\])?$", ln)
            if m:
                tgt = _short(m.group(4)) if m.group(4) else ""
                ev[_seat(m.group(1))].append([m.group(2), _short(m.group(3)), tgt])
        elif ln.startswith("Combat: ") and " to attack " in ln:
            m = re.match(r"Combat: (Ai\(\d\)-\S+) assigned (.+) to attack (.+)\.$", ln)
            if m:
                who = [_short(x) for x in re.split(r", | and ", m.group(2))]
                ev[_seat(m.group(1))].append(["attack", ", ".join(who), SEAT.sub(lambda k: k.group(2), m.group(3))])
        elif ln.startswith("Combat: ") and " to block " in ln:
            m = re.match(r"Combat: (Ai\(\d\)-\S+) assigned (.+) to block (.+)\.$", ln)
            if m: ev[_seat(m.group(1))].append(["block", _short(m.group(2)), _short(m.group(3))])
        elif ln.startswith("Damage: ") and "combat damage to Ai(" in ln:
            m = re.match(r"Damage: (.+?) deals (\d+) combat damage to (Ai\(\d\)-\S+)\.?$", ln)
            if m: cur["dmg"][_seat(m.group(3))] += int(m.group(2))
        elif ln.startswith("Life: "):
            m = re.match(r"Life: Life: (Ai\(\d\)-\S+) (-?\d+) > (-?\d+)", ln)
            if m: life[_seat(m.group(1))] = int(m.group(3))
        elif ln.startswith("Zone Change: ") and "from Battlefield" in ln:
            cur.setdefault("left", []).append(ln)
        cur["life"] = dict(life)
    return names, turns


def _commanders(boards, turns, names):
    """seat -> commander names (the board's list; else the first cast whose name starts with the seat's short name)."""
    out = {}
    for b in boards.values():
        for k, v in b.items():
            if v.get("cmd") and int(k) not in out: out[int(k)] = [c["n"] for c in v["cmd"]]
    for tr in turns:
        for s, evs in tr["ev"].items():
            for e in evs:
                if s not in out and e[0] == "cast" and e[1].startswith(names.get(s, "~")): out[s] = [e[1]]
    return out


MOVED = {("Library", "Hand"): "found {c}", ("Library", "Battlefield"): "{c} onto the battlefield",
         ("Hand", "Battlefield"): "{c} onto the battlefield", ("Graveyard", "Battlefield"): "{c} back from the graveyard",
         ("Graveyard", "Hand"): "{c} back to hand"}


def _attach_moves(turns, moves, names):
    """What a tutor found and what Show and Tell, reanimation or a dig put onto the battlefield (#FP-MOVE), on the cast or
    activation that did it; a trigger's moves (Zur's attack search) become their own line on the seat's events."""
    by_t = defaultdict(list)
    for m in moves: by_t[m["t"]].append(m)
    for tr in turns:
        ms = by_t.get(tr["t"])
        if not ms: continue
        groups = defaultdict(list)
        for m in ms: groups[(int(m["by"]) if str(m["by"]).isdigit() else None, m["src"], m.get("trigger", False))].append(m)
        for (by, src, trig), lst in groups.items():
            parts = []
            for m in lst:
                txt = MOVED.get((m["from"], m["to"]), "{c}").format(c=m["card"])
                owner = int(m["seat"]) if str(m["seat"]).isdigit() else None
                parts.append((names.get(owner, "?") + ": " if owner != by else "") + txt)
            res = "; ".join(parts)
            evs = tr["ev"].get(by) if by is not None else None
            hit = None
            if evs and not trig:
                for e in reversed(evs):
                    if e[0] in ("cast", "activated") and e[1] == src and len(e) < 4: hit = e; break
            if hit is not None: hit.append(res)
            elif by is not None: tr["ev"][by].append(["found", src + (" (trigger)" if trig else ""), "", res])


def game_record(lines, plans, seqs, boards, wipes, moves, end, pod=""):
    names, turns = _parse(lines)
    _attach_moves(turns, moves, names)
    cmds = _commanders(boards, turns, names)
    wipe_cards = {w["card"] for w in wipes}
    seats = sorted(names)
    order = list(dict.fromkeys(tr["seat"] for tr in turns)) + [s for s in seats if s not in {tr["seat"] for tr in turns}]
    # commander leaving the battlefield, with a cause when the log names one
    for tr in turns:
        out = []
        for ln in tr.pop("left", []):
            for s, cl in cmds.items():
                for c in cl:
                    if ln.startswith(f"Zone Change: {c} ("):
                        dest = ("dies" if "into Graveyard" in ln else "goes to the command zone" if "Command" in ln else "exiled" if "Exile" in ln
                                else "returned to hand" if "into Hand" in ln else "put into the library")
                        out.append((s, c, dest))
        tr["cmd_left"] = out
    rows = []
    stats = {s: dict(attacks=0, dealt=0, casts=0, cmd_first=None, cmd_casts=0, cmd_left=0) for s in seats}
    moments = []
    for tr in turns:
        a = tr["seat"]
        for s, evs in tr["ev"].items():
            for e in evs:
                if e[0] == "cast":
                    stats[s]["casts"] += 1
                    if cmds.get(s) and e[1] == cmds[s][0]:
                        stats[s]["cmd_casts"] += 1
                        if stats[s]["cmd_first"] is None:
                            stats[s]["cmd_first"] = tr["own"] if s == a else None
                            moments.append(dict(t=tr["t"], seat=s, kind="cmd", text=f"{names[s]} casts {e[1]}"
                                                + (f" on its turn {tr['own']}" if s == a else " (on another deck's turn)")))
                        elif stats[s]["cmd_casts"] > 1:
                            moments.append(dict(t=tr["t"], seat=s, kind="cmd", text=f"{names[s]} recasts {e[1]} (cast {stats[s]['cmd_casts']})"))
                    if e[1] in wipe_cards:
                        moments.append(dict(t=tr["t"], seat=s, kind="wipe", text=f"{names[s]} casts {e[1]} (a wipe)"))
                if e[0] == "attack" and s == a: stats[s]["attacks"] += 1
        dealt = sum(tr["dmg"].values())
        stats[a]["dealt"] += dealt
        if dealt >= BIG_COMBAT:
            moments.append(dict(t=tr["t"], seat=a, kind="combat", text=f"{names[a]} deals {dealt} combat damage ("
                                + ", ".join(f"{names.get(k, k)} {v}" for k, v in sorted(tr["dmg"].items(), key=lambda x: -x[1])) + ")"))
        for s, c, dest in tr["cmd_left"]:
            stats[s]["cmd_left"] += 1
            cause = None
            for s2, evs in tr["ev"].items():
                for e in evs:
                    if e[0] in ("cast", "activated") and len(e) > 2 and c in e[2]:
                        cause = f"{e[1]} ({names.get(s2, s2)})"
                    elif e[0] == "cast" and e[1] in wipe_cards and cause is None:
                        cause = f"{e[1]} ({names.get(s2, s2)}'s wipe)"
                    elif e[0] == "block" and (e[2] == c or e[1] == c) and cause is None:
                        cause = "combat" + (f": blocked by {e[1]}" if e[2] == c else f", blocking {e[2]}")
            by = (" in " if cause.startswith("combat") else " to " if dest == "dies" else " by ") + cause if cause else ""
            moments.append(dict(t=tr["t"], seat=s, kind="removed", text=f"{c.split(',')[0]} {dest}{by}"))
        # cells: the active deck's own turn; the others' plays on that turn
        row = dict(t=tr["t"], seat=a, own=tr["own"], items=[], off={}, dmg=dict(tr["dmg"]))
        for s, evs in tr["ev"].items():
            shown = [[e[0], e[1] + (f" → {e[2]}" if len(e) > 2 and e[2] and e[0] != "block" else "")] + ([e[3]] if len(e) > 3 else [])
                     if e[0] != "block" else ["block", f"{e[1]} blocks {e[2]}"] for e in evs]
            if s == a: row["items"] = shown
            else: row["off"][s] = shown
        p = plans.get((tr["t"], a))
        q = seqs.get((a, tr["own"]))
        row["plan"] = None if not p else dict(budget=p["budget"], left=[f"{x['card']} ({x['cost']})" for x in p["left_out"][:3]])
        row["unused"] = None if not q else q.get("left")
        row["hand"] = None if not q else q.get("hand")
        b = boards.get(tr["t"])
        row["board"] = b.get(str(a)) if b else None   # the active seat's board at the end of its turn
        row["life"] = tr.get("life", {})
        rows.append(row)
    # eliminations: the first board that shows the seat out, else its last turn
    out_at = {}
    for t in sorted(boards):
        for k, v in boards[t].items():
            if v.get("out") and int(k) not in out_at: out_at[int(k)] = t
    outcome = {int(k): v["outcome"] for k, v in end["players"].items()}
    for s in seats:
        o = outcome.get(s, "")
        if o.startswith("has won"):
            continue
        if s not in out_at and "an opponent has won" not in o:
            for tr in turns:
                if tr.get("life", {}).get(s, 1) <= 0: out_at[s] = tr["t"]; break
        if s in out_at:
            moments.append(dict(t=out_at[s], seat=s, kind="out", text=f"{names[s]} is out: {re.sub(r'^has lost (because |due to )?', '', o)}"))
    winner = next((s for s in seats if outcome.get(s, "").startswith("has won")), None)
    how = ""
    if winner is not None:
        how = re.sub(r"^has won (because |due to )?", "", outcome[winner])
        alt = [o for o in outcome.values() if "won by " in o]
        if alt: how = alt[0].split("won by ", 1)[1]
        moments.append(dict(t=end.get("global_turns"), seat=winner, kind="win", text=f"{names[winner]} wins: {how}"))
    moments.sort(key=lambda m: (m["t"] or 0, ["cmd", "wipe", "removed", "combat", "out", "win"].index(m["kind"])))
    return dict(pod=pod, game=end["id"], seed=end.get("seed"), stop=end.get("stop"), turns=end.get("global_turns"), order=order,
                names={s: names[s] for s in seats}, commanders={s: cmds.get(s, []) for s in seats}, winner=winner, how=how,
                outcome={s: outcome.get(s, "") for s in seats}, out_at=out_at, stats=stats, moments=moments, rows=rows)


def load_run(run_dir):
    """Every game of one run directory (a pod), in game order."""
    games = []
    for log in sorted(glob.glob(os.path.join(run_dir, "logs", "worker*.log"))):
        for parts in _games_in(log):
            try:
                games.append(game_record(*parts, pod=os.path.basename(os.path.normpath(run_dir))))
            except (KeyError, ValueError, IndexError):
                continue
    games.sort(key=lambda g: g["game"])
    return games


# ---------------------------------------------------------------------------------------------------------------- colors
# light / dark pairs per color, two shades each so two decks of one color stay apart
HUES = {"W": [("#a8801a", "#e2c46a"), ("#8d7a52", "#cdb98d")], "U": [("#2f5fa8", "#7ea6ee"), ("#1f7f95", "#62c3d6")],
        "B": [("#5d4a8a", "#a993e0"), ("#6e5562", "#c39bb0")], "R": [("#c2412d", "#f07a63"), ("#b8601a", "#ec9b56")],
        "G": [("#3c7d3a", "#7cc076"), ("#617d1f", "#a8c766")], "C": [("#6f6a64", "#b3ada6"), ("#7d6c55", "#c2ad8e")]}


def deck_pips(run_dirs):
    """deck name -> colored mana symbols counted over the whole list (the run's decks/*.dck: [metadata] Name=, then '1 Card')."""
    try:
        import mtg
    except ImportError:
        return {}
    out = {}
    for d in run_dirs:
        for f in glob.glob(os.path.join(d, "decks", "*.dck")):
            name, pips = None, defaultdict(int)
            for line in open(f, encoding="utf-8", errors="replace"):
                line = line.strip()
                if line.startswith("Name="): name = line[5:]; continue
                m = re.match(r"(\d+) (.+?)(?:\|.*)?$", line)
                if not m: continue
                card = mtg.find(m.group(2))[0]
                if not card: continue
                cost = card.get("mana_cost") or " ".join(f.get("mana_cost", "") for f in card.get("card_faces") or [])
                for ch in re.findall(r"\{([WUBRG])(?:/[WUBRGP])?\}", cost): pips[ch] += int(m.group(1))
            if name and name not in out: out[name] = pips
    return out


def deck_colors(commanders, pips_by_deck=None):
    """deck name -> {identity, light, dark}: the commanders' color identity; the deck's color is the identity color with the
    most mana symbols across its list (else in its first commander's cost; ties in WUBRG order), the second shade when another
    deck already has the first."""
    try:
        import mtg
    except ImportError:
        mtg = None
    out, used = {}, set()
    for deck, cl in commanders.items():
        ident, pips = set(), defaultdict(int)
        for k, c in enumerate(cl):
            card = mtg.find(c)[0] if mtg else None
            if not card: continue
            ident |= set(card.get("color_identity") or [])
            if k == 0:
                for ch in re.findall(r"\{([WUBRG])\}", card.get("mana_cost") or ""): pips[ch] += 1
        if pips_by_deck and sum(pips_by_deck.get(deck, {}).values()): pips = pips_by_deck[deck]
        order = sorted((x for x in "WUBRG" if x in ident), key=lambda x: (-pips[x], "WUBRG".index(x))) or ["C"]
        pick = None
        for col in order + ["C"]:
            for k, pair in enumerate(HUES[col]):
                if (col, k) not in used: pick = (col, k, pair); break
            if pick: break
        if pick is None: pick = (order[0], 0, HUES[order[0]][0])
        used.add(pick[:2])
        out[deck] = dict(identity="".join(x for x in "WUBRG" if x in ident) or "C", light=pick[2][0], dark=pick[2][1])
    return out


# ---------------------------------------------------------------------------------------------------------------- page
def build(games, title, note, run_dirs=()):
    decks = {}
    for g in games:
        for s, n in g["names"].items():
            decks.setdefault(n, g["commanders"].get(s) or [n])
    colors = deck_colors(decks, deck_pips(run_dirs))
    agg = {}
    for g in games:
        for s, n in g["names"].items():
            a = agg.setdefault(n, dict(games=0, wins=0, cast=[], never=0, attacks=0, dealt=0, removed=0))
            st = g["stats"][s]
            a["games"] += 1; a["wins"] += g["winner"] == s
            if st["cmd_first"] is None and not st["cmd_casts"]: a["never"] += 1
            elif st["cmd_first"] is not None: a["cast"].append(st["cmd_first"])
            a["attacks"] += st["attacks"]; a["dealt"] += st["dealt"]; a["removed"] += st["cmd_left"]
    order = list(dict.fromkeys(n for g in games for _, n in sorted(g["names"].items())))
    css_decks = "\n".join(f'[data-deck="{html.escape(n)}"] {{ --c: {c["light"]} }}' for n, c in colors.items())
    def dark(scope):
        return "\n".join(f'{scope} [data-deck="{html.escape(n)}"] {{ --c: {c["dark"]} }}' for n, c in colors.items())
    payload = json.dumps(dict(games=games, agg=agg, order=order, colors=colors), separators=(",", ":")).replace("</", "<\\/")
    return (PAGE.replace("__TITLE__", html.escape(title)).replace("__NOTE__", html.escape(note))
            .replace("__DECKCSS__", css_decks).replace("__DECKDARK_MEDIA__", dark(':root:not([data-theme="light"])'))
            .replace("__DECKDARK_THEME__", dark(':root[data-theme="dark"]')).replace("__DATA__", payload))


def title_for(games, meta=None):
    names = list(dict.fromkeys(n for g in games for _, n in sorted(g["names"].items())))
    return ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "") if names else "Fishpond games"


def note_for(games, meta, run_dir):
    bits = [f"{len(games)} game{'s' if len(games) != 1 else ''}"]
    if meta:
        if meta.get("seed") is not None: bits.append(f"seed {meta['seed']}")
        if meta.get("sim"): bits.append(f"{meta['sim']} lookahead")
        if meta.get("patches"): bits.append(f"Forge patches 01-{meta['patches']:03d}" if isinstance(meta["patches"], int) else str(meta["patches"]))
    bits.append(os.path.relpath(run_dir, os.path.dirname(HERE)) if run_dir.startswith(os.path.dirname(HERE)) else run_dir)
    return " · ".join(bits)


def write(run_dir, out=None, title=None, note=None, quiet=True):
    """Write RUN_DIR/games.html (or OUT) for one run directory; returns the path, or None when it has no finished game."""
    games = load_run(run_dir)
    if not games: return None
    meta = None
    try: meta = json.load(open(os.path.join(run_dir, "meta.json"), encoding="utf-8"))
    except (OSError, ValueError): pass
    out = out or os.path.join(run_dir, "games.html")
    open(out, "w", encoding="utf-8").write(build(games, title or title_for(games, meta), note or note_for(games, meta, run_dir), [run_dir]))
    if not quiet: print(f"fishpond: game page -> {out} ({len(games)} games)")
    return out


def cmd(args):
    """`fishpond page RUN_DIR...`: a run directory gets its page; a study directory gets one page per pod."""
    for d in args.runs:
        d = os.path.normpath(d)
        if os.path.isdir(os.path.join(d, "logs")):
            write(d, out=args.out, title=args.title, quiet=False)
        else:
            for pod in sorted(glob.glob(os.path.join(d, "*/"))):
                if os.path.isdir(os.path.join(pod, "logs")): write(os.path.normpath(pod), quiet=False)


PAGE = r"""<title>__TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* Layout: a match sheet. Decks across the games on top, a tab per game (result, key moments), then one row per round with a
   column per deck. Each deck's color comes from its commander's color identity. */
:root {
  --bg: #f6f5f2; --panel: #ffffff; --ink: #1e1d22; --muted: #66636e; --line: #dedbe3; --chip: #efedf3;
  --accent: #5b3fa6; --win: #1f7a4d; --loss: #a33a2c; --warn: #9a6a00;
  --pW: #d9c27a; --pU: #4f86d1; --pB: #4a4352; --pR: #d4553f; --pG: #4f9a4b; --pC: #a9a39b;
  --c: var(--accent);
  --display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
__DECKCSS__
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #16151a; --panel: #1f1e25; --ink: #ecebf0; --muted: #a29fac; --line: #34323d; --chip: #2a2833;
    --accent: #a58cf0; --win: #5cc28f; --loss: #f08a78; --warn: #e5b450;
    --pW: #e8d58f; --pU: #7ea6ee; --pB: #8d84a0; --pR: #f07a63; --pG: #7cc076; --pC: #c2bcb4; color-scheme: dark }
  __DECKDARK_MEDIA__
}
:root[data-theme="dark"] {
  --bg: #16151a; --panel: #1f1e25; --ink: #ecebf0; --muted: #a29fac; --line: #34323d; --chip: #2a2833;
  --accent: #a58cf0; --win: #5cc28f; --loss: #f08a78; --warn: #e5b450;
  --pW: #e8d58f; --pU: #7ea6ee; --pB: #8d84a0; --pR: #f07a63; --pG: #7cc076; --pC: #c2bcb4; color-scheme: dark }
__DECKDARK_THEME__
* { box-sizing: border-box }
[hidden] { display: none !important }
body { background: var(--bg); color: var(--ink); font: 15px/1.45 var(--body); }
.wrap { max-width: 1440px; margin: 0 auto; padding-block: 28px 56px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 22px; }
h1 { font: 700 2.1rem/1.05 var(--display); letter-spacing: .01em; margin: 0; text-wrap: balance }
h2 { font: 600 1.35rem/1.1 var(--display); margin: 0; letter-spacing: .02em }
h3 { margin: 0 }
.sub { color: var(--muted); margin: 6px 0 0; max-width: 80ch }
.label { font: 600 .72rem/1 var(--body); text-transform: uppercase; letter-spacing: .08em; color: var(--muted) }
.num { font-family: var(--mono); font-variant-numeric: tabular-nums }
.decks { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px }
.deck { background: var(--panel); border: 1px solid var(--line); border-top: 4px solid var(--c); border-radius: 6px; padding: 12px 14px; display: grid; gap: 8px; align-content: start }
.deck h3 { font: 600 1.2rem/1 var(--display); color: var(--c); display: flex; gap: 8px; align-items: center; flex-wrap: wrap }
.pips { display: inline-flex; gap: 3px }
.pip { width: 10px; height: 10px; border-radius: 50%; display: inline-block; border: 1px solid var(--line) }
.pip.W { background: var(--pW) } .pip.U { background: var(--pU) } .pip.B { background: var(--pB) } .pip.R { background: var(--pR) } .pip.G { background: var(--pG) } .pip.C { background: var(--pC) }
.kv { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 3px 10px; font-size: .9rem }
.kv span:nth-child(odd) { color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.kv span:nth-child(even) { text-align: right }
.tabs { display: flex; flex-wrap: wrap; gap: 8px }
.tab { font: 600 1rem/1 var(--display); letter-spacing: .03em; padding: 9px 14px; border-radius: 6px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); cursor: pointer; display: grid; gap: 3px; text-align: left }
.tab small { font: 400 .78rem/1.1 var(--body); color: var(--muted) }
.tab[aria-selected="true"] { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent) }
.tab:focus-visible, button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
.game-head { display: grid; gap: 12px }
.result { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: baseline }
.result b { font: 700 1.5rem/1 var(--display) }
.pill { display: inline-block; font: 600 .75rem/1 var(--body); padding: 4px 7px; border-radius: 99px; background: var(--chip); color: var(--muted) }
.pill.win { color: var(--win) } .pill.loss { color: var(--loss) }
.moments { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; display: grid; gap: 8px }
.moments ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px }
.moments li { display: grid; grid-template-columns: 52px 74px minmax(0, 1fr); gap: 8px; align-items: baseline; font-size: .9rem }
.moments .when { font-family: var(--mono); font-size: .78rem; color: var(--muted) }
.tag { font: 600 .66rem/1.5 var(--body); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); border-left: 3px solid var(--c); padding-left: 6px }
.moments li.win .tag { color: var(--win) } .moments li.out .tag, .moments li.removed .tag { color: var(--loss) } .moments li.wipe .tag { color: var(--warn) }
.moments li .who { color: var(--c); font-weight: 600 }
.grid { overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--panel) }
table { border-collapse: collapse; width: 100%; min-width: 1040px; table-layout: fixed }
th, td { vertical-align: top; border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left }
th { font: 600 1.05rem/1 var(--display); letter-spacing: .03em; position: sticky; top: 0; background: var(--panel); z-index: 1 }
th.deckh { color: var(--c); border-bottom: 3px solid var(--c) }
td.rnd, th.rnd { width: 52px; color: var(--muted); font-family: var(--mono); font-size: .8rem }
td + td { border-left: 1px solid var(--line) }
.cell { display: grid; gap: 4px; font-size: .86rem }
.top { display: flex; justify-content: space-between; gap: 6px; align-items: baseline }
.top .t { font: 600 .95rem/1 var(--display); color: var(--c) }
.mana { font-family: var(--mono); font-size: .76rem; color: var(--muted) }
.it { display: grid; grid-template-columns: 52px minmax(0, 1fr); gap: 6px }
.it .k { font: 600 .66rem/1.6 var(--body); text-transform: uppercase; letter-spacing: .07em; color: var(--muted) }
.it.cast .k { color: var(--accent) } .it.attack .k { color: var(--loss) } .it.cmd .k, .it.block .k { color: var(--warn) }
.it.land .v { color: var(--muted) }
.off { border-top: 1px dashed var(--line); padding-top: 4px; color: var(--muted); font-size: .8rem }
.off .it .v { color: var(--ink) }
.note { font-size: .76rem; color: var(--muted) }
.bd { border-top: 1px solid var(--line); padding-top: 5px; display: grid; gap: 3px; font-size: .8rem }
.bd .sum { font-family: var(--mono); font-size: .74rem; color: var(--muted) }
.bd .cr { overflow-wrap: anywhere }
.bd .cmdc { color: var(--c); font-weight: 600 }
.bd details summary { cursor: pointer; color: var(--muted); font-size: .76rem }
.life { display: flex; gap: 6px; align-items: center; font-family: var(--mono); font-size: .78rem }
.life .bar { flex: 1; height: 4px; background: var(--chip); border-radius: 2px; overflow: hidden }
.life .bar i { display: block; height: 100%; background: var(--c) }
.dmgwarn { color: var(--loss) }
.dead { color: var(--loss); font-weight: 600; font-size: .8rem }
.cmd-chip { font: 600 .66rem/1 var(--body); text-transform: uppercase; letter-spacing: .06em; padding: 3px 5px; border-radius: 4px; background: var(--chip); color: var(--muted); white-space: nowrap }
.cmd-chip.on { color: var(--c) }
.deckbtn { font: inherit; color: inherit; text-align: left; cursor: pointer; width: 100% }
.deckbtn:hover { border-color: var(--c) }
.deckbtn[aria-pressed="true"] { box-shadow: inset 0 0 0 2px var(--c) }
.deckbtn:focus-visible, .linkbtn:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }
.deck h3 .go { margin-left: auto; font: 600 .66rem/1 var(--body); text-transform: uppercase; letter-spacing: .07em; color: var(--muted) }
.res { display: block; color: var(--muted); font-size: .8rem }
.res::before { content: "↳ " }
.it.found .k { color: var(--accent) }
.linkbtn { font: 600 .85rem/1.2 var(--body); color: var(--accent); background: none; border: 0; padding: 0; cursor: pointer; text-decoration: underline }
.browser { display: grid; gap: 10px; width: 100% }
.filters { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center }
.filters input { min-width: 0; flex: 1 1 260px; max-width: 420px; padding: 7px 9px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); font: inherit }
.filters select { padding: 7px 9px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); font: inherit }
.glist { display: flex; flex-wrap: wrap; gap: 8px }
.pager { display: flex; gap: 12px; align-items: center }
.pager button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer }
.pager button[disabled] { opacity: .45; cursor: default }
table.dv { min-width: 900px; margin-bottom: 0 }
table.dv + table.dv { border-top: 2px solid var(--line) }
table.dv td, table.dv th { font-size: .85rem }
table.dv th.wide { width: 30% } table.dv th.wide2 { width: 46% }
.mms { display: grid; gap: 2px }
.mm { font-size: .8rem } .mm.win { color: var(--win) } .mm.out, .mm.removed { color: var(--loss) } .mm.wipe { color: var(--warn) }
.legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: .82rem; color: var(--muted) }
@media (max-width: 520px) { h1 { font-size: 1.7rem } .moments li { grid-template-columns: 44px minmax(0, 1fr) } .moments li .tag { display: none } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important } }
</style>
<div class="wrap">
  <header>
    <div class="label">Fishpond · game page</div>
    <h1>__TITLE__</h1>
    <p class="sub">__NOTE__</p>
  </header>
  <section aria-label="Across all games"><div class="decks" id="agg"></div></section>
  <nav class="tabs" id="tabs" role="tablist" aria-label="Games"></nav>
  <section id="game" class="game-head"></section>
  <div class="legend" id="legend"><span>Each row is one round: every deck's own turn N; #N counts turns across all four seats.</span><span>Mana: the main-phase plan's budget (lands, rocks, a land drop) and what was left unused.</span><span>Board: at the end of that deck's turn.</span><span>Dashed: plays on other decks' turns.</span></div>
  <div class="grid" id="board"></div>
</div>
<script>
const DATA = __DATA__;
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const KIND = {land: "Land", cast: "Cast", activated: "Ability", attack: "Attack", block: "Block", found: "Search"};
const TAG = {cmd: "Commander", wipe: "Wipe", removed: "Removed", combat: "Combat", out: "Out", win: "Win"};
const dd = n => `data-deck="${esc(n)}"`;
const pips = n => { const c = DATA.colors[n]; return c ? `<span class="pips" aria-label="color identity ${c.identity}">${c.identity.split("").map(x => `<i class="pip ${x}"></i>`).join("")}</span>` : ""; };
const median = a => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const fmt1 = v => v == null ? "–" : (Math.round(v * 10) / 10).toString();
const pct = (k, n) => n ? Math.round(100 * k / n) + "%" : "–";
const BIG = DATA.games.length > 12;      // past a dozen games the tabs become a game list
const state = {view: "game", game: 0, deck: null, page: 0, filter: "", winner: ""};
const save = () => { try { localStorage.setItem("fp-view", JSON.stringify({view: state.view, game: state.game, deck: state.deck})); } catch (e) {} };

function aggView() {
  document.getElementById("agg").innerHTML = DATA.order.filter(n => DATA.agg[n]).map(n => {
    const a = DATA.agg[n];
    const casts = a.cast.length ? a.cast.slice().sort((x, y) => x - y).map(x => "T" + x).join(", ") : "none";
    const on = state.view === "deck" && state.deck === n;
    return `<button class="deck deckbtn" ${dd(n)} aria-pressed="${on}" data-open="${esc(n)}" title="Show ${esc(n)} across all games">
      <h3>${esc(n)} ${pips(n)}<span class="go">${on ? "Showing" : "Deck view"}</span></h3><div class="kv">
      <span>Games won</span><span class="num">${a.wins} of ${a.games}</span>
      <span>Commander first cast</span><span class="num">${casts.length > 26 ? "median T" + fmt1(median(a.cast)) : casts}${a.never ? ` · never ${a.never}` : ""}</span>
      <span>Commander removed or died</span><span class="num">${a.removed}</span>
      <span>Attacks declared</span><span class="num">${a.attacks}</span>
      <span>Combat damage to players</span><span class="num">${a.dealt}</span></div></button>`;
  }).join("");
  document.querySelectorAll(".deckbtn").forEach(b => b.addEventListener("click", () => { state.view = "deck"; state.deck = b.dataset.open; render(); }));
}

const items = (list, who) => list.map(([k, v, res]) => `<div class="it ${k}"><span class="k">${KIND[k] || k}</span><span class="v">${esc(v)}${who ? ` <span class="note">(${esc(who)}'s turn)</span>` : ""}${res ? `<span class="res">${esc(res)}</span>` : ""}</span></div>`).join("");

function boardHtml(b) {
  if (!b) return "";
  const cr = b.creatures || [];
  const power = cr.reduce((x, c) => x + Math.max(0, c.p) * (c.x || 1), 0);
  const count = cr.reduce((x, c) => x + (c.x || 1), 0);
  const fmt = c => `${c.cmd ? `<span class="cmdc">${esc(c.n)}</span>` : esc(c.n)}${c.x ? " ×" + c.x : ""} ${c.p}/${c.t}${c.tap ? " (tapped)" : ""}${c.att && c.att.length ? " + " + esc(c.att.join(", ")) : ""}`;
  const sorted = cr.slice().sort((a, b2) => (b2.cmd ? 1 : 0) - (a.cmd ? 1 : 0) || b2.p * (b2.x || 1) - a.p * (a.x || 1));
  const head = sorted.slice(0, 5).map(fmt), rest = sorted.slice(5).map(fmt);
  let h = `<div class="bd"><div class="sum">${count} creature${count === 1 ? "" : "s"} · ${power} power · ${b.lands} land${b.lands === 1 ? "" : "s"} · hand ${b.hand} · library ${b.lib}</div>`;
  if (head.length) h += `<div class="cr">${head.join(" · ")}</div>`;
  if (rest.length) h += `<details><summary>${rest.length} more creature${rest.length === 1 ? "" : "s"}</summary><div class="cr">${rest.join(" · ")}</div></details>`;
  const other = b.other || [];
  if (other.length) h += other.length > 6
    ? `<details><summary>Other permanents: ${other.length}</summary><div class="cr">${esc(other.join(", "))}</div></details>`
    : `<div class="cr note">${esc(other.join(", "))}</div>`;
  const cd = Object.entries(b.cmd_dmg || {});
  if (cd.length) h += `<div class="note ${cd.some(([, v]) => v >= 15) ? "dmgwarn" : ""}">Commander damage taken: ${esc(cd.map(([k, v]) => k.split(",")[0] + " " + v).join(", "))}</div>`;
  return h + "</div>";
}

const seatOf = (g, n) => Number(Object.keys(g.names).find(k => g.names[k] === n));
const resultOf = (g, s) => g.winner === s ? "won" : (g.out_at[s] != null ? "out at #" + g.out_at[s] : "lost");

// ---- the game list: tabs for a dozen games or fewer, else a filtered, paged list
function navView() {
  const nav = document.getElementById("tabs");
  const label = g => `Game ${g.game + 1}<small>${esc(g.winner != null ? g.names[g.winner] + " won" : "no winner")} · ${g.turns} turns</small>`;
  if (!BIG) {
    nav.innerHTML = DATA.games.map((g, i) => `<button class="tab" role="tab" data-i="${i}" aria-selected="${state.view === "game" && state.game === i}">${label(g)}</button>`).join("");
  } else {
    const q = state.filter.toLowerCase();
    const hits = DATA.games.map((g, i) => [g, i]).filter(([g]) =>
      (!state.winner || (state.winner === "-" ? g.winner == null : g.names[g.winner] === state.winner)) &&
      (!q || g.moments.some(m => m.text.toLowerCase().includes(q)) || String(g.game + 1) === q));
    const per = 24, pages = Math.max(1, Math.ceil(hits.length / per));
    state.page = Math.min(state.page, pages - 1);
    const shown = hits.slice(state.page * per, state.page * per + per);
    const winners = DATA.order.map(n => `<option value="${esc(n)}" ${state.winner === n ? "selected" : ""}>${esc(n)} won</option>`).join("");
    nav.innerHTML = `<div class="browser">
      <div class="filters"><label class="label" for="fp-q">Find games</label>
        <input id="fp-q" type="search" placeholder="A card, a deck, &quot;wipe&quot;, a game number" value="${esc(state.filter)}">
        <select id="fp-w" aria-label="Winner"><option value="">Any winner</option>${winners}<option value="-" ${state.winner === "-" ? "selected" : ""}>No winner</option></select>
        <span class="note">${hits.length} of ${DATA.games.length} games</span></div>
      <div class="glist">${shown.map(([g, i]) => `<button class="tab" data-i="${i}" aria-selected="${state.view === "game" && state.game === i}">${label(g)}</button>`).join("")}</div>
      ${pages > 1 ? `<div class="pager"><button id="fp-prev" ${state.page ? "" : "disabled"}>Previous</button><span class="note">Page ${state.page + 1} of ${pages}</span><button id="fp-next" ${state.page < pages - 1 ? "" : "disabled"}>Next</button></div>` : ""}</div>`;
    const qi = document.getElementById("fp-q");
    qi.addEventListener("change", () => { state.filter = qi.value; state.page = 0; navView(); });
    document.getElementById("fp-w").addEventListener("change", e => { state.winner = e.target.value; state.page = 0; navView(); });
    const pv = document.getElementById("fp-prev"), nx = document.getElementById("fp-next");
    if (pv) pv.addEventListener("click", () => { state.page--; navView(); });
    if (nx) nx.addEventListener("click", () => { state.page++; navView(); });
  }
  nav.querySelectorAll("[data-i]").forEach(b => b.addEventListener("click", () => { state.view = "game"; state.game = Number(b.dataset.i); render(); }));
}

function gameView(i) {
  const g = DATA.games[i];
  const seats = g.order && g.order.length ? g.order : Object.keys(g.names).map(Number).sort((a, b) => a - b);
  const W = g.winner != null ? g.names[g.winner] : null;
  const moments = g.moments.map(m => `<li class="${m.kind}" ${dd(g.names[m.seat])}><span class="when">#${m.t ?? "?"}</span><span class="tag">${TAG[m.kind]}</span><span>${esc(m.text)}</span></li>`).join("");
  document.getElementById("game").innerHTML = `<h2>Game ${g.game + 1}</h2>
    <div class="result">${W ? `<b ${dd(W)} style="color:var(--c)">${esc(W)} wins</b><span>${esc(g.how)}</span>` : `<b>No winner</b><span>stopped: ${esc(g.stop)}</span>`}
      <span class="pill">${g.turns} turns in all</span><span class="pill">seed ${esc(g.seed)}</span><span class="pill">turn order: ${seats.map(s => esc(g.names[s])).join(" → ")}</span></div>
    <div class="decks">${seats.map((s, k) => {
      const n = g.names[s], st = g.stats[s];
      return `<article class="deck" ${dd(n)}><h3>${esc(n)} ${pips(n)} <span class="pill ${g.winner === s ? "win" : "loss"}">${resultOf(g, s)}</span></h3><div class="kv">
        <span>Turn order</span><span class="num">${k + 1}${["st", "nd", "rd", "th"][Math.min(k, 3)]}</span>
        <span>Commander first cast</span><span class="num">${st.cmd_first != null ? "own turn " + st.cmd_first : (st.cmd_casts ? "off-turn" : "never")}</span>
        <span>Commander casts · removed</span><span class="num">${st.cmd_casts} · ${st.cmd_left}</span>
        <span>Spells cast</span><span class="num">${st.casts}</span>
        <span>Attacks · damage dealt</span><span class="num">${st.attacks} · ${st.dealt}</span></div>
        <div class="note">${esc(g.outcome[s].replace(/^has /, "").replace(/^\w/, c => c.toUpperCase()))}</div></article>`;
    }).join("")}</div>
    <section class="moments" aria-label="Key moments"><div class="label">Key moments</div><ol>${moments}</ol></section>`;
  const rounds = {};
  for (const r of g.rows) (rounds[r.own] ||= {own: {}, off: {}}).own[r.seat] = r;
  for (const r of g.rows) for (const [s, list] of Object.entries(r.off)) if (list.length) ((rounds[r.own].off[s] ||= [])).push([r.seat, list]);
  const body = Object.keys(rounds).map(Number).sort((a, b) => a - b).map(n => {
    const R = rounds[n];
    const tds = seats.map(s => {
      const name = g.names[s], o = R.own[s];
      let h = `<div class="cell" ${dd(name)}>`;
      if (o) {
        const b = o.board;
        const cmdOut = b ? (b.cmd || []).some(c => c.zone === "Battlefield") : null;
        h += `<div class="top"><span class="t">Turn ${n} <span class="note">· #${o.t}</span></span>${cmdOut == null ? "" : `<span class="cmd-chip ${cmdOut ? "on" : ""}">${cmdOut ? "Cmdr out" : "Cmdr not out"}</span>`}</div>`;
        if (o.plan || o.unused != null) h += `<div class="mana">${o.plan ? o.plan.budget + " mana" : ""}${o.unused != null ? " · " + o.unused + " unused" : ""}</div>`;
        h += o.items.length ? items(o.items) : `<div class="note">No plays</div>`;
        const dealt = Object.entries(o.dmg).map(([t, v]) => `${v} to ${g.names[t]}`).join(", ");
        if (dealt) h += `<div class="note">Combat damage: ${esc(dealt)}</div>`;
        if (o.plan && o.plan.left.length) h += `<div class="note">Plan left out: ${esc(o.plan.left.join(", "))}</div>`;
        h += boardHtml(b);
        const life = b ? b.life : o.life[s];
        if (life != null) h += `<div class="life"><span>${life} life</span><span class="bar"><i style="width:${Math.max(0, Math.min(100, life / 40 * 100))}%"></i></span></div>`;
      } else if (g.out_at[s] != null) {
        h += `<div class="dead">Out of the game</div>`;
      }
      const off = R.off[s];
      if (off) h += `<div class="off">${off.map(([a, list]) => items(list, g.names[a])).join("")}</div>`;
      return `<td>${h}</div></td>`;
    }).join("");
    return `<tr><td class="rnd">R${n}</td>${tds}</tr>`;
  }).join("");
  document.getElementById("board").innerHTML = `<table><thead><tr><th class="rnd">Round</th>${seats.map(s => `<th class="deckh" ${dd(g.names[s])}>${esc(g.names[s])} ${pips(g.names[s])}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
}

// ---- one deck across every game: by its own turn, then game by game
function deckView(n) {
  const games = DATA.games.filter(g => Object.values(g.names).includes(n));
  const turns = {};
  for (const g of games) {
    const s = seatOf(g, n);
    for (const r of g.rows) {
      if (r.seat !== s) continue;
      const T = turns[r.own] ||= {n: 0, mana: [], unused: [], cmd: 0, cmdKnown: 0, cr: [], pw: [], atk: 0, dmg: 0, life: [], cast: {}};
      T.n++;
      if (r.plan) T.mana.push(r.plan.budget);
      if (r.unused != null) T.unused.push(r.unused);
      if (r.board) {
        T.cmdKnown++; if ((r.board.cmd || []).some(c => c.zone === "Battlefield")) T.cmd++;
        const cr = r.board.creatures || [];
        T.cr.push(cr.reduce((x, c) => x + (c.x || 1), 0)); T.pw.push(cr.reduce((x, c) => x + Math.max(0, c.p) * (c.x || 1), 0));
        T.life.push(r.board.life);
      }
      if (r.items.some(it => it[0] === "attack")) T.atk++;
      T.dmg += Object.values(r.dmg).reduce((x, v) => x + v, 0);
      for (const it of r.items) if (it[0] === "cast") { const c = it[1].split(" → ")[0]; T.cast[c] = (T.cast[c] || 0) + 1; }
    }
  }
  const a = DATA.agg[n];
  document.getElementById("game").innerHTML = `<h2 ${dd(n)} style="color:var(--c)">${esc(n)} ${pips(n)} across ${games.length} game${games.length === 1 ? "" : "s"}</h2>
    <div class="result"><span class="pill">won ${a.wins} of ${a.games}</span><span class="pill">commander first cast: ${a.cast.length ? "median own turn " + fmt1(median(a.cast)) : "never"}${a.never ? `, never in ${a.never}` : ""}</span>
    <span class="pill">commander removed or died ${a.removed}×</span><button class="linkbtn" id="fp-back">Back to the games</button></div>
    <p class="note">By its own turn: in how many games it got that turn, then medians (mana, creatures, power, life) or shares (commander out, attacked) across them. Combat damage is the average per game. Most cast: that turn's spells, counted across games.</p>`;
  const rows = Object.keys(turns).map(Number).sort((x, y) => x - y).map(t => {
    const T = turns[t];
    const top = Object.entries(T.cast).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([c, k]) => esc(c) + (k > 1 ? ` ×${k}` : "")).join(", ");
    return `<tr><td class="rnd">T${t}</td><td class="num">${T.n}</td><td class="num">${fmt1(median(T.mana))}</td><td class="num">${fmt1(median(T.unused))}</td>
      <td class="num">${pct(T.cmd, T.cmdKnown)}</td><td class="num">${fmt1(median(T.cr))}</td><td class="num">${fmt1(median(T.pw))}</td><td class="num">${pct(T.atk, T.n)}</td>
      <td class="num">${fmt1(T.dmg / T.n)}</td><td class="num">${fmt1(median(T.life))}</td><td>${top || "–"}</td></tr>`;
  }).join("");
  const glist = games.map(g => {
    const s = seatOf(g, n), st = g.stats[s], k = (g.order || []).indexOf(s);
    const mine = g.moments.filter(m => m.seat === s || m.text.includes(n)).map(m => `<span class="mm ${m.kind}">#${m.t} ${esc(m.text)}</span>`).join("");
    return `<tr ${dd(n)}><td><button class="linkbtn" data-i="${DATA.games.indexOf(g)}">Game ${g.game + 1}</button></td>
      <td><span class="pill ${g.winner === s ? "win" : "loss"}">${resultOf(g, s)}</span></td><td class="num">${k >= 0 ? k + 1 : "–"}</td><td class="num">${g.turns}</td>
      <td class="num">${st.cmd_first != null ? "T" + st.cmd_first : (st.cmd_casts ? "off-turn" : "never")}</td><td class="num">${st.cmd_left}</td><td class="num">${st.attacks} · ${st.dealt}</td>
      <td class="mms">${mine}</td></tr>`;
  }).join("");
  document.getElementById("board").innerHTML = `<table class="dv"><thead><tr><th class="rnd">Turn</th><th>Games</th><th>Mana</th><th>Unused</th><th>Cmdr out</th><th>Creatures</th><th>Power</th><th>Attacked</th><th>Combat dmg</th><th>Life</th><th class="wide">Most cast</th></tr></thead><tbody>${rows}</tbody></table>
    <table class="dv"><thead><tr><th>Game</th><th>Result</th><th>Turn order</th><th>Turns</th><th>Cmdr cast</th><th>Removed</th><th>Attacks · dmg</th><th class="wide2">Its key moments</th></tr></thead><tbody>${glist}</tbody></table>`;
  document.getElementById("fp-back").addEventListener("click", () => { state.view = "game"; render(); });
  document.getElementById("board").querySelectorAll("[data-i]").forEach(b => b.addEventListener("click", () => { state.view = "game"; state.game = Number(b.dataset.i); render(); }));
}

function render() {
  aggView(); navView();
  document.getElementById("legend").hidden = state.view !== "game";
  if (state.view === "deck" && DATA.agg[state.deck]) deckView(state.deck); else { state.view = "game"; if (DATA.games.length) gameView(state.game); }
  save();
}

(function init() {
  try {
    const v = JSON.parse(localStorage.getItem("fp-view") || "null");
    if (v) { state.view = v.view; state.deck = v.deck; if (v.game >= 0 && v.game < DATA.games.length) state.game = v.game; }
  } catch (e) {}
  render();
})();
</script>
"""
