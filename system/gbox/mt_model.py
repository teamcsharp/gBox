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


def roundtrip(data: bytes) -> bytes:
    """parse then build: the bytes a writer produces for an unchanged model."""
    return build(parse(data))
