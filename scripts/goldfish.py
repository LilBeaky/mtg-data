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
                         (repeatable; a bare card name also works). '# track: Label=REGEX'
                         lines in the deck header are added automatically
  --variant "Label|Out=>In;Out=>In"   also run a swapped build, side by side (repeatable)
  --kill-commander T     every clean game loses its commander after turn T-1 (recast with tax)
  --disruption MODE      'auto' (default): the bracket's interaction ladder when the bracket is 2-4
                         (header '# bracket:' or --bracket), else 'sample'. 'ladder': per shuffle, 5 clean
                         baselines + 15 rungs from data/goldfish_gradients.json, with a fold/breakpoint read.
                         'sample': each game replayed with 0-2 sampled events. 'off'. Or a fixed scenario
                         for every game, e.g. 'wipe@5;cmd@4;ctrK!@3' (codes: see the gradients file)
  --bracket N            bracket for the ladder (overrides the header)
  --shuffles N           ladder shuffles (default from the gradients file: 100)
  --horizon N            ladder horizon (default per bracket: B2 10, B3 9, B4 8)
  --ladder-max           every ladder event fires (stress test / pilot audit)
  --disruption-trace X   play-by-play of a disrupted game: N (sample/fixed) or SHUFFLE:RUNG (ladder)
  --order LIST           cast priority (default commander,track,ramp,draw,other)
  --cast-interaction     also cast held removal / counters / protection spells proactively
  --no-mulligan          keep every opening 7
  --explain              print how each card was modeled, then exit
  --trace N              print a play-by-play of game N (to audit the pilot)
  --json                 machine-readable output

Tutors read targets and destinations with tutors.py's parser and fetch '# key:' cards and
missing '# package:' pieces first. The graveyard is a zone: recursion, reanimation and
flashback-family casting are modeled, as are cycling, typecycling and transmute.

Card behavior is compiled from Oracle text once per card. data/goldfish_overrides.json
replaces the parse for the cards it names. --explain marks each card modeled / partial /
blank; a blank is still cast (it costs its mana) but does nothing.
"""
import argparse, json, os, random, re, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtg
import tutors as tu          # tutor targets and destinations are read exactly as tutors.py reads them
import stats_math as sm      # '# package:' part resolution

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
_CTX = {"raw": None, "text": "", "orig": None}   # card being compiled; original-case effect text for parse_fx
_EXPLAIN_DECK = []                              # raw cards of the list, so --explain can count tutor hits
# Opponents are not simulated. Cards that only work off other players get these fixed approximations
# (no knobs; tagged ~opp in --explain): 3 other turns per round (a 4-player pod: turn structure);
# each opponent draws 1 and casts 1 spell a turn (40% creatures), a second spell 30% of the time;
# taxes (Rhystic, Tithe) are paid 75% of the time, so each lands about once a round; an opponent
# holds 4 cards; an opponent's land count is their turn count.
POD, OPP_CREATURE_SHARE, OPP_SECOND, TAX_PAID, OPP_HAND = 3, 0.4, 0.3, 0.75, 4
OPP_LINE = re.compile(r"\bopponents?\b|attacks you\b|\bother players?\b|each player(?! may)")
START_LIFE, LIFE_FLOOR = 40, 20
# Disruption to your own game. Two modes (see docs/GOLDFISH.md):
#  ladder (default when the bracket is 2-4): 5 clean baselines + 15 rungs of the bracket's interaction ladder
#          (data/goldfish_gradients.json) per shuffle, events firing on per-slot rolls shared across rungs.
#  sample: 25% of games have none, 50% one event, 25% two, on turns 3+ (the older, bracket-free read).
# Events land after your turn t (counters during it). Your held counters / protection answer an event if you
# left mana open (or it's free with a commander out).
DIS_KINDS = (("cmd", 0.25), ("removal", 0.25), ("wipe", 0.20), ("nuke", 0.10), ("counter", 0.20))
DIS_NAMES = {"cmd": "commander removal", "removal": "spot removal", "wipe": "creature wipe",
             "nuke": "nonland wipe", "counter": "counterspell", "removal+": "exile removal (smart)",
             "nuke+gy": "nonland exile + graveyard exile", "rift": "mass bounce", "gy": "graveyard exile",
             "ld": "land destruction", "tax": "noncreature tax", "taxall": "spell tax", "lock": "command zone/graveyard lock",
             "counterK": "held counter (commander/key)"}
# event codes (ladder file and --disruption) -> (kind, min MV for counters)
DIS_CODES = {"cmd": ("cmd", 0), "rem": ("removal", 0), "removal": ("removal", 0), "rem+": ("removal+", 0),
             "wipe": ("wipe", 0), "nuke": ("nuke", 0), "nuke+gy": ("nuke+gy", 0), "rift": ("rift", 0), "gy": ("gy", 0),
             "ld": ("ld", 0), "tax": ("tax", 0), "taxall": ("taxall", 0), "lock": ("lock", 0), "counter": ("counter", 3),
             "ctr2": ("counter", 2), "ctr3": ("counter", 3), "ctr4": ("counter", 4), "ctrK": ("counterK", 0)}
PERSIST = {"tax": "creature", "taxall": "artifact", "lock": "creature"}   # stax effects -> the permanent type behind them
ANSWERS = {"counter": {"cmd", "removal", "removal+", "wipe", "nuke", "nuke+gy", "rift", "tax", "taxall", "lock",
                       "counter", "counterK"},
           "protect": {"cmd", "removal", "removal+", "wipe", "nuke", "nuke+gy", "rift"},
           "redirect": {"cmd", "removal", "removal+"}}   # the pilot won't pay life below the floor (a goldfish still has a table to survive)
GRADIENTS_FILE = os.path.join(mtg.DATA_DIR, "goldfish_gradients.json")

def parse_event(tok, slot=None):
    """'rem+@4', 'wipe!@6' -> (turn, event dict). Raises ValueError on a bad token."""
    code, _, t = tok.strip().partition("@")
    backup = code.endswith("!"); code = code.rstrip("!")
    code = {"commander": "cmd", "spot": "rem", "creature": "wipe", "nonland": "nuke", "counterspell": "counter"}.get(code, code)
    if code not in DIS_CODES or not t.isdigit() or int(t) < 1: raise ValueError(tok)
    kind, mv = DIS_CODES[code]
    return int(t), {"kind": kind, "mv": mv, "backup": backup, "code": code + ("!" if backup else ""), "slot": slot}
GY_KW = ("flashback", "jump-start", "retrace", "escape", "unearth", "harmonize")

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

def _load_subtypes():
    """Every subtype named in CR 205.3g-m (creature, artifact, land... types), for filters like 'Dragon spells'."""
    try:
        with open(mtg.RULES_FILE, encoding="utf-8", errors="ignore") as fh:
            txt = fh.read()
    except Exception:
        return set()
    out = set()
    for m in re.finditer(r"^205\.3[g-m]\s.*$", txt, re.M):
        out |= set(re.findall(r"\b([A-Z][a-z\-']+)", m.group(0)))
    return out - {"Artifact", "Creature", "Land", "Enchantment", "Planeswalker", "Instant", "Sorcery", "Battle", "Kindred"}

SUBTYPES = _load_subtypes()
TOKEN_CAP = 150          # permanents on your side; stops runaway token loops

def as_subtype(w):
    """'dragons' / 'elves' / 'pegasus' -> the CR subtype, or None."""
    t = w.capitalize()
    for c in (t, t[:-1] if t.endswith("s") else None, t[:-3] + "f" if t.endswith("ves") else None,
              t[:-2] if t.endswith("es") else None):
        if c and c in SUBTYPES: return c
    return None

# ---------------------------------------------------------------- filters
FILTER_OK_WORDS = {"a", "an", "card", "cards", "spell", "spells", "or", "and", "and/or", "your",
                   "any", "number", "of", "one", "two", "three", "up", "to", "with", "different", "names"}

def parse_filter(s):
    """'legendary creature' / 'noncreature' / 'instant or sorcery' / 'white' -> filter dict.
    Words it doesn't know set 'unknown' (callers skip or flag those)."""
    s = (s or "").lower()
    f = {"types": set(), "non": set(), "legendary": False, "colors": set(), "multi": False,
         "historic": False, "mv_max": None, "unknown": False, "sub": set()}
    m = re.search(r"with mana value (\d+) or less", s)
    if m: f["mv_max"] = int(m.group(1)); s = s.replace(m.group(0), "")
    m = re.search(r"with power (\d+) or greater", s)
    if m: f["pow_min"] = int(m.group(1)); s = s.replace(m.group(0), "")
    if re.search(r"^the first\b", s.strip()): f["first"] = True; s = re.sub(r"^\s*the first\b", "", s)
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
        elif w == "nontoken": f["nontoken"] = True
        elif w in ("token", "tokens"): f["istoken"] = True
        elif w not in FILTER_OK_WORDS:
            f["unknown"] = True
            st = as_subtype(w)
            if st: f["sub"].add(st)               # Dragon spells, Elves: a real subtype narrows the filter
    return f

def spell_ok(k, f):
    if not f: return True
    if f["types"] and not (k.types & f["types"]): return False
    if f.get("sub") and not (k.subtypes & f["sub"]): return False
    if f["non"] and (k.types & f["non"]): return False
    if f["legendary"] and not k.legendary: return False
    if f["colors"] and not (k.colors & f["colors"]): return False
    if f["multi"] and len(k.colors) < 2: return False
    if f["historic"] and not (k.legendary or "Artifact" in k.types or "Saga" in k.subtypes): return False
    if f["mv_max"] is not None and k.mv > f["mv_max"]: return False
    if f.get("pow_min") is not None and k.power < f["pow_min"]: return False
    if f.get("nontoken") and k.token: return False
    if f.get("istoken") and not k.token: return False
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
                    (r"greatest power", "power"), (r"(?:^|\beach )cards? in your graveyard", "gy"), (r"colors? among", "colors"), (r"lands? you control", "lands"),
                    (r"creatures? you control", "creatures"), (r"artifacts? you control", "artifacts"),
                    (r"enchantments? you control", "enchantments"), (r"permanents? you control", "permanents")):
        m = re.search(rx, w)
        if m: return ("ctr", m.group(1)) if key == "ctr" else (key,)
    return None

OPP_SUBJ = ("target opponent", "each opponent", "an opponent", "that player")
SUBJ = r"(?P<subj>\b(?:target opponent|each opponent|an opponent|that player|target player|each player|you)\s+)?(?:may )?"

def _subj_ok(m):
    return (m.group("subj") or "").strip() not in OPP_SUBJ

def _orig(m, g):
    """Group g of a parse_fx match in its original case (tutors.py reads subtypes by capital letter)."""
    o = _CTX["orig"]
    return o[m.start(g):m.end(g)] if o and len(o) == len(m.string) else m.group(g)

def tutor_dest(after):
    """Where a searched card goes: tutors.py's destination reader, mapped to goldfish zones.
    hand / top / bf / bf_t / graveyard / exile (castable, treated like hand) / none (exiled, no access)."""
    dest, first = "hand", 10**9
    for d, rx in tu.DEST_RX:
        mm = rx.search(after)
        if mm and mm.start() < first: dest, first = d, mm.start()
    if dest == "battlefield": return "bf_t" if re.search(r"onto the battlefield tapped", after, re.I) else "bf"
    if dest == "exile":
        castable = re.search(r"\b(?:cast|play)\b[^.]*\b(?:exiled|that card|those cards|it|them)|put the exiled card into your hand"
                             r"|may cast spells? from among", _CTX["text"], re.I)
        return "exile" if castable else "none"
    return dest

LAND_WORDS = re.compile(r"\b(land|plains|island|swamp|mountain|forest|gate)s?\b")
NONLAND_WORDS = re.compile(r"\b(creature|artifact|enchantment|instant|sorcery|planeswalker|permanent|battle|card with)\b")

def _fx_search(m):
    s = m.group(1)
    head = s.split(" card")[0]
    dest = tutor_dest(s)
    if dest != "graveyard" and LAND_WORDS.search(head) and not NONLAND_WORDS.search(head):
        mc = re.match(r"(up to )?(\w+) ", head + " ")
        count = num(mc.group(2)) if mc and mc.group(2) not in ("a", "an") else 1
        if not isinstance(count, int): count = 1
        ldest = ("split" if re.search(r"one onto the battlefield tapped and the other into your hand", s)
                 else "top" if "on top" in s else "bf_t" if "onto the battlefield tapped" in s
                 else "bf" if "onto the battlefield" in s else "hand")
        return ("land_search", count, land_filter(head), ldest)
    multi = re.findall(r"an? ([a-z]+) card", s)
    if len(multi) > 1 and all(w in COLOR_WORDS for w in multi):
        return ("tutor_multi", [parse_filter(w) for w in multi], dest)
    orig = "search your library for " + _orig(m, 1)          # "and/or graveyard" searches read as library-only
    tm = tu.SEARCH_RX.search(orig)
    tg = tu.parse_target(tm.group("what") if tm else _orig(m, 1), _CTX["raw"] or {})
    return ("tutor", tg, dest, max(1, min(tg.count, 7)))

def tutor_unread(tg):
    """A target with words tutors.py couldn't read: the ability isn't used (other approximations are)."""
    return any(a.startswith("unread") for a in tg.approx)

RECUR_RX = re.compile(r"(?:returns?|puts?) (?P<what>[^.]*?\bcards?\b[^.]*?) from (?P<whose>your|a|their) graveyards? "
                      r"(?:to|into|onto) (?P<dest>your hand|its owner's hand|their owners' hands|the battlefield)")

def _fx_recur(m):
    what = re.sub(r"\b(?:another )?target ", "", _orig(m, "what"), flags=re.I)
    what = re.sub(r"^all ", "any number of ", what, flags=re.I)
    tg = tu.parse_target(what, _CTX["raw"] or {})
    if m.group("whose") != "your": tg.approx.append("only your own graveyard is modeled")
    return ("recur", tg, "bf" if "battlefield" in m.group("dest") else "hand", max(1, min(tg.count, 7)))

