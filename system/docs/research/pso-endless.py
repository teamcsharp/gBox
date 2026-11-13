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
import pathlib
import re
import sys
import time
import traceback

from pso_pad import Pad, call

import singleton                      # one bot only: a second loop fights the first for the pad

# The operator's controller relay (controller_relay.py) creates this while they are playing, so the bot stands down.
OPERATOR_PLAYING = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
FLAG_STALE_S = 15.0        # a pause flag older than this is a dead relay, not a playing operator
TRIVIAL_HP = 40            # an enemy this cheap is worth killing before a box (the flies are 8 HP)
LOOP_LOCK = pathlib.Path(r"D:\gBox\pso-ds\endless.lock")

# The game's own affordance classifier, so a door key is recognised from its entity CLASS in RAM rather than guessed
# from distance: SWITCH_CLASSES {'TLazerFenceSw', 'TObjDoorKey'} must be PRESSED, DOOR_CLASSES {'TObjDoor',
# 'TObjLazerFenceNorm', 'TOBarrierEnergy01'} are walked through.
sys.path.insert(0, r"C:\_tools\gBox\system")
try:
    from gbox import pso_coop_gates
except Exception:                                          # noqa: BLE001 - the loop must still run without it
    pso_coop_gates = None

GAME = "436e0bb84d5337d1"
BOOT_MENU = [("start", 2.6), ("down", 1.2), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.0), ("a", 3.5)]


def log(message: str) -> None:
    """Print a timestamped line, ASCII-safe.

    The console here is cp1252, so a BOM or any non-Latin character in a note or an entity class would raise
    UnicodeEncodeError and take the loop down. Anything unprintable becomes '?' - a mangled log line is always better
    than a dead bot.
    """
    safe = str(message).encode("ascii", "replace").decode("ascii")
    print(f"[{time.strftime('%H:%M:%S')}] {safe}", flush=True)


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
GIVE_UP_AFTER = 8                # swings with no HP change before leaving the enemy and taking a gate
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


