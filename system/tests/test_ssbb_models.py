"""Tests for gbox.ssbb_models (Super Smash Bros. Brawl PAC/BRRES/MDL0/TEX0).

The real-data tests use the operator's extracted Brawl disc (``.tmp/brawl``) and are skipped when it is absent,
so CI stays green; the container/palette/texture/format tests use small synthetic fixtures built here.
"""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import characters, ssbb_models as S

BRAWL = Path(__file__).resolve().parents[2] / ".tmp" / "brawl" / "files" / "DATA" / "files" / "fighter" / "fighter"
SONIC = BRAWL / "sonic" / "FitSonic00.pac"
MARIO = BRAWL / "mario" / "FitMario00.pac"
needs_brawl = pytest.mark.skipif(not SONIC.is_file(), reason="Brawl disc files are not extracted under .tmp/brawl")


# ---------------------------------------------------------------------------- synthetic fixtures

def _arc(name: str, children: list[tuple[int, int, bytes]]) -> bytes:
    """A minimal Brawl PAC: 0x40-byte header, then 0x20-byte child headers with inline payloads."""
    out = bytearray(b"ARC\0" + struct.pack(">HHII", 0x0101, len(children), 0, 0))
    out += name.encode("ascii").ljust(0x30, b"\0")
    for ty, sub, payload in children:
        out += struct.pack(">hhi", ty, sub, len(payload)) + bytes([0]) + struct.pack(">h", 0xFF)
        out += bytes(0x20 - 11)
        out += payload
        out += bytes(-len(payload) % 0x20)
    return bytes(out)


def _tex0(w: int, h: int, fmt: int, pixels: bytes, name: str = "TEST") -> bytes:
    """A minimal TEX0 resource at offset 0 (0x40-byte header, name string after it, data at 0x40)."""
    header = bytearray(0x40)
    header[0:4] = b"TEX0"
    struct.pack_into(">I", header, 4, 0x40 + len(pixels))
    struct.pack_into(">I", header, 8, 1)
    struct.pack_into(">I", header, 0x10, 0x40)
    struct.pack_into(">I", header, 0x14, 0x40 + len(pixels))
    struct.pack_into(">HH", header, 0x1C, w, h)
    struct.pack_into(">II", header, 0x20, fmt, 1)
    return bytes(header) + pixels + name.encode("ascii") + b"\0"


def _plt0(entries: list[int], fmt: int = 2) -> bytes:
    """A minimal PLT0 resource at offset 0 (0x40 header, u16 entries after it)."""
    header = bytearray(0x40)
    header[0:4] = b"PLT0"
    struct.pack_into(">I", header, 4, 0x40 + 2 * len(entries))
    struct.pack_into(">I", header, 8, 1)
    struct.pack_into(">i", header, 0x10, 0x40)
    struct.pack_into(">I", header, 0x14, 0x40 + 2 * len(entries))       # name after the entries
    struct.pack_into(">I", header, 0x18, fmt)
    struct.pack_into(">h", header, 0x1C, len(entries))
    return bytes(header) + b"".join(struct.pack(">H", v) for v in entries) + b"TEST\0"


def test_pac_container_lists_children():
    payload0 = b"TEST" + b"\0" * 0x1C
    payload1 = b"ANIM" + b"\0" * 0x3C
    data = _arc("FitTest00", [(2, 0, payload0), (4, 3, payload1)])
    files = S.pac_files(data)
    assert [f["type"] for f in files] == [2, 4]
    assert [f["index"] for f in files] == [0, 3]
    assert [f["size"] for f in files] == [len(payload0), len(payload1)]
    assert [f["magic"] for f in files] == ["TEST", "ANIM"]
    assert files[0]["offset"] == 0x40 + 0x20
    assert files[1]["offset"] == 0x40 + 0x20 + 0x20 + len(payload0)
    assert files[0]["archive"] == "FitTest00"
    assert all(f["redirect"] == 0xFF and f["inline"] for f in files)


def test_plt0_rgb5a3_entries():
    # RGB5A3: 0xFFFF is opaque white (RGB555 form), 0x0000 is transparent black (RGB4A3 form)
    pal = S.plt0_entries(_plt0([0xFFFF, 0x0000], fmt=2), 0)
    assert pal.shape == (2, 4) and pal.dtype == np.uint8
    assert tuple(pal[0]) == (255, 255, 255, 255)
    assert tuple(pal[1]) == (0, 0, 0, 0)


