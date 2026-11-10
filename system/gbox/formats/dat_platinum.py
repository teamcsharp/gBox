"""PlatinumGames DAT container (Bayonetta/Bayonetta 2 character packs, e.g. pl0000.dat).

Layout (little-endian): "DAT\0", file_count, offsets_off, ext_off, names_off,
sizes_off, hashmap_off.  Names table = u32 name_len + count*name_len NUL-padded
names.  Parsed from the public Bayonetta modding spec; proven here against the
owned Bayonetta 2 pl0000/pl0005/pl0010 packs (counts/sizes consistent).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass
class DatEntry:
    name: str
    ext: str
    offset: int
    size: int


def parse_dat(buf: bytes) -> list[DatEntry]:
    if buf[:4] != b"DAT\0":
        raise ValueError("not DAT")
    n, off_o, ext_o, nam_o, siz_o, _hash = struct.unpack_from("<6I", buf, 4)
    nlen = struct.unpack_from("<I", buf, nam_o)[0]
    out = []
    for i in range(n):
        offset = struct.unpack_from("<I", buf, off_o + 4 * i)[0]
        size = struct.unpack_from("<I", buf, siz_o + 4 * i)[0]
        ext = buf[ext_o + 4 * i: ext_o + 4 * i + 4].split(b"\0")[0].decode("ascii", "replace")
        name = buf[nam_o + 4 + nlen * i: nam_o + 4 + nlen * (i + 1)].split(b"\0")[0].decode("ascii", "replace")
        if offset + size > len(buf):
            raise ValueError(f"entry {name} out of range")
        out.append(DatEntry(name, ext, offset, size))
    return out
