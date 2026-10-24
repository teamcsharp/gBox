"""Native asset probes for Armored Core 4 (xbox360), read from the owned XDVDFS image.

Verified against the owned build (roms/Armored Core 4.iso, 6330384384 bytes,
XDVDFS container, 2048-byte sectors, little-endian directory entries):

  model/poly/m000/s000_000.rmb  (2332 bytes, sector 1199028)
  model/poly/m000/s900_000.rmb  (1176 bytes, sector 1199030)
      Big-endian u32 header: [0] = 1 (version), [4] = the member size (2332 /
      1176, equal to the size the directory reports), [0x4c] = 8 (name
      length), [0x50] = 17 (length of the "N:\AC4\data\model\" root prefix).
      The name is NUL terminated and the authoring path of the mesh source
      follows it, e.g. "N:\AC4\data\model\poly\m000\ap2\s000_000.ap2" (an
      .ap2 file).

  ane/ac/ac_4_n.anc            (23904 bytes, sector 6049)
      b"#ANIEDIT" at 0x20, member name "ac_4_n.ane" at 0x30, b"ANE" tag at 0x40.

These are the native target assets the inventory stage names.  The functions
here parse bytes only; the ISO plumbing stays in ac4_inventory.
"""
from __future__ import annotations

import hashlib
import re
import struct

SECTOR_SIZE = 2048
RMB_VERSION = 1
ANC_MAGIC = "#ANIEDIT"
_TRAILING_PRINTABLE = re.compile(rb"[\x20-\x7e]+$")


def sector_offset(sector: int) -> int:
    """Byte offset of an XDVDFS sector inside the image."""
    return int(sector) * SECTOR_SIZE


def _cstr(blob: bytes, start: int) -> str:
    end = blob.find(b"\x00", start)
    if end < 0:
        end = len(blob)
    return blob[start:end].decode("latin-1")


def parse_rmb_header(blob: bytes) -> dict:
    """Header of an AC4 .rmb mesh container.

    Big-endian u32 fields.  The name and the authoring path are located by
    structure (NUL terminated strings), not by a fixed offset, because the
    header fields before them shift between members.
    """
    if len(blob) < 0x58:
        raise ValueError("rmb blob too small: %d bytes" % len(blob))
    version, declared = struct.unpack_from(">2I", blob, 0)
    path = name = name_len = root_len = None
    path_at = blob.find(b"N:\\")
    if path_at > 1:
        path = _cstr(blob, path_at)
        end = path_at - 1                      # the NUL that ends the name
        head = blob[:end]
        m = _TRAILING_PRINTABLE.search(head)
        if m:
            name = m.group(0).decode("latin-1")
            name_at = end - len(name)
            if name_at >= 8:
                name_len = struct.unpack_from(">I", blob, name_at - 8)[0]
            if name_at >= 4:
                root_len = struct.unpack_from(">I", blob, name_at - 4)[0]
    return {"version": version, "declared_size": declared, "name": name,
            "name_len": name_len, "root_prefix_len": root_len, "path": path,
            "path_slashes": path.replace("\\", "/") if path else None}


def parse_anc_header(blob: bytes) -> dict:
    """Header of an AC4 .anc animation container."""
    if len(blob) < 0x44:
        raise ValueError("anc blob too small: %d bytes" % len(blob))
    return {"magic": blob[0x20:0x28].decode("latin-1"), "magic_offset": 0x20,
            "name": blob[0x30:0x40].split(b"\x00", 1)[0].decode("latin-1"),
            "tag": blob[0x40:0x43].decode("latin-1")}


def member_row(path: str, sector: int, size: int, blob: bytes | None = None) -> dict:
    """One manifest row for a member: location, size and optional digest."""
    row = {"path": path, "container": "XDVDFS", "sector": int(sector),
           "byte_offset": sector_offset(sector), "size": int(size)}
    if blob is not None:
        row["sha256"] = hashlib.sha256(blob).hexdigest()
    return row
