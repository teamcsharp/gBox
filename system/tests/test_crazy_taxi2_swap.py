"""gbox.crazy_taxi2_swap: the Crazy Taxi 2 (DC) driver writer - slots, native object / strip encoding, the PowerVR
safety validator, the pol budget, the slot-table patch and a whole driver written from a donor GLB and read back.
Synthetic data only (tests/ct2_synth.py)."""
import struct

import numpy as np
import pytest

import ct2_synth as S
from gbox import crazy_taxi2 as c2
from gbox import crazy_taxi2_swap as W


def test_slots():
    assert W.parse_slot("player") == ["PP2A"] and W.parse_slot(None) == ["PP2A"]
    assert W.parse_slot("drivers") == list(c2.PLAYER_KEYS)
    assert W.parse_slot("driver:gus") == ["PP1D"] and W.parse_slot("Hot-D") == ["PP2D"]
    assert W.parse_slot("driver:b.d. joe") == ["PP1B"] and W.parse_slot("pp2c") == ["PP2C"]
    assert not W.is_slot("pedestrians") and W.is_slot("driver:cinnamon")
    slots = {s["slot"] for s in W.cast_slots()}
    assert {"player", "drivers", "driver:slash", "driver:axel"} <= slots and all(W.is_slot(s) for s in slots)


def _grid(n=6):
    P = np.array([[x, y, 0.0] for y in range(n) for x in range(n)], float)
    T = []
    for y in range(n - 1):
        for x in range(n - 1):
            a = y * n + x
            T += [(a, a + 1, a + n), (a + 1, a + n + 1, a + n)]
    N = np.tile([0.0, 0.0, 1.0], (len(P), 1))
    UV = P[:, :2] / (n - 1)
    return P, N, UV, np.array(T)


def _oriented(P, T):
    return {tuple(np.round(P[list(t)], 5).reshape(-1)) for t in
            [t[i:] + t[:i] for t in map(tuple, T) for i in (min(range(3), key=lambda k: tuple(P[t[k]])),)]}


def test_strips_encode_and_decode_the_same_triangles():
    d = S.driver()
    stock = c2.walk(d["pol"])[3]
    P, N, UV, T = _grid()
    t = d["tables"]["textures"][0]
    ob = W.encode_object(d["pol"], stock, P, N, UV, T, 0, t)
    (back,) = c2.walk(ob)
    (m,) = back.meshes
    assert back.entries == sum(len(x.pos) for x in back.meshes) and m.refs == 0
    flags = struct.unpack_from("<I", ob, 0x18 + c2.MESH_HEADER)[0]
    assert flags == W.STRIP_FLAGS                                    # the grid strips
    assert _oriented(np.array(m.pos), np.array(m.tris)) == _oriented(P, T)
    assert np.allclose(np.unique(np.round(m.uv, 5), axis=0), np.unique(np.round(UV, 5), axis=0))


def test_mesh_header_matches_the_texture_slot():
    d = S.driver()
    stock = c2.walk(d["pol"])[3]
    P, N, UV, T = _grid(3)
    for k, t in enumerate(d["tables"]["textures"]):
        ob = W.encode_object(d["pol"], stock, P, N, UV, T, k, t)
        pcw, isp, tsp, tcw = struct.unpack_from("<4I", ob, 0x18)
        assert pcw >> 29 == 4 and (pcw >> 24) & 7 == 0 and pcw & 8
        assert (8 << ((tsp >> 3) & 7), 8 << (tsp & 7)) == (t["w"], t["h"]) and (tsp >> 29, (tsp >> 26) & 7) == (1, 0)
        assert (tcw >> 27) & 7 == t["pix"] and bool((tcw >> 30) & 1) == (t["fmt"] in (3, 4)) and tcw & 0x1FFFFF == 0
        assert struct.unpack_from("<I", ob, 0x18 + 0x20)[0] == k


def test_validator_accepts_stock_like_and_rejects_unsafe():
    d = S.driver()
    objs = c2.walk(d["pol"])
    names = c2.part_names(objs, d["tables"]["slots"])
    geo = {p: W.weld(*_box(p)) for p in names}
    new, slots, rep = W.write_pol(d["pol"], d["tables"], {c2.joint_of(p): g for p, g in geo.items()}, 0,
                                  d["tables"]["alloc"] * 4)
    tables = {"slots": slots, "textures": d["tables"]["textures"]}
    ok = W.validate(new, d["tex"], tables, len(new), names)
    assert ok["objects"] == len(objs) and ok["triangles"] > 0
    with pytest.raises(ValueError, match="buffer"):
        W.validate(new, d["tex"], tables, len(new) - 32, names)
    with pytest.raises(ValueError, match="not an object"):
        W.validate(new, d["tex"], {"slots": [s + 4 for s in slots], "textures": tables["textures"]}, None)
    bad = bytearray(new)
    o = next(m.offset for ob in c2.walk(new) for m in ob.meshes)
    struct.pack_into("<I", bad, o + 8, struct.unpack_from("<I", bad, o + 8)[0] ^ 0x08)       # wrong TSP U size
    with pytest.raises(ValueError, match="TSP size"):
        W.validate(bytes(bad), d["tex"], tables, None)
    bad = bytearray(new)
    struct.pack_into("<I", bad, o + 12, struct.unpack_from("<I", bad, o + 12)[0] ^ (1 << 30))  # wrong VQ bit
    with pytest.raises(ValueError, match="TCW"):
        W.validate(bytes(bad), d["tex"], tables, None)
    bad = bytearray(new)
    struct.pack_into("<I", bad, o + 0x20, 9)                                                  # texture outside
    with pytest.raises(ValueError, match="outside"):
        W.validate(bytes(bad), d["tex"], tables, None)
    with pytest.raises(ValueError, match="textures"):
        W.validate(new, d["tex"][:-40], tables, None)


