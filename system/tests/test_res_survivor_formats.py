"""Focused format checks for the owned Resident Evil - Survivor (PSX) disc."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox.res_survivor_formats import (
    ROSTER_NAMES, build_inventory, focused_probe, open_disc, parse_psx_tim,
    read_range,
)


def test_psx_tim_magic_and_offsets():
    p = focused_probe()
    aex = p["aex_first_tim"]
    assert aex is not None, "no PSX TIM at AEX.DAT offset 0"
    assert aex["offset"] == 0
    assert aex["bpp"] == 8, aex
    assert aex["clut"] is not None, aex
    assert aex["image"]["data_size"] > 0
    big = p["bigtim_first_tim"]
    assert big is not None, "no PSX TIM at B/BIGTIM.BIN offset 12"
    assert big["offset"] == 12
    assert big["bpp"] == 8, big
    assert parse_psx_tim(b"\x00" * 64, 0) is None


def test_pbav_container_magic_and_offset():
    p = focused_probe()
    pb = p["noise_pbav"]
    assert pb is not None, "pBAV container not detected in NOISE.BIN"
    assert pb["magic"] == "pBAV"
    assert pb["offset"] == 12
    assert pb["version"] == 2, pb
    assert pb["header_size"] == 12, pb
    assert pb["first_block_offset"] == 0xC2C, pb


def test_psx_exe_program_split():
    p = focused_probe()
    kern = p["KERNEL.BIN"]
    assert kern["exe"] is not None, "KERNEL.BIN is not a PS-X EXE"
    assert kern["exe"]["text_addr"] == 0x80010000, kern["exe"]
    assert kern["size"] > 400000, kern
    loader = p["SLUS_010.87"]
    assert loader["exe"] is not None
    assert loader["size"] == 45056, loader
    assert len(kern["sha256"]) == 64 and len(loader["sha256"]) == 64


def test_asset_class_counts():
    inv = build_inventory()
    counted = inv["counted_assets"]
    assert counted[".STR"]["count"] == 40, counted
    assert counted[".BIN"]["count"] == 72, counted
    assert counted[".DAT"]["count"] == 6, counted
    assert sum(c["count"] for c in counted.values()) == inv["member_count"] == 120


def test_no_ascii_cast_names_in_character_containers():
    disc, iso, members = open_disc()
    by = {m["path"]: m for m in members}
    for p in ("OBJ.DAT", "EV_OBJ.DAT", "ITEMDAT.DAT", "CONFFILE.BIN", "KERNEL.BIN"):
        data = read_range(disc, by[p])
        for n in ROSTER_NAMES:
            assert n.encode() not in data, (p, n)


if __name__ == "__main__":
    fails = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_"):
            try:
                _fn()
                print("PASS", _name)
            except Exception as exc:
                fails += 1
                print("FAIL", _name, type(exc).__name__, exc)
    raise SystemExit(1 if fails else 0)
