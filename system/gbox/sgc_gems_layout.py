"""Verified layout facts for Sonic Gems Collection (USA), game code G2XE8P.

Everything here was derived from the owned disc and re-verified against the
actual bytes of ``main.dol`` and the shipped memory-card saves.  This module
is READ-ONLY: it parses and describes, it never writes a save or a ROM.

Verified facts
--------------
* ``main.dol`` is 2,065,152 bytes, sha256
  ``a57a1d15b993a5881b002089d4ed993da4b43f796988abdad981e9b5269675f9`` and
  carries the game code ``G2XE8P`` at offset 0x00.
* The DOL uses a LINEAR address map: ``VA = file_offset + 0x80003000``.
  Cross-checked on the entry point (VA 0x80005600 -> file 0x2600) and on six
  independent string literals (STATE_JP\\MUSEUM01.STM, STATE_US\\MUSEUM01.STM,
  STATE_US\\MUSEUM10.STM, STATE_US\\MUSEUM01.STG, LMUSEUM\\DEFTIME.PRS,
  MODULE/GEMS.STR) whose VAs round-trip to their exact file offsets.
* The museum state filenames are reached through three tables in the DOL:
  - ``0x801E4C00`` - 30 pointers: STATE_{{JP,US,EU}}\\MUSEUM01..10.STM
  - ``0x801CDF88`` - STATE_{{JP,US,EU}}\\MUSEUM01..06.STG
  - ``0x801E4C88`` - the region back-pointer block used by the .STG path
  ``fn@0x80010810`` is the state-file loader: it indexes those tables by
  region and slot to build the path it opens.
* Each state save holds a table of 2-byte records starting at offset 0x80:
      byte0 = object id
      byte1 = (class << 5) | sub
  The class field (bits 5-7) takes exactly eight values across all sixteen
  shipped saves, and the first 34 records are identical in every save
  (object id 0x81, class 3, sub 0x1F).

Hypothesis (not proven, kept explicit)
--------------------------------------
byte1 looks like a per-object "seen / unlocked" marker whose upper three bits
select one of eight object classes and whose lower five bits are a sub-state,
with class 3 / sub 0x1F meaning "not yet seen".  The eight classes line up
one-for-one with the eight categories the operator asked to inventory, and
the 34 leading unset records plausibly correspond to the first 34 museum
objects that have not been seen yet.  This still needs a runtime check.
"""
from __future__ import annotations

import struct

GAME_ID = "fc5914e3ddb540c4"
PLATFORM = "gamecube"
GAME_CODE = "G2XE8P"
DOL_SHA256 = "a57a1d15b993a5881b002089d4ed993da4b43f796988abdad981e9b5269675f9"
DOL_SIZE = 2065152
DOL_IMAGE_BASE = 0x80003000
SAVE_SIZE = 221248

# --- virtual addresses established in main.dol -----------------------------
STATE_FILENAME_TABLE_VA = 0x801E4C00      # STATE_{JP,US,EU}\MUSEUM01..10.STM
STG_FILENAME_TABLE_VA = 0x801CDF88        # STATE_{JP,US,EU}\MUSEUM01..06.STG
STATE_REGION_BLOCK_VA = 0x801E4C88        # region back-pointers for the .STG path
STATE_LOADER_FN_VA = 0x80010810           # builds the state path and opens it
ENTRY_POINT_VA = 0x80005600

# --- state record layout ---------------------------------------------------
RECORD_TABLE_OFFSET = 0x80
RECORD_SIZE = 2
CLASS_SHIFT = 5
CLASS_MASK = 0xE0
SUB_MASK = 0x1F
UNSET_CLASS = 3
UNSET_SUB = 0x1F
UNSET_BYTE = 0x7F
CLASS_BYTE_VALUES = (0x1F, 0x3F, 0x5F, 0x7F, 0x9F, 0xBF, 0xDF, 0xFF)
LEADING_UNSET_RECORDS = 34

REGIONS = ("JP", "US", "EU")
MUSEUM_SLOTS = 10
STG_SLOTS = 6


def vm_to_file_offset(vm: int) -> int:
    """Map a main.dol virtual address to its file offset (linear map)."""
    return vm - DOL_IMAGE_BASE


def file_offset_to_vm(off: int) -> int:
    return off + DOL_IMAGE_BASE


