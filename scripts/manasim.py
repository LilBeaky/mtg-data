#!/usr/bin/env python3
"""
manasim.py — mana development with ramp: when can you cast your commander and key cards?

Plays the deck's lands and acceleration through goldfish.py's game engine (same card reading,
same mulligans, same land choice) with every other card inert, and asks each turn whether
each target could be cast that turn by the best line the pilot finds: as is, after casting
ramp first (Sol Ring, then the commander), or with a ritual. Cost reducers count only
where their filter matches the target (Dragonspeaker Shaman for a Dragon, Emerald
Medallion for a green spell).

  python3 scripts/manasim.py DECK [options]            (run from the repo root)

  --commander NAME   if the list has no Commander section
  --draw             on the draw (default: on the play)
  --turns N          turns per game (default 8)
  --trials N         games (default 3000)
  --seed N           RNG seed (default 1)
  --target NAME      also report this card (repeatable); the commander and '# key:' cards
                     are always targets
  --lands N          play N lands: basics added or cut against inert cards (ramp is kept)

REPORT
  1 Development   lands and mana at the start of each main phase; P(T mana by turn T)
  2 Castable by   per target, P(castable by turn T) with ramp, with lands only, with card draw
                  and tutors played too (tutor mode), and with ramp when every land drop was hit
                  (to check by hand)
  3 Coverage      every card counted as acceleration, and how goldfish.py reads it;
                  partial readings named; what is not counted (draw, tutors)

Shared with landbase.py (land-count table) and audit.py (section 3).
"""
import argparse, os, random, sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import mtg
import stats_math as sm

gf = sm._gf()
BASIC_OF = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
COMBAT_EVENTS = {"attack", "attack_self", "attack_att", "attack_any", "combat_begin", "blocked", "dmg_att", "cdmg", "cdmg_att", "cdmg_any"}


# ---------------------------------------------------------------- what counts as acceleration
def _land_search_act(a):
    return any(e[0] in ("land_search", "land_from_hand") for e in gf.flat(a["fx"]))

def accelerates(k):
    """goldfish.py's own ramp category (mana producers, land search, extra land drops, cost
    reducers, free/alt casting, mana doublers, Treasure), plus rituals (one-turn mana)."""
    return not k.is_land and (k.cat == "ramp" or k.ritual)

def plays_in_tutor_mode(k):
    """Tutor mode also plays card flow: goldfish.py's draw category (draw, look, tutors, wheels, recursion to hand)
    and any card with a tutor effect anywhere (ETB, cycling, transmute, activated)."""
    return not k.is_land and (k.cat == "draw" or any(e[0] in ("tutor", "tutor_multi") for e in gf.all_fx(k)))


def why(k):
    """Short reading of what makes k acceleration, for the coverage list."""
    out = []
    fx = gf.all_fx(k)
    if k.units:
        n = len(k.units); cols = "".join(sorted(set().union(*(u[0] | u[1] for u in k.units)) - {"C"})) or "C"
        out.append(f"+{n} {cols}" + (" (creature)" if "Creature" in k.types else ""))
    if k.dyn_mana: out.append("scaling mana")
    if k.convs: out.append("filter")
    for e in fx:
        if e[0] == "land_search":
            out.append(f"land search x{e[1]}" + {"bf_t": " tapped", "bf": " untapped", "hand": " to hand", "top": " to the top",
                                                 "split": " (one tapped, one to hand)"}.get(e[3], f" ({e[3]})"))
        elif e[0] == "treasure": out.append("Treasure")
        elif e[0] == "reveal_lands": out.append("lands from the top")
        elif e[0] == "land_from_hand": out.append("land from hand")
        elif e[0] == "extra_land": out.append("extra land drop")
    for s in k.statics:
        t = s[0]
        if t == "reduce":
            f = {a: v for a, v in s[1].items() if v not in (set(), False, None, 0, frozenset())}
            out.append(f"reduce {s[2]} ({_filter_txt(f)})")
        elif t in ("free", "alt"): out.append(f"{'free' if t == 'free' else 'alt cost'} ({_filter_txt({a: v for a, v in s[1].items() if v not in (set(), False, None, 0, frozenset())})})")
        elif t == "extra_land": out.append("extra land drop")
        elif t in ("mana_mult", "mana_add"): out.append("mana doubler" if t == "mana_mult" else "extra mana")
        elif t == "reduce_dyn": out.append("scaling reducer")
        elif t in ("lands_any", "spend_any"): out.append("fixing")
    if k.ritual: out.append("ritual")
    if k.sac_outlets: out.append("sacrifice for mana")
    if k.untapper: out.append("untaps a mana source")
    if getattr(k, "cond_units", None): out.append("conditional mana")
    if k.imprint: out.append("imprint mana")
    return "; ".join(dict.fromkeys(out)) or "ramp (other)"

def _filter_txt(f):
    if not f: return "all spells"
    parts = []
    if f.get("colors"): parts.append("/".join(sorted(f["colors"])))
    if f.get("sub"): parts.append("/".join(sorted(f["sub"])))
    if f.get("types"): parts.append("/".join(sorted(f["types"])))
    if f.get("pow_min"): parts.append(f"power {f['pow_min']}+")
    if f.get("first"): parts.append("first each turn")
    if f.get("non"): parts.append("non" + "/".join(sorted(f["non"])))
    rest = [a for a in f if a not in ("colors", "sub", "types", "pow_min", "first", "non")]
    return " ".join(parts + rest)


# ---------------------------------------------------------------- fidelity: are the deck's ramp, draw and tutors played?
ROLE_TAGS = {
    "ramp": {"ramp", "mana-rock", "mana-dork", "extra-land", "cost-reducer", "ritual", "land-ramp"},
    "draw": {"draw", "card-advantage", "pure-draw", "repeatable-pure-draw", "draw-engine", "repeatable-draw", "wheel"},
}
ROLE_NAMES = {"ramp": "ramp", "draw": "card draw", "tutor": "tutors"}

