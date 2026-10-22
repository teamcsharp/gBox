"""Native reader for NBA Street V3 (USA) (GameCube) - EA EAGL BIG/VIV containers and SHPG character assets.

Verified against the owned build (game_id c7c407414dfd06b4) by streaming the ROM bytes:

* Container: 16-byte header - 'BIGF' or 'BIG4' magic, u32-LE total size, u32-BE member count,
  u32-BE data start.  The table of contents is a run of records, each
  ``[u32-BE offset][u32-BE size][NUL-terminated name]``, where offset/size are relative to the
  archive start.  Both 'BIGF' (.viv/.big) and 'BIG4' use the identical layout.
* Character assets: every ``fe/players.viv`` member is an EA RefPack (QFS) stream that inflates to
  an 'SHPG' payload.  The 4 bytes at 0x10 of the payload are the member's short tag (the first four
  characters of the member file name, e.g. 'warr' for ``warriorsDUNLEAVY_lrg.gsh``).

The SHPG geometry layout past the header is not yet reverse engineered; this module only owns the
container walk, the RefPack inflate and the tagged-header parse.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Iterable

from . import refpack

MAGICS = (b"BIGF", b"BIG4")
HEADER_SIZE = 16
SHPG_MAGIC = b"SHPG"
SHPG_TAG_OFFSET = 0x10
SHPG_TAG_SIZE = 4

#: character slots in fe/players.viv - '<team><PLAYER>_lrg.gsh' (177 entries in the owned build).
PLAYER_RE = r"^[a-z]+[A-Z]+_lrg\.gsh$"


@dataclass(frozen=True)
class Member:
    """One archive member.  ``offset``/``size`` are relative to the archive start."""
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class BigHeader:
    magic: bytes
    total_size: int
    count: int
    data_start: int


def parse_header(head: bytes) -> BigHeader:
    if len(head) < HEADER_SIZE:
        raise ValueError("BIG header truncated")
    magic = bytes(head[0:4])
    if magic not in MAGICS:
        raise ValueError(f"not an EA BIG container: {magic!r}")
    total_size, = struct.unpack_from("<I", head, 4)
    count, = struct.unpack_from(">I", head, 8)
    data_start, = struct.unpack_from(">I", head, 12)
    return BigHeader(magic, total_size, count, data_start)


def _parse_records(buf: bytes, count: int) -> tuple[list[Member], bool]:
    """Parse up to ``count`` TOC records out of ``buf``.  Returns (members, complete)."""
    out: list[Member] = []
    pos = 0
    for _ in range(count):
        if pos + 8 > len(buf):
            return out, False
        off, size = struct.unpack_from(">II", buf, pos)
        end = buf.find(b"\0", pos + 8)
        if end < 0:
            return out, False
        name = buf[pos + 8:end].decode("latin-1")
        out.append(Member(name, off, size))
        pos = end + 1
    return out, True


class BigArchive:
    """An EA BIGF/BIG4 container read through a ``read(offset, size)`` callable.

    The callable receives offsets relative to the archive start, so a BIG container embedded in a
    GameCube disc can be opened with ``BigArchive(lambda o, n: disc._r(base + o, n))``.
    """

    def __init__(self, read: Callable[[int, int], bytes]):
        self._read = read
        self.header = parse_header(read(0, HEADER_SIZE))
        self.members: list[Member] = []
        self._by_name: dict[str, Member] = {}
        self._load_toc()

    def _load_toc(self) -> None:
        want = self.header.count
        buf = b""
        while True:
            chunk = self._read(HEADER_SIZE + len(buf), 1 << 20)
            if not chunk:
                raise ValueError("BIG table of contents truncated")
            buf += chunk
            members, complete = _parse_records(buf, want)
            if complete:
                self.members = members
                self._by_name = {m.name: m for m in members}
                return
            if len(buf) > self.header.total_size:
                raise ValueError("BIG table of contents overruns the archive")

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def member(self, name: str) -> Member:
        return self._by_name[name]

    def read_member(self, name: str) -> bytes:
        m = self._by_name[name]
        data = self._read(m.offset, m.size)
        if len(data) != m.size:
            raise ValueError(f"short read for {name}")
        return data

    def names(self) -> list[str]:
        return [m.name for m in self.members]

    def read_from_disc(self, disc, path: str) -> "BigArchive":
        """Open the BIG container stored as ``path`` on a GameCube disc."""
        off, size = disc.files[path]
        return BigArchive(lambda o, n: disc._r(off + o, n))


def build_big(members: Iterable[tuple[str, bytes]], magic: bytes = b"BIGF") -> bytes:
    """Build a BIGF container from (name, bytes) pairs.  Used for round-trip tests.

    Layout mirrors the owned build: 16-byte header, then the table of contents, then the member
    data.  Member offsets in the table are relative to the archive start, so the header's
    data_start field is the first byte after the table of contents.
    """
    members = list(members)
    names = [n.encode("latin-1") for n, _ in members]
    toc_len = sum(8 + len(nm) + 1 for nm in names)
    data_start = HEADER_SIZE + toc_len
    toc = bytearray()
    body_off = 0
    for nm, (_, blob) in zip(names, members):
        toc += struct.pack(">II", data_start + body_off, len(blob)) + nm + b"\0"
        body_off += len(blob)
    body = b"".join(blob for _, blob in members)
    header = magic + struct.pack("<I", data_start + len(body))
    header += struct.pack(">II", len(members), data_start)
    return bytes(header) + bytes(toc) + body


@dataclass(frozen=True)
class Gsh:
    """A decoded SHPG character asset."""
    tag: str
    payload: bytes
    compressed_size: int

    @property
    def unpacked_size(self) -> int:
        return len(self.payload)


def decode_gsh(raw: bytes) -> Gsh:
    """Inflate one RefPack/QFS member and check the SHPG header."""
    if not refpack.is_refpack(raw):
        raise ValueError("member is not an EA RefPack stream")
    data, used = refpack.decompress_ex(raw)
    if data[:4] != SHPG_MAGIC:
        raise ValueError(f"member does not carry an SHPG payload: {data[:4]!r}")
    tag = data[SHPG_TAG_OFFSET:SHPG_TAG_OFFSET + SHPG_TAG_SIZE].decode("latin-1")
    return Gsh(tag, data, used)


def character_slots(archive: BigArchive) -> list[str]:
    """The native character slots of a players archive, in table order."""
    import re
    rx = re.compile(PLAYER_RE)
    return [m.name for m in archive.members if rx.match(m.name)]
