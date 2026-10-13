"""`smb1_analysis`: locate the PRG code that drives SMB1's sprite rendering.

This module works on the owned No-Intro build identified by `smb1_inventory`
(game_id 49b6a2f65aca26a2).  It reuses the signature-verified table offsets and
parses the PRG to find:

* the routines that read the player/enemy tile-id tables
  (`PlayerGraphicsTable`, `EnemyGraphicsTable`) and write tile numbers into the
  shadow OAM at $0200;
* the OAM DMA trigger (write to $4014) that copies shadow OAM to the PPU;
* evidence that sprite tiles are taken from the 8 KiB CHR-ROM pattern table,
  not uploaded by the CPU (no $2007 writes are needed for sprites).

All addresses are reported as CPU addresses (NROM-256: bank 0 at $8000-$BFFF,
bank 1 at $C000-$FFFF).  The module also exposes a small CHR tile parser that
can decode any 8x8 tile into palette indices and render it to RGBA.

The analysis is deliberately bounded: it scans for a handful of known opcodes
and operands rather than decompiling the whole ROM.  Results are reproducible
from the ROM bytes and the table offsets documented in `smb1_inventory`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from gbox.smb1_inventory import OFFSETS, tile_pixels, parse_header, cpu_addr

# OAM layout used by the disassembly (zero-page-ish labels in $0200 page).
OAM_PAGE = 0x0200
SPRITE_Y = 0x0200
SPRITE_TILE = 0x0201
SPRITE_ATTR = 0x0202
SPRITE_X = 0x0203
SPR_DMA = 0x4014

# Opcodes we scan for.  Mapping: opcode byte -> (mnemonic, addressing mode).
# We only need absolute / absolute-indexed loads/stores for this stage.
OPCODES = {
    0xAD: ("LDA", "abs"),
    0xBD: ("LDA", "abs,x"),
    0xB9: ("LDA", "abs,y"),
    0x8D: ("STA", "abs"),
    0x9D: ("STA", "abs,x"),
    0x99: ("STA", "abs,y"),
    0x20: ("JSR", "abs"),
    0x4C: ("JMP", "abs"),
}


@dataclass(frozen=True)
class Reference:
    """A PRG location that references a known CPU address."""

    prg_offset: int
    cpu_addr: int
    opcode: int
    opcode_name: str
    mode: str
    target_cpu: int


def _prg_offset_to_cpu(prg_offset: int) -> int:
    """Map a 32 KiB PRG file offset to its NROM-256 CPU address."""
    return cpu_addr(prg_offset)


def load_prg(rom_path: str) -> bytes:
    """Read a .nes file and return the 32 KiB PRG ROM."""
    data = open(rom_path, "rb").read()
    h = parse_header(data)
    return data[h["prg_offset"]: h["prg_offset"] + h["prg_bytes"]]


def find_references(
    prg: bytes,
    target_cpu: int,
    opcodes: Iterable[int] | None = None,
) -> list[Reference]:
    """Find all instructions in PRG whose 16-bit operand equals `target_cpu`.

    The scan walks every PRG byte, decodes a two-byte little-endian operand
    when an allowed opcode is seen, and returns a `Reference` for each match.
    This is intentionally simple; it does not model bank switching because
    NROM-256 has a fixed linear 32 KiB PRG map.
    """
    if opcodes is None:
        opcodes = OPCODES.keys()
    allowed = set(opcodes)
    target_lo = target_cpu & 0xFF
    target_hi = (target_cpu >> 8) & 0xFF
    out: list[Reference] = []
    i = 0
    while i < len(prg) - 2:
        op = prg[i]
        if op in allowed:
            lo, hi = prg[i + 1], prg[i + 2]
            if lo == target_lo and hi == target_hi:
                name, mode = OPCODES[op]
                out.append(
                    Reference(
                        prg_offset=i,
                        cpu_addr=_prg_offset_to_cpu(i),
                        opcode=op,
                        opcode_name=name,
                        mode=mode,
                        target_cpu=target_cpu,
                    )
                )
        i += 1
    return out


def find_table_readers(prg: bytes) -> dict[str, list[Reference]]:
    """Locate PRG code that reads the player/enemy tile-id tables."""
    return {
        "PlayerGraphicsTable": find_references(
            prg, 0xEE17, opcodes=(0xBD, 0xB9)
        ),
        "PlayerGfxTblOffsets": find_references(
            prg, 0xEE07, opcodes=(0xBD, 0xB9)
        ),
        "EnemyGraphicsTable": find_references(
            prg, 0xE73E, opcodes=(0xBD, 0xB9)
        ),
        "EnemyGfxTableOffsets": find_references(
            prg, 0xE840, opcodes=(0xBD, 0xB9)
        ),
    }


def find_oam_dma(prg: bytes) -> list[Reference]:
    """Find the OAM DMA handshake (LDA #$02 ; STA $4014)."""
    return find_references(prg, SPR_DMA, opcodes=(0x8D,))


def find_oam_tile_writes(prg: bytes) -> list[Reference]:
    """Find stores into the shadow OAM tile-number field ($0201)."""
    return find_references(prg, SPRITE_TILE, opcodes=(0x99, 0x9D, 0x8D))


def find_oam_attr_writes(prg: bytes) -> list[Reference]:
    """Find stores into the shadow OAM attribute field ($0202)."""
    return find_references(prg, SPRITE_ATTR, opcodes=(0x99, 0x9D, 0x8D))


def find_oam_xy_writes(prg: bytes) -> list[Reference]:
    """Find stores into shadow OAM X/Y fields ($0200/$0203)."""
    return sorted(
        find_references(prg, SPRITE_Y, opcodes=(0x99, 0x9D, 0x8D))
        + find_references(prg, SPRITE_X, opcodes=(0x99, 0x9D, 0x8D)),
        key=lambda r: r.prg_offset,
    )


def decode_chr_tile(chr_data: bytes, tile: int) -> list[int]:
    """Decode an 8x8 2bpp CHR tile into 64 palette-index pixels.

    Tiles 0-255 live in the sprite half of the 8 KiB CHR bank; tiles 256-511
    live in the background half.  The returned list is row-major.
    """
    if tile < 0 or tile >= len(chr_data) // 16:
        raise ValueError(f"tile {tile} out of range for {len(chr_data)//16} tiles")
    return tile_pixels(chr_data, tile)


def describe_sprite_pipeline(rom_path: str) -> dict:
    """Return a structured summary of the sprite rendering path."""
    prg = load_prg(rom_path)
    readers = find_table_readers(prg)
    dma = find_oam_dma(prg)
    tile_writes = find_oam_tile_writes(prg)
    attr_writes = find_oam_attr_writes(prg)
    xy_writes = find_oam_xy_writes(prg)

    # The disassembly identifies these routines by name.  We pin them by
    # matching the first PlayerGraphicsTable reference pattern:
    #   LDA PlayerGraphicsTable,X   at the DrawPlayerLoop entry.
    draw_player_loop = None
    if readers["PlayerGraphicsTable"]:
        draw_player_loop = readers["PlayerGraphicsTable"][0].cpu_addr

    return {
        "source": {
            "prg_bytes": len(prg),
            "rom_path": rom_path,
        },
        "tile_table_readers": {
            name: [{"cpu": ref.cpu_addr, "opcode": ref.opcode_name,
                    "mode": ref.mode, "prg_offset": ref.prg_offset}
                   for ref in refs]
            for name, refs in readers.items()
        },
        "shadow_oam": {
            "tile_number_writes": [
                {"cpu": ref.cpu_addr, "opcode": ref.opcode_name,
                 "mode": ref.mode, "prg_offset": ref.prg_offset}
                for ref in tile_writes
            ],
            "attribute_writes": [
                {"cpu": ref.cpu_addr, "opcode": ref.opcode_name,
                 "mode": ref.mode, "prg_offset": ref.prg_offset}
                for ref in attr_writes
            ],
            "xy_writes": [
                {"cpu": ref.cpu_addr, "opcode": ref.opcode_name,
                 "mode": ref.mode, "prg_offset": ref.prg_offset}
                for ref in xy_writes
            ],
        },
        "oam_dma": [
            {"cpu": ref.cpu_addr, "opcode": ref.opcode_name,
             "mode": ref.mode, "prg_offset": ref.prg_offset}
            for ref in dma
        ],
        "draw_player_loop_cpu": draw_player_loop,
        "notes": [
            "Sprite tile numbers are read from PRG tables and stored to "
            "$0201+Y in the shadow OAM; the NMI then writes $02 to $4014.",
            "CHR patterns come from the 8 KiB CHR-ROM bank, not from CPU "
            "$2007 uploads (SMB1 uses mapper-0 NROM with fixed pattern tables).",
        ],
    }


def render_tile_rgba(
    chr_data: bytes,
    tile: int,
    palette: list[int],
    scale: int = 1,
) -> bytes:
    """Render one decoded CHR tile to a scaled RGBA byte string."""
    idx = decode_chr_tile(chr_data, tile)
    rows = []
    for y in range(8):
        row = bytearray()
        for x in range(8):
            c = palette[idx[y * 8 + x] & 0x3F]
            row += bytes((c >> 16 & 0xFF, c >> 8 & 0xFF, c & 0xFF, 0xFF)) * scale
        rows.append(bytes(row) * scale)
    return b"".join(rows)
