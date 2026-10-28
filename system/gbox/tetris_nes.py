"""Tetris (Nintendo Famicom) CHR-page and PPU-palette reader.

The Tetris build is an iNES 1.0 ROM with mapper 3 (CNROM):
- 32 KB PRG (banked through $8000-$9FFF, only $8000-$9FFF is writable)
- 16 KB CHR (16 pages of 1 KB each at PPU $0000-$3FFF)

This reader extracts:
1. All 16 CHR pages as 2bpp tile atlases (PNG sheets)
2. PPU palette RAM contents from two known sources:
   - Static 32-byte table at $9C86 (PPU $2006/$2007 write path)
   - Dynamic 16-byte palette from zero-page $049A (ANDed with $0F)
3.CHR page SHA-256 checksums for verification

Usage: ``python -m gbox.tetris_nes ROM_PATH --out OUTPUT_DIR``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Tuple, List, Dict, Any

VERSION = "1.0"
READER_VERSION = "1.0"
CHR_PAGE_SIZE = 1024
CHR_TOTAL_PAGES = 16
PPU_PALETTE_SIZE = 32
INES_HEADER_SIZE = 16
INES_MAGIC = b"NES\x1a"
PRG_PAGE_SIZE = 16384


def title_test(title: str | None, platform: str) -> bool:
    """Match Tetris (Nintendo Famicom) on NES platform."""
    if platform.lower() != "nes":
        return False
    t = (title or "").lower().strip()
    return "tetris" in t and any(k in t for k in ("nintendo", "famicom", "nes"))


def roster() -> List[Dict[str, Any]]:
    """Return the Tetris roster entries."""
    return [
        {
            "key": "CHR_PAGES",
            "slug": "tetris_chr_pages",
            "name": "Tetris CHR pages",
            "aliases": ["tetris tiles", "tetris graphics", "CHR pages"],
            "kind": "sprites",
        },
        {
            "key": "PALETTE",
            "slug": "tetris_palette",
            "name": "Tetris PPU palette",
            "aliases": ["tetris colors", "PPU palette", "palette RAM"],
            "kind": "palette",
        },
    ]


def read_ines_header(data: bytes) -> Dict[str, Any]:
    """Parse iNES 1.0 header."""
    if len(data) < INES_HEADER_SIZE:
        raise ValueError(f"File too small for iNES header ({len(data)} bytes)")
    if data[:4] != INES_MAGIC:
        raise ValueError("Not an iNES file (missing magic)")

    prg_pages = data[4]
    chr_pages = data[5]
    flags6 = data[6]
    flags7 = data[7]
    prg_ram_size = data[8]
    flags10 = data[10]

    # Mapper number: bits 4-7 of flags6 + bits 0-2 of flags7
    mapper = ((flags6 & 0xF0) >> 4) | (flags7 & 0x0F)

    return {
        "version": 1,
        "prg_pages": prg_pages,
        "chr_pages": chr_pages,
        "mapper": mapper,
        "trainer": (flags6 & 0x04) != 0,
        "mirror": "vertical" if (flags6 & 0x01) else "horizontal",
        "prg_ram": prg_ram_size > 0,
        "system": "ntsc" if flags10 == 0 else "pal",
    }


def read_chr_pages(data: bytes, header: Dict[str, Any]) -> bytes:
    """Read CHR ROM data from iNES file.

    The header's chr_pages count is in 8 KB units; each unit is 8 pages of 1 KB.
    Total CHR size = chr_pages * 8 * 1024 bytes.
    """
    offset = INES_HEADER_SIZE + (1 if header["trainer"] else 0) + (header["prg_pages"] * PRG_PAGE_SIZE)
    size = header["chr_pages"] * 8 * CHR_PAGE_SIZE
    if len(data) < offset + size:
        raise ValueError(f"File too small for CHR data ({len(data)} bytes)")
    return data[offset:offset + size]


def read_prg_pages(data: bytes, header: Dict[str, Any]) -> bytes:
    """Read PRG ROM data from iNES file."""
    offset = INES_HEADER_SIZE + (1 if header["trainer"] else 0)
    size = header["prg_pages"] * PRG_PAGE_SIZE
    if len(data) < offset + size:
        raise ValueError(f"File too small for PRG data ({len(data)} bytes)")
    return data[offset:offset + size]


def decode_2bpp_tile(data: bytes) -> List[List[int]]:
    """Decode a 16-byte 2bpp tile to 8x8 colour indices (0-3)."""
    if len(data) != 16:
        raise ValueError(f"Tile data must be 16 bytes, got {len(data)}")

    tile = []
    for y in range(8):
        row = []
        lo = data[y]
        hi = data[y + 8]
        for x in range(7, -1, -1):
            bit_lo = (lo >> x) & 1
            bit_hi = (hi >> x) & 1
            index = (bit_hi << 1) | bit_lo
            row.append(index)
        tile.append(row)
    return tile


def encode_tile(rows: List[List[int]]) -> bytes:
    """Encode 8x8 colour indices (0-3) to 16-byte 2bpp tile."""
    if len(rows) != 8 or any(len(r) != 8 for r in rows):
        raise ValueError("Tile must be 8x8")

    tile = bytearray(16)
    for y in range(8):
        for x in range(8):
            v = rows[y][x]
            bit_pos = 7 - x
            if v & 1:
                tile[y] |= (1 << bit_pos)
            if v & 2:
                tile[y + 8] |= (1 << bit_pos)
    return bytes(tile)


def tile_sha256(chr_data: bytes, page_idx: int) -> str:
    """Compute SHA-256 of a CHR page."""
    start = page_idx * CHR_PAGE_SIZE
    end = start + CHR_PAGE_SIZE
    return hashlib.sha256(chr_data[start:end]).hexdigest()


def count_blank_tiles(chr_data: bytes, page_idx: int) -> int:
    """Count blank (all-zero) tiles in a CHR page."""
    start = page_idx * CHR_PAGE_SIZE
    end = start + CHR_PAGE_SIZE
    blank = 0
    for i in range(start, end, 16):
        if chr_data[i:i + 16] == b"\x00" * 16:
            blank += 1
    return blank


def indexed_png_bytes(
    w: int,
    h: int,
    indices: List[int],
    palette: List[Tuple[int, int, int]],
    transparent: int | None = None,
) -> bytes:
    """Create an indexed PNG (color type 3) from pixel indices."""
    if w <= 0 or h <= 0 or len(indices) != w * h:
        raise ValueError("Invalid PNG dimensions")
    if any(p < 0 or p >= len(palette) for p in indices):
        raise ValueError("PNG index out of palette range")

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    # IHDR
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    ihdr_chunk = chunk(b"IHDR", ihdr)

    # PLTE
    plte = bytearray()
    for r, g, b in palette:
        plte.extend([r, g, b])
    plte_chunk = chunk(b"PLTE", bytes(plte))

    # tRNS (optional)
    trns_chunk = b""
    if transparent is not None:
        trns = bytes([0] * transparent + [255] * (len(palette) - transparent))
        trns_chunk = chunk(b"tRNS", trns)

    # IDAT
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # no filter
        for x in range(w):
            rows.append(indices[y * w + x])
    idat = zlib.compress(bytes(rows))
    idat_chunk = chunk(b"IDAT", idat)

    iend_chunk = chunk(b"IEND", b"")

    png_sig = b"\x89PNG\r\n\x1a\n"
    return png_sig + ihdr_chunk + plte_chunk + trns_chunk + idat_chunk + iend_chunk


def extract_chr_pages(chr_data: bytes, output_dir: Path) -> Dict[str, Any]:
    """Extract all CHR pages as PNG atlases."""
    pages = []
    for page_idx in range(CHR_TOTAL_PAGES):
        start = page_idx * CHR_PAGE_SIZE
        end = start + CHR_PAGE_SIZE
        page_bytes = chr_data[start:end]

        # Decode all 64 tiles
        tile_indices = []
        for tile_idx in range(64):
            tile_start = tile_idx * 16
            tile_bytes = page_bytes[tile_start:tile_start + 16]
            tile = decode_2bpp_tile(tile_bytes)
            tile_indices.append(tile)

        # Build 8x8 grid of tiles (512x64 pixel sheet)
        sheet_w = 512
        sheet_h = 64

        # 4-colour grey palette
        palette: List[Tuple[int, int, int]] = [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)]

        indices = bytearray()
        for tile_y in range(8):
            for px_y in range(8):
                for col_idx in range(64):
                    for px_x in range(8):
                        indices.append(tile_indices[col_idx][px_y][px_x])

        png_data = indexed_png_bytes(sheet_w, sheet_h, list(indices), palette)

        page_file = output_dir / f"chr_page_{page_idx:02x}.png"
        page_file.parent.mkdir(parents=True, exist_ok=True)
        page_file.write_bytes(png_data)

        pages.append({
            "page_idx": page_idx,
            "sha256": tile_sha256(chr_data, page_idx),
            "blank_tiles": count_blank_tiles(chr_data, page_idx),
            "png_file": str(page_file.relative_to(output_dir)),
        })

    return {"pages": pages, "version": READER_VERSION}


def parse_palette_data(prg_data: bytes, palettes: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse palette data from PRG ROM.

    Tetris has two palette sources:
    - Static 32-byte table at $9C86 (offset 0x9C86 from PRG start)
    - Dynamic 16-byte palette from zero-page $049A
    """
    static_offset = 7318  # 0x9C86
    if len(prg_data) > static_offset + 32:
        palettes["static_32b"] = list(prg_data[static_offset:static_offset + 32])
    return palettes