def test_tex0_i4_8x8():
    tile = bytearray()
    for row in range(8):
        for col in range(0, 8, 2):
            tile.append(((row * 8 + col) % 16) << 4 | ((row * 8 + col + 1) % 16))
    img = S.tex0_image(_tex0(8, 8, 0x00, bytes(tile)), 0)
    assert img.shape == (8, 8, 4)
    assert tuple(img[0, 0]) == (0, 0, 0, 255)
    assert tuple(img[0, 1]) == (17, 17, 17, 255)
    assert tuple(img[1, 0]) == (8 * 17, 8 * 17, 8 * 17, 255)


def test_tex0_cmpr_8x8():
    # four DXT1 blocks: TL solid red, the other three solid white
    red = struct.pack(">HHI", 0xF800, 0x001F, 0)                       # c0 > c1, all indices 0 -> c0
    white = struct.pack(">HHI", 0xFFFF, 0x0000, 0)
    img = S.tex0_image(_tex0(8, 8, 0x0E, red + white * 3), 0)
    assert img.shape == (8, 8, 4)
    assert tuple(int(v) for v in img[0, 0]) == (255, 0, 0, 255)
    assert tuple(int(v) for v in img[0, 4]) == (255, 255, 255, 255)
    assert tuple(int(v) for v in img[4, 0]) == (255, 255, 255, 255)
    assert tuple(int(v) for v in img[7, 7]) == (255, 255, 255, 255)


def test_tex0_ci8_needs_palette():
    pixels = bytes(range(64))                                          # one 8x8 CI8 tile
    pal = np.array([[10, 20, 30, 255], [40, 50, 60, 255]], np.uint8)
    img = S.tex0_image(_tex0(8, 8, 0x09, pixels), 0, {"TEST": pal})
    assert tuple(int(v) for v in img[0, 0]) == (10, 20, 30, 255)
    assert tuple(int(v) for v in img[0, 1]) == (40, 50, 60, 255)
    with pytest.raises(ValueError):
        S.tex0_image(_tex0(8, 8, 0x09, pixels), 0)


def test_attribute_format_widths():
    # bits 9..10/11..12/13..14/15..16 are (format - 1): 2 = u8 index, 3 = u16 index, 0 = absent
    obj = {"vtx_fmt_lo": (2 << 9) | (3 << 11) | (2 << 13), "vtx_fmt_hi": (2 << 0) | (3 << 2)}
    got = S.Mdl0._attr_formats(obj)
    assert got == [("pos", 0, 1), ("nrm", 0, 2), ("col", 0, 1), ("uv", 0, 1), ("uv", 1, 2)]
    with pytest.raises(ValueError):
        S.Mdl0._attr_formats({"vtx_fmt_lo": 1 << 9, "vtx_fmt_hi": 0})


def test_roles_from_bones_brawl_scheme():
    names = ["TopN", "TransN", "HipN", "WaistN", "BustN", "NeckN", "HeadN", "LShoulderN", "LShoulderJ", "LArmJ",
             "LHandN", "RShoulderN", "RShoulderJ", "RArmJ", "RHandN", "LLegJ", "LKneeJ", "LFootJ", "RLegJ",
             "RKneeJ", "RFootJ", "LToeN", "RToeN"]
    roles = S.roles_from_bones(names)
    assert roles == {"hip": "HipN", "chest": "WaistN", "neck": "NeckN", "head": "HeadN", "l_clav": "LShoulderN",
                     "l_upper": "LShoulderJ", "l_fore": "LArmJ", "l_hand": "LHandN", "r_clav": "RShoulderN",
                     "r_upper": "RShoulderJ", "r_fore": "RArmJ", "r_hand": "RHandN", "l_thigh": "LLegJ",
                     "l_shin": "LKneeJ", "l_foot": "LFootJ", "r_thigh": "RLegJ", "r_shin": "RKneeJ",
                     "r_foot": "RFootJ"}


def test_roles_from_bones_never_invents():
    # Kirby's skeleton has no waist/neck/head: BodyN is the only torso bone, everything else stays missing
    roles = S.roles_from_bones(["TopN", "HipN", "BodyN", "LLegJ", "RFootJ"])
    assert roles == {"hip": "HipN", "chest": "BodyN", "l_thigh": "LLegJ", "r_foot": "RFootJ"}


# ---------------------------------------------------------------------------- real fighter data

