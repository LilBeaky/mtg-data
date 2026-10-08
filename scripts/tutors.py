#!/usr/bin/env python3
"""
tutors.py — how well a deck can find its cards. Works on any decklist.

Reads every tutor in the list (spells, ETBs, attack/dies/upkeep triggers, activated
abilities, typecycling and landcycling, transmute, commander abilities), builds a
"this card can fetch that card" graph, and reports what that access is worth.

  python3 scripts/tutors.py DECK [options]           (run from the repo root)

  --commander NAME    if the list has no Commander section
  --draw              odds on the draw (default: on the play)
  --turns 4,6         turns for the odds tables (default 4,6)
  --no-lists          shorter output: counts instead of card lists
  --trials N          games sampled for multi-card packages (default 40000)

REPORT
  1 Tutors        every tutor effect: how it's used, repeatable or not, where the card
                  lands, what it can find here, and anything read approximately
  2 Chains        tutors that find tutors (Step Through -> Spellseeker -> Cyclonic Rift)
  3 Coverage      how many ways each card can be reached; cards no tutor can find
  4 Dependencies  what loses all tutor access if a card is gone (the commander first)
  5 Key cards     yours ('# key:' / '# package:' lines) and inferred beyond them, with reasons;
                  access odds for both: drawn, or a card that leads to them, by each turn, then
                  with the commander's own tutoring added once it's out (manasim.py games);
                  "plays like N copies"
  6 Packages      Spellbook combos (<= 3 cards) and '# package:' lines, with chains
  7 Tutor worth   each tutor taken out: points of access lost on the key cards and on the
                  whole deck, and the cards only it reaches

Key cards: your header lines are always used; inference runs alongside and adds cards beyond
them (win conditions, payoffs for a mechanic the deck is full of, typal packages, draw engines,
EDHREC synergy for this commander, cards the deck's narrow tutors converge on, Spellbook combo
pieces). With no header lines, inference alone. --no-infer turns it off.
All odds ignore mana and the turns a chain takes: they say "can you get there",
not "how fast". goldfish.py is the mana-aware check. Full docs: USE_INSTRUCTIONS.md §6.
"""
import argparse, glob, json, os, random, re, sys
from collections import Counter, deque

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import mtg
import stats_math as sm

CARD_TYPES = {"artifact", "creature", "enchantment", "instant", "sorcery", "land",
              "planeswalker", "battle", "kindred", "tribal"}
NO_ACCESS = {"graveyard", "exile (no access)"}          # the card doesn't become usable
PERMANENT_TYPES = {"artifact", "creature", "enchantment", "land", "planeswalker", "battle"}
SUPERTYPES = {"basic", "legendary", "snow"}
COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
NUMBER = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9, "ten": 10}

SEARCH_RX = re.compile(
    r"(?:search(?:es)? your library|(?<=each of them )searches their library|(?<=target player )searches their library)"
    r"(?: and(?:/or)? (?:your )?graveyard)?(?: and/or graveyard)? for "
    r"(?P<what>.+?)(?=, (?:put|reveal|then|and|exile|shuffle|where)\b| and put | and reveal | and exile |\. |\.$|\)|$)", re.I)
DEST_RX = [("battlefield", re.compile(r"onto the battlefield", re.I)),
           ("hand", re.compile(r"into (?:your|its owner's) hand|put (?:that card|it|them|those cards) in your hand", re.I)),
           ("graveyard", re.compile(r"into your graveyard", re.I)),
           ("top", re.compile(r"on top(?: of your library)?|(?:second|third|fourth) from the top", re.I)),
           ("exile", re.compile(r"\bexile (?:it|them|that card|those cards)\b", re.I))]
FLICKER_RX = re.compile(
    r"exile (?:up to (?:one|two|x) )?(?:another )?(?:other )?target (?:nontoken )?(?P<what>creature|artifact|enchantment|"
    r"nonland permanent|permanent)s?[^.]*?(?:\.\s*if you do,|,? then| and) return (?:that card|it|them|the exiled card|those cards)"
    r"[^.]*?to the battlefield", re.I)


# ------------------------------------------------------------------ card facts
def front(c):
    return (c.get("card_faces") or [c])[0]

def type_parts(c):
    tl = front(c).get("type_line") or c.get("type_line") or ""
    left, _, right = tl.partition("—")
    words = left.lower().split()
    return ({w for w in words if w in SUPERTYPES}, {w for w in words if w in CARD_TYPES},
            {s.lower() for s in right.split()})

def pt(c, key):
    v = front(c).get(key, c.get(key))
    try: return int(v)
    except (TypeError, ValueError): return 0          # '*' is 0 in the library

def has_mana_ability(c):
    return bool(re.search(r"\badd \{|add one mana|add (?:two|three|x) mana", mtg.text_of(c), re.I))


