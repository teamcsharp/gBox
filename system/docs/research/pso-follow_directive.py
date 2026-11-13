"""Honour the operator's map directive: read `pso-directive.json` and walk the bot to that point.

`pso_map.parse_directive` defines the operator's interface exactly:

```
{"op": "goto",   "x": <float>, "z": <float>, "episode": int, "floor": int, "room": int, "id": str}
{"op": "attack", "ptr": "80..."}  or  {"op": "attack", "x": <float>, "z": <float>}
{"op": "press",  "flag": 0..255}
{"op": "clear"}
```

with optional `episode`/`floor`/`room` scope carried "for the controller to match against live state (a stale-scope directive must not act)". That is the mechanism behind the red arrow on the minimap: **the operator marks a point, the controller walks there.**

`pso-coop` is the process that normally consumes it, and it is not running in this build - so this reader does the job from the same file, with the same validation: a directive whose `episode`/`floor`/`room` does not match the live state is **refused rather than acted on**.

Walking uses the tank controls with the measured polarity (`left` increases `heading_deg`, `right` decreases it), and the same measuring unstick, because a blocked direction retried
forever is what every stall in this session looked like.
"""
import json
import math
import os
import time
from pathlib import Path

from pso_pad import Pad, call

CANDIDATES = [
    Path(r"D:\gBox\runtime\pso-directive.json"),
    Path(r"C:\_tools\gBox\system\gbox-data\pso-directive.json"),
    Path(r"D:\gBox\pso-directive.json"),
]
MELEE = 40.0


def directive() -> tuple[dict | None, Path | None]:
    """Newest readable directive file, validated the way pso_map does."""
    best = None
    for path in CANDIDATES:
        try:
            if path.is_file():
                stamp = path.stat().st_mtime
                if best is None or stamp > best[0]:
                    best = (stamp, path)
        except OSError:
            continue
    if not best:
        return None, None
    try:
        raw = json.loads(best[1].read_text(encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return None, best[1]
    op = str(raw.get("op", "")).lower()
    if op not in ("goto", "press", "attack", "clear"):
        return None, best[1]
    clean = {"op": op, "id": str(raw.get("id", "")) or None}
    for key in ("episode", "floor", "room"):
        if type(raw.get(key)) is int:
            clean[key] = raw[key]
    if op in ("goto", "attack"):
        if isinstance(raw.get("x"), (int, float)) and isinstance(raw.get("z"), (int, float)):
            clean["x"], clean["z"] = float(raw["x"]), float(raw["z"])
        elif op == "attack" and isinstance(raw.get("ptr"), str):
            clean["ptr"] = raw["ptr"]
        else:
            return None, best[1]
    if op == "press":
        if type(raw.get("flag")) is int and 0 <= raw["flag"] <= 255:
            clean["flag"] = raw["flag"]
        else:
            return None, best[1]
    return clean, best[1]


def player(pad):
    state = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}
    return state


def in_scope(clean: dict, state_now: dict) -> bool:
    me = state_now.get("player") or {}
    for key, value in (("floor", None), ("room", me.get("room"))):
        if key in clean and value is not None and clean[key] != value:
            return False
    return True


def hold(pad, key, secs):
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def walk_to(pad, target_x, target_z, budget=90.0) -> str:
    started = time.time()
    last = None
    stuck = 0
    while time.time() - started < budget:
        state_now = player(pad)
        me = state_now.get("player") or {}
        if not me:
            return "no player"
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        distance = math.hypot(target_x - x, target_z - z)
        if distance < 18:
            return f"arrived ({distance:.1f} away)"

        if last and abs(x - last[0]) < 0.8 and abs(z - last[1]) < 0.8:
            stuck += 1
        else:
            stuck = 0
        last = (x, z)

        if stuck >= 2:
            for key in ("up", "left", "right", "down"):
                before = player(pad).get("player") or {}
                b = (float(before.get("x") or 0), float(before.get("z") or 0))
                hold(pad, key, 0.6)
                time.sleep(0.15)
                after = player(pad).get("player") or {}
                a = (float(after.get("x") or 0), float(after.get("z") or 0))
                if math.dist(b, a) > 1.0:
                    break
            stuck = 0
            continue

        want = (math.degrees(math.atan2(target_x - x, target_z - z)) + 360.0) % 360.0
        error = ((want - float(me.get("heading_deg") or 0) + 540.0) % 360.0) - 180.0
        if abs(error) > 20:
            hold(pad, "left" if error > 0 else "right", min(0.4, max(0.12, abs(error) / 240.0)))
        else:
            hold(pad, "up", min(1.0, max(0.3, distance / 260.0)))
        time.sleep(0.15)
    return "ran out of time"


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid)
    clean, path = directive()
    print("directive file:", path)
    print("directive:", json.dumps(clean))
    if not clean:
        print("\nno valid directive yet - write one to", path or CANDIDATES[0])
        print('example: {"op":"goto","x":250.0,"z":600.0,"room":15}')
        raise SystemExit(0)

    state_now = player(pad)
    if not in_scope(clean, state_now):
        print("REFUSED: the directive's scope does not match the live state (stale)")
        me = state_now.get("player") or {}
        print("live room:", me.get("room"), "| directive:", clean.get("room"))
        raise SystemExit(0)

    if clean["op"] == "goto":
        print("walking to", (clean["x"], clean["z"]))
        print(walk_to(pad, clean["x"], clean["z"]))
    elif clean["op"] == "attack":
        target = clean.get("x"), clean.get("z")
        print("closing on", target)
        print(walk_to(pad, target[0], target[1]))
        for _ in range(3):
            pad.send([{"key": "a", "down": True}, {"key": "a", "down": False}])
            time.sleep(0.3)
    elif clean["op"] == "clear":
        print("operator cleared the directive - standing down")
    print("shot:", pad.shot("directive"))
