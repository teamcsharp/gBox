"""`smb1_inventory`: inventory of the owned Super Mario Bros. (World) NES build.

Source: the hyperspin zip ``Super Mario Bros. (World).zip`` (sha256
fb16c56ad6e0f2db925b09468f477de911ac8c52db0ea62a8553a72df2851883, catalog
game_id 49b6a2f65aca26a2). It holds a single 40976-byte iNES ROM
(sha256 f61548fdf1670cffefcc4f0b7bdcdd9eaba0c226e3b74f8666071496988248de)
whose PRG CRC32 5cf548d3 identifies the No-Intro "Super Mario Bros. (World)"
(JU) build. All table offsets below are signature-verified against that ROM
and cross-checked against the doppelganger SMB1 disassembly (mirrored at
github.com/abnuo/smbdis-dasm, src/smbdis.asm).

SMB1 is a 2D tile-sprite game: there are no meshes or animations in the 3D
sense. Characters are compositions of 8x8 CHR pattern tiles (sprite half of
the 8 KiB CHR bank), assembled by tile-id tables in PRG and tinted by the
PPU palette the game loads at startup. A "character replacement" for this
title therefore means replacing/redrawing CHR tiles (or retargeting the
tile-id tables), which the reader stage will export and the writer stage
will re-import.

Layout (NROM-256, mapper 0):
  file 0x0000-0x000f   16 B iNES 1.0 header
  file 0x0010-0x800f   32 KiB PRG, 2 x 16 KiB banks
                       bank 0 -> CPU $8000-$BFFF, bank 1 -> CPU $C000-$FFFF
  file 0x8010-0xa00f   8 KiB CHR, 256 sprite tiles + 256 background tiles
  no trainer, no battery RAM, vertical mirroring.

Verified table offsets (file offset in PRG, CPU address):
  PlayerGfxTblOffsets   0x6e07  $EE07   16 offsets (one per player state)
  PlayerGraphicsTable   0x6e17  $EE17   26 rows x 8 tile ids ($FC = blank)
  EnemyGraphicsTable    0x673e  $E73E   43 rows x 6 tile ids
  EnemyGfxTableOffsets  0x6840  $E840   27 offsets (one per enemy slot)
  GroundPaletteData     0x0cc8  $8CC8   35 B: PPU addr $3F00 + 8 x 4 B palettes
  WaterPaletteData      0x0ca4  $8CA4   same shape
  UndergroundPaletteData 0x0cec $8CEC  same shape
  CastlePaletteData     0x0d10  $8D10   same shape
  DaySnowPaletteData    0x0d34  $8D34   8 B (2 palettes, overwrites BG0/BG3)
  NightSnowPaletteData  0x0d3c  $8D3C   8 B
  MushroomPaletteData   0x0d44  $8D44   8 B
  BowserPaletteData     0x0d4c  $8D4C   8 B
  Palette3Data          0x09d1  $89D1   16 B fire-Mario palette cycle (4 x 4 B)

Player sprite palettes (from GroundPaletteData): palette 4 = Mario
(0f 16 27 18), palette 5 = Luigi (0f 1a 30 27), palette 6 = fireball/enemy
(0f 16 30 27). Luigi is a palette swap of Mario.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib

GAME_ID = "49b6a2f65aca26a2"
TITLE = "Super Mario Bros."

# PRG CRC32 -> (build name, notes). CRC32 covers the 32 KiB PRG only, so
# header/CHR variations keep the same identity.
KNOWN_BUILDS = {
    0x5CF548D3: (
        "Super Mario Bros. (World) [!]",
        "No-Intro (JU) World build; NROM-256, 2x16K PRG + 8K CHR",
    ),
}

OFFSETS = {
    "PlayerGfxTblOffsets": 0x6E07,
    "PlayerGraphicsTable": 0x6E17,
    "EnemyGraphicsTable": 0x673E,
    "EnemyGfxTableOffsets": 0x6840,
    "WaterPaletteData": 0x0CA4,
    "GroundPaletteData": 0x0CC8,
    "UndergroundPaletteData": 0x0CEC,
    "CastlePaletteData": 0x0D10,
    "DaySnowPaletteData": 0x0D34,
    "NightSnowPaletteData": 0x0D3C,
    "MushroomPaletteData": 0x0D44,
    "BowserPaletteData": 0x0D4C,
    "Palette3Data": 0x09D1,
}

# Player row names, in PlayerGraphicsTable order (comments in the
# doppelganger disassembly; rows of 8 tile ids, $FC = blank sprite).
PLAYER_ROW_NAMES = [
    "big walking frame 1", "big walking frame 2", "big walking frame 3",
    "big skidding", "big jumping", "big swimming frame 1",
    "big swimming frame 2", "big swimming frame 3", "big climbing frame 1",
    "big climbing frame 2", "big crouching", "big fireball throwing",
    "small walking frame 1", "small walking frame 2", "small walking frame 3",
    "small skidding", "small jumping", "small swimming frame 1",
    "small swimming frame 2", "small swimming frame 3",
    "small climbing frame 1", "small climbing frame 2", "small killed",
    "small standing", "intermediate grow frame", "big standing",
]

# Enemy row names, in EnemyGraphicsTable order (rows of 6 tile ids).
ENEMY_ROW_NAMES = [
    "buzzy beetle frame 1", "buzzy beetle frame 2",
    "koopa troopa frame 1", "koopa troopa frame 2",
    "koopa paratroopa frame 1", "koopa paratroopa frame 2",
    "spiny frame 1", "spiny frame 2",
    "spiny's egg frame 1", "spiny's egg frame 2",
    "bloober frame 1", "bloober frame 2",
    "cheep-cheep frame 1", "cheep-cheep frame 2",
    "goomba", "koopa shell frame 1 (upside-down)", "koopa shell frame 2",
    "koopa shell frame 1 (rightside-up)", "koopa shell frame 2",
    "buzzy beetle shell frame 1 (rightside-up)",
    "buzzy beetle shell frame 2",
    "buzzy beetle shell frame 1 (upside-down)",
    "buzzy beetle shell frame 2", "defeated goomba",
    "lakitu frame 1", "lakitu frame 2", "princess", "mushroom retainer",
    "hammer bro frame 1", "hammer bro frame 2", "hammer bro frame 3",
    "hammer bro frame 4", "piranha plant frame 1", "piranha plant frame 2",
    "podoboo", "bowser front frame 1", "bowser rear frame 1",
    "bowser front frame 2", "bowser rear frame 2", "bullet bill",
    "jumpspring frame 1", "jumpspring frame 2", "jumpspring frame 3",
]

# Enemy object codes (disassembly constants). For standard enemies the
# graphics-slot id (index into EnemyGfxTableOffsets) equals this code;
# Bowser ($2d) uses a dedicated BowserGfxHandler path instead.
ENEMY_CODES = {
    0x00: "green koopa troopa", 0x02: "buzzy beetle",
    0x03: "red koopa troopa", 0x05: "hammer bro", 0x06: "goomba",
    0x07: "bloober", 0x08: "bullet bill", 0x09: "tall enemy (koopa variant)",
    0x0A: "grey cheep-cheep", 0x0B: "red cheep-cheep", 0x0C: "podoboo",
    0x0D: "piranha plant", 0x0E: "green paratroopa (hopping)",
    0x0F: "red paratroopa", 0x10: "green paratroopa (flying)",
    0x11: "lakitu", 0x12: "spiny", 0x14: "flying cheep-cheep",
    0x15: "bowser flame", 0x2D: "bowser",
}

# Canonical 64-color NES palette (public reference data) for PNG previews.
NES_PALETTE = [
    0x666666, 0x002A88, 0x1412A7, 0x3B00A4, 0x5C007E, 0x6E0040, 0x6C0600,
    0x561D00, 0x333500, 0x0B4800, 0x005200, 0x004F08, 0x00404D, 0x000000,
    0x000000, 0x000000, 0xADADAD, 0x155FD9, 0x4240FF, 0x7527FE, 0xA01ACC,
    0xB71E7B, 0xB53120, 0x994E00, 0x6B6D00, 0x388700, 0x0C9300, 0x008F32,
    0x007C8D, 0x000000, 0x000000, 0x000000, 0xFFFEFF, 0x64B0FF, 0x9290FF,
    0xC676FF, 0xF36AFF, 0xFE6ECC, 0xFE8170, 0xEA9E22, 0xBCBE00, 0x88D800,
    0x5CE430, 0x45E082, 0x48CDDE, 0x4F4F4F, 0x000000, 0x000000, 0xFFFEFF,
    0xC0DFFF, 0xD3D2FF, 0xE8C8FF, 0xFBC2FF, 0xFEC4EA, 0xFECCC5, 0xF7D8A5,
    0xE4E594, 0xCFEF96, 0xBDF4AB, 0xB3F3CC, 0xB5EBF2, 0xB8B8B8, 0x000000,
    0x000000,
]


def parse_header(data: bytes) -> dict:
    if len(data) < 16 or data[:4] != b"NES\x1a":
        raise ValueError("not an iNES ROM")
    magic, prg16, chr8, flags6, flags7, flags8, flags9, flags10 = \
        struct.unpack("<4sBBBBBBB", data[:11])
    mapper = (flags6 >> 4) | (flags7 & 0xF0)
    return {
        "format": "iNES 1.0" if (flags7 & 0x0C) == 0 else "iNES 2.0",
        "prg_rom_16kb_banks": prg16,
        "chr_rom_8kb_banks": chr8,
        "mapper": mapper,
        "mirroring": "vertical" if flags6 & 1 else "horizontal",
        "battery": bool(flags6 & 2),
        "trainer": bool(flags6 & 4),
        "four_screen": bool(flags6 & 8),
        "flags8": flags8, "flags9": flags9, "flags10": flags10,
        "prg_offset": 16 + (512 if flags6 & 4 else 0),
        "prg_bytes": prg16 * 16384,
        "chr_offset": 16 + (512 if flags6 & 4 else 0) + prg16 * 16384,
        "chr_bytes": chr8 * 8192,
    }


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def identify(data: bytes) -> tuple | None:
    """Return (build name, notes) for a known build, else None."""
    h = parse_header(data)
    if h["mapper"] != 0 or h["prg_rom_16kb_banks"] != 2 \
            or h["chr_rom_8kb_banks"] != 1 or h["trainer"]:
        return None
    return KNOWN_BUILDS.get(_crc32(data[h["prg_offset"]:h["prg_offset"] + h["prg_bytes"]]))


def cpu_addr(prg_offset: int) -> int:
    """Map a PRG file offset to its CPU address (NROM-256)."""
    return 0x8000 + prg_offset if prg_offset < 0x4000 \
        else 0xC000 + (prg_offset - 0x4000)


def _player_rows(data: bytes) -> list:
    """26 rows x 8 tile ids from PlayerGraphicsTable."""
    off = OFFSETS["PlayerGraphicsTable"]
    return [list(data[off + 8 * i:off + 8 * i + 8]) for i in range(26)]


def _player_states(data: bytes) -> list:
    """16 per-state offsets into PlayerGraphicsTable, as row indices."""
    off = OFFSETS["PlayerGfxTblOffsets"]
    return [data[off + i] // 8 for i in range(16)]


def _enemy_rows(data: bytes) -> list:
    """43 rows x 6 tile ids from EnemyGraphicsTable."""
    off = OFFSETS["EnemyGraphicsTable"]
    return [list(data[off + 6 * i:off + 6 * i + 6]) for i in range(43)]


def _enemy_slots(data: bytes) -> list:
    """27 per-slot offsets into EnemyGraphicsTable, as row indices."""
    off = OFFSETS["EnemyGfxTableOffsets"]
    return [data[off + i] // 6 for i in range(27)]


def _area_palettes(data: bytes) -> dict:
    """Area palette blocks: PPU addr (3 B) + 8 palettes of 4 B."""
    out = {}
    for name in ("WaterPaletteData", "GroundPaletteData",
                 "UndergroundPaletteData", "CastlePaletteData"):
        off = OFFSETS[name]
        addr = data[off] << 8 | data[off + 1]
        out[name] = {"ppu_addr": addr, "count": data[off + 2] // 4,
                     "palettes": [list(data[off + 3 + 4 * i:off + 7 + 4 * i])
                                  for i in range(8)]}
    for name in ("DaySnowPaletteData", "NightSnowPaletteData",
                 "MushroomPaletteData", "BowserPaletteData"):
        off = OFFSETS[name]
        out[name] = {"palettes": [list(data[off + 4 * i:off + 4 * i + 4])
                                  for i in range(2)]}
    off = OFFSETS["Palette3Data"]
    out["Palette3Data"] = {"fire_mario_cycle":
                           [list(data[off + 4 * i:off + 4 * i + 4])
                            for i in range(4)]}
    return out


def build_inventory(rom_path: str, source_sha256: str = "") -> dict:
    data = open(rom_path, "rb").read()
    h = parse_header(data)
    prg = data[h["prg_offset"]:h["prg_offset"] + h["prg_bytes"]]
    chr_ = data[h["chr_offset"]:h["chr_offset"] + h["chr_bytes"]]
    ident = identify(data)
    rows = _player_rows(prg)
    st_rows = _player_states(prg)
    e_rows = _enemy_rows(prg)
    e_slots = _enemy_slots(prg)
    return {
        "game": TITLE, "game_id": GAME_ID, "platform": "nes",
        "source": {
            "zip_sha256": source_sha256 or None,
            "rom_sha256": hashlib.sha256(data).hexdigest(),
            "rom_md5": hashlib.md5(data).hexdigest(),
            "rom_crc32": "%08x" % _crc32(data),
            "prg_sha256": hashlib.sha256(prg).hexdigest(),
            "chr_sha256": hashlib.sha256(chr_).hexdigest(),
            "rom_bytes": len(data),
        },
        "build": {"name": ident[0] if ident else None,
                  "notes": ident[1] if ident else "unknown build",
                  "known": ident is not None},
        "launch": {
            "library": "hyperspin",
            "rel_path": "collections/Nintendo Entertainment System/roms/"
                        "Super Mario Bros. (World).zip",
            "emulator": "Nintendo Classic Mini",
            "retroarch_core": "mesen",
            "prerequisites": ["retroarch/mesen core (auto-install)",
                              "no BIOS, no battery, no mapper chip"],
        },
        "layout": {
            "header_bytes": 16,
            "prg": {"banks": h["prg_rom_16kb_banks"], "bank_bytes": 16384,
                    "cpu_map": ["$8000-$BFFF", "$C000-$FFFF"]},
            "chr": {"banks": h["chr_rom_8kb_banks"], "bank_bytes": 8192,
                    "sprite_tiles": "0-255", "background_tiles": "256-511"},
            "mirroring": h["mirroring"], "mapper": h["mapper"],
        },
        "characters": {
            "format": "2D 8x8 CHR pattern tiles composed by PRG tile-id "
                      "tables; no 3D geometry or skeletal animation",
            "player": {
                "forms": ["small mario (16x16, 4 tiles)",
                          "big mario (16x32, 8 tiles)",
                          "fire mario (big + palette3 cycle)"],
                "luigi": "palette swap (sprite palette 5: 0f 1a 30 27)",
                "frames": [{"row": i, "name": PLAYER_ROW_NAMES[i],
                            "tiles": rows[i]} for i in range(26)],
                "state_rows": [{"state": i, "row": st_rows[i],
                                "row_name": PLAYER_ROW_NAMES[st_rows[i]]}
                               for i in range(16)],
            },
            "enemies": {
                "rows": [{"row": i, "name": ENEMY_ROW_NAMES[i],
                          "tiles": e_rows[i]} for i in range(43)],
                "slots": [{"slot": i, "row": e_slots[i],
                           "row_name": ENEMY_ROW_NAMES[e_slots[i]],
                           "object_code": ENEMY_CODES.get(i)}
                          for i in range(27)],
                "bowser_note": "bowser ($2d) uses BowserGfxHandler, "
                               "graphics rows 35-38 of EnemyGraphicsTable",
            },
            "palettes": _area_palettes(prg),
        },
        "tables": {k: {"prg_offset": v, "cpu": cpu_addr(v)}
                   for k, v in OFFSETS.items()},
    }


def tile_pixels(chr_data: bytes, tile: int) -> list:
    """Decode one 8x8 2bpp NES tile into 64 palette indices (0-3)."""
    base = tile * 16
    out = []
    for y in range(8):
        lo, hi = chr_data[base + y], chr_data[base + y + 8]
        for x in range(8):
            out.append(((hi >> (7 - x)) & 1) << 1 | ((lo >> (7 - x)) & 1))
    return out


def _png(w: int, h: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4]
                   for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _rgba_px(rom_data: bytes, tile: int, pal: list, scale: int) -> bytes:
    """Render one CHR tile at `scale` px, returning RGBA bytes."""
    h = parse_header(rom_data)
    chr_ = rom_data[h["chr_offset"]:h["chr_offset"] + h["chr_bytes"]]
    idx = tile_pixels(chr_, tile)
    rows = []
    for y in range(8):
        row = bytearray()
        for x in range(8):
            c = NES_PALETTE[pal[idx[y * 8 + x]] & 0x3F]
            px = bytes((c >> 16 & 0xFF, c >> 8 & 0xFF, c & 0xFF, 0xFF))
            row += px * scale
        rows.append(bytes(row) * scale)
    return b"".join(rows)


def chr_png(rom_path: str, out_path: str, scale: int = 4) -> None:
    """Render all 512 CHR tiles as one PNG (sprite half with the Mario
    palette, background half with the ground BG palette)."""
    rom_data = open(rom_path, "rb").read()
    prg = rom_data[16:16 + 32768]
    pal = _area_palettes(prg)
    mario = pal["GroundPaletteData"]["palettes"][4]
    bg = pal["GroundPaletteData"]["palettes"][0]
    tile = scale * 8
    cols, rows = 32, 16
    img = bytearray(tile * tile * cols * rows * 4)
    stride = tile * cols * 4
    for i in range(512):
        p = _rgba_px(rom_data, i, mario if i < 256 else bg, scale)
        tx, ty = (i % cols) * tile, (i // cols) * tile
        for y in range(tile):
            off = (ty + y) * stride + tx * 4
            img[off:off + tile * 4] = p[y * tile * 4:(y + 1) * tile * 4]
    open(out_path, "wb").write(
        _png(tile * cols, tile * rows, bytes(img)))


def player_png(rom_path: str, out_path: str, scale: int = 6) -> None:
    """Render the 26 player-frame rows (big then small) side by side."""
    rom_data = open(rom_path, "rb").read()
    prg = rom_data[16:16 + 32768]
    mario = _area_palettes(prg)["GroundPaletteData"]["palettes"][4]
    rows = _player_rows(prg)
    tile = scale * 8
    per = 7  # frames per row, keeps the sheet viewable
    gap = 4
    # the disassembly comment: "tiles arranged in order, 2 tiles per row,
    # top to bottom" -> each frame is 2 tiles wide x 4 tiles tall.
    fw, fh = 2 * tile, 4 * tile
    w = per * fw + (per - 1) * gap
    h = 4 * fh + 3 * gap
    img = bytearray(w * h * 4)
    stride = w * 4
    for r, row in enumerate(rows):
        fr = bytearray(fw * fh * 4)  # one frame canvas
        fstride = fw * 4
        for c, tid in enumerate(row):
            if tid == 0xFC:
                continue
            p = _rgba_px(rom_data, tid, mario, scale)
            tx, ty = (c % 2) * tile, (c // 2) * tile
            for y in range(tile):
                off = tx * 4 + (ty + y) * fstride
                fr[off:off + tile * 4] = p[y * tile * 4:(y + 1) * tile * 4]
        fx = (r % per) * (fw + gap)
        fy = (r // per) * (fh + gap)
        for y in range(fh):
            off = (fy + y) * stride + fx * 4
            img[off:off + fw * 4] = fr[y * fstride:(y + 1) * fstride]
    open(out_path, "wb").write(_png(w, h, bytes(img)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="smb1_inventory",
                                 description="Inventory the owned SMB (World) NES build.")
    ap.add_argument("rom", help="path to the .nes file")
    ap.add_argument("--out", help="write manifest JSON here")
    ap.add_argument("--png", help="directory for chr.png / player.png previews")
    ap.add_argument("--source-sha256", default="",
                    help="sha256 of the owned source zip")
    args = ap.parse_args(argv)
    inv = build_inventory(args.rom, args.source_sha256)
    print(json.dumps({"build": inv["build"], "source": inv["source"],
                      "characters": {
                          "player_frames": len(inv["characters"]["player"]["frames"]),
                          "enemy_rows": len(inv["characters"]["enemies"]["rows"]),
                          "enemy_slots": len(inv["characters"]["enemies"]["slots"]),
                      }, "tables": inv["tables"]}, indent=2))
    if args.out:
        open(args.out, "w").write(json.dumps(inv, indent=2))
        print(f"manifest written: {args.out}")
    if args.png:
        import os
        os.makedirs(args.png, exist_ok=True)
        chr_png(args.rom, os.path.join(args.png, "chr.png"))
        player_png(args.rom, os.path.join(args.png, "player.png"))
        print(f"PNGs written: {args.png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
