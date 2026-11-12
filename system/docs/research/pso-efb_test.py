"""Test whether cheaper per-frame GPU work raises the speed ceiling.

Dolphin is bound by single-thread throughput (1.24 of 16 cores used, 31.6% total CPU), and the one part of that serial work which can be genuinely reduced is the GPU
thread's per-frame cost:

* **`EFBAccessEnable = False`** - EFB peeks/pokes from the CPU force a GPU-to-CPU synchronisation every frame they happen, which is a classic Dolphin stall;
* **`EFBToTextureEnable = True`** - EFB copies go to a texture instead of a RAM copy, which is far cheaper and is what modern Dolphin defaults to for most games;
* **`VSync = False`** - removes any display-rate coupling;
* **`InternalResolution = 1`** - native, so the GPU thread has the least work.

`GFX.ini` is currently **empty**, so all of this is at defaults. The measurement is done on the **title screen**, which runs the frame counter without needing to reach a field
- so a bad setting can be reverted cheaply instead of costing a Forest run.

Revert path: the original file is kept as `GFX.ini.bak-efbtest`, and deleting the new one restores Dolphin's defaults.
"""
import json
import pathlib
import subprocess
import time
import urllib.request

GFX = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GFX.ini")
BACKUP = GFX.with_suffix(".ini.bak-efbtest")
TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
COUNTER = 0x805D53A4
GAME = "436e0bb84d5337d1"

SETTINGS = """[Settings]
EFBAccessEnable = False
EFBToTextureEnable = True
EFBCopyEnable = True
VSync = False
InternalResolution = 1
"""


def call(path, payload=None, method="GET", timeout=90):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__}


def live():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def worker():
    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row["id"] for row in rows if row.get("online")), "")


def rate(sid: str, seconds: float = 5.0) -> float | None:
    def read():
        raw = call("/api/sessions/%s/rpc" % sid,
                   {"op": "read_memory", "args": {"address": COUNTER, "length": 4}}, "POST")
        try:
            return int.from_bytes(bytes.fromhex(raw), "big")
        except Exception:                                          # noqa: BLE001
            return None
    first = read()
    time.sleep(seconds)
    second = read()
    return round((second - first) / seconds, 1) if first is not None and second is not None and second >= first else None


def session_op(sid: str, wid: str, op: str, args: dict) -> str:
    job = call("/api/jobs", {"tool": "session_op", "require_worker": wid,
                             "input": {"session_id": sid, "op": op, "args": args}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(40):
        time.sleep(0.5)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
    return "timeout"


if __name__ == "__main__":
    if not BACKUP.exists():
        BACKUP.write_bytes(GFX.read_bytes())
        print("kept the original GFX.ini as", BACKUP.name, f"({BACKUP.stat().st_size} bytes)")
    GFX.write_text(SETTINGS, encoding="utf-8")
    print("wrote", len(SETTINGS), "bytes of speed settings to GFX.ini")

    for row in live():
        print("stopping session", row["session_id"])
        session_op(row["session_id"], row["session_id"].split("-")[0], "stop_game", {})
        time.sleep(5)

    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Start-ScheduledTask -TaskName 'gbox-desktop-launch'"], capture_output=True, timeout=90)
    for _ in range(30):
        if worker():
            break
        time.sleep(3)
    wid = worker()
    print("worker:", wid)
    if not wid:
        raise SystemExit("no worker")

    game = call("/api/catalog/" + GAME)
    job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game},
                             "require_worker": wid}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("launch:", row.get("state"), str(row.get("error"))[:90])
            break
    sessions = live()
    if not sessions:
        raise SystemExit("no session")
    sid = sessions[0]["session_id"]
    print("session:", sid)
    time.sleep(30)

    print("\nbaseline (new settings):", rate(sid), "fps")
    print("fast_forward:", session_op(sid, wid, "fast_forward", {"on": True}))
    time.sleep(2)
    print("fast-forward (new settings):", rate(sid), "fps")
    time.sleep(3)
    print("settled:", rate(sid), "fps")
    print("\nreference with default GFX: 127.2 - 130.2 fps")
