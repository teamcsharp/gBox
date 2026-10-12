#!/usr/bin/env python3
"""Nemesis format probe for Sonic 1 and 2 (Genesis).

Uses the bit-exact clownnemesis decoder to extract a Nemesis-compressed art
stream from the owned ROM, decodes it to 4bpp Genesis tiles, and writes a PNG
sheet so the art can be visually inspected before any re-encoder work.

Dependencies:
    - Pillow (pip install Pillow)
    - clownnemesis-tool on PATH or in the same directory as this script
      (build from https://github.com/Clownacy/clownnemesis)

Usage:
    python3 nemesis_probe.py "Sonic 1 and 2.bin" --offset 0xd49a --out tiles.png
"""
from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore


def find_clownnemesis() -> str:
    """Locate the clownnemesis-tool executable."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "clownnemesis-tool",
        here / "clownnemesis" / "build" / "clownnemesis-tool",
        Path("clownnemesis-tool"),
    ]
    for c in candidates:
        if c.exists() and (c.stat().st_mode & 0o111):
            return str(c)
    found = shutil.which("clownnemesis-tool")
    if found:
        return found
    raise FileNotFoundError(
        "clownnemesis-tool not found. Build it from https://github.com/Clownacy/clownnemesis"
    )


def decode_with_clownnemesis(data: bytes, tool: Optional[str] = None) -> bytes:
    """Decode a Nemesis byte blob using the external clownnemesis tool."""
    if tool is None:
        tool = find_clownnemesis()
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in.nem"
        out = Path(td) / "out.bin"
        inp.write_bytes(data)
        result = subprocess.run(
            [tool, "-d", str(inp), str(out)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise NemesisProbeError(
                f"clownnemesis-tool failed ({result.returncode}): {result.stderr}"
            )
        return out.read_bytes()


def scan_nemesis_streams(
    rom: bytes,
    tool: Optional[str] = None,
    max_results: int = 50,
    min_tiles: int = 4,
    max_tiles: int = 2048,
    chunk_size: int = 0x2000,
) -> list[tuple[int, int, bool, int]]:
    """Scan a ROM for word-aligned Nemesis streams that decode successfully."""
    results: list[tuple[int, int, bool, int]] = []
    for off in range(0, len(rom) - 2, 2):
        header = struct.unpack(">H", rom[off : off + 2])[0]
        xor_mode = bool(header & 0x8000)
        tile_count = header & 0x7FFF
        if not (min_tiles <= tile_count <= max_tiles):
            continue
        try:
            data = rom[off : off + chunk_size]
            out = decode_with_clownnemesis(data, tool=tool)
            if len(out) == tile_count * 32:
                results.append((off, len(data), xor_mode, tile_count))
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    return results


def tile_to_rgba(tile_bytes: bytes, palette: Optional[List[int]] = None) -> bytes:
    """Convert one 32-byte 4bpp Genesis tile to 8x8 RGBA pixels."""
    if len(tile_bytes) != 32:
        raise ValueError("tile must be 32 bytes")
    if palette is None:
        # Greyscale default: index 0 is transparent.
        palette = [0x00000000] + [0xFF000000 | (i * 17) * 0x010101 for i in range(1, 16)]
    if len(palette) < 16:
        raise ValueError("palette must have at least 16 entries")

    pixels = bytearray(8 * 8 * 4)
    for y in range(8):
        row = int.from_bytes(tile_bytes[y * 4 : (y + 1) * 4], "big")
        for x in range(8):
            nibble = (row >> (28 - x * 4)) & 0x0F
            color = palette[nibble]
            if color > 0xFFFFFF:
                r = (color >> 16) & 0xFF
                g = (color >> 8) & 0xFF
                b = color & 0xFF
                a = (color >> 24) & 0xFF
            else:
                # Convert 9-bit 0xBGR to 24-bit RGB.
                b = ((color >> 1) & 7) * 36
                g = ((color >> 5) & 7) * 36
                r = ((color >> 9) & 7) * 36
                a = 255 if nibble != 0 else 0
            idx = (y * 8 + x) * 4
            pixels[idx : idx + 4] = bytes([r, g, b, a])
    return bytes(pixels)


def tiles_to_image(tiles: bytes, palette: Optional[List[int]] = None, cols: int = 8) -> Image.Image:
    if Image is None:
        raise RuntimeError("PIL is required for PNG export")
    n_tiles = len(tiles) // 32
    rows = (n_tiles + cols - 1) // cols
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    for i in range(n_tiles):
        tile = tiles[i * 32 : (i + 1) * 32]
        rgba = tile_to_rgba(tile, palette)
        tile_img = Image.frombytes("RGBA", (8, 8), rgba)
        x = (i % cols) * 8
        y = (i // cols) * 8
        img.paste(tile_img, (x, y))
    return img


class NemesisProbeError(Exception):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decode a Nemesis stream from a Genesis ROM and dump a PNG tile sheet"
    )
    parser.add_argument("rom", type=Path, help="Genesis ROM file")
    parser.add_argument("--offset", type=lambda x: int(x, 0), help="Nemesis stream offset")
    parser.add_argument("--out", type=Path, help="output PNG")
    parser.add_argument("--scan", action="store_true", help="scan ROM for Nemesis streams")
    parser.add_argument("--tool", help="path to clownnemesis-tool")
    parser.add_argument("--max-results", type=int, default=50)
    args = parser.parse_args()

    if Image is None:
        print("Error: Pillow is required (pip install Pillow)", file=sys.stderr)
        sys.exit(1)

    rom = args.rom.read_bytes()

    if args.scan:
        print(f"{'offset':>8} {'size':>8} {'xor':>4} {'tiles':>6}")
        for off, size, xor_mode, tiles in scan_nemesis_streams(
            rom, tool=args.tool, max_results=args.max_results
        ):
            print(f"{off:#08x} {size:>8} {str(xor_mode):>4} {tiles:>6}")
        return

    if args.offset is None:
        parser.error("specify --offset to decode, or --scan to search")

    chunk = rom[args.offset : args.offset + 0x4000]
    tiles = decode_with_clownnemesis(chunk, tool=args.tool)
    print(f"decoded {len(tiles)} bytes ({len(tiles)//32} tiles) at offset {args.offset:#x}")

    if args.out:
        img = tiles_to_image(tiles)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        img.save(args.out)
        print(f"saved {args.out}")


if __name__ == "__main__":
    main()
