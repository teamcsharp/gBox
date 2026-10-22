"""NDS (NitroFS) inventory + BMD0 header probe for Call of Duty: World at War (CALE).

Header field order at 0x20/0x30 is (rom_offset, entry, ram_address, size).
Bounds-checked: FAT/FNT/files must lie inside the ROM image.
"""
from __future__ import annotations

import hashlib
import struct

BMD0_MAGIC = b"BMD0"


def _u32(d, o):
    if o < 0 or o + 4 > len(d):
        raise ValueError("read out of range")
    return struct.unpack_from("<I", d, o)[0]


def nds_header(d: bytes) -> dict:
    if len(d) < 0x84:
        raise ValueError("short NDS header")
    o9, e9, r9, s9 = struct.unpack_from("<4I", d, 0x20)
    o7, e7, r7, s7 = struct.unpack_from("<4I", d, 0x30)
    fnt, fnts, fat, fats = struct.unpack_from("<4I", d, 0x40)
    for n, off, sz in (("arm9", o9, s9), ("arm7", o7, s7), ("fnt", fnt, fnts), ("fat", fat, fats)):
        if off + sz > len(d):
            raise ValueError(f"{n} outside image")
    return {"title": d[:12].rstrip(b"\0").decode("latin1"), "gamecode": d[12:16].decode("latin1"),
            "arm9": {"off": o9, "entry": e9, "ram": r9, "size": s9,
                     "sha256": hashlib.sha256(d[o9:o9 + s9]).hexdigest()},
            "arm7": {"off": o7, "entry": e7, "ram": r7, "size": s7,
                     "sha256": hashlib.sha256(d[o7:o7 + s7]).hexdigest()},
            "fnt": (fnt, fnts), "fat": (fat, fats)}


def nds_files(d: bytes) -> list[dict]:
    h = nds_header(d)
    fnt, _ = h["fnt"]
    fat, fats = h["fat"]
    out, seen = {}, set()

    def walk(dir_id, path):
        if dir_id in seen:
            raise ValueError("directory cycle")
        seen.add(dir_id)
        base = fnt + (dir_id & 0xFFF) * 8
        sub, fid = struct.unpack_from("<IH", d, base)
        q = fnt + sub
        while True:
            b = d[q]
            q += 1
            if b == 0:
                return
            n = b & 0x7F
            name = d[q:q + n].decode("latin1")
            if len(name) != n:
                raise ValueError("truncated name")
            q += n
            if b & 0x80:
                walk(struct.unpack_from("<H", d, q)[0], path + name + "/")
                q += 2
            else:
                if fid * 8 + 8 > fats:
                    raise ValueError("fat index out of range")
                s, e = struct.unpack_from("<2I", d, fat + fid * 8)
                if e < s or e > len(d):
                    raise ValueError("file extent out of range")
                out[fid] = {"path": path + name, "off": s, "size": e - s}
                fid += 1

    walk(0xF000, "")
    return [out[k] for k in sorted(out)]


def bmd0_probe(b: bytes) -> dict:
    """Parse the BMD0 container header: sections (MDL0/TEX0) must lie inside the file."""
    if len(b) < 16 or b[:4] != BMD0_MAGIC:
        raise ValueError("not BMD0")
    _bom, _ver, size, hdr, n = struct.unpack_from("<HHIHH", b, 4)
    if size != len(b) or n > 8 or hdr + 4 * n > len(b):
        raise ValueError("bad BMD0 header")
    secs = {}
    for i in range(n):
        o = _u32(b, hdr + 4 * i)
        tag = b[o:o + 4]
        sz = _u32(b, o + 4)
        if o + sz > len(b):
            raise ValueError("section out of range")
        secs[tag.decode("latin1")] = {"off": o, "size": sz}
    return {"size": size, "sections": secs}
