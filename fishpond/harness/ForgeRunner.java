// Fishpond harness: plays a list of seeded Commander games on Forge in one JVM and prints each game's log in the
// stock `sim` format, plus Fishpond's own lines (#FP-...) with per-turn snapshots and how the game was stopped.
//
// Compiled at runtime by fishpond/runner.py against the cached Forge jar (javac -cp <jar>); never vendored.
// Modelled on forge.view.SimulateMatch. Differences: every game is its own Match with its own RNG seed (any game can be
// replayed alone), the game stops when the hero (seat 1) has lost and no real opponent is left to finish the pod, or at
// the end of the hero's turn CAP, and snapshots are taken at the hero's first main phase and cleanup step.
//
// usage: java -cp <jar>:<dir> ForgeRunner DECK_DIR PLAN_FILE    (cwd = the Forge install: it reads res/ from there)
// PLAN_FILE lines, tab-separated: id seed cap timeout_s colors play_out deck1 deck2 deck3 deck4 ai1,ai2,ai3,ai4 sim1,..,sim4 keys
//   colors = the hero's color identity (e.g. WUG); play_out = 1 to keep playing after the hero dies (real opponents left)
//   sim = off | hybrid | full per seat: Forge's lookahead (AIOption). hybrid = the heuristic AI picks, a one-move simulation
//   vetoes plays that leave it worse off; full = picks by search (depth 3, fixed in Forge) and also decides library searches.
//   keys = the hero's '# key:' cards, '|'-separated (for tutor reporting)

import com.google.common.eventbus.Subscribe;
import forge.GuiDesktop;
import forge.ai.AIOption;
import forge.ai.AiController;
import forge.ai.PlayerControllerAi;
import forge.game.ability.ApiType;
import forge.ai.ComputerUtilMana;
import forge.deck.Deck;
import forge.deck.io.DeckSerializer;
import forge.game.Game;
import forge.game.GameEndReason;
import forge.game.GameLogEntry;
import forge.game.GameRules;
import forge.game.GameType;
import forge.game.Match;
import forge.game.card.Card;
import forge.game.event.GameEvent;
import forge.game.event.GameEventCardChangeZone;
import forge.game.event.GameEventTurnBegan;
import forge.game.event.GameEventTurnPhase;
import forge.game.event.GameEventSpellAbilityCast;
import forge.game.event.GameEventAttackersDeclared;
import forge.game.event.GameEventLandPlayed;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerOutcome;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.AbilityManaPart;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.util.MyRandom;

import java.io.File;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.*;

public class ForgeRunner {
    enum AiControllerSim {
        HYBRID(AIOption.USE_HYBRID_SIMULATION), FULL(AIOption.USE_FULL_SIMULATION);
        final AIOption option;
        AiControllerSim(AIOption o) { option = o; }
    }

    static final String[] COLORS = {"W", "U", "B", "R", "G"};
    static PrintStream out;

    public static void main(String[] args) throws Exception {
        out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8");
        System.setProperty("java.awt.headless", "true");
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        // fishpond patch 54: Forge's cast ordering asks the seat's pilot policy for the deck's plan (PilotPolicy.castPriority);
        // (the lookahead's game copies keep the same lobby players, so their seats get it too)
        // (set by reflection: the harness compiles against the stock jar, where the field doesn't exist)
        java.util.function.ToIntBiFunction<Player, forge.game.spellability.SpellAbility> castPlan =
                (p, sa) -> p.getController() instanceof SafeControllerAi c && c.policy != null ? c.policy.castPriority(p, sa) : 0;
        try { forge.ai.AiController.class.getField("CAST_PRIORITY").set(null, castPlan); }
        catch (ReflectiveOperationException e) { out.println("#FP-WARN no cast-plan hook in this Forge build (patch 54)"); }
        // fishpond patch 55: the deck's '# key:' cards, so the cycling rule never cycles one away
        java.util.function.BiPredicate<Player, Card> keyCard =
                (p, c) -> p.getController() instanceof SafeControllerAi sc && sc.policy != null && sc.policy.isKey(c.getName());
        try { forge.ai.AiController.class.getField("KEY_CARD").set(null, keyCard); }
        catch (ReflectiveOperationException e) { out.println("#FP-WARN no key-card hook in this Forge build (patch 55)"); }
        ThreatModel.installHooks();   // patch 57: counterspells and removal weigh the threat model
        String deckDir = args[0];
        Map<String, Deck> decks = new HashMap<>();
        out.println("#FP-READY");
        for (String line : Files.readAllLines(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("#")) continue;
            String[] f = line.split("\t");
            try {
                runGame(f, deckDir, decks, null);
            } catch (Throwable t) {
                out.println("#FP-ERROR {\"id\": " + f[0] + ", \"error\": " + js(String.valueOf(t)) + "}");
                out.println("\nGame Result: Game " + f[0] + " ended in a Draw! Took 0 ms.");
            }
            out.flush();
        }
        out.flush();
        System.exit(0);
    }

    /** Safety net for Forge's lookahead throwing inside its own search, where the harness can't see or pause (copies of
     *  copies). The known cases are fixed in fishpond/forge_patches (docs/FORGE_ISSUES.md #2, #4); anything still thrown
     *  would end the real game, so that one decision is made again with lookahead off, logged (#FP-SIMFB, sim_decision_log),
     *  and the game goes on with lookahead back on. It should stay at zero: each one is a Forge bug to root out.
     *  Deterministic: the same seed throws at the same point. */
    static final class SimFallbacks { int n = 0; String first = null; Game game; final List<String> log = new ArrayList<>(); }

    /** The frames that say where Forge threw: from the throw point down to the AI's entry, Forge frames only. */
    static String where(Throwable e) {
        StringBuilder b = new StringBuilder();
        int k = 0;
        for (StackTraceElement el : e.getStackTrace()) {
            String c = el.getClassName();
            if (c.startsWith("ForgeRunner") || c.equals("forge.ai.PlayerControllerAi")) break;
            if (!c.startsWith("forge.")) continue;
            if (b.length() > 0) b.append(" < ");
            b.append(c.substring(6)).append('.').append(el.getMethodName()).append(':').append(el.getLineNumber());
            if (++k >= 14) break;
        }
        return b.toString();
    }

