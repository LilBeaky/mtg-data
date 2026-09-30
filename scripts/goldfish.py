#!/usr/bin/env python3
"""
goldfish.py — Monte Carlo goldfish simulator for Commander decks (mtg-data).

Plays a decklist alone thousands of times with a greedy pilot and reports how it
develops turn by turn: lands, mana and colors, commander timing, when tracked
cards get cast, card flow (extra cards, hand size, cards stranded by color,
and which cards produced the card advantage), and combat: attacks into three
opponents at 40 life (blockers and combat denial from --blockers; they never attack), damage, poison,
commander damage per opponent, triggers of every kind, and the turn the table
dies (which ends the game). Full docs: USE_INSTRUCTIONS.md §6, docs/GOLDFISH.md.

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
import argparse, itertools, json, os, random, re, sys
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
# (no knobs; tagged ~opp in --explain): one other turn per living opponent (OPP_N, a 4-player pod);
# each opponent draws 1 and casts 1 spell a turn (40% creatures), a second spell 30% of the time;
# taxes (Rhystic, Tithe) are paid 75% of the time, so each lands about once a round; an opponent
# holds 4 cards; an opponent's land count is their turn count.
OPP_CREATURE_SHARE, OPP_SECOND, TAX_PAID, OPP_HAND = 0.4, 0.3, 0.75, 4
OPP_LINE = re.compile(r"\bopponents?\b|attacks? you\b|\bother players?\b|each player(?! may)|\btarget player\b")
# ...but a line that touches anything the sim tracks is a real miss, not vacuum: you (a clause led by "you", counters and
# pumps on your things, keyword grants), opponents' life totals (damage, drain, life gain), or their creatures (the
# --blockers boards: removal, edicts, taps, -X/-X). Only lines touching none of those are opponent-only.
SELF_GAIN = re.compile(r"(?:^|[,.;:]\s*|\b(?:then|and|if you do,?)\s+)you (?:may )?(?!can't|don't|control)[a-z]+"
                       r"|\b(?:create|investigate|proliferate|scry|surveil|manifest|amass|explore|connive)\b|\bdraw (?:a|\w+) cards?|\badd \{"
                       r"|under your control|\bgets? \+|\bcounters? on ~|\b(?:has|have|gains?) (?:trample|flying|haste|menace|lifelink|"
                       r"deathtouch|double strike|first strike|vigilance|indestructible)"
                       r"|\bdeals? [^.]{0,25}damage|\blose[s]? [^.]{0,25}\blife|\bgains? (?:\d+|x|that much) life|\bpoison|\bmills?\b"
                       r"|\bsacrifices?\b|\btap (?:up to \w+ )?target|\bcreatures? (?:an opponent|your opponents|target opponent|that player|each opponent) controls?"
                       r"|\bgets? -|\bextra turn|\bsearch(?:es)? (?:your|their) library|\breturn ~|from your graveyard|\bdetain")
START_LIFE, LIFE_FLOOR = 40, 20
FLOOR_BY_BRACKET = {4: 10}   # optional life payments stop here; set from the deck's bracket at run time (default 20)
# Combat (docs/GOLDFISH.md "Combat"). Three opponents at START_LIFE. An opponent dies at 0 life, POISON_KILL
# poison, or CMD_KILL combat damage from one commander; killing all of them ends the game. Opponents never attack.
# Their boards come from --blockers (a fixed spec; the blocker gradient will feed the same channel): creatures that
# block, and combat denial (DENY) that stops, taxes or blanks attacks. With no spec every board is empty.
OPP_N, POISON_KILL, CMD_KILL = 3, 10, 21
XCOMBAT_CAP = 5          # additional combat phases per turn (stops Port Razer-style loops)
DENY = {"fog": "fog", "settle": "Settle the Wreckage", "prop": "attack tax (Propaganda)", "arb": "Silent Arbiter",
        "bridge": "Ensnaring Bridge", "moat": "Moat", "maze": "Maze of Ith"}
DENY_TYPE = {"prop": "enchantment", "bridge": "artifact", "moat": "enchantment", "arb": "creature"}   # what held removal must hit
BLOCKER_KW = ("flying", "reach", "deathtouch", "first strike", "double strike", "indestructible", "lifelink", "infect",
              "wither", "flanking", "horsemanship", "shadow", "white", "blue", "black", "red", "green", "artifact", "wall")
COMBAT_KW = ("flying", "reach", "trample", "vigilance", "haste", "lifelink", "deathtouch", "menace", "first strike",
             "double strike", "indestructible", "defender", "infect", "wither", "shadow", "horsemanship", "fear",
             "intimidate", "skulk", "flanking", "prowess", "exalted", "battle cry", "myriad", "melee", "dethrone",
             "training", "mentor", "living weapon", "unblockable", "hexproof", "shroud")
COMBAT_KWN = ("toxic", "poisonous", "annihilator", "bushido", "rampage", "afflict")
# trigger events -> the kinds the report counts them under
TRIG_KIND = {"blocked_self": "combat", "blocked": "combat", "cast": "cast", "draw_card": "other", "dies_att": "dies", "etb": "enter", "landfall": "enter", "upkeep": "timed", "end": "timed", "drawstep": "timed", "main1": "timed",
             "combat_begin": "timed", "attack": "combat", "attack_self": "combat", "attack_any": "combat", "cdmg": "combat",
             "cdmg_self": "combat", "cdmg_any": "combat", "attack_att": "combat", "cdmg_att": "combat", "unblocked_self": "combat", "dies": "dies", "dies_self": "dies", "opp_cast": "~opp",
             "opp_draw": "~opp", "opp_second": "~opp", "opp_land": "~opp", "cycle": "other", "prolif": "other",
             "gy_self": "dies", "leave_self": "dies", "sac": "other", "gain": "other", "dmg_att": "other", "dmg_self": "other"}
EVASIVE = {"flying", "shadow", "horsemanship", "fear", "intimidate", "skulk", "unblockable", "menace"}
NEUTRAL_KW = re.compile(r"^(?:flash|riot|hexproof(?: from [\w ]+)?|shroud|ward(?: [—-]? ?.*)?|protection from [\w ,]+|changeling|"
                        r"banding|split second|devoid|cascade|partner(?: with [\w ,']+)?|"
                        r"reconfigure .*|crew \d+|ninjutsu .*|dash .*|evoke .*|persist|undying|riot|decayed|ascend)$")
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
DIS_NAMES.update(DENY)
# event codes (ladder file and --disruption) -> (kind, min MV for counters)
DIS_CODES = {"cmd": ("cmd", 0), "rem": ("removal", 0), "removal": ("removal", 0), "rem+": ("removal+", 0),
             "wipe": ("wipe", 0), "nuke": ("nuke", 0), "nuke+gy": ("nuke+gy", 0), "rift": ("rift", 0), "gy": ("gy", 0),
             "ld": ("ld", 0), "tax": ("tax", 0), "taxall": ("taxall", 0), "lock": ("lock", 0), "counter": ("counter", 3),
             "ctr2": ("counter", 2), "ctr3": ("counter", 3), "ctr4": ("counter", 4), "ctrK": ("counterK", 0)}
PERSIST = {"tax": "creature", "taxall": "artifact", "lock": "creature"}   # stax effects -> the permanent type behind them
ANSWERS = {"counter": {"cmd", "removal", "removal+", "wipe", "nuke", "nuke+gy", "rift", "tax", "taxall", "lock",
                       "counter", "counterK", "fog", "settle", "prop", "arb", "bridge", "moat"},
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

def parse_blockers(spec):
    """--blockers 'SPEC' -> [(turn, until, seats, item)]. Tokens split by ';'. A creature: [SEAT:]P/T[ keyword...]@T[-U][xN]
    (SEAT 1-3 or 'each'; default each opponent). Denial: [SEAT:]CODE@T[-U], CODE in DENY (default seat 1).
    @T: on that opponent's battlefield for your turn-T combat (it arrives on their turn before); -U: gone after your
    turn U; xN: N copies. Keywords: BLOCKER_KW (two-word ones with a space or '_'). Raises ValueError on a bad token."""
    out = []
    for tok in re.split(r"[;,]", spec or ""):
        tok = tok.strip().lower()
        if not tok: continue
        m = re.fullmatch(r"(?:(each|[1-3])\s*:)?\s*(?P<body>.+?)\s*@(?P<t>\d+)(?:-(?P<u>\d+))?(?:x(?P<n>\d+))?", tok)
        if not m or int(m.group("t")) < 1: raise ValueError(tok)
        t, u, n = int(m.group("t")), int(m.group("u")) if m.group("u") else None, int(m.group("n") or 1)
        if (u is not None and u < t) or n < 1: raise ValueError(tok)
        body, seat = m.group("body"), m.group(1)
        seats = None if seat in (None, "each") else [int(seat) - 1]
        if body in DENY:
            if seat is None: seats = [0]
            item = {"deny": body}
        else:
            bm = re.fullmatch(r"(\d+)/(\d+)((?:\s+[a-z_]+)*)", body)
            if not bm: raise ValueError(tok)
            words, kws, i = bm.group(3).replace("_", " ").split(), set(), 0
            while i < len(words):
                two = " ".join(words[i:i + 2])
                if two in BLOCKER_KW: kws.add(two); i += 2
                elif words[i] in BLOCKER_KW: kws.add(words[i]); i += 1
                else: raise ValueError(tok)
            item = {"p": int(bm.group(1)), "t": int(bm.group(2)), "kw": frozenset(kws)}
        out += [(t, u, seats, item)] * n
    return out

EVADE_TXT = {"pow_le": "unblockable by power {0} or less", "pow_ge": "unblockable by power {0} or more", "gt_pow": "unblockable by greater power",
             "max1": "blocked by one at most", "color": "unblockable by {0}", "min": "blocked by {0}+ only", "only": "blocked by {0} only"}

def evade_rule(how, what):
    """'~ can't be blocked by creatures with power 2 or less' -> ('pow_le', 2); None if unread."""
    what = what.strip()
    if how == "by":
        m = re.fullmatch(r"creatures with power (\d+) or (less|greater)", what)
        if m: return ("pow_le" if m.group(2) == "less" else "pow_ge", int(m.group(1)))
        if what == "creatures with greater power": return ("gt_pow",)
        if what == "more than one creature": return ("max1",)
        m = re.fullmatch(r"(white|blue|black|red|green|artifact) creatures", what)
        if m: return ("color", m.group(1))
        if what == "walls": return ("color", "wall")
        if what == "creatures with flying": return ("color", "flying")
    else:
        m = re.fullmatch(r"(two|three|four) or more creatures", what)
        if m: return ("min", num(m.group(1)))
        m = re.fullmatch(r"(white|blue|black|red|green|artifact) creatures|(walls)|creatures with (flying)", what)
        if m: return ("only", "wall" if m.group(2) else m.group(1) or m.group(3))
    return None

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
    return out - {"Artifact", "Creature", "Land", "Enchantment", "Planeswalker", "Instant", "Sorcery", "Battle", "Kindred",
                  # sentence words of those rules, not subtypes ('Creatures and kindreds share...', 'One creature type is')
                  "Artifacts", "Creatures", "Enchantments", "Lands", "Planeswalkers", "Instants", "The", "See", "One", "All",
                  "Of", "Time", "Lord"}

SUBTYPES = _load_subtypes() | {"Chosen"}    # 'Chosen': 'the chosen type' outside a deck (matches nothing)
CHOSEN_TYPE = None       # the deck's creature type for 'choose a creature type' cards (set by main before compiling; chosen_type)

def chosen_type(cmds, lib):
    """The creature type a tribal pilot names: the most common among the deck's creatures (commanders count twice), if at
    least three share it. None: no tribe, 'the chosen type' matches nothing."""
    cnt = Counter()
    for c, w in [(c, 2) for c in cmds] + [(c, 1) for c in lib]:
        tl = (c.get("card_faces") or [c])[0].get("type_line") or c.get("type_line") or ""
        main, _, sub = tl.partition("—")
        if "Creature" in main or "Kindred" in main:
            for t in sub.split():
                if t in SUBTYPES: cnt[t] += w
    t, n = cnt.most_common(1)[0] if cnt else (None, 0)
    return t if n >= 3 else None

def chosen_text(text):
    """'creature spells you cast of the chosen type' -> 'Elf creature spells you cast' (CHOSEN_TYPE or the placeholder)."""
    if "chosen type" not in text.lower(): return text
    t = CHOSEN_TYPE or "Chosen"
    text = re.sub(r"\b(creatures?|creature spells?|creature cards?|permanents?|spells?|cards?)( you (?:control|cast))? of the chosen type\b",
                  lambda m: f"{t} {m.group(1)}{m.group(2) or ''}", text, flags=re.I)
    return re.sub(r"\bcreatures? of the chosen type\b", f"{t} creatures", text, flags=re.I)

def _load_ability_words():
    """CR 207.2c: ability words (Metalcraft, Threshold, ...) label an ability and have no rules meaning."""
    try:
        with open(mtg.RULES_FILE, encoding="utf-8", errors="ignore") as fh:
            m = re.search(r"^207\.2c .*?The ability words are (.+?)\.$", fh.read(), re.M)
    except Exception:
        return set()
    return {w.strip().replace("’", "'") for w in re.split(r",\s*(?:and\s+)?", m.group(1))} if m else set()

ABILITY_WORDS = _load_ability_words()

def _load_land_types():
    """CR 205.3i land types (Forest, Desert, Gate, ...): fodder of these is a land, which fodder filters don't take."""
    try:
        with open(mtg.RULES_FILE, encoding="utf-8", errors="ignore") as fh:
            m = re.search(r"^205\.3i .*?The land types are (.+?)\.(?:\s|$)", fh.read(), re.M)
    except Exception:
        return set(t.capitalize() for t in BASIC)
    return {w.strip().replace("’", "'") for w in re.split(r",\s*(?:and\s+)?", m.group(1))} if m else set(t.capitalize() for t in BASIC)

LAND_TYPES = _load_land_types()
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
            st = as_subtype(w)
            if st: f["sub"].add(st)               # Dragon / Aura spells, Elves: a real subtype narrows the filter (read, not unknown)
            else: f["unknown"] = True
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
ATTACHED_DYN = ((r"^auras? and equipment attached to (?:it|~|that creature|enchanted creature|equipped creature)", ("attached", "both")),
                (r"^auras? attached to (?:it|~|that creature|enchanted creature)", ("attached", "aura")),
                (r"^equipment attached to (?:it|~|that creature|equipped creature)", ("attached", "equip")),
                (r"^auras? you control (?:that's|that are) attached to (?:a )?creatures?", ("auras_on_cr",)))

RX_DOMAIN = r"^basic land types? among lands you control"

def dyn_key(what):
    w = what.lower()
    if re.search(RX_DOMAIN, w): return ("domain",)
    if re.search(r"colors? of mana spent to cast (?:it|~|this spell)", w): return ("converge",)
    m = re.match(r"^your devotion to (white|blue|black|red|green)(?: and (white|blue|black|red|green))?$", w.strip())
    if m: return ("devotion",) + tuple(COLOR_WORDS[c] for c in m.groups() if c)          # Gray Merchant
    for rx, key in ATTACHED_DYN:
        if re.search(rx, w): return key
    m = re.match(r"^(?:the number of )?([a-z\-']+?)(?: creatures?| permanents?| lands?)? you control$", w.strip())
    if m and as_subtype(m.group(1)): return ("sub", as_subtype(m.group(1)))      # 'Elves you control', 'Forests you control'
    for rx, key in ((r"(\S+) counters? on (?:it|~)", "ctr"), (r"cards? in [^.]*?opponent's hand", "opp_hand"),
                    (r"greatest power", "power"),
                    (r"^creature cards? in your graveyard", "gy_creature"), (r"^land cards? in your graveyard", "gy_land"),
                    (r"^instant and(?:/or)? sorcery cards? in your graveyard", "gy_instsorc"),
                    (r"(?:^|\beach )cards? in your graveyard", "gy"), (r"^cards? in your hand", "hand"), (r"^opponents? you have", "opps"), (r"^your life total", "life"),
                    (r"colors? among", "colors"), (r"lands? you control", "lands"),
                    (r"creatures? you control", "creatures"), (r"artifacts? you control", "artifacts"),
                    (r"enchantments? you control", "enchantments"), (r"permanents? you control", "permanents")):
        m = re.search(rx, w)
        if m: return ("ctr", m.group(1)) if key == "ctr" else (key,)
    return None

QUALIFIED = re.compile(r"\b(attacking|blocking|tapped|untapped|with|that|other|another|opponents?|each player|died|this turn|named|modified|type|party|among|exiled)\b")

def clean_dyn(what):
    """dyn_key for counts the sim can read exactly; a qualified count ('attacking creature', 'creature with a counter') is None."""
    if any(re.search(rx, what.lower()) for rx, _ in ATTACHED_DYN): return dyn_key(what)     # 'Aura attached to it': read exactly
    if re.search(RX_DOMAIN, what.lower()): return ("domain",)                                # domain: 'type' and 'among' aren't qualifiers here
    return None if QUALIFIED.search(what.lower()) else dyn_key(what)

OPP_SUBJ = ("target opponent", "each opponent", "an opponent", "that player", "its controller", "its owner", "their controller",
            "that creature's controller", "that permanent's controller", "that spell's controller")
SUBJ = (r"(?P<subj>\b(?:target opponent|each opponent|an opponent|that player|target player|each player|you|its controller|its owner"
        r"|their controller|that (?:creature|permanent|spell)'s controller)\s+)?(?:may )?")

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
    if not any(rx.search(s) for _, rx in tu.DEST_RX):         # 'Search ... . Put that card onto the battlefield' (Eldritch Evolution)
        nx = re.match(r"\.\s*((?:then )?put (?:that card|it|them|those cards)[^.]*)", m.string[m.end():])
        if nx and not re.search(r"\bif\b|\bunless\b", nx.group(1)): dest = tutor_dest(nx.group(1))    # not 'onto the battlefield if it's a land'
    orig = "search your library for " + _orig(m, 1)          # "and/or graveyard" searches read as library-only
    tm = tu.SEARCH_RX.search(orig)
    tg = tu.parse_target(tm.group("what") if tm else _orig(m, 1), _CTX["raw"] or {})
    rm = re.search(r"mana value (equal to|x or less, where x is) (\w+) plus the sacrificed (\w+)'s mana value", s)
    if rm:                                                     # Birthing Pod, Neoform, Eldritch Evolution: tied to the fodder
        tg.approx = [a for a in tg.approx if not a.startswith("mana value")]
        tg.approx.append(f"mana value {'=' if rm.group(1) == 'equal to' else '<='} sacrificed {rm.group(3)}'s + {num(rm.group(2))}")
    return ("tutor", tg, dest, max(1, min(tg.count, 7)))

def rel_mv(tg):
    """A search tied to the sacrificed permanent's mana value ('=' or '<=', plus N), or None."""
    for a in tg.approx:
        m = re.match(r"mana value (=|<=) sacrificed \w+'s \+ (\d+)", a)
        if m: return m.group(1), int(m.group(2))
    return None

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
    if re.search(r"\b(?:destroy|exile) (?:another )?target|if (?:that|the) creature (?:dies|died)|that creature's power|its controller", before[-160:]) \
            and not re.search(r"you may have its controller $", before):     # Najeela: the attacking Warrior's controller is you
        return None                                   # the token comes off someone else's creature: not in a vacuum
    if re.search(r"\bcop(?:y|ies)\b", desc + rest): return None               # copies aren't modeled
    n = _xn(m) if m.group("n") == "x" else num(m.group("n"))              # Krenko: 'X, where X is the number of Goblins'
    if n is None: return None
    n = n if isinstance(n, (int, tuple)) or n == "X" else 1
    tapped = "tapped" if re.match(r"create \S+ tapped\b", m.group(0)) else False
    fe = re.search(r"\bfor each (.+)$", rest)
    if fe:
        n = clean_dyn(fe.group(1))
        if not n: return None                                               # counts things the sim can't see
    quotes = _CTX.get("quotes") or []
    qm = re.search(r"@q(\d+)@", rest) or re.match(r"\.?\s*(?:it|they|those tokens|each of them) (?:has|have) @q(\d+)@", m.string[m.end():])
    text = quotes[int(qm.group(1))] if qm and int(qm.group(1)) < len(quotes) else ""
    if m.group("p") is not None or "creature" in desc:
        pw, tg = m.group("p"), m.group("t")
        pw = "X" if pw == "x" else int(pw) if pw else 0
        tg = "X" if tg == "x" else int(tg) if tg else 0
        subs = tuple(dict.fromkeys(x for x in (as_subtype(w) for w in re.findall(r"[A-Za-z\-']+", _orig(m, "desc"))) if x))
        wm = re.search(r"\bwith ([^.@]*)", rest)
        kws = frozenset(w for w in COMBAT_KW if wm and re.search(r"\b" + w + r"\b", wm.group(1)))
        kind = "artifact creature" if re.search(r"\bartifact\b", desc) else "creature"      # Servo, Thopter: artifacts too
        return ("token", n, pw, subs, text, kind, tg, kws, "attacking" in rest or tapped)
    if re.search(r"\bclue\b", desc): return CLUE_E[:1] + (n,) + CLUE_E[2:8] + (tapped,)
    if re.search(r"\bfood\b", desc): return FOOD_E[:1] + (n,) + FOOD_E[2:8] + (tapped,)
    if re.search(r"\bgold\b", desc): return ("token", n, 0, ("Gold",), "Sacrifice ~: Add one mana of any color.", "artifact", 0, frozenset(), tapped)
    if re.search(r"\bartifact\b", desc):                                     # 'an artifact token named Munitions with "..."'
        nm = re.search(r"\bnamed ([a-z][a-z' ]*?)(?= with\b| that\b|\s*@|$)", rest)
        if not nm and not text: return None
        return ("token", n, 0, (nm.group(1).strip().title(),) if nm else (), text, "artifact", 0, frozenset(), tapped)
    return None

# noncreature token templates (the effect tuple of a 'token' effect; e[8] = True attacking / "tapped" / False)
CLUE_E = ("token", 1, 0, ("Clue",), "{2}, Sacrifice ~: Draw a card.", "artifact", 0, frozenset(), False)
FOOD_E = ("token", 1, 0, ("Food",), "{2}, {T}, Sacrifice ~: You gain 3 life.", "artifact", 0, frozenset(), False)
TREASURE_E = ("token", 1, 0, ("Treasure",), "{T}, Sacrifice ~: Add one mana of any color.", "artifact", 0, frozenset(), False)
THOPTER_E = ("token", 1, 1, ("Thopter",), "", "artifact creature", 1, frozenset({"flying"}), False)

# ---- combat and damage effects
FACE_WHO = r"(?P<who>each opponent|each player|target opponent|target player|any target|any other target|(?:the )?defending player|that player|target (?:player|opponent) or planeswalker|the player (?:or planeswalker )?(?:it's|it is) attacking)"
FACE_WHO_L = r"(?P<who>each opponent|each player|target opponent|target player|(?:the )?defending player|that player)"

def _face_who(w):
    return "each" if w.startswith("each opponent") else "all" if w.startswith("each player") else "one"

def _face_n(n, rest):
    """'3' -> 3; 'x' + ', where x is the number of creatures you control' -> dyn key; bare x -> 'X' (the spell's X)."""
    if n != "x": return num(n)
    wm = re.search(r"where x is (?:the number of )?([^.]+)", rest or "")
    if not wm: return "X"
    ms = re.fullmatch(r"(\w+?)s? you control", wm.group(1).strip())
    if ms and as_subtype(ms.group(1)): return ("sub", as_subtype(ms.group(1)))
    return _count(wm.group(1))

def _count(what):
    """A count clause ('the number of creatures you control', 'the greatest power among creatures you control') -> key or None."""
    w = re.sub(r"^the number of ", "", what.strip())
    if re.match(r"(?:its|~'s) power$", w): return ("pow",)                        # Prime Speaker Zegana, Lifeblood Hydra
    if re.match(r"cards? in (?:target|an) opponent's hand$", w): return ("opp_hand",)   # ~opp (Recurring Insight)
    om = re.match(r"(?:the number of )?other ([a-z\-']+?)s? you control$", w)
    if om and as_subtype(om.group(1)): return ("sub_other", as_subtype(om.group(1)))   # Earthshaker Dreadmaw: 'other Dinosaurs'
    if re.match(r"(?:the )?greatest power among other creatures you control$", w): return ("power_o",)    # Zegana
    gm = re.match(r"(?:the )?greatest power among (?:non-?([a-z]+) )?creatures you control$", w)
    if gm: return ("power",) + ((as_subtype(gm.group(1)),) if gm.group(1) and as_subtype(gm.group(1)) else ()) if not gm.group(1) or as_subtype(gm.group(1)) else None
    return clean_dyn(w)

def _xn(m, g="n"):
    """A count word; 'x' reads its sentence's 'where X is ...' (a count key), else it's the spell's X. None: an unread count."""
    n = m.group(g)
    if n != "x": return num(n)
    return _face_n("x", _where_x(m))

def _where_x(m):
    """The text that defines a match's X: its own sentence, else a 'where X is' elsewhere in the ability (Tezzeret's
    '... where X is the number of artifacts you control. You gain X life.')."""
    rest = m.string[m.end():].split(".")[0]
    if "where x is" not in rest and "where x is" in m.string: rest = m.string[m.string.index("where x is"):]
    return rest

def _face_what(what):
    """Amount clauses: 'its power' / '~'s power' -> ('pow',); 'that creature's power' -> ('objpow',); counts -> dyn key."""
    w = what.strip()
    if re.match(r"^(?:its|~'s) power", w): return ("pow",)
    if re.match(r"^(?:that|the attacking|the sacrificed) creature's power", w): return ("objpow",)
    return clean_dyn(re.sub(r"^the number of ", "", w))

def _fx_face(m):
    """-> ('face', amount, who, damage?). Damage (not life loss) is what lifelink and damage doublers see."""
    d = m.groupdict()
    n = _face_what(d["what"]) if d.get("what") else _face_n(d["n"], d.get("rest") if "where x is" in (d.get("rest") or "") else _where_x(m))
    if n == ("pow",) and re.search(r"\b(?:it|that creature) $", m.string[:m.start()]): n = ("objpow",)   # 'it deals damage equal to its power'
    return ("face", n, _face_who(d["who"]), "damage" in m.group(0)) if n else None

def _pt_val(s, rest=""):
    """'+2' -> 2, '-1' -> -1, '+x' with 'where x is ...' / 'for each ...' -> ('per', 1, dyn key); unreadable -> None."""
    if s.lstrip("+-") != "x": return int(s)
    if re.search(r"where x is the greatest power among creatures you control", rest or ""): return ("per", -1 if s.startswith("-") else 1, ("power",))
    wm = re.search(r"(?:where x is (?:the number of )?|for each )([^.]+)", rest or "")
    key = clean_dyn(wm.group(1)) if wm else None
    return ("per", -1 if s.startswith("-") else 1, key) if key else None

def _kw_in(text):
    return frozenset(w for w in COMBAT_KW if re.search(r"\b" + w + r"\b", text or ""))

def _fx_pump_team(m):
    """'creatures you control get +3/+3 and gain trample until end of turn' (Overrun, Craterhoof)."""
    cf = creature_filter(m.group("subj"))
    if not cf: return None
    body, rest = m.group("body"), m.group("rest") or ""      # the duration-first pump regex's rest is optional
    pm = re.search(r"([+-](?:\d+|x))/([+-](?:\d+|x))", body)
    dp, dt = (_pt_val(pm.group(1), rest + body), _pt_val(pm.group(2), rest + body)) if pm else (0, 0)
    fe = re.search(r"for each ([^.,]+)", body + " " + rest)
    if fe and pm and isinstance(dp, int):              # '+1/+1 for each basic land type...' (Tromp the Domains): never read it flat
        key = clean_dyn(fe.group(1))
        if not key: return None
        dp, dt = ("per", dp, key), ("per", dt, key)
    kws = _kw_in(body)
    if dp is None or dt is None or not (pm or kws): return None
    return ("pump_team", dp, dt, kws) + cf

def _fx_pump(m):
    """'~ gets +1/+0 until end of turn' / 'target creature gets +3/+3' / 'it gains flying' -> ('pump', who, p, t, kws)."""
    w = m.group("who")
    who = "self" if w == "~" else "obj" if w in ("it", "that creature") else "attach" if w.startswith(("equipped", "enchanted")) \
        else "others_attacking" if "attacking" in w else "attackers" if w in ("they", "those creatures") else "target"
    body, rest = m.group("body"), m.group("rest") or ""      # the duration-first pump regex's rest is optional
    pm = re.search(r"([+-](?:\d+|x))/([+-](?:\d+|x))", body)
    dp, dt = (_pt_val(pm.group(1), rest + body), _pt_val(pm.group(2), rest + body)) if pm else (0, 0)
    fe = re.search(r"for each ([^.]+)", rest)
    if fe and isinstance(dp, int):                    # '+1/+0 until end of turn for each other attacking Goblin'
        key = ("atk_share",) if re.match(r"other attacking creature that shares a creature type with it", fe.group(1)) else clean_dyn(fe.group(1))
        if not key: return None
        dp, dt = ("per", dp, key), ("per", dt, key)
    kws = _kw_in(body)
    if dp is None or dt is None or not (pm or kws): return None
    return ("pump", who, dp, dt, kws)

def _fx_ctr_on(m):
    w = m.group("who")
    if not _xn(m): return None                            # 'put X +1/+1 counters ..., where X is' something unread
    if m.group("kind").startswith("-"):                   # -1/-1 counters
        if w.startswith("target") and "you control" not in w: return None      # removal (the kill reader declined it)
        if re.match(r"\s*for each", m.string[m.end():]): return None           # a count not read flat
        if "target" in w: return ("ctr_on", "least", m.group("kind"), _xn(m), "other" in w) if _xn(m) else None   # Soulstinger
    tm = re.match(r"each of (?:up to )?(one|two|three) ", w)
    if tm: return ("ctr_on", ("targets", num(tm.group(1))), m.group("kind"), _xn(m), "other" in w)
    if w.startswith("each"):
        am = re.match(r"each (?:other )?([a-z\-]+?)s?(?: creatures?)? you control$", w)
        word = am.group(1) if am else "creature"
        if word == "creature": f = None
        elif word in ("artifact", "enchantment", "legendary", "token", "nontoken") or word in COLOR_WORDS:
            f = parse_filter(word + " creature")                         # 'each artifact creature you control' (Steel Overseer)
        elif as_subtype(word):
            f = parse_filter("creature"); f["sub"] = {as_subtype(word)}; f["unknown"] = False
        else: return None
        return ("ctr_on", ("each", f) if f else "each", m.group("kind"), _xn(m), "other" in w)
    return ("ctr_on", "obj" if w in ("it", "that creature") else "target", m.group("kind"), _xn(m), "other" in w)

def _fx_mana(m):
    if re.match(r"x mana", m.group(1)):
        wm = re.search(r"where x is the total power of attacking creatures", m.string[m.end():m.end() + 80])
        if wm: return ("mana_x", ("atkpow",))              # Klauth
    units, _ = parse_prod(m.group(1), ALL5)
    if units and re.match(r" for each card in (?:target|an) opponent's hand", m.string[m.end():]):
        units = units * OPP_HAND                          # ~opp: an opponent holds OPP_HAND cards
    else:
        fe = re.match(r"(?P<alt>(?:\s*or \{[^}]+\})*)\s*for each ([^.]+)", m.string[m.end():])
        if fe:                                            # Brightstone Ritual ('for each Goblin on the battlefield'); Culling Ritual unread
            key = None if fe.group("alt") else dyn_prod("for each " + fe.group(2))
            return ("mana_n", units, key) if key and units else None
    return ("mana", units) if units else None

# ---- creature removal: read as removal of opponents' creatures (--blockers boards), never aimed at your own
RM_TYPES = (r"creatures?|nonland permanents?|permanents?|artifact or creature|creature or planeswalker|planeswalker or creature"
            r"|creature or enchantment|artifact, creature, or enchantment|creature or vehicle")
RM_CTRL = r"(?: (?:an opponent controls|you don't control|your opponents control|defending player controls|that player controls))?"
RM_WHAT = (r"(?P<what>(?:non[a-z]+,? )*(?:" + RM_TYPES + r")" + RM_CTRL
           + r"(?: with (?:flying|(?:power|toughness|mana value) \d+ or (?:less|greater)))?" + RM_CTRL + r")(?![a-z])"
           # allowlist: only a clause end or a safe word may follow the noun. Anything else ('card from a graveyard',
           # 'that's attacking you', 'it's blocking', 'you control', 'with a counter') leaves the line unread.
           r"(?=$|[.,;:\"@)]| (?:and|until|if|then|unless|instead|to|gets?|shuffles)\b)")
RM_Q = r"(?:up to (?P<n>one|two|three) )?(?:another )?(?:other )?target "
RM_KW = {"white", "blue", "black", "red", "green", "artifact"}

def _rm_filter(what):
    """'nonartifact, nonblack creature' / 'creature with power 3 or less' -> filter dict for can_kill; None if unread."""
    w = re.sub(r"(?: (?:an opponent controls|you don't control|your opponents control|defending player controls|that player controls))",
               "", what.strip().lower())
    m = re.fullmatch(r"(?P<pre>(?:non[a-z]+,? )*)(?:" + RM_TYPES + r")(?: with (?P<with>.+))?", w)
    if not m: return None
    non = set(re.findall(r"non([a-z]+)", m.group("pre")))
    if non - RM_KW - {"legendary", "token", "land"}: return None       # 'nonhuman', 'nonzombie': subtypes aren't on blockers
    f = {"non": frozenset(non & RM_KW), "need": frozenset(), "cmp": ()}
    wt = m.group("with")
    if wt == "flying": f["need"] = frozenset({"flying"})
    elif wt:
        cm = re.fullmatch(r"(power|toughness|mana value) (\d+) or (less|greater)", wt)
        if not cm: return None
        f["cmp"] = ((cm.group(1), cm.group(3), int(cm.group(2))),)
    return f

def _fx_kill(how):
    """-> ('kill_blk', how, targets, toughness limit, filter, controller gains life = power, each/all)."""
    def fn(m):
        after = m.string[m.end():m.end() + 90]
        if re.match(r"[^.]*?\.? ?(?:its|that creature's|that permanent's) controller (?:creates|manifests)", after): return None   # Beast Within: they get a body back
        if re.match(r"\s*(?:for each|where x)", after): return None        # a count on the removal (Soulstinger): not read flat
        if how in ("exile", "all_exile") and re.search(r"return (?:it|that card|them|those cards|the exiled cards?|that creature|each card exiled this way)"
                                                       r" to the battlefield", after): return None   # flicker, not removal
        gd = m.groupdict()
        flt = _rm_filter(gd.get("what") or "creature")
        if flt is None: return None
        lim = gd.get("lim")
        lim = (int(lim) if lim.isdigit() else num(lim)) if lim else None
        if lim is not None and lim <= 0: return None
        each = how.startswith("all_") or (how == "edict" and gd.get("who") == "each opponent")
        gain = bool(re.match(r"[^.]*?\.? ?its controller gains life equal to its power", after))
        return ("kill_blk", how.replace("all_", ""), num(gd.get("n")) if gd.get("n") else 1, lim, flt, gain, each)
    return fn

