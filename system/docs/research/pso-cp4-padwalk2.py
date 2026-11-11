"""CP4: the boot walk with an auto-selected press path - the worker's pad (relay) or the agent's own pad.

Two input paths exist on this machine and which one works depends on the launch:

* the worker created a ViGEm pad (`_setup_vpad` succeeded): `send_input` applies events to **that** pad
  ("Player 1 on the virtual pad: focus-independent"), so the HTTP relay works;
* it did not (the documented i9 fallback): `GCPad1` binds `XInput/0/Gamepad`, which is exactly the slot a pad created by
  **this** process lands on, so `vpad_win.VGamepad().apply(...)` works.

This driver creates its own pad first (harmless if the launch binds slot 0), then probes both paths with a single START press
and uses whichever changes the game state. `mode` leaving 0 is the probe.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader, BASE                # noqa: E402
from gbox import pso_boot_walk as W, vpad_win           # noqa: E402

LOG = Path(r"C:\_tools\gBox\.tmp\cp4_padwalk2.log")
INI = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def bound_slot() -> str:
    try:
        text = INI.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "?"
    for line in text.splitlines():
        if line.strip().startswith("Device ="):
            return line.strip()
    return "?"


def relay_press(plane, sid, keys):
    body = json.dumps({"events": [{"key": k, "down": True} for k in keys]
                       + [{"key": k, "down": False} for k in keys]}).encode()
    req = urllib.request.Request(f"{BASE}/api/sessions/{sid}/input", data=body, headers={
        "authorization": f"Bearer {plane.token}", "x-gbox-actor": "agent", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode()


def main():
    pad = vpad_win.VGamepad() if vpad_win.available() else None
    log(f"agent pad: {'slot %s' % pad.slot if pad else 'unavailable'}")
    plane = Plane()
    session = None
    for _ in range(48):
        session = plane.running()
        if session:
            break
        time.sleep(5)
    if not session:
        log("no session within 4 minutes")
        if pad:
            pad.close()
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    log(f"session {sid}; GCPad1 {bound_slot()}; state {json.dumps(W.state(reader))}")

    def tap_pad(keys):
        rows = []
        for key in keys:
            rows += [{"key": key, "down": True}, {"key": key, "down": False}]
        return pad.apply(rows) if pad else {"sent": 0}

    # probe: one START through each path, whichever changes `mode` is the one to use
    method = None
    for name, press in (("relay", lambda: relay_press(plane, sid, ["start"])),
                        ("pad", lambda: tap_pad(["start"]))):
        try:
            log(f"probe {name}: {press()}")
        except Exception as exc:                        # noqa: BLE001
            log(f"probe {name} raised {type(exc).__name__}: {exc}")
            continue
        time.sleep(2.5)
        state = W.state(reader)
        log(f"  after {name}: mode={state.get('mode')} floor={state.get('floor')}")
        if state.get("mode") not in (None, 0):
            method = name
            break
    if method is None:
        log("neither path advanced the game; stopping before the walk")
        if pad:
            pad.close()
        return 2
    log(f"using the {method} path for the walk")

    def press(keys):
        if method == "relay":
            log(f"  relay tap {keys} -> {relay_press(plane, sid, list(keys))}")
        else:
            log(f"  pad tap {keys} -> {tap_pad(list(keys))}")

    try:
        result = W.walk(lambda: W.state(reader), press, settle=2.0, log=log, start_at="press_start")
        log(f"walk result: {json.dumps({k: result[k] for k in ('ok', 'arrived', 'why')})}")
    except Exception as exc:                            # noqa: BLE001
        log(f"walk raised {type(exc).__name__}: {exc}")
    log(f"final state {json.dumps(W.state(reader))}")
    if pad:
        pad.close()
    log("agent pad released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
