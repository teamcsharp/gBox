"""Give the character the best weapons the disc and its class allow.

The operator's requirement: *"the bot must have the best weapons and fight properly"* - and it is the gate on Ultimate, because PSO offers Ultimate at level 80 while BQF is level 5
with 68 HP.

`pso_loadout` is built for exactly this. Its own contract:

* `op=plan` - "returns an exact disc/class-matched list", presets `community`, `hunter`, `ranger`, `force`, and **`atp` "a measured ATP-only ranking"**;
* `op=drop` - "sends one of each planned item through the verified live PSO channel, requires session_id and memory_write";
* it refuses online play and unknown revisions, and never retries a timed-out mutation.

So: plan the HUmar's best weapons by ATP, then drop them into the live session. **`op=drop` mutates, so it is called once and its result is read, never retried** - a timed-out
mutation is treated as unknown rather than repeated.
"""
import json
import time

from pso_pad import Pad, call

CLASS = "HUmar"


def run(pad: Pad, payload: dict, wait: float = 60.0) -> dict:
    job = call("/api/jobs", {"tool": "pso_loadout", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, **payload}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    if not job_id:
        return {"submitted": False, "answer": job}
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"state": "timeout"}


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    print("\n=== plan: HUmar, measured ATP ranking ===")
    plan = run(pad, {"op": "plan", "character_class": CLASS, "preset": "atp", "count": 10})
    print("state:", plan.get("state"), "| error:", str(plan.get("error"))[:160])
    print(json.dumps(plan.get("output"))[:1500])

    if plan.get("state") != "succeeded":
        print("\n=== retry with the hunter preset ===")
        plan = run(pad, {"op": "plan", "character_class": CLASS, "preset": "hunter", "count": 10})
        print("state:", plan.get("state"), "| error:", str(plan.get("error"))[:160])
        print(json.dumps(plan.get("output"))[:1500])

    print("\n=== drop: send them into the live game (single attempt, never retried) ===")
    drop = run(pad, {"op": "drop", "character_class": CLASS, "preset": "atp", "count": 10}, wait=90)
    print("state:", drop.get("state"), "| error:", str(drop.get("error"))[:200])
    print(json.dumps(drop.get("output"))[:900])
