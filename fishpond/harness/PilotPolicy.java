// Fishpond pilot policy: picks library-search and dig targets for every seat from what the deck is built to do, instead
// of Forge's generic "best card" pickers. The deck intel comes from fishpond/policy.py (<deck>.dck.policy.json next to
// the .dck); this class adds the board at decision time. General rules only; a deck can add an optional '# priority:'
// header (the "boost" table), and none ships one.
//
// Score per candidate = sum of layers (docs/FORGE_PLAN.md, "Pilot policy"):
//   combo     completes a Commander Spellbook combo with cards in hand, on the battlefield, in the command zone or the
//             source itself (Approach of the Second Sun off Solve the Equation)
//   survival  facing lethal or a board that outclasses yours: removal, wipes, protection, lifegain rise
//   engine    a payoff whose mechanic the deck is built around (strength from policy.py) ranks high until one is on the
//             battlefield; after that the enablers that fire it rise (Astral Slide first, then cyclers)
//   role      what the board lacks against what the deck runs (ramp early, draw when the hand is empty, a win-con late)
//   synergy   how much of the deck the card connects with
//   playable  cards Forge's AI never casts (AI:RemoveDeck:All, unless fishpond overrides the script) score a tenth on
//             every layer when fetched to hand or the library top (a card that rots in hand is no plan); onto the
//             battlefield they count fully, unless all their value is activated abilities (the AI never activates them)
//   boost     the deck's '# priority:' header, if any
//   forge     Forge's own pick gets a small edge, so it wins ties and decks the policy knows nothing about
// Every applied decision is logged ("#FP-POLICY {json}" after the game) with the pick, Forge's pick, the deciding layer and the top scores.
// -Dfishpond.policy=off turns it off (for A/B runs).

import java.io.File;
import java.io.FileReader;
import java.util.*;

import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;

import forge.ai.ComputerUtilMana;
import forge.game.Game;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;

public final class PilotPolicy {
    public static final boolean ON = !"off".equals(System.getProperty("fishpond.policy", "on"));
    static final String[] LAYERS = {"combo", "survival", "engine", "role", "synergy", "boost", "forge"};
    static final int COMBO = 0, SURVIVAL = 1, ENGINE = 2, ROLE = 3, SYNERGY = 4, BOOST = 5, FORGE = 6;

    public static final class CardIntel {
        List<String> roles = new ArrayList<>(), payoff = new ArrayList<>(), enabler = new ArrayList<>();
        double syn, cmc;
        boolean flag, flag_dead, cmdr;
    }
    public static final class Mech { int enablers, payoffs; double s; }
    public static final class Combo { List<String> cards = new ArrayList<>(); boolean win; }
    public static final class Intel {
        int v;
        String deck;
        Map<String, CardIntel> cards = new HashMap<>();
        Map<String, Double> boost = new HashMap<>();
        Map<String, Mech> mechs = new HashMap<>();
        List<Combo> combos = new ArrayList<>();
        Map<String, Double> role_share = new HashMap<>();
    }

    final Intel in;
    final List<String> log = new ArrayList<>();

    PilotPolicy(Intel in) { this.in = in; }

    /** The policy for a seat's deck file, or null when there's no intel (a dummy) or the policy is off. */
    static PilotPolicy load(String deckDir, String dckFile) {
        if (!ON) return null;
        File f = new File(deckDir, dckFile + ".policy.json");
        if (!f.exists()) return null;
        try (FileReader r = new FileReader(f, java.nio.charset.StandardCharsets.UTF_8)) {
            Intel in = new Gson().fromJson(r, new TypeToken<Intel>() {}.getType());
            return in == null ? null : new PilotPolicy(in);
        } catch (Exception e) {
            System.out.println("#FP-WARN policy intel unreadable for " + dckFile + ": " + e);
            return null;
        }
    }

    // ------------------------------------------------------------------ when the policy applies

    /** A library search of the player's own library into hand, play or the top of the library (not lands-only lists). */
    static boolean appliesToSearch(ZoneType dest, List<ZoneType> origin, List<Card> fetch, Player decider, Player me) {
        if (fetch == null || fetch.size() < 2 || decider != me || origin == null || !origin.contains(ZoneType.Library)) return false;
        if (dest != ZoneType.Hand && dest != ZoneType.Battlefield && dest != ZoneType.Library) return false;
        boolean nonland = false;
        for (Card c : fetch) {
            if (c.getOwner() != me || !c.isInZone(ZoneType.Library)) return false;
            if (!c.isLand()) nonland = true;
        }
        return nonland;                                   // fetchlands and land tutors: Forge's land logic is fine
    }

