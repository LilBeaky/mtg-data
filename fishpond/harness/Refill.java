import forge.ai.ComputerUtilMana;
import forge.game.ability.AbilityUtils;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.trigger.Trigger;
import forge.game.trigger.TriggerType;
import forge.game.zone.ZoneType;

import java.util.*;

/**
 * Refills: an effect that discards (or shuffles away) its controller's hand and draws (Knollspine Dragon, Wheel of Fortune,
 * Windfall, Reforge the Soul, Timetwister). The user, 2026-10-20: score the hand it has, project the score of the draw from how
 * many cards it will draw, with the mulligan scorer's logic and mid-game gates. Forge patch 78 asks this for every pilot seat.
 *
 *   keep      HandScore's role scoring of the hand that would go: each spell 1 plus its role (key/tutor 3, draw 2, interaction
 *             1.5, creature 1, other 0.5; the commander's role half; repeats 0.7; Game Changers +1), with this turn's mana in place of
 *             the opening gate: a spell no battlefield source can make the colors for 0.25, one costing more than the mana now + 2
 *             0.5; a land 0.6 while the seat has under 7 lands (0.2 after), ramp 0.5 more while under 6
 *   draw      the expected score of N cards from the library as it is (what's left, not the list), the same way, counting only the
 *             cards that will stay: hand size (all of them with no maximum) plus what the mana left after the refill can cast
 *   costs     the opponents' draw punishers (life x LIFE) and, for a refill every player gets, the opponents' new cards (OPP_GAIN x an
 *             average card per card each gets beyond its hand) unless the seat has payoffs for opponents drawing (Xyris)
 *   verdict   refill when the projected draw beats the hand by MARGIN (-Dfishpond.refillMargin, for tuning)
 *   scarcity  (the user, 2026-10-21: a card is worth more the smaller the hand, rising steeply toward an empty one) each card the
 *             refill adds past the hand's size fills a slot k (the cards already in hand before it) and is worth an average drawn card
 *             times scarcity(k) = 1 + SCARCITY x DECAY^k (Forge patch 80's curve: 4x into an empty hand, 1.75x with two); an
 *             opponent's new cards count the same way from its own hand's size
 *   feeding   (the user: punishment "exponentially when stacked") the cards drawn traced through the opponents' triggers: a draw
 *             payoff that makes tokens (Xyris's Snakes) times what each token entering does to the seat (Purphoros: 2), plus the
 *             tokens themselves (TOKEN each)
 */
final class Refill {
    static final boolean ON = !"false".equals(System.getProperty("fishpond.refill"));
    static final double MARGIN = Double.parseDouble(System.getProperty("fishpond.refillMargin", "2.0"));
    static final double LIFE = Double.parseDouble(System.getProperty("fishpond.refillLife", "0.25"));
    static final double OPP_GAIN = Double.parseDouble(System.getProperty("fishpond.refillOpp", "0.5"));
    static final double PAYOFF = Double.parseDouble(System.getProperty("fishpond.refillPayoff", "1.0"));   // a draw payoff's trigger
    static final double OPEN_MANA = 1.5;   // an opponent with 2+ untapped lands uses its new cards at once (the user: "if they have a response")
    static final double LAND = 0.6, LAND_LATE = 0.2, RAMP_EARLY = 0.5;
    static final double SCARCITY = Double.parseDouble(System.getProperty("fishpond.drawScarcity", "3"));
    static final double DECAY = Double.parseDouble(System.getProperty("fishpond.drawDecay", "0.5"));
    static final double TOKEN = Double.parseDouble(System.getProperty("fishpond.refillToken", "0.25"));   // an opponent's token, in hand-score units
    static final int SAMPLES = 200;

    /** Patch 78's hook: refill? null when sa isn't one or the score is off. */
    static Boolean judge(Player ai, SpellAbility sa) {
        try {
            return judge0(ai, sa);
        } catch (RuntimeException e) {
            System.out.println("#FP-WARN refill: " + e);
            return null;
        }
    }

