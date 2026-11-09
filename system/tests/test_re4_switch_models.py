"""RE4 Switch player-model writers on synthetic packs (no game data, no donor file)."""
import io
import json

import numpy as np
import pytest

from gbox import re4_switch_assets as A
from gbox import re4_switch_models as M
from tests.test_re4_switch_assets import gradient, make_bin, make_dat, make_pack, make_tpl, make_udas, material

# A round-number humanoid with the role ids the writer uses (0 hip .. 25 left toe); x < 0 is the right side.
SKELETON = [(0, 0xFF, (0, 1000, 0)), (1, 0, (0, 50, 0)), (2, 1, (0, 200, 0)), (3, 2, (0, 200, 0)), (4, 3, (0, 100, 0)),
            (5, 2, (-50, 100, 0)), (6, 5, (-100, 50, 0)), (7, 5, (-100, 50, 0)), (8, 7, (-250, 0, 0)),
            (9, 8, (-150, 0, 0)), (10, 9, (-100, 0, 0)),
            (11, 2, (50, 100, 0)), (12, 11, (100, 50, 0)), (13, 11, (100, 50, 0)), (14, 13, (250, 0, 0)),
            (15, 14, (150, 0, 0)), (16, 15, (100, 0, 0)),
            (17, 0, (0, 0, 0)), (18, 17, (-100, -100, 0)), (19, 18, (0, -400, 0)), (20, 19, (0, -400, 0)),
            (21, 20, (0, -80, 80)), (22, 17, (100, -100, 0)), (23, 22, (0, -400, 0)), (24, 23, (0, -400, 0)),
            (25, 24, (0, -80, 80))]
PACK_ID, OTHER_ID = 0x01000008, 0x01000006


def body_bin(seed=0, triangles=4, skeleton=SKELETON, diffuse=5):
    """A body on the synthetic skeleton: `triangles` list triangles, each vertex on one bone."""
    rng = np.random.default_rng(seed)
    count = 3 * triangles
    sets = [((bone, 100),) for bone in (0, 2, 4, 8, 19)]
    return A.HdBin.parse(make_bin(skeleton=skeleton)).with_geometry(
        positions=rng.uniform(-500, 1500, (count, 3)), normals=np.tile([0.0, 0.0, 1.0], (count, 1)),
        uvs=rng.uniform(0, 1, (count, 2)), weight_sets=sets, weight_index=rng.integers(0, len(sets), count),
        materials=[material([(A.PRIM_LIST, count)], diffuse=diffuse)], texture_count=6).build()


def player_pack(*, pack_id=PACK_ID, seed=0, triangles=4, images=6, skeleton=SKELETON, diffuse=5):
    """The measured slot layout in miniature: body, tables, head pieces, far head, eight hands, effects, a motion."""
    part = make_bin(skeleton=[(2, 0xFF, (0, 1250, 0)), (3, 2, (0, 200, 0)), (4, 3, (0, 100, 0))])
    face = make_bin(morph=True, skeleton=[(4, 0xFF, (0, 1550, 0))])
    hand = make_bin(skeleton=[(9, 0xFF, (-500, 1400, 0)), (10, 9, (-100, 0, 0))])
    slots = [("BIN", body_bin(seed, triangles, skeleton, diffuse)), ("TPL", make_tpl(images, pack_id).slot()),
             ("BIN", part), ("TPL", make_tpl(2, pack_id, first=images).slot()), ("BIN", face), ("BIN", part),
             ("BIN", part), ("BIN", part), ("BIN", make_bin(skeleton=[(0, 0xFF, (0, 0, 0))])), ("BIN", part),
             ("", b""), ("TPL", make_tpl(1, pack_id).slot()), ("BIN", part), ("TPL", make_tpl(1, pack_id).slot())]
    slots += [("BIN", hand)] * 8 + [("EFF", b"\xcd" * 64), ("FCV", bytes(32)), ("FCV", b"\x28\x00\x18\x01" * 16)]
    return make_udas(make_dat(slots))


def slots_of(udas):
    return A.pack_slots(udas)[1].slots


def corners(model):
    """The triangles as coordinates, so two encodings of one surface compare equal."""
    points = model.positions()
    return sorted(tuple(np.round(points[face], 3).ravel().tolist())
                  for faces in A.triangles(model.materials()) for face in faces)


