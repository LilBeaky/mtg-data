import forge.game.Game;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.keyword.Keyword;
import forge.game.player.Player;
import forge.game.replacement.ReplacementEffect;
import forge.game.replacement.ReplacementType;
import forge.game.spellability.SpellAbility;
import forge.game.trigger.Trigger;
import forge.game.trigger.TriggerType;
import forge.game.zone.ZoneType;

import java.util.*;

/** Threat assessment (the user, 2026-10-16): a score per player for how close it is to winning the game (threat) and how close
 *  to dying (vulnerability). It uses what a player at the table knows: every deck's list (the pilot policy intel: known combos),
 *  the battlefield, graveyards and hand counts, never a hidden card. Logged at the start of every turn's first main phase as
 *  #FP-THREAT; nothing acts on it yet. The user's rule: combo proximity outweighs everything except a board clock that kills
 *  within two turns.
 *
 *  threat (v2.1) = combo + clock + engines + mana + growth + resources + alt-win, where
 *    combo      (0-100) the seat's known combos with pieces on the battlefield: all of them 100 (a win combo; 60 otherwise),
 *               one missing 55 scaled by its hand (cards to find it with), two missing 15
 *    clock      turns for its board to kill another player, the opposing untapped creatures chump-blocking its biggest
 *               attackers (fliers only by fliers or reach); 2 turns or less overrides: threat at least 110 (one) or 100 (two);
 *               otherwise it adds 50 / turns
 *    engines    payoffs (permanents with triggers that do something for it) 8 each up to 40; enabler -> payoff links 2 each up
 *               to 10; cycles 15 each, up to two (the user: "Astral Slide + Archaeomancer"). Each permanent produces events (a
 *               blink, permanents entering, landfall, tokens, its own and opponents' draws, life gained, opponents' life lost,
 *               damage, counters, sacrifices, mana) and consumes them (its triggers that do something for it, abilities paid
 *               with counters); a blink is the only event that fires a creature's own enter trigger again; lifelink, printed
 *               or granted, turns damage into life gained (Heliod <-> Walking Ballista is a cycle); a permanent feeding itself
 *               counts as a link (Xyris: its combat damage makes the opponent draw, each draw a Snake)
 *    mana       (0-40) the mana it can make next turn (each source's most, times Nyxbloom Ancient-style multipliers, plus mana
 *               triggers: Klauth's attack worth the power that can attack, landfall 1) over the other players' average,
 *               times a hand factor (0.4 + 0.6 x hand/4), 1.5 per mana of lead (the user: Klauth's 30 mana is telegraphed)
 *    growth     (0-15) 1.5 per mana of capacity gained since its turn a round ago
 *    resources  (0-30) 2 per card in hand plus 1 per mana source
 *    alt-win    (0-60) a "wins with an empty library" permanent out with 5 or fewer cards left; poison it dealt (7+)
 *  Momentum (threat gained over the last round) is logged but not scored.
 *  v2 weighted links 15 and cycles 35 with momentum, and on a fresh seed (study150_20261017_threat, 104 games) predicted the
 *  winner a round out less often than v1 (62% vs 69%); every lighter weighting landed at 67-71%, within the noise. Winner
 *  prediction can't separate them; mana and links stay for the decisions they are meant for.
 *  vulnerability (0-100) = 2 per life under 40, plus 5 per missing untapped blocker under 5. */
public final class ThreatModel {
    final Game g;
    final List<String> log = new ArrayList<>();
    final Map<String, TreeMap<Integer, double[]>> history = new HashMap<>();   // seat -> turn -> {mana capacity, threat}

    ThreatModel(Game g) { this.g = g; }

    static final EnumSet<ApiType> GOOD = EnumSet.of(ApiType.Draw, ApiType.Token, ApiType.GainLife, ApiType.LoseLife,
            ApiType.DealDamage, ApiType.PutCounter, ApiType.PutCounterAll, ApiType.Mana, ApiType.Dig, ApiType.Pump,
            ApiType.PumpAll, ApiType.CopyPermanent, ApiType.ChangeZone);

    // ---------------------------------------------------------------- events: what a permanent makes happen and what it feeds on
    static List<SpellAbility> chain(SpellAbility sa) {
        List<SpellAbility> out = new ArrayList<>();
        for (SpellAbility x = sa; x != null; x = x.getSubAbility()) out.add(x);
        return out;
    }

    static boolean good(SpellAbility ex) {
        for (SpellAbility x : chain(ex)) if (x.getApi() != null && GOOD.contains(x.getApi())) return true;
        return false;
    }

