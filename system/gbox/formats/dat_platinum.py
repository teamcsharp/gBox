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

    ``replace`` maps entry key -> replacement payload bytes. Key is
    ``"name.ext"``; a bare ``name`` is accepted only when unambiguous (that
    name occurs once in the file). Verified modes:
      * no-op (``replace`` None/empty): consistency-checked, byte-identical
        output — tables, payloads and the unknown hashmap/inter-table regions
        are preserved verbatim;
      * same-size member swap: payload overwritten in place, tables unchanged;
      * shorter (donor) swap: new payload written at the head of the slot,
        original trailing bytes preserved — file size, offset/size tables,
        alignment and the per-member hash region stay byte-identical
        (the loader reads exactly ``size`` bytes; the inert original tail is
        ignored by WMB section parsing).

    Longer replacements raise ValueError (needs a shifted-layout rebuild
    with hash-region semantics; open, pending the ExeFS loader oracle).
    Open question for the loader oracle: if the game verifies per-member
    content hashes at load, changed payloads will fail that check regardless
    of swap mode.
    """
    buf = bytes(buf)
    if buf[:4] != b"DAT\x00":
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
    names = [e.name for e in entries]
    out = bytearray(buf)
    for e in entries:
        full = f"{e.name}.{e.ext}" if e.ext and not e.name.endswith("." + e.ext) else e.name
        if full in replace:
            key = full
        elif e.name in replace:
            if names.count(e.name) > 1:
                raise ValueError(
                    f"ambiguous replace key {e.name!r}; use {e.name}.{e.ext}")
            key = e.name
        else:
            continue
        new = bytes(replace[key])
        if len(new) > e.size:
            raise ValueError(
                f"longer replacement for {e.name} not implemented "
                f"({len(new)} > {e.size}; needs shifted layout + hash-table handling)")
        out[e.offset:e.offset + len(new)] = new
    return bytes(out)
