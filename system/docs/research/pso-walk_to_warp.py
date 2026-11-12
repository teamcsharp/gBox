"""Walk to Pioneer 2's warp door and enter the Forest.

The semantic profile names the target outright:

```
slot 24  room 10  (254.0, 25.0)  TObjCityDoor_Warp  [object]      <- the warp
player  room 10  (228.995, 253.999)                                <- where we are
```

`explore` needs doors and enemies, which the city has none of - the field does. So: calibrate what each direction does to `(x, z)` with a short hold, then step toward the
warp, re-measuring after every move, and press A when close. This is path-guiding with the profile the bot already reads, not a scripted route.
"""
import struct
import time

from pso_pad import Pad, call

TARGET = (254.0, 25.0)
TOLERANCE = 22.0


def read_state(pad: Pad) -> dict:
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST")
    return (state or {}).get("player") or {}


def position(pad: Pad) -> tuple | None:
    player = read_state(pad)
    if not player:
        return None
    return (float(player.get("x") or 0.0), float(player.get("z") or 0.0))


def hold(pad: Pad, key: str, secs: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    start = position(pad)
    print("start:", start, "-> target", TARGET)
    if not start:
        raise SystemExit("no player")

    # calibrate: a short hold of each direction, measuring what it does to (x, z)
    effects = {}
    for key in ("up", "down", "left", "right"):
        before = position(pad)
        hold(pad, key, 0.45)
        time.sleep(0.5)
        after = position(pad)
        if before and after:
            effects[key] = (round(after[0] - before[0], 1), round(after[1] - before[1], 1))
        print(f"  {key:5s}: {before} -> {after} | delta {effects.get(key)}")

    # which key reduces each axis
    def best_key(axis: int, want: float) -> str:
        scored = []
        for key, (dx, dz) in effects.items():
            delta = (dx, dz)[axis]
            if abs(delta) < 0.5:
                continue
            scored.append((abs(delta), key if (delta > 0) == (want > 0) else None))
        scored = [row for row in scored if row[1]]
        return max(scored)[1] if scored else ""

    for step in range(30):
        now = position(pad)
        if not now:
            print("player lost")
            break
        dx, dz = TARGET[0] - now[0], TARGET[1] - now[1]
        dist = (dx * dx + dz * dz) ** 0.5
        print(f"  step {step:2d}: {now} | to target ({dx:7.1f},{dz:7.1f}) | dist {dist:6.1f}")
        if dist <= TOLERANCE:
            print("\nAT THE WARP - pressing A")
            pad.press("a")
            time.sleep(4)
            print("after A:", position(pad), "| player ptr:", pad.player_pointer())
            print("shot:", pad.shot("after_warp"))
            break
        axis = 0 if abs(dx) >= abs(dz) else 1
        key = best_key(axis, (dx, dz)[axis])
        if not key:
            print("  no key moves that axis")
            break
        secs = min(1.6, max(0.35, abs((dx, dz)[axis]) / 90.0))
        hold(pad, key, secs)
        time.sleep(0.4)
