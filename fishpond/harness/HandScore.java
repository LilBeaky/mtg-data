import forge.card.ColorSet;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.staticability.StaticAbility;
import forge.game.staticability.StaticAbilityMode;
import forge.game.trigger.Trigger;
import forge.game.zone.ZoneType;

import java.util.*;

/**
 * The mulligan (the user, 2026-10-18; Forge patch 68 asks this for every pilot seat). A hand passes a mana gate, then scores:
 *
 *   gate     2+ lands and under 6 (0-1 lands is a hard no; the user: "there are keepable 2's")
 *   mana     lands + ramp the hand's lands can cast by turn 3, less 2 x (commander colors no source in the hand makes) / (colors
 *            in the deck): a missing color hurts a 2-color deck far more than a 5-color one. 0.75 a mana up to 5; 1.5 off per mana
 *            under 3 (2-land hands are punished, not barred)
 *   spells   each 1, plus its role: key card or tutor 3, draw 2, interaction (removal, wipes, counters) 1.5, a creature 1, anything
 *            else 0.5; a role the commander already fills counts half (Yusri and Erebos draw, Zur tutors); each further card in a
 *            role 0.7 of the one before; a spell the hand's colors can't cast 0.25; one it can't cast by turn 4 0.5; a Game
 *            Changer +1
 *   the commander   a card of its role the hand can cast on time (x1), a turn late (x0.5), or ahead of curve with ramp (x1.6)
 *   flood    5+ lands with 2 spells or fewer: 3 off
 *
 * Roles come from the deck's oracle tags (policy.py, Scryfall's tagger), checked against the card script where tags overreach (a
 * tutor that needs six copies of itself, a "ramp" that makes no mana); the deck's '# hand:' line overrides a card's role.
 * A 7 keeps when it scores at least what an average 4-card hand of this deck is worth (the bar is worked out from the deck's own
 * list at the first decision; a smaller hand's bar shrinks with its size); 4 cards always keep. Checked by hand against the user's
 * verdicts on 17 hands (15 agree; the two misses were Erebos hands he called close).
 */
final class HandScore {
    static final boolean ON = !"false".equals(System.getProperty("fishpond.handScore"));
    static final double BASE = 1.0, COMMANDER_ROLE = 0.5, REPEAT = 0.7, UNCASTABLE = 0.25, LATE = 0.5;
    static final double MANA_UNIT = 0.75, MANA_CAP = 5, SHORT = 1.5, COLOR = 2.0, EARLY = 1.6, FLOOD = 3.0, GAME_CHANGER = 1.0;
    static final Map<String, Double> W = Map.of("key", 3.0, "tutor", 3.0, "draw", 2.0, "interaction", 1.5, "threat", 1.0, "other", 0.5);
    static final String COLORS = "WUBRG";

    /** What a card is in an opening hand. Strings and numbers only: kept per player in weak maps, so it must not reach the game. */
    record Info(String name, boolean land, double ramp, String reduces, String colors, String pips, int cmc, String role, boolean gc, boolean tapped) { }

    record Result(boolean gate, double score, int lands, double ramp, String missing, double mana, List<String> detail) { }

    static final Map<Player, Map<String, Info>> INFO = Collections.synchronizedMap(new WeakHashMap<>());
    static final Map<Player, Double> BAR = Collections.synchronizedMap(new WeakHashMap<>());

    // ---------------------------------------------------------------- the hook (Forge patch 68)
    /** Mulligan? null when the score is off or the seat has no policy (Forge's patch-26 rule decides). */
    static Boolean wantMulligan(Player ai, int cardsToReturn) {
        if (!ON) return null;
        PilotPolicy pol = ThreatModel.policyOf(ai);
        if (pol == null) return null;
        CardCollectionView hand = ai.getCardsIn(ZoneType.Hand);
        if (hand.isEmpty()) return false;
        // Forge's London mulligan bottoms the cards (toBottom) before it asks, so the hand here is the one that would be kept;
        // cardsToReturn is how many already went (patch 26's rule took them off again: its "4 or fewer cards" fired at 5)
        List<Card> kept = new ArrayList<>(hand);
        int size = kept.size();
        Result r = score(ai, pol, kept);
        double bar = bar(ai, pol) * Math.min(1.0, size / 7.0);
        boolean mull = size > 4 && !(r.gate() && r.score() >= bar);
        String why = size <= 4 ? "4 or fewer cards: always keep" : !r.gate() ? (r.lands() < 2 ? "under 2 lands" : "6+ lands")
                : mull ? "score under the bar" : "score met the bar";
        StringBuilder b = new StringBuilder("#FP-MULL {\"player\": \"").append(ai.getName()).append("\", \"cards\": ").append(size)
                .append(", \"lands\": ").append(r.lands()).append(", \"ramp\": ").append(round(r.ramp())).append(", \"missing\": \"").append(r.missing())
                .append("\", \"mana\": ").append(round(r.mana())).append(", \"score\": ").append(round(r.score())).append(", \"bar\": ").append(round(bar))
                .append(", \"bottomed\": ").append(cardsToReturn).append(", \"mulligan\": ").append(mull).append(", \"why\": \"").append(why).append("\", \"hand\": [");
        for (int i = 0; i < r.detail().size(); i++) b.append(i > 0 ? ", " : "").append(ForgeRunner.js(r.detail().get(i)));
        System.out.println(b.append("]}"));
        return mull;
    }

