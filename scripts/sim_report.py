#!/usr/bin/env python3
"""
sim_report.py — shared stats and report printers for the deck simulators (mtg-data).

goldfish.py's report layout is the house style. Both goldfish.py and Fishpond (fishpond/, the
Forge-backed simulator) fill the same result bundle and print it through this module:

  res = {"rec": {metric: {turn: [one value per game]}}, "turns": T, "trials": n,
         "cmd_first": {commander: [first turn out per game, or None]},
         "first": {group index: [first-cast turn per game, or None]},
         "finals": [{"deaths": [turns opponents died], "won": turn or None, "how": [kill routes], ...}],
         "kept": Counter(hand size), "mulliganed": share, ...optional keys...}

Every block is optional except rec/turns/trials/cmd_first/first/finals: a metric a tool can't
produce is left out of the bundle and its column or line is omitted, never faked. A metric a tool
measures differently from goldfish keeps its column with a '≈' in front of the header (pass its
metric key in `approx`); the tool prints the footnote.

Not a CLI. Import it: sys.path.insert(0, "scripts"); import sim_report as sr.
"""
import math
from collections import Counter

def pct(v): return f"{100 * v:5.1f}%"
def q(vals, p):
    s = sorted(vals); return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]
def mean(v): return sum(v) / len(v) if v else 0
def by_turn(turns_list, t): return mean([1 if x is not None and x <= t else 0 for x in turns_list])

def nz(counter):
    """Drop entries that round to nothing (cycling nets 0 extra cards; it is filtering, not advantage)."""
    return Counter({k: v for k, v in counter.items() if abs(v) >= 1})

def sd(v):
    m = mean(v); return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5 if len(v) > 1 else 0.0

def mean_leq1(d):
    return d["hand"].get("leq1", 0.0)

def ci95(k, n):
    """Wilson 95% interval for k successes in n trials, as (low, high) shares."""
    if not n: return (0.0, 0.0)
    z, p = 1.96, k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))

def summary(res, groups, opp_n=3, start_life=40, life_floor=20):
    rec, T = res["rec"], res["turns"]
    out = {"turns": {}}
    for t in range(1, T + 1):
        out["turns"][t] = {m: ({"p10": q(v, .1), "med": q(v, .5), "p90": q(v, .9), "mean": round(mean(v), 2)}
                               if m not in ("colors", "cmd_out") else round(mean(v), 4))
                           for m, v in ((m, rec[m][t]) for m in rec)}
    out["commander_by_turn"] = {c: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for c, v in res["cmd_first"].items()}
    out["tracked_by_turn"] = {groups[gi][0]: {t: round(by_turn(v, t), 4) for t in range(1, T + 1)} for gi, v in res["first"].items()}
    if "attr" in res: out["extra_card_sources"] = {k: round(v / res["trials"], 3) for k, v in nz(res["attr"]).most_common(12)}
    if "rattr" in res: out["recursion_sources"] = {k: round(v / res["trials"], 3) for k, v in nz(res["rattr"]).most_common(10)}
    if "tut" in res: out["tutor_targets"] = {k: round(v / res["trials"], 3) for k, v in nz(res["tut"]).most_common(10)}
    if "kept" in res:
        out["kept_hand_size"] = {k: round(v / res["trials"], 4) for k, v in sorted(res["kept"].items(), reverse=True)}
        out["mulligan_rate"] = round(res["mulliganed"], 4)
    F, n = res["finals"], res["trials"]
    out["kill_by_turn"] = {lab: {t: round(mean([1 if len(f["deaths"]) >= need and f["deaths"][need - 1] <= t else 0 for f in F]), 4)
                                 for t in range(1, T + 1)}
                           for lab, need in (("first", 1), ("second", 2), ("table", opp_n))}
    wins = sorted(f["won"] for f in F if f["won"] and f["won"] <= T)     # a game can outlast the horizon (Fishpond)
    out["table_kill"] = {"share": round(len(wins) / n, 4), "p10": q(wins, .1) if wins else None,
                         "med": q(wins, .5) if wins else None, "p90": q(wins, .9) if wins else None}
    how = Counter(h for f in F for h in f["how"])
    out["kills_by"] = {h: round(v / sum(how.values()), 3) for h, v in how.most_common()}
    if "dsrc" in res: out["damage_sources"] = {k: round(v / n, 2) for k, v in res["dsrc"].most_common(10) if v / n >= 0.05}
    if "trigs" in res:
        kinds = Counter()
        for (_, kind), v in res["trigs"].items(): kinds[kind] += v
        out["triggers_by_kind"] = {k: round(kinds[k] / n, 2) for k in ("enter", "cast", "timed", "combat", "dies", "~opp", "other") if kinds[k]}
        out["trigger_sources"] = {f"{name} ({kind})": round(v / n, 2) for (name, kind), v in res["trigs"].most_common(12) if v / n >= 0.05}
    if "lost" in res: out["lost_in_combat"] = round(res["lost"], 3)
    if "atk_turns" in res: out["attack_turns"] = round(res["atk_turns"], 2)
    if "xcombats" in res: out["extra_combats"] = round(res["xcombats"], 2)
    if res.get("spec"): out["blocks"] = {k: round(v / n, 3) for k, v in sorted(res["bstat"].items())}
    paid = Counter()
    for f in F: paid.update(f.get("life_paid") or {})
    died = sorted(f["died"] for f in F if f.get("died"))
    out["self_life"] = {"paid_avg": round(sum(paid.values()) / n, 2), "paid_by": {k: round(v / n, 2) for k, v in paid.most_common()},
                        "died_share": round(len(died) / n, 4), "died_med": q(died, .5) if died else None,
                        "died_by": dict(Counter(f.get("death") for f in F if f.get("died"))), "floor": life_floor,
                        "end_p10": q(sorted(f.get("life", start_life) for f in F), .1)}
    return out

