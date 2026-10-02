#!/usr/bin/env python3
"""
explorer.py — single-card explorer: who plays a card, how, what it combos with, and
where it could go next. Standalone research tool; not part of the audit.

USAGE
  python3 scripts/explorer.py "Card Name" [options]

OPTIONS
  --commanders N   EDHREC commander pages to open for themes and synergy (default 8)
  --themes N       EDHREC theme pages to open for the card's in-theme numbers (default 6)
  --ci WUBRG       only combos and suggested commanders inside these colors
  --limit N        rows per list (default 10)
  --offline        local data only (oracle text, tags, Spellbook); no EDHREC
  --refresh        ignore the EDHREC cache (data/explorer_cache/, 7 days) and refetch
  --out FILE       also write the report to FILE

SECTIONS
  1 card          oracle text, price, Game Changer, salt, EDHREC deck count and inclusion
  2 combos        Spellbook (local file): counts, what they produce, recurring partners,
                  top combos, commanders that are themselves combo pieces
  3 commanders    EDHREC top commanders by deck count, with the card's inclusion and
                  synergy in each (synergy only for the N opened pages)
  4 strategies    EDHREC themes across those commanders, weighted by how many decks play
                  the card; then the card's inclusion and synergy on each theme page
  5 build-around  high-lift cards, similar cards, untapped commanders (share the card's
                  oracle tags, not in EDHREC's top list)
  6 prompt        a reasoning prompt for the assistant (REASONING_PROMPT, end of this file)

EDHREC is reached through its page JSON (json.edhrec.com), which is undocumented and can
change or refuse scripted traffic. Any EDHREC failure degrades to the local sections with a
note; nothing here is card truth, only meta signal (USE_INSTRUCTIONS section 9).
"""
import json, math, os, re, sys, time, unicodedata, urllib.error, urllib.request
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mtg

EDHREC_JSON = "https://json.edhrec.com/pages/"
EDHREC_WEB = "https://edhrec.com/"
CACHE_DIR = os.path.join(mtg.DATA_DIR, "explorer_cache")     # gitignored
CACHE_DAYS = 7
USER_AGENT = "mtg-data-explorer/1.0 (+https://github.com/LilBeaky/mtg-data)"
COLORS = "WUBRG"

# ---------- EDHREC ----------
def slug(name):
    """EDHREC slug: front face, lowercase, apostrophes/commas dropped, other runs of
    non-alphanumerics -> '-'. 'Elas il-Kor, Sadistic Pilgrim' -> 'elas-il-kor-sadistic-pilgrim'."""
    s = mtg.norm(name.split(" // ")[0])
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"['\",.!?]", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

class Edhrec:
    def __init__(self, offline=False, refresh=False):
        self.offline, self.refresh = offline, refresh
        self.errors, self.fetched, self.cached = [], 0, 0

    def get(self, path):
        """path like 'cards/blood-artist'. Returns parsed JSON or None (error recorded)."""
        if self.offline: return None
        cpath = os.path.join(CACHE_DIR, path.replace("/", "__") + ".json")
        if not self.refresh and os.path.exists(cpath) and \
                time.time() - os.path.getmtime(cpath) < CACHE_DAYS * 86400:
            try:
                with open(cpath, encoding="utf-8") as fh:
                    d = json.load(fh)
                self.cached += 1
                return d
            except (OSError, ValueError):
                pass
        if self.fetched: time.sleep(0.4)     # be polite: one request at a time, spaced
        req = urllib.request.Request(EDHREC_JSON + path + ".json", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # EDHREC's JSON bucket answers 403 AccessDenied for a page that doesn't exist
            self.errors.append(f"{path}: HTTP {e.code}" + (" (no such page)" if e.code in (403, 404) else ""))
            return None
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"{path}: {getattr(e, 'reason', e)}")
            return None
        self.fetched += 1
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cpath, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
        except OSError:
            pass
        return d

def cardlists(page):
    """{tag: [cardview...]} from an EDHREC page."""
    try:
        return {cl.get("tag"): cl.get("cardviews", []) for cl in page["container"]["json_dict"]["cardlists"]}
    except (KeyError, TypeError):
        return {}

def find_view(page, name):
    """The card's cardview on a commander or theme page (highest-count copy), or None."""
    best, want = None, front(name)
    for views in cardlists(page).values():
        for v in views:
            if front(v.get("name", "")) == want and (best is None or v.get("num_decks", 0) > best.get("num_decks", 0)):
                best = v
    return best

