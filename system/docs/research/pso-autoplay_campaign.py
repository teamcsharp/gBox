"""Start the co-op campaign on the co-op session - the plane's own two-player PSO driver.

`pso_campaign` defines CAMPAIGN = "pso-episodes-1-2" and COOP_CAMPAIGN = "pso-coop-episodes-1-2", and its `play(ad, send, stopped, ...)` loop combines
"the existing semantic combat driver with a vision planner for menus, healing and routes that have no recorded mission". For a co-op session the right
one is the co-op campaign, and it drives the session's own pads rather than the keyboard - which is what an agent-owned, headless emulator needs.

Mission mode failed earlier with "no player in semantic state" because there is no character yet; the campaign is the mode that gets a character.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"
CAMPAIGN = "pso-coop-episodes-1-2"


def call(op, extra=None, wait=180):
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


stop = call("stop", wait=60)
print("stop:", stop.get("state"), "|", json.dumps(stop.get("output") or {})[:160])
time.sleep(3)

start = call("start", {"campaign": CAMPAIGN})
print("start campaign:", start.get("state"), "| error:", str(start.get("error"))[:200])
print("output:", json.dumps(start.get("output") or {})[:500])

for round_index in range(12):
    time.sleep(12)
    status = call("status", wait=60)
    result = (status.get("output") or {}).get("result") or {}
    print(f"t+{(round_index + 1) * 12:3d}s running={result.get('running')} steps={result.get('steps')} "
          f"mode={result.get('mode')} mission={result.get('mission')} last={json.dumps(result.get('last'))[:110]}")
