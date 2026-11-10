"""Sonic Heroes (GameCube) ``.one`` archive reader (inventory milestone).

Layout verified on playmodel/so_dff.one of Sonic Heroes (USA).gcz:
  outer chunk  type 0, RW-style 12-byte LE header (type,size,version)
    chunk 1    16 KiB directory: 0x40-byte slots of NUL-padded names
    chunk 2..  one per directory name, in order; payload is Sega PRS
               (gbox.formats.lz.prs_decompress). Decoded DFF payloads are
               RenderWare clumps (type 0x10, LE chunk header, size == len-12).
"""
from __future__ import annotations

import re
import struct

from gbox.formats import lz

HDR = struct.Struct("<III")


def _chunks(data: bytes):
    if len(data) < 12:
        raise ValueError("short ONE")
    t, s, _v = HDR.unpack_from(data, 0)
    if t != 0 or s + 12 > len(data):
        raise ValueError("not a Heroes ONE archive")
    o, end = 12, 12 + s
    while o + 12 <= end:
        t, s, v = HDR.unpack_from(data, o)
        yield t, v, data[o + 12:o + 12 + s]
        o += 12 + s


def names(directory: bytes) -> list[str]:
    return [m.decode("ascii") for m in re.findall(rb"[\x20-\x7e]{4,}", directory)]


def unpack(data: bytes) -> dict[str, bytes]:
    """Return {name: decoded bytes}. Raises on name/chunk count mismatch."""
    ch = list(_chunks(data))
    if not ch or ch[0][0] != 1:
        raise ValueError("missing directory chunk")
    nm = names(ch[0][2])
    body = ch[1:]
    if len(nm) != len(body):
        raise ValueError(f"{len(nm)} names vs {len(body)} chunks")
    return {n: lz.prs_decompress(p) for n, (_t, _v, p) in zip(nm, body)}


def is_clump(b: bytes) -> bool:
    return len(b) >= 12 and HDR.unpack_from(b, 0)[0] == 0x10 and HDR.unpack_from(b, 0)[1] + 12 == len(b)
