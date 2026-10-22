"""Focused tests for the Tetris DS archive-asset binding (#2268)."""
import hashlib
import json
import os
from pathlib import Path

from gbox.tetris_ds_overlay import (OVERLAY_ASSETS, PROFILE_PATH, SUPPORT_ASSETS,
                                    asset_digests, pinned, verify)

REAL_ROM = Path(os.environ.get(
    "GBX_TETRIS_DS_ROM",
    "/home/ehm_eckx/.hermes/cache/scratch/tetris_ds/rom/0366 - Tetris DS (U)(WRG).nds"))


class FakeRom:
    def __init__(self, blobs):
        self.blobs = {k.lower(): v for k, v in blobs.items()}

    def paths(self):
        return list(self.blobs)

    def read(self, path):
        return self.blobs[path.lower()]


def test_source_pins_every_tracked_asset():
    pins = pinned()
    for name in list(OVERLAY_ASSETS) + list(SUPPORT_ASSETS):
        assert name in pins["assets"], name
        assert len(pins["assets"][name]["sha256"]) == 64
        assert pins["assets"][name]["size"] > 0
    assert len(pins["arm9_sha256"]) == 64
    assert len(pins["rom_sha256"]) == 64


def test_profile_file_agrees_with_source_pins_when_present():
    if not PROFILE_PATH.exists():
        return
    prof = json.loads(PROFILE_PATH.read_text())
    assert prof["rom_sha256"] == pinned()["rom_sha256"]
    for key in ("arm9_sha256",):
        if key in prof:
            assert prof[key] == pinned()[key]
    for name, a in prof.get("archive_assets", {}).items():
        assert a["sha256"] == pinned()["assets"][name]["sha256"]


def test_asset_digests_hashes_only_tracked_members():
    rom = FakeRom({"ct.srl": b"standard", "od.srl": b"option", "readme.txt": b"noise"})
    digests = asset_digests(rom)
    assert digests["ct.srl"]["sha256"] == hashlib.sha256(b"standard").hexdigest()
    assert digests["od.srl"]["size"] == 6
    assert "readme.txt" not in digests
    assert "pt.srl" not in digests


def test_verify_flags_a_mismatched_revision():
    rom = FakeRom({"ct.srl": b"standard", "od.srl": b"option", "pt.srl": b"party",
                   "push1.pak": b"p", "quiz.dat": b"q", "title.pak": b"t"})
    result = verify(rom, b"\x00" * 0x40)
    assert result["ok"] is False
    assert any(m["field"] == "rom_sha256" for m in result["mismatches"])


def test_real_rom_matches_the_pinned_digests():
    if not REAL_ROM.exists():
        print("skip: owned ROM not present at", REAL_ROM)
        return
    from gbox.tetris_ds import NDSRom
    data = REAL_ROM.read_bytes()
    result = verify(NDSRom(data), data)
    assert result["ok"], result["mismatches"]
