"""TimeSplitters 2 (GameCube) unlock research register for request #2280.

Owned revision for game_id=7049196b853fb256 (platform=gamecube):
  main DOL sha256 5c4e544220b7f9576e7f0f78189778b8974caa8c3554a970fea213a8de28e69f
  main DOL bytes  3553088

Write-free by construction: ``profile()`` reports status='pending_research' and
verified=False, so the automatic pre_launch hook in gbox.game_unlocks has no
writer to reach (same gate the DOAX2 profile uses).  The evidence gathered so
far is carried here so the next run resumes without re-deriving it.
"""

from __future__ import annotations

GAME_ID = "7049196b853fb256"
PLATFORM = "gamecube"

# --- measured 2026-10-22 from the owned ISO (GCDisc / gbox.gcdisc) ---
# Owned disc: "TimeSplitters 2 (USA).iso" -> GCDisc.game_id = GTSE4F.
# The community Gecko list (codes.rc24, header "GTSE4F") therefore targets THIS
# exact retail revision; its addresses are candidates for this build, not a
# different image base. Gecko addresses are 6 hex digits offset from 0x80000000.
OWNED_DISC_ID = "GTSE4F"
OWNED_DOL_SHA256 = "5c4e544220b7f9576e7f0f78189778b8974caa8c3554a970fea213a8de28e69f"
OWNED_IMAGE_SPAN = (0x80003100, 0x8046F9A0)   # file-backed text+data
OWNED_BSS_SPAN = (0x80360280, 0x8046F9E0)      # main.dol bss_addr .. bss_addr+bss_size
COMMUNITY_LIST_DISC_ID = "GTSE4F"
# (desc, gecko line, decoded runtime RAM address, write width)
COMMUNITY_UNLOCK_CODES = (
    ("All Cut Scenes",        "0461435C FFFFFFFF", 0x8061435C, 32),
    ("All Story Levels",      "04614360 FFFFFFFF", 0x80614360, 32),
    ("Full Gallery",          "04614364 FFFFFFFF", 0x80614364, 32),
    ("Full Gallery (flags a)","02614388 0005FFFF", 0x80614388, 16),
    ("Full Gallery (flags b)","02614398 0003FFFF", 0x80614398, 16),
    ("All Challenge Levels",  "04614378 FFFFFFFF", 0x80614378, 32),
)
# Mission "complete" codes write an 8-bit flag that lands inside the owned
# main.dol data segment d3 (file-backed) - proof the list matches this build.
COMMUNITY_MISSION_FLAG_SAMPLES = (
    ("Mission 1 - Siberia",      "082CB0DF 00000005", 0x802CB0DF),
    ("Mission 5 - Neo Tokyo",    "082F68F7 00000005", 0x802F68F7),
    ("Mission 10 - Space Station","082C0D57 00000005", 0x802C0D57),
)

CATEGORIES = ["characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras"]

EXECUTABLE_NAME = "ts2 main DOL"
EXECUTABLE_SHA256 = "5c4e544220b7f9576e7f0f78189778b8974caa8c3554a970fea213a8de28e69f"
EXECUTABLE_BYTES = 3553088

# Measured from the owned DOL.  Its header is shifted +0x10 relative to a stock
# DOL header (text addresses at 0x48, data addresses at 0x64).
DOL_SEGMENTS = [
    {
        "kind": "text",
        "index": 0,
        "file_offset": 256,
        "vaddr": 2147496192,
        "size": 9440,
        "file_end": 9696,
        "vaddr_end": 2147505632
    },
    {
        "kind": "text",
        "index": 1,
        "file_offset": 9696,
        "vaddr": 2147505632,
        "size": 2738112,
        "file_end": 2747808,
        "vaddr_end": 2150243744
    },
    {
        "kind": "data",
        "index": 0,
        "file_offset": 2747808,
        "vaddr": 2150243744,
        "size": 32,
        "file_end": 2747840,
        "vaddr_end": 2150243776
    },
    {
        "kind": "data",
        "index": 1,
        "file_offset": 2747840,
        "vaddr": 2150243776,
        "size": 32,
        "file_end": 2747872,
        "vaddr_end": 2150243808
    },
    {
        "kind": "data",
        "index": 2,
        "file_offset": 2747872,
        "vaddr": 2150243808,
        "size": 99744,
        "file_end": 2847616,
        "vaddr_end": 2150343552
    },
    {
        "kind": "data",
        "index": 3,
        "file_offset": 2847616,
        "vaddr": 2150343552,
        "size": 679648,
        "file_end": 3527264,
        "vaddr_end": 2151023200
    },
    {
        "kind": "data",
        "index": 4,
        "file_offset": 3527264,
        "vaddr": 2152103552,
        "size": 1760,
        "file_end": 3529024,
        "vaddr_end": 2152105312
    },
    {
        "kind": "data",
        "index": 5,
        "file_offset": 3529024,
        "vaddr": 2152111008,
        "size": 24064,
        "file_end": 3553088,
        "vaddr_end": 2152135072
    }
]

