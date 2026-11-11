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


def registry(dol: bytes, slots: int = 0x100) -> dict[int, str | None]:
    """``{class id: name}`` for ids 0..``slots``. The lobby sets use 0x80..0x8c, so the window must reach past 0x60."""
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


#: name prefix -> family, most specific first. The editor groups and colours a placement's marker by this.
FAMILIES = (
    ("TObjCityDoor", "door"),
    ("TObjCityMainWarp", "warp"),
    ("TObjCityAreaWarp", "warp"),
    ("TObjCityMapWarp", "warp"),
    ("TObjMapWarp", "warp"),
    ("TObjGoalWarp", "warp"),
    ("TObjAreaWarp", "warp"),
    ("TObjMapForceWarp", "warp"),
    ("TObjWarp", "warp"),
    ("TOSwitch", "switch"),
    ("TOTrap", "trap"),
    ("TOSensor", "sensor"),
    ("TOSign", "sign"),
    ("TORock", "prop"),
    ("TOWreck", "prop"),
    ("TOVS2", "prop"),
    ("TObjCityAirCar", "prop"),
    ("TObjCity_Season", "decor"),
    ("TButterfly", "decor"),
    ("TObjCamera", "effects"),
    ("TObjBgmCol", "effects"),
    ("TObjCollision", "collision"),
    ("TObj", "object"),
    ("TO", "object"),
)

#: The table's address **and** its slot list as they were read independently (branch `ds-pso-class-registry-20261110`,
#: 2026-11-10): 240 slots, 148 named, the rest zero. They are cross-check data, not the module's source of truth - the
#: registry above is located from the anchor at run time, and the tests below prove the two agree on this build. Keeping
#: the list is what makes a *silently different* executable (a patched DOL, another region) show up as a failure.
PINNED_ADDRESS = 0x805D3138
PINNED_NAMES = ['TORockCaveBL02', 'TORockCaveBL03', 'TOSensor', None, 'TOSensorAncient01', None, None, 'TOSensorGeneral01', None, 'TOSignCave01', None, 'TOSignCave02', None, 'TOSignCave03', None, 'TOSparkMachine01', 'TOSwitchAttack', 'TOSwitchAttackSub', 'TOSwitchItem', None, 'TOSwitchTimer', None, 'symbolchatcolli.prs', 'TOSymbolchatColli', 'TOTrap', None, None, 'TOTrapAncient01', None, None, None, 'TOTrapAncient02', 'TOTrapAncient02R', None, None, 'TOVS2', 'TOVS2Wreck01', 'TOVS2Wreck02', 'TOVS2Wreck03', 'TOVS2Wreck04', 'TOVS2Wreck05', 'TOVS2Wreck06', 'TOVS2Wall01', None, 'TObjMapWarpAncient', 'TObjGoalWarpAncient', None, None, 'TOWreckAncient', 'TOWreckAncient01', 'TOWreckAncient04', 'TOWreckAncient05', 'TOWreckAncient06', 'TOWreckAncient07', 'TOWreckAncientBrakable', 'TOWreckAncientBrakable05', 'TOWreckAncient02', None, 'TOWreckAncient03', None, 'TObjBgmCol', 'TObjBgmColCtrl', 'TButterfly', None, 'TObjCamera', None, 'TObjChip', None, 'TObjCityAirCar_Ctrl', 'TObjCityAirCar_Car', 'TObjCityDoor_Shop', 'TObjCityDoor_Guild', 'TObjCityDoor_Warp', 'TObjCityDoor_Med', 'TObjCityDoor_Lobby', None, 'TObjCity_Season_EasterEgg', 'TObjCity_Season_ValentineHeart', 'TObjCity_Season_XmasTree', 'TObjCity_Season_XmasWreath', 'TObjCity_Season_HalloweenPumpkin', 'TObjCity_Season_21_21', 'TObjCity_Season_SonicAdv2', 'TObjCity_Season_Board', 'TObjCity_Season_FireWorkCtrl', 'TObjCity_Season_FireWork', None, None, None, None, None, None, 'TObjCityMainWarp', 'TObjCityAreaWarp', 'TObjCityMapWarp', 'TObjLaboMapWarp', 'TObjCityMainWarpChallenge', None, None, None, None, 'TObjComputer', 'TObjGbAdvance', None, None, None, None, None, 'TObjContainerBase', 'TObjContainerItem', 'TObjContainerEnemy', 'TObjContainerNoItem', 'TObjContainerAbeEnemy', None, 'TContainerAncient01', 'TContainerAncient01R', None, 'TObjContainerIdo', None, None, 'TObjContainerJung', 'TObjContainerJungEx', 'TObjContainerJungEnemy', None, 'TObjDoaEx01', None, 'TObjDoor', None, None, 'TObjDoorJung', None, 'TObjDoorKey', 'TObjEnvSound', 'TObjEnvSoundEx', 'TObjEnvSoundGlobal', None, 'TObjEvtCollision', None, None, None, None, None, None, 'TObjHashiBase', 'TObjHashi', 'TObjHashiVersus1', 'TObjHashiVersus2', None, 'TObjInfoCol', None, 'TObjItemLight', None, None, 'TKomorebi', 'TObjLazerFenceNorm', 'TObjLazerFenceExtra', 'TObjLazerFence4', None, 'TLazerFenceSw', None, 'TObjLight', None, 'TMapCsnCtrl', None, 'TObjMesBase', None, None, 'TMotorcycle', 'TObjParticle', None, 'TObjPlayerSet', None, 'TObjQuestColBase', 'TObjQuestCol', 'TObjQuestColA', 'TObjQuestColALock', 'TObjQuestColApc', 'TObjQuestColApcIN', 'TObjQuestColApcINW', 'TQuestColCtrl', 'TObjQuestColALock2', 'TObjQuestCol2', 'TObjRaderCol', 'TObjRaderHideCol', 'TObjRaderIcon', None, 'TObjRain', None, 'TObjRainCtrl', None, 'TObjSinBoard', 'PSO______099', None, None, None, 'TObjTank', None, None, 'TObjTuitate', 'TObjBigTuitate', None, 'TObjWarpBase', 'TObjMapWarp', 'TObjMapWarpForest', 'TObjAreaWarp', 'TObjAreaWarpForest', 'TObjAreaWarpQuest', 'TObjAreaWarpEnding', 'TObjMapForceWarp', 'TObjWarpString', 'TObjAreaWarpEndingJung', None, 'TObjWarpBoss', 'TObjWarpBossMulti', 'TObjWarpBoss03', None, 'TObjWarpJung', 'TObjWarpJungMain', 'TObjWarpLobby', None, 'TObjLuker', None, 'TObjRoomId', None, None, None, 'TPacket', None, None, None, 'TPhotonConcentrate', None, 'TPhotonEstlla', None, 'TPhotonFarlla', None, 'TPhotonGolla', None, 'TPhotonLaser', None]


