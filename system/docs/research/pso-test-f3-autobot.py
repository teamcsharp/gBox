"""Press F3's path from code: POST /api/sessions/<sid>/autoplay {op:'start'} - then watch the character.

This is exactly what F3 does (`f3Autobot` -> `GBoxPiPMedia.autobot(..., {op:'toggle'})` -> this endpoint -> the `autoplay` tool on the session's worker). Running
it directly shows two things the UI cannot: how long the start takes, and whether the character actually moves afterwards.

The character's position is at +0x38 of the pointer in 0x8050EA10, read from the control plane on 18765 (the app proxy on 8765 cuts off at 10 s).
"""
import json
import struct
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PORT = 18765
PLAYER = 0x8050EA10
POS = 0x38


def call(path, payload=None, method="POST", timeout=90):
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except urllib.error.HTTPError as exc:
        return {"_http": exc.code, "_body": exc.read()[:300].decode("utf-8", "replace")}
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def position(sid):
    raw = call(f"/api/sessions/{sid}/rpc",
               {"op": "read_memory", "args": {"address": PLAYER, "length": 4}})
    if isinstance(raw, str):
        pointer = int(raw, 16)
    else:
        return None
    if not (0x80000000 <= pointer < 0x81800000):
        return None
    raw = call(f"/api/sessions/{sid}/rpc",
               {"op": "read_memory", "args": {"address": pointer + POS, "length": 12}})
    try:
        return struct.unpack(">fff", bytes.fromhex(raw))
    except Exception:                                              # noqa: BLE001
        return None


if __name__ == "__main__":
    sid = S.session_id()
    print("session:", sid)
    print("pos before:", position(sid))

    print("\nPOST /api/sessions/<sid>/autoplay {op:'start'}  (F3's action):")
    start = time.time()
    answer = call(f"/api/sessions/{sid}/autoplay",
                  {"op": "start", "source": "probe", "continuous": True, "assist": False})
    print(f"  took {time.time() - start:.2f}s")
    print("  ->", json.dumps(answer)[:400])

    print("\nwatching the character for 20 s:")
    samples = []
    for index in range(10):
        time.sleep(2)
        spot = position(sid)
        samples.append(spot)
        print(f"  {index + 1}: {spot}")
    moving = [s for s in samples if s]
    if len(moving) >= 2:
        span = max(abs(a[0] - b[0]) + abs(a[2] - b[2]) for a in moving for b in moving)
        print(f"\nlargest movement: {span:.2f} units")
        print("VERDICT:", "the autobot is driving the character" if span > 0.5 else "the character did not move")