    /** The London mulligan's bottom cards: one at a time, the card whose loss leaves the best hand. */
    static CardCollectionView toBottom(Player ai, int n) {
        if (!ON) return null;
        PilotPolicy pol = ThreatModel.policyOf(ai);
        if (pol == null) return null;
        return new CardCollection(bottom(ai, pol, new ArrayList<>(ai.getCardsIn(ZoneType.Hand)), n));
    }

    static List<Card> bottom(Player ai, PilotPolicy pol, List<Card> hand, int n) {
        List<Card> left = new ArrayList<>(hand), out = new ArrayList<>();
        for (int k = 0; k < n && !left.isEmpty(); k++) {
            Card worst = null;
            double best = Double.NEGATIVE_INFINITY;
            for (Card c : left) {
                List<Card> rest = new ArrayList<>(left);
                rest.remove(c);
                Result r = score(ai, pol, rest);
                double v = (r.gate() ? 1000 : 0) + r.score();
                if (v > best) { best = v; worst = c; }
            }
            left.remove(worst);
            out.add(worst);
        }
        return out;
    }

    // ---------------------------------------------------------------- the bar
    /** What an average 4-card hand of this deck scores (7 drawn, the best 4 kept): a 7 keeps at this. Worked out once per player
     *  from its own cards with a fixed seed (the deck's list), so the game's own random numbers aren't touched. */
    static double bar(Player ai, PilotPolicy pol) {
        Double v = BAR.get(ai);
        if (v != null) return v;
        List<Card> deck = new ArrayList<>(ai.getCardsIn(ZoneType.Library));
        deck.addAll(ai.getCardsIn(ZoneType.Hand));
        deck.sort(Comparator.comparing(Card::getName));
        Random rng = new Random(deck.stream().map(Card::getName).toList().hashCode());
        double sum = 0;
        int n = 300;
        for (int i = 0; i < n; i++) {
            List<Card> h = new ArrayList<>(deck);
            Collections.shuffle(h, rng);
            h = new ArrayList<>(h.subList(0, Math.min(7, h.size())));
            h.removeAll(bottom(ai, pol, h, Math.max(0, h.size() - 4)));
            sum += score(ai, pol, h).score();
        }
        v = sum / n;
        BAR.put(ai, v);
        return v;
    }

