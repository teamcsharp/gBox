"""NFL Blitz 2003 (GC) same-size member replacement in the store-method ZIP containers.

Writer step for the owned build (GCZ sha256 040ae15f...bb439, players.zip
off=468586952 size=41559965 in the disc FST).  A member's bytes are replaced
in place; sizes and offsets never change, so the disc FST, the .ziH sidecar
and every other member stay byte-identical.  The CRC-32 is rewritten in the
local header (``PK\\x03\\x04`` at +14) and in the matching central-directory
record (``PK\\x01\\x02`` at +16).

The disc image itself is never modified: callers get a new players.zip blob.
"""
from __future__ import annotations

import struct
import zlib

from .nfl_blitz_2003 import ZipMember, scan_zip

CENTRAL = b"PK\x01\x02"


def central_records(blob: bytes) -> dict[str, int]:
    """name -> offset of the central-directory record."""
    out: dict[str, int] = {}
    pos = 0
    while True:
        s = blob.find(CENTRAL, pos)
        if s < 0:
            break
        fnl, exl, cml = struct.unpack_from("<HHH", blob, s + 28)
        name = blob[s + 46 : s + 46 + fnl].decode("latin1")
        out[name] = s
        pos = s + 46 + fnl + exl + cml
    return out


def find_member(blob: bytes, name: str) -> ZipMember:
    for m in scan_zip(blob):
        if m.name == name:
            return m
    raise KeyError(name)


def replace_member(blob: bytes, name: str, new_data: bytes) -> bytes:
    """Return a copy of ``blob`` with member ``name`` replaced by ``new_data``.

    Only same-size store-method replacement is supported.
    """
    m = find_member(blob, name)
    if m.method != 0:
        raise ValueError(f"{name}: method {m.method} not supported")
    if len(new_data) != m.file_size:
        raise ValueError(
            f"{name}: size {len(new_data)} != {m.file_size} (same-size only)")
    crc = zlib.crc32(new_data) & 0xFFFFFFFF
    cd = central_records(blob).get(name)
    if cd is None:
        raise KeyError(f"{name}: no central-directory record")
    out = bytearray(blob)
    out[m.data_offset : m.data_offset + m.file_size] = new_data
    # local header: data_offset = s + 30 + fnl + expl; locate s by name length
    lh = blob.rfind(b"PK\x03\x04", 0, m.data_offset)
    struct.pack_into("<I", out, lh + 14, crc)
    struct.pack_into("<I", out, cd + 16, crc)
    return bytes(out)
