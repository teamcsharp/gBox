"""Which endpoints still answer? One call at a time, timed, on the running session."""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PORT = 18765


def call(sid, label, path, payload=None, method="POST", timeout=20):
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"},
    )
    start = time.time()
    try:
        raw = urllib.request.urlopen(request, timeout=timeout).read()
        print(f"  {label:34s} {time.time() - start:5.2f}s  OK   {raw[:110]!r}")
        return raw
    except urllib.error.HTTPError as exc:
        print(f"  {label:34s} {time.time() - start:5.2f}s  HTTP {exc.code}  {exc.read()[:110]!r}")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  {label:34s} {time.time() - start:5.2f}s  {type(exc).__name__}")
    return None


if __name__ == "__main__":
    sid = S.session_id()
    print("session:", sid)

    call(sid, "rpc read_memory", f"/api/sessions/{sid}/rpc",
         {"op": "read_memory", "args": {"address": 0x805D5FC0, "length": 4}})
    call(sid, "rpc state (player only)", f"/api/sessions/{sid}/rpc",
         {"op": "state", "args": {"player_only": True}})
    call(sid, "input w down", f"/api/sessions/{sid}/input",
         {"events": [{"key": "w", "down": True}]})
    time.sleep(0.6)
    call(sid, "input w up", f"/api/sessions/{sid}/input",
         {"events": [{"key": "w", "down": False}]})
    call(sid, "rpc read_memory again", f"/api/sessions/{sid}/rpc",
         {"op": "read_memory", "args": {"address": 0x805D5FC0, "length": 4}})
    call(sid, "pso_controls status", f"/api/sessions/{sid}/rpc",
         {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 12,
                                        "input": {"session_id": sid, "op": "status"}}})
