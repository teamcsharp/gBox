"""One supervisor, one play loop - and it picks the loop that will actually work.

Repeatedly during this session two or three play loops have been running at once and fighting each other for the keyboard. This exists to make that
impossible: it is the only thing that starts a play loop, it runs exactly one at a time, and it restarts one only if it dies.

It also **decides which loop to run** by testing the machine rather than assuming:

  1. wait for a live session (nothing to do otherwise);
  2. **test background input** - send one key while the game is unfocused and see whether the character moves. If it does, `play_background` is used,
     which needs no focus and never raises a window; if not, `play_when_focused` is used, which waits for the operator to give the game the screen;
  3. supervise: if the child exits, restart it after a pause; if the session ends, stop.

The decision is logged with the measurement that produced it, so the choice is auditable rather than mysterious.
"""
import math
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import map_exit as ME                                              # noqa: E402
import session as S                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\supervisor.log"
TMP = Path(r"C:\_tools\gBox\.tmp")


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def session_alive():
    try:
        ME.read_pos()
        return True
    except Exception:                                            # noqa: BLE001
        return False


def background_input_works():
    """Send one key while unfocused and see whether the character actually moves."""
    if G.game_has_focus():
        return None, "game already focused - cannot test"
    before = ME.read_pos()
    if before is None:
        return None, "no character"
    try:
        G.win_send_keys(G._pid(), [{"key": "up", "down": True}], polite=False)
        time.sleep(0.7)
        G.win_send_keys(G._pid(), [{"key": "up", "down": False}], polite=False)
    except Exception as exc:                                      # noqa: BLE001
        return False, f"send refused: {str(exc)[:60]}"
    time.sleep(0.2)
    after = ME.read_pos()
    moved = math.dist(before, after) if after else 0.0
    return moved > 1.0, f"character moved {moved:.2f} units while unfocused"


def main():
    log("=== supervisor starting")
    while True:
        if not session_alive():
            log("no live session - waiting for the game to be launched")
            time.sleep(10)
            continue
        works, detail = background_input_works()
        log(f"background input test: {works} ({detail})")
        script = "play_background.py" if works else "play_when_focused.py"
        log(f"starting {script}")
        child = subprocess.Popen([sys.executable, script, "3600"], cwd=str(TMP),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while child.poll() is None:
            time.sleep(5)
            if not session_alive():
                log("session ended - stopping the child")
                child.terminate()
                break
        log(f"{script} exited with {child.returncode}; restarting in 10 s")
        time.sleep(10)


if __name__ == "__main__":
    main()