FX = [
    (re.compile(r"\b(?:destroy|exile) (?:all|each) (?:other )?(?P<what>creatures?|nonland permanents?) (?:you don't control|your opponents control|target (?:player|opponent) controls)"),
     lambda m: _fx_kill("all_" + ("exile" if m.group(0).startswith("exile") else "destroy"))(m)),
    (re.compile(r"\breturn (?:all|each) (?P<what>creatures?|nonland permanents?) (?:you don't control|your opponents control) to (?:their|its) owners?'?s? hands?"),
     lambda m: _fx_kill("all_bounce")(m)),
    (re.compile(r"\bdestroy " + RM_Q + RM_WHAT), _fx_kill("destroy")),
    (re.compile(r"\bexile " + RM_Q + RM_WHAT), _fx_kill("exile")),
    (re.compile(r"\breturn " + RM_Q + RM_WHAT + r" to (?:its|their) owners?'?s? hands?"), _fx_kill("bounce")),
    (re.compile(r"\bthe owner of " + RM_Q + RM_WHAT + r" shuffles it into their library"), _fx_kill("exile")),     # Chaos Warp
    (re.compile(r"\bdeals? (?P<lim>\d+) damage to " + RM_Q + RM_WHAT), _fx_kill("dmg")),
    (re.compile(r"(?<!each )\b" + RM_Q + RM_WHAT + r" gets? -\d+/-(?P<lim>\d+) until end of turn"), _fx_kill("minus")),
    (re.compile(r"\bput (?P<lim>a|an|one|two|three|four|five|\d+) -1/-1 counters? on " + RM_Q + RM_WHAT), _fx_kill("minus")),
    (re.compile(r"(?P<who>each opponent|target opponent|target player) sacrifices (?:a|an|one) (?P<what>creature|nonland permanent|creature or planeswalker|artifact or creature)(?: of their choice)?(?![a-z])"),
     _fx_kill("edict")),
    (re.compile(r"look at the top x cards of your library, where x is your devotion to (white|blue|black|red|green)\..*?if x is greater than or equal to the number of cards in your library, you win the game"),
     lambda m: ("oracle", COLOR_WORDS[m.group(1)])),                                 # Thassa's Oracle
    (re.compile(r"reveal the top card of your library and put that card into your hand\. you lose life equal to its mana value"),
     lambda m: ("bob",)),                                                          # Dark Confidant
    # Well of Lost Dreams: X is capped by the life just gained (read before the plain 'draw x cards')
    (re.compile(r"you may pay \{x\}, where x is less than or equal to the amount of life you gained\. if you do, draw x cards?"),
     lambda m: ("pay_x_draw",)),
    (re.compile(r"(?:each player |you )?(?:discards? (?:their|your) hand|shuffles? (?:their|your) hand(?: and graveyard)? into (?:their|your) library)(?:,| and)? ?(?:then )?(?:each player |you )?draws? (\w+) cards?"),
     lambda m: ("wheel", num(m.group(1)), "shuffle" in m.group(0))),
    (re.compile(r"discards? (?:their|your) hand,? then draws? cards equal to the greatest number"),
     lambda m: ("wheel", "max", False)),
    (re.compile(SUBJ + r"draws? cards equal to (?:the number of )?(?P<what>[^.;]+)"),
     lambda m: ("draw", _count(m.group("what"))) if _subj_ok(m) and _count(m.group("what")) else None),
    (re.compile(SUBJ + r"draws? (?:a|one) cards? for each (?P<what>[^.;]+)"),
     lambda m: ("draw", _count(m.group("what"))) if _subj_ok(m) and _count(m.group("what")) else None),
    (re.compile(SUBJ + r"draws? (?P<n>a|an|one|two|three|four|five|six|seven|eight|x|\d+) (?:additional )?cards?"),
     lambda m: ("draw", _xn(m)) if _subj_ok(m) and _xn(m) else None),
    # Card filtering, not card advantage: Brainstorm-style put-backs and looter discards.
    (re.compile(r"put (a|an|one|two|three|\w+) cards? from your hand on (?:the )?(?:top|bottom) of (?:your|their owner's) library"),
     lambda m: ("putback", num(m.group(1)), "bottom" in m.group(0))),
    (re.compile(r"(?<!whenever you )(?<!if you would )(?<!unless you )(?<!may )(?<!player )(?<!opponent )(?<!opponents )\bdiscard (a|an|one|two|three|x|\d+) (?:cards?|of them)"),
     lambda m: ("discard", num(m.group(1)))),
    (re.compile(r"look at the top (\w+) cards? of your library,? (?:then )?put them back in any order"), lambda m: ("arrange", num(m.group(1)))),
    (re.compile(r"look at the top card of your library\. if it's an? (?P<what>[^.,]+?) card, you may reveal it and put it into your hand"),
     lambda m: ("peek", parse_filter(_orig(m, "what"))) if not parse_filter(_orig(m, "what"))["unknown"] else None),   # Herald's Horn
    (re.compile(r"look at the top (?P<n>\w+) cards? of your library\. you may (?:reveal |put )?(?:an? |up to one )?(?P<what>[^.]+?) cards? from among them"
                r" (?:and put (?:it|that card) )?(?P<dest>into your hand|onto the battlefield)"),
     lambda m: ("look_f", num(m.group("n")), tu.parse_target(_orig(m, "what") + " card", _CTX["raw"] or {}),
                "bf" if "battlefield" in m.group("dest") else "hand")),
    (re.compile(r"look at the top (\w+) cards? of your library\.? [^.]*?put (a|one|two|three|up to one|up to two|any number) of (?:them|those cards) into your hand"),
     lambda m: ("look", num(m.group(1)), 2 if "two" in m.group(2) else 3 if "three" in m.group(2) else 1)),
    (re.compile(r"search your library(?: and/or graveyard)? for ([^.]+)"), _fx_search),
    (RECUR_RX, _fx_recur),
    (re.compile(r"reveal the top (\w+) cards? of your library\. you may put (?P<what>an? [^.]+?) cards? from among them into your hand"
                r"[^.]*\. put the rest into your graveyard"),
     lambda m: ("dig_gy", num(m.group(1)), tu.parse_target(_orig(m, "what") + " card", _CTX["raw"] or {}))),
    (re.compile(SUBJ + r"mills? (?P<n>a|an|one|two|three|four|five|six|seven|eight|nine|ten|x|\d+) cards?"),
     lambda m: (("mill", _xn(m)) + (("choice",) if (m.group("subj") or "").strip() == "target player" else ())) if _subj_ok(m) and _xn(m) else None),
    (re.compile(r"\bscry (\w+)"), lambda m: ("scry", _xn(m, 1)) if _xn(m, 1) else None),
    (re.compile(r"\bsurveil (\w+)"), lambda m: ("surveil", _xn(m, 1)) if _xn(m, 1) else None),
    (re.compile(r"you may play an additional land this turn"), lambda m: ("extra_land", 1)),
    (re.compile(r"put (?:a|up to one) land card from your hand onto the battlefield"), lambda m: ("land_from_hand", 1)),
    (re.compile(r"create (a|an|one|two|three|four|five|x|\w+) (tapped )?(?:(?:food|clue|blood) token or an? )?treasure tokens?"),
     lambda m: ("treasure", _xn(m, 1), bool(m.group(2))) if _xn(m, 1) else None),
    (re.compile(r"\bcreate (?P<n>a|an|one|two|three|four|five|six|seven|x|\d+) (?:tapped )?(?:(?P<p>\d+|x)/(?P<t>\d+|x) )?"
                r"(?P<desc>[a-z ,\-]*?)\btokens?\b(?P<rest>[^.]*)"), _fx_token),
    (re.compile(r"\binvestigate(?: (twice|three times))?"),
     lambda m: ("token", {"twice": 2, "three times": 3}.get(m.group(1), 1), 0, ("Clue",), "{2}, Sacrifice ~: Draw a card.", "artifact",
                0, frozenset(), False)),
    (re.compile(r"\badd (?:that much \{(\w)\}|an amount of \{(\w)\} equal to (?:the |that )?(?:amount of )?damage)"),
     lambda m: ("mana_dmg", frozenset((m.group(1) or m.group(2)).upper()))),   # Mark of Sakiko: the damage dealt
    (re.compile(r"\buntap (?:all|each) lands you control"), lambda m: ("untap_lands",)),     # Bear Umbra, Nature's Will, Sword of Feast and Famine
    (re.compile(r"\badd ((?:\{[^}]+\})+|(?:two|three|four|five|six|seven|eight|nine|ten) \{[^}]+\}|one mana of any color|\w+ mana (?:of any one color|in any combination of colors))"), _fx_mana),
    (re.compile(r"\bproliferate(?:,? then proliferate again| twice)?"),
     lambda m: ("prolif", 2 if ("twice" in m.group(0) or "again" in m.group(0)) else 1)),
    (re.compile(r"put (a|an|one|two|three|\w+) (\S+?) counters? on ~"), lambda m: ("ctr", m.group(2), _xn(m, 1)) if _xn(m, 1) else None),
    (re.compile(r"double the number of each kind of counter on"), lambda m: ("double_ctr",)),
    (re.compile(r"you may cast (?:a|an) (?:[\w ]+? )?spell with mana value (\w+) or less from your hand without paying its mana cost"),
     lambda m: ("free_cast", num(m.group(1)))),
    # damage and life loss to opponents (face), your life, pumps and counters on creatures (combat)
    (re.compile(r"deals? damage equal to (?P<what>[^.]+?) to " + FACE_WHO), _fx_face),
    (re.compile(r"deals? damage to " + FACE_WHO + r" equal to (?P<what>[^.]+)"), _fx_face),
    (re.compile(FACE_WHO_L + r" loses? life equal to (?P<what>[^.]+)"), _fx_face),
    (re.compile(r"deals? (?P<n>\d+|x) damage to " + FACE_WHO + r"(?=(?P<rest>[^.]*))"), _fx_face),     # rest: read, not consumed
    (re.compile(FACE_WHO_L + r" loses? (?P<n>\d+|x) life(?=(?P<rest>[^.]*))"), _fx_face),
    (re.compile(r"\byou gain (\d+) life"), lambda m: ("life", int(m.group(1)))),
    (re.compile(r"\byou gain (?P<n>x) life"), lambda m: ("life", _xn(m)) if _xn(m) else None),
    (re.compile(r"\byou gain (?:that much life|life equal to the damage dealt)"), lambda m: ("life_dmg",)),     # Spirit Loop
    (re.compile(r"\byou gain life equal to the (?:life lost|damage dealt) this way"), lambda m: ("life_lost",)),   # Gray Merchant
    (re.compile(r"\buntap ~(?![\w'])"), lambda m: ("untap_self",)),                                            # Ragost
    (re.compile(r"\b(?:you|and) lose (\d+) life"), lambda m: ("life", -int(m.group(1)))),       # "you draw a card and lose 1 life"
    (re.compile(r"\band loses (\d+) life"), lambda m: ("life", -int(m.group(1)))            # Sign in Blood: 'target player draws two
     if re.search(r"(?:^|[.,] )(?:you|target player) draws? [^.]*$", (_CTX["orig"] or "")[:m.start()], re.I) else None),   # cards and loses 2 life'
    (re.compile(r"\b(?:you|and) lose (?P<n>x) life"), lambda m: ("lose", _xn(m)) if _xn(m) else None),     # Painful Truths
    (re.compile(r"(?P<subj>(?:other |each |each other )?(?:attacking )?(?:[a-z\-]+ )?(?:creatures?|creature tokens?) you control|"
                r"other [a-z\-]+s you control) (?P<body>(?:get|gain|have)\b[^.]*?) until end of turn(?P<rest>[^.]*)"), _fx_pump_team),
    (re.compile(r"(?P<who>~|it|that creature|equipped creature|enchanted creature|(?:up to one )?(?:another )?target creature(?: you control)?"
                r"|each other attacking creature|other attacking creatures|they|those creatures) (?:gets?|gains?|has) (?P<body>[^.]*?) until end of turn(?P<rest>[^.]*)"),
     _fx_pump),
    (re.compile(r"put (?P<n>a|an|one|two|three|four|five|\d+) (?P<kind>\S+?) counters? on (?P<who>(?:up to one )?(?:another )?target (?:artifact or )?creature"
                r"(?: you control)?|each of (?:up to )?(?:one|two|three) (?:other )?target creatures?(?: you control)?"
                r"|each (?:other )?(?:[a-z\-]+ )?creatures? you control|each other [a-z\-]+ you control|it|that creature)(?![a-z])"), _fx_ctr_on),
    (re.compile(r"untap (?:all|each) (?:other )?(creatures? you control|creatures? that attacked this turn|attacking creatures)"),
     lambda m: ("untap_cr", "attacked" if "attacked" in m.group(1) else "attacking" if "attacking" in m.group(1) else "all")),
    (re.compile(r"there(?: is|'s) an additional combat phase"), lambda m: ("extra_combat",)),
    (re.compile(r"(?P<who>(?:each |all )?creatures your opponents control|(?:all )?creatures(?P<ground> without flying)?|"
                r"(?:up to (?P<n>one|two) )?target creatures?(?: an opponent controls| defending player controls| your opponents control)?)"
                r" can't block this turn"),
     lambda m: ("noblock", "ground" if m.group("ground") else "all" if "target" not in m.group("who") else num(m.group("n") or "one"))),
    (re.compile(r"(?P<who>~|it|that creature|(?:up to one )?target creature(?: you control)?) can't be blocked this turn"),
     lambda m: ("unblock", {"~": "self", "it": "obj", "that creature": "obj"}.get(m.group("who"), "target"))),
    (re.compile(r"exile the top (\w+) cards? of your library\. (?:until end of turn, )?you may play (?:them|those cards)(?: this turn)?"),
     lambda m: ("draw", num(m.group(1)))),              # impulse draw, read as drawing them (~approx)
    (re.compile(r"reveal the top (\w+) cards? of your library\. put all land cards from among them onto the battlefield( tapped)?"),
     lambda m: ("reveal_lands", "X" if m.group(1) == "x" else num(m.group(1)))),
    (re.compile(r"return ~ to its owner's hand"), lambda m: ("bounce_self",)),
    (re.compile(r"exile cards from the top of your library until you exile a nonland card\. you may cast it without paying its mana cost"
                r"(?: if that spell's mana value is (\w+) or less)?"), lambda m: ("free_top", num(m.group(1)) if m.group(1) else 99)),
    (re.compile(r"each player's life total becomes the number of creatures they control"), lambda m: ("biorhythm",)),
    (re.compile(r"double the power( and toughness)? of each (creature|[a-z]+) you control"),
     lambda m: ("double_pow", bool(m.group(1)), None if m.group(2) == "creature" else as_subtype(m.group(2)))),
    # duration first: 'Until end of turn, creatures you control gain trample and get +X/+X, where X is ...' (Overwhelming Stampede)
    (re.compile(r"until end of turn, (?P<subj>(?:other )?(?:[a-z\-]+ )?creatures? you control) (?P<body>(?:get|gain|have)\b[^.]*?)(?P<rest>, where x is [^.]*)?(?=\.|$)"),
     _fx_pump_team),
]

def _ifdo_cost(cost):
    """The cost sentence before 'If you do,' -> a cost the sim pays ('discard', n, filter) / ('sac_self',) / ('sac', fodder)
    / ('life', n); 'free' when it's an effect read on its own (draw, mill, reveal); None when unread (the effect is dropped)."""
    m = re.fullmatch(r"discard (a|an|one|two|three|\d+) (?:(?P<what>[a-z ]+?) )?cards?", cost)
    if m:
        f = parse_filter(m.group("what")) if m.group("what") else None
        return None if f and f["unknown"] else ("discard", num(m.group(1)), f)
    if re.fullmatch(r"sacrifice (?:~|this (?:creature|artifact|enchantment|permanent|land))", cost): return ("sac_self",)
    m = re.fullmatch(r"sacrifice (a|an|another|two|three) (.+)", cost)
    if m:
        f = fodder_filt(m.group(1), m.group(2))
        return ("sac", f) if f else None
    m = re.fullmatch(r"pay (\d+) life", cost)
    if m: return ("life", int(m.group(1)))
    saved = _CTX.get("left"); _CTX["left"] = None                         # probing the cost: its leftovers aren't the line's
    free = re.match(r"reveal\b|pay \{", cost) or parse_fx(cost)[0]
    _CTX["left"] = saved
    if free: return "free"                                                # mana payments: the 'paid' reader, Well of Lost Dreams
    return None

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
    cm = re.match(r"choose (?P<n>\w+) target (?P<what>[^.]+?) cards? in your graveyard\. (?=.*\bthe chosen cards\b)", s)
    if cm:                                        # Victimize: 'the chosen cards' are the targets named first
        s0 = s0[cm.end():].replace("the chosen cards", f"{cm.group('n')} target {cm.group('what')} cards from your graveyard")
        s = s0.lower()
    im0 = re.search(r"\. if you do\b(?!n)", s)
    i = im0.start() if im0 else -1
    if i >= 0:                                    # '[you may] COST. If you do, EFFECT': the effect only when the cost is paid
        j = s.rfind(". ", 0, i); cs = j + 2 if j >= 0 else 0
        c = _ifdo_cost(re.sub(r"^(?:then )?(?:you may )?", "", s[cs:i].strip()))
        if c != "free":
            im = re.match(r"\. if you do,? ", s[i:])
            body = s0[i + im.end():] if im else ""
            om = re.search(r"\. otherwise,? ", body, re.I)                     # Pippin's Bravery: the unpaid branch
            inner, _ = parse_fx(body[:om.start()] if om else body)
            other, _ = parse_fx(body[om.end():]) if om else ([], False)
            pre, _ = parse_fx(s0[:cs]) if cs else ([], False)
            if not c: return pre + other, tax                                    # an unread cost: the effect isn't free
            return pre + ([("ifdo", c, inner, other)] if inner else other), tax
    out, masked = [], s
    for rx, fn in FX:
        for mm in rx.finditer(masked):
            _CTX["orig"] = s0
            e = fn(mm)
            if e: out.append((mm.start(), e))
        masked = rx.sub(lambda mm: "#" * len(mm.group(0)), masked)
    out.sort(key=lambda t: t[0])
    if out: _leftover(masked)
    return [e for _, e in out], tax

# ---- leftover detector: what the effect regexes didn't consume. A sentence with an effect verb nobody read, or a
# condition on an effect that was read ('if X is 10 or more, ...'), makes its line partial, not modeled.
LEFT_VERB = re.compile(r"\b(?:create|destroy|exile|search|return|cop(?:y|ies)|discard|put|draws?|sacrifice|untap|tap|gain control|"
                       r"mills?|cast|add|scry|surveil|look at|reveal|attach|transform|double|proliferate|investigate|counter target|"
                       r"deals? (?:\d+|x)|loses? (?:\d+|x) life|gains? (?:\d+|x) life|gets? [+-]|win the game|lose the game|skip|"
                       r"prevent|phases? (?:in|out)|explores?|connives?|amass|venture|populate|fights?|goad)\b")
LEFT_GLUE = re.compile(r"if you search your library this way,? shuffle|(?:then )?(?:you may )?shuffle(?: your library| it into your library)?|reveal (?:it|them|that card|those cards)"
                       r"|where x is [^.#]*|activate only [^.#]*|this ability triggers only [^.#]*|@q\d+@|\bif able\b|\bif you do,?"
                       r"|(?:(?:and )?put )?(?:all )?(?:the )?rest(?: of the cards)? (?:on the bottom|on top|into (?:your|their owner's) graveyard|back)[^.#]*"
                       r"|put (?:them|those cards|the rest) back[^.#]*|in a random order|in any order|this way"
                       r"|as an additional cost to cast (?:~|this spell),?|spend this mana only [^.#]*")
LEFT_OPP = re.compile(r"\b(?:its controller|its owner|their controller|controller of|that player|each opponent|target opponent|an opponent"
                      r"|defending player|each other player|opponents?|they|their)\b")
LEFT_VS = re.compile(r"\b(?:gain control of|tap (?:up to \w+ )?(?:another )?target|tap all creatures)\b|\b(?:an opponent|defending player|your opponents|you don't) control"
                     r"|\b(?:that player|target opponent|an opponent|each opponent|that land|that creature|that permanent)'s\b|\b\w+'s controller\b"
                     r"|\btarget players\b")
LEFT_COND = re.compile(r"\b(?:if|unless|as long as|only if)\b")

def _leftover(masked):
    if "left" not in _CTX or _CTX["left"] is None: return
    spell = bool(re.search(r"\b(?:instant|sorcery)\b", ((_CTX.get("raw") or {}).get("type_line") or "").lower()))
    prev = ""
    for sent in re.split(r"(?<=[.;])\s+", masked):
        was, prev = prev, sent
        if "#" in was and re.match(r"(?:then )?put (?:that card|it|them|those cards) (?:onto the battlefield|into your hand)", sent) \
                and not re.search(r"\bif\b|\bunless\b", sent): continue    # a search's destination, read by _fx_search
        bare = re.sub(r"#+", " ", LEFT_GLUE.sub("", sent))
        if "may pay {" in masked: bare = re.sub(r"^\s*if (?:the|that) player doesn't,?", "", bare)   # the tax clause (parse_fx's tax)
        if LEFT_VS.search(bare) or (spell and re.fullmatch(r"\s*exile ~\.?\s*", bare)): continue   # aimed at opponents; a spell exiling itself
        v = LEFT_VERB.search(bare)
        if v and not LEFT_OPP.search(bare[:v.start()]):
            _CTX["left"].append(re.sub(r"#+", "…", sent).strip())
        elif not v and "#" in sent and LEFT_COND.search(bare) and not LEFT_OPP.search(bare):
            _CTX["left"].append(re.sub(r"#+", "…", sent).strip())

def can_kill(e, b, board=None):
    """Can kill_blk effect e remove blocker b (an opponent's --blockers creature)? An edict takes their weakest instead."""
    _, how, _, lim, flt, _, _ = e
    if b.get("dead"): return False
    if "indestructible" in b["kw"] and how in ("destroy", "dmg"): return False
    if lim is not None and b["t"] > lim: return False
    if flt["non"] & b["kw"] or flt["need"] - b["kw"]: return False
    for field, op, v in flt["cmp"]:
        got = b[{"power": "p", "toughness": "t", "mana value": "mv"}[field]]
        if (op == "less" and got > v) or (op == "greater" and got < v): return False
    if how == "edict" and board is not None:        # the opponent sacrifices their least valuable creature
        live = [x for x in board if not x.get("dead")]
        return bool(live) and b is min(live, key=lambda x: (x["p"] + x["t"], x["name"]))
    return True

def kill_str(e):
    _, how, n, lim, flt, gain, each = e
    q = ",".join(sorted(["non" + x for x in flt["non"]] + list(flt["need"])) + [f"{f} {'<=' if o == 'less' else '>='} {v}" for f, o, v in flt["cmp"]])
    q = f" ({q})" if q else ""
    if how == "edict": return ("each opponent" if each else "an opponent") + " sacrifices a creature (their weakest)"
    verb = {"destroy": "destroy", "exile": "exile", "bounce": "bounce", "dmg": f"{lim} damage to", "minus": f"-{lim}/-{lim} on"}[how]
    tgt = "every opposing creature" if each else ("an opposing creature" if n == 1 else f"{n} opposing creatures")
    return f"removal: {verb} {tgt}{q}" + ("; its controller gains life = its power" if gain else "")

def pv(v, sign=False):
    """A readable amount: 3 / +3 / X / per creatures / power."""
    if isinstance(v, int): return f"{v:+d}" if sign else str(v)
    if v == "X": return "X"
    if isinstance(v, tuple) and v and v[0] == "per":
        return ("-" if v[1] < 0 else "+" if sign else "") + f"{abs(v[1])} per " + " ".join(v[2])
    if isinstance(v, tuple) and v[0] == "power": return "greatest power" + (f" (non-{v[1]})" if len(v) > 1 else "")
    if isinstance(v, tuple) and v[0] == "power_o": return "greatest power among others"
    if isinstance(v, tuple): return {"pow": "its power", "objpow": "that creature's power"}.get(v[0], "per " + " ".join(v))
    return str(v)

def fx_str(e):
    t = e[0]
    if t in ("draw", "scry", "surveil", "prolif", "treasure", "extra_land", "land_from_hand", "free_cast"):
        v = e[1]
        return f"{t} {pv(v)}" + (" tapped" if t == "treasure" and len(e) > 2 and e[2] else "")
    if t == "wheel": return f"wheel {e[1]}" + (" ~opp" if e[1] == "max" else "")
    if t == "oracle": return f"win if devotion to {e[1]} >= library (held until it wins)"
    if t == "bob": return "draw 1, lose life equal to its MV"
    if t == "sylvan": return "draw 2, keep 1 for 4 life above the floor, put the rest back"
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
    if t == "mill": return f"mill {pv(e[1])}" + (" (yourself only with a graveyard payoff)" if len(e) > 2 else "")
    if t == "lose": return f"you lose {pv(e[1])} life"
    if t == "cond":
        c = e[1]
        head = "if an opponent has more lands ~opp" if c == "opp_lands" else "if you gained life this turn" if c == "gained" \
            else f"if you have {c[1]}+ life" if isinstance(c, tuple) and c[0] == "life" else f"if {c}"
        return head + ": " + ", ".join(fx_str(x) for x in e[2])
    if t == "arrange": return f"arrange top {e[1]}"
    if t == "peek": return "take the top card if " + " ".join(sorted(e[1]["sub"]) + sorted(x.lower() for x in e[1]["types"]))
    if t == "look_f":
        tg = e[2]
        return f"look {e[1]}, take {tg.describe()} -> {e[3]}" + (" (filter unread; not used)" if tutor_unread(tg) else "")
    if t == "dig_gy": return f"reveal {e[1]}, take {e[2].describe()}, rest to graveyard"
    if t == "mana": return "mana " + "".join("".join(sorted(u)) if len(u) == 1 else "*" for u in e[1])
    if t == "token":
        what = " ".join(e[3]) or "creature"
        cnt = f"({pv(e[1])})" if isinstance(e[1], tuple) else e[1]
        cr = "creature" in e[5]
        return f"token {cnt}x {what}" + (f" {e[2]}/{e[6]}" if cr else "") + (" artifact" if e[5] == "artifact creature" else "") \
            + (" " + ",".join(sorted(e[7])) if e[7] else "") + (" attacking" if e[8] is True else " tapped" if e[8] else "") \
            + (" (has an ability)" if e[4] and (cr or what not in ("Clue", "Food", "Treasure", "Gold")) else "")
    if t == "face":
        return {"each": "each opponent", "all": "each player", "one": "an opponent"}[e[2]] + " loses " + pv(e[1])
    if t == "life": return f"you gain {pv(e[1])} life" if not isinstance(e[1], int) else f"you {'gain' if e[1] > 0 else 'lose'} {abs(e[1])} life"
    if t in ("pump", "pump_team"):
        if t == "pump": who, dp, dt, kws = e[1], e[2], e[3], e[4]
        else:
            dp, dt, kws = e[1], e[2], e[3]
            who = "team" + ("(other)" if e[5] else "") + ("(attacking)" if e[6] else "") \
                + ("(" + " ".join(sorted(e[4]["sub"])) + ")" if e[4].get("sub") else "")
        pt = f" {pv(dp, True)}/{pv(dt, True)}" if (dp or dt) else ""
        return f"pump {who}{pt}" + (" " + ",".join(sorted(kws)) if kws else "") + " EOT"
    if t == "extra_combat": return "additional combat"
    if t == "noblock": return {"all": "opponents' creatures can't block EOT", "ground": "creatures without flying can't block EOT"}.get(
        e[1], f"{e[1]} opposing blocker(s) can't block EOT")
    if t == "unblock": return f"{ {'self': '~', 'obj': 'that creature'}.get(e[1], 'target creature') } can't be blocked EOT"
    if t == "reveal_lands": return f"reveal {e[1]}, lands onto the battlefield tapped"
    if t == "bounce_self": return "return ~ to hand"
    if t == "cascade": return "cascade" + (f" x{e[2]}" if e[2] > 1 else "") + f" (MV < {e[1]})"
    if t == "free_top": return f"free cast of the next nonland card (MV <= {e[1]})"
    if t == "biorhythm": return "life totals become creature counts ~opp"
    if t == "mana_x": return "mana X (total power of attackers)"
    if t == "mana_n": return "mana " + "".join("".join(sorted(u)) if len(u) == 1 else "*" for u in e[1]) + " " + pv(e[2])
    if t == "double_pow": return "double power" + (" and toughness" if e[1] else "") + f" of each {e[2] or 'creature'} EOT"
    if t == "untap_cr": return f"untap {e[1]} creatures"
    if t == "untap_lands": return "untap your lands"
    if t == "mana_dmg": return "mana " + "".join(sorted(e[1])) + " x damage dealt"
    if t == "ctr_on":
        w = e[1] if isinstance(e[1], str) else f"up to {e[1][1]} targets" if e[1][0] == "targets" else \
            "each " + " ".join(sorted(x.lower() for x in (e[1][1].get("sub") or set()) | (set(e[1][1].get("types") or ()) - {"Creature"}))) + " creature"
        return f"+{e[3]} {e[2]} ctr on {w}" + (" other" if e[4] else "")
    if t == "ctr": return f"+{e[2]} {e[1]} ctr"
    if t == "paid": return f"pay {e[1] + len(e[2])}: " + ", ".join(fx_str(x) for x in e[3])
    if t == "ifdo":
        c = e[1]
        head = "sacrifice ~" if c[0] == "sac_self" else "sacrifice " + perm_desc(c[1]) if c[0] == "sac" else \
            f"pay {c[1]} life" if c[0] == "life" else f"discard {c[1]}" + (" " + " ".join(sorted(c[2]["types"] | c[2]["sub"])).lower() if c[2] else "")
        return f"{head} -> " + ", ".join(fx_str(x) for x in e[2]) + (", else " + ", ".join(fx_str(x) for x in e[3]) if e[3] else "")
    if t == "untap_self": return "untap ~"
    if t == "kill_blk": return kill_str(e)
    if t == "win": return "you win the game"
    if t == "pay_x_draw": return "pay X (up to the life gained): draw X"
    if t == "life_dmg": return "you gain life equal to the damage"
    if t == "life_lost": return "you gain the life lost"
    if t == "opt": return "[" + ", ".join(fx_str(x) for x in e[1]) + "]"
    if t == "regrow_self": return "return ~ to hand"
    return t

# ---------------------------------------------------------------- card compiler
RX_MANA = re.compile(r'^(?P<cost>[^:"]*?):\s*(?:(?P<vivid>for each color among permanents you control, add one mana of that color)|add (?P<prod>[^.]+?))\.(?P<rest>.*)$', re.I)
RX_INTERACT = re.compile(r"\b(destroy (?:target|all|each|up to)|exile (?:target|all|each|up to)|counter target|shuffles it into their library|return (?:target|up to|all|each)[^.]*? to (?:its|their) owner(?:'s|s') hands?|deals? (?:\d+|x) damage|gets? -\d+/-\d+|gets? -x/-x|phase out|gains? (?:hexproof|indestructible|protection|shroud)|(?:opponent|player)s? sacrifices?)")
RX_NEUTRAL = re.compile(r"\b(?:ha(?:s|ve)|gains?) (?:indestructible|hexproof|shroud|ward)|can't be (?:countered|the target)|^enchant |protection from|choose a (?:creature type|color|basic land type)|^as ~ enters, choose|for each color among|this spell can't be countered|if you would get one or more counters|^you may look at the top card of your library (?:at )?any time")
# (combat lines - pumps, evasion, keyword grants, life - are no longer neutral: combat reads them, and a miss shows as partial)

FACE_ONLY = r"deals? (?:\d+|x) damage to (?:each opponent|each player|target opponent|target player|(?:the )?defending player)\b"
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
        self.labman = False      # drawing from an empty library wins instead (Laboratory Maniac, Jace, Wielder of Mysteries)
        self.life_per_mv = False # Reanimate: lose life equal to the returned card's mana value
        self.ppips = []          # Phyrexian pips' colors: paid with 2 life each, or with mana below the floor
        self.addlife = 0         # "As an additional cost to cast ~, pay N life"
        self.addsac = None       # "As an additional cost to cast ~, sacrifice a creature": fodder filter (Deadly Dispute, Village Rites)
        self.addsac_bf = False
        self.no_untap = False    # "~ doesn't untap during your untap step" (Mana Vault, Grim Monolith): tapped once, spent last   # ...and the spell puts a creature onto the battlefield (a small creature is fair trade)
        self.pain = 0            # life lost each time this mana source taps (painlands, Ancient Tomb, City of Brass, Horizon lands)
        self.pain_col = False    # ...only when it makes colored mana (a painless {C} ability exists)
        self.fetch_life = 0      # "Pay N life, sacrifice ~: search" fetchlands
        self.opp_approx = False  # leans on the fixed opponent approximations (~opp)
        self.cum_upkeep = False  # cumulative upkeep: kept for 3 of your upkeeps, then let go (~approx)
        self.answer = None       # counter / protect / redirect: can stop a disruption event
        self.token = False       # a token: ceases to exist when it leaves the battlefield
        self.dyn_mana = None     # dyn key: the mana ability makes that many (Selvala, Priest of Titania, Cradle)
        self.self_red = None     # (n, dyn key): "~ costs {1} less to cast for each ..."
        self.free_cmdr = False   # free while you control a commander (Fierce Guardianship)
        self.kill = frozenset()  # held removal: permanent types it can remove (clears tax/lock pieces)
        self.burn_blk = None     # held 'N damage to any target': also a kill_blk option on a blocker (Shock, Lightning Bolt)
        self.tough = 0           # printed toughness (0 for * or none)
        self.kw = set()          # combat keywords it has (flying, trample, double strike...; 'unblockable')
        self.kwn = {}            # numbered keywords: toxic 2, annihilator 2, exalted (instances)...
        self.evade = []          # partial unblockability rules (evade_rule): 'can't be blocked by creatures with power 2 or less'
        self.dyn_pt = None       # ('both' | 'power', dyn key): */* read at use time (Tarmogoyf-style counts)
        self.pt_unread = False   # a * power/toughness the parser couldn't read (counted as 0, never attacks)
        self.cond_units = []     # mana abilities with 'Activate only if you control ...': [(units, count key, n)]
        self.imprint = False     # Chrome Mox: exiles a nonartifact, nonland card from hand; taps for its colors
        self.mox_diamond = False # Mox Diamond: enters only by discarding a land card
        self.sac_outlets = []    # 'Sacrifice a creature: Add {C}{C}' (Ashnod's Altar): [(fodder filter, units, taps?)]
        self.tough_known = True  # toughness read (printed, or counted): toughness 0 kills it (X/X tokens and * stay out)
        self.attach = None       # equipment/aura bonus to the creature it's on: (power, toughness, keywords)
        self.equip = None        # equip cost (generic, pips)
        self.alpha = False       # team pump (Overrun, Craterhoof): cast only when it wins a fight this turn
        self.god = None          # (color, n): not a creature while devotion to color < n (Theros gods)
        self.attach_cond = []    # conditional Aura/Equipment bonuses: [(cond, power, toughness, keywords)]; cond ('color', C) / ('aura2',)
        self.debuff = False      # a removal Aura (Darksteel Mutation, Kenrith's Transformation): never put on your own creature
        self.untapper = None     # (n, land filter): '{T}: Untap target land' read as a mana source copying that land's mana
        self.gain_untap = False  # 'at the beginning of each end step, if you gained life this turn, untap ~' (Ragost)

RX_KILL = re.compile(r"\b(?:destroy|exile|return|the owner of) (?:up to (?:one|two|three) |any number of )?(?:other )?targets? ([^.;]{0,60})")
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

def creature_filter(s):
    """Subject of an anthem or team pump -> (filter, other, attacking only) or None.
    'other elf creatures you control' / 'creature tokens you control' / 'attacking creatures you control' / 'other zombies'."""
    s = re.sub(r"\byou control\b", " ", (s or "").lower())
    other = bool(re.search(r"\b(?:other|another)\b", s)); atk = bool(re.search(r"\battacking\b", s))
    s = re.sub(r"\b(?:other|another|each|all|attacking|your|the)\b", " ", s)
    words = re.findall(r"[a-z\-]+", s)
    if not words: return None
    subs = set()
    for w in words:
        if w in ("creature", "creatures", "token", "tokens", "nontoken", "legendary", "multicolored") or w in COLOR_WORDS \
                or w in FILTER_OK_WORDS: continue
        st = as_subtype(w)
        if not st: return None
        subs.add(st)
    if not ({"creature", "creatures"} & set(words)) and not subs: return None
    f = parse_filter(" ".join(w for w in words if not as_subtype(w) or w in ("creature", "creatures")))
    f["types"], f["sub"], f["unknown"] = {"Creature"}, subs, False
    return f, other, atk

def kw_line(k, L):
    """A line made only of keywords ('Flying, first strike', 'Toxic 2', 'Equip {3}', 'Ward {2}').
    None = not one; True = combat keywords read (or equip); 'neutral' = keywords with no goldfish effect."""
    lo = L.lower().strip().rstrip(".")
    parts = [x.strip() for x in re.split(r",\s*|;\s*", lo) if x.strip()]
    if not parts: return None
    got, kwn, eq = set(), {}, None
    for part in parts:
        if part in COMBAT_KW: got.add(part); continue
        if part in ("umbra armor", "totem armor"): got.add("umbra armor"); continue     # read by disruption (destroy -> the Aura instead)
        m = re.fullmatch(r"(" + "|".join(COMBAT_KWN) + r") (\d+)", part)
        if m: kwn[m.group(1)] = kwn.get(m.group(1), 0) + int(m.group(2)); continue
        m = re.fullmatch(r"equip(?: [a-z ]+?)? ((?:\{[^}]+\})+)", part)
        if m: eq = parse_cost(m.group(1))[:2]; continue
        if NEUTRAL_KW.fullmatch(part): continue
        return None
    k.kw |= got
    for key, v in kwn.items(): k.kwn[key] = k.kwn.get(key, 0) + v
    if "exalted" in got: k.kwn["exalted"] = k.kwn.get("exalted", 0) + 1
    if eq: k.equip = eq
    return True if (got or kwn or eq) else "neutral"

