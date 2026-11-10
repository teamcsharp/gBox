"""`smb1_swap`: native CHR-ROM writer for Super Mario Bros. (NES, NROM).

Replaces the pixels of the tiles one player frame row uses with the pixels of
an enemy graphics row (the donor). Only CHR bytes for those tiles change; the
iNES header, PRG and every other CHR tile are preserved, and the original ROM
is never modified (output must be a different path).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from gbox.smb1_inventory import OFFSETS, parse_header, tile_pixels
from gbox.smb1_reader import tile_bytes

GAME_IDS = {"49b6a2f65aca26a2"}
SOURCE_SHA256 = "fb16c56ad6e0f2db925b09468f477de911ac8c52db0ea62a8553a72df2851883"
BLANK = 0xFC
SPRITE_TILES = 256  # sprite pattern table = first 4 KiB of CHR (tile ids are u8)


def _rows(rom: bytes, h: dict, table: str, width: int, n: int, row: int) -> list[int]:
    if not 0 <= row < n:
        raise ValueError(f"{table} row {row} out of range 0-{n - 1}")
    off = h["prg_offset"] + OFFSETS[table] + width * row  # table value = offset in PRG
    if off + width > h["prg_offset"] + h["prg_bytes"]:
        raise ValueError(f"{table} row {row} outside PRG")
    return list(rom[off: off + width])


def plan_tiles(rom: bytes, player_row: int, enemy_row: int) -> dict[int, int]:
    """Map player tile id -> donor tile id (position-aligned, blanks skipped)."""
    h = parse_header(rom)
    if h["mapper"] != 0 or h["chr_bytes"] < SPRITE_TILES * 16:
        raise ValueError("unsupported cartridge (need NROM with CHR-ROM)")
    p = _rows(rom, h, "PlayerGraphicsTable", 8, 26, player_row)
    d = _rows(rom, h, "EnemyGraphicsTable", 6, 43, enemy_row)
    plan: dict[int, int] = {}
    for pos in range(6):
        if p[pos] != BLANK and d[pos] != BLANK and p[pos] != d[pos]:
            plan[p[pos]] = d[pos]
    if not plan:
        raise ValueError("donor row would not change any tile")
    return plan


def write_mod(rom_path: str, out_path: str, player_row: int = 0, enemy_row: int = 0) -> dict:
    """Write a modded ROM and independently verify it; returns the receipt."""
    src = Path(rom_path)
    out = Path(out_path)
    if out.resolve() == src.resolve():
        raise ValueError("refusing to overwrite the original ROM")
    rom = src.read_bytes()
    sha = hashlib.sha256(rom).hexdigest()
    h = parse_header(rom)
    plan = plan_tiles(rom, player_row, enemy_row)
    chr0 = h["chr_offset"]
    # Donor pixels are read first from the untouched ROM so overlapping ids stay consistent.
    chr_src = rom[chr0: chr0 + h["chr_bytes"]]
    new = bytearray(rom)
    for dst, don in plan.items():
        new[chr0 + dst * 16: chr0 + dst * 16 + 16] = tile_bytes(tile_pixels(chr_src, don))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(new))
    # Readback from disk
    back = out.read_bytes()
    changed = [i for i in range(len(rom)) if rom[i] != back[i]]
    allowed = {chr0 + t * 16 + k for t in plan for k in range(16)}
    assert len(back) == len(rom) and back[:chr0] == rom[:chr0], "header/PRG changed"
    assert set(changed) <= allowed, "bytes outside the target tiles changed"
    cb = back[chr0:]
    for dst, don in plan.items():
        assert tile_pixels(cb, dst) == tile_pixels(chr_src, don), f"tile {dst} != donor {don}"
    return {"source_sha256": sha, "mod_sha256": hashlib.sha256(back).hexdigest(),
            "player_row": player_row, "enemy_row": enemy_row, "tile_map": plan,
            "changed_bytes": len(changed), "out": str(out)}
