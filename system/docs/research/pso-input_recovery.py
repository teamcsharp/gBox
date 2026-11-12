"""After a queued input, how long is the RPC unavailable?

The sequence just measured:

```
input w down                0.02s  {"queued":1}
input w up                  0.14s  {"queued":1}
read_memory again          10.03s  HTTP 504  Session did not acknowledge
pso_controls status        10.21s  HTTP 504  Session did not acknowledge
```

Sending input is instant; reading afterwards hangs for ten seconds. A bot in that shape cannot play: it presses, then cannot see the result, which is exactly
"just standing there".

This polls `read_memory` with a short timeout after one press and reports when it answers again - so the cost of a press is known in seconds rather than
guessed at.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PORT = 18765


def call(sid, path, payload=None, timeout=6):
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"},
    )
    start = time.time()
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
        return time.time() - start, raw
    except urllib.error.HTTPError as exc:
        return time.time() - start, f"HTTP {exc.code}"
    except Exception as exc:                                       # noqa: BLE001
        return time.time() - start, type(exc).__name__


if __name__ == "__main__":
    sid = S.session_id()
    print("baseline read:", call(sid, f"/api/sessions/{sid}/rpc",
                                 {"op": "read_memory", "args": {"address": 0x805D5FC0, "length": 4}}))

    print("\npressing 'w' for 0.15s:")
    print("  down:", call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": True}]}))
    time.sleep(0.15)
    print("  up:  ", call(sid, f"/api/sessions/{sid}/input", {"events": [{"key": "w", "down": False}]}))

    print("\npolling read_memory until it answers (short timeout each):")
    start = time.time()
    for attempt in range(30):
        elapsed, body = call(sid, f"/api/sessions/{sid}/rpc",
                             {"op": "read_memory", "args": {"address": 0x805D5FC0, "length": 4}}, timeout=4)
        state = "OK" if isinstance(body, bytes) else str(body)
        print(f"  +{time.time() - start:5.2f}s  attempt {attempt + 1}: {elapsed:4.2f}s {state}")
        if isinstance(body, bytes):
            print(f"\nRPC recovered {time.time() - start:.2f}s after the press")
            break
        time.sleep(0.5)
    else:
        print("\nstill unavailable after 30 attempts")