def front(name):
    """EDHREC names double-faced cards by their front face."""
    return name.split(" // ")[0].strip().lower()

def tagged(name):
    """Name plus a flag when the local data says it isn't Commander-legal (EDHREC lists
    some, e.g. Rulebreaker commanders from non-tournament sets). Partner pairs
    ('A + B') are checked per card; only exact or alias matches count."""
    flags = []
    for part in name.split(" + "):
        k, how = mtg.find(part)
        if k is None or how not in ("exact", "alias"):
            flags.append(f"{part}: not in local data" if " + " in name else "not in local data")
        elif mtg.legal(k) != "legal":
            flags.append((f"{part}: " if " + " in name else "") + mtg.legal(k).upper())
    return name + (" {" + "; ".join(flags) + "}" if flags else "")

# Scryfall tags about printing trivia, not function; they make noise in tag overlap
TRIVIA_TAG_RX = re.compile(r"^(unique |supercycle|cycle-)|achievement|reprint")

def pct(n, d):
    if not d: return "?"
    p = 100 * n / d
    return f"{p:.1f}%" if p < 10 else f"{p:.0f}%"

def syn(v):
    s = (v or {}).get("synergy")
    return f"{s * 100:+.0f}%" if isinstance(s, (int, float)) else "?"

# ---------- local data ----------
def tag_index():
    """One pass over the oracle tag file: ({oracle_id: [label]}, {label: size}).
    Only direct taggings; parent tags have none (USE_INSTRUCTIONS section 7)."""
    by_oid, size = defaultdict(list), {}
    with open(mtg.TAGS_FILE, encoding="utf-8") as fh:
        for l in fh:
            t = json.loads(l)
            oids = {x.get("oracle_id") for x in t.get("taggings", [])}
            size[t["label"]] = len(oids)
            for o in oids: by_oid[o].append(t["label"])
    return by_oid, size

def ci_ok(card_or_ci, allowed):
    if allowed is None: return True
    ci = card_or_ci if isinstance(card_or_ci, str) else "".join(card_or_ci.get("color_identity", []))
    return set(ci) <= allowed

def combo_short(v):
    """mtg.combo_line with the outcome list cut to 3 (the full list is one 'combos' call away)."""
    p = v.get("produces", [])
    more = f" (+{len(p) - 3} more)" if len(p) > 3 else ""
    return mtg.combo_line(dict(v, produces=p[:3])).replace(" | pop", more + " | pop", 1)

# ---------- sections ----------
def section_card(c, ep, ed, out):
    out.append("== 1 CARD")
    out.append(mtg.line(c))
    if mtg.legal(c) != "legal":
        out.append(f"  ! Commander legality: {mtg.legal(c)}")
    bits = []
    if c.get("edhrec_rank"): bits.append(f"EDHREC card rank #{c['edhrec_rank']}")
    if ep:
        cd = ep.get("container", {}).get("json_dict", {}).get("card", {})
        if cd.get("num_decks") is not None:
            bits.append(f"in {cd['num_decks']:,} of {cd.get('potential_decks', 0):,} eligible decks "
                        f"({pct(cd['num_decks'], cd.get('potential_decks'))})")
        if isinstance(cd.get("salt"), (int, float)):
            bits.append(f"salt {cd['salt']:.2f}")
    if bits: out.append("  " + " | ".join(bits))
    if mtg.commander_eligible(c):
        out.append(f"  can be a commander: {EDHREC_WEB}commanders/{slug(c['name'])}")
        cp = ed.get(f"commanders/{slug(c['name'])}")
        n = (cp or {}).get("container", {}).get("json_dict", {}).get("card", {}).get("num_decks")
        links = ((cp or {}).get("panels") or {}).get("taglinks") or []
        if n:
            out.append(f"  as a commander: {n:,} decks" + (" | themes: " + "; ".join(
                f"{t.get('value')} {pct(t.get('count', 0), n)}" for t in links[:8]) if links else "")
                       + (" | solo only: partner pairs have their own EDHREC pages" if "Partner" in c.get("keywords", []) else ""))
    out.append("")

