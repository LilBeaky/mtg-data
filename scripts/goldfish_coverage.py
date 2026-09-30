#!/usr/bin/env python3
"""goldfish_coverage.py — how much of the Commander card pool goldfish.py's parser reads, and what a parser change did.

  report [--top N]          status table (raw and popularity-weighted), compile errors, biggest miss clusters,
                            most-played blank/partial cards
  diff [REF]                every card whose goldfish reading changed between git REF (default HEAD) and the
                            working tree: status transitions, then the changed readings, most-played first
        [--limit N | --all] how many changed readings to print (default 60)
  card NAME [NAME ...]      the --explain line for any cards, no deck file needed

Readings are the exact --explain lines, with goldfish_overrides.json applied (the working tree's overrides on both
sides of a diff). Popularity weight = 1/sqrt(edhrec_rank); unranked cards weigh 0. See docs/GOLDFISH_ROADMAP.md.
"""
import contextlib, io, math, os, re, subprocess, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANYC = frozenset("WUBRG")
CHUNK = 400                      # explain() counts tutor hits within the chunk; that text is stripped below
LINE = re.compile(r"^(\S+)\s+(\S+)\s+(.+?) — (.*)$")

def load(scripts_dir):
    sys.path.insert(0, scripts_dir)
    import mtg, goldfish as g
    return mtg, g

def readings(scripts_dir=HERE):
    """name -> (status, rank, reading) for every Commander-legal card; plus [(name, error)]."""
    mtg, g = load(scripts_dir)
    ov = g.load_overrides()
    seen, cache, errs, ranks = set(), {}, [], {}
    for c in mtg.cards():
        if mtg.legal(c) != "legal" or c["name"] in seen: continue
        seen.add(c["name"])
        try:
            k = g.compile_card(c, ANYC)
            o = ov.get(mtg.norm(c["name"]))
            if o: g.apply_override(k, o, ANYC)
        except Exception as e:
            errs.append((c["name"], f"{type(e).__name__}: {e}"[:100])); continue
        cache[c["name"]] = k; ranks[c["name"]] = c.get("edhrec_rank")
    out, names = {}, list(cache)
    for i in range(0, len(names), CHUNK):
        part = names[i:i + CHUNK]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g.explain({n: cache[n] for n in part}, part, [])
        for ln in buf.getvalue().splitlines():
            m = LINE.match(ln)
            if m and m.group(3) in cache:
                out[m.group(3)] = (m.group(1), ranks[m.group(3)], re.sub(r", \d+ in list", "", m.group(4)))
    return out, errs

def weight(rank): return 1 / math.sqrt(rank) if rank else 0.0

def norm_line(l):
    l = l.lower().strip(); l = re.sub(r"\{[^}]+\}", "{M}", l)
    return re.sub(r"\b(\d+|x|a|an|one|two|three|four|five|up to one|up to two)\b", "N", l)

def cluster_key(note):
    """An unmodeled line -> its effect's first two words ('destroy target', 'put N'), past any cost or trigger frame."""
    b = norm_line(note)
    if ":" in b and b.index(":") < 40: b = b.split(":", 1)[1].strip()
    elif b.startswith(("when", "whenever", "at the")) and "," in b: b = b.split(",", 1)[1].strip()
    b = re.sub(r"^(you may|then|if you do,?)\s*", "", b)
    return " ".join(b.split()[:2])

def report(top):
    data, errs = readings()
    nonland = {n: v for n, v in data.items() if v[0] != "land"}          # land* (a land with an unread line) stays in
    st, sw = Counter(), Counter()
    for s, r, _ in nonland.values(): st[s] += 1; sw[s] += weight(r)
    tot, totw = sum(st.values()), sum(sw.values()) or 1
    print(f"{len(data)} Commander-legal cards ({len(data) - len(nonland)} lands), {len(errs)} compile errors\n")
    print(f"{'status':<9}{'cards':>7}{'share':>8}{'weighted':>10}")
    for s, n in st.most_common(): print(f"{s:<9}{n:>7}{100 * n / tot:>7.1f}%{100 * sw[s] / totw:>9.1f}%")
    if st["land*"]: print("land* = a land with an unmodeled line (Bojuka Bog, Boseiju); plain lands are left out")
    read = sum(sw[s] for s in ("modeled", "held", "vacuum", "override"))
    print(f"\nfully read (modeled + held + vacuum + override), weighted: {100 * read / totw:.1f}%")
    for n, e in errs: print(f"  ! {n}: {e}")
    cc, cw, ex = Counter(), Counter(), {}
    for n, (s, r, rd) in nonland.items():
        notes = re.findall(r"(?:unmodeled|unread part): ([^\]]+?)(?=; |\]|$)", rd)
        notes += ["kw " + w for kn in re.findall(r"keyword not modeled: ([^;\]]+)", rd) for w in kn.split(", ")]
        for note in notes:
            k = note if note.startswith("kw ") else cluster_key(note); cc[k] += 1; cw[k] += weight(r)
            if k not in ex or (r or 1e9) < (nonland[ex[k]][1] or 1e9): ex[k] = n
    cwt = sum(cw.values()) or 1
    print(f"\nbiggest miss clusters (by effect; share of weighted unmodeled lines):")
    for k, v in cw.most_common(top): print(f"  {100 * v / cwt:4.1f}%  {cc[k]:5}  {k:<26} e.g. {ex[k]}")
    worst = sorted((r, n, s) for n, (s, r, _) in nonland.items() if r and s in ("blank", "partial"))[:top]
    print(f"\nmost-played blank/partial: " + ", ".join(f"{n} ({s[0]})" for _, n, s in worst))

