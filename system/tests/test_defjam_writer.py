"""Def Jam: Vendetta PS2 writer: batching limits, hidden parts, texture re-encode, container layout, owned-ISO fit."""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import defjam_inventory as I
from gbox import defjam_models as M
from gbox import defjam_writer as W

from test_defjam_models import _alpha, _fighter, _local, _texture_slot, _wrs

ISO = Path(os.environ.get("GBOX_DEFJAM_PS2_ISO") or Path.home() / "gBox_alt/gbox-cache" / "deabd11481aa5a0c" / "source.iso")


def _grid(n):
    """n x n quad grid in the z=0 plane, CCW seen from +z, page-pixel UVs."""
    P = np.array([(x, y, 0.0) for y in range(n + 1) for x in range(n + 1)])
    F = []
    for y in range(n):
        for x in range(n):
            a = y * (n + 1) + x
            F += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    return {"P": P, "N": np.tile([0, 0, 1.0], (len(P), 1)), "UV": P[:, :2] * 4, "F": np.array(F), "mtx": 72}


def test_batches_respect_the_vu_limits_and_double_buffer_parity():
    bts = W.make_batches([_grid(12)])                       # 288 triangles
    assert sum(len(b["loose"]) for b in bts) == 288
    for k, b in enumerate(bts):
        base = 0x200 if k % 2 == 0 else 0x100
        assert len(b["loose"]) <= W.MAX_BATCH_TRIS and len(b["verts"]) <= W.MAX_BATCH_VERTS
        assert all(base < a < base + 0x100 and (a - base - 1) % 3 == 0 for t in b["loose"] for a in t)
        assert len(M.encode_batch(b)) // 16 <= M.MAX_BATCH_QW
    nodes = [(1, -1, -1, _local()), (-1, -1, 1, _local((0, 1, 0)))]
    from test_defjam_models import _node
    raw = b"".join(_node(*n) for n in nodes)
    m = M.parse_model(M.encode_model(raw, 2, bts, 2))
    assert len(m["tris"]) == 288 and M.winding(m["positions"], m["normals"], m["tris"]) == 1.0
    assert set(m["joints"][:, 0].tolist()) == {1}            # matrix 72 = palette 1 = node 1


def test_palette_fallback_walks_to_the_nearest_vertex_node():
    sk = {"palette": [-1, -1, 0, -1, 1], "parent": [-1, 0, 1, 2, 3], "count": 5}
    assert W.palette_of(sk) == {0: 0, 1: 0, 2: 0, 3: 1, 4: 1}


def test_speck_and_blank_alpha_keep_layout_but_draw_nothing():
    slots = _fighter()
    face = W.speck(slots[3])
    m = M.parse_model(face)
    assert M.parse_nodes(face)["parent"] == M.parse_nodes(slots[3])["parent"] and len(m["tris"]) == 1
    assert np.ptp(m["positions"], 0).max() == 0
    face_nodes = [(1, -1, -1, _local()), (2, -1, 0, _local((0, 1, 0))), (-1, -1, 1, _local((1, 0, 0)))]
    al = _alpha(face_nodes, [((0, 0, 0), 1), ((1, 0, 0), 1), ((0, 1, 0), 2)], [(0, 1, 2)])
    blank = W.blank_alpha(al)
    assert len(blank) == len(al) and np.abs(M.parse_alpha(blank)["positions"]).max() == 0


def test_texture_reencode_round_trips_through_the_reader():
    rng = np.random.default_rng(3)
    slot = _texture_slot(np.zeros((512, 512), np.uint8), np.zeros((256, 4), np.uint8))
    page = np.zeros((512, 512, 4), np.uint8)
    page[..., :3] = rng.integers(0, 8, (512, 512, 1)) * 32                  # 8 grey levels: exact in 255 colours
    page[..., 3] = 255
    out = W.encode_texture(slot, page)
    assert len(out) == len(slot) and out[:0x80 + 0x60] == slot[:0x80 + 0x60]          # registers kept
    back = M.parse_texture(out)["rgba"]
    assert np.array_equal(back[..., :3], page[..., :3]) and int(back[..., 3].min()) == 255


def test_rebuild_keeps_order_and_alignment_and_updates_size():
    slots = {**_fighter(), 18: b"T" * 0x50}
    b = _wrs(slots)
    new = W.rebuild_wrs(b, {3: W.speck(slots[3]), 18: b"U" * 0x60})
    w = I.parse_wrs(new)
    assert sorted(w["slots"]) == sorted(slots) and w["size"] == len(new)
    assert all(s["start"] % 0x80 == 0x10 for s in w["slots"].values())
    assert new[w["slots"][18]["start"]:w["slots"][18]["end"]] == b"U" * 0x60
    assert new[w["slots"][1]["start"]:w["slots"][1]["end"]].rstrip(b"\0") == slots[1].rstrip(b"\0")


def test_find_wrestler_names_costumes_and_player():
    assert W.find_wrestler("player") == list(range(198, 210))
    assert W.find_wrestler("Briggs") == [198, 199, 200] and W.find_wrestler("briggs 2") == [199]
    assert W.find_wrestler("DMX") == [239] and W.find_wrestler("wrs244") == [244]
    with pytest.raises(LookupError):
        W.find_wrestler("Mario")


def test_routed_in_characters_and_coverage():
    from gbox import char_coverage
    w = char_coverage.writer_for({"game_id": "deabd11481aa5a0c", "title": "Def Jam - Vendetta", "platform": "ps2"})
    assert w["writer"] == "gbox.defjam_writer" and w["routed"]


@pytest.mark.skipif(not ISO.exists(), reason="owned SLUS_206.39 ISO not staged")
def test_owned_iso_dmx_into_briggs_reads_back(tmp_path):
    disc = I.Iso(ISO)
    ents = I.entries(disc)
    dmx = M.extract_index(disc, 239, tmp_path / "dmx.glb")
    bases = {198: I.read_entry(disc, ents[198])}
    r = W.fit_fitting(bases, {198: ents[198]["size"]}, {"model": Path(dmx["glb"]), "roles": dmx["roles"], "name": "dmx"},
                      tmp_path / "work")
    e = r["entries"][0]
    assert e["bytes"] <= e["budget"] and r["fit"]["triangles"] >= 700
    a = M.assemble(e["data"])
    body = next(p for p in a["report"] if p["slot"] == 1)
    assert body["triangles"] == r["fit"]["triangles"] and body["winding"] >= 0.9
    w = I.parse_wrs(e["data"])
    orig = I.parse_wrs(bases[198])
    for k in (0, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17):                    # untouched slots are copied verbatim
        s, o = w["slots"][k], orig["slots"][k]
        assert e["data"][s["start"]:s["end"]] == bases[198][o["start"]:o["end"]]
    assert struct.unpack_from("<I", e["data"], 4)[0] == len(e["data"])