def donor_record():
    """A stick figure in an arms-down pose: one vertex on each role joint and a few that pin the fit down."""
    place = {"hip": (0, 5, 0), "chest": (0, 6, 0), "head": (0, 7, 0),
             "l_upper": (1, 6.5, 0), "l_fore": (1.5, 5.5, 0), "l_hand": (2, 4.5, 0),
             "r_upper": (-1, 6.5, 0), "r_fore": (-1.5, 5.5, 0), "r_hand": (-2, 4.5, 0),
             "l_thigh": (0.4, 4.5, 0), "l_shin": (0.5, 3, 0), "l_foot": (0.6, 1.5, 0),
             "r_thigh": (-0.4, 4.5, 0), "r_shin": (-0.5, 3, 0), "r_foot": (-0.6, 1.5, 0)}
    role_nodes = {role: 10 + i for i, role in enumerate(M.ROLE_BONES)}
    joints = {role_nodes[role]: np.asarray(point, float) for role, point in place.items()}
    joints |= {1: np.zeros(3), 60: np.array([2.2, 4.2, 0.0])}               # a scene root and a finger
    parents = {role_nodes["hip"]: 1, 60: role_nodes["l_hand"]}
    for child, parent in (("chest", "hip"), ("head", "chest"), ("l_upper", "chest"), ("l_fore", "l_upper"),
                          ("l_hand", "l_fore"), ("r_upper", "chest"), ("r_fore", "r_upper"), ("r_hand", "r_fore"),
                          ("l_thigh", "hip"), ("l_shin", "l_thigh"), ("l_foot", "l_shin"),
                          ("r_thigh", "hip"), ("r_shin", "r_thigh"), ("r_foot", "r_shin")):
        parents[role_nodes[child]] = role_nodes[parent]

    def vertex(point, *influences):
        return {"position": tuple(map(float, point)), "normal": (0.0, 0.0, 1.0), "uv": (0.25, 0.75),
                "source_joints": tuple(j for j, _w in influences), "source_weights": tuple(w for _j, w in influences)}

    vertices = [vertex(place[role], (role_nodes[role], 1.0)) for role in M.ROLE_BONES]
    extra = {"mid_arm": vertex((1.25, 6.0, 0), (role_nodes["l_upper"], 1.0)),
             "sole": vertex((0.6, 0.0, 0.5), (role_nodes["l_foot"], 1.0)),
             "finger": vertex((2.2, 4.2, 0), (60, 1.0)),
             "root": vertex((0, 5, 0.2), (1, 1.0)),
             "blend": vertex((0, 5.5, 0), (role_nodes["hip"], 0.5), (role_nodes["chest"], 0.5)),
             "other_sole": vertex((-0.6, 0.0, 0.5), (role_nodes["r_foot"], 1.0))}
    names = list(M.ROLE_BONES) + list(extra)
    vertices += list(extra.values())
    faces = [(i, (i + 1) % len(vertices), (i + 2) % len(vertices)) for i in range(0, len(vertices), 3)]
    return {"name": "stick.glb", "vertices": vertices, "faces": faces, "atlas": gradient(64, 64), "joints": joints,
            "parents": parents, "role_nodes": role_nodes, "report": {"materials": 1}}, names


# --------------------------------------------------------------------------------------------------- native swap

def test_native_body_swap_replaces_the_body_and_its_table_only():
    target = player_pack(seed=1)
    donor = player_pack(pack_id=OTHER_ID, seed=2, triangles=9, images=2, diffuse=1)
    out, receipt = M.native_body_swap(target, donor)
    before, after, given = slots_of(target), slots_of(out), slots_of(donor)
    assert after[M.BODY][1] == given[M.BODY][1] and len(after) == len(before)
    assert [i for i, (x, y) in enumerate(zip(before, after)) if x != y] == [M.BODY, M.BODY_TPL]
    table = A.Tpl.parse(after[M.BODY_TPL][1]).images
    assert len(table) == 6 and {image.archive() for image in table} == {"01000006.pack.fen"}
    assert [image.index for image in table] == [0, 1, 0, 0, 0, 0]              # the donor's two, then its first again
    pack, grown = A.Udas.parse(out), A.Udas.parse(target)
    assert (pack.slack, pack.rest, pack.lead) == (grown.slack, grown.rest, grown.lead)
    assert pack.entries[1][2] - grown.entries[1][2] == len(out) - len(target) != 0
    assert receipt["slots_replaced"] == [0, 1] and receipt["other_slots_byte_identical"] == len(before) - 2
    assert receipt["skeleton"]["identical"] and receipt["body"]["donor_bin_bytes_kept"] and receipt["live_verified"] is False