def state_filenames(region: str) -> tuple:
    """The ten .STM slot names the game uses for one region."""
    if region not in REGIONS:
        raise ValueError("unknown region %r" % (region,))
    return tuple("STATE_%s\\MUSEUM%02d.STM" % (region, i)
                 for i in range(1, MUSEUM_SLOTS + 1))


def stg_filenames(region: str) -> tuple:
    if region not in REGIONS:
        raise ValueError("unknown region %r" % (region,))
    return tuple("STATE_%s\\MUSEUM%02d.STG" % (region, i)
                 for i in range(1, STG_SLOTS + 1))


def decode_records(raw: bytes):
    """Decode the 2-byte object records that start at offset 0x80.

    Returns a list of ``(offset, object_id, class_id, sub)`` tuples.
    """
    out = []
    for off in range(RECORD_TABLE_OFFSET, len(raw) - RECORD_SIZE + 1,
                     RECORD_SIZE):
        b0 = raw[off]
        b1 = raw[off + 1]
        out.append((off, b0, (b1 & CLASS_MASK) >> CLASS_SHIFT, b1 & SUB_MASK))
    return out


def summarise(raw: bytes) -> dict:
    """Summarise one state save: header fields and record statistics."""
    recs = decode_records(raw)
    classes = {}
    for _off, _oid, cls, _sub in recs:
        classes[cls] = classes.get(cls, 0) + 1
    leading = 0
    for off, oid, cls, sub in recs:
        if oid == 0x81 and cls == UNSET_CLASS and sub == UNSET_SUB:
            leading += 1
        else:
            break
    return {
        "size": len(raw),
        "gamecode": raw[0:6].decode("ascii", "replace"),
        "banner": raw[0x08:0x18].split(b"\x00")[0].decode("ascii", "replace"),
        "title": raw[0x40:0x60].split(b"\x00")[0].decode("ascii", "replace"),
        "comment": raw[0x60:0x80].split(b"\x00")[0].decode("ascii", "replace"),
        "record_count": len(recs),
        "class_counts": classes,
        "leading_unset": leading,
    }


# --- content inventory established from the disc and the DOL strings -------
# Twelve museum media entries ship on the owned disc (museum01..museum12);
# each is a playable entry in the Museum layer.
MUSEUM_MEDIA = tuple("museum%02d" % i for i in range(1, 13))

# The Game Select layer exposes sixteen object titles (LYR_MODE_GS_OBJECT_TITLE
# 00..15) and sixteen game-select screens (LYR_MODE_GS_SCR_SELECT_GAME00..15).
GS_OBJECT_TITLES = tuple("LYR_MODE_GS_OBJECT_TITLE%02d" % i for i in range(16))
GS_SELECT_SCREENS = tuple("LYR_MODE_GS_SCR_SELECT_GAME%02d" % i for i in range(16))

# The Mode Select layer exposes four entries (LYR_MODE_MS_SCR_SELECT_01..04).
MS_SELECT_ENTRIES = tuple("LYR_MODE_MS_SCR_SELECT_%02d" % i for i in range(1, 5))

# The twelve Game Gear games reachable from the Museum (GGROM *.CPT).
MUSEUM_GAMES = (
    "SONIC", "SONIC2", "SONIC3", "SANDK", "SONIC3D", "SONICSPN",
    "PUYO_USA", "S_DRIFT2", "SKYPAT", "TAILSADV", "S_TAIL2", "LABYLIN",
)

# The eight categories the operator asked to inventory, with what is actually
# proven so far.  "unknown" means not yet mapped to a named entry - it is NOT
# a claim that the content is absent.
CATEGORY_STATUS = {
    "characters": "unknown",
    "hidden_characters": "unknown",
    "modes": "partial",
    "levels": "partial",
    "stages": "partial",
    "costumes": "unknown",
    "items": "unknown",
    "extras": "unknown",
}

CATEGORY_EVIDENCE = {
    "modes": {
        "entries": list(MS_SELECT_ENTRIES),
        "source": "main.dol strings at 0x801CD5F0..0x801CD740",
    },
    "levels": {
        "entries": list(MUSEUM_GAMES),
        "source": "main.dol GGROM *.CPT strings at 0x801CDE48..0x801CDF74",
    },
    "stages": {
        "entries": list(MUSEUM_MEDIA),
        "source": "owned disc: museum__museum01..12 .adx/.sfd media",
    },
}
