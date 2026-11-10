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


def _name_slot(b: bytes, p: int):
    """A Nitro 16-byte name slot: printable name, zero padding, nothing else."""
    s = b[p:p + 16]
    n = s.split(b"\0")[0]
    if not n or len(n) > 15 or not all(0x20 <= c < 0x7F for c in n):
        return None
    if any(c != 0 for c in s[len(n) + 1:]):
        return None
    return n.decode("latin1")


def mdl0_parse(M: bytes) -> dict:
    """Parse an MDL0 model block header.

    Two header shapes exist in this title: single-LOD (model name slot at
    0x20) and multi-LOD (name slots from 0x30, one per LOD, byte 9 = count).
    The dict-offsets table (5 u32, first == last) is located structurally:
    first candidate whose five entries are in-range offsets preceded by that
    many valid name slots.
    """
    if len(M) < 0x90 or M[:4] != b"MDL0":
        raise ValueError("not MDL0")
    size = _u32(M, 4)
    if size > len(M):
        raise ValueError("MDL0 size out of range")
    n = M[9]
    if not 1 <= n <= 3:
        raise ValueError("bad LOD count")
    for t in range(0x20, 0x81, 4):
        tab = [_u32(M, t + 4 * i) for i in range(5)]
        if not all(0 < x < size for x in tab) or tab[0] != tab[4]:
            continue
        ns = t - 16 * n
        if ns < 0x20:
            continue
        names = [_name_slot(M, ns + 16 * i) for i in range(n)]
        if any(x is None for x in names):
            continue
        return {"size": size, "n_lods": n, "names": names, "table_off": t, "table": tab}
    raise ValueError("dict table not found")


def mdl0_bones(M: bytes, info: dict) -> list:
    """Bone names: longest contiguous run of name slots between the dict
    table and the materials dict (table[1]). All 16 phases are tried; the
    longest run wins (the region start is not 16-aligned uniformly)."""
    start, end = info["table_off"] + 20, min(info["table"][1], len(M) - 16)
    best = []
    for phase in range(16):
        cur = []
        p = start + phase
        while p + 16 <= end:
            nm = _name_slot(M, p)
            if nm is None:
                if len(cur) > len(best):
                    best = cur
                cur = []
            else:
                cur.append(nm)
            p += 16
        if len(cur) > len(best):
            best = cur
    return best


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
