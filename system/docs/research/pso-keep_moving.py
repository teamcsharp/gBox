"""keep_moving - a bot that never stands still.

Requirement: *"The bot must always be moving and playing this game. I never want to see the bot just standing around."*

So every pass of the loop presses something. The order of preference is what a player would do:

1. **an enemy nearby** - turn to face it and swing (A), which is playing the game;
2. **close to a warp** - walk into it, because the field is where there are enemies to fight;
3. **otherwise** - walk forward in bursts, turning when the way is blocked, sweeping the room so the character keeps moving and keeps discovering.

Two failure modes it guards against, both observed today:

* the **pause menu** opens (a stray press while near an NPC) and freezes everything - a stuck check presses START, which closes it;
* a **wall** stops forward movement - the stuck check turns instead of pushing.

Positions and heading come from the semantic profile (`rpc state`), which reads PSO correctly: `TObjPlayer`, `x/z`, `heading_deg`, `hp`, plus every NPC and door.
"""
import math
import time

from pso_pad import Pad, call

WARP = (254.0, 25.0)
ENEMY_KINDS = {"enemy", "monster", "hostile"}


def read(pad: Pad) -> dict:
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def tap(pad: Pad, key: str) -> str:
    return pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


def hold(pad: Pad, key: str, secs: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(secs)
    pad.send([{"key": key, "down": False}])


def bearing(fx: float, fz: float, tx: float, tz: float) -> float:
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


def turn_to(pad: Pad, me: dict, target: float, tolerance: float = 18.0) -> None:
    heading = float(me.get("heading_deg") or 0.0)
    error = ((target - heading + 540.0) % 360.0) - 180.0
    if abs(error) > tolerance:
        hold(pad, "right" if error > 0 else "left", min(0.55, max(0.15, abs(error) / 200.0)))


if __name__ == "__main__":
    pad = Pad()
    print("session:", pad.sid, flush=True)
    sweep, last_position, stuck_count, best_distance = 0.0, None, 0, 1e9

    while True:
        state = read(pad)
        me = state.get("player") or {}
        if not me:
            time.sleep(0.6)
            tap(pad, "a")
            print("no player - pressing A", flush=True)
            continue

        x, z = float(me.get("x") or 0.0), float(me.get("z") or 0.0)
        room = me.get("room")
        enemies = [e for e in (state.get("entities") or [])
                   if str(e.get("kind")) in ENEMY_KINDS]

        # a stuck character: the pause menu, or a wall
        if last_position and abs(x - last_position[0]) < 0.8 and abs(z - last_position[1]) < 0.8:
            stuck_count += 1
        else:
            stuck_count = 0
        last_position = (x, z)

        if stuck_count >= 3:
            # A character wedged in a corner cannot be freed by turning alone - `up` just presses it into the wall. Back
            # off first, then turn, so there is room to rotate. START is also pressed because a pause menu looks
            # identical from the position alone (measured: the character stood still in a corner with no menu open).
            print(f"stuck at ({x:.1f},{z:.1f}) - backing off, pressing START, then turning", flush=True)
            tap(pad, "start")
            time.sleep(0.7)
            hold(pad, "down", 0.7)
            time.sleep(0.2)
            hold(pad, "right", 0.6)
            time.sleep(0.2)
            hold(pad, "up", 0.6)
            stuck_count = 0
            continue

        if enemies:
            near = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2 + (float(e.get("z") or 0) - z) ** 2)
            ex, ez = float(near.get("x") or 0.0), float(near.get("z") or 0.0)
            distance = math.hypot(ex - x, ez - z)
            print(f"enemy {near.get('class')} at {distance:5.1f} - attacking", flush=True)
            if distance > 55:
                turn_to(pad, me, bearing(x, z, ex, ez))
                hold(pad, "up", min(1.0, distance / 160.0))
            else:
                turn_to(pad, me, bearing(x, z, ex, ez))
                tap(pad, "a")
                time.sleep(0.25)
                tap(pad, "a")
            continue

        warp_distance = math.hypot(WARP[0] - x, WARP[1] - z)
        if warp_distance < best_distance - 5:
            best_distance = warp_distance
        if warp_distance < 260:
            print(f"warp {warp_distance:5.1f} away - heading for it", flush=True)
            turn_to(pad, me, bearing(x, z, *WARP))
            hold(pad, "up", 0.9)
            if warp_distance < 28:
                tap(pad, "a")
                time.sleep(1.5)
            continue

        # nothing to fight and the warp is far: sweep the room so the character keeps moving
        sweep += 0.35
        turn = 0.35 if int(sweep) % 2 else -0.35
        hold(pad, "right" if turn > 0 else "left", 0.3)
        hold(pad, "up", 0.7)
        print(f"sweeping room {room} at ({x:7.1f},{z:7.1f})", flush=True)
