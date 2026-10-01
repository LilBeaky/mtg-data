// Fishpond harness: plays a list of seeded Commander games on Forge in one JVM and prints each game's log in the
// stock `sim` format, plus Fishpond's own lines (#FP-...) with per-turn snapshots and how the game was stopped.
//
// Compiled at runtime by fishpond/runner.py against the cached Forge jar (javac -cp <jar>); never vendored.
// Modelled on forge.view.SimulateMatch. Differences: every game is its own Match with its own RNG seed (any game can be
// replayed alone), the game stops when the hero (seat 1) has lost and no real opponent is left to finish the pod, or at
// the end of the hero's turn CAP, and snapshots are taken at the hero's first main phase and cleanup step.
//
// usage: java -cp <jar>:<dir> ForgeRunner DECK_DIR PLAN_FILE    (cwd = the Forge install: it reads res/ from there)
// PLAN_FILE lines, tab-separated: id seed cap timeout_s colors play_out deck1 deck2 deck3 deck4 ai1,ai2,ai3,ai4
//   colors = the hero's color identity (e.g. WUG); play_out = 1 to keep playing after the hero dies (real opponents left)

import com.google.common.eventbus.Subscribe;
import forge.GuiDesktop;
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
import forge.game.event.GameEventTurnBegan;
import forge.game.event.GameEventTurnPhase;
import forge.game.phase.PhaseType;
import forge.game.player.Player;
import forge.game.player.PlayerOutcome;
import forge.game.player.RegisteredPlayer;
import forge.game.spellability.AbilityManaPart;
import forge.game.spellability.SpellAbility;
import forge.game.zone.ZoneType;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.player.GamePlayerUtil;
import forge.util.MyRandom;

import java.io.File;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.*;

public class ForgeRunner {
    static final String[] COLORS = {"W", "U", "B", "R", "G"};
    static PrintStream out;

    public static void main(String[] args) throws Exception {
        out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8");
        System.setProperty("java.awt.headless", "true");
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        String deckDir = args[0];
        Map<String, Deck> decks = new HashMap<>();
        out.println("#FP-READY");
        for (String line : Files.readAllLines(Paths.get(args[1]), StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("#")) continue;
            String[] f = line.split("\t");
            try {
                runGame(f, deckDir, decks);
            } catch (Throwable t) {
                out.println("#FP-ERROR {\"id\": " + f[0] + ", \"error\": " + js(String.valueOf(t)) + "}");
                out.println("\nGame Result: Game " + f[0] + " ended in a Draw! Took 0 ms.");
            }
            out.flush();
        }
        out.flush();
        System.exit(0);
    }

    static void runGame(String[] f, String deckDir, Map<String, Deck> decks) throws Exception {
        int id = Integer.parseInt(f[0]);
        long seed = Long.parseLong(f[1]);
        int cap = Integer.parseInt(f[2]);
        int timeout = Integer.parseInt(f[3]);
        String colors = f[4];
        boolean playOut = f[5].equals("1");
        String[] ai = f[10].split(",");

        MyRandom.setRandom(new Random(seed));
        GameRules rules = new GameRules(GameType.Commander);
        rules.setAppliedVariants(EnumSet.of(GameType.Commander));
        rules.setGamesPerMatch(1);
        List<RegisteredPlayer> players = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            String file = f[6 + i];
            Deck d = decks.computeIfAbsent(file, k -> DeckSerializer.fromFile(new File(deckDir, k)));
            RegisteredPlayer rp = RegisteredPlayer.forCommander(d);
            String profile = ai[i].equals("Default") ? "" : ai[i];
            rp.setPlayer(GamePlayerUtil.createAiPlayer("Ai(" + (i + 1) + ")-" + d.getName(), i, profile));
            players.add(rp);
        }
        Match match = new Match(rules, players, "Fishpond");
        Game game = match.createGame();
        game.setNoGUIUser();
        Player hero = null;
        for (Player p : game.getPlayers()) if (p.getName().startsWith("Ai(1)-")) hero = p;
        Watcher w = new Watcher(game, hero, cap, colors, playOut);
        game.subscribeToEvents(w);

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
        }
        ex.shutdownNow();
        if (!game.isGameOver()) game.setGameOver(GameEndReason.Draw);
        long ms = System.currentTimeMillis() - t0;

        List<GameLogEntry> log = game.getGameLog().getLogEntries(null);
        Collections.reverse(log);
        for (GameLogEntry e : log) out.println(e);
        for (String s : w.snaps) out.println("#FP-SNAP " + s);
        StringBuilder end = new StringBuilder("{\"id\": " + id + ", \"seed\": " + seed + ", \"stop\": " + js(w.stop == null ? "natural" : w.stop)
                + ", \"ms\": " + ms + ", \"hero_turns\": " + w.heroTurns + ", \"global_turns\": " + w.globalTurns + ", \"players\": {");
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
        end.append("}}");
        out.println("#FP-END " + end);
        if (winner != null && !game.getOutcome().isDraw()) out.println("\nGame Result: Game " + id + " ended in " + ms + " ms. " + winner + " has won!");
        else out.println("\nGame Result: Game " + id + " ended in a Draw! Took " + ms + " ms.");
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
        volatile String stop = null;
        final List<String> snaps = new ArrayList<>();

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
            Player p = g.getPhaseHandler().getPlayerTurn();
            if (hero.hasLost()) {
                if (!playOut) halt("hero_lost");
                else if (++afterDeath > 4 * cap) halt("cap_after_death");
                return;
            }
            if (p == hero) heroTurns++;
            else if (heroTurns >= cap) halt("cap");
        }

        @Subscribe public void onPhase(GameEventTurnPhase e) {
            if (stop != null || g.getPhaseHandler().getPlayerTurn() != hero || hero.hasLost()) return;
            if (e.phase() == PhaseType.MAIN1) snap("main");
            else if (e.phase() == PhaseType.CLEANUP) snap("end");
        }

        @Subscribe public void any(GameEvent e) {
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
            if (when.equals("main")) {
                b.append(", \"lands\": ").append(hero.getLandsInPlay().size());
                int mana = 0;
                try { mana = ComputerUtilMana.getAvailableManaEstimate(hero, false); } catch (Throwable t) { mana = -1; }
                b.append(", \"mana\": ").append(mana);
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
