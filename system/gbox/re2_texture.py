"""RE2 N64 (USA Rev 1) character texture asset container (magic 0xBE1E).

Proven (550/550 assets in directory range 5922-6471 decode and satisfy it):
  0x00 u16 magic = 0xBE1E
  0x02 u16 f       (unresolved; 16..128, not a size -> hypothesis only)
  0x04 u16 width
  0x06 u16 height
  0x08 u16 mode    (1 = 16-entry palette, 2 = 256-entry palette, 7/8 variants)
  0x0A u16 ncolors (16 or 256; always 16 for modes 1/7, 256 for 2/8)
  0x0C u32 reserved (always 0)
  0x10 palette: ncolors * u16 big-endian (RGBA5551 — hypothesis, plausible ramps)
  ....  pixels: width*height bytes (one byte per pixel)
  total length == 16 + 2*ncolors + width*height exactly.

Hypotheses (not yet verified against the loader): mode 2 pixels are CI8
indices into the RGBA5551 palette. Mode 1 bytes exceed 15 (nibble pairs),
so they are NOT plain indices into the 16-entry palette; likely 4+4 bit
(e.g. IA44 / palette+intensity). The loader in overlay 1 is not yet traced.
"""
from __future__ import annotations

import dataclasses
import struct
from pathlib import Path
from typing import Any

from gbox import re2_inventory as ri

TEXTURE_MAGIC = 0xBE1E
TEXTURE_HEADER_SIZE = 16
TEXTURE_ASSET_RANGE = (5922, 6471)


@dataclasses.dataclass
class TextureAsset:
    asset_id: int
    field_02: int
    width: int
    height: int
    mode: int
    ncolors: int
    palette: bytes
    pixels: bytes
    valid: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id, "field_02": self.field_02,
            "width": self.width, "height": self.height, "mode": self.mode,
            "ncolors": self.ncolors, "pixel_bytes": len(self.pixels),
            "valid": self.valid, "notes": self.notes,
        }


def parse_texture_asset(asset_id: int, raw: bytes) -> TextureAsset:
    notes: list[str] = []
    if len(raw) < TEXTURE_HEADER_SIZE:
        return TextureAsset(asset_id, 0, 0, 0, 0, 0, b"", b"", False, ["too short"])
    magic, f, w, h, mode, ncol, res = struct.unpack(">HHHHHHI", raw[:16])
    if magic != TEXTURE_MAGIC:
        notes.append(f"bad magic 0x{magic:04x}")
    if res != 0:
        notes.append("reserved field nonzero")
    if ncol not in (16, 256):
        notes.append(f"unexpected ncolors {ncol}")
    expect = TEXTURE_HEADER_SIZE + 2 * ncol + w * h
    if expect != len(raw):
        notes.append(f"length {len(raw)} != expected {expect}")
    pal = raw[16:16 + 2 * ncol]
    pix = raw[16 + 2 * ncol:]
    return TextureAsset(asset_id, f, w, h, mode, ncol, pal, pix, not notes, notes)


def build_texture_asset(t: TextureAsset) -> bytes:
    """Re-serialize; byte-identical to the source for every owned asset."""
    return (struct.pack(">HHHHHHI", TEXTURE_MAGIC, t.field_02, t.width, t.height,
                        t.mode, t.ncolors, 0) + t.palette + t.pixels)


def rgba5551_to_rgba8(v: int) -> tuple[int, int, int, int]:
    return ((v >> 11 & 31) * 255 // 31, (v >> 6 & 31) * 255 // 31,
            (v >> 1 & 31) * 255 // 31, 255 if v & 1 else 0)


def probe_all(rom_path: Path) -> dict[str, Any]:
    rom, _, _ = ri.load_rom(rom_path)
    directory = ri.read_asset_directory(rom, ri.read_overlays(rom))
    lo, hi = TEXTURE_ASSET_RANGE
    total = valid = roundtrip = 0
    shapes: dict[str, int] = {}
    bad: list[int] = []
    for e in directory.entries:
        if not lo <= e.index <= hi:
            continue
        raw = e.decode(rom, directory.base)
        if raw is None:
            bad.append(e.index)
            continue
        t = parse_texture_asset(e.index, raw)
        total += 1
        valid += t.valid
        roundtrip += t.valid and build_texture_asset(t) == raw
        k = f"{t.width}x{t.height}/mode{t.mode}/{t.ncolors}c"
        shapes[k] = shapes.get(k, 0) + 1
        if not t.valid:
            bad.append(e.index)
    return {"range": [lo, hi], "total": total, "valid": valid,
            "roundtrip_identical": roundtrip, "shapes": shapes, "bad": bad}


if __name__ == "__main__":
    import json, sys
    print(json.dumps(probe_all(Path(sys.argv[1])), indent=2))