    static Boolean judge0(Player ai, SpellAbility sa) {
        if (!ON || sa == null || sa.getHostCard() == null || !ThreatModel.REAL.contains(ai.getGame()) || !refill(sa)) return null;   // the real game only, as the threat hooks
        if (sa.isTrigger() && (sa.getTrigger() == null || !sa.getTrigger().hasParam("OptionalDecider"))) return null;   // a mandatory trigger just happens (Whirlpool Warrior's)
        PilotPolicy pol = ThreatModel.policyOf(ai);
        Card host = sa.getHostCard();
        List<Card> hand = new ArrayList<>(ai.getCardsIn(ZoneType.Hand));
        hand.remove(host);
        int cost = sa.getPayCosts() == null || sa.getPayCosts().getTotalMana() == null || !host.isInZone(ZoneType.Hand) ? 0
                : sa.getPayCosts().getTotalMana().getCMC();
        int manaNow = Math.max(0, ComputerUtilMana.getAvailableManaEstimate(ai, false));
        int manaAfter = Math.max(0, manaNow - cost);
        Set<Character> cols = colorsOnBoard(ai);
        int base = drawCount(ai, sa);
        int n = base * drawMultiplier(ai);   // Thought Reflection, Teferi's Ageless Insight: each draw is two
        double keep = value(ai, pol, hand, manaNow, cols);
        int maxHand = ai.isUnlimitedHandSize() ? Integer.MAX_VALUE : ai.getMaxHandSize();
        double avgCmc = avgSpellCmc(ai);
        int cap = maxHand == Integer.MAX_VALUE ? n : Math.min(n, maxHand + (int) Math.floor(manaAfter / Math.max(1.0, avgCmc)));
        double expect = expected(ai, pol, n, cap, manaAfter, cols);
        double perCard = n == 0 ? 0 : expect / Math.max(1, cap);   // an average drawn card
        double scarce = 0;
        for (int k = hand.size(); k < cap; k++) scarce += scarcity(k) - 1;
        double bonus = perCard * scarce;
        int[] fed = feeding(ai, sa, n, base);   // {life the seat loses, tokens the opponents get}
        int punish = punishment(ai, n) + fed[0];
        // draw payoffs (the user, 2026-10-20: "draw payoffs should massively increase the evaluation of casting the wheel effects,
        // including things like draw multipliers"): each trigger on the seat's own draws, and on opponents' draws for a refill they share
        int oppDraws = 0;
        if (symmetric(sa)) for (Player o : ai.getOpponents()) if (!o.hasLost()) oppDraws += base;
        int[] pay = payoffTriggers(ai);
        double payoff = PAYOFF * (pay[0] * n + pay[1] * oppDraws);
        double opp = 0;
        if (symmetric(sa) && pay[1] == 0) {
            for (Player o : ai.getOpponents()) {
                if (o.hasLost()) continue;
                double w = untappedLands(o) >= 2 ? OPP_GAIN * OPEN_MANA : OPP_GAIN;
                double gain = 0;
                for (int k = o.getCardsIn(ZoneType.Hand).size(); k < base; k++) gain += scarcity(k);
                opp += w * perCard * gain;
            }
        }
        opp += TOKEN * fed[1];
        double net = expect + bonus + payoff - LIFE * punish - opp - keep;
        boolean go = net >= MARGIN;
        System.out.println("#FP-REFILL {\"seat\": \"" + ai.getName() + "\", \"turn\": " + ai.getGame().getPhaseHandler().getTurn()
                + ", \"card\": " + ForgeRunner.js(host.getName()) + ", \"hand\": " + hand.size() + ", \"draw\": " + n + ", \"cap\": " + cap
                + ", \"mana_after\": " + manaAfter + ", \"keep\": " + HandScore.round(keep) + ", \"expect\": " + HandScore.round(expect) + ", \"scarce\": " + HandScore.round(bonus)
                + ", \"punish\": " + punish + ", \"tokens\": " + fed[1] + ", \"payoff\": " + HandScore.round(payoff) + ", \"opp\": " + HandScore.round(opp) + ", \"net\": " + HandScore.round(net)
                + ", \"margin\": " + MARGIN + ", \"refill\": " + go + ", \"cards\": " + names(hand) + "}");
        return go;
    }

    /** The hand's card names as a JSON list, for the log. */
    static String names(List<Card> cards) {
        StringBuilder b = new StringBuilder("[");
        for (Card c : cards) b.append(b.length() > 1 ? ", " : "").append(ForgeRunner.js(c.getName()));
        return b.append("]").toString();
    }

    // ---------------------------------------------------------------- what the effect is
    /** sa (or, for a permanent spell, its enter trigger) discards or shuffles away its controller's hand and draws. */
    static boolean refill(SpellAbility sa) {
        if (chainRefills(sa)) return true;
        Card host = sa.getHostCard();
        if (sa.isSpell() && host.isPermanent()) {
            for (Trigger t : host.getTriggers()) {
                if (t.getMode() != TriggerType.ChangesZone || !"Battlefield".equals(t.getParam("Destination"))) continue;
                try { if (t.ensureAbility() != null && chainRefills(t.ensureAbility())) return true; } catch (RuntimeException e) { }
            }
        }
        return false;
    }

