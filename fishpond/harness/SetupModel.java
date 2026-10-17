import forge.game.Game;
import forge.game.ability.AbilityUtils;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CardLists;
import forge.game.player.Player;
import forge.game.spellability.SpellAbility;
import forge.game.staticability.StaticAbility;
import forge.game.trigger.Trigger;
import forge.game.zone.ZoneType;

import java.util.*;

/** Setup value (the user, 2026-10-17): a light weight on cards that pay off turn over turn, so the pilot plays setup pieces
 *  early (a Talisman on turn 2 over mana held for removal). Derived from the card's script and the deck, not hand-scored:
 *
 *    yield per turn (mana-turns; a card counts 1.5):
 *      mana rock or dork      its net mana (a dork 0.8 of it: summoning sickness, fragility); a land aura its extra mana
 *      land ramp spell        the lands it puts onto the battlefield, +0.5 per land to hand
 *      extra land drops       0.6 per extra land
 *      cost reducer           its reduction x the deck's share of spells it applies to x 1.5 spells a turn (up to 2)
 *      draw engine            cards a turn by trigger: each upkeep 1 (each player's 3), your spells of a kind 1.5 x that share,
 *                             opponents' spells 2, creatures entering 1.2 x the creature share, land drops 0.9, attacks 0.8
 *      activated draw         0.5 a turn
 *    value = K x turns left x (mana yield x mana need + 1.5 x card yield x card need)
 *      turns left  = a 10-turn game less the seat's own turns so far
 *      mana need   = 1 under 6 mana, 0.5 under 9, else 0.15; 1 again when the hand holds a spell it can't afford yet
 *      card need   = 1.2 with 2 cards or fewer in hand, 1.0 up to 4, 0.6 up to 6, else 0.3
 *      K = 20 Forge value units (-Dfishpond.setupK): a turn-2 Talisman is worth about 160, a turn-9 one about 8
 *  Board and deck knowledge only. The turn plan (Forge patch 64) adds it to a card's value. */
public final class SetupModel {
    static final double K = Double.parseDouble(System.getProperty("fishpond.setupK", "20"));
    static final int GAME_TURNS = 10;

    /** {nonland, creatures, instants+sorceries, enchantments, artifacts} in p's deck (its list, every zone). */
    static final Map<Game, Map<Player, List<Card>>> DECK = Collections.synchronizedMap(new WeakHashMap<>());

    static List<Card> deck(Player p) {
        Map<Player, List<Card>> m = DECK.computeIfAbsent(p.getGame(), k -> new HashMap<>());
        List<Card> v = m.get(p);
        if (v == null) {
            v = new ArrayList<>();
            for (ZoneType z : new ZoneType[] {ZoneType.Library, ZoneType.Hand, ZoneType.Graveyard, ZoneType.Battlefield, ZoneType.Exile, ZoneType.Command})
                for (Card c : p.getCardsIn(z)) if (c.getOwner() == p && !c.isToken() && !c.isLand()) v.add(c);
            m.put(p, v);
        }
        return v;
    }

    /** The share of p's nonland cards a card filter matches ("Enchantment", "Instant,Sorcery", "Creature.YouCtrl" ...). */
    static double share(Player p, Card host, String valid) {
        List<Card> d = deck(p);
        if (d.isEmpty() || valid == null || valid.isEmpty()) return 0;
        try {
            return (double) CardLists.getValidCards(d, valid.replace("+YouCtrl", "").replace(".YouCtrl", ""), p, host, null).size() / d.size();
        } catch (RuntimeException e) {
            return 0;
        }
    }

    static int num(Card c, SpellAbility sa, String param, String def) {
        try {
            return Math.max(0, Math.min(3, AbilityUtils.calculateAmount(c, sa.getParamOrDefault(param, def), sa)));
        } catch (RuntimeException e) {
            return 1;
        }
    }

