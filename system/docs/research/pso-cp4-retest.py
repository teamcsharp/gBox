"""CP4 round 98: the discriminating input retest - wait for the title menu, then try both press paths.

Round 96 pressed within seconds of boot, while `mode == 0` (the attract loop that plays the opening movie, during which PSO
ignores START), so its "no reaction" was not conclusive. This script separates the two questions:

  1. does the game reach `mode == 1` **on its own** (the movie ending)? - that also tells us the round-65 "press worked"
     reading was probably the movie ending;
  2. once at `mode == 1`, does a press land (a) with a focus attempt, and (b) with a plain unfocused SendInput?

Every step is logged with a timestamp so the sequence itself is evidence.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                      # noqa: E402
from gbox import pso_boot_walk as W                     # noqa: E402
import pso_boot_local as L                              # noqa: E402

LOG = Path(r"C:\_tools\gBox\.tmp\cp4_retest.log")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def press(keys, *, focus: bool, pid: int):
    if focus:
        L.win_bring_to_front(pid)
        time.sleep(0.3)
    for name in keys:
        scan, ext = L.scancode(name)
        if scan:
            L.send(scan, ext)
    time.sleep(0.15)
    for name in keys:
        scan, ext = L.scancode(name)
        if scan:
            L.release(scan, ext)
    log(f"  pressed {keys} (focus attempt={focus}, foreground={L.foreground_is(pid)})")


def main():
    plane = Plane()
    session = None
    for _ in range(36):
        session = plane.running()
        if session:
            break
        time.sleep(5)
    if not session:
        log("no session within 3 minutes")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    pid = L.emulator_pid()
    log(f"session {sid}, emulator pid {pid}")

    # phase 1: does the game reach the title menu on its own?
    reached = False
    start = time.time()
    while time.time() - start < 180:
        state = W.state(reader)
        if state.get("mode") != 0:
            log(f"mode reached {state.get('mode')} on its own after {int(time.time() - start)}s: {json.dumps(state)}")
            reached = True
            break
        time.sleep(3)
    if not reached:
        log("still mode 0 after 180 s: the attract loop did not end on its own")
        return 2

    # phase 2: a press with the focus attempt
    before = W.state(reader)
    press(("start",), focus=True, pid=pid)
    time.sleep(2.5)
    after = W.state(reader)
    log(f"after focused press: before={json.dumps(before)} after={json.dumps(after)}")
    if after != before:
        log("RESULT: a focused press landed")
        return 0

    # phase 3: the same press with no focus attempt at all
    press(("start",), focus=False, pid=pid)
    time.sleep(2.5)
    after2 = W.state(reader)
    log(f"after unfocused press: {json.dumps(after2)}")
    if after2 != after:
        log("RESULT: an unfocused press landed (Dolphin polls the keyboard in the background)")
        return 0
    log("RESULT: neither press changed the state at mode==1 - the input path really does not deliver")
    return 3


if __name__ == "__main__":
    sys.exit(main())
