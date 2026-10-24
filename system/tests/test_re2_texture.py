import os
import struct
from pathlib import Path

import pytest

from gbox import re2_texture as rt

ROM_PATH = Path(os.environ.get("GBOX_RE2_N64_ROM", Path.home() / "gbox-cache" / "46eec2fc627c8f58" / "rom.z64"))


def _synth(w=4, h=2, ncol=16, mode=1):
    return struct.pack(">HHHHHHI", 0xBE1E, 32, w, h, mode, ncol, 0) + bytes(2 * ncol) + bytes(range(w * h))


def test_synthetic_parse_and_roundtrip():
    raw = _synth()
    t = rt.parse_texture_asset(1, raw)
    assert t.valid and (t.width, t.height, t.ncolors) == (4, 2, 16)
    assert rt.build_texture_asset(t) == raw


def test_synthetic_rejects_bad():
    assert not rt.parse_texture_asset(1, _synth()[:-1]).valid
    bad = bytearray(_synth()); bad[0] = 0
    assert not rt.parse_texture_asset(1, bytes(bad)).valid
    assert not rt.parse_texture_asset(1, b"\0" * 4).valid


def test_rgba5551():
    assert rt.rgba5551_to_rgba8(0xFFFF) == (255, 255, 255, 255)
    assert rt.rgba5551_to_rgba8(0) == (0, 0, 0, 0)


@pytest.mark.skipif(not ROM_PATH.exists(), reason="owned RE2 N64 rom not cached")
def test_owned_rom_all_textures():
    r = rt.probe_all(ROM_PATH)
    assert r["total"] == 550 and r["valid"] == 550 and not r["bad"]
    assert r["roundtrip_identical"] == 550
