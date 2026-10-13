"""ue_mesh: synthetic UE 4.24-4.27 cooked SkeletalMesh / Skeleton exports -> parsed LOD0 + rigged GLB."""
import json
import struct

import numpy as np
import pytest

import ue_synth as S
from gbox import ue_asset, ue_mesh


def _glb(path):
    b = path.read_bytes()
    assert b[:4] == b"glTF"
    jl = struct.unpack_from("<I", b, 12)[0]
    gl = json.loads(b[20:20 + jl])
    blob = b[20 + jl + 8:]

    def acc(i):
        a = gl["accessors"][i]
        v = gl["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}[a["componentType"]]
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[a["type"]]
        return np.frombuffer(blob[v["byteOffset"]:v["byteOffset"] + v["byteLength"]], dt).reshape(-1, n)
    return gl, acc


def _parse(minor=27, inlined=True, max_inf=4, **kw):
    ua, ue, ub = S.mesh_package(inlined=inlined, minor=minor, max_inf=max_inf, **kw)
    pkg = ue_asset.parse_package(ua, (4, minor))
    return pkg, ue_mesh.parse_skeletal_mesh(pkg, 1, ua, ue, ub, (4, minor))


@pytest.mark.parametrize("minor", [24, 25, 26, 27])
def test_lod0_geometry_and_skeleton(minor):
    _pkg, m = _parse(minor)
    assert len(m["positions"]) == 4 and m["triangles"].tolist() == [[0, 1, 2], [0, 2, 3]]
    assert np.allclose(m["normals"], [[0, 0, 1]] * 4, atol=0.01)
    assert np.allclose(m["uv"], [[0, 0], [1, 0], [0, 1], [1, 1]])
    assert [b["name"] for b in m["bones"]] == ["root", "spine", "head"]
    assert [b["parent"] for b in m["bones"]] == [-1, 0, 1]
    assert m["joints"][:, 0].tolist() == [0, 1, 1, 2]
    assert np.allclose(m["weights"].sum(1), 1.0)
    assert m["materials"] == [{"slot": "Body", "material": None}]
    assert ue_mesh.mesh_report(m)["vertices"] == 4


def test_lod0_streamed_from_ubulk():
    _pkg, m = _parse(inlined=False)
    assert not m["lod0_inlined"] and len(m["positions"]) == 4


def test_ubulk_missing_is_a_clear_blocker():
    ua, ue, _ub = S.mesh_package(inlined=False)
    pkg = ue_asset.parse_package(ua, (4, 27))
    with pytest.raises(ue_mesh.MeshUnsupported, match="ubulk"):
        ue_mesh.parse_skeletal_mesh(pkg, 1, ua, ue, None, (4, 27))


def test_eight_influences_keep_the_strongest_four(tmp_path):
    _pkg, m = _parse(max_inf=8)
    assert m["max_influences"] == 8
    gl, acc = _glb(ue_mesh.to_glb(m, tmp_path / "m.glb"))
    w = acc(gl["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"])
    assert np.allclose(w.sum(1), 1.0)


def test_glb_is_y_up_metres_with_skin(tmp_path):
    _pkg, m = _parse()
    gl, acc = _glb(ue_mesh.to_glb(m, tmp_path / "SK_Test.glb"))
    attrs = gl["meshes"][0]["primitives"][0]["attributes"]
    pos = acc(attrs["POSITION"])
    # UE (0, 0, 100) cm, Z up -> glTF (0, 1, 0) m, Y up
    assert np.allclose(pos[3], [0, 1, 0]) and np.allclose(pos[1], [1, 0, 0]) and np.allclose(pos[2], [0, 0, 1])
    nrm = acc(attrs["NORMAL"])
    assert np.allclose(nrm[0], [0, 1, 0], atol=0.01)
    assert acc(gl["meshes"][0]["primitives"][0]["indices"]).reshape(-1).tolist() == [0, 1, 2, 0, 2, 3]
    names = [n["name"] for n in gl["nodes"]]
    assert names[:3] == ["root", "spine", "head"]
    assert gl["skins"][0]["joints"] == [0, 1, 2]
    world = ue_mesh.bone_world_matrices(m["bones"])
    assert np.allclose(world[2][:3, 3], [0, 0.9, 0])                # head: 50 + 40 cm up


def test_skeleton_export():
    ua, ue, _ = S.mesh_package()
    pkg = ue_asset.parse_package(ua, (4, 27))
    e = pkg.exports[1]
    bones = ue_mesh.skeleton_from_export(pkg, ue_asset.export_body(pkg, e, ua, ue), e.flags)
    assert [b["name"] for b in bones] == ["root", "spine"] and bones[1]["translation"] == [0, 0, 50]


@pytest.mark.parametrize("engine,needle", [((4, 18), "SplitModelAndRenderData"), ((4, 21), "SerializeRenderItem_Legacy"),
                                           ((5, 1), "UE5"), (None, "engine version unknown"), ((3, 0), "not Unreal")])
def test_unsupported_versions_name_the_blocker(engine, needle):
    ua, ue, _ = S.mesh_package()
    pkg = ue_asset.parse_package(ua, (4, 27))
    assert needle in ue_mesh.mesh_support(engine, pkg)
    with pytest.raises(ue_mesh.MeshUnsupported, match=needle):
        ue_mesh.parse_skeletal_mesh(pkg, 1, ua, ue, None, engine)


def test_unversioned_properties_are_a_blocker():
    ua, ue, _ = S.mesh_package(unversioned_props=True)
    pkg = ue_asset.parse_package(ua, (4, 27))
    assert pkg.unversioned_properties
    with pytest.raises(ue_mesh.MeshUnsupported, match="unversioned property"):
        ue_mesh.parse_skeletal_mesh(pkg, 1, ua, ue, None, (4, 27))


def test_wrong_export_class_and_corrupt_body():
    ua, ue, _ = S.mesh_package()
    pkg = ue_asset.parse_package(ua, (4, 27))
    with pytest.raises(ue_asset.AssetError, match="not a SkeletalMesh"):
        ue_mesh.parse_skeletal_mesh(pkg, 2, ua, ue, None, (4, 27))
    with pytest.raises(ue_asset.AssetError):
        ue_mesh.parse_skeletal_mesh(pkg, 1, ua, ue[:200], None, (4, 27))


def test_tagged_property_values():
    N = S.Names()
    blob = S.tagged_props(N, [("bHasVertexColors", "BoolProperty", True), ("Count", "IntProperty", 7)])
    pkg = ue_asset.Package({"ue4_version": 522, "ue5_version": 0, "package_flags": 0}, N.names)
    props = ue_mesh.read_tagged_properties(ue_mesh.Reader(blob), pkg)
    assert props == {"bHasVertexColors": True, "Count": 7}