    /** A dig (look at the top N, take some) of the player's own library into hand or play. */
    static boolean appliesToDig(SpellAbility sa, Collection<?> options, Player me) {
        if (sa == null || options == null || options.size() < 2) return false;
        if (sa.getApi() != ApiType.Dig && sa.getApi() != ApiType.DigUntil) return false;
        String dest = sa.hasParam("DestinationZone") ? sa.getParam("DestinationZone") : "Hand";
        if (!dest.equals("Hand") && !dest.equals("Battlefield")) return false;
        for (Object o : options) if (!(o instanceof Card c) || c.getOwner() != me) return false;
        return true;
    }

    // ------------------------------------------------------------------ scoring

    static final class Board {
        Set<String> have = new HashSet<>();          // hand + battlefield + command zone (+ the source)
        Set<String> field = new HashSet<>();         // battlefield + command-zone commanders that are out
        int lands, mana, hand, life, turn, oppPower, oppCreatures, myCreatures;
        Map<String, Integer> fieldRoles = new HashMap<>();
        boolean engineOut;
    }

    Board board(Player me, SpellAbility sa) {
        Board b = new Board();
        for (Card c : me.getCardsIn(ZoneType.Hand)) b.have.add(c.getName());
        for (Card c : me.getCardsIn(ZoneType.Command)) b.have.add(c.getName());
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) { b.have.add(c.getName()); b.field.add(c.getName()); }
        if (sa != null && sa.getHostCard() != null) b.have.add(sa.getHostCard().getName());
        b.lands = me.getLandsInPlay().size();
        try { b.mana = ComputerUtilMana.getAvailableManaEstimate(me, false); } catch (Throwable t) { b.mana = b.lands; }
        b.hand = me.getCardsIn(ZoneType.Hand).size();
        b.life = me.getLife();
        Game g = me.getGame();
        b.turn = (g.getPhaseHandler().getTurn() + 3) / 4;  // rough "own turn" count in a 4-player game
        b.myCreatures = me.getCreaturesInPlay().size();
        for (Player o : me.getOpponents()) {
            int pw = 0;
            for (Card c : o.getCreaturesInPlay()) pw += Math.max(0, c.getNetPower());
            b.oppPower = Math.max(b.oppPower, pw);
            b.oppCreatures = Math.max(b.oppCreatures, o.getCreaturesInPlay().size());
        }
        for (String n : b.field) {
            CardIntel ci = in.cards.get(n);
            if (ci == null) continue;
            for (String r : ci.roles) b.fieldRoles.merge(r, 1, Integer::sum);
            if (!ci.payoff.isEmpty()) b.engineOut = true;
        }
        return b;
    }

    double[] score(Card c, Board b, ZoneType dest, boolean forgePick) {
        double[] s = new double[LAYERS.length];
        String n = c.getName();
        CardIntel ci = in.cards.get(n);
        // combo
        for (Combo cb : in.combos) {
            if (!cb.cards.contains(n)) continue;
            int missing = 0;
            for (String x : cb.cards) if (!x.equals(n) && !b.have.contains(x)) missing++;
            double v = missing == 0 ? (cb.win ? 1200 : 700) : missing == 1 ? (cb.win ? 160 : 60) : 0;
            s[COMBO] = Math.max(s[COMBO], v);
        }
        if (ci != null) {
            // survival
            double danger = b.oppPower >= b.life ? 1.0 : b.oppPower * 2 >= b.life || b.life <= 10 ? 0.5 : 0.0;
            if (danger > 0) {
                double v = 0;
                if (ci.roles.contains("wipe") && b.oppCreatures >= 3 && b.oppCreatures > b.myCreatures) v = Math.max(v, 420);
                if (ci.roles.contains("protection")) v = Math.max(v, 360);
                if (ci.roles.contains("removal")) v = Math.max(v, 260);
                if (ci.roles.contains("lifegain")) v = Math.max(v, 120);
                if (ci.roles.contains("counter")) v = Math.max(v, 100);
                s[SURVIVAL] = v * danger;
            }
            // engine
            double pay = 0, en = 0;
            for (String m : ci.payoff) {
                Mech me = in.mechs.get(m);
                if (me == null) continue;
                int out = 0;                              // payoffs of this mechanic already on the battlefield
                for (String f : b.field) { CardIntel o = in.cards.get(f); if (o != null && o.payoff.contains(m)) out++; }
                pay = Math.max(pay, 320 * me.s / (1 + 2 * out));   // the first payoff turns the engine on; more add less
            }
            for (String m : ci.enabler) {
                Mech me = in.mechs.get(m);
                if (me == null) continue;
                for (String f : b.field) {
                    CardIntel o = in.cards.get(f);
                    if (o != null && o.payoff.contains(m)) { en = Math.max(en, 200 * me.s); break; }
                }
            }
            s[ENGINE] = pay + en;
            if (ci.roles.contains("engine") && ci.payoff.isEmpty() && !b.fieldRoles.containsKey("engine")) s[ENGINE] += 60;
            // role gap
            double role = 0;
            for (String r : ci.roles) {
                double need = switch (r) {
                    case "ramp" -> b.turn <= 6 && (b.lands < 5 || b.mana < 5) ? 1.0 : 0.2;
                    case "land" -> dest == ZoneType.Battlefield && b.lands < 6 ? 0.8 : 0.1;
                    case "draw" -> b.hand <= 2 ? 1.0 : 0.4;
                    case "wincon" -> b.turn >= 8 || b.engineOut ? 0.9 : 0.25;
                    case "removal" -> b.oppCreatures > 0 ? 0.5 : 0.2;
                    case "wipe" -> b.oppCreatures >= 3 && b.oppCreatures > b.myCreatures + 1 ? 0.7 : 0.1;
                    case "protection" -> b.engineOut ? 0.7 : 0.4;
                    case "counter" -> 0.35;
                    case "hate" -> 0.3;
                    default -> 0.0;
                };
                int onBoard = b.fieldRoles.getOrDefault(r, 0);
                double share = in.role_share.getOrDefault(r, 0.0);
                role = Math.max(role, 200 * need * (1 - Math.min(1.0, onBoard / 2.0)) * (0.5 + share));
            }
            if (dest == ZoneType.Hand && ci.cmc > b.mana + 2) role *= 0.6;   // to hand but far from castable
            s[ROLE] = role;
            s[SYNERGY] = 60 * ci.syn;
            // Forge's AI never casts an AI:RemoveDeck:All card (unless fishpond overrides it), so fetched to hand or the
            // library top it's a dead card; put onto the battlefield (Zur) it works, the flag only stops casting
            if (ci.flag && (dest != ZoneType.Battlefield || ci.flag_dead)) for (int k = 0; k < s.length; k++) s[k] *= 0.1;
        }
        s[BOOST] = in.boost.getOrDefault(n, 0.0);
        if (b.field.contains(n) && c.getType().isLegendary()) Arrays.fill(s, 0);   // legend rule: a second copy is useless
        if (forgePick) s[FORGE] = 15;
        return s;
    }

    static double sum(double[] s) { double t = 0; for (double x : s) t += x; return t; }

    /** Rank candidates (best first) with their score vectors. */
    List<Map.Entry<Card, double[]>> rank(List<Card> cands, Player me, SpellAbility sa, ZoneType dest, Card forgePick) {
        Board b = board(me, sa);
        List<Map.Entry<Card, double[]>> out = new ArrayList<>();
        for (Card c : cands) out.add(Map.entry(c, score(c, b, dest, c == forgePick)));
        out.sort((x, y) -> Double.compare(sum(y.getValue()), sum(x.getValue())));
        return out;
    }

    /** Record the decision: why the pick beat Forge's (the layer with the biggest lead), and the top three. */
    void note(Player me, SpellAbility sa, String kind, ZoneType dest, List<Map.Entry<Card, double[]>> ranked, Card pick,
              Card forgePick, String mode) {
        double[] p = null, f = null;
        for (var e : ranked) { if (e.getKey() == pick) p = e.getValue(); if (e.getKey() == forgePick) f = e.getValue(); }
        String layer = "forge";
        if (p != null && pick != forgePick) {
            double best = 0;
            for (int i = 0; i < LAYERS.length; i++) {
                double d = p[i] - (f == null ? 0 : f[i]);
                if (d > best) { best = d; layer = LAYERS[i]; }
            }
        } else if (p != null && pick == forgePick) layer = "agree";
        StringBuilder top = new StringBuilder();
        for (int i = 0; i < Math.min(3, ranked.size()); i++) {
            var e = ranked.get(i);
            if (i > 0) top.append(", ");
            top.append("[").append(ForgeRunner.js(e.getKey().getName())).append(", ").append(Math.round(sum(e.getValue()))).append(", {");
            boolean first = true;
            for (int k = 0; k < LAYERS.length; k++) {
                if (Math.round(e.getValue()[k]) == 0) continue;
                top.append(first ? "" : ", ").append("\"").append(LAYERS[k]).append("\": ").append(Math.round(e.getValue()[k]));
                first = false;
            }
            top.append("}]");
        }
        Game g = me.getGame();
        String seat = me.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
        String line = "{\"seat\": " + seat + ", \"gt\": " + g.getPhaseHandler().getTurn()
                + ", \"active\": " + (g.getPhaseHandler().getPlayerTurn() == me)
                + ", \"kind\": \"" + kind + "\", \"src\": " + ForgeRunner.js(sa != null && sa.getHostCard() != null ? sa.getHostCard().getName() : "?")
                + ", \"to\": \"" + dest + "\", \"n\": " + ranked.size()
                + ", \"pick\": " + ForgeRunner.js(pick == null ? "" : pick.getName())
                + ", \"forge\": " + ForgeRunner.js(forgePick == null ? "" : forgePick.getName())
                + ", \"layer\": \"" + layer + "\", \"mode\": \"" + mode + "\", \"top\": [" + top + "]}";
        log.add(line);
    }
}
