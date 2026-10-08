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
                  lands, what it can find here, and anything read approximately; find-anything
                  tutors (Demonic Tutor: any card, or any nonland card) in a table of their own,
                  their targets "everything" rather than a list (the same split in sections 2 and 8)
  2 Chains        tutors that find tutors (Step Through -> Spellseeker -> Cyclonic Rift)
  3 Coverage      how many ways each card can be reached; cards no tutor can find
  4 Dependencies  what loses all tutor access if a card is gone (the commander first)
  5 Key cards     yours ('# key:' / '# package:' lines) and inferred beyond them, with reasons;
                  access odds for both: drawn, or a card that leads to them, by each turn, then
                  with the commander's own tutoring added once it's out (manasim.py games);
                  "plays like N copies"
  6 Packages      Spellbook combos (<= 3 cards) and '# package:' lines, with chains
  7 Tutor worth   each tutor taken out: points of access lost on the key cards and on the
                  whole deck, and the cards only it reaches; then played: the same games with that
                  tutor inert, key cards found by the last turn, game by game

  8 Tutors to add  tutors from the whole card pool (tutor_index.py) in the deck's colors that reach its
                  key cards, Game Changers within the bracket allowance, under --max-price; each is
                  played in the deck (same games) and ranked by key cards found per 100 games it adds;
                  then the best one swapped for the weakest tutor you run

PLAYED (sections 5-8): manasim.py's tutor mode plays lands, ramp, tutors and card draw through
goldfish.py's engine (mana paid, timing, one-shot tutors used once, the commander attacking for its
trigger), fetching your key cards first, then package pieces, then inferred keys; every other card
is inert, so nothing competes for the mana but ramp and card flow. A key card counts as found once
it has left the library. --no-played skips the games; --played-trials N (default 2000).

  --md              the same report with Markdown tables (renders in the app and on GitHub)

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
    r"(?:search(?:es)? your library|(?<=each of them )searches their library|(?<=target player )searches their library"
    r"|search(?:es)? your (?:graveyard|hand)[a-z ,/]*?library"                       # graveyard, hand, and/or library
    r"|(?<=each player )searches their library|(?<=each player may )search their library"
    r"|(?<=may each )search their library"                                            # any number of target players may each
    r"|(?<=that creature's controller may )search their library"                     # your creature dies (Pattern of Rebirth)
    r"|(?<=that player loses 3 life, )searches their library)"                         # Maralen of the Mornsong, Mornsong Aria
    r"(?: and(?:/or)? (?:your )?graveyard)?(?: and/or graveyard)?"
    r"(?:,? (?:and/or |or |and )?(?:your )?(?:hand|graveyard|outside the game))* for "
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
        self.same_name = False      # "a card with the same name as ...": only extra copies (none in a singleton deck)

    def broad(self):
        """Finds (nearly) anything: any card, or any nonland card with no other limit."""
        if self.alts: return any(a.broad() for a in self.alts)
        if self.same_name: return False
        if self.any: return True
        return (self.non <= {"land"} and not (self.types or self.supers or self.subs or self.colors or self.colorless
                or self.multicolored or self.permanent or self.historic or self.mv or self.power or self.tough
                or self.mana_ability or self.flash or self.named))

    def matches(self, c):
        if self.alts: return any(a.matches(c) for a in self.alts)
        if self.same_name: return False             # Mask of the Mimic, Remembrance: a second copy, never another card
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
        if self.same_name: return "another copy of a card you already have (none in a singleton deck)"
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


