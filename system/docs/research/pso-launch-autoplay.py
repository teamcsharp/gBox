"""Launch PSO with autoplay on, and watch whether the bot actually plays.

Two things changed since the last attempt and both are now live because the app restarted:

* the launch route no longer requires a `linux` worker for `kind: "attract"` games (my guard), so an agent launch can be dispatched;
* `pad_route.py` is present, so a new session binds Player 1 to the virtual pad.

The route also accepts **`autoplay=true`**, which starts the app's own bot on launch:

```python
if autoplay and not debug:
    from . import screensaver
    screensaver.autoplay_on_launch(store, job_id, gid, actor=actor, agent=bool(req.agent_use))
```

That is the sanctioned way to get a bot playing without the operator pressing F3 - the autoplay injects input inside the worker, which agent-posted input can never do.

This launches with autoplay and samples floor, player pointer and position for a minute, so "the bot is playing" is a measurement.
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
                    "body": exc.read()[:240].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:140]}


def live_sessions():
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
    print("sessions before:", [row["session_id"] for row in live_sessions()])
    answer = call(f"/api/games/{GAME}/launch?node=auto&autoplay=true", {}, "POST")
    print("launch:", json.dumps(answer)[:220])
    job_id = answer.get("id") if isinstance(answer, dict) else None
    if not job_id:
        raise SystemExit("no job id")

    started = time.time()
    for index in range(30):
        time.sleep(3)
        row = call(f"/api/jobs/{job_id}")
        state = row.get("state")
        progress = row.get("progress") or {}
        print(f"  {index + 1:2d} {state:9s} pct={progress.get('pct')} "
              f"{str(progress.get('msg'))[:50]} {str(row.get('error'))[:60]}")
        if state in ("succeeded", "failed", "cancelled"):
            print(f"  launch took {time.time() - started:.1f}s")
            break

    live = live_sessions()
    print("live sessions:", [(row["session_id"], row.get("agent_owned")) for row in live])
    if not live:
        raise SystemExit("no session to watch")
    sid = live[0]["session_id"]

    print("\nwatching for the bot to play (30 samples):")
    positions = []
    for index in range(30):
        pointer, spot, floor = snapshot(sid)
        if spot:
            positions.append(spot)
        label = hex(pointer) if pointer else "none"
        where = tuple(round(v, 1) for v in spot) if spot else None
        print(f"  {index + 1:2d}: floor {floor} | player {label} | pos {where}")
        time.sleep(3)

    if not positions:
        print("\nVERDICT: no character ever appeared - autoplay did not boot the game")
    else:
        moved = sum(abs(a[0] - b[0]) + abs(a[2] - b[2]) for a, b in zip(positions, positions[1:]))
        print(f"\ntotal movement: {moved:.1f} units over {len(positions)} samples")
        print("VERDICT:", "THE BOT IS PLAYING" if moved > 2 else "character present but not moving")
