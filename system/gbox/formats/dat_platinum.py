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


def repack_dat(buf: bytes, replace: dict[str, bytes] | None = None) -> bytes:
    """Rebuild a Platinum DAT, preserving the original layout.

    ``replace`` maps entry name -> replacement payload bytes. Verified modes:
      * no-op (``replace`` None/empty): consistency-checked, byte-identical
        output — tables, payloads and the unknown hashmap/inter-table regions
        are preserved verbatim;
      * same-size member swap: payload overwritten in place, tables unchanged.

    A size-changing repack needs the shifted-layout path (hash-table extent
    handling, hypothesis: hashmap is name-based so it can be preserved
    verbatim); it is not implemented yet and raises ValueError.
    """
    buf = bytes(buf)
    if buf[:4] != b"DAT\0":
        raise ValueError("not DAT")
    entries = parse_dat(buf)
    n, off_o, ext_o, nam_o, siz_o, _hash = struct.unpack_from("<6I", buf, 4)
    if not n:
        raise ValueError("empty DAT")
    nlen = struct.unpack_from("<I", buf, nam_o)[0]
    for a, b in ((off_o, 4 * n), (ext_o, 4 * n), (nam_o, 4 + n * nlen), (siz_o, 4 * n)):
        if a + b > len(buf):
            raise ValueError("table out of range")
    order = sorted((e.offset, i) for i, e in enumerate(entries))
    for (o1, i1), (o2, _) in zip(order, order[1:]):
        if entries[i1].offset + entries[i1].size > o2:
            raise ValueError(f"payloads overlap: {entries[i1].name}")
    if not replace:
        return buf
    out = bytearray(buf)
    for e in entries:
        if e.name in replace:
            new = bytes(replace[e.name])
            if len(new) != e.size:
                raise ValueError(
                    f"size-changing repack for {e.name} not implemented "
                    f"(needs shifted layout + hash-table handling)")
            out[e.offset:e.offset + e.size] = new
    return bytes(out)