def test_a_larger_donor_table_is_kept_whole():
    donor = player_pack(pack_id=OTHER_ID, images=8)
    out, receipt = M.native_body_swap(player_pack(), donor)
    assert len(A.Tpl.parse(slots_of(out)[M.BODY_TPL][1]).images) == 8 and receipt["texture_table"]["donor_images"] == 8


def test_rewritten_body_draws_the_same_triangles_with_other_bytes():
    target = player_pack(seed=1)
    stock = A.HdBin.parse(make_bin(skeleton=SKELETON))                          # a list, a strip and a quad
    slots = list(slots_of(player_pack(pack_id=OTHER_ID)))
    slots[M.BODY] = ("BIN", stock.build())
    donor = make_udas(make_dat(slots))
    out, receipt = M.native_body_swap(target, donor, rewrite=True)
    written = A.HdBin.parse(slots_of(out)[M.BODY][1])
    assert written.build() != stock.build() and corners(written) == corners(stock)
    assert {kind for m in written.materials() for kind, _n in m.prims} == {A.PRIM_LIST}
    assert written.vertex_count == 18 and stock.vertex_count == 14 and receipt["body"]["triangles"] == 6
    assert written.weights() == stock.weights() and [m.header for m in written.materials()] == [m.header for m in stock.materials()]
    assert written.sections["bones"] == stock.sections["bones"] and not receipt["body"]["donor_bin_bytes_kept"]


def test_skeleton_report_names_where_a_donor_stops_matching():
    target = A.HdBin.parse(body_bin())
    moved = list(SKELETON)
    moved[8] = (8, 7, (-262, 0, 0))                                             # a 12-unit shorter upper arm
    moved[20] = (20, 0, (0, -900, 0))                                           # and an ankle on another parent
    report = M.skeleton_report(target, A.HdBin.parse(body_bin(skeleton=moved)))
    assert report["first_id_with_another_parent"] == 20 and report["largest_bind_shift_before_it"] == 12.0
    assert not report["identical"] and report["ids_that_differ_after_it"] == 1
    assert M.skeleton_report(target, target)["identical"]


def test_a_pack_without_the_player_layout_is_refused():
    with pytest.raises(M.ModelError, match="not a playable player pack"):
        M.native_body_swap(make_udas(make_dat([("TPL", make_tpl().slot())] * 22)), player_pack())
    with pytest.raises(M.ModelError, match="not a playable player pack"):
        M.native_body_swap(player_pack(), make_udas(make_dat([("BIN", make_bin())])))
    part = [(2, 0xFF, (0, 0, 0)), (3, 2, (0, 1, 0))]
    with pytest.raises(M.ModelError, match="ids 0..n-1"):
        M.native_body_swap(player_pack(), player_pack(skeleton=part))


def test_shrink_part_moves_positions_and_nothing_else():
    payload = make_bin(morph=True)
    model = A.HdBin.parse(payload)
    out = A.HdBin.parse(M.shrink_part(payload, 0.1))
    assert len(out.build()) == len(payload) and out.sections["morph"] == model.sections["morph"]
    assert np.allclose(np.ptp(out.positions(), 0), np.ptp(model.positions(), 0) * 0.1, rtol=1e-4)
    assert np.allclose(out.positions().mean(0), model.positions().mean(0), atol=1e-3)
    aimed = A.HdBin.parse(M.shrink_part(payload, 0.5, centre=(0, 100, 0)))
    assert np.allclose(aimed.positions(), np.array([0, 100, 0]) + (model.positions() - [0, 100, 0]) * 0.5, atol=1e-4)
    assert all(out.sections[name] == model.sections[name] for name in model.sections if name != "positions")


# ----------------------------------------------------------------------------------------------------- donor fit

