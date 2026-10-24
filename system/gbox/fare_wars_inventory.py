"""Crazy Taxi: Fare Wars (USA) (PSP) owned-build inventory -- request #2453, game_id 30beeba223eaf3d9.

Stage 1 (inventory) evidence for the exact owned build, all read-only:

  * the owned source is the CISO/CSO UMD image in the operator's HyperSpin PSP collection
    (the generic container lister cannot open .cso, which is why earlier runs called the
    build "missing" -- it is not missing, it is a CISO image);
  * the ISO9660 member manifest of that image: member path, byte offset, size and the
    sha256 of the member bytes (counted from the real member table, never from filenames);
  * the PSP revision fields from PARAM.SFO (TITLE, TITLE_ID, VERSION, APP_VER);
  * one identified native target asset: the Hitmaker AFS archive that the next stage
    (analysis) will prove to hold the character geometry, named by exact member path,
    offset, size and sha256.

The owned image is never modified: this module only reads it.
"""
from __future__ import annotations

import functools
import hashlib
import struct
from pathlib import Path

from .cso import CSO
from .romexport import iso_files

OWNED_LIBRARY = "hyperspin"
OWNED_REL_PATH = "collections/Sony PlayStation Portable/roms/Crazy Taxi - Fare Wars (USA).cso"
OWNED_CSO_SHA256 = "54589cc910cb8e5b0a7d8ec79ba6e8fbf5051459f0507506ccd06beb6151c187"
OWNED_CSO_SIZE = 321343675
ISO_MEMBER_COUNT = 364

# Native target asset candidates: the Hitmaker AFS archives shipped for the two included
# games. Which one carries the character geometry is analysis-stage work; the inventory
# identifies them by exact path/offset/size/sha256 so the analysis has a fixed target.
TARGET_ASSET_CANDIDATES = (
    "PSP_GAME/USRDIR/DATA/CT2/BINC1.AFS",
    "PSP_GAME/USRDIR/DATA/CT2/BINC2.AFS",
    "PSP_GAME/USRDIR/DATA/CT2/BINC3.AFS",
    "PSP_GAME/USRDIR/DATA/CT1/BINC1.AFS",
    "PSP_GAME/USRDIR/DATA/CT1/BINC2.AFS",
    "PSP_GAME/USRDIR/DATA/CT1/BINC3.AFS",
)
PRIMARY_TARGET = "PSP_GAME/USRDIR/DATA/CT2/BINC1.AFS"

REQUIRED_MEMBERS = (
    "PSP_GAME/PARAM.SFO",
    "PSP_GAME/SYSDIR/BOOT.BIN",
    "PSP_GAME/SYSDIR/EBOOT.BIN",
    "PSP_GAME/USRDIR/DATA/CT1.PRX",
    "PSP_GAME/USRDIR/DATA/CT2.PRX",
    "PSP_GAME/USRDIR/DATA/CT1/COURSE1.BIN.LZSS",
    "PSP_GAME/USRDIR/DATA/CT2/COURSE1.BIN.LZSS",
    PRIMARY_TARGET,
)


