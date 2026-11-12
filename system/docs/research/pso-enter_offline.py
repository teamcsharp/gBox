"""Land on OFFLINE GAME and enter it, capturing each screen.

The D-pad works: a DOWN press moved the title menu's highlight (it wrapped to WEBSITE, so held presses repeat). The menu order is ONLINE, OFFLINE, OPTIONS, WEBSITE, so
from WEBSITE two short DOWNs reach **OFFLINE GAME**.

Short holds matter - a long hold repeats and overshoots - so each press is a down event, a pause, and an up event, one job apiece.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
BASE = r"D:\gBox\pso-ds"


def call(path, payload=None, method="GET", timeout=60):
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


def press(sid: str, worker: str, key: str, hold: float = 0.09) -> None:
    for state in (True, False):
        job = call("/api/jobs", {"tool": "session_op", "require_worker": worker,
                                 "input": {"session_id": sid, "op": "send_input",
                                           "args": {"events": [{"key": key, "down": state}]}}}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        if job_id:
            for _ in range(6):
                time.sleep(0.5)
                row = call("/api/jobs/" + job_id)
                if row.get("state") in ("succeeded", "failed"):
                    break
        if state:
            time.sleep(hold)
    time.sleep(1.2)


def frame(sid: str) -> bytes:
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/mjpeg?fps=2" % sid,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    response = urllib.request.urlopen(request, timeout=25)
    buffer = b""
    try:
        for _ in range(80):
            chunk = response.read(32768)
            if not chunk:
                break
            buffer += chunk
            start = buffer.find(b"\xff\xd8")
            if start >= 0:
                end = buffer.find(b"\xff\xd9", start + 2)
                if end > start:
                    return buffer[start:end + 2]
    finally:
        response.close()
    return b""


if __name__ == "__main__":
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    worker = sid.split("-")[0]
    print("session:", sid)

    # from WEBSITE: down -> ONLINE, down -> OFFLINE
    for label, presses, key in (("to OFFLINE", 2, "down"),):
        for _ in range(presses):
            press(sid, worker, key)
        shot = frame(sid)
        open(f"{BASE}\\menu_offline.jpg", "wb").write(shot)
        print(f"  {label}: {len(shot)} bytes -> menu_offline.jpg")

    press(sid, worker, "a")
    shot = frame(sid)
    open(f"{BASE}\\offline_entered.jpg", "wb").write(shot)
    print(f"  after A: {len(shot)} bytes -> offline_entered.jpg")
