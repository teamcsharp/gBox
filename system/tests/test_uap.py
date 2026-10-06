from conftest import make_cube
from gbox import uap


def test_cube_valid_and_stats():
    m = make_cube()
    assert uap.validate(m) == []
    assert uap.stats(m) == {"meshes": 1, "vertices": 8, "triangles": 12, "materials": 1, "bones": 2, "clips": 1, "nodes": 1}


def test_validator_catches_breakage():
    m = make_cube()
    m.meshes[0].indices.append(99)
    m.meshes[0].weights[0] = [0.5, 0, 0, 0]
    m.skeleton[0].parent = 1                       # cycle root<->tip
    m.animations[0].channels[0].times = [0, 0, 1]
    m.materials[0].texture = "textures/missing.png"
    m.provenance = []
    p = " | ".join(uap.validate(m, pkg="."))
    for needle in ("not a multiple of 3", "index out of range", "weights not summing", "parent chain",
                   "strictly increasing", "texture missing", "no provenance"):
        assert needle in p, needle


def test_gltf_roundtrip():
    m = make_cube()
    g = uap.to_gltf(m)
    prim = g["meshes"][0]["primitives"][0]
    assert uap.read_accessor(g, prim["attributes"]["POSITION"]) == m.meshes[0].positions
    assert uap.read_accessor(g, prim["indices"]) == m.meshes[0].indices
    assert g["accessors"][prim["attributes"]["POSITION"]]["min"] == [-1, -1, -1]
    assert g["nodes"][0]["skin"] == 0 and len(g["skins"][0]["joints"]) == 2
    ch = g["animations"][0]["channels"][0]
    assert ch["target"] == {"node": 1 + 1, "path": "rotation"}         # bones follow the 1 scene node
    assert g["extras"]["gbox"]["source"]["game_id"] == "fixture"


def test_inverse_bind_is_inverse_of_world():
    m = make_cube()
    m.skeleton[1].rotation = [0, 0, 0.3826834, 0.9238795]
    m.skeleton[1].scale = [2, 2, 2]
    ib = uap.inverse_bind(m.skeleton)
    b0, b1 = m.skeleton
    world1 = uap._mul(uap._trs(b0.translation, b0.rotation, b0.scale), uap._trs(b1.translation, b1.rotation, b1.scale))
    ident = uap._mul(ib[1], world1)
    assert all(abs(ident[i] - (1 if i % 5 == 0 else 0)) < 1e-6 for i in range(16))


def test_obj():
    o = uap.to_obj(make_cube())
    assert o.count("\nv ") == 8 and o.count("\nf ") == 12 and "f 1/1/1 2/2/2 4/4/4" in o
