"""Launch PSO and test whether input now reaches the game.

The app has been reloaded, so `_setup_vpad` ran: `GCPadNew.ini` now carries `Options/Always Connected = True` on `[GCPad1]`, and `Device` reads `XInput/0/Gamepad`
because that is the slot the virtual pad took this time - the replacement is a no-op when the slot is 0, which is correct.

With the pad in place, `send_input` takes the `vpad.apply` branch, which needs no window focus. So even an agent-launched session should now be drivable, and this
launches one and measures the character before and after a press. A real movement is the proof that the whole chain works.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PLAYER, POS = 0x8050EA10, 0x38
GAME = "436e0bb84d5337d1"          # Phantasy Star Online Episode I & II Plus (USA)


def call(path, payload=None, method="POST", timeout=180):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def live_sessions():
    rows = call("/api/sessions", method="GET")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def read(sid, address, length):
    raw = call(f"/api/sessions/{sid}/rpc", {"op": "read_memory", "args": {"address": address, "length": length}})
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def position(sid):
    body = read(sid, PLAYER, 4)
    if len(body) != 4:
        return None
    pointer = int.from_bytes(body, "big")
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    spot = read(sid, pointer + POS, 12)
    return struct.unpack(">fff", spot) if len(spot) == 12 else None


if __name__ == "__main__":
    existing = live_sessions()
    print("live sessions:", len(existing))
    if existing:
        sid = existing[0]["session_id"]
        print("using", sid, "| agent:", existing[0].get("agent_owned"))
    else:
        game = call(f"/api/catalog/{GAME}")
        print("launching PSO...")
        job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game}})
        job_id = job.get("id")
        print("job:", job_id)
        for _ in range(40):
            time.sleep(3)
            row = call(f"/api/jobs/{job_id}")
            if row.get("state") in ("succeeded", "failed", "cancelled"):
                print("launch:", row.get("state"), "|", str(row.get("error"))[:120])
                break
        else:
            raise SystemExit("launch did not finish")
        live = live_sessions()
        if not live:
            raise SystemExit("no session after launch")
        sid = live[0]["session_id"]
        print("session:", sid, "| agent:", live[0].get("agent_owned"))

    time.sleep(6)
    before = position(sid)
    print("\nposition before:", tuple(round(v, 1) for v in before) if before else None)
    if before is None:
        raise SystemExit("no player yet - the game may still be booting")

    print("\npressing 'w' for 0.6 s through the app input endpoint:")
    print("  down:", call(f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": True}]}))
    time.sleep(0.6)
    print("  up:  ", call(f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": False}]}))
    time.sleep(0.6)

    after = position(sid)
    print("position after: ", tuple(round(v, 1) for v in after) if after else None)
    if after:
        moved = abs(after[0] - before[0]) + abs(after[2] - before[2])
        print(f"\nmovement: {moved:.2f} units")
        print("VERDICT:", "INPUT REACHES THE GAME - the bot can drive it" if moved > 0.2
              else "still no movement")