    // ---------------------------------------------------------------- the score
    static Result score(Player ai, PilotPolicy pol, List<Card> hand) {
        String ident = letters(ai.getCommanderColorID());
        List<Info> cards = new ArrayList<>();
        for (Card c : hand) cards.add(info(ai, pol, c));
        int lands = 0;
        for (Info x : cards) if (x.land()) lands++;
        Set<Character> cols = new HashSet<>();
        for (Info x : cards) if (x.land() || x.ramp() > 0) for (char ch : x.colors().toCharArray()) cols.add(ch);
        double ramp = 0;
        for (Info x : cards) {
            if (x.land() || x.ramp() <= 0 || x.cmc() > Math.max(1, Math.min(3, lands))) continue;
            if (!x.reduces().isEmpty() && !x.reduces().equals("*") && !cols.contains(x.reduces().charAt(0))) continue;   // a Medallion for a color the hand can't make
            ramp += x.ramp();
        }
        StringBuilder miss = new StringBuilder();
        for (char ch : ident.toCharArray()) if (!cols.contains(ch)) miss.append(ch);
        double mana = lands + ramp - COLOR * miss.length() / Math.max(1, ident.length());
        boolean gate = lands >= 2 && lands < 6;
        double total = MANA_UNIT * Math.max(0, Math.min(mana, MANA_CAP)) - SHORT * Math.max(0, 3 - mana);
        List<String> det = new ArrayList<>();
        Set<String> cmdRoles = new HashSet<>();
        List<Card> commanders = new ArrayList<>();
        for (Card c : ai.getCardsIn(ZoneType.Command)) if (c.isCommander() && ai.equals(c.getOwner())) commanders.add(c);
        for (Card c : commanders) cmdRoles.add(info(ai, pol, c).role());
        cmdRoles.remove("other");   // a Background's "other" (Flaming Fist) isn't a role to discount
        double by4 = Math.min(5, lands + ramp + 1);
        Map<String, List<double[]>> byRole = new HashMap<>();
        Map<String, List<String>> names = new HashMap<>();
        int spells = 0;
        int tappedLands = 0;
        for (Info x : cards) if (x.tapped()) tappedLands++;
        for (Info x : cards) {
            boolean rampNow = x.ramp() > 0 && x.cmc() <= Math.max(1, Math.min(3, lands));
            if (x.land() || (rampNow && x.reduces().isEmpty())) {
                det.add(x.name() + ":" + (x.land() ? "land" : "ramp " + round(x.ramp())));
                if (x.land() && x.role().equals("tutor")) add(byRole, names, "tutor", 0.5 * W.get("tutor"), x.name() + " (land)");
                if (x.gc()) { total += GAME_CHANGER; det.add(x.name() + ":game changer +1"); }
                continue;
            }
            if (rampNow) det.add(x.name() + ":ramp " + round(x.ramp()));   // a cost reducer is ramp and a spell
            // ramp the hand can't cast by turn 3 (Crypt Ghast on two lands) is a spell of its role, late (the user, 2026-10-18)
            spells++;
            double v = BASE + W.get(x.role()) * (cmdRoles.contains(x.role()) ? COMMANDER_ROLE : 1);
            String note = cmdRoles.contains(x.role()) ? " (commander's role" : " (";
            boolean colorsOk = true;
            for (char ch : x.pips().toCharArray()) if (!cols.contains(ch)) colorsOk = false;
            if (!colorsOk) { v *= UNCASTABLE; note += note.endsWith("(") ? "off-color" : ", off-color"; }
            else if (x.cmc() > by4) { v *= LATE; note += note.endsWith("(") ? "late" : ", late"; }
            add(byRole, names, x.role(), v, x.name() + (note.endsWith("(") ? "" : note + ")"));
            if (x.gc()) { total += GAME_CHANGER; det.add(x.name() + ":game changer +1"); }
        }
        for (Map.Entry<String, List<double[]>> e : byRole.entrySet()) {
            List<double[]> vs = e.getValue();
            for (int k = 0; k < vs.size(); k++) {
                double v = vs.get(k)[0] * Math.pow(REPEAT, k);
                total += v;
                det.add(names.get(e.getKey()).get((int) vs.get(k)[1]) + ":" + e.getKey() + " " + round(v));
            }
        }
        if (lands >= 5 && spells <= 2) { total -= FLOOD; det.add("flood:-3"); }
        for (Card c : commanders) {   // the commander: a card of its role the hand can cast on time
            Info x = info(ai, pol, c);
            boolean colorsOk = true;
            for (char ch : x.pips().toCharArray()) if (!cols.contains(ch)) colorsOk = false;
            int cost = x.cmc() + 2 * ai.getCommanderCast(c);
            double early = lands - tappedLands + ramp;   // ahead of curve needs untapped lands: Zur's two cycling lands held both Signets to turn 3
            double f = !colorsOk ? 0.15 : ramp >= 1 && early >= cost ? EARLY : lands + ramp + 1 >= cost ? 1.0 : lands + ramp + 2 >= cost ? 0.5 : 0.15;
            double v = (BASE + W.get(x.role())) * f;
            total += v;
            det.add(x.name() + " (commander):" + x.role() + " x" + f + " " + round(v));
        }
        return new Result(gate, total, lands, ramp, miss.toString(), mana, det);
    }

    static void add(Map<String, List<double[]>> byRole, Map<String, List<String>> names, String role, double v, String name) {
        List<String> ns = names.computeIfAbsent(role, k -> new ArrayList<>());
        byRole.computeIfAbsent(role, k -> new ArrayList<>()).add(new double[] {v, ns.size()});
        ns.add(name);
        byRole.get(role).sort((a, b) -> Double.compare(b[0], a[0]));
    }

