"""endless - keep PSO running and being played, automatically, forever.

The ask: *"keep those builds cycling in the game endlessly. that should be automatic with PSO."* So this is the outer loop that owns the whole lifecycle rather than one
run:

    ensure a session exists (launch the game if there is none)
    ensure the character is in the world (drive the menus, wait out the intro cutscene)
    play: fight the nearest enemy, otherwise travel - never stand still
    if the character vanishes (death, a transition, a menu) recover: close menus, press A through the respawn
    if the session disappears entirely, start over - and keep cycling

Each phase is decided from the semantic profile, not from timers alone, because every failure mode in this session was a state the bot was in without knowing it: a pause
menu open (looks like "stuck"), an intro cutscene (no player entity), a session that ended (worker restarts), and a corner (position frozen while input works).

Combat uses the profile's own enemy entries, which carry `hp`, so a swing is verified by the enemy losing health instead of by hoping.
"""
from __future__ import annotations

import json
import math
import sys
import time
import traceback

from pso_pad import Pad, call

GAME = "436e0bb84d5337d1"
BOOT_MENU = [("start", 2.6), ("down", 1.2), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.5)]


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def live_sessions() -> list:
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [row for row in rows if row.get("state") in ("running", "starting")]


def worker() -> str:
    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return next((row["id"] for row in rows if row.get("online")), "")


def state(pad: Pad) -> dict:
    return call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {}}, "POST") or {}


def tap(pad: Pad, key: str) -> None:
    pad.send([{"key": key, "down": True}, {"key": key, "down": False}])


DIRECTIONS = ("up", "down", "left", "right")


def release_all(pad: Pad) -> None:
    """Return the stick to neutral.

    Releasing a single direction is unsafe on this pad: `up:False` pins the stick fully LEFT and `down:False` pins it
    fully RIGHT (measured). Only releasing all four together produces (lx 0, ly 0), so this is how every hold ends.
    """
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])


def hold(pad: Pad, key: str, seconds: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    release_all(pad)


def bearing(fx, fz, tx, tz) -> float:
    return (math.degrees(math.atan2(tx - fx, tz - fz)) + 360.0) % 360.0


# ---- lifecycle -------------------------------------------------------------------------------------------------------
def ensure_session() -> Pad | None:
    sessions = live_sessions()
    if sessions:
        return Pad(sessions[0]["session_id"])

    wid = worker()
    if not wid:
        log("no online worker; waiting")
        return None
    log("no session - launching the game")
    game = call("/api/catalog/" + GAME)
    job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game},
                             "require_worker": wid}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            log(f"launch: {row.get('state')} {str(row.get('error'))[:90]}")
            break
    sessions = live_sessions()
    return Pad(sessions[0]["session_id"]) if sessions else None


def ensure_in_game(pad: Pad) -> bool:
    """Drive the menus until the character is in the world, or say why not."""
    for attempt in range(3):
        now = state(pad)
        if now.get("player"):
            return True

        # An open pause menu reads exactly like "no player": the entity table is suspended while it is up. Close it
        # before deciding the game needs booting, or the boot sequence navigates the pause menu instead of the title.
        tap(pad, "start")
        time.sleep(1.2)
        if state(pad).get("player"):
            log("closed a pause menu - character was there all along")
            return True
        tap(pad, "b")
        time.sleep(0.8)
        if state(pad).get("player"):
            log("closed a dialog - character is in the world")
            return True

        log(f"boot attempt {attempt + 1}: pressing through the title and menus")
        time.sleep(4)
        for key, wait in BOOT_MENU:
            tap(pad, key)
            time.sleep(wait)

        # the intro cutscene: no player entity exists until it ends - but the session can also die, and waiting on a
        # session that no longer exists is what left the loop pressing into nothing
        for index in range(12):
            time.sleep(5)
            if not live_sessions():
                log("session ended while booting - letting the outer loop relaunch")
                return False
            if state(pad).get("player"):
                log("character is in the world")
                return True
            if index in (2, 5, 8):
                tap(pad, "a")
        tap(pad, "b")
        time.sleep(2)
    return False



def mods(pad: Pad, payload: dict, wait: float = 45.0) -> dict:
    """One pso_mods mutation, single attempt."""
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


WARP_CELL = (361.2, 0.0, 28.8)      # the cell that actually triggers the city warp (found by searching Corridor.safe)


TELEPORT_ATTEMPTS = {"count": 0}
ARMED_SESSIONS: set = set()      # armed once per session: re-giving fills the inventory
GOOD_POSITION = {}