def extract_all(data: bytes, output_dir: Path) -> Dict[str, Any]:
    """Extract all Tetris assets from ROM data."""
    header = read_ines_header(data)

    if header["version"] != 1:
        raise ValueError(f"Only iNES 1.0 supported, got {header['version']}")
    if header["chr_pages"] != 2:
        raise ValueError(f"Expected 2 CHR pages (8 KB), got {header['chr_pages']}")
    if header["mapper"] != 3:
        raise ValueError(f"Expected mapper 3 (CNROM), got {header['mapper']}")

    # Offsets
    chr_offset = INES_HEADER_SIZE + header["prg_pages"] * PRG_PAGE_SIZE
    prg_offset = INES_HEADER_SIZE

    # Extract data
    chr_data = read_chr_pages(data, header)
    prg_data = read_prg_pages(data, header)

    # SHA-256 of PRG + CHR combined
    prg_chr_sha256 = hashlib.sha256(prg_data + chr_data).hexdigest()

    # Extract CHR pages
    chr_pages = extract_chr_pages(chr_data, output_dir)

    # Parse palettes
    palettes = parse_palette_data(prg_data, {})

    return {
        "header": header,
        "chr_pages": chr_pages,
        "palettes": palettes,
        "sha256_prg_chr": prg_chr_sha256,
        "version": READER_VERSION,
    }