def dump(path, scripts_dir):
    data, errs = readings(scripts_dir)
    with open(path, "w", encoding="utf-8") as f:
        for n, (s, r, rd) in data.items(): f.write(f"{n}\t{s}\t{r or ''}\t{rd}\n")
        for n, e in errs: f.write(f"{n}\tERROR\t\t{e}\n")

def read_dump(path):
    out = {}
    for ln in open(path, encoding="utf-8"):
        n, s, r, rd = ln.rstrip("\n").split("\t", 3)
        out[n] = (s, int(r) if r else None, rd)
    return out

def diff(ref, limit):
    with tempfile.TemporaryDirectory() as tmp:
        arch = subprocess.run(["git", "-C", ROOT, "archive", ref, "scripts"], capture_output=True)
        if arch.returncode: sys.exit(f"git archive {ref}: {arch.stderr.decode().strip()}")
        subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
        os.symlink(os.path.join(ROOT, "data"), os.path.join(tmp, "data"))
        a, b = os.path.join(tmp, "old.tsv"), os.path.join(tmp, "new.tsv")
        for scripts, out in ((os.path.join(tmp, "scripts"), a), (HERE, b)):
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "_dump", out, scripts], capture_output=True, text=True)
            if r.returncode: sys.exit(f"dump failed ({scripts}):\n{r.stderr[-2000:]}")
        old, new = read_dump(a), read_dump(b)
    trans, changed = Counter(), []
    for n in sorted(set(old) | set(new)):
        o, w = old.get(n, ("absent", None, "")), new.get(n, ("absent", None, ""))
        if o[0] != w[0]: trans[(o[0], w[0])] += 1
        if o[0] != w[0] or o[2] != w[2]: changed.append((w[1] or o[1] or 10 ** 9, n, o, w))
    print(f"{ref} -> working tree: {len(changed)} cards changed reading, {sum(trans.values())} changed status")
    for (x, y), n in trans.most_common(): print(f"  {x:>8} -> {y:<8} {n}")
    changed.sort()
    for _, n, o, w in changed[:limit]:
        print(f"\n{n}  [{o[0]} -> {w[0]}]\n  - {o[2]}\n  + {w[2]}")
    if len(changed) > limit: print(f"\n... {len(changed) - limit} more (--all)")

def card(names):
    mtg, g = load(HERE)
    idx, ov, cache, found = mtg.index(), g.load_overrides(), {}, []
    for n in names:
        c = idx.get(mtg.norm(n)) or idx.get(n.lower())
        if not c: print(f"NOT FOUND: {n}"); continue
        k = g.compile_card(c, ANYC)
        o = ov.get(mtg.norm(c["name"]))
        if o: g.apply_override(k, o, ANYC)
        cache[c["name"]] = k; found.append(c["name"])
    if found: g.explain(cache, found, [])

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(0)
    if a[0] == "report": report(int(a[a.index("--top") + 1]) if "--top" in a else 25)
    elif a[0] == "diff":
        pos = [x for x in a[1:] if not x.startswith("--") and not (a[a.index(x) - 1] == "--limit")]
        lim = 10 ** 9 if "--all" in a else int(a[a.index("--limit") + 1]) if "--limit" in a else 60
        diff(pos[0] if pos else "HEAD", lim)
    elif a[0] == "card": card(a[1:])
    elif a[0] == "_dump": dump(a[1], a[2])
    else: print(__doc__); sys.exit(2)
