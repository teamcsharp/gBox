"""RE4 Switch enemy writer on synthetic Ganado packs (no game data, no donor file)."""
import json
import struct

import numpy as np
import pytest

from gbox import re4_switch_assets as A
from gbox import re4_switch_enemies as E
from gbox import re4_switch_models as M
from tests.test_re4_switch_assets import gradient, make_bin, make_dat, make_pack, make_tpl, make_udas, material
from tests.test_re4_switch_models import SKELETON, donor_record

PACK_ID = 0x00000016
HEAD_EXTRAS = [(26, 1, (0, 0, 0)), (27, 4, (0, 4, 7)), (28, 4, (0, 70, 60)), (29, 4, (0, 20, 40)), (30, 27, (0, 0, 0)),
               (31, 4, (0, -10, 65)), (32, 4, (-31, 80, 62)), (33, 4, (31, 80, 62))]
GANADO = SKELETON + HEAD_EXTRAS                       # the player's tree on 0..25 plus the Ganado head bones
HEAD = [(0, 0xFF, (0, 1000, 0)), (1, 0, (0, 50, 0)), (2, 1, (0, 200, 0)), (3, 2, (0, 200, 0)), (4, 3, (0, 100, 0))]
RIGHT_HAND = [(9, 0xFF, (-500, 1400, 0)), (10, 9, (-100, 0, 0))]
LEFT_HAND = [(15, 0xFF, (500, 1400, 0)), (16, 15, (100, 0, 0))]
PARASITE = [(i, 0xFF if i == 0 else 0, (0.0, 20.0 * i, 0.0)) for i in range(26)]      # every bone hangs off the root


def piece(skeleton, bones, low, high, *, diffuse=0, texture_count=3, triangles=4, seed=0):
    """A model on `skeleton` skinned to `bones`, its vertices inside the box low..high (the corners pinned)."""
    rng = np.random.default_rng(seed)
    count = 3 * triangles
    low, high = np.asarray(low, float), np.asarray(high, float)
    positions = rng.uniform(low, high, (count, 3))
    positions[0], positions[1] = low, high
    sets = [((bone, 100),) for bone in bones]
    return A.HdBin.parse(make_bin(skeleton=skeleton)).with_geometry(
        positions=positions, normals=np.tile([0.0, 0.0, 1.0], (count, 1)), uvs=rng.uniform(0, 1, (count, 2)),
        weight_sets=sets, weight_index=np.arange(count) % len(sets),
        materials=[material([(A.PRIM_LIST, count)], diffuse=diffuse)], texture_count=texture_count).build()


def body(seed=0, diffuse=1, texture_count=3, triangles=180):
    return piece(GANADO, (2, 8, 13, 17, 19, 23), (-708, 1, -150), (708, 1604, 212), diffuse=diffuse,
                 texture_count=texture_count, triangles=triangles, seed=seed)


def ganado_pack(*, pack_id=PACK_ID, item=None):
    """A Ganado pack in miniature: two body groups (body, table, head), two hand poses, a gear piece and the parasite."""
    slots = [("EFF", b"\xcd" * 64),
             ("BIN", body(1)), ("TPL", make_tpl(3, pack_id).slot()),
             ("BIN", piece(HEAD, (3, 4), (-90, 1450, -100), (90, 1830, 100), diffuse=0)),
             ("BIN", body(2, texture_count=5)), ("TPL", make_tpl(5, pack_id, first=3).slot()),
             ("BIN", piece(HEAD, (2, 3, 4), (-93, 1500, -100), (93, 1837, 100), diffuse=0, texture_count=5)),
             ("BIN", piece(RIGHT_HAND, (10,), (-891, 1443, -40), (-707, 1534, 40), diffuse=2)),
             ("BIN", piece(LEFT_HAND, (16,), (707, 1443, -40), (891, 1534, 40), diffuse=2)),
             ("BIN", piece(GANADO, (2, 5, 11), (-300, 1200, -100), (300, 1600, 100), diffuse=2)),
             ("BIN", piece(PARASITE, (0, 5, 8, 18, 19), (-497, -42, -120), (500, 1312, 142), diffuse=0, texture_count=6)),
             ("", b""), ("FCV", bytes(32))]
    if item is not None:
        slots.append(("BIN", item))
    return make_udas(make_dat(slots))