    static boolean chainRefills(SpellAbility sa) {
        boolean loses = false, draws = false;
        for (SpellAbility x = sa; x != null; x = x.getSubAbility()) {
            ApiType api = x.getApi();
            if (api == ApiType.Discard && "Hand".equals(x.getParam("Mode"))) loses = true;
            if (api == ApiType.ChangeZoneAll && x.getParamOrDefault("Origin", "").contains("Hand")   // the whole hand (Timetwister), not one card (Enter the Infinite puts one back)
                    && ("Library".equals(x.getParam("Destination")) || "Graveyard".equals(x.getParam("Destination")) || "Exile".equals(x.getParam("Destination")))) loses = true;
            if (api == ApiType.Draw && includesYou(x)) draws = true;
        }
        return loses && draws;
    }

    static boolean includesYou(SpellAbility x) {
        String d = x.getParamOrDefault("Defined", "You");
        return d.equals("You") || d.equals("Player");
    }

    static boolean symmetric(SpellAbility sa) {
        for (SpellAbility x = sa; x != null; x = x.getSubAbility())
            if (x.getApi() == ApiType.Draw && "Player".equals(x.getParam("Defined"))) return true;
        return false;
    }

    /** Cards the seat would draw: the Draw's amount now; an amount set at resolution (Windfall: the most cards discarded) reads 0
     *  before, so a symmetric refill reading 0 takes the biggest hand at the table. */
    static int drawCount(Player ai, SpellAbility sa) {
        List<SpellAbility> chain = new ArrayList<>();
        for (SpellAbility x = sa; x != null; x = x.getSubAbility()) chain.add(x);
        Card host = sa.getHostCard();
        if (sa.isSpell() && host.isPermanent() && !chainRefills(sa)) {
            for (Trigger t : host.getTriggers()) {
                try {
                    SpellAbility ex = t.ensureAbility();
                    if (ex != null && chainRefills(ex)) for (SpellAbility x = ex; x != null; x = x.getSubAbility()) chain.add(x);
                } catch (RuntimeException e) { }
            }
        }
        int n = 0;
        for (SpellAbility x : chain) {
            if (x.getApi() != ApiType.Draw || !includesYou(x)) continue;
            try { n += Math.max(0, AbilityUtils.calculateAmount(x.getHostCard(), x.getParamOrDefault("NumCards", "1"), x)); }
            catch (RuntimeException e) { n += 1; }
        }
        if (n == 0 && symmetric(sa)) {
            for (Player p : ai.getGame().getPlayers()) if (!p.hasLost()) n = Math.max(n, p.getCardsIn(ZoneType.Hand).size() - (p == ai ? 1 : 0));
        }
        return n;
    }

    // ---------------------------------------------------------------- scoring with this turn's mana
    /** HandScore's role scoring for cards held mid-game (no opening-hand gate). */
    static double value(Player ai, PilotPolicy pol, List<Card> cards, int mana, Set<Character> cols) {
        Set<String> cmdRoles = new HashSet<>();
        for (Card c : ai.getCardsIn(ZoneType.Command)) if (c.isCommander() && ai.equals(c.getOwner())) cmdRoles.add(HandScore.info(ai, pol, c).role());
        for (Card c : ai.getCardsIn(ZoneType.Battlefield)) if (c.isCommander() && ai.equals(c.getOwner())) cmdRoles.add(HandScore.info(ai, pol, c).role());
        cmdRoles.remove("other");
        int landsOut = ai.getLandsInPlay().size();
        Map<String, List<Double>> byRole = new HashMap<>();
        double total = 0;
        int landsHeld = 0;
        for (Card c : cards) {
            HandScore.Info x = HandScore.info(ai, pol, c);
            if (x.land()) {
                total += (landsOut + landsHeld < 7 ? LAND : LAND_LATE) * Math.pow(HandScore.REPEAT, landsHeld);
                landsHeld++;
                continue;
            }
            double v = HandScore.BASE + HandScore.W.get(x.role()) * (cmdRoles.contains(x.role()) ? HandScore.COMMANDER_ROLE : 1);
            boolean colorsOk = true;
            for (char ch : x.pips().toCharArray()) if (!cols.contains(ch)) colorsOk = false;
            if (!colorsOk) v *= HandScore.UNCASTABLE;
            else if (x.cmc() > mana + 2) v *= HandScore.LATE;
            if (x.ramp() > 0 && landsOut < 6) v += RAMP_EARLY;
            if (x.gc()) v += HandScore.GAME_CHANGER;
            byRole.computeIfAbsent(x.role(), k -> new ArrayList<>()).add(v);
        }
        for (List<Double> vs : byRole.values()) {
            vs.sort(Comparator.reverseOrder());
            for (int k = 0; k < vs.size(); k++) total += vs.get(k) * Math.pow(HandScore.REPEAT, k);
        }
        return total;
    }

