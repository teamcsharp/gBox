"""Owned-build inventory for Def Jam Icon (Xbox 360, gBox request #1994).

Identifies the exact disc image, hashes it, and lists the GDFX directory tree so later
stages can locate the character/asset archives. This reader replaces the assimilation
fingerprint's "start from gbox.defjam_models" advice, which is wrong for this title:
Def Jam Icon is an EA Chicago (Fight Night engine) game, not an AKI title. Its assets
are EA BIG4/VIV4 archives (``common/char.viv`` + ``common/char.viv.bh``), its textures
are RX2, its animation system is ANT, and its executable is a PowerPC XEX2 image --
none of which the AKI PS2 reader ``gbox.defjam_models`` understands.

Disc layout (an XGD2-style image, not a plain ISO9660 volume):

    sector 0x10   ISO9660 PVD ("CD001"), an empty bridge stub (7-Zip reports 0 files)
    sector 0x20   GDFX descriptor: "MICROSOFT*XBOX*MEDIA", root_sector at +20,
                  root_size (bytes) at +24
    sector N      the game partition; root directory at root_sector * 2048

Directory entries are packed records forming a binary tree (confirmed against Xenia's
``disc_image_device.cc``, the GDFX reader):

    u16 left_ordinal    byte-offset/4 of the left child in the same buffer (0 = none)
    u16 right_ordinal   byte-offset/4 of the right child (0 = none)
    u32 sector          file: data sector; directory: child-list buffer sector
    u32 length          file: byte size; directory: child-list buffer byte size
    u8  attributes      0x10 = directory, 0x20 = file
    u8  name_length
    u8  name[name_length]
    .. padded to a 4-byte boundary

Usage:
    python -m gbox.defjam_icon_inventory <iso> [--json out.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

SECTOR = 2048
MAGIC = b"MICROSOFT*XBOX*MEDIA"
ATTR_DIRECTORY = 0x10
# Descriptor bases checked by Xenia (and extract-xiso) for the game partition.
GAME_OFFSETS = (0x00000000, 0x0000FB20, 0x00020600, 0x02080000, 0x0FD90000)


class GDFXError(Exception):
    """Raised when an image is not a recognized GDFX (Xbox 360) disc."""


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def sha256(path: str | Path, chunk: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while data := stream.read(chunk):
            digest.update(data)
    return digest.hexdigest()


class GDFX:
    """Read-only GDFX (Xbox 360 game partition) directory walker."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh = open(self.path, "rb")
        self.size = self._fh.seek(0, os.SEEK_END)
        self.game_offset = 0
        self.root_sector = 0
        self.root_size = 0
        try:
            self._find_descriptor()
        except Exception:
            self._fh.close()
            raise

    def _find_descriptor(self) -> None:
        for game_offset in GAME_OFFSETS:
            at = game_offset + 32 * SECTOR
            if at + SECTOR > self.size:
                continue
            self._fh.seek(at)
            block = self._fh.read(SECTOR)
            if block[:20] != MAGIC:
                continue
            root_sector = struct.unpack_from("<I", block, 20)[0]
            root_size = struct.unpack_from("<I", block, 24)[0]
            root_offset = game_offset + root_sector * SECTOR
            if not 13 <= root_size <= (32 * 1024 * 1024):
                raise GDFXError(f"GDFX root directory size {root_size} is out of range")
            if root_offset + root_size > self.size:
                raise GDFXError("GDFX root directory lies outside the image")
            self.game_offset = game_offset
            self.root_sector = root_sector
            self.root_size = root_size
            return
        raise GDFXError("no GDFX descriptor (MICROSOFT*XBOX*MEDIA) found in image")

    def _read(self, sector: int, length: int) -> bytes:
        at = self.game_offset + sector * SECTOR
        if length < 0 or at < 0 or at + length > self.size:
            raise GDFXError(f"read {at:#x}+{length} exceeds image size {self.size:#x}")
        self._fh.seek(at)
        return self._fh.read(length)

    def read_file(self, sector: int, length: int) -> bytes:
        return self._read(sector, length)

    def walk(self):
        """Yield (path, is_dir, sector, length) for every entry, files only after dirs.

        Directory child lists are read on demand and guarded against cycles on the
        (sector, length) pair so a self-referential or damaged image cannot recurse
        forever.
        """
        visited: set[tuple[int, int]] = {(self.root_sector, self.root_size)}
        root = self._read(self.root_sector, self.root_size)

        def emit(buf: bytes, ordinal: int, prefix: str, seen=None):
            seen = set() if seen is None else seen
            if ordinal in seen:
                raise GDFXError("cyclic GDFX directory entry")
            seen.add(ordinal)
            p = ordinal * 4
            if p + 14 > len(buf):
                return
            left, right = struct.unpack_from("<HH", buf, p)
            sector, length = struct.unpack_from("<II", buf, p + 4)
            attr = buf[p + 12]
            name_len = buf[p + 13]
            if name_len > len(buf) - p - 14:
                return
            name = buf[p + 14 : p + 14 + name_len].decode("latin1")
            path = f"{prefix}/{name}" if prefix else name
            if left:
                yield from emit(buf, left, prefix, seen)
            if attr & ATTR_DIRECTORY:
                yield path, True, sector, length
                key = (sector, length)
                if length and key not in visited:
                    visited.add(key)
                    try:
                        yield from emit(self._read(sector, length), 0, path)
                    except GDFXError:
                        yield f"{path} <unreadable>", False, sector, length
            else:
                yield path, False, sector, length
            if right:
                yield from emit(buf, right, prefix, seen)

        yield from emit(root, 0, "")

    def manifest(self) -> dict:
        files = []
        total = 0
        for path, is_dir, sector, length in self.walk():
            if not is_dir:
                files.append({"path": path, "sector": sector, "size": length})
                total += length
        return {
            "source_sha256": sha256(self.path),
            "size": self.size,
            "game_offset": self.game_offset,
            "root_sector": self.root_sector,
            "root_size": self.root_size,
            "file_count": len(files),
            "total_bytes": total,
            "files": files,
        }

    def close(self) -> None:
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m gbox.defjam_icon_inventory",
                                 description=(__doc__ or "").strip().split("\n")[0])
    ap.add_argument("iso", help="path to the Xbox 360 disc image")
    ap.add_argument("--json", help="write the manifest to this file")
    ap.add_argument("--tree", action="store_true", help="print the full directory tree")
    args = ap.parse_args(argv)

    with GDFX(args.iso) as disc:
        if args.tree:
            for path, is_dir, sector, length in disc.walk():
                kind = "dir " if is_dir else "file"
                print(f"{kind:4s} {path:60s} sector={sector:8d} size={length}")
        manifest = disc.manifest()
        if args.json:
            Path(args.json).write_text(json.dumps(manifest, indent=2), encoding="utf8")
            print(f"wrote {args.json}")
        print(f"source_sha256={manifest['source_sha256']}")
        print(f"files={manifest['file_count']} total_bytes={manifest['total_bytes']}")


if __name__ == "__main__":
    main()