def slots_of(udas):
    return A.pack_slots(udas)[1].slots


def test_measure_class_finds_bodies_tables_heads_hands_gear_and_leaves_the_parasite():
    layout = E.measure_class(ganado_pack(), "em16")
    assert layout.archive == "00000016.pack.fen"
    assert layout.bodies == {1: 2, 4: 5}
    assert layout.heads == (3, 6) and layout.hands == (7, 8) and layout.parts == (9,)
    assert layout.native == {"other_skeleton_10": 10}
    assert layout.group_heads == {1: (3,), 4: (6,)}
    assert layout.hidden() == (3, 6, 7, 8, 9)


def test_measure_class_refuses_a_body_without_a_table_and_a_pack_without_bodies():
    no_table = make_udas(make_dat([("BIN", body()), ("BIN", body(1))]))
    with pytest.raises(E.EnemyError, match="no texture table"):
        E.measure_class(no_table, "x")
    with pytest.raises(E.EnemyError, match="no Ganado body"):
        E.measure_class(make_udas(make_dat([("TPL", make_tpl().slot())] * 3)), "x")


def test_layout_matches_names_each_difference():
    layout = E.measure_class(ganado_pack(), "em16")
    known = {"archive": "00000016.pack.fen", "bodies": {1: 2, 4: 5}, "heads": (3, 6), "hands": (7, 8), "parts": (9,),
             "native": {"parasite": 10}}
    assert E.layout_matches(layout, known) == []
    wrong = known | {"bodies": {1: 2}, "hands": (), "native": {"parasite": 99}}
    report = E.layout_matches(layout, wrong)
    assert len(report) == 3 and report[0].startswith("bodies") and "native slot 99" in report[-1]


def test_body_image_avoids_an_image_a_native_model_samples():
    layout = E.measure_class(ganado_pack(), "em16")
    _pack, dat = A.pack_slots(ganado_pack())
    image, choice = E.body_image(dat, layout, 1)
    assert image == 1 and choice["free_of_native_models"]
    # a native item bound to a 3-image table that samples image 1: the body's other image is not available either
    # (the body draws only image 1), so image 1 is kept and the receipt says who shares it
    item = piece([(0, 0xFF, (0, 0, 0))], (0,), (-40, -50, -40), (40, 80, 40), diffuse=1)
    with_item = ganado_pack(item=item)
    layout2 = E.measure_class(with_item, "em16")
    _pack2, dat2 = A.pack_slots(with_item)
    image2, choice2 = E.body_image(dat2, layout2, 1)
    assert image2 == 1 and not choice2["free_of_native_models"] and choice2["shared_with_native_models"] == {"1": [13]}


