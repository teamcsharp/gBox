"""Focused tests for gbox.ac4_inventory against the owned Armored Core 4 ISO."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gbox import ac4_inventory as ac4

ISO = Path("/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Armored Core 4.iso")

pytestmark = pytest.mark.skipif(not ISO.exists(), reason="Armored Core 4 ISO not mounted")

EXPECTED_DEFAULT_XEX_SHA256 = "e2f117e053921784f354fa5811ab7d3ea99364c0b27f5e73dc3b5005d537be11"
EXPECTED_TOP_DIRS = {
    "bullet", "ane", "airesource", "bind", "common", "cap", "dbmenu", "param",
    "lang", "enemy", "effect", "garage", "model", "menu", "movie", "shader",
    "sfx", "sound", "system",
}


def test_descriptor():
    root_sector, root_len = ac4.descriptor(ISO)
    assert root_sector == 264
    assert root_len == 412


def test_root_listing_has_executable_and_asset_dirs():
    entries = list(ac4.walk(ISO, max_depth=0))
    names = {e.name for _, e in entries}
    assert "default.xex" in names
    assert EXPECTED_TOP_DIRS <= names


def test_default_xex_identity():
    entry = next(e for _, e in ac4.walk(ISO, max_depth=0) if e.name == "default.xex")
    assert entry.sector == 265
    assert entry.size == 11_808_768
    blob = ac4.extract(ISO, entry.sector, entry.size)
    assert blob[:4] == b"XEX2"
    assert ac4.sha256_bytes(blob) == EXPECTED_DEFAULT_XEX_SHA256


def test_asset_format_census_depth1():
    """One level down, the param/shader/sound native formats appear."""
    exts: dict[str, int] = {}
    for _parts, entry in ac4.walk(ISO, max_depth=1):
        if entry.is_dir:
            continue
        leaf = entry.name.rsplit("/", 1)[-1]
        ext = leaf.rsplit(".", 1)[-1].lower() if "." in leaf else "(none)"
        exts[ext] = exts.get(ext, 0) + 1
    # Native formats observed at depth 1 in this build.
    assert exts.get("bin", 0) > 0      # params / bullet physics
    assert exts.get("fxo", 0) > 0      # compiled shaders
    assert exts.get("xwb", 0) > 0      # sound bank containers


def test_rmb_mesh_and_anc_animation_formats():
    """Deep-but-targeted checks: .rmb meshes and .anc animations exist in place."""
    model_poly_m000 = ac4.resolve(ISO, ("model", "poly", "m000"))
    assert model_poly_m000 is not None
    names = {e.name for e in ac4.parse_dir(ac4.extract(ISO, *model_poly_m000))}
    assert any(n.endswith(".rmb") for n in names)

    ane_ac = ac4.resolve(ISO, ("ane", "ac"))
    assert ane_ac is not None
    anames = {e.name for e in ac4.parse_dir(ac4.extract(ISO, *ane_ac))}
    assert any(n.endswith(".anc") for n in anames)


def test_parse_dir_4byte_alignment():
    # Synthesized directory buffer matching the observed layout:
    # header 14 bytes + name, padded with 0xff to a 4-byte boundary.
    def ent(sector, size, attr, name):
        raw = struct.pack("<HHIIBB", 0, 0, sector, size, attr, len(name)) + name.encode("latin-1")
        pad = (-len(raw)) % 4
        return raw + b"\xff" * pad
    buf = ent(265, 11808768, 0x20, "default.xex") + ent(6031, 316, 0x10, "bullet")
    parsed = ac4.parse_dir(buf)
    assert [(e.name, e.sector, e.size, e.is_dir) for e in parsed] == [
        ("default.xex", 265, 11808768, False),
        ("bullet", 6031, 316, True),
    ]
