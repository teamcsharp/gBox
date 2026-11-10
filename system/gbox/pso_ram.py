"""PSO Episode I & II (GameCube, ``GPOE8P`` / exec ``PsoV3.dol``) RAM map: named addresses and readers.

Everything here is an address the repo already drives live, re-proven against the executable on the
owned disc: 17 of the code addresses below match byte-exact prologues in ``PsoV3.dol`` (see
``docs/research/pso-gc-executable.md`` for the guard table and the Ghidra project), and the data
addresses are the globals those routines touch.

The module is pure: nothing here opens an emulator. Callers pass an object with
``read_memory(address, length) -> bytes`` (the Dolphin adapter's primitive), so the readers work
against a live session, a RAM dump, or a synthetic byte map in a test. That is deliberate -- the bot
has burned sessions before on an address map that only the adapter could exercise.

Layout facts used below (all big-endian; a GameCube is a big-endian PowerPC):

* ``0x804FE120``  unsigned byte   the game phase / state machine (10 -> 3 -> 9 through a boot)
* ``0x805D5FC0``  u32             the current **floor id** (0 Pioneer 2, 1 Forest 1 ... 14 Dark Falz)
* ``0x805D6060``  u32             the current **episode**, 0-based (0 = Episode I, 1 = Episode II)
* ``0x805D49B8``  u32             non-zero while an area transition is in flight
* ``0x80515BA0``  block           travel state; the destination floor is stored at +0xC
* ``0x8050EA10``  4 x u32         the player slot table: the four u32s are actor pointers
* ``0x8050D460``  u32             the live entity/object table base
* ``0x805D541C``  u32             pointer to the per-floor item **table** array (18 entries)
* ``0x805D5420``  u32             pointer to the per-floor item **count** array (18 entries)
* ``0x805D4E68`` / ``0x805D6000`` / ``0x805D6014`` / ``0x805D5650``   collision roots

Actor field offsets (a "player" is an actor pointer from the slot table; the same offsets are the
object layout for entities, which is why ``room`` at +0x28 and the class string at +0x00 are shared):

    +0x000  char*     class string  ("TObjPlayer", "TObjDoorKey", ...)
    +0x028  u16       room
    +0x038  f32 x     +0x03C f32 y     +0x040 f32 z      world position
    +0x0A8  u32       active hit-record count (non-zero while an attack is live)
    +0x0AC  u32       per-object native state
    +0x0C8  u16       stage-flag index (low 16 bits)
    +0x2B8  u16       max HP
    +0x324  u16       control mode -- the player update/input path. **Do not force it on a player.**
    +0x326  u16       action state (the probe-locked "attacking" value the speed gate matches)
    +0x32C  u16       HP

The floor ids are the proven Episode I order from :mod:`gbox.pso_fence` (``FLOOR_NAMES_EP1``); the
Episode II numbering differs and is not asserted here.
"""
from __future__ import annotations

import struct

# ------------------------------------------------------------------------------------------------ address constants

PHASE = 0x804FE120
FLOOR = 0x805D5FC0
EPISODE_FLOOR = 0x805D6060
TRAVELLING = 0x805D49B8
TRAVEL_STATE = 0x80515BA0
TRAVEL_DESTINATION = TRAVEL_STATE + 0xC

PLAYER_SLOTS = 0x8050EA10
PLAYER_SLOTS_COUNT = 4
ENTITY_TABLE = 0x8050D460

# The boot-screen id (u8) and its mirror: 3 = PRESS START, 1 = the title main menu, 9 = the ONLINE GAME submenu,
# 0 = transient, 4 = the title with its menu closed. Proven live; see gbox.pso_menu_walk for the transitions.
BOOT_SCREEN = 0x80516303
BOOT_SCREEN_MIRROR = 0x805145F7

FLOOR_ITEM_TABLE = 0x805D541C
FLOOR_ITEM_COUNTS = 0x805D5420
FLOOR_ITEM_RECORD = 36

COLLISION_ROOTS = (0x805D4E68, 0x805D6000, 0x805D6014, 0x805D5650)