# ------------------------------------------------------------------ target filter
class Target:
    """What one search can find. `approx` lists clauses read loosely (never silently)."""
    def __init__(self):
        self.any = False; self.types = set(); self.non = set(); self.supers = set(); self.subs = set(); self.non_subs = set()
        self.colors = set(); self.colorless = False; self.multicolored = False
        self.mv = None; self.power = None; self.tough = None; self.named = None; self.not_named = set()
        self.mana_ability = False; self.permanent = False; self.historic = False; self.flash = False
        self.count = 1; self.approx = []; self.alts = []

    def broad(self):
        """Finds (nearly) anything: any card, or any nonland card with no other limit."""
        if self.alts: return any(a.broad() for a in self.alts)
        if self.any: return True
        return (self.non <= {"land"} and not (self.types or self.supers or self.subs or self.colors or self.colorless
                or self.multicolored or self.permanent or self.historic or self.mv or self.power or self.tough
                or self.mana_ability or self.flash or self.named))

    def matches(self, c):
        if self.alts: return any(a.matches(c) for a in self.alts)
        if self.named: return c["name"].lower() == self.named
        if c["name"].lower() in self.not_named: return False
        sup, typ, sub = type_parts(c)
        if self.any: return True
        if self.types and not (typ & self.types): return False
        if self.permanent and not (typ & PERMANENT_TYPES): return False
        if self.non & typ: return False
        if self.supers and not self.supers <= sup: return False
        if self.subs and not (sub & self.subs): return False
        if self.non_subs & sub: return False
        if self.historic and not ({"artifact"} & typ or "legendary" in sup or "saga" in sub): return False
        cols = set(front(c).get("colors") or c.get("colors") or [])
        if self.colors and not self.colors <= cols: return False
        if self.colorless and cols: return False
        if self.multicolored and len(cols) < 2: return False
        if self.mv:
            op, v = self.mv; m = int(c.get("cmc", 0))
            if (op == "<=" and m > v) or (op == ">=" and m < v) or (op == "==" and m != v): return False
        for key, lim in (("power", self.power), ("toughness", self.tough)):
            if lim:
                op, v = lim; x = pt(c, key)
                if (op == "<=" and x > v) or (op == ">=" and x < v): return False
        if self.mana_ability and not has_mana_ability(c): return False
        if self.flash and "flash" not in [k.lower() for k in (c.get("keywords") or [])]: return False
        return True

    def describe(self):
        if self.alts: return " or ".join(a.describe() for a in self.alts)
        if self.named: return f"cards named {self.named.title()}"
        if self.any: bits = ["any card"]
        else:
            bits = []
            if self.supers: bits.append(" ".join(sorted(self.supers)))
            if self.colors: bits.append("/".join(sorted(self.colors)))
            if self.colorless: bits.append("colorless")
            if self.non: bits.append(" ".join("non" + t for t in sorted(self.non)))
            if self.non_subs: bits.append(" ".join("non-" + t.title() for t in sorted(self.non_subs)))
            if self.subs: bits.append("/".join(s.title() for s in sorted(self.subs)))
            if self.types: bits.append("/".join(sorted(self.types)))
            if self.permanent: bits.append("permanent")
            if self.historic: bits.append("historic")
            if not bits: bits.append("card")
        if self.mv: bits.append(f"MV{self.mv[0].replace('==', '=')}{self.mv[1]}")
        if self.power: bits.append(f"power{self.power[0]}{self.power[1]}")
        if self.tough: bits.append(f"toughness{self.tough[0]}{self.tough[1]}")
        if self.mana_ability: bits.append("with a mana ability")
        if self.flash: bits.append("with flash")
        if self.not_named: bits.append("not named " + "/".join(n.title() for n in self.not_named))
        return " ".join(bits)


def parse_target(what, self_card):
    """'an enchantment card with mana value 3 or less' -> Target."""
    raw = what.strip()
    low = raw.lower()
    t = Target()
    if low.startswith("any number of "):
        t.count = 99; low = low[len("any number of "):]; raw = raw[len("any number of "):]
    m = re.match(r"(up to )?(x|\d+|a|an|one|two|three|four|five|six|seven)\b ?", low)
    if m:
        w = m.group(2)
        t.count = NUMBER.get(w, int(w) if w.isdigit() else 1)
        if w == "x": t.approx.append("X cards")
    # alternatives: "... card or a basic land card"
    parts = re.split(r" or (?=an? [^,]*?\bcards?\b)", raw)        # "X card ... or a Y card"
    if len(parts) > 1:
        t.alts = [parse_target(p, self_card) for p in parts]
        for a in t.alts: t.approx += a.approx
        return t
    m = re.search(r"cards? named (.+?)(?:,| and |$)", low)
    if m and not re.search(r"not named", low):
        t.named = m.group(1).strip().rstrip(".").lower()
        return t
    for mm in re.finditer(r"not named ([^,]+?)(?= that| with|,|$)", low):
        t.not_named.add(mm.group(1).strip().lower())
    rest = low
    def cut(rx):
        nonlocal rest
        mm = re.search(rx, rest)
        if mm: rest = rest[:mm.start()] + " " + rest[mm.end():]
        return mm
    if cut(r"with the same mana value as (?:this card|~|it)"):
        t.mv = ("==", int(self_card.get("cmc", 0)))
    elif (mm := cut(r"with (?:a )?mana value (\d+) or (less|greater)")):
        t.mv = ("<=" if mm.group(2) == "less" else ">=", int(mm.group(1)))
    elif (mm := cut(r"with (?:a )?mana value (\d+)\b")):
        t.mv = ("==", int(mm.group(1)))
    elif (mm := cut(r"(?:with|that each have|each with) (?:a )?mana value (x|equal to|less than|greater than)[^,]*")):
        t.approx.append("mana value " + mm.group(0).split("value", 1)[1].strip())
    for key in ("power", "toughness"):
        mm = cut(rf"with {key} (\d+) or (less|greater)")
        if mm:
            lim = ("<=" if mm.group(2) == "less" else ">=", int(mm.group(1)))
            if key == "power": t.power = lim
            else: t.tough = lim
        elif (mm := cut(rf"with {key} [^,]*")):
            t.approx.append(mm.group(0).strip())
    if cut(r"with a mana ability"): t.mana_ability = True
    if cut(r"with flash"): t.flash = True
    cut(r"(?:that each have|with) different names")
    for rx, note in ((r"that shares? a (?:creature|card) type[^,]*", "shares a type (read as any)"),
                     (r"with the same name as [^,]*", "same name as a card in play (read as any)"),
                     (r"not named [^,]+?(?= that| with|,|$)", None),
                     (r"from among [^,]*", "restricted pool (read as any)")):
        mm = cut(rx)
        if mm and note: t.approx.append(note)
    # words before "card(s)" carry types/subtypes/colors; keep original case for subtypes
    head = re.split(r"\bcards?\b", rest, maxsplit=1)[0]
    orig_head = raw[:len(raw)]
    words = re.findall(r"[a-z\-']+", head)
    orig_words = {w.lower(): w for w in re.findall(r"[A-Za-z\-']+", raw)}
    known = set()
    for w in words:
        if w in ("up", "to", "a", "an", "or", "and", "one", "two", "three", "four", "five", "x", "each", "that", "have"):
            continue
        if w.startswith("non") and w[3:].strip("-") in CARD_TYPES:
            t.non.add(w[3:].strip("-")); continue
        if w.startswith("non-"):                            # non-Human, non-Dragon: a subtype exclusion
            t.non_subs.add(w[4:]); continue
        if w in CARD_TYPES: t.types.add("kindred" if w == "tribal" else w); continue
        if w in SUPERTYPES: t.supers.add(w); continue
        if w in COLOR_WORDS: t.colors.add(COLOR_WORDS[w]); continue
        if w == "colorless": t.colorless = True; continue
        if w in ("multicolored",): t.multicolored = True; continue
        if w == "permanent": t.permanent = True; continue
        if w == "historic": t.historic = True; continue
        o = orig_words.get(w, w)
        if o[:1].isupper(): t.subs.add(w); continue          # Wizard, Equipment, Aura, Forest...
        t.approx.append(f"unread word '{w}'")
    if re.search(r"\bwith (?!mana value|power|toughness|a mana ability|flash|different|the same)\w+", rest):
        t.approx.append("unread 'with ...' condition: " + re.search(r"\bwith [^,]*", rest).group(0).strip())
    if not (t.types or t.non or t.supers or t.subs or t.colors or t.colorless or t.multicolored
            or t.permanent or t.historic or t.mv or t.power or t.tough or t.mana_ability or t.flash):
        t.any = True
    return t


