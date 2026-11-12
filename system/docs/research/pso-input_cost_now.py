"""Does one queued input still blind the RPC? Re-measure, because the autobot moved while reads worked.

Earlier a single 0.15 s press left the RPC unreadable for 25 s, which is why a live grid could not be recorded by driving. But when the **autobot** was playing, the
same `/api/sessions/<sid>/input` path moved the character 258 units while position reads returned normally every 2 s - so the blindness may not be inherent to input,
and it is worth measuring again rather than assuming.

This sends one short press through the app's endpoint and polls a read with a short timeout, reporting how long until the session answers again.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
COUNTER = 0x805D53A4


def call(sid, path, payload=None, timeout=6):
    request = urllib.request.Request(
        f"http://127.0.0.1:18765{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    start = time.time()
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
        return time.time() - start, raw
    except urllib.error.HTTPError as exc:
        return time.time() - start, f"HTTP {exc.code}"
    except Exception as exc:                                       # noqa: BLE001
        return time.time() - start, type(exc).__name__


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    read = {"op": "read_memory", "args": {"address": COUNTER, "length": 4}}
    print("baseline read:", call(sid, f"/api/sessions/{sid}/rpc", read))

    print("\npressing 'w' for 0.2 s:")
    print("  down:", call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": True}]}))
    time.sleep(0.2)
    print("  up:  ", call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": False}]}))

    print("\npolling the read:")
    started = time.time()
    recovered = None
    for attempt in range(20):
        elapsed, body = call(sid, f"/api/sessions/{sid}/rpc", read, timeout=5)
        ok = isinstance(body, bytes)
        print(f"  +{time.time() - started:5.1f}s  attempt {attempt + 1}: {elapsed:4.1f}s {'OK' if ok else body}")
        if ok:
            recovered = time.time() - started
            break
        time.sleep(0.4)
    print(f"\nrecovered after {recovered:.1f}s" if recovered is not None else "\nnever recovered in the window")
    print("VERDICT:", "input is cheap - a live grid can be recorded by driving"
          if recovered is not None and recovered < 3 else "input still costs the RPC time; driving is impractical")