def section_combos(c, allowed, lim, out):
    """Returns the list of commander-eligible combo partners (for the build-around section)."""
    out.append("== 2 COMBOS (Commander Spellbook, local data)")
    ts, vs = mtg.combos()
    if vs is None:
        out.append("  no Spellbook file in data/"); out.append(""); return []
    me = c["name"].lower()
    hits = [v for v in vs if me in {x.lower() for x in v.get("cards", [])} and ci_ok(v.get("ci", ""), allowed)]
    out.append(f"  {len(hits)} combo(s) include it" + (f" inside {''.join(sorted(allowed, key=COLORS.index)) or 'C'}" if allowed is not None else "")
               + " | " + mtg.combo_age_note(ts))
    if not hits:
        out.append(""); return []
    size = Counter(min(len(v["cards"]), 4) for v in hits)
    tags = Counter(mtg.TAG_NAMES.get(v.get("tag"), "?") for v in hits)
    out.append("  size: " + ", ".join(f"{k if k < 4 else '4+'}-card {size[k]}" for k in sorted(size))
               + " | Spellbook tag: " + ", ".join(f"{k} {n}" for k, n in tags.most_common()))
    prod = Counter(p for v in hits for p in v.get("produces", []))
    out.append("  produces: " + "; ".join(f"{p} ({n})" for p, n in prod.most_common(8)))
    reqs = Counter(t for v in hits for t in v.get("templates") or [])
    if reqs:
        out.append("  generic pieces it needs: " + "; ".join(f"{t} ({n})" for t, n in reqs.most_common(5)))
    partners, ppop = Counter(), Counter()
    for v in hits:
        for x in v["cards"]:
            if x.lower() != me:
                partners[x] += 1; ppop[x] += v.get("pop") or 0
    out.append("  recurring partners (combos | summed Spellbook popularity):")
    for x, n in sorted(partners.items(), key=lambda kv: (-kv[1], -ppop[kv[0]]))[:lim]:
        out.append(f"    {x}: {n} | pop {ppop[x]:,}")
    two = [v for v in hits if len(v["cards"]) == 2 and not v.get("templates")]
    if two:
        two.sort(key=lambda v: -(v.get("pop") or 0))
        out.append(f"  2-card combos, no generic piece ({len(two)}; bracket 3 forbids them before turn 6):")
        for v in two[:lim]: out.append("    " + combo_short(v))
    hits.sort(key=lambda v: -(v.get("pop") or 0))
    out.append("  most played:")
    for v in hits[:lim]: out.append("    " + combo_short(v))
    # commanders that are a combo piece with this card: the build-around shortcut
    cmd_rows = []
    for x, n in partners.items():
        pc, _ = mtg.find(x)
        if pc and pc["name"] == x and mtg.commander_eligible(pc) and mtg.legal(pc) == "legal" \
                and set(c.get("color_identity", [])) <= set(pc.get("color_identity", [])) and ci_ok(pc, allowed):
            cmd_rows.append((x, n, ppop[x]))
    cmd_rows.sort(key=lambda r: (-r[1], -r[2]))
    if cmd_rows:
        out.append("  commanders that are themselves a piece (card fits their colors):")
        out.append("    " + "; ".join(f"{x} ({n} combo{'s' if n > 1 else ''})" for x, n, _ in cmd_rows[:lim]))
    out.append("")
    return [r[0] for r in cmd_rows]

def section_commanders(c, ep, ed, ncmd, lim, out):
    """Returns [(name, card_decks, commander_page or None)] for the opened commanders."""
    out.append("== 3 COMMANDERS (EDHREC)")
    if ep is None:
        out.append("  no EDHREC data (offline or fetch failed); see notes at the end"); out.append(""); return []
    lists = cardlists(ep)
    top = lists.get("topcommanders", [])
    if not top:
        out.append("  EDHREC lists no commanders for this card"); out.append(""); return []
    opened = []
    out.append(f"  by decks playing it (inclusion = share of that commander's decks; synergy for the top {ncmd}):")
    for i, v in enumerate(top):
        page, sv = None, None
        if i < ncmd and v.get("url"):
            page = ed.get(v["url"].lstrip("/"))
            sv = find_view(page, c["name"]) if page else None
            opened.append((v["name"], v.get("num_decks", 0), page))
        if i < max(lim, ncmd):
            out.append(f"    {tagged(v['name'])}: {v.get('num_decks', 0):,} decks, {pct(v.get('num_decks', 0), v.get('potential_decks'))} inclusion"
                       + ((f", synergy {syn(sv)}" if sv else ", not on its page (below cutoff)") if page else ""))
    loyal = sorted((v for v in top if v.get("potential_decks", 0) >= 200),
                   key=lambda v: -v.get("num_decks", 0) / v["potential_decks"])[:5]
    out.append("  most committed (highest inclusion, 200+ decks): "
               + "; ".join(f"{tagged(v['name'])} {pct(v['num_decks'], v['potential_decks'])}" for v in loyal))
    new = lists.get("newcommanders", [])
    if new:
        out.append("  new commanders picking it up: "
                   + "; ".join(f"{tagged(v['name'])} {pct(v.get('num_decks', 0), v.get('potential_decks'))}" for v in new))
    out.append("")
    return opened

