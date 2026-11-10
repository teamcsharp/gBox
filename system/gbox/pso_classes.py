"""The executable's object-class registry: what a placement record's `kind` low byte means.

A placement record in a `map_*o.dat` set carries a `kind` word whose low byte is a **class id** -- the same id space the
game's own object registry uses. The registry is an array of name pointers in the executable, and it is **self-calibrating**:
find the string ``TObjCityDoor_Shop``, find the pointer to it, and the array is 0x46 entries (4 bytes each) before that
pointer. That anchor is not a coincidence -- round 46 matched four placement records to the four city doors by position and
got Shop/Guild/Warp/Med in the order 0x46..0x49, and those are exactly the four names at those slots.

Measured on `PsoV3.dol` (i9-NUC 2026-11-10):

```
=====  ==============================   ==========================================
slot   name                              evidence in this lane
=====  ==============================   ==========================================
0x40   TObjCamera                       --
0x42   TObjChip                         --
0x44   TObjCityAirCar_Ctrl              a record at world (308,211) is this class
0x45   TObjCityAirCar_Car               --
0x46   TObjCityDoor_Shop                matched at (-165,147.5) in round 46
0x47   TObjCityDoor_Guild               matched at (185,173); does not transition
0x48   TObjCityDoor_Warp                matched at (254,25); **does** transition
0x49   TObjCityDoor_Med                 matched at (193.5,-93.5)
0x4a   TObjCityDoor_Lobby               --
0x4c-55 TObjCity_Season_*               nine seasonal decorations
=====  ==============================   ==========================================
```

Empty slots are zeros in the array: a third of the ids are unused, which is why a naive "is every slot a name" score comes
out around 0.67 -- the array is contiguous and sparse, not ragged.
"""
from __future__ import annotations

import struct

from . import pso_dol as D

ANCHOR_NAME = "TObjCityDoor_Shop"
ANCHOR_SLOT = 0x46
ENTRY_SIZE = 4
MAX_SLOTS = 0x400


class ClassError(ValueError):
    """The registry could not be located in this executable."""


def _cstr(dol: bytes, off: int, limit: int = 96) -> str | None:
    end = dol.find(b"\x00", off, off + limit)
    if end <= off:
        return None
    raw = dol[off:end]
    if not raw or any(b < 32 or b > 126 for b in raw):
        return None
    return raw.decode("ascii")


def table_offset(dol: bytes) -> int:
    """The file offset of the registry's first slot, found from the Shop anchor."""
    found = D.find_string(dol, ANCHOR_NAME)
    if found is None:
        raise ClassError(f"{ANCHOR_NAME} is not in this executable")
    hits = D.find_pointers(dol, found["address"])
    if not hits:
        raise ClassError(f"nothing points at {ANCHOR_NAME}")
    return hits[0]["offset"] - ANCHOR_SLOT * ENTRY_SIZE


def registry(dol: bytes, slots: int = 0x60) -> dict[int, str | None]:
    """``{class id: name}`` for the low ids -- enough to name every city class and the seasonal ones."""
    base = D.header(dol)["image_base"]
    start = D.header(dol)["code_start"]
    table = table_offset(dol)
    out: dict[int, str | None] = {}
    for i in range(slots):
        off = table + i * ENTRY_SIZE
        if off + ENTRY_SIZE > len(dol):
            break
        ptr = struct.unpack_from(">I", dol, off)[0]
        name = None
        if base <= ptr < base + len(dol):
            name = _cstr(dol, start + (ptr - base))
        out[i] = name
    return out


def name_of(dol: bytes, kind: int) -> str | None:
    """The class name a placement record's ``kind`` word refers to, or None when the slot is empty.

    ``kind`` carries flags in its upper bits, so only the low byte is used as the id -- the same masking the door helper in
    `pso_editor` does.
    """
    return registry(dol).get(int(kind) & 0xFF)