def combat_static(k, lo):
    """Static combat lines -> k fields. True if read. Anthems ('other Elves you control get +1/+1'), keyword grants
    ('creatures you control have haste'), equipment/aura bonuses, self P/T counts, unblockability, Theros gods."""
    if lo.startswith(("when", "at the beginning")) or re.match(r"^[^:\"]*\{[^}]*\}[^:\"]*:", lo): return None
    if re.search(r"until end of turn|\bas long as\b|^if |\bduring\b|\bthis turn\b", lo):
        m = re.match(r"^as long as (?P<cond>enchanted creature is (?:white|blue|black|red|green)|equipped creature is (?:white|blue|black|red|green)"
                     r"|another aura is attached to enchanted creature), (?:it|enchanted creature|equipped creature) "
                     r"(?:gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+))?(?: and )?(?:has (?P<kw>[^.\"]+?))?\.?$", lo)
        if m and (m.group("p") or m.group("kw")):          # Shield of the Oversoul, Face of Divinity
            c = m.group("cond")
            cond = ("aura2",) if c.startswith("another") else ("color", COLOR_WORDS[c.split()[-1]])
            k.attach_cond.append((cond, int(m.group("p") or 0), int(m.group("t") or 0), frozenset(_kw_in(m.group("kw") or ""))))
            k.attach = k.attach or (0, 0, frozenset())
            return True
        m = re.match(r"^as long as your devotion to (white|blue|black|red|green)(?: and (white|blue|black|red|green))? is less than (\w+), ~ isn't a creature", lo)
        if m: k.god = (frozenset(COLOR_WORDS[c] for c in m.groups()[:2] if c), num(m.group(3))); return True
        return None
    m = re.match(r"^~'s power and toughness are each equal to (?:the number of )?(.+?)\.?$", lo) or \
        re.match(r"^~'s power is equal to (?:the number of )?(.+?)\.?$", lo)
    if m:
        key = clean_dyn(m.group(1))
        if key: k.dyn_pt = ("both" if "toughness" in m.group(0) else "power", key); return True
        return None
    if re.fullmatch(r"~ can't be blocked\.?", lo): k.kw.add("unblockable"); return True
    m = re.match(r"^~ can't be blocked (by|except by) (.+?)\.?$", lo)
    if m:
        r = evade_rule("by" if m.group(1) == "by" else "except", m.group(2))
        if r: k.evade.append(r); return True
        k.kw.add("evasion~"); k.notes.append("partial unblockability not read (blocks it as normal)"); return True
    if re.fullmatch(r"~ can't block\.?", lo): k.kw.add("cant_block"); return True
    if re.fullmatch(r"~ can't attack(?: or block)?\.?", lo): k.kw.add("defender"); return True
    if re.fullmatch(r"~ attacks each (?:combat|turn) if able\.?", lo): k.kw.add("must_attack"); return True
    m = re.match(r"^(?P<subj>.+?) (?:get|gets) (?P<p>[+-](?:\d+|x))/(?P<t>[+-](?:\d+|x))(?: and (?:have|has|gain|gains) (?P<kw>[^.]+?))?"
                 r"(?P<fe> for each [^.]+?)?\.?$", lo)
    m2 = None if m else re.match(r"^(?P<subj>.+?) (?:have|has) (?P<kw>[^.\"@]+?)\.?$", lo)
    mm = m or m2
    if not mm: return None
    subj = mm.group("subj")
    if re.fullmatch(r"creatures attacking (?:your opponents|an opponent)", subj):   # Blast-Furnace Hellkite: every attacker here
        subj = "attacking creatures you control"
    dp = dt = 0
    if m:
        dp, dt = _pt_val(m.group("p"), m.group("fe") or ""), _pt_val(m.group("t"), m.group("fe") or "")
        if dp is None or dt is None: return None
        if m.group("fe") and isinstance(dp, int):          # '+1/+1 for each artifact you control'
            key = clean_dyn(m.group("fe").replace(" for each ", "", 1))
            if not key: return None
            dp, dt = ("per", dp, key), ("per", dt, key)
    kwtxt = mm.group("kw") or ""
    kws = _kw_in(kwtxt) | ({"unblockable"} if "can't be blocked" in kwtxt else set()) | ({"haste"} if re.search(r"\briot\b", kwtxt) else set())
    if m2 and not kws: return None
    if subj == "~":
        k.statics.append(("anthem", {"self": True}, dp, dt, frozenset(kws), False, False)); return True
    if subj in ("equipped creature", "enchanted creature"):
        k.attach = (dp, dt, frozenset(kws)); return True
    if re.fullmatch(r"commander creatures you (?:own|control)", subj):
        k.statics.append(("anthem", CMDR_FILTER, dp, dt, frozenset(kws), False, False)); return True
    if not subj.endswith("you control") and not re.match(r"^other \w+s$", subj): return None
    cf = creature_filter(subj)
    if not cf: return None
    k.statics.append(("anthem", cf[0], dp, dt, frozenset(kws), cf[1], cf[2]))
    return True

PERM_QUALS = ("pow_max", "kw", "ctr", "nonsub", "modified", "equipped", "enchanted", "historic")
PERM_OK_WORDS = {"a", "an", "another", "other", "or", "and", "nontoken", "token", "tokens", "creature", "creatures", "artifact",
                 "artifacts", "enchantment", "enchantments", "permanent", "permanents", "land", "lands", "planeswalker",
                 "planeswalkers", "legendary"}

def perm_filt(article, subj):
    """'another nontoken creature you control' / 'Dragon' / 'creature with power 4 or greater' -> the permanent filter
    used by enter / attack / combat damage / dies triggers, or None."""
    subj = re.sub(r"\b(?:you control|under your control)\b", "", subj).strip()
    extra = {}
    m = re.search(r"\bwith power (\d+) or less\b", subj)
    if m: extra["pow_max"] = int(m.group(1)); subj = subj.replace(m.group(0), "")
    m = re.search(r"\bwith (" + "|".join(COMBAT_KW + COMBAT_KWN) + r")\b", subj)
    if m: extra["kw"] = m.group(1); subj = subj.replace(m.group(0), "")          # 'a creature you control with flying'
    m = re.search(r"\bwith (?:a |one or more )?(\+1/\+1 )?counters? on (?:it|them)\b", subj)
    if m: extra["ctr"] = "+1/+1" if m.group(1) else "any"; subj = subj.replace(m.group(0), "")
    m = re.search(r"\bnon-?([a-z]+)\b", subj)
    if m and as_subtype(m.group(1)): extra["nonsub"] = as_subtype(m.group(1)); subj = subj.replace(m.group(0), "")
    for w in ("modified", "equipped", "enchanted", "historic"):
        if re.search(r"\b" + w + r"\b", subj): extra[w] = True; subj = re.sub(r"\b" + w + r"\b", "", subj)
    tm = re.search(r"\b(creature|artifact|enchantment|permanent|land|planeswalker)s?\b", subj)
    subs = {x for x in (as_subtype(w) for w in re.findall(r"[a-z\-']+", subj)) if x}
    if not tm and not subs: return None
    pw = re.search(r"power (\d+) or greater", subj)
    words = re.findall(r"[a-z\-']+", re.sub(r"with power \d+ or greater", "", subj))
    if any(w not in PERM_OK_WORDS and w not in COLOR_WORDS and not as_subtype(w) for w in words): return None   # 'modified', 'attacking'...
    return {"type": tm.group(1).capitalize() if tm else "Permanent", "another": article == "another" or "another" in subj or "other" in words,
            "power": int(pw.group(1)) if pw else 0, "sub": subs, "nontoken": "nontoken" in subj,
            "token": bool(re.search(r"\btokens?\b", subj)) and "nontoken" not in subj,
            "colors": {COLOR_WORDS[w] for w in words if w in COLOR_WORDS}, "legendary": "legendary" in words, **extra}

def strip_reminder(t):
    return re.sub(r"\s*\([^()]*\)", "", t)

def tildify(text, names):
    for n in sorted({n for n in names if n}, key=len, reverse=True):
        text = re.sub(r"(?<![\w'])" + re.escape(n) + r"(?![\w]|'(?!s\b))", "~", text)     # "Name's power" -> "~'s power"
    return re.sub(r"\bthis (?:creature|artifact|enchantment|land|permanent|card|spell|aura|equipment|vehicle|planeswalker|battle|siege|saga|class|case|room|kindred|token)\b",
                  "~", text, flags=re.I)

def parse_prod(prod, anyc):
    """'{G}, {W}, or {U}' / '{W}{U}' / 'one mana of any color' / 'two mana in any combination
    of colors' -> ([unit color sets], approximated?)."""
    p = prod.lower().strip()
    m = re.match(r"(two|three|four|five|six|seven|eight|nine|ten) (\{[^}]+\})$", p)
    if m: return [frozenset(m.group(2)[1:-1].upper())] * num(m.group(1)), False
    m = re.match(r"(\w+) mana in any combination of ((?:\{[wubrgc]\}(?:,? (?:and/or|or) |, )?)+)$", p)
    if m and isinstance(num(m.group(1)), int):          # 'three mana in any combination of {R} and/or {G}' (Orcish Lumberjack)
        return [frozenset(x.upper() for x in SYM.findall(m.group(2)))] * num(m.group(1)), False
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
    if QUALIFIED.search(what) and "greatest power" not in what: return None
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

FODDER_WORDS = {"a", "an", "another", "other", "nontoken", "token", "tokens", "you", "control", "creature", "creatures",
                "artifact", "artifacts", "enchantment", "enchantments", "permanent", "permanents", "planeswalker", "planeswalkers"}

def fodder_filt(article, subj):
    """'a Food' / 'another creature' / 'an artifact or creature' / 'two artifacts' -> {"any": [permanent filters], "n": count},
    or None (lands and anything perm_filt can't read stay unmodeled)."""
    n = num(article) if article not in ("a", "an", "another") else 1
    if not isinstance(n, int): return None
    fs = []
    for part in re.split(r",\s*(?:or\s+)?|\s+or\s+", subj.strip()):
        if any(w not in FODDER_WORDS and w not in COLOR_WORDS and not as_subtype(w) for w in re.findall(r"[a-z\-']+", part)):
            return None                                   # 'another colorless creature', 'a creature with ...': unread
        f = perm_filt("another" if article == "another" else "a", part.strip())
        if not f or f["type"] == "Land" or f["sub"] & LAND_TYPES: return None        # lands aren't fodder here (Orcish Lumberjack)
        fs.append(f)
    return {"any": fs, "n": n} if fs else None

def perm_desc(f):
    """A permanent filter as words, for --explain."""
    if "any" in f: return ("two " if f.get("n") == 2 else "three " if f.get("n") == 3 else "") + " or ".join(perm_desc(x) for x in f["any"])
    return ("another " if f["another"] else "") + ("commander " if f.get("commander") else "") \
        + ("legendary " if f.get("legendary") else "") + ("".join(sorted(f["colors"])) + " " if f.get("colors") else "") \
        + ("nontoken " if f.get("nontoken") else "") + ("token " if f.get("token") else "") \
        + (" ".join(sorted(f["sub"])) + " " if f.get("sub") else "") \
        + "".join(q + " " for q in ("modified", "equipped", "enchanted", "historic") if f.get(q)) \
        + ("" if f.get("sub") and f["type"] == "Permanent" else f["type"].lower()) + (f" power>={f['power']}" if f["power"] else "") \
        + (f" power<={f['pow_max']}" if f.get("pow_max") is not None else "") + (f" with {f['kw']}" if f.get("kw") else "") \
        + (f" non-{f['nonsub']}" if f.get("nonsub") else "") + (" with a counter" if f.get("ctr") else "")

def ab_cost(cost):
    """Ability cost -> (tap, generic, pips, sacrifice ~, (counter kind, n) or None, unparsed?, fodder).
    fodder: 'Sacrifice a Food / another creature / an artifact or creature' as a fodder_filt, else None."""
    lo = cost.lower()
    syms = "".join("{%s}" % s for s in SYM.findall(cost) if s not in ("T", "Q"))
    g, p, _, _ = parse_cost(syms)
    fm = re.search(r"sacrifice (a|an|another|two|three) ([^,]+?)\s*(?=,|$)", lo)
    fod = fodder_filt(fm.group(1), fm.group(2)) if fm else None
    if fod: lo = lo[:fm.start()] + lo[fm.end():]
    rm = re.search(r"remove (a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+) (\S+?) counters? from ~", lo)
    if rm: lo = lo[:rm.start()] + lo[rm.end():]              # an unread counter cost ('Remove X ...') stays in rest: unparsed
    rest = re.sub(r"\{[^}]+\}|pay \d+ life|sacrifice ~|,|\s", "", lo)
    return "{t}" in lo, g, p, "sacrifice ~" in lo, ((rm.group(2), num(rm.group(1))) if rm else None), bool(rest), fod

PAIN_LINE = re.compile(r"(?:^|\n)\{t\}(?P<pay>, pay (?P<n1>\d+) life)?: add [^\n]*?(?:~ deals (?P<n2>\d+) damage to you)?\.?(?=\n|$)")
def read_life_costs(k, lo):
    """Life the deck pays itself: pain on mana abilities, additional life costs on spells."""
    m = re.search(r"as an additional cost to cast (?:this spell|~), pay (\d+) life", lo)
    if m: k.addlife = int(m.group(1))
    m = re.search(r"whenever ~ becomes tapped, it deals (\d+) damage to you", lo)
    if m: k.pain = int(m.group(1)); return
    free_c, hurt = False, []
    for a in PAIN_LINE.finditer(lo):
        n = int(a.group("n1") or a.group("n2") or 0)
        if n: hurt.append((n, a.group(0)))
        elif re.search(r"add \{c\}", a.group(0)): free_c = True
    if hurt:
        k.pain = max(n for n, _ in hurt)
        k.pain_col = free_c and all(re.search(r"\{[wubrg]\}|any color", t) for _, t in hurt)

def etap_rule(lo):
    m = re.search(r"you may pay (\d+) life\. if you don't", lo)
    if m: return ("shock", int(m.group(1)))
    if "two or fewer other lands" in lo: return ("fast",)
    if "two or more other lands" in lo: return ("slow",)
    if "two or more opponents" in lo: return None
    m = re.search(r"unless you control an? (\w+)(?: or (?:an? )?(\w+))?", lo)
    if m and m.group(1) in BASIC: return ("check", frozenset(g for g in m.groups() if g))
    m = re.search(r"(?:unless you|you may) reveal an? (\w+)(?: or (?:an? )?(\w+))? card from your hand", lo)
    if m: return ("reveal", frozenset(g for g in m.groups() if g))
    return ("always", "conditional") if ("unless" in lo or " if " in lo) else ("always",)

def _trig_x(what, ev):
    kind = "enter" if ev.startswith("entering") else "dies" if ev == "dying" else "attack"
    w = re.sub(r"\s*you control$", "", what.strip())
    f = {"land": True} if w == "land" else {"any": [perm_filt("a", "permanent")]} if w == "permanent" else fodder_filt("a", w) or perm_filt("a", w)
    return ("trig_x", kind, f) if f else ("unread",)

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
    (r"^([\w ,]*?)spells?(?: you cast)?( with power \d+ or greater)?(?: each turn)? costs? \{(\d+)\} less to cast\.?$",
     lambda m, lo: ("reduce", parse_filter(m.group(1) + (m.group(2) or "")), int(m.group(3)))),
    # Strong Back: read as always on (Auras go on the creature it enchants, the pilot's best attacker) ~approx
    (r"^([\w ,]*?)spells? you cast that targets? (?:an? )?(?:enchanted|equipped) creature costs? \{(\d+)\} less to cast",
     lambda m, lo: ("reduce", parse_filter(m.group(1)), int(m.group(2)))),
    (r"^equip abilities you activate(?: that target (?:an? )?(?:enchanted|equipped) creature)? cost \{(\d+)\} less to activate",
     lambda m, lo: ("equip_red", int(m.group(1)))),
    (r"^([\w ]*?)spells you cast have affinity for (artifacts|[a-z]+s)\.?$",           # Pearl-Ear: enchantment spells, affinity for Auras
     lambda m, lo: ("reduce_dyn", parse_filter(m.group(1)),
                    ("artifacts",) if m.group(2) == "artifacts" else ("sub", as_subtype(m.group(2)) or m.group(2).capitalize()))),
    (r"^no more than (one|two|three) creatures? can attack each combat", lambda m, lo: ("attack_limit", num(m.group(1)))),   # Silent Arbiter
    (r"^no more than (?:one|two|three) creatures? can block each combat", lambda m, lo: ("neutral_block",)),                 # opponents never attack
    (r"^(other )?creatures have base power and toughness (\d+)/(\d+)", lambda m, lo: ("base_pt", int(m.group(2)), int(m.group(3)), bool(m.group(1)))),
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
    # token replacements: Academy Manufactor (one of each), Stridehangar Automaton (an extra Thopter per artifact-token event)
    (r"^if you would create a clue, food, or treasure token, instead create one of each", lambda m, lo: ("token_each",)),
    # Doubling Season, Anointed Procession, Parallel Lives, Mondrak; Ojer Taq triples creature tokens
    (r"^if (?:an effect would create one or more (?P<c1>creature )?tokens under your control, it creates |one or more (?P<c2>creature )?tokens "
     r"would be created(?: under your control)?, )(?P<n>twice|three times) that many of those tokens(?: are created)? instead\.?$",
     lambda m, lo: ("token_mult", 2 if m.group("n") == "twice" else 3, bool(m.group("c1") or m.group("c2")))),
    (r"^if one or more artifact tokens would be created under your control, those tokens plus an additional 1/1 colorless thopter",
     lambda m, lo: ("thopter_plus",)),
    # trigger doublers: Panharmonicon / Yarok / Teysa / Isshin (what caused it), Roaming Throne / Annie Joins Up (whose ability)
    (r"^if (?:a |an )?(?P<what>[a-z ,']+?) (?P<ev>entering(?: the battlefield)?|dying|attacking) causes a triggered ability of a permanent "
     r"you control to trigger, that ability triggers an additional time\.?$", lambda m, lo: _trig_x(m.group("what"), m.group("ev"))),
    (r"^if a triggered ability of (?P<a>another|an?) (?P<what>[a-z ,'\-]+?) you control triggers, (?:that ability|it) triggers an additional time\.?$",
     lambda m, lo: ("trig_x", "src", perm_filt(m.group("a"), m.group("what"))) if perm_filt(m.group("a"), m.group("what")) else ("unread",)),
    # damage doublers: Furnace of Rath / Dictate of the Twin Gods (any source), City on Fire / Fiery Emancipation (yours)
    (r"^if a source(?P<yours> you control)? would deal damage to (?:a permanent or player|an opponent or a permanent an opponent controls"
     r"|a permanent or player an opponent controls)[^,]*, it deals (?P<n>double|triple) that damage",
     lambda m, lo: ("dmg_mult", 2 if m.group("n") == "double" else 3, bool(m.group("yours")))),
]
STATIC_RX = [(re.compile(rx), fn) for rx, fn in STATIC_RX]

def combat_trigger(k, lo):
    """Attack, combat damage, beginning of combat and dies triggers -> k.trig. None = not one of these.
    Events: attack_self / attack (a creature you control attacks; filter) / attack_any (you attack, once per combat) /
    cdmg_self / cdmg (filter) / cdmg_any (once per player dealt damage) / combat_begin / dies_self / dies (filter)."""
    once = bool(re.search(r"for the first time each turn|if it's the first combat phase of the turn|this ability triggers only once each turn", lo))
    lo = re.sub(r" for the first time each turn|,? if it's the first combat phase of the turn", "", lo)
    def add(ev, f, fxt):
        if re.match(r"if\b", fxt): k.notes.append("conditional combat trigger (intervening 'if') not modeled"); return False
        fx, tax = parse_fx(fxt)
        if fx: k.trig.append((ev, f, fx, once, tax, False))
        return bool(fx)
    m = re.match(r"^whenever (?:equipped|enchanted) creature attacks,\s*(.+)$", lo)
    if m: return add("attack_att", None, m.group(1))
    m = re.match(r"^whenever (?:equipped|enchanted) creature deals combat damage to (?:a player|an opponent),\s*(.+)$", lo)
    if m: return add("cdmg_att", None, m.group(1))
    m = re.match(r"^whenever ~ attacks(?: or blocks)?(?: alone)?,\s*(.+)$", lo) or \
        re.match(r"^whenever ~ and at least \w+ other creatures? attack,\s*(.+)$", lo)
    if m: return add("attack_self", None, m.group(1))
    m = re.match(r"^whenever ~ deals combat damage to (?:a player|an opponent)(?: or (?:a )?(?:planeswalker|battle))?,\s*(.+)$", lo) or \
        re.match(r"^whenever ~ deals damage to (?:a player|an opponent),\s*(.+)$", lo)
    if m: return add("cdmg_self", None, m.group(1))
    m = re.match(r"^whenever (?:you attack|one or more (?P<subj>[^,]+?) attack)(?: a player| an opponent| one or more of your opponents)?,\s*(?P<fx>.+)$", lo)
    if m:
        if m.group("subj") and "opponent" in m.group("subj"): return False
        f = perm_filt("a", m.group("subj")) if m.group("subj") else None
        if m.group("subj") and not f: return False                   # an unread filter isn't 'any creature'
        return add("attack_any", f, m.group("fx"))
    m = re.match(r"^whenever one or more (?P<subj>[^,]+?) deal combat damage to (?:a player|an opponent|one or more players),\s*(?P<fx>.+)$", lo)
    if m:
        if "opponent controls" in m.group("subj") or not perm_filt("a", m.group("subj")): return False
        return add("cdmg_any", perm_filt("a", m.group("subj")), m.group("fx"))
    m = re.match(r"^whenever (?P<a>a|an|another) (?P<subj>[^,]+?) deals combat damage to (?:a player|an opponent),\s*(?P<fx>.+)$", lo)
    if m:
        f = perm_filt(m.group("a"), m.group("subj"))
        if not f or "opponent" in m.group("subj"): return False
        return add("cdmg", f, m.group("fx"))
    m = re.match(r"^whenever ~ attacks and isn't blocked,\s*(.+)$", lo)
    if m: return add("unblocked_self", None, m.group(1))
    m = re.match(r"^whenever ~ becomes blocked(?: by a creature)?,\s*(.+)$", lo)
    if m: return add("blocked_self", None, m.group(1))
    m = re.match(r"^whenever (?P<a>a|an|another) (?P<subj>[^,]+?) becomes blocked,\s*(?P<fx>.+)$", lo)
    if m:
        f = perm_filt(m.group("a"), m.group("subj"))
        return add("blocked", f, m.group("fx")) if f else False
    m = re.match(r"^whenever (?P<a>a|an|another) (?P<subj>[^,]+?) attacks(?P<alone> alone)?,\s*(?P<fx>.+)$", lo)
    if m:
        f = perm_filt(m.group("a"), m.group("subj"))
        if not f or "opponent" in m.group("subj"): return False
        if m.group("alone"): f["alone"] = True
        return add("attack", f, m.group("fx"))
    m = re.match(r"^at the beginning of (?:combat on your turn|each combat),\s*(.+)$", lo)
    if m: return add("combat_begin", None, m.group(1))
    m = re.match(r"^when(?:ever)? ~ dies,\s*(.+)$", lo)
    if m: return add("dies_self", None, m.group(1))
    m = re.match(r"^whenever (?P<self>~ or )?(?P<a>a|an|another|one or more(?: other)?) (?P<subj>[^,]+?) (?:dies|die),\s*(?P<fx>.+)$", lo)
    if m:
        if "opponent" in m.group("subj"): return False
        f = perm_filt("another" if "other" in m.group("a") else "a", m.group("subj"))
        if not f: return False
        if m.group("self"): f = dict(f, another=False)          # 'whenever ~ or another creature dies'
        if m.group("a").startswith("one or more"):               # one trigger for a batch: ~approx once per phase
            fx, tax = parse_fx(re.sub(r"\s*this ability triggers only once each turn\.?", "", m.group("fx")))
            if fx: k.trig.append(("dies", f, fx, True, tax, False))
            return bool(fx)
        return add("dies", f, m.group("fx"))
    return None