_NAMES = set()
def _card_names():
    """Every card name, lowercased (named-card tutors whose name has a comma)."""
    if not _NAMES: _NAMES.update(c["name"].lower() for c in mtg.cards())
    return _NAMES

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
        # a name with a comma (Ajani, Valiant Protector): take the longest comma-joined run that's a real card name
        rest = low[low.index("named ") + 6:].strip().rstrip(".")
        parts = [x.strip() for x in rest.split(",")]
        for i in range(len(parts), 1, -1):
            cand = ", ".join(parts[:i])
            if cand in _card_names(): t.named = cand; break
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
    elif (mm := cut(r"(?:with|that (?:have|has)) (?:a )?mana value (\d+)\b")):        # Grozoth: "that have mana value 9"
        t.mv = ("==", int(mm.group(1)))
    elif (mm := cut(r"(?:with|that each have|each with) (?:a |the same )?mana value (x|equal to|less than|greater than|as)[^,]*")):
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
                     (r"with the same name as [^,]*", None),
                     (r"not named [^,]+?(?= that| with|,|$)", None),
                     (r"from among [^,]*", "restricted pool (read as any)")):
        mm = cut(rx)
        if mm and note: t.approx.append(note)
        if mm and "same name" in rx: t.same_name = True
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
            or t.permanent or t.historic or t.mv or t.power or t.tough or t.mana_ability or t.flash or t.same_name):
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
                head = m.group(0).lower()
                pre = line[max(0, m.start() - 40):m.start()]
                each = bool(re.search(r"(?:each player (?:may )?|may each |that player loses 3 life, )$", pre, re.I))
                own_creature = bool(re.search(r"that creature's controller may $", pre, re.I))
                self_target = head.startswith("searches their") and not each
                if not self_target and not each and not own_creature and re.search(r"(their|target player's|that player's|an opponent's) library",
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
                if each: tgt.approx.append("each player searches: your opponents tutor too")
                if own_creature: tgt.approx.append("only when it's your creature")
                out.append(Tutor(c, fi, kind, tgt, dest, rep, cond, line.strip()))
            # 'Partner with X (When this creature enters, target player may put X into their hand from their library...)':
            # the reminder text is a tutor for the partner, with no 'search' in it
            mp = re.match(r"partner with ([^(\n]+?)\s*(?:\(when this creature enters, target player may put [^)]*? into their hand "
                          r"from their library|$)", line.strip(), re.I)
            if mp:
                tgt = parse_target(f"a card named {mp.group(1).strip()}", c)
                tgt.named = mp.group(1).strip().lower()             # names with commas (Toothy, Imaginary Friend)
                tgt.approx.append("target player: you, or an opponent who has the partner")
                out.append(Tutor(c, fi, "etb", tgt, "hand", False, "enters", line.strip()))
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

def names_list(xs, lists):
    """Every name, sorted (nothing cut); with --no-lists, just the count."""
    xs = sorted(xs)
    if not lists: return f"{len(xs)} card{'s' if len(xs) != 1 else ''}"
    return "; ".join(xs)

def played_runs(path, commander, on_play, turns, yours, inferred, packages, lib_tutors, trials=2000, seed=7):
    """manasim.py tutor-mode games: the deck as is, then once per library tutor with that tutor inert (same shuffles).
    packages: [(label, [[names] per part])]. Returns (base, {tutor: run}) or (None, {}) when manasim can't run."""
    try:
        import manasim
    except Exception:
        return None, {}
    want = (tuple(yours), tuple((lab, tuple(tuple(sorted(p)) for p in parts)) for lab, parts in packages), tuple(inferred))
    specs = [(0, False, (), (), (), "tutors", (), want)] + [(0, False, (), (), (), "tutors", (t,), want) for t in lib_tutors]
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        runs = manasim.simulate_many(path, commander, on_play, trials, max(turns), seed, specs)
    return runs[0], dict(zip(lib_tutors, runs[1:]))


GC_ALLOW = {1: 0, 2: 0, 3: 3}                     # Game Changers allowed by bracket (as audit.py)

def tutor_candidates(d, keys, yours, bracket=None, max_price=None, limit=16):
    """Tutors from the whole pool (tutor_index.py) that could join this deck: in its colors, legal, not in it, Game
    Changers within the bracket allowance, under max_price, reaching at least one key card where it stays usable.
    Shortlist by the key cards reached (yours count double, a repeatable tutor double), then EDHREC rank.
    Only tutors goldfish.py reads fully (or holds as interaction) are played and ranked: a part it doesn't read can
    make a card look far better or worse than it is (Profane Tutor's suspend read as a free tutor). The others
    come back as `unverified`.
    Returns ([(card, reached key names, effect)], pool size, gc_ok, unverified [(card, reached, status)])."""
    import tutor_index as ti
    ci = set().union(*((c.get("color_identity") or []) for c in d.cmdrs)) if d.cmdrs else \
        set().union(*((d.card[n].get("color_identity") or []) for n in d.lib_names))
    in_deck = d.lib_names | d.cmd_names
    deck_gc = sum(1 for n in in_deck if d.card[n].get("game_changer"))
    gc_ok = bracket is None or bracket >= 4 or deck_gc < GC_ALLOW.get(bracket, 0)
    pool = []
    for c, ts in ti.index():
        if c["name"] in in_deck or not set(c.get("color_identity") or []) <= ci: continue
        if c.get("game_changer") and not gc_ok: continue
        if max_price is not None and (mtg.price(c) is None or mtg.price(c) > max_price): continue
        if ti.land_only(ts) or "land" in type_parts(c)[1]: continue      # lands are land-swap territory (landbase.py)
        best, reached = None, []
        for t in ts:
            if t.dest in NO_ACCESS: continue
            r = [k for k in keys if t.target.matches(d.card[k])]
            if len(r) > len(reached): best, reached = t, r
        if not reached: continue
        # efficiency: key cards reached (yours double) per mana, a repeatable tutor double
        score = sum(2 if k in yours else 1 for k in reached) * (2 if best.repeatable else 1) / max(1, int(c.get("cmc") or 0))
        pool.append((score, c, reached, best))
    import goldfish as gf
    anyc = frozenset(ci) or gf.ALL5
    def status(c):
        try:
            k = gf.compile_card(c, anyc)
            ov = gf.load_overrides().get(mtg.norm(c["name"]))
            if ov: gf.apply_override(k, ov, anyc)
            tg = [e for e in gf.all_fx(k) if e[0] == "tutor"]
            if tg and all(gf.tutor_unread(e[1]) for e in tg): return "tutor unread"   # the games would skip its search
            return k.status
        except Exception:
            return "?"
    st = {x[1]["name"]: status(x[1]) for x in pool}
    unverified = sorted(((c, r, st[c["name"]]) for _, c, r, t in pool if st[c["name"]] not in ("modeled", "held")),
                        key=lambda x: (x[0].get("edhrec_rank") or 10**7, x[0]["name"]))
    pool = [x for x in pool if st[x[1]["name"]] in ("modeled", "held")]
    # shortlist: half the most played (EDHREC rank), half the most efficient; all of them are then played and ranked
    by_rank = sorted(pool, key=lambda x: (x[1].get("edhrec_rank") or 10**7, x[1]["name"]))
    by_eff = sorted(pool, key=lambda x: (-x[0], x[1].get("edhrec_rank") or 10**7, x[1]["name"]))
    short, seen = [], set()
    for a, b in zip(by_rank, by_eff):
        for x in (a, b):
            if x[1]["name"] not in seen and len(short) < limit: short.append(x); seen.add(x[1]["name"])
    return [(c, r, t) for _, c, r, t in short], len(pool) + len(unverified), gc_ok, unverified


def found_paired(r, base, keys, T):
    """(mean difference, standard error) of the number of key cards found by T, game by game."""
    import math
    ks = [k for k in keys if k in base["found"] and k in r["found"]]
    if not ks: return 0.0, 1.0
    score = lambda run: [sum(1 for k in ks if run["found"][k]["first"][i] is not None and run["found"][k]["first"][i] <= T)
                         for i in range(len(run["found"][ks[0]]["first"]))]
    d = [x - y for x, y in zip(score(r), score(base))]
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return m, sd / math.sqrt(n)


class Out:
    """The report's one layout: headings, notes, bullet lines and tables. Text (default) prints aligned tables;
    --md prints the same tables as Markdown (they render in the app, on GitHub and in claude.ai)."""
    WIDTH = 60                                     # widest text column; longer cells wrap onto more lines

    def __init__(self, md=False): self.md = md

    def title(self, s): print(f"# {s}" if self.md else f"=== {s} ===")

    def h2(self, s): print(f"\n## {s}\n" if self.md else f"\n## {s}")

    def note(self, s): print(f"{s}  " if self.md else f"  {s}")       # Markdown: two trailing spaces keep the line break

    def bullet(self, s, depth=0): print(("  " * depth + "- " + s) if self.md else ("  " + "    " * depth + s))

    def table(self, headers, rows, right=()):
        rows = [["" if c is None else str(c) for c in r] for r in rows]
        if not rows: return
        if self.md:
            print()                                                   # a table renders only after a blank line
            print("| " + " | ".join(headers) + " |")
            print("|" + "|".join("---:" if i in right else "---" for i in range(len(headers))) + "|")
            for r in rows: print("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
            print()
            return
        import textwrap
        wrap = lambda c: textwrap.wrap(c, self.WIDTH, break_on_hyphens=False) or [""] if len(c) > self.WIDTH else [c]
        rows = [[wrap(c) for c in r] for r in rows]
        w = [max([len(h)] + [len(x) for r in rows for x in r[i]]) for i, h in enumerate(headers)]
        fmt = lambda cells: "  " + "  ".join(c.rjust(w[i]) if i in right else c.ljust(w[i]) for i, c in enumerate(cells)).rstrip()
        print(fmt(headers)); print("  " + "  ".join("-" * x for x in w))
        for r in rows:
            for j in range(max(len(c) for c in r)):        # a wrapped cell continues on the next lines, other cells blank
                print(fmt([c[j] if j < len(c) else "" for c in r]))


def anything(t):
    """A find-anything tutor (Demonic Tutor): any card, or any nonland card with no other limit. Its targets are
    'everything', so the report lists these on their own instead of naming every card."""
    return t.target.broad()


def everything_str(t):
    return "everything" if t.target.any else "every " + t.target.describe()


def how_used(t):
    """Short 'how' for the tutor table: spell, enters, attack trigger, wizardcycling, transmute, activated..."""
    if t.kind == "trigger": return (t.condition or "trigger").replace("whenever ", "").replace("when ", "")
    if t.kind == "etb": return "enters"
    if t.kind == "cycling": return t.condition or "cycling"
    if t.kind == "transmute": return "transmute"
    if t.kind == "activated": return "activated"
    if t.kind == "loyalty": return t.condition
    return t.kind


def main():
    ap = argparse.ArgumentParser(description="Tutor graph and access analysis (see module docstring)")
    ap.add_argument("deck"); ap.add_argument("--commander"); ap.add_argument("--draw", action="store_true")
    ap.add_argument("--turns", default="4,6"); ap.add_argument("--no-lists", action="store_true")
    ap.add_argument("--trials", type=int, default=40000)
    ap.add_argument("--no-infer", action="store_true", help="key cards from the header lines only")
    ap.add_argument("--md", action="store_true", help="Markdown tables (same report)")
    ap.add_argument("--no-played", action="store_true", help="best-case odds only (no manasim.py games)")
    ap.add_argument("--played-trials", type=int, default=2000)
    ap.add_argument("--no-suggest", action="store_true", help="skip section 8 (tutors to add)")
    ap.add_argument("--max-price", type=float, help="section 8: candidate tutors at most $N")
    ap.add_argument("--suggest", type=int, default=16, help="section 8: candidates played (default 16)")
    ap.add_argument("--json", help="also write the headline numbers to this file (audit.py section 4c reads it)")
    a = ap.parse_args()
    if not os.path.exists(a.deck): sys.exit(f"deck file not found: {a.deck}")
    if a.deck.lower().endswith(".dck"): sys.exit("this is a Forge .dck file; pass the .txt list")
    try: turns = [int(x) for x in a.turns.split(",") if x.strip()]
    except ValueError: sys.exit("--turns takes a comma list, e.g. 4,6")
    if not turns or min(turns) < 1: sys.exit("--turns must be positive, e.g. 4,6")
    if a.trials < 1: sys.exit("--trials must be at least 1")
    on_play, lists = not a.draw, not a.no_lists
    o = Out(a.md)
    summary = {"turns": turns, "keys": [], "deps": [], "worth": [], "add": [], "swap": None, "played_trials": None,
               "fidelity": None, "yours": [], "inferred": [], "agree": None, "bad_keys": [], "packages": []}
    d = Deck(a.deck, a.commander)
    cmd = " + ".join(sorted(d.cmd_names)) or "(no commander)"
    o.title(f"TUTORS: {cmd} | {d.N} cards in library | on the {'play' if on_play else 'draw'}")
    o.note("Odds ignore mana and the turns a chain takes (\"can you get there\", not \"how fast\"); goldfish.py is the mana check.")

    # ---- 1. inventory
    all_t = [t for ts in d.tutors.values() for t in ts]
    main_t = [t for t in all_t if not d.land_only(t)]
    land_t = [t for t in all_t if d.land_only(t)]
    o.h2(f"1. Tutors ({len(main_t)} effects on {len({t.name for t in main_t})} cards; "
         f"{len(land_t)} land-only effects listed separately)")
    order = sorted(main_t, key=lambda t: (t.name not in d.cmd_names, not t.repeatable, t.name))
    dead, shallow, approx, rows, targets, any_rows = [], [], [], [], [], []
    for t in order:
        tg = sorted(x for x in d.lib_names if t.target.matches(d.card[x]) and not (x == t.name and d.qty.get(x, 0) < 2))
        nonland = [x for x in tg if not d.is_land[x]]
        nl = len(tg) - len(nonland)
        finds = t.target.describe() + (f" ×{t.target.count}" if t.target.count > 1 else "") + (" ⚠" if t.target.approx else "")
        row = [t.name + (" (commander)" if t.name in d.cmd_names else ""), how_used(t),
               "repeatable" if t.repeatable else ("one-shot, re-buyable" if t.rebuy else "one-shot"),
               t.dest + (" (no access)" if t.dest in NO_ACCESS else "")]
        if anything(t):
            any_rows.append(row + [everything_str(t) + (f" ×{t.target.count}" if t.target.count > 1 else "")
                                   + (" ⚠" if t.target.approx else ""), f"{len(nonland)}" + (f" + {nl} lands" if nl else "")])
        else:
            rows.append(row + [finds, f"{len(nonland)}" + (f" + {nl} lands" if nl else "")])
            targets.append((t.name, nonland or tg))
        if t.target.approx: approx.append(f"{t.name}: {'; '.join(dict.fromkeys(t.target.approx))}")
        if not tg: dead.append(t.name)
        elif len(nonland) <= 2 and not all(d.is_land[x] for x in tg): shallow.append(f"{t.name} ({len(nonland)})")
    if rows: o.table(["Tutor", "How", "Uses", "Puts it", "Finds", "Targets here"], rows, right=(5,))
    elif main_t: o.note("specific tutors: none")
    if any_rows:
        o.note(f"find-anything tutors ({len(any_rows)}; their targets are everything, so they aren't listed card by card):")
        o.table(["Find-anything tutor", "How", "Uses", "Puts it", "Finds", "Cards here"], any_rows, right=(5,))
    if not main_t: o.note("no tutors outside land search")
    if land_t: o.note(f"land-only (mana, not analyzed further): {'; '.join(sorted({t.name for t in land_t}))}")
    if d.engines:
        o.note("flicker engines: " + "; ".join(f"{n} ({w}{', repeatable' if r else ', one-shot'})" for n, w, r in d.engines))
    rebuy = sorted({f"{t.name} via {'; '.join(t.rebuy)}" for t in main_t if t.rebuy})
    if rebuy: o.note("re-buyable ETB tutors: " + " | ".join(rebuy))
    if approx: o.note("⚠ read approximately: " + " | ".join(approx))
    if dead: o.note(f"⚠ no targets in this deck: {'; '.join(dead)}")
    if shallow: o.note(f"shallow pools (≤2 nonland targets): {'; '.join(shallow)}")
    generic = sorted({t.name for t in main_t if t.target.broad() and t.dest not in NO_ACCESS})
    if generic: o.note("the 'specific only' columns below set the find-anything tutors aside")
    if lists and targets:
        o.note("targets of the specific tutors:")
        for n, tg in targets:
            if tg: o.bullet(f"{n}: {names_list(tg, lists)}", 1)

    # ---- 2. chains
    o.h2("2. Chains (tutors that find other tutors; a fetched tutor must land where it still works)")
    links, any_links = [], []
    any_names = {x for x in d.tutors if any(anything(t) for t in d.tutors[x] if t.dest not in NO_ACCESS)}
    for src, outs in sorted(d.edges.items()):
        found = []
        for u, ts in sorted(outs.items()):
            if u == src or u not in d.tutors or all(d.land_only(t2) for t2 in d.tutors[u]): continue
            if any(t.dest not in NO_ACCESS and any(t2.usable_from(t.dest) for t2 in d.tutors[u] if not d.land_only(t2)) for t in ts):
                found.append(u)
        if found: (any_links if src in any_names else links).append((src, found))
    reach_all = {x: d.reach(x) for x in d.lib_names}
    if links:
        o.table(["Tutor", "Can find these tutors"],
                [[src + (" (commander)" if src in d.cmd_names else ""), "; ".join(found)] for src, found in links])
    if any_links:
        o.note("find-anything tutors find every tutor: " + "; ".join(src + (" (commander)" if src in d.cmd_names else "")
                                                                      for src, _ in any_links))
    chains = []
    for x in [y for y in d.lib_names if not d.is_land[y]]:
        for src, p in reach_all[x].items():
            if len(p) >= 3: chains.append((len(p), p))
    if chains:
        chains.sort(key=lambda z: (-z[0], z[1]))
        into_any = sorted({tuple(p[:-1]) for L, p in chains if p[-2] in any_names}, key=lambda k: (-len(k), k))
        spec = [(L, p) for L, p in chains if p[-2] not in any_names]
        if spec: o.note("routes a tutor only gets through another tutor (shortest route to each card):")
        seen_keys = set()
        for L, p in spec:
            key = tuple(p[:-1])
            if key in seen_keys: continue
            seen_keys.add(key)
            ends = sorted({q[-1] for L2, q in spec if tuple(q[:-1]) == key})
            o.bullet(f"{path_str(p[:-1])} → {names_list(ends, lists)}", 1)
        if into_any:
            o.note("routes into a find-anything tutor (then everything):")
            for key in into_any: o.bullet(f"{path_str(list(key))} → everything", 1)
    if not links and not chains:
        o.note("none: no tutor here can find another tutor that still works where it lands")

    # ---- 3. coverage
    o.h2("3. Coverage (nonland cards; ways = cards that can start a path to it)")
    nonbasic = [x for x in d.lib_names if not d.is_land[x]]
    reach_spec = {x: d.reach(x, specific=True) for x in d.lib_names}
    views = [("all tutors", reach_all)] + ([("specific tutors only", reach_spec)] if generic else [])
    rows, extra = [], []
    for label, R in views:
        unreach = sorted(x for x in nonbasic if not R[x])
        one = sorted(x for x in nonbasic if len(R[x]) == 1)
        many = sorted(x for x in nonbasic if len(R[x]) >= 2)
        rows.append([label, len(many), len(one), len(unreach), len(nonbasic)])
        if unreach: extra.append(f"{label}, draw-only: {names_list(unreach, lists)}")
        if one:
            via = {}
            for x in one: via.setdefault(next(iter(R[x])), []).append(x)
            for v, xs in sorted(via.items(), key=lambda kv: -len(kv[1])):
                extra.append(f"{label}, only via {v}: {names_list(xs, lists)}")
    o.table(["View", "2+ ways", "1 way", "No tutor", "Of"], rows, right=(1, 2, 3, 4))
    for e in extra: o.note(e)
    lands_nb = sorted(x for x in d.lib_names if d.is_land[x] and not d.basic[x])
    if lands_nb: o.note(f"nonbasic lands a tutor can find: {sum(1 for x in lands_nb if reach_all[x])} of {len(lands_nb)}")

    # ---- 4. dependencies
    o.h2("4. Dependencies (cards that lose ALL tutor access without this one)")
    rows = []
    for label, R, spec in [("all tutors", reach_all, False)] + ([("specific tutors only", reach_spec, True)] if generic else []):
        deps = []
        for src in sorted({x for t in nonbasic for x in R[t]}):
            lost = [x for x in nonbasic if R[x] and not d.reach(x, frozenset({src}), spec)]
            if lost: deps.append((src, lost))
        deps.sort(key=lambda z: (z[0] not in d.cmd_names, -len(z[1]), z[0]))
        if not deps:
            rows.append([label, "none", 0, "every tutorable card has two independent starting points"])
            summary["deps"].append({"view": label, "card": None, "commander": False, "lost": []})
        for src, lost in deps:
            rows.append([label, src + (" (commander)" if src in d.cmd_names else ""), len(lost), names_list(lost, lists)])
            summary["deps"].append({"view": label, "card": src, "commander": src in d.cmd_names, "lost": sorted(lost)})
    o.table(["View", "Without", "Cards cut off", "Which"], rows, right=(2,))

    # ---- keys: yours (header lines) and inferred beyond them
    yours, inferred, scores, bad_keys = key_cards(d, infer=not a.no_infer)
    bad_keys = [b for b in bad_keys if "it's the commander" not in b]       # a commander named as a key is fine
    keys = yours + inferred
    pk_specs = [sm.parse_package(v) for v in (d.meta.get("package") or [])]
    ts_, dc = mtg.deck_combos(sorted(d.lib_names | d.cmd_names))
    tutor_names = {x for x in d.tutors if not all(d.land_only(t) for t in d.tutors[x])}
    def tutor_plus_target(cards):
        """Spellbook's 'combo' that's a tutor plus a card it can find (Approach of the Second Sun + Mystical Tutor)."""
        return any(x in tutor_names and any(y in d.edges.get(x, {}) for y in cards if y != x) for x in cards)
    combos = sorted((v for v in (dc or []) if len(v["cards"]) <= 3 and not tutor_plus_target(v["cards"])),
                    key=lambda v: (len(v["cards"]), -v.get("pop", 0)))
    trees = None
    if any(p.lower().startswith("tag:") for _, parts in pk_specs for p in parts):
        trees = mtg.load_tags_multi(sorted({p[4:].strip() for _, parts in pk_specs for p in parts if p.lower().startswith("tag:")}))
    pk_resolved = []
    for label, parts in pk_specs:
        mem = [sm._part_members(p, d.lib_names | d.cmd_names, trees) for p in parts]
        pk_resolved.append(("header", label, parts, mem))
    PLAYED_COMBOS = 8                     # combos the played games try to assemble (more would dilute what the pilot fetches)
    for i, v in enumerate(combos):
        pk_resolved.append(("combo", " + ".join(v["cards"]), v["cards"], [{x} for x in v["cards"]]))
    n_played_pk = len(pk_specs) + min(len(combos), PLAYED_COMBOS)

    # ---- played games (manasim.py tutor mode)
    lib_tutors = sorted(x for x in d.tutors if x in d.lib_names and not all(d.land_only(t) for t in d.tutors[x]))
    played, dropped_runs = None, {}
    if not a.no_played and (keys or pk_resolved):
        pk_names = [(label, [sorted(m) for m in mem]) for src, label, parts, mem in pk_resolved[:n_played_pk] if all(mem)]
        played, dropped_runs = played_runs(a.deck, a.commander, on_play, turns, yours, inferred, pk_names, lib_tutors,
                                           a.played_trials)

    # ---- 5. key cards and access odds
    o.h2(f"5. Key cards (drawn, or a card with a path to it, by " + ", ".join(f"T{T}" for T in turns) + ")")
    if bad_keys: o.note(f"⚠ '# key:' names not in the library: {'; '.join(bad_keys)}")
    agree = [x for x in yours if x in scores and scores[x][0] >= INFER_MIN]
    o.note(f"yours ({len(yours)}, from the header lines): " + ("; ".join(yours) if yours else "none"))
    summary.update(yours=list(yours), inferred=list(inferred), bad_keys=list(bad_keys),
                   agree=None if a.no_infer or not yours else len(agree))
    if not a.no_infer:
        if yours:
            o.note(f"inference also picks {len(agree)} of your {len(yours)}"
                   + (f"; it misses {'; '.join(x for x in yours if x not in agree)}" if len(agree) < len(yours) else "")
                   + " (how far to trust the inferred list on this deck)")
        if inferred:
            o.note(f"inferred beyond yours ({len(inferred)}):")
            o.table(["Inferred card", "Score", "Why"], [[x, f"{scores[x][0]:.1f}", "; ".join(scores[x][1])] for x in inferred],
                    right=(1,))
        else:
            o.note("inferred beyond yours: none")
    timing = cmd_timing(a.deck, a.commander, on_play, turns) if any(c in d.tutors for c in d.cmd_names) else {}
    if not keys:
        o.note("no key cards (none in the header, none inferred)")
    else:
        has_cmd = any(cmd_access(d, x, T, timing, reach_all[x]) for x in keys for T in turns)
        pl = played is not None
        head = ["Card", "Key", "Ways"]
        for T in turns:
            head += [f"T{T} best"] + ([f"T{T} specific"] if generic else []) + ([f"T{T} +cmdr"] if has_cmd else []) \
                + ([f"T{T} played"] if pl else [])
        head += ["Drawn " + "/".join(f"T{T}" for T in turns), f"Copies T{turns[-1]}" + (" (played)" if pl else "")]
        rows = []
        for x in keys:
            r = [x, "yours" if x in yours else "inferred", len(reach_all[x])]
            for T in turns:
                p = access_odds(d, x, T, on_play, frozenset(d.cmd_names))[0]
                r.append(pct(p).strip())
                if generic: r.append(pct(access_odds(d, x, T, on_play, frozenset(d.cmd_names), True)[0]).strip())
                if has_cmd:
                    pc = cmd_access(d, x, T, timing, reach_all[x])
                    r.append(pct(1 - (1 - p) * (1 - pc)).strip() if pc else "—")
                if pl: r.append(pct(played["found"][x]["by"][T]).strip() if x in played["found"] else "—")
            r.append(" / ".join(pct(sm.hyper_at_least(d.N, d.qty.get(x, 0), sm.cards_seen(T, on_play), 1)).strip() for T in turns))
            T0 = turns[-1]
            pv = played["found"][x]["by"][T0] if pl and x in played["found"] else access_odds(d, x, T0, on_play, frozenset(d.cmd_names))[0]
            r.append(f"{copies_equiv(d.N, sm.cards_seen(T0, on_play), pv):.1f}")
            rows.append(r)
            summary["keys"].append({"card": x, "key": r[1], "ways": r[2], "cells": dict(zip(head[3:], r[3:])),
                                    "best": {T: access_odds(d, x, T, on_play, frozenset(d.cmd_names))[0] for T in turns},
                                    "played": {T: played["found"][x]["by"][T] for T in turns} if pl and x in played["found"] else None})
        o.table(head, rows, right=tuple(range(2, len(head))))
        o.note("best: the card, or a library card that leads to it, every chain free. specific: without find-anything tutors.")
        o.note("+cmdr: also the commander's own tutor once manasim.py games have it out long enough to use it (a ceiling).")
        if pl:
            o.note(f"played: found (out of the library) by that turn in {played['trials']:,} manasim.py games with lands, ramp, tutors")
            o.note("and draw played and the mana paid; your keys are fetched first, then package pieces, then inferred keys.")
            try:
                import manasim
                fl = manasim.fidelity_line(manasim.role_coverage(manasim.load(a.deck, a.commander)))
                if fl: o.note(fl + " (played numbers run low where these aren't played)")
                summary["fidelity"] = fl
            except Exception:
                pass
        o.note("Copies: how many copies of the card would give the same odds by that turn" + (" (from played)." if pl else "."))

    # ---- 6. packages
    o.h2("6. Packages (every piece drawn, or reached by a different tutor chain; a repeatable tutor can cover several)")
    rows, notes6 = [], []
    def head6():
        h = []
        for T in turns: h += [f"T{T} drawn", f"T{T} tutors"] + ([f"T{T} specific"] if generic else []) + [f"T{T} +cmdr"] \
            + ([f"T{T} played"] if played is not None else [])
        return h
    for src, label, parts, mem in pk_resolved:
        bad = [p for p, m in zip(parts, mem) if not m]
        if bad: notes6.append(f"{label}: no card in the deck matches {'; '.join(bad)}"); continue
        pieces = [set(m) for m in mem]
        if src == "header" and any(pieces[i] & pieces[j] for i in range(len(pieces)) for j in range(i + 1, len(pieces))):
            notes6.append(f"{label}: parts share cards, so the odds aren't computed; make each part distinct"); continue
        cmd_reach = d.cmd_names and any(any(c in d.reach(x) for c in d.cmd_names) for m in pieces for x in m)
        asm = next((x for x in (played or {}).get("assembled", []) if x["label"] == label), None)
        r = [label, "yours" if src == "header" else "Spellbook"]
        for T in turns:
            nat, lib_ = package_odds_chains(d, pieces, T, on_play, a.trials, use_cmd=False)
            r += [pct(nat).strip(), pct(lib_).strip()]
            if generic: r.append(pct(package_odds_chains(d, pieces, T, on_play, a.trials, use_cmd=False, specific=True)[1]).strip())
            r.append(pct(package_odds_chains(d, pieces, T, on_play, a.trials)[1]).strip() if cmd_reach else "—")
            if played is not None: r.append(pct(asm["by"][T]).strip() if asm else "—")
        rows.append(r)
        summary["packages"].append({"label": label, "source": src, "cells": dict(zip(head6(), r[2:]))})
    head = ["Package", "From"] + head6()
    if rows: o.table(head, rows, right=tuple(range(2, len(head))))
    for n_ in notes6: o.note(n_)
    dropped = sum(1 for v in (dc or []) if len(v["cards"]) <= 3 and tutor_plus_target(v["cards"]))
    if not pk_resolved:
        o.note("none: no Spellbook combo of ≤3 cards here and no '# package:' lines"
               + (f" ({dropped} Spellbook 'combo(s)' that are only a tutor and its target left out)" if dropped else ""))
    elif rows:
        o.note(f"tutors: drawn or reached through library tutors; +cmdr: the commander's tutoring too, used as often as needed (a")
        o.note(f"ceiling). Sampled, {a.trials:,} games per cell (±~0.5 pts). Spellbook 'combos' that are only a tutor and its target are left out.")
    if len(combos) > PLAYED_COMBOS and played is not None:
        o.note(f"played: the games assemble your package lines and the {PLAYED_COMBOS} smallest, most played combos; the other "
               f"{len(combos) - PLAYED_COMBOS} show '—' there")

    worth = {}
    # ---- 7. tutor worth
    T0 = turns[-1]
    o.h2(f"7. Tutor worth (each library tutor taken out, by T{T0}: played, then best case)")
    if not lib_tutors:
        o.note("no library tutors")
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
        pl = played is not None and bool(dropped_runs)
        worth = {}
        if pl:
            for tname, r_ in dropped_runs.items():
                m, se = found_paired(r_, played, keys, T0)
                worth[tname] = (-m, se)                     # points of key-card finding lost without it
            rows.sort(key=lambda r: (-worth.get(r[3], (0, 0))[0], -r[0], r[3]))
        head = ["Tutor"] + (["Played: key cards per 100 games"] if pl else []) + ["Key cards (best)"] + (["Specific only"] if generic else []) \
            + ["Whole deck (best)", "Only it reaches"]
        out = []
        for dk, ks, da, tname, only in rows:
            r = [tname]
            if pl:
                m, se = worth.get(tname, (0.0, 1.0))
                r.append(f"{100 * m:+.0f}" + ("" if abs(m) >= max(2 * se, 0.01) else " ≈"))
            r.append(f"{100 * dk:+.1f}")
            if generic: r.append(f"{100 * ks:+.1f}" if ks is not None else "find-anything")
            r += [f"{100 * da:+.1f}", names_list(only, lists) if only else "—"]
            out.append(r)
        for dk, ks, da, tname, only in rows:
            summary["worth"].append({"tutor": tname, "played": worth[tname][0] if tname in worth else None,
                                     "se": worth[tname][1] if tname in worth else None, "best_keys": dk, "best_all": da,
                                     "only": only})
        nr = 1 + (1 if pl else 0) + (1 if generic else 0)
        o.table(head, out, right=tuple(range(1, nr + 2)))
        if pl:
            o.note(f"Played: key cards found by T{T0} per 100 games that this tutor adds (the same {played['trials']:,} games with the tutor")
            o.note("inert, compared one by one; ≈: within noise or under 1 per 100). This is the number for 'is it worth its slot'.")
            o.note("Best-case columns: points of mean access lost over the key cards and the whole deck.")
        o.note(f"Best case: mean access over the {len(keys)} key cards and the {len(nonbasic)} nonland cards, the commander's own tutoring")
        o.note("left out, every chain free (so tutors look alike); 'specific only' sets the find-anything tutors aside.")

    # ---- 8. tutors to add (played)
    if not a.no_suggest and played is not None and keys:
        o.h2(f"8. Tutors to add (the whole card pool, played in this deck, by T{T0})")
        cands, pool_n, gc_ok, unverified = tutor_candidates(d, keys, yours, d.meta.get("bracket"), a.max_price, a.suggest)
        if not cands:
            o.note("no tutor in the pool reaches these key cards within the filters")
        else:
            import manasim, io, contextlib
            pk_names = [(label, [sorted(m) for m in mem]) for src, label, parts, mem in pk_resolved[:n_played_pk] if all(mem)]
            want = (tuple(yours), tuple((lab, tuple(tuple(p) for p in parts)) for lab, parts in pk_names), tuple(inferred))
            specs = [(0, False, (), (c["name"],), (), "tutors", (), want) for c, r, t in cands]
            with contextlib.redirect_stdout(io.StringIO()):
                runs = manasim.simulate_many(a.deck, a.commander, on_play, played["trials"], max(turns), 7, specs)
            res = []
            for (c, r, t), run in zip(cands, runs):
                m, se = found_paired(run, played, keys, T0)
                res.append((m, se, c, r, t))
            res.sort(key=lambda x: -x[0])
            rows, any_rows = [], []
            lib_tutor_names = [x for x in d.tutors if x in d.lib_names and not all(d.land_only(tt) for tt in d.tutors[x])]
            for m, se, c, r, t in res:
                if anything(t):
                    summary["add"].append({"tutor": c["name"], "played": m, "se": se, "finds": everything_str(t), "anything": True,
                                           "mv": int(c.get("cmc") or 0), "how": how_used(t), "price": mtg.price_str(c) or "—",
                                           "gc": bool(c.get("game_changer"))})
                    any_rows.append([c["name"], f"{100 * m:+.0f}" + ("" if abs(m) >= max(2 * se, 0.01) else " ≈"),
                                     int(c.get("cmc") or 0), how_used(t), everything_str(t), t.dest, mtg.price_str(c) or "—",
                                     "GC" if c.get("game_changer") else ""])
                    continue
                ry = [k for k in r if k in yours]
                ri = [k for k in r if k not in yours]
                chain = sorted(x for x in lib_tutor_names if t.target.matches(d.card[x]))
                reach = ("all your keys" if len(ry) == len(yours) and yours else "; ".join(ry) or "none of yours")                     + (f" (+{len(ri)} inferred)" if ri else "") + (f"; via {', '.join(chain)}" if chain and not t.target.any else "")
                summary["add"].append({"tutor": c["name"], "played": m, "se": se, "finds": reach, "anything": False, "mv": int(c.get("cmc") or 0),
                                       "how": how_used(t), "price": mtg.price_str(c) or "—", "gc": bool(c.get("game_changer"))})
                rows.append([c["name"], f"{100 * m:+.0f}" + ("" if abs(m) >= max(2 * se, 0.01) else " ≈"),
                             reach, int(c.get("cmc") or 0), how_used(t) + (f" ({t.target.describe()})" if not t.target.any else ""),
                             t.dest, mtg.price_str(c) or "—", "GC" if c.get("game_changer") else ""])
            if rows:
                o.note("specific tutors:")
                o.table(["Tutor", "Played: key cards per 100 games", "Finds (your keys; via: tutors it can fetch)", "MV", "How (finds)",
                         "Puts it", "Price", "GC"], rows, right=(1, 3))
            if any_rows:
                o.note("find-anything tutors (every key card, so no list):")
                o.table(["Find-anything tutor", "Played: key cards per 100 games", "MV", "How", "Finds", "Puts it", "Price", "GC"],
                        any_rows, right=(1, 2))
            o.note(f"{pool_n} nonland tutors in the pool reach these key cards; {len(cands)} that goldfish.py reads fully were played (half")
            o.note(f"the most played, half the most efficient: key cards reached per mana), each in a spare inert card's slot, against the")
            o.note(f"same {played['trials']:,} games (≈: within noise or under 1 per 100)."
                   + ("" if gc_ok else " Game Changers left out at this bracket.") + (f" Under ${a.max_price:g}." if a.max_price else ""))
            if unverified:
                is_any = lambda c: any(anything(t) for t in card_tutors(c) if t.dest not in NO_ACCESS)
                o.note("not ranked, because goldfish.py reads them only partly (the games could misjudge them; worth a look by hand):")
                for label, grp in (("specific", [x for x in unverified if not is_any(x[0])]),
                                   ("find-anything", [x for x in unverified if is_any(x[0])])):
                    if grp: o.bullet(f"{label} ({len(grp)}): " + "; ".join(f"{c['name']} ({st_})" for c, r, st_ in grp), 1)
            if worth and res and res[0][0] > 0:
                weakest = min(worth, key=lambda t: worth[t][0])
                best_c = res[0][2]["name"]
                with contextlib.redirect_stdout(io.StringIO()):
                    sw = manasim.simulate_many(a.deck, a.commander, on_play, played["trials"], max(turns), 7,
                                               [(0, False, (), (best_c,), (), "tutors", (weakest,), want)])[0]
                m, se = found_paired(sw, played, keys, T0)
                summary["swap"] = {"out": weakest, "out_worth": worth[weakest][0], "in": best_c, "played": m, "se": se}
                o.note(f"swap: {weakest} (your weakest tutor, {100 * worth[weakest][0]:+.0f}) → {best_c}: "
                       f"{100 * m:+.0f} key cards per 100 games" + ("" if abs(m) >= max(2 * se, 0.01) else " (≈ noise)"))

    if a.json:
        summary["played_trials"] = played["trials"] if played is not None else None
        summary["commander"] = cmd
        json.dump(summary, open(a.json, "w", encoding="utf-8"), indent=1, default=str)


if __name__ == "__main__":
    main()