    /** Events the permanent's triggers and repeatable activated abilities make. */
    static Set<String> produces(Card c, boolean lifelink) {
        Set<String> ev = new HashSet<>();
        List<SpellAbility> abilities = new ArrayList<>();
        for (Trigger t : c.getTriggers()) {
            // its own enter trigger fires once (Kabira Crossroads' life), not again and again: not an engine's output
            if (t.getMode() == TriggerType.ChangesZone && "Battlefield".equals(t.getParam("Destination"))
                    && t.getParamOrDefault("ValidCard", "").startsWith("Card.Self")) continue;
            try { if (t.ensureAbility() != null) abilities.add(t.ensureAbility()); } catch (RuntimeException e) { }
        }
        for (SpellAbility a : c.getSpellAbilities()) if (a.isActivatedAbility() && !a.isManaAbility()) abilities.add(a);
        boolean returns = false;
        for (String v : c.getSVars().values()) if (v.contains("ChangeZone") && v.contains("Destination$ Battlefield")) returns = true;
        for (SpellAbility a : abilities) {
            if (a.isActivatedAbility() && a.getPayCosts() != null && a.getPayCosts().toString().toLowerCase().contains("sacrifice")) ev.add("sacrifice");
            for (SpellAbility x : chain(a)) {
                ApiType api = x.getApi();
                if (api == null) continue;
                switch (api) {
                    case ChangeZone -> {
                        String dest = x.getParamOrDefault("Destination", "");
                        if (dest.equals("Battlefield")) {
                            ev.add("enters");
                            if (x.getParamOrDefault("ChangeType", "").contains("Land")) ev.add("landfall");
                            if ("Battlefield".equals(x.getParam("Origin"))) ev.add("blink");
                        } else if (dest.equals("Exile") && returns) { ev.add("enters"); ev.add("blink"); }   // exile, then return (Astral Slide)
                    }
                    case Token, CopyPermanent -> { ev.add("token"); ev.add("enters"); }
                    case Draw -> {
                        String def = x.getParamOrDefault("Defined", "You");
                        if (!def.equals("Opponent") && !def.startsWith("Player.Opponent")) ev.add("draw");
                        // an opponent draws too (Xyris's combat damage: "you and that player", a wheel: each player)
                        if (def.contains("Opponent") || def.contains("TriggeredTarget") || def.startsWith("Player") || def.contains("Remembered")) ev.add("oppdraw");
                    }
                    case GainLife -> ev.add("lifegain");
                    case LoseLife -> { if (x.getParamOrDefault("Defined", "").contains("Opponent")) ev.add("lifeloss"); }
                    case DealDamage, DamageAll -> { ev.add("damage"); if (lifelink) ev.add("lifegain"); }
                    case PutCounter, PutCounterAll -> ev.add("counter");
                    case Sacrifice -> ev.add("sacrifice");
                    case Mana -> ev.add("mana");
                    default -> { }
                }
            }
        }
        return ev;
    }

    /** Events the permanent feeds on: its triggers that do something for it, and abilities paid with counters. */
    static Set<String> consumes(Card c) {
        Set<String> ev = new HashSet<>();
        for (Trigger t : c.getTriggers()) {
            SpellAbility ex;
            try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
            if (ex == null || !good(ex)) continue;
            String vc = t.getParamOrDefault("ValidCard", "") + t.getParamOrDefault("ValidToken", "");
            // a trigger on the card's own deeds (Xyris dealing combat damage) doesn't feed on other permanents' events
            if (t.getMode() != TriggerType.ChangesZone && (vc.startsWith("Card.Self") || t.getParamOrDefault("ValidSource", "").startsWith("Card.Self"))) continue;
            switch (t.getMode()) {
                case ChangesZone -> {
                    String dest = t.getParamOrDefault("Destination", ""), orig = t.getParamOrDefault("Origin", "");
                    if (dest.equals("Battlefield")) {
                        if (vc.contains("Land")) ev.add("landfall");
                        else if (vc.contains("OppCtrl") || vc.contains("OppOwn")) { }
                        else if (vc.startsWith("Card.Self")) { if (c.isCreature()) ev.add("blink"); }   // its own enter trigger: only a blink fires it again
                        else ev.add("enters");
                    } else if (orig.equals("Battlefield") && dest.equals("Graveyard")) ev.add("sacrifice");
                }
                case TokenCreated -> ev.add("token");
                case Drawn -> { if (vc.contains("OppOwn")) ev.add("oppdraw"); else ev.add("draw"); }   // Xyris's Snakes feed on opponents' draws
                case LifeGained -> { if (t.getParamOrDefault("ValidPlayer", "You").contains("You")) ev.add("lifegain"); }
                case LifeLost -> { if (t.getParamOrDefault("ValidPlayer", "").contains("Opponent")) ev.add("lifeloss"); }
                case Sacrificed -> ev.add("sacrifice");
                case DamageDone, DamageDoneOnce -> ev.add("damage");
                case CounterAdded, CounterAddedOnce -> ev.add("counter");
                default -> { }
            }
        }
        for (SpellAbility a : c.getSpellAbilities())
            if (a.isActivatedAbility() && a.getPayCosts() != null && a.getPayCosts().toString().toLowerCase().contains("counter")) ev.add("counter");
        return ev;
    }

