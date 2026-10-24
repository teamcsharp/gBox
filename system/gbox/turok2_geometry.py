"""Turok 2 (N64, Europe NT2P) native geometry reader.

Scope
-----
Decodes the *Geometry* block of a tengine GraphicObject from the owned
"Turok 2 - Seeds of Evil (Europe)" ROM (NT2P, 32 MiB, z64) into the
structures observed on the real file:

    GraphicObject = CIndexedSet { ObjectInfo, Geometry(RNC), Anims, StaticEvents }
    Geometry (decompressed) = CIndexedSet of 3 blocks (static) or 6 blocks (skinned)

        [0] node parts     CIndexedSet { per-node CUnindexedSet{ u32 stride, u32 count, data } }
        [1] texture header 8 bytes
        [2] display lists  CIndexedSet of index sets
        [3] skin/morph     CIndexedSet of 152-byte index sets  (6-block variant only)
        [4] morph tables   CIndexedSet of 20-byte records      (6-block variant only)
        [5] small tables   CIndexedSet of 8-byte records       (6-block variant only)

Verified against the owned ROM: block counts, CIndexedSet nesting, vertex
record stride/count, and the 8-byte texture header size.

HYPOTHESIS (not yet proven against the engine's own loader): the 16-byte
vertex record is laid out as

    s16 x, s16 y, s16 z, u16 flags, s16 u, s16 v, u16 pad

The structural facts above are measured; the field meanings are not.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

from gbox import turok_inventory as ti
from gbox import turok2_inventory as t2

OBJECT_PART_NAMES = ("object_info", "geometry", "anims", "static_events")
VERTEX_STRIDE = 16
RNC_MAGIC = b"RNC"


class Turok2FormatError(ValueError):
    """Raised when the owned bytes do not match the expected tengine layout."""


@dataclass
class VertexPart:
    """One node's vertex array: a planar CUnindexedSet payload."""

    stride: int
    count: int
    data: bytes

    def _field(self, k: int, off: int, fmt: str) -> int:
        return struct.unpack_from(fmt, self.data, k * self.stride + off)[0]

    @property
    def positions(self) -> List[Tuple[int, int, int]]:
        return [(self._field(k, 0, ">h"), self._field(k, 2, ">h"), self._field(k, 4, ">h"))
                for k in range(self.count)]

    @property
    def flags(self) -> List[int]:
        return [self._field(k, 6, ">H") for k in range(self.count)]

    @property
    def uvs(self) -> List[Tuple[int, int]]:
        return [(self._field(k, 8, ">h"), self._field(k, 10, ">h")) for k in range(self.count)]

    def bbox(self) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
        pts = self.positions
        if not pts:
            raise Turok2FormatError("empty vertex part")
        lo = tuple(min(p[i] for p in pts) for i in range(3))
        hi = tuple(max(p[i] for p in pts) for i in range(3))
        return lo, hi


@dataclass
class Geometry:
    """Decompressed Geometry block plus its CIndexedSet sub-block table."""

    raw: bytes
    blocks: List[Tuple[int, int]]

    def block(self, i: int) -> bytes:
        rel, size = self.blocks[i]
        return self.raw[rel:rel + size]

    @property
    def is_skinned(self) -> bool:
        return len(self.blocks) == 6


def parse_vertex_part(blob: bytes) -> VertexPart:
    """Decode one CUnindexedSet vertex array (header: u32 stride, u32 count)."""
    if len(blob) < 8:
        raise Turok2FormatError("vertex part too small")
    stride, count = struct.unpack_from(">II", blob, 0)
    if stride < 4 or count < 0 or 8 + stride * count > len(blob):
        raise Turok2FormatError("vertex part overruns its block")
    return VertexPart(stride=stride, count=count, data=blob[8:8 + stride * count])


def _candidate_roots(rom: bytes) -> List[int]:
    cands: List[int] = []
    finder = getattr(t2, "find_cart_root", None)
    if finder is not None:
        found = finder(rom)
        if found:
            cands.append(int(found))
    const = getattr(t2, "CART_ROOT_OFFSET", None)
    if const and int(const) not in cands:
        cands.append(int(const))
    return cands


class Cart:
    """Parsed tengine cart for the owned Turok 2 (Europe) ROM."""

    def __init__(self, rom: bytes):
        self.rom = rom
        last: Exception | None = None
        for root in _candidate_roots(rom):
            try:
                rset = ti.parse_indexed(rom, root)
                go_base = root + rset[0][0]
                go = ti.parse_indexed(rom, go_base)
                if not go:
                    raise Turok2FormatError("no graphic objects")
                probe = ti.parse_indexed(rom, go_base + go[0][0])
                if len(probe) != len(OBJECT_PART_NAMES):
                    raise Turok2FormatError("graphic object is not a 4-part set")
                self.root = root
                self.go_base = go_base
                self.go = go
                return
            except Exception as exc:  # try the next candidate
                last = exc
        raise Turok2FormatError(f"no usable cart root ({last})")

    @property
    def object_count(self) -> int:
        return len(self.go)

    def parts(self, index: int) -> Dict[str, bytes]:
        rel, _size = self.go[index]
        base = self.go_base + rel
        ob = ti.parse_indexed(self.rom, base)
        if len(ob) != len(OBJECT_PART_NAMES):
            raise Turok2FormatError("unexpected graphic object part count")
        out: Dict[str, bytes] = {}
        for name, (r, s) in zip(OBJECT_PART_NAMES, ob):
            out[name] = self.rom[base + r:base + r + s]
        return out

    def geometry(self, index: int) -> Geometry:
        blob = self.parts(index)["geometry"]
        for cand in _decode_candidates(blob):
            try:
                blocks = ti.parse_indexed(cand, 0)
            except Exception:
                continue
            if blocks and len(blocks) in (3, 6) and all(0 < s <= len(cand) for _r, s in blocks):
                return Geometry(raw=cand, blocks=blocks)
        raise Turok2FormatError("geometry block has no 3/6-block CIndexedSet shape")

    def node_parts(self, index: int) -> List[VertexPart]:
        geom = self.geometry(index)
        parts = ti.parse_indexed(geom.block(0), 0)
        return [parse_vertex_part(geom.block(0)[r:r + s]) for r, s in parts]

    def texture_header(self, index: int) -> bytes:
        return self.geometry(index).block(1)


def _decode_candidates(blob: bytes) -> List[bytes]:
    cands: List[bytes] = []
    if blob[:3] == RNC_MAGIC:
        try:
            cands.append(ti.decode_rnc(blob))
        except Exception:
            pass
    cands.append(blob)
    return cands
