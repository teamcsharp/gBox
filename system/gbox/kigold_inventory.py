"""Killer Instinct Gold (USA) N64 — owned-build inventory.

Resolves the exact owned ROM, verifies its No-Intro identity, parses the
N64 header and CIC, and records the container-layout facts the analysis
stage needs (RDP texture-op code leads, candidate LUTs/frame tables,
padding map). The asset payload itself is opaque high-entropy data with
no gzip members or Rare ``1172`` markers in this build, so the container
decode belongs to the analysis stage.

Usage:
    python -m gbox.kigold_inventory SRC [--out manifest.json]
"""

from __future__ import annotations

import binascii
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

from . import n64_rom

GAME_ID = "407771fca8e3cd17"
GAME_TITLE = "Killer Instinct Gold (USA)"

# No-Intro: Nintendo 64 — "Killer Instinct Gold (USA) (Rev 2)".
# The hyperspin catalog calls the same build "(Rev B)"; the header
# revision byte is 0x02. Identity is confirmed by sha1/crc32 below.
KNOWN = {
    "no_intro_name": "Killer Instinct Gold (USA) (Rev 2)",
    "catalog_name": "Killer Instinct Gold (USA) (Rev B)",
    "sha1": "aaeb492b1e538af65a3544a97240675ef438a04f",
    "crc32": "0b5b5df8",
    "md5": "dd0a82fcc10397afb37f12bb7f94e67a",
    "crc1": 0xF908CA4C,
    "crc2": 0x36464327,
    "size": 12 * 1024 * 1024,
}

# crc32 of the 4032-byte IPL3 boot block (rom[0x40:0x1000]).
CIC_TABLE = {
    0x6170A4A1: "CIC-NUS-6101/7101",
    0x90BB6CB5: "CIC-NUS-6102/7102",
    0x0B050EE0: "CIC-NUS-6103/7103",
    0x98BC2C86: "CIC-NUS-6105/7105",
}

# Offsets observed in this exact build (ROM image offsets, not VRAM).
LAYOUT = {
    "boot_block": (0x40, 0x1000),
    "code_scan_range": (0x1000, 0x90000),
    "lut_bit_shuffle": 0x7160,   # 32-byte shuffle LUT right after a MIPS epilogue
    "lut_size_ladder": 0x7180,   # u16 ladder 9,10,11,13,15,...(doubling by fours)
    "frame_table_candidates": (0x992D54, 0x9AA85C),  # u16 pairs (0xFE00, off+0x400*i)
    "ff_tail": 0xBFB000,         # 0xFF fill to end of ROM
    "dense_region": (0x1000, 0xBFB000),
}

# RDP command bases looked for as big-endian u32 constants in the code range.
RDP_OPS = {
    "G_SETTIMG": 0xED000000,
    "G_SETTIMG2": 0xEF000000,
    "G_LOADTLUT": 0xF0000000,
    "G_LOADBLOCK": 0xF3000000,
    "G_LOADTILE": 0xF4000000,
    "G_SETTILE": 0xF5000000,
}


def boot_cic(rom: bytes) -> str:
    """Identify the CIC from the IPL3 boot-block crc32."""
    return CIC_TABLE.get(binascii.crc32(rom[0x40:0x1000]) & 0xFFFFFFFF, "unknown")


def parse_header(rom: bytes) -> dict:
    """Parse the z64 cartridge header."""
    if rom[:4] != b"\x80\x37\x12\x40":
        raise ValueError("not a normalized z64 ROM")
    return {
        "entry": hex(struct.unpack(">I", rom[8:12])[0]),
        "crc1": hex(struct.unpack(">I", rom[0x10:0x14])[0]),
        "crc2": hex(struct.unpack(">I", rom[0x14:0x18])[0]),
        "cart_id": rom[0x3C:0x3E].decode("ascii", "replace"),
        "country": chr(rom[0x3E]) if 0x20 < rom[0x3E] < 0x7F else hex(rom[0x3E]),
        "revision": rom[0x3F],
        "clock": hex(struct.unpack(">I", rom[0x4C:0x50])[0]),
        "cic": boot_cic(rom),
    }


