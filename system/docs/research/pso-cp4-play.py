"""Play PSO: start gBox's own PSO campaign autoplay on a live session and report/frame its progress.

The plane ships a PSO campaign (`pso_campaign.CAMPAIGN = "pso-episodes-1-2"`, gated to the GPOE8P rev 2 disc, which is what this
machine has). `autoplay` is exempt from the background-admission gate, so once a session exists the plane can play the game
itself through its own controller - menus, field, fights, and onward.

This driver waits for a session (the operator's Play is the fastest way), starts the campaign, then logs the campaign state and
saves a frame every 20 s so the run is watchable. The agent's ViGEm pad is the fallback if the campaign refuses.
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from pso_boot import Plane, Reader, BASE                 # noqa: E402
from gbox import pso_boot_walk as W, vpad_win            # noqa: E402

LOG = Path(r"C:\_tools\gBox\.tmp\pso_play.log")
FRAMES = Path(r"D:\gBox\pso-ds\demo")
CAMPAIGN = "pso-episodes-1-2"
WATCH = 25 * 60


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def api(plane, method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
        "authorization": f"Bearer {plane.token}", "x-gbox-actor": "agent", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def frame(tag: str):
    try:
        FRAMES.mkdir(parents=True, exist_ok=True)
        out = FRAMES / f"{time.strftime('%H%M%S')}-{tag}.png"
        script = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing;"
                  "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                  "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                  "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                  "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
                  f"$bmp.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png);"
                  "$g.Dispose();$bmp.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=60)
        log(f"frame {out.name}")
    except Exception as exc:                                # noqa: BLE001
        log(f"frame failed: {type(exc).__name__}: {exc}")


def main():
    plane = Plane()
    log(f"player up (native campaign {CAMPAIGN!r}); waiting for a session")
    session = None
    start = time.time()
    while time.time() - start < WATCH:
        session = plane.running()
        if session:
            break
        time.sleep(10)
    if not session:
        log("no session appeared within the watch window")
        return 1
    sid = session["session_id"]
    reader = Reader(plane, sid)
    log(f"session {sid}; state={json.dumps(W.state(reader))}")

    job = api(plane, "POST", "/api/jobs", {"tool": "autoplay", "input": {
        "session_id": sid, "op": "start", "campaign": CAMPAIGN}})
    log(f"autoplay start job {job.get('id')} state={job.get('state')}")
    jid = job.get("id")
    state = None
    for _ in range(40):
        time.sleep(3)
        if jid:
            state = api(plane, "GET", f"/api/jobs/{jid}")
            if state.get("state") in ("succeeded", "failed", "cancelled"):
                break
    log(f"start job: {json.dumps({k: state.get(k) for k in ('state', 'error') if state}, default=str)[:300]}")
    if state and state.get("output"):
        log(f"output: {json.dumps(state['output'], default=str)[:400]}")

    last_frame = 0.0
    for step in range(150):
        time.sleep(8)
        status = {}
        try:
            status = api(plane, "POST", "/api/jobs", {"tool": "autoplay", "input": {
                "session_id": sid, "op": "status"}})
        except Exception as exc:                            # noqa: BLE001
            log(f"status failed: {type(exc).__name__}: {exc}")
        if step % 3 == 0:
            game = W.state(reader)
            log(f"tick {step}: state={json.dumps(game)}")
        if time.time() - last_frame > 20:
            frame("playing")
            last_frame = time.time()
    log("watch finished; the session is left as the operator finds it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
