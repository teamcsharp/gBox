"""Pinned BRES resource layout for Metroid: Other M (USA) FST file '0'.

This run resolved the previously suspected BRES gap 0x59500..0x7AF30
(a hypothesized 16-bit packed per-vertex / vertex-color stream): it is
TEX0 texture data spanning the ashimawari / ashimawari_bm / ball_n
blocks, so there is no separate vertex-color block and no contiguous
triangle index array in the BRES. The layout below is authoritative
(verified against the real file, sha256 817f8a7ad8baaae7b8818181cb66c17c02532f1e2633ee1ceba4df6e4145f30).
"""
import os
import struct

import pytest

from gbox.formats import omchr

BRES = os.environ.get("OM_SAMUS_BRES", "")

FOLDERS = {
    "3DModels(NW4R)": [
        ("morph_ball_normal", "MDL0", 0x00000240),
        ("samus_normal", "MDL0", 0x0000F6E0),
    ],
    "Textures(NW4R)": [
        ("ashimawari", "TEX0", 0x000568C0),
        ("ashimawari_bm", "TEX0", 0x00066900),
        ("ball_n", "TEX0", 0x00076940),
        ("ball_n_bm", "TEX0", 0x0007E980),
        ("environment", "TEX0", 0x0009E9C0),
        ("environment_eye", "TEX0", 0x000A2A00),
        ("samus_arm", "TEX0", 0x000A4A40),
        ("samus_arm_bm", "TEX0", 0x000C4A80),
        ("samus_hips", "TEX0", 0x000E4AC0),
        ("samus_hips_bm", "TEX0", 0x00104B00),
    ],
    "AnmClr(NW4R)": [
        ("morph_ball__blink_off", "CLR0", 0x00124B40),
        ("morph_ball__blink_on_non_reg", "CLR0", 0x00124BA0),
        ("morph_ball__normal_hit_non_reg", "CLR0", 0x00124CA4),
        ("morph_ball__super_bomb_in_low_hp_non_reg", "CLR0", 0x00124D58),
        ("morph_ball__super_bomb_in_normal_hp_non_reg", "CLR0", 0x00124E64),
        ("morph_ball__super_bomb_out_low_hp_non_reg", "CLR0", 0x00124F70),
        ("morph_ball__super_bomb_out_normal_hp_non_reg", "CLR0", 0x0012507C),
        ("samus__blink_off", "CLR0", 0x00125188),
        ("samus__blink_on_non_reg", "CLR0", 0x001251E8),
        ("samus__normal_hit_non_reg", "CLR0", 0x001252EC),
    ],
    "AnmScn(NW4R)": [
        ("DefaultScene", "SCN0", 0x001253E0),
    ],
}


def _b():
    if not BRES or not os.path.exists(BRES):
        pytest.skip("OM_SAMUS_BRES not set")
    with open(BRES, "rb") as f:
        return f.read()


def test_magic_and_size():
    b = _b()
    assert b[:4] == b"bres"
    assert len(b) == 0x126580  # 1,205,632 B (FST size field, 32B tail pad after last block)


def test_folder_set():
    assert set(omchr.parse_bres(_b())) == set(FOLDERS)


def test_3dmodels():
    got = omchr.parse_bres(_b())["3DModels(NW4R)"]
    assert sorted(got, key=lambda r: r[2]) == FOLDERS["3DModels(NW4R)"]


def test_textures_exact_offsets():
    got = omchr.parse_bres(_b())["Textures(NW4R)"]
    assert sorted(got, key=lambda r: r[2]) == FOLDERS["Textures(NW4R)"]


def test_anm_blocks():
    b = _b()
    got = omchr.parse_bres(b)
    assert sorted(got["AnmClr(NW4R)"], key=lambda r: r[2]) == FOLDERS["AnmClr(NW4R)"]
    assert got["AnmScn(NW4R)"] == FOLDERS["AnmScn(NW4R)"]


def test_resource_magics_at_offsets():
    b = _b()
    for folder in FOLDERS.values():
        for _name, magic, off in folder:
            assert b[off:off + 4] == magic.encode(), (magic, hex(off))


def test_samus_mdl0_block_contiguous_to_first_tex0():
    b = _b()
    import gbox.formats.nw4r_mdl0 as mdl
    m = mdl.parse_mdl0(b, 0xF6E0)
    assert 0xF6E0 + m["size"] == 0x568C0  # ends exactly where ashimawari TEX0 starts
    for _n, magic, off in FOLDERS["3DModels(NW4R)"] + FOLDERS["Textures(NW4R)"]:
        assert not (0xF6E0 < off < 0x568C0)
    m2 = mdl.parse_mdl0(b, 0x240)
    assert m2["num_bones"] > 0


def test_former_gap_is_texture_data():
    # 0x59500..0x7AF30 was misread as a packed per-vertex stream; both
    # endpoints fall inside TEX0 blocks -> no vertex-color block exists.
    assert 0x568C0 < 0x59500 < 0x66900   # inside ashimawari
    assert 0x76940 < 0x7AF30 < 0x7E980   # inside ball_n
