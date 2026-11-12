"""Ask the plane's autoplay what it can do, on the co-op session.

`autoplay` is documented as "let gBox play the live game (take control): runs a scripted mission (navigate / interact / fight) through the session's
debugger". Driving through the **debugger** rather than the keyboard is the important part: it means an agent-owned session can be played, which the
keyboard path never could.

It is a job, dispatched with `require_worker` and `agent_use: false` - the combination that was shown to work.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

SESSION = "bcd14c8d972940b2-c25969f531a04870"
WORKER = "bcd14c8d972940b2"


def run(body, wait=90):
    created = S._call("/api/jobs", "POST", body)
    job_id = created.get("id")
    deadline = time.time() + wait
    while time.time() < deadline:
        job = S._call(f"/api/jobs/{job_id}")
        if job.get("state") in ("succeeded", "failed"):
            return job
        time.sleep(2)
    return {"state": "timeout"}


def main():
    for op in ("list", "status"):
        body = {"tool": "autoplay", "input": {"session_id": SESSION, "op": op},
                "require_worker": WORKER, "agent_use": False}
        job = run(body, 60)
        print(f"--- autoplay {op}: {job.get('state')}")
        if job.get("error"):
            print("   error:", str(job["error"])[:300])
        output = job.get("output") or {}
        print("   output:", json.dumps(output)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
