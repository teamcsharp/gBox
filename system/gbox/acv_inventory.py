"""Armored Core V (Xbox 360) inventory: XISO disc layout + FromSoftware BHD5 binder.

Verified against the owned build:
  collections/Microsoft XBOX 360/roms/Armored Core V.iso  (3,555,393,536 bytes)

Disc container is the extract-xiso ("XISO") format:
  - ISO9660 PVD ("CD001") at LBA 16 (offset 0x8000), but its root-dir record is
    zeroed; the real root directory is named by the Xbox media header.
  - "MICROSOFT*XBOX*MEDIA" header at LBA 32; root directory LBA at +0x14 and root
    directory size (bytes) at +0x18.  For ACV: root LBA 264, size 88.
  - Directory entry = 14-byte header + name, padded to a 4-byte boundary:
        u16 left, u16 right, u32 lba, u32 size, u8 attr, u8 namelen, name[namelen]
    attr & 0x10 => directory, attr & 0x20 => file.

Top-level files (24 files, 3 dirs):
  default.xex              LBA 265      23,248,896 B  XEX2 (sha256 818a8e22...)
  bind/dvdbnd5.bhd         LBA 12148       338,640 B  "BHD5" (sha256 7656d45f...)
  bind/dvdbnd.bdt          LBA 12314 3,298,094,700 B  binder payload
  bind/script.bhd          LBA 1623361      18,308 B  "BHF311G21X35" (sha256 c08a4254...)
  bind/script.bdt          LBA 1622712   1,328,198 B
  movie/jp/*.wmv           18 files (cutscenes)
  NxeArt                   LBA 11617    1,085,440 B  NXE art

Game data lives in the FromSoftware Binder (dvdbnd5.bhd index -> dvdbnd.bdt data).
BHD5 header: "BHD5" + 4 flag bytes + u32 bucketCount + u32 bucketOffsets[bucketCount].
File table (ACV) is 16-byte records: u32 hash, u32 size (BIG endian), u64 offset
(BIG endian; high 32 bits are 0 because the BDT is < 4 GiB).  Verified 19,747 file
records (file table at BHD offset 0x58a0), every offset inside the BDT, and the
records account for 3,298,094,684 bytes -- the BDT size minus 16 bytes of trailing
slack.  Sampled payload
magics are FromSoftware DCX (0x44435800), nested BND3 (0x424E4433), TPF textures and
"[PAT]" params -- the same stack as Dark Souls (FLVER models / DDS textures / Havok
animation behind DCX compression).  The 0x10..0x58a0 region of the BHD (low entropy)
is an undetermined directory/name structure, left for the analysis stage.

This module is read-only: it never writes to the disc or the binder.
"""

from __future__ import annotations

import struct

XISO_SECTOR = 2048
MEDIA_MAGIC = b"MICROSOFT*XBOX*MEDIA"
BHD5_MAGIC = b"BHD5"

# ACV constants (verified against the owned ISO).
ACV_DEFAULT_XEX_SHA256 = "818a8e2269437291bcf3b0de2e17a23782979766524144f20a689b8323750041"
ACV_DVDBND5_BHD_SHA256 = "7656d45f09b4ad43a3e16be81bfd621bba39cce187f85c9af954a62308dfee6e"


def parse_xiso_directory(reader, root_lba: int, root_size: int) -> list[dict]:
    """Return every file/dir entry in an XISO tree as a flat list of dicts.

    reader: callable(lba, nbytes) -> bytes.  Directory entries are the 14-byte
    header + name layout above, 4-byte aligned.  Stops at an empty name length.
    """
    out: list[dict] = []

    def walk(lba: int, size: int, path: str, depth: int):
        if depth > 16:
            return
        data = reader(lba, size)
        off = 0
        while off + 14 <= len(data) and off < size:
            left, right = struct.unpack_from("<HH", data, off)
            lba_, sz = struct.unpack_from("<II", data, off + 4)
            attr = data[off + 12]
            namelen = data[off + 13]
            if namelen == 0:
                break
            name = data[off + 14:off + 14 + namelen].decode("ascii", "replace")
            p = f"{path}/{name}" if path else name
            isdir = bool(attr & 0x10)
            out.append({"path": p, "lba": lba_, "size": sz,
                        "is_dir": isdir, "attr": attr,
                        "left": left, "right": right})
            if isdir and sz > 0:
                walk(lba_, sz, p, depth + 1)
            step = 14 + namelen
            off += (step + 3) & ~3

    walk(root_lba, root_size, "", 0)
    return out


def xiso_root(reader) -> tuple[int, int]:
    """Return (root_lba, root_size) from the XISO media header at LBA 32."""
    hdr = reader(32, 64)
    if hdr[:len(MEDIA_MAGIC)] != MEDIA_MAGIC:
        raise ValueError("not an XISO image (missing MICROSOFT*XBOX*MEDIA)")
    root_lba = struct.unpack_from("<I", hdr, 0x14)[0]
    root_size = struct.unpack_from("<I", hdr, 0x18)[0]
    return root_lba, root_size


def find_bhd5_file_table(bhd: bytes, bdt_size: int) -> tuple[int, int]:
    """Locate the 16-byte file-header run inside a BHD5 and return (offset, count).

    Heuristic: the header ends after bucketCount + its bucket offsets; the file
    table follows some undetermined low-entropy region.  We scan for a run of
    16-byte records where size is small, the 64-bit offset fits the BDT and its
    high 32 bits are zero -- the run that agrees with almost every record wins.
    """
    if bhd[:4] != BHD5_MAGIC:
        raise ValueError("not a BHD5 binder")
    best = (0, 0, 0.0)
    n = len(bhd)
    for start in range(0x10, min(n, 0x10000), 4):
        good = 0
        total = 0
        for off in range(start, n - 15, 16):
            size = struct.unpack_from(">I", bhd, off + 4)[0]
            foff = struct.unpack_from(">Q", bhd, off + 8)[0]
            total += 1
            if 0 < size < 0x10000000 and foff < bdt_size and (foff >> 32) == 0:
                good += 1
            if total >= 40:
                break
        if total and good / total > best[2]:
            best = (start, good, good / total)
    return best[0], best[1]


def parse_bhd5_files(bhd: bytes, bdt_size: int, table_off: int | None = None) -> list[dict]:
    """Parse BHD5 file records into [{"hash": hex, "size": int, "offset": int}]."""
    if table_off is None:
        table_off, _ = find_bhd5_file_table(bhd, bdt_size)
    out = []
    for off in range(table_off, len(bhd) - 15, 16):
        h = bhd[off:off + 4]
        size = struct.unpack_from(">I", bhd, off + 4)[0]
        foff = struct.unpack_from(">Q", bhd, off + 8)[0]
        out.append({"hash": h.hex(), "size": size, "offset": foff})
    return out