def identity(rom: bytes) -> dict:
    """Hashes and No-Intro identity check for the normalized ROM."""
    return {
        "size": len(rom),
        "sha1": hashlib.sha1(rom).hexdigest(),
        "md5": hashlib.md5(rom).hexdigest(),
        "crc32": f"{zlib.crc32(rom) & 0xFFFFFFFF:08x}",
        "matches_no_intro": (
            len(rom) == KNOWN["size"]
            and hashlib.sha1(rom).hexdigest() == KNOWN["sha1"]
        ),
        "no_intro_name": KNOWN["no_intro_name"],
        "catalog_name": KNOWN["catalog_name"],
    }


def layout_map(rom: bytes) -> dict:
    """Container-layout facts for this exact build."""
    pads = []
    for i in range(0, len(rom), 4096):
        block = rom[i : i + 4096]
        dominant = max(set(block), key=block.count)
        if block.count(dominant) / 4096 > 0.9:
            pads.append({"offset": i, "byte": dominant})
    code_lo, code_hi = LAYOUT["code_scan_range"]
    rdp_hits: dict[str, int] = {}
    for i in range(code_lo, code_hi - 3, 4):
        value = struct.unpack(">I", rom[i : i + 4])[0]
        for name, base in RDP_OPS.items():
            if value & 0xFF000000 == base:
                rdp_hits[name] = rdp_hits.get(name, 0) + 1
    tail_ff = all(b == 0xFF for b in rom[LAYOUT["ff_tail"] :])
    return {
        "dense_region": [hex(v) for v in LAYOUT["dense_region"]],
        "padding_blocks": pads,
        "ff_tail": {"offset": hex(LAYOUT["ff_tail"]), "pure_ff": tail_ff},
        "rdp_op_constant_counts_in_code": rdp_hits,
        "leads": {
            "bit_shuffle_lut": hex(LAYOUT["lut_bit_shuffle"]),
            "size_ladder_lut": hex(LAYOUT["lut_size_ladder"]),
            "frame_table_candidates": [hex(v) for v in LAYOUT["frame_table_candidates"]],
        },
        "no_rare_gzip_markers": b"1172" not in rom and b"\x1f\x8b\x08\x00\x00\x00\x00\x00" not in rom,
    }


def inventory(source: str | Path) -> dict:
    """Build the inventory manifest for an owned source archive/ROM."""
    source = Path(source)
    rom = n64_rom.read(source)
    if rom[:4] != b"\x80\x37\x12\x40":
        raise ValueError(f"{source.name}: not an N64 ROM (or unsupported archive)")
    with source.open("rb") as fh:
        source_sha256 = hashlib.sha256(fh.read()).hexdigest()
    ident = identity(rom)
    return {
        "game_id": GAME_ID,
        "title": GAME_TITLE,
        "platform": "n64",
        "emulator": "retroarch/parallel_n64",
        "source": {
            "path": str(source),
            "sha256": source_sha256,
            "format": source.suffix.lstrip("."),
        },
        "rom": {
            "bytes": len(rom),
            "sha256": hashlib.sha256(rom).hexdigest(),
            "sha1": ident["sha1"],
            "md5": ident["md5"],
            "crc32": ident["crc32"],
            "matches_no_intro": ident["matches_no_intro"],
            "no_intro_name": ident["no_intro_name"],
            "catalog_name": ident["catalog_name"],
            "header": parse_header(rom),
        },
        "layout": layout_map(rom),
        "characters": {
            "documented_roster": [
                "Jago", "Black Orchid", "Sabrewulf", "Glacius", "Chief Thunder",
                "T.J. Combo", "Spinal", "Cinder", "Fulgore", "Maya", "Kim Wu", "Tusk",
            ],
            "bosses": ["Eyedol", "Gargos"],
            "in_rom": "unverified — no plaintext name strings exist in this build; "
                       "roster tables must come from code analysis",
        },
        "assets": {
            "kind": "pre-rendered 2D sprites (Rare KI2 engine port)",
            "container": "opaque dense blob, no gzip members, no '1172' RareZip "
                         "markers in this build; decode is the analysis stage",
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, out = argv[1], None
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    manifest = inventory(src)
    text = json.dumps(manifest, indent=2)
    if out:
        Path(out).write_text(text + "\n")
        print(f"wrote {out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
