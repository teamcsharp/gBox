"""007 - Nightfire (USA) GameCube (GO7E69) -- analysis-stage map of the on-foot character data.

Pinned from Nightfire.elf (sha256 ef49ce2b...3367) with a capstone scan of lis/addi and bl xrefs, and cross-checked
against headless Ghidra (gBox job 44ac2a3bf14a44df: 4754 functions, PowerPC:BE:32 auto-detected from the ELF):

  0x80044780  HT_File name builder: sprintf("%s%8.8x.bin", "gc/" | "common/", hash) (string 0x801a5730),
              then 0x80051b64 (lookup by hashcode) / 0x800519d4.
  0x80044a38  Bondcombat skin check: 0x80051e7c(0x05000000) then 0x80051b64(0x05000007); on failure prints
              "***** FATAL : Bondcombat skin must be loaded on all levels!" (0x801a5774, xref 0x80044a84).
  0x80058e5c  HT_Level dependency walk: compares each needed hashcode's family with 0x06000000, 0x03000000 and
              0x05000000 and reports "HT_Script / HT_Skin 0x%x not loaded in HT_Level %x" (0x801a74a0).
  0x800457cc  "Skin 0x%x not loaded" after the per-actor 0x80056534 resource releases.
  0x8005c7a8  level loader call into the EDL module (see gbox.nightfire_edl).

A decompressed EDL level (all 31 decode to their exact unpacked size) has the SAME layout as the on-disc hash
packs (`nightfire_inventory.pack_index`): u32 BE table size, u32 BE count, LE size + type byte + name entries.
The pack type byte maps to HT families as follows on this build:

  type 3   0x05xxxxxx HT_Skin, payload starts with its own hash (LE) and three 1.0f scale floats,
           then a bone-remap byte table (0xFF, 0x80, 0x81, ...); Bondcombat = 0x05000007 (4320 B)
  type 6   SKELnnnn  skeletons (u16 index, u8 bone count, ...)
  type 5   0x06xxxxxx HT_Script / animation scripts (self-hashed)
  type 0/1/2/11  0x01xxxxxx objects (header 00000000 1400000e <hash BE>): models/textures
  type 7/8/12    0x06 / 0x08 / misc records;  13/14 = "GC EXTRA STATIC"/"GC EXTRA DISCARD"
"""
from __future__ import annotations

import hashlib
import struct
from collections import Counter, defaultdict

from .nightfire_edl import decompress
from .nightfire_inventory import pack_index

HT_SKIN, HT_SCRIPT = 0x05000000, 0x06000000
BONDCOMBAT_SKIN = 0x05000007
TYPE_NAMES = {3: "skin", 5: "script", 6: "skeleton", 0: "object", 1: "object", 2: "object", 11: "object",
              7: "record06", 8: "record08", 12: "misc", 13: "extra_static", 14: "extra_discard"}
XREFS = {"HT_FileName": 0x80044780, "BondcombatCheck": 0x80044A38, "BondcombatHashSite": 0x80044A70,
         "HT_LevelDeps": 0x80058E5C, "SkinNotLoaded": 0x800457CC, "HT_Lookup": 0x80051B64,
         "HT_FamilyLoaded": 0x80051E7C, "LevelLoaderEDL": 0x8005C7A8}


def level_index(edl: bytes) -> tuple[bytes, dict]:
    """Decompress one gc/0700xxxx.bin EDL level and index it as a hash pack."""
    data = decompress(edl)
    return data, pack_index(data)


def skin_header(payload: bytes) -> dict:
    """Fixed head of an HT_Skin (type 3) payload: self hash, three scale floats, five header bytes."""
    if len(payload) < 0x15:
        raise ValueError("skin payload shorter than its 0x15-byte head")
    h, sx, sy, sz = struct.unpack_from("<I3f", payload, 0)
    return {"hash": f"{h:#010x}", "scale": [sx, sy, sz], "head": list(payload[0x10:0x15])}


def census(levels: dict[str, tuple[bytes, dict]]) -> dict:
    """Per-type counts, the skins each level carries and the Bondcombat skin's presence/identity."""
    types, skins, bond = Counter(), defaultdict(list), {}
    for name, (data, idx) in sorted(levels.items()):
        for e in idx["entries"]:
            types[TYPE_NAMES.get(e["type"], f"type{e['type']}")] += 1
            if e["type"] == 3:
                skins[e["name"].lower()].append(name)
                if int(e["name"], 16) == BONDCOMBAT_SKIN:
                    p = data[e["offset"]:e["offset"] + e["size"]]
                    bond[name] = {"size": e["size"], "sha256": hashlib.sha256(p).hexdigest(),
                                  **skin_header(p)}
    return {"types": dict(types), "distinct_skins": len(skins),
            "skins": {k: sorted(v) for k, v in sorted(skins.items())}, "bondcombat": bond}
