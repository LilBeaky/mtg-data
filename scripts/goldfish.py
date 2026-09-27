#!/usr/bin/env python3
"""
goldfish.py — Monte Carlo goldfish simulator for Commander decks (mtg-data).

Plays a decklist alone thousands of times with a greedy pilot and reports how it
develops turn by turn: lands, mana and colors, commander timing, when tracked
cards get cast, and card flow (extra cards, hand size, cards stranded by color,
and which cards produced the card advantage). Full docs: USE_INSTRUCTIONS.md §6.

  python3 scripts/goldfish.py DECK [options]            (run from the repo root)

  --turns N              turns per game (default 8)
  --trials N             games per build (default 2000)
  --draw                 you're on the draw (default: on the play)
  --seed N               RNG seed (default 1); every build replays the same shuffles
  --track "Label=REGEX"  first-cast turn for any card whose name matches REGEX
                         (repeatable; a bare card name also works)
  --variant "Label|Out=>In;Out=>In"   also run a swapped build, side by side (repeatable)
  --kill-commander T     your commander is removed before your turn T (recast with tax)
  --order LIST           cast priority (default commander,track,ramp,draw,other)
  --opps N --opp-casts N --opp-pay P --opp-hand N
                         table model for opponent-triggered cards (defaults: 3 opponents,
                         1 spell each per turn cycle, 50% pay a tax, 4 cards in hand)
  --cast-interaction     also cast held removal / counters / protection spells
  --no-mulligan          keep every opening 7
  --explain              print how each card was modeled, then exit
  --trace N              print a play-by-play of game N (to audit the pilot)
  --json                 machine-readable output

Card behavior is compiled from Oracle text once per card. data/goldfish_overrides.json
replaces the parse for the cards it names. --explain marks each card modeled / partial /
blank; a blank is still cast (it costs its mana) but does nothing.
"""
import argparse, json, os, random, re, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtg

COLORS = "WUBRG"
ALL5 = frozenset(COLORS)
NOC = frozenset()
CLESS = frozenset("C")
WORDNUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "x": "X"}
TYPES = ("Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Instant", "Sorcery", "Battle")
PERMANENT = {"Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"}
BASIC = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
COLOR_WORDS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}
SYM = re.compile(r"\{([^}]+)\}")
OVERRIDES_FILE = os.path.join(mtg.DATA_DIR, "goldfish_overrides.json")
ORDER_DEFAULT = "commander,track,ramp,draw,other"

def num(s, default=1):
    s = (s or "").strip().lower()
    return int(s) if s.isdigit() else WORDNUM.get(s, default)

def parse_cost(cost):
    """'{2}{G}{W/U}{B/P}{X}' -> (generic, [pip color sets], has_x, life).
    Phyrexian pips are paid with life (a goldfish never runs out)."""
    gen, pips, x, life = 0, [], False, 0
    for s in SYM.findall(cost or ""):
        s = s.upper()
        parts = s.split("/")
        if s.isdigit(): gen += int(s)
        elif s == "X": x = True
        elif "P" in parts: life += 2
        elif len(parts) == 2 and parts[0].isdigit(): pips.append(frozenset(parts[1]))
        elif all(p in COLORS or p == "C" for p in parts): pips.append(frozenset(parts))
        else: gen += 1
    return gen, pips, x, life

# ---------------------------------------------------------------- filters
FILTER_OK_WORDS = {"a", "an", "card", "cards", "spell", "spells", "or", "and", "and/or", "your",
                   "any", "number", "of", "one", "two", "three", "up", "to", "with", "different", "names"}

def parse_filter(s):
    """'legendary creature' / 'noncreature' / 'instant or sorcery' / 'white' -> filter dict.
    Words it doesn't know set 'unknown' (callers skip or flag those)."""
    s = (s or "").lower()
    f = {"types": set(), "non": set(), "legendary": False, "colors": set(), "multi": False,
         "historic": False, "mv_max": None, "unknown": False}
    m = re.search(r"with mana value (\d+) or less", s)
    if m: f["mv_max"] = int(m.group(1)); s = s.replace(m.group(0), "")
    if "mana value" in s or "power" in s: f["unknown"] = True
    for w in re.findall(r"[a-z/+\-]+", s):
        t = w.capitalize()
        if w.startswith("non") and w[3:].capitalize() in TYPES: f["non"].add(w[3:].capitalize())
        elif t in TYPES or t.rstrip("s") in TYPES: f["types"].add(t.rstrip("s") if t not in TYPES else t)
        elif w in ("permanent", "permanents"): f["types"] |= PERMANENT
        elif w == "legendary": f["legendary"] = True
        elif w in COLOR_WORDS: f["colors"].add(COLOR_WORDS[w])
        elif w == "multicolored": f["multi"] = True
        elif w == "historic": f["historic"] = True
        elif w not in FILTER_OK_WORDS: f["unknown"] = True
    return f

def spell_ok(k, f):
    if not f: return True
    if f["types"] and not (k.types & f["types"]): return False
    if f["non"] and (k.types & f["non"]): return False
    if f["legendary"] and not k.legendary: return False
    if f["colors"] and not (k.colors & f["colors"]): return False
    if f["multi"] and len(k.colors) < 2: return False
    if f["historic"] and not (k.legendary or "Artifact" in k.types or "Saga" in k.subtypes): return False
    if f["mv_max"] is not None and k.mv > f["mv_max"]: return False
    return True

def land_filter(s):
    s = s.lower()
    return ("basic" in s, frozenset(t for t in BASIC if re.search(r"\b" + t + r"\b", s)))

def land_ok(k, f):
    basic, types = f
    return k.is_land and (not basic or k.basic) and (not types or bool(k.land_types & types))

def restr_ok(r, k, sim):
    if r is None: return True
    if k is None: return False                      # restricted mana can't pay ability costs here
    if r == "creature": return "Creature" in k.types
    if r == "legendary": return k.legendary
    if r == "multi": return len(k.colors) >= 2
    if r == "instsorc": return bool(k.types & {"Instant", "Sorcery"})
    if r == "artifact": return "Artifact" in k.types
    if r == "commander": return k in sim.commanders
    return True

# ---------------------------------------------------------------- effect parser
def dyn_key(what):
    w = what.lower()
    for rx, key in ((r"(\S+) counters? on (?:it|~)", "ctr"), (r"cards? in [^.]*?opponent's hand", "opp_hand"),
                    (r"greatest power", "power"), (r"colors? among", "colors"), (r"lands? you control", "lands"),
                    (r"creatures? you control", "creatures"), (r"artifacts? you control", "artifacts"),
                    (r"enchantments? you control", "enchantments"), (r"permanents? you control", "permanents")):
        m = re.search(rx, w)
        if m: return ("ctr", m.group(1)) if key == "ctr" else (key,)
    return None

OPP_SUBJ = ("target opponent", "each opponent", "an opponent", "that player")
SUBJ = r"(?P<subj>\b(?:target opponent|each opponent|an opponent|that player|target player|each player|you)\s+)?(?:may )?"

def _subj_ok(m):
    return (m.group("subj") or "").strip() not in OPP_SUBJ

def _fx_search(m):
    s = m.group(1)
    head = s.split(" card")[0]
    mc = re.match(r"(up to )?(\w+) ", head + " ")
    count = num(mc.group(2)) if mc and mc.group(2) not in ("a", "an") else 1
    if not isinstance(count, int): count = 1
    dest = ("split" if re.search(r"one onto the battlefield tapped and the other into your hand", s)
            else "top" if "on top" in s else "bf_t" if "onto the battlefield tapped" in s
            else "bf" if "onto the battlefield" in s else "hand")
    if re.search(r"\b(land|plains|island|swamp|mountain|forest|gate)s?\b", head):
        return ("land_search", count, land_filter(head), dest)
    multi = re.findall(r"an? ([a-z]+) card", s)
    if len(multi) > 1 and all(w in COLOR_WORDS for w in multi):
        return ("tutor_multi", [parse_filter(w) for w in multi], dest)
    f = parse_filter(re.sub(r"^(up to )?\w+ ", "", head + " ").strip())
    m = re.search(r"with mana value (\d+) or less", s)
    if m: f["mv_max"] = int(m.group(1))
    if re.search(r"mana value (?:less|greater) than|with power|named|with the same name", s): f["unknown"] = True
    return ("tutor", f, dest, count)

def _fx_mana(m):
    units, _ = parse_prod(m.group(1), ALL5)
    return ("mana", units) if units else None

FX = [
    (re.compile(r"(?:each player |you )?(?:discards? (?:their|your) hand|shuffles? (?:their|your) hand(?: and graveyard)? into (?:their|your) library)(?:,| and)? ?(?:then )?(?:each player |you )?draws? (\w+) cards?"),
     lambda m: ("wheel", num(m.group(1)), "shuffle" in m.group(0))),
    (re.compile(r"discards? (?:their|your) hand,? then draws? cards equal to the greatest number"),
     lambda m: ("wheel", "max", False)),
    (re.compile(SUBJ + r"draws? cards equal to (?:the number of )?(?P<what>[^.;]+)"),
     lambda m: ("draw", dyn_key(m.group("what")) or ("unknown",)) if _subj_ok(m) else None),
    (re.compile(SUBJ + r"draws? (?:a|one) cards? for each (?P<what>[^.;]+)"),
     lambda m: ("draw", dyn_key(m.group("what")) or ("unknown",)) if _subj_ok(m) else None),
    (re.compile(SUBJ + r"draws? (?P<n>a|an|one|two|three|four|five|six|seven|eight|x|\d+) (?:additional )?cards?"),
     lambda m: ("draw", num(m.group("n"))) if _subj_ok(m) else None),
    # Card filtering, not card advantage: Brainstorm-style put-backs and looter discards.
    (re.compile(r"put (a|an|one|two|three|\w+) cards? from your hand on (?:the )?(?:top|bottom) of (?:your|their owner's) library"),
     lambda m: ("putback", num(m.group(1)), "bottom" in m.group(0))),
    (re.compile(r"(?<!whenever you )(?<!if you would )(?<!unless you )(?<!may )(?<!player )(?<!opponent )(?<!opponents )\bdiscard (a|an|one|two|three|x|\d+) cards?"),
     lambda m: ("discard", num(m.group(1)))),
    (re.compile(r"look at the top (\w+) cards? of your library\.? [^.]*?put (a|one|two|three|up to one|up to two|any number) of (?:them|those cards) into your hand"),
     lambda m: ("look", num(m.group(1)), 2 if "two" in m.group(2) else 3 if "three" in m.group(2) else 1)),
    (re.compile(r"search your library for ([^.]+)"), _fx_search),
    (re.compile(r"\bscry (\w+)"), lambda m: ("scry", num(m.group(1)))),
    (re.compile(r"\bsurveil (\w+)"), lambda m: ("surveil", num(m.group(1)))),
    (re.compile(r"you may play an additional land this turn"), lambda m: ("extra_land", 1)),
    (re.compile(r"put (?:a|up to one) land card from your hand onto the battlefield"), lambda m: ("land_from_hand", 1)),
    (re.compile(r"create (a|an|one|two|three|four|five|x|\w+) (?:tapped )?(?:(?:food|clue|blood) token or an? )?treasure tokens?"), lambda m: ("treasure", num(m.group(1)))),
    (re.compile(r"\badd ((?:\{[^}]+\})+|one mana of any color|\w+ mana (?:of any one color|in any combination of colors))"), _fx_mana),
    (re.compile(r"\bproliferate(?:,? then proliferate again| twice)?"),
     lambda m: ("prolif", 2 if ("twice" in m.group(0) or "again" in m.group(0)) else 1)),
    (re.compile(r"put (a|an|one|two|three|\w+) (\S+?) counters? on ~"), lambda m: ("ctr", m.group(2), num(m.group(1)))),
    (re.compile(r"double the number of each kind of counter on"), lambda m: ("double_ctr",)),
    (re.compile(r"you may cast (?:a|an) (?:[\w ]+? )?spell with mana value (\w+) or less from your hand without paying its mana cost"),
     lambda m: ("free_cast", num(m.group(1)))),
]