def test_build_class_writes_a_donor_on_every_body_and_hides_the_shared_pieces():
    from PIL import Image
    import io

    udas, archive = ganado_pack(), make_pack(PACK_ID).build()
    donor, _names = donor_record()
    other = dict(donor) | {"name": "second.glb", "atlas": gradient(32, 32)}
    out, grown, receipt = E.build_class(udas, archive, [donor, other], pack="em16", known=None)
    before, after = slots_of(udas), slots_of(out)
    assert receipt["slots_replaced"] == [1, 2, 3, 4, 5, 6, 7, 8, 9] and receipt["other_slots_byte_identical"] == 4
    assert after[10] == before[10] and after[0] == before[0]                       # the parasite and the effects
    for slot, donor_used in ((1, donor), (4, other)):
        model = A.HdBin.parse(after[slot][1])
        assert model.vertex_count == 3 * len(donor_used["faces"]) and model.material_count == 1
        assert model.sections["bones"] == A.HdBin.parse(before[slot][1]).sections["bones"]
        used = {bone for entry in model.weights() for bone, _w in entry}
        assert used <= set(E.ENEMY_ROLE_BONES.values()) and 17 in used and 0 not in used
    tables = [A.Tpl.parse(after[2][1]).images, A.Tpl.parse(after[5][1]).images]
    assert (tables[0][1].pack_id, tables[0][1].index) == (PACK_ID, 2) and (tables[1][1].index) == 3
    assert [i.index for i in tables[0] if i is not tables[0][1]] == [0, 2]
    pack = A.ImagePack.parse(grown)
    assert len(pack.entries) == 4 and receipt["archive_entries"] == [2, 4]
    decoded = np.asarray(Image.open(io.BytesIO(pack.entries[3][1])).convert("RGBA"), np.int32)
    assert decoded.shape == (32, 32, 4) and np.abs(decoded - gradient(32, 32)).mean() < 6
    for slot in (3, 6, 7, 8, 9):
        small, full = A.HdBin.parse(after[slot][1]), A.HdBin.parse(before[slot][1])
        assert len(after[slot][1]) == len(before[slot][1])
        assert np.allclose(np.ptp(small.positions(), 0), np.ptp(full.positions(), 0) * 0.1, rtol=1e-3)
    assert receipt["live_verified"] is False and receipt["role_bones"]["hip"] == 17
    assert [g["body"] for g in receipt["groups"]] == [1, 4] and receipt["groups"][0]["skeleton_bytes_identical"]
    assert set(receipt["parts_shrunk"]) == {"3", "6", "7", "8", "9"}
    assert A.roundtrip("em16.udas", out)["identical"] and A.roundtrip("00000016.pack.fen", grown)["identical"]


def test_build_class_deals_one_donor_to_every_body_and_checks_the_pinned_layout():
    udas, archive = ganado_pack(), make_pack(PACK_ID).build()
    donor, _names = donor_record()
    out, _grown, receipt = E.build_class(udas, archive, [donor], pack="em16", known=None)
    assert [g["donor"]["name"] for g in receipt["groups"]] == ["stick.glb", "stick.glb"]
    with pytest.raises(E.EnemyError, match="2 bodies need 2 donors"):
        E.build_class(udas, archive, [donor, donor, donor], pack="em16", known=None)
    pinned = {"archive": "00000016.pack.fen", "bodies": {1: 2}, "heads": (3, 6), "hands": (7, 8), "parts": (9,),
              "native": {}}
    with pytest.raises(E.EnemyError, match="does not measure as the pinned layout"):
        E.build_class(udas, archive, [donor], pack="em16", known=pinned)
    E.build_class(udas, archive, [donor], pack="em16", known=pinned, trust_measurement=True)
    with pytest.raises(E.EnemyError, match="the tables name"):
        E.build_class(udas, make_pack(0x0000001C).build(), [donor], pack="em16", known=None)


def test_build_class_names_the_donor_a_body_refuses():
    udas, archive = ganado_pack(), make_pack(PACK_ID).build()
    donor, _names = donor_record()
    broken = dict(donor) | {"donor": {"slug": "flat_rig"}}
    broken["joints"] = dict(donor["joints"]) | {donor["role_nodes"]["chest"]: donor["joints"][donor["role_nodes"]["hip"]]}
    with pytest.raises(E.EnemyError, match="em16 body 1 <- flat_rig"):
        E.build_class(udas, archive, [broken], pack="em16", known=None)


def esl(entries):
    """32-byte rows as the GameCube lists: +1 em, +2 type, +8 hp, +0xC xyz/10, +0x18 room."""
    out = b""
    for em, kind, room in entries:
        row = bytearray(32)
        row[1], row[2] = em, kind
        struct.pack_into("<H", row, 8, 1000)
        struct.pack_into("<3h", row, 0xC, 120, 0, -340)
        struct.pack_into("<H", row, 0x18, room)
        out += bytes(row)
    return out + bytes(32)                                 # one unused row


