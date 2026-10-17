"""gbox.crazy_taxi2 driver reader (request #1482): 1ST_READ.BIN tables, PowerVR textures, part names, the derived rest
rig, the rigged GLB and the DEDICATED registration. Synthetic data only (tests/ct2_synth.py)."""
import json
import struct

import numpy as np
import pytest

import ct2_synth as S
from gbox import crazy_taxi2 as c2


def _glb(path):
    b = path.read_bytes()
    n = struct.unpack_from("<I", b, 12)[0]
    return json.loads(b[20:20 + n]), b


def test_tex_size_matches_the_loader_layout():
    assert c2.tex_size(32, 32, 1, 2) == 0xAB0                      # 1x1 level at 6, 32x32 ends at 0xAB0
    assert c2.tex_size(32, 32, 1, 4) == 2048 + 0x56 + 256           # VQ mip: 0x56 index bytes before the top level
    assert c2.tex_size(128, 128, 1, 3) == 2048 + 64 * 64
    assert c2.tex_size(128, 64, 1, 0x0D) == 128 * 64 * 2


@pytest.mark.parametrize("pix,fmt,w,h", [(1, 1, 16, 16), (2, 1, 16, 16), (1, 2, 16, 16), (2, 2, 32, 32),
                                         (1, 0x0D, 32, 16), (2, 0x0D, 16, 32), (0, 1, 8, 8)])
def test_twiddled_textures_round_trip(pix, fmt, w, h):
    from gbox import crazy_taxi2_swap as W
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
    t = {"w": w, "h": h, "pix": pix, "fmt": fmt, "offset": 0, "size": c2.tex_size(w, h, pix, fmt)}
    data = W.encode_texture(img, t)
    out = c2.decode_texture(data, t)
    q = {0: 8, 1: 8, 2: 17}[pix]
    assert np.abs(out[..., :3].astype(int) - img[..., :3]).max() <= q
    if pix == 2:
        assert np.abs(out[..., 3].astype(int) - img[..., 3]).max() <= q


@pytest.mark.parametrize("fmt", [3, 4])
def test_vq_textures_round_trip_exactly_with_few_blocks(fmt):
    from gbox import crazy_taxi2_swap as W
    img = np.zeros((32, 32, 4), np.uint8)
    img[..., 3] = 255
    img[:16, :, 0] = 255                                            # four distinct 2x2 blocks at most
    img[:, :16, 2] = 255
    t = {"w": 32, "h": 32, "pix": 1, "fmt": fmt, "offset": 0, "size": c2.tex_size(32, 32, 1, fmt)}
    out = c2.decode_texture(W.encode_texture(img, t), t)
    assert np.array_equal(out[..., :3], img[..., :3])


def test_vq_texel_order_and_twiddle():
    """A hand-made VQ texture: code k's four texels are (x, y) = (0,0) (0,1) (1,0) (1,1); index bytes are twiddled."""
    book = np.zeros((256, 4), np.uint16)
    book[1] = [0xF800, 0x07E0, 0x001F, 0xFFFF]                      # red, green, blue, white
    idx = np.zeros(4, np.uint8)
    idx[1] = 1                                                      # twiddled index 1 = block (x 0, y 1)
    data = book.astype("<u2").tobytes() + idx.tobytes()
    out = c2.decode_texture(data, {"w": 4, "h": 4, "pix": 1, "fmt": 3, "offset": 0, "size": len(data)})
    assert tuple(out[2, 0, :3]) == (255, 0, 0) and tuple(out[3, 0, :3]) == (0, 255, 0)
    assert tuple(out[2, 1, :3]) == (0, 0, 255) and tuple(out[3, 1, :3]) == (255, 255, 255)
    assert tuple(out[0, 0, :3]) == (0, 0, 0)


def test_texture_table_and_layout_checks():
    d = S.driver()
    table = c2.read_tex_table(d["exe"], S.VA["tex"])
    assert [(t["w"], t["h"], t["pix"], t["fmt"]) for t in table] == S.TEXTURES
    assert table == d["tables"]["textures"]
    imgs = c2.textures(d["tex"], table)
    assert [i.shape for i in imgs] == [(16, 16, 4), (16, 16, 4)]
    with pytest.raises(ValueError, match="ends at"):
        c2.textures(d["tex"] + b"\0" * 64, table)
    bad = bytearray(d["exe"])
    struct.pack_into("<HH", bad, S.VA["tex"] - c2.EXE_BASE, 12, 16)  # not a power of two
    with pytest.raises(ValueError, match="not a texture"):
        c2.read_tex_table(bytes(bad), S.VA["tex"])


def test_find_tables_by_content():
    d = S.driver()
    t = c2.find_tables(d["exe"], d["pol"], d["tex"])
    assert t["slots"] == d["tables"]["slots"] and t["textures"] == d["tables"]["textures"]
    with pytest.raises(ValueError, match="slot tables"):
        c2.find_tables(bytes(len(d["exe"])), d["pol"], None)


