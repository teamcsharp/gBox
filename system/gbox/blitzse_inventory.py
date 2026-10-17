"""Exact-build inventory for NFL Blitz: Special Edition (USA), N64 (favorite ad56bf0fc382891b).

The owned HyperSpin zip holds one ``.n64``-named member that is really
byte-swapped v64 data, so the ROM is always read through
:func:`gbox.n64_rom.read` (normalised big-endian z64).  The normalised image is
game code NSZE rev 0, internal name "NFL BLITZ SPECIAL ED", CIC-NUS-6102
(header CRCs 30EAD54F/31620BF6 recompute exactly), (c) 2001 Midway.

Layout recovered from the ROM itself (nothing written, no emulator):

* IPL3 loads ROM 0x1000.. to the entry point 0x80000400 (RAM = ROM +
  0x7FFFF400).  The entry stub sets sp 0x800474E0, clears BSS 0x80049B80 ..
  0x800818B0 and so the resident segment is ROM 0x1000-0x4A780.  Readable game
  code/data (libultra + Blitz strings such as ``GENSEQ.ANI``, ``ARMHND.WMS``,
  ``HEDSHU.WMS``, ``t_ball_tex_data``, the HUGE HEAD/NO HEAD cheat names)
  continues as overlays up to the file system.
* One Midway file system ("fs") lives at ROM 0x1410E0 (preceded by a
  0xFFFFFFFF word): ``b"fs\\x02\\x05"``, u32 0, u32 table_offset, u32 count;
  file data starts at +0x10.  The table (at base + 0xE922B8 = ROM 0xFD3398)
  holds ``count`` 40-byte records sorted by name: ``name[24]`` (NUL padded),
  u32 unpacked_size, u32 offset (relative to the fs base), u32 method,
  u32 stored_size.  In offset order every file starts at
  align8(previous offset + stored size), and the data ends exactly at the
  table.
* Method 5 = stored (unpacked == stored): the 44 team/announcer ``.wbk``
  wave banks (``N64 WaveTables`` magic) and ``genseq.ani``, the shared
  animation-sequence bank (1,213,920 bytes).  Method 4 = packed with a
  Midway codec that is NOT any Okumura LZSS variant (brute-forced flag order,
  literal bit, 12/4 layouts, thresholds and ring/relative windows: 0/20
  samples decode); its decompressor must be located in Ghidra (analysis).
* Character assets visible in the fs: helmet shells/logos (``hel_*``),
  jerseys (``jer_*``), socks/stripes, arm/hand, face sheets and the secret
  big-head textures (``hed_*``: brain, hat, lashun, raiden, rob, sal, shinok,
  skull, thug).  No mesh container exists in the fs (only .wms textures,
  .ani, .bin, .ptr/.wbk/.bfx audio), so player geometry is expected to be
  compiled into the code/data segments, as in the arcade Blitz source.

``python -m gbox.blitzse_inventory SOURCE.zip --out manifest.json`` writes the
manifest.  It refuses any other ROM (gBox mods included) unless
``strict=False``.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

from . import n64_rom
from .mkmyth_inventory import header_crc, ipl3_cic, parse_header

GAME_ID = "ad56bf0fc382891b"
TITLE = "NFL Blitz: Special Edition (USA)"

# Exact build identity (normalised z64), pinned from the owned source.
KNOWN = {
    "source_zip_sha256": "362bd74a0c9ee3a510dce7154dbd4049bad80897efb95b1d5456bac3e79419fe",
    "z64_sha256": "8e861e75e7f16a9baefe2d82525240b68dfb79e01933571537dc5967dd482cc0",
    "z64_sha1": "a109f44bbb3270205205755ba9a889bafc6ff5ab",
    "z64_md5": "7e856fa8f743900feba5a4e28c234af7",
    "z64_size": 0x1000000,
    "game_code": "NSZE",
    "version": 0,
}

ENTRY_POINT = 0x80000400
RAM_DELTA = ENTRY_POINT - 0x1000
BSS = (0x80049B80, 0x800818B0)
RESIDENT_ROM = (0x1000, 0x1000 + BSS[0] - ENTRY_POINT)   # 0x1000-0x4A780

FS_BASE = 0x1410E0
FS_MAGIC = b"fs\x02\x05"
FS_HEADER = struct.Struct(">4sIII")       # magic, zero, table_offset, count
FS_ENTRY = struct.Struct(">24sIIII")      # name, unpacked, offset, method, stored
METHOD_PACKED = 4
METHOD_STORED = 5

# Character-texture families by file-name prefix (fs names are lower case).
CHARACTER_FAMILIES = {
    "helmet": ("hel_",),
    "jersey": ("jer_",),
    "sock": ("sock",),
    "stripe": ("strp",),
    "secret_head": ("hed_",),
    "arm_hand": ("arm_",),
    "face": ("face",),
}


class FsError(ValueError):
    pass


def parse_fs(rom: bytes, base: int = FS_BASE) -> list[dict]:
    """Parse and validate the Midway fs at ``base``; raises FsError if malformed."""
    if base + FS_HEADER.size > len(rom):
        raise FsError("fs header out of range")
    magic, zero, table, count = FS_HEADER.unpack_from(rom, base)
    if magic != FS_MAGIC or zero != 0:
        raise FsError(f"bad fs header {rom[base:base + 8].hex()}")
    tab = base + table
    if count == 0 or tab + count * FS_ENTRY.size > len(rom):
        raise FsError("fs table out of range")
    ents = []
    for i in range(count):
        raw, unpacked, off, method, stored = FS_ENTRY.unpack_from(rom, tab + i * FS_ENTRY.size)
        name = raw.split(b"\0", 1)[0]
        if not re.fullmatch(rb"[!-~]{1,24}", name):
            raise FsError(f"entry {i}: bad name {raw!r}")
        if method not in (METHOD_PACKED, METHOD_STORED):
            raise FsError(f"{name!r}: unknown method {method}")
        if method == METHOD_STORED and unpacked != stored:
            raise FsError(f"{name!r}: stored entry size mismatch")
        if off < FS_HEADER.size or off + stored > table:
            raise FsError(f"{name!r}: data out of range")
        ents.append({"index": i, "name": name.decode(), "offset": off, "stored": stored,
                     "unpacked": unpacked, "method": method, "rom": base + off})
    names = [e["name"].lower() for e in ents]
    if names != sorted(names):
        raise FsError("fs table is not name-sorted")
    pos = FS_HEADER.size
    for e in sorted(ents, key=lambda e: e["offset"]):
        if e["offset"] != pos:
            raise FsError(f"{e['name']}: offset {e['offset']:#x} != chained {pos:#x}")
        pos = (e["offset"] + e["stored"] + 7) & ~7
    if pos != table:
        raise FsError(f"data end {pos:#x} != table {table:#x}")
    return ents


def file_bytes(rom: bytes, entry: dict) -> bytes:
    return rom[entry["rom"]:entry["rom"] + entry["stored"]]


def family(name: str) -> str | None:
    n = name.lower()
    for fam, prefixes in CHARACTER_FAMILIES.items():
        if n.startswith(prefixes) and n.endswith(".wms"):
            return fam
    return None


def resident_names(rom: bytes) -> list[str]:
    """Upper-case asset names the code references directly (e.g. ARMHND.WMS)."""
    hi = min(len(rom), FS_BASE)
    return sorted({m.group().decode() for m in
                   re.finditer(rb"[A-Z0-9_]{3,16}\.(?:WMS|ANI|BIN)(?=\0)", rom[0x1000:hi])})


def identify(rom: bytes, strict: bool = True) -> dict:
    hdr = parse_header(rom)
    cic = ipl3_cic(rom)[0]
    ident = {
        "z64_sha256": hashlib.sha256(rom).hexdigest(),
        "z64_sha1": hashlib.sha1(rom).hexdigest(),
        "z64_md5": hashlib.md5(rom).hexdigest(),
        "z64_size": len(rom),
        "game_code": hdr["game_code"],
        "version": hdr["version"],
        "internal_name": hdr["internal_name"],
        "entry_point": hdr["entry_point"],
        "cic": cic,
        "header_crc_ok": bool(cic) and tuple(header_crc(rom, cic)) == (hdr["crc1"], hdr["crc2"]),
    }
    if strict:
        for k in ("z64_sha1", "z64_size", "game_code", "version"):
            if ident[k] != KNOWN[k]:
                raise ValueError(f"not the owned {TITLE} build: {k}={ident[k]!r}")
    return ident


def inventory(rom: bytes, strict: bool = True) -> dict:
    ident = identify(rom, strict=strict)
    ents = parse_fs(rom)
    ext = Counter(e["name"].rsplit(".", 1)[-1].lower() for e in ents)
    methods = Counter(e["method"] for e in ents)
    fams: dict[str, list[str]] = {}
    for e in ents:
        f = family(e["name"])
        if f:
            fams.setdefault(f, []).append(e["name"])
    wbk = [e for e in ents if e["name"].endswith(".wbk")]
    teams = sorted(e["name"][:-4] for e in wbk)
    wave_ok = sum(file_bytes(rom, e).startswith(b"N64 WaveTables") for e in wbk)
    ani = [e for e in ents if e["name"].endswith(".ani")]
    lower = {e["name"].lower() for e in ents}
    refs = resident_names(rom)
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "identity": ident,
        "layout": {
            "entry_point": ENTRY_POINT,
            "resident_rom": list(RESIDENT_ROM),
            "bss": list(BSS),
            "fs_base": FS_BASE,
            "fs_table": FS_BASE + FS_HEADER.unpack_from(rom, FS_BASE)[2],
            "fs_count": len(ents),
            "fs_end": FS_BASE + FS_HEADER.unpack_from(rom, FS_BASE)[2] + len(ents) * FS_ENTRY.size,
        },
        "extensions": dict(ext),
        "methods": {str(k): v for k, v in methods.items()},
        "packed_codec": "unresolved Midway method 4 (not Okumura LZSS)",
        "character_textures": {k: sorted(v) for k, v in sorted(fams.items())},
        "secret_heads": sorted(n[4:-4] for n in fams.get("secret_head", [])),
        "wave_banks": {"count": len(wbk), "wavetable_magic": wave_ok, "names": teams},
        "animation_banks": [{"name": e["name"], "size": e["stored"],
                             "sha256": hashlib.sha256(file_bytes(rom, e)).hexdigest()} for e in ani],
        "code_referenced_assets": [{"name": n, "in_fs": n.lower() in lower} for n in refs],
        "meshes": "no mesh container in fs; player geometry expected in code/data segments",
        "files": [{k: e[k] for k in ("name", "offset", "stored", "unpacked", "method")} for e in ents],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("source")
    ap.add_argument("--out")
    ap.add_argument("--no-strict", action="store_true")
    a = ap.parse_args(argv)
    src = Path(a.source)
    man = inventory(n64_rom.read(src), strict=not a.no_strict)
    man["source"] = {"path": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest()}
    text = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
