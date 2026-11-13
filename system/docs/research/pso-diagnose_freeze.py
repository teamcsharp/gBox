"""Why does the character stop moving? Test `walk_through` as the cause.

The freeze is state-dependent, not a dead input path: the same `session_id` + `send_input` moved the character **211 units through a gate** and then **206 units of exploration**,
yet at `(490.6, 380.7)` it sat frozen for forty rounds while enemies moved around it.

`walk_through` disables collision. That is exactly the kind of change that can leave a character **inside** geometry - and a character embedded in a wall has no legal move, so
every direction is refused while the rest of the world keeps animating. It is on in every cycle because it is in the arming step, and the NPC conversation lock earlier looked
identical from the outside (position frozen, world live).

So: read the full transform (x, **y**, z, angle, room) - a `y` that drifts or sits below the floor is the tell - then turn `walk_through` **off** and repeat the identical movement
test. If movement returns with it off, the mod is the cause and arming should not enable it blind.
"""
import json
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
        return {"state": "rejected", "error": str(job)[:120]}
    deadline = time.time() + wait
    while time.time() < deadline:
        time.sleep(1.5)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return {"state": row.get("state"), "error": row.get("error"),
                    "output": (row.get("output") or {}).get("result")}
    return {"state": "timeout"}


def try_move(pad, seconds=1.2) -> float:
    before = player(pad)
    start = (float(before.get("x") or 0), float(before.get("z") or 0))
    pad.send([{"key": "up", "down": True}])
    time.sleep(seconds)
    pad.send([{"key": "up", "down": False}])
    time.sleep(0.5)
    after = player(pad)
    end = (float(after.get("x") or 0), float(after.get("z") or 0))
    return round(math.dist(start, end), 1)


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    me = player(pad)
    print("transform: x %s  y %s  z %s  angle %s  room %s  hp %s/%s"
          % (me.get("x"), me.get("y"), me.get("z"), me.get("angle"), me.get("room"),
             me.get("hp"), me.get("hp_max")))
    print(json.dumps(me)[:400])

    # y is the tell: a character below the floor or drifting in y is embedded / falling
    print("\nmovement with walk_through ON (current):", [try_move(pad) for _ in range(2)])

    answer = mods(pad, {"op": "walk_through", "on": False})
    print("\nwalk_through off:", answer.get("state"), str(answer.get("error"))[:100])
    time.sleep(1.5)
    print("movement with walk_through OFF:", [try_move(pad) for _ in range(3)])

    me = player(pad)
    print("\ntransform now: x %s  y %s  z %s  room %s" % (me.get("x"), me.get("y"), me.get("z"), me.get("room")))
    print("shot:", pad.shot("walk_through_off"))