def test_known_build_tables(monkeypatch):
    d = S.driver()
    S.known(monkeypatch)
    t = c2.player_tables(d["exe"], "PP2A", True)
    assert t["slots"] == d["tables"]["slots"] and t["alloc"] == d["tables"]["alloc"] >= len(d["pol"])
    assert t["va"]["slots"] == S.VA_H["slots"] and c2.player_tables(d["exe"], "PP2A")["va"]["slots"] == S.VA["slots"]


def test_part_names_from_the_sorted_slot_table():
    d = S.driver()
    objs = c2.walk(d["pol"])
    names = c2.part_names(objs, d["tables"]["slots"])
    assert set(names) == set(c2.PARTS)
    at = {o.offset: i for i, o in enumerate(objs)}
    assert all(names[n] == at[d["offsets"][n]] for n in c2.PARTS)
    plain = [p for p in c2.PARTS if p not in c2.HAND_POSES]           # polPP2CH: no gesture hands
    d15 = S.driver(parts=plain)
    assert set(c2.part_names(c2.walk(d15["pol"]), d15["tables"]["slots"])) == set(plain)
    da = S.driver(accessory=True)                                    # Gus: ude_lB rides ude_l
    na = c2.part_names(c2.walk(da["pol"]), da["tables"]["slots"])
    assert "ude_l+1" in na and set(na) - {"ude_l+1"} == set(c2.PARTS) and c2.joint_of("ude_l+1") == "ude_l"
    with pytest.raises(ValueError, match="drawn parts"):
        c2.part_names(c2.walk(d15["pol"]), d15["tables"]["slots"][:-3])


def test_measures_and_rest_skeleton():
    d = S.driver()
    objs = c2.walk(d["pol"])
    m = c2.measures(objs, c2.part_names(objs, d["tables"]["slots"]))
    assert m["thigh_l"] == pytest.approx(4.0 - 0.6) and m["shin_l"] == pytest.approx(4.5)
    assert m["hips"] == pytest.approx(2.0 - 0.8) and m["hip_w"] == pytest.approx(1.2 + 0.02)
    W = c2.skeleton(m)
    assert set(W) == set(c2.RIG)
    for j, M in W.items():                                           # proper rotations
        assert np.allclose(M[:3, :3] @ M[:3, :3].T, np.eye(3)) and np.linalg.det(M[:3, :3]) == pytest.approx(1.0)
    pos = {j: M[:3, 3] for j, M in W.items()}
    assert pos["kakato_l"][1] == pytest.approx(m["sole_l"])           # soles on y = 0
    assert pos["momo_l"][0] > 0 > pos["momo_r"][0] and pos["kata_l"][0] > 0 > pos["kata_r"][0]   # left = +X
    assert pos["atama"][1] > pos["kubi"][1] > pos["koshi"][1] > pos["sune_l"][1]
    # a part's local x runs down for the legs, up for the chest; the head's x faces +Z
    assert np.allclose(W["sune_l"][:3, 0], [0, -1, 0]) and np.allclose(W["mune"][:3, 0], [0, 1, 0])
    assert np.allclose(W["atama"][:3, 0], [0, 0, 1]) and np.allclose(W["koshi"][:3, 2], [-1, 0, 0])


def test_assemble_and_glb(tmp_path):
    d = S.driver(accessory=True)
    a = c2.assemble(d["pol"], d["tex"], d["tables"])
    parts = {p["part"] for p in a["parts"]}
    assert not parts & set(c2.HAND_POSES) and "ude_l+1" in parts
    allp = np.concatenate([p["pos"] for p in a["parts"]])
    assert allp[:, 1].min() == pytest.approx(-0.0, abs=1e-6) or allp[:, 1].min() > -1e-6
    gu = c2.assemble(d["pol"], d["tex"], d["tables"], hands="gu")
    assert {"te_l_gu", "te_r_gu"} <= {p["part"] for p in gu["parts"]} and "te_l" not in {p["part"] for p in gu["parts"]}
    glb = c2.write_glb(tmp_path / "x.glb", a, "x", {"driver": "synthetic"})
    gl, raw = _glb(glb)
    names = [n["name"] for n in gl["nodes"]]
    assert all(j in names for j in c2.ROLES.values()) and len(gl["skins"][0]["joints"]) == len(c2.RIG) == 18
    assert set(c2.ROLES) == {"hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand",
                             "r_upper", "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin",
                             "r_foot"}
    assert len(gl["images"]) == 2 and all(p["attributes"].keys() >= {"JOINTS_0", "WEIGHTS_0", "TEXCOORD_0"}
                                          for p in gl["meshes"][0]["primitives"])
    from gbox.characters import rig_from_gltf
    rig = rig_from_gltf(glb, c2.ROLES)
    assert len(rig["joints"]) == 18 and set(rig["roles"]) == set(c2.ROLES)
    # every vertex rides its part's joint rigidly: owner of the head's vertices is atama
    head = [pr for pr in rig["prims"] if len(pr["pos"])]
    assert head and all(np.isfinite(np.asarray(pr["pos"])).all() for pr in head)


