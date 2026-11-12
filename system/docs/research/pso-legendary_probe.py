"""Read the 422 body for the legendary op, so its schema is known rather than guessed.

`S.controls` raises before the body is visible. This sends the same RPC and prints FastAPI's validation detail, which names the offending field.
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

session_id = S.session_id()
print("session:", session_id)

candidates = [
    ("legendary", {"on": True}),
    ("legendary", {"on": True, "player_index": 0}),
    ("modes", {"on": True}),
    ("modes", {}),
]
for op, fields in candidates:
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": session_id, "op": op, **fields}}}
    data = json.dumps(body).encode()
    request = urllib.request.Request(f"{S.API}/api/sessions/{session_id}/rpc", data=data, method="POST",
                                     headers={"authorization": "Bearer " + S.TOKEN, "x-gbox-actor": "agent",
                                              "content-type": "application/json"})
    try:
        reply = json.loads(urllib.request.urlopen(request, timeout=60).read() or b"null")
        print(f"{op} {fields} -> ok: {json.dumps(reply)[:260]}")
    except urllib.error.HTTPError as exc:
        print(f"{op} {fields} -> HTTP {exc.code}: {exc.read()[:300]}")
    except Exception as exc:                                      # noqa: BLE001
        print(f"{op} {fields} -> {type(exc).__name__}: {str(exc)[:150]}")
