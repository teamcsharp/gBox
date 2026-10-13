"""gbox.pe2_models: Parasite Eve II model format (#559). Synthetic 19-bone body; the owned disc only when mounted."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import pe2_inventory as I
from gbox import pe2_models as M

DISC = Path(os.environ.get("PE2_DISC", "/mnt/gbox/hyperspin/Arcade/collections/Sony Playstation/roms/"
                           "Parasite Eve II (USA) (Disc 1).chd"))
PARENT = [-1, 0, 1, 2, 3, 3, 5, 6, 7, 3, 9, 10, 11, 1, 13, 14, 1, 16, 17]          # Aya's 19-bone layout
TRANS = [(0, 0, 0), (0, -927, 0), (0, -79, 3), (0, -160, -7), (0, -292, -13), (71, -248, -24), (100, 39, -2),
         (8, 248, -21), (8, 216, 26), (-71, -248, -24), (-101, 36, -2), (-9, 248, -21), (-9, 216, 25), (94, 40, 3),
         (-20, 366, -38), (-22, 408, -42), (-94, 40, 3), (18, 366, -38), (20, 408, -42)]
BASE = 0x80115770


def synthetic_model() -> M.Model:
    nb = len(PARENT)
    counts = [0] + [3] * (nb - 1)
    vb = np.repeat(np.arange(nb), counts)
    verts = np.array([[10 * (k % 3), -5 * (k % 2), 40 if b == 4 else 0] for k, b in enumerate(vb)], float)
    normals = np.array([[0, 0, 1.0], [0, -1.0, 0]])
    prims = []
    for b in range(1, nb):
        v0 = sum(counts[:b])
        prims.append(M.Prim([v0, v0 + 1, v0 + 2], [(0, 0), (8, 0), (0, 8)], 0x3D80, 0xB7, b, normals=[0, 0, 1]))
    prims.append(M.Prim([0, 1, 3, 4], [(1, 1), (2, 2), (3, 3), (4, 4)], 0x3D40, 0xB6, 1, normals=[0, 1, 0, 1]))
    prims.append(M.Prim([0, 3, 6], [(5, 5), (6, 6), (7, 7)], 0x3D80, 0xB7, nb, seam=True, normals=[1, 0, 1], code=0x39))
    prims.append(M.Prim([1, 4, 7, 9], [(5, 5), (6, 6), (7, 7), (8, 8)], 0x3D80, 0xB7, nb, seam=True,
                        normals=[0, 0, 0, 1], code=0x79))
    return M.Model(BASE, 0, nb, np.tile(np.eye(3), (nb, 1, 1)), np.array(TRANS, float), PARENT, counts, verts, vb,
                   normals, prims, [], {}, {})


def blob_of(m: M.Model, pad: int = 0x40) -> tuple[bytes, int]:
    tab, ptr = M.serialize_tables(m, BASE + pad)
    head = pad + len(tab)
    return bytes(pad) + tab + M.header_bytes(ptr, m.nbones) + bytes(16), head


def test_serialize_parse_roundtrip():
    m = synthetic_model()
    blob, head = blob_of(m)
    assert M.find_headers(blob, BASE) == [head]
    p = M.parse_model(blob, BASE)
    assert p.nbones == 19 and p.parent == PARENT and p.counts == m.counts
    assert np.allclose(p.verts, m.verts) and np.allclose(p.trans, TRANS)
    order = sorted(m.prims, key=lambda q: (q.seam, q.bone, len(q.verts)))       # stream order: per bone tris, quads
    assert [(q.verts, q.uvs, q.clut, q.tpage, q.seam) for q in p.prims] == \
        [(q.verts, q.uvs, q.clut, q.tpage, q.seam) for q in order]
    assert [q.normals for q in p.prims if q.seam] == [[1, 0, 1], [0, 0, 0, 1]]
    assert len(p.seams) == 7                                  # one 0xC8 per seam corner
    hdr = struct.unpack_from("<9I", blob, head)
    assert hdr[1:3] == (18 * 0x28 + 0x34 + 0x28 + 0x34, 0x28 + 0x34)   # packet bytes: all, seam
    tab2, _ = M.serialize_tables(p, BASE + 0x40)
    assert tab2 == blob[0x40:head]


def test_parse_rejects_bad_data():
    m = synthetic_model()
    blob, head = blob_of(m)
    bad = bytearray(blob)
    struct.pack_into("<I", bad, head + 0x20, BASE + len(blob) + 64)          # stream pointer outside the blob
    with pytest.raises(ValueError):
        M.parse_model(bytes(bad), BASE, head)
    bad = bytearray(blob)
    struct.pack_into("<I", bad, head, 1)                                      # already relocated
    with pytest.raises(ValueError):
        M.parse_model(bytes(bad), BASE, head)
    with pytest.raises(ValueError):
        M.parse_model(bytes(64), BASE)
    m.prims[0].verts = [0, 1, 999]
    with pytest.raises(ValueError):
        M.parse_model(blob_of(m)[0], BASE)


def test_roles_and_glb(tmp_path):
    m = synthetic_model()
    r = M.infer_roles(m)
    assert r["hip"] == 1 and r["chest"] == 3 and r["head"] == 4
    assert {r["l_upper"], r["r_upper"]} == {6, 10} and {r["l_thigh"], r["r_thigh"]} == {13, 16}
    # face (+8 PSX z on the head vertices) points glTF +Z; her left is glTF +X = PSX -X: bones 9..12
    assert r["l_upper"] == 10 and r["l_thigh"] == 16
    v = M.VRAM()
    v.put(384, 256, 64, 256, bytes(range(256)) * 128)
    v.put(0, 246, 256, 1, struct.pack("<256H", *range(256)))
    out = tmp_path / "a.glb"
    rep = M.to_glb(m, v, out)
    d = out.read_bytes()
    assert d[:4] == b"glTF"
    jl = struct.unpack_from("<I", d, 12)[0]
    gl = json.loads(d[20:20 + jl])
    assert len(gl["skins"][0]["joints"]) == 19 and gl["images"] and rep["prims"] == len(m.prims)
    assert gl["nodes"][2 + 1]["translation"][1] > 0.9                      # hip ~0.93 m above the root


def test_vram_8bit_page():
    v = M.VRAM()
    v.put(384, 256, 64, 256, bytes([1, 2]) * (64 * 256))
    v.put(0, 245, 4, 1, struct.pack("<4H", 0, 31, 31 << 5, 31 << 10))
    px = v.page(0xB6, 0x3D40)
    assert px.shape == (256, 256, 4)
    assert tuple(px[0, 0]) == (255, 0, 0, 255) and tuple(px[0, 1]) == (0, 255, 0, 255)


def test_dedicated_registration():
    from gbox import characters as C
    hit = [n for n, t, *_ in C.DEDICATED if t("parasite eve ii (usa) (disc 1)", "psx")]
    assert hit == ["pe2"]
    assert [n for n, t, *_ in C.DEDICATED if t("parasite eve (usa) (disc 1)", "psx")] == ["parasite_eve"]
    ros = M.roster()
    assert len(ros) == 5 and sum(e["slug"] == "pe2_aya" for e in ros) == 1


@pytest.mark.skipif(not DISC.exists(), reason="owned PE2 disc 1 not mounted")
def test_owned_disc_aya(tmp_path):
    d = I.PE2Disc(DISC)
    for o, fid in d.outfit_files().items():
        m, vram, info = M.load_file_model(d, fid)
        assert m.nbones == 19 and info["chunk"].addr == I.AYA_MODEL_RAM
        assert m.base + m.header == I.AYA_HEADERS[fid]                     # the EXE's header table
        L = m.layout
        tab, ptr = M.serialize_tables(m, m.base + L["bones"])
        assert tab == info["blob"][L["bones"]:L["header"]]                # byte-identical tables
        assert M.header_bytes(ptr, 19) == info["blob"][L["header"]:L["header"] + 36]
    rep = M.export_aya(d, 3, tmp_path / "aya.glb")
    assert rep["verts"] == 352 and rep["prims"] == 498 and 1.6 < rep["height_m"] < 1.75
    assert rep["roles"]["head"] == "j04" and rep["roles"]["l_hand"] == "j12"
