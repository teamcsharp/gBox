"""Fresh test: does agent input reach the game on a session launched after the pad fix?

`pad_takeover.inputs` returns the events **unchanged** when no operator lease exists:

```python
lz = LEASES.get(sid)
if lz is None or lz.run is None or not events:
    return events
```

So an agent's input is only held back while the operator is actually using the pad - it is not dropped wholesale. That changes the earlier conclusion: the reason
fourteen START presses did nothing may have been the pad (keyboard fallback, no focus), not the actor.

The app has restarted since, so `_setup_vpad` ran with `pad_route.py` present and `GCPadNew.ini` carries `Always Connected`. This launches a fresh session, waits
for the title, then presses START and A and watches the floor and player pointer.
"""
import json
import struct
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
GAME = "436e0bb84d5337d1"
PLAYER, FLOOR, POS = 0x8050EA10, 0x805D5FC0, 0x38


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:200].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__}


def live():
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def read(sid, address, length):
    raw = call(f"/api/sessions/{sid}/rpc", {"op": "read_memory",
                                           "args": {"address": address, "length": length}}, "POST")
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def state(sid):
    body = read(sid, PLAYER, 4)
    pointer = int.from_bytes(body, "big") if len(body) == 4 else 0
    spot = None
    if 0x80000000 <= pointer < 0x81800000:
        raw = read(sid, pointer + POS, 12)
        if len(raw) == 12:
            spot = struct.unpack(">fff", raw)
    floor_body = read(sid, FLOOR, 4)
    return pointer, spot, (int.from_bytes(floor_body, "big") if len(floor_body) == 4 else None)


def press(sid, key, seconds=0.3):
    call(f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": True}]}, "POST")
    time.sleep(seconds)
    call(f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": False}]}, "POST")
    time.sleep(0.3)


if __name__ == "__main__":
    if not live():
        answer = call(f"/api/games/{GAME}/launch?node=auto", {}, "POST")
        job_id = answer.get("id") if isinstance(answer, dict) else None
        print("launch job:", job_id, "|", json.dumps(answer)[:120])
        for _ in range(30):
            time.sleep(3)
            row = call(f"/api/jobs/{job_id}")
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                print("launch:", row.get("state"), "|", str(row.get("error"))[:80])
                break
    sessions = live()
    if not sessions:
        raise SystemExit("no session")
    sid = sessions[0]["session_id"]
    print("session:", sid)

    print("\nletting it boot...")
    for _ in range(10):
        time.sleep(4)
        pointer, spot, floor = state(sid)
        print(f"  floor {floor} | player {hex(pointer) if pointer else 'none'}")

    print("\npressing START and A:")
    for index in range(12):
        press(sid, "start")
        press(sid, "a")
        pointer, spot, floor = state(sid)
        label = hex(pointer) if pointer else "none"
        print(f"  {index + 1:2d}: floor {floor} | player {label}")
        if pointer:
            print("\nVERDICT: INPUT REACHES THE GAME - the title was passed")
            break
    else:
        print("\nVERDICT: the game still did not advance")
