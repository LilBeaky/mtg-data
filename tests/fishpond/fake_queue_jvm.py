"""A stand-in for `ForgeRunner --queue` (tests/fishpond_units.py, the runner's pool): the same protocol on standard input and
output, no Forge. A game's plan line is 'ID<TAB>WHAT': ok | restart (finish, then stop like a timed-out JVM) | die (stop
mid-game the first time this game is played, finish it the second) | dead (stop mid-game every time) | slow (0.3 s)."""
import os, sys, time

print("Forge startup noise", flush=True)
print("#FP-READY", flush=True)
for line in sys.stdin:
    log, deck_dir, gid, what = line.rstrip("\n").split("\t")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"Turn: Turn 1 (game {gid})\n"); fh.flush()
        marker = log + f".died{gid}"
        if what == "dead" or (what == "die" and not os.path.exists(marker)):
            open(marker, "w").close()
            os._exit(1)
        if what == "slow": time.sleep(0.3)
        fh.write('#FP-END {"id": %s, "stop": "natural"}\nGame Result: Game %s ended in 5 ms. Ai(1)-X has won!\n' % (gid, gid))
    print(f"#FP-DONE {gid}" + (" restart" if what == "restart" else ""), flush=True)
    if what == "restart": sys.exit(3)
