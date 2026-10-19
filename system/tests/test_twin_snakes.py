"""Metal Gear Solid: The Twin Snakes (GC): stage.dat container, .kms models, .tri texture sets, the cast reader,
the writer (fit, budget, stage rebuild, hidden accessories), slots / pick whip, and the live RAM write - all on
synthetic data built here (no game files). The owned-disc checks at the end run only with TTS_ISO set."""
from __future__ import annotations

import base64
import os
import struct
import types
from pathlib import Path

import numpy as np
import pytest

from gbox import ts_kms as K
from gbox import ts_stage as S
from gbox import ts_tex as T
from gbox import twin_snakes as TS
from gbox import twin_snakes_swap as W

# ----------------------------------------------------------------------------------------------- builders

BONES = [(0, 0, 0), (0, 20, 0), (0, 170, 0), (-30, 400, 0), (-165, 400, 0), (-165, 120, 0), (-165, -140, 0),
         (30, 400, 0), (165, 400, 0), (165, 120, 0), (165, -140, 0), (0, 460, 0), (0, 560, 0),
         (-90, -40, 0), (-90, -500, 0), (-90, -950, 0), (-90, -1000, 100),
         (90, -40, 0), (90, -500, 0), (90, -950, 0), (90, -1000, 100)]
LAYER = (0x111111, 0x222222, 0x333333)                 # bump, colour, specular strcodes of the body layer


def _box(c, r=40.0):
    c = np.asarray(c, float)
    v = np.array([[x, y, z] for x in (-r, r) for y in (-r, r) for z in (-r, r)]) + c
    f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4),
         (1, 5, 7), (1, 7, 3)]
    return v, np.array(f)


def template(name: int = 0xF7A622, tex_set: int = 0x413AA8, nmesh: int = 21, nb: int = 21, parts_on=None) -> K.Kms:
    """A bare model on the MGS2 skeleton (21 bones, or 53 like a cut-scene model: fingers on the hands, face bones
    on the head): header, bones, mesh-group header, mesh records and one part record (texture layer LAYER) on the
    meshes in `parts_on` (default every bone mesh) - what ts_kms.encode keeps from a stock model."""
    extra = [(6 if k < 8 else 10 if k < 16 else 12) for k in range(nb - 21)]
    parents = K.PARENTS + extra
    world = BONES + [tuple(float(x) for x in np.add(BONES[p], (0, -20, 10))) for p in extra]
    nmesh = max(nmesh, nb)
    G = 0x60 + 0x40 * nb
    head = bytearray(0x60)
    struct.pack_into(">6I", head, 0, 0, nb, nmesh, tex_set, name, 3)
    struct.pack_into(">6f", head, 0x18, -1260, -1260, -1260, 1260, 1260, 1260)
    struct.pack_into(">HH", head, 0x48, nb, 0xFFFE)
    struct.pack_into(">I", head, 0x5C, G)
    bones = bytearray()
    for p, w in zip(parents, world):
        pw = world[p] if p >= 0 else (0, 0, 0)
        loc = tuple(a - b for a, b in zip(w, pw))
        bones += struct.pack(">Ii3f3f4f4f", 0, p, *loc, *w, -50, -50, -50, 0, 50, 50, 50, 0)
    g = struct.pack(">IIHHII", 0xFF54, 0x15039E, nmesh, nmesh, 0, 0x14)
    meshes = []
    on = set(range(min(nb, 21))) if parts_on is None else set(parts_on)
    for i in range(nmesh):
        w = world[i] if i < nb else BONES[12]
        par = parents[i] if i < nb else 12
        rec = struct.pack(">II6f3f3fHhIHHI", 0, 0, -50, -50, -50, 50, 50, 50, 0, 0, 0, *w, 1, par, K.MARK, 0, 0xFFFF, 0)
        part = struct.pack(">4IHH4I", 0x1F8, *LAYER, 0, 0, 0, 0, 3, 0)
        parts = [K.Part(0x1F8, LAYER, [], [], [], part)] if i in on else []
        meshes.append(K.Mesh(rec, par, parts, tuple(float(x) for x in w)))
    data = bytes(head + bones + g)
    return K.Kms(data, 0, tex_set, name, [{"parent": p, "local": (0, 0, 0), "world": w}
                                           for p, w in zip(parents, world)], meshes, None, None, None, [], G)


def body_mesh(scale: float = 1.0):
    P, F, B = [], [], []
    for b in range(21):
        v, f = _box(BONES[b], 30 * scale)
        F.append(f + sum(len(x) for x in P))
        P.append(v)
        B += [b] * len(v)
    P = np.concatenate(P)
    F = np.concatenate(F)
    N = P - np.repeat(np.array(BONES, float), 8, 0)
    UV = (P[:, :2] - P[:, :2].min(0)) / np.ptp(P[:, :2], 0)
    return P, N, UV, np.array(B), F


def model_bytes(name=0xF7A622, tex_set=0x413AA8) -> bytes:
    P, N, UV, B, F = body_mesh()
    return K.encode(template(name, tex_set), P, N, UV, B, F)