# ---------------------------------------------------------------- per-turn tables
# A column: (metric, header, width, align, kind[, prefix]). kind: trio = P10/median/P90, pct = a share,
# mean2 = the mean to 2 places, leq1 = share of games with hand <= 1. A column whose metric is missing
# from the summary is left out; a metric in `approx` gets '≈' before its header.
DEV_COLS = [("lands", "lands", 10, "<", "trio"), ("mana", "mana", 10, "<", "trio"), ("colors", "all colors", 11, ">", "pct"),
            ("cmd_out", "cmdr out", 10, ">", "pct"), ("casts", "spells cast", 13, "<", "trio", "   "),
            ("spent", "mana spent", 12, "<", "trio")]
FLOW_COLS = [("extra", "extra (cum)", 13, "<", "trio"), ("extra", "mean", 6, ">", "mean2"), ("hand", "hand", 10, ">", "trio"),
             ("hand", "hand<=1", 9, ">", "leq1"), ("stranded", "stranded", 10, ">", "mean2"), ("disc", "discarded", 11, ">", "mean2"),
             ("gy", "graveyard", 11, ">", "trio"), ("recur", "recursion", 11, ">", "mean2"), ("cycled", "cycled", 8, ">", "mean2")]
COMBAT_COLS = [("atk", "attackers", 11, "<", "trio"), ("cdmg", "combat dmg", 13, "<", "trio"), ("dmg", "all dmg", 13, "<", "trio"),
               ("cmdmax", "top cmdr dmg", 14, "<", "trio"), ("poison", "poison", 9, "<", "trio"), ("kills", "opps dead", 10, ">", "mean2"),
               ("life", "your life", 13, ">", "trio")]
BLOCKER_COL = ("oppb", "opp blockers", 14, ">", "trio")

def _has(d, col):
    if col[0] not in d: return False
    return col[4] != "leq1" or "leq1" in d[col[0]]

def _cell(d, col):
    m, kind = col[0], col[4]
    if kind == "trio": v = d[m]; return f"{v['p10']}/{v['med']}/{v['p90']}"
    if kind == "pct": return pct(d[m])
    if kind == "leq1": return pct(mean_leq1(d))
    return f"{d[m]['mean']:.2f}"

def print_table(sm, T, cols, approx=()):
    """Header + one row per turn for the columns whose metric the summary has."""
    tt = sm["turns"]
    cols = [c for c in cols if _has(tt[1], c)]
    def fmt(s, c): return (c[5] if len(c) > 5 else "") + format(s, f"{c[3]}{c[2]}")
    print(f"{'turn':<5}" + "".join(fmt(("≈" if c[0] in approx else "") + c[1], c) for c in cols))
    for t in range(1, T + 1):
        print(f"T{t:<4}" + "".join(fmt(_cell(tt[t], c), c) for c in cols))

