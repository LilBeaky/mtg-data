import forge.game.Game;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.keyword.Keyword;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.trigger.Trigger;
import forge.game.trigger.TriggerType;
import forge.game.zone.ZoneType;

import java.util.*;

/** Threat assessment, phase 1 (the user, 2026-10-16): a score per player for how close it is to winning the game (threat) and
 *  how close to dying (vulnerability), from public information and hand counts only. Logged at the start of every turn's
 *  first main phase as #FP-THREAT; nothing acts on it yet. The user's ranking: combo proximity outweighs everything except a
 *  board clock that kills within two turns.
 *
 *  threat = combo + clock + engines + resources + alt-win, where
 *    combo      (0-100) the seat's known combos (pilot policy intel, Commander Spellbook): all pieces on the battlefield 100
 *               (a win combo; 60 otherwise), one missing 55 scaled by its hand (cards to find it with), two missing 15
 *    clock      turns for its board to kill another player, the opposing creatures chump-blocking its biggest attackers;
 *               2 turns or less overrides: threat is at least 110 (one turn) or 100 (two)
 *               otherwise it adds 50 / turns
 *    engines    (0-40) its permanents with triggers that do something for it (draws, tokens, life, counters, mana, damage),
 *               8 each, and 10 more when its commander is on the battlefield
 *    resources  (0-30) 2 per card in hand plus 1 per mana source on the battlefield
 *    alt-win    (0-60) a "wins with an empty library" permanent out with 5 or fewer cards left; poison it dealt (7+)
 *  vulnerability (0-100) = 2 per life under 40, plus 5 per missing untapped blocker under 5. */
public final class ThreatModel {
    final Game g;
    final List<String> log = new ArrayList<>();

    ThreatModel(Game g) { this.g = g; }

    static final EnumSet<ApiType> GOOD = EnumSet.of(ApiType.Draw, ApiType.Token, ApiType.GainLife, ApiType.LoseLife,
            ApiType.DealDamage, ApiType.PutCounter, ApiType.PutCounterAll, ApiType.Mana, ApiType.Dig, ApiType.Pump,
            ApiType.PumpAll, ApiType.CopyPermanent, ApiType.ChangeZone);

    static boolean engine(Card c) {
        for (Trigger t : c.getTriggers()) {
            if (t.getMode() == TriggerType.Phase && "Card.Self".equals(t.getParam("ValidCard"))) continue;
            SpellAbility ex;
            try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
            for (SpellAbility x = ex; x != null; x = x.getSubAbility()) {
                if (x.getApi() != null && GOOD.contains(x.getApi())) return true;
            }
        }
        return false;
    }

    /** A permanent whose replacement makes drawing from an empty library win (Laboratory Maniac, Jace, Wielder of Mysteries). */
    static boolean emptyLibraryWin(Card c) {
        for (forge.game.replacement.ReplacementEffect re : c.getReplacementEffects()) {
            if (re.getMode() != forge.game.replacement.ReplacementType.Draw) continue;
            SpellAbility ov = re.getOverridingAbility();
            for (SpellAbility x = ov; x != null; x = x.getSubAbility()) if (x.getApi() == ApiType.WinsGame) return true;
        }
        return false;
    }

    /** Turns for p's creatures to kill its most killable opponent: each opponent's untapped creatures chump-block p's biggest
     *  attackers (fliers only by fliers or reach). 99 when it can't. */
    int clockTurns(Player p) {
        List<Integer> ground = new ArrayList<>(), air = new ArrayList<>();
        for (Card c : p.getCreaturesInPlay()) {
            if (c.hasKeyword(Keyword.DEFENDER)) continue;
            int pw = Math.max(0, c.getNetCombatDamage());
            if (pw == 0) continue;
            (c.hasKeyword(Keyword.FLYING) || c.hasKeyword(Keyword.TRAMPLE) || c.hasKeyword(Keyword.SHADOW) ? air : ground).add(pw);
        }
        ground.sort(Collections.reverseOrder());
        air.sort(Collections.reverseOrder());
        int best = 99;
        for (Player o : p.getOpponents()) {
            if (o.hasLost() || !o.canLoseLife()) continue;
            int groundBlock = 0, airBlock = 0;
            for (Card b : o.getCreaturesInPlay()) {
                if (b.isTapped()) continue;
                if (b.hasKeyword(Keyword.FLYING) || b.hasKeyword(Keyword.REACH)) airBlock++;
                else groundBlock++;
            }
            int dmg = 0;
            for (int i = Math.min(airBlock, air.size()); i < air.size(); i++) dmg += air.get(i);
            int spareAirBlockers = Math.max(0, airBlock - air.size());
            for (int i = Math.min(groundBlock + spareAirBlockers, ground.size()); i < ground.size(); i++) dmg += ground.get(i);
            if (dmg <= 0) continue;
            best = Math.min(best, (o.getLife() + dmg - 1) / dmg);
        }
        return best;
    }

