"""Burnout Revenge (Xbox 360, title 454107DC) .bgv geometry parser.

A .bgv file is the per-car vehicle geometry. On the owned build the file on disc is
a zlib stream (magic 0x78 0xda observed on /pveh/high/us/Car1A.bgv) that decompresses
to a big-endian geometry blob. The blob is a vertex/index soup:

    +0   u32  format marker          0x00000025  (little-endian 0x25 as the low byte)
    +4   u32  vertex_count
    +8   vertex_count * 20 B         vertex array
             f32 x, y, z             position
             f32 nx, ny, nz         normal
    ...  u16 * index_count           index array (16-bit, big-endian)
    +end u32  index_count            trailing index count (so the writer need not
                                     precompute it; the parser verifies it matches)

Everything is big-endian (">") to match the rest of the Criterion disc data the
inventory module already reads (DNBW rig buffer, Gnsu geometry info, XEX2 header
are all big-endian). The parser is pure stdlib so it runs in CI without the
analysis stack.

read_bgv() accepts either the raw compressed .bgv bytes (it decompresses the zlib
stream) or an already-decompressed blob. parse_bgv() takes a decompressed blob and
returns a BGVGeometry. build_bgv() is a deterministic serializer used by the tests
to round-trip geometry without needing the owned 3.8 GB disc image on the test host.
"""

from __future__ import annotations

import struct
import zlib

FORMAT_MARKER = 0x00000025
_VERTEX_STRIDE = 24          # 6 * f32
_VERTEX_FMT = ">6f"          # x, y, z, nx, ny, nz  (position then normal)
HEADER_LEN = 8               # marker + vertex_count


class BGVError(ValueError):
    """Raised when a .bgv blob does not match the expected layout."""


class BGVGeometry:
    """Parsed .bgv geometry: parallel position/normal arrays and a 16-bit index list."""

    __slots__ = ("marker", "positions", "normals", "indices")

    def __init__(self, marker: int, positions: list[tuple[float, float, float]],
                 normals: list[tuple[float, float, float]], indices: list[int]):
        self.marker = marker
        self.positions = positions
        self.normals = normals
        self.indices = indices

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def index_count(self) -> int:
        return len(self.indices)

    def validate_index_range(self) -> None:
        """Index values must address existing vertices."""
        if not self.positions:
            return
        lo, hi = 0, len(self.positions) - 1
        for i in self.indices:
            if i < lo or i > hi:
                raise BGVError(f"index {i} out of range [0, {hi}]")


def parse_bgv(data: bytes) -> BGVGeometry:
    """Parse a decompressed .bgv blob into a BGVGeometry.

    Raises BGVError on a short/marker-mismatched/truncated blob and on index values
    that do not address existing vertices.
    """
    if len(data) < HEADER_LEN:
        raise BGVError(f"blob too short for header: {len(data)} < {HEADER_LEN}")
    marker, vertex_count = struct.unpack_from(">II", data, 0)
    if marker != FORMAT_MARKER:
        raise BGVError(f"unexpected format marker {marker:#010x} (expected {FORMAT_MARKER:#x})")

    need = HEADER_LEN + vertex_count * _VERTEX_STRIDE
    if len(data) < need:
        raise BGVError(f"blob too short for {vertex_count} vertices: "
                       f"{len(data)} < {need}")

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    off = HEADER_LEN
    for _ in range(vertex_count):
        x, y, z, nx, ny, nz = struct.unpack_from(_VERTEX_FMT, data, off)
        off += _VERTEX_STRIDE
        positions.append((x, y, z))
        normals.append((nx, ny, nz))

    # 16-bit index array; trailing u32 count must match what we read.
    rest = data[off:]
    if len(rest) < 4 or (len(rest) - 4) % 2:
        raise BGVError(f"index section malformed: {len(rest)} trailing bytes "
                       f"(need even index bytes + 4-byte count)")
    index_bytes = rest[:-4]
    declared, = struct.unpack_from(">I", rest, len(index_bytes))
    indices = list(struct.unpack(f">{len(index_bytes) // 2}H", index_bytes))
    if len(indices) != declared:
        raise BGVError(f"index count mismatch: declared {declared}, found {len(indices)}")

    geom = BGVGeometry(marker, positions, normals, indices)
    geom.validate_index_range()
    return geom


def read_bgv(blob: bytes) -> BGVGeometry:
    """Read a .bgv file: if it is a zlib stream, decompress first, then parse.

    Accepts both the raw on-disc compressed bytes (leading 0x78 0x9c/0xda/0x01) and
    an already-decompressed geometry blob.
    """
    if len(blob) >= 2 and blob[0] == 0x78 and blob[1] in (0x01, 0x9c, 0xda, 0x5e, 0x78):
        try:
            data = zlib.decompress(blob)
        except zlib.error as e:
            raise BGVError(f"invalid zlib stream: {e}") from e
    else:
        data = blob
    return parse_bgv(data)


def build_bgv(positions: list[tuple[float, float, float]],
              normals: list[tuple[float, float, float]],
              indices: list[int]) -> bytes:
    """Deterministically serialize geometry into a decompressed .bgv blob.

    The inverse of parse_bgv; used by tests to round-trip without the owned disc.
    """
    if len(positions) != len(normals):
        raise BGVError("positions and normals length mismatch")
    body = b"".join(struct.pack(_VERTEX_FMT, *xyz, *nrm)
                    for xyz, nrm in zip(positions, normals))
    idx = struct.pack(f">{len(indices)}H", *indices) if indices else b""
    return struct.pack(">II", FORMAT_MARKER, len(positions)) + body + idx + struct.pack(">I", len(indices))


def build_bgv_compressed(positions, normals, indices) -> bytes:
    """Serialize geometry and wrap it in a zlib stream, like the on-disc .bgv files."""
    return zlib.compress(build_bgv(positions, normals, indices), 9)