DATA_SPAN = "0x802A1DA0-0x8046F9A0"
LOADED_TEXT_BASE = "0x80003100"

BLOCKERS = [
    "Ghidra MCP bridge (127.0.0.1:8080) refused connections this run; ghidra_bridge job on JAYBUILTFINALE reports PyGhidra missing (gbox ghidra-bridge-install required offline). i9-NUC unavailable. No xref/lock-check analysis completed.",
    "Community unlock-block addresses (0x8061435C-0x80614398) fall 6.07 MB beyond the owned DOL text base and 1.68 MB beyond BSS end - they do NOT resolve inside the owned DOL's loaded image (0x80003100-0x8046F9A0, 4.42 MB). The community list targets a different image base (NTSC-U retail DOL loads at a shifted base). The equivalent runtime block on the owned revision must be re-derived, not reused.",
    "Mission-complete flag samples (0x802CB0DF/0x802F68F7/0x802C0D57) DO resolve inside owned DOL data segment d3 (file-backed, file offsets 0x2C80DF/0x2F38F7/0x2BDD57) - confirming the community list matches this build's mission layout, but the unlock block location differs.",
    "No lock-check xref analysis, menu-eligibility trace or runtime save inspection completed, so no category can be marked 'unlocked' and no writer is published."
]
NEXT_STEPS = [
    "Bring the Ghidra bridge back up (install PyGhidra offline on JAYBUILTFINALE via `gbox ghidra-bridge-install`, or re-open on Spark) and run get_xrefs_to on the owned DOL's mission-flag bytes in data segment d3 (0x2C80DF, 0x2F38F7, 0x2BDD57) to find the code that reads/writes the mission-complete table and the equivalent runtime unlock block.",
    "Trace from the d3 mission-flag table to locate the owned revision's per-character/mode unlock block - the community 0x04614360 equivalent is at a different runtime address on this build (the community list's 0x806143xx block is out-of-DOL at a shifted image base).",
    "Determine whether TS2 stores progress in the memory-card save or in SRAM/EEPROM, then implement the monotonic progress writer behind verified=True.",
    "Re-run runtime acceptance on an idle authorised worker (i9-NUC or Spark) with an isolated save overlay: boot, select each discovered character and mode, second launch, then rollback."
]

