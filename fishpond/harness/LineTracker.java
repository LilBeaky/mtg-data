import forge.game.Game;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.zone.ZoneType;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;

/** Win-line audit (fishpond/win_lines.txt): for every seat, each of its commander's lines is checked at the start of the seat's
 *  first main phase; when its pieces are there ("available"), the seat's plays until its next turn are watched for the line's
 *  action ("did"). Printed after the game as #FP-LINE, one per seat and line; `python -m fishpond lines RUN_DIR` adds them up. */
public class LineTracker {
    record Line(String commander, String kind, String label, List<String> needs, List<String> did) {}

    /** What a seat did since its last check. */
    static final class Window {
        final Map<String, Integer> casts = new HashMap<>(), acts = new HashMap<>();
        final Set<String> lands = new HashSet<>();
        boolean attackedWithCmd = false;
        int maxCmc = -1;
    }

    static final class Record {
        final List<Integer> avail = new ArrayList<>(), did = new ArrayList<>();
        final Map<Integer, List<String>> hands = new LinkedHashMap<>();   // the seat's hand on turns it missed the line
    }

    final Game g;
    final List<Line> all = new ArrayList<>();
    final Map<Player, List<Line>> lines = new LinkedHashMap<>();
    final Map<Player, Window> window = new HashMap<>();
    final Map<Player, List<Line>> open = new HashMap<>();       // lines available at the seat's last check
    final Map<Player, Integer> openTurn = new HashMap<>();
    final Map<Player, Map<Line, Record>> records = new HashMap<>();
    final Map<Player, Integer> cmdFirst = new HashMap<>(), lastTurn = new HashMap<>();   // reach: commander first out, turns seen
    final Map<Player, Set<Line>> closed = new HashMap<>();    // closers the seat has played: later turns aren't misses

    LineTracker(Game g, File spec) {
        this.g = g;
        if (spec != null && spec.exists()) {
            try {
                for (String raw : Files.readAllLines(spec.toPath(), StandardCharsets.UTF_8)) {
                    String s = raw.trim();
                    if (s.isEmpty() || s.startsWith("#")) continue;
                    String[] f = s.split("\\|");
                    if (f.length < 5) continue;
                    all.add(new Line(f[0].trim(), f[1].trim(), f[2].trim(), split(f[3]), split(f[4])));
                }
            } catch (Exception e) {
                ForgeRunner.out.println("#FP-WARN win lines not read: " + e);
            }
        }
    }

    /** The seat's lines, by its commanders' names (known once the game has started). */
    List<Line> linesOf(Player p) {
        return lines.computeIfAbsent(p, k -> {
            List<Line> mine = new ArrayList<>();
            for (Card c : p.getCommanders())
                for (Line l : all) if (l.commander.equals(c.getName())) mine.add(l);
            Map<Line, Record> r = new LinkedHashMap<>();
            for (Line l : mine) r.put(l, new Record());
            records.put(p, r);
            return mine;
        });
    }

    static List<String> split(String s) {
        List<String> out = new ArrayList<>();
        for (String x : s.split(";")) if (!x.trim().isEmpty()) out.add(x.trim());
        return out;
    }

    /** Start of the seat's first main phase (its seat-turn number t): close the last window, open the next. */
    void check(Player p, int t) {
        close(p);
        lastTurn.put(p, t);
        if (!cmdFirst.containsKey(p) && cmdOut(p) != null) cmdFirst.put(p, t);
        List<Line> now = new ArrayList<>();
        List<String> hand = null;
        for (Line l : linesOf(p)) {
            if (closed.getOrDefault(p, Set.of()).contains(l)) continue;
            boolean ok;
            try { ok = l.needs.stream().allMatch(n -> holds(p, n)); } catch (Throwable e) { ok = false; }
            if (ok) {
                now.add(l);
                Record r = records.get(p).get(l);
                r.avail.add(t);
                if (hand == null) { hand = new ArrayList<>(); for (Card c : p.getCardsIn(ZoneType.Hand)) hand.add(c.getName()); }
                r.hands.put(t, hand);
            }
        }
        open.put(p, now);
        openTurn.put(p, t);
        window.put(p, new Window());
    }

    void close(Player p) { close(p, false); }