# ------------------------------------------------------------------ tutor effects
class Tutor:
    def __init__(self, card, face, kind, target, dest, repeatable, condition, text):
        self.card, self.face, self.kind, self.target, self.dest = card, face, kind, target, dest
        self.repeatable, self.condition, self.text = repeatable, condition, text
        self.rebuy = []                                  # flicker engines that can re-buy an ETB tutor

    @property
    def name(self): return self.card["name"]

    def usable_from(self, arrived):
        """Can this tutor still be used if its card was fetched to `arrived`?"""
        if arrived in ("graveyard", "exile (no access)", None): return False
        hand_only = self.kind in ("cycling", "transmute", "spell")
        if arrived == "battlefield": return not hand_only
        return True                                       # hand / top / exile (castable)

    def label(self):
        rep = "repeatable" if self.repeatable else "one-shot"
        if self.rebuy: rep += ", re-buyable via " + "; ".join(self.rebuy)
        return f"{self.kind}{' (' + self.condition + ')' if self.condition else ''}, {rep}"


def _names(c):
    n = c["name"]
    out = {n.lower(), n.split(",")[0].lower(), n.split(" // ")[0].lower()}
    return {x for x in out if x}

def classify(line, prev, c, is_spell):
    """(kind, repeatable, condition) for the ability line holding a search."""
    L = line.strip(); low = L.lower()
    if L.startswith("•") and prev: return classify(prev, None, c, is_spell)
    nm = "|".join(re.escape(x) for x in _names(c)) + r"|~|this creature|this permanent|this artifact|this enchantment|this land|it"
    ml = re.match(r"([+−\-]?\d+|[+−\-]x):\s", L, re.I)
    if ml:
        emblem = "emblem" in low
        return "loyalty", not emblem or True, f"loyalty {ml.group(1)}" + (" (emblem; only after this ultimate)" if emblem else "")
    mcyc = re.match(r"(\w[\w ]*?)cycling \{", L, re.I)
    if mcyc: return "cycling", False, f"{mcyc.group(1).strip().lower()}cycling"
    if re.match(r"transmute \{", low): return "transmute", False, "transmute, sorcery speed"
    if re.search(rf"whenever (?:{nm}) attacks", low): return "trigger", True, "when it attacks"
    if re.search(rf"when(?:ever)? (?:{nm}) (?:enters|is turned face up)", low): return "etb", False, "enters"
    if re.search(rf"when(?:ever)? (?:{nm}) dies", low): return "trigger", False, "when it dies"
    if re.match(r"at the beginning of", low):
        return "trigger", True, re.match(r"(at the beginning of [^,]*)", low).group(1)
    if re.match(r"whenever", low):
        return "trigger", True, re.match(r"(whenever [^,]*)", low).group(1)
    ma = re.match(r"([^\"]*?):\s", L)
    if ma and not re.match(r"(when|whenever|at the|as an additional cost)", low) and \
            re.search(r"\{|sacrifice|discard|pay|remove|exile|tap", ma.group(1), re.I):
        cost = ma.group(1)
        one = re.search(rf"sacrifice (?:{nm})\b", cost, re.I) or re.search(r"exile (?:this|~)", cost, re.I)
        return "activated", not one, cost.strip()
    return ("spell", False, "") if is_spell else ("other", False, "")

def card_tutors(c):
    """Every search-your-library effect on a card (all faces, reminder text included)."""
    out = []
    faces = c.get("card_faces") or [c]
    for fi, f in enumerate(faces):
        text = f.get("oracle_text") or ""
        types = (f.get("type_line") or c.get("type_line") or "").lower()
        is_spell = "instant" in types or "sorcery" in types
        prev = None
        for line in text.split("\n"):
            for m in SEARCH_RX.finditer(line):
                self_target = m.group(0).lower().startswith("searches their")
                if not self_target and re.search(r"(their|target player's|that player's|an opponent's) library",
                                                 line[max(0, m.start() - 30):m.start() + 25], re.I):
                    continue
                kind, rep, cond = classify(line, prev, c, is_spell)
                if rep and re.search(r"an opponent gains control of (?:this|~|it)", line, re.I):
                    rep, cond = False, (cond + "; an opponent gains control after" if cond else "an opponent gains control after")
                after = line[m.end():m.end() + 220]
                dest, first = "hand", 10**9
                for d, rx in DEST_RX:
                    mm = rx.search(after)
                    if mm and mm.start() < first: dest, first = d, mm.start()
                if kind == "spell" and re.search(r"\bthen shuffle and put that card on top\b", after, re.I): dest = "top"
                if dest == "exile" and not re.search(r"\b(?:cast|play)\b[^.]*\b(?:exiled|that card|those cards|it|them)|put the exiled card into your hand|may cast spells? from among", text, re.I):
                    dest = "exile (no access)"
                tgt = parse_target(m.group("what"), c)
                if re.search(r"opponent chooses|target opponent chooses", line, re.I): tgt.approx.append("opponent picks which card you get")
                if self_target: tgt.approx.append("you must target yourself (the other player also tutors)")
                out.append(Tutor(c, fi, kind, tgt, dest, rep, cond, line.strip()))
            if not line.strip().startswith("•"): prev = line
    return out

