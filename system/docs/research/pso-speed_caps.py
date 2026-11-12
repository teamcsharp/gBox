"""What does the live session say about speed, and is a 10x rate reachable?

`pso_controls` has a `capabilities` op that reports which features this session supports. `autoplay_speed` is one of them, and the status carries the current
multiplier and whether it is changeable. That decides whether 10x is a configuration change or a code change - measured rather than assumed.
"""
import json
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def controls(sid, op, fields=None, timeout=60):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 12,
                                          "input": {"session_id": sid, "op": op, **(fields or {})}}}
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps(body).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {str(exc)[:160]}"}


if __name__ == "__main__":
    sid = S.session_id()
    print("session:", sid)
    caps = controls(sid, "capabilities")
    print("\ncapabilities:")
    print(json.dumps(caps, indent=2, default=str)[:1200])

    status = controls(sid, "status")
    print("\nstatus.autoplay_speed:")
    print(json.dumps(status.get("autoplay_speed") if isinstance(status, dict) else status, indent=2, default=str)[:600])
