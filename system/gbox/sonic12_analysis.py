"""Sonic 1 and 2 (Genesis hack, 2 MB) analysis helpers. No game data is stored here."""
from __future__ import annotations

import hashlib
from pathlib import Path

from gbox import genesis_nemesis as nem

ROM_SHA256 = "a755e0ae96df4b881f52e347ac450ce2207f8403667e06de5da0ef9fb499d99d"
ROM_SIZE = 2_097_152
ZIP_SHA256 = "49fccb41fef1a8f3faf981625258a0e426f4f153438774f9aebae27eb0a9bf30"
# Offsets verified: decode == clownnemesis-tool output. (offset: tile count)
VERIFIED_NEMESIS = {0x4B42: 10, 0xD49A: 64, 0x78AA2: 32, 0x7BEB4: 457}


def check_rom(rom: bytes) -> dict:
    """Identity + Genesis header check (header checksum is stale in this hack)."""
    computed = sum(int.from_bytes(rom[i:i + 2], "big") for i in range(0x200, len(rom) - 1, 2)) & 0xFFFF
    return {
        "sha256_ok": hashlib.sha256(rom).hexdigest() == ROM_SHA256,
        "size_ok": len(rom) == ROM_SIZE,
        "console": rom[0x100:0x110].decode("ascii", "replace").strip(),
        "header_checksum": int.from_bytes(rom[0x18E:0x190], "big"),
        "computed_checksum": computed,
    }


def decode_at(rom: bytes, offset: int) -> tuple[bytes, int]:
    """Decode the Nemesis stream at ROM offset -> (tile bytes, compressed size)."""
    return nem.decode_with_size(rom[offset:offset + 0x4000 * 4])


def probe(rom_path: str | Path, offset: int = 0xD49A, png_out: str | Path | None = None) -> dict:
    rom = Path(rom_path).read_bytes()
    tiles, size = decode_at(rom, offset)
    if png_out:
        Path(png_out).write_bytes(nem.tiles_to_png_bytes(tiles))
    return {"offset": offset, "tiles": len(tiles) // 32, "compressed_size": size,
            "tiles_sha256": hashlib.sha256(tiles).hexdigest()}
