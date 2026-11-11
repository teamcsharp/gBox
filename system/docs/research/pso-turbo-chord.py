"""The operator's turbo chord: hold R and press D-pad forward to speed the emulator up, D-pad back to return to normal.

R1 on a GameCube pad is the right analog trigger; on XInput it reads as `rt`. The chord is watched on the physical controller (the
`pad_bind` alive slot, so a ghost at slot 0 is never mistaken for the operator) and applied through the plane's proven
`session_op fast_forward` on the running PSO session.

    python pso_turbo_chord.py --session <sid> [--rt 0.35] [--level 1.5]

Dolphin's fast-forward is a *binary* turbo whose rate is Dolphin's own FF speed setting, not a per-press multiplier; the chord therefore
reports the level it represents and the watcher logs both the request and the plane's answer.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\imitate-wt\system")

from gbox import pad_bind, xinput                                 # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
LOG = Path(r"D:\gBox\pso-ds\turbo.log")
DEBOUNCE_S = 0.35


def call(path, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def fast_forward(session: str, on: bool) -> dict:
    started = time.time()
    job = call("/api/jobs", "POST", {"tool": "session_op",
                                    "input": {"session_id": session, "op": "fast_forward", "args": {"on": on}}})
    while time.time() - started < 10:
        time.sleep(0.25)
        state = call("/api/jobs/" + job["id"])
        if state.get("state") not in ("queued", "running"):
            return {"state": state.get("state"), "result": (state.get("output") or {}).get("result"),
                    "error": str(state.get("error"))[:160]}
    call(f"/api/jobs/{job['id']}/cancel", "POST")
    return {"state": "timeout"}


def pads():
    fn = xinput.load()
    out = {}
    for slot in range(4):
        state = xinput.read(fn, slot)
        if state is not None:
            g = state.gamepad
            out[slot] = (g.buttons, g.lt, g.rt, g.lx, g.ly, g.rx, g.ry)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--rt", type=float, default=0.35, help="right-trigger threshold for R1")
    ap.add_argument("--level", type=float, default=1.5, help="the factor the chord represents")
    ap.add_argument("--seconds", type=float, default=6 * 3600)
    args = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    fast_forward(args.session, False)                              # start at normal speed
    print(f"turbo chord armed: R1 + D-pad forward = {args.level}x, R1 + D-pad back = 1x", flush=True)
    last_action, turbo, slot = 0.0, False, None
    start = time.time()
    while time.time() - start < args.seconds:
        state = pads()
        alive = pad_bind.live_slots(state)
        slot = alive[0] if alive else slot
        if slot is None or slot not in state:
            time.sleep(0.05)
            continue
        buttons, _lt, rt, _lx, _ly, _rx, _ry = state[slot]
        # R1 is the GameCube R shoulder: Dolphin's GCPad1 binds Buttons/Z = Shoulder R, i.e. XInput's right bumper (0x0200).
        # The analog right trigger is accepted too, so either physical control works.
        r_held = bool(buttons & 0x0200) or (rt / 255.0) >= args.rt
        forward = bool(buttons & 0x0001)
        back = bool(buttons & 0x0002)
        now = time.time()
        if r_held and forward and not turbo and now - last_action > DEBOUNCE_S:
            answer = fast_forward(args.session, True)
            turbo, last_action = True, now
            line = {"at": time.strftime("%H:%M:%S"), "chord": "r+forward", "level": args.level, "turbo": True, **answer}
            print(json.dumps(line)[:260], flush=True)
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        elif r_held and back and turbo and now - last_action > DEBOUNCE_S:
            answer = fast_forward(args.session, False)
            turbo, last_action = False, now
            line = {"at": time.strftime("%H:%M:%S"), "chord": "r+back", "level": 1.0, "turbo": False, **answer}
            print(json.dumps(line)[:260], flush=True)
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        time.sleep(1 / 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