def flicker_engines(cards):
    """Cards that exile-and-return (re-running ETBs): [(name, what, repeatable)]."""
    out = []
    for c in cards:
        m = FLICKER_RX.search(mtg.text_of(c))
        if m:
            _, typ, _ = type_parts(c)
            out.append((c["name"], m.group("what").lower(), not ({"instant", "sorcery"} & typ)))
    return out


# ------------------------------------------------------------------ deck + graph
class Deck:
    def __init__(self, path, commander_override=None):
        entries = mtg.parse_deck(path)
        self.meta = mtg.parse_deck_meta(path)
        self.N, cmd_names, _ = sm.count_population(path, commander_override)
        self.cmdrs = [c for c in (mtg.find(n)[0] for n in cmd_names) if c]
        self.qty, self.card, missing = {}, {}, []
        for s, q, n in entries:
            if s in sm.EXCLUDED_FROM_POPULATION: continue
            c, how = mtg.find(n)
            if not c: missing.append(n); continue
            self.qty[c["name"]] = self.qty.get(c["name"], 0) + q
            self.card[c["name"]] = c
        self.missing = missing
        if missing: print("⚠ NOT FOUND, left out of the analysis (fix the names or add them to data/aliases.txt): " + "; ".join(missing))
        for c in self.cmdrs: self.card[c["name"]] = c
        self.cmd_names = {c["name"] for c in self.cmdrs}
        self.lib_names = set(self.qty)
        self.engines = flicker_engines([self.card[n] for n in self.lib_names | self.cmd_names])
        self.tutors = {}
        for n in sorted(self.lib_names | self.cmd_names):
            ts = card_tutors(self.card[n])
            for t in ts:
                if t.kind == "etb":
                    _, typ, _ = type_parts(self.card[n])
                    t.rebuy = [e for e, what, rep in self.engines if e != n and rep and (
                        what in typ or what == "permanent" or (what == "nonland permanent" and "land" not in typ))]
            if ts: self.tutors[n] = ts
        # edges: source -> target, with the tutor effect used
        self.edges = {}
        for s, ts in self.tutors.items():
            for t in ts:
                for x in self.lib_names:
                    if x == s and self.qty.get(x, 0) < 2: continue
                    if t.target.matches(self.card[x]):
                        self.edges.setdefault(s, {}).setdefault(x, []).append(t)
        self.is_land = {n: "land" in type_parts(self.card[n])[1] for n in self.card}
        self.basic = {n: "basic" in type_parts(self.card[n])[0] for n in self.card}

    def land_only(self, t):
        tg = [x for x in self.lib_names if t.target.matches(self.card[x]) and x != t.name]
        return bool(tg) and all(self.is_land[x] for x in tg)

    def reach(self, target, banned=frozenset(), specific=False):
        """{source: shortest path [source, ..., target]} for every card (library or command
        zone) that can get `target` into hand/play/top/exile. A fetched tutor keeps the chain
        going only if it arrives where its own tutor works (Entomb ends a chain; a card put
        onto the battlefield can't be cycled). Solved to a fixpoint, so a longer valid route
        is found even when the shortest route is blocked."""
        valid = {target: None}                   # node -> set of its effects that continue a path
        path = {target: [target]}
        changed = True
        while changed:
            changed = False
            for s, outs in self.edges.items():
                if s == target or s in banned: continue
                for u, ts in outs.items():
                    if u not in valid: continue
                    for t in ts:
                        if specific and t.target.broad(): continue
                        if u == target: good = t.dest not in NO_ACCESS
                        else: good = t.dest not in NO_ACCESS and any(t2.usable_from(t.dest) for t2 in valid[u])
                        if not good: continue
                        if s not in valid: valid[s] = set(); changed = True
                        if t not in valid[s]: valid[s].add(t); changed = True
                        cand = [s] + path[u]
                        if s not in path or len(cand) < len(path[s]): path[s] = cand; changed = True
        return {k: v for k, v in path.items() if k != target}


def path_str(p):
    return " → ".join(p)


# ------------------------------------------------------------------ odds
def access_odds(deck, name, T, on_play, banned=frozenset(), specific=False):
    """P(by turn T you've seen `name` or a library card with a tutor path to it). Exact
    hypergeometric; a commander path counts as always available (returned separately)."""
    r = deck.reach(name, banned, specific)
    via_cmd = any(s in deck.cmd_names for s in r)
    K = deck.qty.get(name, 0) + sum(deck.qty.get(s, 0) for s in r if s in deck.lib_names)
    return sm.hyper_at_least(deck.N, K, sm.cards_seen(T, on_play), 1), via_cmd, K

def package_odds_chains(deck, pieces, T, on_play, trials, seed=11, use_cmd=True, specific=False):
    """pieces: [set of member names]. Monte Carlo: every piece is drawn, or gets a distinct
    starting card with a tutor path to one of its members (repeatable sources cover several).
    Returns (natural, with_chains)."""
    lib = []
    for n, q in deck.qty.items(): lib += [n] * q
    pad = deck.N - len(lib)
    lib += [None] * max(0, pad)
    n = min(sm.cards_seen(T, on_play), len(lib))
    starts = []                                      # per piece: {source: repeatable?}
    for mem in pieces:
        srcs = {}
        for m in mem:
            for s, path in deck.reach(m, specific=specific).items():
                first = [t for t in deck.edges[s][path[1]] if not (specific and t.target.broad())]
                rep = any(t.repeatable for t in first)
                srcs[s] = srcs.get(s, False) or rep
        starts.append(srcs)
    rng = random.Random(seed)
    nat = ok = 0
    for _ in range(trials):
        seen = set(x for x in rng.sample(lib, n) if x)
        missing = [i for i, mem in enumerate(pieces) if not (mem & seen) and not (mem & deck.cmd_names)]
        if not missing: nat += 1; ok += 1; continue
        avail = seen | (deck.cmd_names if use_cmd else set())
        # bipartite matching: missing pieces -> source units (repeatable sources get one unit per piece)
        match = {}
        def aug(i, visited):
            for s, rep in starts[i].items():
                if s not in avail: continue
                units = [(s, j) for j in range(len(missing))] if rep else [(s, 0)]
                for u in units:
                    if u in visited: continue
                    visited.add(u)
                    if u not in match or aug(match[u], visited):
                        match[u] = i; return True
            return False
        if all(aug(i, set()) for i in missing): ok += 1
    return nat / trials, ok / trials


