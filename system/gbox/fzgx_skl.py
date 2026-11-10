"""F-Zero GX .skl skeleton parser (motion/*.skl), big-endian.

Layout verified on the owned disc (every motion/*.skl parses to exactly EOF):
  0x00 u16 bone_count, u16 pad(0)
  then bone_count records, each:
      i16 parent_or_link, u16 flags   (first record: -1, 0x40)
      11 x f32                        (transform data; semantics not yet decoded)
      name: NUL-terminated ASCII padded to a multiple of 4 bytes (min 1 NUL)
Field meaning of the first u16 pair and the 11 floats is a hypothesis: they are
exposed raw and must not be treated as a decoded bind pose.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from gbox.fzgx_gma import FzgxFormatError


@dataclass
class SklBone:
    name: str
    link: int
    flags: int
    values: tuple[float, ...]


def parse_skl(blob: bytes) -> list[SklBone]:
    if len(blob) < 4:
        if len(blob) == 0:
            return []  # octman_handr.skl is a zero-byte placeholder on disc
        raise FzgxFormatError("SKL too short")
    if blob[:4] == b"\0\0\0\0" and len(blob) == 4:
        return []  # *_lip.skl: header-only, zero bones
    count, pad = struct.unpack_from(">HH", blob, 0)
    if pad != 0 or not 0 < count <= 256:
        raise FzgxFormatError(f"bad SKL header count={count} pad={pad}")
    pos, bones = 4, []
    for i in range(count):
        if pos + 48 + 4 > len(blob):
            raise FzgxFormatError(f"SKL bone {i} truncated")
        link, flags = struct.unpack_from(">hH", blob, pos)
        vals = struct.unpack_from(">11f", blob, pos + 4)
        pos += 48
        end = blob.find(b"\0", pos)
        if end < 0:
            raise FzgxFormatError(f"SKL bone {i} name unterminated")
        raw = blob[pos:end]
        if not raw or not all(32 < c < 127 for c in raw):
            raise FzgxFormatError(f"SKL bone {i} bad name {raw!r}")
        pos += (len(raw) + 1 + 3) & ~3
        bones.append(SklBone(raw.decode("ascii"), link, flags, vals))
    if pos != len(blob):
        raise FzgxFormatError(f"SKL trailing bytes: parsed {pos} of {len(blob)}")
    return bones