def parse_trigger(k, lo):
    """'when ~ enters, ...' / 'whenever you cast ...' / 'at the beginning of ...' -> k fields.
    Trigger tuple: (event, filter, effects, once per turn, tax, also on opponents' turns)."""
    m = re.match(r"^when(?:ever)? ~ enters(?: the battlefield)?( or attacks| or dies| or is put into a graveyard from the battlefield)?,\s*(.+)$", lo)
    if m:
        fx, _ = parse_fx(m.group(2)); k.etb += fx
        if m.group(1) and fx:
            ev = "attack_self" if "attacks" in m.group(1) else "dies_self" if "dies" in m.group(1) else "gy_self"
            k.trig.append((ev, None, fx, False, False, False))
        return bool(fx)
    m = re.match(r"^when(?:ever)? ~ (is put into a graveyard from the battlefield|leaves the battlefield),\s*(.+)$", lo)
    if m:                                               # Spirit Loop, Munitions: fire as the permanent leaves (tokens too)
        fxt = m.group(2).strip().rstrip(".")
        fx = [("regrow_self",)] if re.fullmatch(r"return (?:it|~) to its owner's hand", fxt) else parse_fx(fxt)[0]
        if fx: k.trig.append(("gy_self" if "graveyard" in m.group(1) else "leave_self", None, fx, False, False, False))
        return bool(fx)
    r = combat_trigger(k, lo)
    if r is not None: return r
    m = re.match(r"^whenever (?:you|a player) sacrifices? (?P<subj>(?:a|an|another|one or more) [^,]+?),\s*(?P<fx>.+)$", lo)
    if m:                                               # Nuka-Cola, Experimental Confectioner (only your sacrifices exist)
        am = re.match(r"(a|an|another|one or more) (.+)$", m.group("subj"))
        f = fodder_filt("another" if am.group(1) == "another" else "a", am.group(2))
        if not f: return False
        if "a player" in lo: k.notes.append("only your own sacrifices are modeled")
        fx, tax = parse_fx(m.group("fx"))
        if fx: k.trig.append(("sac", f, fx, False, tax, False))
        return bool(fx)
    m = re.match(r"^whenever you gain life( for the first time each turn)?,\s*(.+)$", lo)
    if m:                                               # Well of Lost Dreams, Heliod, Trudge Garden
        fx, tax = parse_fx(m.group(2))
        if fx: k.trig.append(("gain", None, fx, bool(m.group(1)), tax, False))
        return bool(fx)
    m = re.match(r"^whenever (enchanted creature|equipped creature|~) deals damage,\s*(.+)$", lo)
    if m:                                               # Spirit Loop: combat and noncombat damage, one trigger per damage event
        fx, _ = parse_fx(m.group(2))
        if fx: k.trig.append(("dmg_self" if m.group(1) == "~" else "dmg_att", None, fx, False, False, False))
        return bool(fx)
    m = re.match(r"^when you cast (?:this spell|~),\s*(.+)$", lo)
    if m:
        fx, _ = parse_fx(m.group(1)); k.castfx += fx; return bool(fx)
    m = re.match(r"^at the beginning of (your|each|each player's) (upkeep|end step|draw step|(?:first|precombat) main phase)[^,]*,\s*(.+)$", lo)
    if m:
        body, cond = m.group(3), None
        cm = re.match(r"if you gained life this turn,\s*(.+)$", body) or re.match(r"if you have (\d+) or more life,\s*(.+)$", body)
        if cm:                                         # Ragost's untap, Test of Endurance: read intervening 'if's
            cond = ("life", int(cm.group(1))) if cm.lastindex == 2 else "gained"
            body = cm.group(cm.lastindex)
        elif re.match(r"if (?!an opponent controls more lands)", body):
            k.notes.append("conditional trigger (intervening 'if') not modeled"); return False
        fx, tax = parse_fx(body)
        if cond and re.fullmatch(r"you win the game\.?", body.strip()): fx = [("win",)]     # Test of Endurance, Felidar Sovereign
        if fx and cond: fx = [("cond", cond, fx)]
        ev = {"upkeep": "upkeep", "end step": "end", "draw step": "drawstep"}.get(m.group(2), "main1")
        if fx: k.trig.append((ev, None, fx, False, tax, m.group(1) != "your"))
        return bool(fx)
    m = re.match(r"^whenever you cast (?:or copy )?(an|a|your first|your second)?\b ?(.*?)spells?(?: each turn)?(?: from [^,]+)?"
                 r"(?: that targets (?P<tg>~|(?:a |an |one or more )?(?:creatures?|modified permanents?|permanents?) you control))?,\s*(?P<fx>.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group("fx")); f = parse_filter(m.group(2)) if m.group(2).strip() else None
        if f and f["unknown"]: k.notes.append("cast-trigger filter partly unread: " + m.group(2).strip())
        if m.group("tg"):                                  # heroic / Season of Growth / Pearl-Ear: the spell must target yours
            f = f or parse_filter("")
            f["targets"] = "self" if m.group("tg") == "~" else "modified" if "modified" in m.group("tg") else "creature"
        k.trig.append(("cast", f, fx, "first" in (m.group(1) or ""), tax, False)); return bool(fx)
    m = re.match(r"^when(?:ever)? (?P<self>~ or )?(a|an|another|one or more) (?P<subj>.+?) enters?(?: the battlefield)?(?: under your control)?(?: this turn)?,\s*(?P<fx>.+)$", lo)
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
        f = perm_filt(m.group(2), subj)
        if not f: return False
        if m.group("self"): f = dict(f, another=False)       # constellation: 'whenever ~ or another enchantment enters'
        once = bool(re.search(r"this ability triggers only once each turn", m.group("fx"))) or m.group(2) == "one or more"
        fx, tax = parse_fx(re.sub(r"\s*this ability triggers only once each turn\.?", "", m.group("fx")))
        if f["type"] == "Land":
            k.trig.append(("landfall", None, fx, once, tax, False)); return bool(fx)
        k.trig.append(("etb", f, fx, once, tax, False)); return bool(fx)
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
    m = re.match(r"^whenever an opponent casts (an|a|their first)\b ?(.*?)spells?(?: each turn)?,\s*(.+)$", lo)
    if m:
        fx, tax = parse_fx(m.group(3)); f = parse_filter(m.group(2)) if m.group(2).strip() else None
        if fx: k.trig.append(("opp_cast", f, fx, "first" in m.group(1), tax, False))
        return bool(fx)
    def gated(body):                                       # intervening 'if': left unmodeled, like the other trigger frames
        if re.match(r"if ", body): k.notes.append("conditional trigger (intervening 'if') not modeled"); return True
        return False
    m = re.match(r"^whenever an opponent draws a card,\s*(.+)$", lo)
    if m:
        if gated(m.group(1)): return False
        fx, tax = parse_fx(re.sub(r"\bto them\b", "to that player", m.group(1)))
        if fx: k.trig.append(("opp_draw", None, fx, False, tax, False))
        return bool(fx)
    m = re.match(r"^when(?:ever)? (?:equipped|enchanted) creature dies,\s*(.+)$", lo)   # Skullclamp, Malefic Scythe
    if m:
        if gated(m.group(1)): return False
        fx, tax = parse_fx(m.group(1))
        if fx: k.trig.append(("dies_att", None, fx, False, tax, False))
        return bool(fx)
    m = re.match(r"^whenever you draw a card,\s*(.+)$", lo)                  # Niv-Mizzet, Psychosis Crawler, Chasm Skulker
    if m:
        if gated(m.group(1)): return False
        fx, tax = parse_fx(m.group(1))
        if fx: k.trig.append(("draw_card", None, fx, False, tax, False))
        return bool(fx)
    m = re.match(r"^whenever a player casts (an|a)\b ?(.*?)spells?,\s*(.+)$", lo)   # yours and theirs (Forgotten Ancient, Managorger)
    if m:
        if gated(m.group(3)): return False
        if re.search(r"\bthat player\b|\bthey\b", m.group(3)): return False   # rewards whoever cast it (Unifying Theory): not read
        fx, tax = parse_fx(m.group(3)); f = parse_filter(m.group(2)) if m.group(2).strip() else None
        if fx: k.trig += [("cast", f, fx, False, tax, False), ("opp_cast", f, fx, False, tax, False)]
        return bool(fx)
    if re.search(r"attacks|combat damage|blocks", lo): k.notes.append("combat trigger not read")
    return False

RX_GRANT = re.compile(r'^(?P<subj>equipped creature|enchanted creature|enchanted (?:land|forest|plains|island|swamp|mountain)'
                      r'|commander creatures you (?:own|control)|(?:other )?(?:[a-z\-]+ )?creatures you control)'
                      r'(?: gets? (?P<p>[+-]\d+)/(?P<t>[+-]\d+))?,?(?: and)? (?:has|have) (?:(?P<kw>[a-z, ]+?),? and )?"(?P<q>[^"]+)"\.?$')

def _as_obj(fx):
    """A granted ability's effects, re-aimed from the granting card at the creature that has the ability."""
    out = []
    for e in fx:
        if e[0] == "pump" and e[1] == "self": e = ("pump", "obj") + tuple(e[2:])
        elif e[0] == "ctr": e = ("ctr_on", "obj", e[1], e[2], False)
        elif e[0] == "face" and e[1] == ("pow",): e = ("face", ("objpow",)) + tuple(e[2:])
        elif e[0] == "bounce_self": continue
        out.append(e)
    return out

CMDR_FILTER = {"types": {"Creature"}, "non": set(), "legendary": False, "colors": set(), "multi": False, "historic": False,
               "mv_max": None, "unknown": False, "sub": set(), "commander": True}     # 'commander creatures you own'

def grant_line(k, lo, anyc):
    """'Enchanted creature has "Whenever this creature deals combat damage to a player, ..."' (Mark of Sakiko, Snake Umbra),
    'Commander creatures you own have "Whenever this creature attacks, ..."' (Backgrounds), 'Creatures you control have
    "{T}: Add ..."' (Cryptolith Rite), 'Enchanted land has "{T}: Add two mana ..."' (Gift of Paradise).
    None = not a grant; True = read; False = a grant whose quoted ability isn't read."""
    m = RX_GRANT.match(lo)
    if not m: return None
    subj, q = m.group("subj"), m.group("q").strip()
    kws = _kw_in(m.group("kw") or "")
    dp, dt = (int(m.group("p")), int(m.group("t"))) if m.group("p") else (0, 0)
    attach = subj in ("equipped creature", "enchanted creature")
    mm = RX_MANA.match(q)
    if subj.startswith("enchanted") and not attach:            # a land Aura granting a mana ability: the land taps for this instead
        units = parse_prod(mm.group("prod"), anyc)[0] if mm else None
        if not units: return False
        if len(units) > 1: k.units += [(anyc, NOC, None, False)] * (len(units) - 1)
        else: k.notes.append("granted land mana is color fixing only (no extra mana)")
        return True
    if attach:
        a = k.attach or (0, 0, frozenset())
        k.attach = (a[0] + dp, a[1] + dt, frozenset(a[2] | kws))
    pf = {"type": "Creature", "another": subj.startswith("other"), "power": 0, "sub": set(), "nontoken": False, "token": False}
    if subj.startswith("commander"):
        pf["commander"] = True
        if dp or dt or kws: k.statics.append(("anthem", CMDR_FILTER, dp, dt, frozenset(kws), False, False))
    elif not attach:
        cf = creature_filter(subj)
        if not cf: return False
        pf["sub"] = set(cf[0]["sub"])
        if dp or dt or kws: k.statics.append(("anthem", cf[0], dp, dt, frozenset(kws), cf[1], False))
    if mm and not attach:                                      # creatures gain a mana ability (Cryptolith Rite, Citanul Hierophants)
        tap, g, p, sac, rm, other, fod = ab_cost(mm.group("cost").upper())     # lowercased text: {t} -> {T}
        units = parse_prod(mm.group("prod"), anyc)[0]
        if not tap or g or p or sac or rm or other or fod or not units: return False
        k.statics.append(("cr_mana", [(u, NOC, None, False) for u in units], pf)); return True
    if not q.startswith(("when", "whenever", "at the beginning")):
        k.notes.append("granted ability not read: " + q[:50]); return False
    tmp = Card(k.name); tmp.types = {"Creature"}
    if not parse_trigger(tmp, q) or not tmp.trig:
        k.notes.append("granted ability not read: " + q[:50]); return False
    ev_map = {"attack_self": "attack_att" if attach else "attack", "cdmg_self": "cdmg_att" if attach else "cdmg"}
    got = False
    for ev, f, fx, once, tax, each in tmp.trig:
        if ev not in ev_map: k.notes.append(f"granted {ev} trigger not modeled"); continue
        k.trig.append((ev_map[ev], None if attach else dict(pf), _as_obj(fx), once, tax, each)); got = True
    return got

RX_TYPE_GRANT = re.compile(r'^(?:all )?(?P<subj>artifacts|creatures|enchantments|nonland permanents|permanents)(?: you control)? are '
                           r'(?P<what>[a-z ]+?) in addition to their other (?:creature )?types'
                           r'(?:,? and (?:have|gain) "(?P<q>[^"]+)")?\.?$', re.I)

def type_grant_line(k, L, anyc):
    """'Artifacts you control are Foods in addition to their other types and have "{2}, {T}, Sacrifice this artifact:
    You gain 3 life."' (Ragost) -> ('type_grant', printed types it covers, added types, added subtypes, granted abilities).
    The added types count for fodder costs, sacrifice triggers and filters; the quoted ability is read like card text
    and every permanent it covers can use it. None = not one; False = a grant it can't read."""
    m = RX_TYPE_GRANT.match(L.strip())
    if not m: return None
    subj = m.group("subj").lower()
    covers = {"artifacts": {"Artifact"}, "creatures": {"Creature"}, "enchantments": {"Enchantment"}}.get(subj, PERMANENT - {"Land"})
    add_t, add_s = set(), set()
    for w in re.findall(r"[a-z]+", m.group("what").lower()):
        t = w.capitalize().rstrip("s") if w.capitalize().rstrip("s") in TYPES else None
        st = as_subtype(w)
        if t: add_t.add(t)
        elif st: add_s.add(st)
        elif w not in ("and", "a", "an"): return False
    acts = []
    if m.group("q"):
        tmp = Card(k.name); tmp.types = set(covers)
        abil = []
        if parse_line(tmp, m.group("q").strip(), anyc, abil) is not True or not tmp.acts or abil:
            k.notes.append("granted ability not read: " + m.group("q")[:50]); return False
        acts = tmp.acts
    k.statics.append(("type_grant", frozenset(covers), frozenset(add_t), frozenset(add_s), acts))
    return True

def parse_line(k, L, anyc, abil):
    """One Oracle line -> k fields. True = modeled, False = not modeled, 'neutral' = irrelevant to a goldfish."""
    aw = re.match(r"^([A-Z][\w']*(?: [\w']+){0,2}) — (?=[^:]*\{[^:]*:)", L)
    if aw and aw.group(1).lower() in ABILITY_WORDS: L = L[aw.end():]   # 'Metalcraft — {T}: Add ...': a label (CR 207.2c), not Boast/Exhaust
    lo = L.lower()
    m = RX_MANA.match(L)
    if m and k.imprint and re.match(r"one mana of any of the exiled card's colors", m.group("prod") or "", re.I):
        return True                                       # Chrome Mox: units per permanent (Perm.imp)
    if m:
        tap, g, p, sac, rm, other, fod = ab_cost(m.group("cost"))
        if other or rm: return False
        if fod:                                           # Ashnod's Altar, Phyrexian Tower, Gilded Goose: fodder becomes mana
            units, approx = parse_prod(m.group("prod"), anyc)
            restr, co = restriction(m.group("rest"))
            if not units or approx or g or p or restr == "unknown" or re.search(r"activate only", m.group("rest").lower()): return False
            k.sac_outlets.append((fod, [(NOC, u, restr, co) if restr else (u, NOC, None, co) for u in units], tap))
            return True
        if m.group("vivid"): k.vivid = True; return True
        units, approx = parse_prod(m.group("prod"), anyc)
        if not units: return False
        restr, co = restriction(m.group("rest"))
        if restr == "unknown": k.notes.append("mana restriction not recognized; treated as unrestricted"); restr = None
        cm = re.search(r"activate only if you control (a|an|one|two|three|four|five|\d+)(?: or more)? ([^.]+)", m.group("rest").lower())
        if cm:                                            # Mox Opal (metalcraft), Fanatic of Rhonas (ferocious)
            pm = re.fullmatch(r"creatures? with power (\d+) or greater", cm.group(2).strip())
            w = cm.group(2).strip()
            key = ("power",) if pm else clean_dyn(w if w.endswith("you control") else w + " you control")
            if not key or approx or g or p: return False
            k.cond_units.append(([(u, NOC, restr, co) if not restr else (NOC, u, restr, co) for u in units], key,
                                 int(pm.group(1)) if pm else num(cm.group(1))))
            return True
        elif re.search(r"activate only if", m.group("rest").lower()): return False
        dk = dyn_prod(m.group("prod")) if approx else None
        if dk: k.dyn_mana = dk; units = units[:1]
        elif approx: k.notes.append("variable mana amount counted as one")
        if "opponent controls could produce" in lo: k.notes.append("assumes opponents' lands cover your colors")
        if " among " in lo: k.notes.append("'any color among' approximated as any color")
        if sac: k.sac_mana = True
        abil.append((units, restr, co, g + len(p)))
        return True
    r = type_grant_line(k, L, anyc)
    if r is not None: return r
    r = grant_line(k, lo, anyc)
    if r is not None: return r
    m = re.match(r"^\{t\}: untap (?:target|up to (one|two|three) target) (land|basic land|forest|plains|island|swamp|mountain)s?\.?$", lo)
    if m:                                            # Arbor Elf, Voyaging Satyr, Krosan Restorer: tap for that land's mana again
        k.untapper = (num(m.group(1)) if m.group(1) else 1, land_filter(m.group(2))); return True
    if re.search(r"~ enters(?: the battlefield)? tapped|if you don't, (?:it|~) enters tapped", lo):
        k.etap = etap_rule(lo)
        if k.etap == ("always", "conditional"): k.notes.append("conditional enters-tapped read as always tapped")
        return True
    m = re.match(r"^(?:\{t\}, )?(?:pay \d+ life, )?sacrifice ~: search your library for (?:an? |up to one )?(.+?) cards?,.*?put (?:it|that card) onto the battlefield( tapped)?", lo)
    if m and k.is_land:
        k.fetch = (land_filter(m.group(1)), bool(m.group(2)))
        fl = re.search(r"pay (\d+) life", lo); k.fetch_life = int(fl.group(1)) if fl else 0; return True
    m = re.match(r"^when ~ enters, sacrifice it\. when you do, search your library for (?:a|an) (basic [^.]+?) card, put it onto the battlefield( tapped)?", lo)
    if m and k.is_land:                                  # Riveteers Overlook: a fetchland that cracks itself
        k.fetch = (land_filter(m.group(1)), bool(m.group(2))); k.fetch_life = 0; return True
    if re.search(r"if (?:this card|~) is in your opening hand, you may begin the game with it on the battlefield", lo):
        k.leyline = True; return True
    m = re.search(r"~ enters with (a|an|one|two|three|four|five|six|x|\d+) (\S+?) counters? on it", lo)
    if m:
        n = num(m.group(1))
        if m.group(1) == "x":                         # 'where X is ...' (Prime Speaker Zegana); a bare X is the spell's
            n = _face_n("x", lo[m.end():].split(".")[0] if "where x is" in lo[m.end():].split(".")[0] else
                        lo[lo.index("where x is"):] if "where x is" in lo else "")
            if not n: return False
        fe = re.match(r" for each (.+?)\.?$", lo[m.end():])
        if fe:                                        # converge (Magmablood Archaic), 'for each creature you control'
            n = clean_dyn(fe.group(1))
            if not n: return False
        k.ctr_enter = (m.group(2), n, "if you cast it from your hand" in lo); return True
    if re.search(r"when ~ enters, return a land you control to its owner's hand", lo):
        k.bounce = True; return True
    m = re.match(r"^(?:~|this spell) costs \{(\d+)\} less to cast for each (.+?)\.?$", lo)
    if m and clean_dyn(m.group(2)):
        k.self_red = (int(m.group(1)), clean_dyn(m.group(2))); return True
    for rx, fn in STATIC_RX:
        m = rx.search(lo)
        if m:
            st = fn(m, lo)
            if st[0] == "unread": return False
            k.statics.append(st); return True
    if combat_static(k, lo): return True
    lo2 = re.sub(r"^[a-z][\w' ]* — ", "", lo)
    if re.fullmatch(r"whenever ~ becomes tapped, it deals \d+ damage to you\.?", lo2): return True   # pain (read_life_costs)
    if re.fullmatch(r"if you would draw a card while your library has no cards in it, you win the game instead\.?", lo2):
        k.labman = True; return True
    if k.requires == "gy" and "return enchanted creature card to the battlefield" in lo:
        return True                                       # Animate Dead: the recursion is read from its enchant line
    if re.fullmatch(r"~ is the chosen type in addition to its other types\.?", lo2):
        if CHOSEN_TYPE: k.subtypes = k.subtypes | {CHOSEN_TYPE}
        return True                                       # Metallic Mimic, Roaming Throne
    if re.fullmatch(r"when ~ enters, you may exile a nonartifact, nonland card from your hand\.?", lo2):
        k.imprint = True; return True                     # Chrome Mox (the mana ability reads the exiled card)
    if re.fullmatch(r"if ~ would enter, you may discard a land card instead\. if you do, put ~ onto the battlefield\. "
                    r"if you don't, put it into its owner's graveyard\.?", lo2):
        k.mox_diamond = True; k.requires = "spare_land"; return True
    if lo2.startswith(("when", "whenever", "at the beginning")):
        return parse_trigger(k, lo2) or ("neutral" if is_neutral(lo2) else False)
    m = re.match(r"^([+−\-]?)(\d+|x):\s*(.+)$", lo)
    if m and "Planeswalker" in k.types:
        fx, _ = parse_fx(m.group(3))
        cost = (int(m.group(2)) if m.group(2).isdigit() else 0) * (-1 if m.group(1) in "−-" and m.group(1) else 1)
        if fx: k.pw.append((cost, fx))
        return bool(fx)
    m = re.match(r'^(?P<cost>[^:"]+?):\s*(?P<fx>.+)$', L)
    if m and re.search(r"\{|sacrifice |remove |pay \d+ life", m.group("cost").lower()):
        tap, g, p, sac, rm, other, fod = ab_cost(m.group("cost"))
        fx, _ = parse_fx(m.group("fx"))
        if other or not fx: return "neutral" if is_neutral(lo) else False
        if any(e[0] == "tutor" and tutor_unread(e[1]) for e in fx):
            k.notes.append("tutor filter not fully read; ability not used"); return False
        if not tap and not g and not p and sac and not rm and not fod and any(e[0] == "land_search" for e in fx):
            k.etb += fx; k.sac_etb = True; return True        # Sakura-Tribe Elder style: sacrifice at once
        lm = re.search(r"pay (\d+) life", m.group("cost").lower())
        k.acts.append({"tap": tap, "gen": g, "pips": p, "sac": sac, "rm": rm, "fx": fx, "life": (int(lm.group(1)) if lm else 0) + parse_cost(m.group("cost"))[3],
                       "combat": "activate only during combat" in lo, "sorcery": "activate only as a sorcery" in lo, "fodder": fod})
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
MODE_RANK = ("draw", "look", "look_f", "tutor", "tutor_multi", "recur", "land_search", "treasure", "token", "mana", "extra_land",
             "prolif", "ctr", "scry", "surveil", "mill")

def modal_lines(lines):
    """Fold 'Choose one —' + its bullet lines into one ('MODAL', prefix, n, [bullets]) item."""
    out, i = [], 0
    while i < len(lines):
        m = MODAL_RX.match(lines[i])
        mc = re.match(r"^choose one\. if you control a commander as you cast (?:this spell|~), you may choose both instead\.?$", lines[i], re.I)
        if mc:                                            # Jeska's / Klauth's Will: both modes (a commander is usually out)
            bullets = []
            j = i + 1
            while j < len(lines) and lines[j].startswith("•"):
                bullets.append(re.sub(r"^•\s*(?:[^—]{1,30}—\s*)?", "", lines[j])); j += 1
            if bullets: out.append(("MODAL", "", 2, bullets)); i = j; continue
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
    saved = _CTX.get("left"); _CTX["left"] = None                          # scoring every mode: only the chosen ones count
    ranked = sorted(bullets, key=lambda b: (score(b)[0], not score(b)[1]))
    chosen = [b for b in ranked[:take] if score(b)[1]]
    _CTX["left"] = saved
    if not chosen: return False
    text = " ".join(b if b.endswith(".") else b + "." for b in chosen)
    if not pre:
        if k.types & {"Instant", "Sorcery"}:
            fx, _ = parse_fx(text); k.spell += fx; return bool(fx)
        return False
    lo = (pre + ", " + text).lower()
    lo = re.sub(r"^[a-z][\w' ]* — ", "", lo)
    if not lo.startswith(("when", "whenever", "at the beginning")): return False
    if take == 99 and len(chosen) > 1:                   # 'choose one or more': each mode on its own, life costs checked (BMC)
        n0, e0 = len(k.trig), len(k.etb)
        if parse_trigger(k, re.sub(r"^[a-z][\w' ]* — ", "", (pre + ", draw a card.").lower())) and len(k.trig) == n0 + 1 and len(k.etb) == e0:
            opts = [("opt", parse_fx(b if b.endswith(".") else b + ".")[0]) for b in chosen]
            k.trig[-1] = k.trig[-1][:2] + ([o for o in opts if o[1]],) + k.trig[-1][3:]
            return True
        del k.trig[n0:]; del k.etb[e0:]
    return parse_trigger(k, lo)

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
    k.ppips = [frozenset(p for p in s.upper().split("/") if p in COLORS) or frozenset(COLORS)
               for s in SYM.findall(face.get("mana_cost") or c.get("mana_cost") or "") if "P" in s.upper().split("/")]
    k.colors = frozenset(face.get("colors") or c.get("colors") or [])
    pw = face.get("power") or c.get("power")
    k.power = int(pw) if pw and str(pw).isdigit() else 0
    tg = face.get("toughness") or c.get("toughness")
    k.tough = int(tg) if tg and str(tg).isdigit() else 0
    star = "*" in str(pw or "") + str(tg or "")
    kws = [w.lower() for w in (c.get("keywords") or [])]
    k.haste, k.rebound = "haste" in kws, "rebound" in kws
    loy = face.get("loyalty") or c.get("loyalty")
    k.loyalty = int(loy) if loy and str(loy).isdigit() else 0
    text = tildify(strip_reminder(face.get("oracle_text") or c.get("oracle_text") or ""),
                   [c["name"], face.get("name", ""), c["name"].split(",")[0].split(" // ")[0],
                    c["name"].split(" the ")[0] if "Legendary" in (face.get("type_line") or c.get("type_line", "")) and "," not in c["name"] else "",
                    c["name"].split(" of ")[0] if "Legendary" in (face.get("type_line") or c.get("type_line", "")) and "," not in c["name"]
                    and " " in c["name"].split(" of ")[0] else ""])   # two words at least: never a bare 'Lord'/'Master'    # "Thrakkus the Butcher" -> "Thrakkus"
    text = chosen_text(text)
    k.raw = c
    k.life_per_mv = bool(re.search(r"lose life equal to (?:its|that card's) mana value", text.lower()))
    read_life_costs(k, text.lower())
    saved = dict(_CTX); _CTX.update(raw=c, text=text)
    abil, done, missed, vac = [], 0, 0, 0
    for L in modal_lines([l.strip() for l in text.split("\n")]):
        if missed_part(k): missed += 1                   # the previous line was read with a part left over
        _CTX["left"] = []
        if isinstance(L, tuple):                          # a "choose one —" block, read as the chosen mode(s)
            r = parse_modal(k, L, anyc, abil)
            if r: done += 1
            else: missed += 1; k.notes.append("unmodeled modes: " + " / ".join(b[:30] for b in L[3])[:72]); _CTX["left"] = []
            continue
        if not L: continue
        kl = kw_line(k, L)
        if kl is not None:
            if kl is True: done += 1
            continue
        kw = keyword_line(k, L, c)
        if kw is not None:
            if kw: done += 1
            else: missed += 1; k.notes.append("unmodeled: " + L[:72])
            continue
        am = re.match(r"^as an additional cost to cast (?:this spell|~), sacrifice (a|an|another|two|three) ([^.]+?)\.\s*(.*)$", L.lower() + ("" if L.endswith(".") else "."))
        if am:
            f = fodder_filt(am.group(1), am.group(2)) or ({"land": True, "n": 1} if am.group(1) in ("a", "an") and am.group(2) == "land" else None)
            if f:
                k.addsac = f; done += 1
                rest = L[len(L) - len(am.group(3)):].strip() if am.group(3) else ""
                if rest:
                    r = parse_line(k, rest, anyc, abil)
                    if r is True: done += 1
                    elif r is False: missed += 1; k.notes.append("unmodeled: " + rest[:72])
                continue
        if re.fullmatch(r"~ doesn't untap during your untap step\.?", L.lower()):
            k.no_untap = True; done += 1; continue
        if re.fullmatch(r"if you control a commander, you may cast ~ without paying its mana cost\.?", L.lower()):
            k.free_cmdr = True; done += 1; continue
        r = parse_line(k, L, anyc, abil)
        if r is True: done += 1
        elif r is False:
            _CTX["left"] = []                              # an unread line is a miss already
            kp = kw_parts(L, kws)
            if kp is not None:                             # keyword line (Ward {2}, Kicker {1}{B}, Sunburst...)
                unread = [w for w in kp if not KW_SILENT.fullmatch(w) and w not in KW_READ]
                if any(w.endswith("walk") for w in kp): k.notes.append("landwalk not read (blocks it as normal)")
                if any(w in KW_READ for w in kp): done += 1
                if unread: missed += 1; k.notes.append("keyword not modeled: " + ", ".join(unread))
                continue
            missed += 1
            if OPP_LINE.search(L.lower()) and not SELF_GAIN.search(L.lower()): vac += 1; k.notes.append("needs opponents: " + L[:72])
            else: k.notes.append("unmodeled: " + L[:72])
    if missed_part(k): missed += 1
    _CTX["left"] = None
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
    if "sunburst" in kws and not k.ctr_enter:          # a counter per color of mana spent: +1/+1 on a creature, else charge
        k.ctr_enter = ("+1/+1" if "Creature" in k.types else "charge", ("converge",), False)
    if "cascade" in kws:                                # each instance triggers (Maelstrom Wanderer: cascade, cascade)
        k.castfx.append(("cascade", k.mv, max(1, len(re.findall(r"(?:^|\n|, )cascade\b", text.lower())))))
    if "Creature" in k.types or k.kw:                # keyword triggers, read as ordinary triggers
        if "prowess" in k.kw: k.trig.append(("cast", parse_filter("noncreature"), [("pump", "self", 1, 1, frozenset())], False, False, False))
        if "battle cry" in k.kw: k.trig.append(("attack_self", None, [("pump", "others_attacking", 1, 0, frozenset())], False, False, False))
    if star and not k.dyn_pt and "Creature" in k.types:
        k.pt_unread = True; k.notes.append("* power/toughness not read (counted 0)")
    if star and not (k.dyn_pt and k.dyn_pt[0] == "both"): k.tough_known = False
    if k.types & {"Instant", "Sorcery"} and any(e[0] in ("pump", "pump_team", "extra_combat", "biorhythm", "noblock", "unblock") for e in flat(k.spell)) \
            or any(e[0] == "pump_team" for e in k.etb):
        k.alpha = True
    lt = re.sub(r'"[^"]*"', '""', text.lower())          # granted abilities in quotes aren't the card's own interaction
    if k.types & {"Instant", "Sorcery"}:
        k.ritual = bool(k.spell) and all(e[0] in ("mana", "mana_n") for e in k.spell)
        k.hold = bool(RX_INTERACT.search(re.sub(FACE_ONLY, "", lt))) and not k.ritual
    if "Instant" in k.types or "flash" in kws:
        if re.search(r"counter target [^.]*?spell\b", lt): k.answer = "counter"
        elif re.search(r"phases? out|(?:creatures|permanents) you control gain [^.]*?(?:hexproof|indestructible|protection|shroud)"
                       r"|(?:you and )?permanents you control gain|target (?:creature|permanent) you control gains? [^.]*?"
                       r"(?:hexproof|indestructible|protection|shroud)"
                       r"|target (?:creature|permanent|artifact|enchantment)(?: or \w+)? gains? (?:hexproof|indestructible|protection|shroud)"
                       r"|it also gains [^.]*?(?:hexproof|indestructible)", lt): k.answer = "protect"
        elif "choose new targets for target spell" in lt: k.answer = "redirect"
        if k.answer and "Creature" not in k.types: k.hold = True
    if k.hold and not k.answer: k.kill = kill_types(lt)
    if k.hold:                                             # held text isn't a miss: answers answer disruption; symmetric wipes stay held
        rx = {"counter": r"^counter target", "protect": r"phase out|gains? [^.]*?(?:hexproof|indestructible|protection|shroud)",
              "redirect": r"choose new targets"}.get(k.answer)
        keep = []
        for n_ in k.notes:
            body = n_.split(": ", 1)[1].lower() if n_.startswith(("unmodeled: ", "unread part: ")) else ""
            if body and rx and re.search(rx, body): continue
            if body and n_.startswith("unread part: ") and RX_INTERACT.search(body): continue   # held: kill_types reads it
            if body and re.match(r"(?:~ deals \w+ damage to each creature|destroy all (?:other )?(?:creatures|nonland permanents|permanents)"
                                 r"|exile all (?:other )?(?:creatures|nonland permanents)|all creatures get -|each creature gets? -)", body):
                keep.append("held wipe (symmetric, never cast): " + n_[11:]); continue
            keep.append(n_)
        k.notes = keep
    if any(e[0] == "kill_blk" for e in k.spell): k.kill = k.kill | {"creature"}      # incl. one-sided wipes (Plague Wind)
    bm = re.search(r"deals (\d+) damage to any (?:other )?target", lt)
    if k.hold and bm and int(bm.group(1)) > 0 and not any(e[0] == "kill_blk" for e in k.spell):
        k.burn_blk = ("kill_blk", "dmg", 1, int(bm.group(1)), {"non": frozenset(), "need": frozenset(), "cmp": ()}, False, False)
    if "Aura" in k.subtypes and re.search(r"enchanted creature (?:can't attack|can't block|loses all|doesn't untap|has base power|gets -\d)"
                                         r"|enchanted creature is an? [^.]*?with base power", lt):
        k.debuff = True                                   # removal Aura: cast on an opponent's creature, never on yours
    _CTX.update(saved)
    for a in k.hand_acts:
        if a["kind"] != "transmute": a["fx"] = a["fx"] + k.cycle_fx
    allfx = k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f]
    k.trig = [t for t in k.trig if t[2]]                   # a trigger whose effect didn't parse does nothing (and isn't 'read')
    k.recur_fx = [e for e in allfx if e[0] == "recur"]
    k.addsac_bf = bool(k.addsac) and any(e[0] in ("tutor", "recur") and e[2] in ("bf", "bf_t") for e in k.spell)
    k.gain_untap = any(t[0] == "end" and any(e[0] == "cond" and e[1] == "gained" and any(x[0] == "untap_self" for x in e[2])
                                             for e in t[2]) for t in k.trig)
    k.haste = k.haste or "haste" in k.kw
    if k.types & {"Instant", "Sorcery"} and k.spell:
        rec = [e for e in flat(k.spell) if e[0] == "recur"]
        if rec and not k.requires: k.requires, k.gy_need = "gy", rec[0][1]
        if all(e[0] == "tutor" and e[2] == "graveyard" for e in k.spell): k.requires = "gy_payoff"
    categorize(k)
    if any(e[0] == "oracle" for e in k.etb): k.requires = "oracle"
    k.status = "blank" if missed and not done and not k.units else "partial" if missed > vac else "modeled"   # opponent-only lines can't matter here
    if k.status == "blank" and vac == missed: k.status = "vacuum"
    if k.hold: k.status = "held"
    return k

# Scryfall keywords whose line has no goldfish effect, or is read elsewhere from the keyword list (haste, rebound,
# cumulative upkeep, flash); and ones compile_card models from the list (sunburst, cascade)
KW_SILENT = re.compile(r"enchant|ward|partner|partner with|friends forever|choose a background|doctor's companion|companion|"
                       r"protection|hexproof|shroud|daybound|nightbound|flash|changeling|devoid|split second|haste|rebound|"
                       r"cumulative upkeep|[a-z ]*walk|crew|reconfigure|living weapon")
KW_READ = {"sunburst", "cascade"}

def kw_parts(L, kws):
    """The card's keywords a line is made of ('Kicker {1}{B}', 'Ward—Pay 2 life', 'Islandwalk'), or None when the line
    has anything else (an 'Enchanted creature ...' line is not the enchant keyword)."""
    out = []
    for part in (x.strip() for x in re.split(r"[,;]", L.lower().strip().rstrip(".")) if x.strip()):
        w = next((w for w in sorted(kws, key=len, reverse=True) if re.match(re.escape(w) + r"(?:$|\s|—)", part)), None)
        if w is None or re.search(r"\. |\bwhen|\bwhenever|\bif\b|~", part) or len(part[len(w):].split()) > 6: return None   # 'Threshold — As long as ...': a line
        out.append(w)
    return out or None

def missed_part(k):
    """A line that read with a leftover (see _leftover): note it once; True if it counts as a miss."""
    left = _CTX.get("left")
    if not left: return False
    k.notes.append("unread part: " + left[0][:64]); _CTX["left"] = []
    return True

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
    m = re.match(r"^affinity for (\w+)$", lo)
    if m:
        w = m.group(1)
        key = ("artifacts",) if w == "artifacts" else ("sub", as_subtype(w)) if as_subtype(w) else None
        if not key: return False
        k.self_red = (1, key); return True
    if lo in ("convoke", "improvise"): return False          # tapping creatures/artifacts to pay isn't modeled
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
    for e in fxs: out += [e] + (flat(e[2]) if e[0] == "cond" else flat(e[2] + e[3]) if e[0] == "ifdo" else flat(e[3]) if e[0] == "paid"
                                else flat(e[1]) if e[0] == "opt" else [])
    return out

def all_fx(k):
    return flat(k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f] + [e for a in k.hand_acts for e in a["fx"]])

def categorize(k):
    fxs = flat(k.etb + k.castfx + k.spell + [e for t in k.trig for e in t[2]] + [e for a in k.acts for e in a["fx"]] \
        + [e for _, f in k.pw for e in f])
    kinds = {e[0] for e in fxs}
    k.opp_approx = any(t[0] in ("opp_cast", "opp_draw", "opp_second", "opp_land") or t[4] for t in k.trig) \
        or any(e[0] == "cond" and e[1] == "opp_lands" or e[0] == "biorhythm" or e[0] == "wheel" and e[1] == "max"
               or e[0] == "draw" and e[1] == ("opp_hand",) for e in fxs)
    ramp = (not k.is_land and (k.units or k.cond_units or k.sac_outlets or k.imprint or k.vivid or k.convs or k.untapper)) or kinds & {"land_search", "extra_land", "land_from_hand", "treasure", "reveal_lands"} \
        or any(s[0] in ("lands_any", "lands_any_n", "spend_any", "reduce", "alt", "free", "extra_land",
                                "mana_mult", "mana_add", "cr_mana", "reduce_dyn") for s in k.statics)
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
        perm_ev = ("etb", "attack", "cdmg", "dies", "attack_any", "cdmg_any", "sac")     # permanent filters; cast events take spell filters
        def filt(t):
            if not t.get("filter"): return {"type": "Permanent", "another": False, "power": 0, "sub": set()} if t["on"] in ("etb", "attack", "cdmg", "dies", "sac") else None
            return perm_filt("a", t["filter"].lower()) if t["on"] in perm_ev else parse_filter(t["filter"])
        k.trig = [(t["on"], filt(t), [e for s in t["do"] for e in dsl(s)], t.get("once", False), t.get("tax", False), t.get("each", False))
                  for t in spec["triggers"]]
    if "activated" in spec:
        k.acts = []
        for a in spec["activated"]:
            g, p, _, _ = parse_cost(a.get("cost", ""))
            rm = a.get("remove")
            k.acts.append({"tap": a.get("tap", False), "gen": g, "pips": p, "sac": a.get("sac", False),
                           "rm": (rm.split()[0], int(rm.split()[1])) if rm else None,
                           "fodder": fodder_filt("a", a["fodder"].lower()) if a.get("fodder") else None,   # 'Food', 'artifact or creature'
                           "fx": [e for s in a["do"] for e in dsl(s)]})
    if "pt" in spec: k.power, k.tough = spec["pt"]; k.dyn_pt = None; k.pt_unread = False
    if "keywords" in spec:
        k.kw = {w.lower() for w in spec["keywords"] if not w[-1].isdigit()}
        k.kwn = {w.rsplit(" ", 1)[0].lower(): int(w.rsplit(" ", 1)[1]) for w in spec["keywords"] if w[-1].isdigit()}
        k.haste = "haste" in k.kw
    categorize(k)
    for key in ("hold", "requires", "cat"):
        if key in spec: setattr(k, key, spec[key])
    if "status" in spec: k.status = spec["status"]
    elif not spec.get("skip"): k.status = "modeled"
    if spec.get("note"): k.notes = ["override: " + spec["note"]] + [n for n in k.notes if not n.startswith("unmodeled")]

def dsl(s):
    """Override effect strings: 'draw 2', 'draw permanents', 'scry 2', 'look 3 1', 'prolif 1',
    'treasure 1', 'extra_land 1', 'land basic bf_t 1', 'ctr divinity 1', 'mana WUBRG',
    'tutor DEST TARGET' / 'recur DEST TARGET' (DEST hand/top/bf/graveyard; TARGET in Oracle words), 'mill 3',
    'face 2' (one opponent loses 2) / 'face_each 1', 'life 3' (you gain; negative loses), 'pump 2 0 [self|obj|target] [kw...]',
    'pump_team 1 1 [kw...]' (creatures you control, until end of turn)."""
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
    if t in ("face", "face_each"): return [("face", int(w[1]), "each" if t == "face_each" else "one")]
    if t == "life": return [("life", int(w[1]))]
    if t in ("sylvan", "bob"): return [(t,)]
    if t == "pump": return [("pump", w[3] if len(w) > 3 else "self", int(w[1]), int(w[2]), frozenset(x.replace("_", " ") for x in w[4:]))]
    if t == "pump_team":                   # 'pump_team 1 1 trample' : creatures you control get +1/+1 and gain trample EOT
        f = parse_filter("creature"); f["types"] = {"Creature"}
        return [("pump_team", int(w[1]), int(w[2]), frozenset(x.replace("_", " ") for x in w[3:]), f, False, False)]
    raise ValueError("goldfish override: unknown effect " + repr(s))

# ---------------------------------------------------------------- mana solver
def solve(cands, pips, gen):
    """cands: [(pool index, usable colors, colored_only)]. Colored pips by bipartite
    matching (least flexible unit first), generic from leftovers. -> [indices] or None."""
    if len(pips) + gen > len(cands): return None
    order = sorted(range(len(cands)), key=lambda i: ((cands[i][3] if len(cands[i]) > 3 else 0) >= 10, len(cands[i][1]),
                                                     cands[i][3] if len(cands[i]) > 3 else 0))   # fodder mana (>= 10) last
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

def colors_spent(units):
    """Most distinct colors a set of paying units could have spent (each unit is one mana): converge, sunburst. ~approx:
    the payment was chosen for the pips, not to maximize colors."""
    match = {}
    def aug(c, seen):
        for i, u in enumerate(units):
            if c in u and i not in seen:
                seen.add(i)
                if i not in match or aug(match[i], seen): match[i] = c; return True
        return False
    return sum(1 for c in COLORS if aug(c, set()))

class Perm:
    # pp/pt/tkw: until-end-of-turn pump and keywords; att: the creature this Equipment/Aura is on; dmg: damage marked
    __slots__ = ("k", "tapped", "sick", "ctr", "hand", "once", "pp", "pt", "tkw", "att", "dmg", "imp")
    def __init__(self, k, tapped=False, sick=False, hand=False):
        self.k, self.tapped, self.sick, self.hand, self.ctr, self.once = k, tapped, sick, hand, None, None
        self.pp = self.pt = self.dmg = 0; self.tkw = None; self.att = None; self.imp = None    # imp: Chrome Mox's colors
    def copy(self):
        p = Perm(self.k, self.tapped, self.sick, self.hand)
        p.ctr = dict(self.ctr) if self.ctr else None
        p.once = set(self.once) if self.once else None
        p.pp, p.pt, p.dmg, p.att, p.imp = self.pp, self.pt, self.dmg, self.att, self.imp
        p.tkw = set(self.tkw) if self.tkw else None
        return p

class Statics:
    def __init__(self, perms):
        self.lands_any = False; self.lands_any_n = 0; self.spend_any = False; self.all_colors = False
        self.free = []; self.alts = []; self.reduce = []; self.extra_land = 0; self.prolif = 1
        self.plus = []; self.times = []; self.no_max = False; self.mana_mult = []; self.mana_add = []
        self.reduce_dyn = []    # (filter, dyn key): affinity-style reducers granted to spells (Pearl-Ear)
        self.equip_red = 0      # equip costs {N} less (Strong Back ~approx: on the creature it enchants)
        self.cr_mana = []       # (source Perm, units, permanent filter): creatures gain a mana ability (Cryptolith Rite)
        self.attack_limit = 0   # no more than N creatures can attack each combat (Silent Arbiter; binds you too)
        self.base_pt = []       # (source Perm, power, toughness, other): 'other creatures have base power and toughness 2/2' (Kudo)
        self.anthems = []       # (source Perm, filter, +power, +toughness, keywords, other, attacking only)
        self.type_grants = []   # (source Perm, printed types covered, added types, added subtypes, granted abilities): Ragost
        self.trig_x = []        # (enter / dies / attack / src, filter, source Perm): triggers an additional time (Panharmonicon)
        self.token_mult = []    # (x2 / x3, creature tokens only): Doubling Season, Parallel Lives, Ojer Taq
        self.token_each = 0     # Academy Manufactors: a Clue/Food/Treasure becomes one of each (3^(n-1) of each with n)
        self.thopter_plus = 0   # Stridehangar Automatons: each artifact-token event adds that many Thopters
        self.dmg_mult = 1       # Furnace of Rath / City on Fire: damage multiplier (every modeled source is yours)
        self.events = {t[0] for p in perms for t in p.k.trig}     # trigger events anything on the battlefield listens for
        for p in perms:
            for s in p.k.statics:
                t = s[0]
                if t == "anthem": self.anthems.append((p,) + tuple(s[1:]))
                elif t == "type_grant": self.type_grants.append((p,) + tuple(s[1:]))
                elif t == "token_each": self.token_each += 1
                elif t == "thopter_plus": self.thopter_plus += 1
                elif t == "dmg_mult": self.dmg_mult *= s[1]
                elif t == "lands_any": self.lands_any = True
                elif t == "lands_any_n": self.lands_any_n = min(self.lands_any_n or 99, s[1])
                elif t == "spend_any": self.spend_any = True
                elif t == "all_colors": self.all_colors = True
                elif t == "free": self.free.append((s[1], s[2]))
                elif t == "alt": self.alts.append((s[1], s[2]))
                elif t == "reduce": self.reduce.append((s[1], s[2]))
                elif t == "reduce_dyn": self.reduce_dyn.append((s[1], s[2]))
                elif t == "equip_red": self.equip_red += s[1]
                elif t == "cr_mana": self.cr_mana.append((p, s[1], s[2]))
                elif t == "trig_x": self.trig_x.append((s[1], s[2], p))
                elif t == "attack_limit": self.attack_limit = min(self.attack_limit or 99, s[1])
                elif t == "base_pt": self.base_pt.append((p, s[1], s[2], s[3]))
                elif t == "extra_land": self.extra_land += s[1]
                elif t == "prolif_x2": self.prolif *= 2
                elif t == "ctr_plus": self.plus.append((s[1], s[2]))
                elif t == "ctr_times": self.times.append((s[1], s[2]))
                elif t == "no_max_hand": self.no_max = True
                elif t == "token_mult": self.token_mult.append((s[1], s[2]))
                elif t == "mana_mult": self.mana_mult.append((s[1], s[2]))
                elif t == "mana_add": self.mana_add.append((s[1], s[2]))

OPP_CREATURE, OPP_SPELL = Card("opponent creature spell"), Card("opponent noncreature spell")
OPP_CREATURE.types, OPP_SPELL.types = {"Creature"}, {"Instant"}

