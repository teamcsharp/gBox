"""VR Missions textures (#848, #1117): native PCC codec, PSX DAR repack, and repainting Snake's texture slots so a
fitted collection character wears its own textures.  Owned-disc tests (skipped elsewhere) use the US disc image."""
import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import mgs_kmd as K, mgs_pcc as C, mgs_vr_swap as W, mgs_vr_tex as X, mgs_vr_tool as T


def header(w, h, vram=(960, 80), clut=(784, 226), planes=4):
    hdr = bytearray(0x80)
    hdr[0:4] = bytes([0x0A, 5, 1, 1])
    struct.pack_into("<4H", hdr, 4, 0, 0, w - 1, h - 1)
    struct.pack_into("<2H", hdr, 12, 1600, 1200)
    hdr[0x41] = planes
    struct.pack_into("<H", hdr, 0x42, ((w + 7) // 8 + 1) & ~1)
    struct.pack_into("<H", hdr, 0x44, 1)
    struct.pack_into("<7H", hdr, 0x4A, C.MAGIC, 8, *vram, *clut, 16)
    return bytes(hdr)


def pcc(w, h, seed=0, **kw):
    rng = np.random.default_rng(seed)
    pal = np.clip(rng.integers(8, 255, (16, 3)), 8, 255).astype(np.uint8)
    idx = rng.integers(0, 16, (h, w)).astype(np.uint8)
    return C.dumps(C.Pcc(w, h, pal, idx, header=header(w, h, **kw)))


# ---------------------------------------------------------------------------------------------- codec
def test_pcc_round_trip_keeps_size_place_palette_and_pixels():
    data = pcc(20, 23)
    t = C.loads(data)
    assert (t.width, t.height, t.vram, t.clut) == (20, 23, (960, 80), (784, 226))
    again = C.loads(C.dumps(t))
    assert np.array_equal(again.index, t.index) and np.array_equal(again.palette, t.palette)


def test_rle_escapes_high_bytes_and_long_runs():
    assert C._rle(bytes([0xC5])) == bytes([0xC1, 0xC5])
    assert C._rle(bytes(100)) == bytes([0xFF, 0, 0xC0 | 37, 0])
    assert C._unrle(b"\0" * 0x80 + bytes([0xC3, 7, 9]), 4) == bytes([7, 7, 7, 9])


def test_quantize_keeps_opaque_texels_off_ps1_transparent_black():
    img = np.zeros((4, 4, 4), np.uint8)
    img[..., 3] = 255
    img[0, 0] = (255, 0, 0, 255)
    pal, idx = C.quantize(img, 16)
    assert (pal[idx] >= 8).all()                       # 15-bit 0x0000 would be see-through on the PS1
    img[1, 1, 3] = 0                                    # a transparent texel gets the black (clear) entry
    pal, idx = C.quantize(img, 16)
    assert (pal[idx[1, 1]] == 0).all() and (pal[idx[0, 0]] >= 8).all()


def test_dar_pack_round_trips_and_pads_to_its_allocation():
    ents = [(1025, ord("p"), b"abc"), (1077, ord("p"), b"defgh")]
    data = X.pack_dar(ents)
    assert X.parse_dar(data) == ents and len(data) == 8 + 4 + 8 + 8
    padded = X.pack_dar(ents, 64)
    assert len(padded) == 64 and X.parse_dar(padded)[0] == ents[0]
    with pytest.raises(ValueError):
        X.pack_dar(ents, 16)


# ---------------------------------------------------------------------------------------------- painting
def snake_like():
    """Four Snake slots in two CLUT groups, plus one foreign texture sharing the first CLUT."""
    archive = {1: pcc(48, 48, 1), 2: pcc(44, 36, 2, vram=(896, 160)), 3: pcc(24, 33, 3, clut=(768, 226)),
               4: pcc(12, 12, 4, clut=(768, 226)), 99: pcc(32, 20, 5, vram=(924, 0))}
    snake = {h: C.loads(archive[h]) for h in (1, 2, 3, 4)}
    return snake, archive


def test_paint_puts_each_image_in_a_slot_and_rewrites_uvs():
    snake, archive = snake_like()
    red = np.zeros((64, 64, 4), np.uint8); red[..., 0] = 200; red[..., 3] = 255
    blue = np.zeros((64, 64, 4), np.uint8); blue[..., 2] = 200; blue[..., 3] = 255
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]])
    faces = [("r", red, uv, (255, 255, 255))] * 5 + [("b", blue, uv + 2.0, (255, 255, 255))] * 2 + \
            [(None, None, uv, (10, 200, 10))]
    new, per_face, rep = X.paint(snake, archive, faces)
    assert rep["images"] >= 3 and rep["flat_colours"] == 1
    tex = [t for t, _ in per_face]
    assert len(set(tex[:5])) >= 1 and set(tex) <= set(snake)
    assert per_face[5][1] == per_face[0][1] or per_face[5][1][:2] == bytes([0, 0])   # wrapped UVs back into 0..1
    # every CLUT group shares one palette, the foreign member keeps its look against it
    for h in (1, 2, 99):
        assert np.array_equal(C.loads(new[h]).palette, C.loads(new[1]).palette)
    assert np.array_equal(C.loads(new[3]).palette, C.loads(new[4]).palette)
    budget = sum(len(b) + (-len(b) % 4) for b in archive.values())
    assert sum(len(b) + (-len(b) % 4) for b in new.values()) <= budget
    reds = C.loads(new[tex[0]]).rgba()[..., :3].reshape(-1, 3).mean(0)
    assert reds[0] > 150 and reds[2] < 60                         # the busiest slot shows the red image


