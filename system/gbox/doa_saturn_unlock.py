"""Offline research reader for the Sega Saturn build of Dead or Alive (Japan).

Owned source (fingerprinted, never mutated by this module):
  /mnt/gbox/hyperspin/Arcade/collections/Sega Saturn/roms/Dead or Alive (Japan).chd
  CHD v5 (cdlz/cdzl/cdfl), SHA1 88b62945e2af57e624620cfb4a7256384efeca3e,
  streamed SHA256 ba192288469e259bdb35e2b90a4a9ce17b9fc41bc463ea1c15a2dd63c1793a5b.
  Raw extraction (chdman extractcd) yields doa_jp.bin (459,016,320 B).

Status: RESEARCH ONLY. This module parses the owned build and reports the
category inventory (roster/costumes/stages). It performs no writes to the ROM,
the CHD, saves or running sessions, and registers no unlock profile because
runtime verification has not happened yet. gbox.game_unlocks.profile_for stays
unsupported for game_id f01738d1a4522208 until the on-load routine is deployed
and gameplay-verified.

Verified evidence (this request's checkpointed findings, reproducible offline):
1. 00DOA.BIN (ISO LBA 29, 734,684 B, sha256
   b5f37a7140fe530d1d5dbdc6f736a176a4f1a1e8888d4c2eff3795e9060c0610) embeds
   1,274 '.def' STABS debug records at 0x27052..0x3b203 naming the native
   Tecmo Saturn model structs (_POLYGON/_pntbl/_vntbl/_pltbl/_attbl/_texno,
   _GOURAUDTBL, _KAST/_DKAST key-anim, GFS/STM file handles).
2. The first 0x0..0x16e0 of the executable is a fixed-stride (46 B) GFS load
   table of 112 ';1'-suffixed filenames; each entry's mirrored u16 field
   equals ceil(iso_size/2048) for its ISO9660 directory size (47/47 verifiable
   entries match), proving the table drives per-asset CD loading.
3. Character assets follow '<PREFIX><n>_{MDL,TEX,LAD,OPT,TNK}.BIN'; costume n
   indexes variant files (FA1..FA4 = Kasumi variants, LU1..LU5 = Ryu variants).
   *_MDL.BIN is NOT a VDP1 CRX stream (walk breaks at 0x60a; disproven).
4. gbox.doa2usa_inventory / gbox.doa2_chars are Dreamcast PVR readers and are
   incompatible with this build (VDP1-era Tecmo layout, no PVR chunks).
"""
from __future__ import annotations

import hashlib
import json
import re
import struct

GAME_ID = "f01738d1a4522208"
CHD_PATH = "/mnt/gbox/hyperspin/Arcade/collections/Sega Saturn/roms/Dead or Alive (Japan).chd"
CHD_SHA256 = "ba192288469e259bdb35e2b90a4a9ce17b9fc41bc463ea1c15a2dd63c1793a5b"
CHD_SHA1 = "88b62945e2af57e624620cfb4a7256384efeca3e"
EXE_NAME = "00DOA.BIN"
EXE_SHA256 = "b5f37a7140fe530d1d5dbdc6f736a176a4f1a1e8888d4c2eff3795e9060c0610"

# Verified from the 112-entry GFS load table at 00DOA.BIN[0x0..0x16e0].
FILE_TABLE_OFFSET = 0x0
FILE_TABLE_STRIDE = 46
FILE_RECORD = re.compile(rb"([A-Z0-9_]{1,12}\.(?:BIN|SEQ|AVI|TXT));1")

# Verified roster asset families (counted from the 354-file ISO manifest):
# every one of FA/GY/KL/KM/KS/LE/LU/RI/TN ships TNK voice sets and numbered
# MDL/TEX variant sets; FA/GY/KL/KM/KS/LE/LU/TN additionally ship LAD sets.
# TR appears only as TR1_MDL/TEX + TR0_TNK (suspected boss/test entity).
CHARACTER_PREFIXES = ("FA", "GY", "KL", "KM", "KS", "LE", "LU", "RI", "TN")
SUSPECTED_EXTRA_PREFIXES = ("TR",)
ASSET_SUFFIXES = ("MDL", "TEX", "LAD", "OPT", "TNK")

# Categories this build can actually contain (stock Saturn disc, Japan region).
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def parse_file_table(exe_bytes: bytes) -> list[dict]:
    """Return the verified GFS load table entries from 00DOA.BIN head."""
    entries = []
    for match in FILE_RECORD.finditer(exe_bytes[:0x1700]):
        name = match.group(1).decode("ascii")
        off = match.end()
        # Mirrored u16 pair after the NUL terminator holds ceil(size/2048).
        block_count = struct.unpack_from(">H", exe_bytes, off + 1)[0]
        entries.append({"name": name, "table_offset": off - len(match.group(0)),
                        "blocks2k": block_count})
    return entries


def character_inventory(exe_bytes: bytes, iso_manifest: dict) -> dict:
    """Aggregate the category inventory from the load table + ISO manifest.

    iso_manifest maps filename -> [lba, size] as produced by the streamed
    ISO9660 read of doa_jp.bin (see request artifacts).
    """
    table = parse_file_table(exe_bytes)
    # Cross-check: every load-table name must exist in the ISO manifest.
    missing = [e["name"] for e in table if e["name"] not in iso_manifest]
    # Manifest-side variant census (authoritative; the exe table is a tail
    # subset of 112 late-alphabet names, not the whole disc).
    variant_re = re.compile(r"^([A-Z]+)(\d+)_([A-Z]{3})\.BIN$")
    census: dict[str, dict[str, set]] = {}
    for name in iso_manifest:
        hit = variant_re.match(name)
        if hit and hit.group(1) in CHARACTER_PREFIXES + SUSPECTED_EXTRA_PREFIXES \
                and hit.group(3) in ASSET_SUFFIXES:
            per = census.setdefault(hit.group(1), {})
            per.setdefault(hit.group(2), set()).add(hit.group(3))
    return {
        "game_id": GAME_ID,
        "region": "japan",
        "platform": "saturn",
        "load_table_entries": len(table),
        "load_table_names_in_manifest": f"{len(table) - len(missing)}/{len(table)}",
        "roster_prefixes": sorted(c for c in census if c in CHARACTER_PREFIXES),
        "suspected_extra_prefixes": sorted(c for c in census
                                           if c in SUSPECTED_EXTRA_PREFIXES),
        "costume_variants": {p: {n: sorted(s) for n, s in sorted(v.items())}
                             for p, v in sorted(census.items())},
        "asset_kinds": list(ASSET_SUFFIXES),
    }


def unlock_profile(game: dict) -> dict:
    """Honest profile_for response for this exact catalog game/build.

    Returns research_pending (never verified) until the native routine is
    implemented, deployed and gameplay-verified per the standing request.
    """
    if game.get("game_id") != GAME_ID or game.get("platform") != "saturn":
        return {"status": "unsupported", "verified": False}
    return {
        "status": "research_pending", "verified": False, "profile": None,
        "scope": [], "requires_runtime_verification": True,
        "reason": "Saturn Tecmo build: offline inventory published "
                  "(gbox.doa_saturn_unlock); no native unlock routine is "
                  "implemented or gameplay-verified yet, so no save/memory "
                  "write is authorised.",
        "evidence": {
            "chd_sha256": CHD_SHA256, "exe_sha256": EXE_SHA256,
            "debug_symbols": "1274 .def records at 0x27052..0x3b203 in 00DOA.BIN",
            "load_table": "112 GFS ';1' entries, stride 46 B, block fields verified vs ISO",
        },
    }
