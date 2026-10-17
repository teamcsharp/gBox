"""Tekken Tag Tournament 2 (Xbox 360) owned-disc inventory (#1993).

Read-only.  The owned source is the HyperSpin ISO ``collections/Microsoft XBOX 360/
roms/Tekken Tag Tournament 2.iso`` (8,303,542,272 bytes, one XDVDFS volume at base 0).
There is no PS3/360 engine reader in gBox yet, so this module is the first Xbox-360
XDVDFS walker; it does not modify the image and never loads it whole.

Disc facts (verified against the image):

* XDVDFS descriptor at offset 0x10000: ``MICROSOFT*XBOX*MEDIA`` (2048-byte block that
  also ends with the magic), root directory at sector 264, 1280 bytes.  The catalog
  platform label ``xbox360`` is correct: the boot file is ``Default.xex`` (XEX2,
  PowerPC), not an original-Xbox ``default.xbe``.
* 46 files, all at the disc root (no subdirectories):
  - ``Default.xex`` (15,941,632 B, XEX2 magic ``XEX2``)
  - ``data000.bin``..``data053.bin`` (the packed game data, ~7.9 GB total, with gaps:
    no 020-024, 029-033, 048-049)
  - ``AvatarAssetPack`` (13,799,424 B), ``nxeart`` (PIRS container, 2.3 MB),
    ``nrfo.bin`` (0.3 MB u32 table)
* ``data026.bin`` is NOT a data pack: it is an ISO-BMFF/MP4 stub (``ftyp nrfi``).
  ``nxeart`` is a PIRS/LIVE container (magic ``PIRS``).

Engine / container identification (first pass):

* Every ``dataNNN.bin`` starts with the big-endian Namco pack magic ``0x0FF512ED``
  (version ``0x01000000``), then two u32 (a CRC/hash pair) and a table of 16-byte
  records.  The first 16 records of ``data000.bin`` read as ``(offset, size)`` pairs
  whose ranges stay inside the file; the 17th is out of bounds, so the table is at
  least 16 entries and its exact terminator/count field is analysis-stage work.
  Byte probes at those offsets are high-entropy (no sub-magic), consistent with the
  community finding that entries are XMemCompress/LZX-compressed and that the game
  was shipped with ``xbdecompress`` for them.
* Namco model/texture/shader/skeleton sub-formats (public TTT2 documentation):
  NDXR (geometry), NTXR (texture), NSXR (shader), BONE (skeleton), packed in the
  ``dataNNN.bin`` stream after decompression.  Enumerating the actual character/costume
  entries requires decoding the pack table + XMemCompress, which is the analysis stage.

Usage::

    python -m gbox.ttt2_inventory <image.iso> --source-sha256 HEX --out manifest.json
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

SECTOR = 2048
XDVDFS_MAGIC = b"MICROSOFT*XBOX*MEDIA"
# Descriptor bases checked by the pinned XboxDev extractor (base + 0x10000).
BASES = (0, 0x0FD90000, 0x02080000, 0x18300000)
PACK_MAGIC = 0x0FF512ED
BOOT = "Default.xex"


class Xdvdfs:
    """Seek-based XDVDFS walker; never load the image whole."""

    def __init__(self, path: str):
        self.path = str(path)
        self.size = Path(path).stat().st_size
        self.f = open(path, "rb")
        try:
            self.base, self.root_sector, self.root_size = self._locate()
        except Exception:
            self.f.close()
            raise

    def _locate(self):
        found = []
        for base in BASES:
            at = base + 0x10000
            if at + 2048 > self.size:
                continue
            self.f.seek(at)
            block = self.f.read(2048)
            if block[:20] != XDVDFS_MAGIC:
                continue
            if block[-20:] != XDVDFS_MAGIC:
                raise ValueError(f"{self.path}: incomplete XDVDFS descriptor at 0x{at:x}")
            sector, length = struct.unpack_from("<II", block, 20)
            offset = base + sector * SECTOR
            if not 14 <= length <= 16 * 1024**2 or offset + length > self.size:
                raise ValueError(f"{self.path}: XDVDFS root directory out of bounds")
            found.append((base, sector, length))
        if len(found) != 1:
            raise ValueError(f"{self.path}: need exactly one XDVDFS volume, found {len(found)}")
        return found[0]

    def read(self, sector: int, size: int) -> bytes:
        offset = self.base + sector * SECTOR
        if sector < 0 or size < 0 or offset + size > self.size:
            raise ValueError("XDVDFS read outside image")
        self.f.seek(offset)
        data = self.f.read(size)
        if len(data) != size:
            raise ValueError("truncated XDVDFS read")
        return data

    def close(self):
        self.f.close()

    def files(self) -> dict[str, tuple[int, int]]:
        """Return ``{path: (sector, size)}`` for every file (directories dropped)."""
        files: dict[str, tuple[int, int]] = {}

        visited = set()
        def walk(sec: int, size: int, path: str):
            if (sec, size) in visited:
                raise ValueError("cyclic XDVDFS directory")
            visited.add((sec, size))
            data = self.read(sec, size)
            stack, seen = [0], set()
            while stack:
                idx = stack.pop()
                if idx in seen:
                    continue
                seen.add(idx)
                off = idx * 4
                if off + 14 > len(data):
                    continue
                left, right, s, n, attr, nl = struct.unpack("<HHIIBB", data[off:off + 14])
                if off + 14 + nl > len(data):
                    raise ValueError("truncated XDVDFS filename")
                name = data[off + 14:off + 14 + nl].decode("latin-1")
                if left not in (0, 0xFFFF):
                    stack.append(left)
                if right not in (0, 0xFFFF):
                    stack.append(right)
                full = f"{path}/{name}" if path else name
                if attr & 0x10:
                    if n:
                        walk(s, n, full)
                else:
                    files[full] = (s, n)

        walk(self.root_sector, self.root_size, "")
        return files


def pack_header(blob: bytes, file_size: int) -> dict:
    """First-pass 0x0FF512ED header read (big-endian); entry terminator is TBD."""
    if len(blob) < 16:
        raise ValueError("pack header too short")
    magic, version, f1, f2 = struct.unpack_from(">IIII", blob, 0)
    if magic != PACK_MAGIC:
        raise ValueError(f"not a Namco pack: magic 0x{magic:08x}")
    records = []
    for i in range(16, len(blob) - 7, 8):
        a, b = struct.unpack_from(">II", blob, i)
        # Records whose range leaves the file mark the end of the table.
        if a == 0 or b == 0 or a + b > file_size or a >= file_size:
            break
        records.append((a, b))
    return {"magic": magic, "version": version, "field1": f1, "field2": f2,
            "records": records}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:]]
    source_sha256 = None
    out = None
    image = None
    i = 0
    while i < len(args):
        if args[i] == "--source-sha256":
            source_sha256 = args[i + 1]; i += 2
        elif args[i] == "--out":
            out = args[i + 1]; i += 2
        else:
            image = args[i]; i += 1
    if not image or not out:
        print("usage: python -m gbox.ttt2_inventory <image.iso> "
              "--source-sha256 HEX --out manifest.json", file=sys.stderr)
        return 2

    dvd = Xdvdfs(image)
    try:
        files = dvd.files()
        print(f"XDVDFS base=0x{dvd.base:x} root_sector={dvd.root_sector} "
              f"root_size={dvd.root_size} files={len(files)}")

        if BOOT not in files and BOOT.lower() not in {p.lower() for p in files}:
            raise ValueError("no Default.xex boot executable on disc")

        boot_path = BOOT if BOOT in files else next(p for p in files if p.lower() == BOOT.lower())
        s, n = files[boot_path]
        xex = dvd.read(s, n)
        if xex[:4] != b"XEX2":
            raise ValueError(f"boot file is not XEX2: {xex[:4]!r}")
        boot_sha = hashlib.sha256(xex).hexdigest()
        print(f"{boot_path}: {n} bytes, XEX2, sha256={boot_sha}")

        # Container first pass: classify every root file, parse pack headers in place.
        containers = []
        for path, (sec, size) in sorted(files.items()):
            head = dvd.read(sec, min(size, 16))
            kind = "other"
            info = {}
            if head[:4] == b"XEX2":
                kind = "xex"
            elif len(head) >= 4 and struct.unpack(">I", head[:4])[0] == PACK_MAGIC:
                kind = "pack"
                blob = dvd.read(sec, min(size, 65536))
                info = pack_header(blob, size)
                info["table_truncated"] = (size > 65536 and 65536 - len(info["records"]) * 8 <= 32)
                info["record_count"] = len(info["records"])
                info["records"] = info["records"][:8]  # sample only; re-run for full table
            elif head[:4] == b"PIRS":
                kind = "pirs"
            elif head[4:8] == b"ftyp":
                kind = "isobmff"
            elif path == "nrfo.bin":
                kind = "table"
            entry = {"path": path, "sector": sec, "size": size, "kind": kind}
            if kind == "pack":
                entry.update(info)
            containers.append(entry)

        manifest = {
            "game": "Tekken Tag Tournament 2",
            "platform": "xbox360",
            "source_sha256": source_sha256,
            "source_size": dvd.size,
            "xdvdfs": {"base": dvd.base, "root_sector": dvd.root_sector,
                       "root_size": dvd.root_size},
            "boot": {"path": boot_path, "sha256": boot_sha, "size": n, "format": "xex2"},
            "files": containers,
            "engine": "Namco (Tekken 6 / TTT2 family)",
            "pack_magic": "0x0FF512ED",
            "known_sub_formats": ["NDXR geometry", "NTXR texture", "NSXR shader", "BONE skeleton"],
            "next_stage": "analysis: decode 0x0FF512ED table terminator + XMemCompress entries",
        }
        with open(out, "w") as fh:
            json.dump(manifest, fh, indent=1)
        packs = [c for c in containers if c["kind"] == "pack"]
        print(f"manifest -> {out}  ({len(packs)} packs, {len(files)} files total)")
        for c in packs:
            print(f"  {c['path']:18s} records={c.get('record_count', 0)}"
                  f"{' (truncated)' if c.get('table_truncated') else ''}")
        return 0
    finally:
        dvd.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