    static boolean grantsLifelink(Card c) {
        if (c.hasKeyword(Keyword.LIFELINK)) return true;
        for (SpellAbility a : c.getSpellAbilities()) if (a.getParamOrDefault("KW", "").contains("Lifelink")) return true;
        return false;
    }

    /** {payoffs alone, links, cycles} on p's battlefield; the links' names ("Astral Slide>Archaeomancer:enters") go to names. */
    static int[] engineGraph(Player p, List<String> names) {
        List<Card> perms = new ArrayList<>(p.getCardsIn(ZoneType.Battlefield));
        boolean lifelink = false;
        for (Card c : perms) if (grantsLifelink(c)) { lifelink = true; break; }
        int n = perms.size();
        List<Set<String>> prod = new ArrayList<>(), cons = new ArrayList<>();
        for (Card c : perms) { prod.add(produces(c, lifelink)); cons.add(consumes(c)); }
        boolean[][] edge = new boolean[n][n];
        int links = 0, payoffs = 0;
        for (int i = 0; i < n; i++) {
            if (!cons.get(i).isEmpty()) payoffs++;
            for (int j = 0; j < n; j++) {
                if (prod.get(i).isEmpty() || cons.get(j).isEmpty()) continue;
                if (i == j) {   // a permanent that feeds itself (Xyris: its combat damage makes the opponent draw, each draw a Snake)
                    for (String e : prod.get(i)) if (cons.get(i).contains(e) && !e.equals("blink") && !e.equals("enters")) {
                        links++;
                        if (names.size() < 12) names.add(perms.get(i).getName() + ">self:" + e);
                        break;
                    }
                    continue;
                }
                for (String e : prod.get(i)) if (cons.get(j).contains(e)) {
                    edge[i][j] = true;
                    if (names.size() < 12) names.add(perms.get(i).getName() + ">" + perms.get(j).getName() + ":" + e);
                    break;
                }
                if (edge[i][j]) links++;
            }
        }
        int cycles = 0;
        for (int i = 0; i < n; i++)
            for (int j = i + 1; j < n; j++) {
                if (edge[i][j] && edge[j][i]) cycles++;
                for (int k = j + 1; k < n; k++)
                    if ((edge[i][j] && edge[j][k] && edge[k][i]) || (edge[i][k] && edge[k][j] && edge[j][i])) cycles++;
            }
        return new int[] {payoffs, links, cycles};
    }