def parse_fx(s):
    """Effect text -> ([effect tuples in text order], tax). tax = a Rhystic-style
    'unless that player pays' clause (resolved per trigger with --opp-pay)."""
    s = re.sub(r'"[^"]*"', "", s.lower().strip())
    s = re.sub(r"[^.]*\binstead\b[^.]*\.?", "", s).strip()
    tax = bool(re.search(r"unless (?:that player|they) pays?|that player may pay \{", s))
    m = re.search(r"you may pay ((?:\{[^}]+\})+)\. if you do,? (.+)", s)
    if m:
        g, p, _, _ = parse_cost(m.group(1))
        inner, _ = parse_fx(m.group(2))
        pre, _ = parse_fx(s[:m.start()]) if m.start() else ([], False)
        return pre + ([("paid", g, p, inner)] if inner else []), tax
    out, masked = [], s
    for rx, fn in FX:
        for mm in rx.finditer(masked):
            e = fn(mm)
            if e: out.append((mm.start(), e))
        masked = rx.sub(lambda mm: "#" * len(mm.group(0)), masked)
    out.sort(key=lambda t: t[0])
    return [e for _, e in out], tax

def fx_str(e):
    t = e[0]
    if t in ("draw", "scry", "surveil", "prolif", "treasure", "extra_land", "land_from_hand", "free_cast"):
        v = e[1]
        return f"{t} {'/'.join(v) if isinstance(v, tuple) else v}"
    if t == "wheel": return f"wheel {e[1]}"
    if t == "putback": return f"put back {e[1]}" + (" (bottom)" if e[2] else "")
    if t == "discard": return f"discard {e[1]}"
    if t == "look": return f"look {e[1]} take {e[2]}"
    if t == "land_search": return f"land x{e[1]}->{e[3]}"
    if t in ("tutor", "tutor_multi"): return f"{t}->{e[2]}" + (" (filter?)" if t == "tutor" and e[1]["unknown"] else "")
    if t == "mana": return "mana " + "".join("".join(sorted(u)) if len(u) == 1 else "*" for u in e[1])
    if t == "ctr": return f"+{e[2]} {e[1]} ctr"
    if t == "paid": return f"pay {e[1] + len(e[2])}: " + ", ".join(fx_str(x) for x in e[3])
    return t

# ---------------------------------------------------------------- card compiler
RX_MANA = re.compile(r'^(?P<cost>[^:"]*?):\s*(?:(?P<vivid>for each color among permanents you control, add one mana of that color)|add (?P<prod>[^.]+?))\.(?P<rest>.*)$', re.I)
RX_INTERACT = re.compile(r"\b(destroy (?:target|all|each|up to)|exile (?:target|all|each|up to)|counter target|return (?:target|up to|all|each)[^.]*? to (?:its|their) owner(?:'s|s') hands?|deals? (?:\d+|x) damage|gets? -\d+/-\d+|gets? -x/-x|phase out|gains? (?:hexproof|indestructible|protection|shroud)|(?:opponent|player)s? sacrifices?)")
RX_NEUTRAL = re.compile(r"\b(?:ha(?:s|ve)|gains?) (?:indestructible|hexproof|shroud|flying|trample|vigilance|lifelink|deathtouch|haste|ward|first strike|reach|menace)|can't be (?:blocked|countered|the target)|gets? [+-]\d+/[+-]\d+|gets? \+x/\+x|equipped creature|enchanted creature (?:gets|has)|^enchant |protection from|choose a (?:creature type|color|basic land type)|^as ~ enters, choose|for each color among|this spell can't be countered|attacks each combat|you lose \d+ life|you gain \d+ life|if you would get one or more counters")

SUBSTANTIVE = re.compile(r"\b(target|counters?|create|destroy|exile|search|return|damage|copy|discard|put|draw|sacrifice|untap)\b")

def is_neutral(lo):
    """Goldfish-irrelevant line (evasion, pumps, protection, life gain) with no real effect in it."""
    if lo.startswith("if you would get one or more counters"): return True     # player counters
    body = lo.split(":", 1)[1] if ":" in lo else lo
    return bool(RX_NEUTRAL.search(lo)) and not SUBSTANTIVE.search(re.sub(r"indestructible counter|divinity counter", "", body))

class Card:
    """A card compiled into goldfish behavior. Every field has a safe default."""
    def __init__(self, name):
        self.name = name; self.mv = 0; self.gen = 0; self.pips = []; self.x = False; self.life = 0
        self.types = set(); self.subtypes = set(); self.legendary = False; self.colors = NOC
        self.power = 0; self.haste = False; self.loyalty = 0
        self.is_land = False; self.land_types = frozenset(); self.basic = False; self.mdfc = None
        self.units = []          # per tap: [(colors, restricted colors, restriction, colored_only)]
        self.vivid = False; self.convs = []; self.src_sick = False; self.sac_mana = False
        self.etap = None; self.fetch = None; self.bounce = False; self.leyline = False; self.sac_etb = False
        self.ctr_enter = None; self.etb = []; self.castfx = []; self.spell = []
        self.trig = []; self.acts = []; self.pw = []; self.statics = []
        self.requires = None; self.rebound = False; self.hold = False; self.ritual = False
        self.cat = "other"; self.groups = (); self.status = "modeled"; self.notes = []; self.override = False

def strip_reminder(t):
    return re.sub(r"\s*\([^()]*\)", "", t)

def tildify(text, names):
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(r"(?<![\w'])" + re.escape(n) + r"(?![\w'])", "~", text)
    return re.sub(r"\bthis (?:creature|artifact|enchantment|land|permanent|card|spell|aura|equipment|vehicle|planeswalker)\b",
                  "~", text, flags=re.I)

def parse_prod(prod, anyc):
    """'{G}, {W}, or {U}' / '{W}{U}' / 'one mana of any color' / 'two mana in any combination
    of colors' -> ([unit color sets], approximated?)."""
    p = prod.lower().strip()
    m = re.match(r"(\w+) mana (?:in any combination of colors|of any one color)", p)
    if m:
        n = num(m.group(1))
        return [anyc] * (n if isinstance(n, int) else 1), not isinstance(n, int)
    if re.match(r"one mana of any (?:color|type)", p): return [anyc], False
    syms = [x.upper() for x in SYM.findall(prod)]
    if " for each " in p or "equal to" in p or p.startswith("x ") or "amount of" in p:
        return [frozenset(syms[:1]) if syms else anyc], True
    per = [[x.upper() for x in SYM.findall(c)] for c in re.split(r",\s*(?:or\s+)?|\s+or\s+", prod) if SYM.search(c)]
    if not per: return None, False
    width = max(len(x) for x in per)
    return [frozenset(x[i] if i < len(x) else x[-1] for x in per) for i in range(width)], False

def restriction(rest):
    lo = rest.lower()
    colored_only = "can't be spent to pay generic" in lo
    m = re.search(r"spend this mana only (?:to cast|on) ([^.]+)", lo)
    if not m: return None, colored_only
    s = m.group(1)
    for word, key in (("legendary", "legendary"), ("creature", "creature"), ("multicolored", "multi"),
                      ("instant or sorcery", "instsorc"), ("artifact", "artifact"), ("commander", "commander")):
        if word in s: return key, colored_only
    return (None if re.fullmatch(r"(?:a )?spells?", s.strip()) else "unknown"), colored_only

def ab_cost(cost):
    """Ability cost -> (tap, generic, pips, sacrifice ~, (counter kind, n) or None, unparsed?)"""
    lo = cost.lower()
    syms = "".join("{%s}" % s for s in SYM.findall(cost) if s not in ("T", "Q"))
    g, p, _, _ = parse_cost(syms)
    rm = re.search(r"remove (a|an|one|two|three|x|\d+) (\S+?) counters? from ~", lo)
    rest = re.sub(r"\{[^}]+\}|pay \d+ life|sacrifice ~|remove [^,]+? counters? from ~|,|\s", "", lo)
    return "{t}" in lo, g, p, "sacrifice ~" in lo, ((rm.group(2), num(rm.group(1))) if rm else None), bool(rest)

def etap_rule(lo):
    if re.search(r"you may pay \d+ life\. if you don't", lo): return None
    if "two or fewer other lands" in lo: return ("fast",)
    if "two or more other lands" in lo: return ("slow",)
    if "two or more opponents" in lo: return None
    m = re.search(r"unless you control an? (\w+)(?: or (?:an? )?(\w+))?", lo)
    if m and m.group(1) in BASIC: return ("check", frozenset(g for g in m.groups() if g))
    m = re.search(r"(?:unless you|you may) reveal an? (\w+)(?: or (?:an? )?(\w+))? card from your hand", lo)
    if m: return ("reveal", frozenset(g for g in m.groups() if g))
    return ("always", "conditional") if ("unless" in lo or " if " in lo) else ("always",)

def _ctr_mod(m, lo):
    scope_txt, kind_txt = m.group(1), m.group(2)
    scope = None if re.search(r"\bpermanent\b", scope_txt) else frozenset(
        t for t in ("Artifact", "Creature", "Planeswalker") if t.lower() in scope_txt) or None
    kinds = frozenset({"+1/+1"}) if "+1/+1 counter" in lo else None
    return ("ctr_plus" if "plus one" in kind_txt else "ctr_times", scope, kinds)

