#!/usr/bin/env python3
"""T0: decompose every unread goldfish line into frame / conditions / counts / effects, test each part with
goldfish.py's own readers, and name what's missing.

Per line, the verdict is one of:
  oos          out of scope for a goldfish (needs-opponents lines, counterspells, politics...): never blocks a card
  parse gap    every part is something the engine already executes; only the wording wasn't matched.
               A translation into structured effects would read it with no engine work.
  engine gap   at least one part needs a mechanic the engine lacks (or has only in other forms)
Each engine gap names its mechanics: 'keyword: convoke', 'event: is dealt damage', 'cond: morbid', 'cost: discard',
'count: ...', or an effect family from t0_mechanics.EFFECT.

  python3 translation/t0_decompose.py        # reads translation/out/t0_cards.jsonl, writes translation/out/t0_lines.jsonl
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "translation"))
import mtg, goldfish as g                       # noqa: E402
import t0_mechanics as tm                       # noqa: E402

OUT = os.path.join(ROOT, "translation", "out")
MISS = {"unmodeled", "unmodeled modes", "unread part", "keyword not modeled", "needs opponents",
        "held wipe (symmetric, never cast)"}
ABILITY_WORD = re.compile(r"^(?:[a-z'!\-]+ ){0,4}[a-z'!\-]+ — (?=\S)")

def split_outside_quotes(s, sep):
    """Index of the first sep outside double quotes, or -1."""
    q = False
    for i, ch in enumerate(s):
        if ch == '"': q = not q
        elif not q and s.startswith(sep, i): return i
    return -1

def frame(lo):
    """-> (kind, frame_text, body): kind trigger / activated / loyalty / static."""
    lo = ABILITY_WORD.sub("", lo)
    if re.match(r"^(?:when|whenever|at the beginning of|at end of|at the end of)\b", lo):
        i = split_outside_quotes(lo, ", ")
        return ("trigger", lo[:i], lo[i + 2:]) if i > 0 else ("trigger", lo, "")
    m = re.match(r"^([+−\-]?(?:\d+|x)):\s*(.+)$", lo)
    if m: return "loyalty", m.group(1), m.group(2)
    i = split_outside_quotes(lo, ":")
    if 0 < i < 110 and re.search(r"\{|\bsacrifice\b|\bdiscard\b|\btap\b|\bexile\b|\bremove\b|\bpay\b|\breturn\b|\bexert\b|\bmill\b|\breveal\b", lo[:i]):
        return "activated", lo[:i], lo[i + 1:].strip()
    return "static", "", lo

def check_event(ev):
    m = re.match(r"^when ~ enters and (whenever .+)$", ev)
    if m: return check_event(m.group(1))                 # both halves must read (Brinelin)
    for rx, kind in tm.EVENTS_OK:
        m = re.match(rx, ev)
        if not m: continue
        if kind == "perm":
            subj = m.group("subj")
            if re.search(r"opponent|each player|a player", subj): return ("event", "event: opponents' permanents", "approx", "partial")
            if not g.perm_filt("a", subj):
                return ("filter", "trigger filter: " + filt_key(subj), "sim", "partial")
        if kind == "spell":
            f = g.parse_filter(m.group("spell"))
            if f["unknown"]: return ("filter", "trigger filter: " + filt_key(m.group("spell")), "sim", "partial")
        return None
    row = tm.first(tm.EVENT_CLASS, ev)
    return ("event", row[0] if row else "event: other", "sim", "lacks")

def filt_key(s):
    """A qualifier the filter readers don't know, named by its first unusual word group."""
    for rx, lab in ((r"mana value|converted", "mana value"), (r"\bpower\b|\btoughness\b", "power/toughness"),
                    (r"\btoken\b", "token"), (r"\battacking\b|\bblocking\b|\btapped\b|\buntapped\b", "combat state"),
                    (r"\bwith\b", "'with ...' ability/counter"), (r"\bcolorless\b|\bmulticolored\b|\bmonocolored\b", "color"),
                    (r"\bnon\w+", "non-X"), (r"\bor\b|\band\b", "combined types"), (r"\bopponent\b|\bplayer\b", "controller"),
                    (r"\bcard\b|\bspell\b", "card/spell qualifier")):
        if re.search(rx, s): return lab
    return "other"

