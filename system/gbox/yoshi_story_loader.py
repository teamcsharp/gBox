"""Yoshi's Story (USA, NYSE rev0) slot-loader facts derived from the owned ROM code.

Verified by disassembling the normalized z64 (sha256 e8a63388...0ce9). Main code:
ROM 0x1070 <-> VRAM 0x80000470.  These are code-derived facts, not a reader yet.
"""
from __future__ import annotations
import struct

MAIN_ROM, MAIN_VRAM, MAIN_END = 0x1070, 0x80000470, 0xB58B0
Z64_SHA256 = "e8a63388c38f8f0bea37e9b13a97f0898ac5496e08ca2028afb8db9a866e0ce9"

SLOT_LOADER = 0x80008C3C        # callers 0x800071a8, 0x80008978
RELOCATOR = 0x80007490          # only caller 0x80008c98; walks offset->pointer fixups
SLOT_TABLE = 0x800B4D10         # +0x180 = runtime pointer array of slot descriptors
DESC_SIZE_MASK = 0x00FFFFFF     # descriptor word0: size (low 24) | mode bits 27..26
UNKBIN_OFFSET_TABLE = 0xB58B4   # 61 ascending (0x20-step) file-relative offset pairs


def vram_to_rom(va: int) -> int:
    if not MAIN_VRAM <= va < MAIN_VRAM + 0x1000000:
        raise ValueError(hex(va))
    return va - MAIN_VRAM + MAIN_ROM


def word(rom: bytes, off: int) -> int:
    return struct.unpack(">I", rom[off:off + 4])[0]


def jal_callers(rom: bytes, target: int) -> list[int]:
    w = 0x0C000000 | ((target & 0x0FFFFFFF) >> 2)
    return [MAIN_VRAM + o - MAIN_ROM for o in range(MAIN_ROM, MAIN_END, 4) if word(rom, o) == w]


def descriptor_fields(w0: int) -> tuple[int, int]:
    """(mode, size) as decoded by the loader: mode=(w0<<4)>>30, size=w0&0xFFFFFF."""
    return ((w0 << 4) & 0xFFFFFFFF) >> 30, w0 & DESC_SIZE_MASK


def unkbin_offset_table(rom: bytes, n: int = 61) -> list[int]:
    return list(struct.unpack(f">{n * 2}I", rom[UNKBIN_OFFSET_TABLE:UNKBIN_OFFSET_TABLE + n * 8]))
