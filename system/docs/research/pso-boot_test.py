"""Press START at the title and watch for the game to advance.

The session is up but there is no character in the field, so the game sits at the title screen - and a title screen needs input to leave. That makes it the cleanest
possible test of whether the virtual pad works: nothing else can move the game forward, and a character appearing (the player pointer becoming non-null) or the floor
value changing is proof that the presses arrived.

If this works, it is also the first thing the bot has never been able to do on its own: boot the game from the title.
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
        return {"err": f"{type(exc).__name__}: {str(exc)[:120]}"}


def read(sid, address, length):
    raw = call(f"/api/sessions/{sid}/rpc", {"op": "read_memory", "args": {"address": address, "length": length}})
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def player(sid):
    body = read(sid, PLAYER, 4)
    if len(body) != 4:
        return None
    pointer = int.from_bytes(body, "big")
    return pointer if 0x80000000 <= pointer < 0x81800000 else None


def floor(sid):
    body = read(sid, FLOOR, 4)
    return int.from_bytes(body, "big") if len(body) == 4 else None


def press(sid, key, seconds=0.25):
    call(f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": True}]})
    time.sleep(seconds)
    call(f"/api/sessions/{sid}/input", {"events": [{"key": key, "down": False}]})
    time.sleep(0.25)


if __name__ == "__main__":
    rows = call("/api/sessions", method="GET")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    print("session:", sid)
    print("floor before:", floor(sid), "| player:", player(sid))

    for round_index in range(14):
        press(sid, "start")
        press(sid, "a")
        current_floor, current_player = floor(sid), player(sid)
        print(f"  round {round_index + 1:2d}: floor {current_floor} | player "
              f"{hex(current_player) if current_player else None}")
        if current_player is not None:
            spot = read(sid, current_player + POS, 12)
            if len(spot) == 12:
                print("  character in the field at",
                      tuple(round(v, 1) for v in struct.unpack(">fff", spot)))
            print("\nVERDICT: INPUT REACHES THE GAME - the title was passed by pressing buttons")
            break
    else:
        print("\nVERDICT: the game did not advance - presses are still not arriving")
