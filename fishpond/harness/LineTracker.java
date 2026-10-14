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
    }

    final Game g;
    final List<Line> all = new ArrayList<>();
    final Map<Player, List<Line>> lines = new LinkedHashMap<>();
    final Map<Player, Window> window = new HashMap<>();
    final Map<Player, List<Line>> open = new HashMap<>();       // lines available at the seat's last check
    final Map<Player, Integer> openTurn = new HashMap<>();
    final Map<Player, Map<Line, Record>> records = new HashMap<>();

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
        List<Line> now = new ArrayList<>();
        for (Line l : linesOf(p)) {
            boolean ok;
            try { ok = l.needs.stream().allMatch(n -> holds(p, n)); } catch (Throwable e) { ok = false; }
            if (ok) { now.add(l); records.get(p).get(l).avail.add(t); }
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
        for (Line l : was) {
            Record r = records.get(p).get(l);
            if (l.did.stream().anyMatch(d -> done(w, d, won))) r.did.add(openTurn.get(p));
            else if (won) r.avail.remove(openTurn.get(p));     // the seat won before its next turn: the line wasn't needed
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
        for (Player p : g.getRegisteredPlayers()) linesOf(p);
        for (Player p : new ArrayList<>(open.keySet())) close(p, p == winner);
        List<String> out = new ArrayList<>();
        for (Map.Entry<Player, Map<Line, Record>> e : records.entrySet()) {
            String seat = e.getKey().getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
            for (Map.Entry<Line, Record> x : e.getValue().entrySet()) {
                Line l = x.getKey();
                out.add("{\"seat\": \"" + seat + "\", \"commander\": " + ForgeRunner.js(l.commander) + ", \"kind\": " + ForgeRunner.js(l.kind)
                        + ", \"line\": " + ForgeRunner.js(l.label) + ", \"avail\": " + x.getValue().avail + ", \"did\": " + x.getValue().did
                        + ", \"won\": " + (e.getKey() == winner) + "}");
            }
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
            case "big_other": return p.getCreaturesInPlay().stream().filter(c -> !c.isCommander()).mapToInt(Card::getNetToughness).max().orElse(0);
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
