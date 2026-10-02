"""Pilot policy intel: what each card in a deck is for, built once per deck for the harness's tutor policy.

Forge's AI picks library-search targets with generic "best card" pickers, blind to what the deck is built to do. The
harness (fishpond/harness/PilotPolicy.java) scores every candidate of a search or dig instead, from this file plus the
board at decision time. Everything here is general; no deck is special-cased:

  roles     what a card does (ramp, draw, removal, wipe, protection, counter, wincon, tutor, engine, hate), from
            Scryfall's oracle tags (data/oracle-tags-*.jsonl) with their parent tags, plus a few oracle-text fallbacks
  mechanics payoff -> enabler links: a card tagged 'synergy-X' (or a payoff tag such as 'landfall') pays off cards that
            are or do X (type, keyword, color or tag). A mechanic counts as an engine when the deck has a payoff for it
            and at least ENGINE_MIN enablers (Astral Slide: 'synergy-cycling', and every cycler in the deck)
  combos    Commander Spellbook combos entirely inside the deck (data/spellbook_combos.json.gz)
  flag      Forge marks the card AI:RemoveDeck:All (its AI can't play it well): the policy discounts it unless
            fishpond/forge_card_overrides/ fixes the card
  boost     optional deck header '# priority: Card A; Card B' (earlier = stronger). Support only: no deck ships one.

Output: a JSON file next to the seat's .dck (<dck>.policy.json), keyed by the names Forge uses.
"""
import glob, gzip, json, os, re

from . import decks as dk

DATA = os.path.join(dk.REPO, "data")
POLICY_VERSION = 1
ENGINE_MIN = 6            # enablers in the deck before a payoff's mechanic counts as an engine
MAX_COMBOS = 300

# role -> oracle tags (a card has a role when it carries one of these tags or a tag under them)
ROLE_TAGS = {
    "ramp": {"ramp", "mana rock", "mana dork", "tutor-land-basic", "tutor-land-to-battlefield", "extra land", "cost reducer"},
    "draw": {"draw", "card advantage", "draw engine", "wheel", "impulse", "pure draw"},
    "removal": {"removal", "spot removal", "removal-creature", "removal-nonland", "removal-destroy", "removal-exile", "banish"},
    "wipe": {"sweeper", "sweeper-one-sided", "mass removal"},
    "protection": {"protection", "pillowfort", "fog", "fog-selective", "damage prevention-you", "gives player shroud",
                   "gives player hexproof", "hexproof granter", "indestructible granter", "protects-creature"},
    "counter": {"counterspell", "counterspell-soft", "counterspell-reusable", "counterspell-automatic"},
    "wincon": {"alternate win condition", "extra turn", "infinite combo piece"},
    "tutor": {"tutor", "tutor-to-hand", "tutor-to-battlefield", "tutor-card"},
    "hate": {"hate", "rule of law", "tax", "stax"},
    "lifegain": {"lifegain"},
}
ENGINE_TAGS = {"draw engine", "repeatable draw", "repeatable card advantage", "repeatable pure draw", "repeatable crime",
               "repeatable lifegain", "repeatable token generator", "repeatable removal", "repeatable"}
# payoff tags that aren't 'synergy-X', mapped to the X they pay off
PAYOFF_ALIASES = {"cycle-ons-cycling-matters": "cycling", "landfall": "land", "magecraft": "instant-sorcery",
                  "lifegain matters": "lifegain", "draw matters": "draw", "cast trigger-other": "spell",
                  "death trigger": "creature-dies", "sacrifice outlet": "token"}
KEYWORDS = {"cycling": r"\b\w*cycling\b", "flying": r"\bflying\b", "haste": r"\bhaste\b", "trample": r"\btrample\b",
            "deathtouch": r"\bdeathtouch\b", "vigilance": r"\bvigilance\b", "menace": r"\bmenace\b",
            "first-strike": r"\bfirst strike\b", "scry": r"\bscry\b", "mill": r"\bmills?\b", "suspend": r"\bsuspend\b",
            "food": r"\bfood\b", "treasure": r"\btreasure\b", "clue": r"\bclue\b", "token": r"\bcreate\b.*\btoken",
            "token-creature": r"\bcreate\b.*\bcreature tokens?\b", "poison": r"\b(toxic|infect|poison)\b",
            "counters": r"\+1/\+1 counter", "lifegain": r"\bgain \w+ life\b", "draw": r"\bdraws? (a|two|three|\w+) cards?\b",
            "token-artifact": r"\bcreate\b.*\bartifact token", "exiling": r"\bexile\b", "graveyard-cast": r"\bflashback\b|\bescape\b"}
