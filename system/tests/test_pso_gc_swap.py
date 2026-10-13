"""PSO Episode I & II (GC) writer (gbox.pso_gc_swap) on synthetic data: slots, GX texture re-encoding in place,
AFS / GVM rebuilds, the big-endian body writer and the read-back validator."""
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import ninja, pso_gc as G, pso_gc_swap as S


def _gvr(fmt, w, h, flags=0):
    from gbox.melee_models import tex_size
    body = bytes([0, 0, flags, fmt]) + struct.pack(">HH", w, h) + bytes(tex_size(fmt, w, h))
    return b"GBIX" + struct.pack("<I", 8) + bytes(8) + b"GVRT" + struct.pack("<I", len(body)) + body


def _afs(entries):
    n = len(entries)
    start = 0x800
    head = bytearray(start)
    head[:4] = b"AFS\0"
    struct.pack_into("<I", head, 4, n)
    body = bytearray()
    for i, e in enumerate(entries):
        struct.pack_into("<II", head, 8 + 8 * i, start + len(body), len(e))
        body += e + bytes((-len(e)) % 0x800)
    return bytes(head + body)


def test_parse_slot():
    assert S.parse_slot("class:hucast") == ("class", "C")
    assert S.parse_slot("player") == ("class", "A")
    assert S.parse_slot("FOmar") == ("class", "L")
    assert S.parse_slot("enemy:booma") == ("enemy", "booma")
    assert S.parse_slot("enemies") == ("enemies", "")
    with pytest.raises(ValueError):
        S.parse_slot("enemy:not_a_monster")
    assert S.mod_name("sonic", "class:humar") == "psogc_sonic_as_humar"
    assert {r["slot"] for r in S.cast_slots()} >= {"class:humar", "enemy:booma"}


@pytest.mark.parametrize("fmt,w,h", [(14, 64, 64), (5, 32, 32), (4, 16, 8), (14, 8, 8)])
def test_gvr_like_keeps_header_and_length(fmt, w, h):
    chunk = _gvr(fmt, w, h)
    img = Image.new("RGB", (100, 100), (200, 30, 40))
    new = S.gvr_like(chunk, img)
    assert len(new) == len(chunk) and new[:G.gvr_header(chunk)["data"]] == chunk[:G.gvr_header(chunk)["data"]]
    px = G.gvr_decode(new).astype(int)
    assert abs(px[..., 0].mean() - 200) < 10 and abs(px[..., 1].mean() - 30) < 10


def test_gvr_like_refuses_palette_textures():
    with pytest.raises(ValueError):
        S.gvr_like(_gvr(9, 8, 8, flags=8), Image.new("RGB", (8, 8)))


def test_afs_rebuild_identical_and_atlas_everywhere():
    data = _afs([_gvr(14, 32, 32), _gvr(5, 16, 16), b"not a texture"])
    assert S.afs_build(data, G.afs(data)) == data
    new, done = S.afs_with_atlas(data, Image.new("RGB", (64, 64), (10, 200, 10)))
    assert done == 2
    ents = G.afs(new)
    assert [len(e) for e in ents] == [len(e) for e in G.afs(data)] and ents[2] == b"not a texture"
    assert G.gvr_decode(ents[0])[..., 1].mean() > 150


def test_gvm_with_atlas_keeps_entries():
    a, b = _gvr(14, 16, 16), _gvr(5, 8, 8)
    hdr = b"".join(struct.pack(">H", i) + n.ljust(28, b"\0") + bytes(8) for i, n in enumerate([b"t0", b"t1"]))
    gvm = b"GVMH" + struct.pack("<I", 4 + len(hdr)) + struct.pack(">HH", 0x0F, 2) + hdr + a + b
    new, done = S.gvm_with_atlas(gvm, Image.new("RGB", (32, 32), (0, 0, 255)))
    assert done == 2 and len(new) == len(gvm)
    assert [n for n, _c in G.gvm_entries(new)] == ["t0", "t1"]


def _be_tree():
    """root (no model) -> node 1 (a one-triangle model, its vertex cache slots 0..2) -> node 2 (no model)."""
    nrm = np.tile([0, 1.0, 0], (3, 1))
    vl, pl, c, r = ninja.cnk_model_lists(np.eye(3), nrm, [((0, 1, 2), ((0, 0), (1, 0), (0, 1)))], 2, b"", e=">")
    trs = struct.pack(">3f3i3f", 0, 1, 0, 0, 0, 0, 1, 1, 1)
    nodes = [{"flags": 0x07, "trs": trs, "child": 1, "sibling": None},
             {"flags": 0x06, "trs": trs, "child": 2, "sibling": None},
             {"flags": 0x07, "trs": trs, "child": None, "sibling": None}]
    data, _root, ptrs = ninja.write_tree(nodes, {1: (vl, pl, c, r)}, 0, ">")
    return b"NJCM" + struct.pack("<I", len(data)) + data + ninja.pof0(ptrs)


def test_body_nj_keeps_vertex_chunks_and_draws_new_geometry():
    f = _be_tree()
    before = G.read_nj(f)
    assert sorted(before.vbuf) == [0, 1, 2]
    pos = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 0]], float)
    nrm = np.tile([0, 0, 1.0], (4, 1))
    tris = [((0, 1, 2), ((0, 0), (1, 0), (0, 1))), ((1, 3, 2), ((1, 0), (1, 1), (0, 1)))]
    new = S.body_nj(f, {2: (pos, nrm, tris)}, 1)
    nj = G.read_nj(new)
    assert len(nj.bones) == 3
    assert {0, 1, 2} <= set(nj.vbuf)                      # node 1's original vertex chunk still runs
    assert list(nj.tris) == [1] and len(nj.tris[1]) == 2  # only the new strips draw, on texture 1
    assert min(k for k in nj.vbuf if k > 2) == 16         # the donor's vertices start at a free, aligned cache slot
    assert not S.validate({"x.nj": new})


def test_gc_find_gap_uses_room_between_files():
    """A full disc (PSO's last file ends on the last byte) still has junk-filled stretches between files."""
    import io
    import types
    from gbox.romexport import gc_find_gap, gc_used_regions
    img = bytearray(0x200000)
    struct.pack_into(">III", img, 0x420, 0x10000, 0x20000, 0x1000)        # DOL, FST, FST size
    struct.pack_into(">II", img, 0x2454, 0x2000, 0)                        # apploader size, trailer
    struct.pack_into(">I", img, 0x10000 + 0x90, 0x4000)                    # DOL text0 size
    disc = types.SimpleNamespace(files={"a": (0x30000, 0x8000), "b": (0x80000, 0x1000)})
    f = io.BytesIO(bytes(img))
    regions = gc_used_regions(f, disc)
    assert regions[0] == (0, 0x2460 + 0x2000) and (0x30000, 0x38000) in regions
    assert gc_find_gap(f, disc, 0x10000) == 0x38000                       # after a, before b
    assert gc_find_gap(f, disc, 0x8000) == 0x8000                         # after the apploader, before the DOL
    assert gc_find_gap(f, disc, 0x50000) == 0x88000                        # past the last file


def test_speck_reads_back_and_validate_reports_garbage():
    assert G.read_nj(S.speck_nj()).bones
    bad = S.validate({"broken.nj": b"NJCM" + struct.pack("<I", 8) + bytes(4)})
    assert bad and bad[0].startswith("broken.nj")
