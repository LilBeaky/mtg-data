// Fishpond puzzle runner: loads a board state (Forge's GameState format) into a 2-player AI-vs-AI game, lets the AI play
// for a few turns, and prints the game log. fishpond/puzzles.py checks the log against the puzzle's expect/forbid lines.
// Used to test the AI on one mechanic at a time (docs/FORGE_PLAN.md, "Pilot policy", Part 2).
//
// usage: java -cp <jar>:<dir> PuzzleRunner STATE_FILE TURNS SEED   (cwd = the Forge install)
// STATE_FILE: GameState lines (p0... = seat 1, the player under test; p1... = seat 2), e.g. p0battlefield=Astral Slide;Plains

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.concurrent.*;

import com.google.common.eventbus.Subscribe;
import forge.GuiDesktop;
import forge.deck.Deck;
import forge.game.*;
import forge.game.event.GameEventTurnBegan;
import forge.game.player.RegisteredPlayer;
import forge.gui.GuiBase;
import forge.model.FModel;
import forge.util.MyRandom;

public class PuzzleRunner {
    /** GameState.applyToGame hands the work to another thread, which races the game loop; the start hook already runs on
     *  the game thread, so apply directly. */
    static final class State extends GameState { void applyHere(Game g) { applyGameOnThread(g); } }

    public static void main(String[] args) throws Exception {
        List<String> lines = Files.readAllLines(new File(args[0]).toPath(), StandardCharsets.UTF_8);
        int turns = Integer.parseInt(args[1]);
        long seed = Long.parseLong(args[2]);
        ForgeRunner.out = new java.io.PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, "UTF-8");
        GuiBase.setInterface(new GuiDesktop());
        FModel.initialize(null, null);
        MyRandom.setRandom(new Random(seed));

        GameRules rules = new GameRules(GameType.Constructed);
        rules.setGamesPerMatch(1);
        List<RegisteredPlayer> players = new ArrayList<>();
        ForgeRunner.SimFallbacks fb = new ForgeRunner.SimFallbacks();
        for (int i = 0; i < 2; i++) {
            Deck d = new Deck("Puzzle" + (i + 1));
            d.getMain().add("Wastes", 40);
            RegisteredPlayer rp = new RegisteredPlayer(d);
            ForgeRunner.SafeLobbyPlayerAi lp = new ForgeRunner.SafeLobbyPlayerAi("Ai(" + (i + 1) + ")-P" + (i + 1), EnumSet.noneOf(forge.ai.AIOption.class), fb, null);
            rp.setPlayer(lp);
            players.add(rp);
        }
        Match match = new Match(rules, players, "Puzzle");
        Game game = match.createGame();
        game.setNoGUIUser();
        fb.game = game;
        State state = new State();
        state.parse(lines);
        final int[] started = {0};
        game.subscribeToEvents(new Object() {
            @Subscribe public void onTurn(GameEventTurnBegan e) {
                if (++started[0] > turns + 1 && !game.isGameOver()) game.setGameOver(GameEndReason.Draw);
            }
        });
        ExecutorService ex = Executors.newSingleThreadExecutor();
        // Forge's own puzzle hook: the state is applied once the game is set up, before the first turn
        Future<?> fut = ex.submit(() -> match.startGame(game, () -> state.applyHere(game)));
        try { fut.get(300, TimeUnit.SECONDS); }
        catch (TimeoutException e) { if (!game.isGameOver()) game.setGameOver(GameEndReason.Draw); fut.cancel(true); }
        catch (ExecutionException e) {
            StringBuilder tr = new StringBuilder();
            for (StackTraceElement el : e.getCause().getStackTrace()) { tr.append(" < ").append(el.getClassName()).append('.').append(el.getMethodName()).append(':').append(el.getLineNumber()); if (tr.length() > 1500) break; }
            System.out.println("#FP-PUZZLE error " + e.getCause() + tr);
        }
        ex.shutdownNow();
        List<GameLogEntry> log = game.getGameLog().getLogEntries(null);
        Collections.reverse(log);
        for (GameLogEntry e : log) System.out.println(e);
        for (var p : game.getRegisteredPlayers())
            System.out.println("#FP-PUZZLE end " + p.getName() + " life " + p.getLife() + " hand " + p.getCardsIn(forge.game.zone.ZoneType.Hand).size()
                    + " battlefield " + p.getCardsIn(forge.game.zone.ZoneType.Battlefield).stream().map(c -> c.getName()).toList());
        System.exit(0);
    }
}