def section_strategies(c, ep, ed, opened, nthemes, out):
    out.append("== 4 STRATEGIES (EDHREC themes)")
    if not opened:
        out.append("  no commander pages opened; no theme data"); out.append(""); return []
    # Estimate decks that play the card AND run theme t: for each commander,
    # card decks x (theme decks / all decks). Assumes the card is spread evenly across that
    # commander's themes, so it's a ranking, not a count.
    est, seen_in, names, total = Counter(), Counter(), {}, 0
    for name, n, page in opened:
        if not page: continue
        cdecks = page.get("container", {}).get("json_dict", {}).get("card", {}).get("num_decks") or 0
        links = (page.get("panels") or {}).get("taglinks") or []
        if not cdecks or not links: continue
        total += n
        for t in links:
            est[t["slug"]] += n * t.get("count", 0) / cdecks
            names[t["slug"]] = t.get("value", t["slug"])
        for t in links[:5]: seen_in[t["slug"]] += 1
    if not est:
        out.append("  commander pages had no themes"); out.append(""); return []
    weight = sum(est.values())
    out.append(f"  themes of the {len(opened)} opened commanders ({total:,} decks play the card there), weighted by"
               f" those decks; % = share of theme weight, [N] = top-5 theme for N commanders:")
    ranked = est.most_common(12)
    out.append("    " + "; ".join(f"{names[s]} {100 * v / weight:.0f}% [{seen_in[s]}]" for s, v in ranked))
    out.append(f"  on the theme pages (all commanders running that theme):")
    rows = []
    for s, _ in ranked[:nthemes]:
        page = ed.get(f"tags/{s}")
        if not page:
            out.append(f"    {names[s]}: page unavailable"); continue
        v = find_view(page, c["name"])
        if v:
            rows.append((names[s], v))
            out.append(f"    {names[s]}: {pct(v.get('num_decks', 0), v.get('potential_decks'))} of theme decks, synergy {syn(v)}")
        else:
            out.append(f"    {names[s]}: not in the theme's listed cards (off-theme or under its cutoff)")
    if rows:
        best = max(rows, key=lambda r: r[1].get("synergy") or -9)
        out.append(f"  strongest theme fit by synergy: {best[0]} ({syn(best[1])})")
    out.append("")
    return [names[s] for s, _ in ranked]