def check_cost(cost):
    t = cost.strip()
    if re.fullmatch(r"[+−\-]?\d+", t): return None
    if re.fullmatch(r"[+−\-]x", t): return ("cost", "cost: loyalty X", "sim", "partial")
    r = g.ab_cost(cost)
    if not r[5]: return None
    row = tm.first(tm.COST_CLASS, t)
    return ("cost", row[0] if row else "cost: other", "sim", "partial")

COND_RX = re.compile(r"(?:^|(?<=\. )|(?<=, ))(?:then )?if ([^,]+),|\bas long as ([^,.]+)|\bunless ([^,.]+)|\bonly if ([^,.]+)|\bonly during ([^,.]+)"
                     r"|(?<=[a-z}]) if ((?!you do\b|able\b|it's an? )[^,.]+)(?=\.|$)")    # trailing: '~ costs {2} less if ...' 

def check_conds(body):
    gaps, clean = [], body
    for m in COND_RX.finditer(body):
        c = next(x for x in m.groups() if x)
        whole = m.group(0)
        if whole.startswith(("if", "then if", " if")) or whole.startswith(", if") or " if " in whole[:5]:
            if re.match(r"(?:you do|you don't|they do|they don't|it's an? |it is an? |that player doesn't|no one does)", c): continue
            if g.parse_cond(c): continue
        elif whole.startswith("unless") and re.match(r"(?:its controller|that player|they|an opponent|any player) pays?", c):
            gaps.append(("cond", "tax / cost increase on others", "approx", "partial")); continue
        elif whole.startswith("only during") and re.match(r"your turn", c): continue
        elif whole.startswith("only if") and re.match(r"you control (?:\w+|a|an) ", c) and g.parse_cond(c): continue
        row = tm.first(tm.COND_CLASS, whole)
        gaps.append(("cond", row[0] if row else "cond: other", "sim", "lacks" if "as long as" in whole else "partial"))
    return gaps

COUNT_RX = re.compile(r"\bfor each ([^.,;]+)|\bequal to (?!the damage dealt this way|that much|the life (?:lost|gained) this way|the amount of life you gained)((?:the number of |the total |twice |half )?[^.,;]+)|\bwhere x is ([^.;]+)")

def check_counts(body):
    gaps = []
    for m in COUNT_RX.finditer(body):
        w = next(x for x in m.groups() if x).strip()
        if g.clean_dyn(w) or g._count(w) or re.match(r"(?:its|~'s|that creature's) power|the number of cards in your hand", w): continue
        lab = ("count: opponents' things" if re.search(r"opponent|player|defending", w) else
               "count: events this turn" if re.search(r"this turn|this way|died|dealt", w) else
               "count: mana value / power / toughness" if re.search(r"mana value|power|toughness", w) else
               "count: graveyard / exile / library" if re.search(r"graveyard|exile|library", w) else
               "count: other")
        gaps.append(("count", lab, "sim", "partial"))
    return gaps

def check_effects(body, card):
    """Per sentence: read by goldfish's parse_fx with nothing left over -> fine; else the effect family."""
    gaps, marks = [], []
    body = re.sub(r"(?:^|(?<=\. ))(?:then )?if [^,]+, ", "", body)
    sents = [s for s in re.split(r"(?<=\.)\s+(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", body) if s.strip(" .")]
    for s in sents:
        if g.OPP_LEAD.match(s) and not re.search(r"(?:,|\band|\bthen) you\b", s): continue     # 'its controller creates ...': theirs
        g._CTX.update(raw=card, text=card.get("oracle_text") or "", left=[])
        try: fx, _ = g.parse_fx(s)
        except Exception: fx = []
        left = g._CTX.get("left") or []
        g._CTX["left"] = None
        if fx and not left: continue
        row = tm.first(tm.EFFECT, s)
        if not row: marks.append(("effect", "effect: unclassified", "sim", "lacks")); continue
        lab, sc, en, _ = row
        (marks if en == "has" else gaps).append(("effect", lab, sc, en))
    return gaps, marks