STATIC_RX = [
    (r"as long as you control (\w+) or more lands, lands you control have \"\{t\}: add one mana of any color",
     lambda m, lo: ("lands_any_n", num(m.group(1)))),
    (r"lands you control are every basic land type", lambda m, lo: ("lands_any",)),
    (r"lands you control have \"\{t\}: add one mana of any color", lambda m, lo: ("lands_any",)),
    (r"you may spend mana as though it were mana of any (?:color|type)", lambda m, lo: ("spend_any",)),
    (r"each nonland permanent you control is all colors", lambda m, lo: ("all_colors",)),
    (r"you may cast spells from your hand without paying their mana costs", lambda m, lo: ("free",)),
    (r"you may pay ((?:\{[^}]+\})+) rather than pay the mana cost for ([\w ]*?)spells you cast",
     lambda m, lo: ("alt", parse_filter(m.group(2)), parse_cost(m.group(1)))),
    (r"^([\w ,]*?)spells you cast cost \{(\d+)\} less to cast\.?$",
     lambda m, lo: ("reduce", parse_filter(m.group(1)), int(m.group(2)))),
    (r"you may play (an|two|three) additional lands? on each of your turns", lambda m, lo: ("extra_land", num(m.group(1)))),
    (r"if you would proliferate, proliferate twice instead", lambda m, lo: ("prolif_x2",)),
    (r"you have no maximum hand size", lambda m, lo: ("no_max_hand",)),
    (r"(?:would put one or more (?:\S+ )?counters on|counters would be put on) ([^,]+?),[^.]*?(that many plus one|twice that many)", _ctr_mod),
    (r"whenever enchanted (?:land|forest|plains|island|swamp|mountain) is tapped for mana, its controller adds an additional (\{\w\}|one mana of [^.]+)",
     lambda m, lo: ("aura_mana", m.group(1))),
]
STATIC_RX = [(re.compile(rx), fn) for rx, fn in STATIC_RX]