@needs_brawl
def test_real_pac_members():
    files = S.pac_files(SONIC.read_bytes())
    assert len(files) == 3
    assert [f["magic"] for f in files] == ["bres", "bres", "bres"]
    assert files[0]["resources"] == ["FitSonic00"]
    assert files[0]["size"] == 0x61E80 and files[0]["offset"] == 0x60
    assert files[2]["index"] == 10                              # the shadow model (FitSonicShd)
    assert "FitSonicShd" in files[2]["resources"]


@needs_brawl
def test_real_brres_models():
    blob = S._pac_brres(SONIC.read_bytes())[0][1]
    parsed = S.brres_models(blob)
    assert parsed["folders"] == {"3DModels(NW4R)": ["FitSonic00"]}
    assert len(parsed["models"]) == 1
    model = parsed["models"][0]
    assert model["name"] == "FitSonic00" and model["version"] == 9
    assert parsed["textures"] == []                             # textures live in the PAC's second BRRES


@needs_brawl
def test_real_mdl0_props_and_bones():
    blob = S._pac_brres(SONIC.read_bytes())[0][1]
    parsed = S.brres_models(blob)
    m = S.Mdl0(blob, parsed["models"][0]["offset"])
    assert m.version == 9 and m.props["vertex_count"] == 16806 and m.props["triangle_count"] == 12310
    assert len(m.bones) == 83
    assert len(m.node_table) == 368
    assert m.props["node_count"] == 368
    for i, b in enumerate(m.bones):
        assert -1 <= b["parent"] < len(m.bones)
        assert b["parent"] != i                                 # no self-parent
    assert "HipN" in m.bone_names and "LFootJ" in m.bone_names


@needs_brawl
def test_real_decode_indices_and_uvs():
    blob = S._pac_brres(SONIC.read_bytes())[0][1]
    m = S.Mdl0(blob, S.brres_models(blob)["models"][0]["offset"])
    textures, _ = S._collect_textures([b for _l, b in S._pac_brres(SONIC.read_bytes())])
    prims = m.decode(textures=textures)
    assert prims, "Sonic decoded no primitives"
    skipped_verts = sum(o["num_vertices"] for o in m.objects if m._is_effect_object(o))
    assert sum(len(p["tris"]) for p in prims) == m.props["triangle_count"] - 960   # minus the spin-ball mesh
    assert sum(len(p["pos"]) for p in prims) == m.props["vertex_count"] - skipped_verts
    assert skipped_verts == 1024
    for p in prims:
        n = len(p["pos"])
        assert len(p["nrm"]) == n and len(p["uv"]) == n
        assert np.isfinite(p["pos"]).all() and np.isfinite(p["uv"]).all()
        t = p["tris"]
        assert t.size and t.min() >= 0 and t.max() < n
        assert p["J"].shape == (n, 4) and p["W"].shape == (n, 4)
        assert p["owner"].shape == (n,)
        assert 0 <= p["owner"].min() and p["owner"].max() < len(m.bones)
        assert np.isfinite(p["W"]).all()
    assert sum(1 for p in prims if p["tex"] is not None) > 20
    assert m.skipped == ["polygon30"]                           # the spin ball is an animation-only prop


@needs_brawl
@pytest.mark.parametrize("pac, expected_roles", [(SONIC, 15), (MARIO, 18)])
def test_extract_character_round_trips_through_rig(tmp_path, pac, expected_roles):
    out = tmp_path / f"{pac.parent.name}_brawl.glb"
    rep = S.extract_character(pac, out, name=pac.parent.name)
    assert rep["triangles"] > 1000 and rep["vertices"] > 1000
    assert rep["joints"] == rep["bones"] > 0
    assert rep["glb_bytes"] == out.stat().st_size > 0
    assert rep["textures"] > 0 and rep["texture_names"]
    assert rep["roles"]
    assert len(rep["roles"]) + len(rep["roles_missing"]) == 18     # retarget_profile.ROLES
    stats = characters.model_stats(out)
    assert stats["triangles"] == rep["triangles"]
    assert stats["rig"]["skinned"] and stats["rig"]["joints"] == rep["joints"]
    rig = characters.rig_from_gltf(out, rep["roles"])
    assert len(rig["joints"]) == rep["joints"]
    assert len(rig["roles"]) == expected_roles
    assert len(rig["prims"]) == rep["primitives"] > 0
    for prim in rig["prims"]:
        assert len(prim["pos"]) and len(prim["tris"]) and prim["tris"].shape[1] == 3
        assert prim["tex"] is not None and prim["tex"].ndim == 3 and prim["tex"].shape[2] == 4