    void check(int turn, Player active) {
        StringBuilder sb = new StringBuilder("{\"t\": " + turn + ", \"active\": \"" + seat(active) + "\", \"seats\": {");
        boolean first = true;
        for (Player p : g.getPlayers()) {
            if (p.hasLost()) continue;
            PilotPolicy pol = p.getController() instanceof ForgeRunner.SafeControllerAi c ? c.policy : null;
            Set<String> field = new HashSet<>();
            for (Card c : p.getCardsIn(ZoneType.Battlefield)) field.add(c.getName());
            int hand = p.getCardsIn(ZoneType.Hand).size();
            // combo
            double combo = 0;
            if (pol != null) {
                for (PilotPolicy.Combo cb : pol.in.combos) {
                    if (cb.cards.size() < 2) continue;
                    int missing = 0;
                    for (String x : cb.cards) if (!field.contains(x)) missing++;
                    double v = missing == 0 ? (cb.win ? 100 : 60) : missing == 1 ? 55 * Math.min(1.0, (hand + 1) / 4.0) * (cb.win ? 1 : 0.6)
                            : missing == 2 ? 15 * (cb.win ? 1 : 0.6) : 0;
                    combo = Math.max(combo, v);
                }
            }
            // engines
            int engines = 0;
            boolean cmdOut = false;
            int manaSources = 0;
            for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
                if (c.isCommander() && c.getOwner() == p) cmdOut = true;
                if (!c.getManaAbilities().isEmpty()) manaSources++;
                if (!c.isLand() && engine(c)) engines++;
            }
            double eng = Math.min(40, 8 * engines + (cmdOut ? 10 : 0));
            double res = Math.min(30, 2 * hand + manaSources);
            // alt-win
            double alt = 0;
            int lib = p.getCardsIn(ZoneType.Library).size();
            if (lib <= 5) {
                for (Card c : p.getCardsIn(ZoneType.Battlefield)) if (emptyLibraryWin(c)) { alt = 60; break; }
            }
            for (Player o : p.getOpponents()) if (!o.hasLost() && o.getPoisonCounters() >= 7) alt = Math.max(alt, 40);
            int clock = clockTurns(p);
            double threat = combo + eng + res + alt + (clock <= 20 ? 50.0 / clock : 0);
            if (clock <= 1) threat = Math.max(threat, 110);
            else if (clock <= 2) threat = Math.max(threat, 100);
            // vulnerability
            int blockers = 0;
            for (Card b : p.getCreaturesInPlay()) if (!b.isTapped()) blockers++;
            double vul = Math.min(100, 2 * Math.max(0, 40 - p.getLife()) + 5 * Math.max(0, 5 - blockers));
            if (!first) sb.append(", ");
            first = false;
            sb.append("\"").append(seat(p)).append("\": {\"threat\": ").append(Math.round(threat)).append(", \"combo\": ").append(Math.round(combo))
                    .append(", \"clock\": ").append(clock).append(", \"engines\": ").append(engines).append(", \"res\": ").append(Math.round(res))
                    .append(", \"alt\": ").append(Math.round(alt)).append(", \"vul\": ").append(Math.round(vul)).append(", \"life\": ").append(p.getLife()).append("}");
        }
        sb.append("}}");
        log.add(sb.toString());
    }

    static String seat(Player p) { return p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1"); }
}
