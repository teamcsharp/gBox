"""Naruto: The Broken Bond (Xbox 360, Ubisoft Montreal) -- owned-disc inventory for character work.

Catalog e0d46d43990c3b82 is a plain 3.4 GB Xbox 360 ISO (no CHD/GCZ wrapper) at
/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Naruto - The Broken Bond.iso.
The disc is an XDVDFS filesystem (``MICROSOFT*XBOX*MEDIA`` volume descriptor at sector 32, root
sector 264), NOT the iso9660 that gbox.assimilate reports -- its fingerprint ("[disc] engine
unknown", 0 files) simply cannot read XDVDFS, so the fingerprint's platform/container claims are
wrong for this disc.  The walk below resolves 215 files.

Container layout (every byte of game data lives behind two archives):

  naruto.bf        750,046,958 B  "BF64" BigFile -- THE asset archive.  Header: magic BF64,
                    version 1, then 42 indices / 1780 parameter / 2 files / 0 folders and the
                    file/folder info tables.  Ubisoft Montreal's custom BigFile (documented by
                    aluigi's ubisoft_bf64.bms / sally_bf.bms).  Character models, textures and
                    animation are inside this file; parsing it is the analysis-stage opener.
  Naruto.SRA       165,408,943 B  "FRSA" streaming archive (audio/video bank, 4 .SRA in total:
                    Naruto_clip.SRA, naruto_sound.sra, naruto_stream.sra ~1.4 GB combined).
  *.bik (204)      Bink video ("BIKi"), 720p cutscenes / jutsu / rage / attract loops.
  media/LinkApp.xzp "XUIZ" Xbox 360 XUI resource archive (Loading.xur + UBITTB/UBITXTR .ttf).
  xeshader.sdb     "3BDS" Xenon compiled shader database (dx9featuredefinitions.h).

Executables (both XEX2, big-endian module headers):
  default.xex   15,351,808 B  sha256 8f70e79443e36b38e44b6a105dad51fb8909fb615d982753cabaac9b15f0d576
  LinkApp.xex    1,875,968 B  sha256 2505f44b7cfa7e35742673668bee8e38618ff198432f1b6ba13c71b80a540c95

Character evidence so far is only cutscene filenames (F_M301NAR/SHIKA, F_M302NAR/CHOJI,
F_M306_Itachi, F_M208) -- the real roster is inside naruto.bf.  No model/texture magic exists
outside the BigFile, so the reader must parse BF64 first (analysis stage).
"""
from __future__ import annotations

import hashlib
import json
import struct
from collections import Counter

XDVDFS_MAGIC = b"MICROSOFT*XBOX*MEDIA"
SECTOR = 2048
# XDVDFS partition base candidates used across the Xbox 360 library.
PARTITIONS = (0, 0x2080000, 0xFD90000, 0x18300000, 0x12000000)

CONTAINER_MAGICS = {
    b"BF64": "Ubisoft BigFile (BF64) -- game asset archive",
    b"FRSA": "Ubisoft streaming archive (SRA)",
    b"BIKi": "Bink video (Rad Game Tools)",
    b"XUIZ": "Xbox 360 XUI resource archive",
    b"3BDS": "Xenon compiled shader database",
    b"XEX2": "Xbox 360 executable",
}


def xdvdfs_locate(fh, partitions=PARTITIONS) -> tuple[int, int, int]:
    """Return (partition_base, root_sector, root_size) for an XDVDFS disc.

    The volume descriptor is at partition_base + 32*sector; it holds the root
    directory sector and byte size.  Falls back to a linear scan of the first
    64 MiB when the standard partition bases miss.
    """
    for p in partitions:
        fh.seek(p + 32 * SECTOR)
        hdr = fh.read(28)
        if hdr[:20] == XDVDFS_MAGIC:
            root_sector, root_size = struct.unpack("<II", hdr[20:28])
            return p, root_sector, root_size
    fh.seek(0)
    buf = fh.read(0x4000000)
    idx = buf.find(XDVDFS_MAGIC)
    if idx < 0:
        raise ValueError("no XDVDFS volume descriptor found")
    base = idx & ~(SECTOR - 1)
    root_sector, root_size = struct.unpack("<II", buf[base + 20:base + 28])
    return max(base - 32 * SECTOR, 0), root_sector, root_size


