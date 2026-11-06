"""MT Framework model files (`MRL\\0`), the container a Switch RE title reads for a mesh.

Stage 1 (this module today): parse the header and the resource-path table and re-emit them byte-for-byte, so the writer
owns those fields instead of copying bytes. The geometry that follows the table is carried opaque until its layout is
decoded; nothing here invents a field it does not understand.

Measured layout (all values little-endian, verified against nine models in uPl00ChrisNormal.arc and uWp06.arc):

    0x00  "MRL\\0"
    0x04  u32 version            34 in every model seen
    0x08  u32 count1             unknown meaning, varies per model (6, 9, 12, 60, 65, 123, 131 ...)
    0x0c  u32 path_count         EQUALS the number of 88-byte path records that follow - 9 of 9 models matched
    0x10  u32 hash               varies (0x7be0e51f on evf0000)
    0x14  u32 0
    0x18  u32 40                 the offset of the table below
    0x1c  u32 0
    0x20  u32 offset             a second offset (0x6b0 on evf0000); meaning not yet decoded
    0x24  u32 0
    0x28  u32 0x241f5deb         the same constant .arc entry records carry
    0x2c  .. 0x3f zeros
    0x40  path_count * 88 bytes, each a NUL-terminated ASCII path padded with 0xcd fill, e.g.
          "pawn\\pl\\pl00\\model\\evf0000_01_NM"
    then the geometry stream, opaque here.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"MRL\x00"
VERSION = 34
CONST_OFFSET = 0x28          # the header field at 0x18 points here (40); the 0x241f5deb constant lives at it
HEADER_SIZE = 0x40           # the path table starts here: CONST_OFFSET + 24 (the constant and five zero words)
PATH_RECORD = 0x58           # 88 bytes per resource path: path[64] + u32 + 20 zero bytes
PATH_FIELD = 0x40            # the path occupies the first 64 bytes (NUL-terminated, 0xcd filled)
PATH_TAIL = 24               # what follows: the 0x241f5deb constant and twenty zero bytes, kept verbatim
TABLE_OFFSET = 0x18          # the header field holding CONST_OFFSET
ARC_CONST = 0x241F5DEB


class ModelError(ValueError):
    """A payload that is not an MRL model, or one whose header does not describe its own bytes."""


@dataclass
class ModelFile:
    version: int
    count1: int
    words: list[int]                     # the six u32 at 0x10..0x27, kept verbatim
    const: int                           # the u32 at 0x28 (ARC_CONST in every model seen)
    zeros: bytes                         # 0x2c..0x3f, kept verbatim
    paths: list[str] = field(default_factory=list)
    path_tails: list[bytes] = field(default_factory=list)   # per record: the constant and its zero padding
    tail: bytes = b""                    # the geometry stream, opaque

    def __len__(self) -> int:
        return HEADER_SIZE + PATH_RECORD * len(self.paths) + len(self.tail)


def parse(data: bytes, *, strict: bool = True) -> ModelFile:
    """Read an MRL model's header and path table. `strict` also checks the offsets against the payload length."""
    data = bytes(data)
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise ModelError(f"not an MRL model (magic {data[:4]!r})")
    version, count1, path_count = struct.unpack_from("<III", data, 4)
    if version != VERSION:
        raise ModelError(f"unsupported MRL version {version} (expected {VERSION})")
    words = list(struct.unpack_from("<6I", data, 0x10))
    const = struct.unpack_from("<I", data, CONST_OFFSET)[0]
    zeros = data[0x2C:HEADER_SIZE]
    # the header says where the constant block is; the path table begins 24 bytes after it. Deriving it from the file
    # rather than assuming 0x40 is what caught this: 40 means 0x28, not the table's own offset.
    if strict and words[2] != CONST_OFFSET:
        raise ModelError(f"constant-block offset field is {words[2]}, not {CONST_OFFSET}")
    table = (words[2] if words[2] else CONST_OFFSET) + 0x18
    end = table + path_count * PATH_RECORD
    if path_count > 4096 or end > len(data):
        raise ModelError(f"path table of {path_count} records runs past the payload ({len(data)} bytes)")
    paths = []
    tails = []
    for i in range(path_count):
        record = data[table + i * PATH_RECORD:table + (i + 1) * PATH_RECORD]
        path = record[:PATH_FIELD].split(b"\x00", 1)[0]
        if not path or any(b < 0x20 or b > 0x7E for b in path):
            raise ModelError(f"path record {i} is not printable ASCII")
        paths.append(path.decode("ascii"))
        tails.append(record[PATH_FIELD:])
    return ModelFile(version=version, count1=count1, words=words, const=const, zeros=zeros,
                     paths=paths, path_tails=tails, tail=data[end:])


