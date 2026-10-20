"""Def Jam: Vendetta PS2 (SLUS_206.39) wrestler reader: synthetic WRS/VIF/GS round trips + owned-ISO pins."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import defjam_inventory as I
from gbox import defjam_models as M

ISO = Path(os.environ.get("GBOX_DEFJAM_PS2_ISO") or Path.home() / "gBox_alt/gbox-cache" / "deabd11481aa5a0c" / "source.iso")


def _qf(*v):
    return struct.pack("<4f", *v)


def _node(child, sib, pal, local):
    rec = struct.pack("<iiiI", child, sib, pal, 0) + struct.pack("<16f", *np.eye(4).ravel())
    rec += struct.pack("<16f", *np.asarray(local, float).ravel())
    return rec.ljust(M.NODE_SIZE, b"\0")


def _local(t=(0, 0, 0)):
    m = np.eye(4)
    m[3, :3] = t
    return m


def _model(nodes=None, base=0x200, single_mtx=64, wmtx=(64, 72), weights=(0.25, 0.75)):
    """3 rigid vertices on palette 0 + 1 vertex split between two palettes; one 4-vertex strip (2 CCW triangles, +z)."""
    nodes = nodes or [(1, -1, -1, _local()), (2, -1, 0, _local((0, 1, 0))), (-1, -1, 1, _local((1, 0, 0)))]
    q = [struct.pack("<4I", 3, 1, 1, 0x8000)]
    for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0)):
        q += [struct.pack("<ffII", 0.5, -0.25, 0x3F800000, single_mtx), _qf(0, 0, 1, 1.0), _qf(*p, 1.0)]
    q += [_qf(0.5, -0.5, 1.0, 1.0), _qf(0, 0, 1, 1.0), _qf(1, 1, 0, 1.0), struct.pack("<IfIf", wmtx[0], weights[0], wmtx[1], weights[1])]
    words = [4, base + 1, base + 4, base + 7, base + 10]
    words += [0] * (-len(words) % 4)
    data = b"".join(q) + struct.pack(f"<{len(words)}I", *words)
    n = len(data) // 16
    vif = struct.pack("<I", 0x6C008000 | (n << 16)) + data + struct.pack("<II", 0x11000000, 0x15000000)
    nn = len(nodes)
    geo = (0x20 + nn * M.NODE_SIZE + 0x7F) & ~0x7F
    head = struct.pack("<3I", geo, len(vif), nn).ljust(0x10, b"\0")
    recs = b"".join(_node(*nd) for nd in nodes)
    return (head + recs).ljust(geo, b"\0") + vif


def _wrs(slots):
    out = bytearray(b"WRS " + b"\0" * 12 + b"\xff" * 4 * I.WRS_SLOTS)
    struct.pack_into("<f", out, 8, 1.0)
    for i in sorted(slots):
        while len(out) % 16:
            out.append(0)
        struct.pack_into("<I", out, 0x10 + 4 * i, len(out) - (0x10 + 4 * i))
        out += slots[i]
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def _texture_slot(idx: np.ndarray, pal: np.ndarray) -> bytes:
    """512x512 PSMT8 indices + 256 RGBA -> the game's slot-18 packet (texels uploaded as 256x256 CT32)."""
    mem = np.zeros(512 * 512, np.uint8)
    mem[M._addr8(512, 512, 8).reshape(-1)] = idx.reshape(-1)
    ct32 = mem[M._addr32(256, 256, 4).reshape(-1, 1) + np.arange(4)].reshape(-1)
    perm = [(i & ~0x18) | ((i & 8) << 1) | ((i & 0x10) >> 1) for i in range(256)]
    clut = np.zeros((256, 4), np.uint8)
    clut[perm] = pal
    clut[:, 3] = 0x80

    def ad(*regs):
        tag = struct.pack("<QQ", 1 | (len(regs) << 60), int("e" * len(regs), 16))
        return tag + b"".join(struct.pack("<QQ", v, r) for r, v in regs)

    def image(data):
        return struct.pack("<QQ", (len(data) // 16) | (2 << 58), 0) + data
    pkt = ad((0x50, 4 << 48), (0x51, 0), (0x52, 256 | (256 << 32)), (0x53, 0)) + image(ct32.tobytes())
    pkt += ad((0x50, 1 << 48), (0x51, 0), (0x52, 16 | (16 << 32)), (0x53, 0)) + image(clut.tobytes())
    return struct.pack("<II", 0x80, len(pkt)).ljust(0x80, b"\0") + pkt


def test_nodes_tree_and_t_pose():
    sk = M.parse_nodes(_model())
    assert sk["parent"] == [-1, 0, 1] and sk["pal2node"] == {0: 1, 1: 2}
    assert np.allclose(sk["world"][2][3, :3], (1, 1, 0))


def test_nodes_reject_cycles_and_bad_indices():
    loop = [(1, -1, -1, _local()), (0, -1, 0, _local()), (-1, -1, 1, _local())]
    with pytest.raises(M.FormatError):
        M.parse_nodes(_model(loop))
    with pytest.raises(M.FormatError):
        M.parse_nodes(_model([(5, -1, -1, _local()), (-1, -1, 0, _local()), (-1, -1, 1, _local())]))


def test_batch_singles_take_the_matrix_in_st_w_and_weights_pair_up():
    m = M.parse_model(_model())
    assert m["tris"].tolist() == [[0, 1, 2], [2, 1, 3]] and m["batches"] == 1
    assert m["joints"].tolist() == [[1, 0], [1, 0], [1, 0], [1, 2]]
    assert m["weights"][3].tolist() == [0.25, 0.75] and m["single"] == 3 and m["weighted"] == 1
    assert M.winding(m["positions"], m["normals"], m["tris"]) == 1.0


@pytest.mark.parametrize("bad", [dict(single_mtx=68), dict(single_mtx=80), dict(weights=(0.5, 0.75)), dict(base=0x180)])
def test_bad_matrix_address_weights_or_strip_base_raise(bad):
    with pytest.raises(M.FormatError):
        M.parse_model(_model(**bad))


def test_texture_packet_round_trips_through_the_gs_swizzle():
    rng = np.random.default_rng(7)
    idx = rng.integers(0, 256, (512, 512), dtype=np.uint8)
    pal = rng.integers(0, 256, (256, 4), dtype=np.uint8)
    t = M.parse_texture(_texture_slot(idx, pal))
    assert (t["width"], t["height"]) == (512, 512) and t["transfers"] == [(256, 256, 0), (16, 16, 0)]
    assert np.array_equal(t["rgba"][..., :3], pal[idx][..., :3]) and int(t["rgba"][..., 3].min()) == 255
    with pytest.raises(M.FormatError):
        M.parse_texture(b"\x81" + _texture_slot(idx, pal)[1:])


def _fighter():
    """A 42-node BODY tree (chain) + a face on node 7 and hands on 13 / 19 whose rings touch the body."""
    body_nodes = [(k + 1 if k < 41 else -1, -1, k if k < 19 else -1, _local((0, 0.5, 0) if k else (0, 0, 0)))
                  for k in range(42)]
    return {1: _model(body_nodes, single_mtx=64, wmtx=(64, 72)), 3: _model(), 4: _model(), 5: _model()}


def test_assemble_attaches_parts_and_reports_roles(tmp_path):
    slots = _fighter()
    idx = np.zeros((512, 512), np.uint8)
    b = _wrs({**slots, 18: _texture_slot(idx, np.full((256, 4), 200, np.uint8))})
    r = M.extract_wrs(b, tmp_path / "x.glb", "x")
    parts = {p["part"]: p for p in r["parts"]}
    assert parts["face"]["attach"] == "body_07" and parts["left_hand"]["attach"] == "body_13"
    assert r["joints"] == 42 + 3 * 3 and r["roles"]["hip"] == "body_02" and r["roles"]["l_hand"] == "body_13"
    raw = Path(r["glb"]).read_bytes()
    assert raw[:4] == b"glTF"
    gl = json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]])
    assert len(gl["skins"][0]["joints"]) == 51 and gl["images"] and gl["meshes"][0]["primitives"][0]["material"] == 0
    face_root = next(i for i, n in enumerate(gl["nodes"]) if n.get("name") == "face_00")
    assert face_root in gl["nodes"][7]["children"]                      # the face hangs under BODY node 7


