"""Metal Gear Solid VR Missions character writer (gbox.mgs_vr_swap, request #1597): any collection character - the
Sonic Adventure cast included - as Snake, every soldier and the other 16-object figures, from synthetic KMD / PCC /
STAGE.DIR data (no game files): the proportions a big-headed donor needs, per-object decimation inside the KMD's
allocation, the native .stg / DAR / cached-block layer, one fit painted per stage texture archive, the pick op that
projects the actors through the game's view matrix, the cast-swap registration and live (pick whip) stacking.
Owned-disc checks at the end are skipped without the disc image."""
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import fit_events as FE, mgs_kmd as K, mgs_pcc as C, mgs_vr_swap as W, mgs_vr_tex as X, mgs_vr_tool as T

# Snake's KMD joint offsets (relative to the parent object) and tree, from the US disc (docs/mgs_vr_decomp.md)
LOCAL = [(0, 0, 0), (0, 0, 0), (-190, 265, -29), (0, -260, -50), (0, -249, 47), (0, 310, -55), (0, 94, 55),
         (190, 265, -29), (0, -260, -50), (0, -249, 47), (-90, -255, -10), (0, -311, 37), (0, -508, -47),
         (90, -253, -11), (0, -312, 39), (0, -508, -47)]
CHILD = {0: 1, 1: 5, 2: 3, 3: 4, 5: 6, 7: 8, 8: 9, 10: 11, 11: 12, 13: 14, 14: 15}


