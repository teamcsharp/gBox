"""PSO's object-class registry: a placement's class index -> its class name.

Every `.dat` placement carries `kind = flags | class_index` (`pso_setdata.kind_class`). The class index is an
index into a flat table of class-name pointers in `PsoV3.dol` at **`0x805D3138`** (240 slots, 4 bytes each;
148 named in this build, the rest zero). It is the table that turns a marker's number into `TObjCityDoor_Guild`,
`TOSwitchAttack`, `TObjAreaWarpForest` or `TORockCaveBL02` - the last open decompile
`docs/research/pso-gc-executable.md` section 7.3 named as "the single highest-value decompile left for the
editor".

How it was found and checked:

* the four room-10 door entities were walked live and their kinds measured (`0x46` Shop, `0x47` Guild, `0x48` Warp,
  `0x49` Med); searching the .data name-pointer sections for the alignment where those four indices land on
  exactly those four names gives this base and stride (4/4, and no other alignment matches more than 1/4);
* it labels **44 of the 60 class indices** the 141 object-set files use, **15,975 of 18,927 placements (84.4%)**;
* the 16 unresolved ids are real holes in this build's table (`0x05`, `0x06`, `0x08`, `0x0a`, `0x0c`, `0x0e`,
  `0x13`, `0x1e`, `0x22`, `0x4b`, `0x61`, `0x67`, `0x74`, `0xc4`, `0xc5`, `0xc8`) - their classes exist (the sets
  spawn them) but the name slot is zero, so :func:`label` reports `class_0xNN` rather than inventing a name.

`derive(dol)` re-reads the table from a decompressed `PsoV3.dol`; `tools/verify_pso_classes.py` runs it.
"""

from __future__ import annotations

import struct

TABLE_ADDRESS = 0x805D3138
SLOTS = 240


class RegistryError(ValueError):
    pass


#: class index -> class name, None where this build leaves the slot empty
CLASS_NAMES = (
    'TORockCaveBL02', 'TORockCaveBL03', 'TOSensor', None,
    'TOSensorAncient01', None, None, 'TOSensorGeneral01',
    None, 'TOSignCave01', None, 'TOSignCave02',
    None, 'TOSignCave03', None, 'TOSparkMachine01',
    'TOSwitchAttack', 'TOSwitchAttackSub', 'TOSwitchItem', None,
    'TOSwitchTimer', None, 'symbolchatcolli.prs', 'TOSymbolchatColli',
    'TOTrap', None, None, 'TOTrapAncient01',
    None, None, None, 'TOTrapAncient02',
    'TOTrapAncient02R', None, None, 'TOVS2',
    'TOVS2Wreck01', 'TOVS2Wreck02', 'TOVS2Wreck03', 'TOVS2Wreck04',
    'TOVS2Wreck05', 'TOVS2Wreck06', 'TOVS2Wall01', None,
    'TObjMapWarpAncient', 'TObjGoalWarpAncient', None, None,
    'TOWreckAncient', 'TOWreckAncient01', 'TOWreckAncient04', 'TOWreckAncient05',
    'TOWreckAncient06', 'TOWreckAncient07', 'TOWreckAncientBrakable', 'TOWreckAncientBrakable05',
    'TOWreckAncient02', None, 'TOWreckAncient03', None,
    'TObjBgmCol', 'TObjBgmColCtrl', 'TButterfly', None,
    'TObjCamera', None, 'TObjChip', None,
    'TObjCityAirCar_Ctrl', 'TObjCityAirCar_Car', 'TObjCityDoor_Shop', 'TObjCityDoor_Guild',
    'TObjCityDoor_Warp', 'TObjCityDoor_Med', 'TObjCityDoor_Lobby', None,
    'TObjCity_Season_EasterEgg', 'TObjCity_Season_ValentineHeart', 'TObjCity_Season_XmasTree', 'TObjCity_Season_XmasWreath',
    'TObjCity_Season_HalloweenPumpkin', 'TObjCity_Season_21_21', 'TObjCity_Season_SonicAdv2', 'TObjCity_Season_Board',
    'TObjCity_Season_FireWorkCtrl', 'TObjCity_Season_FireWork', None, None,
    None, None, None, None,
    'TObjCityMainWarp', 'TObjCityAreaWarp', 'TObjCityMapWarp', 'TObjLaboMapWarp',
    'TObjCityMainWarpChallenge', None, None, None,
    None, 'TObjComputer', 'TObjGbAdvance', None,
    None, None, None, None,
    'TObjContainerBase', 'TObjContainerItem', 'TObjContainerEnemy', 'TObjContainerNoItem',
    'TObjContainerAbeEnemy', None, 'TContainerAncient01', 'TContainerAncient01R',
    None, 'TObjContainerIdo', None, None,
    'TObjContainerJung', 'TObjContainerJungEx', 'TObjContainerJungEnemy', None,
    'TObjDoaEx01', None, 'TObjDoor', None,
    None, 'TObjDoorJung', None, 'TObjDoorKey',
    'TObjEnvSound', 'TObjEnvSoundEx', 'TObjEnvSoundGlobal', None,
    'TObjEvtCollision', None, None, None,
    None, None, None, 'TObjHashiBase',
    'TObjHashi', 'TObjHashiVersus1', 'TObjHashiVersus2', None,
    'TObjInfoCol', None, 'TObjItemLight', None,
    None, 'TKomorebi', 'TObjLazerFenceNorm', 'TObjLazerFenceExtra',
    'TObjLazerFence4', None, 'TLazerFenceSw', None,
    'TObjLight', None, 'TMapCsnCtrl', None,
    'TObjMesBase', None, None, 'TMotorcycle',
    'TObjParticle', None, 'TObjPlayerSet', None,
    'TObjQuestColBase', 'TObjQuestCol', 'TObjQuestColA', 'TObjQuestColALock',
    'TObjQuestColApc', 'TObjQuestColApcIN', 'TObjQuestColApcINW', 'TQuestColCtrl',
    'TObjQuestColALock2', 'TObjQuestCol2', 'TObjRaderCol', 'TObjRaderHideCol',
    'TObjRaderIcon', None, 'TObjRain', None,
    'TObjRainCtrl', None, 'TObjSinBoard', 'PSO______099',
    None, None, None, 'TObjTank',
    None, None, 'TObjTuitate', 'TObjBigTuitate',
    None, 'TObjWarpBase', 'TObjMapWarp', 'TObjMapWarpForest',
    'TObjAreaWarp', 'TObjAreaWarpForest', 'TObjAreaWarpQuest', 'TObjAreaWarpEnding',
    'TObjMapForceWarp', 'TObjWarpString', 'TObjAreaWarpEndingJung', None,
    'TObjWarpBoss', 'TObjWarpBossMulti', 'TObjWarpBoss03', None,
    'TObjWarpJung', 'TObjWarpJungMain', 'TObjWarpLobby', None,
    'TObjLuker', None, 'TObjRoomId', None,
    None, None, 'TPacket', None,
    None, None, 'TPhotonConcentrate', None,
    'TPhotonEstlla', None, 'TPhotonFarlla', None,
    'TPhotonGolla', None, 'TPhotonLaser', None,
)


