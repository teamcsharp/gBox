"""NFL Blitz Pro (USA) GameCube (GFVE5D) owned-build inventory.

Facts verified against the owned ``NFL Blitz Pro (USA).gcz`` (Dolphin GCZ, sub_type 0, image 1459978240 bytes):
- gcz sha256 973a209f08e8abb77daf8bd3ebbb3bd8d5cd2bc873f009bf02d9aa81b16074e5 (file 1228174428 bytes);
  main.dol 3390720 bytes sha256 91e3553184a532f56437bea02126918407669b65013db58114ce7f4fd8802953.
- FST (disc offset, size): blitzpro.tpl 0x360000/153664, opening.bnr, blitzopt.obf, blitz04.mpk 0x3891ac/386857088,
  resimg1.dat 0x17480000/342614592, movies/*.h4m.  (An earlier note listing blitzpro.tpl as 334 MB was wrong.)
- ``PAK `` container, BIG-endian: u32 magic, u32 0x200 (version), u32 size-ish (0x170e3d40 / 0x146be060; within
  ~0x4400 / 0x1e0 of the FST size - not exact, treat as hypothesis), u32 header-ish (0x6c10 / 0x110),
  u32 count-ish (0x4f1c / 0xc0), u32 0x200000.  blitz04.mpk directory records start at 0x40 with a 4-digit id
  ("1000","1002",...) NUL padded to 16 bytes; sub-records name parts like ``c0130_1`` (142 distinct names
  in the directory, all prefix ``c``).  NOT yet a model reader; field meanings are unproven.
"""
from __future__ import annotations

import hashlib
import re
import struct

PAK_MAGIC = b"PAK "


class FormatError(ValueError):
    pass


def sha256_stream(path, chunk=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def pak_header(b: bytes) -> dict:
    if len(b) < 0x18:
        raise FormatError("short PAK header")
    if b[:4] != PAK_MAGIC:
        raise FormatError("not a PAK container")
    ver, size, f3, f4, f5 = struct.unpack_from(">5I", b, 4)
    return {"version": ver, "size_field": size, "field_0c": f3, "field_10": f4, "field_14": f5}


def pak_entries(b: bytes, limit: int | None = None) -> list[dict]:
    """Directory entries (4-digit id records) found in the leading directory bytes; bounded by len(b)."""
    hdr = pak_header(b)
    end = min(len(b), limit if limit is not None else hdr["field_0c"])
    out = []
    for i in range(0x40, max(end - 32, 0x40), 16):
        if re.fullmatch(rb"\d{4}\x00{12}", b[i:i + 16]) and b[i + 16:i + 32] == b"\0" * 16:
            out.append({"offset": i, "id": b[i:i + 4].decode()})
    return out


def part_names(b: bytes, limit: int) -> list[str]:
    return sorted({m.decode() for m in re.findall(rb"c\d{4}_\d", b[:limit])})
