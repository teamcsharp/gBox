"""Splinter Cell: Double Agent (GameCube) ``*.lin`` container reader.

Verified on the owned build (common.lin, sha256 f142b355...2c37): the file is a
sequence of chunks ``u32be compressed_size`` + zlib stream (<=32768 bytes
inflated), consumed exactly to EOF.  ``common.lin`` inflates to a virtual-file
TOC: 22-byte header, then records ``u8 len`` + name(len bytes incl. NUL) +
``u32be offset`` + ``u32be size`` + ``u32be 0``.  Offsets are in a virtual
space (8-byte aligned) holding the Unreal Engine 2.x-style ``.ugx`` script
packages and ``DataGCN\\Maps\\*.unr`` maps.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Iterator, List

TOC_HEADER = 22


@dataclass(frozen=True)
class TocEntry:
    name: str
    offset: int
    size: int


def iter_chunks(data: bytes) -> Iterator[bytes]:
    """Yield inflated chunks; raise ValueError if the stream is not exact."""
    o = 0
    while o < len(data):
        if o + 4 > len(data):
            raise ValueError("truncated chunk header at %d" % o)
        c = struct.unpack(">I", data[o:o + 4])[0]
        if c == 0 or o + 4 + c > len(data):
            raise ValueError("bad chunk size %d at %d" % (c, o))
        yield zlib.decompress(data[o + 4:o + 4 + c])
        o += 4 + c


def inflate(data: bytes) -> bytes:
    return b"".join(iter_chunks(data))


def parse_toc(inflated: bytes) -> List[TocEntry]:
    """Parse TOC records until the first malformed one (the tail of
    common.lin holds non-TOC data such as ini text)."""
    o, out = TOC_HEADER, []
    while o < len(inflated):
        n = inflated[o]
        if n < 2 or o + 1 + n + 12 > len(inflated):
            break
        raw = inflated[o + 1:o + 1 + n]
        if raw[-1:] != b"\0" or not all(32 <= b < 127 for b in raw[:-1]):
            break
        off, size, z = struct.unpack(">III", inflated[o + 1 + n:o + 1 + n + 12])
        if z != 0:
            break
        out.append(TocEntry(raw[:-1].decode("ascii"), off, size))
        o += 1 + n + 12
    return out


def parse_lin(data: bytes) -> List[TocEntry]:
    return parse_toc(inflate(data))


def package_names(entries: List[TocEntry]) -> List[str]:
    return [e.name for e in entries if e.name.lower().endswith((".ugx", ".unr"))]
