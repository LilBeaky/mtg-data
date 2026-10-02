"""Decks for Fishpond: deck files (mtg.py format and headers) -> Forge .dck, dummies, and opponent seat specs.

A pod is always 4 players: the hero plus 3 opponent seats. Each seat is a dummy or a real deck.
Opponent SPEC: 'dummy' | a deck file path | a name in fishpond/opponents/ (with or without .txt) |
'gauntlet:NAME' (a folder fishpond/opponents/NAME/, any folder path, or a list file of deck paths; each game
samples its seats from it, seeded).
"""
import os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import mtg  # noqa: E402
from . import forge  # noqa: E402

OPP_DIR = os.path.join(HERE, "opponents")
SKIP = {"sideboard", "maybeboard", "considering"}
# A dummy must never act. Isamaru costs {W}; 99 Wastes make only {C}, so it is never castable, and its white
# identity keeps Wastes legal. Dummies still play lands (no stack items); a run checks they never cast.
DUMMY_COMMANDER, DUMMY_LAND = "Isamaru, Hound of Konda", "Wastes"

class Deck:
    """A resolved list. names are Oracle names (Scryfall); dck_lines are what Forge reads."""
    def __init__(self, path, kind):
        self.path, self.kind = path, kind
        self.commanders, self.main = [], []        # Oracle names; main = [(qty, name)]
        self.meta, self.not_found, self.not_forge, self.partial = {}, [], [], []
        self.flags = {}                            # Oracle name -> Forge AI flags ('All', 'Random')
        self.forge = {}                            # Oracle name -> name written in the .dck
        self.produced = {}                         # name the log uses -> colors the card can make (Scryfall produced_mana)
        self.companion = []
        self.identity = ""                         # commanders' color identity, WUBRG order
        self.label = ""
        self.tag = ""                              # Forge player name: letters/digits only (the log shows Ai(k)-<tag>)

    @property
    def size(self): return len(self.commanders) + sum(q for q, _ in self.main)
    def names(self): return set(self.commanders) | {n for _, n in self.main}
    def log_names(self):
        """Every name the Forge log may use for this deck's cards: Oracle names, .dck names, face names."""
        out = set()
        for n in self.names():
            out |= {n, self.forge.get(n, n)} | {f.strip() for f in n.split(" // ")}
        return out
    @property
    def bracket(self): return self.meta.get("bracket_text") or self.meta.get("bracket")

    def dck(self, name):
        lines = ["[metadata]", f"Name={name}", "[Commander]"]
        lines += [f"1 {self.forge[c]}" for c in self.commanders if c in self.forge]
        lines.append("[Main]")
        lines += [f"{q} {self.forge[n]}" for q, n in self.main if n in self.forge]
        return "\n".join(lines) + "\n"

_OVR = None
def _overridden():
    """Card names fishpond/forge_card_overrides/ replaces: their AI:RemoveDeck flag no longer applies."""
    global _OVR
    if _OVR is None:
        _OVR = set()
        for f in forge.override_files():
            m = re.search(r"^Name:(.+)$", open(f, encoding="utf-8").read(), re.M)
            if m: _OVR.add(m.group(1).strip())
    return _OVR

def tag_for(label):
    first = re.split(r"[,\s]", label.strip())[0] if label.strip() else "Deck"
    return re.sub(r"[^A-Za-z0-9]", "", first) or "Deck"

def load(path, kind="hero", idx=None, commander=None):
    """Parse and resolve a deck file. Unresolvable names land in not_found; names Forge has no script for in not_forge
    (both are left out of the .dck and reported). partial = names that only matched partially (mtg.py's fuzzy step)."""
    if not os.path.exists(path): sys.exit(f"fishpond: deck file not found: {path}")
    idx = idx if idx is not None else forge.index()
    d = Deck(path, kind)
    entries = mtg.parse_deck(path)
    d.meta = mtg.parse_deck_meta(path)
    cmd = [n for s, q, n in entries if s in ("commander", "commanders")]
    if commander: cmd = [commander]
    main = {}
    for s, q, n in entries:
        if s in SKIP or n in cmd and s in ("commander", "commanders"): continue
        if s == "companion": d.companion.append(n); continue
        main[n] = main.get(n, 0) + q
    def resolve(n):
        c, how = mtg.find(n)
        if not c or (how or "").startswith("ambiguous"): d.not_found.append(n); return None
        if how == "partial": d.partial.append(f"{n} -> {c['name']}")
        fn, flags = forge.forge_name(c, idx)
        if not fn: d.not_forge.append(c["name"]); return None
        d.forge[c["name"]] = fn
        if fn in _overridden(): flags = [f for f in flags if f != "All"]   # fishpond replaces the script (forge_card_overrides)
        if flags: d.flags[c["name"]] = flags
        if c.get("produced_mana"): d.produced[fn] = "".join(x for x in c["produced_mana"] if x in "WUBRG")
        return c["name"]
    ci = set()
    for n in cmd:
        r = resolve(n)
        if r:
            d.commanders.append(r)
            ci |= set(mtg.find(r)[0].get("color_identity") or [])
    d.identity = "".join(c for c in "WUBRG" if c in ci)
    merged = {}
    for n, q in main.items():
        r = resolve(n)
        if r: merged[r] = merged.get(r, 0) + q
    d.main = list(merged.items())
    d.main = [(q, n) for n, q in d.main]
    d.label = " + ".join(d.commanders) or os.path.splitext(os.path.basename(path))[0]
    d.tag = tag_for(d.label)
    return d