def section_build(c, ep, combo_cmds, allowed, lim, out, top_names):
    out.append("== 5 BUILD-AROUND")
    lists = cardlists(ep) if ep else {}
    hl = lists.get("highliftcards", [])
    if hl:
        out.append("  high-lift cards (played with it far more than their base rate):")
        out.append("    " + "; ".join(f"{v['name']} x{v['lift']:.1f}" for v in hl[:lim] if isinstance(v.get("lift"), (int, float))))
    sim = (ep or {}).get("similar") or []
    if sim:
        out.append("  similar cards (EDHREC; redundancy or substitutes): " + "; ".join(sim[:lim]))
    # untapped commanders: share the card's rarer oracle tags, aren't in EDHREC's top list
    by_oid, size = tag_index()
    mine = [t for t in by_oid.get(c["oracle_id"], []) if 2 <= size.get(t, 0) <= 3000 and not TRIVIA_TAG_RX.search(t)]
    if mine:
        n_all = len(mtg.cards())
        want = set(c.get("color_identity", []))
        skip = {front(x) for x in top_names} | {front(c["name"])}
        scored = []
        for k in mtg.cards():
            if front(k["name"]) in skip or mtg.legal(k) != "legal" or not mtg.commander_eligible(k): continue
            if not want <= set(k.get("color_identity", [])) or not ci_ok(k, allowed): continue
            shared = [t for t in by_oid.get(k["oracle_id"], []) if t in mine]
            if shared:
                scored.append((sum(math.log(n_all / size[t]) for t in shared), k["name"], shared))
        scored.sort(key=lambda r: (-r[0], r[1]))
        out.append(f"  card's specific oracle tags: {', '.join(sorted(mine))}")
        if scored:
            out.append("  untapped commanders (share those tags, not in EDHREC's top list; colors fit):")
            for s, nm, sh in scored[:lim]:
                out.append(f"    {nm}: {', '.join(sh)}")
        else:
            out.append("  no other commander shares its specific oracle tags")
    else:
        out.append("  no specific oracle tags on this card (tags lag new sets)")
    if combo_cmds:
        out.append("  combo commanders (section 2): " + "; ".join(combo_cmds[:lim]))
    out.append("")

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 1
    opts = {"--commanders": 8, "--themes": 6, "--limit": 10}
    flags, name_parts, outfile, allowed = set(), [], None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--offline", "--refresh"):
            flags.add(a); i += 1
        elif a in opts or a in ("--ci", "--out"):
            if i + 1 >= len(argv): sys.exit(f"option {a} needs a value")
            v = argv[i + 1]
            if a == "--ci": allowed = set(v.upper().replace("C", ""))
            elif a == "--out": outfile = v
            else:
                try: opts[a] = int(v)
                except ValueError: sys.exit(f"option {a} needs a number, got '{v}'")
            i += 2
        else:
            name_parts.append(a); i += 1
    name = " ".join(name_parts)
    c, how = mtg.find(name)
    if not c:
        print(f"NOT FOUND: {name}" + (f" — {how}" if how else "")); return 1
    w = mtg.stale_warning()
    out = [w] if w else []
    out.append(f"=== EXPLORER: {c['name']}  ({date.today().isoformat()})")
    if how not in ("exact", "alias"): out.append(f"  (matched partially from '{name}')")
    ed = Edhrec(offline="--offline" in flags, refresh="--refresh" in flags)
    ep = ed.get(f"cards/{slug(c['name'])}")
    lim = opts["--limit"]
    section_card(c, ep, ed, out)
    combo_cmds = section_combos(c, allowed, lim, out)
    opened = section_commanders(c, ep, ed, opts["--commanders"], lim, out)
    section_strategies(c, ep, ed, opened, opts["--themes"], out)
    top_names = [v["name"] for v in cardlists(ep).get("topcommanders", [])] if ep else []
    section_build(c, ep, combo_cmds, allowed, lim, out, top_names)
    out.append("== NOTES")
    if ed.offline:
        out.append("  offline: EDHREC sections skipped")
    else:
        out.append(f"  EDHREC: {ed.fetched} fetched, {ed.cached} from cache | {EDHREC_WEB}cards/{slug(c['name'])}")
    for e in ed.errors: out.append(f"  ! EDHREC {e}")
    if ed.errors and ep is None:
        out.append("  ! EDHREC unreachable or name mismatch: check the page by hand (web tools) before reasoning on meta")
    out.append("  EDHREC = meta signal, not card truth. Verify any card you recommend with mtg.py card.")
    out.append("")
    out.append(REASONING_PROMPT.replace("{CARD}", c["name"]).rstrip())
    text = "\n".join(out)
    print(text)
    if outfile:
        with open(outfile, "w", encoding="utf-8") as fh: fh.write(text + "\n")
    return 0

# ---------- reasoning prompt (printed at the end of every report) ----------
REASONING_PROMPT = """
== 6 PROMPT (for the assistant)
Reason on {CARD} using only the data above, oracle text, and mtg.py lookups:
1. Engine: what resource does it make or convert (mana, cards, bodies, life, counters,
   triggers, damage, tempo), and what does it need fed to it? One sentence.
2. Read the field: staple (high inclusion, low synergy) or build-around (high synergy,
   few commanders)? What do the top commanders, themes, and combo outputs have in common?
3. Three homes on different axes: (a) the proven one from the data; (b) an underplayed
   one: untapped or combo commanders, or a theme where synergy beats inclusion; (c) an
   off-label angle from the rules text the data doesn't show (a different payoff, a
   nonbo flipped into a feature, an unusual enabler).
4. For each: commander(s), a 5-8 card core (verify every name with mtg.py card), how it
   wins, what it folds to, and the likely bracket (2-card combos, Game Changers).
5. Verdict and risks in two lines, then one question for the user whose answer would
   change the pick (colors, bracket, budget, a pet card).
Tie claims to the numbers above; label guesses as guesses.
"""

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
