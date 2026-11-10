"""RE4 (Switch) Mercenaries: the room's real map for every walk and shot the bot makes (#9342, checked; mm, y up).

    rm = for_snap(snap)                  # the stage's map (snap["nav"]'s room, else the round's stage, else the last)
    rm.walk_block(a, b)                  # why a walk from a to b (positions, his feet) is refused, or None
    rm.walk_clear(a, b)                  # ... is allowed
    rm.sight_block(a, b)                 # the wall a shot from a to b (feet; his gun EYE_MM up, the target's chest
                                         #   CHEST_MM up) meets, or None
    rm.blocked_cell(x, z, y)             # the computed '#': no floor, or a wall within his body's height crosses it

The table (gbox/data/re4_switch_room_map/r4xx.json, built by gbox.re4_switch_room_map from the RomFS and #9342's
JSON; the builder's docstring says what was checked and what was dropped): a 250 mm floor mask by #9342's rule (every
storey merged - "floor somewhere under this cell") and #9342's wall segments, each with the height span of the SAT
triangles behind it and a blocker flag (an invisible wall: it stops him, not a shot).

* a walk is refused when a sample along it (every SAMPLE_MM, the start's own cell aside) falls on a cell without floor
  (off the map: water, a void), when it crosses a wall whose height span meets his body (his feet + BODY_LO_MM ..
  BODY_HI_MM: a wall on the floor below or a beam above his head does not count; an invisible blocker does), when it
  brings him nearer than body_r (BRUSH_R_MM: his half width) to such a wall than he already is (a corner, a shallow
  angle), or when it ends within end_r of one (he would stand pressed to it, the camera inside it);
* a shot is refused when it crosses a wall that is not a blocker at the shot's own height there.

Rooms and MercMode's stages (Select Stage's order, gbox.mercs.titles.re4_switch.STAGES; re4_stage_greybox.STAGES and
re4_nav.ROOMS name the same rooms): Village r400, Castle r402, Base r403, Waterworld r404 (STAGE_ROOM). The frame was
checked live: the bot's RAM positions lie on each room's SAT floor with RAM y = the floor's height (median 0 mm).
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from . import re4_nav
from ..core import room_map as _core
from ..core.room_map import (BODY_HI_MM, BODY_LO_MM, BODY_R_MM, BRUSH_R_MM, BUCKET_MM,  # noqa: F401 - re-exported
                             SAMPLE_MM, RoomMap, _cross, _dist_seg, _dist_segs, _ok)

FORMAT = "gbox.re4_switch_room_map/1"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "re4_switch_room_map"
ROOMS = dict(re4_nav.ROOMS)                                  # r400 Village, r402 Castle, r403 Base, r404 Waterworld
STAGE_ROOM = {name: room for room, name in ROOMS.items()}    # MercMode / Select Stage name -> the room
STAGE_INDEX = dict(re4_nav.STAGE_INDEX)                      # Select Stage index (re4_switch.STAGES order) -> the room
EYE_MM, CHEST_MM = re4_nav.EYE_MM, re4_nav.CHEST_MM


def from_json(data: dict) -> RoomMap:
    rm = _core.from_json(data, formats=(FORMAT,))
    rm.stage = data.get("stage") or ROOMS.get(rm.room, rm.room)
    return rm


_CACHE: dict = {}


def path_of(room: str, data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / f"{room}.json"


def load(room: str | None, data_dir: Path | None = None) -> RoomMap | None:
    """The room's map (r400 ...), read once and kept; None when there is none or it cannot be read."""
    if not room:
        return None
    key = (str(data_dir or DATA_DIR), room)
    if key not in _CACHE:
        try:
            _CACHE[key] = from_json(json.loads(path_of(room, data_dir).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError, zlib.error):
            _CACHE[key] = None
    return _CACHE[key]


def room_for_stage(value) -> str | None:
    """A MercMode / Select Stage name ("Base"), its index (2), or a room id ("r403", 0x0403) -> the room."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return re4_nav.room_of(value)
    text = str(value).strip()
    return STAGE_ROOM.get(text) or STAGE_ROOM.get(text.title()) or re4_nav.room_of(text)


def room_of_snap(snap: dict) -> str | None:
    """The room a snapshot is in: its stage mesh's (snap["nav"], picked by the player's floor - re4_nav.Picker), else,
    on a snapshot read from the game (module_base), a room / stage it names, the round's own stage index
    (snap["game"]["stage"]) or the last room picked. A mesh that is not the stage's own table (a test's synthetic room
    named r400) gives none: the room map is laid over the room's real coordinates only."""
    snap = snap if isinstance(snap, dict) else {}
    nav = snap.get("nav")
    if nav is not None:
        room = getattr(nav, "room", None)
        return room if room in ROOMS and re4_nav.load(room) is nav else None
    if snap.get("module_base") is None:
        return None
    for key in ("room", "stage_room", "stage_name", "stage"):
        room = room_for_stage(snap.get(key))
        if room in ROOMS:
            return room
    game = snap.get("game")
    if isinstance(game, dict):
        room = STAGE_INDEX.get(game.get("stage")) if isinstance(game.get("stage"), int) else None
        if room in ROOMS:
            return room
    room = getattr(re4_nav.PICKER, "room", None)
    return room if room in ROOMS else None


def for_snap(snap: dict, data_dir: Path | None = None) -> RoomMap | None:
    """This snapshot's room map (snap["room_map"] when one is given, as the tests do), or None; never raises."""
    try:
        given = snap.get("room_map") if isinstance(snap, dict) else None
        if isinstance(given, RoomMap):
            return given
        return load(room_of_snap(snap), data_dir)
    except Exception:                                        # noqa: BLE001 - the map never costs the tick
        return None