def card_roles(c):
    """The roles a card plays by Scryfall's oracle tags (an independent answer key), plus tutors.py's own reader
    for tutors: {'ramp', 'draw', 'tutor'} subset."""
    import tutors as tu
    tags = tu._tags_by_oid().get(c.get("oracle_id"), set())
    roles = {r for r, ts in ROLE_TAGS.items() if tags & ts}
    if any((t == "tutor" or t.startswith("tutor-")) and t not in ("tutor-interaction", "tutor-from-opponent") for t in tags) \
            or tu.card_tutors(c):
        roles.add("tutor")
    return roles

def role_coverage(deck, mode="tutors"):
    """For the deck's ramp, card draw and tutor cards (card_roles): how many the games play (mode 'ramp': ramp only;
    'tutors': ramp and card flow). Returns {"counts": {role: (played, total)}, "unplayed": [(name, roles, status)]}."""
    N, lib, cmdrs, anyc, keys = deck
    counts = {r: [0, 0] for r in ("ramp", "draw", "tutor")}
    unplayed = []
    for q, c, k in list(lib) + [(1, c, k) for c, k in cmdrs]:
        if k.is_land: continue
        roles = card_roles(c)
        if mode == "ramp": roles &= {"ramp"}
        if not roles: continue
        plays = accelerates(k) or (mode == "tutors" and (plays_in_tutor_mode(k) or any(map(_card_flow_act, k.hand_acts))))
        for r in roles:
            counts[r][1] += q
            if plays: counts[r][0] += q
        if not plays: unplayed.append((c["name"], sorted(roles), k.status))
    return {"counts": {r: tuple(v) for r, v in counts.items() if v[1]}, "unplayed": sorted(unplayed)}

def fidelity_line(cov):
    """'fidelity: ramp 9/11 played, card draw 2/14, tutors 11/11; not played: ...' (every unplayed card named; empty when
    there's nothing to say)."""
    if not cov["counts"]: return ""
    parts = [f"{ROLE_NAMES[r]} {p}/{t}" for r, (p, t) in cov["counts"].items()]
    un = cov["unplayed"]
    tail = ("; not played: " + "; ".join(f"{n} ({'/'.join(ROLE_NAMES[r] for r in rs)}, {st})" for n, rs, st in un)) if un else "; all played"
    return "fidelity (Scryfall's role tags as the key): " + ", ".join(parts) + " played" + tail


# ---------------------------------------------------------------- the game
class ManaGame(gf.Game):
    """A goldfish game that records land drops and probes the targets at the start of each main phase."""
    def __init__(self, sim, hand, lib, rng, targets):
        super().__init__(sim, hand, lib, rng)
        self.probe_tg = targets                  # [(name, Card, zone)]
        self.first_ok = {}                        # name -> first turn castable
        self.land_drops = 0; self._probed = 0; self.drops_by = {}
        self.found_tg = []; self.found_first = {}    # tutor mode: [(name, Card)]; name -> first turn it left the library

    def check_found(self):
        """A key card is found once it has left the library (drawn, tutored to hand or battlefield): checked at the
        start of each main phase, after each cast loop and at the end of the turn."""
        for name, k in self.found_tg:
            if name not in self.found_first and k not in self.lib: self.found_first[name] = self.turn

    def opponents(self):
        if self.found_tg: self.check_found()
        super().opponents()

    def play_land(self, k):
        self.land_drops += 1
        super().play_land(k)

    def stranded(self): return 0                 # card-flow bookkeeping: not reported here

    def choose_land(self):
        """goldfish.py's land choice, except when another land in hand makes a target castable this turn and its
        pick doesn't (Plains over a tapped Rustvale Bridge for a T2 commander). In goldfish.py the commander sits in
        the command zone and its land choice sees that; here the targets are only probed, so this says it."""
        pick = super().choose_land()
        if self.dry or not pick: return pick
        # the commander first (goldfish.py's cast order): key cards steer the land only once it's castable, so a
        # 1-drop key card never spends the untapped land the commander needs next turn
        open_ = [(n, k, z) for n, k, z in self.probe_tg if n not in self.first_ok]
        want = [(k, z) for n, k, z in open_ if z == "cmd"] or [(k, z) for n, k, z in open_]
        lands = [k for k in dict.fromkeys(self.hand) if k.is_land]
        if not want or len(lands) < 2: return pick
        def score(land):
            g = self.clone(); g.dry = True
            g.play_land(land); g.build_pool()
            return sum(1 for k, z in want if any(g.pay(k, gg, pp, commit=False) for gg, pp in g.options(k, "cmd")))
        s0 = score(pick)
        best = max(lands, key=score)
        return best if score(best) > s0 else pick

    def combat(self):
        """Combat only when an accelerant has a combat trigger (a Treasure on attack); otherwise nothing to learn."""
        if self.sim.mana_combat: super().combat()
        else: self.combat_done = True

    script = None                                 # line(): the scripted draws, kept on top through shuffles
    def draw(self, n, name=None):
        for _ in range(n):
            if self.script and not self.dry:
                k = self.script.pop(0)
                if k in self.lib: self.lib.remove(k); self.lib.append(k)
            super().draw(1, name)

    def cast_loop(self, activate=True):
        if self._probed != self.turn and self.pool is not None:
            self._probed = self.turn
            self.drops_by[self.turn] = self.land_drops
            for name, k, zone in self.probe_tg:
                if name not in self.first_ok and self.castable(k, zone): self.first_ok[name] = self.turn
        if self.found_tg: self.check_found()
        super().cast_loop(activate)
        if self.found_tg and not self.dry: self.check_found()

    def castable(self, k, zone):
        """Could the pilot cast k this turn? First as is; then in a copy of the game where k is the top priority,
        so ramp that pays for itself this turn (Sol Ring), a reducer, or a ritual can come first."""
        opts = self.options(k, "cmd")
        if any(self.pay(k, g, p, commit=False) for g, p in opts): return True
        if not any(c.cat == "ramp" or c.ritual for c in self.hand): return False
        g = self.clone(); g.dry = True
        g.build_pool()                            # the copy's own permanents: probing never taps the real game's
        g.cmd = [k]; g.cmd_casts = gf.Counter()
        g.cast_loop(activate=False)
        return k not in g.cmd


