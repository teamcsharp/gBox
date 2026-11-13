"""Measure what `move_speed` actually does to traversal, before trusting it.

`pso_mods` documents `factor` as "the player moves N times faster (1 = off)" and it is the one speed lever not yet tested. Since the objective now asks for "the fastest rate"
and for finishing the game, a faster *traversal* matters as much as a faster emulator - and unlike emulation speed this is not bound by Dolphin's serial execution.

The measurement: hold one direction for a fixed time, read the position before and after, and compute units per second. Then set `move_speed` and repeat identically. Anything
else (same direction, same hold, same session) would confound the result.

Baseline first, then factor 3, then factor 1 to put it back - each verified by the same measurement rather than by the call's own success.
"""
import math
import time

from pso_pad import Pad, call


def player(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state.get("player") or {}


def mods(pad, payload, wait=45.0):
    job = call("/api/jobs", {"tool": "pso_mods", "require_worker": pad.worker,
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


def travel(pad, seconds=1.4) -> float:
    """Walk forward for `seconds` and return units per second."""
    before = player(pad)
    start = (float(before.get("x") or 0), float(before.get("z") or 0))
    pad.send([{"key": "up", "down": True}])
    time.sleep(seconds)
    pad.send([{"key": "up", "down": False}])
    time.sleep(0.5)
    after = player(pad)
    end = (float(after.get("x") or 0), float(after.get("z") or 0))
    return round(math.dist(start, end) / seconds, 1)


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    me = player(pad)
    print("start: hp", me.get("hp"), "/", me.get("hp_max"), "| room", me.get("room"))

    # two baselines, so a single lucky sample cannot be mistaken for a change
    base = [travel(pad) for _ in range(2)]
    print("baseline units/s:", base)

    answer = mods(pad, {"op": "move_speed", "factor": 3})
    print("move_speed factor 3:", answer.get("state"), "|", str(answer.get("error"))[:130],
          "|", str(answer.get("output"))[:160])
    time.sleep(1.0)

    fast = [travel(pad) for _ in range(2)]
    print("factor 3 units/s:", fast)

    print("\nputting it back to 1")
    print("move_speed factor 1:", mods(pad, {"op": "move_speed", "factor": 1}).get("state"))
    time.sleep(1.0)
    back = [travel(pad) for _ in range(2)]
    print("factor 1 units/s:", back)

    ratio = (sum(fast) / 2) / (sum(base) / 2) if sum(base) else None
    print(f"\nmeasured ratio: {ratio:.2f}x" if ratio else "\nno baseline")
    print("shot:", pad.shot("move_speed"))
