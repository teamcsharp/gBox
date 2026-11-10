"""Magma (Splinter Cell: Double Agent, GameCube) UE2-style package reader.

Level .lin files inflate (see magma_lin) into a stream of "<path>\\0" strings each
followed by a big-endian package: tag 9E2A83C1, u16 ver, u16 lic, u32 flags,
u32 pad(1), then name/export/import counts+offsets.  Name entries are
u8 len, chars, NUL, u32 flags.
"""
import re
import struct
from dataclasses import dataclass
from typing import Iterator, List

TAG = bytes.fromhex("9e2a83c1")
_HDR = struct.Struct(">HHIIIIIIII")


@dataclass
class PkgHeader:
    offset: int
    path: str
    version: int
    licensee: int
    flags: int
    name_count: int
    name_offset: int
    export_count: int
    export_offset: int
    import_count: int
    import_offset: int


def parse_header(buf: bytes, at: int, path: str = "") -> PkgHeader:
    if buf[at:at + 4] != TAG:
        raise ValueError("bad package tag at %d" % at)
    ver, lic, fl, _pad, nc, no, ec, eo, ic, io = _HDR.unpack_from(buf, at + 4)
    return PkgHeader(at, path, ver, lic, fl, nc, no, ec, eo, ic, io)


def read_names(buf: bytes, hdr: PkgHeader) -> List[str]:
    o = hdr.offset + hdr.name_offset
    out = []
    for _ in range(hdr.name_count):
        n = buf[o]
        out.append(buf[o + 1:o + 1 + n].decode("latin1"))
        o += n + 6
    return out


def iter_packages(stream: bytes) -> Iterator[PkgHeader]:
    """Yield headers for every package in an inflated level .lin stream."""
    for m in re.finditer(re.escape(TAG), stream):
        at = m.start()
        if at + 40 > len(stream):
            continue
        hdr = parse_header(stream, at)
        if hdr.version != 127 or not (0 < hdr.name_count < 100000):
            continue
        j = at - 1
        if j >= 0 and stream[j] == 0:
            k = j
            while k > 0 and 32 <= stream[k - 1] < 127:
                k -= 1
            hdr.path = stream[k:j].decode("latin1")
        yield hdr