def decompose(item, card):
    kind, text = item["kind"], item["text"] if item["kind"] == "keyword not modeled" else (item["line"] or item["text"])
    if kind == "needs opponents": return {"verdict": "oos", "parts": [("scope", "needs opponents (goldfish: vacuum line)", "oos", "has")]}
    if kind == "keyword not modeled":
        w = text.strip().lower(); sc, en = tm.KW.get(w, ("sim", "lacks"))
        return {"verdict": "oos" if sc == "oos" else "engine gap", "parts": [("keyword", "keyword: " + w, sc, en)]}
    lo = re.sub(r"\s*\([^()]*\)", "", (text or "").lower()).strip()
    if kind == "held wipe (symmetric, never cast)":
        return {"verdict": "engine gap", "parts": [("effect", "removal / damage to creatures / wipes / fight / bounce", "approx", "partial")]}
    row = tm.first(tm.STRUCT, lo)
    if row:
        lab, sc, en, _ = row
        return {"verdict": "oos" if sc == "oos" else "engine gap", "parts": [("struct", lab, sc, en)]}
    kwm = re.match(r"^([a-z!' ]+?)(?:—| \{|$| \d| x\b)", lo.strip(" ."))
    if kwm and kwm.group(1).strip() in tm.KW:              # a keyword line nothing reads ('Convoke', 'Warp—{B}, Pay 2 life')
        w = kwm.group(1).strip(); sc, en = tm.KW[w]
        return {"verdict": "oos" if sc == "oos" else "engine gap", "parts": [("keyword", "keyword: " + w, sc, en)]}
    parts = []
    for q in re.findall(r'"([^"]+)"', lo):                 # a granted quoted ability is its own line (Fungus Sliver)
        sub = decompose({"kind": "unmodeled", "text": q, "line": q}, card)
        parts += [p for p in sub["parts"] if p[3] in ("lacks", "partial")]
        if not re.search(r"\b(?:equipped|enchanted) creature\b|\bcommander creatures\b|\bcreatures you control have \"\{t\}: add", lo):
            parts.append(("grant", "grant quoted abilities to other permanents", "sim", "partial"))
    lo = re.sub(r'"[^"]*"', '"q"', lo)
    fk, ft, body = frame(lo)
    if fk == "trigger":
        e = check_event(ft)
        if e: parts.append(e)
    elif fk in ("activated", "loyalty"):
        c = check_cost(ft)
        if c: parts.append(c)
    parts += check_conds(body)
    parts += check_counts(body)
    gaps, marks = check_effects(body, card)
    parts += gaps
    if kind == "unmodeled modes": parts.append(("struct", "modal variants (N modes, spree-like, repeated modes)", "sim", "partial"))
    if any(p[3] in ("lacks", "partial") for p in parts):
        return {"verdict": "engine gap", "parts": parts}
    if any(p[1] == "effect: unclassified" for p in marks):
        return {"verdict": "unclassified", "parts": marks}
    return {"verdict": "parse gap", "parts": marks or [("effect", "combination of read parts", "sim", "has")]}

def main():
    idx = {c["name"]: c for c in mtg.cards() if mtg.legal(c) == "legal"}
    n = 0
    with open(os.path.join(OUT, "t0_cards.jsonl"), encoding="utf-8") as fi, \
            open(os.path.join(OUT, "t0_lines.jsonl"), "w", encoding="utf-8") as fo:
        for ln in fi:
            r = json.loads(ln)
            if r["status"] == "land": continue
            for it in r["unread"]:
                if it["kind"] not in MISS: continue
                d = decompose(it, idx[r["name"]])
                fo.write(json.dumps({"name": r["name"], "status": r["status"], "weight": r["weight"], "kind": it["kind"],
                                     "text": it["text"] if it["kind"] == "keyword not modeled" else (it["line"] or it["text"]),
                                     **d}, ensure_ascii=False) + "\n")
                n += 1
    print(f"{n} unread items decomposed -> translation/out/t0_lines.jsonl")

if __name__ == "__main__":
    main()