def header(w, h, vram=(960, 80), clut=(784, 226), planes=4, bpp=1, colors=16):
    hdr = bytearray(0x80)
    hdr[0:4] = bytes([0x0A, 5, 1, bpp])
    struct.pack_into("<4H", hdr, 4, 0, 0, w - 1, h - 1)
    struct.pack_into("<2H", hdr, 12, 1600, 1200)
    hdr[0x41] = planes
    struct.pack_into("<H", hdr, 0x42, ((w + 7) // 8 + 1) & ~1)
    struct.pack_into("<H", hdr, 0x44, 1)
    struct.pack_into("<7H", hdr, 0x4A, C.MAGIC, 8, *vram, *clut, colors)
    return bytes(hdr)


def pcc(w, h, seed=0, **kw):
    rng = np.random.default_rng(seed)
    pal = np.clip(rng.integers(8, 255, (16, 3)), 8, 255).astype(np.uint8)
    idx = rng.integers(0, 16, (h, w)).astype(np.uint8)
    return C.dumps(C.Pcc(w, h, pal, idx, header=header(w, h, **kw)))


def figure_kmd(textures=(47255, 47256), scale=1.0, flags_head=0x1) -> bytes:
    """A 16-object figure on Snake's tree: a box per object from its joint toward the next one (12 triangles)."""
    T_ = np.zeros((16, 3))
    for i, p in enumerate(W.TREE):
        T_[i] = (T_[p] if p >= 0 else 0) + np.array(LOCAL[i], float) * scale
    objs = []
    for i, p in enumerate(W.TREE):
        end = (T_[CHILD[i]] - T_[i]) if i in CHILD else np.array([0, 150 * scale if i == 6 else -90 * scale,
                                                                    120 * scale if i in (12, 15) else 0])
        a, b = np.zeros(3), end
        r = 40 * scale
        box = [a + (x, 0, z) for x in (-r, r) for z in (-r, r)] + [b + (x, 0, z) for x in (-r, r) for z in (-r, r)]
        verts = [(int(v[0]), int(v[1]), int(v[2]), -1) for v in box]
        quads = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
        faces = [(q[0], q[1], q[1], q[2]) for q in quads] + [(q[0], q[2], q[2], q[3]) for q in quads]
        o = K.KmdObject(flags_head if i == 6 else 0x10001, tuple(int(c * scale) for c in LOCAL[i]), p, 0xFFFFFFFF,
                        verts, [(0, 4096, 0, 0)], faces, [(0, 0, 0, 0)] * len(faces), [bytes(8)] * len(faces),
                        [textures[k % len(textures)] for k in range(len(faces))])
        o.bbox = o.computed_bbox()
        objs.append(o)
    model = K.Kmd(16, (0,) * 6, objs)
    return K.dumps(model, recompute_bbox=True)


def chibi_gltf(path: Path, head_tris=600, with_tex=True) -> Path:
    """A Sonic-like donor: short legs and body, a head as tall as the rest of it with many triangles, shoes that
    reach below the floor, every part rigid on its joint."""
    from gbox.melee_models import write_gltf
    names = ["hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand", "l_thigh",
             "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]
    parents = [-1, 0, 1, 1, 3, 4, 1, 6, 7, 0, 9, 10, 0, 12, 13]
    pos = np.array([[0, .45, 0], [0, .6, 0], [0, .75, 0], [.12, .7, 0], [.18, .58, 0], [.22, .46, 0],
                    [-.12, .7, 0], [-.18, .58, 0], [-.22, .46, 0], [.06, .45, 0], [.06, .27, 0], [.06, .1, 0],
                    [-.06, .45, 0], [-.06, .27, 0], [-.06, .1, 0]], float)
    joints = []
    for p, q in zip(parents, pos):
        w = np.eye(4)
        w[:3, 3] = q
        joints.append({"parent": p, "world": w})
    P, J, F = [], [], []

    def box(k, a, b, r):
        base = len(P)
        for c in (a, b):
            for x in (-r, r):
                for z in (-r, r):
                    P.append(np.asarray(c) + (x, 0, z))
                    J.append(k)
        for q in ((0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4), (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)):
            F.append([base + q[0], base + q[1], base + q[2]])
            F.append([base + q[0], base + q[2], base + q[3]])
    for k, n in enumerate(names):
        if n == "head":
            nlat = int(np.sqrt(head_tris / 2))
            nlon = max(4, head_tris // (2 * nlat))
            base = len(P)
            for i in range(nlat + 1):
                th = np.pi * i / nlat
                for j in range(nlon):
                    ph = 2 * np.pi * j / nlon
                    P.append(np.array([.3 * np.sin(th) * np.cos(ph), 1.05 + .3 * np.cos(th), .3 * np.sin(th) * np.sin(ph)]))
                    J.append(k)
            for i in range(nlat):
                for j in range(nlon):
                    a, b = base + i * nlon + j, base + i * nlon + (j + 1) % nlon
                    c, d = a + nlon, b + nlon
                    F += [[a, b, d], [a, d, c]]
        elif n.endswith("foot"):
            box(k, pos[k] + (0, -.14, .06), pos[k], .05)           # shoes below the floor (y < 0)
        else:
            nxt = {"hip": "chest", "chest": "head", "l_upper": "l_fore", "l_fore": "l_hand", "r_upper": "r_fore",
                   "r_fore": "r_hand", "l_thigh": "l_shin", "l_shin": "l_foot", "r_thigh": "r_shin", "r_shin": "r_foot"}
            end = pos[names.index(nxt[n])] if n in nxt else pos[k] + (0, -.05, 0)
            box(k, pos[k], end, .03)
    P = np.array(P, float)
    jj = np.zeros((len(P), 4), int)
    jj[:, 0] = J
    ww = np.zeros((len(P), 4))
    ww[:, 0] = 1
    tex = np.zeros((16, 16, 4), np.uint8)
    tex[..., 2], tex[..., 3] = 220, 255
    tex[:8, :, 0] = 200
    prims = [{"pos": P, "nrm": P - P.mean(0), "uv": (P[:, :2] - P[:, :2].min(0)) / np.ptp(P[:, :2], 0),
              "tris": np.array(F), "J": jj, "W": ww, "tex": tex if with_tex else None, "color": (255, 255, 255, 255),
              "wrap": (10497, 10497)}]
    return write_gltf(path, joints, prims, 1.0, "chibi", names)


ROLES = {r: r for r in ["hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                        "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]}


@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    from gbox import sm64_swap as S
    path = chibi_gltf(tmp_path_factory.mktemp("donor") / "chibi.gltf")
    return S.load_rig(path, ROLES), path


# ---------------------------------------------------------------------------------------------- slots
def test_slots_cover_snake_the_soldiers_and_the_other_figures():
    assert W.SLOTS["player"]["models"] == [39213] and W.SLOTS["enemy:soldier"]["models"] == [38582, 55267]
    assert W.slot_of("Snake") == "player" and W.slot_of("soldiers") == "enemy:soldier"
    assert W.slot_of("genome soldier") == "enemy:soldier" and W.slot_of("ninja") == "enemy:ninja"
    assert W.slot_of("55267") == "enemy:soldier" and W.slot_of("model:46243") == "model:46243"
    assert W.slot_of("mario") is None and not W.is_slot("roster") and W.is_slot("enemies")
    assert W.slots_of("enemies") == ["enemy:soldier", "enemy:ninja", "model:26944"]
    assert W.slots_of("all") == list(W.SLOTS)
    with pytest.raises(ValueError, match="no slot"):
        W.slots_of("boss")
    rows = W.cast_slots()
    assert [r["slot"] for r in rows] == list(W.SLOTS) and rows[0]["kind"] == "player"
    assert W.plan_mod_name([("player", "sonic")]) == "mgs_vr_sonic_fit"          # the first build's name stays
    assert W.plan_mod_name([("enemy:soldier", "sa1_knuckles")]) == "mgs_vr_sa1_knuckles_enemy_soldier"
    two = W.plan_mod_name([("enemy:soldier", "b"), ("player", "a")])
    assert two.startswith("mgs_vr_cast_") and two == W.plan_mod_name([("player", "a"), ("enemy:soldier", "b")])


def test_coverage_and_cast_swap_route_vr_missions_to_the_pairs_builder():
    from gbox import cast_swap as CS, char_coverage as CC
    game = {"game_id": "afd2fc507bb69843", "title": "Metal Gear Solid - VR Missions", "platform": "psx"}
    w = CC.writer_for(game)
    assert w["writer"] == "gbox.mgs_vr_swap" and w["routed"] and "enemy:soldier" in w["slots"]
    assert "only the HUcast" not in w["replaces"]
    rows = CS.slot_rows(game)
    assert [r["slot"] for r in rows] == list(W.SLOTS)               # aggregates (enemies / all / cast) dropped
    assert CS.strategy("gbox.mgs_vr_swap")[0] == "pairs" and "gbox.mgs_vr_swap" in CS.BUILDERS
    assert [r["slot"] for r in CS.filter_slots(rows, "enemies")] == ["enemy:soldier", "enemy:ninja", "model:26944"]


def test_cast_swap_plans_snake_and_the_soldiers_from_the_sonic_cast(tmp_path):
    from gbox import cast_swap as CS
    from tests.test_cast_swap import CHARS, entry
    sa1 = [entry(f"sa1_{n}", f"{n.title()} (Sonic Adventure)", "Sonic Adventure (USA)", "dreamcast",
                 gid="1a3f4cd416db9ffd", aliases=["player"] if n == "sonic" else [])
           for n in ("sonic", "tails", "knuckles", "amy", "big", "e102", "tikal", "super_sonic")]
    game = {"game_id": "afd2fc507bb69843", "title": "Metal Gear Solid - VR Missions", "platform": "psx"}
    p = CS.plan(game, CHARS + sa1, "sonic", "by_role", "", slots="all")
    assert p["status"] == "planned" and p["writer"] == "gbox.mgs_vr_swap" and p["strategy"] == "pairs"
    got = {r["slot"]: r["character"] for r in p["assignments"]}
    assert set(got) == set(W.SLOTS) and got["player"] in ("sa1_sonic", "sonic")
    assert len(set(got.values())) == len(got)                      # every figure kind gets its own donor
    assert p["mod"].startswith("cast_metal_gear_solid_")


def test_cast_builder_hands_every_pair_to_build_cast(monkeypatch):
    from gbox import cast_swap as CS
    seen = {}

    def fake(ctx, game, pairs, name, inp):
        seen["pairs"] = [(s, m["slug"]) for s, m in pairs]
        return {"mod": name, "slots": {s: {"status": "built"} for s, _m in pairs}}
    monkeypatch.setattr(W, "build_cast", fake)
    res = CS.BUILDERS["gbox.mgs_vr_swap"](None, {"game_id": "afd2fc507bb69843"},
                                          [("player", {"slug": "sonic"}), ("enemy:soldier", {"slug": "sa1_amy"})],
                                          "cast_x", None)
    assert res["mod"] == "cast_x" and seen["pairs"] == [("player", "sonic"), ("enemy:soldier", "sa1_amy")]
    monkeypatch.setattr(W, "build_cast", lambda *a: (_ for _ in ()).throw(RuntimeError("no disc here")))
    res = CS.BUILDERS["gbox.mgs_vr_swap"](None, {}, [("player", {"slug": "sonic"})], "cast_x", None)
    assert res["mod"] is None and res["slots"]["player"] == {"status": "failed", "reason": "no disc here"}


# ---------------------------------------------------------------------------------------------- the fit
def test_proportion_seats_a_big_head_grounds_the_shoes_and_closes_limb_gaps():
    tgt = W.kmd_target(K.loads(figure_kmd()))
    T_ = tgt["T"]
    head = np.array([[0, 0, 0], [0, 1300, 0], [200, 600, 0], [-200, 600, 300]], float) + (0, -900, 0)
    foot = np.array([[0, -1074, 0], [0, -1500, 200], [30, -1500, -40]], float)
    shin = np.array([[-90, -566, 0], [-90, -800, 0], [-80, -820, 10]], float)   # stops 250 short of the ankle
    prims = [{"pos": np.concatenate([head, foot, shin]), "J": np.array([[6, 0, 0, 0]] * 4 + [[12, 0, 0, 0]] * 3 +
                                                                       [[11, 0, 0, 0]] * 3)}]
    out, rep = W.proportion(prims, tgt)
    P = out[0]["pos"]
    assert P[:4, 1].min() == pytest.approx(tgt["head_base"])        # the head sits on the neck
    assert P[:, 1].max() <= tgt["ground"] + W.HEAD_ROOM * tgt["height"] + 1
    assert rep["head_shrink"] < 1 and rep["head_lift"] > 0
    assert P[4:7, 1].min() == pytest.approx(tgt["ground"], abs=1)   # soles on the floor, ankle kept
    assert P[4, 1] == pytest.approx(T_[12][1])
    reach = (P[7:10] - T_[11]) @ ((T_[12] - T_[11]) / np.linalg.norm(T_[12] - T_[11]))
    assert reach.max() == pytest.approx(np.linalg.norm(T_[12] - T_[11]), rel=0.02) and rep["limb_reach"]["11"] > 1


def test_proportion_leaves_a_human_sized_head_where_the_retarget_put_it():
    tgt = W.kmd_target(K.loads(figure_kmd()))
    head = np.array([[0, 300, 0], [0, 520, 0], [60, 400, 40]], float)       # hair to the shoulders, not a chibi head
    prims = [{"pos": head.copy(), "J": np.array([[6, 0, 0, 0]] * 3)}]
    out, rep = W.proportion(prims, tgt)
    assert np.array_equal(out[0]["pos"], head) and rep["head_lift"] == 0.0


def test_a_big_head_no_longer_starves_the_hands_and_the_fit_fills_the_allocation(donor):
    rig, _path = donor
    raw = figure_kmd()
    original = K.loads(raw)
    prims, rep, tgt = W.fit_prims(original, rig, None)
    per = W.split_objects(prims, tgt)
    src = {i: len(per[i]["P"]) // 3 for i in per}
    assert src[6] >= 500 and src[4] == 12                           # the head dwarfs a hand
    meshes, drep = W.decimate(original, per, len(raw))
    assert drep["bytes"] <= len(raw)
    for i, n in src.items():
        if n:
            assert drep["triangles"][i] >= min(n, W.MIN_OBJECT_TRIS) - 2, (i, drep["triangles"])
    assert drep["triangles"][6] > drep["triangles"][4]              # detail follows the donor
    assert all(len(m[0]) <= 255 and len(m[4]) <= 127 for m in meshes.values() if m)


def test_a_triangle_soup_is_clustered_when_no_edge_can_collapse():
    rng = np.random.default_rng(3)
    centres = rng.uniform(-300, 300, (300, 3))
    P = np.concatenate([[c, c + (20, 0, 0), c + (0, 20, 0)] for c in centres])     # 300 separate triangles
    v, vn, faces, keep = W._mesh(P, np.tile([0, 1.0, 0], (len(P), 1)), 40)
    assert 0 < len(faces) <= 40 and len(v) <= 255 and keep.max() < 300


def test_fit_kmd_textured_is_contract_clean_textured_and_grounded(donor):
    _rig, path = donor
    raw = figure_kmd()
    archive = {47255: pcc(48, 48, 1), 47256: pcc(44, 36, 2, vram=(896, 160)), 99: pcc(16, 16, 3, vram=(900, 0))}
    snake = {h: C.loads(archive[h]) for h in (47255, 47256)}
    data, rep, painted = W.fit_kmd_textured(raw, path, ROLES, {"snake": snake, "archive": archive})
    model = K.loads(data)
    assert len(data) <= len(raw) and K.check_compatible(K.loads(raw), model, raw=data) == []
    assert rep["textured"] and set(painted) >= {47255, 47256} and rep["textures"]["images"] >= 1
    tgt = W.kmd_target(K.loads(raw))
    fitted = W.kmd_target(model)
    assert fitted["ground"] == pytest.approx(tgt["ground"], abs=0.02 * tgt["height"])
    assert fitted["height"] <= W.HEAD_ROOM * tgt["height"] * 1.02
    plain, rep2 = W.fit_kmd(raw, path, ROLES)
    assert not rep2["textured"] and K.check_compatible(K.loads(raw), K.loads(plain), raw=plain) == []


def test_the_retarget_editor_profile_reaches_the_vr_fit(donor):
    rig, _path = donor
    original = K.loads(figure_kmd())
    base, _rep, _t = W.fit_prims(original, rig, None)
    wide, rep, _t = W.fit_prims(original, rig, {"profile": {"torso_width": 1.6}})
    assert rep.get("profile")
    w0 = np.ptp(np.concatenate([p["pos"] for p in base])[:, 0])
    w1 = np.ptp(np.concatenate([p["pos"] for p in wide])[:, 0])
    assert w1 > w0 * 1.1                                           # passed through: the first writer dropped it


def test_paint_more_images_than_slots_and_foreign_8bit_textures():
    archive = {1: pcc(32, 32, 1), 2: pcc(16, 16, 2, clut=(768, 226))}
    eight = bytearray(header(64, 64, vram=(320, 0), clut=(520, 226), planes=1, bpp=8, colors=256)) + bytes(64)
    archive[50] = bytes(eight)                                     # an 8-bit stage texture whose palette overlaps CLUT 768
    snake = {h: C.loads(archive[h]) for h in (1, 2)}
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    faces = []
    for k in range(5):                                             # five images for one usable slot
        img = np.zeros((8, 8, 4), np.uint8)
        img[..., k % 3], img[..., 3] = 200, 255
        faces += [(f"i{k}", img, uv, (255, 255, 255))] * (k + 1)
    new, per_face, rep = X.paint(snake, archive, faces)
    assert rep["blocked"] == [2] and set(new) == {1}               # slot 2's palette row is shared with the 8-bit one
    assert {t for t, _uv in per_face} == {1} and rep["flat_colours"] >= 1
    assert C.header(archive[50])["colors"] == 256


def test_paint_keeps_each_archive_inside_its_own_bytes():
    archive = {1: pcc(32, 32, 1), 2: pcc(32, 32, 2, vram=(896, 160)), 3: pcc(16, 16, 3, vram=(700, 0))}
    snake = {h: C.loads(archive[h]) for h in (1, 2)}
    rng = np.random.default_rng(7)
    noisy = rng.integers(0, 255, (64, 64, 4)).astype(np.uint8)
    noisy[..., 3] = 255
    faces = [("n", noisy, np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]), (255,) * 3)] * 3
    bins = {1: 0, 3: 0, 2: 1}
    new, _pf, rep = X.paint(snake, archive, faces, bins=bins)
    for b in (0, 1):
        old = sum(len(archive[h]) + (-len(archive[h]) % 4) for h in archive if bins[h] == b and h in new)
        got = sum(len(new[h]) + (-len(new[h]) % 4) for h in new if bins[h] == b)
        assert got <= old


# ---------------------------------------------------------------------------------------------- the disc layer
def stg(entries) -> bytes:
    """A .stg: entries [(mode, hash, ext, body)] with mode 'c' entries gathered into cached blocks."""
    head, body, pos = [], bytearray(), 0
    i = 0
    while i < len(entries):
        mode, h, ext, data = entries[i]
        if mode != "c":
            head.append(struct.pack("<HBBI", h, ord(mode), ord(ext), len(data)))
            body += data + b"\0" * (-len(data) % 2048)
            i += 1
            continue
        run, block = [], bytearray()
        while i < len(entries) and entries[i][0] == "c":
            _m, hh, ee, dd = entries[i]
            run.append(struct.pack("<HBBI", hh, ord("c"), ord(ee), len(block)))
            block += dd
            i += 1
        run.append(struct.pack("<HBBI", 0, ord("c"), 0xFF, len(block)))
        head += run
        body += block + b"\0" * (-len(block) % 2048)
    hdr = bytes([1, 0]) + struct.pack("<H", 0) + b"".join(head) + bytes(8)
    out = hdr.ljust(0x800, b"\0") + bytes(body)
    return out[:2] + struct.pack("<H", len(out) // 2048) + out[4:]


def stage_dir(stages: dict) -> bytes:
    names = list(stages)
    size = 4 + 12 * len(names)
    out = bytearray(struct.pack("<I", size) + bytes(size - 4))
    out += bytes(-len(out) % 2048)
    for k, n in enumerate(names):
        sector = len(out) // 2048
        struct.pack_into("<8sI", out, 4 + 12 * k, n.encode(), sector)
        out += stages[n] + bytes(-len(stages[n]) % 2048)
    return bytes(out)


SNAKE_TEX = (47255, 47256)
SOLDIER_TEX = (11603, 11604)


def synthetic_disc():
    snake = figure_kmd(SNAKE_TEX)
    soldier = figure_kmd(SOLDIER_TEX, 1.02)
    soldier_lod = figure_kmd(SOLDIER_TEX[:1], 1.02)
    init_models = X.pack_dar([(56141, ord("k"), b"hand" * 20), (39213, ord("k"), snake)])
    init_tex = X.pack_dar([(47255, ord("p"), pcc(48, 48, 1)), (47256, ord("p"), pcc(44, 36, 2, vram=(896, 160))),
                           (62675, ord("p"), pcc(16, 16, 9, vram=(900, 0)))], None) + bytes(8)   # + a terminator
    stages = {"init": stg([("r", 0, "d", init_models), ("n", 0, "d", init_tex), ("c", 59988, "g", b"gcl" * 50)])}
    for k, name in enumerate(("vr_sud01", "vr_sud02")):
        tex = X.pack_dar([(11603, ord("p"), pcc(40, 56, 10 + k, vram=(416 + 16 * k, 440), clut=(800, 236))),
                          (11604, ord("p"), pcc(40, 56, 20 + k, vram=(428, 256), clut=(880 + 16 * k, 237))),
                          (3014, ord("p"), pcc(24, 24, 30 + k, vram=(600, 300), clut=(800, 236)))])
        stages[name] = stg([("s", 24426 + k, "b", b"\x01" * 3000), ("n", 0, "d", tex),
                            ("c", 43169, "o", b"motion" * 100), ("c", 38582, "k", soldier),
                            ("c", 63558, "o", b"m" * 64), ("c", 55267, "k", soldier_lod),
                            ("c", 59988, "g", b"g" * 80), ("s", 44446, "w", b"\x02" * 5000)])
    return stage_dir(stages), {"snake": snake, "soldier": soldier, "soldier_lod": soldier_lod}


def test_stage_files_read_streamed_entries_and_cached_blocks():
    sd, kmds = synthetic_disc()
    dirs = W.stage_dir(sd)
    assert list(dirs) == ["init", "vr_sud01", "vr_sud02"]
    files = W.stage_files(sd, dirs["vr_sud01"])
    assert [(f["index"], f["hash"], f["mode"], f["cached"]) for f in files][:4] == [
        (0, 24426, "s", False), (1, 0, "n", False), (2, 43169, "c", True), (3, 38582, "c", True)]
    k = next(f for f in files if f["hash"] == 38582)
    assert sd[k["offset"]:k["offset"] + k["size"]] == kmds["soldier"]
    lod = next(f for f in files if f["hash"] == 55267)
    assert sd[lod["offset"]:lod["offset"] + lod["size"]] == kmds["soldier_lod"]
    wvx = next(f for f in files if f["hash"] == 44446)
    assert sd[wvx["offset"]:wvx["offset"] + 4] == b"\x02" * 4 and wvx["offset"] % 2048 == 0
    sites = W.model_sites(sd, [39213, 38582, 55267])
    assert [(s["stage"], s["model"]) for s in sites] == [("init", 39213), ("vr_sud01", 38582), ("vr_sud01", 55267),
                                                         ("vr_sud02", 38582), ("vr_sud02", 55267)]
    snake = sites[0]
    assert sd[snake["offset"]:snake["offset"] + snake["size"]] == kmds["snake"] and snake["dar"]
    tex = W.stage_textures(sd, dirs["vr_sud02"])
    assert len(tex) == 1 and set(tex[0]["entries"]) == {11603, 11604, 3014}


def test_stage_dir_writes_in_place_and_repacks_a_dar_to_its_size():
    sd, _k = synthetic_disc()
    st = W.StageDir(sd, strict=False)
    init = W.stage_dir(sd)["init"]
    dar = W.stage_textures(sd, init)[0]
    new = pcc(16, 16, 77)                                         # a different, smaller texture body
    st.repack_dar(dar["offset"], dar["size"], {47255: new}, "init textures")
    blob = bytes(st.data[dar["offset"]:dar["offset"] + dar["size"]])
    ents = X.parse_dar(blob)
    assert dict((h, b) for h, _e, b in ents)[47255].startswith(new) and blob.endswith(bytes(8))
    assert len(st.data) == len(sd) and st.changed_runs() and all(o % 2048 == 0 for o, _b in st.changed_runs())
    with pytest.raises(ValueError, match="allocation"):
        st.put(0, 4, b"12345", "too big")


def test_apply_slot_fits_snake_and_every_soldier_copy_with_their_own_textures(donor, monkeypatch):
    rig, _path = donor
    sd, kmds = synthetic_disc()
    monkeypatch.setattr(W, "PLAYER_KMD_SHA256", __import__("hashlib").sha256(kmds["snake"]).hexdigest())
    st = W.StageDir(sd, strict=False)
    rep = W.apply_slot(st, "player", rig, None)
    assert rep["stages"] == ["init"] and rep["textured_stages"] == 1
    rep = W.apply_slot(st, "enemy:soldier", rig, None)
    assert rep["stages"] == ["vr_sud01", "vr_sud02"] and rep["places"] == 4 and rep["textured_stages"] == 2
    new = bytes(st.data)
    for s in W.model_sites(sd, [39213, 38582, 55267]):
        o, n = sd[s["offset"]:s["offset"] + s["size"]], new[s["offset"]:s["offset"] + s["size"]]
        fitted = K.loads(n)
        assert n != o and len(n) == len(o)
        assert K.check_compatible(K.loads(o), fitted, raw=K.dumps(fitted)) == [], (s["stage"], s["model"])
        assert {t for ob in fitted.objects for t in ob.textures} <= {t for ob in K.loads(o).objects for t in ob.textures}
    # each stage's own texture archive was repainted (its palettes / places are its own), the rest is untouched
    for name in ("vr_sud01", "vr_sud02"):
        off = W.stage_dir(sd)["vr_sud01" if name == "vr_sud01" else "vr_sud02"]
        d = W.stage_textures(new, off)[0]
        assert new[d["offset"]:d["offset"] + d["size"]] != sd[d["offset"]:d["offset"] + d["size"]]
        for h, (o, n) in d["entries"].items():
            C.loads(new[o:o + n])
    gcl = next(f for f in W.stage_files(sd, W.stage_dir(sd)["vr_sud01"]) if f["hash"] == 59988)
    assert new[gcl["offset"]:gcl["offset"] + gcl["size"]] == sd[gcl["offset"]:gcl["offset"] + gcl["size"]]


def test_build_slots_reports_every_slot_and_fit_stage(donor, monkeypatch, tmp_path):
    rig, _path = donor
    sd, kmds = synthetic_disc()
    monkeypatch.setattr(W, "PLAYER_KMD_SHA256", __import__("hashlib").sha256(kmds["snake"]).hexdigest())
    monkeypatch.setattr(W, "read_stage_dir", lambda base: sd)
    monkeypatch.setattr(W, "STAGE_DIR_SIZES", (len(sd),))
    written = {}

    def write_disc(base, stage, out_bin, progress=None):
        written["runs"] = stage.changed_runs()
        return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")), "sectors_written": len(written["runs"])}
    monkeypatch.setattr(W, "write_disc", write_disc)
    lines = []
    with FE.job(lambda p, m: lines.append(m), tmp_path / "snaps"):
        res = W.build_slots(tmp_path / "base.bin", tmp_path / "out" / "x.bin",
                            [("player", rig, None), ("enemy:soldier", rig, None), ("enemy:ninja", rig, None)])
    assert res["slots"]["player"]["status"] == "built" and res["slots"]["enemy:soldier"]["status"] == "built"
    assert res["slots"]["enemy:ninja"]["status"] == "failed" and "is on this disc" in res["slots"]["enemy:ninja"]["reason"]
    evs = [FE.split(m)[1] for m in lines if FE.split(m)[1]]
    for key in ("player", "enemy:soldier"):
        stages = {e["stage"] for e in evs if e.get("model") == key and e.get("stage")}
        assert {"scale", "retarget", "proportion", "weights", "decimate", "encode", "write"} <= stages, (key, stages)
    assert any(e.get("model") == "enemy:ninja" and e.get("stage") == "write" and e.get("state") == "failed"
               for e in evs)


# ---------------------------------------------------------------------------------------------- pick (pick whip)
class Ram:
    """2 MiB of PS1 RAM with the actor system, the view matrix and two figures."""

    def __init__(self):
        self.data = bytearray(0x200000)

    def read_memory(self, a, n):
        return bytes(self.data[a:a + n])

    def put(self, addr, fmt, *v):
        struct.pack_into(fmt, self.data, addr & 0x1FFFFF, *v)


def ram_with(actors, view=((4096, 0, 0), (0, -4096, 0), (0, 0, -4096)), t=(0, 0, 6000)):
    r = Ram()
    r.put(T.STAGE_NAME, "8s", b"vr_sud03")
    r.put(T.VIEW_MATRIX, "<9h", *[c for row in view for c in row])
    r.put(T.VIEW_MATRIX + 0x14, "<3i", *t)
    names = {}
    node = 0x80120000
    for lv in range(T.ACTOR_LEVEL_COUNT):
        head = T.ACTOR_LEVELS + lv * T.ACTOR_LEVEL_SIZE
        r.put(head + 4, "<I", 0)                                     # empty level
    chain = []
    for name, pos in actors:
        if name not in names:
            names[name] = 0x80110000 + 0x40 * len(names)
            r.put(names[name], f"{len(name) + 1}s", name.encode())
        r.put(node + 8, "<4I", 0x800C5218, 0x800C5334, 0, names[name])
        r.put(node + T.ACTOR_POS, "<3h", *pos)
        chain.append(node)
        node += 0x200
    tail = node
    r.put(tail + 8, "<I", 0)
    for a, b in zip(chain, chain[1:] + [tail]):
        r.put(a + 4, "<I", b)
    r.put(T.ACTOR_LEVELS + 5 * T.ACTOR_LEVEL_SIZE + 4, "<I", chain[0] if chain else tail)
    return r


def test_pick_projects_snake_and_the_soldiers_through_the_view_matrix():
    ram = ram_with([("../snake_vr/sna_init.c", (-1500, 1100, 0)), ("watcher.c", (1800, 1100, -2000)),
                    ("breath.c", (0, 0, 0))])
    mem = T.Mem(ram)
    figs = T.figures(mem)
    assert [(f["slot"], f["name"]) for f in figs] == [("player", "Snake"), ("enemy:soldier", "soldier")]
    snake, soldier = figs
    assert snake["screen"][0] < 0.5 < soldier["screen"][0] and snake["top"][1] < snake["screen"][1] < snake["sole"][1]
    r = T.pick(mem, snake["screen"][0], snake["screen"][1])
    assert r["picked"]["slot"] == "player" and r["stage"] == "vr_sud03"
    r = T.pick(mem, soldier["top"][0], (soldier["top"][1] + soldier["sole"][1]) / 2)
    assert r["picked"]["slot"] == "enemy:soldier"
    r = T.pick(mem, 0.5, 0.95)
    assert r["picked"] is None and "no Snake or soldier drawn" in r["note"]
    # a 16:9 window: the 4:3 picture is pillarboxed in the middle
    x = (snake["screen"][0] * 0.75) + 0.125
    assert T.pick(mem, x, snake["screen"][1], 16 / 9)["picked"]["slot"] == "player"
    assert T.run(ram, "Metal Gear Solid - VR Missions", "pick", x=None, y=None)["error"]
    assert T.pick(T.Mem(ram_with([])), 0.5, 0.5)["note"].startswith("no Snake or soldier actor")


# ---------------------------------------------------------------------------------------------- live (pick whip)
def test_live_use_stacks_on_the_running_mod_and_swaps_in_place(monkeypatch, tmp_path):
    from gbox import characters as Ch, filemods
    cfg = SimpleNamespace(cache=str(tmp_path))
    gid = "afd2fc507bb69843"
    prev = filemods.mod_dir(cfg, gid, "mgs_vr_sonic_fit")
    prev.mkdir(parents=True)
    (prev / ".gbox-mod.json").write_text(json.dumps({"name": "mgs_vr_sonic_fit", "character": "sonic",
                                                     "cast": [{"slot": "player", "character": "sonic",
                                                               "status": "built"}]}))
    monkeypatch.setattr(Ch, "_session", lambda ctx, sid: {"session_id": sid, "state": "running", "game_id": gid,
                                                          "mod": "mgs_vr_sonic_fit"})
    monkeypatch.setattr(W, "_can_build_here", lambda ctx: True)
    monkeypatch.setattr(W, "resolve_slot", lambda ctx, game, inp: {"slot": "enemy:soldier", "name": "Genome soldiers",
                                                                   "kind": "enemy"})
    metas = {"sonic": {"slug": "sonic", "name": "Sonic"}, "sa1_knuckles": {"slug": "sa1_knuckles", "name": "Knuckles"}}
    monkeypatch.setattr(Ch, "_api", lambda ctx, method, path, **kw: list(metas.values()))
    built = {}

    def build_mod(ctx, game, rows, name, inp=None):
        built["rows"] = [(s, m["slug"]) for s, m in rows]
        built["name"] = name
        return {"mod": name, "slots": {s: {"status": "built"} for s, _m in rows}}
    monkeypatch.setattr(W, "build_mod", build_mod)
    monkeypatch.setattr(W, "swap_into_session", lambda ctx, g, mod, sid, wait=True: {
        "state": "succeeded", "new_session_id": "w-2", "state_loaded": True, "mod": mod})
    ctx = SimpleNamespace(config=cfg)
    inp = SimpleNamespace(session_id="w-1", x=0.4, y=0.4, slot="player", rebuild=False)
    res = W.live_use(ctx, metas["sa1_knuckles"], {"game_id": gid, "title": "MGS VR"}, inp)
    assert res["status"] == "live_swapped" and res["in_engine"] and res["slot"] == "enemy:soldier"
    assert built["rows"] == [("player", "sonic"), ("enemy:soldier", "sa1_knuckles")]   # Snake stays Sonic
    assert res["mod"] == built["name"] == W.plan_mod_name(built["rows"]) and "state loaded" in res["message"]
    monkeypatch.setattr(W, "swap_into_session", lambda *a, **k: {"state": "failed", "error": "core refused"})
    res = W.live_use(ctx, metas["sa1_knuckles"], {"game_id": gid, "title": "MGS VR"}, inp)
    assert res["status"] == "failed" and "kept running" in res["message"]


def test_characters_routes_live_use_and_resolve_slot_for_vr_missions(monkeypatch):
    from gbox import characters as Ch
    game = {"game_id": "f55555ee6513391b", "title": "Metal Gear Solid - VR Missions (USA)", "platform": "psx"}
    monkeypatch.setattr(Ch, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(W, "resolve_slot", lambda ctx, g, inp: {"slot": "player", "name": "Solid Snake (the player)",
                                                                "kind": "player", "how": "picked"})
    r = Ch.characters_tool(Ch.CharIn(op="resolve_slot", session_id="w-1", x=0.5, y=0.5), SimpleNamespace())
    assert r["result"]["status"] == "resolved" and r["result"]["slot"] == "player" and r["result"]["live"]
    monkeypatch.setattr(W, "resolve_slot", lambda ctx, g, inp: (_ for _ in ()).throw(LookupError("nothing there")))
    r = Ch.characters_tool(Ch.CharIn(op="resolve_slot", session_id="w-1", x=0.5, y=0.9), SimpleNamespace())
    assert r["result"]["status"] == "nothing_there"
    sonic = {"slug": "sonic", "name": "Sonic", "source": {"game_title": "SA2"}, "kind": "character"}
    monkeypatch.setattr(Ch, "_api", lambda ctx, method, path, **kw: [sonic])
    monkeypatch.setattr(W, "live_use", lambda ctx, meta, g, inp: {"status": "live_swapped", "who": meta["slug"]})
    r = Ch.characters_tool(Ch.CharIn(op="live_use", character="sonic", session_id="w-1", x=0.5, y=0.5),
                           SimpleNamespace())
    assert r["result"] == {"status": "live_swapped", "who": "sonic"}


def test_use_routes_every_vr_slot_to_the_writer(monkeypatch):
    import inspect
    from gbox import characters as Ch
    src = inspect.getsource(Ch.characters_tool)
    assert "mgs_vr_swap.is_slot(inp.slot)" in src and 'inp.slot == "cast"' in src


# ---------------------------------------------------------------------------------------------- owned disc
BIN = Path(os.environ.get("GBOX_MGS_VR_BIN", r"D:\gBox\cache\modbase\mgs_vr_us\Metal Gear Solid - VR Missions (USA).bin"))


@pytest.fixture(scope="module")
def disc_stage_dir():
    if not BIN.is_file():
        pytest.skip("owned VR Missions disc image not on this machine")
    return W.read_stage_dir(BIN)


def test_disc_soldiers_live_in_88_stages_with_snakes_tree(disc_stage_dir):
    sd = disc_stage_dir
    sites = W.model_sites(sd, [39213, 38582, 55267, 37617])
    by = {}
    for s in sites:
        by.setdefault(s["model"], []).append(s["stage"])
    assert by[39213] == ["init"] and len(by[38582]) == len(by[55267]) == 88 and sorted(by[37617]) == [
        "vcd_n01", "vcd_n02", "vcd_n03"]
    for h in (38582, 55267, 37617):
        s = next(x for x in sites if x["model"] == h)
        m = K.loads(sd[s["offset"]:s["offset"] + s["size"]])
        assert [o.parent for o in m.objects] == W.TREE
    s = next(x for x in sites if x["model"] == 38582)
    assert s["size"] == 9936


def test_disc_soldier_fit_with_a_synthetic_donor(disc_stage_dir, donor):
    rig, _path = donor
    st = W.StageDir(disc_stage_dir)
    rep = W.apply_slot(st, "enemy:soldier", rig, None)
    assert len(rep["stages"]) == 88 and rep["places"] == 176 and rep["textured_stages"] == 88
    new = bytes(st.data)
    for s in W.model_sites(disc_stage_dir, [38582, 55267])[:6]:
        n = new[s["offset"]:s["offset"] + s["size"]]
        assert K.check_compatible(K.loads(disc_stage_dir[s["offset"]:s["offset"] + s["size"]]), K.loads(n),
                                  raw=K.dumps(K.loads(n))) == []
