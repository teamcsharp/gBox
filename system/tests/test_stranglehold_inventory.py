"""Stranglehold cooked-package inventory (#1410): summary / chunk parsing on a synthetic Midway package, mesh roles, and
the real CookedPS3 folder when the QuickSwap share is reachable (skipped otherwise)."""
import struct
import zlib

import pytest

from gbox import stranglehold_inventory as I


def _chunk(data: bytes) -> bytes:
    comp = zlib.compress(data)
    return struct.pack(">IIII", I.TAG, 0x10000, len(comp), len(data)) + struct.pack(">II", len(comp), len(data)) + comp


def midway_package(mesh="tequila01_lod00_skmesh") -> bytes:
    """A chunked v375/licensee-25 package: summary + chunk table, then one compressed chunk with the tables."""
    names = [b"None", b"Core", b"Class", b"SkeletalMesh", b"Engine", mesh.encode(), b"Default__SkeletalMesh"]
    nt = b"".join(struct.pack(">i", len(n) + 1) + n + b"\x00" + b"\x00" * 8 for n in names)
    imp = struct.pack(">iiiiiii", 1, 0, 2, 0, 0, 3, 0)    # Core.Class SkeletalMesh
    def export(name_idx, size, off):
        return (struct.pack(">iiiiii", -1, 0, 0, name_idx, 0, 0) + b"\x00" * 8 + struct.pack(">ii", size, off)
                + struct.pack(">iii", 0, 0, 0) + b"\x00" * 16)
    pre = struct.pack(">II", I.TAG, 0x00190177) + struct.pack(">I", 0) + struct.pack(">i", 5) + b"None\x00"
    summary_size = len(pre) + 32 + 16 + 4 + 12 + 16 + 16
    no = summary_size
    io = no + len(nt)
    eo = io + len(imp)
    ex = export(5, 64, 0x10000) + export(6, 0, 0)
    dep = eo + len(ex)
    tables = nt + imp + ex
    chunk = _chunk(tables)
    head = (pre + struct.pack(">8I", 0x02880009, len(names), no, 2, eo, 1, io, dep) + b"\x11" * 16
            + struct.pack(">I", 1) + struct.pack(">III", 2, len(names), 0)
            + struct.pack(">IIII", 2605, 32, 1, 1) + struct.pack(">IIII", summary_size, len(tables), summary_size, len(chunk)))
    assert len(head) == summary_size
    return head + chunk


def test_summary_and_tables_of_a_chunked_package(tmp_path):
    p = tmp_path / "char_tequila.xxx"
    p.write_bytes(midway_package())
    s = I.read_summary(p.read_bytes()[:4096])
    assert s["layout"] == "chunked" and s["compression"] == "zlib" and (s["version"], s["licensee"]) == (375, 25)
    assert (s["engine"], s["cooker"], len(s["chunks"])) == (2605, 32, 1)
    r = I.scan_package(p, tmp_path)
    assert r["skeletal_meshes"] == ["tequila01_lod00_skmesh"]           # the class default object is not a mesh
    assert r["mesh_roles"] == {"player": 1} and r["kind"] == "character" and r["exports"] == 2
    assert r["skeletal_mesh_bytes"] == 64


def test_fully_compressed_and_bad_packages(tmp_path):
    raw = midway_package()
    with pytest.raises(I.FormatError):
        I.read_summary(b"\x00" * 64)
    full = struct.pack(">II", I.TAG, 0x10000) + struct.pack(">II", 10, 20)
    assert I.read_summary(full)["layout"] == "fully_compressed"
    with pytest.raises(I.FormatError, match="tag"):
        I.decompress_chunk(b"\x00" * 32)
    assert I.decompress_chunk(_chunk(raw[:100])) == raw[:100]


@pytest.mark.parametrize("name,role", [
    ("tequila_suit_lod00_MP_skmesh", "player"), ("dc_assaultClass03_lod00_skmesh", "enemy"),
    ("Imperial9_sniperClass01_lod00_skmesh_MP", "enemy"), ("SMGClass04_lod00_skmesh", "enemy"),
    ("damonZakarov_lod00_skmesh", "boss"), ("depangClass_lod00_skmesh", "boss"), ("Wong_lod00_cine", "boss"),
    ("johnWoo_lod00_MP_skmesh", "character"), ("asianMale03_suit_lod00_skmesh", "civilian"),
    ("wpn_rifle_ak47_skmesh", "weapon"), ("veh_hind_skmesh", "vehicle"), ("door_hinge_left", "prop")])
def test_mesh_roles(name, role):
    assert I.mesh_role(name) == role


def test_mesh_variants():
    assert I.mesh_variant("tequila01_lod00_MP_skmesh") == "multiplayer"
    assert I.mesh_variant("assaultClass01_lod00_skmesh_MP") == "multiplayer"
    assert I.mesh_variant("tequila01_lod00_cine") == "cinematic"
    assert I.mesh_variant("tequila01_lod00_skmesh") == "game"


ROOT = I.find_root()


@pytest.mark.skipif(ROOT is None, reason="Stranglehold CookedPS3 (QuickSwap2 share) not reachable")
def test_real_character_packages():
    r = I.scan_package(ROOT / "char_tequila.xxx", ROOT)
    assert r["layout"] == "chunked" and r["compression"] == "zlib" and (r["version"], r["licensee"]) == (375, 25)
    assert r["skeletal_meshes"] == ["tequila01_lod00_skmesh"] and r["mesh_roles"] == {"player": 1}
    e = I.scan_package(ROOT / "char_GK_Elite_2_MP.xxx", ROOT)
    assert e["mesh_roles"] == {"enemy": 1} and e["skeletal_meshes"] == ["eliteClass02_lod00_skmesh_MP"]
    assert e["anim_sequences"] > 0 and e["textures"] > 0