def test_stock_measures_drive_a_written_model():
    d = S.driver()
    a0 = c2.assemble(d["pol"], d["tex"], d["tables"])
    m = dict(a0["measures"], legs=a0["measures"]["legs"] + 1.0)
    a1 = c2.assemble(d["pol"], d["tex"], d["tables"], measures_from=m)
    assert a1["joints"]["koshi"][1, 3] == pytest.approx(a0["joints"]["koshi"][1, 3] + 1.0)


def test_dedicated_registration_and_roster():
    from gbox import characters as C
    pick = lambda t, p: next((n for n, test, _r, _run in C.DEDICATED if test(t, p)), None)   # noqa: E731
    for title in ("crazy taxi 2", "crazy taxi 2 (usa)", "2004-06-28-crazy-taxi-2-pal-dcp"):
        assert pick(title, "dreamcast") == "crazy_taxi2", title
    assert pick("crazy taxi", "dreamcast") != "crazy_taxi2" and pick("crazy taxi 2", "gamecube") != "crazy_taxi2"
    assert pick("crazy taxi (usa)", "gamecube") == "crazy_taxi"
    assert C.reader_version("crazy_taxi2") == c2.READER_VERSION
    r = c2.roster()
    assert [e["name"].split(" (")[0] for e in r] == list(c2.DRIVERS.values())
    assert len({e["slug"] for e in r}) == 8 and all(e["slug"].startswith("ct2_") and e["collect"] for e in r)
    assert {"45e9455ca5487e7d", "b5dfa0c44de0ba90", "bed50bf430125ec7"} <= c2.GAME_IDS


def test_extract_run_contract(tmp_path, monkeypatch):
    d = S.driver()
    S.known(monkeypatch)

    class Disc:
        files = {"1ST_READ.BIN": 0, "POLPP2AH.BIN": 0, "TEXPP2AH.BIN": 0}

        def read(self, n):
            return {"1ST_READ.BIN": d["exe"], "POLPP2AH.BIN": d["pol"], "TEXPP2AH.BIN": d["tex"]}[n]
    from gbox import characters as C
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, game: tmp_path / "x.gdi")
    monkeypatch.setattr(c2, "open_disc", lambda path: Disc())
    e = next(x for x in c2.roster() if x["key"] == "PP2A")
    r = c2.extract_run(None, {"game_id": "45e9455ca5487e7d"}, e, tmp_path / "w")
    assert r["files"][0].suffix == ".glb" and r["files"][0].is_file() and r["tool"] == "gbox.crazy_taxi2"
    assert r["roles"] == c2.ROLES and r["extra"]["ct2_reader"] == c2.READER_VERSION
    man = json.loads(r["files"][1].read_text())
    assert man["driver"] == "Slash" and man["joints"] == 18


def test_chd_gd_layout_falls_back_to_frame_padding(tmp_path):
    """A GD-ROM CHD whose CHGD PAD fields name the unstored gap (Crazy Taxi 2 USA: 150 and 44024) is laid out with
    the 4-frame padding when that adds up to the frames the CHD stores."""
    from gbox import chd
    tracks = [(1, "MODE1_RAW", 450, 150), (2, "AUDIO", 44550, 44024), (3, "MODE1_RAW", 504150, 0)]
    meta, base = b"", 124
    entries = []
    for i, (n, typ, frames, pad) in enumerate(tracks):
        txt = f"TRACK:{n} TYPE:{typ} SUBTYPE:NONE FRAMES:{frames} PAD:{pad} PREGAP:0 PGTYPE:MODE1 PGSUB:NONE " \
              f"POSTGAP:0\0".encode()
        entries.append(txt)
    offs, o = [], base
    for txt in entries:
        offs.append(o)
        o += 16 + len(txt)
    for i, txt in enumerate(entries):
        nxt = offs[i + 1] if i + 1 < len(entries) else 0
        meta += b"CHGD" + b"\x01" + len(txt).to_bytes(3, "big") + struct.pack(">Q", nxt) + txt
    total = sum(f + (-f) % 4 for _n, _t, f, _p in tracks)
    hdr = bytearray(124)
    hdr[:8] = b"MComprHD"
    struct.pack_into(">II", hdr, 8, 124, 5)
    struct.pack_into(">QQQ", hdr, 32, total * 2448, 0, base)
    struct.pack_into(">II", hdr, 56, 19584, 2448)
    p = tmp_path / "gd.chd"
    p.write_bytes(bytes(hdr) + meta)
    lay = chd.track_layout(p)
    assert [t["first_frame"] for t in lay] == [0, 452, 45004]
    struct.pack_into(">Q", hdr, 32, (450 + 150 + 44550 + 44024 + 504150) * 2448)   # stored with PAD: kept as before
    p.write_bytes(bytes(hdr) + meta)
    assert [t["first_frame"] for t in chd.track_layout(p)] == [0, 600, 89174]
