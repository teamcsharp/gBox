"""Stop the stuck vision autoplay, then start the deterministic boot mission.

`start` came back `{"already_running": "vision: make progress"}` - a vision-mode autoplay is already running, reporting 0 steps and the same `'choices'`
error every poll, so it is stuck and blocking every other mission. Stopping it is the only way to take over, and it is not a loss: a loop that has
taken no steps and fails the same way every attempt is doing nothing for the game.

Then the deterministic mission runs: `pso-boot-from-title-a`, "break the attract loop and reach the field from a cold title (deterministic, no model)".
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"
MISSION = "pso-boot-from-title-a"


def call(op, extra=None, wait=150):
    body = {"tool": "autoplay", "input": {"session_id": SESSION, "op": op, **(extra or {})},
            "require_worker": WORKER, "agent_use": False}
    created = S._call("/api/jobs", "POST", body)
    job_id = created.get("id")
    deadline = time.time() + wait
    while time.time() < deadline:
        state = S._call(f"/api/jobs/{job_id}")
        if state.get("state") in ("succeeded", "failed"):
            return state
        time.sleep(2)
    return {"state": "timeout"}


stopped = call("stop")
print("stop:", stopped.get("state"), "|", json.dumps(stopped.get("output") or {})[:200])
time.sleep(4)

started = call("start", {"mission": MISSION})
print("start:", started.get("state"), "| error:", str(started.get("error"))[:200])
print("output:", json.dumps(started.get("output") or {})[:500])

for round_index in range(12):
    time.sleep(12)
    status = call("status", wait=60)
    result = (status.get("output") or {}).get("result") or {}
    print(f"t+{(round_index + 1) * 12:3d}s  running={result.get('running')} steps={result.get('steps')} "
          f"mission={result.get('mission')} last={json.dumps(result.get('last'))[:100]}")
    if result.get("steps") and result.get("steps") > 0:
        print("  the mission is taking steps")
        break