def _fx_token(m):
    """'create two 1/1 green Elf Warrior creature tokens' / 'create a Clue token' -> ('token', n, power, subtypes, text)."""
    desc, rest = m.group("desc"), m.group("rest")
    before = m.string[:m.start()]
    if re.search(r"\b(?:destroy|exile) (?:another )?target|if (?:that|the) creature (?:dies|died)|that creature's power|its controller", before[-160:]):
        return None                                   # the token comes off someone else's creature: not in a vacuum
    if re.search(r"\bcop(?:y|ies)\b", desc + rest): return None               # copies aren't modeled
    n = num(m.group("n")); n = "X" if m.group("n") == "x" else n if isinstance(n, int) else 1
    fe = re.search(r"\bfor each (.+)$", rest)
    if fe:
        n = dyn_key(fe.group(1))
        if not n: return None                                               # counts things the sim can't see
    quotes = _CTX.get("quotes") or []
    qm = re.search(r"@q(\d+)@", rest)
    text = quotes[int(qm.group(1))] if qm and int(qm.group(1)) < len(quotes) else ""
    if m.group("p") is not None or "creature" in desc:
        pw = m.group("p")
        pw = "X" if pw == "x" else int(pw) if pw else 0
        subs = tuple(dict.fromkeys(x for x in (as_subtype(w) for w in re.findall(r"[A-Za-z\-']+", _orig(m, "desc"))) if x))
        return ("token", n, pw, subs, text, "creature")
    if re.search(r"\bclue\b", desc): return ("token", n, 0, ("Clue",), "{2}, Sacrifice ~: Draw a card.", "artifact")
    if re.search(r"\bgold\b", desc): return ("token", n, 0, ("Gold",), "Sacrifice ~: Add one mana of any color.", "artifact")
    return None

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
    (re.compile(r"search your library(?: and/or graveyard)? for ([^.]+)"), _fx_search),
    (RECUR_RX, _fx_recur),
    (re.compile(r"reveal the top (\w+) cards? of your library\. you may put (?P<what>an? [^.]+?) cards? from among them into your hand"
                r"[^.]*\. put the rest into your graveyard"),
     lambda m: ("dig_gy", num(m.group(1)), tu.parse_target(_orig(m, "what") + " card", _CTX["raw"] or {}))),
    (re.compile(SUBJ + r"mills? (?P<n>a|an|one|two|three|four|five|six|seven|eight|nine|ten|x|\d+) cards?"),
     lambda m: ("mill", num(m.group("n"))) if _subj_ok(m) else None),
    (re.compile(r"\bscry (\w+)"), lambda m: ("scry", num(m.group(1)))),
    (re.compile(r"\bsurveil (\w+)"), lambda m: ("surveil", num(m.group(1)))),
    (re.compile(r"you may play an additional land this turn"), lambda m: ("extra_land", 1)),
    (re.compile(r"put (?:a|up to one) land card from your hand onto the battlefield"), lambda m: ("land_from_hand", 1)),
    (re.compile(r"create (a|an|one|two|three|four|five|x|\w+) (?:tapped )?(?:(?:food|clue|blood) token or an? )?treasure tokens?"), lambda m: ("treasure", num(m.group(1)))),
    (re.compile(r"\bcreate (?P<n>a|an|one|two|three|four|five|six|seven|x|\d+) (?:tapped )?(?:(?P<p>\d+|x)/(?P<t>\d+|x) )?"
                r"(?P<desc>[a-z ,\-]*?)\btokens?\b(?P<rest>[^.]*)"), _fx_token),
    (re.compile(r"\binvestigate(?: (twice|three times))?"),
     lambda m: ("token", {"twice": 2, "three times": 3}.get(m.group(1), 1), 0, ("Clue",), "{2}, Sacrifice ~: Draw a card.", "artifact")),
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
    quotes = re.findall(r'"([^"]*)"', s)
    _CTX["quotes"] = quotes
    qi = iter(range(len(quotes)))
    s0 = re.sub(r'"[^"]*"', lambda m: f"@q{next(qi)}@", s.strip())
    s0 = re.sub(r"[^.]*\binstead\b[^.]*\.?", "", s0, flags=re.I).strip()
    s = s0.lower()
    if len(s) != len(s0): s0 = s
    tax = bool(re.search(r"unless (?:that player|they) pays?|that player may pay \{", s))
    m = re.match(r"(?:you may )?if an opponent controls more lands than you,? (.+)$", s)
    if m:
        inner, t2 = parse_fx(s0[m.start(1):])
        return ([("cond", "opp_lands", inner)] if inner else []), tax or t2
    if re.match(r"(?:you may )?if (?:an|each) opponent (?:controls|has) more\b", s): return [], tax
    m = re.search(r"you may pay ((?:\{[^}]+\})+)\. if you do,? (.+)", s)
    if m:
        g, p, _, _ = parse_cost(m.group(1))
        inner, _ = parse_fx(s0[m.start(2):m.end(2)])
        pre, _ = parse_fx(s0[:m.start()]) if m.start() else ([], False)
        return pre + ([("paid", g, p, inner)] if inner else []), tax
    out, masked = [], s
    for rx, fn in FX:
        for mm in rx.finditer(masked):
            _CTX["orig"] = s0
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
    if t == "wheel": return f"wheel {e[1]}" + (" ~opp" if e[1] == "max" else "")
    if t == "putback": return f"put back {e[1]}" + (" (bottom)" if e[2] else "")
    if t == "discard": return f"discard {e[1]}"
    if t == "look": return f"look {e[1]} take {e[2]}"
    if t == "land_search": return f"land x{e[1]}->{e[3]}"
    if t == "tutor":
        tg = e[1]
        hits = f", {sum(1 for c in _EXPLAIN_DECK if tg.matches(c))} in list" if _EXPLAIN_DECK else ""
        cnt = f"{e[3]}x " if e[3] > 1 else ""
        return (f"tutor->{e[2]}: {cnt}{tg.describe()}{hits}" + (" (filter unread; not used)" if tutor_unread(tg) else "")
                + (" ~" + "; ".join(a for a in tg.approx if not a.startswith("unread")) if any(not a.startswith("unread") for a in tg.approx) else ""))
    if t == "tutor_multi": return f"tutor_multi->{e[2]}"
    if t == "recur":
        return f"recur->{e[2]}: {e[3]}x {e[1].describe()}".replace(": 1x ", ": ") + (" ~" + "; ".join(e[1].approx) if e[1].approx else "")
    if t == "mill": return f"mill {e[1]}"
    if t == "cond": return "if an opponent has more lands ~opp: " + ", ".join(fx_str(x) for x in e[2])
    if t == "dig_gy": return f"reveal {e[1]}, take {e[2].describe()}, rest to graveyard"
    if t == "mana": return "mana " + "".join("".join(sorted(u)) if len(u) == 1 else "*" for u in e[1])
    if t == "token":
        what = " ".join(e[3]) or "creature"
        return f"token {e[1]}x {what}" + (f" {e[2]}/-" if e[5] == "creature" else "") + (" (has an ability)" if e[4] and e[5] == "creature" else "")
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
        self.raw = None          # the card's data, for tutors.py target matching
        self.hand_acts = []      # cycling / typecycling / transmute: [{"kind", "label", "gen", "pips", "fx"}]
        self.gycast = None       # flashback-style casting from the graveyard (see GY_KW)
        self.gy_need = None      # recursion spell: a Target that must be in the graveyard to cast it
        self.recur_fx = []       # every recursion effect on the card (for reanimation-aware tutoring)
        self.cycle_fx = []       # "when you cycle ~" riders (Krosan Tusker)
        self.life_per_mv = False # Reanimate: lose life equal to the returned card's mana value
        self.opp_approx = False  # leans on the fixed opponent approximations (~opp)
        self.cum_upkeep = False  # cumulative upkeep: kept for 3 of your upkeeps, then let go (~approx)
        self.answer = None       # counter / protect / redirect: can stop a disruption event
        self.token = False       # a token: ceases to exist when it leaves the battlefield
        self.dyn_mana = None     # dyn key: the mana ability makes that many (Selvala, Priest of Titania, Cradle)
        self.self_red = None     # (n, dyn key): "~ costs {1} less to cast for each ..."
        self.free_cmdr = False   # free while you control a commander (Fierce Guardianship)
        self.kill = frozenset()  # held removal: permanent types it can remove (clears tax/lock pieces)

RX_KILL = re.compile(r"\b(?:destroy|exile|return) (?:up to (?:one|two|three) |any number of )?(?:other )?targets? ([^.;]{0,60})")
def kill_types(lt):
    """Permanent types a held removal spell can take off the table (for clearing tax/lock pieces). ~approx"""
    out = set()
    for m in RX_KILL.finditer(lt):
        obj = m.group(1)
        if "nonland permanent" in obj or re.search(r"\bpermanent\b", obj) and "land" not in obj.split("permanent")[0]:
            out |= {"creature", "artifact", "enchantment"}
        out |= {t for t in ("creature", "artifact", "enchantment") if t in obj}
    if re.search(r"deals? (?:\d+|x) damage to (?:any target|target creature)|target creature gets -|sacrifices? (?:a|an) creature", lt):
        out.add("creature")
    return frozenset(out)

def strip_reminder(t):
    return re.sub(r"\s*\([^()]*\)", "", t)