COLORS = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}

_TAGS = None
_COMBOS = None

def _tags():
    """oracle_id -> set of tag labels, each tagging expanded with its ancestor tags."""
    global _TAGS
    if _TAGS is not None: return _TAGS
    files = sorted(glob.glob(os.path.join(DATA, "oracle-tags-*.jsonl")))
    _TAGS = {}
    if not files: return _TAGS
    rows = [json.loads(l) for l in open(files[-1], encoding="utf-8") if l.strip()]
    by_id = {r["id"]: r for r in rows}
    memo = {}
    def labels(r):
        if r["id"] in memo: return memo[r["id"]]
        memo[r["id"]] = out = {r["label"]}
        for p in r.get("parent_ids") or []:
            if p in by_id: out |= labels(by_id[p])
        return out
    for r in rows:
        ls = labels(r)
        for t in r.get("taggings") or []: _TAGS.setdefault(t["oracle_id"], set()).update(ls)
    return _TAGS

def _combos():
    global _COMBOS
    if _COMBOS is not None: return _COMBOS
    p = os.path.join(DATA, "spellbook_combos.json.gz")
    _COMBOS = json.load(gzip.open(p, "rt", encoding="utf-8")).get("variants", []) if os.path.exists(p) else []
    return _COMBOS

def _text(c):
    faces = c.get("card_faces") or [c]
    return " ".join((f.get("oracle_text") or "") for f in faces).lower() or (c.get("oracle_text") or "").lower()

def _type(c):
    faces = c.get("card_faces") or [c]
    return " ".join((f.get("type_line") or "") for f in faces).lower() or (c.get("type_line") or "").lower()

def roles_of(c, tags):
    out = {r for r, ts in ROLE_TAGS.items() if tags & ts}
    t, ty = _text(c), _type(c)
    if "land" in ty and "land" not in out: out.add("land")
    if re.search(r"\bsearch your library\b", t): out.add("tutor")
    if re.search(r"\byou win the game\b", t): out.add("wincon")
    if re.search(r"\badd \{", t) and "land" not in ty: out.add("ramp")
    if tags & ENGINE_TAGS: out.add("engine")
    return sorted(out)

def is_enabler(mech, c, tags):
    """Does card c count toward mechanic `mech` (what a 'synergy-<mech>' payoff wants)?"""
    t, ty = _text(c), _type(c)
    m = mech.replace("-", " ")
    if mech == "noncreature": return "creature" not in ty and "land" not in ty
    if mech == "instant-sorcery": return "instant" in ty or "sorcery" in ty
    if mech == "spell": return "land" not in ty
    if mech == "multicolor": return len(c.get("colors") or []) > 1
    if mech == "colorless": return not c.get("colors") and "land" not in ty
    if mech in COLORS: return COLORS[mech] in (c.get("colors") or [])
    if mech == "creature-dies": return "creature" in ty or bool(re.search(KEYWORDS["token-creature"], t))
    if mech.startswith("typal-"): return mech[6:] in ty
    if re.search(rf"\b{re.escape(m)}\b", ty): return True
    if mech in KEYWORDS and re.search(KEYWORDS[mech], t): return True
    return mech in tags or m in tags

def payoffs_of(tags):
    out = {t[8:] for t in tags if t.startswith("synergy-")} | {v for k, v in PAYOFF_ALIASES.items() if k in tags}
    out |= {t for t in tags if t.startswith("typal-")}
    out -= set(COLORS) | {"typal-creature"}           # "matters for most of the deck" isn't an engine
    return out - {"commander", "color-share", "color-each", "blocker", "blocker-self", "solo-attack", "low-power", "tapped", "modified"}

def strength(enablers, deck_size):
    """How much a mechanic is a real engine, 0..1: enough enablers to fire it, and specific (one that half the deck
    enables, like 'spell', is background, not a plan)."""
    frac = enablers / max(1, deck_size)
    spec = 1.0 if frac <= 0.3 else max(0.15, (0.6 - frac) / 0.3)
    return round(min(1.0, enablers / 15) * spec, 3)

def priority_list(meta):
    """'# priority:' header lines -> card names in order (support for deck-specific overrides; none ship)."""
    v = meta.get("priority") or []
    if isinstance(v, str): v = [v]
    out = []
    for line in v: out += [x.strip() for x in re.split(r"\s*[;>]\s*", line) if x.strip()]
    return out

