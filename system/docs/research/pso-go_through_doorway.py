"""Go through the doorway: walk to the nearest gate and cross it.

The operator's instruction is direct - the switch is pressed, so take the doorway. This does exactly that and nothing else, so the result is unambiguous:

1. read the player position and every `gate` entity the state exposes;
2. pick the nearest gate and hill-climb toward it - turn a side, step, and keep that side only if the measured distance fell;
3. within reach, press **A** (the door's activation), then walk forward;
4. report the room before and after, so a crossing is proved by the room changing rather than assumed.

Every direction release sends all four at once (`up:False` alone pins the stick hard left - measured), and each step re-reads the player rather than trusting the last read.
"""
import math
import time

from pso_pad import Pad, call

DIRECTIONS = ("up", "down", "left", "right")
REACH = 22.0        # close enough to activate and step through


def state(pad):
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def tap(pad, key):
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def nearest_gate(now):
    player = now.get("player") or {}
    gates = [e for e in (now.get("entities") or [])
             if str(e.get("kind")) == "gate" and e.get("x") is not None and e.get("z") is not None]
    if not gates:
        return None, player
    x, z = float(player.get("x") or 0), float(player.get("z") or 0)
    gate = min(gates, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
    distance = math.hypot(float(gate.get("x") or 0) - x, float(gate.get("z") or 0) - z)
    return (gate, distance, len(gates)), player


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    now = state(pad)
    found, player = nearest_gate(now)
    if not found:
        print("no gates listed in this room")
        raise SystemExit(0)
    gate, distance, total = found
    print(f"room {player.get('room')} | {total} gates | nearest at "
          f"({gate.get('x'):.1f},{gate.get('z'):.1f}) {distance:.1f} units away")
    room_start = player.get("room")

    side, misses = 1, 0
    for step in range(90):
        now = state(pad)
        found, player = nearest_gate(now)
        if not found:
            print("gates disappeared from the entity list")
            break
        gate, distance, _ = found
        room_now = player.get("room")
        if room_now != room_start:
            print(f"\n*** CROSSED: room {room_start} -> {room_now} after {step} steps ***")
            break
        if step % 5 == 0:
            print(f"  {step:2d}: room {room_now} | gate ({gate.get('x'):.1f},{gate.get('z'):.1f}) {distance:5.1f} away | hp {player.get('hp')}")

        if distance <= REACH:
            tap(pad, "b")            # a pause menu would eat the A press
            time.sleep(0.12)
            tap(pad, "a")            # activate the door / switch
            time.sleep(0.30)
            hold(pad, "up", 1.0)     # step through
            time.sleep(0.25)
            tap(pad, "a")
            time.sleep(0.2)
            continue

        before = distance
        hold(pad, "left" if side > 0 else "right", 0.18)
        hold(pad, "up", 0.75)
        time.sleep(0.25)
        found_after, _ = nearest_gate(state(pad))
        after = found_after[1] if found_after else before
        if after < before - 1.0:
            misses = 0
        else:
            misses += 1
            if misses >= 4:
                side = -side
                misses = 0

    final = state(pad).get("player") or {}
    print(f"\nfinal room {final.get('room')} | pos ({final.get('x')}, {final.get('z')})")
