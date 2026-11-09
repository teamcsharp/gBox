import pytest
from gbox import mtf_retarget, mtf_author, mt_model
from tests.test_mtf_author import make_target


def test_role_frames_blend_complete_weights_and_merge_native_bones():
    vertices = [{"position": (0., 1., 0.), "normal": (0., 0., 1.), "source_joints": (3, 2),
                 "source_weights": (.25, .75)}]
    output, receipt = mtf_retarget.transfer(vertices, {1: (0., 0., 0.), 2: (0., 2., 0.)}, {3: 1},
        {0: (10., 0., 0.), 1: (14., 0., 0.)}, {"upper": (1, 0), "fore": (2, 1)}, {"upper": "fore"}, scale=2.)
    assert output[0]["position"] == pytest.approx((12., 0., 0.))
    assert output[0]["normal"] == pytest.approx((0., 0., 1.))
    assert output[0]["bones"] == [1, 0] and output[0]["weights"] == [.75, .25]
    assert receipt["discarded_influences"] == 0


def test_native_four_weights_include_short_first_weight_and_every_bone_envelope():
    import struct
    model = mt_model.parse_mod(make_target(1))
    vertices = [{"position": p, "normal": (0., 0., 1.), "uv": (0., 0.), "bounds": model.bounds(),
                 "bones": [0, 1], "weights": [.25, .75]} for p in ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))]
    built = mt_model.parse_mod(mtf_author.build_one_mesh(model, vertices, [(0, 1, 2)], four_weights=True))
    data, record = built.mesh_bytes(0)
    assert record["vertex_flags"] == 33 and record["vertex_stride"] == 28
    first_weight = struct.unpack_from("<h", data, 6)[0] / 32767
    assert first_weight == pytest.approx(.75, abs=1 / 32767)
    assert struct.unpack_from("<2e", data, 24) == (.25, 0.)
    assert first_weight + sum(struct.unpack_from("<2e", data, 24)) <= 1.
    assert list(data[16:20]) == [1, 0, 0, 0]
    assert [row["bone"] for row in built.weight_bounds()] == [0, 1]


def test_native_envelope_points_are_in_bone_local_coordinates():
    import struct
    raw = bytearray(make_target(1))
    start = mt_model.parse_mod(raw).header()["offsets"]["bones"]
    local = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 10., 114., -3., 1.)
    struct.pack_into("<16f", raw, start + 2 * 24, *local)
    model = mt_model.parse_mod(raw)
    assert mtf_author.bone_local_points(model, 0, [(12., 120., 5.)])[0] == pytest.approx((2., 6., 8.))


def test_rotated_child_envelope_uses_complete_composed_bind_matrix():
    import struct
    raw = bytearray(make_target(1))
    start = mt_model.parse_mod(raw).header()["offsets"]["bones"]
    raw[start + 1], raw[start + 25] = 255, 0
    parent = (0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 10., 20., 0., 1.)
    child = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 5., 0., 0., 1.)
    struct.pack_into("<32f", raw, start + 2 * 24, *parent, *child)
    model = mt_model.parse_mod(raw)
    assert mtf_author.bone_local_points(model, 1, [(7., 27., 4.)])[0] == pytest.approx((2., 3., 4.))


def test_weight_only_correspondence_preserves_surface_and_all_positive_influences():
    source = [{'position': (3., 4., 5.), 'normal': (0., 0., 1.), 'uv': (.1, .2),
               'source_joints': [3, 4, 2], 'source_weights': [.2, .3, .5]}]
    mapped, receipt = mtf_retarget.map_weights(source, {3: 1, 4: 1}, {'body': (1, 6), 'hand': (2, 7)})
    assert all(mapped[0][key] == source[0][key] for key in ('position', 'normal', 'uv'))
    assert mapped[0]['bones'] == [6, 7] and mapped[0]['weights'] == [.5, .5]
    assert receipt['discarded_influences'] == 0
    with pytest.raises(ValueError, match='no anatomical ancestor'):
        mtf_retarget.map_weights(source, {}, {'body': (1, 6)})


def test_bind_proportions_preserve_root_compression_and_recompute_inverse_matrices():
    import struct
    import numpy as np
    raw = bytearray(make_target(1))
    start = mt_model.parse_mod(raw).header()['offsets']['bones']
    raw[start + 1], raw[start + 25] = 255, 0
    parent = np.array([[0.,1.,0.,0.],[-1.,0.,0.,0.],[0.,0.,1.,0.],[10.,20.,0.,1.]])
    child = np.eye(4); child[3,:3] = (5.,0.,0.)
    compression = np.diag([100.,100.,100.,1.]); compression[3,:3] = (-10.,-20.,-30.)
    struct.pack_into('<32f', raw, start+2*24, *parent.ravel(), *child.ravel())
    struct.pack_into('<32f', raw, start+2*88, *(compression@np.linalg.inv(parent)).ravel(),
                     *(compression@np.linalg.inv(child@parent)).ravel())
    original = mt_model.parse_mod(raw)
    built, receipt = mtf_retarget.reposition_bind_pose(original, {1:(13.,28.,4.)})
    assert built.position_transform() == pytest.approx(original.position_transform())
    worlds = [np.asarray(m).reshape(4,4) for m in built.bone_world_matrices()]
    assert worlds[1][3,:3] == pytest.approx((13.,28.,4.))
    assert worlds[1][:3,:3] == pytest.approx((child@parent)[:3,:3])
    for i, inverse in enumerate(built.bone_table()['inverse_bind']):
        assert np.asarray(struct.unpack('<16f',inverse)).reshape(4,4)@worlds[i] == pytest.approx(compression,abs=1e-5)
    header = built.bone_table()['headers'][1]
    local = struct.unpack('<16f',built.bone_table()['local'][1])
    assert struct.unpack_from('<3f',header,12) == pytest.approx(local[12:15])
    assert receipt['root_unchanged'] and not receipt['animation_channels_changed']
    with pytest.raises(ValueError,match='root requires'):
        mtf_retarget.reposition_bind_pose(original,{0:(0.,0.,0.)})
