"""Mr. Driller - Drill Spirits (USA, NDS): inventory-stage reader.

Facts verified against the owned ROM (game 4d136a106256966e):
  * Plain NDS cart, little-endian, ROM offsets absolute from file start.
    FNT/FAT are standard (the earlier "FNT does not parse" note was wrong).
  * Asset containers are 'PAK0': u32 magic, u16 header_size, u16 member_count,
    then (header_size-8)/4 u32 offsets relative to the container (last = end).
  * Game/Character.bin: 8 members; members 0-6 start with a 0x40-byte header
    holding two 16-colour BGR555 palettes (colour 0 = 0x03e0 key green) followed
    by tile data; member 7 is a lone 32-byte palette. Tile layout (4bpp,
    512 B per 32x32 block) is a HYPOTHESIS from sizes, not yet a reader.
No writer exists; this module only inventories and slices.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

TARGET_PATH = "Game/Character.bin"


@dataclass
class NdsFile:
    path: str
    fid: int
    start: int
    size: int


def header(rom: bytes) -> dict:
    a9o, a9e, a9r, a9s = struct.unpack_from("<4I", rom, 0x20)
    a7o, a7e, a7r, a7s = struct.unpack_from("<4I", rom, 0x30)
    fnto, fnts, fato, fats = struct.unpack_from("<4I", rom, 0x40)
    return {
        "title": rom[:12].decode("ascii"), "gamecode": rom[12:16].decode("ascii"),
        "version": rom[0x1E], "unit": rom[0x12],
        "arm9": (a9o, a9e, a9r, a9s), "arm7": (a7o, a7e, a7r, a7s),
        "fnt": (fnto, fnts), "fat": (fato, fats),
        "arm9_sha256": hashlib.sha256(rom[a9o:a9o + a9s]).hexdigest(),
    }


def list_files(rom: bytes) -> list[NdsFile]:
    fnto, _, fato, fats = struct.unpack_from("<4I", rom, 0x40)
    fat = [struct.unpack_from("<2I", rom, fato + 8 * i) for i in range(fats // 8)]
    out: list[NdsFile] = []

    def walk(did: int, prefix: str) -> None:
        off, fid, _ = struct.unpack_from("<IHH", rom, fnto + 8 * (did & 0xFFF))
        p = fnto + off
        while True:
            t = rom[p]; p += 1
            if t == 0:
                return
            name = rom[p:p + (t & 0x7F)].decode("latin1"); p += t & 0x7F
            if t & 0x80:
                sub = struct.unpack_from("<H", rom, p)[0]; p += 2
                walk(sub, prefix + name + "/")
            else:
                s, e = fat[fid]
                if e < s or e > len(rom):
                    raise ValueError(f"FAT entry {fid} out of range")
                out.append(NdsFile(prefix + name, fid, s, e - s)); fid += 1

    walk(0xF000, "")
    return out


def pak_members(blob: bytes) -> list[tuple[int, int]]:
    """Return (offset, size) per member of a PAK0 container; validates ranges."""
    if blob[:4] != b"PAK0":
        raise ValueError("not PAK0")
    hs, cnt = struct.unpack_from("<HH", blob, 4)
    offs = struct.unpack_from("<%dI" % ((hs - 8) // 4), blob, 8)
    if len(offs) < cnt + 1 or offs[cnt] != len(blob) and offs[cnt] > len(blob):
        raise ValueError("bad PAK0 offsets")
    res = []
    for i in range(cnt):
        if not (hs <= offs[i] <= offs[i + 1] <= len(blob)):
            raise ValueError(f"member {i} out of range")
        res.append((offs[i], offs[i + 1] - offs[i]))
    return res


def inventory(rom: bytes) -> dict:
    files = list_files(rom)
    by = {f.path: f for f in files}
    tgt = by[TARGET_PATH]
    blob = rom[tgt.start:tgt.start + tgt.size]
    members = []
    for i, (o, n) in enumerate(pak_members(blob)):
        m = blob[o:o + n]
        members.append({"index": i, "rom_offset": tgt.start + o, "size": n,
                        "sha256": hashlib.sha256(m).hexdigest(),
                        "pal0_key": struct.unpack_from("<H", m, 0)[0]})
    return {"source_sha256": hashlib.sha256(rom).hexdigest(), "header": header(rom),
            "file_count": len(files),
            "pak_containers": sum(1 for f in files if rom[f.start:f.start + 4] == b"PAK0"),
            "target": {"path": TARGET_PATH, "rom_offset": tgt.start, "size": tgt.size,
                       "members": members}}