# Code addresses (entry points; the guards in docs/research/pso-gc-executable.md prove each one).
UPDATE_PLAYER = 0x801BB330
OBJECT_CREATE = 0x801057A8
OBJECT_DELETE = 0x80103748
INVENTORY = 0x801B8310
EQUIP = 0x801B9F40
UNEQUIP = 0x801B9D50
SET_TARGET = 0x80228540
BEGIN_TRAVEL = 0x8000F998
WARP = 0x801BAB1C
FLOOR_RECORD = 0x802077CC
FLOOR_MAP_VARIANT = 0x80207E88
FLOOR_HEIGHT_QUERY = 0x800791BC
PLAYER_UPDATER = 0x801B7998
STAGE_FLAG_ACCESSOR = 0x80229220
FENCE_UPDATE = 0x80192DC4
FENCE_DROP = 0x80154764
FENCE_RAISE = 0x80154788

# Actor field offsets.
OFF_CLASS = 0x000
OFF_ROOM = 0x028
OFF_X = 0x038
OFF_Y = 0x03C
OFF_Z = 0x040
OFF_HIT_RECORDS = 0x0A8
OFF_NATIVE_STATE = 0x0AC
OFF_STAGE_FLAG = 0x0C8
OFF_HP_MAX = 0x2B8
OFF_CONTROL_MODE = 0x324
OFF_ACTION_STATE = 0x326
OFF_HP = 0x32C

RAM_START = 0x80000000
RAM_END = 0x81800000                     # 24 MiB of GameCube main RAM
_POSITION = struct.Struct(">3f")

# The three guards that identify a build. `PsoV3.dol`, not `main.dol` (a 213,952-byte AppSwitcher stub).
GAME_ID = "GPOE8P"
DOL_SHA256 = "1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a"

# Episode I floor ids -> names (gbox.pso_fence.FLOOR_NAMES_EP1, the proven order).
FLOOR_NAMES_EP1 = {0: "Pioneer2", 1: "Forest1", 2: "Forest2", 3: "Cave1", 4: "Cave2", 5: "Cave3",
                   6: "Mine1", 7: "Mine2", 8: "Ruins1", 9: "Ruins2", 10: "Ruins3",
                   11: "Dragon", 12: "DeRolLe", 13: "VolOpt", 14: "DarkFalz"}


class RamError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ reader

class Reader:
    """Big-endian accessors over anything with ``read_memory(address, length) -> bytes``.

    Every read is range-checked against the GameCube's RAM window and the length is verified, so a
    truncated read raises here instead of silently producing a wrong player position.
    """

    def __init__(self, memory):
        if not callable(getattr(memory, "read_memory", None)):
            raise TypeError("memory source needs read_memory(address, length)")
        self.memory = memory

    def read(self, address: int, length: int) -> bytes:
        if not isinstance(address, int) or not RAM_START <= address < RAM_END:
            raise RamError(f"{address!r} is outside the GameCube RAM window")
        if not isinstance(length, int) or length <= 0 or address + length > RAM_END:
            raise RamError(f"{length!r} bytes at {address:#x} runs past RAM")
        data = self.memory.read_memory(address, length)
        if data is None or len(data) != length:
            raise RamError(f"short read at {address:#x}: wanted {length}, got "
                           f"{0 if data is None else len(data)}")
        return bytes(data)

    def u8(self, address):
        return self.read(address, 1)[0]

    def u16(self, address):
        return struct.unpack(">H", self.read(address, 2))[0]

    def u32(self, address):
        return struct.unpack(">I", self.read(address, 4))[0]

    def s32(self, address):
        return struct.unpack(">i", self.read(address, 4))[0]

    def f32(self, address):
        return struct.unpack(">f", self.read(address, 4))[0]

    def position(self, actor):
        return _POSITION.unpack(self.read(actor + OFF_X, 12))

    def cstring(self, address, limit=32):
        return self.read(address, limit).split(b"\0")[0].decode("latin-1", "replace")


# ------------------------------------------------------------------------------------------------ readers

def boot_screen(reader) -> int:
    """The boot-screen id: 3 PRESS START, 1 the title main menu, 9 the ONLINE GAME submenu, 0 transient,
    4 the title with its menu closed. See :mod:`gbox.pso_menu_walk` for the proven transitions."""
    return reader.u8(BOOT_SCREEN)


def phase(reader) -> int:
    """The game phase/state-machine byte (10 -> 3 -> 9 through a cold boot)."""
    return reader.u8(PHASE)


def floor(reader) -> int:
    """The current floor id (see :data:`FLOOR_NAMES_EP1` for Episode I)."""
    return reader.u32(FLOOR)


