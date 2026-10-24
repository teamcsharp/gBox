"""Turok: Evolution (GameCube, GTKE51) supertree0.tre index reader (partial).

Verified against the owned build (supertree0.tre @ disc 0x249388A0):
  * u32 BE count (0x2697 = 9879) at +0, one extra header word at +4.
  * Index = ``count`` 16-byte records from +8: [flags][crc][a][b], big endian.
    Records are sorted ascending by ``crc``.
  * ``crc`` = zlib.crc32 of the asset path *without* the leading ``y:\\``
    (case preserved), e.g. ``data\\actors\\players\\talset\\talset.mtf``.
  * Right after the index sits a plaintext script block of ``*PR = "<path>"``
    lines (1488 in the first 32 MiB); every one resolves to an index record.
UNRESOLVED: meaning of ``a``/``b`` (not plain offset/size; a is ~uniform 32-bit),
so this module cannot extract payloads yet.
"""
from __future__ import annotations

import re
import struct
import zlib
from typing import Dict, List, NamedTuple

REC = struct.Struct(">4I")
_PR = re.compile(rb'\*PR = "([^"]*)"')


class TreRecord(NamedTuple):
    flags: int
    crc: int
    a: int
    b: int


def path_crc(path: str | bytes) -> int:
    """CRC32 key of an asset path as stored in the index (drops ``y:\\``)."""
    if isinstance(path, str):
        path = path.encode("latin-1")
    if path[1:3] == b":\\":
        path = path[3:]
    return zlib.crc32(path) & 0xFFFFFFFF


def parse_index(buf: bytes) -> List[TreRecord]:
    count = struct.unpack_from(">I", buf, 0)[0]
    if count * 16 + 8 > len(buf):
        raise ValueError("buffer shorter than index")
    return [TreRecord(*REC.unpack_from(buf, 8 + 16 * i)) for i in range(count)]


def index_is_sorted(recs: List[TreRecord]) -> bool:
    return all(x.crc <= y.crc for x, y in zip(recs, recs[1:]))


def pr_paths(buf: bytes) -> List[str]:
    return [m.group(1).decode("latin-1") for m in _PR.finditer(buf)]


def resolve_pr_paths(buf: bytes) -> Dict[str, TreRecord]:
    """Map every plaintext ``*PR`` path to its index record (KeyError-free)."""
    by_crc = {r.crc: r for r in parse_index(buf)}
    return {p: by_crc[path_crc(p)] for p in pr_paths(buf) if path_crc(p) in by_crc}
