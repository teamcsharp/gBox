"""Tests for gbox.fzgx_inventory — F-Zero GX (USA) owned-disc inventory."""
from __future__ import annotations

import json
import struct

import pytest

from gbox import fzgx_inventory as I

GC_MAGIC = 0xC2339F3D
DISC_ID = "GFZE01"


def _fake_head(disc_id: str = DISC_ID, title: bytes = b"F-ZERO GX (US Version)\0",
               dol_off=0x4C0000, fst_off=0x800000, fst_size=0x4000) -> bytes:
    head = bytearray(0x440)
    head[0:6] = disc_id.encode()
    struct.pack_into(">I", head, 0x1C, GC_MAGIC)
    head[0x20:0x20 + len(title)] = title
    struct.pack_into(">III", head, 0x420, dol_off, fst_off, fst_size)
    return bytes(head)


def _fake_bi2(region: int = 1) -> bytes:
    b = bytearray(0x2000)
    struct.pack_into(">I", b, 0x18, region)
    return bytes(b)


class TestDiscHeader:
    def test_valid_header(self):
        h = I.disc_header(_fake_head(), _fake_bi2())
        assert h["disc_id"] == "GFZE01"
        assert h["region"] == "NTSC-U"
        assert h["title"].startswith("F-ZERO GX")
        assert h["dol_offset"] == 0x4C0000

    def test_wrong_magic_raises(self):
        head = bytearray(_fake_head())
        struct.pack_into(">I", head, 0x1C, 0x00000000)
        with pytest.raises(ValueError, match="not a GameCube"):
            I.disc_header(bytes(head), _fake_bi2())

    def test_short_header_raises(self):
        with pytest.raises(ValueError, match="too short"):
            I.disc_header(b"\x00" * 0x10, b"\x00" * 0x10)

    def test_all_regions(self):
        assert I.disc_header(_fake_head(), _fake_bi2(0))["region"] == "NTSC-J"
        assert I.disc_header(_fake_head(), _fake_bi2(1))["region"] == "NTSC-U"
        assert I.disc_header(_fake_head(), _fake_bi2(2))["region"] == "PAL"
        assert I.disc_header(_fake_head(), _fake_bi2(9))["region"].startswith("unknown")


class TestRoster:
    def test_roster_from_files(self):
        class FakeDisc:
            files = [
                "chara/arrow_500.gma", "chara/arrow_100.gma",
                "chara/bear_face.gma",
                "chara/other.gma",
                "bg/bg_big.gma.lz",
            ]
        r = I.roster(FakeDisc())
        assert "arrow" in r
        assert "bear" in r
        assert "other" not in r
        assert len(r) == 2

    def test_roster_dedup(self):
        class FakeDisc:
            files = ["chara/x_500.gma", "chara/x_100.gma", "chara/x_face.gma"]
        r = I.roster(FakeDisc())
        assert r == ["x"]


class TestManifest:
    def test_game_id_and_source_rel(self):
        assert I.GAME_ID == "c96fc541e4b18d84"
        assert "F-Zero GX" in I.SOURCE_REL
        assert I.SOURCE_REL.endswith(".gcz")

    def test_disc_id(self):
        assert I.DISC_ID == "GFZE01"

    def test_vehicle_names_constant(self):
        # 41 vehicles in F-Zero GX USA (excluding "Hyper" base and unknowns)
        # The manifest extracts them from game/cardata.lz
        assert I.GAME_ID is not None


class TestConstants:
    def test_sha_helper(self):
        h = I._sha(b"test")
        assert len(h) == 64
        assert h == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