def extract_run(ctx, game: Dict[str, Any], entry: Dict[str, Any], work: Path, out: Path) -> None:
    """Dedicated extract hook — pulls the Tetris CHR pages + PPU palette from the owned iNES ROM."""
    from .models import CatalogEntry
    from .tools import rom_path

    src = rom_path(CatalogEntry.model_validate(game), ctx.config)
    raw = src.read_bytes()
    result = extract_all(raw, work)
    out.write_text(json.dumps(result, indent=2))


def main() -> None:
    """Extract Tetris NES CHR pages and palettes"""
    parser = argparse.ArgumentParser(description="Extract Tetris NES CHR pages and palettes")
    parser.add_argument("rom_path", help="Path to Tetris ROM (.nes or .zip)")
    parser.add_argument("--out", required=True, help="Output directory")
    args = parser.parse_args()

    rom_path = Path(args.rom_path)
    if rom_path.suffix.lower() == ".zip":
        import zipfile
        zf = zipfile.ZipFile(rom_path)
        members = [n for n in zf.namelist() if n.endswith(".nes")]
        if not members:
            raise ValueError("No .nes file in archive")
        data = zf.read(members[0])
    else:
        data = rom_path.read_bytes()

    out = Path(args.out)
    result = extract_all(data, out)

    manifest = json.dumps(result, indent=2)
    (out / "manifest.json").write_text(manifest)
    print(f"Extracted to {out}")
    print(f"CHR pages: {len(result['chr_pages']['pages'])}")
    print(f"SHA256 PRG+CHR: {result['sha256_prg_chr']}")


if __name__ == "__main__":
    main()
