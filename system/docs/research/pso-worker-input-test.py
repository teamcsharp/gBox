"""Drive movement through the worker's send_input instead of external keys.

My own win_send_keys calls stopped reaching the game while the worker's send_input still opens the menu. This closes the menu, then
walks a stride with the worker path (down, sleep, up) and reports the position change.
"""
import json
import struct
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_gbox_app as cap                                     # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


def call(path, method="GET", body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def job(tool, payload, timeout=60):
    started = time.time()
    body = call("/api/jobs", "POST", {"tool": tool, "input": payload})
    while time.time() - started < timeout:
        time.sleep(0.3)
        state = call("/api/jobs/" + body["id"])
        if state.get("state") not in ("queued", "running"):
            return state.get("state"), (state.get("output") or {}).get("result"), str(state.get("error"))[:200]
    return "timeout", None, ""


def send(events):
    return job("session_op", {"session_id": SID, "op": "send_input", "args": {"events": events}})


def tap(key, times=1, gap=0.5):
    for _ in range(times):
        send([{"key": key, "down": True}, {"key": key, "down": False}])
        time.sleep(gap)


def hold(key, seconds):
    send([{"key": key, "down": True}])
    time.sleep(seconds)
    send([{"key": key, "down": False}])


def read(address, length):
    body = json.dumps({"op": "read_memory", "args": {"address": address, "length": length}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=body, method="POST",
                                         headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                                  "content-type": "application/json"})
            return bytes.fromhex(json.loads(urllib.request.urlopen(req, timeout=12).read() or b'""'))
        except Exception:                                        # noqa: BLE001
            time.sleep(0.2)
    return b""


def pos():
    actor = int.from_bytes(read(0x8050EA10, 4), "big")
    if not actor:
        return None
    x, y, z = struct.unpack(">fff", read(actor + 0x38, 12))
    return round(x, 1), round(y, 1), round(z, 1)


def main():
    print("before:", pos())
    print("close menu:", tap("b", 2, 0.5))
    for key in ("up", "down", "left", "right"):
        before = pos()
        hold(key, 1.0)
        print(f"  {key}: {before} -> {pos()}")
    cap.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