# ------------------------------------------------------------------ key cards: inferred alongside yours
INFER_MIN, INFER_MAX = 2.0, 10                   # score to count as a key card; most inferred cards shown
ENGINE_TAGS = {"draw-engine": "draw engine", "repeatable-pure-draw": "draw engine",
               "repeatable-token-generator": "token engine", "repeatable-treasure": "mana engine"}
_TAGS = {}

def _tags_by_oid():
    """{oracle_id: set of Scryfall oracle-tag slugs} from the newest tag file (one pass, cached)."""
    if _TAGS: return _TAGS
    for f in sorted(glob.glob(os.path.join(mtg.DATA_DIR, "oracle-tags-*.jsonl")))[-1:]:
        for line in open(f, encoding="utf-8"):
            t = json.loads(line)
            for x in t.get("taggings", []):
                _TAGS.setdefault(x.get("oracle_id"), set()).add(t["slug"])
    return _TAGS

def snapshot_rows(cmdrs, bracket=None):
    """Rows of the newest EDHREC snapshot for this commander (snapshots/), the bracket's variant first; [] if none."""
    try:
        import explorer, edhrec_diff
    except Exception: return []
    if not cmdrs: return []
    slugs = {"-".join(explorer.slug(c["name"]) for c in cmdrs)}
    if len(cmdrs) == 2: slugs.add("-".join(explorer.slug(c["name"]) for c in reversed(cmdrs)))
    found = []
    for f in glob.glob(os.path.join(os.path.dirname(ROOT), "snapshots", "*.txt")):
        parts = os.path.basename(f)[:-4].split("__")
        if len(parts) == 3 and parts[0] in slugs: found.append((parts[1], parts[2], f))
    if not found: return []
    want = getattr(mtg, "BRACKET_VARIANT", {}).get(bracket)
    for pick in ([v for v in found if v[0] == want], [v for v in found if v[0] == "all"], found):
        if pick: return edhrec_diff.parse_snapshot(max(pick, key=lambda v: v[1])[2])[1]
    return []

def infer_keys(d):
    """{card: (score, [reasons])} for every library card with any signal that it's a key card. Signals:
    wins the game (oracle tag), payoff for a mechanic or creature type the deck is full of (8+ cards), typal
    package, repeatable engine, EDHREC synergy >= 30% for this commander, narrow tutors converging on it
    (each specific tutor spreads 1 over its nonland targets, repeatable counts double), a Spellbook combo piece
    that isn't just the tutor in 'tutor + target'. key_cards() keeps the ones scoring INFER_MIN or more."""
    tg = _tags_by_oid()
    cards = {n: d.card[n] for n in d.lib_names if not d.is_land[n]}
    kw, sub = Counter(), Counter()
    for c in cards.values():
        for k in c.get("keywords") or []:
            k = k.lower(); kw[k] += 1
            if k.endswith("cycling") and k != "cycling": kw["cycling"] += 1
        for t in type_parts(c)[2]: sub[t] += 1
    syn = {mtg.norm(r["name"]): r["syn"] for r in snapshot_rows(d.cmdrs, d.meta.get("bracket"))}
    ntarg = {}
    for src, ts in d.tutors.items():
        for t in ts: ntarg[id(t)] = sum(1 for x in cards if t.target.matches(d.card[x]))
    conv = Counter()
    for src, outs in d.edges.items():
        for x, ts in outs.items():
            if x not in cards: continue
            for t in ts:
                if t.target.broad() or t.dest in NO_ACCESS or not ntarg.get(id(t)): continue
                conv[x] += (2 if t.repeatable else 1) / ntarg[id(t)]
    combo = set()
    try:
        _, dc = mtg.deck_combos(sorted(d.lib_names | d.cmd_names))
        for v in dc or []:
            if len(v["cards"]) <= 3:
                tutors_in = {x for x in v["cards"] if x in d.tutors and not all(d.land_only(t) for t in d.tutors[x])}
                combo |= set(v["cards"]) - tutors_in
    except Exception: pass
    out = {}
    for n, c in cards.items():
        r, w = [], 0.0
        tags = tg.get(c.get("oracle_id"), set())
        if "alternate-win-condition" in tags: r.append("wins the game"); w += 3
        for t in sorted(tags):
            m = re.match(r"(?:synergy|payoff)-(.+)$", t) or re.match(r"(.+)-matters$", t)
            if m:
                k = m.group(1).replace("-", " ")
                cnt = kw.get(k, 0) or sub.get(k, 0)
                if cnt >= 8: r.append(f"payoff for {k} ({cnt} cards)"); w += 2
            m = re.match(r"typal-(.+)$", t)
            if m and sub.get(m.group(1), 0) >= 8: r.append(f"{m.group(1)} package ({sub[m.group(1)]} cards)"); w += 1.5
        for e in sorted({ENGINE_TAGS[t] for t in tags if t in ENGINE_TAGS}): r.append(e); w += 1
        sy = syn.get(mtg.norm(n))
        if sy is not None and sy >= 30: r.append(f"EDHREC synergy {sy:g}%"); w += 1
        if n in combo: r.append("Spellbook combo piece"); w += 2
        if conv[n] >= 0.25: r.append(f"narrow tutors converge on it ({conv[n]:.2f})"); w += 1 + min(conv[n], 1.0)
        if w > 0: out[n] = (w, r)
    return out

