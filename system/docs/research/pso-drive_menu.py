"""Drive PSO from the title menu into offline play, checking each step on screen.

The press works: START opened the main menu (ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE), so `session_op` `send_input` reaches the game through the virtual pad.
Every earlier attempt was judged by memory values - floor 0, a null player pointer, a game counter - which do not move on a menu **even while the screen does**. That
is why "the game did not advance" was wrong.

This walks the menu the way a player would, capturing a frame after each press so progress is observed rather than assumed:

    DOWN -> OFFLINE GAME, A -> character/card screen, A -> continue

Each frame is saved with a step number, so any screen can be looked at directly.
"""
import hashlib
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
BASE = r"D:\gBox\pso-ds"
PLAYER, FLOOR = 0x8050EA10, 0x805D5FC0


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


def press(sid: str, worker: str, key: str, hold: float = 0.12) -> str:
    """Hold and release as two events in one job, so the pad sees a real press."""
    job = call("/api/jobs", {"tool": "session_op", "require_worker": worker,
                             "input": {"session_id": sid, "op": "send_input",
                                       "args": {"events": [{"key": key, "down": True}]}}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if job_id:
        for _ in range(6):
            time.sleep(0.8)
            row = call("/api/jobs/" + job_id)
            if row.get("state") in ("succeeded", "failed"):
                break
    time.sleep(hold)
    job = call("/api/jobs", {"tool": "session_op", "require_worker": worker,
                             "input": {"session_id": sid, "op": "send_input",
                                       "args": {"events": [{"key": key, "down": False}]}}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if job_id:
        for _ in range(6):
            time.sleep(0.8)
            row = call("/api/jobs/" + job_id)
            if row.get("state") in ("succeeded", "failed"):
                break
    return "pressed"


def snapshot(sid: str) -> tuple:
    raw = call("/api/sessions/%s/rpc" % sid, {"op": "read_memory",
                                             "args": {"address": PLAYER, "length": 4}}, "POST")
    try:
        pointer = int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                              # noqa: BLE001
        pointer = 0
    body = call("/api/sessions/%s/rpc" % sid, {"op": "read_memory",
                                              "args": {"address": FLOOR, "length": 4}}, "POST")
    try:
        floor = int.from_bytes(bytes.fromhex(body), "big")
    except Exception:                                              # noqa: BLE001
        floor = None
    return (pointer if 0x80000000 <= pointer < 0x81800000 else None), floor


if __name__ == "__main__":
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    worker = sid.split("-")[0]
    print("session:", sid)

    steps = [("down", "menu: OFFLINE GAME"),
             ("a", "enter offline"),
             ("a", "card / continue"),
             ("start", "skip")]
    for index, (key, why) in enumerate(steps, 1):
        press(sid, worker, key)
        time.sleep(2.2)
        shot = frame(sid)
        path = f"{BASE}\\step_{index:02d}_{key}.jpg"
        open(path, "wb").write(shot)
        pointer, floor = snapshot(sid)
        print(f"  step {index}: {key:5s} ({why:22s}) -> {len(shot)} bytes | floor {floor} | "
              f"player {hex(pointer) if pointer else None}")
        print(f"            {path}")
        if pointer:
            print("\nA CHARACTER EXISTS - the game is in play")
            break