def _card_flow_act(a):
    """A hand ability that is card flow: cycling's draw, typecycling and transmute's search."""
    return any(e[0] in ("tutor", "draw") for e in gf.flat(a["fx"]))

def _inert(k, keep_tutor_acts=False):
    """A stand-in for a card that doesn't play here: same mana value (mulligans see the same hand), never cast;
    landcycling kept (it finds a land drop), and in tutor mode every card-flow hand ability (cycling, typecycling,
    transmute: a held counterspell still cycles). goldfish.py values an inert card low, so spare mana at the end of
    the turn cycles it. Tutors still find it by its card (raw), so a key card that isn't played can be fetched and
    counted as found."""
    if k.status == "inert": return k
    f = gf.Card(k.name + " (inert)")
    f.mv = k.mv; f.gen = 99; f.raw = k.raw; f.status = "inert"
    f.hand_acts = [a for a in k.hand_acts if _land_search_act(a) or (keep_tutor_acts and _card_flow_act(a))]
    return f


def load(path, commander=None):
    """Compiled deck: (N, lib [(qty, card, Card)], commanders [(card, Card)], anyc, keys [names])."""
    entries = mtg.parse_deck(path)
    N, cmd_names, _ = sm.count_population(path, commander)
    cmd_cards = [c for c in (mtg.find(n)[0] for n in cmd_names) if c]
    lib_cards = [(q, mtg.find(n)[0]) for s, q, n in entries if s not in sm.EXCLUDED_FROM_POPULATION and mtg.find(n)[0]]
    gf.CHOSEN_TYPE = gf.chosen_type(cmd_cards, [c for _, c in lib_cards])
    N, lib, cmdrs, anyc = sm._deck(path, commander)
    overrides = gf.load_overrides()
    for _, c, k in lib + [(0,) + x for x in cmdrs]:
        ov = overrides.get(mtg.norm(c["name"]))
        if ov and not k.override: gf.apply_override(k, ov, anyc)
    meta = mtg.parse_deck_meta(path)
    keys = []
    for v in (meta.get("key") or "").replace(" + ", ";").split(";"):
        c = mtg.find(v.strip())[0] if v.strip() else None
        if c: keys.append(c["name"])
    return N, lib, cmdrs, anyc, keys


def _land_plan(lib, anyc, delta):
    """(add basics {name: n}, cut {card name: n}) to change the land count by delta. Adds follow the
    deck's basics (or its colors); cuts take basics first, most numerous first."""
    if not delta: return {}, {}
    basics = {c["name"]: q for q, c, k in lib if k.is_land and k.basic}
    if delta > 0:
        pool = sorted(basics.items(), key=lambda x: -x[1]) or [(BASIC_OF[c], 1) for c in sorted(anyc) if c in BASIC_OF]
        tot = sum(q for _, q in pool) or 1
        add = {}
        for i in range(delta):                      # largest remainder over the existing mix
            best = max(pool, key=lambda x: x[1] / tot * (i + 1) - add.get(x[0], 0))
            add[best[0]] = add.get(best[0], 0) + 1
        return add, {}
    cut, left = {}, dict(basics)
    for _ in range(-delta):
        if not any(left.values()): break
        n = max(left, key=lambda x: left[x]); left[n] -= 1; cut[n] = cut.get(n, 0) + 1
    return {}, cut


def compile_named(name, anyc):
    """A card by name, compiled as goldfish.py would (overrides applied)."""
    c = mtg.find(name)[0]
    if not c: raise ValueError(f"card not found: {name}")
    k = gf.compile_card(c, anyc)
    ov = gf.load_overrides().get(mtg.norm(c["name"]))
    if ov: gf.apply_override(k, ov, anyc)
    return c["name"], k


def build(deck, on_play=True, land_delta=0, extra_targets=(), add_cards=(), cut_cards=(), mode="ramp",
          inert_names=(), want=None):
    """The mana-only goldfish Sim for a loaded deck: lands and accelerants real, the rest inert.
    land_delta adds basics (or cuts them); cut_cards come out by name, add_cards go in. Every change takes
    one existing slot in place (a cut card's slot first, then an inert card's from the end), so every run
    with the same seed deals the same games except for the changed cards.
    mode "tutors" also plays card flow (plays_in_tutor_mode); inert_names are made inert whatever they are
    (a tutor taken out, for its worth). want = (your key names, packages [(label, [[names] per part])],
    inferred key names): goldfish.py's tutor priorities, as in a goldfish run.
    Returns (sim, targets [(name, Card, zone)], names, cache, add, cut)."""
    N, lib, cmdrs, anyc, keys = deck
    add, cut = _land_plan(lib, anyc, land_delta)
    tutors_on = mode == "tutors"
    real = lambda k: k.is_land or accelerates(k) or (tutors_on and plays_in_tutor_mode(k))
    names, cache = [], {}
    for q, c, k in lib:
        if c["name"] in inert_names: cache[c["name"]] = _inert(k, False)     # taken out: its tutoring goes too
        else: cache[c["name"]] = k if real(k) else _inert(k, tutors_on)
        names += [c["name"]] * q
    open_slots = []                                     # slots of cut cards
    for n in [n for n, q in cut.items() for _ in range(q)] + list(cut_cards):
        idx = [j for j, x in enumerate(names) if x == n]
        if not idx: raise ValueError(f"not in the deck to cut: {n}")
        names[idx[-1]] = None; open_slots.append(idx[-1])
    # slots an added card may take: inert cards that aren't key cards or targets (taking a key card's slot would
    # remove it from the library, and a key card out of the library counts as found)
    protected = set(keys) | set(extra_targets)
    if want: protected |= set(want[0]) | set(want[2]) | {x for _, parts in want[1] for part in parts for x in part}
    # ...and that keep no hand ability (an inert landcycler still finds lands; taking its slot would cost land drops)
    inert_slots = [i for i, x in enumerate(names) if x is not None and cache[x].status == "inert" and x not in protected
                   and not cache[x].hand_acts]
    new = [n for n, q in add.items() for _ in range(q)] + list(add_cards)
    for n in new:
        if n not in cache:
            if n in add: cache[n] = gf.compile_card(mtg.find(n)[0], anyc)
            else: n2, k2 = compile_named(n, anyc); cache[n] = k2
        if open_slots: names[open_slots.pop(0)] = n
        elif inert_slots: names[inert_slots.pop()] = n
        else: names.append(n)
    if open_slots or len(names) < N:                    # a cut with nothing added: an inert card takes the slot
        filler = gf.Card("(inert filler)"); filler.gen = 99; filler.mv = 3; filler.status = "inert"
        cache["(inert filler)"] = filler
        for i in open_slots: names[i] = "(inert filler)"
        names += ["(inert filler)"] * (N - len(names))
    names = [x for x in names if x is not None]
    acc_cmd = [c["name"] for c, k in cmdrs if accelerates(k) or (tutors_on and plays_in_tutor_mode(k))]
    for c, k in cmdrs: cache[c["name"]] = k
    args = SimpleNamespace(order=gf.ORDER_DEFAULT, draw=not on_play, kill_commander=0, cast_interaction=False,
                           no_mulligan=False, trace=0, board_spec=[])
    gwant = None
    if want:
        yours, packages, inferred = want
        objs = lambda ns: {cache[n] for n in ns if n in cache}
        gwant = (objs(yours), [[objs(part) for part in parts] for _, parts in packages if parts], objs(inferred))
    sim = gf.Sim(names, acc_cmd, args, [], cache, anyc, want=gwant)
    sim.mana_combat = any(t[0] in COMBAT_EVENTS for n in set(names) | set(acc_cmd) for t in cache[n].trig
                          if cache[n].status != "inert")
    # targets: commanders, key cards, extras
    by_name = {c["name"]: getattr(k, "orig", k) for _, c, k in lib}
    by_name.update({c["name"]: k for c, k in cmdrs})
    tg, seen = [], set()
    for c, k in cmdrs: tg.append((c["name"], k, "cmd")); seen.add(c["name"])
    for n in list(keys) + list(extra_targets):
        c = mtg.find(n)[0]
        if not c or c["name"] in seen: continue
        k = by_name.get(c["name"]) or gf.compile_card(c, anyc)
        if k.is_land: continue
        tg.append((c["name"], k, "hand")); seen.add(c["name"])
    return sim, tg, names, cache, add, cut


