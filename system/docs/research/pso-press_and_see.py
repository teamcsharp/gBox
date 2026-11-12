"""Press START and look at the screen before and after - the test that was missing.

Every earlier input attempt judged by memory values (floor 0, player pointer, a game counter), which stay put on the title even when the screen changes. The
MJPEG viewer route now gives the actual picture, so this compares frames:

1. capture a baseline JPEG;
2. press START through `session_op` (straight to the adapter, the `vpad.apply` branch);
3. capture again and compare.

A different frame means the press reached the game. Both frames are saved, so the result can be looked at rather than inferred.
"""
import hashlib
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
BASE = r"D:\gBox\pso-ds"


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


def press(sid: str, worker: str, key: str) -> str:
    job = call("/api/jobs", {"tool": "session_op", "require_worker": worker,
                             "input": {"session_id": sid, "op": "send_input",
                                       "args": {"events": [{"key": key, "down": True},
                                                           {"key": key, "down": False}]}}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return "rejected: " + json.dumps(job)[:90]
    for _ in range(8):
        time.sleep(1)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
    return "timeout"


if __name__ == "__main__":
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    worker = sid.split("-")[0]

    before = frame(sid)
    open(BASE + r"\screen_before.jpg", "wb").write(before)
    print("before:", len(before), "bytes | sha", hashlib.sha256(before).hexdigest()[:12])

    for index in range(4):
        state = press(sid, worker, "start")
        print(f"  press {index + 1}: {state}")
        time.sleep(2.5)
        after = frame(sid)
        digest = hashlib.sha256(after).hexdigest()[:12]
        changed = hashlib.sha256(before).hexdigest() != hashlib.sha256(after).hexdigest()
        print(f"    after: {len(after)} bytes | sha {digest} | changed: {changed}")
        if changed:
            open(BASE + r"\screen_after.jpg", "wb").write(after)
            print("\nTHE SCREEN CHANGED - the press reached the game; saved screen_after.jpg")
            break
        before = after
    else:
        print("\nTHE SCREEN NEVER CHANGED - START is not reaching the game")
