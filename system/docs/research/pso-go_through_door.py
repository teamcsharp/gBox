"""Walk through the door using the game's own affordance model - not vision, not guesswork.

The operator's requirement is that the bot *recognises* doors and switches from memory. The app already has that classifier - `pso_coop_gates.forward_candidates` - and it encodes
precisely the knowledge needed:

```
SWITCH_CLASSES = {'TLazerFenceSw', 'TObjDoorKey'}
DOOR_CLASSES   = {'TObjDoor', 'TObjLazerFenceNorm', 'TOBarrierEnergy01'}
FORWARD_CLASSES = SWITCH_CLASSES | DOOR_CLASSES
```

> *"Switches/panels (is_switch=0) sort before doors (is_switch=1) so the gate is opened before it is crossed; nearest-first within a class."*

and, crucially for this session:

> *"`skip_switches` drops the panels entirely - used once the room's gate flags are already set (pressing a done panel is pointless; the job is now to walk THROUGH the open door)."*

**The flags for this floor are already set** (`ff` x 32, verified last round), so the switches are done and the job is to walk through the open door. So this asks `forward_candidates` with
`skip_switches=True` and steers at the door it names - nearest-first, by measured distance, with the hill-climb that does not trust `heading_deg`.

That is the recognition path the operator asked for: the entity **classes** come from memory, the classifier is the game's own documented model, and nothing is inferred from a picture.
"""
import math
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\system")

from gbox import pso_coop_gates                                   # noqa: E402
from pso_pad import Pad, call                                      # noqa: E402

DIRECTIONS = ("up", "down", "left", "right")


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def target(pad, skip_switches):
    now = state(pad)
    player = now.get("player") or {}
    entities = now.get("entities") or []
    rows = pso_coop_gates.forward_candidates(entities, player.get("room"), float(player.get("x") or 0),
                                             float(player.get("z") or 0), skip_switches=skip_switches)
    return (rows[0] if rows else None), player, len(rows)


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    skip = "--switches" not in sys.argv

    row, player, count = target(pad, skip)
    if not row:
        print("no door/switch affordances in this floor")
        raise SystemExit(0)
    is_switch, distance, gkey, entity, kind = row
    print(f"room {player.get('room')} | {count} forward affordances | nearest {kind} "
          f"{entity.get('class')} at ({entity.get('x'):.1f},{entity.get('z'):.1f}) {distance:.1f} away")
    room_start = player.get("room")

    side, misses = 1, 0
    for step in range(90):
        row, player, _ = target(pad, skip)
        if not row:
            print("no affordance left")
            break
        is_switch, distance, gkey, entity, kind = row
        room_now = player.get("room")
        if room_now != room_start:
            print(f"\n*** CROSSED: room {room_start} -> {room_now} at step {step} ***")
            break
        if step % 4 == 0:
            print(f"  {step:2d}: room {room_now} | {kind} {entity.get('class')} {distance:5.1f} away | hp {player.get('hp')}")

        if distance <= 18.0:
            # at the affordance: activate it (harmless if already set) and step through
            tap(pad, "b")
            time.sleep(0.12)
            tap(pad, "a")
            time.sleep(0.35)
            hold(pad, "up", 1.1)
            time.sleep(0.3)
            continue

        before = distance
        hold(pad, "left" if side > 0 else "right", 0.18)
        hold(pad, "up", 0.75)
        time.sleep(0.25)
        row_after, _, _ = target(pad, skip)
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
