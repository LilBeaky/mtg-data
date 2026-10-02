"""Compare two saved runs side by side (python3 -m fishpond compare RUN_A RUN_B): results, how the hero dies, development,
tutor picks and pilot-policy activity, and the cards whose play changed most. Meant for A/B runs on the same seed and pod
(e.g. FISHPOND_PILOT=off vs on); games with the same index are paired."""
import statistics as st
from collections import Counter

from . import runner

def _loss(r):
    l = r.get("loss") or {}
    return f"{l.get('route', '?')} ({l.get('src') or '?'})"

def _stats(records):
    n = len(records)
    res = Counter(r["result"] for r in records)
    loss_t = [r["hero_turns"] for r in records if r["result"] == "loss"]
    win_t = [r["hero_turns"] for r in records if r["result"] == "win"]
    tut = Counter(t["card"] for r in records for t in r.get("tutors") or [] if t["kind"] == "search" and not t["land"])
    pol = [p for r in records for p in r.get("policy_log") or (r.get("end") or {}).get("policy_log") or [] if p.get("seat") == 1]
    casts = Counter(c for r in records for c in set(r.get("casts") or {}))
    hand = Counter(c for r in records for c in set((r.get("end") or {}).get("hand") or []))
    return {"n": n, "res": res, "loss_t": loss_t, "win_t": win_t, "tut": tut, "pol": pol, "casts": casts, "hand": hand,
            "routes": Counter(r.get("route") for r in records if r["result"] == "win"),
            "losses": Counter(_loss(r) for r in records if r["result"] == "loss"),
            "ms": [(r.get("end") or {}).get("ms") or r.get("ms") or 0 for r in records]}

def _med(v): return st.median(v) if v else "-"

def compare(a_dir, b_dir, top=12):
    (ma, ra), (mb, rb) = runner.load_run(a_dir), runner.load_run(b_dir)
    A, B = _stats(ra), _stats(rb)
    la = "A (pilot " + ("on" if ma.get("pilot", False) else "off") + ")"
    lb = "B (pilot " + ("on" if mb.get("pilot", False) else "off") + ")"
    print(f"A: {a_dir}\nB: {b_dir}")
    if (ma.get("seed"), ma.get("hero")) != (mb.get("seed"), mb.get("hero")): print("note: the runs differ in seed or hero; games aren't paired")
    row = lambda k, x, y: print(f"  {k:34} {str(x):>18} {str(y):>18}")
    print(f"  {'':34} {la:>18} {lb:>18}")
    row("games", A["n"], B["n"])
    for k in ("win", "loss", "draw"): row(k, f"{A['res'][k]} ({A['res'][k] / max(1, A['n']):.0%})", f"{B['res'][k]} ({B['res'][k] / max(1, B['n']):.0%})")
    row("median turn of a win / a loss", f"{_med(A['win_t'])} / {_med(A['loss_t'])}", f"{_med(B['win_t'])} / {_med(B['loss_t'])}")
    row("median game time (s)", round(_med(A["ms"]) / 1000) if A["ms"] else "-", round(_med(B["ms"]) / 1000) if B["ms"] else "-")
    row("nonland tutors per game", f"{sum(A['tut'].values()) / max(1, A['n']):.2f}", f"{sum(B['tut'].values()) / max(1, B['n']):.2f}")
    pb = B["pol"] or A["pol"]
    if pb:
        ov = [p for p in pb if p["pick"] != p["forge"]]
        print(f"  pilot policy ({'B' if B['pol'] else 'A'}): {len(pb)} of your decisions, overrode Forge in {len(ov)} "
              f"({Counter(p['layer'] for p in ov).most_common()})")
    print("  wins by route:     A " + (", ".join(f"{k} {v}" for k, v in A["routes"].most_common()) or "-") + " | B " + (", ".join(f"{k} {v}" for k, v in B["routes"].most_common()) or "-"))
    print("  losses by reason:  A " + (", ".join(f"{k} {v}" for k, v in A["losses"].most_common(4)) or "-") + " | B " + (", ".join(f"{k} {v}" for k, v in B["losses"].most_common(4)) or "-"))
    if ra and rb and len(ra) == len(rb):
        diff = [(x["game"], x["result"], y["result"]) for x, y in zip(sorted(ra, key=lambda r: r["game"]), sorted(rb, key=lambda r: r["game"])) if x["result"] != y["result"]]
        print(f"  paired games with a different result: {len(diff)} of {len(ra)}" + (": " + ", ".join(f"g{g} {x}->{y}" for g, x, y in diff[:10]) if diff else ""))
    print("  tutor targets (games):")
    for c in sorted(set(A["tut"]) | set(B["tut"]), key=lambda c: -(A["tut"][c] + B["tut"][c]))[:top]:
        print(f"    {c:36} {A['tut'][c]:>4} {B['tut'][c]:>4}")
    ch = sorted(set(A["casts"]) | set(B["casts"]), key=lambda c: -abs(B["casts"][c] / max(1, B["n"]) - A["casts"][c] / max(1, A["n"])))
    print("  cards cast in the most changed share of games (A -> B):")
    for c in ch[:top]:
        print(f"    {c:36} {A['casts'][c] / max(1, A['n']):>5.0%} -> {B['casts'][c] / max(1, B['n']):.0%}   left in hand at the end {A['hand'][c] / max(1, A['n']):.0%} -> {B['hand'][c] / max(1, B['n']):.0%}")