    /** LobbyPlayerAi that gives its in-game players a SafeControllerAi (a controller can only be assigned once). Forge's game
     *  copier reuses this lobby player for its copies, whose controllers rethrow so the real game's decision handles it. */
    static final class SafeLobbyPlayerAi extends forge.ai.LobbyPlayerAi {
        final SimFallbacks fb;
        final AIOption mode;
        final PilotPolicy policy;
        SafeLobbyPlayerAi(String name, Set<AIOption> opts, SimFallbacks fb, PilotPolicy policy) {
            super(name, opts);
            this.fb = fb;
            this.policy = policy;
            this.mode = opts == null || opts.isEmpty() ? null : opts.iterator().next();
        }
        SafeControllerAi controllerFor(Player p) {
            SafeControllerAi c = new SafeControllerAi(p.getGame(), p, this, fb, policy);
            c.getAi().setUseSimulation(mode);
            return c;
        }
        @Override public Player createIngamePlayer(Game game, int id) {
            Player p = new Player(getName(), game, id);
            p.setFirstController(controllerFor(p));
            return p;
        }
        @Override public forge.game.player.PlayerController createMindSlaveController(Player master, Player slave) { return controllerFor(slave); }
    }

    static final class SafeControllerAi extends PlayerControllerAi {
        final SimFallbacks fb;
        final PilotPolicy policy;
        SafeControllerAi(Game g, Player p, forge.LobbyPlayer lp, SimFallbacks fb, PilotPolicy policy) { super(g, p, lp); this.fb = fb; this.policy = policy; }

        /** Library searches: the pilot policy picks (PilotPolicy.java); Forge's pick is kept for the log and ties. With full
         *  lookahead, Forge's simulation chooses among the policy's top three instead of the whole list. */
        @Override public Card chooseSingleCardForZoneChange(ZoneType destination, List<ZoneType> origin, SpellAbility sa,
                forge.game.card.CardCollection fetchList, forge.game.player.DelayedReveal delayedReveal, String selectPrompt,
                boolean isOptional, Player decider) {
            Player me = getPlayer();
            if (policy == null || sa == null || sa.getApi() == ApiType.Learn || !PilotPolicy.appliesToSearch(destination, origin, fetchList, decider, me))
                return super.chooseSingleCardForZoneChange(destination, origin, sa, fetchList, delayedReveal, selectPrompt, isOptional, decider);
            if (delayedReveal != null) reveal(delayedReveal);
            Card forgePick = forge.ai.ability.ChangeZoneAi.chooseCardToHiddenOriginChangeZone(destination, origin, sa, fetchList, me, decider);
            if (forgePick == null && isOptional) return null;             // Forge declines an optional search: respect it
            var ranked = policy.rank(new ArrayList<>(fetchList), me, sa, destination, forgePick);
            Card pick = ranked.get(0).getKey();
            String mode = "policy";
            Card gated = policy.commanderGate(me, ranked, forgePick);   // the user's tutor rule (hand, battlefield or top of library)
            if (gated != null) { pick = gated; mode = "commander-gate"; }
            else if (getAi().usesFullSimulation()) {
                forge.game.card.CardCollection shortlist = new forge.game.card.CardCollection();
                for (int i = 0; i < Math.min(3, ranked.size()); i++) shortlist.add(ranked.get(i).getKey());
                Card sim = getAi().chooseCardToHiddenOriginChangeZone(destination, origin, sa, shortlist, me, decider);
                if (sim != null) { pick = sim; mode = "full-shortlist"; }
            }
            if (me.getGame() == fb.game) policy.note(me, sa, "search", destination, ranked, pick, forgePick, mode);
            return pick;
        }

        /** Digs (look at the top N, put some into hand or play): the pilot policy picks; other choices go to Forge. */
        @Override public <T extends forge.game.GameEntity> T chooseSingleEntityForEffect(forge.util.collect.FCollectionView<T> optionList,
                forge.game.player.DelayedReveal delayedReveal, SpellAbility sa, String title, boolean isOptional, Player targetedPlayer,
                Map<String, Object> params) {
            // a card cast from an effect (cascade, "you may cast", PlayAi.chooseSingleCard) is checked by lookahead here too;
            // a crash in it is remade without lookahead and counted, like chooseSpellAbilityToPlay (FORGE_PLAN item 7)
            T forgePick = simRetry(() -> super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, targetedPlayer, params));
            Player me = getPlayer();
            if (policy == null || (forgePick == null && isOptional) || !PilotPolicy.appliesToDig(sa, optionList, me)) return forgePick;
            List<Card> cands = new ArrayList<>();
            for (T o : optionList) cands.add((Card) o);
            ZoneType dest = "Battlefield".equals(sa.getParam("DestinationZone")) ? ZoneType.Battlefield : ZoneType.Hand;
            var ranked = policy.rank(cands, me, sa, dest, (Card) forgePick);
            Card pick = ranked.get(0).getKey();
            if (me.getGame() == fb.game) policy.note(me, sa, "dig", dest, ranked, pick, (Card) forgePick, "policy");
            @SuppressWarnings("unchecked") T t = (T) pick;
            return t;
        }

        /** Thrown inside Forge's lookahead, or with no stack to tell (the JVM can drop it; the runner turns that off): such a
         *  decision is remade without lookahead, and if it was a real crash the remake throws it again. */
        static boolean fromSim(Throwable t) {
            for (; t != null; t = t.getCause()) {
                if (t.getStackTrace().length == 0) return true;
                for (StackTraceElement el : t.getStackTrace()) if (el.getClassName().startsWith("forge.ai.simulation.")) return true;
            }
            return false;
        }