def build(d):
    """Policy intel for a fishpond Deck (decks.load) as a JSON-safe dict, or None for a dummy."""
    if d.kind == "dummy": return None
    import mtg
    tagdb = _tags()
    names = list(d.commanders) + [n for _, n in d.main]
    cards = {}
    for n in names:
        c = mtg.find(n)[0]
        if not c: continue
        cards[n] = (c, tagdb.get(c.get("oracle_id"), set()))
    # mechanics: payoffs in the deck and how many deck cards enable each
    pay = {n: payoffs_of(tg) for n, (c, tg) in cards.items()}
    mechs = {}
    for m in sorted(set().union(*pay.values()) if pay else set()):
        en = [n for n, (c, tg) in cards.items() if is_enabler(m, c, tg)]
        po = [n for n in cards if m in pay[n]]
        if len(en) >= ENGINE_MIN: mechs[m] = {"enablers": len(en), "payoffs": len(po), "_en": en, "_po": po}
    out_cards, role_count = {}, {}
    for n, (c, tg) in cards.items():
        fn = d.forge.get(n, n)
        roles = roles_of(c, tg)
        p = [m for m in pay[n] if m in mechs]
        e = [m for m, v in mechs.items() if n in v["_en"] and n not in v["_po"]]
        if p and "engine" not in roles: roles.append("engine")
        for r in roles: role_count[r] = role_count.get(r, 0) + 1
        syn = sum(mechs[m]["payoffs"] for m in e) + sum(mechs[m]["enablers"] / 10 for m in p)
        out_cards[fn] = {"roles": roles, "payoff": p, "enabler": e, "syn": syn, "cmc": c.get("cmc", 0) or 0,
                         "flag": "All" in d.flags.get(n, []), "cmdr": n in d.commanders}
    top = max([v["syn"] for v in out_cards.values()] + [1])
    for v in out_cards.values(): v["syn"] = round(v["syn"] / top, 3)
    # Spellbook combos made only of deck cards, smallest first
    have = set(names)
    combos = []
    for cb in _combos():
        cs = cb.get("cards") or []
        if len(cs) >= 2 and set(cs) <= have:
            prod = " ".join(cb.get("produces") or [])
            combos.append({"cards": [d.forge.get(x, x) for x in cs], "win": bool(re.search(r"win the game|infinite", prod, re.I)),
                           "produces": (cb.get("produces") or [])[:3]})
    combos.sort(key=lambda x: (not x["win"], len(x["cards"])))
    boost = {}
    pl = priority_list(d.meta)
    for k, n in enumerate(pl):
        c = mtg.find(n)[0]
        fn = d.forge.get(c["name"], c["name"]) if c else n
        boost[fn] = max(50, 600 - 25 * k)
    nonland = max(1, sum(1 for v in out_cards.values() if "land" not in v["roles"]))
    return {"v": POLICY_VERSION, "deck": d.label, "cards": out_cards, "boost": boost,
            "mechs": {m: {"enablers": v["enablers"], "payoffs": v["payoffs"], "s": strength(v["enablers"], len(cards))}
                      for m, v in mechs.items()},
            "combos": combos[:MAX_COMBOS],
            "role_share": {r: round(k / nonland, 3) for r, k in sorted(role_count.items())}}

def write_for(d, dck_path):
    """Write <dck>.policy.json for deck d (skipped for dummies). Returns the path or None."""
    intel = build(d)
    if intel is None: return None
    p = dck_path + ".policy.json"
    with open(p, "w", encoding="utf-8") as fh: json.dump(intel, fh, indent=1, sort_keys=True)
    return p

def explain(d):
    """Human summary of a deck's intel (for `fishpond deck`)."""
    it = build(d)
    if not it: return []
    lines = []
    if it["mechs"]:
        lines.append("policy engines (strength 0-1): " + " | ".join(f"{m} {v['s']:.2f} ({v['payoffs']} payoff(s), {v['enablers']} enablers)"
                                                    for m, v in sorted(it["mechs"].items(), key=lambda x: -x[1]["s"])))
    if it["combos"]:
        lines.append(f"policy combos (Commander Spellbook, all in the deck): {len(it['combos'])}; "
                     + " | ".join(" + ".join(c["cards"]) for c in it["combos"][:5]))
    sh = it["role_share"]
    lines.append("policy roles (share of nonland cards): " + ", ".join(f"{r} {v:.0%}" for r, v in sorted(sh.items(), key=lambda x: -x[1]) if r != "land"))
    if it["boost"]: lines.append("policy priority header: " + " > ".join(it["boost"]))
    return lines
