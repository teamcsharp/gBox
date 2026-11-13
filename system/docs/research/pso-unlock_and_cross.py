"""Unlock the doors in RAM as the bot walks up to them - no waiting, no target needed.

Two faults are visible in the last attempt:

1. **It stopped at 12 units and pressed A from there.** The interaction range is far shorter than that, so A did nothing for ninety steps. The green triangles in the operator's screenshots
   appear when the game considers something action-able, which is close range and facing.
2. **The flag write went to the wrong floor.** Last round's arming logged `gates: floor 0: all gates open` - but the character is in the Forest, and floor 1 is the Forest. It had read the group
   pointer while still in the city (floor 0) and unlocked the city.

So the door handling becomes exactly what the operator asked for - **flip the switch with its mind as it approaches**:

* every iteration, read the current floor from `0x805D5FC0` and, if that floor's 32-byte flag group is not already all `0xFF`, **write it and verify the read-back**;
* that unlocks the doors on whichever floor the character is actually standing on, without a button, a target, or proximity;
* then still walk to within **6 units** of the affordance and press A - because some panels gate on the press itself rather than only on the flag, and because it costs nothing.

The `A` press is the belt to the flags' braces; the flags are the part that makes it work at walking pace.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_coop_gates                                   # noqa: E402
from pso_pad import Pad, call                                      # noqa: E402

DIRECTIONS = ("up", "down", "left", "right")
STAGE_FLAG_BASE = 0x80515CC8
STAGE_FLAG_GROUP_PTR = 0x805D5FC0
STAGE_GROUP_SIZE = 32
PRESS_RANGE = 6.0


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def read(pad, address, length):
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": address, "length": length}}, "POST")
    try:
        return bytes.fromhex(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def write(pad, address, blob):
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address,
                                       "hex_bytes": blob.hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.35)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return True
    return False


def unlock_floor(pad):
    """Set every stage flag for the floor the character is standing on right now."""
    floor_blob = read(pad, STAGE_FLAG_GROUP_PTR, 4)
    if not floor_blob:
        return "no floor"
    floor = int.from_bytes(floor_blob, "big")
    if not 0 <= floor < 18:
        return f"floor {floor} out of range"
    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    group = read(pad, address, STAGE_GROUP_SIZE)
    if group == b"\xff" * STAGE_GROUP_SIZE:
        return f"floor {floor} already open"
    write(pad, address, b"\xff" * STAGE_GROUP_SIZE)
    time.sleep(0.25)
    after = read(pad, address, STAGE_GROUP_SIZE)
    full = bytes([255] * STAGE_GROUP_SIZE)
    state_word = "unlocked" if after == full else "write failed"
    return f"floor {floor} {state_word}"


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def affordance(pad, skip_switches):
    now = state(pad)
    player = now.get("player") or {}
    rows = pso_coop_gates.forward_candidates(now.get("entities") or [], player.get("room"),
                                             float(player.get("x") or 0), float(player.get("z") or 0),
                                             skip_switches=skip_switches)
    return (rows[0] if rows else None), player


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    print("floor unlock at start:", unlock_floor(pad))

    room_start = (state(pad).get("player") or {}).get("room")
    side, misses = 1, 0
    for step in range(100):
        if step % 6 == 0:
            print(f"  [{step:3d}] {unlock_floor(pad)}")      # unlock as it goes, on whatever floor it is now
        row, player = affordance(pad, skip_switches=False)
        if not row:
            print("no affordances left")
            break
        is_switch, distance, gkey, entity, kind = row
        room_now = player.get("room")
        if room_now != room_start:
            print(f"\n*** CROSSED: room {room_start} -> {room_now} at step {step} ***")
            break
        if step % 3 == 0:
            print(f"  {step:3d}: room {room_now} | {kind} {entity.get('class')} {distance:5.1f} away | hp {player.get('hp')}")

        if distance <= PRESS_RANGE:
            tap(pad, "b")
            time.sleep(0.1)
            tap(pad, "a")           # press the panel
            time.sleep(0.3)
            hold(pad, "up", 1.0)    # and step through the unlocked door
            time.sleep(0.25)
            continue

        before = distance
        hold(pad, "left" if side > 0 else "right", 0.18)
        hold(pad, "up", 0.7)
        time.sleep(0.2)
        row_after, _ = affordance(pad, skip_switches=False)
        after = row_after[1] if row_after else before
        if after < before - 1.0:
            misses = 0
        else:
            misses += 1
            if misses >= 4:
                side = -side
                misses = 0

    final = state(pad).get("player") or {}
    print(f"\nfinal room {final.get('room')} | pos ({final.get('x')}, {final.get('z')})")
