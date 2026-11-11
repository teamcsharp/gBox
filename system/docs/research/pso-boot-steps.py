"""Boot the game from the title screen into a loaded character, one step at a time, checking the screen after each input.

The menu needs the STICK (not the D-pad) and each step must be confirmed before the next, or a double press backs out to the title. This
drives: START -> stick down to OFFLINE GAME -> A -> (dialogs) A -> character select -> A/START to enter Pioneer 2, capturing after every
step so the caller can inspect the actual screen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_game as CG                                          # noqa: E402
import game_input as G                                             # noqa: E402

DEMO = Path(r"D:\gBox\pso-ds\demo")


def tap(key, hold=0.28, settle=1.6):
    G.send([{"key": key, "down": True}])
    time.sleep(hold)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def shot(tag):
    CG.main()
    newest = sorted(DEMO.glob("*-game.png"), key=lambda p: p.stat().st_mtime)[-1]
    target = DEMO / f"boot-{tag}.png"
    target.write_bytes(newest.read_bytes())
    print(f"  [{tag}] {target.name} ({target.stat().st_size} bytes)", flush=True)
    return target


if __name__ == "__main__":
    steps = sys.argv[1:] or ["start", "down", "a"]
    for index, step in enumerate(steps):
        print(f"step {index}: {step}", flush=True)
        if step in ("capture", ""):
            shot(f"{index}-look")
            continue
        tap(step)
        shot(f"{index}-{step}")
    print("done")