def build(model: ModelFile) -> bytes:
    """Re-emit the model. The header and the path table are written from the parsed fields; the geometry is the
    payload that was carried, byte for byte."""
    if model.version != VERSION:
        raise ModelError(f"unsupported MRL version {model.version}")
    if len(model.zeros) != HEADER_SIZE - 0x2C:
        raise ModelError("header padding must be 0x2c..0x40")
    if len(model.words) != 6:
        raise ModelError("the header words are six u32")
    out = bytearray(MAGIC)
    out += struct.pack("<III", model.version, model.count1, len(model.paths))
    out += struct.pack("<6I", *model.words)
    out += struct.pack("<I", model.const)
    out += model.zeros
    for index, path in enumerate(model.paths):
        raw = path.encode("ascii")
        if len(raw) >= PATH_FIELD:
            raise ModelError(f"path {path!r} does not fit in {PATH_FIELD} bytes")
        tail = model.path_tails[index] if index < len(model.path_tails) else \
            struct.pack("<I", ARC_CONST) + b"\x00" * (PATH_TAIL - 4)
        if len(tail) != PATH_TAIL:
            raise ModelError("a path record's tail must be its 24 trailing bytes")
        out += raw + b"\x00" + b"\xcd" * (PATH_FIELD - len(raw) - 1) + tail
    out += model.tail
    return bytes(out)


# --- the geometry container (`MOD\0`) ---------------------------------------------------------------------------------
#
# Measured on nine models across five archives (2026-11-06):
#
#     0x00  "MOD\0"
#     0x04  u32            (0x0300d3 / 0x0200d3 / 0xd3 seen)
#     0x08  u32            (0x09000f / 0x020004 / 0x0b000b ...)
#     0x0c  u32 vertex_count        of the first submesh
#     0x10  u32            (2317, 530, 2335 ... no meaning yet)
#     0x14  u32            (1415, 390, 1143 ...)
#     0x18  u32 geometry_bytes      the size of block 4 (25764, 6592, 27336 ... - checked against the offsets)
#     0x1c  u32 0
#     0x20  u32 submesh_count       (2, 1, 1, 11, 9, 20 ...)
#     0x28  7 x u64 block offsets, rising, the last one 4 bytes short of the payload
#     then 6 blocks
#
# For a single-submesh model geometry_bytes / vertex_count is an EXACT integer stride: 16, 20, 24 and 28 were all seen
# (4 of 7 single-submesh models; the other three are the ones whose counts do not divide, so a per-submesh table must
# hold the split). A multi-submesh model (pl0000: 6 submeshes, 28091 vertices, 758592 bytes = 27.005 bytes/vertex) only
# makes sense as a sum over submeshes, which is the part still to decode.
MOD_MAGIC = b"MOD\x00"
MOD_BLOCK_OFFSETS = 0x28
MOD_BLOCKS = 7                       # seven offsets, so six blocks


