"""The 3D view for an RE4-Switch (HD) tree: `decrypt_lab.hd_model_geometry`.

`/api/decrypt-lab/model-geometry` could only draw MTF `MOD` geometry, so an HD tree - which holds no `.arc` files and
no MOD at all - never produced a mesh for the page. The route now falls through to this function, which returns the
same shape the MTF path returns. These tests pin the shaping and the refusal paths with a synthetic pack, so they run
without game data.
"""
import struct

import pytest

from gbox import decrypt_lab as L

# the decoder's own synthetic BIN builder: reusing it keeps this test about the VIEW shaping, not the BIN layout
from test_re4hd_models import make_bin


def le_udas_pack(bin_blob: bytes, *, extra_slots: int = 0) -> bytes:
    """A minimal little-endian RE4-Switch pack: one DAT entry holding one BIN (and optional empty slots)."""
    n = 1 + extra_slots
    blobs = [bin_blob] + [b"" for _ in range(extra_slots)]
    base = 16 + 4 * n + 4 * n
    offs, cursor = [], base
    for b in blobs:
        offs.append(cursor)
        cursor += len(b)
    exts = b"BIN\0" + b"\0\0\0\0" * extra_slots
    dat = bytearray()
    dat += struct.pack("<II", n, 0) + b"\0" * 8
    dat += struct.pack(f"<{n}I", *offs)
    dat += exts
    for b in blobs:
        dat += b
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    hdr += struct.pack("<IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack("<I", 0xFFFFFFFF)
    hdr += b"\0" * (0x400 - len(hdr))
    return bytes(hdr) + bytes(dat)


def synthetic_bin() -> bytes:
    """A tiny BIN the real decoder accepts: three vertices, one triangle, one bone."""
    return make_bin(n=3, bones=((0, 0xFF),), prims=((5, 3),), aux="fixed")


@pytest.fixture
def hd_tree(tmp_path):
    em = tmp_path / "bio4" / "em"
    em.mkdir(parents=True)
    (em / "em21.udas").write_bytes(le_udas_pack(synthetic_bin()))
    return tmp_path


def test_an_hd_tree_returns_the_same_shape_the_mtf_path_returns(hd_tree):
    out = L.hd_model_geometry(hd_tree, "bio4/em/em21.udas", 0)
    assert out is not None and out["edition"] == "hd"
    assert out["entry"] == "bio4/em/em21.udas#BIN0"
    assert out["bone_count"] == 1 and out["triangle_count"] == 1
    mesh = out["meshes"][0]
    assert mesh["drawn"] == mesh["count"] == 3
    assert len(mesh["positions"]) == 9 and len(mesh["normals"]) == 9 and len(mesh["uvs"]) == 6
    assert out["triangles"] == [0, 1, 2]
    # the reported bounds are the mesh's own min/max, not a separate guess
    pts = [mesh["positions"][i:i + 3] for i in range(0, 9, 3)]
    assert out["bounds"] == [[round(min(p[k] for p in pts), 2) for k in range(3)],
                             [round(max(p[k] for p in pts), 2) for k in range(3)]]
    assert len(out["skeleton"]["bones"]) == 1


def test_a_pack_named_the_way_the_extraction_tab_lists_it_is_accepted(hd_tree):
    # switch_inventory names packs relative to bio4/ ("em/em21.udas"); the route takes root-relative paths. Both work.
    relative = L.hd_model_geometry(hd_tree, "em/em21.udas", 0)
    rooted = L.hd_model_geometry(hd_tree, "bio4/em/em21.udas", 0)
    assert relative is not None and relative["positions"] == rooted["positions"]
    assert relative["pack"] == "bio4/em/em21.udas" and relative["entry"].startswith("bio4/em/em21.udas#BIN0")


def test_a_tree_without_bio4_is_not_an_hd_tree(tmp_path):
    assert L.hd_model_geometry(tmp_path, "bio4/em/em21.udas", 0) is None


def test_the_budget_caps_what_the_view_receives(hd_tree):
    out = L.hd_model_geometry(hd_tree, "bio4/em/em21.udas", 0, budget=2)
    assert out["meshes"][0]["drawn"] == 2
    assert len(out["meshes"][0]["positions"]) == 6


def test_a_missing_slot_or_pack_is_reported_not_guessed(hd_tree):
    with pytest.raises(ValueError, match="no BIN at slot 7"):
        L.hd_model_geometry(hd_tree, "bio4/em/em21.udas", 7)
    with pytest.raises(FileNotFoundError):
        L.hd_model_geometry(hd_tree, "bio4/em/nope.udas", 0)
    with pytest.raises(ValueError, match="leaves the extracted tree"):
        L.hd_model_geometry(hd_tree, "../outside.udas", 0)


def test_a_corrupt_pack_is_refused_by_the_decoder_not_served_as_a_mesh(hd_tree):
    em = hd_tree / "bio4" / "em"
    (em / "em99.udas").write_bytes(le_udas_pack(b"\0\0\0\0" + b"\0" * 200))
    with pytest.raises(ValueError):
        L.hd_model_geometry(hd_tree, "bio4/em/em99.udas", 0)
