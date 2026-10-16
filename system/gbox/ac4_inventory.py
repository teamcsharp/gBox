"""Armored Core 4 (Xbox 360) — stage 1 inventory: XDVDFS disc reader + asset census.

The Xbox 360 disc is an XDVDFS volume. The volume descriptor sits at sector 32
(byte 0x10000) and is bracketed by the ``MICROSOFT*XBOX*MEDIA`` magic; its two
u32 fields at offset 20 are (root directory sector, root directory byte length).

Directory entries are 14-byte headers: u16 left, u16 right (binary-tree offsets),
u32 start sector, u32 size, u8 attributes (0x10 = directory, 0x20 = file),
u8 name length, then the raw name. Each entry is padded with 0xff so its total
length (14 + name length) rounds up to a multiple of 4. Entries are stored
contiguously, so a linear scan enumerates a directory without following the tree.

Asset census (this build):
  mesh       model/poly/m###/*.rmb   (Rigged Model Binary, FromSoft)
  texture    model/image/** + *.xpr  (Xbox 360 XPR), *.mlb material libs
  animation  ane/ac/*.anc, ane/enemy/*.anc
  params     param/*.bin             (acparts.bin = AC part table)
  shaders    effect/*.fxo            (compiled Xbox 360 shaders)
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"MICROSOFT*XBOX*MEDIA"
SECTOR = 2048
DESCRIPTOR_SECTOR = 0x10000 // SECTOR  # 32


@dataclass(frozen=True)
class Entry:
    sector: int
    size: int
    attributes: int
    name: str

    @property
    def is_dir(self) -> bool:
        return bool(self.attributes & 0x10)


def parse_dir(buf: bytes) -> list[Entry]:
    """Parse one XDVDFS directory buffer into entries (linear scan)."""
    entries: list[Entry] = []
    o, n = 0, len(buf)
    while o + 14 <= n:
        _left, _right, sector, size, attr, namelen = struct.unpack_from("<HHIIBB", buf, o)
        if namelen == 0:
            break
        end = (o + 14 + namelen + 3) & ~3  # round up to multiple of 4
        if end > n:
            break
        entries.append(Entry(sector, size, attr, buf[o + 14:o + 14 + namelen].decode("latin-1")))
        o = end
    return entries


def descriptor(path: Path) -> tuple[int, int]:
    """(root directory sector, root directory byte length) from an XDVDFS image."""
    with path.open("rb") as f:
        f.seek(DESCRIPTOR_SECTOR * SECTOR)
        blk = f.read(SECTOR)
    if blk[:20] != MAGIC or blk[-20:] != MAGIC:
        raise ValueError("not an XDVDFS Xbox 360 disc image")
    return struct.unpack_from("<II", blk, 20)


def walk(path: Path, max_depth: int | None = None):
    """Yield (parent_parts, Entry) for every file and directory, breadth-first-ish."""
    root_sector, root_len = descriptor(path)
    with path.open("rb") as f:
        def read_dir(sector: int, size: int) -> bytes:
            f.seek(sector * SECTOR)
            return f.read(size)

        stack: list[tuple[int, int, tuple[str, ...]]] = [(root_sector, root_len, ())]
        seen: set[tuple[int, int]] = set()
        while stack:
            sec, size, parts = stack.pop()
            key = (sec, size)
            if key in seen:
                continue
            seen.add(key)
            for entry in parse_dir(read_dir(sec, size)):
                yield parts, entry
                if entry.is_dir and (max_depth is None or len(parts) < max_depth):
                    stack.append((entry.sector, entry.size, parts + (entry.name,)))


def resolve(path: Path, parts: tuple[str, ...]) -> tuple[int, int] | None:
    """(sector, size) of a single directory reached by walking ``parts`` from the root."""
    root_sector, root_len = descriptor(path)
    sector, size = root_sector, root_len
    with path.open("rb") as f:
        for part in parts:
            f.seek(sector * SECTOR)
            entries = parse_dir(f.read(size))
            hit = next((e for e in entries if e.name == part), None)
            if hit is None:
                return None
            sector, size = hit.sector, hit.size
    return sector, size


def extract(path: Path, sector: int, size: int) -> bytes:
    with path.open("rb") as f:
        f.seek(sector * SECTOR)
        return f.read(size)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(path: Path, max_depth: int | None = None) -> dict:
    """Stage-1 census: executable identity, container layout, and format counts."""
    root_sector, root_len = descriptor(path)
    files: dict[str, tuple[int, int]] = {}
    dirs: list[str] = []
    for parts, entry in walk(path, max_depth=max_depth):
        full = "/".join(parts + (entry.name,))
        if entry.is_dir:
            dirs.append(full)
        else:
            files[full] = (entry.sector, entry.size)

    exts: dict[str, int] = {}
    for name in files:
        leaf = name.rsplit("/", 1)[-1]
        ext = leaf.rsplit(".", 1)[-1].lower() if "." in leaf else "(none)"
        exts[ext] = exts.get(ext, 0) + 1

    xex = next((n for n in files if n.lower().endswith("default.xex")), None)
    executable = None
    if xex:
        sector, size = files[xex]
        executable = {"name": xex, "sector": sector, "size": size,
                      "sha256": sha256_bytes(extract(path, sector, size))}

    return {
        "source": str(path),
        "source_sha256": sha256_bytes(path.read_bytes()),
        "root_sector": root_sector,
        "root_length": root_len,
        "file_count": len(files),
        "dir_count": len(dirs),
        "extensions": exts,
        "executable": executable,
    }