def test_fit_lands_each_donor_joint_on_its_native_bone():
    donor, names = donor_record()
    bones = A.HdBin.parse(body_bin()).bone_world()
    positions, normals, influences, report = M.fit(donor["vertices"], donor["joints"], donor["parents"],
                                                   donor["role_nodes"], bones)
    at = dict(zip(names, positions))
    for role, bone in M.ROLE_BONES.items():
        if role.endswith("foot"):
            continue
        assert np.allclose(at[role], bones[bone], atol=1e-6), role
    assert np.allclose(at["mid_arm"], (bones[13] + bones[14]) / 2, atol=1e-6)      # halfway stays halfway
    assert abs(at["sole"][1]) < 1e-6 and abs(at["other_sole"][1]) < 1e-6           # soles on the native floor
    assert np.allclose(at["sole"], [bones[24][0], 0.0, bones[24][2] + 0.5 * M.SCALES["end"]], atol=1e-6)
    assert np.allclose(at["l_foot"][1], 1.5 * M.SCALES["end"]) and report["foot_anchor_height"]["l_foot"] == 150.0
    assert np.allclose(np.linalg.norm(normals, axis=1), 1.0)
    bound = dict(zip(names, influences))
    assert bound["finger"] == [(16, 1.0)] and bound["root"] == [(0, 1.0)] and bound["blend"] == [(0, 0.5), (2, 0.5)]
    assert {bone for entry in influences for bone, _w in entry} <= set(M.ROLE_BONES.values())
    # a vertex shared by two roles is the weighted mean of where each role alone would put it:
    # hip: 1000 + 0.5 * 250 (hip->chest is 250 native, 1 donor), chest: 1250 - 0.5 * 300 (chest->head is 300 native)
    assert np.allclose(at["blend"], [0.0, 0.5 * 1125 + 0.5 * 1100, 0.0], atol=1e-6)


def test_fit_turns_a_hand_with_its_forearm_but_keeps_head_and_feet_level():
    donor, names = donor_record()
    extra = [{"position": (2.0, 4.0, 0.0), "normal": (0, 0, 1.0), "uv": (0, 0),            # below the left wrist
              "source_joints": (donor["role_nodes"]["l_hand"],), "source_weights": (1.0,)},
             {"position": (0.0, 8.0, 0.0), "normal": (0, 0, 1.0), "uv": (0, 0),            # above the head joint
              "source_joints": (donor["role_nodes"]["head"],), "source_weights": (1.0,)}]
    bones = A.HdBin.parse(body_bin()).bone_world()
    positions, _n, _i, _r = M.fit(donor["vertices"] + extra, donor["joints"], donor["parents"], donor["role_nodes"], bones)
    hand, head = positions[-2] - bones[16], positions[-1] - bones[4]
    assert hand[0] > 0.8 * np.linalg.norm(hand) and abs(np.linalg.norm(hand) - 0.5 * M.SCALES["end"]) < 1e-6
    assert np.allclose(head, [0.0, M.SCALES["head"], 0.0], atol=1e-6)


# -------------------------------------------------------------------------------------------------- donor writer

def test_author_body_writes_the_donor_on_the_native_skeleton():
    from PIL import Image

    target, archive = player_pack(seed=3), make_pack(PACK_ID).build()
    donor, _names = donor_record()
    files, receipt = M.author_body(target, archive, donor)
    assert set(files) == {"bio4/em/{pack}.udas", "bio4/imagepackhd/01000008.pack.fen"}
    before, after = slots_of(target), slots_of(files["bio4/em/{pack}.udas"])
    body, stock = A.HdBin.parse(after[M.BODY][1]), A.HdBin.parse(before[M.BODY][1])
    assert body.vertex_count == 3 * len(donor["faces"]) and body.material_count == 1 and body.bone_count == 26
    assert body.sections["bones"] == stock.sections["bones"]
    assert all(body.header[a:b] == stock.header[a:b] for a, b in ((0, 0x10), (0x38, 0x3C), (0x5C, 0x60), (0x88, 0x98)))
    assert body.materials()[0].textures() == [5] and body.positions()[:, 1].min() == 0.0
    assert {bone for entry in body.weights() for bone, _w in entry} <= set(M.ROLE_BONES.values())
    table = A.Tpl.parse(after[M.BODY_TPL][1]).images
    assert len(table) == 6 and (table[5].pack_id, table[5].index, table[5].width, table[5].height) == (PACK_ID, 2, 16, 16)
    assert [(i.pack_id, i.index) for i in table[:5]] == [(PACK_ID, k) for k in range(5)]
    pack = A.ImagePack.parse(files["bio4/imagepackhd/01000008.pack.fen"])
    assert len(pack.entries) == 3 and pack.textures()[2]["fourcc"] == "DXT5"
    assert [e[:2] for e in pack.entries[:2]] == [e[:2] for e in A.ImagePack.parse(archive).entries]
    decoded = np.asarray(Image.open(io.BytesIO(pack.entries[2][1])).convert("RGBA"), np.int32)
    assert decoded.shape == (64, 64, 4) and np.abs(decoded - gradient(64, 64)).mean() < 6
    shrunk = (M.HEAD, M.FACE, M.HAIR, M.FAR_HEAD) + M.HANDS
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    assert changed == sorted({M.BODY, M.BODY_TPL, *shrunk}) == receipt["slots_replaced"]
    for slot in shrunk:
        small, full = A.HdBin.parse(after[slot][1]), A.HdBin.parse(before[slot][1])
        assert len(after[slot][1]) == len(before[slot][1])
        assert np.allclose(np.ptp(small.positions(), 0), np.ptp(full.positions(), 0) * 0.1, rtol=1e-3)
    assert "morph" in A.HdBin.parse(after[M.FACE][1]).sections
    assert receipt["live_verified"] is False and receipt["body"]["skeleton_bytes_identical"]
    assert receipt["texture"] == {"archive": "01000008.pack.fen", "entry": 2, "table_image": 5, "width": 64,
                                  "height": 64, "format": "DXT5", "entries": 3}
    assert A.roundtrip("pl08.udas", files["bio4/em/{pack}.udas"])["identical"]