    // ---------------------------------------------------------------- mana it can make next turn
    static int manaCapacity(Player p) {
        double base = 0, triggered = 0, mult = 1;
        int attackPower = 0;
        for (Card c : p.getCreaturesInPlay()) if (!c.hasKeyword(Keyword.DEFENDER)) attackPower += Math.max(0, c.getNetCombatDamage());
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
            if (!c.getManaAbilities().isEmpty()) base += Math.max(1, Math.min(10, c.getMaxManaProduced()));
            for (ReplacementEffect re : c.getReplacementEffects()) {
                if (re.getMode() != ReplacementType.ProduceMana) continue;
                double f = 2;
                for (String v : c.getSVars().values()) {
                    int i = v.indexOf("ReplaceAmount$ ");
                    if (i >= 0) try { f = Math.max(f, Double.parseDouble(v.substring(i + 15).trim().split("\\s|\\|")[0])); } catch (NumberFormatException e) { }
                }
                mult = Math.max(mult, f);
            }
            for (Trigger t : c.getTriggers()) {
                SpellAbility ex;
                try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
                if (ex == null || ex.getApi() != ApiType.Mana) continue;
                if (t.getMode() == TriggerType.Attacks) {
                    String amount = c.getSVar(ex.getParamOrDefault("Amount", ""));
                    triggered += amount.contains("attacking") && amount.contains("Power") ? attackPower : 1;
                } else triggered += 1;
            }
        }
        return (int) Math.round(base * mult + triggered);
    }

    // ---------------------------------------------------------------- the board's clock
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

    /** A permanent whose replacement makes drawing from an empty library win (Laboratory Maniac, Jace, Wielder of Mysteries). */
    static boolean emptyLibraryWin(Card c) {
        for (ReplacementEffect re : c.getReplacementEffects()) {
            if (re.getMode() != ReplacementType.Draw) continue;
            SpellAbility ov = re.getOverridingAbility();
            for (SpellAbility x = ov; x != null; x = x.getSubAbility()) if (x.getApi() == ApiType.WinsGame) return true;
        }
        return false;
    }

    /** The value a round (4 turns) before, from a seat's history: the latest entry at or before turn - 4. */
    static Double roundAgo(TreeMap<Integer, double[]> h, int turn, int idx) {
        if (h == null) return null;
        Map.Entry<Integer, double[]> e = h.floorEntry(turn - 4);
        return e == null ? null : e.getValue()[idx];
    }

    void check(int turn, Player active) {
        List<Player> alive = new ArrayList<>();
        for (Player p : g.getPlayers()) if (!p.hasLost()) alive.add(p);
        Map<Player, Integer> cap = new HashMap<>();
        for (Player p : alive) cap.put(p, manaCapacity(p));
        StringBuilder sb = new StringBuilder("{\"t\": " + turn + ", \"active\": \"" + seat(active) + "\", \"seats\": {");
        boolean first = true;
        for (Player p : alive) {
            String s = seat(p);
            PilotPolicy pol = p.getController() instanceof ForgeRunner.SafeControllerAi c ? c.policy : null;
            Set<String> field = new HashSet<>();
            boolean cmdOut = false;
            int manaSources = 0;
            for (Card c : p.getCardsIn(ZoneType.Battlefield)) {
                field.add(c.getName());
                if (c.isCommander() && c.getOwner() == p) cmdOut = true;
                if (!c.getManaAbilities().isEmpty()) manaSources++;
            }
            int hand = p.getCardsIn(ZoneType.Hand).size();
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
            List<String> pairNames = new ArrayList<>();
            int[] eg = engineGraph(p, pairNames);
            double eng = Math.min(40, 8 * eg[0]) + Math.min(10, 2 * eg[1]) + 15 * Math.min(2, eg[2]);
            double others = 0;
            for (Player o : alive) if (o != p) others += cap.get(o);
            others = alive.size() > 1 ? others / (alive.size() - 1) : 0;
            int mine = cap.get(p);
            double lead = Math.max(0, mine - others);
            double mana = Math.min(40, 1.5 * lead * (0.4 + 0.6 * Math.min(1.0, hand / 4.0)));
            TreeMap<Integer, double[]> h = history.computeIfAbsent(s, k -> new TreeMap<>());
            Double capAgo = roundAgo(h, turn, 0), threatAgo = roundAgo(h, turn, 1);
            double growth = capAgo == null ? 0 : Math.min(15, 1.5 * Math.max(0, mine - capAgo));
            double res = Math.min(30, 2 * hand + manaSources);
            double alt = 0;
            int lib = p.getCardsIn(ZoneType.Library).size();
            if (lib <= 5) for (Card c : p.getCardsIn(ZoneType.Battlefield)) if (emptyLibraryWin(c)) { alt = 60; break; }
            for (Player o : p.getOpponents()) if (!o.hasLost() && o.getPoisonCounters() >= 7) alt = Math.max(alt, 40);
            int clock = clockTurns(p);
            double base = combo + eng + mana + growth + res + alt + (clock <= 20 ? 50.0 / clock : 0);
            double mom = threatAgo == null ? 0 : Math.min(20, 0.3 * Math.max(0, base - threatAgo));   // logged, not scored (v2.1)
            double threat = base;
            if (clock <= 1) threat = Math.max(threat, 110);
            else if (clock <= 2) threat = Math.max(threat, 100);
            h.put(turn, new double[] {mine, base});
            int blockers = 0;
            for (Card b : p.getCreaturesInPlay()) if (!b.isTapped()) blockers++;
            double vul = Math.min(100, 2 * Math.max(0, 40 - p.getLife()) + 5 * Math.max(0, 5 - blockers));
            if (!first) sb.append(", ");
            first = false;
            sb.append("\"").append(s).append("\": {\"threat\": ").append(Math.round(threat)).append(", \"combo\": ").append(Math.round(combo))
                    .append(", \"clock\": ").append(clock).append(", \"payoffs\": ").append(eg[0]).append(", \"links\": ").append(eg[1])
                    .append(", \"cycles\": ").append(eg[2]).append(", \"mana_cap\": ").append(mine).append(", \"mana\": ").append(Math.round(mana))
                    .append(", \"growth\": ").append(Math.round(growth)).append(", \"mom\": ").append(Math.round(mom)).append(", \"hand\": ").append(hand)
                    .append(", \"alt\": ").append(Math.round(alt)).append(", \"vul\": ").append(Math.round(vul)).append(", \"life\": ").append(p.getLife())
                    .append(", \"cmd\": ").append(cmdOut).append(", \"src\": ").append(manaSources);
            if (!pairNames.isEmpty()) {
                sb.append(", \"pairs\": [");
                for (int i = 0; i < pairNames.size(); i++) sb.append(i > 0 ? ", " : "").append(ForgeRunner.js(pairNames.get(i)));
                sb.append("]");
            }
            sb.append("}");
        }
        sb.append("}}");
        log.add(sb.toString());
    }

    static String seat(Player p) { return p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1"); }
}
