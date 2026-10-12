"""PS1 Metal Gear Solid KMD reader/writer contract (#848)."""

import struct
from dataclasses import replace
from pathlib import Path

import pytest

from gbox import mgs_kmd as K

HOME = Path.home()
DISC_KMD = HOME / ".hermes/cache/scratch/mgs848/dar/39213.kmd"          # extracted from the owned US disc
OLD_TARGET = HOME / "gbox-cache/characters/hucast/targets/mgs_vr_snake_hucast.kmd"


def two_bones(flag_child_weld=True):
    root = K.KmdObject(0x10001, (0, 0, 0), -1, 0xFFFFFFFF,
                       vertices=[(0, 0, 0, -1), (10, 0, 0, -1), (0, 10, 0, -1)],
                       normals=[(0, 0, 4096, 0)],
                       faces=[(0, 1, 1, 2)],
                       face_normals=[(0x80 if flag_child_weld else 0, 0, 0, 0)],
                       uvs=[bytes(8)], textures=[47255])
    child = K.KmdObject(0x10001, (0, 0, 0), 0, 0xFFFFFFFF,
                        vertices=[(0, 0, 0, 0), (0, -10, 0, -1), (5, -10, 0, -1)],
                        normals=[(0, 0, 4096, 0)],
                        faces=[(0, 1, 1, 2)], face_normals=[(0, 0, 0, 0)],
                        uvs=[bytes(8)], textures=[47255])
    for o in (root, child):
        o.bbox = o.computed_bbox()
    return K.Kmd(2, (0, -10, 0, 10, 10, 0), [root, child])


def test_round_trip_keeps_game_order_and_word_alignment():
    model = two_bones()
    data = K.dumps(model)
    again = K.loads(data)
    assert K.dumps(again) == data
    # one face -> 2-byte texture array -> 2 bytes of padding before the next object's vertices
    offsets = K.array_offsets(data)
    assert all(o % 4 == 0 for o in offsets)
    rec = K.RECORD.unpack_from(data, K.HEADER.size)
    voff, vord, noff = rec[14], rec[15], rec[17]
    assert voff < vord < noff                     # vertices, vertex order, normals
    assert K.problems(again, data) == []


def test_misaligned_arrays_and_missing_export_flags_are_rejected():
    model = two_bones(flag_child_weld=False)
    data = bytearray(K.dumps(model))
    assert any("weld-export" in p for p in K.problems(model))
    # move object 1's vertex array onto a 2-mod-4 offset, as the old HUcast KMD had
    base = K.HEADER.size + K.RECORD.size
    voff = struct.unpack_from("<I", data, base + 14 * 4)[0]
    struct.pack_into("<I", data, base + 14 * 4, voff - 2)
    assert any("word aligned" in p for p in K.problems(model, bytes(data)))


def test_skeleton_change_and_bad_weld_are_incompatible():
    original = two_bones()
    moved = K.loads(K.dumps(original))
    moved.objects[1] = replace(moved.objects[1], pos=(1, 2, 3))
    assert any("skeleton record" in p for p in K.check_compatible(original, moved))
    far = K.loads(K.dumps(original))
    far.objects[1].vertices[0] = (3, 3, 0, 5)       # weld to a vertex the parent doesn't have
    assert any("missing parent vertex" in p for p in K.check_compatible(original, far))


def test_normalize_repairs_welds_flags_and_records():
    original = two_bones()
    broken = K.loads(K.dumps(two_bones(flag_child_weld=False)))
    broken.objects[1] = replace(broken.objects[1], vertices=[(10, 0, 0, 9)] + broken.objects[1].vertices[1:],
                                pos=(0, 0, 0), flags=1)
    fixed, notes = K.normalize(original, broken)
    assert fixed.objects[1].vertices[0][3] == 1      # re-pointed at the parent vertex it sits on
    assert fixed.objects[1].flags == 0x10001
    data = K.dumps(fixed)
    assert K.check_compatible(original, K.loads(data), raw=data) == []
    assert notes


@pytest.mark.skipif(not DISC_KMD.is_file(), reason="owned VR Missions KMD not extracted on this host")
def test_real_snake_round_trips_and_old_hucast_target_is_refused():
    raw = DISC_KMD.read_bytes()
    snake = K.loads(raw)
    assert K.dumps(snake) == raw
    assert K.problems(snake, raw) == []
    if OLD_TARGET.is_file():
        old = OLD_TARGET.read_bytes()
        issues = K.check_compatible(snake, K.loads(old), raw=old)
        assert any("word aligned" in p for p in issues)
        assert any("weld-export" in p for p in issues)


@pytest.mark.skipif(not DISC_KMD.is_file(), reason="owned VR Missions KMD not extracted on this host")
def test_fit_kmd_retargets_library_model_inside_budget():
    import json
    from gbox import mgs_vr_swap as W, oot_swap
    lib = HOME / "gbox-cache/characters/hucast"
    if not (lib / "meta.json").is_file():
        pytest.skip("HUcast library entry absent")
    meta = json.loads((lib / "meta.json").read_text())
    raw = DISC_KMD.read_bytes()
    data, rep = W.fit_kmd(raw, lib / meta["model"], oot_swap.roles_of(meta, lib / meta["model"]))
    assert len(data) <= len(raw)
    snake, fitted = K.loads(raw), K.loads(data)
    assert K.check_compatible(snake, fitted, raw=data) == []
    assert rep["triangles"] > 200
    # each limb lands in its own Snake object's local frame (arms hang down like Snake's)
    for i in (2, 7, 10, 13):
        assert fitted.objects[i].bbox[1] < -200 and fitted.objects[i].bbox[4] < 200