    /** How much more a card is worth with k cards already in hand (Forge patch 80's curve): 4x into an empty hand, 1.75x with
     *  two, about 1x from six (DECAY 0.5). */
    static double scarcity(int k) {
        return 1 + SCARCITY * Math.pow(DECAY, Math.max(0, k));
    }

    /** The expected value of drawing n cards from the library as it is, keeping the best cap of them. Sampled with a seed made
     *  from the turn and library, so the game's own random numbers aren't touched. */
    static double expected(Player ai, PilotPolicy pol, int n, int cap, int mana, Set<Character> cols) {
        List<Card> lib = new ArrayList<>(ai.getCardsIn(ZoneType.Library));
        if (n <= 0 || lib.isEmpty()) return 0;
        lib.sort(Comparator.comparing(Card::getName));
        Random rng = new Random(31L * ai.getGame().getPhaseHandler().getTurn() + lib.size());
        double sum = 0;
        for (int i = 0; i < SAMPLES; i++) {
            Collections.shuffle(lib, rng);
            List<Card> drawn = new ArrayList<>(lib.subList(0, Math.min(n, lib.size())));
            if (drawn.size() > cap) {   // keep the best cap, card by card
                drawn.sort(Comparator.comparingDouble((Card c) -> -value(ai, pol, List.of(c), mana, cols)));
                drawn = new ArrayList<>(drawn.subList(0, cap));
            }
            sum += value(ai, pol, drawn, mana, cols);
        }
        return sum / SAMPLES;
    }

    static Set<Character> colorsOnBoard(Player ai) {
        String ident = HandScore.letters(ai.getCommanderColorID());
        Set<Character> cols = new HashSet<>();
        for (Card c : ai.getCardsIn(ZoneType.Battlefield)) for (char ch : HandScore.produced(c, ident).toCharArray()) cols.add(ch);
        return cols;
    }

    static double avgSpellCmc(Player ai) {
        int n = 0, sum = 0;
        for (Card c : ai.getCardsIn(ZoneType.Library)) if (!c.isLand()) { n++; sum += c.getCMC(); }
        return n == 0 ? 3 : (double) sum / n;
    }

    /** Life lost to the opponents' draw punishers for drawing n cards (the harness's copy of Forge patch 76's count). */
    static int punishment(Player drawer, int n) {
        if (n <= 0) return 0;
        int total = 0;
        for (Player o : drawer.getOpponents()) {
            if (o.hasLost()) continue;
            for (Card c : o.getCardsIn(ZoneType.Battlefield))
                for (Trigger t : c.getTriggers()) {
                    if (t.getMode() != TriggerType.Drawn || !t.getParamOrDefault("ValidCard", "").contains("Opp")) continue;
                    SpellAbility ex;
                    try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
                    int per = 0;
                    for (SpellAbility x = ex; x != null; x = x.getSubAbility()) {
                        if (x.getApi() == ApiType.DealDamage) per += amount(x, "NumDmg");
                        else if (x.getApi() == ApiType.LoseLife) per += amount(x, "LifeAmount");
                    }
                    total += per * n;
                }
        }
        return total;
    }

