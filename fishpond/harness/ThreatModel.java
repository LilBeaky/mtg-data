import forge.ai.ComputerUtilMana;
import forge.game.Game;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.cost.Cost;
import forge.game.keyword.Keyword;
import forge.game.phase.PhaseHandler;
import forge.game.phase.PhaseType;
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
 *               one missing 55 scaled by its hand (cards to find it with), two missing up to 5 by the deck's tutor share
 *    clock      turns for its board to kill another player, the opposing untapped creatures chump-blocking its biggest
 *               attackers (fliers only by fliers or reach), double strike counted twice (an attack trigger that grants it too:
 *               Flaming Fist), a commander killing at 21 commander damage; 2 turns or less overrides: threat at least 110 (one) or 100 (two);
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
    /** An attacker for the clock: the combat damage it deals a turn (doubled by double strike) and whether it's a commander. */
    record Attacker(int dmg, Card card) { }

    /** Double strike now, or an attack trigger that gives it double strike (Flaming Fist: "commander creatures you own have
     *  'whenever this creature attacks, it gains double strike until end of turn'"): the board doesn't show it until combat. */
    static boolean doubleStrikes(Card c) {
        if (c.hasKeyword(Keyword.DOUBLE_STRIKE)) return true;
        for (Trigger t : c.getTriggers()) {
            if (t.getMode() != TriggerType.Attacks) continue;
            SpellAbility ex;
            try { ex = t.ensureAbility(); } catch (RuntimeException e) { continue; }
            for (SpellAbility x : ex == null ? List.<SpellAbility>of() : chain(ex)) {
                if (x.getApi() != ApiType.Pump || !x.getParamOrDefault("KW", "").contains("Double Strike")) continue;
                String def = x.getParamOrDefault("Defined", "Self");
                if (def.equals("Self") || def.equals("TriggeredAttacker") || def.equals("TriggeredAttackerLKICopy")) return true;
            }
        }
        return false;
    }

    /** Turns for p's creatures to kill its most killable opponent: each opponent's untapped creatures chump-block p's biggest
     *  attackers (fliers only by fliers or reach). Double strike doubles a creature's damage (patch 64 era: Wilson with
     *  Flaming Fist read half his clock), and a commander kills at 21 commander damage, counting what it has dealt that player,
     *  not at the player's life (Wilson killed 52 of Yusri's 208 losses by commander damage in pod300_20261018, read as a 4+ turn
     *  clock against 40 life). 99 when it can't. */
    int clockTurns(Player p) {
        List<Attacker> ground = new ArrayList<>(), air = new ArrayList<>();
        for (Card c : p.getCreaturesInPlay()) {
            if (c.hasKeyword(Keyword.DEFENDER)) continue;
            int pw = Math.max(0, c.getNetCombatDamage());
            if (pw == 0) continue;
            Attacker a = new Attacker(doubleStrikes(c) ? 2 * pw : pw, c);
            (c.hasKeyword(Keyword.FLYING) || c.hasKeyword(Keyword.TRAMPLE) || c.hasKeyword(Keyword.SHADOW) ? air : ground).add(a);
        }
        Comparator<Attacker> big = Comparator.comparingInt(Attacker::dmg).reversed();
        ground.sort(big);
        air.sort(big);
        int best = 99;
        for (Player o : p.getOpponents()) {
            if (o.hasLost() || !o.canLoseLife()) continue;
            int groundBlock = 0, airBlock = 0;
            for (Card b : o.getCreaturesInPlay()) {
                if (b.isTapped()) continue;
                if (b.hasKeyword(Keyword.FLYING) || b.hasKeyword(Keyword.REACH)) airBlock++;
                else groundBlock++;
            }
            List<Attacker> through = new ArrayList<>();
            for (int i = Math.min(airBlock, air.size()); i < air.size(); i++) through.add(air.get(i));
            int spareAirBlockers = Math.max(0, airBlock - air.size());
            for (int i = Math.min(groundBlock + spareAirBlockers, ground.size()); i < ground.size(); i++) through.add(ground.get(i));
            int dmg = 0;
            for (Attacker a : through) dmg += a.dmg();
            if (dmg <= 0) continue;
            best = Math.min(best, (o.getLife() + dmg - 1) / dmg);
            for (Attacker a : through) {
                if (!a.card().isCommander()) continue;
                int left = Math.max(1, 21 - o.getCommanderDamage(a.card()));
                best = Math.min(best, (left + a.dmg() - 1) / a.dmg());
            }
        }
        return best;
    }

    // ---------------------------------------------------------------- whom to attack (patch 69)
    /** What p's creatures that can attack o right now get through o's untapped blockers (each blocks p's biggest attacker it can):
     *  {damage, 1 if a commander among them reaches 21 commander damage}. Double strike counted, as in the clock. */
    static int[] throughNow(Player p, Player o) {
        List<Attacker> ground = new ArrayList<>(), air = new ArrayList<>();
        for (Card c : p.getCreaturesInPlay()) {
            if (c.hasKeyword(Keyword.DEFENDER) || c.isTapped() || c.hasSickness()) continue;
            int pw = Math.max(0, c.getNetCombatDamage());
            if (pw == 0) continue;
            Attacker a = new Attacker(doubleStrikes(c) ? 2 * pw : pw, c);
            (c.hasKeyword(Keyword.FLYING) || c.hasKeyword(Keyword.TRAMPLE) || c.hasKeyword(Keyword.SHADOW) ? air : ground).add(a);
        }
        Comparator<Attacker> big = Comparator.comparingInt(Attacker::dmg).reversed();
        ground.sort(big);
        air.sort(big);
        int groundBlock = 0, airBlock = 0;
        for (Card b : o.getCreaturesInPlay()) {
            if (b.isTapped()) continue;
            if (b.hasKeyword(Keyword.FLYING) || b.hasKeyword(Keyword.REACH)) airBlock++;
            else groundBlock++;
        }
        int dmg = 0, cmdKill = 0;
        List<Attacker> through = new ArrayList<>();
        for (int i = Math.min(airBlock, air.size()); i < air.size(); i++) through.add(air.get(i));
        int spare = Math.max(0, airBlock - air.size());
        for (int i = Math.min(groundBlock + spare, ground.size()); i < ground.size(); i++) through.add(ground.get(i));
        for (Attacker a : through) {
            dmg += a.dmg();
            if (a.card().isCommander() && o.getCommanderDamage(a.card()) + a.dmg() >= 21) cmdKill = 1;
        }
        return new int[] {dmg, cmdKill};
    }

    /** An opponent of p is a turn from winning: a one-turn clock, a combo on the battlefield, an engine cycle (patch 58's
     *  "very close"). Forge patch 73 casts a transmute card's spell only then. */
    static boolean emergency(Player p) {
        if (!REAL.contains(p.getGame())) return false;
        for (Player o : p.getOpponents()) {
            if (o.hasLost()) continue;
            double[] t = parts(o);
            if (t[T_CLOCK] <= 1 || t[T_COMBO] >= 90 || t[T_CYCLES] >= 1) return true;
        }
        return false;
    }

    /** Whom pilot seat p attacks (Forge patch 69). The user, 2026-10-18: "pressure leader, finish weakest when possible". A player
     *  this attack can kill (damage through its blockers covers its life, or a commander reaches 21), the most threatening of them;
     *  else the threat leader when some damage gets through; else null, and Forge's own pick (board value and low life: every seat
     *  sent most attacks at Erebos, who pays life to draw, in pod300_20261018). Blockers held back for an opponent's combat threat
     *  are Forge's own call (its next-combat prediction, which patch 69 lets see an attack trigger's double strike). */
    static Player chooseDefender(Player p) {
        if (!REAL.contains(p.getGame())) return null;
        Player kill = null, leader = null;
        double killThreat = -1, top = -1;
        int[] leaderThrough = null;
        for (Player o : p.getOpponents()) {
            if (o.hasLost()) continue;
            int[] t = throughNow(p, o);
            double th = threatNow(o);
            if ((o.canLoseLife() && t[0] >= o.getLife()) || t[1] == 1) {
                if (th > killThreat) { killThreat = th; kill = o; }
            }
            if (th > top) { top = th; leader = o; leaderThrough = t; }
        }
        Player pick = kill != null ? kill : leader != null && leaderThrough[0] > 0 ? leader : null;
        String why = kill != null ? "kill" : pick != null ? "leader" : "forge";
        System.out.println("#FP-DEFENDER {\"seat\": \"" + p.getName() + "\", \"turn\": " + p.getGame().getPhaseHandler().getTurn()
                + ", \"pick\": \"" + (pick == null ? "" : pick.getName()) + "\", \"why\": \"" + why + "\"}");
        return pick;
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

    // ---------------------------------------------------------------- on demand, for decisions (phase 2)
    static PilotPolicy policyOf(Player p) { return p.getController() instanceof ForgeRunner.SafeControllerAi c ? c.policy : null; }

    /** The games the harness plays (ForgeRunner, PuzzleRunner). Forge's lookahead plays copies of them (ai.simulation.GameCopier,
     *  same lobby players, so the same SafeControllerAi and policy); the hooks answer 0 there: each copy is a new Game, so the
     *  per-game cache missed and every lookahead decision rescored every seat (games ran about 75% longer on the p57 pods). */
    static final Set<Game> REAL = Collections.synchronizedSet(Collections.newSetFromMap(new WeakHashMap<>()));

    static void register(Game g) { REAL.add(g); }

    /** A finished game's entries leave every per-game map. They are weak-keyed by the Game, but their values reach it (a Player
     *  key in the cache, a hold's threat seat), so the key never cleared and every game a worker played stayed on the heap
     *  (pod300_20261018: a worker ran out of memory after a dozen long games). ForgeRunner calls this when a game ends. */
    static void release(Game g) {
        REAL.remove(g);
        CACHE.remove(g);
        DECK_ANSWERS.remove(g);
        COUNTER_SHARE.remove(g);
        HOLD_SINCE.remove(g);
        HOLDS.remove(g);
    }

    /** p's threat now (no growth term: that needs history), scored as check() does; cached per game, turn, phase and stack,
     *  with the card and spell answers that depend on it (keyed "c|viewer|card id", "s|viewer|card id"). */
    static final Map<Game, Object[]> CACHE = Collections.synchronizedMap(new WeakHashMap<>());

    @SuppressWarnings("unchecked")
    static Map<Object, Object> cache(Game g) {
        String key = g.getPhaseHandler().getTurn() + "|" + g.getPhaseHandler().getPhase() + "|" + g.getStack().size()
                + "|" + g.getCardsIn(ZoneType.Battlefield).size();
        Object[] c = CACHE.get(g);
        if (c == null || !key.equals(c[0])) { c = new Object[] {key, new HashMap<Object, Object>()}; CACHE.put(g, c); }
        return (Map<Object, Object>) c[1];
    }

    static double threatNow(Player p) { return parts(p)[T_THREAT]; }

    static final int T_THREAT = 0, T_COMBO = 1, T_CLOCK = 2, T_PAYOFFS = 3, T_CYCLES = 4, T_MANA = 5;

    /** p's threat now and its parts {threat, combo, clock, payoffs, cycles, mana}, cached like the rest. */
    static double[] parts(Player p) {
        Map<Object, Object> m = cache(p.getGame());
        double[] v = (double[]) m.get(p);
        if (v == null) { v = score(p); m.put(p, v); }
        return v;
    }

    static double[] score(Player p) {
        List<Player> alive = new ArrayList<>();
        for (Player x : p.getGame().getPlayers()) if (!x.hasLost()) alive.add(x);
        Set<String> field = new HashSet<>();
        int manaSources = 0;
        for (Card c : p.getCardsIn(ZoneType.Battlefield)) { field.add(c.getName()); if (!c.getManaAbilities().isEmpty()) manaSources++; }
        int hand = p.getCardsIn(ZoneType.Hand).size();
        double combo = comboScore(policyOf(p), field, hand);
        int[] eg = engineGraph(p, new ArrayList<>());
        double eng = Math.min(40, 8 * eg[0]) + Math.min(10, 2 * eg[1]) + 15 * Math.min(2, eg[2]);
        double others = 0;
        for (Player o : alive) if (o != p) others += manaCapacity(o);
        others = alive.size() > 1 ? others / (alive.size() - 1) : 0;
        double mana = Math.min(40, 1.5 * Math.max(0, manaCapacity(p) - others) * (0.4 + 0.6 * Math.min(1.0, hand / 4.0)));
        double res = Math.min(30, 2 * hand + manaSources);
        int clock = new ThreatModel(p.getGame()).clockTurns(p);
        double t = combo + eng + mana + res + (clock <= 20 ? 50.0 / clock : 0);
        if (clock <= 1) t = Math.max(t, 110); else if (clock <= 2) t = Math.max(t, 100);
        return new double[] {t, combo, clock, eg[0], eg[2], mana};
    }

    /** Two pieces of a known combo still missing: up to 5, by the deck's tutor share (a quarter of its spells tutoring: the full 5).
     *  It was a flat 15, so every deck listing a two-card win led the table from turn 1 with nothing on the battlefield (Yusri and
     *  Zur top threat in 100% of turn 1-8 rows of pod300_20261018 while Wilson won the pod 48%; the user, 2026-10-18). */
    static double twoAway(PilotPolicy pol) {
        Double share = pol == null || pol.in.role_share == null ? null : pol.in.role_share.get("tutor");
        return 5 * Math.min(1.0, 4 * (share == null ? 0 : share));
    }

    static double comboScore(PilotPolicy pol, Set<String> field, int hand) {
        double combo = 0;
        if (pol == null) return 0;
        for (PilotPolicy.Combo cb : pol.in.combos) {
            if (cb.cards.size() < 2) continue;
            int missing = 0;
            for (String x : cb.cards) if (!field.contains(x)) missing++;
            double v = missing == 0 ? (cb.win ? 100 : 60) : missing == 1 ? 55 * Math.min(1.0, (hand + 1) / 4.0) * (cb.win ? 1 : 0.6)
                    : missing == 2 ? twoAway(pol) * (cb.win ? 1 : 0.6) : 0;
            combo = Math.max(combo, v);
        }
        return combo;
    }

    /** o's threat relative to the most threatening of viewer's opponents (1.0 for the leader). */
    static double relative(Player viewer, Player o) {
        double top = 0;
        for (Player x : viewer.getOpponents()) if (!x.hasLost()) top = Math.max(top, threatNow(x));
        return top <= 0 ? 1 : Math.min(1, threatNow(o) / top);
    }

    /** {links between card c and the rest of o's battlefield (either way), 1 if they make a cycle}. A spell about to resolve
     *  counts as if it were out. */
    static int[] cardLinks(Card c, Player o) {
        List<Card> perms = new ArrayList<>(o.getCardsIn(ZoneType.Battlefield));
        if (!perms.contains(c)) perms.add(c);
        boolean lifelink = false;
        for (Card x : perms) if (grantsLifelink(x)) { lifelink = true; break; }
        Set<String> pc = produces(c, lifelink), cc = consumes(c);
        int links = 0;
        boolean cycle = false;
        for (Card x : perms) {
            if (x == c) continue;
            Set<String> px = produces(x, lifelink), cx = consumes(x);
            boolean out = false, in = false;
            for (String e : pc) if (cx.contains(e)) { out = true; break; }
            for (String e : px) if (cc.contains(e)) { in = true; break; }
            links += (out ? 1 : 0) + (in ? 1 : 0);
            if (out && in) cycle = true;
        }
        return new int[] {links, cycle ? 1 : 0};
    }

    /** Is name in one of the deck's known combos; out = {pieces still missing from o's battlefield besides it, 1 if a win}. */
    static boolean inCombo(PilotPolicy pol, String name, Set<String> field, int[] out) {
        if (pol == null) return false;
        int best = 99;
        boolean win = false;
        for (PilotPolicy.Combo cb : pol.in.combos) {
            if (!cb.cards.contains(name) || cb.cards.size() < 2) continue;
            int missing = 0;
            for (String x : cb.cards) if (!x.equals(name) && !field.contains(x)) missing++;
            if (missing < best || (missing == best && cb.win)) { best = missing; win = cb.win; }
        }
        out[0] = best;
        out[1] = win ? 1 : 0;
        return best < 99;
    }

    /** How much removing permanent c matters to viewer (0-100): its controller's threat relative to viewer's other opponents,
     *  times its role: a combo piece, engine links and cycles, a big mana source, its share of the clock, the
     *  deck's '# key:' card; a commander loses points (commanderPenalty). Public information only (the deck lists are known; no hidden card is looked at). */
    public static double cardThreat(Player viewer, Card c) {
        Player o = c.getController();
        if (o == null || o == viewer || !o.isOpponentOf(viewer) || !REAL.contains(viewer.getGame())) return 0;
        Map<Object, Object> m = cache(viewer.getGame());
        String k = "c|" + viewer.getId() + "|" + c.getId();
        Double v = (Double) m.get(k);
        if (v == null) { v = cardThreat0(viewer, c, o); m.put(k, v); }
        return v;
    }

    static double cardThreat0(Player viewer, Card c, Player o) {
        PilotPolicy pol = policyOf(o);
        Set<String> field = new HashSet<>();
        for (Card x : o.getCardsIn(ZoneType.Battlefield)) field.add(x.getName());
        double imp = 0;
        int[] m = new int[2];
        boolean combo = inCombo(pol, c.getName(), field, m);
        if (combo) imp += m[0] == 0 ? (m[1] == 1 ? 70 : 40) : m[0] == 1 ? 30 : 0;
        int[] cl = cardLinks(c, o);
        imp += Math.min(30, 10 * cl[0]) + (cl[1] == 1 ? 25 : 0);
        if (!c.getManaAbilities().isEmpty() && c.getMaxManaProduced() >= 3) imp += 15;
        if (c.isCreature()) imp += Math.min(25, 2 * killDamage(c, viewer));
        if (pol != null && pol.in.keys.contains(c.getName())) imp += 20;
        double v = Math.min(100, imp) * (0.4 + 0.6 * relative(viewer, o));
        if (c.isCommander()) {
            boolean necessary = (combo && m[0] == 0) || cl[1] == 1 || (c.isCreature() && parts(o)[T_CLOCK] <= 2);
            v -= commanderPenalty(c, o, necessary);
        }
        return v;
    }

    /** A creature's combat damage a turn toward killing viewer: double strike counted twice, and a commander's scaled by how
     *  much faster 21 commander damage kills than viewer's life does (Wilson with Flaming Fist, 12 a turn against 40 life, is
     *  worth 23 here, a 9/9 vanilla 9: Forge's removal went to the bigger creature). */
    static double killDamage(Card c, Player viewer) {
        double d = Math.max(0, c.getNetCombatDamage()) * (doubleStrikes(c) ? 2 : 1);
        if (c.isCommander()) d *= Math.max(1.0, (double) viewer.getLife() / Math.max(1, 21 - viewer.getCommanderDamage(c)));
        return d;
    }

    /** Removing a commander mostly buys tempo: it goes back to the command zone and comes back for 2 more (the user,
     *  2026-10-17: often a bad play because it can be recast, sometimes necessary, so a gradient). Points off the removal
     *  weight by how cheaply its owner recasts it next turn: 12 with 2+ mana to spare, 7 just affordable, 3 when the tax puts
     *  it out of reach next turn; none when removing it is necessary anyway (it completes a combo on the battlefield, it is
     *  part of an engine cycle, or its owner's board kills within two turns). Forge adds 4 x this to its target priority, so
     *  12 is 48 points against a 5/5's ~200: a nudge, not a veto. (Replaces a flat +15 for being the commander.) */
    static double commanderPenalty(Card c, Player o, boolean necessary) {
        if (necessary) return 0;
        int spare = manaCapacity(o) - (c.getCMC() + 2 * c.getOwner().getCommanderCast(c));
        return spare >= 2 ? 12 : spare >= 0 ? 7 : 3;
    }

    /** How much countering spell sa matters to viewer (0-100): a win effect 100; completing a known combo, the deck's key card,
     *  engine links or a cycle it would make, the payoff triggers it sets off as it resolves (fedTriggers), a big spell, a mass
     *  removal; times the caster's relative threat; a commander loses points like a removed one (commanderPenalty). */
    public static double spellThreat(Player viewer, SpellAbility sa) {
        Player o = sa.getActivatingPlayer();
        Card c = sa.getHostCard();
        if (!REAL.contains(viewer.getGame())) return -1;
        if (o == null || c == null || o == viewer || !o.isOpponentOf(viewer)) return 0;
        for (SpellAbility x : chain(sa)) if (x.getApi() == ApiType.WinsGame) return 100;
        PilotPolicy pol = policyOf(o);
        Set<String> field = new HashSet<>();
        for (Card x : o.getCardsIn(ZoneType.Battlefield)) field.add(x.getName());
        double v = 0;
        int[] m = new int[2];
        boolean combo = inCombo(pol, c.getName(), field, m);
        if (combo) v += m[0] == 0 ? (m[1] == 1 ? 95 : 55) : m[0] == 1 ? 40 : 0;
        if (pol != null && pol.in.keys.contains(c.getName())) v += 35;
        else if (pol != null && pol.castPriority0(o, sa) >= 2) v += 25;   // it turns on the engine the caster's deck is built around
        if (freeCasts(c)) v += 40;   // patch 87: Dracogenesis, Omniscience: the caster's spells cost nothing from here on
        int[] cl = c.isPermanent() ? cardLinks(c, o) : new int[2];
        v += Math.min(30, 15 * cl[0]) + (cl[1] == 1 ? 25 : 0);
        v += Math.min(40, 10 * fedTriggers(sa, c, o));   // what it sets off as it resolves (Serra Angel into Soul Warden)
        int cmc = c.getCMC();
        v += cmc >= 6 ? 30 : cmc >= 4 ? 15 : 0;
        for (SpellAbility x : chain(sa)) {
            ApiType api = x.getApi();
            if (api == ApiType.DestroyAll || api == ApiType.DamageAll || api == ApiType.SacrificeAll
                    || (api == ApiType.ChangeZoneAll && "Battlefield".equals(x.getParam("Origin")))) { v += 40; break; }
        }
        Posture hp = posture(viewer);
        if (hp != null && hp.threat() == o) v += 20;   // it kept mana up for this seat: this is what the mana was for
        double out = Math.min(100, v) * (0.4 + 0.6 * relative(viewer, o));
        // a countered commander goes back to the command zone and comes again for 2 more, like a removed one (the user,
        // 2026-10-17: weigh it the same as removal; replaces a flat +25)
        if (c.isCommander()) out -= commanderPenalty(c, o, (combo && m[0] == 0) || cl[1] == 1 || (c.isCreature() && parts(o)[T_CLOCK] <= 2));
        return out;
    }

    /** A permanent that lets its controller cast spells without paying their mana costs (Dracogenesis: Dragons; Omniscience). */
    static boolean freeCasts(Card c) {
        if (!c.isPermanent()) return false;
        for (forge.game.staticability.StaticAbility st : c.getStaticAbilities())
            if (st.hasParam("MayPlayWithoutManaCost") && !st.getParamOrDefault("Affected", "").contains("Opp")) return true;
        return false;
    }

    /** Events a spell makes as it resolves, with how often (up to 3): a permanent entering (a land: landfall too) and its own
     *  enter trigger's effects, or a nonpermanent's effects: draws (a wheel's 7 count 3; each player drawing feeds opponents'
     *  draw payoffs too), tokens, life, damage, counters, sacrifices. One-shot effects count here (they fire the caster's
     *  payoffs once) though produces() leaves them out of the engine graph. */
    static Map<String, Integer> resolveEvents(SpellAbility sa, Card host) {
        Map<String, Integer> ev = new HashMap<>();
        List<SpellAbility> parts = new ArrayList<>(chain(sa));
        if (host.isPermanent()) {
            ev.merge("enters", 1, Math::max);
            if (host.isLand()) ev.merge("landfall", 1, Math::max);
            for (Trigger t : host.getTriggers())
                if (t.getMode() == TriggerType.ChangesZone && "Battlefield".equals(t.getParam("Destination"))
                        && t.getParamOrDefault("ValidCard", "").startsWith("Card.Self"))
                    try { if (t.ensureAbility() != null) parts.addAll(chain(t.ensureAbility())); } catch (RuntimeException e) { }
        }
        for (SpellAbility x : parts) {
            ApiType api = x.getApi();
            if (api == null) continue;
            int n = 1;
            try { n = Math.max(1, Math.min(3, Integer.parseInt(x.getParamOrDefault("NumCards", x.getParamOrDefault("Amount", "1")).trim()))); }
            catch (NumberFormatException e) { }
            switch (api) {
                case Draw -> {
                    String def = x.getParamOrDefault("Defined", "You");
                    if (!def.contains("Opponent")) ev.merge("draw", n, Math::max);
                    if (def.contains("Opponent") || def.startsWith("Player")) ev.merge("oppdraw", n, Math::max);
                }
                case Token, CopyPermanent -> { ev.merge("token", n, Math::max); ev.merge("enters", n, Math::max); }
                case ChangeZone -> {
                    if ("Battlefield".equals(x.getParam("Destination"))) {
                        ev.merge("enters", 1, Math::max);
                        if (x.getParamOrDefault("ChangeType", "").contains("Land")) ev.merge("landfall", 1, Math::max);
                    }
                }
                case GainLife -> ev.merge("lifegain", 1, Math::max);
                case LoseLife -> { if (x.getParamOrDefault("Defined", "").contains("Opponent")) ev.merge("lifeloss", 1, Math::max); }
                case DealDamage, DamageAll -> ev.merge("damage", 1, Math::max);
                case PutCounter, PutCounterAll -> ev.merge("counter", 1, Math::max);
                case Sacrifice, SacrificeAll -> ev.merge("sacrifice", 1, Math::max);
                default -> { }
            }
        }
        return ev;
    }

    /** Payoff triggers of o's that spell sa sets off as it resolves: for each of o's permanents, the most a resolution event it
     *  feeds on happens (a counterspell sees what the spell feeds: Serra Angel entering next to Soul Warden and Essence Warden
     *  is 2; Reforge the Soul with Xyris out is 3). Board and deck knowledge only. */
    static int fedTriggers(SpellAbility sa, Card host, Player o) {
        Map<String, Integer> ev = resolveEvents(sa, host);
        if (ev.isEmpty()) return 0;
        int fed = 0;
        for (Card x : o.getCardsIn(ZoneType.Battlefield)) {
            if (x == host) continue;
            int best = 0;
            for (String e : consumes(x)) best = Math.max(best, ev.getOrDefault(e, 0));
            fed += best;
        }
        return fed;
    }

    // ---------------------------------------------------------------- phase 3: mana posture (patch 58)
    // When does a seat keep mana up instead of tapping out? (the user, 2026-10-16) When it holds an instant-speed answer that
    // fits the opponent closest to winning, that opponent is close, the seat isn't the leader itself (the leader pushes) and
    // nobody else at the table is set to answer it (another deck with 6+ instant-speed answers and 2+ mana up) unless the
    // threat is very close (a 1-turn clock, a completed combo, an engine cycle). "Close" is calibrated on 24k logged
    // seat-turns: a 2-turn clock won within a round 20% of the time, a completed combo 26%, an engine cycle 22%, 3+ payoffs
    // 19%, a 30-mana lead 31%, against a 3% base; one missing combo piece only 9%, but that is what counterspells are for.
    // Counterspells fit a combo a piece away or closer, a mana lead and an engine still being built; removal fits a cycle, a
    // 2-turn clock, a completed combo and an engine. Mana kept and not needed is spent at the end of the turn before the
    // seat's own (cycling, instants, flash).
    static final boolean HOLD_ON = !"false".equals(System.getProperty("fishpond.holdMana"));

    /** An instant-speed answer: 1 a counterspell, 2 targeted removal of a permanent (destroy, exile, bounce, sacrifice,
     *  damage to a creature); 0 otherwise. */
    static int answerKind(Card c) {
        if (!(c.isInstant() || c.hasKeyword(Keyword.FLASH))) return 0;
        int kind = 0;
        for (SpellAbility sa : c.getSpells()) {
            boolean blink = false;   // a card exiled and returned (Ephemerate) is protection, not removal
            for (SpellAbility x : chain(sa))
                if (x.getApi() == ApiType.ChangeZone && "Exile".equals(x.getParam("Origin")) && "Battlefield".equals(x.getParam("Destination"))) blink = true;
            for (SpellAbility x : chain(sa)) {
                ApiType api = x.getApi();
                if (api == ApiType.Counter) return 1;
                if (api == null || !x.usesTargeting() || blink) continue;
                String tgts = x.getParamOrDefault("ValidTgts", "");
                if (tgts.contains("YouCtrl") || tgts.contains("YouOwn")) continue;   // its own permanents only
                if (api == ApiType.Destroy || api == ApiType.Sacrifice
                        || (api == ApiType.ChangeZone && "Battlefield".equals(x.getParam("Origin")))
                        || (api == ApiType.DealDamage && tgts.contains("Creature"))) kind = 2;
            }
        }
        return kind;
    }

    static final Map<Game, Map<Player, Integer>> DECK_ANSWERS = Collections.synchronizedMap(new WeakHashMap<>());

    /** Instant-speed answers in p's deck: its list, every zone counted together (deck knowledge, no hidden card located). */
    static int deckAnswers(Player p) {
        Map<Player, Integer> m = DECK_ANSWERS.computeIfAbsent(p.getGame(), k -> new HashMap<>());
        Integer v = m.get(p);
        if (v == null) {
            int n = 0;
            for (ZoneType z : new ZoneType[] {ZoneType.Library, ZoneType.Hand, ZoneType.Graveyard, ZoneType.Battlefield,
                    ZoneType.Exile, ZoneType.Command})
                for (Card c : p.getCardsIn(z)) if (c.getOwner() == p && answerKind(c) > 0) n++;
            m.put(p, v = n);
        }
        return v;
    }

    /** A seat's hold: the answer it keeps mana for, its cost, the opponent it is for and why. */
    record Posture(int keep, String answer, Player threat, String why) { }

    static final Posture NONE = new Posture(0, null, null, null);

    static Posture posture(Player ai) {
        Map<Object, Object> m = cache(ai.getGame());
        String k = "h|" + ai.getId();
        Posture v = (Posture) m.get(k);
        if (v == null) { v = posture0(ai); m.put(k, v); }
        return v == NONE ? null : v;
    }

    static Posture posture0(Player ai) {
        PhaseHandler ph = ai.getGame().getPhaseHandler();
        if ((ph.is(PhaseType.END_OF_TURN) || ph.is(PhaseType.CLEANUP)) && ph.getNextTurn() == ai) return NONE;   // spend it now
        List<Card> answers = new ArrayList<>();
        for (Card c : ai.getCardsIn(ZoneType.Hand)) if (answerKind(c) > 0) answers.add(c);
        if (answers.isEmpty()) return NONE;
        Player top = null;
        double best = -1;
        for (Player o : ai.getOpponents()) if (!o.hasLost() && threatNow(o) > best) { best = threatNow(o); top = o; }
        if (top == null || threatNow(ai) >= best) return NONE;   // the leader pushes
        double[] t = parts(top);
        boolean veryClose = t[T_CLOCK] <= 1 || t[T_COMBO] >= 90 || t[T_CYCLES] >= 1;
        boolean close = veryClose || t[T_CLOCK] <= 2 || t[T_COMBO] >= 40 || t[T_PAYOFFS] >= 3 || t[T_MANA] >= 30;
        if (!close) return NONE;
        if (!veryClose)
            for (Player o : ai.getOpponents())
                if (o != top && !o.hasLost() && deckAnswers(o) >= 6 && ComputerUtilMana.getAvailableManaEstimate(o, false) >= 2)
                    return NONE;   // someone else is set to answer it
        // a counterspell stops the piece still to come, not a combo already on the battlefield
        boolean counterFits = (t[T_COMBO] >= 40 && t[T_COMBO] < 90) || t[T_MANA] >= 30 || t[T_PAYOFFS] >= 3;
        boolean removalFits = t[T_CYCLES] >= 1 || t[T_CLOCK] <= 2 || t[T_COMBO] >= 90 || t[T_PAYOFFS] >= 3;
        int sources = 0;
        for (Card c : ai.getCardsIn(ZoneType.Battlefield)) if (!c.getManaAbilities().isEmpty()) sources++;
        Card pick = null;
        for (Card c : answers) {
            int kind = answerKind(c);
            if (c.getCMC() > sources || !((kind == 1 && counterFits && counterShare(ai, c, top) >= 0.35)
                    || (kind == 2 && removalFits && hitsWhatMatters(ai, c, top)))) continue;
            if (pick == null || c.getCMC() < pick.getCMC()) pick = c;
        }
        if (pick == null) return NONE;
        String why = t[T_CYCLES] >= 1 ? "cycle" : t[T_COMBO] >= 90 ? "combo" : t[T_CLOCK] <= 2 ? "clock"
                : t[T_COMBO] >= 40 ? "combo-1" : t[T_MANA] >= 30 ? "mana" : "payoffs";
        if (why.equals("combo-1") || why.equals("mana") || why.equals("payoffs")) {   // a weak signal earns one round of holding
            Map<String, Integer> since = HOLD_SINCE.computeIfAbsent(ai.getGame(), k -> new HashMap<>());
            Integer first = since.putIfAbsent(ai.getId() + "|" + top.getId() + "|" + why, ph.getTurn());
            if (first != null && ph.getTurn() - first >= 4) return NONE;
        }
        return new Posture(Math.max(1, pick.getCMC()), pick.getName(), top, why);
    }

    static final Map<Game, Map<String, Double>> COUNTER_SHARE = Collections.synchronizedMap(new WeakHashMap<>());

    /** The share of opp's nonland cards (its whole list, every zone: deck knowledge) a counterspell can target. A narrow one
     *  only fits a deck it can hit: Yusri held Muddle the Mixture (instants and sorceries) while Niv cast Niv-Mizzet,
     *  Sheoldred and Rest in Peace, and Swan Song against Xyris's creatures (2026-10-17). Needs 35%. */
    static double counterShare(Player ai, Card answer, Player opp) {
        String valid = null;
        SpellAbility csa = null;
        for (SpellAbility sa : answer.getSpells())
            for (SpellAbility x : chain(sa)) if (valid == null && x.getApi() == ApiType.Counter) { valid = x.getParamOrDefault("ValidTgts", "Card"); csa = x; }
        if (valid == null || valid.equals("Card") || valid.equals("Any")) return 1;
        Map<String, Double> m = COUNTER_SHARE.computeIfAbsent(ai.getGame(), k -> new HashMap<>());
        String key = answer.getName() + "|" + opp.getId();
        Double v = m.get(key);
        if (v == null) {
            int n = 0, ok = 0;
            for (ZoneType z : new ZoneType[] {ZoneType.Library, ZoneType.Hand, ZoneType.Graveyard, ZoneType.Battlefield,
                    ZoneType.Exile, ZoneType.Command})
                for (Card c : opp.getCardsIn(z)) {
                    if (c.getOwner() != opp || c.isLand()) continue;
                    n++;
                    for (String r : valid.split(",")) {
                        boolean hit;
                        try { hit = c.isValid(r, ai, answer, csa); } catch (RuntimeException e) { hit = false; }
                        if (hit) { ok++; break; }
                    }
                }
            m.put(key, v = n == 0 ? 1.0 : (double) ok / n);
        }
        return v;
    }

    /** Removal fits only if it can target one of the threat's permanents that matter (cardThreat at the remove-now line, 40):
     *  Yusri kept Pongify up against Omnath's combo, whose pieces aren't creatures (2026-10-17). */
    static boolean hitsWhatMatters(Player ai, Card answer, Player top) {
        for (SpellAbility sa : answer.getSpells())
            for (SpellAbility x : chain(sa)) {
                if (!x.usesTargeting()) continue;
                for (Card p : top.getCardsIn(ZoneType.Battlefield)) {
                    if (cardThreat(ai, p) < 40) continue;
                    try {
                        if (x.getActivatingPlayer() == null) x.setActivatingPlayer(ai);
                        if (x.canTarget(p)) return true;
                    } catch (RuntimeException e) { /* a target check the card can't answer out of context: not a fit */ }
                }
            }
        return false;
    }

    /** When a seat first held against an opponent for a weak reason ("seat|threat|why" -> turn). */
    static final Map<Game, Map<String, Integer>> HOLD_SINCE = Collections.synchronizedMap(new WeakHashMap<>());

    /** A permanent of p's that triggers on cycling (Astral Drift, Astral Slide, Drake Haven): cycling is its engine. */
    static boolean cyclingPayoff(Player p) {
        for (Card c : p.getCardsIn(ZoneType.Battlefield))
            for (Trigger t : c.getTriggers()) if (t.getMode() == TriggerType.Cycled) return true;
        return false;
    }

    /** Holds per game, one per seat, turn, phase and refused spell: printed as #FP-HOLD at the game's end. */
    static final Map<Game, LinkedHashSet<String>> HOLDS = Collections.synchronizedMap(new WeakHashMap<>());

    /** Patch 58's hook: does ai keep its mana up instead of playing sa? */
    public static boolean holdBlocks(Player ai, SpellAbility sa) {
        if (!HOLD_ON || sa == null || !REAL.contains(ai.getGame()) || sa.isManaAbility() || sa.isLandAbility()) return false;
        Card host = sa.getHostCard();
        if (host != null && sa.isSpell() && answerKind(host) > 0) return false;   // the answers themselves
        Cost cost = sa.getPayCosts();
        if (cost == null || cost.getTotalMana() == null) return false;
        int cmc = cost.getTotalMana().getCMC();
        boolean x = cost.getTotalMana().countX() > 0;
        if (cmc == 0 && !x) return false;
        Posture p = posture(ai);
        if (p == null) return false;
        for (SpellAbility y : chain(sa)) if (y.getApi() == ApiType.WinsGame) return false;
        // its own plan goes ahead: a held 2-mana answer is worth less than the deck's key card, its commander, a combo or
        // engine piece (cast plan level 2+) or a big spell (Yusri held Counterspell over Nexus of Fate, Jin-Gitaxias and Enter
        // the Infinite; Zur over Triskaidekaphile, Astral Drift and itself, 2026-10-17)
        PilotPolicy pol = policyOf(ai);
        if (host != null && sa.isSpell() && (host.isCommander() || host.getCMC() >= 6)) return false;
        if (host != null && pol != null && pol.isKey(host.getName())) return false;   // cast or used: Step Through is only ever wizardcycled
        if (pol != null && pol.castPriority0(ai, sa) >= 2) return false;
        if (sa.isCycling() && cyclingPayoff(ai)) return false;   // cycling into Astral Drift is the engine itself
        int avail = ComputerUtilMana.getAvailableManaEstimate(ai, false);
        if (avail < p.keep() || (!x && avail - cmc >= p.keep())) return false;   // nothing to keep, or enough left after it
        Game g = ai.getGame();
        HOLDS.computeIfAbsent(g, k -> new LinkedHashSet<>()).add("{\"t\": " + g.getPhaseHandler().getTurn() + ", \"seat\": \""
                + seat(ai) + "\", \"phase\": \"" + g.getPhaseHandler().getPhase() + "\", \"answer\": " + ForgeRunner.js(p.answer())
                + ", \"keep\": " + p.keep() + ", \"threat\": \"" + seat(p.threat()) + "\", \"why\": \"" + p.why() + "\", \"refused\": "
                + ForgeRunner.js(host == null ? "?" : host.getName()) + "}");
        return true;
    }

    /** Sets Forge's threat hooks (patches 57 and 58), by reflection: the harness compiles against the stock jar. */
    static void installHooks() {
        java.util.function.ToDoubleBiFunction<Player, Card> ct = ThreatModel::cardThreat;
        java.util.function.ToDoubleBiFunction<Player, SpellAbility> st = ThreatModel::spellThreat;
        try {
            forge.ai.AiController.class.getField("CARD_THREAT").set(null, ct);
            forge.ai.AiController.class.getField("SPELL_THREAT").set(null, st);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no threat hooks in this Forge build (patch 57)");
        }
        java.util.function.BiFunction<Player, SpellAbility, Boolean> rf = Refill::judge;   // patch 78: refills by projected draw
        try {
            forge.ai.AiController.class.getField("REFILL").set(null, rf);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no refill hook in this Forge build (patch 78)");
        }
        java.util.function.BiFunction<Player, SpellAbility, forge.game.card.CardCollectionView> pb = Refill::putBack;   // patch 82
        try {
            forge.ai.ComputerUtil.class.getField("PUT_BACK").set(null, pb);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no put-back hook in this Forge build (patch 82)");
        }
        java.util.function.Predicate<Player> em = ThreatModel::emergency;   // patch 73: a transmute card's spell only in an emergency
        try {
            forge.ai.AiController.class.getField("EMERGENCY").set(null, em);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no emergency hook in this Forge build (patch 73)");
        }
        java.util.function.Function<Player, Player> def = ThreatModel::chooseDefender;   // patch 69: whom to attack
        try {
            forge.ai.AiAttackController.class.getField("DEFENDER").set(null, def);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no defender hook in this Forge build (patch 69)");
        }
        java.util.function.BiPredicate<Player, SpellAbility> hold = ThreatModel::holdBlocks;
        try {
            forge.ai.AiController.class.getField("HOLD_MANA").set(null, hold);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no mana-posture hook in this Forge build (patch 58)");
        }
        // patch 64: the turn plan asks for setup values, the mana Phase 3 keeps up, and which games are real
        // (plus building the seat's repeatable engines: casting a missing piece of a loop, PilotPolicy.loopValue)
        java.util.function.ToDoubleBiFunction<Player, Card> setup = (p, c) -> SetupModel.setupValue(p, c)
                + (p.getController() instanceof ForgeRunner.SafeControllerAi sc && sc.policy != null ? sc.policy.loopValue(p, c, true) : 0);
        java.util.function.ToIntFunction<Player> keep = p -> { Posture x = posture(p); return x == null ? 0 : x.keep(); };
        java.util.function.Predicate<Game> real = REAL::contains;
        try {
            Class<?> tp = Class.forName("forge.ai.TurnPlan");
            tp.getField("SETUP_VALUE").set(null, setup);
            tp.getField("HOLD_KEEP").set(null, keep);
            tp.getField("IS_REAL").set(null, real);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no turn-plan hooks in this Forge build (patch 64)");
        }
        java.util.function.Function<Player, String> answer = p -> { Posture x = posture(p); return x == null ? null : x.answer(); };
        try {   // patch 84: the plan keeps the held answer's colors too
            Class.forName("forge.ai.TurnPlan").getField("HOLD_ANSWER").set(null, answer);
        } catch (ReflectiveOperationException e) {
            ForgeRunner.out.println("#FP-WARN no held-answer hook in this Forge build (patch 84)");
        }
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
                            : missing == 2 ? twoAway(pol) * (cb.win ? 1 : 0.6) : 0;
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