def test_paint_splits_a_lone_atlas_over_more_slots():
    snake, archive = snake_like()
    atlas = np.zeros((128, 128, 4), np.uint8); atlas[..., 3] = 255
    atlas[:64, :64, 0] = 220; atlas[64:, 64:, 2] = 220
    faces = [("a", atlas, np.array([[0.1, 0.1], [0.2, 0.1], [0.1, 0.2]]), (255,) * 3),
             ("a", atlas, np.array([[0.8, 0.8], [0.9, 0.8], [0.8, 0.9]]), (255,) * 3)]
    _, per_face, rep = X.paint(snake, archive, faces)
    assert rep["images"] >= 2 and per_face[0][0] != per_face[1][0]
    assert max(per_face[0][1]) > 0.2 * 255                        # quadrant UVs are rescaled to the tile


# ---------------------------------------------------------------------------------------------- owned disc
BIN = Path(os.environ.get("GBOX_MGS_VR_BIN", r"D:\gBox\cache\modbase\mgs_vr_us\Metal Gear Solid - VR Missions (USA).bin"))
LIB = Path(os.environ.get("GBOX_CHARACTERS", Path.home() / "gBox_alt/gbox-cache/characters"))


@pytest.fixture(scope="module")
def init_dars():
    if not BIN.is_file():
        pytest.skip("owned VR Missions disc image not on this machine")
    from gbox import psxdisc
    d = psxdisc.RawBin(BIN, writable=False)
    try:
        sd = d.read("MGS/STAGE.DIR")
    finally:
        d.close()
    off = T.stage_dir(sd)["init"]
    return T.stg_entry(sd, off, 0)[1], T.stg_entry(sd, off, 1)[1]


def test_disc_textures_decode_and_the_archive_repacks_byte_identically(init_dars):
    models, textures = init_dars
    ents = X.parse_dar(textures)
    assert len(textures) == 141656 and len(ents) == 127
    assert X.pack_dar(ents, len(textures)) == textures
    for h, _e, body in ents:
        t = C.loads(body)
        assert np.array_equal(C.loads(C.dumps(t)).index, t.index), h
    snake = K.loads(dict((h, b) for h, _e, b in X.parse_dar(models))[39213])
    names = {t for o in snake.objects for t in o.textures}
    archive = {h: b for h, _e, b in ents}
    assert len(names) == 28 and {C.loads(archive[h]).clut for h in names} == {(784, 226), (768, 226)}
    assert C.loads(archive[47255]).vram == (960, 80)                # sna_chest4 (MetalMintSolid: 960x80, CLUT 784x226)


@pytest.mark.parametrize("slug", ["hucast", "aya_tshirt_jeans"])
def test_collection_character_is_fitted_with_its_own_textures(init_dars, slug):
    from gbox import oot_swap
    lib = LIB / slug
    if not (lib / "meta.json").is_file():
        pytest.skip(f"{slug} not in the local character library")
    meta = json.loads((lib / "meta.json").read_text())
    glb = lib / meta["model"]
    models, textures = init_dars
    own = dict((h, b) for h, _e, b in X.parse_dar(models))[39213]
    archive = {h: b for h, _e, b in X.parse_dar(textures)}
    names = {t for o in K.loads(own).objects for t in o.textures}
    data, rep, painted = W.fit_kmd_textured(own, glb, oot_swap.roles_of(meta, glb),
                                            {"snake": {h: C.loads(archive[h]) for h in names}, "archive": archive})
    model = K.loads(data)
    assert len(data) <= len(own) and K.check_compatible(K.loads(own), model, raw=data) == []
    used = {t for o in model.objects for t in o.textures}
    assert used <= names and len(used) >= 2                         # faces spread over Snake's slots, not one waist
    assert X.pack_dar([(h, e, painted.get(h, b)) for h, e, b in X.parse_dar(textures)], len(textures))
    assert rep["textures"]["images"] >= 2 and set(painted) >= used


def test_slots_name_the_player_and_the_soldier():
    assert W.SLOTS["player"]["model"] == 39213 == _strcode("snake")
    assert W.SLOTS["enemy:soldier"]["models"] == [38582, 55267] and W.SLOTS["enemy:soldier"]["writer"]
    assert W.SLOTS["enemy:soldier"]["motion"] == _strcode("enemy")


def _strcode(s):
    h = 0
    for c in s.encode():
        h = (((h << 5) | (h >> 11)) + c) & 0xFFFF
    return h