    void close(Player p, boolean won) {
        List<Line> was = open.remove(p);
        Window w = window.remove(p);
        if (was == null || w == null) return;
        int t = openTurn.get(p);
        for (Line l : linesOf(p)) {
            Record r = records.get(p).get(l);
            boolean did = l.did.stream().filter(d -> !d.equals("win")).anyMatch(d -> done(w, d, won))
                    || (was.contains(l) && l.did.contains("win") && won);
            if (was.contains(l)) {
                if (did) { r.did.add(t); r.hands.remove(t); }
                else if (won) { r.avail.remove(Integer.valueOf(t)); r.hands.remove(t); }   // won anyway: the line wasn't needed (by value, not index)
            } else if (did && l.kind.equals("closer") && !closed.getOrDefault(p, Set.of()).contains(l)) {
                // a closer whose pieces came together after the check (a fifth creature on an opponent's turn, then Sprout
                // Swarm's loop at instant speed) still counts, as an available turn played. Closers only: it counts only the
                // plays, never the mid-turn chances missed, which pushed plans and engines toward 100% (study150_20261015_p53b);
                // a closer is played once a game, so that one-sidedness costs little there
                r.avail.add(t); r.did.add(t);
            }
            if (did && l.kind.equals("closer")) closed.computeIfAbsent(p, k -> new HashSet<>()).add(l);
        }
    }

    // ---- events from the Watcher ----
    void cast(Player p, Card c, boolean spell) {
        Window w = window.get(p);
        if (w == null || c == null) return;
        if (spell) { w.casts.merge(c.getName(), 1, Integer::sum); w.maxCmc = Math.max(w.maxCmc, c.getCMC()); }
        else w.acts.merge(c.getName(), 1, Integer::sum);
    }

    void land(Player p, Card c) {
        Window w = window.get(p);
        if (w != null && c != null) w.lands.add(c.getName());
    }

    void attack(Player p, Collection<Card> attackers) {
        Window w = window.get(p);
        if (w == null) return;
        for (Card a : attackers) if (a.isCommander() && a.getOwner() == p) w.attackedWithCmd = true;
    }

    /** After the game: close every open window (the winner's counts its "win") and print one line per seat and line. */
    List<String> finish(Player winner) {
        for (Player p : g.getRegisteredPlayers()) linesOf(p);   // seats with no lines still get a reach record
        for (Player p : new ArrayList<>(open.keySet())) close(p, p == winner);
        List<String> out = new ArrayList<>();
        for (Map.Entry<Player, Map<Line, Record>> e : records.entrySet()) {
            String seat = e.getKey().getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
            for (Map.Entry<Line, Record> x : e.getValue().entrySet()) {
                Line l = x.getKey();
                StringBuilder hands = new StringBuilder("{");
                for (Map.Entry<Integer, List<String>> h : x.getValue().hands.entrySet()) {
                    if (hands.length() > 1) hands.append(", ");
                    hands.append("\"").append(h.getKey()).append("\": [");
                    for (int i = 0; i < h.getValue().size(); i++) hands.append(i > 0 ? ", " : "").append(ForgeRunner.js(h.getValue().get(i)));
                    hands.append("]");
                }
                hands.append("}");
                out.add("{\"seat\": \"" + seat + "\", \"commander\": " + ForgeRunner.js(l.commander) + ", \"kind\": " + ForgeRunner.js(l.kind)
                        + ", \"line\": " + ForgeRunner.js(l.label) + ", \"avail\": " + x.getValue().avail + ", \"did\": " + x.getValue().did
                        + ", \"won\": " + (e.getKey() == winner) + ", \"hands\": " + hands + "}");
            }
            // reach: one record per seat (kind "reach"): when its commander was first out at a main phase, how many turns it had
            Player p = e.getKey();
            String cmd = p.getCommanders().isEmpty() ? "" : p.getCommanders().get(0).getName();
            out.add("{\"seat\": \"" + seat + "\", \"commander\": " + ForgeRunner.js(cmd) + ", \"kind\": \"reach\", \"line\": \"reach\", \"avail\": [], \"did\": []"
                    + ", \"won\": " + (p == winner) + ", \"cmd_first\": " + cmdFirst.getOrDefault(p, -1) + ", \"turns\": " + lastTurn.getOrDefault(p, 0) + "}");
        }
        return out;
    }