def key_cards(d, infer=True):
    """(yours, inferred, scores, bad): yours from '# key:' and '# package:' lines (library cards); inferred = the
    best INFER_MAX library cards scoring INFER_MIN or more that aren't already yours; scores = infer_keys(d)."""
    yours, bad = [], []
    for v in (d.meta.get("key") or "").replace(" + ", ";").split(";"):
        if not v.strip(): continue
        c = mtg.find(v.strip())[0]
        if c and c["name"] in d.lib_names: yours.append(c["name"])
        elif c and c["name"] in d.cmd_names: bad.append(f"{v.strip()} (it's the commander)")
        else: bad.append(v.strip())
    pk_specs = [sm.parse_package(v) for v in (d.meta.get("package") or [])]
    trees = None
    if any(p.lower().startswith("tag:") for _, parts in pk_specs for p in parts):
        trees = mtg.load_tags_multi(sorted({p[4:].strip() for _, parts in pk_specs for p in parts if p.lower().startswith("tag:")}))
    for label, parts in pk_specs:
        for m in [sm._part_members(p, d.lib_names | d.cmd_names, trees) for p in parts]:
            for x in sorted(m):
                if x in d.lib_names and x not in yours: yours.append(x)
    scores = infer_keys(d) if infer else {}
    ranked = sorted((x for x in scores if scores[x][0] >= INFER_MIN and x not in yours), key=lambda x: (-scores[x][0], x))
    return yours, ranked[:INFER_MAX], scores, bad

def cmd_timing(path, commander, on_play, turns, trials=2000):
    """{commander name: {T: P(out on the battlefield by T)}} from manasim.py games (ramp and reducers played),
    or {} when that isn't available."""
    try:
        import io, contextlib, manasim
        with contextlib.redirect_stdout(io.StringIO()):
            r = manasim.simulate(path, commander, on_play, trials, max(turns) + 1, 1)
        return {n: t["by"] for n, t in r["targets"].items() if t["zone"] == "cmd"}
    except Exception:
        return {}

def cmd_fire_delay(t, card):
    """Turns between the commander landing and its tutor first working: an attack trigger or a {T} ability waits a
    turn (summoning sickness) unless it has haste; a cast/ETB trigger or another ability works the same turn."""
    haste = "haste" in [k.lower() for k in card.get("keywords") or []]
    if haste: return 0
    cond = (t.condition or "").lower()
    if t.kind == "trigger" and "attack" in cond: return 1
    if t.kind == "activated" and "{t}" in cond: return 1
    return 0

def cmd_access(d, x, T, timing, reach):
    """P(by T a commander that can tutor x has been out long enough to use it); commanders with paths to x only."""
    best = 0.0
    for cname in d.cmd_names:
        if cname not in reach or cname not in timing: continue
        first = [t for t in d.edges[cname][reach[cname][1]]]
        delay = min(cmd_fire_delay(t, d.card[cname]) for t in first)
        best = max(best, timing[cname].get(T - delay, 0.0) if T - delay >= 1 else 0.0)
    return best

def copies_equiv(N, n, p):
    """The number of copies K for which P(at least one in n cards) = p: 'plays like about K copies'."""
    if p <= 0: return 0.0
    for K in range(1, N + 1):
        if sm.hyper_at_least(N, K, n, 1) >= p:
            lo = sm.hyper_at_least(N, K - 1, n, 1) if K > 1 else 0.0
            hi = sm.hyper_at_least(N, K, n, 1)
            return K - 1 + (p - lo) / (hi - lo) if hi > lo else float(K)
    return float(N)


# ------------------------------------------------------------------ report
def pct(p): return f"{100 * p:5.1f}%"

def names_list(xs, lists, limit=12):
    xs = sorted(xs)
    if not lists: return f"{len(xs)} cards"
    return "; ".join(xs[:limit]) + (f" … (+{len(xs) - limit})" if len(xs) > limit else "")

