"""ISO9660 directory walking shared by every disc reader (PS1/PS2 ISO and CHD, Dreamcast GD-ROM high-density area,
PS2 DVD images, the ROM exporter).

Before this module, psxdisc, gdrom, defjam_inventory, raidou2_inventory and romexport each carried the same record
walk. They now call walk() with their own sector reader and keep their own path conventions (case, leading slash,
trailing '.' handling), so their file tables are unchanged.

Directory record: u8 length, u8 ext-attr length, u32 LE extent LBA (+2), u32 LE size (+10), flags (+25, bit 1 = dir),
u8 name length (+32), name (+33). Records never cross a sector: a 0 length byte means "next sector".
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Iterator

SECTOR = 2048


@dataclass(frozen=True)
class Record:
    name: str           # as stored, ';1' version suffix removed
    lba: int
    size: int
    is_dir: bool
    offset: int         # byte offset of the record inside its directory extent
    flags: int


def pvd_root(pvd: bytes) -> tuple[int, int]:
    """(root directory LBA, size) from a primary volume descriptor sector."""
    if pvd[1:6] != b"CD001":
        raise ValueError("no ISO9660 primary volume descriptor")
    return struct.unpack_from("<I", pvd, 158)[0], struct.unpack_from("<I", pvd, 166)[0]


def pvd_info(pvd: bytes) -> dict:
    root_lba, root_size = pvd_root(pvd)
    return {"system": pvd[8:40].decode("ascii", "replace").strip(), "volume": pvd[40:72].decode("ascii", "replace").strip(),
            "blocks": struct.unpack_from("<I", pvd, 80)[0], "root_lba": root_lba, "root_size": root_size}


def records(buf: bytes, *, strict: bool = False, encoding: str = "latin-1", sector: int = SECTOR,
            where: str = "") -> Iterator[Record]:
    """Every record of one directory extent except '.' and '..'. strict: a malformed record raises ValueError
    (otherwise the walk of this directory stops there)."""
    o = 0
    while o < len(buf):
        n = buf[o]
        if n == 0:
            o = (o // sector + 1) * sector
            continue
        if n < 34 or o + 34 > len(buf) or (strict and (o + n > len(buf) or 33 + buf[o + 32] > n)):
            if strict:
                raise ValueError(f"bad ISO9660 directory record at {where or '/'}+{o:#x}")
            return
        nl = buf[o + 32]
        raw = buf[o + 33:o + 33 + nl]
        if raw not in (b"\0", b"\1"):
            yield Record(raw.decode(encoding, "replace" if encoding == "ascii" else "strict").split(";")[0],
                         struct.unpack_from("<I", buf, o + 2)[0], struct.unpack_from("<I", buf, o + 10)[0],
                         bool(buf[o + 25] & 2), o, buf[o + 25])
        o += n


def walk(read: Callable[[int, int], bytes], lba: int, size: int, *, strict: bool = False, encoding: str = "latin-1",
         max_depth: int | None = None, too_deep: str = "skip", max_dir_size: int | None = None,
         on_dir: Callable[[int, int], None] | None = None) -> Iterator[tuple[tuple[str, ...], Record, int]]:
    """Depth-first walk from a directory extent. read(lba, size) returns the extent's bytes. Yields
    (parent path parts, record, LBA of the directory holding the record) for files AND directories (record.is_dir),
    a directory before its contents. max_depth / max_dir_size bound hostile images: too_deep="skip" drops that
    directory, "raise" raises ValueError. on_dir(lba, size) is called for every directory extent read."""
    def visit(lba, size, parts, depth):
        if (max_depth is not None and depth > max_depth) or (max_dir_size is not None and size > max_dir_size):
            if too_deep == "raise":
                raise ValueError("ISO directory tree too deep")
            return
        if on_dir:
            on_dir(lba, size)
        buf = read(lba, size)
        for rec in records(buf, strict=strict, encoding=encoding, where="/".join(parts)):
            yield parts, rec, lba
            if rec.is_dir:
                yield from visit(rec.lba, rec.size, parts + (rec.name,), depth + 1)
    yield from visit(lba, size, (), 0)


def files(read: Callable[[int, int], bytes], lba: int, size: int, **kw) -> dict[str, tuple[int, int]]:
    """{'DIR/NAME': (lba, size)} for every file (names as stored, without ';1')."""
    return {"/".join(p + (r.name,)): (r.lba, r.size) for p, r, _ in walk(read, lba, size, **kw) if not r.is_dir}


def file_reader(f, sector: int = SECTOR, base: int = 0) -> Callable[[int, int], bytes]:
    """read(lba, size) over a cooked (2048-byte sector) image file object."""
    def read(lba: int, size: int) -> bytes:
        f.seek(base + lba * sector)
        return f.read(size)
    return read


def sector_reader(data: Callable[[int], bytes], sector: int = SECTOR) -> Callable[[int, int], bytes]:
    """read(lba, size) from a one-sector reader data(lba) -> 2048 user bytes (raw images, CHD, GD-ROM tracks)."""
    def read(lba: int, size: int) -> bytes:
        return b"".join(data(lba + i) for i in range((size + sector - 1) // sector))
    return read