    /** The draws traced through the opponents' triggers: {life the seat loses, tokens the opponents get}. A "whenever an opponent
     *  draws" trigger that makes tokens (Xyris) makes them for every card its controller's opponents draw (the seat's n, and each
     *  other player's base for a refill every player gets); each token entering fires that player's "another creature you control
     *  enters" damage or life loss to each opponent (Purphoros, God of the Forge: 2 to the seat per token). */
    static int[] feeding(Player ai, SpellAbility sa, int n, int base) {
        int life = 0, tokens = 0;
        for (Player o : ai.getOpponents()) {
            if (o.hasLost()) continue;
            int perDraw = 0;
            for (Card c : o.getCardsIn(ZoneType.Battlefield))
                for (Trigger t : c.getTriggers()) {
                    if (t.getMode() != TriggerType.Drawn || !t.getParamOrDefault("ValidCard", "").contains("Opp")) continue;
                    try {
                        for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility())
                            if (x.getApi() == ApiType.Token) perDraw += amount(x, "TokenAmount");
                    } catch (RuntimeException e) { }
                }
            if (perDraw == 0) continue;
            int draws = n;
            if (symmetric(sa)) for (Player q : ai.getGame().getPlayers()) if (q != o && q != ai && !q.hasLost()) draws += base;
            int made = perDraw * draws;
            int perToken = 0;
            for (Card c : o.getCardsIn(ZoneType.Battlefield))
                for (Trigger t : c.getTriggers()) {
                    if (t.getMode() != TriggerType.ChangesZone || !"Battlefield".equals(t.getParam("Destination"))
                            || !t.getParamOrDefault("ValidCard", "").contains("Creature")) continue;
                    try {
                        for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility()) {
                            String who = x.getParamOrDefault("Defined", "");
                            if (x.getApi() == ApiType.DealDamage && who.contains("Opponent")) perToken += amount(x, "NumDmg");
                            else if (x.getApi() == ApiType.LoseLife && who.contains("Opponent")) perToken += amount(x, "LifeAmount");
                        }
                    } catch (RuntimeException e) { }
                }
            tokens += made;
            life += made * perToken;
        }
        return new int[] {life, tokens};
    }

    static int amount(SpellAbility x, String p) {
        try { return Integer.parseInt(x.getParamOrDefault(p, "1")); } catch (NumberFormatException e) { return 1; }
    }

    /** Draw payoffs on the seat's battlefield: {triggers on its own draws, triggers on opponents' draws} that do it good (damage, life,
     *  tokens, cards, counters, pumps: Psychosis Crawler, Niv-Mizzet, The Locust God; Xyris, Consecrated Sphinx), each counted per draw. */
    static int[] payoffTriggers(Player ai) {
        int own = 0, opp = 0;
        EnumSet<ApiType> good = EnumSet.of(ApiType.DealDamage, ApiType.LoseLife, ApiType.GainLife, ApiType.Token, ApiType.Draw,
                ApiType.PutCounter, ApiType.PutCounterAll, ApiType.Pump, ApiType.PumpAll, ApiType.Mana, ApiType.Mill);
        for (Card c : ai.getCardsIn(ZoneType.Battlefield))
            for (Trigger t : c.getTriggers()) {
                if (t.getMode() != TriggerType.Drawn) continue;
                String vc = t.getParamOrDefault("ValidCard", "");
                boolean helps = false;
                try {
                    for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility()) if (x.getApi() != null && good.contains(x.getApi())) helps = true;
                } catch (RuntimeException e) { }
                if (!helps) continue;
                if (vc.contains("Opp")) opp++;
                else if (vc.contains("You") || vc.isEmpty()) own++;
            }
        return new int[] {own, opp};
    }

    /** Draws doubled by the seat's own replacements ("if you would draw a card, draw two cards instead"). */
    static int drawMultiplier(Player ai) {
        int m = 1;
        for (Card c : ai.getCardsIn(ZoneType.Battlefield))
            for (forge.game.replacement.ReplacementEffect re : c.getReplacementEffects()) {
                if (re.getMode() != forge.game.replacement.ReplacementType.Draw) continue;
                try {
                    SpellAbility ov = re.ensureAbility();
                    if (ov != null && ov.getApi() == ApiType.Draw) m *= Math.max(1, amount(ov, "NumCards"));
                } catch (RuntimeException e) { }
            }
        return Math.min(m, 4);
    }

    static int untappedLands(Player p) {
        int n = 0;
        for (Card c : p.getLandsInPlay()) if (!c.isTapped()) n++;
        return n;
    }

    /** The seat profits from opponents drawing (Xyris's Snakes, a "whenever an opponent draws" payoff of its own). */
    static boolean payoffForOpponentsDrawing(Player ai) {
        for (Card c : ai.getCardsIn(ZoneType.Battlefield))
            for (Trigger t : c.getTriggers())
                if (t.getMode() == TriggerType.Drawn && t.getParamOrDefault("ValidCard", "").contains("Opp")) {
                    try {
                        SpellAbility ex = t.ensureAbility();
                        for (SpellAbility x = ex; x != null; x = x.getSubAbility()) if (x.getApi() == ApiType.Token) return true;
                    } catch (RuntimeException e) { }
                }
        return false;
    }
}
