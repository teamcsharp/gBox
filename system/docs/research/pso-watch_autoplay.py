"""Is the autoplay actually playing? Watch the game advance from the title.

The `autoplay` tool accepted `op: start` on this agent-owned session (job succeeded), so the app's own bot - which injects input inside the worker rather than posting it
as an agent - is now in charge. Whether it can play is a different question from whether it started, and only the game's own state can answer it:

* `floor` changing from 0 means the title was left;
* a non-null player pointer means a character is in the field;
* a changing position means it is being driven.

This samples all three for half a minute and reports what actually happened.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PLAYER, FLOOR, POS = 0x8050EA10, 0x805D5FC0, 0x38


def call(path, payload=None, method="POST", timeout=45):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"err": f"{type(exc).__name__}: {str(exc)[:100]}"}


def read(sid, address, length):
    raw = call(f"/api/sessions/{sid}/rpc", {"op": "read_memory", "args": {"address": address, "length": length}})
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def snapshot(sid):
    body = read(sid, PLAYER, 4)
    pointer = int.from_bytes(body, "big") if len(body) == 4 else 0
    spot = None
    if 0x80000000 <= pointer < 0x81800000:
        raw = read(sid, pointer + POS, 12)
        if len(raw) == 12:
            spot = struct.unpack(">fff", raw)
    floor_body = read(sid, FLOOR, 4)
    return pointer, spot, (int.from_bytes(floor_body, "big") if len(floor_body) == 4 else None)


if __name__ == "__main__":
    rows = call("/api/sessions", method="GET")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    print("session:", sid)

    positions = []
    for index in range(16):
        pointer, spot, floor = snapshot(sid)
        if spot:
            positions.append(spot)
        label = hex(pointer) if pointer else "none"
        where = tuple(round(v, 1) for v in spot) if spot else None
        print(f"  {index + 1:2d}: floor {floor} | player {label:>10} | pos {where}")
        time.sleep(3)

    print()
    if not positions:
        print("VERDICT: no character ever appeared - the autoplay is not pressing at the title")
    else:
        span = sum(abs(a[0] - b[0]) + abs(a[2] - b[2]) for a, b in zip(positions, positions[1:]))
        print(f"total movement across the samples: {span:.1f} units")
        print("VERDICT:", "THE BOT IS PLAYING" if span > 1.0 else "character present but stationary")