# Community code-list entries for the NTSC-U retail build, recorded as
# hypotheses only: the owned revision uses a different image base.
COMMUNITY_CODE_CANDIDATES = [
    {
        "name": "All Story Levels",
        "addr": "0x04614360",
        "write": "04 FFFFFFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    },
    {
        "name": "All Cut Scenes",
        "addr": "0x0461435C",
        "write": "04 FFFFFFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    },
    {
        "name": "Full Gallery",
        "addr": "0x04614364",
        "write": "04 FFFFFFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    },
    {
        "name": "Full Gallery hi words",
        "addr": "0x02614388",
        "write": "02 0005FFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    },
    {
        "name": "Full Gallery lo words",
        "addr": "0x02614398",
        "write": "02 0003FFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    },
    {
        "name": "All Challenge Levels",
        "addr": "0x04614378",
        "write": "04 FFFFFFFF",
        "list": "RC24 GTSE4F (NTSC-U retail)",
        "status": "unverified_candidate",
        "maps_into_owned_dol": False
    }
]

CATEGORY_INVENTORY = {
    "characters": [
        {
            "name": "serbian",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'serbian' not found in owned main DOL"
        },
        {
            "name": "clegg",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'clegg' not found in owned main DOL"
        },
        {
            "name": "hoxey",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'hoxey' not found in owned main DOL"
        },
        {
            "name": "dux",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'dux' not found in owned main DOL"
        },
        {
            "name": "marco",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'marco' present in owned main DOL at file offset 0x2ab129"
        },
        {
            "name": "agent 14",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'agent 14' not found in owned main DOL"
        },
        {
            "name": "agent",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'agent' not found in owned main DOL"
        },
        {
            "name": "kim",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'kim' present in owned main DOL at file offset 0x2a36f9"
        },
        {
            "name": "serge",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'serge' not found in owned main DOL"
        },
        {
            "name": "vip",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'vip' not found in owned main DOL"
        },
        {
            "name": "terrorist",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'terrorist' not found in owned main DOL"
        }
    ],
    "hidden_characters": [
        {
            "name": "serbian",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'serbian' not found in owned main DOL"
        },
        {
            "name": "clegg",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'clegg' not found in owned main DOL"
        },
        {
            "name": "hoxey",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'hoxey' not found in owned main DOL"
        },
        {
            "name": "dux",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'dux' not found in owned main DOL"
        },
        {
            "name": "marco",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'marco' present in owned main DOL at file offset 0x2ab129"
        },
        {
            "name": "agent 14",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'agent 14' not found in owned main DOL"
        },
        {
            "name": "secret agent",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'secret agent' not found in owned main DOL"
        },
        {
            "name": "unlock",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'unlock' not found in owned main DOL"
        }
    ],
    "modes": [
        {
            "name": "challenge",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'challenge' present in owned main DOL at file offset 0x2aae8c"
        },
        {
            "name": "arcade",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'arcade' present in owned main DOL at file offset 0x2a5567"
        },
        {
            "name": "warzone",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'warzone' present in owned main DOL at file offset 0x2aa60a"
        },
        {
            "name": "time attack",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'time attack' not found in owned main DOL"
        },
        {
            "name": "race",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'race' present in owned main DOL at file offset 0x2a161d"
        },
        {
            "name": "dungeon",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'dungeon' not found in owned main DOL"
        },
        {
            "name": "multiplayer",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'multiplayer' not found in owned main DOL"
        },
        {
            "name": "museum",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'museum' not found in owned main DOL"
        },
        {
            "name": "gallery",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'gallery' not found in owned main DOL"
        },
        {
            "name": "ranked",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'ranked' not found in owned main DOL"
        },
        {
            "name": "survival",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'survival' not found in owned main DOL"
        },
        {
            "name": "boss",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'boss' present in owned main DOL at file offset 0x2a3776"
        },
        {
            "name": "time splitter",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'time splitter' not found in owned main DOL"
        },
        {
            "name": "time splinter",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'time splinter' not found in owned main DOL"
        }
    ],
    "levels": [
        {
            "name": "siberia",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'siberia' present in owned main DOL at file offset 0x2a4a85"
        },
        {
            "name": "chicago",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'chicago' present in owned main DOL at file offset 0x2aaf2a"
        },
        {
            "name": "notre dame",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'notre dame' not found in owned main DOL"
        },
        {
            "name": "neo tokyo",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'neo tokyo' not found in owned main DOL"
        },
        {
            "name": "wild west",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'wild west' not found in owned main DOL"
        },
        {
            "name": "atom smasher",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'atom smasher' not found in owned main DOL"
        },
        {
            "name": "aztec",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'aztec' present in owned main DOL at file offset 0x2a22e9"
        },
        {
            "name": "robot factory",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'robot factory' not found in owned main DOL"
        },
        {
            "name": "space station",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'space station' not found in owned main DOL"
        },
        {
            "name": "precinct",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'precinct' not found in owned main DOL"
        },
        {
            "name": "tower of babel",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'tower of babel' not found in owned main DOL"
        },
        {
            "name": "carnival",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'carnival' not found in owned main DOL"
        },
        {
            "name": "western",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'western' present in owned main DOL at file offset 0x2a25f1"
        },
        {
            "name": "himalaya",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'himalaya' not found in owned main DOL"
        },
        {
            "name": "backstage",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'backstage' not found in owned main DOL"
        },
        {
            "name": "security station",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'security station' not found in owned main DOL"
        },
        {
            "name": "gothic",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'gothic' present in owned main DOL at file offset 0x2b3f70"
        },
        {
            "name": "flesh",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'flesh' not found in owned main DOL"
        },
        {
            "name": "bone",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'bone' present in owned main DOL at file offset 0x2a09a4"
        },
        {
            "name": "pirate",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'pirate' present in owned main DOL at file offset 0x2ae4a8"
        },
        {
            "name": "cowboy",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'cowboy' present in owned main DOL at file offset 0x2a35f9"
        },
        {
            "name": "lumberjack",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'lumberjack' not found in owned main DOL"
        },
        {
            "name": "viking",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'viking' present in owned main DOL at file offset 0x2ae554"
        },
        {
            "name": "manhattan",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'manhattan' not found in owned main DOL"
        },
        {
            "name": "highlands",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'highlands' not found in owned main DOL"
        },
        {
            "name": "deep space",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'deep space' not found in owned main DOL"
        },
        {
            "name": "desert",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'desert' present in owned main DOL at file offset 0x2a4329"
        },
        {
            "name": "golf",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'golf' not found in owned main DOL"
        },
        {
            "name": "death match",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'death match' not found in owned main DOL"
        },
        {
            "name": "deathmatch",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'deathmatch' not found in owned main DOL"
        }
    ],
    "stages": [
        {
            "name": "siberia",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'siberia' present in owned main DOL at file offset 0x2a4a85"
        },
        {
            "name": "chicago",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'chicago' present in owned main DOL at file offset 0x2aaf2a"
        },
        {
            "name": "notre dame",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'notre dame' not found in owned main DOL"
        },
        {
            "name": "neo tokyo",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'neo tokyo' not found in owned main DOL"
        },
        {
            "name": "wild west",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'wild west' not found in owned main DOL"
        },
        {
            "name": "atom smasher",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'atom smasher' not found in owned main DOL"
        },
        {
            "name": "aztec",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'aztec' present in owned main DOL at file offset 0x2a22e9"
        },
        {
            "name": "robot factory",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'robot factory' not found in owned main DOL"
        },
        {
            "name": "space station",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'space station' not found in owned main DOL"
        },
        {
            "name": "precinct",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'precinct' not found in owned main DOL"
        },
        {
            "name": "carnival",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'carnival' not found in owned main DOL"
        },
        {
            "name": "gothic",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'gothic' present in owned main DOL at file offset 0x2b3f70"
        }
    ],
    "costumes": [
        {
            "name": "costume",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'costume' not found in owned main DOL"
        },
        {
            "name": "outfit",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'outfit' not found in owned main DOL"
        },
        {
            "name": "skin",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'skin' present in owned main DOL at file offset 0x2a3eed"
        },
        {
            "name": "model",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'model' not found in owned main DOL"
        },
        {
            "name": "serbian",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'serbian' not found in owned main DOL"
        },
        {
            "name": "clegg",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'clegg' not found in owned main DOL"
        },
        {
            "name": "hoxey",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'hoxey' not found in owned main DOL"
        },
        {
            "name": "dux",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'dux' not found in owned main DOL"
        },
        {
            "name": "marco",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'marco' present in owned main DOL at file offset 0x2ab129"
        }
    ],
    "items": [
        {
            "name": "weapon",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'weapon' not found in owned main DOL"
        },
        {
            "name": "gun",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'gun' present in owned main DOL at file offset 0x2a0b4b"
        },
        {
            "name": "rifle",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'rifle' present in owned main DOL at file offset 0x2a60e6"
        },
        {
            "name": "pistol",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'pistol' present in owned main DOL at file offset 0x2a0b23"
        },
        {
            "name": "grenade",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'grenade' present in owned main DOL at file offset 0x2a07c5"
        },
        {
            "name": "knife",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'knife' not found in owned main DOL"
        },
        {
            "name": "ammo",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'ammo' present in owned main DOL at file offset 0x2a0624"
        },
        {
            "name": "pickup",
            "state": "unknown",
            "present_in_executable": True,
            "evidence": "ascii 'pickup' present in owned main DOL at file offset 0x2aee17"
        }
    ],
    "extras": [
        {
            "name": "gallery",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'gallery' not found in owned main DOL"
        },
        {
            "name": "cutscene",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'cutscene' not found in owned main DOL"
        },
        {
            "name": "cut scene",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'cut scene' not found in owned main DOL"
        },
        {
            "name": "replay",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'replay' not found in owned main DOL"
        },
        {
            "name": "movie",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'movie' not found in owned main DOL"
        },
        {
            "name": "extra",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'extra' not found in owned main DOL"
        },
        {
            "name": "secret",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'secret' not found in owned main DOL"
        },
        {
            "name": "encyclopedia",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'encyclopedia' not found in owned main DOL"
        },
        {
            "name": "cheat",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'cheat' not found in owned main DOL"
        },
        {
            "name": "unlock",
            "state": "not_observed",
            "present_in_executable": False,
            "evidence": "ascii 'unlock' not found in owned main DOL"
        }
    ]
}


def segment_for_vaddr(vaddr):
    """Return the owning segment dict for a loaded virtual address, or None."""
    for seg in DOL_SEGMENTS:
        if seg["vaddr"] <= vaddr < seg["vaddr_end"]:
            return seg
    return None


def file_offset_for_vaddr(vaddr):
    """Translate a loaded virtual address to a file offset in the owned DOL."""
    seg = segment_for_vaddr(vaddr)
    if seg is None:
        raise ValueError("vaddr 0x%08X is not mapped in the owned DOL" % vaddr)
    return seg["file_offset"] + (vaddr - seg["vaddr"])


def matches_revision(sha256):
    """True only for the exact owned revision this profile was built against.

    Any future writer must refuse to run on a different hash.
    """
    if not sha256:
        return False
    return sha256.strip().lower() == EXECUTABLE_SHA256


def _all_items():
    out = []
    for category, entries in CATEGORY_INVENTORY.items():
        for entry in entries:
            item = dict(entry)
            item["category"] = category
            out.append(item)
    return out


def profile():
    """Revision-guarded, still-unverified research profile for TS2."""
    return {
        "status": "pending_research",
        "profile": None,
        "verified": False,
        "game_id": GAME_ID,
        "platform": PLATFORM,
        "scope": list(CATEGORIES),
        "exclusions": [
            "online competitive advantage patches",
            "account entitlements",
            "content absent from the owned revision (no invented DLC)",
        ],
        "evidence": {
            "executable_name": EXECUTABLE_NAME,
            "executable_sha256": EXECUTABLE_SHA256,
            "executable_bytes": EXECUTABLE_BYTES,
            "dol_segments": DOL_SEGMENTS,
            "loaded_text_base": LOADED_TEXT_BASE,
            "loaded_data_span": DATA_SPAN,
            "community_code_candidates": COMMUNITY_CODE_CANDIDATES,
            "community_code_caveat": (
                "unlock-block addresses (0x8061435C-0x80614398) are out-of-DOL on the "
                "owned revision (6.07 MB beyond text base); mission-flag samples "
                "(0x802CBxxx) resolve inside owned data segment d3 - the community "
                "list matches this build's mission layout but the unlock block is at a "
                "different runtime address"),
            "blockers": list(BLOCKERS),
            "next_steps": list(NEXT_STEPS),
        },
        "items": _all_items(),
        "save_effect": "None (no writer reachable while verified=False)",
        "requires_live_testing": True,
        "requires_save_reverse_engineering": True,
        "reason": (
            "Owned TS2 revision hashed and its DOL map measured, but lock checks, "
            "progress flags and save layout are not yet resolved, and the Ghidra "
            "bridge was offline for this run. No category can be marked unlocked, "
            "so no writer is published."),
    }


def profile_gate():
    """Gate payload consumed by gbox.game_unlocks.profile_for."""
    return {
        "status": "pending_research",
        "verified": False,
        "scope": list(CATEGORIES),
        "reason": (
            "TS2 unlock research for the owned revision is incomplete: "
            "progress/save layout and lock checks unresolved."),
    }
