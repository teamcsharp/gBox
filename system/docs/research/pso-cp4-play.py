"""Wait for a session, then hand it to gBox's own PSO campaign and frame the play.

Deliberately small: no pad, no taps, no launch. Everything that can be done without the operator is already done; the campaign
(`autoplay op=start campaign=pso-episodes-1-2`) is exempt from the admission gate, so the moment a session exists this starts
the plane's own play and captures frames.
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
from gbox import pso_boot_walk as W                     # noqa: E402

LOG = Path(r"C:\_tools\gBox\.tmp\pso_campaign.log")
FRAMES = Path(r"D:\gBox\pso-ds\demo")
CAMPAIGN = "pso-episodes-1-2"
WATCH = 45 * 60


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


def frame(tag):
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
    log(f"waiter up: campaign {CAMPAIGN!r} starts on the first session it sees")
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
    log(f"campaign start job {job.get('id')} state={job.get('state')}")
    frames = 0
    for step in range(240):
        time.sleep(10)
        try:
            status = api(plane, "POST", "/api/jobs", {"tool": "autoplay", "input": {
                "session_id": sid, "op": "status"}})
            log(f"status: {json.dumps(status, default=str)[:400]}")
        except Exception as exc:                            # noqa: BLE001
            log(f"status failed: {type(exc).__name__}: {exc}")
        game = W.state(reader)
        log(f"state: {json.dumps(game)}")
        if step % 2 == 0:
            frame("campaign")
            frames += 1
    log(f"watch finished after {frames} frames; the session is left as the operator finds it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