def _box(part):
    lo, hi = zip(*S.BOXES[c2.joint_of(part)])
    P, T = S.box(lo, hi)
    N = P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
    return P, N, (P[:, :2] % 1.0), np.asarray(T)


def test_write_pol_fits_the_buffer_and_keeps_names():
    d = S.driver(accessory=True)
    objs = c2.walk(d["pol"])
    names = c2.part_names(objs, d["tables"]["slots"])
    P, N, UV, T = _grid(8)                                           # a dense donor part everywhere
    geo = {c2.joint_of(p): (P * 0.3, N, UV, T) for p in names if "+" not in p}
    budget = len(d["pol"]) + 2000
    new, slots, rep = W.write_pol(d["pol"], d["tables"], geo, 0, budget)
    assert len(new) <= budget and rep["ratio"] < 4.0 and rep["triangles"] > 0
    nn = c2.part_names(c2.walk(new), slots)
    assert set(nn) == set(names)                                     # the wristband stays an accessory
    acc = c2.walk(new)[nn["ude_l+1"]]
    assert acc.tris() == 1 and np.allclose(np.array(acc.meshes[0].pos).mean(0), objs[names["ude_l+1"]].centre,
                                           atol=1e-5)
    assert all(c2.walk(new)[i].entries <= W.MAX_OBJECT_ENTRIES for i in nn.values())
    with pytest.raises(ValueError, match="does not fit"):
        W.write_pol(d["pol"], d["tables"], geo, 0, 600)


def test_texture_write_keeps_the_file_layout():
    d = S.driver()
    table = d["tables"]["textures"]
    assert W.atlas_slot(table) == 0                                  # twiddled beats VQ at the same size
    img = np.zeros((32, 32, 4), np.uint8)
    img[..., 0], img[..., 3] = 200, 255
    new = W.write_texture(d["tex"], table, 1, img)
    assert len(new) == len(d["tex"]) and new[:table[1]["offset"]] == d["tex"][:table[1]["offset"]]
    out = c2.textures(new, table)[1]
    assert np.abs(out[..., 0].astype(int) - 200).max() <= 17


def test_patch_slots():
    d = S.driver()
    exe = W.patch_slots(d["exe"], S.VA["slots"], [1, 2, 3])
    assert struct.unpack_from("<3I", exe, S.VA["slots"] - c2.EXE_BASE) == (1, 2, 3) and len(exe) == len(d["exe"])


def test_whole_driver_from_a_donor_glb(tmp_path, monkeypatch):
    """The synthetic driver's own rigged GLB (18 roles) as the donor: both detail levels written, validated, the slot
    table patched in 1ST_READ.BIN, and the result reads back through the reader."""
    d = S.driver()
    S.known(monkeypatch)
    a = c2.assemble(d["pol"], d["tex"], d["tables"])
    glb = c2.write_glb(tmp_path / "donor.glb", a, "donor")
    files = {"1ST_READ.BIN": d["exe"]}
    for stem in ("PP2A", "PP2AH"):
        files[f"POL{stem}.BIN"], files[f"TEX{stem}.BIN"] = d["pol"], d["tex"]
    # room for the donor's parts and their gesture-hand copies
    exe = bytearray(d["exe"])
    for va in (S.VA, S.VA_H):
        struct.pack_into("<I", exe, va["alloc"] - c2.EXE_BASE, len(d["pol"]) // 2)
    files["1ST_READ.BIN"] = bytes(exe)
    changed, reports = W.write_drivers(files, glb, dict(c2.ROLES), ["PP2A"])
    assert {"1ST_READ.BIN", "POLPP2A.BIN", "POLPP2AH.BIN", "TEXPP2A.BIN", "TEXPP2AH.BIN"} >= set(changed)
    assert "POLPP2A.BIN" in changed and "1ST_READ.BIN" in changed
    rep = reports["PP2A"]["levels"]
    assert set(rep) == {"PP2A", "PP2AH"} and all(r["check"]["triangles"] > 0 for r in rep.values())
    back = W.readback({**files, **changed}, ["PP2A"])
    assert back["PP2A"]["parts"] == 15 and back["PP2A"]["triangles"] > 0
    assert len(changed["TEXPP2A.BIN"]) == len(d["tex"])


def test_build_mod_refuses_a_cdi(tmp_path):
    with pytest.raises(ValueError, match="cdi"):
        W.build_mod(tmp_path / "Crazy Taxi 2.cdi", None, {}, ["PP2A"], tmp_path, "x")


def test_registered_writer():
    from gbox import char_coverage as CC
    import inspect
    from gbox import characters as C
    row = next(r for r in CC.WRITERS if r[0] == "crazy_taxi2_swap")
    assert "drivers" in row[1] and "player" in row[1]
    game = {"game_id": "b5dfa0c44de0ba90", "title": "Crazy Taxi 2 (USA)", "platform": "dreamcast"}
    w = CC.writer_for(game)
    assert w and w["writer"] == "gbox.crazy_taxi2_swap" and w["routed"]
    assert {"player", "driver:slash"} <= {s["slot"] for s in CC.cast_slots(game)}
    assert "Crazy Taxi 2 (DC)" in inspect.getsource(C.CharIn)
