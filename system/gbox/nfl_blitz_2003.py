"""NFL Blitz 2003 (USA) GameCube container readers.

Owned source: ``NFL Blitz 2003 (USA).gcz`` (HyperSpin), sha256
``040ae15fe656155e6c92f439998cc987715f6b6161bc7884c7ee126ba76bb439``.
Disc FST: 23 entries; 7 ZIP payload containers (players/shell/stadium/anim/
misc/sound/teamdata) with ``.ziH`` sidecar header tables, 7 AVI cutscenes,
``opening.bnr``.  Engine family: Midway (assimilate fingerprint 0.49).

``.ziH`` layout (verified empirically on players.ziH, 296 members, from the
owned GCZ read-only):

* 8-byte header: ``u32 LE`` entry count (``count``) + ``u32 LE`` blob size.
* ``count`` entries of 24 bytes = 6 x ``u32 BE`` starting at offset 8.
  Entry field meanings are *not* fully resolved yet: f0/f3 index the
  trailing NUL-separated filename table (some rows store the name offset
  pre-decremented by a length-dependent amount and therefore underflow the
  table start), f1/f4 look like RAM image sizes and f2/f5 are engine RAM
  addresses (0 matches against ZIP local-header offsets), with a duplicate
  low/hi variant row pair per logical asset.
* Trailing NUL-separated filename table (starts right after the entry
  array region; every distinct member name occurs exactly once).

The ZIP containers use **store** (method 0) with a *corrupted* local file
header signature byte sequence at each central-directory ``header_offset``
(python :mod:`zipfile` raises ``BadZipFile: Bad magic number for file
header``), so member data must be located by scanning for the real
``PK\\x03\\x04`` local headers, which sit at regular positions and parse
cleanly.  All 296 players members verify against their stored CRC-32 with
this reader.

This module is an *inventory* reader: it enumerates containers and extracts
members with CRC verification.  It is **not** a ``.dff``/``.gtd`` model
reader; do not claim character replacement readiness from it.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

LOCAL_HEADER = b"PK\x03\x04"

#: sha256 of the owned GCZ (streamed, read-only) - identity anchor.
GCZ_SHA256 = "040ae15fe656155e6c92f439998cc987715f6b6161bc7884c7ee126ba76bb439"
#: sha256 of main.dol extracted from that GCZ.
MAIN_DOL_SHA256 = "ee3ae63083eee6a7a0141b0aeeb16ce8b1e13b31302e18a8a058928163364d8c"


@dataclass
class ZiHEntry:
    """One 24-byte .ziH table row (6 x u32 BE), raw fields."""

    f0: int
    f1: int
    f2: int
    f3: int
    f4: int
    f5: int


@dataclass
class ZiHTable:
    count: int
    blob: int
    entries: list[ZiHEntry] = field(default_factory=list)
    names: list[str] = field(default_factory=list)

    @property
    def entry_bytes(self) -> int:
        return 8 + 24 * self.count


def parse_zih(blob: bytes) -> ZiHTable:
    """Parse a ``.ziH`` sidecar table.

    Raises ``ValueError`` if the blob is too small or the declared entry
    count does not fit the file (entries must end within the blob).
    """
    if len(blob) < 12:
        raise ValueError("ziH blob too small")
    count, blob_sz = struct.unpack_from("<II", blob, 0)
    if count == 0 or count > 100_000:
        raise ValueError(f"implausible ziH count {count}")
    if 8 + 24 * count > len(blob):
        raise ValueError(
            f"ziH entry array overruns blob: count={count} "
            f"need>={8 + 24 * count} have={len(blob)}"
        )
    entries = [
        ZiHEntry(*struct.unpack_from(">6I", blob, 8 + 24 * k))
        for k in range(count)
    ]
    tail = blob[8 + 24 * count:]
    # Names live in a trailing NUL-separated table that may overlap the last
    # entries; scan the whole blob for NUL-separated ASCII asset names.
    names: list[str] = []
    for chunk in blob.split(b"\x00"):
        try:
            s = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        if 2 < len(s) <= 64 and "." in s and all(32 <= ord(c) < 127 for c in s):
            names.append(s)
    return ZiHTable(count=count, blob=blob_sz, entries=entries, names=names)


@dataclass
class ZipMember:
    name: str
    crc32: int
    compress_size: int
    file_size: int
    data_offset: int
    method: int


def scan_zip(blob: bytes) -> list[ZipMember]:
    """Enumerate members by scanning local file headers.

    The players/shell/... containers have corrupted local-header positions
    relative to the central directory, but the real ``PK\\x03\\x04``
    headers are present and regular; scanning them is authoritative for
    data offsets.
    """
    members: list[ZipMember] = []
    pos = 0
    while True:
        s = blob.find(LOCAL_HEADER, pos)
        if s < 0:
            break
        try:
            (method,) = struct.unpack_from("<H", blob, s + 8)
            crc, csz, usz, fnl, expl = struct.unpack_from("<IIIHH", blob, s + 14)
        except struct.error:
            break
        name = blob[s + 30 : s + 30 + fnl].decode("latin1")
        data_off = s + 30 + fnl + expl
        if data_off + csz > len(blob):
            pos = s + 4
            continue
        members.append(
            ZipMember(name, crc, csz, usz, data_off, method)
        )
        pos = data_off if data_off > s else s + 4
    return members


def extract_member(blob: bytes, member: ZipMember) -> bytes:
    """Return decompressed member bytes, verifying CRC-32 and size."""
    raw = blob[member.data_offset : member.data_offset + member.compress_size]
    if member.method == 0:
        data = raw
    elif member.method == 8:
        data = zlib.decompress(raw, -15)
    else:
        raise ValueError(f"unsupported zip method {member.method}")
    if len(data) != member.file_size:
        raise ValueError(
            f"{member.name}: size {len(data)} != declared {member.file_size}"
        )
    if zlib.crc32(data) & 0xFFFFFFFF != member.crc32:
        raise ValueError(f"{member.name}: CRC mismatch")
    return data


def load_container(zip_blob: bytes, zih_blob: bytes) -> tuple[ZiHTable, list[ZipMember]]:
    """Parse a (zip, ziH) pair and cross-check member counts."""
    table = parse_zih(zih_blob)
    members = scan_zip(zip_blob)
    if len(members) != table.count:
        raise ValueError(
            f"ziH count {table.count} != zip members {len(members)}"
        )
    return table, members
