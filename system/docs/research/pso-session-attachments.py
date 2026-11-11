"""Report the session's ownership and input attachments.

If the emulator ignores the operator's controller as well as the agent's keys, the problem is upstream of any injection: the app is not
relaying input to this session, which happens when the session was started by an agent job rather than by the desktop app.
"""
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

SID = S.session_id()
print("session:", SID)
detail = None
for path in ("/api/sessions", f"/api/sessions/{SID}"):
    try:
        detail = S._call(path)
        break
    except Exception as exc:                                      # noqa: BLE001
        print(f"  {path} failed: {str(exc)[:80]}")
if isinstance(detail, dict):
    row = detail
elif isinstance(detail, list):
    row = next((item for item in detail if item.get("session_id") == SID), None) or {}
else:
    row = {}
print("session record:")
for key in ("session_id", "state", "pid", "worker_id", "game_id", "origin", "actor", "attach", "input", "pad"):
    if key in row:
        print(f"  {key}: {json.dumps(row[key])[:160]}")
print("all keys:", sorted(row.keys())[:40])

try:
    caps = S.controls("capabilities", {})
    print("capabilities:", json.dumps({k: caps[k] for k in ("supported", "reason", "players") if k in caps})[:300])
except Exception as exc:                                        # noqa: BLE001
    print("capabilities failed:", str(exc)[:100])