def test_inverse_binds_match_the_joint_worlds(tmp_path):
    from gbox import characters as C
    b = _wrs(_fighter())
    r = M.extract_wrs(b, tmp_path / "x.glb", "x")
    gl, acc, _img, W = C._load(Path(r["glb"]))
    ibm = acc(gl["skins"][0]["inverseBindMatrices"]).reshape(-1, 4, 4)
    for k, j in enumerate(gl["skins"][0]["joints"]):
        assert np.allclose(W[j] @ ibm[k].T, np.eye(4), atol=1e-4)


def test_roster_names_every_buffer_once():
    ros = M.roster()
    assert len(ros) == 58 and len({r["slug"] for r in ros}) == 58
    by = {r["data_index"]: r for r in ros}
    assert by[198]["name"].startswith("Briggs (costume 1)") and by[239]["slug"] == "djv_ps2_dmx"
    assert by[235]["name"].startswith("Method Man") and "Method Man" in by[235]["aliases"]


def test_registered_for_ps2_only():
    from gbox import characters as C
    entry = next(d for d in C.DEDICATED if d[0] == "defjam_vendetta_ps2")
    assert entry[1]("def jam - vendetta", "ps2") and not entry[1]("def jam - vendetta", "gamecube")
    assert len(entry[2]()) == 58


