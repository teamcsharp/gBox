"""gbox.pe2_swap: Parasite Eve II writer pieces (#559) on synthetic data; the owned disc only when mounted."""
import struct

import numpy as np
import pytest

from gbox import char_coverage as CC
from gbox import pe2_inventory as I
from gbox import pe2_models as M
from gbox import pe2_swap as S

from test_pe2_models import BASE, DISC, blob_of, synthetic_model


def test_pair_quads_draws_the_same_triangles():
    a = M.Prim([0, 1, 2], [(0, 0), (1, 0), (0, 1)], 1, 2, 5, normals=[0, 1, 2])
    b = M.Prim([2, 1, 3], [(0, 1), (1, 0), (1, 1)], 1, 2, 5, normals=[2, 1, 3])
    c = M.Prim([3, 4, 5], [(9, 9), (9, 9), (9, 9)], 1, 2, 6, normals=[0, 0, 0])
    seam = M.Prim([0, 3, 4], [(0, 0)] * 3, 1, 2, 19, seam=True, normals=[0, 0, 0], code=0x39)
    out = S.pair_quads([a, b, c, seam])
    quads = [p for p in out if len(p.verts) == 4]
    assert len(quads) == 1 and len(out) == 3 and seam in out and c in out
    q = quads[0]

    def tris(p):                                   # the GPU's GT4 split (0,1,2) + (1,3,2), as cyclic triangles
        v, t = p.verts, [(0, 1, 2), (1, 3, 2)] if len(p.verts) == 4 else [(0, 1, 2)]
        return {min((v[i], v[j], v[k]), (v[j], v[k], v[i]), (v[k], v[i], v[j])) for i, j, k in t}
    assert tris(q) == tris(a) | tris(b)
    uv = dict(zip(q.verts, q.uvs))
    assert uv == {0: (0, 0), 1: (1, 0), 2: (0, 1), 3: (1, 1)}


def test_pair_quads_needs_matching_uvs_and_bone():
    a = M.Prim([0, 1, 2], [(0, 0), (1, 0), (0, 1)], 1, 2, 5, normals=[0, 0, 0])
    b = M.Prim([2, 1, 3], [(0, 2), (1, 0), (1, 1)], 1, 2, 5, normals=[0, 0, 0])     # UV seam on the shared edge
    assert all(len(p.verts) == 3 for p in S.pair_quads([a, b]))
    b2 = M.Prim([2, 1, 3], [(0, 1), (1, 0), (1, 1)], 1, 2, 6, normals=[0, 0, 0])    # another bone
    assert all(len(p.verts) == 3 for p in S.pair_quads([a, b2]))


def test_atlas8_quantizes_to_one_clut():
    at = S.Atlas8()
    tex = np.zeros((16, 16, 4), np.uint8)
    tex[..., 0], tex[..., 3] = np.arange(16)[:, None] * 16, 255
    at.add("t", tex, (255, 255, 255, 255))
    at.add("f", None, (0, 255, 0, 255))
    idx, clut = at.indexed()
    assert idx.shape == (256, 256) and len(clut) == 256 and 0 not in clut
    assert at.uv("t", [(0, 0), (1, 1)]) == [(1, 1), (16, 16)]
    x, y = at.uv("f", [(0.3, 0.7)])[0]
    assert tuple(at.rgb[y, x]) == (0, 255, 0)


def _chunk(t, flag, data, addr=0):
    return S._chunk(t, flag, data, addr)


def test_rebuild_file_chain_roundtrip(tmp_path):
    m = synthetic_model()
    blob, head = blob_of(m)
    page = np.zeros((256, 256), np.uint8)
    img = struct.pack("<HHI", 0x180, 0x100, 24) + struct.pack("<HHI", 0x1C0, 0x100, 0) + b"\xff\xff" + bytes(6)
    strips = b"".join(I.lz_encode(bytes(4096)) for _ in range(8))
    img = bytearray(img + strips + strips)
    struct.pack_into("<I", img, 12, 24 + len(strips))
    clut = struct.pack("<4H", 0, 245, 2, 256) + bytes(8) + I.lz_encode(bytes(1024))
    chain = _chunk(2, 1, clut) + _chunk(1, 1, bytes(img)) + _chunk(0, 0xFF, I.lz_encode(blob), BASE)
    nsec = len(chain) // 2048 + 2
    cdf = chain.ljust(nsec * 2048, b"\0")
    hed = I.build_hed([], [(10200, 0)])
    d = tmp_path / "disc"
    d.mkdir()
    (d / "SLUS_010.42").write_bytes(b"x")
    (d / "STAGE0.HED").write_bytes(hed)
    (d / "STAGE0.CDF").write_bytes(cdf)
    disc = I.PE2Disc(d)
    page[78:94, 0:50] = 7
    page[200, 200] = 3
    pal = list(range(1, 257))
    data = S.rebuild_file(disc, 10200, blob, page, pal)
    assert len(data) == nsec * 2048
    ch = I.walk_file(data, 0, nsec)
    assert [c.type for c in ch] == [2, 1, 0] and ch[-1].last and ch[-1].addr == BASE
    assert I.lz_decode(I.payload(data, ch[2]))[0] == blob
    cl = I.decode_clut(I.payload(data, ch[0]))
    assert (cl["y"], cl["h"]) == (245, 2) and struct.unpack("<256H", cl["data"][:512]) == tuple(pal)
    v = M.VRAM()
    for b in I.decode_image(I.payload(data, ch[1])):
        v.put(b["x"], b["y"] & 0x1FF, 64, 256, b["data"])
    got = v.mem[256:512, 384:512].copy().view(np.uint8).reshape(256, 256)
    assert (got == page).all()
    with pytest.raises(ValueError):                                     # too big for the file's sectors
        S.rebuild_file(disc, 10200, bytes(np.random.default_rng(1).integers(0, 256, 200000, dtype=np.uint8)), page, pal)


def test_writer_registered_and_routed():
    row = next((r for r in CC.WRITERS if r[0] == "pe2_swap"), None)
    assert row is not None and row[1] == ["player"]
    assert ("Parasite Eve II", "psx") not in CC.DISCUSSED
    w = CC.writer_for({"game_id": "1b8acc6f11536a68", "title": "Parasite Eve II (USA) (Disc 1)", "platform": "psx"})
    assert w["writer"] == "gbox.pe2_swap" and w["routed"]


@pytest.mark.skipif(not DISC.exists(), reason="owned PE2 disc 1 not mounted")
def test_owned_disc_face_rects():
    d = I.PE2Disc(DISC)
    m, vram, info = M.load_file_model(d, 10200)
    page = vram.mem[256:512, 384:512].copy().view(np.uint8).reshape(256, 256)
    r = S.face_rects(info["blob"], m, page)
    assert [(f["x"], f["y"], f["w"], f["h"]) for f in r] == [(0, 78, 50, 16)] * 3 + [(12, 104, 28, 20)] * 2
    assert r[0]["mismatch"] == 0