def parse_trigger(k, lo):
    """'when ~ enters, ...' / 'whenever you cast ...' / 'at the beginning of ...' -> k fields.
    Trigger tuple: (event, filter, effects, once per turn, tax, also on opponents' turns)."""
    m = re.match(r"^when(?:ever)? ~ enters(?: the battlefield)?( or attacks| or dies)?,\s*(.+)$", lo)
    if m:
        fx, _ = parse_fx(m.group(2)); k.etb += fx
        if m.group(1): k.notes.append("attack/dies half of the trigger not modeled")
        return bool(fx)
    m = re.match(r"^when you cast (?:this spell|~),\s*(.+)$", lo)
    if m:
        fx, _ = parse_fx(m.group(1)); k.castfx += fx; return bool(fx)
    m = re.match(r"^at the beginning of (your|each|each player's) (upkeep|end step|draw step)[^,]*,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(3))
        ev = {"upkeep": "upkeep", "end step": "end", "draw step": "drawstep"}[m.group(2)]
        if fx: k.trig.append((ev, None, fx, False, tax, m.group(1) != "your"))
        return bool(fx)
    m = re.match(r"^whenever you cast (?:or copy )?(a|an|your first|your second)? ?(.*?)spells?(?: each turn)?(?: from [^,]+)?,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(3)); f = parse_filter(m.group(2)) if m.group(2).strip() else None
        if f and f["unknown"]: k.notes.append("cast-trigger filter partly unread: " + m.group(2).strip())
        k.trig.append(("cast", f, fx, "first" in (m.group(1) or ""), tax, False)); return bool(fx)
    m = re.match(r"^whenever (a|an|another|one or more) (?P<subj>.+?) enters?(?: the battlefield)?(?: under your control)?(?: this turn)?,\s*(?P<fx>.+)$", lo)
    if m:
        subj = m.group("subj")
        tm = re.search(r"\b(creature|artifact|enchantment|permanent|land|planeswalker)s?\b", subj)
        if not tm: return False
        fx, tax = parse_fx(m.group("fx"))
        if tm.group(1) == "land":
            k.trig.append(("landfall", None, fx, False, tax, False)); return bool(fx)
        pw = re.search(r"power (\d+) or greater", subj)
        f = {"type": tm.group(1).capitalize(), "another": m.group(1) == "another",
             "power": int(pw.group(1)) if pw else 0}
        k.trig.append(("etb", f, fx, False, tax, False)); return bool(fx)
    m = re.match(r"^whenever you proliferate,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(1)); k.trig.append(("prolif", None, fx, False, tax, False)); return bool(fx)
    m = re.match(r"^whenever an opponent casts (a|an|their first) ?(.*?)spells?(?: each turn)?,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(3)); f = parse_filter(m.group(2)) if m.group(2).strip() else None
        k.trig.append(("opp_cast", f, fx, "first" in m.group(1), tax, False)); return bool(fx)
    m = re.match(r"^whenever an opponent draws a card,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(1)); k.trig.append(("opp_draw", None, fx, False, tax, False)); return bool(fx)
    if re.search(r"attacks|combat damage|blocks", lo): k.notes.append("combat trigger (not modeled)")
    return False

def parse_line(k, L, anyc, abil):
    """One Oracle line -> k fields. True = modeled, False = not modeled, 'neutral' = irrelevant to a goldfish."""
    lo = L.lower()
    m = RX_MANA.match(L)
    if m:
        tap, g, p, sac, rm, other = ab_cost(m.group("cost"))
        if other or rm: return False
        if m.group("vivid"): k.vivid = True; return True
        units, approx = parse_prod(m.group("prod"), anyc)
        if not units: return False
        restr, co = restriction(m.group("rest"))
        if restr == "unknown": k.notes.append("mana restriction not recognized; treated as unrestricted"); restr = None
        if approx: k.notes.append("variable mana amount counted as one")
        if "opponent controls could produce" in lo: k.notes.append("assumes opponents' lands cover your colors")
        if " among " in lo: k.notes.append("'any color among' approximated as any color")
        if sac: k.sac_mana = True
        abil.append((units, restr, co, g + len(p)))
        return True
    if re.search(r"~ enters(?: the battlefield)? tapped|if you don't, (?:it|~) enters tapped", lo):
        k.etap = etap_rule(lo)
        if k.etap == ("always", "conditional"): k.notes.append("conditional enters-tapped read as always tapped")
        return True
    m = re.match(r"^(?:\{t\}, )?(?:pay \d+ life, )?sacrifice ~: search your library for (?:an? |up to one )?(.+?) cards?,.*?put (?:it|that card) onto the battlefield( tapped)?", lo)
    if m and k.is_land:
        k.fetch = (land_filter(m.group(1)), bool(m.group(2))); return True
    if re.search(r"if (?:this card|~) is in your opening hand, you may begin the game with it on the battlefield", lo):
        k.leyline = True; return True
    m = re.search(r"~ enters with (a|an|one|two|three|four|five|six|x|\d+) (\S+?) counters? on it", lo)
    if m:
        k.ctr_enter = (m.group(2), num(m.group(1)), "if you cast it from your hand" in lo); return True
    if re.search(r"when ~ enters, return a land you control to its owner's hand", lo):
        k.bounce = True; return True
    for rx, fn in STATIC_RX:
        m = rx.search(lo)
        if m:
            k.statics.append(fn(m, lo)); return True
    lo2 = re.sub(r"^[a-z][\w' ]* — ", "", lo)
    if lo2.startswith(("when", "whenever", "at the beginning")):
        return parse_trigger(k, lo2) or ("neutral" if is_neutral(lo2) else False)
    m = re.match(r"^([+−\-]?)(\d+|x):\s*(.+)$", lo)
    if m and "Planeswalker" in k.types:
        fx, _ = parse_fx(m.group(3))
        cost = (int(m.group(2)) if m.group(2).isdigit() else 0) * (-1 if m.group(1) in "−-" and m.group(1) else 1)
        if fx: k.pw.append((cost, fx))
        return bool(fx)
    m = re.match(r'^(?P<cost>[^:"]+?):\s*(?P<fx>.+)$', L)
    if m and re.search(r"\{|sacrifice ~|remove |pay \d+ life", m.group("cost").lower()):
        tap, g, p, sac, rm, other = ab_cost(m.group("cost"))
        fx, _ = parse_fx(m.group("fx"))
        if other or not fx: return "neutral" if is_neutral(lo) else False
        if any(e[0] == "tutor" and e[1]["unknown"] for e in fx):
            k.notes.append("tutor filter not fully read; ability not used"); return False
        if not tap and not g and not p and sac and not rm and any(e[0] == "land_search" for e in fx):
            k.etb += fx; k.sac_etb = True; return True        # Sakura-Tribe Elder style: sacrifice at once
        k.acts.append({"tap": tap, "gen": g, "pips": p, "sac": sac, "rm": rm, "fx": fx})
        return True
    if "Aura" in k.subtypes:
        m = re.match(r"^enchant (.+)$", lo)
        if m:
            s = m.group(1)
            k.requires = "legendary creature" if "legendary creature" in s else "creature" if "creature" in s else \
                         "land" if re.search(r"land|forest|plains|island|swamp|mountain", s) else None
            return "neutral"
    if k.types & {"Instant", "Sorcery"} or "Addendum" in L:
        fx, _ = parse_fx(lo)
        if fx:
            k.spell += fx; return True
    return "neutral" if is_neutral(lo) else False

def compile_card(c, anyc):
    faces = c.get("card_faces") or []
    face = dict(faces[0]) if faces and c.get("layout") != "normal" else c
    k = Card(c["name"])
    k.mv = int(c.get("cmc") or 0)
    tl = face.get("type_line") or c.get("type_line", "")
    main, _, sub = tl.partition("—")
    k.types = {t for t in TYPES if t in main}
    k.subtypes = set(sub.split())
    k.legendary, k.basic = "Legendary" in main, "Basic" in main
    k.is_land = "Land" in k.types
    k.land_types = frozenset(t.lower() for t in k.subtypes if t.lower() in BASIC)
    k.gen, k.pips, k.x, k.life = parse_cost(face.get("mana_cost") or c.get("mana_cost") or "")
    k.colors = frozenset(face.get("colors") or c.get("colors") or [])
    pw = face.get("power") or c.get("power")
    k.power = int(pw) if pw and str(pw).isdigit() else 0
    kws = [w.lower() for w in (c.get("keywords") or [])]
    k.haste, k.rebound = "haste" in kws, "rebound" in kws
    loy = face.get("loyalty") or c.get("loyalty")
    k.loyalty = int(loy) if loy and str(loy).isdigit() else 0
    text = tildify(strip_reminder(face.get("oracle_text") or c.get("oracle_text") or ""),
                   [c["name"], face.get("name", ""), c["name"].split(",")[0].split(" // ")[0]])
    abil, done, missed = [], 0, 0
    for L in (l.strip() for l in text.split("\n")):
        if not L: continue
        r = parse_line(k, L, anyc, abil)
        if r is True: done += 1
        elif r is False:
            if all(any(part.strip().startswith(w) for w in kws) for part in re.split(r"[,;]", L.lower()) if part.strip()):
                continue                                   # keyword line (Flying, Ward {2}, Equip {1}...)
            missed += 1; k.notes.append("unmodeled: " + L[:72])
    if k.is_land and k.land_types:
        abil.append(([frozenset(BASIC[t] for t in k.land_types)], None, False, 0))
    plain = [a for a in abil if not a[3]]
    for units, restr, co, cost in abil:
        if cost:
            k.convs.append((cost, [(NOC, u, restr, co) if restr else (u, NOC, None, co) for u in units]))
    if len(plain) == 1:
        units, restr, co, _ = plain[0]
        k.units = [(NOC, u, restr, co) if restr else (u, NOC, None, co) for u in units]
    elif plain:
        if all(len(a[0]) == 1 for a in plain):
            cols = frozenset().union(*(a[0][0] for a in plain if not a[1]))
            rc = [a for a in plain if a[1]]
            k.units = [(cols, frozenset().union(*(a[0][0] for a in rc)) if rc else NOC,
                        rc[0][1] if rc else None, all(a[2] for a in plain))]
        else:
            units, restr, co, _ = max(plain, key=lambda a: len(a[0]))
            k.units = [(u, NOC, None, co) for u in units]
            k.notes.append("several mana abilities; modeled the biggest")
    for st in [s for s in k.statics if s[0] == "aura_mana"]:
        u, _ = parse_prod(st[1], anyc)
        k.units += [(x, NOC, None, False) for x in (u or [anyc])]
    if k.is_land and not k.units and not k.fetch and c.get("produced_mana"):
        k.units = [(frozenset(c["produced_mana"]) & (anyc | CLESS) or CLESS, NOC, None, False)]
        k.notes.append("mana read from produced_mana")
    if len(faces) > 1 and c.get("layout") == "modal_dfc" and "Land" in (faces[1].get("type_line") or "") and not k.is_land:
        back = dict(faces[1]); back.setdefault("cmc", 0)
        k.mdfc = compile_card(dict(back, name=faces[1]["name"], layout="normal", keywords=c.get("keywords")), anyc)
    if k.types & {"Instant", "Sorcery"}:
        k.ritual = bool(k.spell) and all(e[0] == "mana" for e in k.spell)
        k.hold = bool(RX_INTERACT.search(text.lower())) and not k.ritual
    categorize(k)
    k.status = "blank" if missed and not done and not k.units else "partial" if missed else "modeled"
    if k.hold: k.status = "held"
    return k

def categorize(k):
    fxs = k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f]
    kinds = {e[0] for e in fxs}
    ramp = (not k.is_land and (k.units or k.vivid or k.convs)) or kinds & {"land_search", "extra_land", "land_from_hand", "treasure"} \
        or any(s[0] in ("lands_any", "lands_any_n", "spend_any", "reduce", "alt", "free", "extra_land") for s in k.statics)
    draws = kinds & {"draw", "look", "tutor", "tutor_multi", "wheel"}
    k.cat = "ramp" if ramp and not k.ritual else "draw" if draws else "other"

def apply_override(k, spec, anyc):
    """Replace parsed fields with an entry from goldfish_overrides.json (see §6 of the docs)."""
    def col(s): return anyc if s == "any" else frozenset(s)
    k.override = True
    if spec.get("skip"):
        k.units, k.convs, k.etb, k.spell, k.trig, k.acts, k.pw, k.statics = [], [], [], [], [], [], [], []
        k.status = "blank"
    if "mana" in spec:
        k.units = []
        for m in spec["mana"]:
            u = col(m.get("colors", "any"))
            r = m.get("restrict")
            k.units += [((NOC, u, r, m.get("colored_only", False)) if r else (u, NOC, None, m.get("colored_only", False)))] * m.get("count", 1)
            k.src_sick = m.get("sick", False)
    for field in ("etb", "spell"):
        if field in spec: setattr(k, field, [e for s in spec[field] for e in dsl(s)])
    if "triggers" in spec:
        k.trig = [(t["on"], parse_filter(t["filter"]) if t.get("filter") else None,
                   [e for s in t["do"] for e in dsl(s)], t.get("once", False), t.get("tax", False), t.get("each", False))
                  for t in spec["triggers"]]
    if "activated" in spec:
        k.acts = []
        for a in spec["activated"]:
            g, p, _, _ = parse_cost(a.get("cost", ""))
            rm = a.get("remove")
            k.acts.append({"tap": a.get("tap", False), "gen": g, "pips": p, "sac": a.get("sac", False),
                           "rm": (rm.split()[0], int(rm.split()[1])) if rm else None,
                           "fx": [e for s in a["do"] for e in dsl(s)]})
    categorize(k)
    for key in ("hold", "requires", "cat"):
        if key in spec: setattr(k, key, spec[key])
    if "status" in spec: k.status = spec["status"]
    elif not spec.get("skip"): k.status = "modeled"
    if spec.get("note"): k.notes = ["override: " + spec["note"]] + [n for n in k.notes if not n.startswith("unmodeled")]

def dsl(s):
    """Override effect strings: 'draw 2', 'draw permanents', 'scry 2', 'look 3 1', 'prolif 1',
    'treasure 1', 'extra_land 1', 'land basic bf_t 1', 'ctr divinity 1', 'mana WUBRG'."""
    w = s.split()
    t = w[0]
    if t == "draw": return [("draw", int(w[1]) if w[1].isdigit() else (w[1],))]
    if t in ("scry", "surveil", "prolif", "treasure", "extra_land", "land_from_hand"): return [(t, int(w[1]))]
    if t == "look": return [("look", int(w[1]), int(w[2]))]
    if t == "land": return [("land_search", int(w[3]) if len(w) > 3 else 1, land_filter(w[1]), w[2])]
    if t == "ctr": return [("ctr", w[1], int(w[2]))]
    if t == "mana": return [("mana", [frozenset(ch) for ch in w[1]])]
    raise ValueError("goldfish override: unknown effect " + repr(s))

# ---------------------------------------------------------------- mana solver
def solve(cands, pips, gen):
    """cands: [(pool index, usable colors, colored_only)]. Colored pips by bipartite
    matching (least flexible unit first), generic from leftovers. -> [indices] or None."""
    if len(pips) + gen > len(cands): return None
    order = sorted(range(len(cands)), key=lambda i: len(cands[i][1]))
    match = {}
    def aug(j, seen):
        pj = pips[j]
        for i in order:
            if i in seen or not (cands[i][1] & pj): continue
            seen.add(i)
            if i not in match or aug(match[i], seen):
                match[i] = j; return True
        return False
    for j in sorted(range(len(pips)), key=lambda j: len(pips[j])):
        if not aug(j, set()): return None
    rest = [i for i in order if i not in match and not cands[i][2]]
    if len(rest) < gen: return None
    return [cands[i][0] for i in list(match) + rest[:gen]]

class Perm:
    __slots__ = ("k", "tapped", "sick", "ctr", "hand", "once")
    def __init__(self, k, tapped=False, sick=False, hand=False):
        self.k, self.tapped, self.sick, self.hand, self.ctr, self.once = k, tapped, sick, hand, None, None
    def copy(self):
        p = Perm(self.k, self.tapped, self.sick, self.hand)
        p.ctr = dict(self.ctr) if self.ctr else None
        p.once = set(self.once) if self.once else None
        return p

class Statics:
    def __init__(self, perms):
        self.lands_any = False; self.lands_any_n = 0; self.spend_any = False; self.all_colors = False
        self.free = False; self.alts = []; self.reduce = []; self.extra_land = 0; self.prolif = 1
        self.plus = []; self.times = []; self.no_max = False
        for p in perms:
            for s in p.k.statics:
                t = s[0]
                if t == "lands_any": self.lands_any = True
                elif t == "lands_any_n": self.lands_any_n = min(self.lands_any_n or 99, s[1])
                elif t == "spend_any": self.spend_any = True
                elif t == "all_colors": self.all_colors = True
                elif t == "free": self.free = True
                elif t == "alt": self.alts.append((s[1], s[2]))
                elif t == "reduce": self.reduce.append((s[1], s[2]))
                elif t == "extra_land": self.extra_land += s[1]
                elif t == "prolif_x2": self.prolif *= 2
                elif t == "ctr_plus": self.plus.append((s[1], s[2]))
                elif t == "ctr_times": self.times.append((s[1], s[2]))
                elif t == "no_max_hand": self.no_max = True

OPP_CREATURE, OPP_SPELL = Card("opponent creature spell"), Card("opponent noncreature spell")
OPP_CREATURE.types, OPP_SPELL.types = {"Creature"}, {"Instant"}

# ---------------------------------------------------------------- one game
class Game:
    def __init__(self, sim, hand, lib, rng):
        self.sim, self.hand, self.lib, self.rng = sim, hand, lib, rng
        self.gy, self.lands, self.perms, self.cmd = [], [], [], list(sim.commanders)
        self.cmd_casts = Counter(); self.turn = 0; self.phase = 0; self.drops = 0; self.treasures = 0
        self.pool = None; self.convs = []; self.dry = False; self._st = None
        self.extra = 0; self.drawn = len(hand); self.casts = 0; self.spent = 0; self.disc = 0
        self.attr = Counter(); self.first = {}; self.cmd_first = {}; self.rebound = []
        self.log = None

    @property
    def st(self):
        if self._st is None: self._st = Statics(self.perms + self.lands)
        return self._st

    def clone(self):
        g = Game.__new__(Game)
        g.__dict__.update(self.__dict__)
        mp = {id(p): p.copy() for p in self.lands + self.perms}
        g.lands = [mp[id(p)] for p in self.lands]; g.perms = [mp[id(p)] for p in self.perms]
        g.hand, g.lib, g.gy, g.cmd, g.rebound = self.hand[:], self.lib[:], self.gy[:], self.cmd[:], self.rebound[:]
        g.cmd_casts = Counter(self.cmd_casts); g.first = dict(self.first); g.cmd_first = dict(self.cmd_first)
        g.attr = Counter(); g.pool = None; g.convs = []; g._st = None
        g.rng = self.sim.dry_rng; g.log = None
        return g

    # ---- mana
    def any_lands(self):
        st = self.st
        return st.lands_any or (st.lands_any_n and len(self.lands) >= st.lands_any_n)

    def perm_colors(self):
        if self.st.all_colors and any(not p.k.is_land for p in self.perms): return set(self.sim.anyc)
        return set().union(*(p.k.colors for p in self.perms)) if self.perms else set()

    def usable(self, p):
        k = p.k
        if p.tapped: return False
        if p.sick and (("Creature" in k.types and not k.haste) or k.src_sick): return False
        return True

    def add_units(self, p, anyl=None):
        k, pool = p.k, self.pool
        if k.is_land and (self.any_lands() if anyl is None else anyl):
            cols = self.sim.anyc.union(*(u[0] | u[1] for u in k.units)) if k.units else self.sim.anyc
            for _ in range(max(1, len(k.units))): pool.append([cols, NOC, None, False, p, False])
        else:
            for u in k.units: pool.append([u[0], u[1], u[2], u[3], p, False])
            if k.vivid:
                for col in self.perm_colors(): pool.append([frozenset(col), NOC, None, False, p, False])
        for cost, outs in k.convs: self.convs.append((p, cost, outs))

    def build_pool(self):
        self.pool, self.convs = [], []
        anyl = self.any_lands()
        for p in self.lands:
            if not p.tapped: self.add_units(p, anyl)
        for p in self.perms:
            if self.usable(p): self.add_units(p)
        for _ in range(self.treasures): self.pool.append([self.sim.anyc, NOC, None, False, "T", False])
        self.eager_convs()

    def eager_convs(self):
        """Net-positive filters (Signets) are always worth running: pay with the least flexible unit."""
        for conv in list(self.convs):
            p, cost, outs = conv
            if len(outs) <= cost or p.tapped or any(u[4] is p for u in self.pool): continue
            c = sorted((x for x in self.cands(None) if not x[2]), key=lambda x: len(x[1]))
            if len(c) < cost: continue
            for x in c[:cost]: self.use_unit(x[0])
            p.tapped = True
            self.convs.remove(conv)
            for o in outs: self.pool.append([o[0], o[1], o[2], o[3], None, False])

    def cands(self, k, pool=None):
        pool = self.pool if pool is None else pool
        sa, anyc, sim, out = self.st.spend_any, self.sim.anyc, self.sim, []
        for i, u in enumerate(pool):
            if u[5]: continue
            eff = u[0] | u[1] if (u[1] and restr_ok(u[2], k, sim)) else u[0]
            if not eff: continue
            if sa: eff = eff | anyc
            out.append((i, eff, u[3]))
        return out

    def use_unit(self, i, pool=None):
        pool = self.pool if pool is None else pool
        u = pool[i]; u[5] = True
        if u[4] == "T": self.treasures -= 1
        elif u[4] is not None:
            u[4].tapped = True
            if u[4].k.sac_mana and u[4] in self.perms:
                self.perms.remove(u[4]); self.gy.append(u[4].k); self._st = None

    def pay(self, k, gen, pips, commit=True):
        sel = solve(self.cands(k), pips, gen)
        if sel is None:
            return self.pay_conv(k, gen, pips, commit) if self.convs else False
        if commit:
            for i in sel: self.use_unit(i)
        return True

    def pay_conv(self, k, gen, pips, commit):
        """Filter lands / converters (Great Hall, Crystal Quarry): try each once."""
        for conv in self.convs:
            p, cost, outs = conv
            own = [i for i, u in enumerate(self.pool) if u[4] is p]
            if p.tapped and not own or any(self.pool[i][5] for i in own): continue
            c = sorted((x for x in self.cands(None) if x[0] not in own and not x[2]), key=lambda x: len(x[1]))
            if len(c) < cost: continue
            payers = [x[0] for x in c[:cost]]
            trial = [u[:] for u in self.pool]
            for i in own + payers: trial[i][5] = True
            trial += [[o[0], o[1], o[2], o[3], None, False] for o in outs]
            if solve(self.cands(k, trial), pips, gen) is None: continue
            if commit:
                for i in own + payers: self.use_unit(i)
                p.tapped = True
                self.convs.remove(conv)
                self.pool += [[o[0], o[1], o[2], o[3], None, False] for o in outs]
                for i in solve(self.cands(k), pips, gen): self.use_unit(i)
            return True
        return False

    # ---- casting
    def options(self, k, zone):
        st = self.st
        tax = 2 * self.cmd_casts[k] if zone == "cmd" else 0
        red = sum(n for f, n in st.reduce if spell_ok(k, f))
        xm = 2 if k.x else 0                          # X spells wait for X >= 2
        opts = [(max(0, k.gen - red) + tax + xm, k.pips)]
        for f, (ag, ap, _, _) in st.alts:
            if spell_ok(k, f): opts.append((max(0, ag - red) + tax, ap))
        if st.free and zone == "hand": opts.append((0, []))
        return sorted(opts, key=lambda o: o[0] + len(o[1]))

    def has(self, req):
        if req == "land": return bool(self.lands)
        leg = req.startswith("legendary")
        return any("Creature" in p.k.types and (p.k.legendary or not leg) for p in self.perms)

    def try_cast(self, k, zone):
        if k.requires and not self.has(k.requires): return False
        for gen, pips in self.options(k, zone):
            if self.pay(k, gen, pips):
                x = 0
                if k.x:
                    rest = [x_[0] for x_ in self.cands(k) if not x_[2]]
                    for i in rest: self.use_unit(i)
                    x = len(rest) + 2
                self.resolve(k, zone, gen + len(pips) + x - (2 if k.x else 0), x)
                return True
        return False

    def resolve(self, k, zone, paid, x=0):
        if zone == "hand": self.hand.remove(k)
        elif zone == "cmd":
            self.cmd.remove(k); self.cmd_casts[k] += 1; self.cmd_first.setdefault(k.name, self.turn)
        self.casts += 1; self.spent += paid
        self.note(f"  cast {k.name} ({zone}, paid {paid})")
        for gi in k.groups: self.first.setdefault(gi, self.turn)
        self.fire("cast", k)
        if k.castfx: self.do(k.castfx, k, None, x)
        if k.types & PERMANENT:
            self.enter(k, from_hand=(zone == "hand"), x=x)
        else:
            self.do(k.spell, k, None, x)
            (self.rebound if k.rebound and zone == "hand" else self.gy).append(k)

    def enter(self, k, from_hand=False, x=0):
        if k.is_land: return self.land_enters(k)
        prev_drops = self.st.extra_land
        p = Perm(k, tapped=bool(k.etap), sick=True, hand=from_hand)
        self.perms.append(p); self._st = None
        if self.st.extra_land > prev_drops:        # Exploration/Azusa give their drops this turn
            self.drops += self.st.extra_land - prev_drops
        if k.ctr_enter:
            kind, n, if_cast = k.ctr_enter
            if from_hand or not if_cast: self.add_ctr(p, kind, x if n == "X" else n)
        if k.loyalty: self.add_ctr(p, "loyalty", k.loyalty)
        if self.pool is not None:
            if k.statics:
                if self.any_lands():
                    for u in self.pool:
                        if not u[5] and isinstance(u[4], Perm) and u[4].k.is_land:
                            u[0], u[1], u[2] = self.sim.anyc | u[0] | u[1], NOC, None
            if self.usable(p): self.add_units(p); self.eager_convs()
        if k.etb: self.do(k.etb, k, p)
        if k.sac_etb and p in self.perms: self.perms.remove(p); self.gy.append(k); self._st = None
        self.fire("etb", p)
        return p

    def etapped(self, k):
        r = k.etap
        if r is None: return False
        if r[0] == "always": return True
        if r[0] == "fast": return len(self.lands) > 2
        if r[0] == "slow": return len(self.lands) < 2
        if r[0] == "check": return not (self.any_lands() or any(p.k.land_types & r[1] for p in self.lands))
        if r[0] == "reveal": return not any(c.is_land and c.land_types & r[1] for c in self.hand)
        return True

    def land_enters(self, k, force_tapped=False):
        p = Perm(k, tapped=force_tapped or self.etapped(k))
        self.lands.append(p)
        if k.statics: self._st = None
        if self.pool is not None and not p.tapped: self.add_units(p); self.eager_convs()
        if k.bounce:
            others = [q for q in self.lands if q is not p]
            back = min(others, key=lambda q: (len(q.k.units) > 1, len(q.k.units[0][0]) if q.k.units else 0)) if others else p
            self.lands.remove(back); self.hand.append(back.k)
        if k.etb: self.do(k.etb, k, p)
        self.fire("landfall", p)
        if k.fetch:
            filt, tapped = k.fetch
            targets = [c for c in self.lib if land_ok(c, filt)]
            if targets:
                if self.pool is not None:
                    for u in self.pool:
                        if u[4] is p: u[5] = True
                self.lands.remove(p); self.gy.append(k)
                have = self.land_colors()
                t = max(targets, key=lambda c: (len(self.colors_of(c) - have), not self.etapped(c)))
                self.lib.remove(t); self.rng.shuffle(self.lib)
                self.land_enters(t, force_tapped=tapped)
        return p

    def play_land(self, k):
        self.hand.remove(k); self.drops -= 1
        self.note(f"  land {k.name}" + (" (tapped)" if self.etapped(k.mdfc if (k.mdfc and not k.is_land) else k) else ""))
        self.land_enters(k.mdfc if (k.mdfc and not k.is_land) else k)

    def colors_of(self, k):
        if k.fetch: return set().union(*(self.colors_of(c) for c in self.sim.land_cards if land_ok(c, k.fetch[0])))
        return set().union(*(u[0] | u[1] for u in k.units)) - {"C"} if k.units else set()

    def land_colors(self):
        if self.any_lands(): return set(self.sim.anyc)
        return set().union(*(self.colors_of(p.k) for p in self.lands)) if self.lands else set()

    def choose_land(self):
        uniq = list(dict.fromkeys(self.hand))
        lands = [k for k in uniq if k.is_land]
        if not lands:
            md = [k for k in uniq if k.mdfc]
            return min(md, key=lambda k: self.value(k)) if md else None
        if len(lands) == 1: return lands[0]
        have = self.land_colors()
        score = lambda k: (len(self.colors_of(k) - have), bool(k.fetch), len(self.colors_of(k)), -len(k.units))
        tap = [k for k in lands if self.etapped(k)]
        unt = [k for k in lands if not self.etapped(k)]
        bt = max(tap, key=score) if tap else None
        bu = max(unt, key=score) if unt else None
        if not bt or not bu or self.dry: return bu or bt
        return bu if self.dry_score(bu) > self.dry_score(bt) else bt

    def dry_score(self, land):
        g = self.clone(); g.dry = True
        g.play_land(land); g.build_pool(); g.cast_loop(activate=False)
        return (len(g.cmd_first) - len(self.cmd_first), len(g.first) - len(self.first), g.spent - self.spent)

    def cast_loop(self, activate=True):
        sim = self.sim
        while True:
            if self.drops > 0 and any(c.is_land for c in self.hand):
                self.play_land(self.choose_land() if not self.dry else next(c for c in self.hand if c.is_land))
                continue
            avail = sum(1 for u in self.pool if not u[5])
            cands = []
            for k in dict.fromkeys(self.hand):
                if k.is_land or k.ritual or (k.hold and not sim.cast_hold): continue
                cands.append((sim.prio(k, "hand"), k, "hand"))
            for k in self.cmd: cands.append((sim.prio(k, "cmd"), k, "cmd"))
            cands.sort(key=lambda t: t[0])
            for _, k, zone in cands:
                if min(g_ + len(p_) for g_, p_ in self.options(k, zone)) > avail: continue
                if self.try_cast(k, zone): break
            else:
                if not self.try_ritual(cands): break
        if activate: self.activations()

    def try_ritual(self, cands):
        for r in dict.fromkeys(c for c in self.hand if c.ritual):
            for gen, pips in self.options(r, "hand"):
                sel = solve(self.cands(r), pips, gen)
                if sel is None: continue
                trial = [u[:] for u in self.pool]
                for i in sel: trial[i][5] = True
                for e in r.spell: trial += [[u, NOC, None, False, None, False] for u in e[1]]
                if any(solve(self.cands(k, trial), p_, g_) is not None
                       for _, k, z in cands for g_, p_ in self.options(k, z)):
                    for i in sel: self.use_unit(i)
                    self.resolve(r, "hand", gen + len(pips))
                    return True
        return False

    def stranded(self):
        n, avail = 0, sum(1 for u in self.pool if not u[5])
        for k in set(self.hand):
            if k.is_land or k.hold or k.ritual: continue
            opts = self.options(k, "hand")
            if min(g_ + len(p_) for g_, p_ in opts) > avail or (k.requires and not self.has(k.requires)): continue
            if any(self.pay(k, g_, p_, commit=False) for g_, p_ in opts): continue
            n += self.hand.count(k)
        return n

    def activations(self):
        prolif_useful = any(p.ctr for p in self.perms + self.lands) or any(
            t[0] == "prolif" for p in self.perms for t in p.k.trig)
        for p in list(self.perms) + list(self.lands):
            k = p.k
            for ab in k.acts:
                fx = ab["fx"]; kinds = {e[0] for e in fx}
                if not (kinds & {"draw", "look", "tutor", "tutor_multi", "land_search", "treasure"}
                        or ("prolif" in kinds and prolif_useful) or ("ctr" in kinds and "draw" in kinds)):
                    continue
                if ab["sac"] and "draw" in kinds and not (len(self.hand) <= 1 and self.turn >= 5): continue
                for _ in range(1 if (ab["tap"] or ab["sac"]) else 3):
                    if p not in self.perms and p not in self.lands: break
                    if ab["tap"] and (p.tapped or not self.usable(p) and not k.is_land): break
                    if ab["rm"]:
                        kind, n = ab["rm"]
                        keep = 1 if kind in ("divinity", "indestructible") else 0
                        if (p.ctr or {}).get(kind, 0) - n < keep: break
                    if not self.pay(None, ab["gen"], ab["pips"]): break
                    if ab["tap"]:
                        p.tapped = True
                        for u in self.pool:
                            if u[4] is p: u[5] = True
                    if ab["rm"]: p.ctr[ab["rm"][0]] -= ab["rm"][1]
                    if ab["sac"]:
                        (self.lands if k.is_land else self.perms).remove(p); self.gy.append(k); self._st = None
                    self.do(fx, k, p)
            if k.pw and p in self.perms:
                loy = (p.ctr or {}).get("loyalty", 0)
                opts = [(("draw" in {e[0] for e in fx}) * 2 + (cost > 0), cost, fx) for cost, fx in k.pw if loy + cost >= 1]
                if opts:
                    _, cost, fx = max(opts, key=lambda o: (o[0], o[1]))
                    if cost > 0: self.add_ctr(p, "loyalty", cost)
                    else: p.ctr["loyalty"] = loy + cost
                    self.do(fx, k, p)

    # ---- effects
    def note(self, msg):
        if self.log is not None and not self.dry: self.log.append(msg)

    def gain(self, n, name):
        self.extra += n; self.attr[name] += n
        self.note(f"    {n:+d} card(s) from {name}")

    def draw(self, n, name=None):
        if self.dry or n <= 0: return
        n = min(n, len(self.lib))
        for _ in range(n): self.hand.append(self.lib.pop())
        if name: self.gain(n, name)
        else: self.drawn += n

    def val(self, v, p, x):
        if isinstance(v, int): return v
        if v == "X": return x
        key = v[0]
        if key == "lands": return len(self.lands)
        if key == "permanents": return len(self.lands) + len(self.perms)
        if key == "creatures": return sum("Creature" in q.k.types for q in self.perms)
        if key == "artifacts": return sum("Artifact" in q.k.types for q in self.perms)
        if key == "enchantments": return sum("Enchantment" in q.k.types for q in self.perms)
        if key == "opp_hand": return self.sim.opp_hand
        if key == "power": return max((q.k.power + (q.ctr or {}).get("+1/+1", 0) for q in self.perms if "Creature" in q.k.types), default=0)
        if key == "colors": return len(self.perm_colors())
        if key == "ctr": return (p.ctr or {}).get(v[1], 0) if isinstance(p, Perm) else 0
        return 1

    def value(self, k):
        """Pilot's sense of a card's worth right now (scry, look, tutor, bottom, discard)."""
        if k.groups and any(gi not in self.first for gi in k.groups): return 100
        if k.is_land:
            need = min(self.turn + 3, 7) - len(self.lands) - sum(c.is_land for c in self.hand)
            return 70 if need > 0 else 10
        if k.cat == "ramp": return 55 if len(self.lands) < 6 else 20
        if k.cat == "draw": return 45
        if k.hold: return 35
        return 40 + min(k.mv, 7) if k.mv <= len(self.lands) + 2 else 20

    def do(self, fx, k, p=None, x=0):
        name = k.name
        for e in fx:
            t = e[0]
            if t == "draw": self.draw(self.val(e[1], p, x), name)
            elif t == "wheel":
                if self.dry: continue
                size = len(self.hand)
                if e[2]:
                    self.lib += self.hand + self.gy; self.gy = []; self.rng.shuffle(self.lib)
                else: self.gy += self.hand
                n = e[1] if isinstance(e[1], int) else max(size, self.sim.opp_hand)
                self.hand = []; self.draw(n)                       # count only the net gain
                self.gain(max(0, n - size), name)
            elif t in ("scry", "surveil"):
                n = self.val(e[1], p, x)
                if self.dry or n <= 0: continue
                top = [self.lib.pop() for _ in range(min(n, len(self.lib)))]
                bad = [c for c in top if self.value(c) < 40]
                (self.gy if t == "surveil" else self.lib)[0:0] = bad
                self.lib += sorted((c for c in top if self.value(c) >= 40), key=self.value)
            elif t == "look":
                if self.dry: continue
                top = sorted((self.lib.pop() for _ in range(min(e[1], len(self.lib)))), key=self.value, reverse=True)
                self.hand += top[:e[2]]; self.gain(len(top[:e[2]]), name); self.lib[0:0] = top[e[2]:]
            elif t == "land_search":
                _, count, filt, dest = e
                for i in range(count):
                    targets = [c for c in self.lib if land_ok(c, filt)]
                    if not targets: break
                    have = self.land_colors() | {BASIC[tt] for c in self.hand if c.is_land for tt in c.land_types}
                    pick = max(targets, key=lambda c: (len(self.colors_of(c) - have), not self.etapped(c)))
                    self.lib.remove(pick)
                    if dest == "hand" or (dest == "split" and i == 1): self.hand.append(pick); self.gain(1, name)
                    elif dest == "top": self.lib.append(pick)
                    else: self.land_enters(pick, force_tapped=dest in ("bf_t", "split"))
                if dest != "top": self.rng.shuffle(self.lib)
            elif t in ("tutor", "tutor_multi"):
                filts = [e[1]] * e[3] if t == "tutor" else e[1]
                picks = []
                for f in filts:
                    if f["unknown"]: continue
                    targets = [c for c in self.lib if spell_ok(c, f)]
                    if targets:
                        pick = max(targets, key=self.value); self.lib.remove(pick); picks.append(pick)
                self.rng.shuffle(self.lib)
                for c in picks:
                    if e[2] == "top": self.lib.append(c)
                    elif e[2] in ("bf", "bf_t"):
                        if c.types & PERMANENT: self.enter(c)
                        else: self.hand.append(c); self.gain(1, name)
                    else: self.hand.append(c); self.gain(1, name)
            elif t in ("putback", "discard"):
                n = self.val(e[1], p, x)
                if self.dry or not isinstance(n, int) or n <= 0: continue
                n = min(n, len(self.hand))
                worst = sorted(self.hand, key=self.value)[:n]
                for c in worst: self.hand.remove(c)
                if t == "discard": self.gy += worst
                elif e[2]: self.lib[0:0] = worst          # bottom
                else: self.lib += worst                   # top (drawn next)
                self.gain(-n, name)                       # filtering, not advantage
            elif t == "extra_land": self.drops += e[1]
            elif t == "land_from_hand":
                ls = [c for c in self.hand if c.is_land]
                if ls:
                    c = max(ls, key=lambda c: len(self.colors_of(c) - self.land_colors()))
                    self.hand.remove(c); self.land_enters(c)
            elif t == "treasure":
                n = self.val(e[1], p, x); self.treasures += n
                if self.pool is not None:
                    self.pool += [[self.sim.anyc, NOC, None, False, "T", False] for _ in range(n)]
            elif t == "mana":
                if self.pool is not None:
                    self.pool += [[u & (self.sim.anyc | CLESS) or u, NOC, None, False, None, False] for u in e[1]]
            elif t == "prolif": self.proliferate(e[1])
            elif t == "ctr":
                if isinstance(p, Perm): self.add_ctr(p, e[1], self.val(e[2], p, x))
            elif t == "double_ctr":
                for q in self.perms + self.lands:
                    if q.ctr:
                        for kind, n in list(q.ctr.items()): self.add_ctr(q, kind, n)
            elif t == "free_cast":
                opts = [c for c in dict.fromkeys(self.hand) if not c.is_land and not c.hold and c.mv <= e[1]
                        and not (c.requires and not self.has(c.requires))]
                if opts: self.resolve(min(opts, key=lambda c: self.sim.prio(c, "hand")), "hand", 0)
            elif t == "paid":
                if self.pool is not None and self.pay(None, e[1], e[2]): self.do(e[3], k, p, x)

    def add_ctr(self, p, kind, n):
        if not isinstance(n, int) or n <= 0: return
        st = self.st
        for scope, kinds in st.plus:
            if (kinds is None or kind in kinds) and (scope is None or p.k.types & scope): n += 1
        for scope, kinds in st.times:
            if (kinds is None or kind in kinds) and (scope is None or p.k.types & scope): n *= 2
        if p.ctr is None: p.ctr = {}
        p.ctr[kind] = p.ctr.get(kind, 0) + n

    def proliferate(self, n=1):
        for _ in range(n * self.st.prolif):
            for q in self.perms + self.lands:
                if q.ctr:
                    for kind in [kk for kk, v in q.ctr.items() if v > 0]: self.add_ctr(q, kind, 1)
            self.fire("prolif")

    def fire(self, event, obj=None, each_only=False):
        for p in list(self.perms):
            for ev, filt, fx, once, tax, each in p.k.trig:
                if ev != event or (each_only and not each): continue
                if event in ("cast", "opp_cast") and filt and not spell_ok(obj, filt): continue
                if event == "etb":
                    ok = filt["type"] == "Permanent" or filt["type"] in obj.k.types
                    if not ok or (filt["another"] and obj is p) or obj.k.power < filt["power"]: continue
                if once:
                    if p.once is None: p.once = set()
                    if (ev, self.phase) in p.once: continue
                    p.once.add((ev, self.phase))
                if tax and self.rng.random() < self.sim.opp_pay: continue
                self.do(fx, p.k, p)

    # ---- turn structure
    def opponents(self):
        sim = self.sim
        for _ in range(sim.opps):
            self.phase += 1
            self.fire("upkeep", each_only=True)
            self.fire("opp_draw")
            for _ in range(sim.opp_casts):
                self.fire("opp_cast", OPP_CREATURE if self.rng.random() < 0.4 else OPP_SPELL)
            self.fire("end", each_only=True)

    def play(self, turns, rec):
        sim = self.sim
        for k in [c for c in self.hand if c.leyline]:
            self.hand.remove(k); self.enter(k)
        for t in range(1, turns + 1):
            self.turn = t; self.phase += 1
            if t == sim.kill_turn:
                for p in [q for q in self.perms if q.k in sim.commanders]:
                    self.perms.remove(p); self.cmd.append(p.k); self._st = None
            for p in self.lands: p.tapped = False
            for p in self.perms: p.tapped = False; p.sick = False
            self.drops = 1 + self.st.extra_land
            self.fire("upkeep")
            for k in self.rebound:
                self.fire("cast", k); self.do(k.spell, k); self.gy.append(k)
            self.rebound = []
            if not (t == 1 and sim.on_play): self.draw(1)
            self.fire("drawstep")
            self.note(f"T{t} hand: " + "; ".join(c.name for c in self.hand))
            if self.drops > 0:
                land = self.choose_land()
                if land: self.play_land(land)
            self.build_pool()
            pool_n = sum(1 for u in self.pool if not u[5])
            cols = set().union(*(u[0] | u[1] for u in self.pool if not u[5])) if self.pool else set()
            if self.st.spend_any and cols - {"C"}: cols |= sim.anyc
            rec["lands"][t].append(len(self.lands)); rec["mana"][t].append(pool_n)
            rec["colors"][t].append(sim.anyc <= cols)
            rec["stranded"][t].append(self.stranded())
            self.note(f"  mana {pool_n} ({''.join(sorted(cols))}) at the start of main")
            self.cast_loop()
            self.pool = None; self.convs = []
            self.fire("end")
            if not self.st.no_max and len(self.hand) > 7:
                self.hand.sort(key=self.value)
                n = len(self.hand) - 7
                self.gy += self.hand[:n]; del self.hand[:n]; self.disc += n
            rec["hand"][t].append(len(self.hand)); rec["extra"][t].append(self.extra)
            rec["casts"][t].append(self.casts); rec["spent"][t].append(self.spent)
            rec["disc"][t].append(self.disc)
            rec["cmd_out"][t].append(bool(sim.commanders) and all(any(p.k is c for p in self.perms) for c in sim.commanders))
            if self.log is not None and self.perms: self.note("  board: " + "; ".join(p.k.name + (str(p.ctr) if p.ctr else "") for p in self.perms))
            self.opponents()

# ---------------------------------------------------------------- simulation
def load_overrides():
    if not os.path.exists(OVERRIDES_FILE): return {}
    data = json.load(open(OVERRIDES_FILE, encoding="utf-8"))
    return {mtg.norm(k): v for k, v in data.items() if not k.startswith("_")}

class Sim:
    def __init__(self, names, commanders, args, groups, cache, anyc):
        self.args, self.anyc, self.groups = args, anyc, groups
        self.deck = [cache[n] for n in names]
        self.commanders = [cache[n] for n in commanders]
        self.land_cards = [k for k in dict.fromkeys(self.deck) if k.is_land]
        self.order = {c: i for i, c in enumerate(args.order.split(","))}
        self.on_play, self.kill_turn, self.cast_hold = not args.draw, args.kill_commander, args.cast_interaction
        self.opps, self.opp_casts, self.opp_pay, self.opp_hand = args.opps, args.opp_casts, args.opp_pay, args.opp_hand
        self.dry_rng = random.Random(0)

    def prio(self, k, zone):
        o = self.order
        cat = "commander" if zone == "cmd" else "track" if k.groups else k.cat
        return (o.get(cat, len(o)), k.mv if cat == "ramp" else -k.mv, k.name)

    def keep(self, hand, bottom):
        lands = sum(1 for k in hand if k.is_land or k.mdfc)
        if bottom == 0:
            cheap = sum(1 for k in hand if not k.is_land and k.cat == "ramp" and k.mv <= 2)
            return 3 <= lands <= 5 or (lands == 2 and cheap >= 1)
        return 2 <= lands <= 5

    def bottom_score(self, k, lands):
        if k.is_land: return 5 if lands >= 5 else 90
        return (80 if k.groups else 0) + (40 if k.cat == "ramp" and k.mv <= 3 else 0) + 30 - k.mv

    def opening(self, rng):
        mulls = bottom = 0
        while True:
            lib = self.deck[:]; rng.shuffle(lib)
            hand = [lib.pop() for _ in range(min(7, len(lib)))]   # partial lists can be < 7 cards
            if self.args.no_mulligan or bottom >= 2 or self.keep(hand, bottom): break
            mulls += 1
            if mulls >= 2: bottom += 1          # the first mulligan is free (rule 103.5c)
        if bottom:
            lands = sum(1 for k in hand if k.is_land)
            hand.sort(key=lambda k: self.bottom_score(k, lands))
            lib[0:0] = hand[:bottom]; hand = hand[bottom:]
        return hand, lib, 7 - bottom, mulls

    def run(self, trials, turns, seed):
        T = range(1, turns + 1)
        rec = {m: {t: [] for t in T} for m in
               ("lands", "mana", "colors", "stranded", "hand", "extra", "casts", "spent", "disc", "cmd_out")}
        first = {gi: [] for gi in range(len(self.groups))}
        cmd_first = {c.name: [] for c in self.commanders}
        attr, kept, mull_n = Counter(), Counter(), 0
        for i in range(trials):
            rng = random.Random(seed * 1_000_003 + i)
            hand, lib, size, mulls = self.opening(rng)
            kept[size] += 1; mull_n += mulls > 0
            g = Game(self, hand, lib, rng)
            if self.args.trace == i + 1: g.log = [f"game {i + 1}: kept {len(hand)} after {mulls} mulligan(s)"]
            g.play(turns, rec)
            if g.log: print("\n".join(g.log)); print()
            for gi in first: first[gi].append(g.first.get(gi))
            for c in cmd_first: cmd_first[c].append(g.cmd_first.get(c))
            attr.update(g.attr)
        return {"rec": rec, "first": first, "cmd_first": cmd_first, "attr": attr, "kept": kept,
                "mulliganed": mull_n / trials, "trials": trials, "turns": turns}

# ---------------------------------------------------------------- report
def pct(v): return f"{100 * v:5.1f}%"
def q(vals, p):
    s = sorted(vals); return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]
def mean(v): return sum(v) / len(v) if v else 0
def by_turn(turns_list, t): return mean([1 if x is not None and x <= t else 0 for x in turns_list])

def summary(res, groups):
    rec, T = res["rec"], res["turns"]
    out = {"turns": {}}
    for t in range(1, T + 1):
        out["turns"][t] = {m: ({"p10": q(v, .1), "med": q(v, .5), "p90": q(v, .9), "mean": round(mean(v), 2)}
                               if m not in ("colors", "cmd_out") else round(mean(v), 4))
                           for m, v in ((m, rec[m][t]) for m in rec)}
    out["commander_by_turn"] = {c: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for c, v in res["cmd_first"].items()}
    out["tracked_by_turn"] = {groups[gi][0]: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for gi, v in res["first"].items()}
    out["extra_card_sources"] = {k: round(v / res["trials"], 3) for k, v in res["attr"].most_common(12)}
    out["kept_hand_size"] = {k: round(v / res["trials"], 4) for k, v in sorted(res["kept"].items(), reverse=True)}
    out["mulligan_rate"] = round(res["mulliganed"], 4)
    return out

def print_report(label, sm, meta, groups, show_header=True):
    T = meta["turns"]
    tt = sm["turns"]
    def trio(t, m): d = tt[t][m]; return f"{d['p10']}/{d['med']}/{d['p90']}"
    if show_header:
        print(f"=== GOLDFISH: {meta['commander']} | {meta['n']} cards | {meta['trials']} games x {T} turns | "
              f"{'on the draw' if meta['draw'] else 'on the play'} | seed {meta['seed']} ===")
        print(f"model: {meta['model']}  (--explain for the per-card list)")
        print(f"mulligans: {pct(sm['mulligan_rate']).strip()} of games mulligan; kept size "
              + ", ".join(f"{k}: {pct(v).strip()}" for k, v in sm["kept_hand_size"].items())
              + "  (London, first mulligan free per rule 103.5c)")
        print(f"table model: {meta['opps']} opponents, {meta['opp_casts']} spell(s) each per cycle, "
              f"{int(meta['opp_pay'] * 100)}% pay a tax, {meta['opp_hand']} cards in an opponent's hand")
    print(f"\n## {label}: development (P10/median/P90; lands and mana at the start of your main phase)")
    print(f"{'turn':<5}{'lands':<10}{'mana':<10}{'all colors':>11}{'cmdr out':>10}   {'spells cast':<13}{'mana spent':<12}")
    for t in range(1, T + 1):
        print(f"T{t:<4}{trio(t, 'lands'):<10}{trio(t, 'mana'):<10}{pct(tt[t]['colors']):>11}{pct(tt[t]['cmd_out']):>10}   "
              f"{trio(t, 'casts'):<13}{trio(t, 'spent'):<12}")
    turns_show = [t for t in range(2, T + 1)]
    for c, v in sm["commander_by_turn"].items():
        print(f"commander {c}: " + " | ".join(f"<=T{t} {pct(v[t]).strip()}" for t in turns_show))
    for g, v in sm["tracked_by_turn"].items():
        print(f"tracked {g}: " + " | ".join(f"<=T{t} {pct(v[t]).strip()}" for t in turns_show))
    print(f"\n## {label}: card flow (end of turn; extra = cards put in hand beyond draw steps)")
    print(f"{'turn':<5}{'extra (cum)':<13}{'mean':>6}{'hand':>10}{'hand<=1':>9}{'stranded':>10}{'discarded':>11}")
    for t in range(1, T + 1):
        d = tt[t]
        print(f"T{t:<4}{trio(t, 'extra'):<13}{d['extra']['mean']:>6.2f}{trio(t, 'hand'):>10}"
              f"{pct(mean_leq1(d)):>9}{d['stranded']['mean']:>10.2f}{d['disc']['mean']:>11.2f}")
    src = sm["extra_card_sources"]
    if src:
        print(f"extra cards by source (avg per game over {T} turns): "
              + " | ".join(f"{k} {v:.2f}" for k, v in src.items()))

def mean_leq1(d):
    return d["hand"].get("leq1", 0.0)

def compare_table(builds, groups, T):
    print("\n## Builds compared (same shuffles)")
    labels = [b[0] for b in builds]
    rows = []
    def cm(sm, t):
        v = list(sm["commander_by_turn"].values())
        return v[0][t] if v else 0
    for t in (3, 4, 5):
        if t <= T: rows.append((f"commander <=T{t}", [pct(cm(sm, t)) for _, sm in builds]))
    for g in [g[0] for g in groups]:
        for t in (5, 6):
            if t <= T: rows.append((f"{g} <=T{t}", [pct(sm["tracked_by_turn"][g][t]) for _, sm in builds]))
    for t in (3, 4):
        if t <= T: rows.append((f"all colors T{t}", [pct(sm["turns"][t]["colors"]) for _, sm in builds]))
    t4 = min(4, T)
    rows.append((f"mana T{t4} P10/med", [f"{sm['turns'][t4]['mana']['p10']}/{sm['turns'][t4]['mana']['med']}" for _, sm in builds]))
    rows.append((f"stranded T{t4} (avg)", [f"{sm['turns'][t4]['stranded']['mean']:.2f}" for _, sm in builds]))
    rows.append((f"extra cards T{T} P10/med/P90", [f"{sm['turns'][T]['extra']['p10']}/{sm['turns'][T]['extra']['med']}/{sm['turns'][T]['extra']['p90']}" for _, sm in builds]))
    rows.append((f"mana spent T{T} median", [str(sm['turns'][T]['spent']['med']) for _, sm in builds]))
    w = max(len(r[0]) for r in rows) + 2
    cw = max(10, max(len(l) for l in labels) + 2)
    print(f"{'':<{w}}" + "".join(f"{l:>{cw}}" for l in labels))
    for name, vals in rows:
        print(f"{name:<{w}}" + "".join(f"{v:>{cw}}" for v in vals))

def explain(cache, names, commanders):
    counts = Counter()
    seen = list(dict.fromkeys(commanders + names))
    print(f"{'status':<9}{'role':<7}card — model")
    for n in seen:
        k = cache[n]
        if k.is_land:
            cols = "".join(c for c in "WUBRGC" if any(c in (u[0] | u[1]) for u in k.units))
            bits = [f"land {cols or '-'}"] + (["tapped" if k.etap[0] == "always" else k.etap[0]] if k.etap else [])
            if k.fetch: bits.append("fetch" + (" (tapped)" if k.fetch[1] else ""))
            if k.bounce: bits.append("bounce")
            if k.convs: bits.append(f"filter {k.convs[0][0]}->{len(k.convs[0][1])}")
        else:
            counts[k.status] += 1
            bits = []
            if k.units: bits.append("mana " + "+".join("".join(sorted(u[0] | u[1])) or "-" for u in k.units)
                                    + (" (restricted)" if any(u[2] for u in k.units) else "")
                                    + (" (colored only)" if any(u[3] for u in k.units) else ""))
            if k.vivid: bits.append("mana: 1 per color among your permanents")
            if k.convs: bits.append(f"filter {k.convs[0][0]}->{len(k.convs[0][1])}")
            if k.etap: bits.append("enters tapped")
        if k.etb: bits.append("ETB " + ", ".join(fx_str(e) for e in k.etb) + (" (sacrificed)" if k.sac_etb else ""))
        if k.spell: bits.append(", ".join(fx_str(e) for e in k.spell))
        for ev, f, fx, once, tax, each in k.trig:
            if not f: fl = ""
            elif "types" in f:
                fl = "(" + ",".join(sorted({x.lower() for x in f["types"]} | ({"legendary"} if f["legendary"] else set())
                                           | {"non" + x.lower() for x in f["non"]})) + ")"
            else:
                fl = "(" + ("another " if f["another"] else "") + f["type"].lower() + (f" power>={f['power']}" if f["power"] else "") + ")"
            bits.append(f"on {ev}{fl}{' 1/turn' if once else ''}{' taxed' if tax else ''}{' +opp turns' if each else ''}: "
                        + ", ".join(fx_str(e) for e in fx))
        for a in k.acts:
            cost = ("T " if a["tap"] else "") + (f"{a['gen'] + len(a['pips'])} " if a["gen"] or a["pips"] else "") \
                   + ("sac " if a["sac"] else "") + (f"-{a['rm'][1]} {a['rm'][0]} " if a["rm"] else "")
            bits.append(f"act [{cost.strip()}]: " + ", ".join(fx_str(e) for e in a["fx"]))
        for c_, fx in k.pw: bits.append(f"loyalty {c_:+d}: " + ", ".join(fx_str(e) for e in fx))
        if k.ctr_enter: bits.append(f"enters with {k.ctr_enter[1]} {k.ctr_enter[0]}" + (" if cast from hand" if k.ctr_enter[2] else ""))
        for s in k.statics:
            if s[0] != "aura_mana": bits.append(s[0])
        if k.leyline: bits.append("leyline")
        if k.requires: bits.append("needs a " + k.requires)
        if k.hold: bits.append("held (interaction)")
        if k.ritual: bits.append("ritual (cast only to enable a spell)")
        if k.mdfc: bits.append("MDFC land back")
        if k.rebound: bits.append("rebound")
        role = "land" if k.is_land else k.cat
        status = ("override" if k.override else k.status) if not k.is_land else ("land" if not k.notes else "land*")
        line = f"{status:<9}{role:<7}{k.name} — {'; '.join(bits) or 'body only'}"
        if k.notes: line += "  [" + "; ".join(k.notes) + "]"
        print(line)
    print("\nnonland: " + ", ".join(f"{v} {s}" for s, v in counts.most_common()))

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Monte Carlo goldfish simulator (see module docstring)")
    ap.add_argument("deck")
    ap.add_argument("--turns", type=int, default=8); ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--draw", action="store_true"); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--track", action="append", default=[]); ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--kill-commander", type=int, default=0); ap.add_argument("--order", default=ORDER_DEFAULT)
    ap.add_argument("--opps", type=int, default=3); ap.add_argument("--opp-casts", type=int, default=1)
    ap.add_argument("--opp-pay", type=float, default=0.5); ap.add_argument("--opp-hand", type=int, default=4)
    ap.add_argument("--cast-interaction", action="store_true"); ap.add_argument("--no-mulligan", action="store_true")
    ap.add_argument("--trace", type=int, default=0)
    ap.add_argument("--explain", action="store_true"); ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.deck): sys.exit(f"deck file not found: {args.deck}")
    if args.trials < 1: sys.exit("--trials must be at least 1")
    if args.turns < 1: sys.exit("--turns must be at least 1")
    if args.opps < 0 or args.opp_casts < 0 or args.opp_hand < 0: sys.exit("--opps, --opp-casts and --opp-hand can't be negative")
    if not 0 <= args.opp_pay <= 1: sys.exit("--opp-pay is a probability between 0 and 1 (e.g. 0.5)")

    entries = mtg.parse_deck(args.deck)
    if not entries: sys.exit(f"no cards found in {args.deck}")
    skip = {"sideboard", "maybeboard", "considering", "companion"}
    raw_cmd = [n for s, q, n in entries if s in ("commander", "commanders")]
    raw_lib = [n for s, q, n in entries if s not in skip | {"commander", "commanders"} for _ in range(q)]
    found, missing = {}, []
    def resolve(n):
        if n not in found:
            c, how = mtg.find(n)
            if not c or (how or "").startswith("ambiguous"): missing.append(n); return None
            found[n] = c
        return found[n]
    for n in raw_cmd + raw_lib: resolve(n)
    variants = []
    for v in args.variant:
        label, _, swaps = v.rpartition("|")
        pairs = [tuple(x.strip() for x in s.split("=>")) for s in swaps.split(";") if "=>" in s]
        for o, i in pairs: resolve(o); resolve(i)
        variants.append((label or f"variant {len(variants) + 1}", pairs))
    if missing:
        sys.exit("NOT FOUND (fix the names or add them to data/aliases.txt): " + "; ".join(dict.fromkeys(missing)))
    ci = set().union(*(found[n].get("color_identity") or [] for n in raw_cmd)) if raw_cmd else \
        set().union(*(found[n].get("color_identity") or [] for n in raw_lib))
    anyc = frozenset(ci) or ALL5
    overrides = load_overrides()
    groups = []
    for t in args.track:
        label, sep, rx = t.partition("=")
        if not sep: label, rx = t, "^" + re.escape(found.get(t, {}).get("name", t)) + "$"
        try:
            groups.append((label, re.compile(rx, re.I)))
        except re.error as ex:
            sys.exit(f"--track {t!r}: bad pattern ({ex}). For an exact card, pass just the name.")
    cache = {}
    for n, c in found.items():
        k = compile_card(c, anyc)
        ov = overrides.get(mtg.norm(c["name"]))
        if ov: apply_override(k, ov, anyc)
        k.groups = tuple(gi for gi, (_, rx) in enumerate(groups) if rx.search(c["name"]))
        cache[n] = k
    if args.explain:
        explain(cache, raw_lib + [i for _, pairs in variants for _, i in pairs], raw_cmd); return
    nonland = [cache[n] for n in dict.fromkeys(raw_lib) if not cache[n].is_land]
    st = Counter(k.status for k in nonland)
    meta = {"commander": " + ".join(found[n]["name"] for n in raw_cmd) or "(no commander)", "n": len(raw_lib),
            "trials": args.trials, "turns": args.turns, "draw": args.draw, "seed": args.seed, "opps": args.opps,
            "opp_casts": args.opp_casts, "opp_pay": args.opp_pay, "opp_hand": args.opp_hand,
            "model": f"{len(nonland)} nonland cards: {st['modeled']} modeled, {st['partial']} partial, {st['blank']} blank, "
                     f"{st['held']} held as interaction; {sum(k.override for k in cache.values())} overrides"}
    builds = [("base", raw_lib)]
    for label, pairs in variants:
        lib = list(raw_lib)
        for o, i in pairs:
            idx = next((j for j, n in enumerate(lib) if found[n]["name"] == found[o]["name"]), None)
            if idx is None: sys.exit(f"--variant: {o} is not in the deck")
            lib[idx] = i
        builds.append((label, lib))
    results = []
    for label, lib in builds:
        sim = Sim(lib, raw_cmd, args, groups, cache, anyc)
        res = sim.run(args.trials, args.turns, args.seed)
        sm = summary(res, groups)
        for t in sm["turns"]:
            sm["turns"][t]["hand"]["leq1"] = round(mean([1 if h <= 1 else 0 for h in res["rec"]["hand"][t]]), 4)
        results.append((label, sm))
    if args.json:
        print(json.dumps({"meta": meta, "builds": {l: s for l, s in results}}, indent=1)); return
    for i, (label, sm) in enumerate(results):
        print_report(label, sm, meta, groups, show_header=(i == 0))
    if len(results) > 1: compare_table(results, groups, args.turns)
    print("\nnot modeled: combat, opponents' interaction, graveyard recursion, tokens beyond Treasures; "
          "partial/blank cards are cast for their mana cost only. Treat numbers as a floor/ceiling sketch, not a prediction.")

if __name__ == "__main__":
    main()