def print_report(label, sm, T, groups, approx=(), dev_title=None, flow_title=None, **combat_kw):
    """Development table, card flow, combat (goldfish's layout; the caller prints its own header first)."""
    print(f"\n## {label}: " + (dev_title or "development (P10/median/P90; lands and mana at the start of your main phase)"))
    print_table(sm, T, DEV_COLS, approx)
    turns_show = [t for t in range(2, T + 1)]
    for c, v in sm["commander_by_turn"].items():
        print(f"commander {c}: " + " | ".join(f"<=T{t} {pct(v[t]).strip()}" for t in turns_show))
    for g, v in sm["tracked_by_turn"].items():
        print(f"tracked {g}: " + " | ".join(f"<=T{t} {pct(v[t]).strip()}" for t in turns_show))
    if any(_has(sm["turns"][1], c) for c in FLOW_COLS):
        print(f"\n## {label}: " + (flow_title or "card flow (end of turn; extra = cards put in hand beyond draw steps)"))
        print_table(sm, T, FLOW_COLS, approx)
    src = sm.get("extra_card_sources")
    if src:
        print(f"extra cards by source (avg per game over {T} turns): "
              + " | ".join(f"{k} {v:.2f}" for k, v in src.items()))
    if sm.get("recursion_sources"):
        print(f"recursion by source (cards back from the graveyard, avg per game): "
              + " | ".join(f"{k} {v:.2f}" for k, v in sm["recursion_sources"].items()))
    if sm.get("tutor_targets"):
        print(f"tutor targets (times fetched, avg per game): "
              + " | ".join(f"{k} {v:.2f}" for k, v in sm["tutor_targets"].items()))
    print_combat(label, sm, T, approx=approx, **combat_kw)

def print_combat(label, sm, T, approx=(), opp_n=3, start_life=40, title=None, tail=None, death_labels=None):
    bl = sm.get("blocks")
    if title is None:
        title = (f"combat and damage ({opp_n} opponents at {start_life} life; "
                 + (f"boards from --blockers: {sm.get('blockers_spec', '')}" if bl is not None else "no opposing creatures (--blockers not set)")
                 + "; opponents never attack; cumulative, end of turn)")
    print(f"\n## {label}: {title}")
    print_table(sm, T, COMBAT_COLS + ([BLOCKER_COL] if bl is not None else []), approx)
    kb = sm["kill_by_turn"]
    show = [t for t in range(3, T + 1)]
    for lab, name in (("first", "first opponent dead"), ("table", "all opponents dead")):
        print(f"{name}: " + " | ".join(f"<=T{t} {pct(kb[lab][t]).strip()}" for t in show))
    sl = sm.get("self_life")
    if sl and sl["died_share"]:
        lab = death_labels or {}
        print(f"you lost in {pct(sl['died_share']).strip()} of games (median T{sl['died_med']}): "
              + " | ".join(f"{lab.get(k) or ('your own life payments' if k == 'life' else 'drew from an empty library')} "
                           f"{v / sum(sl['died_by'].values()):.0%}" for k, v in sl["died_by"].items()))
    if sl and sl["paid_avg"]:
        print(f"life you paid yourself (avg per game): {sl['paid_avg']:.2f} = " + " | ".join(f"{k} {v:.2f}" for k, v in sl["paid_by"].items())
              + f"; life at the end P10 {sl['end_p10']}; floor {sl['floor']} for optional payments"
              )
    tk = sm["table_kill"]
    print(f"table killed in {pct(tk['share']).strip()} of games by T{T}" +
          (f" (P10 T{tk['p10']} / median T{tk['med']} / P90 T{tk['p90']} of those)" if tk["med"] else "")
          + ("; kills by: " + " | ".join(f"{h} {pct(v).strip()}" for h, v in sm["kills_by"].items()) if sm["kills_by"] else ""))
    if sm.get("damage_sources"):
        print("damage by source (avg per game): " + " | ".join(f"{k} {v:.1f}" for k, v in sm["damage_sources"].items()))
    if sm.get("triggers_by_kind"):
        print("triggers fired (avg per game): " + " | ".join(f"{k} {v:.2f}" for k, v in sm["triggers_by_kind"].items()))
    if sm.get("trigger_sources"):
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
    if tail is None and "attack_turns" in sm:
        tail = (f"attacked on {sm['attack_turns']:.1f} turns per game" + (f"; {sm['extra_combats']:.2f} additional combat phases per game"
                if sm.get('extra_combats') else "") + f"; your creatures lost in combat {sm['lost_in_combat']:.2f} per game. "
                f"A game ends when all opponents are dead; its later turns repeat its final state.")
    if tail: print(tail)