def unlock_floor(pad: Pad) -> str:
    """Set every stage flag for the floor the character is standing on, and verify it.

    Doors recompute their open state from this array every frame (pso_coop_gates: "native_state (+0xAC) is futile -
    it is recomputed each frame FROM this flag"), so this opens them without a button or a target.
    """
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": STAGE_FLAG_GROUP_PTR, "length": 4}}, "POST")
    try:
        floor = int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                      # noqa: BLE001
        return "no floor"
    if not 0 <= floor < STAGE_FLAG_GROUPS:
        return f"floor {floor} out of range"
    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    full = bytes([255] * STAGE_GROUP_SIZE)
    raw_group = call("/api/sessions/%s/rpc" % pad.sid,
                     {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        group = bytes.fromhex(raw_group)
    except Exception:                                      # noqa: BLE001
        group = b""
    if group == full:
        return f"floor {floor} already open"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address, "hex_bytes": full.hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.2)
    check = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        ok = bytes.fromhex(check) == full
    except Exception:                                      # noqa: BLE001
        ok = False
    return f"floor {floor} {'unlocked' if ok else 'write failed'}"


STAGE_FLAG_BASE = 0x80515CC8
STAGE_FLAG_GROUP_PTR = 0x805D5FC0
STAGE_GROUP_SIZE = 32
STAGE_FLAG_GROUPS = 18


def open_all_gates(pad: Pad) -> str:
    """Set every stage flag for the current floor - the door recomputes from these each frame.

    Returns a short description of what happened, for the arm log.
    """
    raw = call("/api/sessions/%s/rpc" % pad.sid,
               {"op": "read_memory", "args": {"address": STAGE_FLAG_GROUP_PTR, "length": 4}}, "POST")
    try:
        floor = int.from_bytes(bytes.fromhex(raw), "big")
    except Exception:                                  # noqa: BLE001
        return "could not read the floor"
    address = STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE
    before = call("/api/sessions/%s/rpc" % pad.sid,
                  {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        already = bytes.fromhex(before)
    except Exception:                                  # noqa: BLE001
        already = b""
    if already and all(byte == 0xFF for byte in already):
        return f"floor {floor}: gates already open"
    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": address,
                                       "hex_bytes": ("ff" * STAGE_GROUP_SIZE)}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(10):
        time.sleep(0.4)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.4)
    after = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": address, "length": STAGE_GROUP_SIZE}}, "POST")
    try:
        ok = bytes.fromhex(after) == b"\xff" * STAGE_GROUP_SIZE
    except Exception:                                  # noqa: BLE001
        ok = False
    return f"floor {floor}: {'all gates open' if ok else 'flag write did not stick'}"


DIFFICULTY_GLOBAL = 0x805D5550      # 0 normal, 1 hard, 2 very hard, 3 ultimate


ULTIMATE_AT = 250          # hp_max at which Ultimate becomes survivable (level 5 has 68)


def set_difficulty(pad: Pad) -> str:
    """Choose Normal or Ultimate from the character's own max HP, and verify the write.

    Ultimate content is not survivable at 68 HP - the Forest beasts there carry 1556 - so the bot levels on Normal and
    switches to Ultimate once its HP shows it can take hits. The objective wants Ultimate; this is how it is earned
    rather than pretended.
    """
    import struct as _struct

    profile = call("/api/sessions/%s/rpc" % pad.sid, {"op": "state", "args": {"player_only": True}}, "POST") or {}
    player = profile.get("player") or {}
    hp_max = float(player.get("hp_max") or 0)
    wanted = 3 if hp_max >= ULTIMATE_AT else 0
    label = "Ultimate" if wanted == 3 else "Normal"

    before = call("/api/sessions/%s/rpc" % pad.sid,
                  {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        current = int.from_bytes(bytes.fromhex(before), "big")
    except Exception:                                          # noqa: BLE001
        current = None
    if current == wanted:
        return f"{label} (already, hp_max {hp_max:.0f})"

    job = call("/api/jobs", {"tool": "write_memory", "require_worker": pad.worker,
                             "input": {"session_id": pad.sid, "address": DIFFICULTY_GLOBAL,
                                       "hex_bytes": _struct.pack(">I", wanted).hex()}}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    for _ in range(8):
        time.sleep(0.3)
        row = call("/api/jobs/" + job_id) if job_id else {}
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            break
    time.sleep(0.2)
    after = call("/api/sessions/%s/rpc" % pad.sid,
                 {"op": "read_memory", "args": {"address": DIFFICULTY_GLOBAL, "length": 4}}, "POST")
    try:
        now = int.from_bytes(bytes.fromhex(after), "big")
    except Exception:                                          # noqa: BLE001
        now = None
    verdict = "ok" if now == wanted else "DID NOT STICK"
    return f"{label} for hp_max {hp_max:.0f} ({current} -> {now}) {verdict}"

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
    log(f"  difficulty: {set_difficulty(pad)}")
    for payload in ({"op": "floor_rares", "on": True, "character_class": "HUmar"},
                    {"op": "enemy_drops", "on": True,
                     "codes": ["009d00", "003200", "004400", "000100", "000200"]}):
        answer = mods(pad, payload)
        log(f"  {payload['op']}: {answer.get('state')} {str(answer.get('error'))[:60]}")
    log(f"  gates: {open_all_gates(pad)}")
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
                time.sleep(1.2)                     # let the game settle the character before judging the move
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


OPERATOR_NOTES = pathlib.Path(r"D:\gBox\pso-ds\operator-notes.txt")
NOTE_STATE = {"last": None, "mode": None, "goto": None}


def read_notes(pad: Pad) -> None:
    """Read the operator's notes file; log it, classify it, and set the flags the loop obeys."""
    try:
        if not OPERATOR_NOTES.exists():
            return
        raw = OPERATOR_NOTES.read_text(encoding="utf-8-sig", errors="replace").strip()
    except OSError:
        return
    if not raw or raw == NOTE_STATE["last"]:
        return
    NOTE_STATE["last"] = raw
    latest = [line.strip() for line in raw.splitlines() if line.strip()]
    text_line = latest[-1] if latest else raw
    log(f"  NOTE from operator: {text_line}")
    lowered = text_line.lower()

    if any(word in lowered for word in ("stop", "halt", "wait", "hold")):
        NOTE_STATE["mode"] = "stop"
        log("  note internalized: standing down")
        return
    if any(word in lowered for word in ("go ", "resume", "play", "continue")) or lowered in ("go", "resume"):
        NOTE_STATE["mode"] = None
        log("  note internalized: resuming")
        return
    if any(word in lowered for word in ("kill", "attack", "fight", "enemy")):
        NOTE_STATE["mode"] = "fight"
        log("  note internalized: prioritising enemies")
        return
    if any(word in lowered for word in ("box", "loot", "rare", "item", "drop")):
        NOTE_STATE["mode"] = "loot"
        log("  note internalized: prioritising containers and rares")
        return
    if any(word in lowered for word in ("door", "gate", "warp", "exit", "next room", "level")):
        NOTE_STATE["mode"] = "exit"
        log("  note internalized: prioritising the way forward")
        return
    match = re.search(r"goto\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", lowered)
    if match:
        NOTE_STATE["goto"] = (float(match.group(1)), float(match.group(2)))
        log(f"  note internalized: walking to {NOTE_STATE['goto']}")
        return
    log("  note internalized: noted (no action keyword) - it stays in effect as context")


FOREST_MAPS = pathlib.Path(r"D:\gBox\pso-ds\forest-maps.json")
_ROUTERS = {}


def _router():
    """The Forest 1 router, loaded once. None when the map file is absent."""
    if "forest01" in _ROUTERS:
        return _ROUTERS["forest01"]
    router = None
    try:
        if FOREST_MAPS.exists():
            data = json.loads(FOREST_MAPS.read_text(encoding="utf-8"))
            row = data.get("Scene/map_forest01c.rel")
            if row and row.get("cells"):
                sys.path.insert(0, r"C:\_tools\gBox\.tmp")
                from forest_route import MapRouter
                router = MapRouter(row["cells"])
    except Exception:                                          # noqa: BLE001 - the map is an aid, never a dependency
        router = None
    _ROUTERS["forest01"] = router
    return router


def map_step(pad: Pad, tx: float, tz: float) -> "tuple[float, float] | None":
    """The next waypoint from the character toward (tx,tz) on the internalised map, or None.

    A route is only returned when both ends snap to safe cells and A* finds a path - i.e. when the map genuinely knows
    how to get there. Anything else returns None and the caller keeps its own approach.
    """
    router = _router()
    if router is None:
        return None
    try:
        me = (state(pad).get("player") or {})
        here = (float(me.get("x") or 0), float(me.get("z") or 0))
        route = router.route(here, (tx, tz))
        if not route:
            return None
        for waypoint in route:
            if math.dist(here, waypoint) > 8.0:
                return (float(waypoint[0]), float(waypoint[1]))
    except Exception:                                          # noqa: BLE001
        return None
    return None


DEG_PER_TAP = 10.0      # measured: a single tap rotates ~11 deg left, ~8 deg right (a hold rotates far more)
WALK_BURST = 0.5        # ~10 units per burst; a longer hold does not walk at all


def steer_to(pad: Pad, tx: float, tz: float) -> float:
    """Turn to face (tx,tz) with counted taps, then take one short step. Returns the remaining distance.

    Taps, not holds: a press is a fixed ~46-degree rotation, so holding over-rotates by a full step every correction
    and the character zigzags. Counting taps makes the facing deterministic.
    """
    me = (state(pad).get("player") or {})
    x, z = float(me.get("x") or 0), float(me.get("z") or 0)
    heading = float(me.get("heading_deg") or 0)
    distance = math.hypot(tx - x, tz - z)
    if distance < 1.0:
        return distance
    want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
    error = ((want - heading + 540.0) % 360.0) - 180.0
    taps = int(round(abs(error) / DEG_PER_TAP))
    if taps > 0:
        key = "left" if error > 0 else "right"
        for _ in range(min(taps, 20)):
            tap(pad, key)
            time.sleep(0.12)
        time.sleep(0.2)
        me = (state(pad).get("player") or {})
        x, z = float(me.get("x") or 0), float(me.get("z") or 0)
        heading = float(me.get("heading_deg") or 0)
        want = (math.degrees(math.atan2(tx - x, tz - z)) + 360.0) % 360.0
        error = ((want - heading + 540.0) % 360.0) - 180.0
    if abs(error) < 35:
        hold(pad, "up", WALK_BURST)
        time.sleep(0.15)
    return math.hypot(tx - x, tz - z)


def play(pad: Pad, seconds: float = 120.0) -> str:
    """Fight what is near, otherwise travel. Returns what it did most."""
    started = time.time()
    last_position, stuck, killed, moved, closest = None, 0, 0, 0.0, 999.0
    gates_seen, crossed = set(), []
    unproductive, walked_out = 0, 0
    unlock_counter, last_unlock = 0, ""
    pressed_keys, key_misses = set(), 0      # door keys already pressed this window, and approach misses
    warped, warp_misses, warp_reported = 0, 0, None   # level exits entered, approach misses, last report
    boxes_hit, box_misses = 0, 0                        # containers destroyed, approach misses
    reticle_hits = 0                                    # presses made because something actionable was close
    attacks = 0                                         # swing bursts aimed by sweeping the cone
    map_steps = 0                                       # steps chosen from the internalised Forest map
    box_debug = 0                                       # box-approach samples logged
    last_enemy_hp = {}

    while time.time() - started < seconds:
        # The operator's controller relay drops this file while they are touching the pad: stand down so the bot does
        # not fight them for it. They get the game; the bot waits.
        # Stand down while the operator plays - but never trust a stale marker. If the relay dies with the flag set,
        # an endless stand-down is indistinguishable from a dead bot, so the flag expires on its own age.
        operator_active = False
        if OPERATOR_PLAYING.exists():
            try:
                operator_active = (time.time() - OPERATOR_PLAYING.stat().st_mtime) < FLAG_STALE_S
            except OSError:
                operator_active = False
        if operator_active:
            if not globals().get("_PAUSED_LOGGED"):
                log("  operator is playing - bot standing down")
                globals()["_PAUSED_LOGGED"] = True
            time.sleep(0.4)
            continue
        globals()["_PAUSED_LOGGED"] = False

        # The operator types notes into operator-notes.txt; they are read and acted on every iteration.
        read_notes(pad)
        if NOTE_STATE.get("mode") == "stop":
            time.sleep(0.5)
            continue

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

        unlock_counter += 1
        if unlock_counter % 12 == 0:
            result = unlock_floor(pad)
            if result != last_unlock:
                log(f"  doors: {result}")
                last_unlock = result

        if stuck >= 2:
            # measured, not assumed: try every direction and keep the one that moves
            unstick(pad)
            stuck = 0

        enemies = [e for e in (now.get("entities") or [])
                   if str(e.get("kind")) == "enemy" and e.get("hp") is not None
                   and float(e.get("hp")) > 0]
        # BOXES FIRST. They are destructible at this level and do not fight back, so they are where the attack can
        # be perfected - and the instrumented run showed the box branch never ran because enemies were always present.
        nearby_boxes = [e for e in (now.get("entities") or [])
                        if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))
                            or "Trap" in str(e.get("class")))
                        and e.get("x") is not None and e.get("z") is not None]
        # A CHEAP ENEMY OUTRANKS A BOX. An 8 HP fly is one swing and one step toward levelling; a 300 HP nest and a
        # 1556 HP beast are not worth the window. So boxes come first only when nothing cheap is in reach.
        trivials = [e for e in enemies
                    if float(e.get("hp") or 9999) <= TRIVIAL_HP
                    and math.hypot(float(e.get("x") or 0) - x, float(e.get("z") or 0) - z) <= 22.0]
        if nearby_boxes and not trivials:
            box = min(nearby_boxes, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                      + (float(e.get("z") or 0) - z) ** 2)
            bx, bz = float(box.get("x") or 0), float(box.get("z") or 0)
            bdist = math.hypot(bx - x, bz - z)
            if bdist <= 220.0:
                if bdist <= 20.0:        # real PMT range is 13-30 units (was 8, from the fallback)
                    for _ in range(3):
                        tap(pad, "b")
                        time.sleep(0.08)
                        tap(pad, "a")
                        time.sleep(0.3)
                    hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                    boxes_hit += 1
                else:
                    # Hill-climb on the distance that is actually measured, with patience and a step scaled to the
                    # remaining distance. The map still chooses the box; the movement is decided by what happened.
                    step = map_step(pad, bx, bz)
                    side_b = globals().get("BOX_SIDE", 1)
                    hold(pad, "left" if side_b > 0 else "right", 0.16)
                    hold(pad, "up", 0.35 if bdist < 30.0 else 0.6)
                    time.sleep(0.2)
                    after_b = state(pad).get("player") or {}
                    now_b = math.hypot(bx - float(after_b.get("x") or 0), bz - float(after_b.get("z") or 0))
                    if now_b < bdist - 1.0:
                        box_misses = 0
                    else:
                        box_misses += 1
                        if box_misses >= 3:
                            globals()["BOX_SIDE"] = -side_b
                            box_misses = 0
                    box_debug += 1
                    if box_debug % 4 == 1:
                        log(f"  box {box.get('class')} d={bdist:.1f} -> {now_b:.1f} "
                            f"side={side_b:+d} route={'yes' if step else 'no'}")
                moved += 1
                time.sleep(0.1)
                continue

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
                unproductive = 0
            elif name in last_enemy_hp:
                unproductive += 1
            last_enemy_hp[name] = hp
            if unproductive >= GIVE_UP_AFTER:
                # cannot hurt this one: leave it and take the way out rather than standing in front of it
                log(f"  {name} untouched after {unproductive} swings - leaving it and heading for a gate")
                unproductive = 0
                last_enemy_hp = {}
                tap(pad, "down")
                time.sleep(0.15)
                hold(pad, "down", 0.6)
                walked_out += 1
                time.sleep(0.1)
                continue

            # Nothing here trusts `heading_deg`: presses in one direction produced +130, +21, 0 and +145 degrees, so
            # it is not a signal to servo on. Instead hill-climb on DISTANCE - turn a side, step, and keep that side
            # only if it made us closer. That is how an enemy was closed from 210 units to 12 and killed.
            if distance <= 22.0:      # real PMT range is 13-30 units (was 10, from the fallback)
                # SWEEP the aim cone here too. An attack only connects inside 8 degrees and heading_deg cannot be
                # trusted to aim (presses in one direction gave +130, +21, 0 and +145 degrees), so swing three times
                # and rotate a little each visit. This is the fix for "untouched after 8 swings".
                for _ in range(3):
                    tap(pad, "b")       # a pause menu eats the swing; START toggles it, B cancels it
                    time.sleep(0.08)
                    tap(pad, "a")
                    time.sleep(0.3)
                hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                killed += 0
                attacks += 1
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
            # No enemies: find the way forward, in priority order. All of it comes from RAM - entity CLASSES and the
            # stage-flag array - never from the screen.
            #
            # 1. a LEVEL-EXIT teleporter. The warp family is in pso_class_registry: TObjWarpBase, TObjMapWarp,
            #    TObjMapWarpForest, TObjMapForceWarp, TObjWarpString, TObjAreaWarpEndingJung, TObjWarpBoss,
            #    TObjWarpJung, TObjWarpLobby - and pso_classes maps TObjWarp to "warp". Walking into one advances
            #    the stage, so this is the end-of-level door and it outranks everything else once the room is clear.
            # 2. a door KEY (TObjDoorKey / TLazerFenceSw) which must be PRESSED, close up.
            # 3. a DOOR (TObjDoor / TObjLazerFenceNorm / TOBarrierEnergy01) to walk through.
            # THE RETICLE RULE. If the game is offering something to act on, act on it: press B then A. Anything
            # actionable within 12 units counts, because the reticle is the game's own way of saying so. Townsfolk are
            # excluded by class - talk to them and the character can be locked in a conversation, which happened.
            actionables = []
            for candidate in (now.get("entities") or []):
                candidate_class = str(candidate.get("class"))
                if "Npc" in candidate_class or "NPC" in candidate_class:
                    continue                                    # never talk to townsfolk
                if candidate.get("x") is None or candidate.get("z") is None:
                    continue
                kind = str(candidate.get("kind"))
                if not (kind == "enemy" or kind == "object" or kind == "gate"):
                    continue
                # NEVER pick items up: TItemMoney / TItemEquipBase and the rest of the loose-drop family are skipped.
                # The operator wants the bag empty - the character has unlimited Scape Dolls and needs no monomates,
                # trimates, monofluids or difluids - and a full bag is what stopped pickups working in the first place.
                if candidate_class.startswith("TItem") or candidate_class.startswith("TObjItem"):
                    continue
                # Containers, capsules and traps are NOT for the catch-all: they belong to the box branch, which
                # SWEEPS the aim cone. A single press here was preempting that and destroying nothing.
                if ("Container" in candidate_class or "Capsule" in candidate_class
                        or "Trap" in candidate_class):
                    continue
                distance_c = math.hypot(float(candidate.get("x") or 0) - x, float(candidate.get("z") or 0) - z)
                if distance_c <= 12.0:
                    actionables.append((distance_c, candidate_class))
            if actionables:
                actionables.sort()
                nearest_class = actionables[0][1]
                tap(pad, "b")
                time.sleep(0.08)
                tap(pad, "a")
                time.sleep(0.3)
                reticle_hits += 1
                if reticle_hits % 10 == 1:
                    log(f"  acted on {nearest_class} ({actionables[0][0]:.1f} units) - reticle rule")
                moved += 1
                continue

            # BREAK THE BOXES. Containers are ordinary entities in the table (TObjContainerItem, TOCapsuleAncient01),
            # so they can be walked up to and hit. Boxes come before warps and doors: loot before leaving.
            boxes = [e for e in (now.get("entities") or [])
                     if ("Container" in str(e.get("class")) or "Capsule" in str(e.get("class"))
                         or "Trap" in str(e.get("class")))
                     and e.get("x") is not None and e.get("z") is not None]
            if boxes:
                box = min(boxes, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                          + (float(e.get("z") or 0) - z) ** 2)
                bx, bz = float(box.get("x") or 0), float(box.get("z") or 0)
                bdist = math.hypot(bx - x, bz - z)
                if bdist <= 20.0:         # real PMT range is 13-30 units; the 12-unit figure was the fallback
                    # SWEEP the aim cone. The attack only connects inside an 8-degree cone and heading_deg cannot be
                    # trusted to aim, so swing a few times and rotate a little each visit - verified to break a box
                    # at heading 58 after the same sweep. A fixed heading beside a box hits nothing.
                    for _ in range(3):
                        tap(pad, "b")                  # a pause menu eats the swing here too
                        time.sleep(0.08)
                        tap(pad, "a")
                        time.sleep(0.3)
                    hold(pad, "left" if int(time.time() * 3) % 2 else "right", 0.2)
                    boxes_hit += 1
                else:
                    side_b = globals().get("BOX_SIDE", 1)
                    before_b = bdist
                    step = map_step(pad, bx, bz)      # route on the internalised Forest map when it knows the way
                    box_debug += 1
                    if box_debug % 3 == 1:
                        log(f"  box {box.get('class')} at ({bx:.0f},{bz:.0f}) d={bdist:.1f} "
                            f"route={'yes' if step else 'no'}")
                    if step and math.dist((x, z), (bx, bz)) > 10.0:
                        side_toward = 1 if step[0] >= x else -1
                        hold(pad, "left" if side_toward > 0 else "right", 0.16)
                        hold(pad, "up", 0.7)
                        map_steps += 1
                    else:
                        hold(pad, "left" if side_b > 0 else "right", 0.18)
                        hold(pad, "up", 0.7)
                    time.sleep(0.2)
                    after_b = state(pad).get("player") or {}
                    now_b = math.hypot(bx - float(after_b.get("x") or 0), bz - float(after_b.get("z") or 0))
                    if now_b > before_b - 1.0:
                        box_misses += 1
                        if box_misses >= 4:
                            globals()["BOX_SIDE"] = -side_b
                            box_misses = 0
                    else:
                        box_misses = 0
                moved += 1
                continue

            warps = [e for e in (now.get("entities") or [])
                     if "Warp" in str(e.get("class")) and e.get("x") is not None and e.get("z") is not None]
            if warps:
                warp = min(warps, key=lambda e: (float(e.get("x") or 0) - x) ** 2
                           + (float(e.get("z") or 0) - z) ** 2)
                wx, wz = float(warp.get("x") or 0), float(warp.get("z") or 0)
                wdist = math.hypot(wx - x, wz - z)
                wcls = str(warp.get("class"))
                if warp_reported != (wcls, round(wx / 40.0), round(wz / 40.0)):
                    log(f"  LEVEL EXIT {wcls} {wdist:.1f} units away - heading for it")
                    warp_reported = (wcls, round(wx / 40.0), round(wz / 40.0))
                if wdist <= 12.0:
                    room_before_warp = player.get("room")
                    hold(pad, "up", 1.2)                       # step into the teleporter
                    time.sleep(0.4)
                    after_warp = state(pad).get("player") or {}
                    if after_warp.get("room") != room_before_warp:
                        log(f"  ENTERED THE WARP {wcls}: room {room_before_warp} -> {after_warp.get('room')}")
                        warped += 1
                    else:
                        tap(pad, "a")
                        time.sleep(0.4)
                        hold(pad, "up", 1.0)
                else:
                    side_w = globals().get("WARP_SIDE", 1)
                    before_w = wdist
                    hold(pad, "left" if side_w > 0 else "right", 0.18)
                    hold(pad, "up", 0.75)
                    time.sleep(0.2)
                    after_p2 = state(pad).get("player") or {}
                    now_w = math.hypot(wx - float(after_p2.get("x") or 0), wz - float(after_p2.get("z") or 0))
                    if now_w > before_w - 1.0:
                        warp_misses += 1
                        if warp_misses >= 4:
                            globals()["WARP_SIDE"] = -side_w
                            warp_misses = 0
                    else:
                        warp_misses = 0
                moved += 1
            else:
                rows = []
                if pso_coop_gates is not None:
                    try:
                        rows = pso_coop_gates.forward_candidates(now.get("entities") or [], player.get("room"),
                                                                 x, z, skip_switches=False)
                    except Exception:                              # noqa: BLE001
                        rows = []
                if rows:
                    is_switch, adist, gkey, entity, kind = rows[0]
                    ax = float(entity.get("x") or 0)
                    az = float(entity.get("z") or 0)
                    cls = str(entity.get("class"))
                    if is_switch == 0:
                        # A DOOR KEY. Its press only registers close up, so approach and then press.
                        if adist <= 6.5:
                            tap(pad, "b")
                            time.sleep(0.1)
                            tap(pad, "a")
                            time.sleep(0.3)
                            log(f"  pressed the door key {cls} at {adist:.1f} units")
                            pressed_keys.add(gkey)
                        elif adist <= 70.0:
                            if gkey not in pressed_keys or adist <= 25.0:
                                log(f"  DOOR KEY {cls} detected {adist:.1f} units ahead - going to press it")
                            side_key = globals().get("KEY_SIDE", 1)
                            before_key = adist
                            hold(pad, "left" if side_key > 0 else "right", 0.18)
                            hold(pad, "up", 0.7)
                            time.sleep(0.2)
                            after_key_state = state(pad)
                            after_rows = []
                            try:
                                after_rows = pso_coop_gates.forward_candidates(
                                    after_key_state.get("entities") or [],
                                    (after_key_state.get("player") or {}).get("room"),
                                    float((after_key_state.get("player") or {}).get("x") or 0),
                                    float((after_key_state.get("player") or {}).get("z") or 0),
                                    skip_switches=False)
                            except Exception:                      # noqa: BLE001
                                after_rows = []
                            after_key = after_rows[0][1] if after_rows else before_key
                            if after_key > before_key - 1.0:
                                key_misses += 1
                                if key_misses >= 4:
                                    globals()["KEY_SIDE"] = -side_key
                                    key_misses = 0
                            else:
                                key_misses = 0
                        moved += 1
                    else:
                        # A DOOR: walk through it; only count a crossing when the room actually changes.
                        if adist <= 18.0:
                            room_before = player.get("room")
                            hold(pad, "up", 1.0)
                            time.sleep(0.25)
                            after_gate = state(pad).get("player") or {}
                            if after_gate.get("room") != room_before:
                                crossed.append((round(ax / 25.0), round(az / 25.0)))
                                log(f"  crossed a door: room {room_before} -> {after_gate.get('room')}")
                        else:
                            side_key = globals().get("KEY_SIDE", 1)
                            hold(pad, "left" if side_key > 0 else "right", 0.18)
                            hold(pad, "up", 0.75)
                        moved += 1
                else:
                    # Nothing classifiable nearby: short sweep so the next sample can find something.
                    hold(pad, "left" if int(time.time()) % 2 else "right", 0.25)
                    hold(pad, "up", 0.6)
                    moved += 1
        time.sleep(0.15)

    return (f"played {seconds:.0f}s, {moved} travel steps, closest approach {closest:.1f}, "
            f"gates approached {len(gates_seen)}, crossed {len(crossed)}, left {walked_out} unwinnable")


# ---- outer loop ------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    if not singleton.acquire(LOOP_LOCK):
        raise SystemExit(0)                     # another bot is already playing; two would fight over the pad
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