def dummy():
    d = Deck(None, "dummy")
    d.commanders, d.main = [DUMMY_COMMANDER], [(99, DUMMY_LAND)]
    d.forge = {DUMMY_COMMANDER: DUMMY_COMMANDER, DUMMY_LAND: DUMMY_LAND}
    d.label, d.tag = "dummy", "Dummy"
    return d

def swapped(deck, pairs, idx=None):
    """A copy of the hero with Out=>In swaps (--variant). Returns (deck, problems)."""
    idx = idx if idx is not None else forge.index()
    v = Deck(deck.path, deck.kind)
    v.__dict__.update({k: (list(x) if isinstance(x, list) else dict(x) if isinstance(x, dict) else x) for k, x in deck.__dict__.items()})
    probs = []
    for o, i in pairs:
        co, _ = mtg.find(o); ci, _ = mtg.find(i)
        if not co: probs.append(f"{o}: not found"); continue
        if not ci: probs.append(f"{i}: not found"); continue
        j = next((k for k, (q, n) in enumerate(v.main) if n == co["name"]), None)
        if j is None: probs.append(f"{co['name']} is not in the deck"); continue
        fn, flags = forge.forge_name(ci, idx)
        if not fn: probs.append(f"{ci['name']}: Forge has no script for it"); continue
        q, _ = v.main[j]
        v.main[j] = (1, ci["name"])
        if q > 1: v.main.append((q - 1, co["name"]))
        v.forge[ci["name"]] = fn
        if flags: v.flags[ci["name"]] = flags
    return v, probs

# ---------------------------------------------------------------- opponent seats
def _deck_paths(target):
    if os.path.isdir(target):
        return sorted(os.path.join(target, f) for f in os.listdir(target) if f.endswith(".txt") and not f.startswith("_"))
    base = os.path.dirname(os.path.abspath(target))
    out = []
    for raw in open(target, encoding="utf-8"):
        s = raw.split("#", 1)[0].strip()
        if s: out.append(s if os.path.isabs(s) else os.path.join(base, s))
    return out

def resolve_spec(spec):
    """One --opp SPEC -> ('dummy', None) | ('deck', path) | ('gauntlet', [paths])."""
    s = spec.strip()
    if s.lower() == "dummy": return ("dummy", None)
    if s.lower().startswith("gauntlet:"):
        g = s.split(":", 1)[1].strip()
        for t in (g, os.path.join(OPP_DIR, g), os.path.join(OPP_DIR, g + ".txt")):
            if os.path.exists(t):
                paths = _deck_paths(t)
                if not paths: sys.exit(f"fishpond: gauntlet {g!r} has no decks")
                return ("gauntlet", paths)
        sys.exit(f"fishpond: gauntlet not found: {g} (a folder in fishpond/opponents/, a folder path, or a list file)")
    for t in (s, os.path.join(OPP_DIR, s), os.path.join(OPP_DIR, s + ".txt")):
        if os.path.isfile(t): return ("deck", t)
    sys.exit(f"fishpond: opponent not found: {s} ('dummy', a deck file, a name in fishpond/opponents/, or gauntlet:NAME)")

def read_opp_set(path):
    specs = [l.split("#", 1)[0].strip() for l in open(path, encoding="utf-8")]
    specs = [s for s in specs if s]
    if len(specs) > 3: sys.exit(f"fishpond: {path} lists {len(specs)} opponents; a pod has 3 seats")
    return specs

def seat_plan(specs):
    """--opp specs (0-3) -> fixed seats [('dummy'|'deck', path)] and the gauntlet pool (or None).
    Seats not given are dummies, unless a gauntlet is named: then the gauntlet fills every seat not given."""
    if len(specs) > 3: sys.exit("fishpond: at most 3 --opp (a pod has 3 opponent seats)")
    fixed, pool = [], None
    for s in specs:
        kind, val = resolve_spec(s)
        if kind == "gauntlet":
            if pool is not None: sys.exit("fishpond: name one gauntlet per run")
            pool = val
        else: fixed.append((kind, val))
    return fixed, pool

def pod_for(fixed, pool, rng, fixed_pod=None):
    """The 3 opponent seats for one game (or one CLI chunk): fixed seats first, the rest sampled from the gauntlet
    without repeats (filled with dummies if the gauntlet is short), else dummies."""
    seats = list(fixed)
    free = 3 - len(seats)
    if pool and free:
        pick = fixed_pod if fixed_pod is not None else rng.sample(pool, min(free, len(pool)))
        seats += [("deck", p) for p in pick]
    seats += [("dummy", None)] * (3 - len(seats))
    return seats

def validate(d):
    """Problems worth printing before a run: names that didn't resolve, cards Forge lacks, odd sizes, companions."""
    out = []
    if d.not_found: out.append(f"NOT FOUND (left out; fix the names or add data/aliases.txt entries): {'; '.join(d.not_found)}")
    if d.not_forge: out.append(f"Forge {forge.FORGE_VERSION} has no script for (left out): {'; '.join(d.not_forge)}")
    if d.partial: out.append(f"partial name matches (check them): {'; '.join(d.partial)}")
    if d.companion: out.append(f"companion not played (Forge sim has no companion seat here): {'; '.join(d.companion)}")
    if not d.commanders: out.append("no commander (add a Commander section or --commander)")
    if d.size != 100: out.append(f"{d.size} cards in the .dck (Commander decks are 100)")
    return out
