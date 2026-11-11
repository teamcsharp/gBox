"""CP4: the pad-driven boot walk - the agent holds the game's controller, so no focus and no key injection are involved.

Measured (round 103): `vpad_win.VGamepad()` creates a ViGEm pad on **XInput slot 0**, which is exactly the slot the launch's
keyboard-fallback INI binds (`Device = XInput/0/Gamepad`); `probe_pads()` shows slot 0 reporting zeros while idle - the
"phantom slot" the code warns about - and `apply()` makes it report real values (a press showed 4096). So a process that holds
such a pad can act as the game's controller:

    pad = vpad_win.VGamepad(); pad.apply([{"key": "start", "frames": 2}])

`apply` is focus-independent by design ("Player 1 on the virtual pad: focus-independent, so no polite/focus gating"), which is
the one input path this machine has that works without the window being foreground.

This driver: creates the pad, waits for a session, then runs `pso_boot_walk.walk` with presses fed through the pad and
checkpoints read from RAM through the plane.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader                      # noqa: E402
from gbox import pso_boot_walk as W, vpad_win           # noqa: E402

LOG = Path(r"C:\_tools\gBox\.tmp\cp4_padwalk.log")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def main():
    if not vpad_win.available():
        log("ViGEm is not available here")
        return 1
    pad = vpad_win.VGamepad()
    log(f"virtual pad created on XInput slot {pad.slot}")

    plane = Plane()
    session = None
    for _ in range(48):
        session = plane.running()
        if session:
            break
        time.sleep(5)
    if not session:
        log("no session within 4 minutes")
        pad.close()
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    log(f"session {sid}; state {json.dumps(W.state(reader))}")

    def press(keys):
        # `apply` holds a key unless the same batch also releases it, so a tap is a down+up pair per key
        # (vpad_win.apply renders the press, waits TAP_S, then renders the release).
        rows = []
        for key in keys:
            rows += [{"key": key, "down": True}, {"key": key, "down": False}]
        log(f"  pad tap {keys} -> {pad.apply(rows)}")

    try:
        result = W.walk(lambda: W.state(reader), press, settle=2.0, log=log, start_at="press_start")
        log(f"walk result: {json.dumps({k: result[k] for k in ('ok', 'arrived', 'why')})}")
    except Exception as exc:                            # noqa: BLE001
        log(f"walk raised {type(exc).__name__}: {exc}")
    log(f"final state {json.dumps(W.state(reader))}")
    pad.close()
    log("virtual pad released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