    /** {mana a turn, cards a turn} the card yields once on the battlefield (or, for a ramp spell, once cast). */
    static double[] yieldOf(Player p, Card c) {
        double mana = 0, cards = 0;
        if (!c.isLand()) {
            int best = 0;
            for (SpellAbility ma : c.getManaAbilities()) {
                try {
                    int amount = AbilityUtils.calculateAmount(c, ma.getParamOrDefault("Amount", "1"), ma);
                    int pay = ma.getPayCosts() != null && ma.getPayCosts().getTotalMana() != null ? ma.getPayCosts().getTotalMana().getCMC() : 0;
                    best = Math.max(best, amount - pay);
                } catch (RuntimeException e) { /* skip */ }
            }
            mana += c.isCreature() ? 0.8 * best : best;
        }
        for (SpellAbility sa : c.getSpells()) {
            for (SpellAbility x = sa; x != null; x = x.getSubAbility()) {
                if (x.getApi() == ApiType.ChangeZone && "Library".equals(x.getParam("Origin")) && x.getParamOrDefault("ChangeType", "").contains("Land")) {
                    if ("Battlefield".equals(x.getParam("Destination"))) mana += num(c, x, "ChangeNum", "1");
                    else if ("Hand".equals(x.getParam("Destination"))) mana += 0.5 * num(c, x, "ChangeNum", "1");
                }
            }
        }
        for (StaticAbility st : c.getStaticAbilities()) {
            String mode = st.getParamOrDefault("Mode", "");
            if (mode.contains("Continuous") && st.hasParam("AdjustLandPlays")) {
                try { mana += 0.6 * Integer.parseInt(st.getParam("AdjustLandPlays").trim()); } catch (NumberFormatException e) { mana += 0.6; }
            } else if (mode.contains("ReduceCost") && "You".equals(st.getParamOrDefault("Activator", "You"))) {
                double amount = 1;
                try { amount = Integer.parseInt(st.getParamOrDefault("Amount", "1").trim()); } catch (NumberFormatException e) { /* 1 */ }
                String valid = st.getParamOrDefault("ValidCard", "Card");
                mana += Math.min(2, amount * share(p, c, valid) * 1.5);
            }
        }
        for (Trigger t : c.getTriggers()) {
            SpellAbility ex;
            try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
            if (ex == null) continue;
            if (t.getMode() == forge.game.trigger.TriggerType.TapsForMana && (ex.getApi() == ApiType.Mana || ex.getApi() == ApiType.ManaReflected)) {
                mana += num(c, ex, "Amount", "1");   // "whenever enchanted land is tapped for mana, add one more" (Utopia Sprawl, Wild Growth)
                continue;
            }
            int n = 0;
            for (SpellAbility x = ex; x != null; x = x.getSubAbility())
                if (x.getApi() == ApiType.Draw && !x.getParamOrDefault("Defined", "You").contains("Opponent")) n = Math.max(n, num(c, x, "NumCards", "1"));
            if (n == 0) continue;
            double rate;
            switch (t.getMode()) {
                case Phase: rate = t.getParamOrDefault("ValidPlayer", "").contains("You") ? 1 : 3; break;
                case SpellCast: case SpellCastOrCopy:
                    rate = t.getParamOrDefault("ValidActivatingPlayer", "You").contains("Opponent") ? 2
                            : 1.5 * (t.hasParam("ValidCard") ? share(p, c, t.getParam("ValidCard")) : 1);
                    break;
                case ChangesZone:
                    rate = "Battlefield".equals(t.getParam("Destination")) && !t.getParamOrDefault("ValidCard", "").startsWith("Card.Self")
                            ? 1.2 * share(p, c, "Creature") : 0;
                    break;
                case LandPlayed: rate = 0.9; break;
                case Attacks: rate = 0.8; break;
                case DamageDone: case DamageDoneOnce: rate = 0.8; break;
                case Drawn: rate = 0; break;   // draw-on-draw would count itself
                default: rate = 0.5;
            }
            cards += Math.min(3, rate * n);
        }
        for (SpellAbility a : c.getSpellAbilities()) {
            if (!a.isActivatedAbility() || a.isManaAbility()) continue;
            for (SpellAbility x = a; x != null; x = x.getSubAbility())
                if (x.getApi() == ApiType.Draw) { cards += 0.5; break; }
        }
        return new double[] {mana, cards};
    }

    static int manaSources(Player p) {
        int n = 0;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) if (!c.getManaAbilities().isEmpty()) n++;
        return n;
    }

    /** The turn plan's hook: the setup value of casting c now (0 in the lookahead's copies). */
    public static double setupValue(Player p, Card c) {
        if (!ThreatModel.REAL.contains(p.getGame())) return 0;
        double[] y = yieldOf(p, c);
        if (y[0] <= 0 && y[1] <= 0) return 0;
        double left = Math.max(0, GAME_TURNS - p.getTurn());
        int mana = manaSources(p);
        double needMana = mana < 6 ? 1.0 : mana < 9 ? 0.5 : 0.15;
        for (Card h : p.getCardsIn(ZoneType.Hand)) if (!h.isLand() && h != c && h.getCMC() > mana) { needMana = Math.max(needMana, 1.0); break; }
        int hand = p.getCardsIn(ZoneType.Hand).size();
        double needCards = hand <= 2 ? 1.2 : hand <= 4 ? 1.0 : hand <= 6 ? 0.6 : 0.3;
        return K * left * (y[0] * needMana + 1.5 * y[1] * needCards);
    }

    /** One line per deck: its setup cards and their yields (#FP-SETUP at game start), for review. */
    static String table(Player p) {
        List<String> rows = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Card c : deck(p)) {
            if (!seen.add(c.getName())) continue;
            double[] y = yieldOf(p, c);
            if (y[0] <= 0 && y[1] <= 0) continue;
            rows.add(String.format(Locale.ROOT, "%s (mana %.1f, cards %.1f)", c.getName(), y[0], y[1]));
        }
        Collections.sort(rows);
        return String.join("; ", rows);
    }
}