@pytest.mark.skipif(not ISO.exists(), reason="owned SLUS_206.39 ISO not staged")
def test_owned_iso_briggs_and_dmx(tmp_path):
    disc = I.Iso(ISO)
    for idx, tris in ((198, (1277, 432, 161, 161)), (239, None)):
        r = M.extract_index(disc, idx, tmp_path / f"{idx}.glb")
        parts = {p["part"]: p for p in r["parts"]}
        assert r["verified"] and r["joints"] == 79 and r["texture_error"] is None
        assert all(parts[k]["placed"] for k in ("face", "left_hand", "right_hand"))
        if tris:
            assert tuple(parts[k]["triangles"] for k in ("body", "face", "left_hand", "right_hand")) == tris
        assert parts["body"]["winding"] >= 0.98 and abs(r["height"] - 20.711) < 0.01
    b = I.read_entry(disc, I.entries(disc)[198])
    w = I.parse_wrs(b)
    for slot in (1, 2, 3, 4, 5):                                          # the codec rebuilds every model slot exactly
        blk = b[w["slots"][slot]["start"]:w["slots"][slot]["end"]]
        d = M.decode_batches(blk)
        npal = sum(p >= 0 for p in M.parse_nodes(blk)["palette"])
        assert M.encode_model(d["nodes"], d["count"], d["batches"], npal) == blk


def test_loose_triangles_follow_the_strips_and_the_codec_round_trips():
    raw = _model()
    nodes = raw[0x10:0x10 + 3 * M.NODE_SIZE]
    v = [{"st": [0.5, -0.25, 1.0], "n": [0, 0, 1, 1], "p": [*p, 1], "mtx": 64} for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0))]
    v.append({"st": [0.5, -0.5, 1.0], "stw": 1.0, "n": [0, 0, 1, 1], "p": [1, 1, 0, 1], "w": (64, 0.25, 72, 0.75)})
    d = {"nodes": nodes, "count": 3, "batches": [{"verts": v, "strips": [[0x201, 0x204, 0x207, 0x20A]], "loose": []}]}
    d["batches"][0]["loose"] = [[0x201, 0x20A, 0x204]]                     # one extra triangle (v0, v3, v1)
    enc = M.encode_model(d["nodes"], d["count"], d["batches"], 2)
    m = M.parse_model(enc)
    assert m["loose"] == 1 and m["tris"].tolist()[-1] == [0, 3, 1]
    d2 = M.decode_batches(enc)
    assert M.encode_model(d2["nodes"], d2["count"], d2["batches"], 2) == enc
    big = {**d["batches"][0], "verts": d["batches"][0]["verts"] * 30}
    with pytest.raises(M.FormatError):
        M.encode_batch(big)


def _alpha(nodes, verts, tris):
    """ALPHA slot: header, node records from +0x20, 0x48-byte vertices {pos, nrm, st, node a, node b, wa, wb}, tris."""
    out = struct.pack("<4I", len(nodes), len(verts), len(tris), 0).ljust(0x20, b"\0")
    out += b"".join(_node(*nd) for nd in nodes)
    for p, ja in verts:
        out += struct.pack("<8fiiff", *p, 0, 0, 1, 0.25, -0.5, ja, -1, 1.0, 0.0).ljust(M.ALPHA_VERTEX, b"\0")
    out += struct.pack(f"<{3 * len(tris)}I", *[i for t in tris for i in t])
    return out + bytes(-len(out) % 0x80)


def test_alpha_layer_rides_the_face_tree_with_a_blended_material(tmp_path):
    face_nodes = [(1, -1, -1, _local()), (2, -1, 0, _local((0, 1, 0))), (-1, -1, 1, _local((1, 0, 0)))]
    al = _alpha(face_nodes, [((0, 0, 0), 1), ((1, 0, 0), 1), ((0, 1, 0), 2)], [(0, 1, 2)])
    b = _wrs({**_fighter(), 7: al})
    a = M.assemble(b)
    rec = next(r for r in a["report"] if r["slot"] == 7)
    assert rec["tree"] == "face" and rec["verified"] and rec["triangles"] == 1
    pr = next(p for p in a["prims"] if p.get("alpha"))
    face0 = next(i for i, j in enumerate(a["joints"]) if j["name"] == "face_00")
    assert pr["joints"][:, 0].tolist() == [face0 + 1, face0 + 1, face0 + 2]
    assert np.allclose(pr["pos"][0], a["joints"][face0]["world"][3, :3])          # FACE space -> head attach
    r = M.extract_wrs(b, tmp_path / "x.glb", "x")
    raw = Path(r["glb"]).read_bytes()
    gl = json.loads(raw[20:20 + struct.unpack_from("<I", raw, 12)[0]])
    assert gl["materials"][1]["alphaMode"] == "BLEND" and gl["meshes"][0]["primitives"][-1]["material"] == 1
    with pytest.raises(M.FormatError):
        M.parse_alpha(_alpha(face_nodes, [((0, 0, 0), 5)], [(0, 0, 0)]))      # node outside the tree