def teleport(pad: Pad, x: float, y: float, z: float) -> bool:
    """Move the character by writing its position - the same primitive go_to_field() uses.

    Position is three big-endian floats at `player_ptr + 0x38`. Returns whether the write landed, by re-reading.
    """
    import struct

    now = state(pad)
    pointer = (now.get("player") or {}).get("ptr")
    if not pointer:
        return False
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", x, y, z).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(10):
        time.sleep(0.6)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.8)
    after = state(pad).get("player") or {}
    moved = math.dist((x, z), (float(after.get("x") or 0), float(after.get("z") or 0)))
    return moved < 40.0


def where_am_i(state_now: dict) -> str:
    """'boss' | 'field' | 'city' - from the entity list alone.

    A boss arena has very few entities (7 in the Dragon's room) while a field has 85-130, so counting is not enough:
    the give-away for a boss is `Boss` in a class name, and for the city it is the absence of gates and enemies.
    """
    entities = state_now.get("entities") or []
    classes = [str(e.get("class")) for e in entities]
    if any("Boss" in name for name in classes):
        return "boss"
    if len(entities) > 60 and any(str(e.get("kind")) == "gate" for e in entities):
        return "field"
    if any(str(e.get("kind")) == "enemy" for e in entities):
        return "field"
    return "city"


def go_to_field(pad: Pad) -> bool:
    """Leave the city for a field, where there are enemies and doors to progress through.

    The city has ~31 entities and no enemies; a field has 80+ and `gate`-kind entries. Writing the warp platform's centre does not land on the warp because the raised disc is
    not walkable, so the specific trigger cell is used instead.
    """
    now = state(pad)
    player = now.get("player") or {}
    entities = now.get("entities") or []
    if where_am_i(now) in ("field", "boss"):
        return True                                     # a field or a boss arena both count as arrived

    import struct
    pointer = player.get("ptr")
    if not pointer:
        return False
    log(f"in the city ({len(entities)} entities) - warping to a field")
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": int(pointer, 16) + 0x38,
                                       "hex_bytes": struct.pack(">fff", *WARP_CELL).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(12):
        time.sleep(1)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(1.5)
    tap(pad, "a")

    # A warp tears the old area's entity table down before the new one is built, so a single check right after the
    # press sees "1 entity" for a warp that is working. Poll until the field exists.
    for attempt in range(13):
        time.sleep(2)
        after = state(pad)
        entities = after.get("entities") or []
        count = len(entities)
        gates = [e for e in entities if str(e.get("kind")) == "gate"]
        log(f"  warp +{(attempt + 1) * 2}s: {count} entities, {len(gates)} gates")
        if where_am_i(after) in ("field", "boss"):
            return True
    return False


def arm(pad: Pad) -> None:
    """Make this cycle's character able to play: unblockable, armed, and unable to stay dead.

    A relaunched session starts with none of this, because equipment lives in live memory rather than on the worker.
    But this runs every cycle and the cycle reuses a live session, so re-arming re-gives the same three weapons into the
    same inventory until every give fails with "Not enough inventory slots" and the character is left unarmed.
    """
    if pad.sid in ARMED_SESSIONS:
        log("already armed this session - skipping (re-giving fills the inventory)")
        return
    log("arming: walk_through, best weapons, survival")
    for payload in ({"op": "walk_through", "on": True},
                    {"op": "give", "code": "009d00", "equip": True},      # DARK FLOW
                    {"op": "give", "code": "003200", "equip": True},      # TSUMIKIRI J-SWORD
                    {"op": "give", "code": "004400", "equip": True},      # RED HANDGUN: reaches from ~17 units
                    {"op": "survival", "on": True}):                      # virtual Scape Doll
        answer = mods(pad, payload)
        log(f"  {payload['op']} {payload.get('code', '')}: {answer.get('state')} "
            f"{str(answer.get('error'))[:70]}")
    ARMED_SESSIONS.add(pad.sid)