    // ---- needs ----
    boolean holds(Player p, String n) {
        int i = n.indexOf(':');
        if (i > 0 && !n.contains(">=") && !n.contains("<=")) {
            String kind = n.substring(0, i);
            String[] names = n.substring(i + 1).split("/");
            for (String name : names) if (has(p, kind, name.trim())) return true;
            return false;
        }
        if (n.equals("cmd")) return cmdOut(p) != null;
        String[] kv = n.split(">=|<=");
        String key = kv[0].trim();
        int v = Integer.parseInt(kv[1].trim());
        int have = count(p, key);
        return n.contains(">=") ? have >= v : have <= v;
    }

    Card cmdOut(Player p) {
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) if (c.isCommander() && c.getOwner() == p) return c;
        return null;
    }

    boolean has(Player p, String kind, String name) {
        switch (kind) {
            case "bf": return named(p, ZoneType.Battlefield, name) != null;
            case "hand": return named(p, ZoneType.Hand, name) != null;
            case "gy": return named(p, ZoneType.Graveyard, name) != null;
            case "castable": {                                  // in hand or the command zone and castable now (not already out)
                for (ZoneType z : new ZoneType[] {ZoneType.Hand, ZoneType.Command}) {
                    Card c = named(p, z, name);
                    if (c == null) continue;
                    if (c.isLand()) { if (z == ZoneType.Hand && p.canPlayLand(c, false, null)) return true; }
                    else if (ForgeRunner.Watcher.castableNow(c, p)) return true;
                }
                return false;
            }
            case "ready": {
                if (named(p, ZoneType.Battlefield, name) != null) return true;
                for (ZoneType z : new ZoneType[] {ZoneType.Hand, ZoneType.Command}) {
                    Card c = named(p, z, name);
                    if (c == null) continue;
                    if (c.isLand()) { if (z == ZoneType.Hand && p.canPlayLand(c, false, null)) return true; }
                    else if (ForgeRunner.Watcher.castableNow(c, p)) return true;
                }
                return false;
            }
            default: return false;
        }
    }

    static Card named(Player p, ZoneType z, String name) {
        for (Card c : p.getCardsIn(z)) if (c.getName().equals(name)) return c;
        return null;
    }

    int count(Player p, String key) {
        switch (key) {
            case "creatures": return p.getCreaturesInPlay().size();
            case "life": return p.getLife();
            case "lands": return p.getLandsInPlay().size();
            case "mana": return ForgeRunner.Watcher.usableMana(p);
            case "library": return p.getCardsIn(ZoneType.Library).size();
            case "hand": return p.getCardsIn(ZoneType.Hand).size();
            case "artifacts": return (int) p.getCardsIn(ZoneType.Battlefield).stream().filter(Card::isArtifact).count();
            case "gy_creatures": return (int) p.getCardsIn(ZoneType.Graveyard).stream().filter(Card::isCreature).count();
            case "gy_lands": return (int) p.getCardsIn(ZoneType.Graveyard).stream().filter(Card::isLand).count();
            case "cmd_attached": { Card c = cmdOut(p); return c == null ? 0 : c.getAttachedCards().size(); }
            case "hand_cmc": return p.getCardsIn(ZoneType.Hand).stream().filter(Card::isPermanent).mapToInt(Card::getCMC).max().orElse(0);
            case "big_other": return p.getCreaturesInPlay().stream().filter(c -> !c.isCommander()).mapToInt(Card::getNetPower).max().orElse(0);   // power: Jarad drains by it
            default: throw new IllegalArgumentException("unknown need " + key);
        }
    }

    // ---- did ----
    static boolean done(Window w, String d, boolean won) {
        if (d.equals("win")) return won;
        if (d.equals("attack:cmd")) return w.attackedWithCmd;
        if (d.startsWith("cast_cmc>=")) return w.maxCmc >= Integer.parseInt(d.substring(10).trim());
        int i = d.indexOf(':');
        if (i < 0) return false;
        String kind = d.substring(0, i), rest = d.substring(i + 1);
        int min = 1;
        int ge = rest.indexOf(">=");
        if (ge >= 0) { min = Integer.parseInt(rest.substring(ge + 2).trim()); rest = rest.substring(0, ge); }
        int n = 0;
        for (String name : rest.split("/")) {
            String nm = name.trim();
            switch (kind) {
                case "cast": n += w.casts.getOrDefault(nm, 0); break;
                case "act": n += w.acts.getOrDefault(nm, 0); break;
                case "play": n += w.lands.contains(nm) ? 1 : 0; break;
                default: break;
            }
        }
        return n >= min;
    }
}