def test_read_esl_and_roster(tmp_path):
    rows = E.read_esl(esl([(0x16, 3, 0x400), (0x16, 4, 0x400), (0x28, 0, 0x400), (0x1C, 7, 0x402)]))
    assert len(rows) == 4 and rows[0] == {"flags": 0, "em": "em16", "type": 3, "hp": 1000, "pos": (1200, 0, -3400),
                                          "room": 0x400}
    with pytest.raises(E.EnemyError):
        E.read_esl(b"\0" * 33)
    (tmp_path / "omake01.esl").write_bytes(esl([(0x16, 3, 0x400), (0x16, 4, 0x400), (0x28, 0, 0x400), (0x1C, 7, 0x402)]))
    (tmp_path / "omake02.esl").write_bytes(esl([(0x1D, 14, 0x403), (0x20, 15, 0x404), (0x20, 15, 0x404)]))
    report = E.roster(tmp_path)
    assert report["Village"] == {"room": "0400", "esl": "omake01.esl", "packs": {"em16": {3: 1, 4: 1}, "em28": {0: 1}},
                                 "spawns": 3}
    assert report["Waterworld"]["packs"] == {"em20": {15: 2}} and report["Castle"]["packs"] == {"em1c": {7: 1}}
    assert json.dumps(report)                                   # JSON-serialisable for a receipt


def test_known_table_is_consistent_and_names_the_mercenaries_packs():
    assert set(E.KNOWN) == {"em16", "em1c", "em1d", "em20"} and "em28" in E.NOT_WRITTEN
    for pack, known in E.KNOWN.items():
        assert known["archive"] == f"000000{pack[2:]}.pack.fen" and len(known["sha256"]) == 64
        assert all(table == body_slot + 1 for body_slot, table in known["bodies"].items())
        assert not set(known["bodies"]) & set(known["heads"]) & set(known["hands"])
    assert E.ENEMY_ROLE_BONES["hip"] == 17 and {k: v for k, v in E.ENEMY_ROLE_BONES.items() if k != "hip"} == \
        {k: v for k, v in M.ROLE_BONES.items() if k != "hip"}


def test_build_class_uploads_opaque_atlases_without_black_by_default():
    from PIL import Image
    import io

    from tests.test_re4_switch_models import cut_out_atlas

    udas, archive = ganado_pack(), make_pack(PACK_ID).build()
    donor, _names = donor_record()
    donor["atlas"] = cut_out_atlas(32)
    _out, grown, receipt = E.build_class(udas, archive, [donor], pack="em16", known=None)
    for entry in (2, 3):
        decoded = np.asarray(Image.open(io.BytesIO(A.ImagePack.parse(grown).entries[entry][1])).convert("RGBA"), np.int32)
        assert (decoded[..., 3] == 255).all() and decoded[..., :3].sum(2).min() > 0
    assert receipt["groups"][0]["atlas"]["finish"]["filled_share"] > 0.4
    _out, raw, plain = E.build_class(udas, archive, [donor], pack="em16", known=None, opaque_atlas=False)
    decoded = np.asarray(Image.open(io.BytesIO(A.ImagePack.parse(raw).entries[2][1])).convert("RGBA"), np.int32)
    assert decoded[..., 3].min() == 0 and plain["groups"][0]["atlas"]["finish"] is None


def test_enemy_pool_refuses_a_pinned_assignment_that_does_not_fit(tmp_path):
    (tmp_path / "em").mkdir()
    (tmp_path / "img").mkdir()
    (tmp_path / "em" / "emzz.udas").write_bytes(ganado_pack())
    (tmp_path / "img" / "00000016.pack.fen").write_bytes(make_pack(PACK_ID).build())
    with pytest.raises(E.EnemyError, match="pinned assignment does not fit"):
        E.enemy_pool(tmp_path / "em", tmp_path / "img", tmp_path, [], "seed", tmp_path / "out", classes=("emzz",),
                     assignment={"emzz:1": "nobody"})
