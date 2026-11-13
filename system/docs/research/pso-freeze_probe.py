"""Catch the freeze and find out what it actually is.

The character stops accepting movement, intermittently, and nothing in the input path is wrong: the pad reads correctly, injection moves it 30-73 units when it works, the session is live, and the game runs
at 30 fps. The relocation unstuck frees it *sometimes*, which means the freeze is not a single thing.

So this probe does not guess - it **catches** a freeze and gathers everything that could distinguish the causes:

1. press `up`; if the position does not change, a freeze is in progress;
2. **try every direction** - if any moves, it was a blocked direction, not a lock;
3. **nearest entity distance** - something within ~3 units is a body or wall pressing on the character;
4. **player state** - hp, room, y; a y far from the room's floor suggests a ledge;
5. **entity count** - a sudden drop means the area is unloading (a warp or a transition);
6. repeat the `up` test after all of that, to see whether trying the other directions freed it.

Every branch corresponds to a cause that has already been seen once in this session, so the output names the cause instead of describing symptoms.
"""
import math
import time

from pso_pad import Pad, call

DIRECTIONS = ("up", "down", "left", "right")


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def pos(pad):
    player = (state(pad).get("player") or {})
    return (float(player.get("x") or 0), float(player.get("z") or 0)), player


def nudge(pad, key, seconds=0.8):
    before, _ = pos(pad)
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    pad.send([{"key": k, "down": False} for k in DIRECTIONS])
    time.sleep(0.35)
    after, _ = pos(pad)
    return math.dist(before, after)


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)

    for attempt in range(12):
        moved = nudge(pad, "up")
        if moved > 2.0:
            print(f"  attempt {attempt}: moving ({moved:.1f} units)")
            continue

        print(f"\n*** FROZEN at attempt {attempt} ***")
        where, player = pos(pad)
        print(f"  position: {tuple(round(v) for v in where)} | y {player.get('y')} | room {player.get('room')} | hp {player.get('hp')}")

        current = state(pad)
        entities = current.get("entities") or []
        print(f"  entities in the area: {len(entities)}")
        nearest = None
        for entity in entities:
            if entity.get("kind") == "player" or entity.get("x") is None:
                continue
            distance = math.hypot(float(entity.get("x") or 0) - where[0], float(entity.get("z") or 0) - where[1])
            if nearest is None or distance < nearest[0]:
                nearest = (distance, entity.get("kind"), entity.get("class"))
        if nearest:
            print(f"  nearest entity: {nearest[1]} {nearest[2]} at {nearest[0]:.1f} units")

        print("  trying every direction:")
        freed_by = None
        for key in DIRECTIONS:
            moved = nudge(pad, key)
            print(f"    {key:5s}: {moved:5.1f} units")
            if moved > 2.0 and freed_by is None:
                freed_by = key
        tail = nudge(pad, "up")
        print(f"  up again afterwards: {tail:.1f} units")

        if freed_by:
            print(f"  VERDICT: a blocked direction - {freed_by} freed it")
        elif nearest and nearest[0] < 4.0:
            print(f"  VERDICT: pressed against {nearest[1]} {nearest[2]} at {nearest[0]:.1f} units")
        elif tail > 2.0:
            print("  VERDICT: the direction sweep freed it - a corner")
        else:
            print("  VERDICT: a genuine lock - nothing moved it")
        break
    else:
        print("\nnever froze during 12 attempts")