def episode(reader) -> int:
    """The current episode as 1 or 2 (the stored value is 0-based)."""
    return reader.u32(EPISODE_FLOOR) + 1


def travelling(reader) -> bool:
    """True while an area transition is in flight (do not issue another one)."""
    return bool(reader.u32(TRAVELLING))


def travel_destination(reader) -> int:
    """The floor id the in-flight transition is loading."""
    return reader.u32(TRAVEL_DESTINATION)


def floor_name(reader) -> str | None:
    """The Episode I name of the current floor, or None when the id is off the proven table."""
    return FLOOR_NAMES_EP1.get(floor(reader))


def player_slots(reader) -> list[int]:
    """The four actor pointers of the player slot table (0 = empty slot)."""
    return list(struct.unpack(">4I", reader.read(PLAYER_SLOTS, 4 * PLAYER_SLOTS_COUNT)))


def player(reader, slot: int = 0) -> dict | None:
    """One player's live state, or None when the slot holds no actor.

    ``slot`` is 0-based (slot 0 is player 1). The class string is read to refuse a stale pointer:
    a slot whose actor is not a ``TObjPlayer`` is reported as None rather than as a player with
    nonsense HP.
    """
    if not 0 <= slot < PLAYER_SLOTS_COUNT:
        raise RamError(f"player slot {slot!r} outside 0..{PLAYER_SLOTS_COUNT - 1}")
    ptr = player_slots(reader)[slot]
    if ptr == 0:
        return None
    cls = reader.cstring(ptr + OFF_CLASS, 16)
    if cls != "TObjPlayer":
        return None
    x, y, z = reader.position(ptr)
    return {"slot": slot, "pointer": ptr, "cls": cls,
            "hp": reader.u16(ptr + OFF_HP), "hp_max": reader.u16(ptr + OFF_HP_MAX),
            "x": x, "y": y, "z": z, "room": reader.u16(ptr + OFF_ROOM),
            "control_mode": reader.u16(ptr + OFF_CONTROL_MODE),
            "action_state": reader.u16(ptr + OFF_ACTION_STATE),
            "hit_records": reader.u32(ptr + OFF_HIT_RECORDS)}


def players(reader) -> dict[int, dict]:
    """{1-based player number: state} for every occupied slot."""
    out = {}
    for slot in range(PLAYER_SLOTS_COUNT):
        p = player(reader, slot)
        if p is not None:
            out[slot + 1] = p
    return out


def entity_table(reader) -> int:
    """The base of the live object/entity table (walker not modelled here)."""
    return reader.u32(ENTITY_TABLE)


def floor_items(reader) -> list[dict]:
    """The floor's item records: [{id, code}] from the per-floor table, in table order.

    ``FLOOR_ITEM_TABLE`` / ``FLOOR_ITEM_COUNTS`` are **pointer** arrays indexed by floor id; each
    item record is 36 bytes with the item code at +16 (3 bytes) and the instance id at +28.
    """
    fid = floor(reader)
    if not 0 <= fid < 18:
        raise RamError(f"floor id {fid} outside 0..17")
    counts = reader.u32(FLOOR_ITEM_COUNTS)
    tables = reader.u32(FLOOR_ITEM_TABLE)
    count = reader.u32(counts + fid * 4)
    if not 0 <= count <= 512:
        raise RamError(f"floor {fid} reports {count} items; refusing to read that")
    if not count:
        return []
    record = reader.u32(tables + fid * 4)
    data = reader.read(record, count * FLOOR_ITEM_RECORD)
    return [{"id": struct.unpack_from(">I", data, i * FLOOR_ITEM_RECORD + 28)[0],
             "code": data[i * FLOOR_ITEM_RECORD + 16:i * FLOOR_ITEM_RECORD + 19].hex()}
            for i in range(count)]


def collision_roots(reader) -> tuple[int, ...]:
    """The four collision root pointers the native geometry provider walks."""
    return tuple(reader.u32(a) for a in COLLISION_ROOTS)


def snapshot(reader) -> dict:
    """One read-only status record: phase, floor, episode, transition, players."""
    return {"phase": phase(reader), "floor": floor(reader), "floor_name": floor_name(reader),
            "episode": episode(reader), "travelling": travelling(reader),
            "players": players(reader)}
