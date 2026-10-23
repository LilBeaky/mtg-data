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
        boolean flag, flag_dead, cmdr, gc;   // gc: a Game Changer (policy.py)
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
        List<String> keys = new ArrayList<>();       // the deck's '# key:' cards (policy.py)
        Map<String, String> hand = new HashMap<>();   // the deck's '# hand:' roles for the mulligan score (policy.py)
        List<List<List<String>>> loops = new ArrayList<>();   // the deck's '# loop:' lines: slots in order, alternatives in each (policy.py)
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

    // ------------------------------------------------------------------ the commander gate (the user's rule, 2026-10-07)

    static final boolean GATE_ON = !"false".equals(System.getProperty("fishpond.tutorGate"));
    static final double KEY_BONUS = Double.parseDouble(System.getProperty("fishpond.keyBonus", "250"));

    /** Mana the player's permanents can make: lands count one each, other mana producers their most (up to 3). */
    static int existingMana(Player me) {
        int n = 0;
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) {
            if (c.getManaAbilities().isEmpty()) continue;
            n += c.isLand() ? 1 : Math.max(1, Math.min(3, c.getMaxManaProduced()));
        }
        return n;
    }

    /** Ramp: a nonland permanent that makes mana or reduces costs, a spell that puts a land onto the battlefield, or a card
     *  the deck intel tags as ramp. */
    boolean isRamp(Card c) {
        if (c.isLand()) return false;
        CardIntel ci = in.cards.get(c.getName());
        if (ci != null && ci.roles.contains("ramp")) return true;
        if (c.isPermanent()) {
            if (!c.getManaAbilities().isEmpty()) return true;
            for (forge.game.staticability.StaticAbility st : c.getStaticAbilities())
                if (st.checkMode(forge.game.staticability.StaticAbilityMode.ReduceCost)) return true;
            return false;
        }
        for (SpellAbility sp : c.getSpells())
            for (SpellAbility a = sp; a != null; a = a.getSubAbility())
                if (a.getApi() == ApiType.ChangeZone && "Battlefield".equals(a.getParam("Destination"))
                        && String.valueOf(a.getParam("ChangeType")).contains("Land")) return true;
        return false;
    }

    /** While the commander sits in the command zone and the seat's mana can't pay for it (tax included), a tutor takes ramp
     *  first, else a '# key:' card (best by the policy's ranking); if the tutor can find neither, Forge's pick if it's
     *  castable with the mana the seat already has, else the best-ranked castable card, else Forge's pick. Returns null when
     *  the rule doesn't apply (no commander waiting, or it's affordable). */
    Card commanderGate(Player me, List<Map.Entry<Card, double[]>> ranked, Card forgePick) {
        if (!GATE_ON) return null;
        // a pick that completes a combo goes first (the user, 2026-10-21: "Witherbloom wants to tutor for Sprout Swarm, most
        // definitely. Combo."; the gate took Deadly Dispute, ramp by its Treasure, over Sprout Swarm with Witherbloom waiting)
        if (!ranked.isEmpty() && ranked.get(0).getValue()[COMBO] >= 700) return null;
        Card cmdr = null;
        for (Card c : me.getCardsIn(ZoneType.Command)) if (c.isCommander() && me.equals(c.getOwner())) { cmdr = c; break; }
        if (cmdr == null) return null;
        int mana = existingMana(me);
        if (mana >= cmdr.getCMC() + 2 * me.getCommanderCast(cmdr)) return null;
        for (Map.Entry<Card, double[]> e : ranked) if (isRamp(e.getKey())) return e.getKey();
        for (Map.Entry<Card, double[]> e : ranked) if (in.keys.contains(e.getKey().getName())) return e.getKey();
        if (forgePick != null && forgePick.getCMC() <= mana) return forgePick;
        for (Map.Entry<Card, double[]> e : ranked) if (e.getKey().getCMC() <= mana) return e.getKey();
        return forgePick;
    }

    // ------------------------------------------------------------------ deck rules (the user's, for one deck)

    /** The user's rules for Zur's engine (2026-10-22, conceded as overrides: "This framework should guarantee it at least
     *  attempts to establish this engine"). With Zur the Enchanter the commander and Archaeomancer, Astral Slide and Step
     *  Through in the deck: any search that can choose Step Through (still in the library) does; Zur's enchantment search
     *  takes Astral Slide (Slide only); Step Through's Wizardcycle takes Archaeomancer. Null when no rule applies. */
    Card deckRule(SpellAbility sa, List<Card> cands) {
        if (!zurEngine() || sa == null || sa.getHostCard() == null) return null;
        String src = sa.getHostCard().getName();
        Card step = named(cands, "Step Through"), slide = named(cands, "Astral Slide"), arch = named(cands, "Archaeomancer");
        if (step != null) return step;
        if (src.equals("Zur the Enchanter") && slide != null) return slide;
        if (src.equals("Step Through") && arch != null) return arch;
        return null;
    }

    boolean zurEngine() {
        CardIntel z = in.cards.get("Zur the Enchanter");
        return z != null && z.cmdr && in.cards.containsKey("Archaeomancer") && in.cards.containsKey("Astral Slide")
                && in.cards.containsKey("Step Through");
    }

    // ------------------------------------------------------------------ repeatable engines (the user, 2026-10-23)
    // "The pilot needs to notice when things like Step Through/Archaeomancer/Slide ... are repeatable, and value building
    // that incredibly highly." A loop is slots in order, each slot a card or its alternatives: the deck's '# loop:' lines
    // and the loops found in the seat's own cards when the policy first looks (both; "I'd definitely want to do both on
    // detection"), logged as #FP-LOOPS. Found from card text: a cycler that a creature's enter trigger returns from the
    // graveyard to hand, with a payoff that blinks a creature whenever a card is cycled (Step Through > Archaeomancer >
    // Astral Slide | Astral Drift | Escape Protocol), and a persist creature with that payoff (Glen Elendra's counter cleared).
    // A slot is ready when one of its cards is on the battlefield (the loop's first card, a cycler, also in hand or the
    // graveyard), held when it's ready or in hand. Building one: a tutor pick that completes it scores like a combo (900;
    // 300 with one piece still missing), casting a missing permanent adds the same to the turn plan (SetupModel's hook), and
    // its pieces are kept from discards and the cycling rule.

    List<List<List<String>>> loops;   // declared + detected, on first use
    String loopsLine;                 // the #FP-LOOPS record

    List<List<List<String>>> loops(Player me) {
        if (loops != null) return loops;
        List<List<List<String>>> declared = in.loops == null ? new ArrayList<>() : in.loops, found = new ArrayList<>();
        try { found = detectLoops(me); } catch (RuntimeException e) { /* none */ }
        List<List<List<String>>> all = new ArrayList<>(declared);
        Set<String> seen = new HashSet<>();
        for (var l : declared) seen.add(loopKey(l));
        for (var l : found) if (seen.add(loopKey(l))) all.add(l);
        String seat = me.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
        loopsLine = "{\"seat\": " + seat + ", \"deck\": " + ForgeRunner.js(in.deck == null ? "" : in.deck)
                + ", \"declared\": " + new Gson().toJson(declared) + ", \"detected\": " + new Gson().toJson(found) + "}";
        return loops = all;
    }

    static String loopKey(List<List<String>> l) {
        List<String> k = new ArrayList<>();
        for (List<String> slot : l) { List<String> x = new ArrayList<>(slot); Collections.sort(x); k.add(String.join("|", x)); }
        Collections.sort(k);
        return String.join(">", k);
    }

    static List<Card> allCards(Player me) {
        List<Card> out = new ArrayList<>();
        for (ZoneType z : new ZoneType[]{ZoneType.Library, ZoneType.Hand, ZoneType.Battlefield, ZoneType.Graveyard, ZoneType.Command, ZoneType.Exile})
            out.addAll(me.getCardsIn(z));
        return out;
    }

    static boolean cycler(Card c) {
        for (SpellAbility a : c.getAllSpellAbilities()) if (!a.isSpell() && a.isCycling()) return true;
        return false;
    }

    /** Whenever a card is cycled while it's on the battlefield, it exiles a creature that comes back (Astral Slide, Drift,
     *  Escape Protocol). */
    static boolean cycleBlinker(Card c) {
        boolean cyc = false;
        for (forge.game.trigger.Trigger t : c.getTriggers())
            if (t.getMode() == forge.game.trigger.TriggerType.Cycled && "Battlefield".equals(t.getParam("TriggerZones"))) cyc = true;
        if (!cyc) return false;
        String all = String.join("\n", c.getCurrentState().getSVars().values());
        return all.contains("Destination$ Exile") && all.contains("Origin$ Battlefield")
                && (all.contains("DelayedTrigger") || all.contains("Origin$ Exile | Destination$ Battlefield"));
    }

    /** The valid-card list of its enter trigger's return from the graveyard to hand (Archaeomancer), or null. */
    static String[] returnsToHand(Card c) {
        if (!c.isCreature()) return null;
        for (forge.game.trigger.Trigger t : c.getTriggers()) {
            if (t.getMode() != forge.game.trigger.TriggerType.ChangesZone || !"Battlefield".equals(t.getParam("Destination"))
                    || !t.getParamOrDefault("ValidCard", "").startsWith("Card.Self")) continue;
            for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility()) {
                if (x.getApi() == ApiType.ChangeZone && x.getParamOrDefault("Origin", "").equals("Graveyard")
                        && "Hand".equals(x.getParam("Destination"))) {
                    String v = x.getParamOrDefault("ValidTgts", x.getParamOrDefault("ChangeType", ""));
                    if (!v.isEmpty()) return v.split(",");
                }
            }
        }
        return null;
    }

    List<List<List<String>>> detectLoops(Player me) {
        List<List<List<String>>> out = new ArrayList<>();
        List<Card> cards = allCards(me);
        List<String> blinkers = new ArrayList<>();
        for (Card c : cards) if (cycleBlinker(c) && !blinkers.contains(c.getName())) blinkers.add(c.getName());
        if (blinkers.isEmpty()) return out;
        // one loop per returner, its fuel slot every cycler it can return (zur300_20261023: one loop per cycling instant made
        // each one look like the missing piece to a tutor)
        Set<String> done = new HashSet<>();
        for (Card r : cards) {
            String[] valid = returnsToHand(r);
            if (valid == null || !done.add("returner>" + r.getName())) continue;
            List<String> fuel = new ArrayList<>();
            for (Card f : cards) {
                if (f == r || !cycler(f) || fuel.contains(f.getName())) continue;
                boolean ok;
                try { ok = f.isValid(valid, me, r, null); } catch (RuntimeException e) { ok = false; }
                if (ok) fuel.add(f.getName());
            }
            Collections.sort(fuel);
            if (!fuel.isEmpty()) out.add(List.of(fuel, List.of(r.getName()), new ArrayList<>(blinkers)));
        }
        for (Card c : cards)
            if (c.isCreature() && c.hasKeyword(forge.game.keyword.Keyword.PERSIST) && done.add("persist>" + c.getName()))
                out.add(List.of(List.of(c.getName()), new ArrayList<>(blinkers)));
        return out;
    }

    /** 2 when a card of the slot is ready (on the battlefield; the first slot's cycler also in hand or the graveyard), 1 when
     *  one is in hand (to cast), else 0. */
    static int slotState(Player me, List<String> slot, boolean first) {
        int st = 0;
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) if (slot.contains(c.getName())) return 2;
        for (Card c : me.getCardsIn(ZoneType.Exile))   // blinked this turn by its own payoff: back at the end step
            if (slot.contains(c.getName()) && c.isCreature() && c.getTurnInZone() == me.getGame().getPhaseHandler().getTurn() && blinkedBack(me)) return 2;
        for (Card c : me.getCardsIn(ZoneType.Hand)) if (slot.contains(c.getName())) { if (first && cycler(c)) return 2; st = 1; }
        if (first) for (Card c : me.getCardsIn(ZoneType.Graveyard)) if (slot.contains(c.getName()) && cycler(c)) return 2;
        return st;
    }

    /** A cycle-blink payoff of the seat's is on the battlefield (what it exiles comes back). */
    static boolean blinkedBack(Player me) {
        for (Card c : me.getCardsIn(ZoneType.Battlefield)) if (cycleBlinker(c)) return true;
        return false;
    }

    /** What a card adds to building the seat's loops: 900 when it fills the last open slot, 300 when one more stays open
     *  (best over its loops); 0 if it fills none. cast: it is being cast from hand (a slot counts open until it's ready);
     *  otherwise it is being fetched (a slot counts filled once held). */
    double loopValue(Player me, Card c, boolean cast) {
        String n = c.getName();
        double best = 0;
        boolean running = loopRunning(me);
        for (List<List<String>> l : loops(me)) {
            int at = -1;
            for (int i = 0; i < l.size(); i++) if (l.get(i).contains(n)) { at = i; break; }
            if (at < 0) continue;
            int need = cast ? 2 : 1;
            if (slotState(me, l.get(at), at == 0) >= need) continue;   // that slot is already covered
            if (cast && (at == 0 && cycler(c) || !c.isPermanent())) continue;   // the fuel works from hand; nothing to build
            int open = 0;
            for (int i = 0; i < l.size(); i++) if (i != at && slotState(me, l.get(i), i == 0) < need) open++;
            double v = open == 0 ? 900 : open == 1 ? 300 : 0;
            // a second loop adds little once one runs (zur300b_20261023: with Step Through > Archaeomancer > Slide running, the
            // Glen Elendra > Slide line made Glen a 900 pick on every Wizardcycle, and Auramancer 300 off a found Drift loop)
            best = Math.max(best, running ? v / 9 : v);
        }
        return best;
    }

    /** One of the seat's loops has every slot ready: the engine runs. */
    boolean loopRunning(Player me) {
        for (List<List<String>> l : loops(me)) {
            boolean all = true;
            for (int i = 0; i < l.size() && all; i++) if (slotState(me, l.get(i), i == 0) < 2) all = false;
            if (all) return true;
        }
        return false;
    }

    // ------------------------------------------------------------------ what a running engine fetches (the user, 2026-10-23)
    // "The loop opens a network of Wizards": Tribute Mage for Fluctuator, Emeritus when cards are needed, Auramancer or
    // Bloodline Necromancer to rebuy a key piece, Spellseeker (Cyclonic Rift, Pest Control, Feed the Swarm, Fracture),
    // Triskaidekaphile when ready to win, Drannith, Disciple. zur300b_20261023: in 133 games with the loop running, its
    // Wizardcycles took Glen Elendra 100 times, Vedalken Aethermage 69 and Bloodline Necromancer 41 (engine and typal-payoff
    // scores), Spellseeker never, and the levers were rare (Drannith cast 15 times, Disciple 7, Rule of Law 5); Zur won as
    // often as without the loop. Once a loop runs: more engine adds little (engine and synergy layers a quarter), the
    // answers the table calls for count double (removal, wipe, counter, hate, protection), a tutor is worth the card it
    // would find (Spellseeker the best instant or sorcery of mana value 2 or less, Tribute Mage the best 2-mana artifact;
    // the user's rule: a tutor is its pick), and a card that phases out all but a few permanents (Disciple of Caelus Nin)
    // counts as a wipe.
    static final ThreadLocal<Boolean> IN_FETCH = ThreadLocal.withInitial(() -> false);

    /** The best score among the library cards its enter-the-battlefield search would find (to hand), 0 if none. */
    double fetchValue(Card c, Board b) {
        if (IN_FETCH.get() || b.me == null) return 0;
        IN_FETCH.set(true);
        try {
            double best = 0;
            for (forge.game.trigger.Trigger t : c.getTriggers()) {
                if (t.getMode() != forge.game.trigger.TriggerType.ChangesZone || !"Battlefield".equals(t.getParam("Destination"))
                        || !t.getParamOrDefault("ValidCard", "").startsWith("Card.Self")) continue;
                for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility()) {
                    if (x.getApi() != ApiType.ChangeZone || !x.getParamOrDefault("Origin", "").contains("Library") || !x.hasParam("ChangeType")) continue;
                    x.setActivatingPlayer(b.me);
                    for (Card k : forge.game.card.CardLists.getValidCards(b.me.getCardsIn(ZoneType.Library), x.getParam("ChangeType").split(","), b.me, c, x))
                        best = Math.max(best, sum(score(k, b, ZoneType.Hand, false)));
                }
            }
            return best;
        } catch (RuntimeException e) {
            return 0;
        } finally {
            IN_FETCH.set(false);
        }
    }

    /** The biggest threat (ThreatModel.cardThreat) among the opponents' permanents its targeted removal could hit, from its
     *  spell or its enter trigger; -1 when it can hit none (Vedalken Aethermage bounces only Slivers). */
    static double removalReach(Card c, Player me) {
        List<SpellAbility> abs = new ArrayList<>(c.getSpells());
        for (forge.game.trigger.Trigger t : c.getTriggers())
            if (t.getMode() == forge.game.trigger.TriggerType.ChangesZone && "Battlefield".equals(t.getParam("Destination"))
                    && t.getParamOrDefault("ValidCard", "").startsWith("Card.Self")) {
                try { abs.add(t.ensureAbility()); } catch (RuntimeException e) { /* skip */ }
            }
        double best = -1;
        for (SpellAbility sa : abs) {
            for (SpellAbility x = sa; x != null; x = x.getSubAbility()) {
                ApiType api = x.getApi();
                if (!x.usesTargeting() || !(api == ApiType.Destroy || api == ApiType.Sacrifice || api == ApiType.DealDamage
                        || api == ApiType.ChangeZone && "Battlefield".equals(x.getParam("Origin")))) continue;
                String valid = x.getParamOrDefault("ValidTgts", "");
                if (valid.isEmpty()) continue;
                for (Player o : me.getOpponents())
                    for (Card p : o.getCardsIn(ZoneType.Battlefield)) {
                        if (p.isLand()) continue;
                        boolean hit;
                        try { hit = p.isValid(valid.split(","), me, c, x); } catch (RuntimeException e) { hit = false; }
                        if (hit) best = Math.max(best, Math.max(0, ThreatModel.cardThreat(me, p)));
                    }
            }
        }
        return best;
    }

    /** Its enter trigger phases out all but some permanents (Disciple of Caelus Nin): a wipe by another name. */
    static boolean phasesOthersOut(Card c) {
        for (forge.game.trigger.Trigger t : c.getTriggers()) {
            if (t.getMode() != forge.game.trigger.TriggerType.ChangesZone || !"Battlefield".equals(t.getParam("Destination"))) continue;
            try {
                for (SpellAbility x = t.ensureAbility(); x != null; x = x.getSubAbility()) if (x.getApi() == ApiType.Phases) return true;
            } catch (RuntimeException e) { /* none */ }
        }
        return false;
    }

    /** A piece the loop can't do without: any slot's card but a fuel slot with alternatives (those cyclers are cycled; the
     *  loop needs one of them). */
    boolean loopPiece(String name) {
        for (List<List<String>> l : loops != null ? loops : in.loops == null ? List.<List<List<String>>>of() : in.loops)
            for (int i = 0; i < l.size(); i++) if (l.get(i).contains(name) && (i > 0 || l.get(i).size() == 1)) return true;
        return false;
    }

    static Card named(List<Card> cands, String name) {
        for (Card c : cands) if (c.getName().equals(name) && c.isInZone(ZoneType.Library)) return c;
        return null;
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
        int lands, mana, hand, life, turn, oppPower, oppCreatures, myCreatures, oppTotal;   // oppTotal: every opponent's power together
        Map<String, Integer> fieldRoles = new HashMap<>();
        boolean engineOut;
        Player me;
    }

    Board board(Player me, SpellAbility sa) {
        Board b = new Board();
        b.me = me;
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
            b.oppTotal += pw;
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

    // ------------------------------------------------------------------ cast ordering (Forge patch 54)
    static final boolean CAST_ON = !"false".equals(System.getProperty("fishpond.castPlan"));

    /** The deck's plan for a spell about to be cast, from the same intel as the tutor picks: 3 when it completes a combo
     *  with the other pieces on the battlefield, 2 when it is a payoff of a mechanic the deck is built around (strength
     *  0.5+) and no payoff of that mechanic is out yet (it turns the engine on: payoff before its fuel), 1 when it feeds a
     *  mechanic whose payoff is out, else 0. Forge orders candidates by it after the trigger payoffs and before its own
     *  mana-value order; a win, Show and Tell and a paying wheel still go first. -Dfishpond.castPlan=false turns it off. */
    boolean isKey(String name) { return in.keys.contains(name); }   // Forge patch 55: the cycling rule keeps key cards
    /** A card the deck wants kept (Forge patches 55 and 70: not cycled away, discarded last): a key card or a piece of a known
     *  win combo (Yusri discarded Zndrsplt to hand size, half of Frenetic Efreet + Zndrsplt + Laboratory Maniac; the user,
     *  2026-10-18: "a COLOSSAL whiff"). */
    boolean keepCard(String name) {
        if (isKey(name)) return true;
        for (Combo cb : in.combos) if (cb.win && cb.cards.contains(name)) return true;
        return loopPiece(name);   // a repeatable engine's pieces
    }

    final int[] castHits = new int[4];   // how often each level was answered (0 = no plan for that spell), for #FP-CASTPLAN

    int castPriority(Player me, SpellAbility sa) {
        int p = castPriority0(me, sa);
        castHits[p]++;
        return p;
    }

    int castPriority0(Player me, SpellAbility sa) {
        if (!CAST_ON || !sa.isSpell()) return 0;
        Card c = sa.getHostCard();
        String n = c.getName();
        CardIntel ci = in.cards.get(n);
        if (ci == null) return 0;
        Set<String> field = new HashSet<>();
        for (Card x : me.getCardsIn(ZoneType.Battlefield)) field.add(x.getName());
        for (Combo cb : in.combos) {
            if (!cb.cards.contains(n) || cb.cards.size() < 2) continue;
            boolean rest = true;
            for (String x : cb.cards) if (!x.equals(n) && !field.contains(x)) { rest = false; break; }
            if (rest) return 3;
        }
        Set<String> paidOut = new HashSet<>();
        for (String f : field) {
            CardIntel fi = in.cards.get(f);
            if (fi != null) paidOut.addAll(fi.payoff);
        }
        for (String m : ci.payoff) {
            Mech mech = in.mechs.get(m);
            if (mech != null && mech.s >= 0.5 && !paidOut.contains(m)) return 2;
        }
        // a '# key:' card not yet on the battlefield is the deck's plan too: as high as turning an engine on
        if (in.keys.contains(n) && !field.contains(n) && !c.isCommander()) return 2;
        for (String m : ci.enabler) if (paidOut.contains(m)) return 1;
        return 0;
    }

    double[] score(Card c, Board b, ZoneType dest, boolean forgePick) {
        double[] s = new double[LAYERS.length];
        String n = c.getName();
        CardIntel ci = in.cards.get(n);
        if (b.me != null) s[COMBO] = loopValue(b.me, c, false);   // building a repeatable engine
        final boolean engineOn = b.me != null && loopRunning(b.me);
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
            List<String> roles = new ArrayList<>(ci.roles);
            if (!roles.contains("wipe") && phasesOthersOut(c)) roles.add("wipe");
            for (String r : roles) {
                double need = switch (r) {
                    case "ramp" -> b.turn <= 6 && (b.lands < 5 || b.mana < 5) ? 1.0 : 0.2;
                    case "land" -> dest == ZoneType.Battlefield && b.lands < 6 ? 0.8 : 0.1;
                    case "draw" -> b.hand <= 2 ? 1.0 : 0.4;
                    case "wincon" -> b.turn >= 8 || b.engineOut ? 0.9 : 0.25;
                    case "removal" -> {   // only what it can hit: a real threat in reach counts most (Swords on Heliod)
                        double reach = b.me == null ? 0 : removalReach(c, b.me);
                        yield reach < 0 ? 0.0 : reach >= 40 ? 1.5 : b.oppCreatures > 0 ? 0.5 : 0.2;
                    }
                    case "wipe" -> b.oppCreatures >= 3 && b.oppCreatures > b.myCreatures + 1 ? 0.7 : 0.1;
                    case "protection" -> b.engineOut ? 0.7 : 0.4;
                    case "counter" -> 0.35;
                    case "hate" -> 0.3;
                    default -> 0.0;
                };
                if (engineOn && (r.equals("removal") || r.equals("wipe") || r.equals("counter") || r.equals("hate") || r.equals("protection"))) need *= 2;
                int onBoard = b.fieldRoles.getOrDefault(r, 0);
                double share = in.role_share.getOrDefault(r, 0.0);
                role = Math.max(role, 200 * need * (1 - Math.min(1.0, onBoard / 2.0)) * (0.5 + share));
            }
            if (dest == ZoneType.Hand && c.isPermanent()) role = Math.max(role, 0.8 * fetchValue(c, b));   // a tutor is its pick
            if (dest == ZoneType.Hand && ci.cmc > b.mana + 2) role *= 0.6;   // to hand but far from castable
            s[ROLE] = role;
            s[SYNERGY] = 60 * ci.syn;
            if (engineOn) { s[ENGINE] /= 4; s[SYNERGY] /= 4; }   // the engine runs: more of it adds little
            // Forge's AI never casts an AI:RemoveDeck:All card (unless fishpond overrides it), so fetched to hand or the
            // library top it's a dead card; put onto the battlefield (Zur) it works, the flag only stops casting
            if (ci.flag && (dest != ZoneType.Battlefield || ci.flag_dead)) for (int k = 0; k < s.length; k++) s[k] *= 0.1;
        }
        // a lock on damage to its controller (Solitary Confinement): with the table's creatures set to kill, surviving comes
        // before the deck's key engines (the user, 2026-10-22: "replace my next search for Zur with Solitary Confinement to make
        // sure that I survive the board state"; Zur fetched Astral Slide at 23 life into Klauth's dragons, zur5b_20261022)
        if (preventsDamageToYou(c)) {
            double lethal = b.oppTotal >= b.life || b.oppPower * 5 >= b.life * 3 ? 1.0 : b.oppPower * 2 >= b.life || b.life <= 10 ? 0.5 : 0.0;
            s[SURVIVAL] = Math.max(s[SURVIVAL], 1300 * lethal);   // over a key engine's ~1000 (Astral Drift in danger: 988)
        }
        s[BOOST] = in.boost.getOrDefault(n, 0.0);
        // the deck's '# key:' cards (the user, 2026-10-16: "if I set a key card in a deck, it's there for a reason, and the
        // deck is typically designed to play around that card"): a big edge over any other engine or role pick, below a
        // combo completion and an urgent survival pick. Zur's trigger fetched Escape Protocol over the key Astral Slide/Drift
        // in about 20 of 30 games on a few points of synergy (study150_20261016_p54). Not for one already on the battlefield.
        if (in.keys.contains(n) && !b.field.contains(n)) s[BOOST] += KEY_BONUS;
        // the user's Wizard network for Zur's loop (2026-10-22): "Typically, it's going to be Tribute Mage if I have the room to
        // make that loop essentially free through Fluctuator, or it'll be Archmage Emeritus if I need cards"; Trisk "when I'm
        // ready to win" (Necrodominance out: the draw to 13)
        if (zurEngine()) {
            if (n.equals("Triskaidekaphile") && !b.field.contains("Necrodominance")) s[BOOST] -= KEY_BONUS;
            if (n.equals("Tribute Mage") && !b.have.contains("Fluctuator")) s[BOOST] += 200;
            if (n.equals("Emeritus of Ideation") && b.hand <= 2) s[BOOST] += 200;
            // Zur's search after Slide/Drift: "Solitary Confinement or Rule of Law (maybe 75% of total games between the two)";
            // Confinement takes over through the survival layer when the board is set to kill
            if (n.equals("Rule of Law") && dest == ZoneType.Battlefield && (b.field.contains("Astral Slide") || b.field.contains("Astral Drift"))
                    && !b.field.contains("Rule of Law")) s[BOOST] += 800;
        }
        if (b.field.contains(n) && c.getType().isLegendary()) Arrays.fill(s, 0);   // legend rule: a second copy is useless
        if (forgePick) s[FORGE] = 15;
        return s;
    }

    static double sum(double[] s) { double t = 0; for (double x : s) t += x; return t; }

    /** The card prevents all damage that would be dealt to its controller (Solitary Confinement). */
    static boolean preventsDamageToYou(Card c) {
        for (forge.game.replacement.ReplacementEffect re : c.getReplacementEffects())
            if (re.getMode() == forge.game.replacement.ReplacementType.DamageDone && "True".equals(re.getParam("Prevent"))
                    && re.getParamOrDefault("ValidTarget", "").equals("You")) return true;
        return false;
    }

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