# ---------------------------------------------------------------- one game
class Game:
    def __init__(self, sim, hand, lib, rng):
        self.sim, self.hand, self.lib, self.rng = sim, hand, lib, rng
        self.gy, self.lands, self.perms, self.cmd = [], [], [], list(sim.commanders)
        self.tcast = (); self.cmd_casts = Counter(); self.turn = 0; self.phase = 0; self.drops = 0
        self.gained = 0                         # life gained this turn (yours or an opponent's): Ragost's untap
        self.turns_left = 0                     # opponent turns still to come this round (mana held for them: engine_reserve)
        self.ctx_gain = 0; self.gain_depth = 0  # the life a 'whenever you gain life' trigger is about; recursion guard
        self.pool = None; self.convs = []; self.dry = False; self._st = None
        self.extra = 0; self.drawn = len(hand); self.casts = 0; self.spent = 0; self.disc = 0
        self.attr = Counter(); self.first = {}; self.cmd_first = {}; self.rebound = []
        self.exile, self.unearthed = [], []
        self.recur = 0; self.cycled = 0; self.rattr = Counter(); self.tut = Counter(); self.life = START_LIFE
        self.died = 0; self.death = None; self.life_paid = Counter()   # turn your own payments killed you; life paid by kind
        self.events = {}; self.open_pool = []; self.dis = []
        self.ctr_now, self.ctr_held = [], []   # counters live this turn / held for your commander or key cards
        self.stax = []                          # live tax/lock effects: {"kind", "start", "until", "on"}
        self.hits = []; self.cleared = 0        # (turn, board before) for each hit that removed permanents
        self.ctrd = 0                           # your spells countered (still counted in casts/spent)
        # opponents: life, poison, combat damage per commander, turn they died (0 = alive), how, their creatures (blocker
        # dicts) and combat denial ({"code", "until"}); boards come from --blockers (Sim.board_spec)
        self.opps = [{"life": START_LIFE, "poison": 0, "cmd": Counter(), "dead": 0, "how": None, "board": [], "deny": []}
                     for _ in range(OPP_N)]
        self.bspec = sim.board_spec
        self.bstat = Counter()                  # blocks, trades, denial: the report's blockers lines
        self.noblock = False; self.mazed = set()   # 'creatures your opponents control can't block this turn'; Maze of Ith's target
        self.prop_paid = self.taxed_out = 0     # attack tax planned this combat; attackers it priced out
        self.won = 0                            # turn the last opponent died
        self.draw_depth = 0                     # nesting of 'whenever you draw a card' triggers
        self.dmg = 0; self.cdmg = 0             # life lost by opponents (all sources / combat)
        self.dsrc = Counter(); self.trigs = Counter()   # damage by source; trigger fires by (source, kind)
        self.atk_n = 0; self.atk_turns = 0; self.lost = 0   # attackers this turn; turns you attacked; your creatures lost in combat
        self.ctx_obj = None; self.ctx_opp = None      # the creature / defending player a combat trigger is about
        self.ctx_dmg = 0                              # combat damage the creature(s) of a combat damage trigger just dealt
        self.combat_on = False; self.combat_done = False; self.attackers = {}   # attacker Perm -> defending opponent
        self.xcombat = 0; self.xcombats = 0     # additional combats pending this turn / taken this game
        self.pending_untap = []; self.attacked = set()   # untaps waiting for the next combat; creatures that attacked this turn
        self.paid_cols = []; self.converge = 0  # colors of the units that paid for the spell being cast (converge, sunburst)
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
        g.rattr = Counter(); g.tut = Counter(); g.life_paid = Counter()
        g.cmd_casts = Counter(self.cmd_casts); g.first = dict(self.first); g.cmd_first = dict(self.cmd_first)
        g.attr = Counter(); g.pool = None; g.convs = []; g._st = None
        g.rng = self.sim.dry_rng; g.log = None
        g.stax = [dict(e) for e in self.stax]; g.ctr_now, g.ctr_held = self.ctr_now[:], self.ctr_held[:]
        for p in g.perms:
            if p.att is not None: p.att = mp.get(id(p.att))
        g.opps = [dict(o, cmd=Counter(o["cmd"]), board=[dict(b) for b in o["board"]]) for o in self.opps]
        g.dsrc = Counter(); g.trigs = Counter(); g.attackers = {}; g.pending_untap = []; g.attacked = set()
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
        if p.sick and (("Creature" in k.types and not (k.haste or self.st.anthems and "haste" in self.stats(p)[2])) or k.src_sick):
            return False
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
            units = k.units * reps
            if k.imprint: units = [(p.imp, NOC, None, False)] if p.imp else []
            for cu, key, n in k.cond_units:                  # the bigger ability when its condition holds (Mox Opal, Fanatic)
                if len(cu) > len(units) and self.val(key, p, 0) >= n: units = cu
            for u in units: pool.append([u[0], u[1], u[2], u[3], p, False])
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
        for p in self.perms:
            if p.k.untapper and self.usable(p): self.untap_units(p)
        if self.st.cr_mana:
            for p in self.perms:
                if p.k.units or p.k.untapper or not self.is_creature(p) or not self.usable(p): continue
                for src, units, f in self.st.cr_mana:
                    if self.pmatch(f, p, src):
                        self.pool += [[u[0], u[1], u[2], u[3], p, False] for u in units]; break
        self.eager_convs()
        self.sac_units()

    SAC_PRIO = 10            # cands priority of fodder mana: spent after every other source

    def sac_units(self, fodder=None, outlet=None):
        """Mana from sacrifice outlets: one group of units per outlet and eligible fodder (tokens, Food, Treasure, Clues;
        never a real card or the commander). A tapping outlet (Phyrexian Tower) gives one group per turn; its own {T} mana
        and the groups exclude each other (use_unit)."""
        if self.pool is None: return
        outs = [q for q in self.perms + self.lands if q.k.sac_outlets and (outlet is None or q is outlet)]
        for o in outs:
            for fod, units, taps in o.k.sac_outlets:
                if taps and (o.tapped or not self.usable(o) and not o.k.is_land): continue
                for q in ([fodder] if fodder is not None else self.perms):
                    if q is o or q not in self.perms or not self.pmatch(fod, q, o) or self.fodder_cost(q) >= self.FODDER_MAX: continue
                    grp = (id(o), id(fod), id(q))
                    if any(len(u) > 6 and u[6][1] == grp for u in self.pool): continue
                    for u in units: self.pool.append([u[0], u[1], u[2], u[3], o if taps else None, False, (q, grp, o)])

    def untap_units(self, p):
        """'{T}: Untap target land' (Arbor Elf, Voyaging Satyr): p taps to make the best matching land's mana again."""
        n, filt = p.k.untapper
        ok = sorted((q for q in self.lands if land_ok(q.k, filt) or (not filt[0] and not filt[1])),
                    key=lambda q: (len(q.k.units), len(set().union(*(u[0] | u[1] for u in q.k.units)) if q.k.units else 0)), reverse=True)
        for q in ok[:n]:
            for u in q.k.units: self.pool.append([u[0], u[1], u[2], u[3], p, False])

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
            src = u[4]                       # tap would-be attackers last (lands and rocks first); painful sources after painless
            hurt = isinstance(src, Perm) and src.k.pain and not src.tapped
            if hurt and self.life - src.k.pain <= 0: continue
            out.append((i, eff, u[3], (2 if isinstance(src, Perm) and "Creature" in src.k.types and not src.k.is_land else 0)
                        + (1 if hurt and not src.k.pain_col else 0)
                        + (3 if isinstance(src, Perm) and src.k.no_untap else 0)     # Mana Vault: only when nothing else covers it
                        + (self.SAC_PRIO if len(u) > 6 else 0)))                        # sacrificing fodder: the last resort
        return out

    def use_unit(self, i, pool=None, colored=False):
        pool = self.pool if pool is None else pool
        u = pool[i]; u[5] = True
        if len(u) > 6 and pool is self.pool:                 # fodder mana: the whole group is produced, the fodder goes
            q, grp, o = u[6]
            for v in pool:
                if len(v) > 6 and v[6][1] != grp and (v[6][0] is q or (u[4] is not None and v[6][2] is o)): v[5] = True
                if u[4] is not None and v[4] is o and len(v) <= 6: v[5] = True                  # the outlet's own {T} mana
            for v in pool:
                if len(v) > 6 and v[6][1] == grp: v[6] = (None, grp, o)                       # siblings stay, already made
            if q is not None and q in self.perms:
                self.note(f"    {o.k.name}: sacrifice {q.k.name} for mana"); self.leave(q, "is sacrificed for mana", quiet=True, sac=True)
        elif u[4] is not None and u[4].k.sac_outlets and pool is self.pool:
            for v in pool:
                if len(v) > 6 and v[4] is u[4]: v[5] = True    # a tapping outlet tapped for its own mana
        if u[4] is not None:
            src = u[4]
            if isinstance(src, Perm) and src.k.pain and not src.tapped and (colored or not src.k.pain_col) and pool is self.pool:
                self.lose_life(src.k.pain, "mana")
            u[4].tapped = True
            if u[4].k.sac_mana and u[4] in self.perms:
                self.leave(u[4], "is sacrificed for mana", quiet=True, sac=True)

    def pay(self, k, gen, pips, commit=True):
        sel = solve(self.cands(k), pips, gen)
        if sel is None:
            return self.pay_conv(k, gen, pips, commit) if self.convs else False
        if commit:
            self.paid_cols = [self.pool[i][0] | self.pool[i][1] for i in sel]
            for n, i in enumerate(sel): self.use_unit(i, colored=n < len(pips))
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
                sel = solve(self.cands(k), pips, gen)
                self.paid_cols = [self.pool[i][0] | self.pool[i][1] for i in sel]
                for i in sel: self.use_unit(i)
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
        if k.addsac and not self.addsac_pick(k): return []       # no fodder the pilot would give up: can't cast it
        st = self.st
        tax = (2 * self.cmd_casts[k] if zone == "cmd" else 0) + self.spell_tax(k)
        red = sum(n for f, n in st.reduce if spell_ok(k, f)
                  and not (f.get("first") and any(spell_ok(c, dict(f, first=False)) for c in self.tcast)))
        if k.self_red: red += k.self_red[0] * self.val(k.self_red[1], None, 0)
        for f, key in st.reduce_dyn:
            if spell_ok(k, f): red += self.val(key, None, 0)
        if zone == "gy":
            g = k.gycast
            if g["kw"] == "unearth": return [(g["gen"], g["pips"])]          # an ability: no reducers
            gen, pips = (k.gen, k.pips) if g["gen"] is None else (g["gen"], g["pips"])
            return [(max(0, gen - red) + tax, pips)]
        xm = 2 if k.x else 0                          # X spells wait for X >= 2
        if k.addlife and self.life - k.addlife < LIFE_FLOOR: return []
        base = k.pips if not k.ppips or self.life - k.addlife - k.life >= LIFE_FLOOR else k.pips + k.ppips   # Phyrexian: life above the floor, else mana
        opts = [(max(0, k.gen - red) + tax + xm, base)]
        for f, (ag, ap, _, _) in st.alts:
            if spell_ok(k, f): opts.append((max(0, ag - red) + tax, ap))
        if any(spell_ok(k, f) and (zone == "hand" or (not hand_only and zone == "cmd")) for f, hand_only in st.free):
            opts.append((tax, []))
        return sorted(opts, key=lambda o: o[0] + len(o[1]))

    def has(self, req, k=None):
        if req == "land": return bool(self.lands)
        if req == "gy":
            if k is None or k.gy_need is None: return False
            if any(e[0] == "recur" and e[2] == "bf" for e in flat(k.spell + k.etb)): return self.worth_target(k)
            return any(self.sim.tmatch(k.gy_need, c) for c in self.gy)
        if req == "gy_payoff": return self.gy_payoff()
        if req == "spare_land":                               # Mox Diamond: a land beyond this turn's drop
            n = sum(c.is_land for c in self.hand)
            return n >= 2 or (n == 1 and self.drops <= 0)
        if req == "oracle":                                   # Thassa's Oracle: cast only when it wins
            col = next(e[1] for e in k.etb if e[0] == "oracle")
            return self.val(("devotion", col), None, 0) + sum(1 for pip in k.pips if col in pip) >= len(self.lib)
        leg = req.startswith("legendary")
        return any("Creature" in p.k.types and (p.k.legendary or not leg) for p in self.perms)

    def try_cast(self, k, zone):
        if k.requires and not self.has(k.requires, k): return False
        if zone != "hand" and self.stax and self.locked() and not (zone == "gy" and k.gycast["kw"] == "unearth"): return False
        if zone == "gy" and not self.gy_extra_ok(k): return False
        for gen, pips in self.options(k, zone):
            if self.pay(k, gen, pips):
                if zone == "gy": self.gy_extra_pay(k)
                if k.ppips and pips is k.pips: self.lose_life(k.life, "phyrexian")   # the life option (see options)
                self.lose_life(k.addlife, "spell")
                if k.addsac:
                    for q in self.addsac_pick(k) or []:
                        self.note(f"    {k.name}: sacrifice {q.k.name}")
                        if q in self.lands:                           # Harrow: a land goes to the graveyard
                            self.lands.remove(q); self.bury(q.k); self._st = None; self.fire("sac", q); continue
                        self.leave(q, "is sacrificed", quiet=True, sac=True)
                        self.ctx_obj = q                          # 'the sacrificed creature's power' (Fling)
                x = 0
                if k.x:
                    rest = [x_[0] for x_ in self.cands(k) if not x_[2] and x_[3] < self.SAC_PRIO]
                    self.paid_cols += [self.pool[i][0] | self.pool[i][1] for i in rest]
                    for i in rest: self.use_unit(i)
                    x = len(rest) + 2
                self.converge = colors_spent(self.paid_cols)
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
        if k.castfx: self.count_trig(k.name, "cast"); self.do(k.castfx, k, None, x)
        if k.types & PERMANENT:
            self.enter(k, from_hand=(zone == "hand"), x=x)
        else:
            self.do(k.spell, k, None, x)
            if zone == "gy" and k.gycast["exile_after"]: self.exile.append(k)
            else: (self.rebound if k.rebound and zone == "hand" else self.gy).append(k)

    def enter(self, k, from_hand=False, x=0, tapped=False):
        if k.is_land: return self.land_enters(k)
        prev_drops = self.st.extra_land
        if k.mox_diamond:                                  # discard a land instead, or it goes to the graveyard
            ls = [c for c in self.hand if c.is_land]
            if not ls or self.dry: self.gy.append(k); return None
            c = min(ls, key=lambda c: (len(self.colors_of(c) - self.land_colors()), not self.etapped(c)))
            self.hand.remove(c); self.gy.append(c); self.gain(-1, k.name); self.note(f"    {k.name}: discard {c.name}")
        p = Perm(k, tapped=bool(k.etap) or tapped, sick=True, hand=from_hand)
        if k.imprint and not self.dry:                     # Chrome Mox: the least useful colored nonartifact, nonland card
            opts = [c for c in self.hand if not c.is_land and "Artifact" not in c.types and c.colors & self.sim.anyc]
            if opts:
                c = min(opts, key=lambda c: (not (c.colors - self.land_colors()), self.value(c)))   # a color the lands lack first
                self.hand.remove(c); self.exile.append(c); self.gain(-1, k.name); p.imp = frozenset(c.colors) & self.sim.anyc
                self.note(f"    {k.name} imprints {c.name}")
        self.perms.append(p); self._st = None
        for gi in k.groups: self.first.setdefault(gi, self.turn)
        if self.st.extra_land > prev_drops:        # Exploration/Azusa give their drops this turn
            self.drops += self.st.extra_land - prev_drops
        if k.ctr_enter:
            kind, n, if_cast = k.ctr_enter
            if from_hand or not if_cast: self.add_ctr(p, kind, self.val(n, p, x))
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
            if any(q.k.sac_outlets for q in self.perms + self.lands): self.sac_units(fodder=p) if not k.sac_outlets else self.sac_units()
        if "Aura" in k.subtypes and k.requires in ("creature", "legendary creature") and not k.debuff:
            cr = [q for q in self.perms if q is not p and self.is_creature(q) and (k.requires == "creature" or q.k.legendary)]
            neg = bool(k.attach) and any(isinstance(v, int) and v < 0 for v in k.attach[:2])
            if cr and not neg: p.att = max(cr, key=self.attack_value)   # your best attacker; a debuff Aura goes elsewhere
        if k.etb:
            for _ in range(self.trig_reps(p, "etb", p) if self.st.trig_x else 1):       # Panharmonicon doubles ETBs too
                self.count_trig(k.name, "enter")
                self.do(k.etb, k, p, x)
        if k.sac_etb and p in self.perms: self.leave(p, "is sacrificed", quiet=True, sac=True)
        if "Aura" in k.subtypes and k.requires == "gy" and p in self.perms:
            cr = [q for q in self.perms if q is not p and self.is_creature(q)]
            p.att = cr[-1] if cr else None                              # Animate Dead: on the creature it returned
        if "living weapon" in k.kw and p in self.perms:                   # a 0/0 Germ, then attach to it
            germ = self.enter(self.sim.token_card(("token", 1, 0, ("Phyrexian", "Germ"), "", "creature", 0, frozenset(), False)))
            p.att = germ
        self.fire("etb", p)
        self.sba()
        return p

    def sba(self):
        """CR 704.5f: your creature with toughness 0 or less goes to the graveyard (indestructible doesn't help)."""
        for q in [q for q in self.perms if q.k.tough_known and self.is_creature(q)]:
            if q in self.perms and self.stats(q)[1] <= 0: self.leave(q, "dies (toughness 0)")

    def etapped(self, k):
        r = k.etap
        if r is None: return False
        if r[0] == "always": return True
        if r[0] == "fast": return len(self.lands) > 2
        if r[0] == "slow": return len(self.lands) < 2
        if r[0] == "check": return not (self.any_lands() or any(p.k.land_types & r[1] for p in self.lands))
        if r[0] == "reveal": return not any(c.is_land and c.land_types & r[1] for c in self.hand)
        if r[0] == "shock": return self.life - r[1] < LIFE_FLOOR      # pay for untapped while above the floor
        return True

    def land_enters(self, k, force_tapped=False):
        p = Perm(k, tapped=force_tapped or self.etapped(k))
        if k.etap and k.etap[0] == "shock" and not p.tapped: self.lose_life(k.etap[1], "shockland")
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
            if targets and self.life - k.fetch_life > 0:
                if k.fetch_life: self.lose_life(k.fetch_life, "fetchland")
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
                if k.is_land or k.ritual or (k.hold and not sim.cast_hold) or (k.alpha and not self.alpha_ok(k)): continue
                cands.append((sim.prio(k, "hand"), k, "hand"))
            for k in self.cmd: cands.append((sim.prio(k, "cmd"), k, "cmd"))     # commanders are never held for an alpha
            for k in dict.fromkeys(self.gy):
                if k.gycast and not k.ritual and not (k.hold and not sim.cast_hold) and not (k.alpha and not self.alpha_ok(k)):
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
                for e in r.spell: trial += [[u, NOC, None, False, None, False] for u in e[1] * (max(0, self.val(e[2], None, 0)) if e[0] == "mana_n" else 1)]
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

    def activations(self, instant=False):
        """Activated abilities, spending what the main phase left. Card flow (draw, tutor, land search, recursion,
        proliferate), Treasure/token makers, damage or drain to opponents, and life gain when it untaps a
        Ragost-style engine. Passes repeat while something happens (a Food made in one pass feeds a sacrifice in the
        next). instant: an opponent's turn, only the engine plays (damage abilities and the life gain that untaps
        them) from the mana you left open; sorcery-speed abilities and loyalty abilities wait."""
        prolif_useful = any(p.ctr for p in self.perms + self.lands) or any(
            t[0] == "prolif" for p in self.perms for t in p.k.trig)
        reserve = 0 if instant else self.engine_reserve(len(self.alive()))
        used = Counter()
        for _ in range(4):
            did = False
            pairs = [(p, ab) for p in list(self.perms) + list(self.lands) for ab in self.acts_of(p)
                     if not ab.get("combat") and not (instant and ab.get("sorcery"))]              # combat: combat_acts
            pairs.sort(key=lambda t: not (not t[1].get("fodder") and any(e[0] in ("token", "treasure") for e in t[1]["fx"])))
            for p, ab in pairs:                            # fodder makers (Nuka-Cola's Food) before what eats fodder
                key = (id(p), id(ab))
                while used[key] < (1 if (ab["tap"] or ab["sac"]) else 3) and self.try_act(p, ab, instant, reserve, prolif_useful):
                    used[key] += 1; did = True
            if not did or not self.alive(): break
        if instant: return
        for p in list(self.perms):
            k = p.k
            if k.pw and p in self.perms:
                loy = (p.ctr or {}).get("loyalty", 0)
                opts = [(("draw" in {e[0] for e in fx}) * 2 + (cost > 0), cost, fx) for cost, fx in k.pw if loy + cost >= 1]
                if opts:
                    _, cost, fx = max(opts, key=lambda o: (o[0], o[1]))
                    if cost > 0: self.add_ctr(p, "loyalty", cost)
                    else: p.ctr["loyalty"] = loy + cost
                    self.do(fx, k, p)

    CARD_FLOW = frozenset({"draw", "look", "look_f", "tutor", "tutor_multi", "land_search", "treasure"})
    FODDER_MAX = 10          # fodder_cost at or above this is never sacrificed as a cost (unless it wins the game)

    def try_act(self, p, ab, instant, reserve, prolif_useful):
        """Activate ab on p once if it's worth it and payable (mana, tap, counters, life, fodder). True if it was."""
        k, fx = p.k, ab["fx"]
        if p not in self.perms and p not in self.lands: return False
        kinds = {e[0] for e in flat(fx)}
        face = any(e[0] == "face" for e in fx)
        life = "life" in kinds and self.wants_life()
        engine = face or life or (bool(kinds & {"token", "treasure"}) and self.has_engine())
        old = bool(kinds & self.CARD_FLOW) or ("ctr" in kinds and "draw" in kinds) or ("prolif" in kinds and prolif_useful) \
            or any(e[0] == "recur" and any(self.sim.tmatch(e[1], c) for c in self.gy) for e in fx)
        if instant: ok = face or life
        else: ok = old or face or life or "token" in kinds or ("kill_blk" in kinds and not ab["sac"] and self.blk_target_exists(fx)) \
            or (not ab["sac"] and any((e[0] == "ctr_on" and e[2] == "+1/+1") or (e[0] == "ctr" and e[1] == "+1/+1") for e in fx)
                and any(self.is_creature(q) for q in self.perms))           # Steel Overseer, Ozolith: grow the team each turn
        if not ok: return False
        if ab["tap"] and (p.tapped or not self.usable(p) and not k.is_land): return False
        if ab["sac"] and "draw" in kinds and not (len(self.hand) <= 1 and self.turn >= 5): return False
        if ab["sac"] and not old and not k.is_land and self.fodder_cost(p) >= self.FODDER_MAX and not self.lethal(fx, p):
            return False                                   # a granted 'sacrifice this artifact' never eats an engine piece
        if ab["rm"]:
            kind, n = ab["rm"]
            if (p.ctr or {}).get(kind, 0) - n < (1 if kind in ("divinity", "indestructible") else 0): return False
        if ab.get("life") and self.life - ab["life"] < LIFE_FLOOR: return False
        cost = ab["gen"] + len(ab["pips"])
        free = sum(1 for u in self.pool if not u[5])
        if not engine and reserve and free - cost < reserve: return False
        if life and not face and not old:                  # an untap is only worth it with mana left to use it next turn
            own = sum(1 for u in self.pool if not u[5] and u[4] is p) if ab["sac"] else 0     # a Treasure's own mana goes too
            if free - cost - own < self.engine_reserve(1): return False
        picks = []
        if ab.get("fodder"):
            picks = self.pick_fodder(ab["fodder"], p, fx)
            if not picks: return False
        held = [u for u in self.pool if not u[5] and u[4] in picks]      # fodder's own mana isn't spent on the cost
        for u in held: u[5] = True
        if not self.pay(None, ab["gen"], ab["pips"]):
            for u in held: u[5] = False
            return False
        self.lose_life(ab.get("life", 0), "ability")
        if ab["tap"]:
            p.tapped = True
            for u in self.pool:
                if u[4] is p: u[5] = True
        if ab["rm"]: p.ctr[ab["rm"][0]] -= ab["rm"][1]
        if face or picks or life: self.note(f"  activate {k.name}" + (f" (sacrifice {', '.join(q.k.name for q in picks)})" if picks else ""))
        for q in picks: self.leave(q, "is sacrificed", quiet=True, sac=True)
        if ab["sac"]:
            if k.is_land: self.lands.remove(p); self.bury(k); self._st = None; self.fire("sac", p)
            else: self.leave(p, "is sacrificed", quiet=True, sac=True)
        saved = self.ctx_obj
        if picks: self.ctx_obj = picks[0]                 # 'the sacrificed creature's power'
        self.do(fx, k, p)
        self.ctx_obj = saved
        return True

    # ---- types granted by other permanents (Ragost: artifacts are Foods and have its quoted ability)
    def types_of(self, p):
        t = p.k.types
        for _, cov, add_t, _, _ in self.st.type_grants:
            if add_t and t & cov: t = t | add_t
        return t

    def subs_of(self, p):
        s = p.k.subtypes
        for _, cov, _, add_s, _ in self.st.type_grants:
            if add_s and p.k.types & cov: s = s | add_s
        return s

    def acts_of(self, p):
        extra = [a for _, cov, _, _, acts in self.st.type_grants if acts and p.k.types & cov for a in acts]
        return p.k.acts + extra if extra else p.k.acts

    # ---- sacrifice fodder and the life-gain untap engine
    def fodder_cost(self, q):
        """How much the pilot minds sacrificing q (lowest goes first): tokens whose leaving pays off (Munitions), tapped
        Food/Treasure, untapped Food, designed fodder (Prized Statue, Ichor Wellspring: they pay off when they hit the
        graveyard), untapped Treasure, Clue, creature tokens by power; real cards (engines, Equipment in use) cost
        FODDER_MAX or more; a commander is never fodder."""
        k = q.k
        if k in self.sim.commanders: return 999
        cr = self.is_creature(q)
        payoff = any(t[0] in ("gy_self", "leave_self", "dies_self") for t in k.trig)
        if k.token and not cr:
            if payoff: return 0
            if q.tapped: return 1                          # a tapped Food/Treasure can't use its own {T} ability this turn
            if "Food" in k.subtypes: return 2
            if k.sac_mana: return 4
            return 5 if "Clue" in k.subtypes else 3
        if k.token: return 6 + max(0, self.stats(q)[0])
        busy = any(r.att is q for r in self.perms) or q.att in self.perms
        if payoff and not cr and not busy and not (k.acts or k.statics or k.units or len(k.trig) > 1): return 3
        return self.FODDER_MAX + k.mv + (10 if (k.acts or k.statics or k.units or k.trig) else 0) + (20 if busy else 0)

    def face_value(self, fx, p):
        """Damage / life loss an effect list deals to opponents right now (after damage doublers)."""
        n_al, v = len(self.alive()), 0
        for e in fx:
            if e[0] != "face": continue
            n = self.val(e[1], p, 0)
            if isinstance(n, int) and n > 0:
                v += n * (self.st.dmg_mult if len(e) > 3 and e[3] else 1) * (1 if e[2] == "one" else n_al)
        return v

    def lethal(self, fx, p):
        """The effect kills an opponent (one-target damage goes to the one closest to dying)."""
        al = self.alive()
        if not al: return False
        per = max((self.face_value([e], p) // (1 if e[2] == "one" else len(al)) for e in fx if e[0] == "face"), default=0)
        return per > 0 and min(self.opps[i]["life"] for i in al) <= per

    def pick_fodder(self, fod, p, fx):
        """The cheapest permanents that pay 'Sacrifice a Food / another creature / ...', or None. A creature is fodder
        only when the ability is worth three of its attacks (Ragost's 9 damage for a 1/1 Servo) or wins; nothing at
        FODDER_MAX or above unless the ability kills an opponent."""
        win, val = self.lethal(fx, p), self.face_value(fx, p)
        c, pods = [], [e[1] for e in flat(fx) if e[0] == "tutor" and rel_mv(e[1])]
        onto = any(e[0] in ("recur", "tutor") and e[2] in ("bf", "bf_t") for e in flat(fx))   # Victimize: a body for bodies
        for i, q in enumerate(self.perms):
            if q is p or not self.pmatch(fod, q, p): continue
            cost = self.fodder_cost(q)
            if pods:                                       # Birthing Pod: a body with no ongoing ability, up the curve
                if cost < self.FODDER_MAX + 10 and all(self.pod_ok(tg, q) for tg in pods): c.append((-q.k.mv, cost, q))
                continue
            if cost >= 999 or (cost >= self.FODDER_MAX + (4 if onto and self.is_creature(q) else 0) and not win): continue
            if self.is_creature(q) and not win and not onto and max(0, self.stats(q)[0]) > 0 and val < 3 * max(0, self.stats(q)[0]): continue
            c.append((cost, i, q))
        n = fod.get("n", 1)
        return [q for _, _, q in sorted(c, key=lambda t: t[:2])[:n]] if len(c) >= n else None

    def pod_ok(self, tg, q):
        """A card the pod-style search could find if q were sacrificed."""
        op, n = rel_mv(tg); cap = q.k.mv + n
        return any(self.sim.tmatch(tg, c) and (c.mv == cap if op == "=" else c.mv <= cap) for c in self.lib)

    def addsac_pick(self, k):
        """Fodder for a spell's 'sacrifice ... as an additional cost': Treasure, Food, Clues and tokens first, never a real
        card; a spell that puts a creature onto the battlefield (Natural Order) may trade a small plain creature. None if none.
        A land (Harrow, Crop Rotation): a tapped land that makes the fewest colors, never the last one."""
        fod, c = k.addsac, []
        if fod.get("land"):
            if len(self.lands) < 2: return None
            return [min(self.lands, key=lambda q: (not q.tapped, len(set().union(*(u[0] | u[1] for u in q.k.units))) if q.k.units else 0,
                                                    bool(q.k.statics or q.k.acts)))]
        if any(e[0] == "face" and e[1] == ("objpow",) for e in k.spell):  # Fling: the biggest creature, and only when it's lethal
            big = [q for q in self.perms if self.pmatch(fod, q, None) and self.is_creature(q) and q.k not in self.sim.commanders]
            al = self.alive()
            if not big or not al: return None
            q = max(big, key=lambda q: (self.stats(q)[0], -self.fodder_cost(q)))
            return [q] if self.stats(q)[0] >= min(self.opps[i]["life"] for i in al) else None
        pods = [e[1] for e in flat(k.spell) if e[0] == "tutor" and rel_mv(e[1])]
        for i, q in enumerate(self.perms):
            if not self.pmatch(fod, q, None): continue
            cost = self.fodder_cost(q)
            if pods:                                       # Neoform, Eldritch Evolution: see pick_fodder
                if cost < self.FODDER_MAX + 10 and all(self.pod_ok(tg, q) for tg in pods): c.append((-q.k.mv, cost, q))
                continue
            if cost >= self.FODDER_MAX + (4 if k.addsac_bf and self.is_creature(q) else 0): continue
            c.append((cost, i, q))
        n = fod.get("n", 1)
        return [q for _, _, q in sorted(c, key=lambda t: t[:2])[:n]] if len(c) >= n else None

    def fodder_ready(self, ab, p):
        """ab's fodder is on the battlefield, or an untapped permanent can make it (Nuka-Cola's Food)."""
        fod = ab.get("fodder")
        if not fod: return True
        if self.pick_fodder(fod, p, ab["fx"]): return True
        for q in self.perms:
            for a in self.acts_of(q):
                if a is ab or (a["tap"] and (q.tapped or not self.usable(q))) or a.get("fodder") or a["sac"]: continue
                for e in a["fx"]:
                    te = TREASURE_E if e[0] == "treasure" else e if e[0] == "token" else None
                    if te and self.pmatch(fod, Perm(self.sim.token_card(te)), p): return True
        return False

    def has_engine(self):
        return any(q.k.gain_untap for q in self.perms)

    def wants_life(self):
        """Gaining life now untaps something: a tapped Ragost-style engine, no life gained yet this turn, and an opponent
        turn still to come (after the last one your own untap step does it)."""
        return not self.gained and self.turns_left > 0 and any(q.k.gain_untap and q.tapped for q in self.perms)

    def engine_reserve(self, turns):
        """Mana held for a Ragost-style engine's activation on each of `turns` opponent turns: other activations,
        paid triggers and end-of-turn cycling leave it open."""
        r = 0
        for q in self.perms:
            if not q.k.gain_untap: continue
            ab = next((a for a in self.acts_of(q) if a["tap"] and any(e[0] == "face" for e in a["fx"])), None)
            if ab: r += (ab["gen"] + len(ab["pips"])) * turns
        return r

    def lose_life(self, n, why):
        """Life the deck costs itself (costs, pain, its own drains). At 0 you lose; the game ends there."""
        if n <= 0: return
        self.life -= n; self.life_paid[why] += n
        if self.life <= 0 and not self.died and not self.won:
            self.died = self.turn; self.death = "life"; self.note(f"  you die to your own life payments on T{self.turn} ({why})")

    def gain_life(self, n):
        """You gain n life: counted for 'if you gained life this turn', and 'whenever you gain life' triggers fire."""
        if n <= 0: return
        self.life += n; self.gained += n
        if "gain" in self.st.events and self.gain_depth < 3:
            saved = self.ctx_gain; self.ctx_gain = n; self.gain_depth += 1
            self.fire("gain")
            self.ctx_gain = saved; self.gain_depth -= 1

    def dealt(self, p, n, kws=None):
        """Permanent p dealt n damage in one event (combat or not): lifelink, and 'whenever enchanted creature / ~ deals
        damage' triggers (Spirit Loop) with that amount. kws: its keywords as it dealt the damage (it may have died since)."""
        if n <= 0 or not isinstance(p, Perm): return
        if "lifelink" in (kws if kws is not None else self.stats(p)[2] if self.is_creature(p) else ()): self.gain_life(n)
        ev = self.st.events
        if "dmg_att" in ev or "dmg_self" in ev:
            saved = self.ctx_dmg; self.ctx_dmg = n
            self.fire("dmg_att", p); self.fire_one(p, "dmg_self", p)
            self.ctx_dmg = saved

    def win_now(self):
        """'You win the game' (Test of Endurance): every opponent left loses."""
        for i in self.alive(): self.opps[i]["dead"], self.opps[i]["how"] = self.turn, "alternate win"
        if not self.won: self.won = self.turn; self.note(f"  you win the game on T{self.turn}")

    def make_tokens(self, e, n, tapped=False):
        """n tokens of template e, through the token replacements: Academy Manufactor (a Clue, Food or Treasure becomes
        one of each; n Manufactors make 3^(n-1) of each) and Stridehangar Automaton (each artifact-token event also
        makes a 1/1 flying Thopter per Automaton). Returns the new permanents."""
        if not isinstance(n, int) or n <= 0: return []
        st, out = self.st, []
        for mult, cr_only in st.token_mult:                   # applied before Academy Manufactor's one-of-each (you order them)
            if not cr_only or "creature" in e[5]: n *= mult
        batch = [(e, n)]
        if st.token_each and e[5] == "artifact" and e[3] and e[3][0] in ("Clue", "Food", "Treasure"):
            m = n * 3 ** (st.token_each - 1)
            batch = [(CLUE_E, m), (FOOD_E, m), (TREASURE_E, m)]
        if st.thopter_plus and "artifact" in e[5]: batch.append((THOPTER_E, st.thopter_plus))
        for te, cnt in batch:
            tk = self.sim.token_card(te)
            for _ in range(min(cnt, 20)):
                if len(self.perms) >= TOKEN_CAP: self.note("    token cap reached"); return out
                out.append(self.enter(tk, tapped=tapped and te is not THOPTER_E))
        return out

    # ---- effects
    def note(self, msg):
        if self.log is not None and not self.dry: self.log.append(msg)

    def gain(self, n, name):
        self.extra += n; self.attr[name] += n
        self.note(f"    {n:+d} card(s) from {name}")

    def draw(self, n, name=None):
        if self.dry or n <= 0: return
        if n > len(self.lib) and not self.won and not self.died:     # a draw from an empty library
            if any(p.k.labman for p in self.perms): self.note("  draw from an empty library: Laboratory Maniac effect"); self.win_now()
            else: self.died = self.turn; self.death = "decked"; self.note(f"  you draw from an empty library on T{self.turn}: you lose")
        n = min(n, len(self.lib))
        for _ in range(n): self.hand.append(self.lib.pop())
        if name: self.gain(n, name)
        else: self.drawn += n
        if "draw_card" in self.st.events and self.draw_depth < 2:     # 'whenever you draw a card' (depth-capped: no loops)
            self.draw_depth += 1
            try:
                for _ in range(n): self.fire("draw_card")
            finally: self.draw_depth -= 1

    def val(self, v, p, x):
        if isinstance(v, int): return v
        if v == "X": return x
        key = v[0]
        if key == "lands": return len(self.lands)
        if key == "permanents": return len(self.lands) + len(self.perms)
        if key == "creatures": return sum(self.is_creature(q) for q in self.perms)
        if key == "artifacts": return sum("Artifact" in q.k.types for q in self.perms + self.lands)      # artifact lands too
        if key == "enchantments": return sum("Enchantment" in q.k.types for q in self.perms + self.lands)
        if key == "opp_hand": return OPP_HAND
        if key == "power": return max((q.k.power + (q.ctr or {}).get("+1/+1", 0) for q in self.perms if "Creature" in q.k.types
                                       and not (len(v) > 1 and v[1] in q.k.subtypes)), default=0)     # ('power', 'Human'): non-Human
        if key == "colors": return len(self.perm_colors())
        if key == "domain":                            # basic land types among your lands (Prismatic Omen-style: all five)
            if any("lands you control are every basic land type" in ((q.k.raw or {}).get("oracle_text") or "").lower() for q in self.perms): return 5
            return len(frozenset().union(*(q.k.land_types for q in self.lands))) if self.lands else 0
        if key == "gy": return len(self.gy)
        if key == "gy_creature": return sum("Creature" in c.types for c in self.gy)
        if key == "gy_land": return sum(c.is_land for c in self.gy)
        if key == "gy_instsorc": return sum(bool(c.types & {"Instant", "Sorcery"}) for c in self.gy)
        if key == "sub": return sum(v[1] in q.k.subtypes for q in self.perms + self.lands)
        if key == "power_o": return max((self.stats(q)[0] for q in self.perms if q is not p and self.is_creature(q)), default=0)
        if key == "sub_other": return sum(v[1] in q.k.subtypes for q in self.perms + self.lands if q is not p)
        if key == "devotion": return sum(1 for q in self.perms for pip in q.k.pips if pip & set(v[1:]))
        if key == "ctr": return (p.ctr or {}).get(v[1], 0) if isinstance(p, Perm) else 0
        if key == "hand": return len(self.hand)
        if key == "attached":                          # Auras/Equipment on the creature (the one p is attached to, or p itself)
            tgt = p.att if isinstance(p, Perm) and p.att is not None else p
            want = {"aura": ("Aura",), "equip": ("Equipment",), "both": ("Aura", "Equipment")}[v[1]]
            return sum(1 for q in self.perms if q.att is tgt and tgt is not None and any(w in q.k.subtypes for w in want))
        if key == "auras_on_cr": return sum(1 for q in self.perms if "Aura" in q.k.subtypes and q.att in self.perms)
        if key == "atk_share":
            o = self.ctx_obj
            return sum(1 for q in self.attackers if q is not o and q in self.perms and q.k.subtypes & o.k.subtypes) if isinstance(o, Perm) else 0
        if key == "atkpow": return sum(max(0, self.stats(q)[0]) for q in self.attackers if q in self.perms)
        if key == "opps": return len(self.alive())
        if key == "converge": return self.converge
        if key == "life": return self.life
        if key == "pow": return self.stats(p)[0] if isinstance(p, Perm) and p.k.types & {"Creature"} else 0
        if key == "objpow": return self.stats(self.ctx_obj)[0] if isinstance(self.ctx_obj, Perm) else 0
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
                if eot and sum(1 for u in self.pool if not u[5]) - ab["gen"] - len(ab["pips"]) < self.reserve() + self.engine_reserve(self.turns_left): continue
                if not self.pay(None, ab["gen"], ab["pips"]): continue
                self.lose_life(ab.get("life", 0), "cycling")
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
            elif t == "oracle":
                if self.val(("devotion", e[1]), p, 0) >= len(self.lib): self.win_now()
            elif t == "bob":
                if self.dry or not self.lib: continue
                self.draw(1, name); self.lose_life(self.hand[-1].mv, "trigger")
            elif t == "sylvan":
                if self.dry or not self.lib: continue
                n0 = len(self.hand); self.draw(2); self.drawn -= len(self.hand) - n0
                new = sorted(self.hand[n0:], key=self.value)
                keep = 1 if self.life - 4 >= LIFE_FLOOR else 0
                back = new[:len(new) - keep]
                for c in back: self.hand.remove(c)
                self.lib += back                                               # the best of the rest ends on top
                if keep: self.lose_life(4, "trigger"); self.gain(keep, name)
            elif t == "peek":                                  # take the top card if it matches (Herald's Horn)
                if not self.dry and self.lib and spell_ok(self.lib[-1], e[1]):
                    self.hand.append(self.lib.pop()); self.gain(1, name)
            elif t == "arrange":                           # look at the top N, put them back in any order: best on top
                if self.dry: continue
                top = [self.lib.pop() for _ in range(min(e[1], len(self.lib)))]
                self.lib += sorted(top, key=self.value)
            elif t == "look_f":                            # dig for a matching card; the rest go to the bottom
                if self.dry or tutor_unread(e[2]): continue
                top = [self.lib.pop() for _ in range(min(e[1], len(self.lib)))]
                ok = [c for c in top if self.sim.tmatch(e[2], c)]
                if ok:
                    pick = max(ok, key=lambda c: self.tutor_value(c, e[3], self.have())); top.remove(pick)
                    self.note(f"    {name} finds {pick.name} -> {e[3]}")
                    if e[3] == "bf" and pick.is_land: self.land_enters(pick)
                    elif e[3] == "bf" and pick.types & PERMANENT: self.enter(pick)
                    else: self.hand.append(pick); self.gain(1, name)
                self.lib[0:0] = top
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
                lo_, rel = 0, rel_mv(tg)
                if rel:                                         # Birthing Pod: the sacrificed permanent's MV sets the range
                    if not isinstance(self.ctx_obj, Perm): continue
                    xcap = self.ctx_obj.k.mv + rel[1]; lo_ = xcap if rel[0] == "=" else 0
                for _ in range(count):
                    cands = [c for c in self.lib if self.sim.tmatch(tg, c) and c not in picks and (xcap is None or lo_ <= c.mv <= xcap)]
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
                    if k.life_per_mv: self.lose_life(pick.mv, "spell")
                    if dest == "bf":
                        if pick.is_land: self.land_enters(pick)
                        elif pick.types & PERMANENT: self.enter(pick)
                        else: self.gy.append(pick)
                    else: self.hand.append(pick); self.gain(1, name)
            elif t == "cond":
                if self.cond_ok(e[1]): self.do(e[2], k, p, x)
            elif t == "untap_self":
                if isinstance(p, Perm) and p in self.perms and p.tapped:
                    p.tapped = False; self.note(f"    {name} untaps")
            elif t == "win": self.win_now()
            elif t == "life_dmg": self.gain_life(self.ctx_dmg)
            elif t == "life_lost": self.gain_life(getattr(self, "ctx_lost", 0))
            elif t == "pay_x_draw":                             # Well of Lost Dreams: X <= life gained, mana permitting
                if self.pool is None or self.dry: continue
                n = min(self.ctx_gain, sum(1 for u in self.pool if not u[5]) - self.engine_reserve(self.turns_left))
                while n > 0 and not self.pay(None, n, []): n -= 1
                if n > 0: self.draw(n, name)
            elif t == "regrow_self":
                if k in self.gy: self.gy.remove(k); self.hand.append(k); self.note(f"    {name} returns to hand")
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
                if len(e) > 2 and not (self.gy_payoff() and len(self.lib) > n + 10): continue   # 'target player': an opponent
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
                for q in self.make_tokens(e, self.val(e[1], p, x), tapped=bool(e[8])):
                    if e[8] is True and q.k is self.sim.token_card(e):   # 'tapped and attacking': joins the attack, no attack triggers
                        if self.combat_on and self.alive():
                            d = self.ctx_opp if self.ctx_opp in self.alive() else self.focus()
                            self.attackers[q] = d
            elif t == "treasure":                               # Treasures are artifact tokens (Ragost makes them Foods)
                self.make_tokens(TREASURE_E, self.val(e[1], p, x), tapped=len(e) > 2 and e[2])
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
            elif t == "ifdo":                                    # 'you may COST. If you do, EFFECT'
                c = e[1]
                if c[0] == "discard":
                    pool = [h for h in self.hand if not c[2] or spell_ok(h, c[2])]
                    if self.dry or len(pool) < c[1]: self.do(e[3], k, p, x); continue
                    for h in sorted(pool, key=self.value)[:c[1]]: self.hand.remove(h); self.gy.append(h)
                    self.gain(-c[1], name)
                elif c[0] == "sac_self":
                    if not (isinstance(p, Perm) and p in self.perms): self.do(e[3], k, p, x); continue
                    self.leave(p, "is sacrificed", quiet=True, sac=True)
                elif c[0] == "sac":
                    picks = self.pick_fodder(c[1], p, e[2])
                    if not picks: self.do(e[3], k, p, x); continue
                    self.note(f"    {name}: sacrifice {', '.join(q.k.name for q in picks)}")
                    for q in picks: self.leave(q, "is sacrificed", quiet=True, sac=True)
                    saved = self.ctx_obj; self.ctx_obj = picks[0]
                    self.do(e[2], k, p, x); self.ctx_obj = saved; continue
                elif c[0] == "life":
                    if self.life - c[1] < LIFE_FLOOR: self.do(e[3], k, p, x); continue
                    self.lose_life(c[1], "ability")
                self.do(e[2], k, p, x)
            elif t == "opt":                                     # an optional mode: skipped when its life cost would cross the floor
                cost = -sum(x_[1] for x_ in e[1] if x_[0] == "life" and isinstance(x_[1], int) and x_[1] < 0)
                if self.life - cost >= LIFE_FLOOR: self.do(e[1], k, p, x)
            elif t == "paid":
                if all(x_[0] == "untap_self" for x_ in e[3]) and k.units and e[1] + len(e[2]) >= len(k.units): continue   # {4} to untap a {C}{C}{C} rock: never
                if self.pool is not None and sum(1 for u in self.pool if not u[5]) - e[1] - len(e[2]) >= self.engine_reserve(self.turns_left) \
                        and self.pay(None, e[1], e[2]): self.do(e[3], k, p, x)
            elif t == "face":
                n = self.val(e[1], p, x)
                if not isinstance(n, int) or n <= 0 or not self.alive(): continue
                dmg = len(e) > 3 and e[3]
                if dmg: n *= self.st.dmg_mult                    # Furnace of Rath, City on Fire
                if e[2] == "one":
                    tg = [self.ctx_opp if self.ctx_opp in self.alive() else self.focus()]
                else: tg = self.alive()
                for i in tg: self.damage_player(i, n, name)
                self.ctx_lost = n * len(tg)                      # 'you gain life equal to the life lost this way'
                if e[2] == "all": self.lose_life(n, "drain")
                self.note(f"    {name}: {n} to {'each opponent' if len(tg) > 1 else f'opponent {tg[0] + 1}'}")
                if dmg: self.dealt(p, n * (len(tg) + (e[2] == "all")))     # one damage event: lifelink, Spirit Loop
                self.check_deaths("noncombat")
            elif t == "lose":
                n = self.val(e[1], p, x)
                if isinstance(n, int) and n > 0: self.lose_life(n, "spell")
            elif t == "life":
                n = self.val(e[1], p, x)
                if not isinstance(n, int): continue
                if n > 0: self.gain_life(n)
                elif n < 0 and isinstance(e[1], int): self.lose_life(-n, "spell")
            elif t == "pump":
                who = e[1]
                if who == "self": qs = [p]
                elif who == "obj": qs = [self.ctx_obj]
                elif who == "attach": qs = [p.att] if isinstance(p, Perm) else []
                elif who == "others_attacking": qs = [q for q in self.attackers if q is not p]
                elif who == "attackers": qs = list(self.attackers)
                else: qs = [self.best_attacker()]
                for q in qs:
                    if isinstance(q, Perm) and q in self.perms and self.is_creature(q):
                        q.pp += self.amt(e[2], p); q.pt += self.amt(e[3], p)
                        if e[4]: q.tkw = (q.tkw or set()) | set(e[4])
            elif t == "kill_blk":
                if not self.dry: self.kill_blockers(e, name)
            elif t == "noblock":
                if self.dry: continue
                if e[1] in ("all", "ground"): self.noblock = e[1]; self.note(f"    {'opponents' if e[1] == 'all' else 'non-flying'} creatures can't block this turn")
                else:
                    i = self.ctx_opp if (self.combat_on and self.ctx_opp is not None) else self.focus()
                    if i is not None:
                        for b in sorted((b for b in self.opps[i]["board"] if not b.get("nob")), key=lambda b: -(b["p"] + b["t"]))[:e[1]]:
                            b["nob"] = True; self.note(f"    opponent {i + 1}'s {b['name']} can't block this turn")
            elif t == "unblock":
                q = p if e[1] == "self" else self.ctx_obj if e[1] == "obj" else self.best_attacker()
                if isinstance(q, Perm) and q in self.perms: q.tkw = (q.tkw or set()) | {"unblockable"}
            elif t == "pump_team":
                _, dp, dt, kws, f, other, atk = e
                dp, dt = self.amt(dp, p), self.amt(dt, p)
                for q in self.perms:
                    if not self.is_creature(q) or (other and q is p) or (atk and q not in self.attackers) or not spell_ok(q.k, f): continue
                    q.pp += dp; q.pt += dt
                    if kws: q.tkw = (q.tkw or set()) | set(kws)
            elif t == "mana_dmg":                             # 'add that much {G}': the combat damage just dealt
                n = self.ctx_dmg
                if self.pool is not None and n > 0:
                    self.pool += [[e[1] & (self.sim.anyc | CLESS) or e[1], NOC, None, False, None, False] for _ in range(n)]
                    self.note(f"    {name} adds {n} mana")
            elif t == "untap_lands":
                for q in self.lands:
                    if q.tapped:
                        q.tapped = False
                        if self.pool is not None: self.add_units(q)
                self.note(f"    {name} untaps your lands")
            elif t == "mana_n":                                # 'Add {R} for each Goblin on the battlefield'
                n = self.val(e[2], p, x)
                if self.pool is not None and isinstance(n, int) and n > 0:
                    self.pool += [[u & (self.sim.anyc | CLESS) or u, NOC, None, False, None, False] for u in e[1] * n]
            elif t == "mana_x":
                n = self.val(e[1], p, x)
                if self.pool is not None and isinstance(n, int) and n > 0:
                    self.pool += [[self.sim.anyc, NOC, None, False, None, False] for _ in range(n)]
                    self.note(f"    {name} adds {n} mana")
            elif t == "double_pow":
                for q in self.perms:
                    if self.is_creature(q) and (not e[2] or e[2] in q.k.subtypes):
                        pw, tg, _ = self.stats(q)
                        q.pp += max(0, pw)
                        if e[1]: q.pt += max(0, tg)
            elif t == "reveal_lands":
                n = self.val(e[1], p, x)
                if self.dry or not isinstance(n, int) or n <= 0: continue
                top = [self.lib.pop() for _ in range(min(n, len(self.lib)))]
                for c in [c for c in top if c.is_land]: self.land_enters(c, force_tapped=True)
                self.lib[0:0] = [c for c in top if not c.is_land]
                self.note(f"    {name} puts {sum(c.is_land for c in top)} land(s) onto the battlefield")
            elif t == "bounce_self":
                if isinstance(p, Perm) and p in self.perms: self.leave(p, "returns to hand", "hand")
            elif t == "cascade":                                # exile until a nonland card with lesser MV; cast it free
                if self.dry: continue
                for _ in range(e[2]):
                    seen, hit = [], None
                    while self.lib:
                        c = self.lib.pop()
                        if not c.is_land and c.mv < e[1]: hit = c; break
                        seen.append(c)
                    self.rng.shuffle(seen); self.lib[0:0] = seen                 # the rest go to the bottom
                    if hit is None: continue
                    if hit.hold or (hit.requires and not self.has(hit.requires, hit)): self.lib.insert(0, hit); continue
                    self.note(f"    {name} cascades into {hit.name}"); self.gain(1, name)
                    self.hand.append(hit); self.resolve(hit, "hand", 0)
            elif t == "free_top":
                if self.dry: continue
                while self.lib:
                    c = self.lib.pop()
                    if c.is_land: self.exile.append(c); continue
                    self.hand.append(c)
                    if c.mv <= e[1] and not (c.requires and not self.has(c.requires, c)):
                        self.note(f"    {name} casts {c.name} free"); self.resolve(c, "hand", 0)
                    else: self.gain(1, name)
                    break
            elif t == "biorhythm":                               # ~opp: an opponent's creatures ~ what they cast so far
                for i in self.alive(): self.opps[i]["life"] = min(self.opps[i]["life"], self.opp_creatures())
                self.life = sum(1 for q in self.perms if self.is_creature(q))
                self.note(f"    {name}: opponents to {self.opp_creatures()} life, you to {self.life}")
                self.check_deaths("noncombat")
            elif t == "extra_combat":
                self.xcombat += 1; self.note("    an additional combat phase is coming")
            elif t == "untap_cr":
                if self.combat_on or self.combat_done: self.untap_cr(e[1])
                else: self.pending_untap.append(e[1])              # cast before combat: it untaps for the extra combat
            elif t == "ctr_on":
                _, who, kind, n, other = e
                if who == "each": qs = [q for q in self.perms if self.is_creature(q) and not (other and q is p)]
                elif isinstance(who, tuple) and who[0] == "each":
                    f = who[1]                                   # every type named (artifact AND creature), subtype, color, legendary
                    qs = [q for q in self.perms if self.is_creature(q) and not (other and q is p)
                          and set(f["types"]) - {"Creature"} <= q.k.types and (not f.get("sub") or f["sub"] & q.k.subtypes)
                          and (not f.get("colors") or set(f["colors"]) & set(q.k.colors)) and (not f.get("legendary") or q.k.legendary)]
                elif isinstance(who, tuple) and who[0] == "targets":
                    qs = sorted((q for q in self.perms if self.is_creature(q) and not (other and q is p)),
                                key=lambda q: -self.stats(q)[0])[:who[1]]
                elif who == "obj": qs = [self.ctx_obj]
                elif who == "least":                             # a cost on your own creature: the one it hurts least
                    cr = [q for q in self.perms if self.is_creature(q) and not (other and q is p)]
                    nv = self.val(n, p, x)
                    qs = [min(cr, key=lambda q: (self.stats(q)[1] <= (nv if isinstance(nv, int) else 1), self.attack_value(q)))] if cr else []
                else: qs = [self.best_attacker()]
                for q in qs:
                    if isinstance(q, Perm) and q in self.perms: self.add_ctr(q, kind, self.val(n, p, x))
                if kind.startswith("-"): self.sba()

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
            for i in self.alive():                                  # opponents' poison counters too
                if self.opps[i]["poison"]: self.opps[i]["poison"] += 1
            self.check_deaths("poison")
            self.fire("prolif")

    def pmatch(self, filt, obj, p):
        """Permanent filter of an enter / attack / combat damage / dies trigger on p, against permanent obj."""
        if not isinstance(obj, Perm): return False
        if "any" in filt: return any(self.pmatch(f, obj, p) for f in filt["any"])      # 'an artifact or creature'
        tg = self.st.type_grants
        types, subs = (self.types_of(obj), self.subs_of(obj)) if tg else (obj.k.types, obj.k.subtypes)
        if not (filt["type"] == "Permanent" or filt["type"] in types): return False
        if (filt["another"] and obj is p) or obj.k.power < filt["power"]: return False
        if filt.get("commander") and obj.k not in self.sim.commanders: return False
        if (filt.get("sub") and not (filt["sub"] & subs)) or (filt.get("nontoken") and obj.k.token) \
                or (filt.get("token") and not obj.k.token): return False
        if (filt.get("colors") and not (filt["colors"] & set(obj.k.colors))) or (filt.get("legendary") and not obj.k.legendary): return False
        if any(q_ in filt for q_ in PERM_QUALS):             # the qualifiers perm_filt reads (Welcoming Vampire, Windreader Sphinx)
            if filt.get("pow_max") is not None and (self.stats(obj)[0] if self.is_creature(obj) else obj.k.power) > filt["pow_max"]: return False
            if filt.get("kw") and filt["kw"] not in self.stats(obj)[2] and filt["kw"] not in obj.k.kwn: return False
            if filt.get("ctr") and not (obj.ctr and any(v > 0 for kk, v in obj.ctr.items() if filt["ctr"] == "any" or kk == filt["ctr"])): return False
            if filt.get("nonsub") and filt["nonsub"] in subs: return False
            on_it = [r for r in self.perms if r.att is obj]
            if filt.get("equipped") and not any("Equipment" in r.k.subtypes for r in on_it): return False
            if filt.get("enchanted") and not any("Aura" in r.k.subtypes for r in on_it): return False
            if filt.get("modified") and not (on_it or (obj.ctr and any(v > 0 for v in obj.ctr.values()))): return False
            if filt.get("historic") and not (obj.k.legendary or "Artifact" in types or "Saga" in subs): return False
        return True

    def targets_mine(self, k, how, p):
        """Does spell k target a creature you control ('whenever you cast a spell that targets a creature you control',
        heroic 'that targets ~', Pearl-Ear's 'a modified permanent')? Creature Auras, 'target creature' pumps and counters,
        and protection spells do; the Aura/pump goes on your best attacker. ~approx"""
        cr = [q for q in self.perms if self.is_creature(q)]
        if not cr: return False
        aims = ("Aura" in k.subtypes and k.requires in ("creature", "legendary creature") and not k.debuff) or k.answer == "protect" \
            or any(e[0] in ("pump", "ctr_on") and e[1] == "target" for e in k.spell + k.etb)
        if not aims: return False
        tgt = max(cr, key=self.attack_value)
        if how == "self": return tgt is p
        if how == "modified": return bool(tgt.ctr and any(v > 0 for v in tgt.ctr.values())) or any(r.att is tgt for r in self.perms)
        return True

    def cond_ok(self, c):
        """A trigger condition: 'if an opponent controls more lands' (~opp), 'if you gained life this turn', 'if you have N or more life'."""
        if c == "opp_lands": return self.opp_lands() > len(self.lands)
        if c == "gained": return self.gained > 0
        return isinstance(c, tuple) and c[0] == "life" and self.life >= c[1]

    def count_trig(self, name, kind):
        if not self.dry: self.trigs[(name, kind)] += 1

    def fire(self, event, obj=None, each_only=False, opp=None):
        if event not in self.st.events: return
        for p in list(self.perms): self.fire_one(p, event, obj, each_only, opp)

    def fire_one(self, p, event, obj=None, each_only=False, opp=None):
        """p's triggers on event. obj: the spell / permanent / attackers it's about; opp: the defending player."""
        for ev, filt, fx, once, tax, each in p.k.trig:
            if ev != event or (each_only and not each): continue
            if event in ("cast", "opp_cast") and filt and not spell_ok(obj, filt): continue
            if event == "cast" and filt and filt.get("targets") and not self.targets_mine(obj, filt["targets"], p): continue
            if event in ("etb", "attack", "cdmg", "dies", "sac", "blocked"):
                if not self.pmatch(filt, obj, p) or (filt.get("alone") and len(self.attackers) != 1): continue
            elif event in ("attack_self", "cdmg_self", "dies_self", "unblocked_self", "blocked_self", "gy_self", "leave_self", "dmg_self"):
                if obj is not p: continue
            elif event in ("attack_att", "cdmg_att", "dmg_att"):
                if p.att is not obj: continue
            elif event in ("attack_any", "cdmg_any"):
                if filt and not any(self.pmatch(dict(filt, another=False), q, p) for q in obj): continue
            if once:
                if p.once is None: p.once = set()
                if (ev, self.phase) in p.once: continue
                p.once.add((ev, self.phase))
            if tax and self.rng.random() < TAX_PAID: continue
            if len(fx) == 1 and fx[0][0] == "cond" and fx[0][1] != "opp_lands" and not self.cond_ok(fx[0][1]): continue   # intervening 'if'
            for _ in range(self.trig_reps(p, event, obj)):
                self.count_trig(p.k.name, TRIG_KIND.get(event, "other"))
                saved = self.ctx_obj, self.ctx_opp
                if isinstance(obj, Perm): self.ctx_obj = obj
                if opp is not None: self.ctx_opp = opp
                self.do(fx, p.k, p)
                self.ctx_obj, self.ctx_opp = saved

    TRIG_CAUSE = {"enter": ("etb", "landfall"), "dies": ("dies", "dies_self", "dies_att"),
                  "attack": ("attack", "attack_self", "attack_any", "attack_att")}

    def trig_reps(self, p, event, obj):
        """1 + the doublers that apply to p's ability triggered by event about obj (Panharmonicon, Teysa, Roaming Throne)."""
        n = 1
        for kind, f, src in self.st.trig_x:
            if src not in self.perms and src not in self.lands: continue
            if kind == "src": n += bool(self.pmatch(f, p, src))
            elif event in self.TRIG_CAUSE[kind]:
                if not isinstance(obj, Perm): n += kind == "attack"            # 'you attack' (a batch): any attacker counts
                elif f.get("land"): n += obj.k.is_land
                else: n += bool(self.pmatch(f, obj, src))
        return n

    # ---- creatures and opponents
    def is_creature(self, p):
        k = p.k
        if "Creature" not in k.types: return False
        if k.god: return sum(1 for q in self.perms for pip in q.k.pips if pip & k.god[0]) >= k.god[1]
        return True

    def amt(self, v, src):
        """An anthem / pump amount: an int, or ('per', n, dyn key) counted now, or a dyn key."""
        if isinstance(v, int): return v
        if isinstance(v, tuple) and v and v[0] == "per": return v[1] * self.val(v[2], src, 0)
        n = self.val(v, src, 0)
        return n if isinstance(n, int) else 0

    def anthem_on(self, a, p):
        src, f, dp, dt, kws, other, atk = a
        if f.get("self"): return src is p
        if (other and src is p) or (atk and p not in self.attackers): return False
        if f.get("commander") and p.k not in self.sim.commanders: return False
        return spell_ok(p.k, f)

    def stats(self, p):
        """(power, toughness, keywords) of creature p right now: printed or counted base, +1/+1 and -1/-1 counters,
        anthems, Equipment/Auras on it, and until-end-of-turn pumps."""
        k = p.k
        pw, tg = k.power, k.tough
        if k.dyn_pt:
            v = max(0, self.val(k.dyn_pt[1], p, 0) or 0); pw = v
            if k.dyn_pt[0] == "both": tg = v
        for src, bp, bt, other in self.st.base_pt:       # base P/T setters (layer 7b) replace the printed/counted base
            if not (other and src is p): pw, tg = bp, bt
        if p.ctr:
            d = p.ctr.get("+1/+1", 0) - p.ctr.get("-1/-1", 0); pw += d; tg += d
        kws = set(k.kw)
        for a in self.st.anthems:
            if self.anthem_on(a, p): pw += self.amt(a[2], a[0]); tg += self.amt(a[3], a[0]); kws |= a[4]
        for q in self.perms:
            if q.att is p and q.k.attach:
                dp, dt, ak = q.k.attach
                pw += self.amt(dp, q); tg += self.amt(dt, q); kws |= ak
                for cond, cp, ct, ck in q.k.attach_cond:     # 'as long as enchanted creature is green' / 'another Aura is attached'
                    if cond[0] == "color" and cond[1] not in k.colors: continue
                    if cond[0] == "aura2" and not any(r is not q and r.att is p and "Aura" in r.k.subtypes for r in self.perms): continue
                    pw += cp; tg += ct; kws |= ck
        if p.tkw: kws |= p.tkw
        return pw + p.pp, tg + p.pt, kws

    def alive(self): return [i for i, o in enumerate(self.opps) if not o["dead"]]

    @staticmethod
    def left(o):
        """How close an opponent is to dying (1 = untouched): the nearest of life, poison and commander damage."""
        return min(o["life"] / START_LIFE, (POISON_KILL - o["poison"]) / POISON_KILL,
                   min(((CMD_KILL - v) / CMD_KILL for v in o["cmd"].values()), default=1))

    def focus(self):
        """The opponent the pilot is killing: the one closest to dying (ties: lowest seat)."""
        al = self.alive()
        return min(al, key=lambda i: (self.left(self.opps[i]), i)) if al else None

    def damage_player(self, i, n, src, combat=False, infect=False, cmdr=None):
        """Opponent i is dealt n damage (infect: as poison counters). Combat damage from a commander is tallied per
        commander for the 21 rule."""
        o = self.opps[i]
        if o["dead"] or n <= 0: return
        if infect: o["poison"] += n
        else:
            o["life"] -= n; self.dmg += n
            if combat: self.cdmg += n
        if not self.dry: self.dsrc[src] += n
        if cmdr: o["cmd"][cmdr] += n

    def check_deaths(self, why):
        for i in self.alive():
            o = self.opps[i]
            how = "poison" if o["poison"] >= POISON_KILL else "commander damage" if any(v >= CMD_KILL for v in o["cmd"].values()) \
                else why if o["life"] <= 0 else None
            if how:
                o["dead"], o["how"] = self.turn, how
                o["board"], o["deny"] = [], []                 # a player who leaves takes their permanents
                self.note(f"    opponent {i + 1} dies ({how})")
        if not self.alive() and not self.won:
            self.won = self.turn; self.note(f"  all opponents dead on T{self.turn}: game over")

    # ---- combat
    def can_attack(self, p):
        if p.tapped or not self.is_creature(p): return False
        kws = self.stats(p)[2]
        return not (kws & {"defender"}) and not (p.sick and "haste" not in kws)

    def attack_value(self, p):
        """Where the pilot puts Equipment, Auras and 'target creature' pumps: evasive, then combat-damage payoffs,
        then the commander, then power."""
        pw, tg, kws = self.stats(p)
        return (bool(kws & EVASIVE), any(t[0] == "cdmg_self" for t in p.k.trig), p.k in self.sim.commanders, pw, p.k.name)

    def best_attacker(self):
        pool = list(self.attackers) or [p for p in self.perms if self.can_attack(p)] or [p for p in self.perms if self.is_creature(p)]
        return max(pool, key=self.attack_value) if pool else None

    def attack_payoff(self, p):
        return any(t[0] == "attack_self" for t in p.k.trig) or any(
            t[0] in ("attack", "attack_any") for q in self.perms for t in q.k.trig)

    def can_block(self, b, kws, pw, p=None):
        """Blocker dict b can block an attacker with these keywords and power (p: the attacker, for its colors and
        partial evasion)."""
        if b.get("dead") or b.get("tapped") or b.get("nob") or "unblockable" in kws: return False
        bk = b["kw"]
        if self.noblock == "all" or (self.noblock == "ground" and "flying" not in bk): return False
        if "flying" in kws and not bk & {"flying", "reach"}: return False
        if "shadow" in kws and "shadow" not in bk: return False
        if "horsemanship" in kws and "horsemanship" not in bk: return False
        if "fear" in kws and not bk & {"artifact", "black"}: return False
        if "intimidate" in kws and "artifact" not in bk and not (p is not None and {COLOR_WORDS[c] for c in bk if c in COLOR_WORDS} & set(p.k.colors)):
            return False
        if "skulk" in kws and b["p"] > pw: return False
        for r in (p.k.evade if p is not None else ()):
            if (r[0] == "pow_le" and b["p"] <= r[1]) or (r[0] == "pow_ge" and b["p"] >= r[1]) or (r[0] == "gt_pow" and b["p"] > pw) \
                    or (r[0] == "color" and r[1] in bk) or (r[0] == "only" and r[1] not in bk):
                return False
        return True

    @staticmethod
    def hit(pw, kws): return max(0, pw) * (2 if "double strike" in kws else 1)

    def group(self, p, kws):
        """(fewest, most) blockers p can be blocked by: menace 2, 'except by three or more' 3, 'by more than one' 1."""
        need = max(2 if "menace" in kws else 1, max((r[1] for r in p.k.evade if r[0] == "min"), default=1)) if p is not None else 1
        return need, (1 if p is not None and any(r[0] == "max1" for r in p.k.evade) else 99)

    @staticmethod
    def duel(b, pw, tg, kws):
        """Blocker b alone against an attacker -> (b kills it, b survives). First/double strike, deathtouch,
        indestructible, flanking (-1/-1 on a blocker without it) and infect/wither blockers are read."""
        bk, bp, bt = b["kw"], b["p"], b["t"]
        if "flanking" in kws and "flanking" not in bk: bp, bt = bp - 1, bt - 1
        if bt <= 0: return False, False
        a_fs, b_fs = bool(kws & {"first strike", "double strike"}), bool(bk & {"first strike", "double strike"})
        a_one = pw > 0 and (pw >= bt or "deathtouch" in kws) and "indestructible" not in bk
        a_all = a_one or ("double strike" in kws and pw > 0 and 2 * pw >= bt and "indestructible" not in bk)
        b_one = bp > 0 and (bp >= tg or "deathtouch" in bk) and "indestructible" not in kws
        b_all = b_one or ("double strike" in bk and bp > 0 and 2 * bp >= tg and "indestructible" not in kws)
        if a_fs and not b_fs and a_one: return False, False        # it dies before it strikes
        if b_fs and not a_fs and b_one: return True, True          # the attacker dies first
        return b_all, not a_all

    def gang(self, can, pw, tg, kws, need):
        """`need` (2+) blockers that stop the attacker without a bad trade: together they kill it losing at most one, or
        none of them dies. The attacker assigns lethal damage in order (1 with deathtouch). None if there's no such set."""
        best = None
        for combo in itertools.combinations(sorted(can, key=lambda b: (-b["p"], -b["t"]))[:6], need):
            kill = "indestructible" not in kws and (sum(max(0, b["p"]) for b in combo) >= tg
                                                    or any("deathtouch" in b["kw"] and b["p"] > 0 for b in combo))
            rem, lost = self.hit(pw, kws), 0
            for b in sorted(combo, key=lambda b: b["t"]):
                d = 1 if "deathtouch" in kws else b["t"]
                if "indestructible" not in b["kw"] and 0 < d <= rem: rem -= d; lost += 1
            if (kill and lost <= 1) or lost == 0:
                key = (kill, -lost, -sum(b.get("mv", 0) for b in combo))
                if best is None or key > best[0]: best = (key, list(combo))
        return best[1] if best else None

    def bad_block(self, p, bl):
        """A predicted block is bad for you: p dies and takes no blocker with it; your commander (unless indestructible)
        isn't traded away at all."""
        pw, tg, kws = self.stats(p)
        bu = p.k.kwn.get("bushido", 0) + p.k.kwn.get("rampage", 0) * max(0, len(bl) - 1)
        pw, tg = pw + bu, tg + bu
        cmd = p.k in self.sim.commanders and "indestructible" not in kws
        if len(bl) == 1:
            kills, lives = self.duel(bl[0], pw, tg, kws)
            return kills and (lives or cmd)
        kill = "indestructible" not in kws and (sum(max(0, b["p"]) for b in bl) >= tg or any("deathtouch" in b["kw"] and b["p"] > 0 for b in bl))
        if not kill: return False
        if cmd: return True
        rem = self.hit(pw, kws)
        for b in sorted(bl, key=lambda b: b["t"]):
            d = 1 if "deathtouch" in kws else b["t"]
            if "indestructible" not in b["kw"] and 0 < d <= rem: return False     # it takes one with it: a trade
        return True

    def clear_blockers(self, ready):
        """Held removal on the one blocker between your attack and killing an opponent (a single-target spell that can
        kill it), else a one-sided wipe when clearing the board gets there. Swords-style life gain counts against it.
        Never cast just to trade: removal stays held for disruption otherwise. True if something was cast."""
        rmfx = lambda c: next((e for e in c.spell if e[0] == "kill_blk"), None) or c.burn_blk
        held = sorted((c for c in dict.fromkeys(self.hand) if c.hold and rmfx(c)), key=lambda c: (c.mv, c.name))
        if not held: return False
        for i in self.alive():
            o = self.opps[i]
            if not o["board"] or self.through(i, ready, o["board"]) >= o["life"]: continue
            for b in sorted(o["board"], key=lambda b: (-(b["p"] + b["t"]), b["name"])):
                for c in held:
                    e = rmfx(c)
                    if e[6] or not can_kill(e, b, o["board"]): continue
                    if self.through(i, ready, o["board"], drop=b) < o["life"] + (max(0, b["p"]) if e[5] else 0): continue
                    if self.cast_held(c, f"opponent {i + 1}'s {b['name']}"):
                        self.remove_blocker(i, b, e, c.name); return True
            for c in held:
                e = rmfx(c)
                if not e[6]: continue
                left = [b for b in o["board"] if not can_kill(e, b, o["board"])]
                if self.through(i, ready, left) >= o["life"] and self.cast_held(c, "every opposing creature it can"):
                    self.kill_blockers(e, c.name); return True
        return False

    def through(self, i, ready, board, drop=None, unblock=None):
        """Damage `ready` attackers ((perm, power, toughness, keywords)) get through if all of them go at opponent i and it
        blocks to survive: each blocker, toughest first, takes the biggest attacker it can; trample carries the excess.
        drop: a blocker to leave out (your removal on it); unblock: an attacker made unblockable."""
        atk = sorted(ready, key=lambda a: -self.hit(a[1], a[3]))
        blocked, total = set(), 0
        for b in sorted((b for b in board if b is not drop and not b.get("dead") and not b.get("tapped")), key=lambda b: -b["t"]):
            for a in atk:
                if id(a) in blocked or a[0] is unblock or not self.can_block(b, a[3], a[1], a[0]) or self.group(a[0], a[3])[0] > 1: continue
                blocked.add(id(a))
                if "trample" in a[3]: total += max(0, self.hit(a[1], a[3]) - b["t"])
                break
        return total + sum(self.hit(a[1], a[3]) for a in atk if id(a) not in blocked)

    def wants_attack(self, p, pw, kws):
        if "must_attack" in kws: return True
        if "vigilance" not in kws and any(a["tap"] and {e[0] for e in a["fx"]} & {"draw", "look", "tutor", "tutor_multi",
                                          "land_search", "treasure", "recur"} for a in p.k.acts):
            return False                                   # keeps its tap ability for card flow
        if "vigilance" not in kws:                         # Ragost: a tap damage ability worth more than its attack, fodder at hand
            free = sum(1 for u in self.pool if not u[5]) if self.pool is not None else 0
            if any(a["tap"] and a["gen"] + len(a["pips"]) <= free and self.face_value(a["fx"], p) >= max(1, pw)
                   and self.fodder_ready(a, p) for a in self.acts_of(p)):
                return False
            if any(a["tap"] and a["gen"] + len(a["pips"]) <= free and not a.get("fodder") and not a["sac"]
                   and sum(max(0, self.val(e[1], p, 0) or 0) * max(1, e[2] if isinstance(e[2], int) else 1)
                           for e in a["fx"] if e[0] == "token" and "creature" in e[5]) >= max(2, pw)
                   for a in self.acts_of(p)):
                return False                               # Krenko: X Goblins beat his own attack
        return pw > 0 or self.attack_payoff(p)

    def assign(self, atk):
        """Defending player per attacker: an opponent this attacker finishes off, else the one closest to dying (focus
        fire; a player already dead on paper isn't hit again while another is alive). Against boards, the pilot reads
        the defenders' own block policy (plan_blocks) on the whole attack: an attacker that would be blocked badly
        there (bad_block) is sent at another opponent, or held back when every opponent would. Blockers run out: a
        wide attack gets its extra attackers through. Attack tax is paid from the mana left after main phase 1."""
        banned = {a[0]: set() for a in atk}
        boards = any(self.opps[i]["board"] for i in self.alive())
        for _ in range(12):
            out = self.targets(atk, banned)
            if not boards: return out
            changed = False
            for i in set(out.values()):
                pb = self.plan_blocks(i, [p for p in out if out[p] == i])
                for p, bl in pb.items():
                    if self.bad_block(p, bl): banned[p].add(i); changed = True
            if not changed: break
        self.bstat["held_back"] += sum(1 for a in atk if a[0] not in out and banned[a[0]] >= set(self.alive()))
        return out

    def targets(self, atk, banned):
        plan = {i: [o["life"], o["poison"], dict(o["cmd"])] for i, o in enumerate(self.opps) if not o["dead"]}
        def dead(s): return s[0] <= 0 or s[1] >= POISON_KILL or any(v >= CMD_KILL for v in s[2].values())
        tax = {i: 2 * sum(1 for d in self.opps[i]["deny"] if d["code"] == "prop") for i in plan}   # Propaganda: {2} per attacker
        budget = sum(1 for u in self.pool if not u[5]) if (self.pool is not None and any(tax.values())) else 0
        out = {}; self.prop_paid = 0; self.taxed_out = 0
        for p, pw, tg, kws in sorted(atk, key=lambda a: (-a[1], a[0].k.name)):
            ok = [i for i in plan if i not in banned[p]]
            if not ok: continue
            if not [i for i in ok if tax[i] <= budget]: self.taxed_out += 1; continue
            ok = [i for i in ok if tax[i] <= budget]
            live = [i for i in ok if not dead(plan[i])] or ok
            n = max(0, pw) * (2 if "double strike" in kws else 1)
            cm = p.k.name if p.k in self.sim.commanders else None
            inf = "infect" in kws
            pois = (n if inf else 0) + (p.k.kwn.get("toxic", 0) + p.k.kwn.get("poisonous", 0) if n > 0 else 0)
            def kills(s):
                return (not inf and s[0] - n <= 0) or s[1] + pois >= POISON_KILL or (cm and s[2].get(cm, 0) + n >= CMD_KILL)
            kill = [i for i in live if kills(plan[i])]
            tgt = kill[0] if kill else min(live, key=lambda i: (min(plan[i][0] / START_LIFE, (POISON_KILL - plan[i][1]) / POISON_KILL,
                                                                    (CMD_KILL - max(plan[i][2].values(), default=0)) / CMD_KILL), i))
            s = plan[tgt]
            if not inf: s[0] -= n
            s[1] += pois
            if cm: s[2][cm] = s[2].get(cm, 0) + n
            out[p] = tgt; budget -= tax[tgt]; self.prop_paid += tax[tgt]
        return out

    def combat(self):
        """Your combat: beginning-of-combat triggers, attackers and defending players, attack triggers (exalted,
        melee, training, dethrone, battle cry, tokens entering attacking), blocks, first-strike and regular damage
        steps, lifelink, poison, commander damage, combat damage triggers, deaths."""
        self.combat_done = True
        if not self.alive() or self.dry: return
        self.mazed = set()
        self.fire("combat_begin")
        cands = []
        for p in list(self.perms):
            if not self.can_attack(p): continue
            pw, tg, kws = self.stats(p)
            if self.wants_attack(p, pw, kws): cands.append((p, pw, tg, kws))
        n0 = len(cands)
        if self.denial("moat"): cands = [c for c in cands if "flying" in c[3]]                 # Moat: flyers only
        if self.denial("bridge"): cands = [c for c in cands if c[1] <= len(self.hand)]        # Ensnaring Bridge
        lim = self.st.attack_limit
        if self.arbiter(): lim = min(lim or 99, 1)
        if lim and len(cands) > lim:                     # Silent Arbiter: send the hardest hitters
            cands = sorted(cands, key=lambda c: (-max(0, c[1]) * (2 if "double strike" in c[3] else 1), c[0].k.name))[:lim]
        if len(cands) < n0 and (self.denial("moat") or self.denial("bridge") or self.arbiter()):
            self.bstat["deny_stop"] += n0 - len(cands); self.note(f"  denial keeps {n0 - len(cands)} attacker(s) home")
        plan = self.assign(cands) if cands else {}
        self.bstat["deny_stop"] += self.taxed_out; self.taxed_out = 0
        if plan and self.prop_paid:
            if self.pay(None, self.prop_paid, []):
                self.spent += self.prop_paid; self.bstat["prop_paid"] += self.prop_paid
                self.note(f"  pays {self.prop_paid} for the attack tax")
            else:                                        # couldn't pay after all: those attackers stay home
                taxed = {i for i in self.alive() if any(d["code"] == "prop" for d in self.opps[i]["deny"])}
                for p in [p for p, i in plan.items() if i in taxed]: del plan[p]; self.bstat["deny_stop"] += 1
        if not plan: return
        self.attackers = dict(plan); self.combat_on = True; self.atk_turns += 0 if self.attacked else 1; self.attacked |= set(plan)
        for p in plan:
            if "vigilance" not in self.stats(p)[2]:
                p.tapped = True
                for u in self.pool or ():
                    if u[4] is p: u[5] = True
        n_def = len(set(plan.values()))
        ex = sum(max(q.k.kwn.get("exalted", 0), 1 if "exalted" in self.stats(q)[2] else 0) for q in self.perms if self.is_creature(q)) \
            + sum(q.k.kwn.get("exalted", 0) for q in self.perms if not self.is_creature(q))    # each instance: +1/+1 attacking alone
        if ex and len(plan) == 1:
            q = next(iter(plan)); q.pp += ex; q.pt += ex; self.count_trig("exalted", "combat")
        for p in plan:
            kws = self.stats(p)[2]
            if "melee" in kws: p.pp += n_def; p.pt += n_def; self.count_trig(p.k.name, "combat")
            if "training" in kws and any(self.stats(q)[0] > self.stats(p)[0] for q in plan if q is not p):
                self.add_ctr(p, "+1/+1", 1); self.count_trig(p.k.name, "combat")
            if "dethrone" in kws and self.opps[plan[p]]["life"] >= max(self.opps[i]["life"] for i in self.alive()):
                self.add_ctr(p, "+1/+1", 1); self.count_trig(p.k.name, "combat")
        if self.log is not None:
            self.note("  attack: " + "; ".join(f"{p.k.name} {self.stats(p)[0]}/{self.stats(p)[1]} -> opp {i + 1}"
                                               for p, i in self.attackers.items() if p in self.perms))
        self.fire("attack_any", list(plan), opp=self.focus())
        for p, i in list(plan.items()):
            self.fire("attack_self", p, opp=i); self.fire("attack", p, opp=i); self.fire("attack_att", p, opp=i)
        if not self.alive() or self.tricks():            # the attack triggers finished the table / a fog or Settle
            self.atk_n = max(self.atk_n, len(self.attackers)); self.combat_on = False; self.attackers = {}; return
        self.maze()
        blocks = self.declare_blocks()
        self.block_triggers(blocks)
        for p, i in list(self.attackers.items()):
            if p not in blocks and p in self.perms and p not in self.mazed: self.fire_one(p, "unblocked_self", p, opp=i)
        fighters = [self.stats(p)[2] for p in self.attackers if p in self.perms] + [b["kw"] for bl in blocks.values() for b in bl]
        if any(k_ & {"first strike", "double strike"} for k_ in fighters) and self.alive(): self.damage_step(blocks, True)
        if self.alive(): self.damage_step(blocks, False)
        for p, bl in blocks.items():                     # how each block went
            a_dead, b_dead = p not in self.perms, sum(1 for b in bl if b.get("dead"))
            self.bstat["blocked"] += 1
            self.bstat["trade" if a_dead and b_dead else "bounced" if a_dead else "chump" if b_dead == len(bl) else "stalled"] += 1
        if self.alive(): self.combat_acts()
        self.atk_n = max(self.atk_n, len(self.attackers))
        self.combat_on = False; self.attackers = {}

    def denial(self, code):
        """Live combat denial of this kind: [(seat, entry)] for living opponents."""
        return [(i, d) for i in self.alive() for d in self.opps[i]["deny"] if d["code"] == code]

    def arbiter(self):
        return any(b.get("deny") == "arb" and not b.get("dead") for i in self.alive() for b in self.opps[i]["board"])

    def tricks(self):
        """A defending opponent uses a held fog (the first attack at it from its turn on) or Settle the Wreckage (when
        two or more creatures or a lethal attack come at it). Your held counters can answer. True if combat is over."""
        at = {}
        for p, i in self.attackers.items():
            if p in self.perms: at.setdefault(i, []).append(p)
        for i in sorted(at):
            o = self.opps[i]
            for d in [d for d in o["deny"] if d["code"] in ("fog", "settle")]:
                inc = sum(self.hit(*self.stats(p)[::2]) for p in at[i])
                if d["code"] == "settle" and len(at[i]) < 2 and inc < o["life"]: continue
                o["deny"].remove(d)
                self.note(f"  opponent {i + 1} casts {DENY[d['code']]}")
                if self.try_answer({"kind": d["code"], "backup": False}, self.pool): self.bstat["deny_countered"] += 1; continue
                if d["code"] == "fog":
                    self.bstat["fog"] += 1
                    self.bstat["stopped"] += sum(self.hit(*self.stats(p)[::2]) for p in self.attackers if p in self.perms)
                    return True
                n = 0
                for p in list(self.attackers):
                    if p in self.perms: self.leave(p, "is exiled (Settle the Wreckage)", "exile"); n += 1
                self.bstat["settle"] += 1; self.bstat["settled"] += n
                for _ in range(n):                       # you search for that many basic lands, tapped
                    b = next((c for c in self.lib if c.is_land and c.basic), None)
                    if b is None: break
                    self.lib.remove(b); self.land_enters(b, force_tapped=True)
                self.rng.shuffle(self.lib)
                return True
        return False

    def maze(self):
        """Maze of Ith (once per round): its controller untaps your biggest attacker coming at them (else the biggest
        overall); no combat damage is dealt to or by it."""
        self.mazed = set()
        for i, d in self.denial("maze"):
            if d.get("used") == self.turn: continue
            live = [p for p in self.attackers if p in self.perms and p not in self.mazed]
            if not live: break
            mine = [p for p in live if self.attackers[p] == i] or live
            v = max(mine, key=lambda p: (self.hit(*self.stats(p)[::2]), p.k.name))
            self.mazed.add(v); v.tapped = False; d["used"] = self.turn
            self.bstat["mazed"] += 1; self.bstat["stopped"] += self.hit(*self.stats(v)[::2])
            self.note(f"    opponent {i + 1}'s Maze of Ith untaps {v.k.name}: no combat damage to or from it")

    def plan_blocks(self, i, attackers):
        """How opponent i blocks these attackers (deterministic; the pilot reads it too) from its untapped board. Per
        attacker, biggest first: one blocker that kills it and/or survives it; else a gang block (two that kill it
        losing at most one, or that both survive); else, only when the attack would kill that player, the cheapest
        chump(s). Menace needs two blockers ('except by three or more' three); 'can't be blocked by more than one
        creature' takes one. -> {attacker: [blocker dicts]}"""
        o, blocks = self.opps[i], {}
        board = [b for b in o["board"] if not b.get("dead") and not b.get("tapped")]
        if not board: return blocks
        mine = sorted((p for p in attackers if p in self.perms and p not in self.mazed), key=lambda p: (-self.stats(p)[0], p.k.name))
        incoming = sum(self.hit(*self.stats(p)[::2]) for p in mine)
        for p in mine:
            pw, tg, kws = self.stats(p)
            need, most = self.group(p, kws)
            can = [b for b in board if self.can_block(b, kws, pw, p)]
            if len(can) < need: continue
            bu = p.k.kwn.get("bushido", 0)                 # the defender sees the bushido bonus coming
            duels = {id(b): self.duel(b, pw + bu, tg + bu, kws) for b in can}
            def score(b):
                k_, l_ = duels[id(b)]
                return (5 if k_ else 0) + (8 if l_ else 0) - 0.25 * b.get("mv", 0)
            can.sort(key=score, reverse=True)
            cmd_lethal = p.k in self.sim.commanders and o["cmd"][p.k.name] + self.hit(pw, kws) >= CMD_KILL
            lethal = incoming >= o["life"] or cmd_lethal or ("infect" in kws and o["poison"] + self.hit(pw, kws) >= POISON_KILL)
            chosen = [can[0]] if need == 1 and any(duels[id(can[0])]) else None
            if chosen is None and most >= 2 and len(can) >= max(need, 2):
                chosen = self.gang(can, pw + bu, tg + bu, kws, max(need, 2))
            if chosen is None and lethal:
                chosen = sorted(can, key=lambda b: (b.get("mv", 0), b["p"] + b["t"]))[:need]
            if not chosen: continue
            blocks[p] = chosen
            for b in chosen: board.remove(b)
            dealt = self.hit(pw, kws)
            incoming -= dealt if "trample" not in kws else min(dealt, sum(b["t"] for b in chosen))
        return blocks

    def declare_blocks(self):
        blocks = {}
        for i in self.alive():
            blocks.update(self.plan_blocks(i, [p for p, d in self.attackers.items() if d == i]))
        for p, bl in blocks.items():
            self.note(f"    {p.k.name} is blocked by " + ", ".join(f"{b.get('name', 'a creature')} {b['p']}/{b['t']}" for b in bl))
        return blocks

    def kill_blocker(self, b, why=""):
        b["dead"] = True; self.bstat["blk_killed"] += 1
        for o in self.opps:
            if b in o["board"]: o["board"].remove(b)
        if why: self.note(f"    {b.get('name', 'a blocker')} dies ({why})")

    def block_triggers(self, blocks):
        """Once blockers are declared: bushido, rampage, flanking, afflict and 'whenever ~ becomes blocked'."""
        for p, bl in blocks.items():
            if p not in self.perms: continue
            i, k = self.attackers[p], p.k
            n = k.kwn.get("bushido", 0) + k.kwn.get("rampage", 0) * max(0, len(bl) - 1)
            if n: p.pp += n; p.pt += n; self.count_trig(k.name, "combat")
            if "flanking" in self.stats(p)[2]:
                for b in bl:
                    if "flanking" in b["kw"] or b.get("dead"): continue
                    b.setdefault("orig", (b["p"], b["t"])); b["p"] -= 1; b["t"] -= 1
                    if b["t"] <= 0: self.kill_blocker(b, "flanking")
            if k.kwn.get("afflict"):
                self.damage_player(i, k.kwn["afflict"], k.name); self.count_trig(k.name, "combat")
            self.fire_one(p, "blocked_self", p, opp=i); self.fire("blocked", p, opp=i)
        if blocks: self.check_deaths("noncombat")

    def damage_step(self, blocks, first):
        """One combat damage step (first: first and double strikers only; else everyone without first strike, plus
        double strikers). Blocked attackers assign lethal damage to blockers in order (1 with deathtouch), the rest to
        the last blocker or, with trample, to the player. An attacker whose blockers are all gone deals no damage
        unless it has trample."""
        hits = []                                      # (opponent, attacker, damage, keywords, myriad copy)
        mult, dealt_by, kws_of = self.st.dmg_mult, Counter(), {}   # doublers apply after assignment; keywords as dealt
        def strikes(kws): return bool(kws & {"first strike", "double strike"}) if first else ("first strike" not in kws or "double strike" in kws)
        for p, i in list(self.attackers.items()):
            if p not in self.perms or self.opps[i]["dead"] or p in self.mazed: continue   # left the game / Maze of Ith
            pw, tg, kws = self.stats(p)
            bl = blocks.get(p)
            if bl is not None:
                for b in bl:
                    if not b.get("dead") and strikes(b["kw"]) and b["p"] > 0:
                        if "deathtouch" in b["kw"]: p.dmg += 10**6
                        elif b["kw"] & {"infect", "wither"}: self.add_ctr(p, "-1/-1", b["p"])
                        else: p.dmg += b["p"]
                        if "lifelink" in b["kw"]: self.opps[i]["life"] += b["p"]
            if not strikes(kws) or pw <= 0: continue
            kws_of[p] = kws
            if bl is None:
                hits.append((i, p, pw * mult, kws, False))
                if "myriad" in kws:                   # token copies attack each other opponent (approximation)
                    hits += [(j, p, pw * mult, kws, True) for j in self.alive() if j != i]
                continue
            live = [b for b in bl if not b.get("dead")]
            if not live and "trample" not in kws: self.bstat["stopped"] += pw * mult; continue
            rem = pw
            for b in live:
                need = 1 if "deathtouch" in kws else max(0, b["t"] - b.get("dmg", 0))
                d = rem if (b is live[-1] and "trample" not in kws) else min(rem, need)
                b["dmg"] = b.get("dmg", 0) + d * mult; rem -= d; dealt_by[p] += d * mult
                if "deathtouch" in kws and d > 0: b["dt"] = True
            if rem > 0 and "trample" in kws: hits.append((i, p, rem * mult, kws, False))
            self.bstat["stopped"] += (pw - (rem if "trample" in kws else 0)) * mult
        for bl in blocks.values():                    # blockers die
            for b in bl:
                if not b.get("dead") and (b.get("dmg", 0) >= b["t"] or b.get("dt")) and "indestructible" not in b["kw"]:
                    self.kill_blocker(b)
        for p in list(self.attackers):                # your creatures die
            if p in self.perms:
                pw, tg, kws = self.stats(p)
                if (tg <= 0 or (p.dmg and p.dmg >= tg)) and "indestructible" not in kws:
                    self.lost += 1; self.leave(p, "dies in combat")
        for i, p, n, kws, copy in hits:               # players are dealt damage (simultaneous)
            cm = p.k.name if (p.k in self.sim.commanders and not copy) else None
            self.damage_player(i, n, p.k.name, combat=True, infect="infect" in kws, cmdr=cm)
            dealt_by[p] += n
            tox = p.k.kwn.get("toxic", 0) + p.k.kwn.get("poisonous", 0)
            if tox and not self.opps[i]["dead"]: self.opps[i]["poison"] += tox
        for p, n in dealt_by.items(): self.dealt(p, n, kws_of.get(p))   # each attacker's damage this step: lifelink, Spirit Loop
        if hits and self.log is not None: self.note("    combat damage: " + "; ".join(f"{p.k.name} {n} -> opp {i + 1}" for i, p, n, _, c in hits))
        self.check_deaths("combat")
        for i in dict.fromkeys(h[0] for h in hits):   # combat damage triggers (a creature that died still triggers)
            dealers = list(dict.fromkeys(p for j, p, _, _, c in hits if j == i and not c))
            for p in dealers:
                self.ctx_dmg = sum(n for j, q, n, _, c in hits if j == i and q is p and not c)
                self.fire_one(p, "cdmg_self", p, opp=i)
                self.fire("cdmg", p, opp=i); self.fire("cdmg_att", p, opp=i)
            self.ctx_dmg = sum(n for j, _, n, _, c in hits if j == i and not c)
            if dealers: self.fire("cdmg_any", dealers, opp=i)
            self.ctx_dmg = 0

    def opp_creatures(self):
        """~opp: creatures an opponent controls now = creature spells cast so far (OPP_CREATURE_SHARE of 1 + OPP_SECOND a turn)."""
        return round(OPP_CREATURE_SHARE * (1 + OPP_SECOND) * self.turn)

    def untap_cr(self, scope):
        """Untap all your creatures / those that attacked this turn / the attacking ones."""
        qs = [q for q in self.perms if self.is_creature(q)] if scope == "all" else \
            [q for q in self.attacked if q in self.perms] if scope == "attacked" else [q for q in self.attackers if q in self.perms]
        for q in qs: q.tapped = False

    def combat_acts(self):
        """'Activate only during combat' abilities that give another combat (Najeela): used after damage, once per combat,
        while mana allows and no extra combat is already coming."""
        if self.pool is None or self.xcombat: return
        for p in list(self.perms):
            for ab in p.k.acts:
                if not ab.get("combat") or not any(e[0] == "extra_combat" for e in ab["fx"]): continue
                if ab["tap"] and p.tapped: continue
                if not self.pay(None, ab["gen"], ab["pips"]): continue
                if ab["tap"]: p.tapped = True
                self.spent += ab["gen"] + len(ab["pips"]); self.count_trig(p.k.name, "combat")
                self.note(f"  activate {p.k.name} (paid {ab['gen'] + len(ab['pips'])})")
                self.do(ab["fx"], p.k, p)
                return

    def clamp_step(self):
        """Skullclamp and friends: Equipment with 'whenever equipped creature dies, draw' goes on a creature it kills
        (toughness drops to 0) that the pilot doesn't mind losing (tokens, fodder), again while mana lasts (cap 6)."""
        for _ in range(6):
            q = next((q for q in self.perms if q.k.equip and q.k.attach and any(t[0] == "dies_att" and any(e[0] == "draw" for e in t[2])
                                                                                 for t in q.k.trig)), None)
            if not q: return
            dt = q.k.attach[1]
            vic = [c for c in self.perms if self.is_creature(c) and c.k not in self.sim.commanders and self.stats(c)[1] + dt <= 0
                   and self.fodder_cost(c) < self.FODDER_MAX]
            if not vic: return
            g_, p_ = q.k.equip
            g_ = max(0, g_ - self.st.equip_red)
            if not self.pay(None, g_, p_): return
            v = min(vic, key=self.fodder_cost)
            q.att = v; self.spent += g_ + len(p_)
            self.note(f"  equip {q.k.name} -> {v.k.name} (paid {g_ + len(p_)})")
            self.leave(v, "dies (toughness 0)")

    def equip_step(self):
        """Before combat: put unattached Equipment on the best attacker, paying its equip cost."""
        if self.dry or not self.alive() or self.pool is None: return
        self.clamp_step()
        for q in [q for q in self.perms if q.k.equip and q.k.attach and (q.att is None or q.att not in self.perms)]:
            ready = [p for p in self.perms if self.can_attack(p)]
            if not ready: return
            g_, p_ = q.k.equip
            g_ = max(0, g_ - self.st.equip_red)
            if not self.pay(None, g_, p_): continue
            best = max(ready, key=self.attack_value)
            q.att = best; self.spent += g_ + len(p_)
            self.note(f"  equip {q.k.name} -> {best.k.name} (paid {g_ + len(p_)})")
            if self.stats(best)[1] <= 0: self.leave(best, "dies (toughness 0)")     # CR 704.5f: indestructible doesn't save it

    def alpha_ok(self, k):
        """Cast a pump (Giant Growth, Overrun, Craterhoof) only before combat, when its damage kills an opponent this
        turn or is worth the card: at least 2 x mana value + 2 extra damage."""
        if self.combat_done or not self.alive() or self.dry: return False
        ready = [(p,) + self.stats(p) for p in self.perms if self.can_attack(p)]
        if "Creature" in k.types and k.haste: ready.append((None, k.power, k.tough, set(k.kw)))
        if not ready: return False
        mult = lambda kws: 2 if "double strike" in kws else 1
        f = self.focus()
        board = self.opps[f]["board"] if f is not None else []
        base = self.through(f, ready, board) if board else sum(max(0, pw) * mult(kws) for _, pw, _, kws in ready)
        n_cr = sum(1 for p in self.perms if self.is_creature(p)) + ("Creature" in k.types)
        def amount(v):
            if isinstance(v, int): return v
            if isinstance(v, tuple) and v[0] == "per": return v[1] * (n_cr if v[2] == ("creatures",) else self.val(v[2], None, 0))
            return 0
        bonus = 0
        for e in k.spell + k.etb:
            if e[0] == "pump_team": bonus += sum(amount(e[1]) * mult(kws) for _, _, _, kws in ready)
            elif e[0] == "pump": bonus += amount(e[2]) * max(mult(kws) for _, _, _, kws in ready)
            elif e[0] == "biorhythm":
                al = self.alive(); after = self.opp_creatures() * len(al)
                return bool(ready) and base >= after + len(al) - 1 and sum(self.opps[i]["life"] for i in al) > after
            elif e[0] == "noblock" and board:               # what the blockers were stopping
                bonus += self.through(f, ready, [b for b in board if e[1] == "ground" and "flying" in b["kw"]]) - base if e[1] in ("all", "ground") else \
                    max((self.through(f, ready, board, drop=b) - base for b in board), default=0) * e[1]
            elif e[0] == "unblock" and board:
                bonus += max((self.through(f, ready, board, unblock=a[0]) - base for a in ready if a[0] is not None), default=0)
            elif e[0] == "extra_combat":                          # attack again: all of it with an untap, else vigilance only
                bonus += base if any(x[0] == "untap_cr" for x in k.spell + k.etb) else \
                    sum(max(0, pw) * mult(kws) for _, pw, _, kws in ready if "vigilance" in kws)
        if bonus <= 0: return False
        lowest = self.opps[f]["life"] if board else min(self.opps[i]["life"] for i in self.alive())
        return base < lowest <= base + bonus or bonus >= 2 * k.mv + 2

    # ---- turn structure
    def opponents(self):
        """The other turns of the round: 'each upkeep / end step' triggers, plus the fixed approximations
        for opponent-triggered cards (see OPP_N), one turn per living opponent. No opponent decisions are simulated.
        The mana you left open at the end of your turn is still there: before each end step, an untapped Ragost-style
        engine activates at instant speed (activations(instant=True)), and paid triggers can use it."""
        seats = self.alive()
        for j, i in enumerate(seats):
            if self.opps[i]["dead"]: continue                   # killed earlier this round: no turn
            if not self.alive(): break
            self.phase += 1; self.gained = 0
            self.turns_left = sum(1 for s in seats[j + 1:] if not self.opps[s]["dead"])
            self.pool, self.convs = self.open_pool, []
            self.fire("upkeep", each_only=True)
            self.fire("opp_draw")
            if self.opp_lands() < 8: self.fire("opp_land")
            self.fire("opp_cast", OPP_CREATURE if self.rng.random() < OPP_CREATURE_SHARE else OPP_SPELL)
            if self.rng.random() < OPP_SECOND:
                self.fire("opp_cast", OPP_CREATURE if self.rng.random() < OPP_CREATURE_SHARE else OPP_SPELL)
                self.fire("opp_second")
            if self.opps[i].get("bounced"):                       # bounced blockers are recast on their turn
                self.opps[i]["board"] += self.opps[i]["bounced"]; self.opps[i]["bounced"] = []
            if self.bspec: self.arrive(self.turn + 1, i)       # their creatures and denial for your next combat
            if self.has_engine() and self.alive():
                self.note(f"  opponent {i + 1}'s turn ({sum(1 for u in self.pool if not u[5])} mana open)")
                self.activations(instant=True)
            self.fire("end", each_only=True)
            self.pool = None
        self.open_pool = []; self.turns_left = 0

    def arrive(self, t, i=None):
        """--blockers: what opponent i (every opponent if None) gets for your turn-t combat: creatures onto its board,
        denial into play. Propaganda, Silent Arbiter, Bridge and Moat are cast on their turn, so a held counter with
        mana left open can stop them; fog and Settle are held for your combat (answered there)."""
        for t0, u, seats, it in self.bspec:
            if t0 != t: continue
            for j in (seats if seats is not None else range(OPP_N)):
                if (i is not None and j != i) or self.opps[j]["dead"]: continue
                o, code = self.opps[j], it.get("deny")
                if code in DENY_TYPE and self.pool is not None:
                    self.note(f"  opponent {j + 1} casts {DENY[code]}")
                    if self.try_answer({"kind": code, "backup": False}, self.pool): self.bstat["deny_countered"] += 1; continue
                if code == "arb":
                    o["board"].append({"name": "Silent Arbiter", "p": 1, "t": 5, "kw": frozenset({"artifact"}), "mv": 4, "deny": "arb", "until": u})
                elif code:
                    o["deny"].append({"code": code, "until": u})
                else:
                    o["board"].append({"name": f"{it['p']}/{it['t']}" + "".join(" " + w for w in sorted(it["kw"])), "p": it["p"],
                                       "t": it["t"], "kw": it["kw"], "mv": max(1, (it["p"] + it["t"]) // 2), "until": u})
                self.note(f"  opponent {j + 1} gets {DENY[code] if code else o['board'][-1]['name']}" + (f" (through T{u})" if u else ""))

    def expire(self, t):
        """Start of your turn t: --blockers entries past their last turn leave."""
        for o in self.opps:
            o["board"] = [b for b in o["board"] if not (b.get("until") and b["until"] < t)]
            o["deny"] = [d for d in o["deny"] if not (d.get("until") and d["until"] < t)]

    def ready_attackers(self):
        out = []
        for p in self.perms:
            if not self.can_attack(p): continue
            pw, tg, kws = self.stats(p)
            if self.wants_attack(p, pw, kws): out.append((p, pw, tg, kws))
        return out

    def cast_held(self, c, what):
        """Pay for and cast held removal c (its effect is applied by the caller). True if cast."""
        opts = self.options(c, "hand")
        if not opts or not self.pay(c, *opts[0]): return False
        g_, p_ = opts[0]
        self.hand.remove(c); self.gy.append(c); self.casts += 1; self.spent += g_ + len(p_)
        self.note(f"  {c.name} removes {what}")
        return True

    def cast_removal(self, want, what):
        """Cast the cheapest held removal that can hit a `want` permanent (creature / artifact / enchantment)."""
        for c in sorted((c for c in dict.fromkeys(self.hand) if want in c.kill),
                        key=lambda c: (any(e[0] == "kill_blk" and e[6] for e in c.spell), c.mv, c.name)):   # wipes last
            if self.cast_held(c, what): return c
        return None

    def remove_blocker(self, i, b, e, src):
        """Blocker b leaves opponent i's board: dies, is exiled, or (bounce) comes back on their next turn."""
        o = self.opps[i]
        if b in o["board"]: o["board"].remove(b)
        if e[1] == "bounce": o.setdefault("bounced", []).append(b)
        else: b["dead"] = True
        if e[5]: o["life"] += max(0, b["p"])                 # Swords to Plowshares
        self.bstat["removed_blk"] += 1
        self.note(f"    {src}: opponent {i + 1}'s {b['name']} " + ("bounced" if e[1] == "bounce" else "removed"))

    def blk_pick(self, e):
        """The blocker a player aims removal at: the one whose removal lets the most damage through at the opponent
        you're killing; with none there, the biggest legal one anywhere. (opponent, blocker) or None."""
        f, ready = self.focus(), self.ready_attackers()
        if f is not None:
            board = self.opps[f]["board"]
            legal = [b for b in board if can_kill(e, b, board)]
            if legal:
                base = self.through(f, ready, board) if ready else 0
                return f, max(legal, key=lambda b: ((self.through(f, ready, board, drop=b) - base) if ready else 0,
                                                    b["p"] + b["t"], b["name"]))
        rest = [(i, b) for i in self.alive() for b in self.opps[i]["board"] if can_kill(e, b, self.opps[i]["board"])]
        return max(rest, key=lambda t: (t[1]["p"] + t[1]["t"], t[1]["name"])) if rest else None

    def kill_blockers(self, e, src):
        """Apply a kill_blk effect (ETB/trigger/activated/spell removal) to opponents' --blockers creatures."""
        if not any(self.opps[i]["board"] for i in self.alive()): return
        if e[1] == "edict" or e[6]:
            for i in (self.alive() if e[6] else [self.focus()]):
                if i is None: continue
                board = self.opps[i]["board"]
                for b in [b for b in board if can_kill(e, b, board)][:None if e[1] != "edict" else 1]:
                    self.remove_blocker(i, b, e, src)
            return
        for _ in range(e[2]):
            pick = self.blk_pick(e)
            if not pick: break
            self.remove_blocker(pick[0], pick[1], e, src)

    def blk_target_exists(self, fx):
        return any(e[0] == "kill_blk" and self.blk_pick(e) for e in fx)

    def clear_path(self):
        """Before combat, held removal (the kind that clears stax) goes at what stops your attack: a Silent Arbiter,
        Moat or Ensnaring Bridge holding attackers home, attack tax on the opponent you're killing, or the one blocker
        (not indestructible) between your attack and killing an opponent."""
        for _ in range(3):
            ready = self.ready_attackers()
            if not ready or not any(c.kill for c in self.hand): return
            targets = []
            if len(ready) > 1:
                targets += [("arb", i, b) for i in self.alive() for b in self.opps[i]["board"] if b.get("deny") == "arb"]
            if any("flying" not in a[3] for a in ready): targets += [("moat", i, d) for i, d in self.denial("moat")]
            if any(a[1] > len(self.hand) for a in ready): targets += [("bridge", i, d) for i, d in self.denial("bridge")]
            f = self.focus()
            targets += [("prop", i, d) for i, d in self.denial("prop") if i == f]
            if self.clear_blockers(ready): continue
            for kind, i, x in targets:
                what = f"opponent {i + 1}'s " + (DENY[kind] if kind != "blk" else x["name"])
                if not self.cast_removal(DENY_TYPE.get(kind, "creature"), what): continue
                if kind in ("arb", "blk"): x["dead"] = True; self.opps[i]["board"].remove(x)
                else: self.opps[i]["deny"].remove(x)
                self.bstat["removed_blk" if kind == "blk" else "removed_deny"] += 1
                break
            else:
                return

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

    def leave(self, p, why, dest="gy", quiet=False, sac=False):
        """p leaves the battlefield. To the graveyard, a creature dies (dies triggers fire, the commander's too, before
        it goes to the command zone). Equipment on it stays; Auras on it go to the graveyard. sac: it was sacrificed
        ('whenever you sacrifice a Food' fires; a grant still in play, like Ragost's, still counts). Then its own
        'put into a graveyard from the battlefield' / 'leaves the battlefield' triggers (tokens too)."""
        if p not in self.perms: return
        dies = dest == "gy" and self.is_creature(p)
        self.perms.remove(p); self._st = None
        self.attackers.pop(p, None)
        for pool in (self.pool, self.open_pool):               # its mana goes with it
            for u in pool or ():
                if u[4] is p: u[5] = True
        if p.k in self.sim.commanders: self.cmd.append(p.k)
        elif p.k.token: pass
        else: {"gy": self.gy, "exile": self.exile, "hand": self.hand}[dest].append(p.k)
        if not quiet: self.note(f"    {p.k.name} {why}")
        on_it = [q for q in self.perms if q.att is p]            # Equipment / Auras it wore: their 'equipped creature dies'
        for q in list(self.perms):
            if q.att is p:
                q.att = None
                if "Aura" in q.k.subtypes: self.leave(q, "goes to the graveyard with it")
        if dies:
            self.fire("dies", p); self.fire_one(p, "dies", p); self.fire_one(p, "dies_self", p)
            for q in on_it: self.fire_one(q, "dies_att", p)
        if sac:
            self.fire("sac", p); self.fire_one(p, "sac", p)
        if p.k.trig:
            if dest == "gy": self.fire_one(p, "gy_self", p)
            self.fire_one(p, "leave_self", p)

    def disrupt(self, ev):
        """A disruption event after your turn. Records (kind, 'hit' / 'answered' / 'no target')."""
        kind, cmdrs = ev["kind"], self.sim.commanders
        if kind == "cmd": targets = [p for p in self.perms if p.k in cmdrs]
        elif kind in ("removal", "removal+"):            # nobody spends removal on a Treasure, Food or Clue
            targets = [p for p in self.perms if p.k not in cmdrs and not (p.k.token and not self.is_creature(p))]
        elif kind == "wipe": targets = [p for p in self.perms if "Creature" in p.k.types]
        elif kind == "gy": targets = list(self.gy)
        elif kind == "ld": targets = list(self.lands)
        elif kind in PERSIST: targets = [True]
        elif kind == "nuke+gy": targets = list(self.perms) + list(self.gy)
        else: targets = list(self.perms)                                     # nuke, rift
        if not targets:
            self.dis.append((kind, "no target")); self.wipe_opps(kind); return
        if kind in ("cmd", "removal", "removal+"):                           # targeted: hexproof / shroud can't be chosen
            open_ = [p for p in targets if not (self.is_creature(p) and self.stats(p)[2] & {"hexproof", "shroud"})]
            if not open_:
                self.note(f"  DISRUPTION: {DIS_NAMES[kind]}: no legal target (hexproof/shroud)")
                self.dis.append((kind, "answered")); return
            targets = open_
        self.note(f"  DISRUPTION: {DIS_NAMES[kind]}" + (" (backed up)" if ev.get("backup") else ""))
        ans = self.try_answer(ev, self.open_pool)
        if ans != "counter": self.wipe_opps(kind)             # protection saves only your side
        if ans and not (kind == "nuke+gy" and ans == "protect"):
            self.dis.append((kind, "answered")); return
        self.dis.append((kind, "hit"))
        before = self.board_n()
        r = self.sim.dis_rng
        if kind in ("cmd", "removal"):
            v = max(targets, key=lambda p: (p.k.mv, p.k.name)) if r.random() < 0.5 else r.choice(targets)
            # spot removal destroys; commander removal destroys half the time (Beast Within) and exiles/bounces otherwise (Swords)
            if self.survives(v, kind == "removal" or (self.protected(v) and r.random() < 0.5)):
                self.dis[-1] = (kind, "answered")
            else: self.leave(v, "is removed")
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
        else:                                                                   # wipe, nuke, nuke+gy
            ex = kind == "nuke+gy"
            kept = set() if ex else {id(p) for p in targets if isinstance(p, Perm) and self.survives(p, True)}
            for p in targets:
                if isinstance(p, Perm) and id(p) not in kept and p in self.perms:
                    self.leave(p, "is exiled" if ex else "dies in the wipe", "exile" if ex else "gy")
            if ex: self.exile += self.gy; self.gy = []
        if self.board_n() < before: self.hits.append((self.turn, before))

    def wipe_opps(self, kind):
        """An opponent's wipe hits every board: their creatures die too (indestructible ones stay, except to Farewell),
        and a nonland wipe takes Propaganda, Bridge and Moat. Mass bounce (rift) leaves the caster's board: not modeled."""
        if kind not in ("wipe", "nuke", "nuke+gy"): return
        for o in self.opps:
            o["board"] = [b for b in o["board"] if "indestructible" in b["kw"] and kind != "nuke+gy"]
            if kind != "wipe": o["deny"] = [d for d in o["deny"] if d["code"] not in DENY_TYPE]

    def protected(self, p):
        """p would survive a destroy effect: indestructible, or an Aura with umbra (totem) armor on it."""
        return self.is_creature(p) and ("indestructible" in self.stats(p)[2]
                                        or any(q.att is p and "umbra armor" in q.k.kw for q in self.perms))

    def survives(self, p, destroy):
        """A destroy effect hits p: indestructible ignores it; umbra armor destroys the Aura instead. True if p stays."""
        if not destroy or not self.protected(p): return False
        if "indestructible" in self.stats(p)[2]: self.note(f"    {p.k.name} is indestructible"); return True
        um = next(q for q in self.perms if q.att is p and "umbra armor" in q.k.kw)
        self.leave(um, f"is destroyed instead (umbra armor on {p.k.name})")
        return True

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

    def board_n(self):
        """Board size for the report and the rebuild read: Treasures (mana in the bank, not board) don't count."""
        return sum(1 for p in self.perms if not (p.k.token and p.k.sac_mana and "Creature" not in p.k.types))

    def opp_lands(self):
        return min(self.turn - (1 if self.sim.on_play else 0), 8)

    def play(self, turns, rec):
        sim = self.sim
        for k in [c for c in self.hand if c.leyline]:
            self.hand.remove(k); self.enter(k)
        if self.bspec: self.arrive(1)                      # boards already there for your first combat
        for t in range(1, turns + 1):
            self.turn = t; self.phase += 1; self.tcast = (); self.gained = 0; self.turns_left = len(self.alive())
            if self.bspec: self.expire(t)
            for p in self.lands: p.tapped = False
            for p in self.perms:
                p.sick = False
                if not p.k.no_untap: p.tapped = False            # Mana Vault stays tapped
            self.drops = 1 + self.st.extra_land
            self.combat_done = False; self.atk_n = 0
            for q in [q for q in self.perms if q.k.cum_upkeep]:
                q.ctr = q.ctr or {}; q.ctr["age"] = q.ctr.get("age", 0) + 1
                if q.ctr["age"] > 3: self.leave(q, "is let go (cumulative upkeep)")
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
            self.fire("main1")                                  # 'at the beginning of your first main phase': BMC, Black Market's mana
            pool_n = sum(1 for u in self.pool if not u[5] and len(u) <= 6)     # fodder mana (sac outlets) isn't development
            cols = set().union(*(u[0] | u[1] for u in self.pool if not u[5] and len(u) <= 6)) if self.pool else set()
            if self.st.spend_any and cols - {"C"}: cols |= sim.anyc
            rec["lands"][t].append(len(self.lands)); rec["mana"][t].append(pool_n)
            rec["colors"][t].append(sim.anyc <= cols)
            rec["stranded"][t].append(self.stranded())
            self.note(f"  mana {pool_n} ({''.join(sorted(cols))}) at the start of main")
            self.cast_loop(activate=False)                          # main phase 1: cast everything (nothing to hide)
            self.equip_step()
            if self.bspec and not self.dry: self.clear_path()
            faced = sum(len(self.opps[i]["board"]) for i in self.alive())
            sig = lambda: (len(self.hand), len(self.gy), len(self.cmd), sum(1 for u in self.pool if not u[5]))
            before = sig()
            self.combat()
            n = 0
            while self.xcombat and self.alive() and n < XCOMBAT_CAP:   # additional combat phases, each after a main phase
                self.xcombat -= 1; n += 1; self.xcombats += 1
                for sc in self.pending_untap: self.untap_cr(sc)
                self.pending_untap = []
                self.note("  additional combat phase")
                self.cast_loop(activate=False)
                self.combat()
            self.xcombat = 0; self.pending_untap = []; self.attacked = set()
            after = sig()
            if after[:3] == before[:3] and after[3] <= before[3]: self.activations()   # combat changed nothing castable
            else: self.cast_loop()                                  # main phase 2: what combat drew or made, then activations
            if self.hand_act(): self.cast_loop(activate=False)       # transmute, then cast what it found
            while self.hand_act(eot=True): pass                     # leftover mana: cycle dead cards
            for e in self.ctr_now: self.dis.append((e["kind"], "no target"))
            self.ctr_now = []
            self.open_pool = [u for u in self.pool if not u[5]] if self.pool else []
            self.pool = None; self.convs = []
            self.fire("end")
            for q in self.unearthed:
                if q in self.perms: self.leave(q, "is exiled (unearth)", "exile", quiet=True)
            self.unearthed = []
            for q in self.perms: q.pp = q.pt = q.dmg = 0; q.tkw = None          # cleanup: pumps wear off, damage heals
            self.noblock = False
            for o in self.opps:
                for b in o["board"]:
                    b["dmg"] = 0; b.pop("dt", None); b.pop("nob", None)
                    if "orig" in b: b["p"], b["t"] = b.pop("orig")
            for e in evs:
                if e["kind"] not in ("counter", "counterK") and not self.won: self.disrupt(e)
            if not self.st.no_max and len(self.hand) > 7:
                self.hand.sort(key=self.value)
                n = len(self.hand) - 7
                self.gy += self.hand[:n]; del self.hand[:n]; self.disc += n
            rec["hand"][t].append(len(self.hand)); rec["extra"][t].append(self.extra)
            rec["casts"][t].append(self.casts); rec["spent"][t].append(self.spent)
            rec["disc"][t].append(self.disc)
            rec["gy"][t].append(len(self.gy)); rec["recur"][t].append(self.recur); rec["cycled"][t].append(self.cycled)
            rec["board"][t].append(self.board_n()); rec["oppb"][t].append(faced)
            rec["cmd_out"][t].append(bool(sim.commanders) and all(any(p.k is c for p in self.perms) for c in sim.commanders))
            if not self.won: self.opponents()                  # the rest of the round; combat rows below include it
            self.open_pool = []
            rec["dmg"][t].append(self.dmg); rec["cdmg"][t].append(self.cdmg); rec["atk"][t].append(self.atk_n)
            rec["kills"][t].append(sum(1 for o in self.opps if o["dead"]))
            rec["cmdmax"][t].append(max((v for o in self.opps for v in o["cmd"].values()), default=0))
            rec["poison"][t].append(max(o["poison"] for o in self.opps))
            rec["life"][t].append(self.life)
            if self.log is not None and self.perms: self.note("  board: " + "; ".join(p.k.name + (str(p.ctr) if p.ctr else "") for p in self.perms))
            if self.log is not None and (self.dmg or any(o["poison"] or o["cmd"] for o in self.opps)): self.note("  opponents: " + "; ".join(
                (f"{i + 1}: dead T{o['dead']} ({o['how']})" if o["dead"] else f"{i + 1}: {o['life']} life"
                 + (f", {o['poison']} poison" if o["poison"] else "")
                 + "".join(f", {v} from {c}" for c, v in o["cmd"].items() if v)) for i, o in enumerate(self.opps)))
            if self.won or self.died:                      # the table (or you) is dead: the game ends; later turns repeat this one
                for t2 in range(t + 1, turns + 1):
                    for m in rec: rec[m][t2].append(rec[m][t][-1])
                break
        for e in self.ctr_held: self.dis.append((e["kind"], "no target"))
        self.ctr_held = []

# ---------------------------------------------------------------- simulation
def blank_rec(turns):
    return {m: {t: [] for t in range(1, turns + 1)} for m in
            ("lands", "mana", "colors", "stranded", "hand", "extra", "casts", "spent", "disc", "cmd_out",
             "gy", "recur", "cycled", "board", "dmg", "cdmg", "atk", "kills", "cmdmax", "poison", "life", "oppb")}

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
        self.board_spec = getattr(args, "board_spec", None) or []     # --blockers: [(turn, until, seats, item)]
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
        _, n, pw, subs, text, kind, tg, kws, _ = e
        key = (pw, subs, text, kind, tg, kws)
        k = self.tokens.get(key)
        if k is None:
            tl = {"creature": "Token Creature", "artifact creature": "Token Artifact Creature"}.get(kind, "Token Artifact") \
                + (" — " + " ".join(subs) if subs else "")
            raw = {"name": (" ".join(subs) or "Creature") + " token", "type_line": tl, "oracle_text": text,
                   "power": str(pw if isinstance(pw, int) else 0), "toughness": str(tg if isinstance(tg, int) else 0),
                   "cmc": 0, "colors": [], "mana_cost": ""}
            k = compile_card(raw, self.anyc); k.token = True; k.cat = "token"
            k.tough_known = isinstance(tg, int)                  # an X/X token's X isn't read: never dies of toughness 0
            k.kw |= kws; k.haste = k.haste or "haste" in kws
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
            low = sum(1 for k in hand if not k.is_land and k.mv <= 2)
            return 3 <= lands <= 5 or (lands == 2 and (cheap >= 1 or low >= 3))
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
        last = g.won or g.died or turns                     # a game that killed the table stops there: no dead turns after
        deaths = sorted(o["dead"] for o in g.opps if o["dead"])
        g.final = {"cmd_out": rec["cmd_out"][turns][-1], "cmd_turns": sum(rec["cmd_out"][t][-1] for t in range(1, turns + 1)), "casts": g.casts, "spent": g.spent, "extra": g.extra,
                   "board": g.board_n(), "recur": g.recur, "dead": sum(1 for t in range(1, last + 1) if ct[t] == ct[t - 1]),
                   "dmg": g.dmg, "kills": len(deaths), "won": g.won or None, "killt": g.won or turns + 1, "deaths": deaths,
                   "died": g.died or None, "death": g.death, "life_paid": dict(g.life_paid), "life": g.life,
                   "how": [o["how"] for o in g.opps if o["dead"]],
                   "rebuild": rebuild, "dis": list(g.dis), "cleared": g.cleared, "resolved": g.casts - g.ctrd,
                   "first": {gi: g.first.get(gi) for gi in range(len(self.groups))}}
        return g, size, mulls

    def run(self, trials, turns, seed):
        T = range(1, turns + 1)
        rec = blank_rec(turns)
        first = {gi: [] for gi in range(len(self.groups))}
        cmd_first = {c.name: [] for c in self.commanders}
        attr, kept, mull_n, rattr, tut = Counter(), Counter(), 0, Counter(), Counter()
        dsrc, trigs, lost, atk_turns, xcombats, bst = Counter(), Counter(), 0, 0, 0, Counter()
        finals = []
        for i in range(trials):
            fixed = {self.kill_turn - 1: [parse_event(f"cmd@{self.kill_turn - 1}")[1]]} if self.kill_turn and self.kill_turn > 1 else None
            g, size, mulls = self.game(i, seed, turns, rec, events=fixed,
                                       trace=self.args.trace == i + 1)
            kept[size] += 1; mull_n += mulls > 0
            for gi in first: first[gi].append(g.first.get(gi))
            for c in cmd_first: cmd_first[c].append(g.cmd_first.get(c))
            attr.update(g.attr); rattr.update(g.rattr); tut.update(g.tut); dsrc.update(g.dsrc); trigs.update(g.trigs)
            lost += g.lost; atk_turns += g.atk_turns; xcombats += g.xcombats; bst.update(g.bstat)
            finals.append(g.final)
        return {"rec": rec, "first": first, "cmd_first": cmd_first, "attr": attr, "kept": kept, "rattr": rattr, "tut": tut,
                "mulliganed": mull_n / trials, "trials": trials, "turns": turns, "finals": finals,
                "dsrc": dsrc, "trigs": trigs, "lost": lost / trials, "atk_turns": atk_turns / trials,
                "xcombats": xcombats / trials, "bstat": bst, "spec": bool(self.board_spec)}

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
    F, n = res["finals"], res["trials"]
    out["kill_by_turn"] = {lab: {t: round(mean([1 if len(f["deaths"]) >= need and f["deaths"][need - 1] <= t else 0 for f in F]), 4)
                                 for t in range(1, T + 1)}
                           for lab, need in (("first", 1), ("second", 2), ("table", OPP_N))}
    wins = sorted(f["won"] for f in F if f["won"])
    out["table_kill"] = {"share": round(len(wins) / n, 4), "p10": q(wins, .1) if wins else None,
                         "med": q(wins, .5) if wins else None, "p90": q(wins, .9) if wins else None}
    how = Counter(h for f in F for h in f["how"])
    out["kills_by"] = {h: round(v / sum(how.values()), 3) for h, v in how.most_common()}
    out["damage_sources"] = {k: round(v / n, 2) for k, v in res["dsrc"].most_common(10) if v / n >= 0.05}
    kinds = Counter()
    for (_, kind), v in res["trigs"].items(): kinds[kind] += v
    out["triggers_by_kind"] = {k: round(kinds[k] / n, 2) for k in ("enter", "cast", "timed", "combat", "dies", "~opp", "other") if kinds[k]}
    out["trigger_sources"] = {f"{name} ({kind})": round(v / n, 2) for (name, kind), v in res["trigs"].most_common(12) if v / n >= 0.05}
    out["lost_in_combat"] = round(res["lost"], 3); out["attack_turns"] = round(res["atk_turns"], 2)
    out["extra_combats"] = round(res["xcombats"], 2)
    if res.get("spec"): out["blocks"] = {k: round(v / n, 3) for k, v in sorted(res["bstat"].items())}
    paid = Counter()
    for f in F: paid.update(f.get("life_paid") or {})
    died = sorted(f["died"] for f in F if f.get("died"))
    out["self_life"] = {"paid_avg": round(sum(paid.values()) / n, 2), "paid_by": {k: round(v / n, 2) for k, v in paid.most_common()},
                        "died_share": round(len(died) / n, 4), "died_med": q(died, .5) if died else None,
                        "died_by": dict(Counter(f.get("death") for f in F if f.get("died"))), "floor": LIFE_FLOOR,
                        "end_p10": q(sorted(f.get("life", START_LIFE) for f in F), .1)}
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
    print_combat(label, sm, T)

def print_combat(label, sm, T):
    tt = sm["turns"]
    def trio(t, m): d = tt[t][m]; return f"{d['p10']}/{d['med']}/{d['p90']}"
    bl = sm.get("blocks")
    print(f"\n## {label}: combat and damage ({OPP_N} opponents at {START_LIFE} life; "
          + (f"boards from --blockers: {sm.get('blockers_spec', '')}" if bl is not None else "no opposing creatures (--blockers not set)")
          + "; opponents never attack; cumulative, end of turn)")
    print(f"{'turn':<5}{'attackers':<11}{'combat dmg':<13}{'all dmg':<13}{'top cmdr dmg':<14}{'poison':<9}{'opps dead':>10}{'your life':>13}"
          + (f"{'opp blockers':>14}" if bl is not None else ""))
    for t in range(1, T + 1):
        print(f"T{t:<4}{trio(t, 'atk'):<11}{trio(t, 'cdmg'):<13}{trio(t, 'dmg'):<13}{trio(t, 'cmdmax'):<14}{trio(t, 'poison'):<9}"
              f"{tt[t]['kills']['mean']:>10.2f}{trio(t, 'life'):>13}" + (f"{trio(t, 'oppb'):>14}" if bl is not None else ""))
    kb = sm["kill_by_turn"]
    show = [t for t in range(3, T + 1)]
    for lab, name in (("first", "first opponent dead"), ("table", "all opponents dead")):
        print(f"{name}: " + " | ".join(f"<=T{t} {pct(kb[lab][t]).strip()}" for t in show))
    sl = sm.get("self_life")
    if sl and sl["died_share"]:
        print(f"you lost in {pct(sl['died_share']).strip()} of games (median T{sl['died_med']}): "
              + " | ".join(f"{'your own life payments' if k == 'life' else 'drew from an empty library'} {v / sum(sl['died_by'].values()):.0%}" for k, v in sl["died_by"].items()))
    if sl and sl["paid_avg"]:
        print(f"life you paid yourself (avg per game): {sl['paid_avg']:.2f} = " + " | ".join(f"{k} {v:.2f}" for k, v in sl["paid_by"].items())
              + f"; life at the end P10 {sl['end_p10']}; floor {sl['floor']} for optional payments"
              )
    tk = sm["table_kill"]
    print(f"table killed in {pct(tk['share']).strip()} of games by T{T}" +
          (f" (P10 T{tk['p10']} / median T{tk['med']} / P90 T{tk['p90']} of those)" if tk["med"] else "")
          + ("; kills by: " + " | ".join(f"{h} {pct(v).strip()}" for h, v in sm["kills_by"].items()) if sm["kills_by"] else ""))
    if sm["damage_sources"]:
        print("damage by source (avg per game): " + " | ".join(f"{k} {v:.1f}" for k, v in sm["damage_sources"].items()))
    if sm["triggers_by_kind"]:
        print("triggers fired (avg per game): " + " | ".join(f"{k} {v:.2f}" for k, v in sm["triggers_by_kind"].items()))
    if sm["trigger_sources"]:
        print("trigger sources (avg fires per game): " + " | ".join(f"{k} {v:.2f}" for k, v in sm["trigger_sources"].items()))
    if bl is not None:
        g_ = lambda k: bl.get(k, 0)
        print(f"blocks (avg per game): attackers blocked {g_('blocked'):.2f} (chumped {g_('chump'):.2f}, traded {g_('trade'):.2f}, "
              f"lost to the blocker {g_('bounced'):.2f}, stalled {g_('stalled'):.2f}) | held back from a bad block {g_('held_back'):.2f} | "
              f"blockers killed {g_('blk_killed'):.2f} | combat damage stopped by blocks/fog/Maze {g_('stopped'):.1f} | "
              f"your removal on a blocker {g_('removed_blk'):.2f}")
        if any(g_(k) for k in ("fog", "settle", "deny_stop", "prop_paid", "mazed", "deny_countered", "removed_deny")):
            print(f"denial (avg per game): fogs {g_('fog'):.2f} | Settles {g_('settle'):.2f} (your creatures exiled {g_('settled'):.2f}) | "
                  f"attackers kept home by Moat/Bridge/Arbiter/attack tax {g_('deny_stop'):.2f} | attack tax paid {g_('prop_paid'):.2f} mana | "
                  f"Maze {g_('mazed'):.2f} | countered {g_('deny_countered'):.2f} | your removal on denial {g_('removed_deny'):.2f}")
    print(f"attacked on {sm['attack_turns']:.1f} turns per game" + (f"; {sm['extra_combats']:.2f} additional combat phases per game"
          if sm['extra_combats'] else "") + f"; your creatures lost in combat {sm['lost_in_combat']:.2f} per game. "
          f"A game ends when all opponents are dead; its later turns repeat its final state.")

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
                      "d_recur": dm("recur"), "d_cmd_turns": dm("cmd_turns"), "d_dmg": dm("dmg"),
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
          f"{'Δboard':>8}{'Δrecur':>8}{'Δcmdr turns':>13}{'Δdamage':>9}")
    for name in order:
        v = ds.get(name)
        if not v: continue
        print(f"{name:<19}{v['games']:>7}{pct(v['answered']):>10}{pct(v['no_target']):>11}{v['d_casts']:>+9.2f}{v['d_spent']:>+8.2f}"
              f"{v['d_extra']:>+8.2f}{v['d_board']:>+8.2f}{v['d_recur']:>+8.2f}{v['d_cmd_turns']:>+13.2f}{v['d_dmg']:>+9.2f}")
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
    keys = ("resolved", "spent", "extra", "board", "recur", "cmd_turns", "dead", "dmg", "killt")
    base_casts = sorted(b["resolved"] for base, _ in out for b in base)
    floor_pct = lad["fold"]["casts_below_clean_pct"]
    p10 = q(base_casts, floor_pct / 100)
    lost = lad["fold"]["cmd_turns_lost"]
    bm = [{k: mean([b[k] for b in base]) for k in keys} for base, _ in out]
    noise = {k: round(mean([sd([b[k] for b in base]) for base, _ in out]), 2) for k in ("resolved", "cmd_turns")}
    weak = mean([1 if m["resolved"] < p10 else 0 for m in bm])
    def folds(d, m):
        if not any(r == "hit" for _, r in d["dis"]) or d.get("won"): return False     # killing the table is never a fold
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
               "cleared": round(mean([d["cleared"] for (f, d), _ in games]), 2),
               "won": round(mean([1 if d.get("won") else 0 for (f, d), _ in games]), 3)}
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
            "base_won": round(mean([1 if b.get("won") else 0 for base, _ in out for b in base]), 3),
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
          f"{b['dead']:.1f} dead turns, {b['dmg']:.0f} damage, table killed in {pct(ls['base_won']).strip()} by T{T}. noise band (avg per-shuffle SD across baselines): ±{ls['noise']['resolved']} spells, "
          f"±{ls['noise']['cmd_turns']} cmdr turns. clean floor (P{ls['floor_pct']}) = {ls['p10_casts']} spells.")
    print(f"{'rung':>4}{'fired':>7}{'hit':>6}{'answered':>10}{'Δspells':>9}{'Δmana':>8}{'Δcards':>8}{'Δboard':>8}{'Δrecur':>8}"
          f"{'Δcmdr t':>9}{'Δdead t':>9}{'rebuilt':>9}{'in':>4}{'fold':>8}{'Δdmg':>8}{'Δkill t':>9}{'won':>7}")
    for r in ls["rungs"]:
        rb = "  -" if r["rebuilt"] is None else pct(r["rebuilt"]).strip()
        print(f"{r['rung']:>4}{r['fired']:>7.2f}{r['hits']:>6.2f}{pct(r['answered']):>10}{r['d_resolved']:>+9.2f}{r['d_spent']:>+8.2f}"
              f"{r['d_extra']:>+8.2f}{r['d_board']:>+8.2f}{r['d_recur']:>+8.2f}{r['d_cmd_turns']:>+9.2f}{r['d_dead']:>+9.2f}"
              f"{rb:>9}{(str(r['rebuild_med']) if r['rebuild_med'] is not None else '-'):>4}{pct(r['fold']):>8}"
              f"{r['d_dmg']:>+8.1f}{r['d_killt']:>+9.2f}{pct(r['won']):>7}")
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
          "pre-hit board size by the horizon / median turns it took. dmg = damage to opponents; kill t = turn the table died "
          f"(T{T + 1} if it didn't); won = games that killed the table (never a fold). Events: data/goldfish_gradients.json (docs/GOLDFISH.md).")

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
    rows.append((f"damage T{T} P10/med/P90", [f"{sm['turns'][T]['dmg']['p10']}/{sm['turns'][T]['dmg']['med']}/{sm['turns'][T]['dmg']['p90']}" for _, sm in builds]))
    rows.append((f"top cmdr dmg T{T} median", [str(sm['turns'][T]['cmdmax']['med']) for _, sm in builds]))
    rows.append((f"first opponent dead <=T{T}", [pct(sm['kill_by_turn']['first'][T]).strip() for _, sm in builds]))
    rows.append((f"table killed <=T{T}", [pct(sm['table_kill']['share']).strip() for _, sm in builds]))
    rows.append(("table kill median turn", [f"T{sm['table_kill']['med']}" if sm['table_kill']['med'] else "-" for _, sm in builds]))
    if all("disruption" in sm and "any disruption" in sm["disruption"] for _, sm in builds):
        rows.append((f"disrupted: Δspells T{T}", [f"{sm['disruption']['any disruption']['d_casts']:+.2f}" for _, sm in builds]))
        rows.append((f"disrupted: Δcmdr turns", [f"{sm['disruption']['any disruption']['d_cmd_turns']:+.2f}" for _, sm in builds]))
        rows.append((f"disrupted: Δdamage", [f"{sm['disruption']['any disruption']['d_dmg']:+.2f}" for _, sm in builds]))
        rows.append(("disrupted: answered", [pct(sm['disruption']['any disruption']['answered']).strip() for _, sm in builds]))
    if all("ladder" in sm for _, sm in builds):
        L = [sm["ladder"] for _, sm in builds]
        rows.append(("ladder: median breakpoint", [str(l["bp"]["med"]) if l["bp"] else "none" for l in L]))
        rows.append(("ladder: never folded", [pct(l["never"]).strip() for l in L]))
        rows.append(("ladder: fold (avg over rungs)", [pct(mean([r["fold"] for r in l["rungs"]])).strip() for l in L]))
        rows.append(("ladder: fold at top rung", [pct(l["rungs"][-1]["fold"]).strip() for l in L]))
        rows.append(("ladder: Δcmdr turns top rung", [f"{l['rungs'][-1]['d_cmd_turns']:+.2f}" for l in L]))
        rows.append(("ladder: Δkill turn top rung", [f"{l['rungs'][-1]['d_killt']:+.2f}" for l in L]))
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
            for fod, su, tp in k.sac_outlets:
                bits.append(f"sac outlet: {'T, ' if tp else ''}sacrifice {perm_desc(fod)} -> " + "+".join("".join(sorted(u[0] | u[1])) or "-" for u in su))
        else:
            counts[k.status] += 1
            bits = []
            if k.units: bits.append("mana " + "+".join("".join(sorted(u[0] | u[1])) or "-" for u in k.units)
                                    + (" (restricted)" if any(u[2] for u in k.units) else "")
                                    + (" (colored only)" if any(u[3] for u in k.units) else ""))
            for fod, su, tp in k.sac_outlets:
                bits.append(f"sac outlet: {'T, ' if tp else ''}sacrifice {perm_desc(fod)} -> " + "+".join("".join(sorted(u[0] | u[1])) or "-" for u in su))
            if k.imprint: bits.append("imprint: mana of the exiled card's colors")
            if k.mox_diamond: bits.append("enters by discarding a land")
            for cu, key, n in k.cond_units:
                bits.append("mana " + "+".join("".join(sorted(u[0] | u[1])) or "-" for u in cu) + f" if {n}+ {pv(key)}")
            if k.vivid: bits.append("mana: 1 per color among your permanents")
            if k.convs: bits.append(f"filter {k.convs[0][0]}->" + ("X" if k.dyn_mana else str(len(k.convs[0][1]))))
            if k.dyn_mana: bits.append("X = " + " ".join(str(x) for x in k.dyn_mana))
            if k.etap: bits.append("enters tapped")
        if k.etb: bits.append("ETB " + ", ".join(fx_str(e) for e in k.etb) + (" (sacrificed)" if k.sac_etb else ""))
        if k.spell: bits.append(", ".join(fx_str(e) for e in k.spell))
        if k.castfx: bits.append("when cast: " + ", ".join(fx_str(e) for e in k.castfx))
        for ev, f, fx, once, tax, each in k.trig:
            if not f: fl = ""
            elif "types" in f:
                fl = "(" + ",".join(sorted({x.lower() for x in f["types"]} | ({"legendary"} if f["legendary"] else set())
                                           | {"non" + x.lower() for x in f["non"]} | {x.lower() for x in f.get("sub") or ()})) \
                     + ({"self": " targeting ~", "modified": " targeting a modified permanent", "creature": " targeting your creature"}
                        .get(f.get("targets"), "")) + ")"
            else: fl = "(" + perm_desc(f) + ")"
            bits.append(f"on {ev}{fl}{' 1/turn' if once else ''}{' taxed' if tax else ''}{' +opp turns' if each else ''}: "
                        + ", ".join(fx_str(e) for e in fx))
        def act_str(a):
            cost = ("T " if a["tap"] else "") + (f"{a['gen'] + len(a['pips'])} " if a["gen"] or a["pips"] else "") \
                   + ("sac " if a["sac"] else "") + (f"sac {perm_desc(a['fodder'])} " if a.get("fodder") else "") \
                   + (f"-{a['rm'][1]} {a['rm'][0]} " if a["rm"] else "") + (f"{a['life']} life " if a.get("life") else "")
            return f"act [{cost.strip()}]: " + ", ".join(fx_str(e) for e in a["fx"]) + (" (sorcery speed)" if a.get("sorcery") else "")
        for a in k.acts: bits.append(act_str(a))
        for c_, fx in k.pw: bits.append(f"loyalty {c_:+d}: " + ", ".join(fx_str(e) for e in fx))
        if k.ctr_enter: bits.append(f"enters with {pv(k.ctr_enter[1])} {k.ctr_enter[0]}" + (" if cast from hand" if k.ctr_enter[2] else ""))
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
            elif s[0] == "anthem":
                f = s[1]
                who = "~" if f.get("self") else ("other " if s[5] else "") + ("attacking " if s[6] else "") + (
                    " ".join(sorted(f.get("sub") or ())) + " " if f.get("sub") else "") + ("tokens" if f.get("istoken") else "creatures")
                pt = f" {pv(s[2], True)}/{pv(s[3], True)}" if (s[2] or s[3]) else ""
                bits.append(f"anthem {who}{pt}" + (" " + ", ".join(sorted(s[4])) if s[4] else ""))
            elif s[0] == "mana_mult": bits.append(f"mana x{s[2]} ({s[1]}s)")
            elif s[0] == "reduce_dyn":
                f = s[1]
                bits.append("reduce " + (" ".join(sorted(f["types"]) + sorted(f.get("sub") or ())) or "all") + " spells by 1 per " + " ".join(s[2]))
            elif s[0] == "equip_red": bits.append(f"equip costs {{{s[1]}}} less")
            elif s[0] == "attack_limit": bits.append(f"at most {s[1]} attacker(s) each combat (yours too)")
            elif s[0] == "neutral_block": bits.append("block limit (opponents never attack)")
            elif s[0] == "base_pt": bits.append(("other " if s[3] else "") + f"creatures are base {s[1]}/{s[2]}")
            elif s[0] == "cr_mana": bits.append("creatures gain: {T}: add " + "+".join("".join(sorted(u[0])) for u in s[1]))
            elif s[0] == "mana_add": bits.append(f"mana +{s[2]} per tap ({s[1]}s)")
            elif s[0] == "type_grant":
                bits.append(" and ".join(t.lower() + "s" for t in sorted(s[1])) + " you control are also "
                            + " ".join(sorted(s[2]) + sorted(s[3])) + ("; they have " + "; ".join(act_str(a) for a in s[4]) if s[4] else ""))
            elif s[0] == "token_each": bits.append("a Clue, Food or Treasure token -> one of each")
            elif s[0] == "token_mult": bits.append(f"tokens x{s[1]}" + (" (creature tokens)" if s[2] else ""))
            elif s[0] == "trig_x":
                what = "land" if s[2].get("land") else perm_desc(s[2])
                bits.append(f"{what} abilities trigger twice" if s[1] == "src" else
                            f"{ {'enter': 'entering', 'dies': 'dying', 'attack': 'attacking'}[s[1]] } ({what}) triggers twice")
            elif s[0] == "thopter_plus": bits.append("artifact tokens: +1 Thopter 1/1 flying each time")
            elif s[0] == "dmg_mult": bits.append(f"damage x{s[1]}" + (" (your sources)" if s[2] else ""))
            else: bits.append(s[0])
        if k.self_red: bits.append(f"costs {{{k.self_red[0]}}} less per " + " ".join(k.self_red[1]))
        if k.leyline: bits.append("leyline")
        if k.requires == "gy": bits.append("needs a target in your graveyard")
        elif k.requires == "gy_payoff": bits.append("cast only with a graveyard payoff (recursion in hand/play or a flashback-style card to fetch)")
        elif k.requires: bits.append("needs a " + k.requires)
        if k.burn_blk: bits.append(f"can burn a blocker ({k.burn_blk[3]} damage)")
        if k.addsac: bits.append("costs a sacrifice: " + ("land" if k.addsac.get("land") else perm_desc(k.addsac)))
        if k.no_untap: bits.append("doesn't untap (spent last)")
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
        if k.attach: bits.append(("equipped" if k.equip or "Equipment" in k.subtypes else "enchanted")
                                 + f" creature {pv(k.attach[0], True)}/{pv(k.attach[1], True)}"
                                 + (" " + ", ".join(sorted(k.attach[2])) if k.attach[2] else ""))
        for cond, cp, ct, ck in k.attach_cond:
            bits.append(("if " + {"color": f"{cond[-1]} ", "aura2": "another Aura on it"}.get(cond[0], "") if cond[0] == "aura2" else f"if it's {cond[1]}")
                        + ": " + (f"{cp:+d}/{ct:+d} " if cp or ct else "") + ", ".join(sorted(ck)))
        if k.debuff: bits.append("removal Aura (never put on your own creature)")
        if k.untapper: bits.append(f"T: untap {k.untapper[0]} land(s) (read as tapping them again for mana)")
        if k.equip: bits.append(f"equip {k.equip[0] + len(k.equip[1])}")
        if k.alpha: bits.append("pump: cast before combat only when it kills an opponent or adds 2 x MV + 2 damage")
        if "Creature" in k.types and not k.is_land:                 # combat bits last, so the ability read leads the line
            pt = f"{k.power}/{k.tough}" if not k.dyn_pt else \
                ("X/X" if k.dyn_pt[0] == "both" else f"X/{k.tough}") + " (X = " + " ".join(k.dyn_pt[1]) + ")"
            kws = sorted(k.kw) + [f"{a} {b}" for a, b in sorted(k.kwn.items()) if a != "exalted"] + [EVADE_TXT[r[0]].format(*r[1:]) for r in k.evade]
            bits.append(pt + (" " + ", ".join(kws) if kws else "") + (f" (a creature only at devotion {k.god[1]}+)" if k.god else ""))
        elif k.kw and not k.is_land: bits.append(", ".join(sorted(k.kw)))
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
    ap.add_argument("--trace", type=int, default=0); ap.add_argument("--blockers", default="")
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

    try: args.board_spec = parse_blockers(args.blockers)
    except ValueError as ex:
        sys.exit(f"--blockers {str(ex)!r}: use [SEAT:]P/T[ keyword...]@T[-U][xN] for a creature (e.g. '2/2@3; 1/4 reach@4x2; "
                 f"1:3/3 deathtouch@5') or [SEAT:]CODE@T[-U] with CODE one of {', '.join(DENY)} (e.g. 'prop@4; 2:fog@6'). "
                 f"Keywords: {', '.join(BLOCKER_KW)}")

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
    globals()["CHOSEN_TYPE"] = chosen_type([found[n] for n in raw_cmd], [found[n] for n in raw_lib])
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
    globals()["LIFE_FLOOR"] = FLOOR_BY_BRACKET.get(int(str(bracket)[0]) if str(bracket)[:1].isdigit() else 0, 20)
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
        if args.blockers: sm["blockers_spec"] = args.blockers
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
    print("\nscope: plays alone by design (opponents are approximations, never decisions; their creatures only block, from --blockers, "
          "and they never attack). not modeled: token copies, noncreature tokens other than Treasure/Clue/Food/Gold/named artifacts; "
          "partial/blank cards are cast for their mana cost only. Treat numbers as a floor/ceiling sketch, not a prediction.")

if __name__ == "__main__":
    main()
