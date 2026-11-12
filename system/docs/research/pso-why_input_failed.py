"""Why did the input job fail on the agent-owned session? Read the exact error.

The session launched fine (21 s, `succeeded`, "Running natively"), so the emulator works. But an input job took 11.5 s and returned False, and the game is
still at the title (floor 0, player null). The job's own error says which side refused it:

  * "agent_owned" / "operator session" -> input is reserved for sessions the operator launched, and the fix is a launch from their side;
  * a worker timeout or a stuck queue -> the worker is the problem, and a different fix applies;
  * something about the adapter -> possibly solvable.

So: submit one input job and print its terminal state and error verbatim, with the queue checked around it.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402


def queue_depth():
    try:
        rows = S._call("/api/jobs?state=queued,running")
        rows = rows if isinstance(rows, list) else (rows.get("items") or [])
        return len(rows)
    except Exception:                                             # noqa: BLE001
        return -1


sid = S.session_id()
worker = sid.split("-")[0]
print("session:", sid, "| worker:", worker, "| queue before:", queue_depth())

body = {"tool": "session_op",
        "input": {"session_id": sid, "op": "send_input", "args": {"events": [{"key": "start", "down": True}]}},
        "require_worker": worker, "agent_use": False}
try:
    job = S._call("/api/jobs", "POST", body)
except Exception as exc:                                          # noqa: BLE001
    print("SUBMIT FAILED:", type(exc).__name__, str(exc)[:300])
    raise SystemExit(1)

print("job:", job.get("id"), "| state:", job.get("state"))
for step in range(20):
    time.sleep(2)
    state = S._call(f"/api/jobs/{job.get('id')}")
    if state.get("state") in ("succeeded", "failed", "cancelled"):
        print("FINAL:", state.get("state"))
        print("error:", str(state.get("error"))[:400])
        print("output:", json.dumps(state.get("output") or {})[:400])
        break
    print(f"  t+{step * 2}s {state.get('state')} queue={queue_depth()}")
else:
    print("no terminal state after 40 s; queue:", queue_depth())
    try:
        S._call(f"/api/jobs/{job.get('id')}/cancel", "POST")
        print("cancelled the probe job")
    except Exception as exc:                                      # noqa: BLE001
        print("cancel failed:", str(exc)[:120])