# MTG_TRIALS_CAP=N caps every run's games (tests/smoke.py sets it: the smoke test checks that the tools run and
# print their sections, not their precision). Every manasim.py game, so landbase.py's, tutors.py's played columns
# and the audit's, goes through simulate().
TRIALS_CAP = int(os.environ.get("MTG_TRIALS_CAP") or 0)

def simulate(path, commander=None, on_play=True, trials=3000, turns=8, seed=1, land_delta=0, extra_targets=(), deck=None,
             add_cards=(), cut_cards=(), mode="ramp", inert_names=(), want=None):
    """Run the mana-only games. Returns a dict: lands, N, dev (P(T mana by T)), mana/lands medians,
    targets {name: {"mv", "zone", "by": {t: p}, "by_hit": {t: (p, share of games)}, "median"}}, coverage."""
    if TRIALS_CAP: trials = min(trials, TRIALS_CAP)
    deck = deck or load(path, commander)
    N, lib, cmdrs, anyc, keys = deck
    sim, tg, names, cache, add, cut = build(deck, on_play, land_delta, extra_targets, add_cards, cut_cards, mode,
                                            inert_names, want)
    T = range(1, turns + 1)
    found_names = []
    if want:
        for n in list(want[0]) + list(want[2]) + [x for _, parts in want[1] for part in parts for x in part]:
            if n in cache and n not in found_names and not cache[n].is_land: found_names.append(n)
    found_tg = [(n, cache[n]) for n in found_names]
    found = {n: [] for n in found_names}
    first = {n: [] for n, _, _ in tg}
    hit = {n: [] for n, _, _ in tg}
    mana = {t: [] for t in T}; lands = {t: [] for t in T}
    for i in range(trials):
        rng = random.Random(seed * 1_000_003 + i)
        hand, libr, size, mulls = sim.opening(rng)
        g = ManaGame(sim, hand, libr, rng, tg)
        g.found_tg = found_tg
        rec = gf.blank_rec(turns)
        g.play(turns, rec)
        for n in found_names: found[n].append(g.found_first.get(n))
        for t in T:
            mana[t].append(rec["mana"][t][-1]); lands[t].append(rec["lands"][t][-1])
        full = next((t - 1 for t in T if g.drops_by.get(t, 0) < t), turns)
        for n, _, _ in tg:
            first[n].append(g.first_ok.get(n)); hit[n].append(full)
    out = {"lands": sum(1 for n in names if cache[n].is_land), "N": len(names), "trials": trials, "turns": turns,
           "dev": {t: sum(1 for m in mana[t] if m >= t) / trials for t in T},
           "mana_med": {t: sorted(mana[t])[trials // 2] for t in T},
           "lands_med": {t: sorted(lands[t])[trials // 2] for t in T}, "targets": {}, "add": add, "cut": cut}
    for n, k, zone in tg:
        f = first[n]
        by = {t: sum(1 for x in f if x is not None and x <= t) / trials for t in T}
        pairs = [(x, h) for x, h in zip(f, hit[n])]
        by_hit = {}
        for t in T:
            pool = [x for x, h in pairs if h >= t]
            by_hit[t] = (sum(1 for x in pool if x is not None and x <= t) / len(pool), len(pool) / trials) if pool else (None, 0)
        out["targets"][n] = {"mv": k.mv, "gen": k.gen, "pips": k.pips, "zone": zone, "by": by, "by_hit": by_hit,
                             "median": _median_turn(f, turns), "first": f}
    out["coverage"] = coverage(lib, cmdrs)
    if want:
        by = lambda f, t: sum(1 for x in f if x is not None and x <= t) / trials
        out["found"] = {n: {"by": {t: by(f, t) for t in T}, "first": f} for n, f in found.items()}
        asm = []
        for label, parts in want[1]:
            per = []
            for i in range(trials):
                turns_ = [min((found[x][i] for x in part if x in found and found[x][i] is not None), default=None) for part in parts]
                per.append(None if not parts or any(x is None for x in turns_) else max(turns_))
            asm.append({"label": label, "by": {t: by(per, t) for t in T}, "first": per})
        out["assembled"] = asm
    return out


def line(deck, hand, draws, turns=6, on_play=True, extra_targets=()):
    """A scripted game: this opening hand, then these draws in order (the rest of the library after them,
    shuffled). Returns (first castable turn per target, play-by-play)."""
    sim, tg, names, cache, add, cut = build(deck, on_play, 0, extra_targets)
    def card(n):
        c = mtg.find(n)[0]
        if not c: sys.exit(f"not found: {n}")
        if c["name"] not in cache: sys.exit(f"not in the deck: {c['name']}")
        return cache[c["name"]]
    h = [card(n) for n in hand]; d = [card(n) for n in draws]
    rest = list(sim.deck)
    for k in h + d:
        if k in rest: rest.remove(k)
    random.Random(0).shuffle(rest)
    g = ManaGame(sim, h, rest + d, random.Random(0), tg)
    g.script = list(d); g.log = []
    g.play(turns, gf.blank_rec(turns))
    return g.first_ok, g.log


def _median_turn(f, turns):
    xs = sorted(x if x is not None else turns + 1 for x in f)
    m = xs[len(xs) // 2]
    return m if m <= turns else None


def coverage(lib, cmdrs):
    rows, other = [], {"draw": 0, "tutor": 0}
    for q, c, k in list(lib) + [("cmdr", c, k) for c, k in cmdrs]:
        if k.is_land: continue
        if accelerates(k):
            rows.append((c["name"], k.mv, k.status, why(k), q))
        elif k.cat == "draw" and q != "cmdr":
            other["draw"] += q
            if any(e[0] == "tutor" for e in gf.all_fx(k)): other["tutor"] += q
    return {"rows": sorted(rows, key=lambda r: (r[1], r[0])), "other": other}


# ---------------------------------------------------------------- report
def pct(p): return "  —  " if p is None else f"{100 * p:5.1f}%"

def report(res, on_play, lands_only=None, with_draw=None):
    T = range(1, res["turns"] + 1)
    print(f"## 1. Development ({res['lands']} lands; lands / mana at the start of each main phase, medians)")
    print("  turn  " + "".join(f"{'T' + str(t):>7}" for t in T))
    print("  lands " + "".join(f"{res['lands_med'][t]:>7}" for t in T))
    print("  mana  " + "".join(f"{res['mana_med'][t]:>7}" for t in T))
    print("  T by T" + "".join(f"{pct(res['dev'][t]):>7}" for t in T) + "   (T mana by turn T)")
    print(f"\n## 2. Castable by (best line: ramp first, reducers that match, rituals; {res['trials']:,} games)")
    for n, r in res["targets"].items():
        tag = " [commander]" if r["zone"] == "cmd" else ""
        print(f"  {n}{tag}  (MV {r['mv']}; median T{r['median'] or '>' + str(res['turns'])})")
        print("      with ramp     " + " | ".join(f"T{t} {pct(r['by'][t])}" for t in T if t >= 2))
        if lands_only and n in lands_only["targets"]:
            lo = lands_only["targets"][n]
            print("      lands only    " + " | ".join(f"T{t} {pct(lo['by'][t])}" for t in T if t >= 2))
        if with_draw and n in with_draw["targets"]:
            wd = with_draw["targets"][n]
            print("      +draw, tutors " + " | ".join(f"T{t} {pct(wd['by'][t])}" for t in T if t >= 2)
                  + "   (card draw and tutors played too)")
        print("      drops all hit " + " | ".join(f"T{t} {pct(r['by_hit'][t][0])}" for t in T if t >= 2)
              + "   (games that hit every land drop through that turn)")
    cov = res["coverage"]
    print(f"\n## 3. Coverage (acceleration the games use: {len(cov['rows'])} cards)")
    for n, mv, st, w, q in cov["rows"]:
        flag = "" if st == "modeled" else f"  ⚠ {st}"
        print(f"  MV{mv} {n}: {w}{flag}")
    part = [r[0] for r in cov["rows"] if r[2] != "modeled"]
    if part: print(f"  read partially by goldfish.py (--explain shows how): {'; '.join(part)}")
    o = cov["other"]
    print(f"  not counted in 'with ramp': card draw and tutors ({o['draw']} cards, {o['tutor']} of them tutors); "
          f"the '+draw, tutors' row plays them")
    if res.get("fidelity"): print("  " + res["fidelity"])


def lands_only(deck):
    """The deck with every nonland accelerant inert: the baseline the ramp is measured against
    (same games, same mulligans; land abilities such as Castle Garenbrig still count)."""
    N, lib, cmdrs, anyc, keys = deck
    out = []
    for q, c, k in lib:
        if accelerates(k):
            f = _inert(k); f.orig = k                # targets are still probed as the real card
            out.append((q, c, f))
        else: out.append((q, c, k))
    return N, out, cmdrs, anyc, keys


# ---------------------------------------------------------------- several runs at once
_DECKS = {}
def _worker(job):
    path, commander, on_play, trials, turns, seed, delta, base, extra, add, cut, mode, inert, want = job
    key = (path, commander)
    if key not in _DECKS: _DECKS[key] = load(path, commander)
    d = _DECKS[key]
    return simulate(path, commander, on_play, trials, turns, seed, delta, extra, deck=lands_only(d) if base else d,
                    add_cards=add, cut_cards=cut, mode=mode, inert_names=inert, want=want)

def simulate_many(path, commander, on_play, trials, turns, seed, specs, deck=None):
    """specs: [(land_delta, lands_only, extra_targets[, add_cards[, cut_cards[, mode[, inert_names[, want]]]]])].
    Same shuffles in every run (the seed), so differences between runs are the deck change, not noise. Runs in
    parallel processes when there are several; falls back to one process if that isn't possible."""
    opt = lambda sp, i, d: sp[i] if len(sp) > i else d
    jobs = [(path, commander, on_play, trials, turns, seed, sp[0], sp[1], tuple(sp[2]), tuple(opt(sp, 3, ())),
             tuple(opt(sp, 4, ())), opt(sp, 5, "ramp"), tuple(opt(sp, 6, ())), opt(sp, 7, None)) for sp in specs]
    if len(jobs) > 2:
        try:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=max(1, min(len(jobs), (os.cpu_count() or 2) - 2))) as ex:
                return list(ex.map(_worker, jobs))
        except Exception as e:                      # spawn blocked, pickling, a frozen interpreter...
            print(f"(manasim: parallel runs unavailable, {type(e).__name__}; running one at a time)", file=sys.stderr)
    if deck: _DECKS[(path, commander)] = deck
    return [_worker(j) for j in jobs]


# ---------------------------------------------------------------- land or ramp: what the next slot should be
CAND_RX = None
GC_ALLOW = {1: 0, 2: 0, 3: 3}                       # as audit.py

def ramp_candidates(deck, bracket=None, max_price=None, limit=30):
    """Ramp cards that could take one slot: legal, in the colors, not in the deck, MV <= 3 (cost reducers that
    apply to the commander up to MV 4), no rituals, Game Changers only inside the bracket's allowance, under
    max_price. Cards goldfish.py reads only partially stay in, tagged with what it didn't read (usually a part
    that isn't mana, like Fanatic of Rhonas's eternalize; sometimes one that is, like a land sacrifice).
    Shortlist: every reducer that applies to the commander, every candidate in the commander's EDHREC snapshot,
    then the most played (EDHREC rank) up to `limit`. Returns (shortlist [(name, card, Card, why, tags)], notes)."""
    import re
    global CAND_RX
    CAND_RX = CAND_RX or re.compile(r"\badd\b|search your library|less to cast|cost \{\d\} less|treasure|untap|additional land|"
                                    r"lands? (?:from your hand|onto the battlefield)|mana", re.I)
    N, lib, cmdrs, anyc, keys = deck
    in_deck = {c["name"] for q, c, k in lib} | {c["name"] for c, k in cmdrs}
    deck_gc = sum(1 for q, c, k in lib if c.get("game_changer")) + sum(1 for c, k in cmdrs if c.get("game_changer"))
    gc_ok = bracket is None or bracket >= 4 or deck_gc < GC_ALLOW.get(bracket, 0)
    cmd_ks = [k for c, k in cmdrs]
    snap = _snapshot_incl(cmdrs, bracket)
    pool, partial = [], 0
    for c in mtg.cards():
        if c["name"] in in_deck or "Land" in (c.get("type_line") or "").split("//")[0] or mtg.legal(c) != "legal": continue
        if not set(c.get("color_identity") or []) <= set(anyc): continue
        mv = int(c.get("cmc") or 0)
        if mv > 4 or not CAND_RX.search(mtg.text_of(c)): continue
        if c.get("game_changer") and not gc_ok: continue
        if max_price is not None and (mtg.price(c) is None or mtg.price(c) > max_price): continue
        try: k = gf.compile_card(c, anyc)
        except Exception: continue
        ov = gf.load_overrides().get(mtg.norm(c["name"]))
        if ov: gf.apply_override(k, ov, anyc)
        if not accelerates(k) or k.ritual: continue
        cmd_red = any(s[0] in ("reduce", "free", "alt") and any(gf.spell_ok(ck, s[1]) for ck in cmd_ks) for s in k.statics)
        if mv > 3 and not cmd_red: continue
        if k.status != "modeled": partial += 1
        tags = (["GC"] if c.get("game_changer") else []) + (["reduces the commander"] if cmd_red else []) \
            + ([f"⚠ partial: {(k.notes or ['?'])[0][:70]}"] if k.status != "modeled" else []) \
            + ([f"EDHREC {snap[mtg.norm(c['name'])]:g}%"] if mtg.norm(c["name"]) in snap else [])
        pool.append((c["name"], c, k, why(k), tags, cmd_red))
    pool.sort(key=lambda x: x[1].get("edhrec_rank") or 10**7)
    must = [x for x in pool if x[5] or mtg.norm(x[0]) in snap]
    rest = [x for x in pool if x not in must]
    short = must + rest[:max(0, limit - len(must))]
    return [x[:5] for x in short], {"pool": len(pool), "partial": partial, "gc_ok": gc_ok, "snapshot": bool(snap)}


def _snapshot_incl(cmdrs, bracket):
    """{normalized name: inclusion %} from the newest EDHREC snapshot for this commander (snapshots/), or {}."""
    import glob
    try:
        import explorer, edhrec_diff
    except Exception: return {}
    if not cmdrs: return {}
    slugs = {"-".join(explorer.slug(c["name"]) for c, k in cmdrs)}
    if len(cmdrs) == 2: slugs.add("-".join(explorer.slug(c["name"]) for c, k in reversed(cmdrs)))
    found = []
    for f in glob.glob(os.path.join(os.path.dirname(ROOT), "snapshots", "*.txt")):
        parts = os.path.basename(f)[:-4].split("__")
        if len(parts) == 3 and parts[0] in slugs: found.append((parts[1], parts[2], f))
    if not found: return {}
    want = getattr(mtg, "BRACKET_VARIANT", {}).get(bracket)
    for pick in ([v for v in found if v[0] == want], [v for v in found if v[0] == "all"], found):
        if pick: path = max(pick, key=lambda v: v[1])[2]; break
    meta, rows, _, _ = edhrec_diff.parse_snapshot(path)
    return {mtg.norm(r["name"]): r["incl"] for r in rows}


def _game_scores(r, cmd_name, mv):
    """Per game: the share of the turns (curve - 1, curve, curve + 1) on which the commander was castable."""
    f = r["targets"][cmd_name]["first"]
    ts = [t for t in (mv - 1, mv, mv + 1) if t in r["targets"][cmd_name]["by"] and t >= 1]
    return [sum(1 for t in ts if x is not None and x <= t) / len(ts) for x in f]


MIN_EFFECT = 0.01            # a difference under 1 point is "the same", however sure the games are of it

def real(m, se):
    """A difference worth naming: beyond twice its standard error and at least MIN_EFFECT."""
    return abs(m) >= max(2 * se, MIN_EFFECT)


def paired(r, base, cmd_name, mv):
    """(mean difference, standard error) of the commander score, game by game: both runs deal the same games,
    so what's left is the changed card's effect and the games it changed."""
    import math
    a, b = _game_scores(r, cmd_name, mv), _game_scores(base, cmd_name, mv)
    d = [x - y for x, y in zip(a, b)]
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return m, sd / math.sqrt(n)


def plan_score(r, cmds, T):
    """Commanders' speed (each one's _score, averaged) for a land plan; no commander: T mana by T."""
    if not cmds: return _score(r, None, 0, T)
    return sum(_score(r, n, mv, T) for n, mv in cmds) / len(cmds)


def plan_paired(r, base, cmds):
    """paired() for plan_score: game by game over all commanders. (mean difference, standard error)."""
    import math
    if not cmds: return 0.0, 1.0
    a = [sum(xs) / len(cmds) for xs in zip(*(_game_scores(r, n, mv) for n, mv in cmds))]
    b = [sum(xs) / len(cmds) for xs in zip(*(_game_scores(base, n, mv) for n, mv in cmds))]
    d = [x - y for x, y in zip(a, b)]
    n = len(d); m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1)) if n > 1 else 0.0
    return m, sd / math.sqrt(n)


def _score(r, cmd_name, mv, T):
    """How fast a commander comes down: P(castable) averaged over the turn before curve, on curve and the
    turn after. cmd_name None: T mana by T for T and T+1."""
    if cmd_name and cmd_name in r["targets"]:
        by = r["targets"][cmd_name]["by"]
        ts = [t for t in (mv - 1, mv, mv + 1) if t in by and t >= 1]
        return sum(by[t] for t in ts) / len(ts)
    return (r["dev"][T] + r["dev"].get(T + 1, r["dev"][T])) / 2


def land_or_ramp(path, commander, on_play, deck, bracket=None, max_price=None, trials=600, confirm=2000,
                 limit=24, T=3, seed=1):
    """One slot: a land, a ramp card, or a land traded for a ramp card? Every shortlisted ramp card is played in
    the deck (taking an inert card's slot) and ranked for each commander independently; the best three for each
    commander are rerun with more games next to: now, +1 land, and each commander's best card in a basic's slot.
    Returns a dict for print_land_or_ramp."""
    N, lib, cmdrs, anyc, keys = deck
    cmds = sorted(((c["name"], int(c.get("cmc") or 0)) for c, k in cmdrs), key=lambda x: (x[1], x[0]))   # cast first, first
    turns = max([T + 1] + [mv + 1 for _, mv in cmds])
    short, notes = ramp_candidates(deck, bracket, max_price, limit)
    if not short: return {"short": [], "notes": notes}
    specs = [(0, False, ())] + [(0, False, (), (n,)) for n, *_ in short]
    runs = simulate_many(path, commander, on_play, trials, turns, seed, specs, deck=deck)
    keys_ = cmds or [(None, 0)]
    ranked = {}
    for name, mv in keys_:
        b = _score(runs[0], name, mv, T)
        ranked[name] = sorted(((x[0], _score(r, name, mv, T) - b) for x, r in zip(short, runs[1:])), key=lambda x: -x[1])
    top = []
    for name, mv in keys_:
        for n, d in ranked[name][:3]:
            if n not in top: top.append(n)
    best_of = {name: ranked[name][0][0] for name, mv in keys_}
    trades = list(dict.fromkeys(best_of.values())) if any(k.is_land and k.basic for q, c, k in lib) else []
    specs2 = [(0, False, ()), (1, False, ())] + [(0, False, (), (n,)) for n in top] + [(-1, False, (), (n,)) for n in trades]
    runs2 = simulate_many(path, commander, on_play, confirm, turns, seed + 1, specs2, deck=deck)
    base, land = runs2[0], runs2[1]
    added = dict(zip(top, runs2[2:2 + len(top)]))
    traded = dict(zip(trades, runs2[2 + len(top):]))
    rows = [("now", base), ("+1 land" + _basic_note(land) + ", cut a nonland", land)]
    rows += [(f"+1 {n}, cut a nonland", added[n]) for n in top]
    rows += [(f"{_basic_note(traded[n], cut=True)} → {n} (land count − 1)", traded[n]) for n in trades]
    verdicts = {}
    for name, mv in cmds:
        best = max(top, key=lambda n: paired(added[n], base, name, mv)[0])
        verdicts[name] = {"land": paired(land, base, name, mv), "best": paired(added[best], base, name, mv),
                          "best_vs_land": paired(added[best], land, name, mv), "best_name": best}
    return {"short": short, "verdicts": verdicts, "ranked": ranked, "rows": rows, "cmds": cmds, "T": T, "notes": notes,
            "trials": trials, "confirm": confirm,
            "why": {n: w for n, c, k, w, t in short}, "tags": {n: t for n, c, k, w, t in short}}


def _basic_note(r, cut=False):
    d = r["cut"] if cut else r["add"]
    return (" (" + ", ".join(d) + ")") if d and not cut else (", ".join(d) if d else "a land")


def _verdict(v):
    (dl, sl), (db, sb), (dd, sd) = v["land"], v["best"], v["best_vs_land"]
    nm = v["best_name"]
    if real(dd, sd) and dd > 0:
        return f"{nm} does more than one more land ({100 * db:+.1f} vs {100 * dl:+.1f} pts, averaged over the three turns)"
    if real(dd, sd):
        return f"one more land does more than the best ramp card, {nm} ({100 * dl:+.1f} vs {100 * db:+.1f} pts)"
    if not real(db, sb) and not real(dl, sl):
        return "neither a land nor a ramp card moves it beyond noise: fill the slot for other reasons"
    return f"one more land and {nm} do about the same ({100 * dl:+.1f} vs {100 * db:+.1f} pts): pick on flood and what else the card does"


def print_land_or_ramp(res, flood_of=None):
    """flood_of(row label, result) -> flood probability or None (landbase passes its exact formula).
    Each commander has its own columns (castable by the turn before curve, on curve, the turn after), its own
    '≈' mark (within noise or under 1 point of now, for that commander), its own verdict and best picks."""
    if not res.get("short"):
        n = res["notes"]
        print(f"  no ramp candidates (pool {n.get('pool', 0)})"); return
    cmds, T = res["cmds"], res["T"]
    groups = [(name, mv, [t for t in (mv - 1, mv, mv + 1) if t >= 2]) for name, mv in cmds]
    W = 50
    short_name = lambda n: n.split(",")[0].split(" // ")[0]
    top_line = "".join(f"{(short_name(n) + f' (MV {mv})')[:len(ts) * 10 + 2]:<{len(ts) * 10 + 2}}" for n, mv, ts in groups)
    print(f"  {'':<{W}}{top_line}")
    head = "".join("".join(f"{'T' + str(t):>10}" for t in ts) + "  " for n, mv, ts in groups)
    print(f"  {'change (castable by turn)':<{W}}{head}{f'{T} by T{T}':>9}" + (f"{'flood':>8}" if flood_of else ""))
    base = res["rows"][0][1]
    for label, r in res["rows"]:
        cells = ""
        for name, mv, ts in groups:
            for t in ts:
                v, b = r["targets"][name]["by"][t], base["targets"][name]["by"][t]
                cells += f"{100 * v:6.1f}%" + (f"{100 * (v - b):+3.0f}" if r is not base else "   ")
            cells += "  " if r is base or real(*paired(r, base, name, mv)) else " ≈"
        dv, db = r["dev"][T], base["dev"][T]
        cells += f"{100 * dv:6.1f}%" + (f"{100 * (dv - db):+3.0f}" if r is not base else "   ")
        fl = flood_of(label, r) if flood_of else None
        if flood_of: cells += f"{100 * fl:7.1f}%" if fl is not None else f"{'':>8}"
        print(f"  {label[:W]:<{W}}{cells}")
    print(f"  ≈ = within noise or under 1 point of now, for that commander. Ramp tried: {len(res['short'])} of "
          f"{res['notes']['pool']} legal candidates ({res['trials']:,} games each; the table reruns the best with "
          f"{res['confirm']:,})" + ("" if res["notes"]["gc_ok"] else "; Game Changers left out at this bracket")
          + ("; the commander's EDHREC snapshot added its ramp" if res["notes"]["snapshot"] else ""))
    for name, mv in cmds:
        print(f"  verdict, {short_name(name)}: {_verdict(res['verdicts'][name])}")
    shown = set()
    for name, mv in (cmds or [(None, 0)]):
        best = res["ranked"][name][:8]
        lab = f"best for {short_name(name)}" if name else "best for T3 development"
        print(f"  {lab}: " + "; ".join(
            f"{n} {100 * d:+.1f}" + (f" [{', '.join(res['tags'][n])}]" if res["tags"][n] else "") for n, d in best))
        for n, d in best[:3]:
            if n not in shown: print(f"      {n}: {res['why'][n]}"); shown.add(n)

def main():
    ap = argparse.ArgumentParser(description="Mana development with ramp (see module docstring)")
    ap.add_argument("deck"); ap.add_argument("--commander")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--turns", type=int, default=8); ap.add_argument("--trials", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--target", action="append", default=[])
    ap.add_argument("--lands", type=int)
    ap.add_argument("--hand", help="check one line: the opening hand, 'Card; Card; ...'")
    ap.add_argument("--draws", default="", help="with --hand: the draws in order, 'Card; Card; ...'")
    ap.add_argument("--land-or-ramp", action="store_true", help="compare one more land with the best ramp cards for the slot")
    ap.add_argument("--max-price", type=float, help="with --land-or-ramp: ramp candidates at most $N")
    a = ap.parse_args()
    if not os.path.exists(a.deck): sys.exit(f"deck file not found: {a.deck}")
    if a.deck.lower().endswith(".dck"): sys.exit("this is a Forge .dck file; pass the .txt list")
    deck = load(a.deck, a.commander)
    N, lib, cmdrs, anyc, keys = deck
    on_play = not a.draw
    if a.hand:
        split = lambda v: [x.strip() for x in v.split(";") if x.strip()]
        first, log = line(deck, split(a.hand), split(a.draws), a.turns, on_play, a.target)
        print("\n".join(l for l in log if not l.startswith("    combat") and "opponents:" not in l))
        print()
        for n, _, _ in build(deck, on_play, 0, a.target)[1]:
            print(f"  {n}: first castable {'T' + str(first[n]) if n in first else 'not by T' + str(a.turns)}")
        return
    L0 = sum(q for q, c, k in lib if k.is_land)
    if a.land_or_ramp:
        meta = mtg.parse_deck_meta(a.deck)
        res = land_or_ramp(a.deck, a.commander, on_play, deck, meta.get("bracket"), a.max_price, seed=a.seed)
        print(f"=== MANASIM land or ramp: {' + '.join(c['name'] for c, _ in cmdrs) or '(no commander)'} | {L0} lands ===")
        print_land_or_ramp(res)
        return
    delta = (a.lands - L0) if a.lands else 0
    fid = fidelity_line(role_coverage(deck))
    res, lo, wd = simulate_many(a.deck, a.commander, on_play, a.trials, a.turns, a.seed,
                            [(delta, False, a.target), (delta, True, a.target), (delta, False, a.target, (), (), "tutors")], deck=deck)
    cmd = " + ".join(c["name"] for c, _ in cmdrs) or "(no commander)"
    print(f"=== MANASIM: {cmd} | N={res['N']} | {res['lands']} lands"
          + (f" ({'+' if delta > 0 else ''}{delta}: {res['add'] or res['cut']})" if delta else "")
          + f" | {len(res['coverage']['rows'])} accelerants | {'on the play' if on_play else 'on the draw'} ===")
    res["fidelity"] = fid
    report(res, on_play, lo, wd)
    print("\nLimits: goldfish.py's pilot and card reading; no draw or tutors; no opponents' interaction. "
          "'drops all hit' is the number to check by hand.")


if __name__ == "__main__":
    main()