        @Override public List<SpellAbility> chooseSpellAbilityToPlay() {
            return simRetry(super::chooseSpellAbilityToPlay);
        }

        /** A spell an effect lets you cast (cascade, "you may cast it"): lookahead checks it in canPlayFromEffectAI before
         *  anything is played, so a crash there (GameCopier mapping a combat, 2026-10-10: 5 of 16 real-pod games) is
         *  remade without lookahead like any other decision. */
        @Override public boolean playSaFromPlayEffect(SpellAbility tgtSA) {
            return simRetry(() -> super.playSaFromPlayEffect(tgtSA));
        }

        /** Run one AI decision; if Forge's simulation code throws inside it, remake that decision with lookahead off, count it
         *  (sim_decision_fallbacks) and log where it threw. */
        <R> R simRetry(java.util.function.Supplier<R> decision) {
            try {
                return decision.get();
            } catch (RuntimeException e) {
                AiController a = getAi();
                AIOption m = a.usesFullSimulation() ? AIOption.USE_FULL_SIMULATION : a.usesHybridSimulation() ? AIOption.USE_HYBRID_SIMULATION : null;
                if (m == null || !fromSim(e) || getPlayer().getGame() != fb.game) throw e;
                fb.n++;
                if (fb.first == null) {
                    StringBuilder tr = new StringBuilder(e.toString());
                    for (StackTraceElement el : e.getStackTrace()) {
                        tr.append(" < ").append(el.getClassName().replaceAll("^forge\\.", "")).append('.').append(el.getMethodName()).append(':').append(el.getLineNumber());
                        if (tr.length() > 1200) break;
                    }
                    fb.first = tr.toString();
                }
                Game g = getPlayer().getGame();
                var ph = g.getPhaseHandler();
                StringBuilder stack = new StringBuilder();
                for (var si : g.getStack()) { if (stack.length() > 0) stack.append(" | "); stack.append(si.getSpellAbility()); }
                a.setUseSimulation(null);
                R played = null;
                try { played = decision.get(); return played; }
                finally {
                    a.setUseSimulation(m);
                    String entry = "{\"t\": " + ph.getTurn() + ", \"phase\": " + js(String.valueOf(ph.getPhase())) + ", \"seat\": " + js(getPlayer().getName())
                            + ", \"active\": " + js(ph.getPlayerTurn() == null ? "" : ph.getPlayerTurn().getName()) + ", \"mode\": " + js(m.name())
                            + ", \"stack\": " + js(stack.toString()) + ", \"exc\": " + js(String.valueOf(e)) + ", \"at\": " + js(where(e))
                            + ", \"played\": " + js(played == null || played instanceof List && ((List<?>) played).isEmpty() ? "(pass)" : String.valueOf(played)) + "}";
                    fb.log.add(entry);
                    out.println("#FP-SIMFB " + entry);
                }
            }
        }
    }

    static long heapPeakMb() {
        long b = 0;
        for (var pool : java.lang.management.ManagementFactory.getMemoryPoolMXBeans())
            if (pool.getType() == java.lang.management.MemoryType.HEAP && pool.getPeakUsage() != null) b += pool.getPeakUsage().getUsed();
        return b >> 20;
    }

    /** fallbackTrace != null: this is a replay with lookahead off after Forge's simulation code crashed on the first try. */
    static void runGame(String[] f, String deckDir, Map<String, Deck> decks, String fallbackTrace) throws Exception {
        int id = Integer.parseInt(f[0]);
        long seed = Long.parseLong(f[1]);
        int cap = Integer.parseInt(f[2]);
        int timeout = Integer.parseInt(f[3]);
        String colors = f[4];
        boolean playOut = f[5].equals("1");
        String[] ai = f[10].split(",");
        String[] sims = f.length > 11 ? f[11].split(",") : new String[]{"off", "off", "off", "off"};
        Set<String> keys = new HashSet<>();
        if (f.length > 12) for (String k : f[12].split("\\|")) if (!k.isBlank()) keys.add(k);

        MyRandom.setRandom(new Random(seed));
        SimFallbacks fb = new SimFallbacks();
        GameRules rules = new GameRules(GameType.Commander);
        rules.setAppliedVariants(EnumSet.of(GameType.Commander));
        rules.setGamesPerMatch(1);
        List<RegisteredPlayer> players = new ArrayList<>();
        List<PilotPolicy> policies = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            String file = f[6 + i];
            Deck d = decks.computeIfAbsent(file, k -> DeckSerializer.fromFile(new File(deckDir, k)));
            RegisteredPlayer rp = RegisteredPlayer.forCommander(d);
            String profile = ai[i].equals("Default") ? "" : ai[i];
            Set<AIOption> opts = sims[i].equals("full") ? EnumSet.of(AIOption.USE_FULL_SIMULATION)
                    : sims[i].equals("hybrid") ? EnumSet.of(AIOption.USE_HYBRID_SIMULATION) : EnumSet.noneOf(AIOption.class);
            String ps = System.getProperty("fishpond.pilotSeats", "all");    // seats that get the pilot (default all)
            PilotPolicy pol = ps.equals("all") || Arrays.asList(ps.split(",")).contains(String.valueOf(i + 1)) ? PilotPolicy.load(deckDir, file) : null;
            if (pol != null) policies.add(pol);
            SafeLobbyPlayerAi lp = new SafeLobbyPlayerAi("Ai(" + (i + 1) + ")-" + d.getName(), opts, fb, pol);
            lp.setAiProfile(profile.isEmpty() ? "Default" : profile);
            rp.setPlayer(lp);
            players.add(rp);
        }
        // per-deck pilot switches from each seat's policy.json, as ';'-separated commander names: '# commander: hold'
        // ("commander_hold": Forge patch 24 doesn't rush them out) and '# mill: self' ("self_mill": patch 39)
        System.setProperty("fishpond.commanderHold", policyNames(deckDir, f, "commander_hold"));
        System.setProperty("fishpond.selfMill", policyNames(deckDir, f, "self_mill"));
        Match match = new Match(rules, players, "Fishpond");
        Game game = match.createGame();
        game.setNoGUIUser();
        fb.game = game;
        // Forge's AI gives up on a decision after Game.AI_TIMEOUT seconds (5, no setter). A timeout makes the result depend on
        // machine load, so raise it (-Dfishpond.aiTimeout, default 120); any timeout left is counted by the log parser.
        try {
            java.lang.reflect.Field fld = Game.class.getDeclaredField("AI_TIMEOUT");
            fld.setAccessible(true);
            fld.setInt(game, Integer.getInteger("fishpond.aiTimeout", 120));
        } catch (Exception e) {
            out.println("#FP-WARN could not raise the AI timeout: " + e);
        }
        Player hero = null;
        for (Player p : game.getPlayers()) if (p.getName().startsWith("Ai(1)-")) hero = p;
        Map<String, String> simOn = new TreeMap<>();      // what the controllers actually run, per seat
        for (Player p : game.getPlayers()) {
            String seat = p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1"), m = "?";
            if (p.getController() instanceof PlayerControllerAi pc)
                m = pc.getAi().usesFullSimulation() ? "full" : pc.getAi().usesHybridSimulation() ? "hybrid" : "off";
            simOn.put(seat, m);
        }
        ThreatModel.register(game);   // patch 57's hooks answer for this game, not for the lookahead's copies of it
        Watcher w = new Watcher(game, hero, cap, colors, playOut);
        w.keys = keys;
        String wl = System.getProperty("fishpond.winLines");     // win-line audit (fishpond/win_lines.txt)
        if (wl != null && !wl.isEmpty()) w.lines = new LineTracker(game, new File(wl));
        if (!"false".equals(System.getProperty("fishpond.threatLog"))) w.threat = new ThreatModel(game);
        for (Player p : game.getPlayers())
            if (p.getController() instanceof PlayerControllerAi pc) {
                AiControllerSim m = pc.getAi().usesFullSimulation() ? AiControllerSim.FULL : pc.getAi().usesHybridSimulation() ? AiControllerSim.HYBRID : null;
                if (m != null) w.simmers.put(pc, m);
            }
        game.subscribeToEvents(w);

        for (var pool : java.lang.management.ManagementFactory.getMemoryPoolMXBeans())   // peak heap per game, for sizing -Xmx
            if (pool.getType() == java.lang.management.MemoryType.HEAP) pool.resetPeakUsage();
        long t0 = System.currentTimeMillis();
        ExecutorService ex = Executors.newSingleThreadExecutor();
        Future<?> fut = ex.submit(() -> match.startGame(game));
        try {
            fut.get(timeout, TimeUnit.SECONDS);
        } catch (TimeoutException e) {
            w.halt("timeout");
            fut.cancel(true);
        } catch (ExecutionException e) {
            w.halt("error: " + e.getCause());
            StringBuilder tr = new StringBuilder();
            for (StackTraceElement el : e.getCause().getStackTrace()) {
                if (tr.length() > 0) tr.append(" < ");
                tr.append(el.getClassName().replaceAll("^forge\\.", "")).append('.').append(el.getMethodName()).append(':').append(el.getLineNumber());
                if (tr.length() > 1500) break;
            }
            w.trace = tr.toString();
            if (w.trace.contains("ai.simulation")) {    // what the lookahead's game copy couldn't map
                Set<Player> in = new HashSet<>(game.getPlayers());
                Throwable cause = e.getCause();
                out.println("#FP-DIAG crash " + cause.getClass().getName() + ": " + cause.getMessage() + " | stack depth " + cause.getStackTrace().length);
                out.println("#FP-DIAG crash turn " + game.getPhaseHandler().getTurn() + " " + game.getPhaseHandler().getPhase()
                        + " | in game " + in.size() + "/" + game.getRegisteredPlayers().size()
                        + " | lost " + game.getRegisteredPlayers().stream().filter(p -> !in.contains(p)).map(Player::getName).toList());
                for (Card c : game.getCardsInGame())
                    if (!in.contains(c.getOwner()) || !in.contains(c.getController()))
                        out.println("#FP-DIAG orphan " + c + " zone " + c.getZone() + " owner " + c.getOwner().getName() + " controller " + c.getController().getName());
                var cb = game.getPhaseHandler().getCombat();
                if (cb != null) {
                    out.println("#FP-DIAG combat defenders " + cb.getDefenders() + " attackers " + cb.getAttackers() + " blockers " + cb.getAllBlockers());
                    List<Card> cs = new ArrayList<>(cb.getAttackers()); cs.addAll(cb.getAllBlockers());
                    for (var d : cb.getDefenders()) if (d instanceof Card c) cs.add(c);
                    for (Card a : cb.getAttackers()) if (cb.getDefenderByAttacker(a) instanceof Card c) cs.add(c);
                    for (Card c : cs) out.println("#FP-DIAG combat card " + c + " zone " + c.getZone() + " live " + (c.getZone() != null && game.findById(c.getId()) == c));
                }
            }
        }
        ex.shutdownNow();
        if (!game.isGameOver()) game.setGameOver(GameEndReason.Draw);
        long ms = System.currentTimeMillis() - t0;
        if (w.trace != null && w.trace.contains("ai.simulation") && fallbackTrace == null && !w.simmers.isEmpty()) {
            String[] g = f.clone();                     // Forge's lookahead crashed: replay this game (same seed) without it
            g[11] = "off,off,off,off";
            runGame(g, deckDir, decks, w.trace);
            return;
        }

        List<GameLogEntry> log = game.getGameLog().getLogEntries(null);
        Collections.reverse(log);
        for (GameLogEntry e : log) out.println(e);
        for (String s : w.snaps) out.println("#FP-SNAP " + s);
        for (String s : w.tutors) out.println("#FP-TUTOR " + s);
        w.flushAllHeld();
        for (String s : w.held) out.println("#FP-HELD " + s);
        for (PilotPolicy pol : policies) for (String s : pol.log) out.println("#FP-POLICY " + s);
        for (PilotPolicy pol : policies)    // patch 54's cast ordering: candidate answers by level (none, feeds, turns on, combo)
            out.println("#FP-CASTPLAN {\"deck\": " + js(pol.in.deck == null ? "" : pol.in.deck) + ", \"levels\": " + Arrays.toString(pol.castHits) + "}");
        if (w.lines != null) {
            List<Player> won = new ArrayList<>();
            for (Player p : game.getRegisteredPlayers()) if (p.getOutcome() != null && p.getOutcome().hasWon()) won.add(p);
            for (String s : w.lines.finish(w.stop == null && won.size() == 1 ? won.get(0) : null)) out.println("#FP-LINE " + s);
        }
        if (w.threat != null) for (String s : w.threat.log) out.println("#FP-THREAT " + s);
        Set<String> holds = ThreatModel.HOLDS.remove(game);     // patch 58: spells refused to keep mana up for an answer
        if (holds != null) for (String s : holds) out.println("#FP-HOLD " + s);
        StringBuilder end = new StringBuilder("{\"id\": " + id + ", \"seed\": " + seed + ", \"stop\": " + js(w.stop == null ? "natural" : w.stop)
                + ", \"ms\": " + ms + ", \"hero_turns\": " + w.heroTurns + ", \"global_turns\": " + w.globalTurns
                + (w.trace != null ? ", \"trace\": " + js(w.trace) : "")
                + (fallbackTrace != null ? ", \"sim_fallback\": " + js(fallbackTrace) : "")
                + ", \"sim_decision_fallbacks\": " + fb.n + (fb.first != null ? ", \"sim_decision_trace\": " + js(fb.first) : "")
                + ", \"sim_decision_log\": [" + String.join(", ", fb.log) + "]"
                + ", \"heap_peak_mb\": " + heapPeakMb() + ", \"heap_max_mb\": " + (Runtime.getRuntime().maxMemory() >> 20)
                + ", \"sim_paused_turns\": " + w.pausedTurns + ", \"sim_pauses\": " + w.pauses
                + ", \"sim_pause_why\": {" + String.join(", ", w.pauseWhy.entrySet().stream().map(x -> js(x.getKey()) + ": " + x.getValue()).toList()) + "}"
                + ", \"policy\": " + PilotPolicy.ON + ", \"policy_seats\": " + policies.size()
                + ", \"sim\": {" + String.join(", ", simOn.entrySet().stream().map(x -> "\"" + x.getKey() + "\": " + js(x.getValue())).toList()) + "}"
                + ", \"players\": {");
        String winner = null;
        int k = 0;
        for (Player p : game.getRegisteredPlayers()) {
            PlayerOutcome o = p.getOutcome();
            String seat = p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
            if (k++ > 0) end.append(", ");
            end.append("\"").append(seat).append("\": {\"name\": ").append(js(p.getName()))
               .append(", \"outcome\": ").append(js(o == null ? "none" : o.toString()))
               .append(", \"loss\": ").append(js(o == null || o.lossState == null ? "" : o.lossState.name()))
               .append(", \"alt\": ").append(js(o == null || o.altWinSourceName == null ? "" : o.altWinSourceName))
               .append(", \"spell\": ").append(js(o == null || o.loseConditionSpell == null ? "" : o.loseConditionSpell))
               .append(", \"life\": ").append(p.getLife()).append(", \"poison\": ").append(p.getPoisonCounters()).append("}");
            if (o != null && o.hasWon() && w.stop == null) winner = p.getName();
        }
        end.append("}, \"hand\": [");
        List<String> hand = new ArrayList<>();
        if (hero.hasLost()) hand = w.lastHand;
        else for (Card c : hero.getCardsIn(ZoneType.Hand)) hand.add(c.getName());
        for (int h = 0; h < hand.size(); h++) end.append(h > 0 ? ", " : "").append(js(hand.get(h)));
        end.append("], \"lib\": ").append(hero.hasLost() ? w.lastLib : hero.getCardsIn(ZoneType.Library).size()).append("}");
        out.println("#FP-END " + end);
        if (winner != null && !game.getOutcome().isDraw()) out.println("\nGame Result: Game " + id + " ended in " + ms + " ms. " + winner + " has won!");
        else out.println("\nGame Result: Game " + id + " ended in a Draw! Took " + ms + " ms.");
    }

    static String policyNames(String deckDir, String[] f, String key) throws java.io.IOException {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < 4; i++) {
            File pf = new File(deckDir, f[6 + i] + ".policy.json");
            if (!pf.exists()) continue;
            java.util.regex.Matcher m = java.util.regex.Pattern.compile("\"" + key + "\"\\s*:\\s*\\[(.*?)\\]", java.util.regex.Pattern.DOTALL)
                    .matcher(new String(java.nio.file.Files.readAllBytes(pf.toPath()), java.nio.charset.StandardCharsets.UTF_8));
            if (!m.find()) continue;
            java.util.regex.Matcher n = java.util.regex.Pattern.compile("\"([^\"]*)\"").matcher(m.group(1));
            while (n.find()) out.append(out.length() > 0 ? ";" : "").append(n.group(1));
        }
        return out.toString();
    }

    static String js(String s) {
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
            else b.append(c);
        }
        return b.append('"').toString();
    }

    public static class Watcher {
        final Game g; final Player hero; final int cap; final String colors; final boolean playOut;
        int heroTurns = 0, globalTurns = 0, afterDeath = 0;
        int discarded = 0, recurred = 0;                // the hero's cards: hand -> graveyard; graveyard -> hand/battlefield/stack
        List<String> lastHand = new ArrayList<>();      // the hero's hand at the latest phase it was alive (a dead player's cards leave)
        Set<String> keys = new HashSet<>();
        final List<String> tutors = new ArrayList<>();  // the hero's library searches and digs that put a card into hand or play
        int lastLib = 0;
        volatile String stop = null;
        String trace = null;                            // Java stack of a crash inside Forge, for the report
        // Forge's lookahead copies the game (ai.simulation.GameCopier), and in Forge 2.0.15 the copy crashes on a prepared card
        // (its "may cast a copy" permission crashes StaticAbilityContinuous), so lookahead is paused while one is on the
        // battlefield (docs/FORGE_ISSUES.md #1). The copier's other crashes are fixed in fishpond/forge_patches (#2).
        final Map<PlayerControllerAi, AiControllerSim> simmers = new HashMap<>();
        boolean paused = false;
        int pauses = 0, pausedTurns = 0;
        final Map<String, Integer> pauseWhy = new TreeMap<>();

        // A board of hundreds of permanents makes every lookahead copy slow: Lumra's Scute Swarm doubling itself and Xyris's
        // Snakes into Niv's per-creature lifegain each ran a game to the 30-minute limit (study150_20261015_p53 V05 g8,
        // V06 g4; p51 V06 g11). Lookahead pauses while the battlefield holds SIM_BOARD_CAP permanents or more and resumes
        // below 80% of it; decisions meanwhile use Forge's own rules, as during a prepared-card pause.
        static final int SIM_BOARD_CAP = Integer.getInteger("fishpond.simBoardCap", 150);

        String unsafeForSim() {
            int perms = 0;
            for (Player p : g.getPlayers())
                for (Card c : p.getCardsIn(ZoneType.Battlefield)) { if (c.isPrepared()) return "prepared"; perms++; }
            if (perms >= (paused && boardPause ? SIM_BOARD_CAP * 4 / 5 : SIM_BOARD_CAP)) { boardPause = true; return "board"; }
            boardPause = false;
            return null;
        }
        boolean boardPause = false;

        void checkSimSafe() {
            if (simmers.isEmpty()) return;
            String why = unsafeForSim();
            boolean any = why != null;
            if (any == paused) return;
            paused = any;
            if (any) { pauses++; pauseWhy.merge(why, 1, Integer::sum); }
            for (Map.Entry<PlayerControllerAi, AiControllerSim> e : simmers.entrySet())
                e.getKey().getAi().setUseSimulation(any ? null : e.getValue().option);
        }
        final List<String> snaps = new ArrayList<>();
        LineTracker lines;                              // win-line audit, null when off
        ThreatModel threat;                             // threat assessment log (phase 1), null when off
        final long t0 = System.currentTimeMillis();

        Watcher(Game g, Player hero, int cap, String colors, boolean playOut) {
            this.g = g; this.hero = hero; this.cap = cap; this.colors = colors; this.playOut = playOut;
        }

        synchronized void halt(String why) {
            if (stop != null) return;
            stop = why;
            if (!g.isGameOver()) g.setGameOver(GameEndReason.Draw);
        }

        @Subscribe public void onTurn(GameEventTurnBegan e) {
            globalTurns++;
            out.println("#FP-TURN " + globalTurns + " " + (System.currentTimeMillis() - t0) / 1000 + "s");   // progress, for watching slow games
            Player p = g.getPhaseHandler().getPlayerTurn();
            if (paused && p == hero) pausedTurns++;
            if (hero.hasLost()) {
                if (!playOut) halt("hero_lost");
                else if (++afterDeath > 4 * cap) halt("cap_after_death");
                return;
            }
            if (p == hero) heroTurns++;
            else if (heroTurns >= cap) halt("cap");
        }

        // Dead-card meter, every seat: a nonland card in hand that its owner could cast at the start of their first main
        // phase (mana, timing and targets; this turn's land drop not counted) and still held at their cleanup is "held"
        // that turn ("unspent" when its cost could still be paid at cleanup: the mana went unused, not to other plays).
        // Consecutive held turns of one card are one streak, printed as #FP-HELD after the game.
        final Map<Player, Map<Integer, Card>> castableAtMain = new HashMap<>();
        final Map<Player, Integer> seatTurns = new HashMap<>();
        final Map<Integer, int[]> heldRun = new HashMap<>();     // card id -> {first held turn, held turns, last held turn, turns with its mana unused}
        final Map<Integer, Player> heldOwner = new HashMap<>();
        final Map<Integer, Card> heldCard = new HashMap<>();
        final List<String> held = new ArrayList<>();

        static boolean castableNow(Card c, Player p) {
            if (c.isLand()) return false;
            for (SpellAbility sp : c.getSpells()) {
                try {
                    sp.setActivatingPlayer(p);
                    if (!sp.canPlay()) continue;
                    if (sp.usesTargeting() && !sp.getTargetRestrictions().hasCandidates(sp)) continue;
                    if (ComputerUtilMana.canPayManaCost(sp, p, xExtra(sp), false)) return true;
                } catch (Throwable t) { /* a card whose check throws counts as not castable */ }
            }
            return false;
        }

        /** An X spell counts only with mana for X = 1 (Walking Ballista for 0 isn't a play). */
        static int xExtra(SpellAbility sp) {
            return sp.getPayCosts() != null && sp.getPayCosts().hasXInAnyCostPart() ? 1 : 0;
        }

        void heldMain(Player p) {
            int t = seatTurns.merge(p, 1, Integer::sum);
            Map<Integer, Card> now = new HashMap<>();
            for (Card c : p.getCardsIn(ZoneType.Hand)) if (castableNow(c, p)) now.put(c.getId(), c);
            castableAtMain.put(p, now);
        }

        /** Its mana cost could still be paid now (timing aside): at cleanup, the seat left that much mana unused. */
        static boolean payableNow(Card c, Player p) {
            for (SpellAbility sp : c.getSpells()) {
                try {
                    sp.setActivatingPlayer(p);
                    if (ComputerUtilMana.canPayManaCost(sp, p, xExtra(sp), false)) return true;
                } catch (Throwable t) { /* counts as not payable */ }
            }
            return false;
        }

        void heldEnd(Player p) {
            Map<Integer, Card> now = castableAtMain.remove(p);
            if (now == null) return;
            int t = seatTurns.getOrDefault(p, 0);
            Set<Integer> inHand = new HashSet<>();
            for (Card c : p.getCardsIn(ZoneType.Hand)) inHand.add(c.getId());
            for (Map.Entry<Integer, Card> x : now.entrySet()) {
                if (!inHand.contains(x.getKey())) continue;
                int unspent = payableNow(x.getValue(), p) ? 1 : 0;
                int[] r = heldRun.get(x.getKey());
                if (r != null && r[2] == t - 1) { r[1]++; r[2] = t; r[3] += unspent; continue; }
                if (r != null) flushHeld(x.getKey());
                heldRun.put(x.getKey(), new int[] {t, 1, t, unspent});
                heldOwner.put(x.getKey(), p); heldCard.put(x.getKey(), x.getValue());
            }
            for (Integer id : new ArrayList<>(heldRun.keySet()))    // this seat's streaks that didn't continue this turn end here
                if (heldOwner.get(id) == p && heldRun.get(id)[2] != t) flushHeld(id);
        }

        void flushHeld(int id) {
            int[] r = heldRun.remove(id);
            Player p = heldOwner.remove(id);
            Card c = heldCard.remove(id);
            if (r == null || r[1] < 2) return;                      // single turns aren't printed (the meter counts 3+)
            String seat = p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
            held.add("{\"seat\": \"" + seat + "\", \"card\": " + js(c.getName()) + ", \"from\": " + r[0] + ", \"turns\": " + r[1] + ", \"unspent\": " + r[3]
                    + ", \"instant\": " + (c.isInstant() || c.hasKeyword(forge.game.keyword.Keyword.FLASH)) + ", \"cmc\": " + c.getCMC() + "}");
        }

        void flushAllHeld() { for (Integer id : new ArrayList<>(heldRun.keySet())) flushHeld(id); }

        /** Mana the player can make now without conditions: Forge's estimate minus abilities whose mana is restricted (Castle
         *  Garenbrig's six counts as none), with a choice of colors counted once (Command Tower's "Combo" made it two). */
        static int usableMana(Player p) {
            int total = p.getManaPool().totalMana();
            boolean free = false;
            for (Card src : p.getCardsIn(ZoneType.Battlefield)) {
                int best = 0;
                for (SpellAbility ma : src.getManaAbilities()) {
                    try {
                        ma.setActivatingPlayer(p);
                        AbilityManaPart mp = ma.getManaPart();
                        if (mp == null || !mp.getManaRestrictions().isEmpty() || !ma.canPlay()) continue;
                        int cost = ma.getPayCosts().getCostMana() != null ? ma.getPayCosts().getCostMana().convertAmount() : 0;
                        String prod = ma.getParamOrDefault("Produced", "");
                        int kinds = prod.startsWith("Combo") || prod.isEmpty() ? 1 : prod.split(" ").length;
                        int made = kinds * forge.game.ability.AbilityUtils.calculateAmount(src, ma.getParamOrDefault("Amount", "1"), ma) - cost;
                        if (cost == 0) free = true;
                        best = Math.max(best, made);
                    } catch (Throwable t) { /* skip an ability whose check throws */ }
                }
                total += best;
            }
            return free ? total : p.getManaPool().totalMana();      // only mana-costed sources: none can start (as Forge assumes)
        }

        @Subscribe public void onPhase(GameEventTurnPhase e) {
            Player turnOf = g.getPhaseHandler().getPlayerTurn();
            if (stop == null && turnOf != null && !turnOf.hasLost()) {
                if (e.phase() == PhaseType.MAIN1) {
                    heldMain(turnOf);
                    if (lines != null) lines.check(turnOf, seatTurns.getOrDefault(turnOf, 0));
                    if (threat != null) { try { threat.check(globalTurns, turnOf); } catch (RuntimeException ex) { /* logging only */ } }
                }
                else if (e.phase() == PhaseType.CLEANUP) heldEnd(turnOf);
            }
            if (stop == null && !hero.hasLost()) {
                lastHand = new ArrayList<>();
                for (Card c : hero.getCardsIn(ZoneType.Hand)) lastHand.add(c.getName());
                lastLib = hero.getCardsIn(ZoneType.Library).size();
            }
            if (stop != null || g.getPhaseHandler().getPlayerTurn() != hero || hero.hasLost()) return;
            if (e.phase() == PhaseType.MAIN1) snap("main");
            else if (e.phase() == PhaseType.CLEANUP) snap("end");
        }

        @Subscribe public void onZone(GameEventCardChangeZone e) {
            if (e.from() == null || e.to() == null || e.from().player() == null || !e.from().player().equals(hero.getView())) return;
            ZoneType f = e.from().zoneType(), t = e.to().zoneType();
            if (f == ZoneType.Library && (t == ZoneType.Hand || t == ZoneType.Battlefield)) tutor(e, t);
            if (f == ZoneType.Hand && t == ZoneType.Graveyard) discarded++;
            else if (f == ZoneType.Graveyard && (t == ZoneType.Hand || t == ZoneType.Battlefield || t == ZoneType.Stack)) recurred++;
        }

        /** A card left the hero's library for hand or play while a library search or dig resolved (draws don't count). */
        void tutor(GameEventCardChangeZone e, ZoneType to) {
            SpellAbility sa = g.getStack().isResolving() ? g.getStack().peekAbility() : null;
            String kind = null;
            for (SpellAbility s = sa; s != null && kind == null; s = s.getSubAbility()) {
                ApiType a = s.getApi();
                if ((a == ApiType.ChangeZone || a == ApiType.ChangeZoneAll) && s.getParam("Origin") != null && s.getParam("Origin").contains("Library")) kind = "search";
                else if (a == ApiType.Dig || a == ApiType.DigUntil) kind = "dig";
            }
            if (kind == null) return;
            Card c = g.findById(e.card().getId());
            String name = c != null ? c.getName() : e.card().getCurrentState().getName();
            int keysLeft = 0;
            for (Card x : hero.getCardsIn(ZoneType.Library)) if (keys.contains(x.getName())) keysLeft++;
            tutors.add("{\"t\": " + heroTurns + ", \"kind\": \"" + kind + "\", \"src\": " + js(sa.getHostCard() != null ? sa.getHostCard().getName() : "?")
                    + ", \"card\": " + js(name) + ", \"to\": \"" + to.name() + "\", \"land\": " + (c != null && c.isLand())
                    + ", \"key\": " + keys.contains(name) + ", \"keys_left\": " + keysLeft
                    + ", \"turn_of\": " + (g.getPhaseHandler().getPlayerTurn() == hero ? "\"you\"" : "\"opp\"") + "}");
        }

        // win-line audit: the plays each seat makes after its check (casts and stack abilities, land drops, attacks)
        @Subscribe public void onCast(GameEventSpellAbilityCast e) {
            if (lines == null || stop != null || e.si() == null || e.si().isTrigger() || e.sa() == null || e.sa().getHostCard() == null) return;
            Player p = e.si().getActivatingPlayer() == null ? null : g.getPlayer(e.si().getActivatingPlayer());
            if (p != null) lines.cast(p, g.findById(e.sa().getHostCard().getId()), e.sa().isSpell());
        }

        @Subscribe public void onLand(GameEventLandPlayed e) {
            if (lines == null || stop != null || e.player() == null || e.land() == null) return;
            lines.land(g.getPlayer(e.player()), g.findById(e.land().getId()));
        }

        @Subscribe public void onAttack(GameEventAttackersDeclared e) {
            if (lines == null || stop != null || e.player() == null) return;
            List<Card> atk = new ArrayList<>();
            for (var cv : e.attackersMap().values()) { Card c = g.findById(cv.getId()); if (c != null) atk.add(c); }
            lines.attack(g.getPlayer(e.player()), atk);
        }

        @Subscribe public void any(GameEvent e) {
            checkSimSafe();
            if (stop == null && !playOut && hero.hasLost()) halt("hero_lost");
        }

        void snap(String when) {
            StringBuilder b = new StringBuilder("{\"t\": " + heroTurns + ", \"at\": \"" + when + "\"");
            b.append(", \"life\": ").append(hero.getLife());
            b.append(", \"hand\": ").append(hero.getCardsIn(ZoneType.Hand).size());
            b.append(", \"lib\": ").append(hero.getCardsIn(ZoneType.Library).size());
            b.append(", \"gy\": ").append(hero.getCardsIn(ZoneType.Graveyard).size());
            b.append(", \"exile\": ").append(hero.getCardsIn(ZoneType.Exile).size());
            int creatures = 0, power = 0;
            for (Card c : hero.getCreaturesInPlay()) { creatures++; power += Math.max(0, c.getNetPower()); }
            b.append(", \"creatures\": ").append(creatures).append(", \"power\": ").append(power);
            b.append(", \"perms\": ").append(hero.getCardsIn(ZoneType.Battlefield).size());
            boolean cmdOut = false;
            for (Card c : hero.getCardsIn(ZoneType.Battlefield)) if (c.isCommander()) cmdOut = true;
            b.append(", \"cmd_out\": ").append(cmdOut);
            int tax = 0;
            for (Card c : hero.getCommanders()) tax += hero.getCommanderCast(c);
            b.append(", \"cmd_casts\": ").append(tax);
            b.append(", \"drawn\": ").append(hero.getNumDrawnThisTurn());
            b.append(", \"disc\": ").append(discarded).append(", \"recur\": ").append(recurred);
            b.append(", \"lands\": ").append(hero.getLandsInPlay().size());
            if (when.equals("main")) {
                // the hand's card names at main phase (for audits: what was held, e.g. ramp not cast)
                b.append(", \"hand_names\": [");
                boolean firstName = true;
                for (Card c : hero.getCardsIn(ZoneType.Hand)) {
                    b.append(firstName ? "" : ", ").append('"').append(c.getName().replace("\\", "\\\\").replace("\"", "\\\"")).append('"');
                    firstName = false;
                }
                b.append(']');
                int mana = 0;
                try { mana = ComputerUtilMana.getAvailableManaEstimate(hero, false); } catch (Throwable t) { mana = -1; }
                b.append(", \"mana\": ").append(mana);
                int usable = 0;
                try { usable = usableMana(hero); } catch (Throwable t) { usable = -1; }
                b.append(", \"usable\": ").append(usable);
                Set<String> col = new TreeSet<>();
                try {
                    for (Card c : ComputerUtilMana.getAvailableManaSources(hero, false)) {
                        if (!c.isInZone(ZoneType.Battlefield)) continue;
                        for (SpellAbility sa : c.getManaAbilities()) {
                            AbilityManaPart mp = sa.getManaPart();
                            if (mp == null) continue;
                            for (String x : COLORS) if (mp.canProduce(x, sa)) col.add(x);
                        }
                    }
                } catch (Throwable t) { col.add("?"); }
                b.append(", \"producible\": ").append(js(String.join("", col)));
                boolean all = true;
                for (char c : colors.toCharArray()) if (!col.contains(String.valueOf(c))) all = false;
                b.append(", \"colors\": ").append(all);
            }
            StringBuilder opp = new StringBuilder();
            for (Player p : g.getRegisteredPlayers()) {
                if (p == hero) continue;
                if (opp.length() > 0) opp.append(", ");
                String seat = p.getName().replaceAll("^Ai\\((\\d+)\\).*", "$1");
                opp.append("\"").append(seat).append("\": [").append(p.getLife()).append(", ").append(p.getPoisonCounters())
                   .append(", ").append(p.hasLost() ? 1 : 0).append(", ").append(p.getCreaturesInPlay().size()).append("]");
            }
            b.append(", \"opps\": {").append(opp).append("}}");
            snaps.add(b.toString());
        }
    }
}