def main():
    ap = argparse.ArgumentParser(description="Tutor graph and access analysis (see module docstring)")
    ap.add_argument("deck"); ap.add_argument("--commander"); ap.add_argument("--draw", action="store_true")
    ap.add_argument("--turns", default="4,6"); ap.add_argument("--no-lists", action="store_true")
    ap.add_argument("--trials", type=int, default=40000)
    ap.add_argument("--no-infer", action="store_true", help="key cards from the header lines only")
    a = ap.parse_args()
    if not os.path.exists(a.deck): sys.exit(f"deck file not found: {a.deck}")
    if a.deck.lower().endswith(".dck"): sys.exit("this is a Forge .dck file; pass the .txt list")
    try: turns = [int(x) for x in a.turns.split(",") if x.strip()]
    except ValueError: sys.exit("--turns takes a comma list, e.g. 4,6")
    if not turns or min(turns) < 1: sys.exit("--turns must be positive, e.g. 4,6")
    if a.trials < 1: sys.exit("--trials must be at least 1")
    on_play, lists = not a.draw, not a.no_lists
    d = Deck(a.deck, a.commander)
    cmd = " + ".join(sorted(d.cmd_names)) or "(no commander)"
    print(f"=== TUTORS: {cmd} | {d.N} cards in library | on the {'play' if on_play else 'draw'} ===")
    print("Odds ignore mana and the turns a chain takes (\"can you get there\", not \"how fast\"); goldfish.py is the mana check.")

    # ---- 1. inventory
    all_t = [t for ts in d.tutors.values() for t in ts]
    main_t = [t for t in all_t if not d.land_only(t)]
    land_t = [t for t in all_t if d.land_only(t)]
    print(f"\n## 1. Tutors ({len(main_t)} effects on {len({t.name for t in main_t})} cards; "
          f"{len(land_t)} land-only effects listed separately)")
    order = sorted(main_t, key=lambda t: (t.name not in d.cmd_names, not t.repeatable, t.name))
    dead, shallow, approx = [], [], []
    for t in order:
        tg = sorted(x for x in d.lib_names if t.target.matches(d.card[x]) and not (x == t.name and d.qty.get(x, 0) < 2))
        nonland = [x for x in tg if not d.is_land[x]]
        where = "commander, " if t.name in d.cmd_names else ""
        nl = len(tg) - len(nonland)
        print(f"  {t.name} [{where}{t.label()}] → {t.dest}{' (not counted as access)' if t.dest in NO_ACCESS else ''}: "
              f"{t.target.describe()}" + (f" ×{t.target.count}" if t.target.count > 1 else "")
              + f" — {len(nonland)} nonland" + (f" + {nl} land" if nl else "") + " target(s)")
        if lists and nonland: print(f"      {names_list(nonland, lists)}")
        elif lists and tg: print(f"      {names_list(tg, lists)}")
        if t.target.approx:
            print(f"      ⚠ read approximately: {'; '.join(dict.fromkeys(t.target.approx))}"); approx.append(t.name)
        if not tg: dead.append(t.name)
        elif len(nonland) <= 2 and not all(d.is_land[x] for x in tg): shallow.append(f"{t.name} ({len(nonland)})")
    if land_t:
        print(f"  land-only (mana, not analyzed further): {'; '.join(sorted({t.name for t in land_t}))}")
    if d.engines:
        print(f"  flicker engines: " + "; ".join(f"{n} ({w}{', repeatable' if r else ', one-shot'})" for n, w, r in d.engines))
    if dead: print(f"  ⚠ no targets in this deck: {'; '.join(dead)}")
    if shallow: print(f"  shallow pools (≤2 nonland targets): {'; '.join(shallow)}")
    if not main_t: print("  no tutors outside land search")
    generic = sorted({t.name for t in main_t if t.target.broad() and t.dest not in NO_ACCESS})
    if generic: print(f"  find-anything tutors: {'; '.join(generic)} (sections 3-6 also show the deck without them)")

    # ---- 2. chains
    print("\n## 2. Chains (tutors that find other tutors; a fetched tutor must land where it still works)")
    links = []
    for src, outs in sorted(d.edges.items()):
        found = []
        for u, ts in sorted(outs.items()):
            if u == src or u not in d.tutors or all(d.land_only(t2) for t2 in d.tutors[u]): continue
            if any(t.dest not in NO_ACCESS and any(t2.usable_from(t.dest) for t2 in d.tutors[u] if not d.land_only(t2)) for t in ts):
                found.append(u)
        if found: links.append((src, found))
    reach_all = {x: d.reach(x) for x in d.lib_names}
    if links:
        print("  links:")
        for src, found in links:
            print(f"      {src}{' [commander]' if src in d.cmd_names else ''} → {'; '.join(found)}")
    chains = []
    for x in [y for y in d.lib_names if not d.is_land[y]]:
        for src, p in reach_all[x].items():
            if len(p) >= 3: chains.append((len(p), p))
    if chains:
        print("  routes a tutor only gets through another tutor (shortest route to each card):")
        chains.sort(key=lambda z: (-z[0], z[1]))
        shown, seen_keys = 0, set()
        for L, p in chains:
            key = tuple(p[:-1])
            if key in seen_keys: continue
            seen_keys.add(key)
            ends = sorted({q[-1] for L2, q in chains if tuple(q[:-1]) == key})
            print(f"      {path_str(p[:-1])} → {names_list(ends, lists, 8)}")
            shown += 1
            if shown >= 12: print("      … more omitted"); break
    if not links and not chains:
        print("  none: no tutor here can find another tutor that still works where it lands")

    # ---- 3. coverage
    print("\n## 3. Coverage (nonland cards; ways = cards that can start a path to it)")
    nonbasic = [x for x in d.lib_names if not d.is_land[x]]
    reach_spec = {x: d.reach(x, specific=True) for x in d.lib_names}
    views = [("all tutors", reach_all)] + ([("specific tutors only", reach_spec)] if generic else [])
    for label, R in views:
        unreach = sorted(x for x in nonbasic if not R[x])
        one = sorted(x for x in nonbasic if len(R[x]) == 1)
        many = sorted(x for x in nonbasic if len(R[x]) >= 2)
        print(f"  {label}: {len(many)} reachable 2+ ways | {len(one)} exactly 1 way | {len(unreach)} no tutor finds (of {len(nonbasic)})")
        if unreach: print(f"      draw-only: {names_list(unreach, lists, 40)}")
        if one:
            print("      single path: " + ("; ".join(f"{x} (via {next(iter(R[x]))})" for x in one[:20])
                                        if lists else f"{len(one)} cards") + (" …" if lists and len(one) > 20 else ""))
    lands_nb = sorted(x for x in d.lib_names if d.is_land[x] and not d.basic[x])
    if lands_nb: print(f"  nonbasic lands a tutor can find: {sum(1 for x in lands_nb if reach_all[x])} of {len(lands_nb)}")

    # ---- 4. dependencies
    print("\n## 4. Dependencies (cards that lose ALL tutor access without this one)")
    for label, R, spec in [("all tutors", reach_all, False)] + ([("specific tutors only", reach_spec, True)] if generic else []):
        deps = []
        for src in sorted({x for t in nonbasic for x in R[t]}):
            lost = [x for x in nonbasic if R[x] and not d.reach(x, frozenset({src}), spec)]
            if lost: deps.append((src, lost))
        deps.sort(key=lambda z: (z[0] not in d.cmd_names, -len(z[1]), z[0]))
        if not deps:
            print(f"  {label}: none, every tutorable card has two independent starting points"); continue
        print(f"  {label}:")
        for src, lost in deps[:10]:
            print(f"      {src}{' [commander]' if src in d.cmd_names else ''}: {len(lost)} — {names_list(lost, lists, 10)}")

    # ---- keys: yours (header lines) and inferred beyond them
    yours, inferred, scores, bad_keys = key_cards(d, infer=not a.no_infer)
    keys = yours + inferred
    pk_specs = [sm.parse_package(v) for v in (d.meta.get("package") or [])]
    ts_, dc = mtg.deck_combos(sorted(d.lib_names | d.cmd_names))
    combos = sorted((v for v in (dc or []) if len(v["cards"]) <= 3), key=lambda v: (len(v["cards"]), -v.get("pop", 0)))
    trees = None
    if any(p.lower().startswith("tag:") for _, parts in pk_specs for p in parts):
        trees = mtg.load_tags_multi(sorted({p[4:].strip() for _, parts in pk_specs for p in parts if p.lower().startswith("tag:")}))
    pk_resolved = []
    for label, parts in pk_specs:
        mem = [sm._part_members(p, d.lib_names | d.cmd_names, trees) for p in parts]
        pk_resolved.append(("header", label, parts, mem))
    for v in combos[:8]:
        pk_resolved.append(("combo", " + ".join(v["cards"]), v["cards"], [{x} for x in v["cards"]]))

    # ---- 5. key cards and access odds
    print(f"\n## 5. Key cards (drawn, or a card with a path to it, by " + ", ".join(f"T{T}" for T in turns) + ")")
    if bad_keys: print(f"  ⚠ '# key:' names not in the library: {'; '.join(bad_keys)}")
    agree = [x for x in yours if x in scores and scores[x][0] >= INFER_MIN]
    print(f"  yours ({len(yours)}, from the header lines): " + ("; ".join(yours) if yours else "none"))
    if not a.no_infer:
        print(f"  inferred beyond yours ({len(inferred)}): "
              + ("; ".join(f"{x} ({'; '.join(scores[x][1])})" for x in inferred) if inferred else "none"))
        if yours:
            print(f"  inference also picks {len(agree)} of your {len(yours)}"
                  + (f"; it misses {'; '.join(x for x in yours if x not in agree)}" if len(agree) < len(yours) else "")
                  + " (how far to trust the inferred list on this deck)")
    timing = cmd_timing(a.deck, a.commander, on_play, turns) if any(c in d.tutors for c in d.cmd_names) else {}
    if not keys:
        print("  no key cards (none in the header, none inferred)")
    for x in keys:
        cells = []
        for T in turns:
            n_seen = sm.cards_seen(T, on_play)
            p = access_odds(d, x, T, on_play, frozenset(d.cmd_names))[0]
            q = sm.hyper_at_least(d.N, d.qty.get(x, 0), n_seen, 1)
            cell = f"T{T} {pct(p)}"
            if generic: cell += f" (specific only {pct(access_odds(d, x, T, on_play, frozenset(d.cmd_names), True)[0])})"
            pc = cmd_access(d, x, T, timing, reach_all[x])
            if pc: cell += f", + commander {pct(1 - (1 - p) * (1 - pc))}"
            cells.append(cell + f", drawn {pct(q)}")
        T0 = turns[0]
        eq = copies_equiv(d.N, sm.cards_seen(T0, on_play), access_odds(d, x, T0, on_play, frozenset(d.cmd_names))[0])
        src = "yours" if x in yours else "inferred"
        print(f"  {x} [{src}]: " + " | ".join(cells) + f" | {len(reach_all[x])} way(s), plays like {eq:.1f} copies by T{T0}")
    if keys:
        print("  (library odds: the card or a library card that leads to it. '+ commander': also the commander's own tutor,")
        print("   once manasim.py games have it on the battlefield long enough to use it; repeatable tutors are a ceiling)")

    # ---- 6. packages
    print("\n## 6. Packages (every piece drawn, or reached by a different tutor chain; a repeatable tutor can cover several)")
    if not pk_resolved:
        print("  none: no Spellbook combo of ≤3 cards here and no '# package:' lines")
    for src, label, parts, mem in pk_resolved:
        print(f"  [{src}] {label}")
        bad = [p for p, m in zip(parts, mem) if not m]
        if bad: print(f"      no card in the deck matches: {'; '.join(bad)}"); continue
        pieces = [set(m) for m in mem]
        if src == "header" and any(pieces[i] & pieces[j] for i in range(len(pieces)) for j in range(i + 1, len(pieces))):
            print("      parts share cards, so the odds aren't computed; make each part distinct"); continue
        for T in turns:
            nat, lib_ = package_odds_chains(d, pieces, T, on_play, a.trials, use_cmd=False)
            line = f"by T{T}: drawn {pct(nat)} | with library tutors {pct(lib_)}"
            if generic:
                line += f" (specific only {pct(package_odds_chains(d, pieces, T, on_play, a.trials, use_cmd=False, specific=True)[1])})"
            if d.cmd_names and any(any(c in d.reach(x) for c in d.cmd_names) for m in pieces for x in m):
                line += f" | + commander tutoring {pct(package_odds_chains(d, pieces, T, on_play, a.trials)[1])}"
            print(f"      {line}")
    if len(combos) > 8: print(f"  +{len(combos) - 8} more combo(s) not shown")

    # ---- 7. tutor worth
    T0 = turns[-1]
    print(f"\n## 7. Tutor worth (each tutor taken out: points of access lost by T{T0}, library tutors; a ceiling)")
    lib_tutors = sorted(x for x in d.tutors if x in d.lib_names and not all(d.land_only(t) for t in d.tutors[x]))
    if not lib_tutors:
        print("  no library tutors")
    else:
        def mean_access(cards, banned, spec=False):
            if not cards: return 0.0
            return sum(access_odds(d, x, T0, on_play, frozenset(d.cmd_names) | banned, spec)[0] for x in cards) / len(cards)
        base_k, base_all = mean_access(keys, frozenset()), mean_access(nonbasic, frozenset())
        base_ks = mean_access(keys, frozenset(), True) if generic else None
        rows = []
        for tname in lib_tutors:
            b = frozenset({tname})
            only = sorted(x for x in nonbasic if x != tname and reach_all[x] and not d.reach(x, b | frozenset(d.cmd_names)))
            ks = (base_ks - mean_access(keys, b, True)) if generic and tname not in generic else None
            rows.append((base_k - mean_access(keys, b), ks, base_all - mean_access(nonbasic, b), tname, only))
        rows.sort(key=lambda r: (-r[0], -(r[1] or 0), -r[2], r[3]))
        print(f"  {'tutor':<34}{'key cards':>11}" + (f"{'specific only':>15}" if generic else "") + f"{'whole deck':>12}   only it reaches")
        for dk, ks, da, tname, only in rows:
            print(f"  {tname[:34]:<34}{100 * dk:+10.1f}" + ((f"{100 * ks:+15.1f}" if ks is not None else f"{'find-anything':>15}") if generic else "")
                  + f"{100 * da:+12.1f}   " + (names_list(only, lists, 6) if only else "—"))
        print(f"  (mean access over the {len(keys)} key cards and the {len(nonbasic)} nonland cards; the commander's own")
        print("   tutoring stays out, so this is what each library tutor adds on top of the rest. Every chain counts as free")
        print("   here, so tutors look alike; 'specific only' sets the find-anything tutors aside, which separates them more)")
    print(f"\nsampled packages: {a.trials:,} games per cell (±~0.5 pts); single-card odds in section 5 are exact.")
    if d.cmd_names & set(d.tutors): print("'+ commander tutoring' assumes the commander is out and its tutor fires as often as needed: a ceiling.")

if __name__ == "__main__":
    main()
