"""Make verified copies of built N64 images with stale header checksums.

Only recognized retail IPL3 algorithms and a complete checksum window are
supported. Size, bootability and game compatibility are separate properties:
no padding, CPU changes or gameplay acceptance are inferred from CRC values.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile

from .n64_rom import MAX_ROM_BYTES
from .romexport import N64_ORDER, n64_cic, n64_crc, n64_to_z64

CHECKSUM_END = 0x101000
CACHE_VERSION = "crc2"
MAX_CACHE_CONFLICTS = 16


class UnsupportedChecksum(ValueError):
    """The image may be legitimate, but this normalizer cannot verify its IPL3."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_bounded(path: Path, maximum=MAX_ROM_BYTES) -> bytes:
    # Bound the descriptor read itself, including growth after the size check.
    with Path(path).open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("N64 image is not a regular file within the byte limit")
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    if len(data) > maximum:
        raise ValueError("N64 image grew beyond the byte limit")
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or len(data) != before.st_size:
        raise ValueError("N64 image changed while being read")
    return data


def finalize_bytes(data: bytes) -> tuple[bytes, dict]:
    """Normalize byte order and repair CRC1/CRC2, preserving every payload byte.

    Explicit callers receive an error for unknown IPL3 or an incomplete CRC
    window; launch_image instead leaves those potentially valid images alone.
    """
    if not 0x40 <= len(data) <= MAX_ROM_BYTES:
        raise ValueError("N64 image outside supported header/byte limits")
    order = N64_ORDER.get(bytes(data[:4]))
    if order is None:
        raise ValueError("not an N64 ROM (unknown header magic)")
    if (order == "v64" and len(data) % 2) or (order == "n64" and len(data) % 4):
        raise ValueError("incomplete N64 byte-order unit")
    rom = n64_to_z64(data)
    if len(rom) < CHECKSUM_END:
        raise UnsupportedChecksum("incomplete retail IPL3 checksum window; image left unchanged")
    try:
        cic = n64_cic(rom)
    except ValueError as exc:
        raise UnsupportedChecksum(str(exc)) from exc
    old = struct.unpack_from(">II", rom, 0x10)
    new = n64_crc(rom, cic)
    out = rom[:0x10] + struct.pack(">II", *new) + rom[0x18:]
    return out, {"status": "normalized", "cic": cic, "size_before": len(data), "size": len(out),
                 "byte_order": order + " -> z64", "crc_before": "%08X %08X" % old,
                 "crc": "%08X %08X" % new, "crc_fixed": old != new, "padded": False,
                 "source_sha256": _sha(data), "sha256": _sha(out), "gameplay_verified": False}


def _publish_exclusive(dst: Path, data: bytes):
    """Publish complete verified bytes atomically, never replacing any destination.

    Same-directory hard-link publication supplies atomic no-replace semantics on
    local NTFS/POSIX filesystems. Unsupported filesystems fail explicitly.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".n64-crc-", suffix=".part", dir=dst.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if _read_bounded(temporary, len(data)) != data:
            raise OSError("N64 temporary output failed byte-exact readback")
        os.link(temporary, dst)  # Fails if a file, symlink or another writer already occupies dst.
    finally:
        temporary.unlink(missing_ok=True)


def finalize_file(src: Path, dst: Path) -> dict:
    """Write a verified, exclusive copy; originals and existing outputs are untouched."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("refusing to overwrite the original image")
    out, report = finalize_bytes(_read_bounded(src))
    _publish_exclusive(dst, out)
    if _read_bounded(dst, len(out)) != out:
        raise OSError("published N64 output failed byte-exact readback")
    return dict(report, path=str(dst))


def needs_finalize(data: bytes) -> bool:
    """True only for a stale checksum under a recognized IPL3 algorithm."""
    return finalize_bytes(data)[1]["crc_fixed"]


def _matches(path: Path, expected: bytes) -> bool:
    try:
        return not path.is_symlink() and _read_bounded(path, len(expected)) == expected
    except (OSError, ValueError):
        return False


def launch_image(image: Path) -> tuple[Path, dict | None]:
    """Use a content-addressed verified copy only when a known CRC is stale.

    Valid byte orders, arbitrary payload lengths and unknown/custom IPL3 are
    preserved. Cache integrity requires equality of the whole expected output,
    including bytes outside the CRC window. Conflicting cache entries are kept
    untouched; a bounded alternate slot allows automatic recovery.
    """
    image = Path(image)
    data = _read_bounded(image)
    try:
        out, report = finalize_bytes(data)
    except UnsupportedChecksum as exc:
        return image, {"status": "unverified", "reason": str(exc), "source_sha256": _sha(data),
                       "size": len(data), "crc_fixed": False, "gameplay_verified": False}
    if not report["crc_fixed"]:
        return image, None
    canonical = image.resolve()
    out_dir = canonical.parent.parent / ("." + canonical.parent.name + ".n64final")
    if out_dir.is_symlink():
        raise ValueError("refusing a redirected N64 normalization cache directory")
    for slot in range(MAX_CACHE_CONFLICTS):
        suffix = "" if not slot else "-" + str(slot)
        dst = out_dir / (CACHE_VERSION + "-" + report["source_sha256"] + suffix + ".z64")
        if _matches(dst, out):
            return dst, dict(report, cached=True, path=str(dst), cache_conflicts=slot)
        try:
            _publish_exclusive(dst, out)
        except FileExistsError:
            if _matches(dst, out):
                return dst, dict(report, cached=True, path=str(dst), cache_conflicts=slot)
            continue
        if not _matches(dst, out):
            raise OSError("published N64 cache failed byte-exact readback")
        return dst, dict(report, cached=False, path=str(dst), cache_conflicts=slot)
    raise ValueError("N64 normalization cache contains too many conflicting entries")
