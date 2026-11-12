"""Press through the adapter directly, not through the HTTP input queue.

The virtual pad now exists and is bound: `XInput` slot 0 reads `lx=0 ly=0` (neutral - a pad at rest), slots 1-3 absent, and `GCPadNew.ini` binds `XInput/0` with
`Always Connected`. So the hardware path is correct, yet START at the title does nothing.

The HTTP route (`PUT /api/sessions/{sid}/input`) puts events in a queue that `pad_takeover` may withhold and that the worker relays. `session_op` with
`op: "send_input"` calls the adapter's `send_input` directly:

```python
if inp.op == "send_input":
    from . import padstate; padstate.report(ctx, ...)
ad, _ = SESSIONS[inp.session_id]        # falls through to getattr(ad, 'send_input')(events)
```

and the adapter's `send_input` takes the `vpad.apply(events)` branch when `_vpad_works()` is true - which is the focus-free path. So this presses the pad itself.

If the game advances here but not over HTTP, the queue is the problem and this is the way to drive it.
"""
import json
import struct
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
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


def read(sid, address, length):
    raw = call("/api/sessions/%s/rpc" % sid, {"op": "read_memory",
                                             "args": {"address": address, "length": length}}, "POST")
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def state(sid):
    body = read(sid, PLAYER, 4)
    pointer = int.from_bytes(body, "big") if len(body) == 4 else 0
    valid = 0x80000000 <= pointer < 0x81800000
    floor_body = read(sid, FLOOR, 4)
    return (pointer if valid else None,
            int.from_bytes(floor_body, "big") if len(floor_body) == 4 else None)


def press(sid, worker, key):
    events = [{"key": key, "down": True}, {"key": key, "down": False}]
    body = {"tool": "session_op", "require_worker": worker,
            "input": {"session_id": sid, "op": "send_input", "args": {"events": events}}}
    return call("/api/jobs", body, "POST")


if __name__ == "__main__":
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    worker = sid.split("-")[0]
    print("session:", sid, "| worker:", worker)

    pointer, floor = state(sid)
    print("before: floor", floor, "| player", hex(pointer) if pointer else None)

    for index in range(10):
        answer = press(sid, worker, "start")
        job_id = answer.get("id") if isinstance(answer, dict) else None
        if job_id:
            for _ in range(8):
                time.sleep(1)
                row = call("/api/jobs/" + job_id)
                if row.get("state") in ("succeeded", "failed", "cancelled"):
                    if row.get("state") != "succeeded":
                        print("  press job:", row.get("state"), str(row.get("error"))[:80])
                    break
        time.sleep(1.2)
        pointer, floor = state(sid)
        print(f"  {index + 1:2d}: floor {floor} | player {hex(pointer) if pointer else None}")
        if pointer:
            print("\nVERDICT: the adapter's send_input reached the game - the HTTP queue was the problem")
            break
    else:
        print("\nVERDICT: even the adapter path did not advance the game")
