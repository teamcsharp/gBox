"""IPS32 patches for RE5 Switch's main executable, delivered as `exefs/main.ips`.

Measured on the Switch main (module offset 0x4f724, Ghidra 0x0014f724):

    add w4, w20, #0x400     ; 0x3000d00 + 0x400 = uEm11 hash 0x3001100
    ->
    add w4, w20, #0x300     ; 0x3000d00 + 0x300 = uEm10 hash 0x3001000

A replaced `exefs/main` file is rejected by the emulator even when byte-identical (Switch "Launching..." splash), while
IPS patches are applied. Use this patch with `uEm11.arc` replaced by a uEm10 archive to make the camera-visible enemy
load the uEm10 class.
"""
from __future__ import annotations

import struct
import hashlib

OFFSET = 0x4F824
ORIGINAL = 0x11100284       # add w4, w20, #0x400
REBIND = 0x110C0284         # add w4, w20, #0x300
TITLE_ID = "010018100CD46000"
ARCHIVE_PATH = "romfs/nativeNXx64/ImgNX/Archive/uEm11.arc"


def make_ips(*, noop: bool = False, main: bytes | None = None) -> bytes:
    """IPS32 patch for the class-hash immediate; `noop` writes the original bytes back."""
    if main is not None:
        assert_supported_main(main)
    data = struct.pack("<I", ORIGINAL if noop else REBIND)
    return b"IPS32" + struct.pack(">IH", OFFSET, len(data)) + data + b"EEOF"


def apply_patch(blob: bytearray, *, noop: bool = False) -> bytearray:
    """Patch the measured, uncompressed NSO in place; ELF offsets are not interchangeable."""
    assert_supported_main(blob)
    blob[OFFSET:OFFSET + 4] = struct.pack("<I", ORIGINAL if noop else REBIND)
    return blob


def assert_original(blob: bytes) -> None:
    if len(blob) < OFFSET + 4:
        raise ValueError(f"main is too short for the uEm11 immediate at {OFFSET:#x}")
    got = struct.unpack_from("<I", blob, OFFSET)[0]
    if got != ORIGINAL:
        raise ValueError(f"offset {OFFSET:#x} holds {got:#010x}, expected the uEm11 immediate {ORIGINAL:#010x}")


def assert_supported_main(blob: bytes) -> None:
    """Accept only the measured build's expanded NSO text at the original IPS location."""
    from .re_switch import RE5_MAIN_BUILD_ID
    if len(blob) < 0x100 or blob[:4] != b"NSO0":
        raise ValueError("the class rebind requires an existing decompressed NSO main.bin, not an ELF or raw image")
    build_id = bytes.fromhex(RE5_MAIN_BUILD_ID)
    if blob[0x40:0x40 + len(build_id)] != build_id:
        raise ValueError(f"the class rebind is only measured for RE5 main build {RE5_MAIN_BUILD_ID}")
    flags = struct.unpack_from("<I", blob, 0x0C)[0]
    text_offset, memory_offset, text_size = struct.unpack_from("<3I", blob, 0x10)
    canonical = not flags & 1 and text_offset == 0x100 and memory_offset == 0
    if not canonical:
        # Eden's existing expanded NSO dumps retain the original compressed offsets/flags. Verify the actual expanded
        # segment bytes against every original NSO SHA256, and require the exact mapped-image + BSS allocation.
        segments = [struct.unpack_from("<3I", blob, at) for at in (0x10, 0x20, 0x30)]
        bss = struct.unpack_from("<I", blob, 0x3c)[0]
        expected_size = 0x100 + segments[2][1] + segments[2][2] + bss
        valid = flags & 0x38 == 0x38 and memory_offset == 0 and len(blob) == expected_size
        last_end = 0x100
        for index, (_, memory, size) in enumerate(segments):
            start, end = 0x100 + memory, 0x100 + memory + size
            valid &= size > 0 and last_end <= start < end <= len(blob)
            valid &= hashlib.sha256(blob[start:end]).digest() == blob[0xa0 + index * 32:0xc0 + index * 32]
            last_end = end
        if not valid:
            raise ValueError("main.bin is neither the uncompressed NSO layout nor a verified expanded Eden NSO dump")
    if OFFSET + 4 > 0x100 + text_size:
        raise ValueError("the patch offset is outside the NSO text segment")
    assert_original(blob)


def rebind_changes(archive: bytes, *, main: bytes | None = None) -> dict:
    """One overlay edit containing both halves of the measured uEm10 -> uEm11 rebind.

    The caller supplies the uEm10 archive (stock or authored), never a replacement main executable. The optional main
    preflight is for callers with extracted ExeFS bytes. This offset is specific to the measured RE5 Switch release.
    """
    from . import mt_arc
    mt_arc.parse(archive)
    return {ARCHIVE_PATH: {"bytes": bytes(archive)}, "exefs/main.ips": {"bytes": make_ips(main=main)}}
