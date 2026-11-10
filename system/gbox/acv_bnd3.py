"""Bounded BND3 (FromSoftware container) parser for Armored Core V (Xbox 360).

Layout (SoulsFormats-compatible): magic 'BND3', 8-byte version, raw format
byte @0x0C, big-endian flag @0x0D, file count @0x10, headers end @0x14,
entries from 0x20.  Entry: flags,pad3,compSize,dataOff[,id][,nameOff][,uncompSize].
Format bits: 0x02 ids, 0x04/0x08 names, 0x10 long offsets, 0x20 compression.
All offsets/sizes are bounds-checked against the buffer; ValueError on violation.
"""
from __future__ import annotations

import struct

MAX_FILES = 100000


def parse_bnd3(buf: bytes) -> dict:
    if len(buf) < 0x20 or buf[:4] != b"BND3":
        raise ValueError("not BND3")
    fmt = buf[0x0C]
    big = bool(buf[0x0D])
    e = ">" if big else "<"
    count, hdr_end = struct.unpack_from(e + "II", buf, 0x10)
    if count > MAX_FILES or hdr_end > len(buf):
        raise ValueError("bad BND3 header")
    long_off = bool(fmt & 0x10)
    has_ids = bool(fmt & 0x02)
    has_names = bool(fmt & 0x0C)
    has_comp = bool(fmt & 0x20)
    size = 8 + (8 if long_off else 4) + (4 if has_ids else 0) + (4 if has_names else 0) + (4 if has_comp else 0)
    if 0x20 + count * size > len(buf):
        raise ValueError("entry table out of range")
    entries = []
    for i in range(count):
        o = 0x20 + i * size
        flags = buf[o]
        csize = struct.unpack_from(e + "I", buf, o + 4)[0]
        p = o + 8
        if long_off:
            doff = struct.unpack_from(e + "Q", buf, p)[0]; p += 8
        else:
            doff = struct.unpack_from(e + "I", buf, p)[0]; p += 4
        eid = None
        name = None
        usize = None
        if has_ids:
            eid = struct.unpack_from(e + "I", buf, p)[0]; p += 4
        if has_names:
            noff = struct.unpack_from(e + "I", buf, p)[0]; p += 4
            if noff >= len(buf):
                raise ValueError("name offset out of range")
            end = buf.find(b"\0", noff)
            if end < 0:
                raise ValueError("unterminated name")
            name = buf[noff:end].decode("shift_jis", "replace")
        if has_comp:
            usize = struct.unpack_from(e + "I", buf, p)[0]
        if doff + csize > len(buf):
            raise ValueError("entry %d data out of range" % i)
        entries.append({"index": i, "flags": flags, "id": eid, "name": name,
                        "offset": doff, "size": csize, "uncompressed_size": usize})
    return {"version": buf[4:12].rstrip(b"\0").decode("ascii", "replace"),
            "format": fmt, "big_endian": big, "entries": entries}


def entry_bytes(buf: bytes, ent: dict) -> bytes:
    return buf[ent["offset"]:ent["offset"] + ent["size"]]


def read_entry(buf: bytes, ent: dict) -> bytes:
    """Entry payload; zlib-inflated (bounded) when the container declares compression."""
    import zlib
    raw = entry_bytes(buf, ent)
    usize = ent.get("uncompressed_size")
    if usize is None or raw[:1] != b"x":
        return raw
    if usize > 256 << 20:
        raise ValueError("uncompressed size too large")
    d = zlib.decompressobj()
    out = d.decompress(raw, usize)
    if len(out) != usize or d.unconsumed_tail:
        raise ValueError("inflate size mismatch")
    return out
