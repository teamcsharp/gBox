import json, os, struct
import numpy as np
import pytest
from gbox.formats import glb_export as G, wmb_platinum as W

D = os.environ.get("GBOX_B2_DIR", os.path.expanduser("~/.hermes/cache/scratch/b2"))
PAIR = [os.path.join(D, "pl0000_pl0000." + e) for e in ("wmb", "wtp", "wta")]
HAVE = all(os.path.exists(x) for x in PAIR)


def parse_glb(b):
    magic, ver, total = struct.unpack_from("<III", b, 0)
    assert magic == 0x46546C67 and ver == 2 and total == len(b)
    jl, jt = struct.unpack_from("<II", b, 12)
    assert jt == 0x4E4F534A
    j = json.loads(b[20:20 + jl])
    bl, bt = struct.unpack_from("<II", b, 20 + jl)
    assert bt == 0x004E4942
    return j, b[28 + jl:28 + jl + bl]


def test_png_bytes_roundtrip_header():
    img = np.zeros((2, 3, 4), np.uint8)
    p = G.png_bytes(img)
    assert p[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", p[16:24]) == (3, 2)


def test_parse_wta_rejects_bad_magic():
    with pytest.raises(ValueError):
        G.parse_wta(b"XXXX" + b"\0" * 64)


@pytest.mark.skipif(not HAVE, reason="real Bayonetta 2 pl0000 wmb/wtp/wta not available")
def test_real_materials_and_glb_structure():
    wmb, wtp, wta = [open(x, "rb").read() for x in PAIR]
    ta = G.parse_wta(wta)
    assert ta["count"] == 38
    mats = W.parse_materials(wmb, ta["ids"])
    assert [m.index for m in mats] == list(range(13))
    assert all(m.texture_ids for m in mats)
    # every batch material index is a valid record
    for m in W.parse_meshes(wmb):
        for b in m.batches:
            assert 0 <= b.material < len(mats)
    j, blob = parse_glb(G.build_glb(wmb, wtp, wta, max_tex_dim=256))
    assert len(j["skins"][0]["joints"]) == 118
    assert len(j["meshes"]) == 19
    assert len(j["materials"]) == 13 and j["images"]
    for a in j["accessors"]:
        v = j["bufferViews"][a["bufferView"]]
        assert v["byteOffset"] + v["byteLength"] <= len(blob)
    for me in j["meshes"]:
        for pr in me["primitives"]:
            n = j["accessors"][pr["attributes"]["POSITION"]]["count"]
            ia = j["accessors"][pr["indices"]]
            v = j["bufferViews"][ia["bufferView"]]
            ix = np.frombuffer(blob, "<u4", ia["count"], v["byteOffset"])
            assert ix.max() < n
            ja = j["accessors"][pr["attributes"]["JOINTS_0"]]
            jv = j["bufferViews"][ja["bufferView"]]
            jj = np.frombuffer(blob, "<u2", ja["count"] * 4, jv["byteOffset"])
            assert jj.max() < 118