# ---- play ------------------------------------------------------------------------------------------------------------
def unstick(pad: Pad, attempts: int = 3) -> str:
    """Find a direction that actually moves the character, and report which one worked.

    A blocked direction retried forever is indistinguishable from a dead bot, and that is what every "stuck" episode in this session was: a ledge at y 16.2, a wall corner, an
    NPC conversation. So instead of a fixed key dance, try each direction and keep the one that produces movement.
    """
    for attempt in range(attempts):
        # A pause menu looks exactly like a blocked direction from the position alone, and it is the more common
        # cause - it was what froze the character twice. Cancel it before testing directions.
        tap(pad, "b")
        time.sleep(0.25)
        for key in ("up", "left", "right", "down", "left", "right"):
            before = state(pad)
            player = before.get("player") or {}
            if not player:
                return "no player"
            start = (float(player.get("x") or 0), float(player.get("z") or 0))
            hold(pad, key, 0.6)
            time.sleep(0.15)
            after = state(pad)
            player = after.get("player") or {}
            end = (float(player.get("x") or 0), float(player.get("z") or 0))
            if math.dist(start, end) > 1.0:
                log(f"unstick: {key} freed it ({math.dist(start, end):.1f} units)")
                return key
        # Nothing physical moved it. Cancel any menu - with B only: START *opens* the pause menu, and pressing it
        # here is what turned a temporary jam into a permanent one. Then back off and go round, alternating sides so
        # the same corner cannot trap it twice.
        log(f"unstick: no direction moved it (attempt {attempt + 1}) - cancelling, retreating, going round")
        tap(pad, "b")
        time.sleep(0.5)
        # A corner needs a real retreat, not one nudge: the way we came in is the likeliest free direction,
        # so walk back along it several steps before trying to turn.
        retreated = 0.0
        for _ in range(4):
            before_step = state(pad).get("player") or {}
            start = (float(before_step.get("x") or 0), float(before_step.get("z") or 0))
            hold(pad, "down", 0.7)
            after_step = state(pad).get("player") or {}
            end = (float(after_step.get("x") or 0), float(after_step.get("z") or 0))
            gained = math.dist(start, end)
            retreated += gained
            if gained < 0.5:
                break                                  # backing up is blocked too - stop wasting time
        log(f"  retreated {retreated:.1f} units")
        if retreated < 0.5 and TELEPORT_ATTEMPTS["count"] < 2:
            # Every direction blocked and the retreat blocked: the character is wedged. Relocate it a short distance
            # AT ITS OWN HEIGHT - writing y=0.1 buried it in terrain when it stood at y 32.3, which is why earlier
            # "drop landed" attempts never freed it. Measured: a same-height move of 15 units freed it and it then
            # walked 8.9 units normally.
            TELEPORT_ATTEMPTS["count"] += 1
            here = state(pad).get("player") or {}
            hx = float(here.get("x") or 0)
            hy = float(here.get("y") or 0)
            hz = float(here.get("z") or 0)
            freed = False
            for dx, dz in ((15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0)):
                log(f"  wedged at ({hx:.0f},{hy:.0f},{hz:.0f}) - relocating {dx:+.0f},{dz:+.0f} at the same height")
                if not teleport(pad, hx + dx, hy, hz + dz):
                    continue
                before_move = state(pad).get("player") or {}
                start = (float(before_move.get("x") or 0), float(before_move.get("z") or 0))
                hold(pad, "up", 0.8)
                after_move = state(pad).get("player") or {}
                end = (float(after_move.get("x") or 0), float(after_move.get("z") or 0))
                if math.dist(start, end) > 2.0:
                    log(f"  relocation freed it ({math.dist(start, end):.1f} units)")
                    freed = True
                    break
            if freed:
                TELEPORT_ATTEMPTS["count"] = 0
                return "up"
        hold(pad, "left" if attempt % 2 == 0 else "right", 0.5)
        time.sleep(0.15)
        hold(pad, "up", 0.6)
        time.sleep(0.2)
    return ""


