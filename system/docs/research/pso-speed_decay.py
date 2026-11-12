"""Does fast-forward hold, or decay? Sample the game counter in short windows after enabling it.

3.49x is a strange number: the machine showed GPU 5% and CPU 10 of 20 cores, so it is not saturated, and `Dolphin.ini` has no `EmulationSpeed` and `GFX.ini` is empty
- nothing is configured to cap it. That leaves a timing explanation: `fast_forward` sends the lane key (F13) **once, as a key-down**, and Dolphin's own hotkey state
may not stay held. If the limit returns after a moment, a measurement averaged over seconds lands between the fast and normal rates - which is exactly 3.49x.

So measure the rate in short slices right after enabling. A rate that holds is real throughput; a rate that falls back to 30.5/s is a key that is not being held.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
COUNTER = 0x805D53A4


def rpc(sid, op, args, timeout=30):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")


def service(sid, op, args):
    body = {"tool": "session_op", "input": {"session_id": sid, "op": op, "args": args}, "require_worker": sid.split("-")[0]}
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/jobs", data=json.dumps(body).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    job = json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")
    job_id = job.get("id")
    for _ in range(30):
        time.sleep(1)
        row = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:18765/api/jobs/{job_id}",
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return row.get("state")
    return "timeout"


def value(sid):
    raw = rpc(sid, "read_memory", {"address": COUNTER, "length": 4})
    return int.from_bytes(bytes.fromhex(raw), "big") if isinstance(raw, str) else None


def rate(sid, seconds=0.5):
    a = value(sid)
    time.sleep(seconds)
    b = value(sid)
    if a is None or b is None:
        return None
    return ((b - a) & 0xFFFFFFFF) / seconds


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    print("\nbaseline rate:", round(rate(sid) or 0, 1), "/s")
    print("enabling fast-forward:", service(sid, "fast_forward", {"on": True}))

    print("\nrate in 0.5 s slices after enabling:")
    for index in range(10):
        r = rate(sid, 0.5)
        print(f"  +{index * 0.5:4.1f}s: {r:7.1f} /s" if r else f"  +{index * 0.5:4.1f}s: read failed")

    print("\nrestoring:", service(sid, "fast_forward", {"on": False}))
