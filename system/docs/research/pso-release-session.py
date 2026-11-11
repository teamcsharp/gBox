"""Stop the agent-owned test session so the app can start an operator-owned game.

The emulator ignores every input (the operator's pad included) because this session was created by an agent job and gBox does not route
operator input to agent-owned sessions. Ending it is the enabling step: the app's Play button then creates an operator-owned session whose
controller works, and every memory write still applies because the plane's write path is independent of ownership.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

SID = S.session_id()
print("stopping agent-owned session:", SID)
state, result, error = S.job("session_op", {"session_id": SID, "op": "stop_game", "args": {}}, timeout=120)
print("stop_game:", state, "| error:", error)
if result:
    print("result:", json.dumps(result)[:200])
time.sleep(4)
for attempt in range(6):
    rows = S._call("/api/sessions")
    running = [row for row in rows if row.get("state") == "running"]
    print(f"t+{4 * (attempt + 1)}s running sessions: {[r['session_id'][:12] for r in running]}")
    if not any(row.get("session_id") == SID for row in running):
        print("agent session is closed; the app can create an operator-owned one")
        break
    time.sleep(3)