def tpl(images: list[dict]) -> bytes:
    """A standard GameCube TPL: images [{fmt, w, h, data, pal (fmt, bytes) | None}]."""
    n = len(images)
    hdr = 12 + 8 * n
    ih = hdr
    ph = ih + 0x24 * n
    body_off = (ph + 12 * n + 31) // 32 * 32
    body, offs, pals = bytearray(), [], []
    for im in images:
        offs.append(body_off + len(body))
        body += im["data"] + bytes((-len(im["data"])) % 32)
        if im.get("pal"):
            pals.append(body_off + len(body))
            body += im["pal"][1] + bytes((-len(im["pal"][1])) % 32)
        else:
            pals.append(0)
    out = bytearray(struct.pack(">III", 0x0020AF30, n, 12))
    for i, im in enumerate(images):
        out += struct.pack(">II", ih + 0x24 * i, (ph + 12 * i) if im.get("pal") else 0)
    for i, im in enumerate(images):
        out += struct.pack(">HHII4IfBBBB", im["h"], im["w"], im["fmt"], offs[i], 1, 1, 1, 1, 0.0, 0, 0, 0, 0)
    for i, im in enumerate(images):
        if im.get("pal"):
            out += struct.pack(">HBBII", len(im["pal"][1]) // 2, 0, 0, im["pal"][0], pals[i])
        else:
            out += bytes(12)
    out += bytes(body_off - len(out))
    return bytes(out + body)


def texture_set(entries: list[tuple[int, dict]]) -> bytes:
    """A .tri set: entries [(strcode, image)] -> header, 0x80-byte entries, the TPL."""
    n = len(entries)
    t = (0x20 + 0x80 * n + 0xFF) // 0x100 * 0x100
    out = bytearray(0x20)
    struct.pack_into(">I", out, 0x10, n)
    struct.pack_into(">I", out, 0x18, t)
    for i, (h, _im) in enumerate(entries):
        e = bytearray(0x80)
        struct.pack_into(">I", e, 0x10, h)
        struct.pack_into(">I", e, 0x1C, i)
        out += e
    out += bytes(t - len(out))
    return bytes(out + tpl([im for _h, im in entries]))


def body_set(colour=(200, 40, 40)) -> bytes:
    rgba = np.zeros((32, 32, 4), np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = 255
    pal = struct.pack(">256H", *[(255 << 8) | i for i in range(256)])
    bump = {"fmt": 9, "w": 32, "h": 32, "data": bytes(range(256)) * 4, "pal": (0, pal)}
    col = {"fmt": 14, "w": 32, "h": 32, "data": T.encode(14, 32, 32, rgba)}
    spec = {"fmt": 8, "w": 32, "h": 32, "data": bytes([0x5A]) * 512, "pal": (0, pal[:32])}
    null = {"fmt": 14, "w": 2, "h": 2, "data": bytes(32)}
    return texture_set([(LAYER[0], bump), (LAYER[1], col), (LAYER[2], spec), (0x9576EF, null)])


def stage_blob(files: list[tuple[int, int, bytes]]) -> bytes:
    st = S.Stage("x", 0, 0)
    data, rows = bytearray(), []
    for t, h, d in files:
        rows.append(((t << 24) | h, len(data)))
        data += d + bytes((-len(d)) % 0x20)
    st.pages.append(S.Page(3, bytes(data), rows))
    return S.build_stage(st, {3}, 6)


def stage_dat(stages: list[tuple[str, bytes]], slack: int = 0x4000) -> bytes:
    n = len(stages)
    head = bytearray(struct.pack(">IIHHI", 0x401D1141, 0x00010001, n, 0xCCCC, 0))
    sec = (16 + 12 * n + S.SECTOR - 1) // S.SECTOR
    blobs = bytearray()
    for name, blob in stages:
        head += struct.pack(">8sI", name.encode(), sec + len(blobs) // S.SECTOR)
        blob = blob + bytes(slack)
        blobs += blob + bytes((-len(blob)) % S.SECTOR)
    head += bytes(sec * S.SECTOR - len(head))
    return bytes(head + blobs)


def accessory(name: int, tex_set: int, textures=(0x777777, 0, 0)) -> bytes:
    """A prop-format model (flags 0x01b253a3, no bone table) of the given texture set: one mesh, one part."""
    head = bytearray(0x60)
    struct.pack_into(">6I", head, 0, 0x01B253A3, 1, 1, tex_set, name, 3)
    struct.pack_into(">I", head, 0x5C, 0x60)
    g = struct.pack(">IIHHII", 0xFF64, 0xA9, 1, 1, 0, 0x14)
    rec = struct.pack(">II6f3f3fHhIHHI", 0, 0, -1, -1, -1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, -1, 0x4755DE, 1, 0xFFFF, 0x5C)
    part = struct.pack(">4IHH4I", 0x1F8, *textures, 0, 0, 0, 0, 3, 0)
    return bytes(head + g + rec + part + bytes(0x40))


# ----------------------------------------------------------------------------------------------- strcode / container

def test_strcode_matches_the_disc_names():
    assert S.strcode("snake_def") == 0xF7A622
    assert S.strcode("sna_def") == 0x413AA8
    assert S.strcode("out_cold") == 0x26E012
    assert S.strcode("in_door") == 0x23E574
    assert S.strcode("hev_grd") == 0x914575
    assert S.strcode("scenerio") == 0x180720


def test_stage_round_trip_is_byte_exact_and_rebuild_respects_the_span():
    files = [(S.MODEL, 0xF7A622, model_bytes()), (S.TEXTURES, 0x413AA8, body_set()), (0x06, 0x180720, b"gcx" * 10)]
    blob = stage_blob(files)
    st = S.parse_stage(blob + bytes(64), "r_sna", 1, len(blob) + 64)
    assert S.build_stage(st) == blob                       # unchanged pages keep their stock zlib stream
    got = {(f.type, f.hash): f.data for f in st.files()}
    assert got[(0x06, 0x180720)].rstrip(b"\0") == b"gcx" * 10
    new = S.rebuild_stage(st, {(0x06, 0x180720): b"GCX" * 10})
    st2 = S.parse_stage(new, "r_sna", 1, len(new))
    assert st2.find(0x180720, 0x06).data.rstrip(b"\0") == b"GCX" * 10
    st3 = S.parse_stage(blob, "r_sna", 1, len(blob))
    with pytest.raises(S.StageTooBig):
        S.rebuild_stage(st3, {(0x06, 0x180720): os.urandom(200000)})
    with pytest.raises(KeyError):
        S.rebuild_stage(S.parse_stage(blob, "r_sna", 1, len(blob) + 0x100000), {(0x0A, 0x123456): b"x"})


def test_stage_dat_directory_spans_and_lookup():
    a = stage_blob([(S.MODEL, 0xF7A622, model_bytes())])
    b = stage_blob([(S.MODEL, 0x26E012, model_bytes(0x26E012, 0x26E012))])
    sd = S.StageDat.from_bytes(stage_dat([("r_sna", a), ("area01a", b)]))
    assert sd.names() == ["r_sna", "area01a"]
    off, span = sd.span(0)
    assert off % S.SECTOR == 0 and span >= len(a)
    assert sd.stage("area01a").find(0x26E012, S.MODEL) is not None
    assert sd.stages_with(0xF7A622) == [0] and sd.stages_with(0x26E012) == [1]


# ----------------------------------------------------------------------------------------------- textures

def test_texture_set_decode_encode_and_in_place_replace():
    data = body_set()
    ts = T.TextureSet(data)
    assert [t.hash for t in ts.textures] == list(LAYER) + [0x9576EF]
    col = ts.by_hash(LAYER[1])
    assert (col.w, col.h, col.fmt) == (32, 32, 14)
    rgba = ts.rgba(col)
    assert rgba.shape == (32, 32, 4) and abs(int(rgba[..., 0].mean()) - 200) < 8
    bump = ts.rgba(ts.by_hash(LAYER[0]))
    assert bump[0, 0, 3] == 255 and bump[0, 1, 0] == 1  # C8 through the IA8 palette, tile order undone
    green = np.zeros((10, 20, 4), np.uint8)
    green[..., 1] = 230
    green[..., 3] = 255
    ts.replace_image(col, green)                           # any size in, the image's own size and format out
    assert len(ts.data) == len(data)
    assert ts.rgba(ts.by_hash(LAYER[1]))[..., 1].mean() > 200
    for fmt in (4, 5, 6, 3, 1):
        img = np.random.default_rng(fmt).integers(0, 255, (8, 8, 4), dtype=np.uint8)
        img[..., 3] = 255
        back = T.decode(fmt, 8, 8, T.encode(fmt, 8, 8, img))
        assert back.shape == (8, 8, 4)


def test_flatten_keeps_palettes_and_skips_shared_stand_ins():
    sets = {0x413AA8: T.TextureSet(body_set())}
    atlas = np.zeros((32, 32, 4), np.uint8)
    atlas[..., 2] = 255
    atlas[..., 3] = 255
    changed, touched = W.paint_layer(sets, LAYER, atlas, 0x413AA8)
    assert changed == {0x413AA8: True} and touched == set(LAYER)
    ts = sets[0x413AA8]
    assert len(set(ts.rgba(ts.by_hash(LAYER[0]))[..., 0].ravel())) == 1       # bump flat
    assert ts.rgba(ts.by_hash(LAYER[2]))[..., 0].max() == 0                     # specular dark
    assert ts.rgba(ts.by_hash(LAYER[1]))[..., 2].mean() > 200                   # the donor atlas
    _c, t2 = W.paint_layer(sets, (0x9576EF, 0, 0), atlas, 0x413AA8)            # the 2x2 null stays
    assert t2 == set()


# ----------------------------------------------------------------------------------------------- models

def test_kms_encode_parse_decode_round_trip():
    P, N, UV, B, F = body_mesh()
    t = template()
    data = K.encode(t, P, N, UV, B, F)
    m = K.parse(data)
    st = K.stats(m)
    assert st["bones"] == 21 and st["meshes"] == 21 and st["parts"] == 21 and st["triangles"] >= len(F)
    prims = K.decode(m)
    got = np.concatenate([p["pos"] for p in prims])
    assert np.allclose(np.unique(np.round(got), axis=0), np.unique(np.round(P), axis=0))
    assert sum(len(p["tris"]) for p in prims) == len(F)
    for p in prims:                                        # rigid: every vertex on its own mesh's bone
        assert (p["J"][:, 0] == p["mesh"]).all() and np.allclose(p["W"][:, 0], 1)
        a, b, c = (p["pos"][p["tris"][:, k]] for k in range(3))
        out = (a + b + c) / 3 - np.asarray(BONES[p["mesh"]], float)
        assert (np.einsum("ij,ij->i", np.cross(b - a, c - a), out) > 0).all()   # counter-clockwise, outward
        assert np.abs(p["uv"]).max() <= 1.0001
    assert K.colour_texture(m.meshes[0].parts[0].tex) == LAYER[1]


def test_palette_split_keeps_every_triangle_and_its_winding():
    strip = list(range(40))
    bone = {v: v // 3 for v in strip}                      # 14 bones along one strip
    parts = K.split_palette(strip, bone.get, 4)
    assert all(len({bone[v] for v in s}) <= 4 for s in parts)

    def tris(s):
        out = set()
        for (a, b, c) in K.strip_triangles(len(s)):
            t = (s[a], s[b], s[c])
            if len(set(t)) == 3:
                k = t.index(min(t))
                out.add(t[k:] + t[:k])
        return out
    whole = tris(strip)
    assert set().union(*[tris(s) for s in parts]) == whole


def test_hide_and_part_textures():
    acc = accessory(0x26523A, 0x413AA8)
    assert W.part_textures(acc) == {0x777777}
    hidden = K.hide(acc)
    assert len(hidden) == len(acc) and W.part_textures(hidden) == set()
    m = K.parse(model_bytes())
    assert W.part_textures(m.data) == set(LAYER)


# ----------------------------------------------------------------------------------------------- reader

def test_reader_exports_a_rigged_textured_glb(tmp_path):
    from gbox.re4gc_models import _gltf_load
    m = K.parse(model_bytes())
    r = TS.export(m, [T.TextureSet(body_set())], tmp_path / "snake.glb", "Snake")
    gl, acc, image = _gltf_load(r["path"])
    assert len(gl["skins"][0]["joints"]) == 21 and gl["nodes"][0]["name"] == "hip"
    assert r["roles"]["head"] == "head" and r["roles"]["l_hand"] == "l_hand" and len(r["roles"]) == 18
    assert r["textures"] == 1 and not r["missing_textures"]
    pos = acc(gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"])
    assert np.abs(pos).max() < 2.0                          # metres
    assert image(0).shape[2] == 4


def test_dedicated_row_roster_and_disc_filter():
    from gbox import characters as C
    row = next(r for r in C.DEDICATED if r[0] == "twin_snakes")
    assert row[1]("metal gear solid: the twin snakes (usa) (disc 1)", "gamecube")
    assert not row[1]("metal gear solid: the twin snakes", "ps2")
    keys1 = {e["key"] for e in TS.roster(1)}
    keys2 = {e["key"] for e in TS.roster(2)}
    assert {"snake_def", "out_cold", "in_door", "hev_grd", "in_gus"} <= keys1
    assert "liq_def" in keys2 and "liq_def" not in keys1 and "in_gus" not in keys2
    assert TS.disc_of({"title": "Metal Gear Solid: The Twin Snakes (USA) (Disc 2)"}) == 2
    assert TS.disc_of(header=b"GGSEA4\x01\x00") == 2
    cfg = types.SimpleNamespace(cache=Path("/nonexistent"))
    ents = C.dedicated_entries(cfg, {"title": "Metal Gear Solid: The Twin Snakes (USA) (Disc 2)", "game_id": "x"},
                               "twin_snakes", row[2])
    assert "liq_def" in {e["key"] for e in ents}
    assert C.READER_VERSIONS["twin_snakes"] == ("gbox.twin_snakes", "tts_reader")
    assert C.reader_version("twin_snakes") == TS.READER_VERSION


# ----------------------------------------------------------------------------------------------- slots / pick whip

def test_slots_groups_and_plans():
    assert W.keys_for("player") == ["snake_def"]
    assert set(W.keys_for("enemies")) == {"out_cold", "out_cold2", "in_door", "in_gus", "in_gus_blue_def", "hev_grd"}
    assert W.keys_for("soldiers") == W.keys_for("enemies")
    assert W.keys_for("model:hev_grd") == ["hev_grd"] and W.keys_for("tts_psy_def") == ["psy_def"]
    assert all(W.is_slot(s) for s in ("player", "enemies", "bosses", "npcs", "all", "cast", "model:out_cold"))
    with pytest.raises(ValueError):
        W.keys_for("model:nobody")
    plan = W.plan_cast([("player", "sonic"), ("enemies", "shadow"), ("model:hev_grd", "knuckles"), ("", "amy")])
    assert plan["snake_def"] == "sonic" and plan["hev_grd"] == "knuckles" and plan["out_cold"] == "shadow"
    assert plan["psy_def"] == "amy"
    rows = W.cast_slots()
    assert rows[0]["slot"] == "player" and rows[0]["kind"] == "player"
    assert any(r["slot"] == "model:out_cold" and r["kind"] == "enemy" for r in rows)
    assert all(r.get("aggregate") for r in rows if r["kind"] == "group")
    assert W.mod_name("player", {"snake_def": "sonic"}) == W.mod_name("player", {"snake_def": "sonic"})


def test_pick_whip_maps_models_and_points_to_slots():
    assert W.slot_for_model("out_cold_sh") == "model:out_cold"
    assert W.slot_for_model(0xF7A622) == "player" and W.slot_for_model("#55ab65") == "player"
    assert W.slot_for_model("0x914575") == "model:hev_grd" and W.slot_for_model("w12c_elvsk01") is None
    assert W.pick_slot(["snake_def", "out_cold", "out_cold_sh"], "", 0.1, 0.2) == "model:out_cold"
    assert W.pick_slot(["snake_def", "out_cold"], "", 0.5, 0.5) == "player"          # the camera follows Snake
    assert W.pick_slot(["snake_def", "in_door", "hev_grd"], "guard in a black mask") == "enemies"
    assert W.pick_slot(["snake_def", "in_door"], "a soldier") == "model:in_door"
    assert W.pick_slot(["snake_def"], "", 0.9, 0.9) == "player"
    assert W.pick_slot(["snake_def", "psy_def"], "Psycho Mantis") == "model:psy_def"
    assert W.pick_slot(["snake_def", "out_cold"], "player") == "player"


def test_routing_coverage_and_cast_builder():
    from gbox import cast_swap, char_coverage
    game = {"game_id": "79965f951e479d2b", "title": "Metal Gear Solid: The Twin Snakes (USA) (Disc 1)",
            "platform": "gamecube"}
    w = char_coverage.writer_for(game)
    assert w["writer"] == "gbox.twin_snakes_swap" and w["routed"]
    slots = {r["slot"] for r in char_coverage.cast_slots(game)}
    assert {"player", "enemies", "model:out_cold", "model:psy_def"} <= slots
    assert cast_swap.strategy("gbox.twin_snakes_swap")[0] == "pairs"
    assert "gbox.twin_snakes_swap" in cast_swap.BUILDERS
    rows = cast_swap.slot_rows(game)
    assert "enemies" not in {r["slot"] for r in rows} and "model:in_door" in {r["slot"] for r in rows}


# ----------------------------------------------------------------------------------------------- writer

@pytest.fixture(scope="module")
def donor(tmp_path_factory):
    """A rigged donor GLB with body roles: the synthetic model, bigger boxes, painted green."""
    d = tmp_path_factory.mktemp("donor")
    P, N, UV, B, F = body_mesh(1.3)
    m = K.parse(K.encode(template(), P, N, UV, B, F))
    green = body_set((20, 200, 20))
    r = TS.export(m, [T.TextureSet(green)], d / "donor.glb", "Donor")
    return W.load_donor("donor", r["path"], r["roles"], "Donor")


def test_fit_model_retargets_within_the_budget(donor):
    m = K.parse(model_bytes())
    fit, atlas = W.fit_model(donor, m, "snake_def", 1.0, (32, 32))
    assert len(fit.data) <= len(m.data)
    n = K.parse(fit.data)
    assert [b["world"] for b in n.bones] == [b["world"] for b in m.bones]     # the skeleton is the game's
    assert atlas.shape == (32, 32, 4) and atlas[..., 1].mean() > 150
    tight, _a = W.fit_model(donor, m, "snake_def", 0.6, (32, 32))           # a smaller budget decimates
    assert len(tight.data) <= int(len(m.data) * 0.6)
    assert tight.report["triangles"] < fit.report["triangles"]
    with pytest.raises(ValueError):
        W.load_donor("x", donor.glb, {"hip": "hip"})                          # no head role: not retargetable


def _disc(snake_slack=0x4000):
    snake = stage_blob([(S.MODEL, 0xF7A622, model_bytes()), (S.TEXTURES, 0x413AA8, body_set()),
                        (S.MODEL, 0x26523A, accessory(0x26523A, 0x413AA8)),          # Snake's bandana tail
                        (S.MODEL, 0x4632AF, accessory(0x4632AF, 0x49E8C3))])         # an unrelated item
    cold = stage_blob([(S.MODEL, 0x26E012, model_bytes(0x26E012, 0x26E012)),
                       (S.TEXTURES, 0x26E012, body_set()),
                       (S.MODEL, 0x1FB776, accessory(0x1FB776, 0x26E012, (LAYER[1], 0, 0)))])  # the sling
    demo = stage_blob([(S.MODEL, 0x26E012, model_bytes(0x26E012, 0x26E012)), (S.TEXTURES, 0x26E012, body_set())])
    return stage_dat([("r_sna", snake), ("area01a", cold), ("demo01a", demo)], snake_slack)


def test_build_stage_dat_replaces_paints_and_hides(donor):
    sdat = _disc()
    new, rep = W.build_stage_dat(sdat, {"snake_def": donor, "out_cold": donor})
    assert len(new) == len(sdat)
    by = {r["stage"]: r for r in rep["stages"]}
    assert set(by) == {"r_sna", "area01a", "demo01a"}       # cutscenes are part of a replacement by default
    assert by["r_sna"]["hidden"] == ["26523a"] and by["area01a"]["hidden"] == ["1fb776"]
    assert rep["slots"]["snake_def"]["status"] == "built" and rep["slots"]["out_cold"]["status"] == "built"
    sd = S.StageDat.from_bytes(new)
    st = sd.stage("r_sna")
    m = K.parse(st.find(0xF7A622, S.MODEL).data)
    assert K.stats(m)["triangles"] > 100
    ts = T.TextureSet(st.find(0x413AA8, S.TEXTURES).data)
    assert ts.rgba(ts.by_hash(LAYER[1]))[..., 1].mean() > 150                  # the donor's green atlas
    assert W.part_textures(st.find(0x26523A, S.MODEL).data) == set()            # bandana hidden
    assert W.part_textures(st.find(0x4632AF, S.MODEL).data) == {0x777777}       # other items untouched
    old = S.StageDat.from_bytes(sdat)
    o, s = old.span(2)
    assert new[o:o + s] != sdat[o:o + s]
    demo = sd.stage("demo01a")
    assert K.stats(K.parse(demo.find(0x26E012, S.MODEL).data))["triangles"] > 100
    demo_tex = T.TextureSet(demo.find(0x26E012, S.TEXTURES).data)
    assert demo_tex.rgba(demo_tex.by_hash(LAYER[1]))[..., 1].mean() > 150
    assert "demo01a" in rep["slots"]["out_cold"]["stages_written"]


def test_explicit_gameplay_only_mode_preserves_cinematic_bytes(donor):
    sdat = _disc()
    new, rep = W.build_stage_dat(sdat, {"out_cold": donor}, cutscenes=False)
    off, size = S.StageDat.from_bytes(sdat).span(2)
    assert new[off:off + size] == sdat[off:off + size]
    assert [r["stage"] for r in rep["stages"]] == ["area01a"]


def test_cutscene_with_only_the_low_detail_twin_is_also_replaced(donor):
    body = stage_blob([(S.MODEL, 0xF7A622, model_bytes()), (S.TEXTURES, 0x413AA8, body_set())])
    twin = stage_blob([(S.MODEL, 0x55AB65, model_bytes(0x55AB65, 0x413AA8)), (S.TEXTURES, 0x413AA8, body_set())])
    sdat = stage_dat([("area01a", body), ("demo_twn", twin)], 0x4000)
    new, rep = W.build_stage_dat(sdat, {"snake_def": donor})
    assert set(rep["slots"]["snake_def"]["stages_written"]) == {"area01a", "demo_twn"}
    demo = S.StageDat.from_bytes(new).stage("demo_twn")
    assert K.stats(K.parse(demo.find(0x55AB65, S.MODEL).data))["triangles"] > 100
    ts = T.TextureSet(demo.find(0x413AA8, S.TEXTURES).data)
    assert ts.rgba(ts.by_hash(LAYER[1]))[..., 1].mean() > 150


def test_build_shrinks_the_budget_until_every_stage_fits(donor):
    sdat = _disc(snake_slack=0)
    new, rep = W.build_stage_dat(sdat, {"snake_def": donor})
    assert rep["slots"]["snake_def"]["status"] == "built" and len(new) == len(sdat)


def test_build_cast_reports_slots_off_the_disc(donor, monkeypatch):
    sdat = _disc()
    rep = W.build_stage_dat(sdat, {"liq_def": donor})[1]
    assert rep["slots"]["liq_def"]["status"] == "failed"


def test_build_mod_writes_a_disc_image_copy(donor, tmp_path):
    from gbox.formats.gcfst import build_fst
    sdat = _disc()
    files = [("stage.dat", 0x8000, len(sdat))]
    fst = build_fst(files)
    img = bytearray(0x8000 + len(sdat) + 0x1000)
    img[:6] = b"GGSEA4"
    img[0x20:0x40] = b"METAL GEAR SOLID THE TWIN SNAKES"[:32]
    struct.pack_into(">III", img, 0x420, 0x2000, 0x4000, len(fst))
    img[0x4000:0x4000 + len(fst)] = fst
    img[0x8000:0x8000 + len(sdat)] = sdat
    iso = tmp_path / "tts.iso"
    iso.write_bytes(bytes(img))
    cfg = types.SimpleNamespace(cache=tmp_path / "cache")
    b = W.build_mod(cfg, {"game_id": "79965f951e479d2b", "title": "TTS"}, iso, "tts_player_test",
                    {"snake_def": donor})
    out = Path(b["image"]).read_bytes()
    assert iso.read_bytes() == bytes(img)                 # the source image is never written
    assert len(out) == len(img) and out[0x8000:0x8000 + len(sdat)] != sdat
    rec = __import__("json").loads((Path(b["dir"]) / ".gbox-mod.json").read_text())
    assert rec["writer"] == "gbox.twin_snakes_swap" and rec["cast"] == [["snake_def", "donor"]]
    assert rec["replacement_scope"]["in_engine_cutscenes"] == "written_unverified"
    assert rec["replacement_scope"]["complete"] is False
    assert rec["replacement_scope"]["prerecorded_movies"] == "unchanged"
    items = W._live_file(cfg, "79965f951e479d2b", "tts_player_test")      # the live write ships with the mod
    assert {i["kind"] for i in items} == {"model", "texels", "hide"}


# ----------------------------------------------------------------------------------------------- live (RAM)

BASE = 0x80000000


def _load(data: bytes, address: int, tex_ptr: int) -> bytes:
    """The game's loader on a model copy at `address` (0x806b6be8 / 0x806b6860 / 0x806a89f4): offsets -> pointers,
    the parts' texture strcodes -> texture-entry pointers."""
    d = bytearray(data)
    G = struct.unpack_from(">I", d, 0x5C)[0]
    Ga = address + G
    struct.pack_into(">I", d, 0x5C, Ga)
    for o in (0x4C, 0x50, 0x54, 0x58):
        v = struct.unpack_from(">I", d, o)[0]
        struct.pack_into(">I", d, o, Ga + v if v else 0)
    nmesh = struct.unpack_from(">H", d, G + 8)[0]
    recs = struct.unpack_from(">I", d, G + 0x10)[0]
    struct.pack_into(">I", d, G + 0x10, Ga + recs)
    for i in range(nmesh):
        mo = G + recs + 0x48 * i
        npart, poff = struct.unpack_from(">H", d, mo + 0x38)[0], struct.unpack_from(">I", d, mo + 0x44)[0]
        struct.pack_into(">I", d, mo + 0x44, Ga + poff if npart else 0)
        for k in range(npart):
            po = G + poff + 0x24 * k
            struct.pack_into(">3I", d, po + 4, tex_ptr, tex_ptr + 0x80, tex_ptr + 0x100)
            nstrip = struct.unpack_from(">H", d, po + 0x10)[0]
            ul, ul2, _t, so = struct.unpack_from(">4I", d, po + 0x14)
            struct.pack_into(">II", d, po + 0x14, Ga + ul, Ga + ul2 if ul2 else 0)
            struct.pack_into(">I", d, po + 0x20, Ga + so)
            for s in range(nstrip):
                q = G + so + 0x20 * s
                offs = list(struct.unpack_from(">7I", d, q))
                for a, b in ((1, 0), (2, 0), (3, 2), (4, 3)):
                    if not offs[a]:
                        offs[a] = offs[b]
                struct.pack_into(">7I", d, q, *[Ga + o if o else 0 for o in offs])
    return bytes(d)


def _unload(ram: bytes, address: int) -> bytes:
    """Pointers back to file offsets (texture fields kept), so ts_kms can read what the draw loop would."""
    d = bytearray(ram)
    Ga = struct.unpack_from(">I", d, 0x5C)[0]
    G = Ga - address
    struct.pack_into(">I", d, 0x5C, G)
    for o in (0x4C, 0x50, 0x54, 0x58):
        v = struct.unpack_from(">I", d, o)[0]
        struct.pack_into(">I", d, o, v - Ga if v else 0)
    nmesh = struct.unpack_from(">H", d, G + 8)[0]
    recs = struct.unpack_from(">I", d, G + 0x10)[0] - Ga
    struct.pack_into(">I", d, G + 0x10, recs)
    for i in range(nmesh):
        mo = G + recs + 0x48 * i
        npart, pp = struct.unpack_from(">H", d, mo + 0x38)[0], struct.unpack_from(">I", d, mo + 0x44)[0]
        poff = pp - Ga if npart else 0
        struct.pack_into(">I", d, mo + 0x44, poff)
        for k in range(npart):
            po = G + poff + 0x24 * k
            struct.pack_into(">3I", d, po + 4, *LAYER)
            nstrip = struct.unpack_from(">H", d, po + 0x10)[0]
            ul, ul2, _t, so = struct.unpack_from(">4I", d, po + 0x14)
            struct.pack_into(">II", d, po + 0x14, ul - Ga, ul2 - Ga if ul2 else 0)
            struct.pack_into(">I", d, po + 0x20, so - Ga)
            for s in range(nstrip):
                q = G + so - Ga + 0x20 * s
                offs = struct.unpack_from(">7I", d, q)
                struct.pack_into(">7I", d, q, *[o - Ga if o else 0 for o in offs])
    return bytes(d)


class FakeDolphin:
    def __init__(self, size: int):
        self.mem = bytearray(size)
        self.state = "RUNNING"
        self.paused = 0

    def query_runtime(self):
        return {"state": self.state}

    def pause(self):
        self.state = "PAUSED"
        self.paused += 1

    def resume(self):
        self.state = "RUNNING"

    def read_memory(self, a, n):
        return bytes(self.mem[a - BASE:a - BASE + n])

    def write_memory(self, a, data):
        assert self.state == "PAUSED"
        self.mem[a - BASE:a - BASE + len(data)] = data
        return {"verified": True}


def test_find_loaded_and_relocate_against_the_engines_loader(donor):
    old = model_bytes()
    addr = BASE + 0x1000
    loaded = _load(old, addr, 0x80900000)
    ram = bytearray(0x40000)
    ram[0x1000:0x1000 + len(loaded)] = loaded
    hits = W.find_loaded(bytes(ram), BASE)
    assert [(h["address"], h["key"]) for h in hits] == [(addr, "snake_def")]
    new, _a = W.fit_model(donor, K.parse(old), "snake_def", 1.0, (32, 32))
    out = W.relocate(new.data, addr, loaded)
    parts = struct.unpack_from(">3I", out, 0)                 # header untouched
    assert parts[1] == 21
    back = K.parse(_unload(out, addr))
    ref = K.parse(new.data)
    assert K.stats(back) == K.stats(ref)
    a = np.concatenate([p["pos"] for p in K.decode(back)])
    b = np.concatenate([p["pos"] for p in K.decode(ref)])
    assert np.allclose(a, b)
    g = struct.unpack_from(">I", out, 0x5C)[0] - addr          # resolved texture pointers kept from the loaded copy
    recs = struct.unpack_from(">I", out, g + 0x10)[0] - addr
    pp = struct.unpack_from(">I", out, recs + 0x44)[0] - addr
    assert struct.unpack_from(">3I", out, pp + 4) == (0x80900000, 0x80900080, 0x80900100)


def test_live_apply_writes_paused_verifies_and_hides(donor, monkeypatch):
    from gbox import twin_snakes_live as L
    monkeypatch.setattr(L, "MEM1", (BASE, BASE + 0x80000))
    monkeypatch.setattr(L, "CHUNK", 0x10000)
    sdat = _disc()
    new_sd, _rep = W.build_stage_dat(sdat, {"snake_def": donor})
    items = W.live_items(sdat, new_sd, ["snake_def"])
    kinds = sorted({i["kind"] for i in items})
    assert kinds == ["hide", "model", "texels"]
    ad = FakeDolphin(0x80000)
    old = model_bytes()
    ad.mem[0x2000:0x2000 + len(old)] = _load(old, BASE + 0x2000, 0x80900000)
    acc = accessory(0x26523A, 0x413AA8)
    ad.mem[0x30000:0x30000 + len(acc)] = _load(acc, BASE + 0x30000, 0x80900000)
    tset = body_set()
    ad.mem[0x40000:0x40000 + len(tset)] = tset
    res = L.apply(ad, items)
    assert res["verified"] and ad.state == "RUNNING" and ad.paused == 1
    got = {next(iter(k for k in d if k in ("model", "hide", "texels"))): d for d in res["written"]}
    assert got["model"]["address"] == hex(BASE + 0x2000) and got["hide"]["address"] == hex(BASE + 0x30000)
    m = K.parse(_unload(bytes(ad.mem[0x2000:0x2000 + len(old)]), BASE + 0x2000))
    assert K.stats(m)["triangles"] == K.stats(K.parse(S.StageDat.from_bytes(new_sd).stage("r_sna")
                                                     .find(0xF7A622, S.MODEL).data))["triangles"]
    ts = T.TextureSet(bytes(ad.mem[0x40000:0x40000 + len(tset)]))
    assert ts.rgba(ts.by_hash(LAYER[1]))[..., 1].mean() > 150
    g = struct.unpack_from(">I", ad.mem, 0x30000 + 0x5C)[0] - BASE
    recs = struct.unpack_from(">I", ad.mem, g + 0x10)[0] - BASE
    assert struct.unpack_from(">H", ad.mem, recs + 0x38)[0] == 0


def test_live_apply_rolls_back_when_a_write_fails(donor, monkeypatch):
    from gbox import twin_snakes_live as L
    monkeypatch.setattr(L, "MEM1", (BASE, BASE + 0x80000))
    monkeypatch.setattr(L, "CHUNK", 0x10000)
    sdat = _disc()
    new_sd, _rep = W.build_stage_dat(sdat, {"snake_def": donor})
    items = W.live_items(sdat, new_sd, ["snake_def"])
    ad = FakeDolphin(0x80000)
    old = model_bytes()
    ad.mem[0x2000:0x2000 + len(old)] = _load(old, BASE + 0x2000, 0x80900000)
    before = bytes(ad.mem)
    items.append({"kind": "model", "hash": "26e012", "data": base64.b64encode(b"x").decode(), "size": 4})
    with pytest.raises(ValueError, match="not loaded"):
        L.apply(ad, items)
    assert bytes(ad.mem) == before and ad.state == "RUNNING"


# ----------------------------------------------------------------------------------------------- owned disc (opt-in)

ISO = os.environ.get("TTS_ISO", "")


@pytest.mark.skipif(not (ISO and Path(ISO).is_file()), reason="set TTS_ISO to an owned Twin Snakes disc 1 image")
def test_owned_disc_reads_snake_and_the_soldiers(tmp_path):
    for key, tris in (("snake_def", 3028), ("out_cold", 2058), ("in_door", 1878), ("hev_grd", 2032)):
        r = TS.extract(Path(ISO), key, tmp_path / f"{key}.glb")
        assert r["triangles"] == tris and not r["missing_textures"] and len(r["roles"]) == 18


# ----------------------------------------------------------------------------------------------- REL (Ghidra input)

def test_rel_link_and_depair_for_ghidra():
    """A tiny REL: text (lis/addi of a data address, a bl into main.dol, a psq_l) and data (a pointer to text)."""
    from gbox import gcdisc
    text = struct.pack(">5I", 0x3C600000, 0x38630000, 0x48000001, 0xE0230010, 0x10000000)   # lis, addi, bl, psq_l, ps
    rel = bytearray(0x100)
    struct.pack_into(">IIIII", rel, 0, 7, 0, 0, 3, 0x40)
    struct.pack_into(">6I", rel, 0x40, 0, 0, 0x80 | 1, len(text), 0x98, 8)        # sections 0, 1 (text), 2 (data)
    rel[0x80:0x80 + len(text)] = text
    own = (struct.pack(">HBBI", 0, 202, 1, 0) +                   # section 1 (text)
           struct.pack(">HBBI", 2, 6, 2, 4) +                     # +2: ADDR16_HA  data + 4
           struct.pack(">HBBI", 4, 4, 2, 4) +                     # +6: ADDR16_LO  data + 4
           struct.pack(">HBBI", 0, 202, 2, 0) +                   # section 2 (data)
           struct.pack(">HBBI", 0, 1, 1, 8) +                     # data + 0: ADDR32 text + 8
           struct.pack(">HBBI", 0, 203, 0, 0))
    main = (struct.pack(">HBBI", 0, 202, 1, 0) + struct.pack(">HBBI", 8, 10, 0, 0x80003100) +    # bl 0x80003100
            struct.pack(">HBBI", 0, 203, 0, 0))
    rel[0xA0:0xA0 + len(own)] = own
    m0 = 0xA0 + len(own)
    rel[m0:m0 + len(main)] = main
    imp = m0 + len(main)
    rel = rel[:imp] + struct.pack(">IIII", 7, 0xA0, 0, m0)
    struct.pack_into(">III", rel, 0x24, 0xA0, imp, 16)
    img = gcdisc.rel_link(bytes(rel), 0x80300000)
    text_a, data_a = 0x80300080, 0x80300098
    hi, lo = struct.unpack_from(">H", img, 0x82)[0], struct.unpack_from(">H", img, 0x86)[0]
    assert ((hi << 16) + (lo - 0x10000 if lo & 0x8000 else lo)) & 0xFFFFFFFF == data_a + 4
    assert struct.unpack_from(">I", img, 0x98)[0] == text_a + 8
    off = struct.unpack_from(">I", img, 0x88)[0] & 0x3FFFFFC
    off = off - 0x4000000 if off & 0x2000000 else off
    assert (text_a + 8 + off) & 0xFFFFFFFF == 0x80003100
    dp = gcdisc.depair(img[0x80:0x80 + len(text)])
    assert struct.unpack_from(">I", dp, 12)[0] >> 26 == 48 and struct.unpack_from(">I", dp, 16)[0] == 0x60000000


# ----------------------------------------------------------------------------------------------- the whole cast

def test_identities_and_humanoid_filter():
    from gbox import twin_snakes_cast as TC
    assert TS.identity_of(model_bytes()) == "snake"                           # sna_def
    assert TS.identity_of(model_bytes(0x26E012, 0x26E012)) == "soldier_arctic"
    assert TS.identity_of(model_bytes(0x123456, 0x49E8C3)) is None            # a gun on the skeleton
    assert TC.humanoid(model_bytes()) and not TC.humanoid(accessory(0x26523A, 0x413AA8))
    P, N, UV, B, F = body_mesh()
    big = K.encode(template(nb=53, parts_on=set(range(21)) - {6, 10}), P, N, UV, B, F)
    assert TC.humanoid(big) and struct.unpack_from(">I", big, 4)[0] == 53
    assert set(TC.SONIC_CAST) >= set(TS.IDENTITIES) and set(TC.SONIC_CAST) >= set(TS.CODEC.values())
    rest = [k for k in TS.IDENTITIES]
    assert len({TC.SONIC_CAST[k] for k in rest}) == len(rest)                 # distinct donors on the 3D cast


def test_encode_draws_hands_on_the_forearm_and_drops_what_a_partial_model_lacks():
    P, N, UV, B, F = body_mesh()
    cut = K.parse(K.encode(template(nb=53, parts_on=set(range(21)) - {6, 10}), P, N, UV, B, F))
    js = {int(j) for p in K.decode(cut) for j in np.unique(p["J"][:, 0])}
    assert {6, 10} <= js                                                       # hands kept, drawn by the forearms
    assert {p["mesh"] for p in K.decode(cut)} == set(range(21)) - {6, 10}
    head = K.parse(K.encode(template(nb=53, parts_on={12}), P, N, UV, B, F))   # a close-up head model
    prims = K.decode(head)
    assert {p["mesh"] for p in prims} == {12}
    ys = np.concatenate([p["pos"][:, 1] for p in prims])
    assert ys.min() > 400                                                      # nothing below the neck


def test_full_cast_covers_gameplay_cut_scenes_and_partial_models(donor):
    from gbox import twin_snakes_cast as TC
    P, N, UV, B, F = body_mesh()
    cut = K.encode(template(0x413BB1, 0x413AA8, nb=53, parts_on=set(range(21)) - {6, 10}), P, N, UV, B, F)
    hv = [_box(np.add(BONES[12], (dx, dy, 0)), 12) for dx in (-30, 0, 30) for dy in (-30, 0, 30)]
    HP = np.concatenate([v for v, _f in hv])                                   # a close-up head: detailed, head only
    HF = np.concatenate([f + 8 * k for k, (_v, f) in enumerate(hv)])
    head = K.encode(template(0x29A6BB, 0x413AA8, nb=53, parts_on={12}), HP, HP - BONES[12],
                    (HP[:, :2] - HP[:, :2].min(0)) / np.ptp(HP[:, :2], 0), np.full(len(HP), 12), HF)
    gun = accessory(0x0143D9, 0x49E8C3, (0x999999, 0, 0))                    # an item with its own textures
    play = stage_blob([(S.MODEL, 0xF7A622, model_bytes()), (S.TEXTURES, 0x413AA8, body_set()),
                       (S.MODEL, 0x26523A, accessory(0x26523A, 0x413AA8))])
    demo = stage_blob([(S.MODEL, 0x413BB1, cut), (S.MODEL, 0x29A6BB, head), (S.MODEL, 0x0143D9, gun),
                       (S.TEXTURES, 0x413AA8, body_set())])
    orphan = stage_blob([(S.MODEL, 0x22D0F9, cut)])                           # its textures live elsewhere
    sdat = stage_dat([("r_sna", play), ("r_demo", demo), ("r_dmo0", orphan)])
    new, rep = TC.build_stage_dat(sdat, {"snake": donor})
    by = {r["stage"]: r for r in rep["stages"]}
    assert set(by["r_sna"]["replaced"]) == {"f7a622"} and by["r_sna"]["hidden"] == ["26523a"]
    assert set(by["r_demo"]["replaced"]) == {"413bb1", "29a6bb"}              # cut-scene body and close-up head
    assert by["r_dmo0"]["replaced"] == {} and "22d0f9" in by["r_dmo0"]["skipped"]
    assert rep["characters"]["snake"] == ["r_demo", "r_sna"]
    st = S.StageDat.from_bytes(new).stage("r_demo")
    assert st.find(0x0143D9, S.MODEL).data.rstrip(b"\0") == gun.rstrip(b"\0")  # the gun stays
    m = K.parse(st.find(0x29A6BB, S.MODEL).data)
    assert {p["mesh"] for p in K.decode(m)} == {12}


def test_face_dat_raw_pages_round_trip_and_codec_swap(donor):
    from gbox import twin_snakes_cast as TC
    rng = np.random.default_rng(3)
    portrait = np.zeros((178, 104, 4), np.uint8)
    g = rng.integers(40, 200, (178, 104))
    portrait[..., 0], portrait[..., 1], portrait[..., 2], portrait[..., 3] = g // 3, g, g // 2, 255
    patch = portrait[88:116, 10:60]
    face = texture_set([(0x111, {"fmt": 14, "w": 104, "h": 178, "data": T.encode(14, 104, 178, portrait)}),
                        (0x222, {"fmt": 14, "w": 104, "h": 178, "data": T.encode(14, 104, 178, portrait)}),
                        (0x333, {"fmt": 14, "w": 50, "h": 28, "data": T.encode(14, 50, 28, patch)})])
    st = S.Stage("f04a", 1, 0)
    st.pages.append(S.Page(0, face + bytes((-len(face)) % 0x20), [((S.TEXTURES << 24) | 0x045793, 0)], b"", True))
    blob = S.build_stage(st)
    assert struct.unpack_from(">II", blob, 4) == (0, len(st.pages[0].data))  # {0, size} opens a raw page
    back = S.parse_stage(blob, "f04a", 1, len(blob))
    assert back.pages[0].raw and S.build_stage(back) == blob
    hdr = struct.pack(">IIHHI", 0x40173944, 0x00010001, 1, 0xCCCC, 1) + struct.pack(">8sI", b"f04a", 1)
    fdat = hdr + bytes(0x800 - len(hdr)) + blob
    new, rep = TC.build_face_dat(fdat, {"meryl": (donor.glb, donor.roles)})
    assert len(new) == len(fdat) and rep["meryl"]["portraits"] == 2 and rep["meryl"]["patches"] == 1
    ts = T.TextureSet(S.StageDat.from_bytes(new).stage(0).files()[0].data)
    p0 = ts.rgba(ts.images[0]).astype(int)
    assert np.abs(p0 - portrait.astype(int)).mean() > 10                     # a new portrait
    assert np.abs(p0[..., 1].astype(int) - p0[..., 0]).mean() > 20             # still the codec green
    crop = p0[88:116, 10:60]
    assert np.abs(ts.rgba(ts.images[2]).astype(int) - crop).mean() < 12        # the patch is its crop