@dataclass
class ModFile:
    """A parsed `MOD` geometry container.

    `raw` is kept whole: the header is 0x60 bytes, then a gap of unknown meaning up to the first block offset (164 in
    the object models), then the blocks. Re-emitting an unchanged model is therefore exact; describing what lies in the
    gap (most likely the per-submesh table) is what writing new geometry still needs.
    """
    words: list[int]                    # the eight u32 at 0x04..0x23
    offsets: list[int]                  # the seven block offsets at 0x28
    raw: bytes
    variant: str = "model"              # "model" (header 0x60, first block at 164) or "effect" (table starts at 0)

    @property
    def vertex_count(self) -> int:
        return self.words[2]

    @property
    def geometry_bytes(self) -> int:
        return self.words[5]

    @property
    def submeshes(self) -> int:
        return self.words[7]

    @property
    def header_size(self) -> int:
        return MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS

    def block(self, index: int) -> bytes:
        """Block `index` (0..5) of the geometry."""
        start, end = self.offsets[index], self.offsets[index + 1]
        return self.raw[start:end]

    def stride(self) -> float | None:
        """Bytes per vertex: exact for single-submesh models, where geometry_bytes == vertex_count * stride."""
        if not self.vertex_count:
            return None
        return self.geometry_bytes / self.vertex_count

    def layout(self) -> dict:
        """What the container's parts are, as far as they are decoded.

        Measured 2026-11-06 over 16 models in four archives:

        * **block 5 is the index buffer**: two bytes per index, and header word 0x10 is the index count
          (`len(block5) == 2 * index_count`, exact on 16/16, sometimes one or two indices of padding);
        * **block 4 is the vertex buffer**: for a single-submesh model `vertex_count * stride` equals its length with a
          stride of 16, 20, 24, 28 or 32 (an occasional 4-24 byte tail of padding makes the division inexact);
        * **block 3 is a table of 200-byte records** (a per-mesh/submesh descriptor: 200 x N records, N = 2, 11, 9, 20 ...
          which is the submesh count in most models), and **block 2 is a table of 128-byte records** beside it;
        * blocks 0 and 1 are small tables that scale with the model.

        The per-submesh vertex counts and strides are NOT in the header; they are what the records above must carry, and
        decoding them is what writing new geometry still needs.
        """
        block = [self.block(i) for i in range(6)]
        vertex, index = self.vertex_count, self.words[3]
        stride = self.stride()
        return {
            "vertex_count": vertex,
            "index_count": index,
            "submeshes": self.submeshes,
            "stride": stride,
            "stride_exact": bool(stride and abs(stride - round(stride)) < 1e-9),
            "vertex_block": len(block[4]),
            "index_block": len(block[5]),
            "index_block_matches": len(block[5]) in (2 * index, 2 * (index + 1), 2 * (index + 2)),
            "blocks": [len(b) for b in block],
            "records_200": len(block[3]) / 200,
            "records_128": len(block[2]) / 128,
            "variant": self.variant,
        }


def parse_mod(data: bytes, *, strict: bool = True) -> ModFile:
    """Read a `MOD` geometry container's header and block table. The blocks are carried, not interpreted."""
    data = bytes(data)
    if len(data) < MOD_BLOCK_OFFSETS + 8 * MOD_BLOCKS or data[:4] != MOD_MAGIC:
        raise ModelError(f"not a MOD container (magic {data[:4]!r})")
    words = list(struct.unpack_from("<8I", data, 0x04))
    offsets = [struct.unpack_from("<I", data, MOD_BLOCK_OFFSETS + 8 * i)[0] for i in range(MOD_BLOCKS)]
    if strict:
        if any(b < a for a, b in zip(offsets, offsets[1:])):
            raise ModelError(f"block offsets are not rising: {offsets}")
        if offsets[-1] > len(data):
            raise ModelError(f"the last block offset runs past the payload: {offsets}")
    return ModFile(words=words, offsets=offsets, raw=data, variant="effect" if offsets[0] < MOD_BLOCK_OFFSETS + 8
                   * MOD_BLOCKS else "model")


def build_mod(model: ModFile) -> bytes:
    """Re-emit the container. Unchanged, this is byte-identical to what was parsed."""
    if len(model.offsets) != MOD_BLOCKS:
        raise ModelError(f"a MOD has {MOD_BLOCKS} block offsets")
    return model.raw


def roundtrip_mod(data: bytes) -> bytes:
    return build_mod(parse_mod(data))


def roundtrip(data: bytes) -> bytes:
    """parse then build: the bytes a writer produces for an unchanged model."""
    return build(parse(data))