def tildify(text, names):
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(r"(?<![\w'])" + re.escape(n) + r"(?![\w'])", "~", text)
    return re.sub(r"\bthis (?:creature|artifact|enchantment|land|permanent|card|spell|aura|equipment|vehicle|planeswalker|battle|siege|saga|class|case|room|kindred)\b",
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

def dyn_prod(prod):
    """Variable mana amounts -> a dyn key (read at tap time), or None.
    'for each Elf on the battlefield' / 'where X is the greatest power...' / 'equal to your devotion to green'."""
    p = prod.lower()
    m = re.search(r"devotion to (white|blue|black|red|green)", p)
    if m: return ("devotion", COLOR_WORDS[m.group(1)])
    m = re.search(r"(?:for each|where x is(?: the number of)?|equal to(?: the number of)?) (.+)$", p)
    if not m: return None
    what = m.group(1)
    key = dyn_key(what)
    if key: return key
    ms = re.match(r"(\w+?)s? (?:on the battlefield|you control)$", what)
    if ms and ms.group(1) not in ("creature", "land", "artifact", "enchantment", "permanent"):
        w = ms.group(1)
        return ("sub", w[:-2] + "f" if w.endswith("ve") else w.capitalize())   # elves -> Elf
    return None

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
    (r"you may cast ([\w ]*?)spells( from your hand)? without paying their mana costs",
     lambda m, lo: ("free", parse_filter(m.group(1)), bool(m.group(2)))),
    (r"you may pay ((?:\{[^}]+\})+) rather than pay the mana cost for ([\w ]*?)spells you cast",
     lambda m, lo: ("alt", parse_filter(m.group(2)), parse_cost(m.group(1)))),
    (r"^([\w ,]*?)spells? you cast( with power \d+ or greater)?(?: each turn)? costs? \{(\d+)\} less to cast\.?$",
     lambda m, lo: ("reduce", parse_filter(m.group(1) + (m.group(2) or "")), int(m.group(3)))),
    (r"you may play (an|two|three) additional lands? on each of your turns", lambda m, lo: ("extra_land", num(m.group(1)))),
    (r"if you would proliferate, proliferate twice instead", lambda m, lo: ("prolif_x2",)),
    (r"you have no maximum hand size", lambda m, lo: ("no_max_hand",)),
    (r"if you tap an? (basic land|land|permanent|forest|plains|island|swamp|mountain) for mana, it produces (twice|three times) as much",
     lambda m, lo: ("mana_mult", m.group(1), 2 if m.group(2) == "twice" else 3)),
    (r"whenever (?:you tap|a player taps) an? (basic land|land|forest|plains|island|swamp|mountain|creature|permanent) for mana, "
     r"(?:add|that player adds|its controller adds) (?:an additional )?(?:one )?(?:additional )?(?:mana of any type that \w+ produced|\{\w\})",
     lambda m, lo: ("mana_add", m.group(1), 1)),
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
    if m and re.match(r"if (?!an opponent controls more lands)", m.group(3)):
        k.notes.append("conditional trigger (intervening 'if') not modeled"); return False
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
        if re.match(r"lands? an opponent controls$", subj):               # ~opp: each opponent drops a land a turn
            fxt = m.group("fx")
            cm = re.match(r"if that player controls more lands than you,\s*(.+)$", fxt)
            fx, tax = parse_fx(cm.group(1) if cm else fxt)
            if cm and fx: fx = [("cond", "opp_lands", fx)]
            if fx: k.trig.append(("opp_land", None, fx, False, tax, False))
            return bool(fx)
        if re.search(r"opponent|each player|a player", subj): return False       # others' permanents aren't simulated
        tm = re.search(r"\b(creature|artifact|enchantment|permanent|land|planeswalker)s?\b", subj)
        subs = {x for x in (as_subtype(w) for w in re.findall(r"[a-z\-']+", subj)) if x}
        if not tm and not subs: return False
        fx, tax = parse_fx(m.group("fx"))
        if tm and tm.group(1) == "land":
            k.trig.append(("landfall", None, fx, False, tax, False)); return bool(fx)
        pw = re.search(r"power (\d+) or greater", subj)
        f = {"type": tm.group(1).capitalize() if tm else "Permanent", "another": m.group(1) == "another" or "another" in subj,
             "power": int(pw.group(1)) if pw else 0, "sub": subs, "nontoken": "nontoken" in subj,
             "token": bool(re.search(r"\btokens?\b", subj)) and "nontoken" not in subj}
        k.trig.append(("etb", f, fx, False, tax, False)); return bool(fx)
    m = re.match(r"^when you cycle ~,\s*(?:you may )?(.+)$", lo)
    if m:
        fx, _ = parse_fx(m.group(1)); k.cycle_fx += fx; return bool(fx)
    m = re.match(r"^whenever (?:you|a player) cycles?(?: or discards?)? (?:a|another) card,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(1)); k.trig.append(("cycle", None, fx, False, tax, False)); return bool(fx)
    m = re.match(r"^whenever you proliferate,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(1)); k.trig.append(("prolif", None, fx, False, tax, False)); return bool(fx)
    m = re.match(r"^whenever an opponent casts their second spell each turn,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(1)); k.trig.append(("opp_second", None, fx, False, tax, False)); return bool(fx)
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
        dk = dyn_prod(m.group("prod")) if approx else None
        if dk: k.dyn_mana = dk; units = units[:1]
        elif approx: k.notes.append("variable mana amount counted as one")
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
    m = re.match(r"^(?:~|this spell) costs \{(\d+)\} less to cast for each (.+?)\.?$", lo)
    if m and dyn_key(m.group(2)):
        k.self_red = (int(m.group(1)), dyn_key(m.group(2))); return True
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
        if any(e[0] == "tutor" and tutor_unread(e[1]) for e in fx):
            k.notes.append("tutor filter not fully read; ability not used"); return False
        if not tap and not g and not p and sac and not rm and any(e[0] == "land_search" for e in fx):
            k.etb += fx; k.sac_etb = True; return True        # Sakura-Tribe Elder style: sacrifice at once
        lm = re.search(r"pay (\d+) life", m.group("cost").lower())
        k.acts.append({"tap": tap, "gen": g, "pips": p, "sac": sac, "rm": rm, "fx": fx, "life": int(lm.group(1)) if lm else 0})
        return True
    if "Aura" in k.subtypes and re.match(r"^enchant creature card in a graveyard$", lo):
        tg = tu.parse_target("a creature card", {}); tg.approx.append("only your own graveyard is modeled")
        k.etb.append(("recur", tg, "bf", 1)); k.requires = "gy"; k.gy_need = tg
        return True
    if k.requires == "gy" and "return enchanted creature card to the battlefield" in lo:
        return True
    if "Aura" in k.subtypes:
        m = re.match(r"^enchant (.+)$", lo)
        if m:
            s = m.group(1)
            k.requires = "legendary creature" if "legendary creature" in s else "creature" if "creature" in s else \
                         "land" if re.search(r"land|forest|plains|island|swamp|mountain", s) else None
            return "neutral"
    if k.types & {"Instant", "Sorcery"} or "Addendum" in L:
        fx, _ = parse_fx(L)
        if fx:
            k.spell += fx; return True
    return "neutral" if is_neutral(lo) else False

MODAL_RX = re.compile(r"^(?:(?P<pre>.*?),\s*)?choose (?P<n>one or both|one or more|any number|one|two|three)(?: or more)?\s*(?:—|-)\s*$", re.I)
MODE_RANK = ("draw", "look", "tutor", "tutor_multi", "recur", "land_search", "treasure", "token", "mana", "extra_land",
             "prolif", "ctr", "scry", "surveil", "mill")

def modal_lines(lines):
    """Fold 'Choose one —' + its bullet lines into one ('MODAL', prefix, n, [bullets]) item."""
    out, i = [], 0
    while i < len(lines):
        m = MODAL_RX.match(lines[i])
        if m:
            bullets = []
            j = i + 1
            while j < len(lines) and lines[j].startswith("•"):
                bullets.append(re.sub(r"^•\s*(?:[^—]{1,30}—\s*)?", "", lines[j])); j += 1
            if bullets:
                n = m.group("n").lower()
                take = 99 if n in ("any number", "one or more") else 2 if n in ("one or both", "two") else 3 if n == "three" else 1
                out.append(("MODAL", (m.group("pre") or "").strip(), take, bullets)); i = j; continue
        out.append(lines[i]); i += 1
    return out

def parse_modal(k, item, anyc, abil):
    """Pick the goldfish-best mode(s) and parse them as if printed alone."""
    _, pre, take, bullets = item
    def score(b):
        fx, _ = parse_fx(b)
        kinds = [e[0] for e in fx]
        return min((MODE_RANK.index(t) for t in kinds if t in MODE_RANK), default=99), fx
    ranked = sorted(bullets, key=lambda b: (score(b)[0], not score(b)[1]))
    chosen = [b for b in ranked[:take] if score(b)[1]]
    if not chosen: return False
    text = " ".join(b if b.endswith(".") else b + "." for b in chosen)
    if not pre:
        if k.types & {"Instant", "Sorcery"}:
            fx, _ = parse_fx(text); k.spell += fx; return bool(fx)
        return False
    lo = (pre + ", " + text).lower()
    lo = re.sub(r"^[a-z][\w' ]* — ", "", lo)
    return parse_trigger(k, lo) if lo.startswith(("when", "whenever", "at the beginning")) else False

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
    k.raw = c
    k.life_per_mv = bool(re.search(r"lose life equal to (?:its|that card's) mana value", text.lower()))
    saved = dict(_CTX); _CTX.update(raw=c, text=text)
    abil, done, missed, vac = [], 0, 0, 0
    for L in modal_lines([l.strip() for l in text.split("\n")]):
        if isinstance(L, tuple):                          # a "choose one —" block, read as the chosen mode(s)
            r = parse_modal(k, L, anyc, abil)
            if r: done += 1
            else: missed += 1; k.notes.append("unmodeled modes: " + " / ".join(b[:30] for b in L[3])[:72])
            continue
        if not L: continue
        kw = keyword_line(k, L, c)
        if kw is not None:
            if kw: done += 1
            else: missed += 1; k.notes.append("unmodeled: " + L[:72])
            continue
        if re.fullmatch(r"if you control a commander, you may cast ~ without paying its mana cost\.?", L.lower()):
            k.free_cmdr = True; done += 1; continue
        r = parse_line(k, L, anyc, abil)
        if r is True: done += 1
        elif r is False:
            if all(any(part.strip().startswith(w) for w in kws) for part in re.split(r"[,;]", L.lower()) if part.strip()):
                continue                                   # keyword line (Flying, Ward {2}, Equip {1}...)
            missed += 1
            if OPP_LINE.search(L.lower()): vac += 1; k.notes.append("needs opponents: " + L[:72])
            else: k.notes.append("unmodeled: " + L[:72])
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
    k.cum_upkeep = "cumulative upkeep" in kws
    if k.types & {"Instant", "Sorcery"}:
        k.ritual = bool(k.spell) and all(e[0] == "mana" for e in k.spell)
        k.hold = bool(RX_INTERACT.search(text.lower())) and not k.ritual
    lt = text.lower()
    if "Instant" in k.types or "flash" in kws:
        if re.search(r"counter target [^.]*?spell\b", lt): k.answer = "counter"
        elif re.search(r"phase out|(?:creatures|permanents) you control gain [^.]*?(?:hexproof|indestructible|protection|shroud)"
                       r"|(?:you and )?permanents you control gain|target (?:creature|permanent) you control gains? [^.]*?"
                       r"(?:hexproof|indestructible|protection|shroud)", lt): k.answer = "protect"
        elif "choose new targets for target spell" in lt: k.answer = "redirect"
        if k.answer and "Creature" not in k.types: k.hold = True
    if k.hold and not k.answer: k.kill = kill_types(lt)
    _CTX.update(saved)
    for a in k.hand_acts:
        if a["kind"] != "transmute": a["fx"] = a["fx"] + k.cycle_fx
    allfx = k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f]
    k.recur_fx = [e for e in allfx if e[0] == "recur"]
    if k.types & {"Instant", "Sorcery"} and k.spell:
        rec = [e for e in k.spell if e[0] == "recur"]
        if rec and not k.requires: k.requires, k.gy_need = "gy", rec[0][1]
        if all(e[0] == "tutor" and e[2] == "graveyard" for e in k.spell): k.requires = "gy_payoff"
    categorize(k)
    k.status = "blank" if missed and not done and not k.units else "partial" if missed else "modeled"
    if k.status == "blank" and vac == missed: k.status = "vacuum"
    if k.hold: k.status = "held"
    return k

def keyword_line(k, L, c):
    """Hand and graveyard keyword lines (cycling, typecycling, transmute, flashback family).
    None = not one of these; True = modeled; False = recognized but its cost isn't readable."""
    lo = L.lower()
    m = re.match(r"^([a-z ]*?)cycling[ —-]*(.*)$", lo)
    if m and not lo.startswith(("whenever", "when ", "at the")):
        prefix, cost = m.group(1).strip(), m.group(2).strip().rstrip(".")
        cm = re.fullmatch(r"((?:\{[^}]+\})+)|pay (\d+) life", cost)
        if not cm: return False
        g, p, _, _ = parse_cost(cm.group(1) or "")
        life = int(cm.group(2) or 0)
        if not prefix:
            k.hand_acts.append({"kind": "cycle", "label": "cycling", "gen": g, "pips": p, "fx": [("draw", 1)], "life": life})
            return True
        t = next((t for t in tu.card_tutors(c) if t.kind == "cycling" and t.condition == prefix + "cycling"), None)
        if not t: return False
        k.hand_acts.append({"kind": "typecycle", "label": prefix + "cycling", "gen": g, "pips": p,
                            "fx": [("tutor", t.target, "hand", 1)], "life": life})
        return True
    m = re.match(r"^transmute ((?:\{[^}]+\})+)$", lo)
    if m:
        t = next((t for t in tu.card_tutors(c) if t.kind == "transmute"), None)
        if not t: return False
        g, p, _, _ = parse_cost(m.group(1))
        k.hand_acts.append({"kind": "transmute", "label": "transmute", "gen": g, "pips": p,
                            "fx": [("tutor", t.target, "hand", 1)]})
        return True
    m = re.match(r"^(" + "|".join(GY_KW) + r")\b[ —-]*(.*)$", lo)
    if not m: return None
    kw, rest = m.group(1), m.group(2).strip().rstrip(".")
    gc = {"kw": kw, "gen": None, "pips": None, "discard": None, "exile_n": 0}
    if kw == "jump-start": gc["discard"] = "card"
    elif kw == "retrace": gc["discard"] = "land"
    else:
        cm = re.match(r"((?:\{[^}]+\})+)", rest)
        if not cm: return False
        gc["gen"], gc["pips"], _, _ = parse_cost(cm.group(1))
        extra = rest[cm.end():].strip(" ,")
        if extra:
            em = re.fullmatch(r"exile (\w+) other cards? from your graveyard", extra)
            if em: gc["exile_n"] = num(em.group(1))
            elif re.fullmatch(r"pay \d+ life", extra): pass
            elif extra == "discard a card": gc["discard"] = "card"
            else: return False
    if kw == "unearth" and "Creature" not in k.types: return False
    gc["exile_after"] = kw != "retrace" and not (kw == "escape" and k.types & PERMANENT)
    k.gycast = gc
    return True

def flat(fxs):
    out = []
    for e in fxs: out += [e] + (flat(e[2]) if e[0] == "cond" else flat(e[3]) if e[0] == "paid" else [])
    return out

def all_fx(k):
    return flat(k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f] + [e for a in k.hand_acts for e in a["fx"]])

def categorize(k):
    fxs = flat(k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f])
    kinds = {e[0] for e in fxs}
    k.opp_approx = any(t[0] in ("opp_cast", "opp_draw", "opp_second", "opp_land") or t[4] for t in k.trig) \
        or any(e[0] == "cond" or e[0] == "wheel" and e[1] == "max" or e[0] == "draw" and e[1] == ("opp_hand",) for e in fxs)
    ramp = (not k.is_land and (k.units or k.vivid or k.convs)) or kinds & {"land_search", "extra_land", "land_from_hand", "treasure"} \
        or any(s[0] in ("lands_any", "lands_any_n", "spend_any", "reduce", "alt", "free", "extra_land",
                                "mana_mult", "mana_add") for s in k.statics)
    draws = kinds & {"draw", "look", "tutor_multi", "wheel"} or any(
        e[0] == "tutor" and e[2] not in ("graveyard", "none") or e[0] == "recur" and e[2] == "hand" for e in fxs)
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
    'treasure 1', 'extra_land 1', 'land basic bf_t 1', 'ctr divinity 1', 'mana WUBRG',
    'tutor DEST TARGET' / 'recur DEST TARGET' (DEST hand/top/bf/graveyard; TARGET in Oracle words), 'mill 3'."""
    w = s.split()
    t = w[0]
    if t == "draw": return [("draw", int(w[1]) if w[1].isdigit() else (w[1],))]
    if t in ("scry", "surveil", "prolif", "treasure", "extra_land", "land_from_hand"): return [(t, int(w[1]))]
    if t == "look": return [("look", int(w[1]), int(w[2]))]
    if t == "land": return [("land_search", int(w[3]) if len(w) > 3 else 1, land_filter(w[1]), w[2])]
    if t == "ctr": return [("ctr", w[1], int(w[2]))]
    if t == "mana": return [("mana", [frozenset(ch) for ch in w[1]])]
    if t in ("tutor", "recur"):           # 'tutor hand a creature card' / 'recur bf a creature card'
        tg = tu.parse_target(" ".join(s.split()[2:]), {})
        return [(t, tg, w[1], max(1, min(tg.count, 7)))]
    if t == "mill": return [("mill", int(w[1]))]
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
        self.free = []; self.alts = []; self.reduce = []; self.extra_land = 0; self.prolif = 1
        self.plus = []; self.times = []; self.no_max = False; self.mana_mult = []; self.mana_add = []
        for p in perms:
            for s in p.k.statics:
                t = s[0]
                if t == "lands_any": self.lands_any = True
                elif t == "lands_any_n": self.lands_any_n = min(self.lands_any_n or 99, s[1])
                elif t == "spend_any": self.spend_any = True
                elif t == "all_colors": self.all_colors = True
                elif t == "free": self.free.append((s[1], s[2]))
                elif t == "alt": self.alts.append((s[1], s[2]))
                elif t == "reduce": self.reduce.append((s[1], s[2]))
                elif t == "extra_land": self.extra_land += s[1]
                elif t == "prolif_x2": self.prolif *= 2
                elif t == "ctr_plus": self.plus.append((s[1], s[2]))
                elif t == "ctr_times": self.times.append((s[1], s[2]))
                elif t == "no_max_hand": self.no_max = True
                elif t == "mana_mult": self.mana_mult.append((s[1], s[2]))
                elif t == "mana_add": self.mana_add.append((s[1], s[2]))

OPP_CREATURE, OPP_SPELL = Card("opponent creature spell"), Card("opponent noncreature spell")
OPP_CREATURE.types, OPP_SPELL.types = {"Creature"}, {"Instant"}

# ---------------------------------------------------------------- one game
class Game:
    def __init__(self, sim, hand, lib, rng):
        self.sim, self.hand, self.lib, self.rng = sim, hand, lib, rng
        self.gy, self.lands, self.perms, self.cmd = [], [], [], list(sim.commanders)
        self.tcast = (); self.cmd_casts = Counter(); self.turn = 0; self.phase = 0; self.drops = 0; self.treasures = 0
        self.pool = None; self.convs = []; self.dry = False; self._st = None
        self.extra = 0; self.drawn = len(hand); self.casts = 0; self.spent = 0; self.disc = 0
        self.attr = Counter(); self.first = {}; self.cmd_first = {}; self.rebound = []
        self.exile, self.unearthed = [], []
        self.recur = 0; self.cycled = 0; self.rattr = Counter(); self.tut = Counter(); self.life = START_LIFE
        self.events = {}; self.open_pool = []; self.dis = []
        self.ctr_now, self.ctr_held = [], []   # counters live this turn / held for your commander or key cards
        self.stax = []                          # live tax/lock effects: {"kind", "start", "until", "on"}
        self.hits = []; self.cleared = 0        # (turn, board before) for each hit that removed permanents
        self.ctrd = 0                           # your spells countered (still counted in casts/spent)
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
        g.exile, g.unearthed = self.exile[:], [mp[id(p)] for p in self.unearthed if id(p) in mp]
        g.rattr = Counter(); g.tut = Counter()
        g.cmd_casts = Counter(self.cmd_casts); g.first = dict(self.first); g.cmd_first = dict(self.cmd_first)
        g.attr = Counter(); g.pool = None; g.convs = []; g._st = None
        g.rng = self.sim.dry_rng; g.log = None
        g.stax = [dict(e) for e in self.stax]; g.ctr_now, g.ctr_held = self.ctr_now[:], self.ctr_held[:]
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

    def mana_scale(self, k):
        """(multiplier, extra units) a tap of k gets from Nyxbloom/Mana Reflection/Vorinclex-style effects."""
        def hit(what):
            if what == "permanent": return True
            if what == "creature": return "Creature" in k.types
            if what == "land": return k.is_land
            if what == "basic land": return k.is_land and k.basic
            return k.is_land and what in k.land_types
        st, mult, add = self.st, 1, 0
        for what, n in st.mana_mult:
            if hit(what): mult *= n
        for what, n in st.mana_add:
            if hit(what): add += n
        return mult, add

    def add_units(self, p, anyl=None):
        k, pool = p.k, self.pool
        n0 = len(pool)
        if k.is_land and (self.any_lands() if anyl is None else anyl):
            cols = self.sim.anyc.union(*(u[0] | u[1] for u in k.units)) if k.units else self.sim.anyc
            for _ in range(max(1, len(k.units))): pool.append([cols, NOC, None, False, p, False])
        else:
            reps = max(0, self.val(k.dyn_mana, p, 0)) if k.dyn_mana else 1
            for u in k.units * reps: pool.append([u[0], u[1], u[2], u[3], p, False])
            if k.vivid:
                for col in self.perm_colors(): pool.append([frozenset(col), NOC, None, False, p, False])
        mult, add = self.mana_scale(k) if (self.st.mana_mult or self.st.mana_add) else (1, 0)
        made = pool[n0:]
        if made and (mult > 1 or add):
            pool += [list(u) for u in made] * (mult - 1) + [list(made[0]) for _ in range(add)]
        for cost, outs in k.convs:
            outs = outs * max(0, self.val(k.dyn_mana, p, 0)) if k.dyn_mana else outs
            self.convs.append((p, cost, outs * mult + outs[:1] * add if outs else outs))

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
                self.perms.remove(u[4]); self.bury(u[4].k); self._st = None

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
    def spell_tax(self, k):
        """Extra generic from live tax effects (Thalia: noncreature spells; Sphere: all spells)."""
        if not self.stax or k is None: return 0
        return sum(1 for e in self.stax if self.live(e) and (e["kind"] == "taxall" or e["kind"] == "tax" and "Creature" not in k.types))

    def live(self, e):
        return e["on"] and e["start"] < self.turn <= e["until"]

    def locked(self):
        return any(e["kind"] == "lock" and self.live(e) for e in self.stax)

    def options(self, k, zone):
        st = self.st
        tax = (2 * self.cmd_casts[k] if zone == "cmd" else 0) + self.spell_tax(k)
        red = sum(n for f, n in st.reduce if spell_ok(k, f)
                  and not (f.get("first") and any(spell_ok(c, dict(f, first=False)) for c in self.tcast)))
        if k.self_red: red += k.self_red[0] * self.val(k.self_red[1], None, 0)
        if zone == "gy":
            g = k.gycast
            if g["kw"] == "unearth": return [(g["gen"], g["pips"])]          # an ability: no reducers
            gen, pips = (k.gen, k.pips) if g["gen"] is None else (g["gen"], g["pips"])
            return [(max(0, gen - red) + tax, pips)]
        xm = 2 if k.x else 0                          # X spells wait for X >= 2
        opts = [(max(0, k.gen - red) + tax + xm, k.pips)]
        for f, (ag, ap, _, _) in st.alts:
            if spell_ok(k, f): opts.append((max(0, ag - red) + tax, ap))
        if any(spell_ok(k, f) and (zone == "hand" or (not hand_only and zone == "cmd")) for f, hand_only in st.free):
            opts.append((tax, []))
        return sorted(opts, key=lambda o: o[0] + len(o[1]))

    def has(self, req, k=None):
        if req == "land": return bool(self.lands)
        if req == "gy":
            if k is None or k.gy_need is None: return False
            if any(e[0] == "recur" and e[2] == "bf" for e in k.spell + k.etb): return self.worth_target(k)
            return any(self.sim.tmatch(k.gy_need, c) for c in self.gy)
        if req == "gy_payoff": return self.gy_payoff()
        leg = req.startswith("legendary")
        return any("Creature" in p.k.types and (p.k.legendary or not leg) for p in self.perms)

    def try_cast(self, k, zone):
        if k.requires and not self.has(k.requires, k): return False
        if zone != "hand" and self.stax and self.locked() and not (zone == "gy" and k.gycast["kw"] == "unearth"): return False
        if zone == "gy" and not self.gy_extra_ok(k): return False
        for gen, pips in self.options(k, zone):
            if self.pay(k, gen, pips):
                if zone == "gy": self.gy_extra_pay(k)
                x = 0
                if k.x:
                    rest = [x_[0] for x_ in self.cands(k) if not x_[2]]
                    for i in rest: self.use_unit(i)
                    x = len(rest) + 2
                paid = gen + len(pips) + x - (2 if k.x else 0)
                if not self.countered(k, zone, paid): self.resolve(k, zone, paid, x)
                return True
        return False

    def resolve(self, k, zone, paid, x=0):
        if zone == "gy":
            self.gy.remove(k); self.recurred(k.name + " (" + k.gycast["kw"] + ")")
            if k.gycast["kw"] == "unearth":
                self.spent += paid; self.note(f"  unearth {k.name} (paid {paid})")
                self.unearthed.append(self.enter(k)); return
        if zone == "hand": self.hand.remove(k)
        elif zone == "cmd":
            self.cmd.remove(k); self.cmd_casts[k] += 1; self.cmd_first.setdefault(k.name, self.turn)
        self.casts += 1; self.spent += paid; self.tcast += (k,)
        self.note(f"  cast {k.name} ({zone}, paid {paid})")
        for gi in k.groups: self.first.setdefault(gi, self.turn)
        self.fire("cast", k)
        if k.castfx: self.do(k.castfx, k, None, x)
        if k.types & PERMANENT:
            self.enter(k, from_hand=(zone == "hand"), x=x)
        else:
            self.do(k.spell, k, None, x)
            if zone == "gy" and k.gycast["exile_after"]: self.exile.append(k)
            else: (self.rebound if k.rebound and zone == "hand" else self.gy).append(k)

    def enter(self, k, from_hand=False, x=0):
        if k.is_land: return self.land_enters(k)
        prev_drops = self.st.extra_land
        p = Perm(k, tapped=bool(k.etap), sick=True, hand=from_hand)
        self.perms.append(p); self._st = None
        for gi in k.groups: self.first.setdefault(gi, self.turn)
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
            if any(s[0] in ("mana_mult", "mana_add") for s in k.statics):
                live = {id(u[4]): u[4] for u in self.pool if not u[5] and isinstance(u[4], Perm)}
                self.pool = [u for u in self.pool if u[5] or not isinstance(u[4], Perm)]
                nc = len(self.convs)
                for q in live.values(): self.add_units(q)
                del self.convs[nc:]
            if self.usable(p): self.add_units(p); self.eager_convs()
        if k.etb: self.do(k.etb, k, p, x)
        if k.sac_etb and p in self.perms: self.perms.remove(p); self.bury(k); self._st = None
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
            if self.drops > 0 and not self.dry and self.hand_act(land_only=True): continue
            avail = sum(1 for u in self.pool if not u[5])
            cands = []
            for k in dict.fromkeys(self.hand):
                if k.is_land or k.ritual or (k.hold and not sim.cast_hold): continue
                cands.append((sim.prio(k, "hand"), k, "hand"))
            for k in self.cmd: cands.append((sim.prio(k, "cmd"), k, "cmd"))
            for k in dict.fromkeys(self.gy):
                if k.gycast and not k.ritual and not (k.hold and not sim.cast_hold):
                    cands.append((sim.prio(k, "gy"), k, "gy"))
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
            if min(g_ + len(p_) for g_, p_ in opts) > avail or (k.requires and not self.has(k.requires, k)): continue
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
                recur_ok = any(e[0] == "recur" and any(self.sim.tmatch(e[1], c) for c in self.gy) for e in fx)
                if not (kinds & {"draw", "look", "tutor", "tutor_multi", "land_search", "treasure"} or recur_ok
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
                    if ab.get("life") and self.life - ab["life"] < LIFE_FLOOR: break
                    if not self.pay(None, ab["gen"], ab["pips"]): break
                    self.life -= ab.get("life", 0)
                    if ab["tap"]:
                        p.tapped = True
                        for u in self.pool:
                            if u[4] is p: u[5] = True
                    if ab["rm"]: p.ctr[ab["rm"][0]] -= ab["rm"][1]
                    if ab["sac"]:
                        (self.lands if k.is_land else self.perms).remove(p); self.bury(k); self._st = None
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
        if key == "opp_hand": return OPP_HAND
        if key == "power": return max((q.k.power + (q.ctr or {}).get("+1/+1", 0) for q in self.perms if "Creature" in q.k.types), default=0)
        if key == "colors": return len(self.perm_colors())
        if key == "gy": return len(self.gy)
        if key == "sub": return sum(v[1] in q.k.subtypes for q in self.perms)
        if key == "devotion": return sum(1 for q in self.perms for pip in q.k.pips if v[1] in pip)
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

    # ---- tutoring and the graveyard
    def have(self):
        """Cards you already have access to: hand, battlefield, command zone."""
        return set(self.hand) | {p.k for p in self.perms} | {p.k for p in self.lands} | set(self.cmd)

    def want_bonus(self, c, have):
        """Tutor priority from the list header: '# key:' cards, then the missing piece of a '# package:'
        (more when the rest is already assembled), then a tutor that can reach a missing key/package card."""
        sim, b = self.sim, 0
        if c in have: return 0
        if c in sim.keys: b = 80
        for parts in sim.packages:
            slots = [i for i, part in enumerate(parts) if c in part]
            if not slots or any(have & parts[i] for i in slots): continue
            filled = sum(1 for part in parts if have & part)
            b = max(b, 70 + 20 * filled / len(parts))
        if not b and c in sim.finds:
            missing = sim.wanted - have
            if missing and sim.finds[c] & missing: b = 50
        return b

    def tutor_value(self, c, dest, have):
        if c.is_land:                                   # a land only when you're actually short
            short = not any(x.is_land for x in self.hand) and len(self.lands) < min(self.turn + 1, 4)
            return 75 if short else 5
        v = self.value(c) + self.want_bonus(c, have)
        if c in have: v -= 30                           # a second copy of something already in hand or play
        if dest in ("hand", "top", "exile"):
            reach = len(self.lands) + sum(1 for p in self.perms if p.k.units) + 1
            if c.mv > reach + 1: v -= 15                # can't cast it soon
        return v

    def reanimator_for(self, c):
        """How well you can use c from the graveyard: 2 = a recursion card in hand/play, 1 = in the library."""
        src = list(self.hand) + [p.k for p in self.perms]
        if any(self.sim.tmatch(e[1], c) for x in src for e in x.recur_fx): return 2
        if any(self.sim.tmatch(e[1], c) for x in self.sim.recursion for e in x.recur_fx): return 1
        return 0

    def gy_usable(self, c):
        """A flashback-style card you could actually cast from the graveyard (its own target included)."""
        return bool(c.gycast) and not (c.gy_need and not any(self.sim.tmatch(c.gy_need, x) for x in self.gy))

    def gy_value(self, c):
        """Pilot's pick for a card sent to the graveyard (Entomb, Buried Alive): a reanimation target
        you can reach beats a flashback card, which beats anything else."""
        r = self.reanimator_for(c) if "Creature" in c.types or c.types & PERMANENT else 0
        if r: return 50 * r + 3 * c.mv + c.power
        if self.gy_usable(c): return 60 + c.mv
        return c.mv

    def gy_payoff(self):
        """Worth putting a card in the graveyard: recursion in hand, play or library (Entomb before you draw
        Reanimate is the normal line), or a flashback-style card you could cast from there."""
        if any(x.recur_fx for x in self.hand) or any(p.k.recur_fx for p in self.perms): return True
        lib = set(self.lib)
        return any(x in lib for x in self.sim.recursion) or any(self.gy_usable(c) for c in lib)

    def worth_target(self, k):
        """Reanimation onto the battlefield waits for a real target: MV 4+, or anything from turn 6."""
        return any(self.sim.tmatch(k.gy_need, c) and (c.mv >= 4 or self.turn >= 6) for c in self.gy)

    def recurred(self, src, n=1):
        self.recur += n; self.rattr[src] += n
        self.note(f"    {n} card(s) back from the graveyard via {src}")

    def gy_extra_ok(self, k):
        g = k.gycast
        if g["discard"] == "card" and not self.hand: return False
        if g["discard"] == "land":
            spare = sum(c.is_land for c in self.hand) - (1 if self.drops > 0 else 0)
            if spare < 1 and not (any(c.is_land for c in self.hand) and len(self.lands) >= 6): return False
        return len(self.gy) - 1 >= g["exile_n"]

    def gy_extra_pay(self, k):
        g = k.gycast
        if g["discard"]:
            pool = [c for c in self.hand if c.is_land] if g["discard"] == "land" else self.hand
            worst = min(pool, key=self.value); self.hand.remove(worst); self.gy.append(worst); self.gain(-1, k.name)
        if g["exile_n"]:
            rest = sorted((c for c in self.gy if c is not k), key=self.gy_value)[:g["exile_n"]]
            for c in rest: self.gy.remove(c); self.exile.append(c)

    def hand_act(self, land_only=False, eot=False):
        """Cycling, typecycling and transmute from hand. land_only: find a land for a missed drop.
        eot: end of turn, spend leftover mana on dead cards (more freely with a cycling payoff out).
        Main phase: transmute toward a wanted card. Returns True if something was used."""
        if self.pool is None: return False
        have = self.have()
        payoff = any(t[0] == "cycle" for p in self.perms for t in p.k.trig)
        for card in sorted(dict.fromkeys(c for c in self.hand if c.hand_acts), key=self.value):
            for ab in card.hand_acts:
                tut = [e for e in ab["fx"] if e[0] == "tutor"]
                if land_only:
                    if not tut or not any(c.is_land and self.sim.tmatch(tut[0][1], c) for c in self.lib): continue
                elif ab["kind"] == "transmute":
                    if eot or not any(self.want_bonus(c, have) >= 50 and self.sim.tmatch(tut[0][1], c) for c in self.lib):
                        continue
                elif not eot: continue
                else:
                    need_land = not any(c.is_land for c in self.hand) and len(self.lands) < 7
                    if tut and any(c.is_land and self.sim.tmatch(tut[0][1], c) for c in self.lib):
                        if not need_land and self.value(card) > (45 if payoff else 20): continue
                    elif self.value(card) > (45 if payoff else 20): continue
                if ab.get("life") and self.life - ab["life"] < LIFE_FLOOR: continue
                if eot and sum(1 for u in self.pool if not u[5]) - ab["gen"] - len(ab["pips"]) < self.reserve(): continue
                if not self.pay(None, ab["gen"], ab["pips"]): continue
                self.life -= ab.get("life", 0)
                self.hand.remove(card); self.gy.append(card); self.gain(-1, card.name)
                self.note(f"  {ab['label']} {card.name}")
                if ab["kind"] != "transmute": self.cycled += 1
                self.do(ab["fx"], card, None, 0, land_first=land_only or ab["kind"] == "typecycle" and not
                        any(c.is_land for c in self.hand))
                if ab["kind"] != "transmute": self.fire("cycle", card)
                return True
        return False

    def do(self, fx, k, p=None, x=0, land_first=False):
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
                n = e[1] if isinstance(e[1], int) else max(size, OPP_HAND)
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
            elif t == "tutor":
                _, tg, dest, count = e
                if tutor_unread(tg): continue
                have = self.have(); picks = []
                xcap = x if any(re.match(r"mana value (?:x or less|less than or equal to x)", a) for a in tg.approx) else None
                for _ in range(count):
                    cands = [c for c in self.lib if self.sim.tmatch(tg, c) and c not in picks and (xcap is None or c.mv <= xcap)]
                    if not cands: break
                    if dest == "graveyard": pick = max(cands, key=self.gy_value)
                    elif land_first and any(c.is_land for c in cands):
                        pick = max((c for c in cands if c.is_land), key=lambda c: self.tutor_value(c, dest, have))
                    else: pick = max(cands, key=lambda c: self.tutor_value(c, dest, have))
                    self.lib.remove(pick); picks.append(pick); have.add(pick)
                self.rng.shuffle(self.lib)
                for c in picks:
                    if not self.dry: self.tut[c.name] += 1
                    self.note(f"    {name} finds {c.name} -> {dest}")
                    if dest == "top": self.lib.append(c)
                    elif dest in ("bf", "bf_t"):
                        if c.is_land: self.land_enters(c, force_tapped=dest == "bf_t")
                        elif c.types & PERMANENT: self.enter(c)
                        else: self.hand.append(c); self.gain(1, name)
                    elif dest == "graveyard": self.gy.append(c)
                    elif dest == "none": self.exile.append(c)
                    else: self.hand.append(c); self.gain(1, name)
            elif t == "tutor_multi":
                picks = []
                for f in e[1]:
                    targets = [c for c in self.lib if spell_ok(c, f) and c not in picks]
                    if targets:
                        pick = max(targets, key=self.value); self.lib.remove(pick); picks.append(pick)
                self.rng.shuffle(self.lib)
                for c in picks:
                    if e[2] == "top": self.lib.append(c)
                    elif e[2] in ("bf", "bf_t") and c.types & PERMANENT: self.enter(c)
                    elif e[2] == "graveyard": self.gy.append(c)
                    else: self.hand.append(c); self.gain(1, name)
            elif t == "recur":
                _, tg, dest, count = e
                if tutor_unread(tg): continue
                for _ in range(count):
                    cands = [c for c in self.gy if self.sim.tmatch(tg, c)]
                    if not cands: break
                    if dest == "bf": pick = max(cands, key=lambda c: (c.mv, c.power, self.value(c)))
                    else: pick = max(cands, key=self.value)
                    self.gy.remove(pick); self.recurred(name)
                    if k.life_per_mv: self.life -= pick.mv
                    if dest == "bf":
                        if pick.is_land: self.land_enters(pick)
                        elif pick.types & PERMANENT: self.enter(pick)
                        else: self.gy.append(pick)
                    else: self.hand.append(pick); self.gain(1, name)
            elif t == "cond":
                if self.opp_lands() > len(self.lands): self.do(e[2], k, p, x)
            elif t == "dig_gy":
                if self.dry: continue
                top = [self.lib.pop() for _ in range(min(e[1], len(self.lib)))]
                ok = [c for c in top if self.sim.tmatch(e[2], c)]
                if ok:
                    pick = max(ok, key=lambda c: self.tutor_value(c, "hand", self.have()))
                    top.remove(pick); self.hand.append(pick); self.gain(1, name)
                self.gy += top
            elif t == "mill":
                n = self.val(e[1], p, x)
                if self.dry or not isinstance(n, int) or n <= 0: continue
                for _ in range(min(n, len(self.lib))): self.gy.append(self.lib.pop())
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
            elif t == "token":
                cnt = self.val(e[1], p, x)
                tk = self.sim.token_card(e)
                for _ in range(max(0, min(cnt, 20))):
                    if len(self.perms) >= TOKEN_CAP: self.note("    token cap reached"); break
                    self.enter(tk)
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
                        and not (c.requires and not self.has(c.requires, c))]
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
                    if (filt.get("sub") and not (filt["sub"] & obj.k.subtypes)) or (filt.get("nontoken") and obj.k.token) \
                            or (filt.get("token") and not obj.k.token): continue
                if once:
                    if p.once is None: p.once = set()
                    if (ev, self.phase) in p.once: continue
                    p.once.add((ev, self.phase))
                if tax and self.rng.random() < TAX_PAID: continue
                self.do(fx, p.k, p)

    # ---- turn structure
    def opponents(self):
        """The other turns of the round: 'each upkeep / end step' triggers, plus the fixed approximations
        for opponent-triggered cards (see POD). No opponent decisions are simulated."""
        for _ in range(POD):
            self.phase += 1
            self.fire("upkeep", each_only=True)
            self.fire("opp_draw")
            if self.opp_lands() < 8: self.fire("opp_land")
            self.fire("opp_cast", OPP_CREATURE if self.rng.random() < OPP_CREATURE_SHARE else OPP_SPELL)
            if self.rng.random() < OPP_SECOND:
                self.fire("opp_cast", OPP_CREATURE if self.rng.random() < OPP_CREATURE_SHARE else OPP_SPELL)
                self.fire("opp_second")
            self.fire("end", each_only=True)

    def answer_cost(self, c):
        """Mana an answer needs right now (0 if it's free with a commander out)."""
        tax = self.spell_tax(c)
        if c.free_cmdr and any(p.k in self.sim.commanders for p in self.perms): return tax, []
        return c.gen + tax, c.pips

    def reserve(self):
        """Mana the pilot keeps open at end of turn for its cheapest held answer (never taps out to cycle)."""
        costs = [g + len(p) for c in self.hand if c.answer for g, p in [self.answer_cost(c)]]
        return min(costs) if costs else 0

    def try_answer(self, ev, pool):
        """Use held answers against a disruption event, paying from `pool`. Returns the answer type that stopped
        it, or None. A backed-up event ('!') counters the first answer you throw at it."""
        kind, backed = ev["kind"], ev.get("backup")
        while True:
            for c in sorted((c for c in dict.fromkeys(self.hand) if c.answer and kind in ANSWERS[c.answer]),
                            key=lambda c: sum(len(x) if isinstance(x, list) else x for x in self.answer_cost(c))):
                g, p = self.answer_cost(c)
                saved, self.pool, self.convs = self.pool, pool, []
                ok = (not g and not p) or self.pay(c, g, p)
                self.pool = saved
                if not ok: continue
                self.hand.remove(c); self.gy.append(c); self.casts += 1; self.spent += g + len(p)
                if backed:
                    self.note(f"  {c.name} tries to answer the {DIS_NAMES[kind]}, but it's backed up: countered")
                    backed = False; self.ctrd += 1; break
                self.note(f"  {c.name} answers the {DIS_NAMES[kind]}")
                return c.answer
            else:
                return None

    def bury(self, k):
        if not k.token: self.gy.append(k)

    def leave(self, p, why, dest="gy"):
        self.perms.remove(p); self._st = None
        if p.k in self.sim.commanders: self.cmd.append(p.k)
        elif p.k.token: pass
        else: {"gy": self.gy, "exile": self.exile, "hand": self.hand}[dest].append(p.k)
        self.note(f"    {p.k.name} {why}")

    def disrupt(self, ev):
        """A disruption event after your turn. Records (kind, 'hit' / 'answered' / 'no target')."""
        kind, cmdrs = ev["kind"], self.sim.commanders
        if kind == "cmd": targets = [p for p in self.perms if p.k in cmdrs]
        elif kind in ("removal", "removal+"): targets = [p for p in self.perms if p.k not in cmdrs]
        elif kind == "wipe": targets = [p for p in self.perms if "Creature" in p.k.types]
        elif kind == "gy": targets = list(self.gy)
        elif kind == "ld": targets = list(self.lands)
        elif kind in PERSIST: targets = [True]
        elif kind == "nuke+gy": targets = list(self.perms) + list(self.gy)
        else: targets = list(self.perms)                                     # nuke, rift
        if not targets: self.dis.append((kind, "no target")); return
        self.note(f"  DISRUPTION: {DIS_NAMES[kind]}" + (" (backed up)" if ev.get("backup") else ""))
        ans = self.try_answer(ev, self.open_pool)
        if ans and not (kind == "nuke+gy" and ans == "protect"):
            self.dis.append((kind, "answered")); return
        self.dis.append((kind, "hit"))
        before = len(self.perms)
        r = self.sim.dis_rng
        if kind in ("cmd", "removal"):
            self.leave(max(targets, key=lambda p: (p.k.mv, p.k.name)) if r.random() < 0.5 else r.choice(targets), "is removed")
        elif kind == "removal+":
            w = self.sim.wanted
            self.leave(max(targets, key=lambda p: (bool(p.k.groups) or p.k in w, p.k.mv, p.k.name)), "is exiled", "exile")
        elif kind == "gy":
            self.note(f"    graveyard exiled ({len(self.gy)} cards)"); self.exile += self.gy; self.gy = []
        elif kind == "ld":
            nb = [p for p in self.lands if not p.k.basic]
            p = max(nb, key=lambda p: (len(set().union(*(u[0] | u[1] for u in p.k.units)) if p.k.units else 0), p.k.name)) \
                if nb else r.choice(self.lands)
            self.lands.remove(p); self.gy.append(p.k); self._st = None
            self.note(f"    {p.k.name} is destroyed")
        elif kind in PERSIST:
            n = self.sim.persist
            self.stax.append({"kind": kind, "start": self.turn, "until": self.turn + n, "on": True})
            self.note(f"    {DIS_NAMES[kind]} for {n} turns (or until your removal kills it)")
        elif kind == "rift":
            for p in list(self.perms): self.leave(p, "returns to hand", "hand")
            self.treasures = 0
        else:                                                                   # wipe, nuke, nuke+gy
            ex = kind == "nuke+gy"
            for p in targets:
                if isinstance(p, Perm): self.leave(p, "is exiled" if ex else "dies in the wipe", "exile" if ex else "gy")
            if kind != "wipe": self.treasures = 0
            if ex: self.exile += self.gy; self.gy = []
        if len(self.perms) < before: self.hits.append((self.turn, before))

    def clear_stax(self):
        """Main phase: kill a live tax/lock piece with held removal that can hit it (Swords on Thalia)."""
        for e in self.stax:
            if not self.live(e) or e["until"] == self.turn and e["kind"] != "lock": continue
            if e["kind"] == "lock" and not self.cmd and not any(c.gycast for c in self.gy): continue
            want = PERSIST[e["kind"]]
            for c in sorted((c for c in dict.fromkeys(self.hand) if want in c.kill), key=lambda c: c.mv):
                opts = self.options(c, "hand")
                if not any(self.pay(c, g_, p_) for g_, p_ in opts[:1]): continue
                g_, p_ = opts[0]
                self.hand.remove(c); self.gy.append(c); self.casts += 1; self.spent += g_ + len(p_)
                e["on"] = False; self.cleared += 1
                self.note(f"  {c.name} removes the {DIS_NAMES[e['kind']]} piece")
                break

    def countered(self, k, zone, paid):
        """Counter events: a live counter hits your first spell of its MV or more (or your commander) this turn;
        a held one (ctrK) waits for your commander or a key/tracked card. True if the spell was countered."""
        if zone == "gy" or self.dry or not (self.ctr_now or self.ctr_held): return False
        ev = next((e for e in self.ctr_now if k.mv >= e["mv"] or zone == "cmd"), None)
        if ev: self.ctr_now.remove(ev)
        elif self.ctr_held and (zone == "cmd" or k.groups or k in self.sim.wanted): ev = self.ctr_held.pop(0)
        else: return False
        self.note(f"  DISRUPTION: {DIS_NAMES[ev['kind']]} on {k.name}" + (" (backed up)" if ev.get("backup") else ""))
        if self.try_answer(ev, self.pool): self.dis.append((ev["kind"], "answered")); return False
        self.dis.append((ev["kind"], "hit")); self.ctrd += 1
        if zone == "hand": self.hand.remove(k); self.gy.append(k)
        else: self.cmd_casts[k] += 1
        self.casts += 1; self.spent += paid; self.fire("cast", k)
        return True

    def opp_lands(self):
        return min(self.turn - (1 if self.sim.on_play else 0), 8)

    def play(self, turns, rec):
        sim = self.sim
        for k in [c for c in self.hand if c.leyline]:
            self.hand.remove(k); self.enter(k)
        for t in range(1, turns + 1):
            self.turn = t; self.phase += 1; self.tcast = ()
            for p in self.lands: p.tapped = False
            for p in self.perms: p.tapped = False; p.sick = False
            self.drops = 1 + self.st.extra_land
            for q in [q for q in self.perms if q.k.cum_upkeep]:
                q.ctr = q.ctr or {}; q.ctr["age"] = q.ctr.get("age", 0) + 1
                if q.ctr["age"] > 3: self.perms.remove(q); self.bury(q.k); self._st = None
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
            evs = self.events.get(t, ())
            self.ctr_now = [e for e in evs if e["kind"] == "counter"]
            self.ctr_held += [e for e in evs if e["kind"] == "counterK"]
            self.build_pool()
            if self.stax and not self.dry: self.clear_stax()
            pool_n = sum(1 for u in self.pool if not u[5])
            cols = set().union(*(u[0] | u[1] for u in self.pool if not u[5])) if self.pool else set()
            if self.st.spend_any and cols - {"C"}: cols |= sim.anyc
            rec["lands"][t].append(len(self.lands)); rec["mana"][t].append(pool_n)
            rec["colors"][t].append(sim.anyc <= cols)
            rec["stranded"][t].append(self.stranded())
            self.note(f"  mana {pool_n} ({''.join(sorted(cols))}) at the start of main")
            self.cast_loop()
            if self.hand_act(): self.cast_loop(activate=False)       # transmute, then cast what it found
            while self.hand_act(eot=True): pass                     # leftover mana: cycle dead cards
            for e in self.ctr_now: self.dis.append((e["kind"], "no target"))
            self.ctr_now = []
            self.open_pool = [u for u in self.pool if not u[5]] if self.pool else []
            self.pool = None; self.convs = []
            self.fire("end")
            for q in self.unearthed:
                if q in self.perms: self.perms.remove(q); self.exile.append(q.k); self._st = None
            self.unearthed = []
            for e in evs:
                if e["kind"] not in ("counter", "counterK"): self.disrupt(e)
            self.open_pool = []
            if not self.st.no_max and len(self.hand) > 7:
                self.hand.sort(key=self.value)
                n = len(self.hand) - 7
                self.gy += self.hand[:n]; del self.hand[:n]; self.disc += n
            rec["hand"][t].append(len(self.hand)); rec["extra"][t].append(self.extra)
            rec["casts"][t].append(self.casts); rec["spent"][t].append(self.spent)
            rec["disc"][t].append(self.disc)
            rec["gy"][t].append(len(self.gy)); rec["recur"][t].append(self.recur); rec["cycled"][t].append(self.cycled)
            rec["board"][t].append(len(self.perms))
            rec["cmd_out"][t].append(bool(sim.commanders) and all(any(p.k is c for p in self.perms) for c in sim.commanders))
            if self.log is not None and self.perms: self.note("  board: " + "; ".join(p.k.name + (str(p.ctr) if p.ctr else "") for p in self.perms))
            self.opponents()
        for e in self.ctr_held: self.dis.append((e["kind"], "no target"))
        self.ctr_held = []

# ---------------------------------------------------------------- simulation
def blank_rec(turns):
    return {m: {t: [] for t in range(1, turns + 1)} for m in
            ("lands", "mana", "colors", "stranded", "hand", "extra", "casts", "spent", "disc", "cmd_out",
             "gy", "recur", "cycled", "board")}

def load_ladder(bracket, horizon=0):
    """The bracket's ladder from data/goldfish_gradients.json, with per-rung, per-slot firing odds precomputed
    (weight x intensity, never decreasing for a slot as the ladder climbs)."""
    data = json.load(open(GRADIENTS_FILE, encoding="utf-8"))
    spec = data["brackets"].get(str(bracket))
    if not spec: return None
    lo, hi = spec["intensity"]; W, bw = data["weights"], data["backup_weight"]
    rungs, p, prev = [], [], {}
    n = len(spec["rungs"])
    for r, line in enumerate(spec["rungs"]):
        s_ = lo + (hi - lo) * r / max(1, n - 1)
        toks, pr = [], {}
        for part in line.split():
            slot, _, tok = part.partition("=")
            t, e = parse_event(tok, slot)
            w = W["ctr" if e["code"].rstrip("!").startswith("ctr") else e["code"].rstrip("!")]
            pr[slot] = prev[slot] = max(prev.get(slot, 0), min(1.0, w * s_))
            if e["backup"]: pr[slot + "!"] = prev[slot + "!"] = max(prev.get(slot + "!", 0), min(1.0, bw * s_))
            toks.append((slot, tok))
        rungs.append(toks); p.append(pr)
    return {"bracket": bracket, "horizon": horizon or spec["horizon"], "rungs": rungs, "p": p, "intensity": (lo, hi),
            "baselines": data["baselines"], "shuffles": data["shuffles"], "fold": data["fold"], "persist": data["persist_turns"]}

def load_overrides():
    if not os.path.exists(OVERRIDES_FILE): return {}
    data = json.load(open(OVERRIDES_FILE, encoding="utf-8"))
    return {mtg.norm(k): v for k, v in data.items() if not k.startswith("_")}

class Sim:
    def __init__(self, names, commanders, args, groups, cache, anyc, want=None):
        self.args, self.anyc, self.groups = args, anyc, groups
        self.deck = [cache[n] for n in names]
        self.commanders = [cache[n] for n in commanders]
        self.land_cards = [k for k in dict.fromkeys(self.deck) if k.is_land]
        self.order = {c: i for i, c in enumerate(args.order.split(","))}
        self.on_play, self.kill_turn, self.cast_hold = not args.draw, args.kill_commander, args.cast_interaction
        self.dry_rng = random.Random(0)
        self.tm = {}; self.tokens = {}
        self.dis_rng = random.Random(0)
        self.persist = 3
        self.keys, self.packages = want or (set(), [])
        self.wanted = set(self.keys) | {c for parts in self.packages for part in parts for c in part}
        uniq = list(dict.fromkeys(self.deck + self.commanders))
        self.recursion = [k for k in uniq if k.recur_fx]
        self.finds = {}
        for k in uniq:
            tgs = [e[1] for e in all_fx(k) if e[0] == "tutor" and e[2] not in ("graveyard", "none")]
            if tgs: self.finds[k] = {c for c in uniq if any(self.tmatch(tg, c) for tg in tgs)}

    def scenario(self, i, seed, turns, fixed=None):
        """Sampled-mode disruption for game i: {turn: [events]}. Its own RNG, so the shuffle matches the clean game."""
        if fixed is not None: evs = [(t, dict(e)) for t, e in fixed]
        else:
            r = random.Random(seed * 7919 + i * 31 + 5)
            x = r.random(); n = 0 if x < 0.25 else 1 if x < 0.75 else 2
            evs = []
            for _ in range(n):
                y, kind = r.random(), DIS_KINDS[-1][0]
                for kk, w in DIS_KINDS:
                    if y < w: kind = kk; break
                    y -= w
                last = turns if kind == "counter" else turns - 1
                evs.append(parse_event(f"{kind}@{r.randint(min(3, last), max(3, last))}"))
        out = {}
        for t, e in evs: out.setdefault(t, []).append(e)
        return out

    def ladder_events(self, i, seed, lad, rung, force=False):
        """Rung `rung` of the ladder for shuffle i: ({turn: [events]}, fired tokens). One roll per slot per shuffle,
        shared by every rung, so a slot that fires at a rung fires at every higher rung."""
        out, fired = {}, []
        for slot, tok in lad["rungs"][rung]:
            t, e = parse_event(tok, slot)
            if not force and random.Random(f"{seed}|{i}|{slot}").random() >= lad["p"][rung][slot]: continue
            if e["backup"] and not force and random.Random(f"{seed}|{i}|{slot}!").random() >= lad["p"][rung][slot + "!"]:
                e["backup"] = False
            fired.append(f"{slot}={e['code'] if e['backup'] else e['code'].rstrip('!')}@{t}")
            out.setdefault(t, []).append(e)
        return out, fired

    def token_card(self, e):
        _, n, pw, subs, text, kind = e
        key = (pw, subs, text, kind)
        k = self.tokens.get(key)
        if k is None:
            tl = ("Token Creature" if kind == "creature" else "Token Artifact") + (" — " + " ".join(subs) if subs else "")
            raw = {"name": (" ".join(subs) or "Creature") + " token", "type_line": tl, "oracle_text": text,
                   "power": str(pw if isinstance(pw, int) else 0), "cmc": 0, "colors": [], "mana_cost": ""}
            k = compile_card(raw, self.anyc); k.token = True; k.cat = "token"
            self.tokens[key] = k
        return k

    def tmatch(self, tg, k):
        key = (id(tg), id(k))
        r = self.tm.get(key)
        if r is None: r = self.tm[key] = bool(k.raw) and tg.matches(k.raw)
        return r

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

    def game(self, i, seed, turns, rec, events=None, trace=False, reseed=0):
        rng = random.Random(seed * 1_000_003 + i)
        hand, lib, size, mulls = self.opening(rng)
        if reseed: rng = random.Random(f"{seed}|{i}|baseline {reseed}")   # same library, fresh in-game randomness
        g = Game(self, hand, lib, rng)
        if events: g.events = events
        self.dis_rng = random.Random(seed * 104_729 + i)
        if trace: g.log = [f"game {i + 1}: kept {len(hand)} after {mulls} mulligan(s)"
                           + (f"; disruption {', '.join(DIS_NAMES[e['kind']] + ('!' if e.get('backup') else '') + f'@T{t}' for t, es in sorted(events.items()) for e in es)}" if events else "")]
        g.play(turns, rec)
        if g.log: print("\n".join(g.log)); print()
        ct = [0] + [rec["casts"][t][-1] for t in range(1, turns + 1)]
        bt = [None] + [rec["board"][t][-1] for t in range(1, turns + 1)]
        rebuild = None
        if g.hits:
            h, before = g.hits[0]
            rebuild = next((u - h for u in range(h + 1, turns + 1) if bt[u] >= before), -1)   # -1: not by the horizon
        g.final = {"cmd_out": rec["cmd_out"][turns][-1], "cmd_turns": sum(rec["cmd_out"][t][-1] for t in range(1, turns + 1)), "casts": g.casts, "spent": g.spent, "extra": g.extra,
                   "board": len(g.perms), "recur": g.recur, "dead": sum(1 for t in range(1, turns + 1) if ct[t] == ct[t - 1]),
                   "rebuild": rebuild, "dis": list(g.dis), "cleared": g.cleared, "resolved": g.casts - g.ctrd,
                   "first": {gi: g.first.get(gi) for gi in range(len(self.groups))}}
        return g, size, mulls

    def run(self, trials, turns, seed):
        T = range(1, turns + 1)
        rec = {m: {t: [] for t in T} for m in
               ("lands", "mana", "colors", "stranded", "hand", "extra", "casts", "spent", "disc", "cmd_out",
                "gy", "recur", "cycled", "board")}
        first = {gi: [] for gi in range(len(self.groups))}
        cmd_first = {c.name: [] for c in self.commanders}
        attr, kept, mull_n, rattr, tut = Counter(), Counter(), 0, Counter(), Counter()
        finals = []
        for i in range(trials):
            fixed = {self.kill_turn - 1: [parse_event(f"cmd@{self.kill_turn - 1}")[1]]} if self.kill_turn and self.kill_turn > 1 else None
            g, size, mulls = self.game(i, seed, turns, rec, events=fixed,
                                       trace=self.args.trace == i + 1)
            kept[size] += 1; mull_n += mulls > 0
            for gi in first: first[gi].append(g.first.get(gi))
            for c in cmd_first: cmd_first[c].append(g.cmd_first.get(c))
            attr.update(g.attr); rattr.update(g.rattr); tut.update(g.tut)
            finals.append(g.final)
        return {"rec": rec, "first": first, "cmd_first": cmd_first, "attr": attr, "kept": kept, "rattr": rattr, "tut": tut,
                "mulliganed": mull_n / trials, "trials": trials, "turns": turns, "finals": finals}

    def run_disruption(self, trials, turns, seed, clean_finals, fixed=None):
        """Replay each game on the same shuffle with its sampled disruption; pair it with the clean game."""
        out = []
        for i in range(trials):
            ev = self.scenario(i, seed, turns, fixed)
            if not ev: out.append(([], [], clean_finals[i], clean_finals[i])); continue
            scratch = blank_rec(turns)
            g, _, _ = self.game(i, seed, turns, scratch, events=ev, trace=self.args.disruption_trace == str(i + 1))
            kinds = [e["kind"] for t in sorted(ev) for e in ev[t]]
            out.append((kinds, g.dis, clean_finals[i], g.final))
        return out

    def run_ladder(self, lad, shuffles, seed, force=False):
        """Per shuffle: `baselines` clean games (same library, reseeded in-game randomness) and every rung of the
        ladder. A rung where nothing fires is the first baseline game exactly, so it isn't replayed."""
        turns, nb = lad["horizon"], lad["baselines"]
        tr = self.args.disruption_trace
        tr_s, _, tr_r = tr.partition(":") if tr else ("", "", "")
        out = []
        for i in range(shuffles):
            base = [self.game(i, seed, turns, blank_rec(turns), reseed=b)[0].final for b in range(nb)]
            rungs = []
            for r in range(len(lad["rungs"])):
                ev, fired = self.ladder_events(i, seed, lad, r, force)
                if not ev: rungs.append((fired, base[0])); continue
                trace = tr_s == str(i + 1) and tr_r == str(r + 1)
                g, _, _ = self.game(i, seed, turns, blank_rec(turns), events=ev, trace=trace)
                rungs.append((fired, g.final))
            out.append((base, rungs))
        return out

# ---------------------------------------------------------------- report
def pct(v): return f"{100 * v:5.1f}%"
def q(vals, p):
    s = sorted(vals); return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]
def mean(v): return sum(v) / len(v) if v else 0
def by_turn(turns_list, t): return mean([1 if x is not None and x <= t else 0 for x in turns_list])

def nz(counter):
    """Drop entries that round to nothing (cycling nets 0 extra cards; it is filtering, not advantage)."""
    return Counter({k: v for k, v in counter.items() if abs(v) >= 1})

def summary(res, groups):
    rec, T = res["rec"], res["turns"]
    out = {"turns": {}}
    for t in range(1, T + 1):
        out["turns"][t] = {m: ({"p10": q(v, .1), "med": q(v, .5), "p90": q(v, .9), "mean": round(mean(v), 2)}
                               if m not in ("colors", "cmd_out") else round(mean(v), 4))
                           for m, v in ((m, rec[m][t]) for m in rec)}
    out["commander_by_turn"] = {c: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for c, v in res["cmd_first"].items()}
    out["tracked_by_turn"] = {groups[gi][0]: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for gi, v in res["first"].items()}
    out["extra_card_sources"] = {k: round(v / res["trials"], 3) for k, v in nz(res["attr"]).most_common(12)}
    out["recursion_sources"] = {k: round(v / res["trials"], 3) for k, v in nz(res["rattr"]).most_common(10)}
    out["tutor_targets"] = {k: round(v / res["trials"], 3) for k, v in nz(res["tut"]).most_common(10)}
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
        if meta.get("priorities"): print(f"tutor priorities from the list header: {meta['priorities']}")
        print(f"opponents: not simulated. {meta['opp_n']} card(s) use the fixed opponent approximations (~opp in --explain); "
              f"{meta['vac_n']} need opponents and do nothing here (vacuum)")
        if meta.get("kill"): print(f"--kill-commander {meta['kill']}: every clean game loses the commander after turn {meta['kill'] - 1}")
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
    print(f"{'turn':<5}{'extra (cum)':<13}{'mean':>6}{'hand':>10}{'hand<=1':>9}{'stranded':>10}{'discarded':>11}"
          f"{'graveyard':>11}{'recursion':>11}{'cycled':>8}")
    for t in range(1, T + 1):
        d = tt[t]
        print(f"T{t:<4}{trio(t, 'extra'):<13}{d['extra']['mean']:>6.2f}{trio(t, 'hand'):>10}"
              f"{pct(mean_leq1(d)):>9}{d['stranded']['mean']:>10.2f}{d['disc']['mean']:>11.2f}"
              f"{trio(t, 'gy'):>11}{d['recur']['mean']:>11.2f}{d['cycled']['mean']:>8.2f}")
    src = sm["extra_card_sources"]
    if src:
        print(f"extra cards by source (avg per game over {T} turns): "
              + " | ".join(f"{k} {v:.2f}" for k, v in src.items()))
    if sm.get("recursion_sources"):
        print(f"recursion by source (cards back from the graveyard, avg per game): "
              + " | ".join(f"{k} {v:.2f}" for k, v in sm["recursion_sources"].items()))
    if sm.get("tutor_targets"):
        print(f"tutor targets (times fetched, avg per game): "
              + " | ".join(f"{k} {v:.2f}" for k, v in sm["tutor_targets"].items()))

def disruption_summary(pairs, groups):
    """Per scenario: games, events answered / with no target, and the average change vs the same clean game."""
    buckets = {}
    for kinds, res, c, d in pairs:
        label = "none" if not kinds else DIS_NAMES[kinds[0]] if len(kinds) == 1 else "two events"
        buckets.setdefault(label, []).append((res, c, d))
        if kinds: buckets.setdefault("any disruption", []).append((res, c, d))
    out = {}
    for label, rows in buckets.items():
        n = len(rows)
        evs = [r for res, _, _ in rows for r in res]
        live = [r for r in evs if r[1] != "no target"]
        dm = lambda key: round(mean([d[key] - c[key] for _, c, d in rows]), 2)
        out[label] = {"games": n, "share": 0, "no_target": round(len([r for r in evs if r[1] == "no target"]) / len(evs), 3) if evs else 0,
                      "answered": round(len([r for r in live if r[1] == "answered"]) / len(live), 3) if live else 0,
                      "d_casts": dm("casts"), "d_spent": dm("spent"), "d_extra": dm("extra"), "d_board": dm("board"),
                      "d_recur": dm("recur"), "d_cmd_turns": dm("cmd_turns"),
                      "tracked": {groups[gi][0]: [round(mean([1 if c["first"][gi] is not None else 0 for _, c, _ in rows]), 3),
                                                  round(mean([1 if d["first"][gi] is not None else 0 for _, _, d in rows]), 3)]
                                  for gi in range(len(groups))}}
    for v in out.values(): v["share"] = round(v["games"] / len(pairs), 3)
    return out

def print_disruption(label, ds, T, fixed):
    order = ["none"] + [DIS_NAMES[k] for k, _ in DIS_KINDS] + ["two events", "any disruption"]
    head = (f"fixed scenario for every game: {fixed}" if fixed else
            "sampled per game: 25% none, 50% one event, 25% two; events on turns 3+")
    print(f"\n## {label}: disruption (same shuffles as the clean games; {head})")
    print(f"{'scenario':<19}{'games':>7}{'answered':>10}{'no target':>11}{'Δspells':>9}{'Δmana':>8}{'Δcards':>8}"
          f"{'Δboard':>8}{'Δrecur':>8}{'Δcmdr turns':>13}")
    for name in order:
        v = ds.get(name)
        if not v: continue
        print(f"{name:<19}{v['games']:>7}{pct(v['answered']):>10}{pct(v['no_target']):>11}{v['d_casts']:>+9.2f}{v['d_spent']:>+8.2f}"
              f"{v['d_extra']:>+8.2f}{v['d_board']:>+8.2f}{v['d_recur']:>+8.2f}{v['d_cmd_turns']:>+13.2f}")
    for g, (a, b) in (ds.get("any disruption", {}).get("tracked") or {}).items():
        print(f"tracked {g} by T{T} (games with disruption): {pct(a).strip()} clean → {pct(b).strip()} disrupted")
    print(f"Δ = disrupted minus the same clean game, averaged over T1-T{T} (board: at end of T{T}; cmdr turns: turns ending with "
          "your commander out). 'answered' = your held counters/protection stopped it (mana left open, or free with a commander "
          "out); 'no target' = nothing there to hit. Positive Δspells/Δmana after a hit usually means rebuilding with spare mana.")

def sd(v):
    m = mean(v); return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0

def ladder_summary(out, lad):
    """Per rung: events fired / hit / answered, Δ vs the shuffle's baseline mean, fold rate, rebuild; per shuffle:
    the breakpoint (first folding rung) and what changed at it."""
    keys = ("resolved", "spent", "extra", "board", "recur", "cmd_turns", "dead")
    base_casts = sorted(b["resolved"] for base, _ in out for b in base)
    floor_pct = lad["fold"]["casts_below_clean_pct"]
    p10 = q(base_casts, floor_pct / 100)
    lost = lad["fold"]["cmd_turns_lost"]
    bm = [{k: mean([b[k] for b in base]) for k in keys} for base, _ in out]
    noise = {k: round(mean([sd([b[k] for b in base]) for base, _ in out]), 2) for k in ("resolved", "cmd_turns")}
    weak = mean([1 if m["resolved"] < p10 else 0 for m in bm])
    def folds(d, m):
        if not any(r == "hit" for _, r in d["dis"]): return False
        return (d["resolved"] < p10 <= m["resolved"]) or (m["cmd_turns"] - d["cmd_turns"] >= lost)
    rows = []
    for r in range(len(lad["rungs"])):
        games = [(rungs[r], bm[i]) for i, (_, rungs) in enumerate(out)]
        evs = [x for (f, d), _ in games for x in d["dis"]]
        live = [x for x in evs if x[1] != "no target"]
        reb = [d["rebuild"] for (f, d), _ in games if d["rebuild"] is not None]
        row = {"rung": r + 1, "fired": round(mean([len(f) for (f, _), _ in games]), 2),
               "hits": round(mean([sum(1 for x in d["dis"] if x[1] == "hit") for (f, d), _ in games]), 2),
               "answered": round(len([x for x in live if x[1] == "answered"]) / len(live), 3) if live else 0,
               "fold": round(mean([1 if folds(d, m) else 0 for (f, d), m in games]), 3),
               "rebuilt": round(mean([1 if x >= 0 else 0 for x in reb]), 3) if reb else None,
               "rebuild_med": q(sorted(x for x in reb if x >= 0), 0.5) if any(x >= 0 for x in reb) else None,
               "cleared": round(mean([d["cleared"] for (f, d), _ in games]), 2)}
        for k in keys: row["d_" + k] = round(mean([d[k] - m[k] for (f, d), m in games]), 2)
        rows.append(row)
    bps, blame = [], Counter()
    for i, (_, rungs) in enumerate(out):
        bp = next((r for r in range(len(rungs)) if folds(rungs[r][1], bm[i])), None)
        bps.append(bp)
        if bp is not None:
            prev = set(rungs[bp - 1][0]) if bp else set()
            for tok in set(rungs[bp][0]) - prev: blame[tok] += 1
    hit = sorted(b + 1 for b in bps if b is not None)
    return {"bracket": lad["bracket"], "horizon": lad["horizon"], "shuffles": len(out), "baselines": lad["baselines"],
            "p10_casts": p10, "cmd_lost": lost, "floor_pct": floor_pct, "noise": noise, "weak": round(weak, 3),
            "base": {k: round(mean([m[k] for m in bm]), 2) for k in keys}, "rungs": rows,
            "never": round(mean([1 if b is None else 0 for b in bps]), 3),
            "bp": {"p25": q(hit, 0.25), "med": q(hit, 0.5), "p75": q(hit, 0.75)} if hit else None,
            "blame": blame.most_common(8), "forced": lad.get("forced", False)}

def print_ladder(label, ls):
    n, T = ls["shuffles"], ls["horizon"]
    print(f"\n## {label}: disruption ladder, Bracket {ls['bracket']} ({n} shuffles × ({ls['baselines']} clean + "
          f"{len(ls['rungs'])} rungs) = {n * (ls['baselines'] + len(ls['rungs']))} games; horizon T{T}"
          + ("; --ladder-max: every event fires" if ls["forced"] else "") + ")")
    b = ls["base"]
    print(f"clean baseline (mean of {ls['baselines']} per shuffle): {b['resolved']:.1f} spells, {b['cmd_turns']:.1f} commander turns, "
          f"{b['dead']:.1f} dead turns by T{T}. noise band (avg per-shuffle SD across baselines): ±{ls['noise']['resolved']} spells, "
          f"±{ls['noise']['cmd_turns']} cmdr turns. clean floor (P{ls['floor_pct']}) = {ls['p10_casts']} spells.")
    print(f"{'rung':>4}{'fired':>7}{'hit':>6}{'answered':>10}{'Δspells':>9}{'Δmana':>8}{'Δcards':>8}{'Δboard':>8}{'Δrecur':>8}"
          f"{'Δcmdr t':>9}{'Δdead t':>9}{'rebuilt':>9}{'in':>4}{'fold':>8}")
    for r in ls["rungs"]:
        rb = "  -" if r["rebuilt"] is None else pct(r["rebuilt"]).strip()
        print(f"{r['rung']:>4}{r['fired']:>7.2f}{r['hits']:>6.2f}{pct(r['answered']):>10}{r['d_resolved']:>+9.2f}{r['d_spent']:>+8.2f}"
              f"{r['d_extra']:>+8.2f}{r['d_board']:>+8.2f}{r['d_recur']:>+8.2f}{r['d_cmd_turns']:>+9.2f}{r['d_dead']:>+9.2f}"
              f"{rb:>9}{(str(r['rebuild_med']) if r['rebuild_med'] is not None else '-'):>4}{pct(r['fold']):>8}")
    bp = ls["bp"]
    print(f"breakpoint (first rung that folds, per shuffle): " +
          (f"P25 {bp['p25']} / median {bp['med']} / P75 {bp['p75']}; " if bp else "") + f"never folded: {pct(ls['never']).strip()}"
          + (f"; {pct(ls['weak']).strip()} of shuffles start below the floor clean (they fold only on commander turns)" if ls["weak"] else ""))
    if ls["blame"]:
        print("what changed at the breakpoint (new or moved events, shuffles): " + "; ".join(f"{t} {c}" for t, c in ls["blame"]))
    if any(r["cleared"] for r in ls["rungs"]):
        print("tax/lock pieces killed by your held removal (per game, top rung): " + f"{ls['rungs'][-1]['cleared']:.2f}")
    print(f"fold = a hit event pushed the game below the clean floor (from at/above it), or cost {ls['cmd_lost']}+ commander turns vs "
          f"the shuffle's baseline mean. Δ = rung game minus that baseline mean (Δ smaller than the noise band is noise); spells = "
          f"spells that resolved (countered ones don't count; their mana does). fired = "
          "events that rolled in; hit = landed unanswered on something. rebuilt/in = games whose first board hit got back to the "
          "pre-hit board size by the horizon / median turns it took. Events: data/goldfish_gradients.json (docs/GOLDFISH.md).")

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
    rows.append((f"recursion T{T} (avg)", [f"{sm['turns'][T]['recur']['mean']:.2f}" for _, sm in builds]))
    rows.append((f"cards cycled T{T} (avg)", [f"{sm['turns'][T]['cycled']['mean']:.2f}" for _, sm in builds]))
    if all("disruption" in sm and "any disruption" in sm["disruption"] for _, sm in builds):
        rows.append((f"disrupted: Δspells T{T}", [f"{sm['disruption']['any disruption']['d_casts']:+.2f}" for _, sm in builds]))
        rows.append((f"disrupted: Δcmdr turns", [f"{sm['disruption']['any disruption']['d_cmd_turns']:+.2f}" for _, sm in builds]))
        rows.append(("disrupted: answered", [pct(sm['disruption']['any disruption']['answered']).strip() for _, sm in builds]))
    if all("ladder" in sm for _, sm in builds):
        L = [sm["ladder"] for _, sm in builds]
        rows.append(("ladder: median breakpoint", [str(l["bp"]["med"]) if l["bp"] else "none" for l in L]))
        rows.append(("ladder: never folded", [pct(l["never"]).strip() for l in L]))
        rows.append(("ladder: fold (avg over rungs)", [pct(mean([r["fold"] for r in l["rungs"]])).strip() for l in L]))
        rows.append(("ladder: fold at top rung", [pct(l["rungs"][-1]["fold"]).strip() for l in L]))
        rows.append(("ladder: Δcmdr turns top rung", [f"{l['rungs'][-1]['d_cmd_turns']:+.2f}" for l in L]))
    w = max(len(r[0]) for r in rows) + 2
    cw = max(10, max(len(l) for l in labels) + 2)
    print(f"{'':<{w}}" + "".join(f"{l:>{cw}}" for l in labels))
    for name, vals in rows:
        print(f"{name:<{w}}" + "".join(f"{v:>{cw}}" for v in vals))

def explain(cache, names, commanders):
    _EXPLAIN_DECK[:] = [cache[n].raw for n in dict.fromkeys(commanders + names)]
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
            if k.convs: bits.append(f"filter {k.convs[0][0]}->" + ("X" if k.dyn_mana else str(len(k.convs[0][1]))))
            if k.dyn_mana: bits.append("X = " + " ".join(str(x) for x in k.dyn_mana))
            if k.etap: bits.append("enters tapped")
        if k.etb: bits.append("ETB " + ", ".join(fx_str(e) for e in k.etb) + (" (sacrificed)" if k.sac_etb else ""))
        if k.spell: bits.append(", ".join(fx_str(e) for e in k.spell))
        for ev, f, fx, once, tax, each in k.trig:
            if not f: fl = ""
            elif "types" in f:
                fl = "(" + ",".join(sorted({x.lower() for x in f["types"]} | ({"legendary"} if f["legendary"] else set())
                                           | {"non" + x.lower() for x in f["non"]})) + ")"
            else:
                fl = "(" + ("another " if f["another"] else "") + ("nontoken " if f.get("nontoken") else "") + ("token " if f.get("token") else "") \
                     + (" ".join(sorted(f["sub"])) + " " if f.get("sub") else "") \
                     + ("" if f.get("sub") and f["type"] == "Permanent" else f["type"].lower()) + (f" power>={f['power']}" if f["power"] else "") + ")"
            bits.append(f"on {ev}{fl}{' 1/turn' if once else ''}{' taxed' if tax else ''}{' +opp turns' if each else ''}: "
                        + ", ".join(fx_str(e) for e in fx))
        for a in k.acts:
            cost = ("T " if a["tap"] else "") + (f"{a['gen'] + len(a['pips'])} " if a["gen"] or a["pips"] else "") \
                   + ("sac " if a["sac"] else "") + (f"-{a['rm'][1]} {a['rm'][0]} " if a["rm"] else "") \
                   + (f"{a['life']} life " if a.get("life") else "")
            bits.append(f"act [{cost.strip()}]: " + ", ".join(fx_str(e) for e in a["fx"]))
        for c_, fx in k.pw: bits.append(f"loyalty {c_:+d}: " + ", ".join(fx_str(e) for e in fx))
        if k.ctr_enter: bits.append(f"enters with {k.ctr_enter[1]} {k.ctr_enter[0]}" + (" if cast from hand" if k.ctr_enter[2] else ""))
        for s in k.statics:
            if s[0] == "aura_mana": continue
            if s[0] == "reduce":
                f = s[1]
                what = " ".join(sorted(f["types"]) + sorted(f.get("sub") or ()) + sorted(f["colors"])) or "all"
                bits.append(f"reduce {{{s[2]}}}: {what}" + (f" power>={f['pow_min']}" if f.get("pow_min") else "")
                            + (" (first each turn)" if f.get("first") else ""))
            elif s[0] == "free":
                f = s[1]
                what = " ".join(sorted(f["types"]) + sorted(f.get("sub") or ())) or "all"
                bits.append(f"free: {what} spells" + (" from hand" if s[2] else " (command zone too)"))
            elif s[0] == "mana_mult": bits.append(f"mana x{s[2]} ({s[1]}s)")
            elif s[0] == "mana_add": bits.append(f"mana +{s[2]} per tap ({s[1]}s)")
            else: bits.append(s[0])
        if k.self_red: bits.append(f"costs {{{k.self_red[0]}}} less per " + " ".join(k.self_red[1]))
        if k.leyline: bits.append("leyline")
        if k.requires == "gy": bits.append("needs a target in your graveyard")
        elif k.requires == "gy_payoff": bits.append("cast only with a graveyard payoff (recursion in hand/play or a flashback-style card to fetch)")
        elif k.requires: bits.append("needs a " + k.requires)
        if k.hold: bits.append("held (interaction)" + (f"; can kill tax/lock pieces: {'/'.join(sorted(k.kill))}" if k.kill else ""))
        if k.answer: bits.append(f"answers disruption: {k.answer}" + (" (free with a commander out)" if k.free_cmdr else ""))
        if k.cum_upkeep: bits.append("cumulative upkeep: let go after 3 upkeeps ~approx")
        if k.opp_approx and not any("~opp" in b for b in bits): bits.append("~opp")
        if k.ritual: bits.append("ritual (cast only to enable a spell)")
        if k.mdfc: bits.append("MDFC land back")
        if k.rebound: bits.append("rebound")
        for a in k.hand_acts:
            cost = f"{a['life']} life" if a.get("life") else f"{{{a['gen'] + len(a['pips'])}}}"
            bits.append(f"{a['label']} {cost}: " + ", ".join(fx_str(e) for e in a["fx"]))
        if k.gycast:
            g = k.gycast
            cost = "mana cost" if g["gen"] is None else str(g["gen"] + len(g["pips"]))
            bits.append(f"{g['kw']} from graveyard ({cost}" + (f", discard a {g['discard']}" if g["discard"] else "")
                        + (f", exile {g['exile_n']} others" if g["exile_n"] else "") + ")")
        role = "land" if k.is_land else k.cat
        status = ("override" if k.override else k.status) if not k.is_land else ("land" if not k.notes else "land*")
        line = f"{status:<9}{role:<7}{k.name} — {'; '.join(bits) or 'body only'}"
        if k.notes: line += "  [" + "; ".join(k.notes) + "]"
        print(line)
    print("\nnonland: " + ", ".join(f"{v} {s}" for s, v in counts.most_common()))

# ---------------------------------------------------------------- main
def header_wants(path, found, cache, names):
    """'# key:' and '# package:' header lines -> (set of key Cards, [package: [set of Cards per part]])."""
    meta = mtg.parse_deck_meta(path)
    by_name = {}
    for n in names: by_name.setdefault(found[n]["name"], cache[n])
    keys = set()
    for v in (meta.get("key") or "").replace(" + ", ";").split(";"):
        c = mtg.find(v.strip())[0] if v.strip() else None
        if c and c["name"] in by_name: keys.add(by_name[c["name"]])
    specs = [sm.parse_package(v) for v in (meta.get("package") or [])]
    trees = None
    if any(p.lower().startswith("tag:") for _, parts in specs for p in parts):
        trees = mtg.load_tags_multi(sorted({p[4:].strip() for _, parts in specs for p in parts if p.lower().startswith("tag:")}))
    pk = []
    for _, parts in specs:
        mem = [{by_name[n] for n in sm._part_members(p, set(by_name), trees)} for p in parts]
        if all(mem): pk.append(mem)
    return keys, pk

def main():
    ap = argparse.ArgumentParser(description="Monte Carlo goldfish simulator (see module docstring)")
    ap.add_argument("deck")
    ap.add_argument("--turns", type=int, default=8); ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--draw", action="store_true"); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--track", action="append", default=[]); ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--kill-commander", type=int, default=0); ap.add_argument("--order", default=ORDER_DEFAULT)
    ap.add_argument("--disruption", default="auto"); ap.add_argument("--disruption-trace", default="")
    ap.add_argument("--bracket", type=int, default=0); ap.add_argument("--shuffles", type=int, default=0)
    ap.add_argument("--horizon", type=int, default=0); ap.add_argument("--ladder-max", action="store_true")
    ap.add_argument("--cast-interaction", action="store_true"); ap.add_argument("--no-mulligan", action="store_true")
    ap.add_argument("--trace", type=int, default=0)
    ap.add_argument("--explain", action="store_true"); ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.deck): sys.exit(f"deck file not found: {args.deck}")
    if args.trials < 1: sys.exit("--trials must be at least 1")
    if args.turns < 1: sys.exit("--turns must be at least 1")
    fixed = None
    if args.disruption not in ("auto", "ladder", "sample", "off"):
        fixed = []
        for part in args.disruption.replace(",", ";").split(";"):
            try: fixed.append(parse_event(part))
            except ValueError:
                sys.exit(f"--disruption {part!r}: use KIND@TURN with KIND one of {', '.join(DIS_CODES)} (add ! for backed up; "
                         "e.g. 'wipe@5;cmd@4;ctrK!@3'), 'ladder', 'sample' or 'off'")

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
    header_tracks = mtg.parse_deck_meta(args.deck).get("track", [])     # '# track: Label=REGEX' lines
    for t in list(dict.fromkeys(header_tracks + args.track)):
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
    want = header_wants(args.deck, found, cache, raw_lib + raw_cmd)
    bracket = args.bracket or (mtg.parse_deck_meta(args.deck).get("bracket") or 0)
    lad, mode, mode_note = None, args.disruption if fixed is None else "fixed", ""
    if mode in ("auto", "ladder"):
        lad = load_ladder(bracket, args.horizon) if bracket else None
        if lad: mode = "ladder"
        elif mode == "ladder":
            sys.exit(f"--disruption ladder needs Bracket 2, 3 or 4 (# bracket: header or --bracket); got {bracket or 'none'}")
        else:
            mode = "sample"
            mode_note = (f"no disruption ladder for Bracket {bracket} (ladders: 2-4); " if bracket else
                         "no bracket in the header or --bracket, so no disruption ladder; ") + "using the sampled disruption read"
    if mode == "ladder":
        if args.disruption_trace and not re.fullmatch(r"\d+:\d+", args.disruption_trace):
            sys.exit("--disruption-trace in ladder mode: SHUFFLE:RUNG, e.g. 3:12")
        if args.ladder_max: lad["forced"] = True
    prio_txt = "; ".join((["key: " + ", ".join(sorted(k.name for k in want[0]))] if want[0] else [])
                         + ([f"{len(want[1])} package(s)"] if want[1] else []))
    nonland = [cache[n] for n in dict.fromkeys(raw_lib) if not cache[n].is_land]
    st = Counter(k.status for k in nonland)
    meta = {"commander": " + ".join(found[n]["name"] for n in raw_cmd) or "(no commander)", "n": len(raw_lib),
            "trials": args.trials, "turns": args.turns, "draw": args.draw, "seed": args.seed, "kill": args.kill_commander,
            "opp_n": sum(1 for k in nonland if k.opp_approx) + sum(1 for n in raw_cmd if cache[n].opp_approx),
            "vac_n": sum(1 for k in nonland if k.status == "vacuum"),
            "priorities": prio_txt, "disruption_mode": mode, "mode_note": mode_note,
            "model": f"{len(nonland)} nonland cards: {st['modeled']} modeled, {st['partial']} partial, {st['blank']} blank, "
                     f"{st['vacuum']} vacuum, {st['held']} held as interaction; {sum(k.override for k in cache.values())} overrides"}
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
        sim = Sim(lib, raw_cmd, args, groups, cache, anyc, want=want)
        res = sim.run(args.trials, args.turns, args.seed)
        sm = summary(res, groups)
        if mode == "ladder":
            sim.persist = lad["persist"]
            sm["ladder"] = ladder_summary(sim.run_ladder(lad, args.shuffles or lad["shuffles"], args.seed, args.ladder_max), lad)
        elif mode != "off":
            sm["disruption"] = disruption_summary(sim.run_disruption(args.trials, args.turns, args.seed, res["finals"], fixed), groups)
        for t in sm["turns"]:
            sm["turns"][t]["hand"]["leq1"] = round(mean([1 if h <= 1 else 0 for h in res["rec"]["hand"][t]]), 4)
        results.append((label, sm))
    if args.json:
        print(json.dumps({"meta": meta, "builds": {l: s for l, s in results}}, indent=1)); return
    for i, (label, sm) in enumerate(results):
        print_report(label, sm, meta, groups, show_header=(i == 0))
        if "disruption" in sm:
            if mode_note and i == 0: print(f"\nnote: {mode_note}")
            print_disruption(label, sm["disruption"], args.turns, args.disruption if fixed else None)
        if "ladder" in sm: print_ladder(label, sm["ladder"])
    if len(results) > 1: compare_table(results, groups, args.turns)
    print("\nscope: plays alone by design (opponents are approximations, never decisions). not modeled: combat, token copies and noncreature tokens other than Treasure/Clue/Gold; "
          "partial/blank cards are cast for their mana cost only. Treat numbers as a floor/ceiling sketch, not a prediction.")

if __name__ == "__main__":
    main()
