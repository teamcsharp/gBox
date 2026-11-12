"""Does input reach this session now that the virtual pad is bound?

The session is agent-launched, which used to be undrivable because `send_input` fell back to `win_send_keys` - which takes window focus and drops presses while the game
sits in the PiP. With `GCPadNew.ini` carrying `Options/Always Connected = True` from `_setup_vpad`, `_vpad_works()` should be true and `send_input` should take the
`vpad.apply` branch instead.

This measures the character before and after a press. Real movement is the proof.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PLAYER, POS = 0x8050EA10, 0x38


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


def live():
    rows = call("/api/sessions", method="GET")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def read(sid, address, length):
    raw = call(f"/api/sessions/{sid}/rpc", {"op": "read_memory", "args": {"address": address, "length": length}})
    try:
        return bytes.fromhex(raw)
    except Exception:                                              # noqa: BLE001
        return b""


def state(sid):
    body = read(sid, PLAYER, 4)
    if len(body) != 4:
        return None, None
    pointer = int.from_bytes(body, "big")
    if not (0x80000000 <= pointer < 0x81800000):
        return None, None
    spot = read(sid, pointer + POS, 12)
    return pointer, (struct.unpack(">fff", spot) if len(spot) == 12 else None)


if __name__ == "__main__":
    sessions = live()
    if not sessions:
        raise SystemExit("no live session")
    sid = sessions[0]["session_id"]
    print("session:", sid, "| agent-owned:", sessions[0].get("agent_owned"))

    # let the game settle past the boot
    pointer, before = None, None
    for attempt in range(12):
        pointer, before = state(sid)
        if before:
            break
        time.sleep(3)
    print("player:", hex(pointer) if pointer else None,
          "| pos:", tuple(round(v, 1) for v in before) if before else None)
    if not before:
        raise SystemExit("no character in the field yet")

    print("\npress 'w' for 0.7 s:")
    print("  down:", call(f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": True}]}))
    time.sleep(0.7)
    print("  up:  ", call(f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": False}]}))
    time.sleep(0.5)

    _, after = state(sid)
    print("pos after:", tuple(round(v, 1) for v in after) if after else None)
    if after:
        moved = abs(after[0] - before[0]) + abs(after[2] - before[2])
        print(f"\nmovement: {moved:.2f} units")
        print("VERDICT:", "INPUT REACHES THE GAME" if moved > 0.2 else "no movement")
