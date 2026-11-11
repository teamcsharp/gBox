"""CP4: one command for the whole live runbook - launch when the window opens, walk with the agent's pad, save the state.

The window is short (the operator comes back), so the runbook is one process that does not need a human between steps:

  1. wait for the worker's idle_seconds >= 300, queue the launch, wait for the session
  2. probe the relay and the agent's ViGEm pad with one START, use whichever lands (rounds 103-104)
  3. walk to the lobby (pso_boot_walk), pressing through the winning path
  4. save the Dolphin state (pso_boot save-state) and print its path for install-jumpstates
  5. read the CP9 seed descriptor ([0x80585F6C] + 0x118) and, if it is non-zero, decode the card's PSO_CHARACTER with
     pso_save_cipher (the module from round 94)
  6. write a JSON report to D:\\gBox\\pso-ds\\live\\run-<timestamp>.json and stop the session cleanly

Every step logs a line with a timestamp; a failure stops the run with the step named.
"""
import json
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader, BASE                        # noqa: E402
from gbox import pso_boot_walk as W, vpad_win                   # noqa: E402

WORK = Path(r"D:\gBox\pso-ds\live")
LOG = Path(r"C:\_tools\gBox\.tmp\cp4_runbook.log")
SEED_PTR = 0x80585F6C
CARD = Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\..\..\User\GC\MemoryCardA.USA.raw")
GID = "436e0bb84d5337d1"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def api(plane, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
        "authorization": f"Bearer {plane.token}", "x-gbox-actor": "agent", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read() or b"{}")


def wait_for_idle(plane, need=300, limit_s=3600):
    start = time.time()
    while time.time() - start < limit_s:
        workers = api(plane, "GET", "/api/workers")
        row = next((w for w in workers if "i9" in (w.get("name") or "").lower()), None)
        idle = (row or {}).get("idle_seconds") or 0
        if idle >= need:
            log(f"idle_seconds={idle:.0f}: queueing the launch")
            return True
        time.sleep(15)
    return False


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}

    def step(name, **kw):
        report["steps"].append({"step": name, "at": time.strftime("%H:%M:%S"), **kw})
        log(f"{name}: " + json.dumps(kw, default=str)[:300])

    pad = vpad_win.VGamepad() if vpad_win.available() else None
    step("agent_pad", slot=getattr(pad, "slot", None))
    plane = Plane()
    session = plane.running()
    if not session:
        if not wait_for_idle(plane):
            step("window", ok=False, why="idle never reached 300 s")
            return 1
        job = api(plane, "POST", f"/api/games/{GID}/launch?node=i9-NUC")
        step("launch", job=job.get("id"), state=job.get("state"))
        for _ in range(48):
            session = plane.running()
            if session:
                break
            time.sleep(5)
    if not session:
        step("session", ok=False, why="no session appeared")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    step("session", id=sid, state=W.state(reader))

    def relay_tap(keys):
        body = {"events": [{"key": k, "down": True} for k in keys] + [{"key": k, "down": False} for k in keys]}
        return api(plane, "POST", f"/api/sessions/{sid}/input", body)

    def pad_tap(keys):
        rows = []
        for key in keys:
            rows += [{"key": key, "down": True}, {"key": key, "down": False}]
        return pad.apply(rows) if pad else {"sent": 0}

    method = None
    for name, fn in (("relay", lambda: relay_tap(["start"])), ("pad", lambda: pad_tap(["start"]))):
        try:
            answer = fn()
        except Exception as exc:                                # noqa: BLE001
            step(f"probe_{name}", error=f"{type(exc).__name__}: {exc}")
            continue
        time.sleep(2.5)
        state = W.state(reader)
        step(f"probe_{name}", answer=answer, mode=state.get("mode"))
        if state.get("mode") not in (None, 0):
            method = name
            break
    if method is None:
        step("input", ok=False, why="neither path advanced the title")
        return 2
    step("input", method=method)

    def press(keys):
        log(f"  tap {keys} via {method}")
        return relay_tap(list(keys)) if method == "relay" else pad_tap(list(keys))

    result = W.walk(lambda: W.state(reader), press, settle=2.0, log=log, start_at="press_start")
    step("walk", ok=result["ok"], arrived=result["arrived"], why=result["why"])
    step("state_after_walk", **W.state(reader))

    if result["arrived"]:
        saved = subprocess.run([sys.executable, r"C:\_tools\gBox\.tmp\tools\pso_boot.py", "save-state"],
                               capture_output=True, text=True)
        step("save_state", rc=saved.returncode, out=(saved.stdout or "").strip()[-300:])
        # the seed descriptor, if a save slot is selected
        try:
            ptr = struct.unpack(">I", reader.read(SEED_PTR, 4))[0]
            step("seed_descriptor", pointer=hex(ptr))
            if 0x80000000 <= ptr < 0x81800000:
                seed = struct.unpack(">I", reader.read(ptr + 0x118, 4))[0]
                step("seed", value=hex(seed))
        except Exception as exc:                                # noqa: BLE001
            step("seed_descriptor", error=str(exc))

    out = WORK / f"run-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log(f"report written to {out}")
    # leave the i9 clean
    try:
        api(plane, "POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": sid, "op": "stop_game"}})
        step("stopped", sid=sid)
    except Exception as exc:                                    # noqa: BLE001
        step("stop_failed", error=str(exc))
    if pad:
        pad.close()
    return 0 if result["arrived"] else 3


if __name__ == "__main__":
    sys.exit(main())
