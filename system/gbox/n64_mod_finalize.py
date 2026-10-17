"""Finalize a written N64 mod image so IPL3 accepts it (#2366).

goldeneye rom_relayout grows the ROM (e.g. 12 MiB + 1996 bytes) and shifts data inside the
0x1000..0x101000 window the CIC boot code checksums, but left the header CRC pair stale
("cic_boot_checksum_patched": false). IPL3 then spins forever and RetroArch reports
"content not running" right after "Init new dynarec". This pads the image to the next
power-of-two cart size with 0xFF and recomputes CRC1/CRC2 via gbox.romexport.n64_crc.
"""
from __future__ import annotations

import struct
from pathlib import Path

from .romexport import n64_cic, n64_crc, n64_to_z64

PAD_BYTE = 0xFF
MIN_CART = 4 * 1024 * 1024
MAX_CART = 64 * 1024 * 1024


def cart_size(n: int) -> int:
    size = MIN_CART
    while size < n:
        size *= 2
    if size > MAX_CART:
        raise ValueError(f"N64 image of {n} bytes exceeds {MAX_CART} bytes")
    return size


def finalize_bytes(data: bytes) -> tuple[bytes, dict]:
    rom = bytearray(n64_to_z64(data))
    before_len = len(rom)
    target = cart_size(before_len)
    rom += bytes([PAD_BYTE]) * (target - before_len)
    cic = n64_cic(rom)
    old = struct.unpack_from(">II", rom, 0x10)
    new = n64_crc(bytes(rom), cic)
    struct.pack_into(">II", rom, 0x10, *new)
    return bytes(rom), {"cic": cic, "size_before": before_len, "size": target,
                        "crc_before": "%08X %08X" % old, "crc": "%08X %08X" % new,
                        "crc_fixed": tuple(old) != tuple(new), "padded": target != before_len}


def finalize_file(src: Path, dst: Path) -> dict:
    """Write a finalized copy; never edits src in place (preserve originals)."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ValueError("refusing to overwrite the original image")
    out, report = finalize_bytes(src.read_bytes())
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(out)
    return report


def needs_finalize(data: bytes) -> bool:
    """True when a written N64 image would hang in IPL3: odd cart size or stale header CRC."""
    rom = n64_to_z64(data)
    if len(rom) < 0x101000 or len(rom) % 0x100000:     # stock 12 MiB carts are fine; 12 MiB + 1996 is not
        return True
    return tuple(struct.unpack_from(">II", rom, 0x10)) != tuple(n64_crc(rom, n64_cic(rom)))


def launch_image(image: Path) -> tuple[Path, dict | None]:
    """Launch-side guard for built N64 mods (#2366).

    Returns ``(path, report)``. A valid image is returned unchanged (report None). A stale one is
    finalized into a hidden sibling folder beside the mod folder (not inside it: the mod folder's
    file list is its manifest), keyed by the source size+mtime so it is rebuilt only when the mod
    changes. The built mod itself is never edited.
    """
    image = Path(image)
    data = image.read_bytes()
    if not needs_finalize(data):
        return image, None
    st = image.stat()
    out_dir = image.parent.parent / f".{image.parent.name}.n64final"
    dst = out_dir / f"{st.st_size}-{st.st_mtime_ns}-{image.stem}.z64"
    if dst.is_file() and not needs_finalize(dst.read_bytes()):
        return dst, {"cached": True, "path": str(dst)}
    out, report = finalize_bytes(data)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    tmp.write_bytes(out)
    tmp.replace(dst)
    report["path"] = str(dst)
    return dst, report