def xdvdfs_walk(fh, part: int, root_sector: int, root_size: int) -> dict[str, tuple[int, int]]:
    """Walk an XDVDFS tree -> {path: (start_sector, size)}.

    Directory entries are a little-endian binary tree (left/right child word
    indices, 14-byte fixed head + name); a node with the 0x10 attribute bit is
    a subdirectory whose `sector/size` locates its own entry table.
    """
    files: dict[str, tuple[int, int]] = {}

    def read_sector(sector):
        fh.seek(part + sector * SECTOR)
        return fh.read(SECTOR)

    def walk(sector, size, path, depth=0):
        if depth > 10:
            return
        fh.seek(part + sector * SECTOR)
        d = fh.read(size)
        stack = [0]
        seen = set()
        while stack:
            idx = stack.pop()
            if idx in seen:
                continue
            seen.add(idx)
            off = idx * 4
            if off + 14 > len(d):
                continue
            left, right, s, n, attr, nl = struct.unpack("<HHIIBB", d[off:off + 14])
            name = d[off + 14:off + 14 + nl].decode("latin-1")
            if left not in (0, 0xFFFF):
                stack.append(left)
            if right not in (0, 0xFFFF):
                stack.append(right)
            full = f"{path}/{name}" if path else name
            if attr & 0x10:
                if n:
                    walk(s, n, full, depth + 1)
            else:
                files[full] = (s, n)

    walk(root_sector, root_size, "")
    return files


def parse_xex_header(blob: bytes) -> dict:
    """Decode a XEX2 executable's optional-header table.

    Optional headers are (u32 key, u32 value) pairs at 0x18..base_header_size.
    0x00040001 = entry point (RVA), 0x00040401 = title id, 0x00010100 = image
    base address.  Returns raw key/value pairs; not all keys are documented.
    """
    if blob[:4] != b"XEX2" or len(blob) < 8:
        raise ValueError("not a XEX2 image")
    hsize = struct.unpack("<I", blob[4:8])[0]
    out = {}
    off = 0x18
    while off + 8 <= hsize:
        key = struct.unpack("<I", blob[off:off + 4])[0]
        if key == 0:
            break
        out[key] = struct.unpack("<I", blob[off + 4:off + 8])[0]
        off += 8
    return out


def bf64_header(blob: bytes) -> dict:
    """Raw leading fields of a Ubisoft BF64 BigFile (semantics per ubisoft_bf64.bms).

    Only the words the community tooling names are captured; the tree-walk of the
    file/folder info tables is the analysis-stage opener, not this function.
    """
    if blob[:4] != b"BF64":
        raise ValueError("not a BF64 BigFile")
    v = struct.unpack("<I", blob[4:8])[0]
    words = struct.unpack("<11I", blob[8:8 + 44])
    # two u64 offsets follow the 11 u32 words (offsets 0x34 and 0x3c)
    file_off, folder_off = struct.unpack("<QQ", blob[8 + 44:8 + 44 + 16])
    return {
        "magic": "BF64",
        "version": v,
        "indices": words[0],
        "parameters": words[1],
        "files": words[2],
        "folders": words[3],
        "raw_words": list(words[4:]),
        "file_info_offset": file_off,
        "folder_info_offset": folder_off,
    }


def classify(blob: bytes) -> str | None:
    """Identify a container by its leading magic, else None."""
    for magic, label in CONTAINER_MAGICS.items():
        if blob[: len(magic)] == magic:
            return label
    return None


def inventory(path: str) -> dict:
    """Stage 1: exact build identity + XDVDFS container layout + format census."""
    from pathlib import Path

    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(path)

    iso_sha = hashlib.sha256(src.read_bytes()) if src.stat().st_size < 64 * 1024 * 1024 else None

    with open(path, "rb") as fh:
        part, root_sector, root_size = xdvdfs_locate(fh)
        files = xdvdfs_walk(fh, part, root_sector, root_size)

        def read(p, n=None):
            s, sz = files[p]
            fh.seek(part + s * SECTOR)
            return fh.read(sz if n is None else min(n, sz))

        exes = {}
        for p in files:
            if p.lower().endswith(".xex"):
                exes[p] = hashlib.sha256(read(p)).hexdigest()

        exts = Counter(p.rsplit(".", 1)[-1].lower() if "." in p else "(none)" for p in files)
        magics = {}
        for p in files:
            head = read(p, 8)
            label = classify(head)
            if label:
                magics[p] = label

    manifest = {
        "game": "Naruto - The Broken Bond",
        "platform": "xbox360",
        "source": {"path": path, "size": src.stat().st_size,
                   "sha256": iso_sha},  # full-hash runs out-of-band for large discs
        "disc": {"partition": part, "root_sector": root_sector, "root_size": root_size,
                 "file_count": len(files)},
        "executables": exes,
        "extensions": dict(exts),
        "container_magics": magics,
    }
    return manifest


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m gbox.naruto_bb_inventory <iso>")
    print(json.dumps(inventory(sys.argv[1]), indent=1))
