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


def hold(pad: Pad, key: str, seconds: float) -> None:
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    pad.send([{"key": key, "down": False}])


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


def arm(pad: Pad) -> None:
    """Make this cycle's character able to play: unblockable, armed, and unable to stay dead.

    A relaunched session starts with none of this, because equipment lives in live memory rather than on the worker.
    """
    log("arming: walk_through, best weapons, survival")
    for payload in ({"op": "walk_through", "on": True},
                    {"op": "give", "code": "009d00", "equip": True},      # DARK FLOW
                    {"op": "give", "code": "003200", "equip": True},      # TSUMIKIRI J-SWORD
                    {"op": "survival", "on": True}):                      # virtual Scape Doll
        answer = mods(pad, payload)
        log(f"  {payload['op']} {payload.get('code', '')}: {answer.get('state')} "
            f"{str(answer.get('error'))[:70]}")


# ---- play ------------------------------------------------------------------------------------------------------------
def play(pad: Pad, seconds: float = 45.0) -> str:
    """Fight what is near, otherwise travel. Returns what it did most."""
    started = time.time()
    last_position, stuck, killed, moved = None, 0, 0, 0.0
    last_enemy_hp = {}

    while time.time() - started < seconds:
        now = state(pad)
        player = now.get("player") or {}
        if not player:
            return "no player"

        x, z = float(player.get("x") or 0), float(player.get("z") or 0)
        heading = float(player.get("heading_deg") or 0)

        if last_position and abs(x - last_position[0]) < 0.8 and abs(z - last_position[1]) < 0.8:
            stuck += 1
        else:
            stuck = 0
        last_position = (x, z)

        if stuck >= 4:
            # a pause menu looks exactly like this from the position alone
            log("stuck - closing menus and backing off")
            tap(pad, "start")
            time.sleep(0.6)
            tap(pad, "b")
            time.sleep(0.4)
            hold(pad, "down", 0.6)
            hold(pad, "right", 0.5)

        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                   and float(e.get("hp")) > 0]
        if enemies:
            target = min(enemies, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                         + (float(e.get("z") or 0) - z) ** 2)
            tx, tz = float(target.get("x") or 0), float(target.get("z") or 0)
            distance = math.hypot(tx - x, tz - z)
            error = ((bearing(x, z, tx, tz) - heading + 540.0) % 360.0) - 180.0
            name = str(target.get("class"))
            hp = float(target.get("hp"))
            if name in last_enemy_hp and hp < last_enemy_hp[name]:
                killed += 0
                log(f"  {name} hit: {last_enemy_hp[name]:.0f} -> {hp:.0f}")
            last_enemy_hp[name] = hp

            if abs(error) > 20:
                hold(pad, "left" if error > 0 else "right", min(0.4, max(0.1, abs(error) / 240.0)))
            elif distance > 40:
                hold(pad, "up", min(0.8, max(0.25, distance / 200.0)))
                moved += 1
            else:
                tap(pad, "a")
                time.sleep(0.3)
                tap(pad, "a")
        else:
            # travel: the game needs the character to cross the floor to find the key and the door
            sweep = time.time() - started
            hold(pad, "left" if int(sweep) % 2 else "right", 0.3)
            hold(pad, "up", 0.7)
            moved += 1
        time.sleep(0.15)

    return f"played {seconds:.0f}s, {moved} travel steps"


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

            while live_sessions():
                outcome = play(pad, seconds=45)
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
