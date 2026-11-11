"""Madden NFL 2005 (GameCube) TERF 'COMP' per-member codec table.

Layout (big-endian), located by scanning the TERF header area for b"COMP":
  'COMP', u32 table_bytes, u32 0, u32 0   (16-byte header; entry[0] = pad)
  entry[k+1] = (codec u32, decoded_size u32) for TERF member k
  final entry = ('DATA', total decoded data bytes)
codec 0 = stored (decoded_size == stored size); codec 5 = compressed
(bit-packed stream, decoder not yet identified).
"""
from __future__ import annotations
import re
import struct
from dataclasses import dataclass

COMP = b"COMP"
DATA_TAG = 0x44415441
CODEC_STORED = 0
CODEC_PACKED = 5


@dataclass(frozen=True)
class CompEntry:
    index: int
    codec: int
    decoded_size: int


def find_comp(buf, limit: int = 0x20000) -> int:
    hits = [m.start() for m in re.finditer(COMP, bytes(buf[:limit]))]
    if not hits:
        raise ValueError("no COMP table")
    return hits[-1]


def parse_comp(buf, member_sizes=None):
    """Return (entries, data_total). Validates against TERF member sizes if given."""
    off = find_comp(buf)
    tbytes = struct.unpack_from(">I", buf, off + 4)[0]
    n = tbytes // 8
    raw = [struct.unpack_from(">II", buf, off + 8 + 8 * k) for k in range(n)]
    if raw[-1][0] != DATA_TAG:
        raise ValueError("COMP table missing DATA terminator")
    body = raw[1:-1]
    entries = [CompEntry(i, c, s) for i, (c, s) in enumerate(body)]
    if member_sizes is not None:
        if len(entries) < len(member_sizes):
            raise ValueError("COMP shorter than member list")
        for e, sz in zip(entries, member_sizes):
            if e.codec == CODEC_STORED and sz and e.decoded_size != sz:
                raise ValueError(f"stored size mismatch member {e.index}")
            if e.codec != CODEC_STORED and e.decoded_size <= sz:
                raise ValueError(f"member {e.index} decoded<=stored")
    return entries, raw[-1][1]


# GCMP.LIB codec registry in main.dol: descriptor tag + version + 6 fn ptrs.
# Registration function at 0x804a0980 calls register(slot, desc) at 0x804a0b50.
CODEC_REGISTRY_VA = {0: 0x8053FB78, 1: 0x8053FB50, 2: 0x8053FB28,
                     3: 0x8053FBA0, 5: 0x8053FBC8}
CODEC_NAMES = {0: b"NONE", 1: b"RLE1", 2: b"HUFF", 3: b"LZM1", 5: b"LZH1"}
LZH1_FUNCS = (0x804A3B58, 0x804A3ED4, 0x804A3CB8, 0x804A3D24, 0x804A3ED4, 0x804A3E48)


def registry_from_dol(dol: bytes) -> dict:
    """Read codec tags straight from the DOL's registry descriptors."""
    from . import madden2005_terf as terf
    out = {}
    for slot, va in CODEC_REGISTRY_VA.items():
        o = terf.va_to_off(dol, va)
        out[slot] = bytes(dol[o:o + 4])
    return out
