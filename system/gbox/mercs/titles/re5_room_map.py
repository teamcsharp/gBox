"""RE5 (Switch) Mercenaries: the stage's real map for every walk and shot the bot makes (#9360, checked: the stage's
Havok collision; positions in the game's cm, y up).

    sm = for_snap(snap)                   # this round's stage map (by the native mesh's navigation signature), or None
    sm.walk_block(a, b)                   # why a walk from a to b (his feet, cm) is refused, or None
    sm.walk_clear(a, b)
    sm.sight_block(a, b, eye, chest)      # the wall a shot from a's gun (eye cm up) to b's chest (chest cm up) meets
    sm.blocked_cell(x, z, y)              # the computed '#': no floor, or a wall within his body's height crosses it

The tables (gbox/data/re5_switch_room_map/s40N.json, mm, built by gbox.re5_switch_room_map from the RomFS; its
docstring says what was checked live and what was dropped) are read through the shared gbox.mercs.core.room_map: the
same rules as RE4's room map (a wall within his body's height, invisible or not, the floor's edge, a corner brushed, a
walk ending against one). The stage is the round's own: snap["nav"]'s learning signature (the stage's native nav
mesh, ss_ledger.SIGNATURES, measured) names it, and STAGE_ARCHIVE its collision. Experimental Facility has none: its
live route lies on none of s404's floors (#9360's name for s404 does not hold there).
"""
from __future__ import annotations

import json
import zlib
from pathlib import Path

from .. import ss_ledger
from ..core import room_map as _core

FORMAT = "gbox.re5_switch_room_map/1"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "re5_switch_room_map"
MM_PER_CM = 10.0
# the stage (ss_ledger.STAGE_NAMES) -> its collision archive, the ones the bot's live routes confirmed
STAGE_ARCHIVE = {"Public Assembly": "s400", "The Mines": "s401", "Village": "s402", "Ancient Ruins": "s403",
                 "Missile Area": "s405", "Ship Deck": "s406", "Prison": "s407"}
BODY_R_CM = _core.BODY_R_MM / MM_PER_CM          # a walk ending this near a wall: refused
BRUSH_R_CM = _core.BRUSH_R_MM / MM_PER_CM        # a walk closing in on one nearer than this: refused


def _mm(p) -> tuple:
    return tuple(float(v) * MM_PER_CM for v in p[:3])


class StageMap:
    """A stage's core.room_map.RoomMap in the game's cm."""

    def __init__(self, rm: _core.RoomMap):
        self.rm = rm
        self.room, self.stage = rm.room, rm.stage

    def walk_block(self, a, b, *, end_r: float = BODY_R_CM, body_r: float = BRUSH_R_CM) -> str | None:
        try:
            a, b = _mm(a), _mm(b)
        except (TypeError, ValueError, IndexError):
            return "not a position"
        return self.rm.walk_block(a, b, end_r=end_r * MM_PER_CM, body_r=body_r * MM_PER_CM)

    def walk_clear(self, a, b, **kw) -> bool:
        return self.walk_block(a, b, **kw) is None

    def sight_block(self, a, b, eye: float, chest: float):
        try:
            return self.rm.sight_block(_mm(a), _mm(b), eye=eye * MM_PER_CM, chest=chest * MM_PER_CM)
        except (TypeError, ValueError, IndexError):
            return ("bad end", 0.0, 0.0)

    def sight_clear(self, a, b, eye: float, chest: float) -> bool:
        return self.sight_block(a, b, eye, chest) is None

    def floor_at(self, x: float, z: float) -> bool:
        return self.rm.floor_at(x * MM_PER_CM, z * MM_PER_CM)

    def blocked_cell(self, x: float, z: float, y: float) -> bool:
        return self.rm.blocked_cell(x * MM_PER_CM, z * MM_PER_CM, y * MM_PER_CM)

    def describe(self) -> dict:
        return self.rm.describe()


def from_json(data: dict) -> StageMap:
    return StageMap(_core.from_json(data, formats=(FORMAT,)))


_CACHE: dict = {}


def path_of(archive: str, data_dir: Path | None = None) -> Path:
    return Path(data_dir or DATA_DIR) / f"{archive}.json"


def load(archive: str | None, data_dir: Path | None = None) -> StageMap | None:
    """The stage's map (s400 ...), read once and kept; None when there is none or it cannot be read."""
    if not archive:
        return None
    key = (str(data_dir or DATA_DIR), archive)
    if key not in _CACHE:
        try:
            _CACHE[key] = from_json(json.loads(path_of(archive, data_dir).read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError, zlib.error):
            _CACHE[key] = None
    return _CACHE[key]


def stage_of_snap(snap: dict) -> str | None:
    """The round's stage by its native nav mesh's learning signature (ss_ledger.SIGNATURES), or None."""
    nav = snap.get("nav") if isinstance(snap, dict) else None
    return ss_ledger.stage_of_signature(getattr(nav, "learning_sig", None))


def for_snap(snap: dict, data_dir: Path | None = None) -> StageMap | None:
    """This snapshot's stage map (snap["room_map"] when one is given, as the tests do), or None; never raises."""
    try:
        given = snap.get("room_map") if isinstance(snap, dict) else None
        if isinstance(given, StageMap):
            return given
        if isinstance(given, _core.RoomMap):
            return StageMap(given)
        return load(STAGE_ARCHIVE.get(stage_of_snap(snap)), data_dir)
    except Exception:                                        # noqa: BLE001 - the map never costs the tick
        return None
