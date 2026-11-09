"""Per-role scales, per-role offsets and the orphan role of the native-segment transfer, and the motion sampler's
animation-id lookup for a skeleton with a ground bone (the uEm11 em1100 shape). Synthetic data only."""
import struct

import pytest

from gbox import mt_model, mtf_motion, mtf_retarget, re5_mesh_import
from tests.test_mtf_motion import model_bytes

SOURCE = {1: (0., 0., 0.), 2: (0., 2., 0.), 3: (0., 3., 0.)}            # hip, chest, head joints
TARGET = {0: (0., 100., 0.), 1: (0., 130., 0.), 2: (0., 160., 0.)}
ROLES = {'hip': (1, 0), 'chest': (2, 1), 'head': (3, 2)}


def vertex(position, joint, weight=1.):
    return {'position': position, 'normal': (0., 0., 1.), 'source_joints': (joint,), 'source_weights': (weight,)}


def test_role_scales_replace_the_uniform_scale_for_the_named_roles_only():
    vertices = [vertex((1., 0., 0.), 1), vertex((1., 2., 0.), 2), vertex((1., 4., 0.), 3)]
    plain, _ = mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10.)
    assert [v['position'] for v in plain] == [pytest.approx(p) for p in ((10., 100., 0.), (10., 130., 0.), (10., 170., 0.))]
    output, receipt = mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10.,
                                            role_scales={'head': 3., 'chest': 20.})
    assert [v['position'] for v in output] == [pytest.approx(p) for p in ((10., 100., 0.), (20., 130., 0.), (3., 163., 0.))]
    assert receipt['scale'] == 10. and receipt['role_scales'] == {'head': 3., 'chest': 20.}
    assert 'role_scales' not in mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10.)[1]
    for bad in ({'neck': 2.}, {'head': 0.}, {'head': float('inf')}):
        with pytest.raises(ValueError, match='per-role scales'):
            mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10., role_scales=bad)
    with pytest.raises(ValueError, match='continuous'):
        mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10., role_scales={'head': 3.},
                              continuous=True)


def test_role_offsets_move_a_role_in_target_space_and_blend_with_the_weights():
    vertices = [vertex((1., 4., 0.), 3), {'position': (0., 2.5, 0.), 'normal': (0., 0., 1.),
                                          'source_joints': (2, 3), 'source_weights': (.5, .5)}]
    output, receipt = mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10.,
                                            role_offsets={'head': (0., -12., 0.)})
    assert output[0]['position'] == pytest.approx((10., 158., 0.))               # the whole head sits 12 lower
    assert output[1]['position'] == pytest.approx((0., 139., 0.))                # half of it for a half influence
    assert receipt['role_offsets'] == {'head': (0., -12., 0.)}
    for bad in ({'neck': (0., 1., 0.)}, {'head': (0., 1.)}, {'head': (0., float('nan'), 0.)}):
        with pytest.raises(ValueError, match='per-role offsets'):
            mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10., role_offsets=bad)


def test_an_influence_outside_the_roles_is_refused_unless_an_orphan_role_carries_it():
    vertices = [vertex((1., -1., 0.), 9)]                                         # joint 9: a root above the hips
    with pytest.raises(ValueError, match='no anatomical ancestor'):
        mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10.)
    output, receipt = mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10., orphan_role='hip')
    assert output[0]['position'] == pytest.approx((10., 90., 0.)) and output[0]['bones'] == [0]
    assert receipt['joint_mapping'][9] == {'role': 'hip', 'target': 0}
    with pytest.raises(ValueError, match='orphan role'):
        mtf_retarget.transfer(vertices, SOURCE, {}, TARGET, ROLES, {}, scale=10., orphan_role='tail')


def test_the_mesh_import_keeps_the_new_options_to_the_native_segment_mode():
    for options in ({'role_scales': {'head': 2.}}, {'role_offsets': {'head': (0., 1., 0.)}}, {'orphan_role': 'hip'}):
        with pytest.raises(ValueError, match='native_segments'):
            re5_mesh_import.build_archive(b'', 'unused.glb', model_name='x', source_roles={}, target_roles={},
                                          segments={}, scale=1., pose_mode='source_proportions', **options)


def ground_bone_model(bone_map):
    """Two bones that both carry animation id 0 (a ground bone and the body root), with a chosen 256-byte map."""
    raw = bytearray(model_bytes())
    model = mt_model.parse_mod(bytes(raw))
    offset, count = model.header()['offsets']['bones'], model.header()['bone_count']
    raw[offset + 24] = 0                                                          # the child now also says id 0
    raw[offset + count * 152:offset + count * 152 + 256] = bone_map
    return mt_model.parse_mod(bytes(raw))


def test_a_duplicate_animation_id_is_settled_only_by_a_real_bone_map():
    named = bytes([1]) + bytes([255]) * 255                                       # id 0 -> bone 1, nothing else
    assert mtf_motion._rig(ground_bone_model(named))[3] == {0: 1}
    first = bytes([0]) + bytes([255]) * 255                                       # id 0 -> bone 0
    assert mtf_motion._rig(ground_bone_model(first))[3] == {0: 0}
    for unusable in (bytes(256),                                                  # zeros: id 1.. would name bone 0 too
                     bytes([255]) * 256,                                          # names neither
                     bytes([1, 1]) + bytes([255]) * 254):                         # id 1 -> bone 1, whose id is 0
        with pytest.raises(mtf_motion.MotionError, match='duplicate native animation bone ID 0'):
            mtf_motion._rig(ground_bone_model(unusable))
    assert mtf_motion._rig(mt_model.parse_mod(model_bytes()))[3] == {0: 0, 1: 1}  # unique ids never consult the map
    assert struct.calcsize('<16f') == 64