def stream_sha256(path) -> str:
    """sha256 of a file, streamed (never a reference hash copied from elsewhere)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@functools.lru_cache(maxsize=4)
def manifest(cso_path: str) -> tuple:
    """((member, offset, size, sha256), ...) for every ISO9660 member of the owned image."""
    rows = []
    with CSO(cso_path) as c:
        files = iso_files(c)
        for name, rec in sorted(files.items()):
            off, size = rec[1] * 2048, rec[2]
            c.seek(off)
            h = hashlib.sha256()
            left = size
            while left > 0:
                chunk = c.read(min(left, 1 << 20))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
            rows.append((name, off, size, h.hexdigest()))
    return tuple(rows)


@functools.lru_cache(maxsize=8)
def read_member(cso_path: str, name: str) -> bytes:
    """Raw bytes of one ISO9660 member of the owned image."""
    with CSO(cso_path) as c:
        files = iso_files(c)
        rec = files[name]
        c.seek(rec[1] * 2048)  # iso_files -> (dir-record offset, extent LBA, size)
        return c.read(rec[2])


def sfo_header(data: bytes) -> dict:
    """The five u32 fields of a PSP PARAM.SFO header, as read (no interpretation)."""
    if len(data) < 20:
        raise ValueError("PARAM.SFO shorter than its 20-byte header")
    magic, version, key_start, data_start, count = struct.unpack_from("<IIIII", data, 0)
    return {"magic": data[:4].hex(), "version": version, "key_table_start": key_start,
            "data_table_start": data_start, "index_count": count}


def sfo_entries(data: bytes) -> dict:
    """PARAM.SFO key -> value, per the layout verified against the owned file.

    Header (20 bytes): b"\\0PSF", version, key_table_start, data_table_start, count.
    Index entries start at 0x14, 16 bytes each: key_off u16, data_fmt u16, data_len u32,
    data_max_len u32, data_off u32. fmt 0x0404 = u32, 0x0204 = utf8 string (NUL padded).
    """
    hdr = sfo_header(data)
    if data[:4] != b"\0PSF":
        raise ValueError("not a PARAM.SFO (missing \\0PSF magic)")
    key_start, data_start, count = hdr["key_table_start"], hdr["data_table_start"], hdr["index_count"]
    if 20 + 16 * count > key_start or key_start > data_start or data_start > len(data):
        raise ValueError("inconsistent PARAM.SFO table offsets")
    out = {}
    for i in range(count):
        key_off, fmt, length, _maxlen, doff = struct.unpack_from("<HHIII", data, 20 + i * 16)
        kstart = key_start + key_off
        key_end = data.find(b"\0", kstart)
        if key_end < 0:
            raise ValueError("unterminated key")
        key = data[kstart:key_end].decode("ascii", "replace")
        start = data_start + doff
        if start + length > len(data):
            raise ValueError("param out of range")
        raw = data[start:start + length]
        if fmt == 0x0404 and length == 4:
            out[key] = struct.unpack("<I", raw)[0]
        else:
            out[key] = raw.rstrip(b"\0").decode("utf-8", "replace")
    out["_header"] = hdr
    return out


def container_probe(data: bytes) -> dict:
    """Uninterpreted evidence about a container: size, first bytes and a magic guess.

    The AFS member layout is deliberately NOT guessed here; the analysis stage proves it.
    """
    head = data[:64]
    magic = head[:4]
    return {"size": len(data), "head_hex": head[:32].hex(), "magic_ascii": magic.decode("latin-1"),
            "magic_hex": magic.hex()}


def inventory(cso_path: str) -> dict:
    """The owned-build manifest: source identity, counted members, revision, target asset."""
    rows = manifest(cso_path)
    by_name = {r[0]: r for r in rows}
    sfo = sfo_entries(read_member(cso_path, "PSP_GAME/PARAM.SFO"))
    targets = {}
    for name in TARGET_ASSET_CANDIDATES:
        if name in by_name:
            _n, off, size, sha = by_name[name]
            targets[name] = {"offset": off, "size": size, "sha256": sha,
                             "container": container_probe(read_member(cso_path, name))}
    primary = targets.get(PRIMARY_TARGET)
    return {
        "game_id": "30beeba223eaf3d9",
        "request_id": "1a58f9b3a95e45e7",
        "title": "Crazy Taxi - Fare Wars (USA)",
        "platform": "psp",
        "library": OWNED_LIBRARY,
        "rel_path": OWNED_REL_PATH,
        "source_sha256": stream_sha256(cso_path),
        "source_size": Path(cso_path).stat().st_size,
        "container": "CISO/CSO v1 (block 2048), ISO9660 inside",
        "byte_order": "little-endian",
        "iso_member_count": len(rows),
        "required_members_present": [m for m in REQUIRED_MEMBERS if m in by_name],
        "required_members_missing": [m for m in REQUIRED_MEMBERS if m not in by_name],
        "revision": {k: v for k, v in sfo.items() if not k.startswith("_")},
        "sfo_header": sfo.get("_header"),
        "target_asset": {"member": PRIMARY_TARGET, **(primary or {})},
        "target_asset_candidates": targets,
        "members": [{"member": n, "offset": o, "size": s, "sha256": h} for n, o, s, h in rows],
    }
