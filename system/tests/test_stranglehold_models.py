"""Stranglehold PS3 model reader (#1410): SPU index decompression, segment / SkeletalMesh / Texture2D parsing and GLB
export on synthetic packages (tests/stranglehold_synth.py); the owned CookedPS3 packages when the share is reachable."""
import json
import struct

import numpy as np
import pytest

import stranglehold_synth as S
from gbox import stranglehold_models as M


def _pack(values, w):
    acc, n = 0, len(values)
    for v in values:
        acc = (acc << w) | v
    nb = (n * w + 7) // 8
    return (acc << (nb * 8 - n * w)).to_bytes(nb, "big") if nb else b""


def test_index_block_strip_codes_and_lane_deltas():
    """Hand-made block: a strip (codes 0/1 share (p0,p2)/(p2,p1)), a code-2 triangle and an own (3) triangle whose
    explicit indexes are delta-coded on eight lanes (index k = index k-8 + value - bias)."""
    # triangles: (0,1,2) (0,2,3) (3,2,4) [code 2 from (3,2,4): (p1,p0,x) = (2,3,5)] then 9 own triangles of explicit refs
    exp = [1, 0, 2, 3, 4, 1, 5, 2, 0, 3, 4, 1, 2, 5, 0, 3, 1, 4, 0, 2, 5, 3, 4, 1, 1, 0, 2]
    tris_exp = [tuple(exp[3 * k:3 * k + 3]) for k in range(9)]
    seq = [0, 0, 0, 0, 0, 0] + [1] * len(exp)
    codes = [3, 0, 1, 2] + [3] * 9
    deltas = [e - (exp[k - 8] if k >= 8 else 0) for k, e in enumerate(exp)]
    bias = -min(deltas)
    width = max(d + bias for d in deltas).bit_length()
    blk = _pack(seq, 1) + _pack(codes, 2) + _pack([d + bias for d in deltas], width)
    tris = M.decode_indexes(blk, len(codes), len(exp), bias, (len(seq) + 7) // 8, width)
    assert [tuple(t) for t in tris[:4]] == [(0, 1, 2), (0, 2, 3), (3, 2, 4), (2, 3, 5)]
    assert [tuple(t) for t in tris[4:]] == tris_exp


def test_encoder_round_trip():
    from gbox import stranglehold_swap as W
    P, F, B, uv = S.figure()
    order, local = S.first_use(F)
    body, h = W.encode_indexes(local)
    tris = M.decode_indexes(body, len(local), h["nexp"], h["bias"], h["seq_bytes"], h["width"])
    assert (tris == local).all() and h["verts"] == len(order)
    seg = W.segment_bytes(P[order], np.zeros((len(order), 9), np.uint8), uv[order], np.zeros((len(order), 2)), B[order], local)
    sg = M.parse_segment(seg, 0)
    assert sg["size"] == len(seg) and sg["nv"] == len(order) and (sg["tris"] == local).all()
    assert np.allclose(sg["pos"], P[order], atol=0.06) and (sg["joints"][:, 0] == B[order]).all()
    assert np.allclose(sg["weights"][:, 0], 1.0) and sg["config"][2:5] == b"\xff\xff\xff"


def test_palette_ranges_and_hole():
    from gbox import stranglehold_swap as W
    assert W.palette_ranges([2, 3, 4, 40, 41]) == ((2, 3), (40, 2))
    assert W.palette_ranges([7]) == ((7, 1), (7, 0))
    assert [W.hole_size(n) for n in (252, 810, 927, 2382, 3126, 3933)] == [0xD, 0xD, 0xE, 0x10, 0x11, 0x12]
    assert W.scratch_words(736, 3648, 17)[1] == 736 * 7


def test_synthetic_package_to_glb(tmp_path):
    raw = S.package()
    s, data = M.load_package(raw)
    assert s["layout"] == "chunked" and len(s["chunks"]) == 2
    pkg = M.Package(data)
    mi = pkg.find("SkeletalMesh")
    mesh = M.parse_mesh(pkg, mi[0])
    P, F, B, _uv = S.figure()
    assert len(mesh["bones"]) == len(S.BONES) and mesh["lods"] == 1 and len(mesh["groups"][0]) == 2
    assert sum(len(sg["tris"]) for sg in mesh["groups"][0]) == len(F)
    W = M.bind_pose(mesh["bones"])
    assert np.allclose(W[:, :3, 3], S.world_positions())
    tj = M.pick_diffuse(pkg, mesh, 0)
    assert pkg.exports[tj - 1]["name"] == S.TEX
    img = M.texture_rgba(pkg, tj)
    assert img.shape == (64, 64, 4) and abs(int(img[..., 0].mean()) - 200) < 8
    p = tmp_path / "pkg.xxx"
    p.write_bytes(raw)
    r = M.extract_package(p, tmp_path / "synth.glb")
    assert r["stats"]["triangles"] == len(F) and r["stats"]["bones"] == len(S.BONES)
    assert set(r["roles"]) == set(M.ROLE_BONES)                       # all 18 body roles
    assert 1.6 < r["stats"]["height_m"] < 1.9                          # feet near 0, head ~1.75 m up (+Y)
    gl = _glb_json(tmp_path / "synth.glb")
    assert gl["skins"][0]["joints"] == list(range(len(S.BONES))) and gl["images"]
    head = [n for n in gl["nodes"] if n.get("name") == "Head"][0]
    assert head["name"] == r["roles"]["head"]


def _glb_json(path):
    b = path.read_bytes()
    n = struct.unpack_from("<I", b, 12)[0]
    return json.loads(b[20:20 + n])


def test_dxt_decode_matches_reference():
    from gbox import gta_vc_models as G
    from gbox import stranglehold_swap as W
    rng = np.random.default_rng(3)
    img = rng.integers(0, 255, (16, 16, 4), dtype=np.uint8)
    for kind in (1, 5):
        data = W.dxt_encode(img, kind)
        assert (M.dxt_decode(data, 16, 16, kind) == G.dxt_decode(data, 16, 16, kind)).all()


def test_bad_segment_rejected():
    with pytest.raises(M.FormatError):
        M.parse_segment(b"\0" * 64, 0)


def test_roster_and_registration():
    from gbox import characters as C, character_collection as CC
    r = M.roster()
    assert r[0]["slug"] == "stranglehold_tequila" and len(r) == 39 and len({e["slug"] for e in r}) == 39
    g = {"title": "John Woo Presents Stranglehold", "platform": "ps3", "game_id": M.GAME_ID}
    assert CC.registered(g) and C.reader_version("stranglehold") == M.READER_VERSION


ROOT = M.SI.find_root()


@pytest.mark.skipif(ROOT is None, reason="Stranglehold CookedPS3 (QuickSwap2 share) not reachable")
def test_real_tequila(tmp_path):
    r = M.extract_package(ROOT / "char_tequila.xxx", tmp_path / "t.glb")
    st = r["stats"]
    assert st["triangles"] == 11713 and st["bones"] == 94 and len(r["roles"]) == 18
    assert st["textures"][0] == "tequila01_all_diffuse" and 1.8 < st["height_m"] < 2.1
    mesh = r["mesh"]
    assert sum(sg["nv"] for g in mesh["groups"] for sg in g) >= mesh["vertices"]


def _mk_cooked(base):
    d = base / "PS3_GAME" / "USRDIR" / "StrangleholdGame" / "CookedPS3"
    d.mkdir(parents=True)
    return d


def test_cooked_root_from_rom_extracted_sibling(tmp_path):
    """Catalog entry points at the .7z; the extracted disc folder (archive stem) sits beside it."""
    rom = tmp_path / "John Woo Presents Stranglehold (USA) (Collector's Edition).7z"
    rom.write_bytes(b"7z")
    want = _mk_cooked(tmp_path / rom.stem)
    assert M.cooked_root_from_rom(rom) == want


def test_cooked_root_from_rom_flat_and_missing(tmp_path):
    flat = tmp_path / "a" / "StrangleholdGame" / "CookedPS3"
    flat.mkdir(parents=True)
    assert M.cooked_root_from_rom(tmp_path / "a" / "EBOOT.BIN") == flat
    (tmp_path / "b" / "c").mkdir(parents=True)
    assert M.cooked_root_from_rom(tmp_path / "b" / "c" / "x.7z") is None
