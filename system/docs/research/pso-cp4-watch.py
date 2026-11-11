"""CP4: a standing watcher - when an AGENT-OWNED session appears, walk it with the pad and record everything.

The queued launch job (a43d86814ee34c36) fires whenever the operator is away for five minutes with CPU under 70. This watcher
polls for the session that job creates and then does the whole sequence, so the walk happens the moment the window opens rather
than only when a human (or the previous runbook) happens to be polling:

  1. wait for a session whose `agent_owned` is true (never touch the operator's own session)
  2. probe the relay and the agent pad with one START, use whichever changes `mode`
  3. walk to the lobby, save the Dolphin state, read the CP9 seed descriptor
  4. write a report and stop the session (leaving the i9 clean)

Every step is timestamped into C:\\_tools\\gBox\\.tmp\\cp4_watch.log.
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

LOG = Path(r"C:\_tools\gBox\.tmp\cp4_watch.log")
REPORT_DIR = Path(r"D:\gBox\pso-ds\live")
SEED_PTR = 0x80585F6C
WATCH_SECONDS = 3 * 3600


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def api(plane, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
        "authorization": f"Bearer {plane.token}", "x-gbox-actor": "agent", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read() or b"{}")


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pad = vpad_win.VGamepad() if vpad_win.available() else None
    log(f"watcher up; agent pad on slot {getattr(pad, 'slot', None)}")
    plane = Plane()
    deadline = time.time() + WATCH_SECONDS
    session = None
    while time.time() < deadline:
        mine = [s for s in api(plane, "GET", "/api/sessions?include_ended=false")
                if s.get("agent_owned")]
        if mine:
            session = mine[0]
            break
        time.sleep(20)
    if not session:
        log("watcher expired without an agent-owned session")
        if pad:
            pad.close()
        return 1
    sid = session["session_id"]
    log(f"agent-owned session {sid} appeared")
    reader = Reader(plane, sid)
    report = {"sid": sid, "started": time.strftime("%H:%M:%S"), "steps": []}

    def step(name, **kw):
        report["steps"].append({"step": name, "at": time.strftime("%H:%M:%S"), **kw})
        log(f"{name}: {json.dumps(kw, default=str)[:260]}")

    step("state", **W.state(reader))

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
        time.sleep(3.0)
        state = W.state(reader)
        step(f"probe_{name}", answer=answer, mode=state.get("mode"))
        if state.get("mode") not in (None, 0):
            method = name
            break
    if method is None:
        step("input", ok=False, why="neither path advanced the title after one press each")
        (REPORT_DIR / f"watch-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
            json.dumps(report, indent=1, default=str), encoding="utf-8")
        if pad:
            pad.close()
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
    try:
        ptr = struct.unpack(">I", reader.read(SEED_PTR, 4))[0]
        step("seed_descriptor", pointer=hex(ptr))
        if 0x80000000 <= ptr < 0x81800000:
            step("seed", value=hex(struct.unpack(">I", reader.read(ptr + 0x118, 4))[0]))
    except Exception as exc:                                    # noqa: BLE001
        step("seed_descriptor", error=str(exc))
    out = REPORT_DIR / f"watch-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log(f"report {out}")
    try:
        api(plane, "POST", "/api/jobs", {"tool": "session_op", "input": {"session_id": sid, "op": "stop_game"}})
        step("stopped", sid=sid)
    except Exception as exc:                                    # noqa: BLE001
        step("stop_failed", error=str(exc))
    if pad:
        pad.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