def play(pad: Pad, seconds: float = 120.0) -> str:
    """Fight what is near, otherwise travel. Returns what it did most."""
    started = time.time()
    last_position, stuck, killed, moved, closest = None, 0, 0, 0.0, 999.0
    gates_seen, crossed = set(), []
    last_enemy_hp = {}

    while time.time() - started < seconds:
        now = state(pad)
        player = now.get("player") or {}
        if not player:
            return "no player"

        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        if last_position and math.dist((x, z), (last_position[0], last_position[1])) > 1.0:
            GOOD_POSITION.update(x=x, y=float(player.get("y") or 0), z=z)
        if last_position and abs(x - last_position[0]) < 0.8 and abs(z - last_position[1]) < 0.8:
            stuck += 1
        else:
            stuck = 0
        last_position = (x, z)

        if stuck >= 2:
            # measured, not assumed: try every direction and keep the one that moves
            unstick(pad)
            stuck = 0

        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                   and float(e.get("hp")) > 0]
        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)
            tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
            distance = math.hypot(tx - x, tz - z)
            closest = min(closest, distance)
            name = str(target.get("class"))
            hp = float(target.get("hp"))
            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                log(f"  {name} HIT: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp

            # Nothing here trusts `heading_deg`: presses in one direction produced +130, +21, 0 and +145 degrees, so
            # it is not a signal to servo on. Instead hill-climb on DISTANCE - turn a side, step, and keep that side
            # only if it made us closer. That is how an enemy was closed from 210 units to 12 and killed.
            if distance <= 15.5:
                tap(pad, "b")           # a pause menu eats the swing; START toggles it, B cancels it
                time.sleep(0.12)
                tap(pad, "a")
                time.sleep(0.45)
                killed += 0
            else:
                approach_side = globals().get("APPROACH_SIDE", 1)
                before = distance
                hold(pad, "left" if approach_side > 0 else "right", 0.18)
                hold(pad, "up", 0.75)
                found_after = state(pad)
                after_enemies = [e for e in (found_after.get("entities") or [])
                                 if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                                 and float(e.get("hp")) > 0]
                if after_enemies:
                    near = min(after_enemies, key=lambda e: (float(e.get("x") or 0) - float((found_after.get("player") or {}).get("x") or 0)) ** 2
                               + (float(e.get("z") or 0) - float((found_after.get("player") or {}).get("z") or 0)) ** 2)
                    px = float((found_after.get("player") or {}).get("x") or 0)
                    pz = float((found_after.get("player") or {}).get("z") or 0)
                    after_distance = math.hypot(float(near.get("x") or 0) - px, float(near.get("z") or 0) - pz)
                    if after_distance > before - 0.5:
                        globals()["APPROACH_SIDE"] = -approach_side
                moved += 1
        else:
            # No enemies here. Instead of sweeping blindly, walk to a DOOR: the state lists every gate with its
            # position (fields carry 19-24 of them), so "proceed to the next room" becomes a target to steer at.
            gates = [e for e in (now.get("entities") or []) if str(e.get("kind")) == "gate"
                     and e.get("x") is not None and e.get("z") is not None]
            if gates:
                gate = min(gates, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                           + (float(e.get("z") or 0) - z) ** 2)
                gx, gz = float(gate.get("x") or 0), float(gate.get("z") or 0)
                gdist = math.hypot(gx - x, gz - z)
                gates_seen.add((round(gx / 25.0), round(gz / 25.0)))     # distinct gates, coarsely binned
                if gdist <= 20.0:
                    # A gate is ACTIVATED with A - walking into it does nothing on its own. Press the button, walk
                    # through, and only count a crossing when the room actually changes.
                    room_before = player.get("room")
                    tap(pad, "b")
                    time.sleep(0.12)
                    tap(pad, "a")                                   # the button
                    time.sleep(0.35)
                    hold(pad, "up", 0.9)                            # walk through the opening
                    time.sleep(0.25)
                    after_gate = state(pad).get("player") or {}
                    if after_gate.get("room") != room_before:
                        crossed.append((round(gx / 25.0), round(gz / 25.0)))
                        log(f"  crossed a gate: room {room_before} -> {after_gate.get('room')}")
                    else:
                        tap(pad, "a")                               # maybe a switch rather than a door
                        time.sleep(0.25)
                        hold(pad, "up", 0.7)
                else:
                    gate_side = globals().get("GATE_SIDE", 1)
                    before_g = gdist
                    hold(pad, "left" if gate_side > 0 else "right", 0.18)
                    hold(pad, "up", 0.75)
                    after_p = state(pad).get("player") or {}
                    ax, az = float(after_p.get("x") or 0), float(after_p.get("z") or 0)
                    if math.hypot(gx - ax, gz - az) > before_g - 0.5:
                        globals()["GATE_SIDE"] = -gate_side
                moved += 1
            else:
                # a room with no gates listed: sweep, but keep it short so the next sample can find one
                hold(pad, "left" if int(time.time()) % 2 else "right", 0.25)
                hold(pad, "up", 0.6)
                moved += 1
        time.sleep(0.15)

    return (f"played {seconds:.0f}s, {moved} travel steps, closest approach {closest:.1f}, "
            f"gates approached {len(gates_seen)}, crossed {len(crossed)}")


# ---- outer loop ------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    cycle = 0
    while True:
        cycle += 1
        log(f"=== cycle {cycle} ===")
        try:
            pad = ensure_session()
            if not pad:
                time.sleep(10)
                continue
            log(f"session {pad.sid}")

            if not ensure_in_game(pad):
                log("could not get into the world this cycle; relaunching")
                call("/api/jobs", {"tool": "session_op", "require_worker": pad.worker,
                                   "input": {"session_id": pad.sid, "op": "stop_game", "args": {}}}, "POST")
                time.sleep(8)
                continue

            arm(pad)
            if not go_to_field(pad):
                log("could not reach a field this cycle - playing where we are")

            while live_sessions():
                outcome = play(pad, seconds=120)
                log(outcome)
                if outcome == "no player":
                    # died, or a transition: recover once, then let the outer loop rebuild
                    for _ in range(6):
                        time.sleep(3)
                        tap(pad, "start")
                        tap(pad, "a")
                        if state(pad).get("player"):
                            break
                    else:
                        log("character gone - rebuilding")
                        break
        except Exception:                                          # noqa: BLE001
            log("cycle error:\n" + traceback.format_exc()[-500:])
            time.sleep(10)