def test_author_body_refuses_a_wrong_archive_image_or_skeleton():
    donor, _names = donor_record()
    target = player_pack()
    with pytest.raises(M.ModelError, match="is not one of them"):
        M.author_body(target, make_pack(PACK_ID).build(), donor, image=9)
    with pytest.raises(M.ModelError, match="not the one the body's texture table names"):
        M.author_body(target, make_pack(OTHER_ID).build(), donor)
    short = player_pack(skeleton=SKELETON[:20])
    with pytest.raises(M.ModelError, match="no bone for"):
        M.author_body(short, make_pack(PACK_ID).build(), donor)


def test_overlay_is_written_once_with_a_receipt(tmp_path):
    target = player_pack(seed=1)
    out, receipt = M.native_body_swap(target, player_pack(pack_id=OTHER_ID, seed=2))
    name = "bio4/em/pl08.udas"
    written = M.write_overlay(tmp_path / "swap", {name: out}, receipt, {name: target})
    assert (tmp_path / "swap" / "romfs" / name).read_bytes() == out
    saved = json.loads((tmp_path / "swap" / "receipt.json").read_text(encoding="utf-8"))
    assert saved == written and saved["live_verified"] is False and saved["title_id"] == "010099A00BC1E000"
    assert saved["files"] == [{"path": "romfs/" + name, "bytes": len(out), "sha256": M.sha256(out),
                               "source_bytes": len(target), "source_sha256": M.sha256(target)}]
    with pytest.raises(M.ModelError, match="never overwritten"):
        M.write_overlay(tmp_path / "swap", {name: out}, receipt, {name: target})


def test_command_line_native_swap(tmp_path, capsys):
    folder = tmp_path / "em"
    folder.mkdir()
    (folder / "pl08.udas").write_bytes(player_pack(seed=1))
    (folder / "pl06.udas").write_bytes(player_pack(pack_id=OTHER_ID, seed=2, triangles=7))
    assert M.main(["native-swap", "--em", str(folder), "--target", "pl08", "--donor", "pl06", "--rewrite",
                   "--out", str(tmp_path / "out")]) == 0
    receipt = json.loads((tmp_path / "out" / "receipt.json").read_text(encoding="utf-8"))
    assert (receipt["target_pack"], receipt["donor_pack"]) == ("pl08", "pl06") and "rewritten" in receipt["operation"]
    assert json.loads(capsys.readouterr().out)["files"][0]["path"] == "romfs/bio4/em/pl08.udas"


def test_cast_names_five_packs_and_says_which_is_inferred():
    assert {name: entry["pack"] for name, entry in M.CAST.items()} == {
        "leon": "pl08", "hunk": "pl06", "krauser": "pl0a", "wesker": "pl0d", "ada": "pl0b"}
    assert M.CAST["ada"]["evidence"].startswith("inferred")
