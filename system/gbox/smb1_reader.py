"""`smb1_reader`: native asset extraction for Super Mario Bros. (NES).

Exports player sprite frames and enemy tiles as editable PNGs from the
owned ROM. The reader stage prepares donor assets for a no-op roundtrip
and a targeted character replacement.

Output:
  player_frames/    26 PNGs (big/small Mario forms, one per frame row)
  enemy_slots/      43 PNGs (one per enemy graphics row; 27 distinct slots
                    plus frame variants, 6 tiles each)
  donor/            selected donor slot (player frame or enemy row) for
                    modification; used to prove the writer roundtrip

All PNGs are 8x8 tiles, rendered in the appropriate NES palette (4 colors
per tile, indexed 0-3). Palettes are pulled from the ROM's GroundPaletteData
for sprites and background tiles as documented in smb1_inventory.py.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
from PIL import Image

from gbox.smb1_inventory import (
    OFFSETS,
    PLAYER_ROW_NAMES,
    ENEMY_ROW_NAMES,
    NES_PALETTE,
    build_inventory,
    cpu_addr,
    parse_header,
    tile_pixels,
)


def _rgba_px(rom_data: bytes, tile: int, pal: list[int], scale: int = 1) -> bytes:
    """Render one 8x8 2bpp tile to RGBA bytes at `scale`."""
    h = parse_header(rom_data)
    chr_ = rom_data[h["chr_offset"]: h["chr_offset"] + h["chr_bytes"]]
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


def _save_png(path: str, rgba: bytes, w: int, h: int) -> None:
    """Write RGBA bytes as PNG with Pillow."""
    arr = np.frombuffer(rgba, dtype=np.uint8).reshape((h, w, 4))
    img = Image.fromarray(arr, mode="RGBA")
    img.save(path, "PNG")


def _area_palettes(rom_data: bytes, h: dict) -> dict:
    """Parse PPU palette blocks from PRG within ROM."""
    prg = rom_data[h["prg_offset"]: h["prg_offset"] + h["prg_bytes"]]
    out = {}
    for name in ("WaterPaletteData", "GroundPaletteData",
                 "UndergroundPaletteData", "CastlePaletteData"):
        off = OFFSETS[name]
        out[name] = {"palettes": [list(prg[off + 3 + 4 * i: off + 7 + 4 * i])
                                  for i in range(8)]}
    for name in ("DaySnowPaletteData", "NightSnowPaletteData",
                 "MushroomPaletteData", "BowserPaletteData"):
        off = OFFSETS[name]
        out[name] = {"palettes": [list(prg[off + 4 * i: off + 4 * i + 4])
                                  for i in range(2)]}
    off = OFFSETS["Palette3Data"]
    out["Palette3Data"] = {"fire_mario_cycle": [list(prg[off + 4 * i: off + 4 * i + 4])
                                                for i in range(4)]}
    return out


def _player_palettes(rom_data: bytes, h: dict) -> dict:
    """Return palette references for player rendering."""
    pal = _area_palettes(rom_data, h)
    return {
        "mario": pal["GroundPaletteData"]["palettes"][4],  # palette 4
        "luigi": pal["GroundPaletteData"]["palettes"][5],  # palette 5
        "fire": pal["Palette3Data"]["fire_mario_cycle"],  # cycle
    }


def export_player_frames(rom_path: str, out_dir: str, scale: int = 1) -> dict:
    """Export all 26 player frame rows as individual PNGs.

    Returns a manifest with per-frame metadata.
    """
    rom_data = open(rom_path, "rb").read()
    h = parse_header(rom_data)
    prg = rom_data[h["prg_offset"]: h["prg_offset"] + h["prg_bytes"]]
    mario_pal = _player_palettes(rom_data, h)["mario"]
    luigi_pal = _player_palettes(rom_data, h)["luigi"]

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    frames = []
    # Each row is 8 tile ids, but a player frame is 2 tiles wide x 4 tiles tall
    # so we pack 4 rows of tiles (8 tile ids) into one 16x32 sprite sheet.
    for r, name in enumerate(PLAYER_ROW_NAMES):
        off = OFFSETS["PlayerGraphicsTable"] + 8 * r
        row_tiles = list(prg[off: off + 8])
        # Build a 16x32 RGBA canvas (2 tiles wide, 4 tiles tall at 8x8 each)
        w, h = 16 * scale, 32 * scale
        rgba = bytearray(w * h * 4)
        stride = w * 4

        for c, tid in enumerate(row_tiles):
            if tid == 0xFC:  # blank sprite
                continue
            p = _rgba_px(rom_data, tid, mario_pal, scale)
            tx, ty = (c % 2) * 8 * scale, (c // 2) * 8 * scale
            for y in range(8 * scale):
                off = (ty + y) * stride + tx * 4
                rgba[off: off + 8 * scale * 4] = p[y * 8 * scale * 4: (y + 1) * 8 * scale * 4]

        frame_path = out_path / f"player_frame_{r:02d}_{name.replace(' ', '_')}.png"
        _save_png(str(frame_path), bytes(rgba), w, h)
        frames.append({
            "index": r,
            "name": name,
            "tiles": row_tiles,
            "output": str(frame_path),
        })

    return {"frames": frames, "palette": "mario_ground"}


def export_enemy_slots(rom_path: str, out_dir: str, scale: int = 1) -> dict:
    """Export all 27 enemy slots as individual PNGs.

    Each slot is rendered using the first 6 tiles from its graphics row.
    """
    rom_data = open(rom_path, "rb").read()
    h = parse_header(rom_data)
    prg = rom_data[h["prg_offset"]: h["prg_offset"] + h["prg_bytes"]]
    mario_pal = _player_palettes(rom_data, h)["mario"]

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    slots = []
    # Each enemy row is 6 tiles, rendered as 24x48 (3x2 layout)
    for s, name in enumerate(ENEMY_ROW_NAMES):
        off = OFFSETS["EnemyGraphicsTable"] + 6 * s
        row_tiles = list(prg[off: off + 6])
        # 3 tiles wide, 2 tiles tall at 8x8 each
        w, h = 24 * scale, 16 * scale
        rgba = bytearray(w * h * 4)
        stride = w * 4

        for c, tid in enumerate(row_tiles):
            if tid == 0xFC:
                continue
            p = _rgba_px(rom_data, tid, mario_pal, scale)
            tx, ty = (c % 3) * 8 * scale, (c // 3) * 8 * scale
            for y in range(8 * scale):
                off = (ty + y) * stride + tx * 4
                rgba[off: off + 8 * scale * 4] = p[y * 8 * scale * 4: (y + 1) * 8 * scale * 4]

        slot_path = out_path / f"enemy_slot_{s:02d}_{name.replace(' ', '_')}.png"
        _save_png(str(slot_path), bytes(rgba), w, h)
        slots.append({
            "index": s,
            "name": name,
            "tiles": row_tiles,
            "output": str(slot_path),
        })

    return {"slots": slots, "palette": "mario_ground"}


def export_donor_slot(rom_path: str, out_dir: str, slot_type: str, index: int,
                      scale: int = 4) -> str:
    """Export one donor slot (player frame or enemy row) at larger scale.

    The donor is the asset a modder will edit. We use scale=4 to make
    pixel editing practical.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if slot_type == "player":
        result = export_player_frames(rom_path, str(out_path / "donor"), scale=scale)
        if index >= len(result["frames"]):
            raise ValueError(f"player frame {index} out of range 0-{len(result['frames'])-1}")
        return result["frames"][index]["output"]
    elif slot_type == "enemy":
        result = export_enemy_slots(rom_path, str(out_path / "donor"), scale=scale)
        if index >= len(result["slots"]):
            raise ValueError(f"enemy slot {index} out of range 0-{len(result['slots'])-1}")
        return result["slots"][index]["output"]
    else:
        raise ValueError(f"unknown slot_type: {slot_type}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="smb1_reader", description="Export SMB1 NES sprite assets as PNGs."
    )
    ap.add_argument("rom", help="path to the .nes file")
    ap.add_argument("--out", default="smb1_assets",
                    help="output directory (player_frames/, enemy_slots/, donor/)")
    ap.add_argument("--scale", type=int, default=4,
                    help="PNG scale (pixel size, default 4)")
    ap.add_argument("--donor", action="store_true",
                    help="export one donor slot (uses --donor-type/--donor-index)")
    ap.add_argument("--donor-type", choices=["player", "enemy"], default="player",
                    help="donor asset type")
    ap.add_argument("--donor-index", type=int, default=0,
                    help="donor index (0-based)")
    args = ap.parse_args(argv)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    print("Exporting player frames...")
    result = export_player_frames(args.rom, str(out_root / "player_frames"), scale=args.scale)
    print(f"  {len(result['frames'])} frames -> {out_root / 'player_frames'}")

    print("Exporting enemy slots...")
    result = export_enemy_slots(args.rom, str(out_root / "enemy_slots"), scale=args.scale)
    print(f"  {len(result['slots'])} slots -> {out_root / 'enemy_slots'}")

    if args.donor:
        path = export_donor_slot(args.rom, str(out_root), args.donor_type,
                                 args.donor_index, scale=args.scale)
        print(f"Donor slot ({args.donor_type} {args.donor_index}) -> {path}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
