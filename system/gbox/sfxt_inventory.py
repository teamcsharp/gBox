"""Street Fighter X Tekken (Xbox 360) — inventory reader.

Stage 1 (inventory): resolve the owned Xbox 360 XDVDFS disc, locate and hash
the XEX executable, and census the container layout.  The game data lives in
MT Framework ``#EAF`` archives (``archive/CMN/CMN.eaf``, ~2.1 GB) plus CRI
ADX2 audio (``.awb``) and WMV cutscenes under ``stream/``.

The catalog platform label ``xbox360`` is correct: this image is a stripped
XDVDFS volume (game partition at offset 0, not the XGD2 offset 0x02080000)
with a ``XEX2`` default.xex.  XDVDFS directory records are little-endian;
the ``#EAF`` archive header is big-endian (PowerPC).  The next stage
(analysis) must parse the ``#EAF`` container to enumerate character
model/texture/animation entries.

Usage:
    python -m gbox.sfxt_inventory /path/to/Street_Fighter_X_Tekken.iso
"""
from __future__ import annotations

import hashlib
import struct
import sys

MAGIC = b"MICROSOFT*XBOX*MEDIA"
# Descriptor bases checked by gbox.xbox_disc (and observed on this disc: base 0).
BASES = (0, 0x0FD90000, 0x02080000, 0x18300000)
EAF_MAGIC = b"#EAF"


def eaf_header(head: bytes) -> dict:
    """Parse the big-endian #EAF archive header (PowerPC).

    Observed on this build:
      +0x00 magic b"#EAF"
      +0x04 u32 BE 0x00010000 (version/flags)
      +0x08 u32 BE 0
      +0x0c u32 BE data/content size (== file size for CMN_boot.eaf)
      +0x10 u32 BE entry count (11610 for CMN.eaf, 67 for CMN_boot.eaf)
      +0x14 u32 BE 1
    """
    magic = head[:4]
    if magic != EAF_MAGIC:
        return {"magic": magic.hex()}
    if len(head) < 24:
        raise ValueError("truncated EAF header")
    word04, word08, word0c, word10, word14 = struct.unpack_from(">5I", head, 4)
    return {
        "magic": "#EAF",
        "version_word": word04,
        "data_size": word0c,
        "entry_count": word10,
        "word14": word14,
    }


class XDVDFS:
    """Read-only XDVDFS filesystem walker over an Xbox 360 ISO."""

    def __init__(self, path: str):
        self.f = open(path, "rb")
        self.f.seek(0, 2)
        self.size = self.f.tell()
        try:
            self.base, self.root_sector, self.root_len = self._locate()
        except Exception:
            self.f.close()
            raise

    def _locate(self):
        for base in BASES:
            at = base + 0x10000
            if at + 2048 > self.size:
                continue
            self.f.seek(at)
            block = self.f.read(2048)
            if block[:20] != MAGIC or block[-20:] != MAGIC:
                continue
            sector, length = struct.unpack_from("<II", block, 20)
            if not 14 <= length <= 16 * 1024**2 or base + sector * 2048 + length > self.size:
                raise ValueError("XDVDFS root outside image")
            return base, sector, length
        raise ValueError("no XDVDFS volume descriptor found")

    def dirents(self, sector: int, length: int):
        db = self.read(sector, length)
        out, seen = [], set()

        def walk(o):
            if o in seen or o + 14 > len(db):
                return
            seen.add(o)
            left, right, ssec, sz, attr, nlen = struct.unpack_from("<HHIIBB", db, o)
            name = db[o + 14:o + 14 + nlen].decode("ascii", "replace")
            out.append((name, ssec, sz, attr))
            if left != 0xFFFF and left * 4 < len(db):
                walk(left * 4)
            if right != 0xFFFF and right * 4 < len(db):
                walk(right * 4)

        walk(0)
        return out

    def files(self):
        found: dict[str, tuple[int, int]] = {}

        visited = set()
        def walk_dir(sector, length, path, depth=0):
            if (sector, length) in visited:
                raise ValueError("cyclic XDVDFS directory")
            visited.add((sector, length))
            for name, ssec, sz, attr in self.dirents(sector, length):
                if name == "" and attr & 0x10:
                    continue  # root self-entry
                p = f"{path}/{name}" if path else name
                if attr & 0x10:
                    walk_dir(ssec, sz, p, depth + 1)
                else:
                    found[p] = (ssec, sz)

        walk_dir(self.root_sector, self.root_len, "")
        return found

    def read(self, sector: int, length: int) -> bytes:
        offset = self.base + sector * 2048
        if sector < 0 or length < 0 or offset + length > self.size:
            raise ValueError("XDVDFS read outside image")
        self.f.seek(offset)
        result = self.f.read(length)
        if len(result) != length:
            raise ValueError("truncated XDVDFS read")
        return result

    def sha256(self, sector: int, length: int) -> str:
        self.f.seek(self.base + sector * 2048)
        h = hashlib.sha256()
        left = length
        while left > 0:
            chunk = self.f.read(min(4 * 1024 * 1024, left))
            if not chunk:
                raise ValueError("truncated XDVDFS file while hashing")
            h.update(chunk)
            left -= len(chunk)
        return h.hexdigest()


def inventory(path: str) -> dict:
    iso = XDVDFS(path)
    try:
        files = iso.files()

        xex = [p for p in files if p.lower() == "default.xex"]
        if len(xex) != 1:
            raise ValueError(f"expected exactly one default.xex, got {xex}")

        xex_sec, xex_sz = files[xex[0]]
        xex_head = iso.read(xex_sec, 4)
        if xex_head != b"XEX2":
            raise ValueError(f"default.xex is not XEX2 (got {xex_head!r})")

        eafs = []
        for p, (sec, sz) in sorted(files.items()):
            if p.lower().endswith(".eaf"):
                eafs.append({"path": p, "size": sz, **eaf_header(iso.read(sec, min(sz, 32)))})

        total = sum(sz for _, sz in files.values())
        return {
            "source": path,
            "size": iso.size,
            "platform": "xbox360",
            "volume": {"base": iso.base, "root_sector": iso.root_sector, "root_bytes": iso.root_len},
            "file_count": len(files),
            "total_bytes": total,
            "executable": {
                "name": xex[0],
                "size": xex_sz,
                "sha256": iso.sha256(xex_sec, xex_sz),
                "magic": "XEX2",
            },
            "eaf_archives": eafs,
        }

    finally:
        iso.f.close()


def main(argv):
    import json
    result = inventory(argv[0])
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
