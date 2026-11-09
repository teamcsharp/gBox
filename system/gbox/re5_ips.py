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

OFFSET = 0x4F824
ORIGINAL = 0x11100284       # add w4, w20, #0x400
REBIND = 0x110C0284         # add w4, w20, #0x300


def make_ips(*, noop: bool = False) -> bytes:
    """IPS32 patch for the class-hash immediate; `noop` writes the original bytes back."""
    data = struct.pack("<I", ORIGINAL if noop else REBIND)
    return b"IPS32" + struct.pack(">IH", OFFSET, len(data)) + data + b"EEOF"


def apply_patch(blob: bytearray, *, noop: bool = False) -> bytearray:
    """Apply the same 4-byte change directly to an NSO/ELF image (for tests or a full main build)."""
    blob[OFFSET:OFFSET + 4] = struct.pack("<I", ORIGINAL if noop else REBIND)
    return blob


def assert_original(blob: bytes) -> None:
    got = struct.unpack_from("<I", blob, OFFSET)[0]
    if got != ORIGINAL:
        raise ValueError(f"offset {OFFSET:#x} holds {got:#010x}, expected the uEm11 immediate {ORIGINAL:#010x}")