def name(index: int):
    """The class name for a class index, or None for an empty slot / out-of-range index."""
    if not isinstance(index, int) or not 0 <= index < SLOTS:
        return None
    return CLASS_NAMES[index]


def class_index(kind_or_index: int):
    """The class index inside a placement's `kind` (its low byte), or the bare index when already small."""
    return int(kind_or_index) & 0xFF


def label(kind_or_index: int, *, unnamed: str = "class_{index:#04x}") -> str:
    """A placement's class name, or `class_0xNN` for a slot this build leaves unnamed."""
    index = class_index(kind_or_index)
    found = name(index)
    return found if found else unnamed.format(index=index)


def index_of(class_name: str):
    """The class index of a name (first match), or None."""
    try:
        return CLASS_NAMES.index(class_name)
    except ValueError:
        return None


def derive(dol: bytes):
    """Re-read the registry from a decompressed `PsoV3.dol` -> tuple of names/None."""
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    sections = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]

    def read(va, n):
        for off0, addr, size in sections:
            if addr <= va < addr + size:
                return dol[off0 + va - addr: off0 + va - addr + n]
        raise RegistryError(f"address {va:#x} is not in a mapped section")

    def cstr(va):
        raw = read(va, 48).split(b"\0")[0]
        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise RegistryError(f"{va:#x} does not hold a class name") from exc
        return text if text and text[0].isalpha() else None

    table = []
    for i in range(SLOTS):
        ptr = struct.unpack(">I", read(TABLE_ADDRESS + 4 * i, 4))[0]
        table.append(cstr(ptr) if ptr and 0x80000000 <= ptr < 0x80600000 else None)
    return tuple(table)


def verify(dol: bytes) -> dict:
    """Compare the pinned table with a DOL's own -> {ok, mismatches}."""
    try:
        derived = derive(dol)
    except RegistryError as exc:
        return {"ok": False, "mismatches": [{"why": str(exc)}]}
    mismatches = [{"slot": i, "pinned": want, "image": got}
                  for i, (want, got) in enumerate(zip(CLASS_NAMES, derived)) if want != got]
    return {"ok": not mismatches, "mismatches": mismatches}

