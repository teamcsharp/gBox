"""Start the plane's deterministic boot mission on the co-op session: title screen -> the field.

The autoplay tool reports a list of named PSO missions, including `pso-boot-from-title-a` - "break the attract loop and reach the field from a cold
title (deterministic, no model)". That is exactly the state the co-op session is in, and "deterministic, no model" matters because the currently
running vision mode is failing with a `'choices'` error, which is a model response problem rather than a game problem.

Autoplay drives through the session's **debugger**, not the keyboard, so it can play a session the keyboard path cannot reach - which is what an
agent-owned session is.

This starts the mission, then polls status to report the steps taken and any error, so the outcome is measured rather than assumed.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"
MISSION = "pso-boot-from-title-a"


def job(body, wait=120):
    created = S._call("/api/jobs", "POST", body)
    job_id = created.get("id")
    deadline = time.time() + wait
    while time.time() < deadline:
        state = S._call(f"/api/jobs/{job_id}")
        if state.get("state") in ("succeeded", "failed"):
            return state
        time.sleep(2)
    return {"state": "timeout", "id": job_id}


def call(op, extra=None):
    body = {"tool": "autoplay", "input": {"session_id": SESSION, "op": op, **(extra or {})},
            "require_worker": WORKER, "agent_use": False}
    return job(body, 150)


started = call("start", {"mission": MISSION})
print("start:", started.get("state"), "| error:", str(started.get("error"))[:200])
print("output:", json.dumps(started.get("output") or {})[:400])

for round_index in range(10):
    time.sleep(12)
    status = call("status")
    result = (status.get("output") or {}).get("result") or {}
    print(f"t+{(round_index + 1) * 12:3d}s  running={result.get('running')} steps={result.get('steps')} "
          f"mission={result.get('mission')} last={json.dumps(result.get('last'))[:90]}")
    if result.get("last", {}).get("ok"):
        print("  last step succeeded")
    if not result.get("running"):
        print("  autoplay stopped")
        break