def family_of_name(name: str | None) -> str:
    """The family of a class name: door, warp, switch, trap, sensor, sign, prop, decor, effects, collision, object.

    "unknown" for a slot this build leaves empty. The grouping is what the editor page colours markers by; it is derived
    from the name only, so a class this lane has never seen still lands somewhere sensible.
    """
    if not name:
        return "unknown"
    for prefix, group in FAMILIES:
        if name.startswith(prefix):
            return group
    return "object"


def label(dol: bytes, kind: int, *, unnamed: str = "class_{id:#04x}") -> str:
    """A placement's class name, or ``class_0xNN`` for a slot this build leaves empty (never an invented name)."""
    found = name_of(dol, kind)
    return found if found else unnamed.format(id=int(kind) & 0xFF)


def family(dol: bytes, kind: int) -> str:
    """The family of a placement's class (see :func:`family_of_name`)."""
    return family_of_name(name_of(dol, kind))


def sections(dol: bytes) -> list[tuple[int, int, int]]:
    """The DOL's real ``(file offset, address, size)`` triples (the 18 entries at 0x00 / 0x48 / 0x90).

    ``pso_dol`` documents a **flat** offset/address mapping (file 0x100 = image base, contiguous). That holds for the
    first two sections only: this executable's triples jump from file 0x2620 (address 0x8000F740) to file 0x426E00
    (address 0x8000E520), so past 0x8000F740 the flat map is off by hundreds of kilobytes. The table here is the
    authoritative mapping and it is what puts the class registry at address **0x805D3138** rather than 0x804FEB58.
    """
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    return [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]


def address_of(dol: bytes, offset: int) -> int:
    """The address the game sees the file byte at ``offset`` at, via the section table."""
    for file_off, addr, size in sections(dol):
        if file_off <= offset < file_off + size:
            return addr + (offset - file_off)
    raise ClassError(f"file offset {offset:#x} is not in any section")


def offset_of(dol: bytes, address: int) -> int | None:
    """The file offset of an address, via the section table (None when the address is not in this image)."""
    for file_off, addr, size in sections(dol):
        if addr <= address < addr + size:
            return file_off + (address - addr)
    return None


def vtable_census(dol: bytes, slots: int = 0x100) -> dict[int, list[int]]:
    """``{class id: [file offsets of the words that hold that slot's address]}``.

    A class's vtable begins with a pointer to its **registry slot** (the array entry itself), then ``0x00010000``, two
    zero words, its methods and two data pointers. So a word anywhere in the image that equals slot *i*'s address is a
    vtable header for class *i*. Measured on `PsoV3.dol`: only **38 of the 148 named classes** have one, and not one of
    the named ``TObj*`` placement classes does (the city pad included) - the executable's C++ objects are engine classes,
    and placements are dispatched by id somewhere else, which is what `docs/research/pso-gc-traversal.md` records.
    """
    table = table_offset(dol)
    wanted = {}
    for i in range(slots):
        off = table + i * ENTRY_SIZE
        if off + ENTRY_SIZE > len(dol):
            break
        wanted[address_of(dol, off)] = i
    found: dict[int, list[int]] = {}
    limit = len(dol) - 4
    for off in range(0x100, limit, 4):        # the DOL header is not code or data
        value = struct.unpack_from(">I", dol, off)[0]
        slot = wanted.get(value)
        if slot is not None:
            # the registry array itself holds those addresses in its slots; a vtable header does not sit in the table
            if not (table <= off < table + slots * ENTRY_SIZE):
                found.setdefault(slot, []).append(off)
    return {slot: sorted(offs) for slot, offs in sorted(found.items())}


def instantiated(dol: bytes, slots: int = 0x100) -> list[int]:
    """The class ids this build actually instantiates as C++ objects (those with a vtable header)."""
    return sorted(vtable_census(dol, slots))


def name_of(dol: bytes, kind: int) -> str | None:
    """The class name a placement record's ``kind`` word refers to, or None when the slot is empty.

    ``kind`` carries flags in its upper bits, so only the low byte is used as the id -- the same masking the door helper in
    `pso_editor` does.
    """
    return registry(dol).get(int(kind) & 0xFF)