    // ---------------------------------------------------------------- what a card is
    static Info info(Player ai, PilotPolicy pol, Card c) {
        Map<String, Info> m = INFO.computeIfAbsent(ai, k -> new HashMap<>());
        Info x = m.get(c.getName());
        if (x == null) { x = classify(ai, pol, c); m.put(c.getName(), x); }
        return x;
    }

    static Info classify(Player ai, PilotPolicy pol, Card c) {
        String ident = letters(ai.getCommanderColorID());
        PilotPolicy.CardIntel ci = pol.in.cards.get(c.getName());
        List<String> tags = ci == null ? List.of() : ci.roles;
        boolean land = c.isLand();
        String colors = produced(c, ident);
        double ramp = 0;
        String reduces = "";
        if (!land) {
            boolean manaSource = c.isPermanent() && !c.getManaAbilities().isEmpty();   // rocks and dorks, tagged or not
            if (tags.contains("ramp") || manaSource || landSearch(c)) {
                double perm = 0, oneShot = 0;
                for (SpellAbility ma : c.getManaAbilities()) {
                    boolean fromHand = ma.getRestrictions() != null && ma.getRestrictions().getZone() != null && ma.getRestrictions().getZone() != ZoneType.Battlefield;
                    int amt = 1;
                    try { amt = Math.max(1, ma.amountOfManaGenerated(true)); } catch (RuntimeException e) { }
                    if (fromHand) oneShot = Math.max(oneShot, 0.5);              // Simian Spirit Guide: once
                    else if (c.isPermanent()) perm = Math.max(perm, Math.min(3, amt));
                }
                String red = reducer(c);
                if (perm > 0) ramp = perm;
                else if (red != null) { ramp = 1; reduces = red; }               // Medallions, Jet Medallion, Bontu's Monument
                else if (landSearch(c)) { ramp = 1; colors = ident; }            // Cultivate, Farseek
                else if (oneShot > 0) ramp = oneShot;
                else if (!c.isPermanent() && apiIn(c, ApiType.Mana)) ramp = 0.5; // Dark Ritual: once
                else if (c.isPermanent() && tags.contains("ramp")) ramp = 1;     // mana auras on lands, land untappers (Wild Growth, Voyaging Satyr)
                // tagged "ramp" but no mana at all (Show and Tell puts a permanent in): not ramp
            }
        }
        String role = "other";
        String forced = pol.in.hand == null ? null : pol.in.hand.get(c.getName());
        if (pol.in.keys.contains(c.getName()) && !c.isCommander()) role = "key";
        else if (tags.contains("tutor") && realTutor(c)) role = "tutor";
        else if (tags.contains("removal") || tags.contains("wipe") || tags.contains("counter")) role = "interaction";   // a counter that cycles (Miscalculation) is a counter
        else if (tags.contains("draw") && !land) role = "draw";
        else if (c.isCreature() || c.isPlaneswalker()) role = "threat";
        if (forced != null) {
            if (forced.equals("ramp")) { if (ramp <= 0) ramp = 1; }
            else role = forced;
        }
        if (land && tags.contains("tutor") && realTutor(c)) role = "tutor";   // Urza's Saga
        return new Info(c.getName(), land, ramp, reduces, colors, letters(ColorSet.fromManaCost(c.getManaCost())), c.getCMC(), role, ci != null && ci.gc,
                land && alwaysTapped(c));
    }

    /** A land that always enters tapped (cycling lands, guildgates): not shock lands or check lands, which can come in untapped. */
    static boolean alwaysTapped(Card c) {
        for (forge.game.replacement.ReplacementEffect re : c.getReplacementEffects()) {
            String d = re.getParamOrDefault("Description", "");
            if (d.contains("enters tapped") && !d.matches("(?s).*(unless|If you don't|you may|if you control|if it's|if you).*")) return true;
        }
        return false;
    }

