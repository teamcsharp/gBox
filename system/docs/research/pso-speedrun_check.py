"""Speedrunning check: the bot playing at 4.2x while it actually progresses through the floor.

Speedrunning here means three things measured at once:

* **speed** - fast-forward on, with the frame rate from the game's own counter at `0x805D53A4`;
* **movement** - the character's position sampled over time, not just the frame rate;
* **progress** - the `room` field changing, which means it is moving through the area rather than circling one spot.

The cave the bot is in has 130 entities and 7 gates; walking through the gates is how a PSO floor is traversed, so a rising set of rooms is the real signal that it is playing
rather than idling.
"""
import json
import time

from pso_pad import Pad, call

COUNTER = 0x805D53A4


def snapshot(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def counter(pad):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": COUNTER, "length": 4}}, "POST")
    try:
        return int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                              # noqa: BLE001
        return None


def session_op(pad, op, args) -> str:
    job = call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "op": op, "args": args}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(40):
        time.sleep(0.5)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return str(row.get("state"))
    return "timeout"


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    state = snapshot(pad)
    player = state.get("player") or {}
    print("start: room", player.get("room"), "| entities", len(state.get("entities") or []),
          "| pos", (player.get("x"), player.get("z")))

    print("\nfast_forward:", session_op(pad, "fast_forward", {"on": True}))
    time.sleep(2)

    first = counter(pad)
    rooms, spots = [], []
    started = time.time()
    for index in range(10):
        time.sleep(3)
        now = counter(pad)
        state = snapshot(pad)
        player = state.get("player") or {}
        spot = (round(float(player.get("x") or 0), 1), round(float(player.get("z") or 0), 1))
        rooms.append(player.get("room"))
        spots.append(spot)
        print(f"  {index + 1}: room {player.get('room')} | {spot} | counter {now}")

    elapsed = time.time() - started
    second = counter(pad)
    moved = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(spots, spots[1:]))
    distinct = sorted({r for r in rooms if r is not None})

    print()
    print("frames/s:", round((second - first) / elapsed, 1) if first is not None and second else None)
    print("movement:", round(moved, 1), "units in", round(elapsed, 1), "s")
    print("rooms visited:", distinct)
    print("PROGRESSING" if len(distinct) > 1 else "in one room (not progressing yet)")
    print("shot:", pad.shot("speedrun"))
