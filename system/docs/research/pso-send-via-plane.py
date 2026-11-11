"""Send input through the plane's own session RPC instead of the Windows focus path.

The docked emulator has no top-level window and a shell overlay steals the foreground, so the direct win_send_keys path refuses. The plane's
`send_input` op goes through the adapter that owns the session, which is exactly the path the app itself uses - no foreground needed.

This presses START through the RPC and reports the answer.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S


def send(events):
    try:
        return S.rpc("send_input", {"events": events})
    except Exception as exc:                                      # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:140]}"


print("session:", S.session_id())
print("before floor:", int.from_bytes(S.read_memory(0x805D5FC0, 4), "big"))
reply = send([{"key": "start", "down": True}, {"key": "start", "down": False}])
print("start reply:", json.dumps(reply)[:300] if not isinstance(reply, str) else reply)
time.sleep(2.5)
reply = send([{"key": "ddown", "down": True}, {"key": "ddown", "down": False}])
print("ddown reply:", json.dumps(reply)[:200] if not isinstance(reply, str) else reply)
time.sleep(1.0)
print("after floor:", int.from_bytes(S.read_memory(0x805D5FC0, 4), "big"))