    /** A tutor that works from hand: not one that needs a stack of its own copies (Shadowborn Apostle: sacrifice six), and not
     *  one that only finds lands (fetch lands, Ash Barrens: tagged tutor, but that's mana, counted as a land or ramp). */
    static boolean realTutor(Card c) {
        boolean nonLand = false, any = false;
        for (SpellAbility sa : c.getAllSpellAbilities())
            for (SpellAbility x = sa; x != null; x = x.getSubAbility()) {
                if (x.getApi() != ApiType.ChangeZone || !"Library".equals(x.getParam("Origin"))) continue;
                any = true;
                if (!x.getParamOrDefault("ChangeType", "").matches("(Land|Basic|Plains|Island|Swamp|Mountain|Forest).*")) nonLand = true;
            }
        for (Trigger t : c.getTriggers()) {
            SpellAbility ex;
            try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
            for (SpellAbility x = ex; x != null; x = x.getSubAbility())
                if (x.getApi() == ApiType.ChangeZone && "Library".equals(x.getParam("Origin"))) {
                    any = true;
                    if (!x.getParamOrDefault("ChangeType", "").matches("(Land|Basic|Plains|Island|Swamp|Mountain|Forest).*")) nonLand = true;
                }
        }
        if (any && !nonLand) return false;
        for (SpellAbility sa : c.getAllSpellAbilities()) {
            String cost = sa.getPayCosts() == null ? "" : sa.getPayCosts().toString();
            if (sa.getApi() == ApiType.ChangeZone && cost.matches(".*[Ss]acrifice (six|five|four|three|two|[2-9]) .*")) return false;
        }
        return true;
    }

    static boolean apiIn(Card c, ApiType api) {
        for (SpellAbility sa : c.getAllSpellAbilities())
            for (SpellAbility x = sa; x != null; x = x.getSubAbility()) if (x.getApi() == api) return true;
        return false;
    }

    /** A spell that puts a land from the library onto the battlefield or into hand. */
    static boolean landSearch(Card c) {
        for (SpellAbility sa : c.getAllSpellAbilities())
            for (SpellAbility x = sa; x != null; x = x.getSubAbility())
                if (x.getApi() == ApiType.ChangeZone && "Library".equals(x.getParam("Origin")) && x.getParamOrDefault("ChangeType", "").matches("(Land|Basic|Plains|Island|Swamp|Mountain|Forest).*"))
                    return true;
        return false;
    }

    /** The color a cost reducer discounts ("*" for any spell), or null. */
    static String reducer(Card c) {
        for (StaticAbility st : c.getStaticAbilities()) {
            if (!st.checkMode(StaticAbilityMode.ReduceCost)) continue;
            String v = st.getParamOrDefault("ValidCard", "");
            String[][] w = {{"White", "W"}, {"Blue", "U"}, {"Black", "B"}, {"Red", "R"}, {"Green", "G"}};
            for (String[] p : w) if (v.contains(p[0])) return p[1];
            return "*";
        }
        return null;
    }

    /** The colors a land or mana source can make, within the commander's identity. */
    static String produced(Card c, String ident) {
        Set<Character> out = new TreeSet<>();
        for (SpellAbility ma : c.getManaAbilities()) {
            String p = ma.getManaPart() == null ? "" : ma.getManaPart().getOrigProduced();
            if (p.contains("Any") || p.contains("ColorIdentity") || p.contains("Chosen")) for (char ch : ident.toCharArray()) out.add(ch);
            for (String tok : p.split(" ")) if (tok.length() == 1 && COLORS.contains(tok)) out.add(tok.charAt(0));
        }
        String[][] basics = {{"Plains", "W"}, {"Island", "U"}, {"Swamp", "B"}, {"Mountain", "R"}, {"Forest", "G"}};
        for (String[] b : basics) if (c.getType().hasSubtype(b[0])) out.add(b[1].charAt(0));
        if (c.isLand()) {   // fetch lands
            for (SpellAbility sa : c.getAllSpellAbilities()) {
                if (sa.getApi() != ApiType.ChangeZone || !"Library".equals(sa.getParam("Origin"))) continue;
                String t = sa.getParamOrDefault("ChangeType", "");
                for (String[] b : basics) if (t.contains(b[0])) out.add(b[1].charAt(0));
                if (t.contains("Basic") || t.equals("Land")) for (char ch : ident.toCharArray()) out.add(ch);
            }
        }
        StringBuilder b = new StringBuilder();
        for (char ch : out) if (ident.indexOf(ch) >= 0) b.append(ch);
        return b.toString();
    }

    static String letters(ColorSet cs) {
        StringBuilder b = new StringBuilder();
        if (cs.hasWhite()) b.append('W');
        if (cs.hasBlue()) b.append('U');
        if (cs.hasBlack()) b.append('B');
        if (cs.hasRed()) b.append('R');
        if (cs.hasGreen()) b.append('G');
        return b.toString();
    }

    static double round(double v) { return Math.round(v * 100) / 100.0; }
}
