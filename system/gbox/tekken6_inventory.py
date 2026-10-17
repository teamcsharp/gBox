"""Tekken 6 (Xbox 360, Namco) disc inventory.

Owned-build identity + container layout for the "Namco Tekken 6 / TTT2 family"
engine. This module is read-only: it never modifies the source ISO. It resolves
the XDVDFS file table, hashes the boot XEX, parses the DINF_300.BIN master
directory, and classifies every DATA3XX.BIN container by its header magic.

Findings this module encodes (verified against the owned ISO, see
tests/test_tekken6_inventory.py):

  * Platform is confirmed Xbox 360 XDVDFS (boot `Default.xex`, XEX2 magic
    `b"XEX2"`), NOT original Xbox (no `default.xbe`), so gbox.xbox_disc does
    not apply here.
  * The disc holds exactly 43 top-level files: `Default.xex`, `DINF_300.BIN`,
    `nxeart`, and 20 pairs `DATA301..DATA320` (`.BIN` + `.IDX`).
  * DATA301..DATA313 are Namco packs with big-endian magic `0F F5 12 ED`
    (`0x0FF512ED`) - the same pack magic Tekken Tag Tournament 2 uses, so the
    two titles share the "Tekken 6 / TTT2" asset-pack family.
  * DATA314.BIN starts `PAC\\x01` (Namco "PAC" packaged audio/voice).
  * DATA315..DATA320 start with the ASF header GUID
    `3026b2758e66cf11a6d900aa0062ce6c` and embed "Windows Media Audio 10
    Professional" - WMA Pro music/movie streams.
  * Every `DATA3XX.BIN` is paired with a `DATA3XX.IDX` whose size is a multiple
    of 8 bytes (8-byte records: a u32 key/index and a u32 value, often a size;
    `0xFFFFFFFF` marks empty slots). Decoding the IDX -> pack-offset mapping is
    the analysis stage, not this inventory.

The full-image sha256 is deliberately NOT computed here (a 7 GB read); callers
that need the authoritative source hash should sha256 the ISO separately and
pass it to `record_game_work` as `source_sha256`.
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

XDVDFS_MAGIC = b"MICROSOFT*XBOX*MEDIA"
XDVDFS_BASES = (0, 0x0FD90000, 0x02080000, 0x18300000)  # plain / XGD3 / XGD2 / XGD1
SECTOR = 2048

PACK_MAGIC_BYTES = b"\x0f\xf5\x12\xed"   # 0x0FF512ED big-endian
PACK_MAGIC = 0x0FF512ED
PAC_MAGIC = b"PAC\x01"
ASF_GUID = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")

DEFAULT_ISO = Path("/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Tekken 6.iso")


def _read(stream, at: int, size: int) -> bytes:
    stream.seek(at)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"short read at {at}: wanted {size}, got {len(data)}")
    return data


def xdvdfs_files(path: str | Path) -> dict[str, tuple[int, int]]:
    """Walk the XDVDFS volume; returns {logical path: (absolute image sector, size)}.

    Mirrors the read-only walk in gbox.re6.XDVD but is self-contained so the
    inventory has no dependency on the RE6 module.
    """
    path = str(path)
    with open(path, "rb") as stream:
        for base in XDVDFS_BASES:
            stream.seek(base + 32 * SECTOR)
            block = stream.read(28)
            if len(block) == 28 and block[:20] == XDVDFS_MAGIC:
                root_sector, root_size = struct.unpack("<II", block[20:28])
                part = base
                break
        else:
            raise ValueError(f"{path}: not an Xbox disc image (no XDVDFS volume)")

        files: dict[str, tuple[int, int]] = {}
        stack: list[tuple[int, int, str]] = [(root_sector, root_size, "")]
        visited_dirs = set()
        while stack:
            sector, size, prefix = stack.pop()
            if (sector, size) in visited_dirs:
                raise ValueError("cyclic or repeated XDVDFS directory")
            visited_dirs.add((sector, size))
            directory = _read(stream, part + sector * SECTOR, size)
            pending = [0]
            seen: set[int] = set()
            while pending:
                index = pending.pop()
                if index in seen:
                    continue
                seen.add(index)
                offset = index * 4
                if offset + 14 > len(directory):
                    continue
                left, right, child_sector, child_size, attr, name_len = struct.unpack(
                    "<HHIIBB", directory[offset:offset + 14]
                )
                if offset + 14 + name_len > len(directory):
                    raise ValueError("truncated XDVDFS filename")
                name = directory[offset + 14:offset + 14 + name_len].decode("latin-1")
                if left not in (0, 0xFFFF):
                    pending.append(left)
                if right not in (0, 0xFFFF):
                    pending.append(right)
                full = f"{prefix}/{name}" if prefix else name
                if attr & 0x10:  # directory
                    if child_size:
                        stack.append((child_sector, child_size, full))
                else:
                    files[full] = (part // SECTOR + child_sector, child_size)
        return files


def classify(header: bytes) -> str:
    if header[:4] == PACK_MAGIC_BYTES:
        return "pack"          # Namco 0x0FF512ED asset pack
    if header[:4] == PAC_MAGIC:
        return "pac"           # Namco PAC packaged audio
    if header[:16] == ASF_GUID:
        return "asf"           # ASF / WMA Pro stream
    if header[:4] == b"XEX2":
        return "xex"
    if header[:4] == b"DINF":
        return "dinf"
    return "unknown"


def dinf_info(path: str | Path, sector: int, size: int) -> dict:
    """Parse the DINF_300.BIN master directory just enough for identity.

    The full variable-length record layout is not decoded (analysis stage);
    this extracts the declared data-file count, the build root, and the build
    date stamp, and cross-checks them against the XDVDFS listing.
    """
    with open(str(path), "rb") as stream:
        data = _read(stream, sector * SECTOR, size)
    if data[:4] != b"DINF":
        raise ValueError("DINF_300.BIN has no DINF magic")
    count = struct.unpack(">I", data[0x0C:0x10])[0] if len(data) >= 0x10 else None
    text = data.decode("latin-1", "replace")
    data_names = sorted(set(re.findall(r"DATA3\d\d\.(?:BIN|IDX)", text)))
    roots = sorted(set(re.findall(r"[a-zA-Z0-9_/]+/x360/", text)))
    dates = sorted(set(re.findall(r"20\d{6}", text)))
    return {
        "count": count,
        "data_names": data_names,
        "build_roots": roots,
        "build_dates": dates,
    }


def idx_records(path: str | Path, sector: int, size: int) -> list[tuple[int, int]]:
    """Decode a DATA3XX.IDX as 8-byte big-endian (key, value) records."""
    if size % 8:
        raise ValueError(f"IDX size {size} is not a multiple of 8")
    with open(str(path), "rb") as stream:
        data = _read(stream, sector * SECTOR, size)
    return [struct.unpack(">II", data[i:i + 8]) for i in range(0, size, 8)]


def inventory(path: str | Path = DEFAULT_ISO) -> dict:
    path = str(path)
    files = xdvdfs_files(path)
    lower = {name.casefold(): name for name in files}

    boot = lower.get("default.xex")
    if boot is None:
        raise ValueError("disc has no Default.xex")
    boot_sector, boot_size = files[boot]
    with open(path, "rb") as stream:
        boot_header = _read(stream, boot_sector * SECTOR, 16)
        boot_bytes = _read(stream, boot_sector * SECTOR, boot_size)
    if classify(boot_header) != "xex":
        raise ValueError(f"boot file {boot} is not a XEX2 executable")

    dinf = lower.get("dinf_300.bin")
    dinf_info_ = None
    if dinf is not None:
        dinf_sector, dinf_size = files[dinf]
        dinf_info_ = dinf_info(path, dinf_sector, dinf_size)

    containers = []
    idx_summary = []
    with open(path, "rb") as stream:
        for name in sorted(files):
            upper = name.upper()
            if upper.startswith("DATA") and upper.endswith(".BIN"):
                sector, size = files[name]
                header = _read(stream, sector * SECTOR, min(size, 16))
                kind = classify(header)
                magic = header[:4].hex()
                containers.append({"path": name, "sector": sector, "size": size, "kind": kind, "magic": magic})
            elif upper.startswith("DATA") and upper.endswith(".IDX"):
                sector, size = files[name]
                records = idx_records(path, sector, size)
                empties = sum(1 for _k, v in records if v == 0xFFFFFFFF)
                idx_summary.append({"path": name, "sector": sector, "size": size,
                                    "records": len(records), "empty_slots": empties})

    return {
        "game": "Tekken 6",
        "platform": "xbox360",
        "source_path": path,
        "file_count": len(files),
        "boot": {"path": boot, "sha256": hashlib.sha256(boot_bytes).hexdigest(),
                 "size": boot_size, "format": "xex2"},
        "dinf": dinf_info_,
        "containers": containers,
        "indexes": idx_summary,
        "pack_magic": "0x0FF512ED",
        "engine": "Namco (Tekken 6 / TTT2 family)",
    }