# ---------------------------------------------------------------- variants side by side
def compare_table(builds, groups, T, title="Builds compared (same shuffles)", extra=None):
    """builds: [(label, summary)]. Rows whose metric a summary lacks are left out; `extra` rows
    ([(name, [cell per build])]) are appended."""
    print(f"\n## {title}")
    labels = [b[0] for b in builds]
    rows = []
    S = [sm for _, sm in builds]
    has = lambda m: all(m in sm["turns"][1] for sm in S)
    def cm(sm, t):
        v = list(sm["commander_by_turn"].values())
        return v[0][t] if v else 0
    for t in (3, 4, 5):
        if t <= T: rows.append((f"commander <=T{t}", [pct(cm(sm, t)) for sm in S]))
    for g in [g[0] for g in groups]:
        for t in (5, 6):
            if t <= T: rows.append((f"{g} <=T{t}", [pct(sm["tracked_by_turn"][g][t]) for sm in S]))
    if has("colors"):
        for t in (3, 4):
            if t <= T: rows.append((f"all colors T{t}", [pct(sm["turns"][t]["colors"]) for sm in S]))
    t4 = min(4, T)
    if has("mana"): rows.append((f"mana T{t4} P10/med", [f"{sm['turns'][t4]['mana']['p10']}/{sm['turns'][t4]['mana']['med']}" for sm in S]))
    if has("stranded"): rows.append((f"stranded T{t4} (avg)", [f"{sm['turns'][t4]['stranded']['mean']:.2f}" for sm in S]))
    if has("extra"): rows.append((f"extra cards T{T} P10/med/P90", [f"{sm['turns'][T]['extra']['p10']}/{sm['turns'][T]['extra']['med']}/{sm['turns'][T]['extra']['p90']}" for sm in S]))
    if has("spent"): rows.append((f"mana spent T{T} median", [str(sm['turns'][T]['spent']['med']) for sm in S]))
    if has("recur"): rows.append((f"recursion T{T} (avg)", [f"{sm['turns'][T]['recur']['mean']:.2f}" for sm in S]))
    if has("cycled"): rows.append((f"cards cycled T{T} (avg)", [f"{sm['turns'][T]['cycled']['mean']:.2f}" for sm in S]))
    if has("dmg"): rows.append((f"damage T{T} P10/med/P90", [f"{sm['turns'][T]['dmg']['p10']}/{sm['turns'][T]['dmg']['med']}/{sm['turns'][T]['dmg']['p90']}" for sm in S]))
    if has("cmdmax"): rows.append((f"top cmdr dmg T{T} median", [str(sm['turns'][T]['cmdmax']['med']) for sm in S]))
    rows.append((f"first opponent dead <=T{T}", [pct(sm['kill_by_turn']['first'][T]).strip() for sm in S]))
    rows.append((f"table killed <=T{T}", [pct(sm['table_kill']['share']).strip() for sm in S]))
    rows.append(("table kill median turn", [f"T{sm['table_kill']['med']}" if sm['table_kill']['med'] else "-" for sm in S]))
    if all("disruption" in sm and "any disruption" in sm["disruption"] for sm in S):
        rows.append((f"disrupted: Δspells T{T}", [f"{sm['disruption']['any disruption']['d_casts']:+.2f}" for sm in S]))
        rows.append((f"disrupted: Δcmdr turns", [f"{sm['disruption']['any disruption']['d_cmd_turns']:+.2f}" for sm in S]))
        rows.append((f"disrupted: Δdamage", [f"{sm['disruption']['any disruption']['d_dmg']:+.2f}" for sm in S]))
        rows.append(("disrupted: answered", [pct(sm['disruption']['any disruption']['answered']).strip() for sm in S]))
    if all("ladder" in sm for sm in S):
        L = [sm["ladder"] for sm in S]
        rows.append(("ladder: median breakpoint", [str(l["bp"]["med"]) if l["bp"] else "none" for l in L]))
        rows.append(("ladder: never folded", [pct(l["never"]).strip() for l in L]))
        rows.append(("ladder: fold (avg over rungs)", [pct(mean([r["fold"] for r in l["rungs"]])).strip() for l in L]))
        rows.append(("ladder: fold at top rung", [pct(l["rungs"][-1]["fold"]).strip() for l in L]))
        rows.append(("ladder: Δcmdr turns top rung", [f"{l['rungs'][-1]['d_cmd_turns']:+.2f}" for l in L]))
        rows.append(("ladder: Δkill turn top rung", [f"{l['rungs'][-1]['d_killt']:+.2f}" for l in L]))
    rows += extra or []
    w = max(len(r[0]) for r in rows) + 2
    cw = max(10, max(len(l) for l in labels) + 2)
    print(f"{'':<{w}}" + "".join(f"{l:>{cw}}" for l in labels))
    for name, vals in rows:
        print(f"{name:<{w}}" + "".join(f"{v:>{cw}}" for v in vals))
