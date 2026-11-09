"""Real buffered motion, native skinning, and refusal boundaries without game assets."""
import math
import struct
import zlib

import numpy as np
import pytest

from gbox import mt_arc, mt_model, mtf_author, mtf_motion as motion
from tests.test_mtf_author import make_target


def model_bytes(child_x=2., meshes=1):
    raw = bytearray(make_target(meshes))
    offset = mt_model.parse_mod(raw).header()['offsets']['bones']
    raw[offset:offset+2] = bytes((0, 255))
    raw[offset+24:offset+26] = bytes((1, 0))
    for bone in range(2):
        local, inverse = np.eye(4), np.eye(4)
        if bone:
            local[3, 0], inverse[3, 0] = child_x, -child_x
        struct.pack_into('<16f', raw, offset+48+bone*64, *local.ravel())
        struct.pack_into('<16f', raw, offset+176+bone*64, *inverse.ravel())
    return bytes(raw)


def lmt_bytes(*tracks, frames=20, loop=0, index=2):
    """Sparse x64 v67 container, one clip and caller-owned key buffers."""
    raw = bytearray(64+48*len(tracks))
    raw[:8] = b'LMT\0'+struct.pack('<HH', 67, index+1)
    struct.pack_into('<Q', raw, 8+index*8, 40)
    struct.pack_into('<QIIi', raw, 40, 64, len(tracks), frames, loop)
    for ti, source in enumerate(tracks):
        t = dict(codec=3, usage=1, joint_type=0, bone=1, weight=1.,
                 reference=(2., 0., 0., 1.), keys=b'', bounds=None)
        t.update(source)
        keys = t['keys']
        pointer = len(raw) if keys else 0
        raw.extend(keys)
        bounds_pointer = len(raw) if t['bounds'] is not None else 0
        if bounds_pointer:
            raw.extend(struct.pack('<8f', *t['bounds']))
        struct.pack_into('<4BfQQ4fQ', raw, 64+48*ti,
                         t['codec'], t['usage'], t['joint_type'], t['bone'], t['weight'],
                         len(keys), pointer, *t['reference'], bounds_pointer)
    return bytes(raw)


def translation_lmt(**kw):
    return lmt_bytes({'keys': struct.pack('<3fI3fI', 0., 0., 0., 10, 10., 0., 0., 0)}, **kw)


def positions(result, side='native', frame=0):
    return np.array(result[side]['frames'][frame]['positions']).reshape(-1, 3)


def test_sparse_catalog_and_reference_then_buffered_key_timing():
    data = translation_lmt()
    assert motion.list_clips(data) == [{'index': 2, 'frame_count': 20, 'supported': True,
                                     'raw_fk_supported': True, 'engine_ik': False,
                                     'loop_frame': 0, 'track_count': 1, 'buffered_tracks': 1}]
    _, loop, tracks = motion._clip(data, 40)
    assert [tracks[0].sample(f, loop)[0] for f in (0, .5, 1, 6, 11, 19)] == [2., 1., 0., 5., 10., 10.]


def test_positive_loop_frame_does_not_insert_reference_key():
    data = translation_lmt(loop=5)
    _, loop, tracks = motion._clip(data, 40)
    assert tracks[0].sample(0, loop)[0] == 0
    assert tracks[0].sample(5, loop)[0] == 5


def test_same_true_clip_frames_for_both_models_and_joint_displacements():
    raw = model_bytes()
    result = motion.sample_compare(raw, raw, translation_lmt(), animation_index=2, frames=[0, 1, 6, 11])
    bind = np.asarray(mt_model.parse_mod(raw).positions(0))
    assert positions(result) == pytest.approx(bind, abs=1e-5)
    # Vertex 1 belongs to child bone; vertices 0/2 belong to unchanged root.
    for index, delta in enumerate((0., -2., 3., 8.)):
        expected = bind.copy()
        expected[1, 0] += delta
        assert positions(result, frame=index) == pytest.approx(expected, abs=1e-5)
        assert positions(result, 'candidate', index) == pytest.approx(expected, abs=1e-5)
    assert result['frame_indices'] == [0, 1, 6, 11]
    assert result['diagnostics']['buffered_tracks'] == 1
    assert all(j['distance_cm'] == 0 for f in result['diagnostics']['joint_displacements'] for j in f['joints'])
    assert result['native']['frames'][2]['skeleton']['world_matrices'][1][12] == 5.


def test_bind_pose_keeps_native_and_candidate_skeleton_difference_visible():
    result = motion.sample_compare(model_bytes(2), model_bytes(1), translation_lmt())
    assert result['clip']['animation_index'] is None
    assert result['clips'][0]['index'] == 2
    assert result['diagnostics']['joint_displacements'][0]['joints'][1]['distance_cm'] == 1
    assert positions(result) == pytest.approx(positions(result, 'candidate'))


def test_candidate_motion_uses_same_clip_and_frames_but_own_authored_translation():
    native = translation_lmt()
    candidate = lmt_bytes({'reference': (5., 0., 0., 1.),
                           'keys': struct.pack('<3fI3fI', 3., 0., 0., 10, 13., 0., 0., 0)})
    result = motion.sample_compare(model_bytes(), model_bytes(), native, candidate_lmt=candidate,
                                   animation_index=2, frames=[0, 1, 6, 11])
    for frame in range(4):
        difference = positions(result, 'candidate', frame)-positions(result, 'native', frame)
        assert difference[1] == pytest.approx((3., 0., 0.), abs=1e-5)
        assert difference[[0, 2]] == pytest.approx(np.zeros((2, 3)))
    assert result['motion_sha256']['native'] != result['motion_sha256']['candidate']


@pytest.mark.parametrize('candidate', [translation_lmt(frames=21), translation_lmt(loop=1),
                                       lmt_bytes({'bone': 0}), translation_lmt(index=1)])
def test_mismatched_candidate_motion_refuses(candidate):
    with pytest.raises(motion.MotionError, match='candidate'):
        motion.sample_compare(model_bytes(), model_bytes(), translation_lmt(), candidate_lmt=candidate,
                              animation_index=2)


def test_candidate_lmt_bytes_alias_and_dual_argument_refusal():
    data = translation_lmt()
    result = motion.sample_compare(model_bytes(), model_bytes(), data, candidate_lmt_bytes=data,
                                   animation_index=2)
    assert result['motion_sha256']['native'] == result['motion_sha256']['candidate']
    with pytest.raises(motion.MotionError, match='only one'):
        motion.sample_compare(model_bytes(), model_bytes(), data, candidate_lmt=data, candidate_lmt_bytes=data)


@pytest.mark.parametrize('track', [
    {'codec': 2, 'usage': 0, 'joint_type': 42, 'reference': (0., 0., 0., 1.)},
    {'bone': 19}, {'bone': 23},
])
def test_engine_ik_requires_explicit_diagnostic_opt_in(track):
    data = lmt_bytes(track)
    row = motion.list_clips(data)[0]
    assert row['engine_ik'] and row['raw_fk_supported'] and not row['supported']
    assert 'IK' in row['reason']
    with pytest.raises(motion.MotionError, match='Engine IK'):
        motion.sample_compare(model_bytes(), model_bytes(), data, animation_index=2)
    result = motion.sample_compare(model_bytes(), model_bytes(), data, animation_index=2, raw_fk=True)
    assert result['evaluation_mode'] == 'raw_fk_without_game_ik'
    assert result['diagnostics']['engine_ik'] is True


def test_sampled_fk_and_bind_modes_are_distinct():
    data = translation_lmt()
    result = motion.sample_compare(model_bytes(), model_bytes(), data, animation_index=2, frames=[0, 5])
    assert result['evaluation_mode'] == 'sampled_fk'
    assert result['diagnostics']['engine_ik'] is False
    assert motion.sample_compare(model_bytes(), model_bytes(), data)['evaluation_mode'] == 'bind_pose'


def test_constant_reference_tracks_and_unmapped_auxiliary_are_explicit():
    lmt = lmt_bytes({'keys': b'', 'reference': (5., 0., 0., 1.)},
                    {'codec': 2, 'usage': 0, 'joint_type': 33, 'bone': 254, 'reference': (0., 0., 0., 1.)})
    result = motion.sample_compare(model_bytes(), model_bytes(), lmt, animation_index=2, frames=[0, 9])
    assert positions(result, frame=0) == pytest.approx(positions(result, frame=1))
    assert result['diagnostics']['unmapped_tracks']['native'] == [{'anim_id': 254, 'usage': 0, 'joint_type': 33}]
    assert 'IK' in result['diagnostics']['limitations'][0]


def test_virtual_root_translation_moves_geometry_and_skeleton_together():
    lmt = lmt_bytes({'bone': 255, 'usage': 4, 'reference': (7., 3., -1., 1.)})
    result = motion.sample_compare(model_bytes(), model_bytes(), lmt, animation_index=2)
    bind = np.asarray(mt_model.parse_mod(model_bytes()).positions(0))
    assert positions(result) == pytest.approx(bind+(7., 3., -1.), abs=1e-5)
    assert result['native']['frames'][0]['skeleton']['bones'][0] == [7., 3., -1.]


def test_slerp_rotation_moves_child_vertices_in_native_row_vector_order():
    # A child-local +90deg Z rotation at constant frame0, keeping its local X=2 translation.
    q = (0., 0., math.sqrt(.5), math.sqrt(.5))
    data = lmt_bytes({'codec': 2, 'usage': 0, 'reference': q})
    result = motion.sample_compare(model_bytes(), model_bytes(), data, animation_index=2)
    bind = np.asarray(mt_model.parse_mod(model_bytes()).positions(0))
    x, y, z = bind[1]
    assert positions(result)[1] == pytest.approx((2-y, x-2, z), abs=1e-5)
    assert motion._interpolate((0, 0, 0, 1), (0, 0, 1, 0), .5, True) == pytest.approx(q)
    assert motion._interpolate(q, tuple(-v for v in q), .5, True) == pytest.approx(q)


@pytest.mark.parametrize('codec,raw,expected,delta', [
    (1, struct.pack('<3f', 1., 2., 3.), (1., 2., 3., 1.), 1),
    (2, struct.pack('<3f', 0., 0., 0.), (0., 0., 0., 1.), 1),
    (3, struct.pack('<3fI', 1., 2., 3., 17), (1., 2., 3., 1.), 17),
    (4, struct.pack('<4H', 0, 32768, 65535, 19), (0., 32768/65535, 1., 1.), 19),
    (5, bytes((0, 128, 255, 21)), (0., 128/255, 1., 1.), 21),
    (6, ((4096 << 42) | ((16383-2048) << 28) | (1024 << 14) | 2048 | (7 << 56)).to_bytes(8, 'little'),
     (4096*4/16383, -2048*4/16383, 1024*4/16383, 2048*4/16383), 7),
    (7, ((127 << 21) | (64 << 14) | (16 << 7) | 8 | (13 << 28)).to_bytes(4, 'little'),
     (1., 64/127, 16/127, 8/127), 13),
    (11, (4096 | (8192 << 14) | (9 << 28)).to_bytes(4, 'little'), (4096/16383, 0., 0., 8192/16383), 9),
    (12, (4096 | (8192 << 14) | (9 << 28)).to_bytes(4, 'little'), (0., 4096/16383, 0., 8192/16383), 9),
    (13, (4096 | (8192 << 14) | (9 << 28)).to_bytes(4, 'little'), (0., 0., 4096/16383, 8192/16383), 9),
    (14, bytes.fromhex('238916f16b92'), tuple(x/2047 for x in (0x123, 0x456, 0x789, 0x135)), 9),
    (15, bytes.fromhex('91abc699a5'), tuple(x/511 for x in (0x123, 0x156, 0x189, 0x135)), 10),
])
def test_measured_v67_codec_lanes(codec, raw, expected, delta):
    value, duration = motion._decode_key(codec, raw, None)
    assert value == pytest.approx(expected)
    assert duration == delta


def test_quantization_uses_span_then_offset_and_preserves_reference():
    data = lmt_bytes({'codec': 5, 'keys': bytes((0, 128, 255, 0)),
                     'bounds': (10., 20., 30., 0., -4., 1., 2., 1.)})
    _, loop, tracks = motion._clip(data, 40)
    assert tracks[0].sample(0, loop) == (2., 0., 0., 1.)
    assert tracks[0].sample(1, loop) == pytest.approx((-4., 1+20*128/255, 32., 1.))


@pytest.mark.parametrize('mutation,match', [
    ({'codec': 9}, 'unsupported LMT codec'),
    ({'codec': 2, 'usage': 1}, 'codec/usage'),
    ({'weight': .5}, 'blend weight'),
    ({'reference': (math.nan, 0, 0, 1)}, 'non-finite'),
    ({'codec': 2, 'usage': 0, 'reference': (0, 0, 0, 0)}, 'zero quaternion'),
    ({'keys': b'bad'}, 'multiple'),
    ({'keys': struct.pack('<3fI3fI', 1, 2, 3, 0, 4, 5, 6, 0)}, 'non-increasing'),
])
def test_unsupported_or_malformed_track_refuses_entire_animation(mutation, match):
    data = lmt_bytes(mutation)
    catalog = motion.list_clips(data)
    assert not catalog[0]['supported']
    assert match in catalog[0]['reason']
    with pytest.raises(motion.MotionError, match=match):
        motion.sample_compare(model_bytes(), model_bytes(), data, animation_index=2)


def test_malformed_table_pointer_and_version_are_rejected():
    data = bytearray(translation_lmt())
    struct.pack_into('<Q', data, 64+16, len(data)+3)
    assert not motion.list_clips(data)[0]['supported']
    data[4:6] = struct.pack('<H', 66)
    with pytest.raises(motion.MotionError, match='version 66'):
        motion.list_clips(data)
    with pytest.raises(motion.MotionError, match='offset table'):
        motion.list_clips(b'LMT\0'+struct.pack('<HH', 67, 200))


@pytest.mark.parametrize('frames', [[], list(range(61)), [-1], [20], [math.nan], [True]])
def test_export_frame_bounds(frames):
    with pytest.raises(motion.MotionError, match='frame'):
        motion.sample_compare(model_bytes(), model_bytes(), translation_lmt(), animation_index=2, frames=frames)


def test_unknown_vertex_layout_refuses_instead_of_dominant_bone_fallback():
    raw = bytearray(model_bytes())
    off = mt_model.parse_mod(raw).header()['offsets']['meshes']
    struct.pack_into('>I', raw, off+20, 0xDEADBEEF)
    with pytest.raises(motion.MotionError, match='skin vertex layout'):
        motion.sample_compare(raw, model_bytes())


@pytest.mark.parametrize('kind', [0x14A07DDB, 0x1C201FC3, 0x1580B60C, 0x16C020A3, 0x2000D414, 0x244042BB])
def test_multiple_skin_weights_are_retained_including_residual(kind):
    raw = bytearray(40)
    if kind in (0x14A07DDB, 0x1C201FC3):
        struct.pack_into('<h', raw, 6, 16384)
        struct.pack_into('<2h' if kind == 0x14A07DDB else '<2e', raw, 12 if kind == 0x14A07DDB else 20, 1, 2)
    elif kind in (0x1580B60C, 0x16C020A3):
        count = 4 if kind == 0x1580B60C else 8
        raw[8:8+count] = bytes(range(count))
        raw[8+count:8+count*2] = bytes([128, 127]+[0]*(count-2))
    else:
        count = 4 if kind == 0x2000D414 else 8
        struct.pack_into('<h', raw, 6, 16384)
        raw[16:16+count] = bytes(range(count))
        struct.pack_into('<2e', raw, 24 if count == 4 else 28, .125, .125)
        if count == 8:
            raw[12:16] = bytes((8, 8, 8, 8))
    row = motion._influences(raw, {'vertex_format': kind, 'vertex_stride': 40}, 8)[0]
    assert len(row) >= 2
    assert sum(w for _, w in row) == pytest.approx(1.)
    if kind == 0x244042BB:
        assert len(row) == 8
        assert row[-1][0] == 7


def test_animated_vertices_blend_all_positive_bones_instead_of_dominant_only():
    native = mt_model.parse_mod(model_bytes())
    vertices = [{'position': p, 'normal': (0., 0., 1.), 'uv': (i/2, i%2),
                 'bones': [0, 1], 'weights': [.75, .25]}
                for i, p in enumerate(((-.5, 0., 0.), (.5, 0., 0.), (0., .5, 0.)))]
    authored = mtf_author.build_one_mesh(native, vertices, [(0, 1, 2)], four_weights=True)
    result = motion.sample_compare(authored, authored, translation_lmt(), animation_index=2, frames=[0, 11])
    # Child travels eight units; a quarter-weight moves each vertex two units.
    displacement = positions(result, frame=1)-positions(result, frame=0)
    assert displacement == pytest.approx(np.tile((2., 0., 0.), (3, 1)), abs=.001)


def test_invalid_positive_bone_and_invalid_weight_sum_refuse():
    raw = bytearray(20)
    struct.pack_into('<H', raw, 6, 30)
    with pytest.raises(motion.MotionError, match='invalid bone'):
        motion._influences(raw, {'vertex_format': 0x18B0FAA8, 'vertex_stride': 20}, 2)
    raw[8:12] = bytes((0, 1, 0, 0))
    raw[12:16] = bytes((0, 0, 0, 0))
    with pytest.raises(motion.MotionError, match='invalid skin weights'):
        motion._influences(raw, {'vertex_format': 0x1580B60C, 'vertex_stride': 20}, 2)


def test_cycle_and_duplicate_animation_mapping_refuse():
    for mutate, match in ((lambda raw, p: raw.__setitem__(p+1, 1), 'cycle'),
                          (lambda raw, p: raw.__setitem__(p+24, 0), 'duplicate')):
        raw = bytearray(model_bytes())
        mutate(raw, mt_model.parse_mod(raw).header()['offsets']['bones'])
        with pytest.raises(motion.MotionError, match=match):
            motion.sample_compare(raw, model_bytes())


def test_named_compressed_arc_and_all_full_detail_groups():
    raw = bytearray(model_bytes(meshes=2))
    p = mt_model.parse_mod(raw).header()['offsets']['meshes']
    raw[p+56+4] = 1  # second mesh is a different group, still LOD bit1.
    # Native strips can use a nonzero vertex_index with a shared buffer base.
    struct.pack_into('<I', raw, p+56+12, 3)
    struct.pack_into('<I', raw, p+56+16, 0)
    indices = mt_model.parse_mod(raw).header()['offsets']['index_buffer']
    struct.pack_into('<3H', raw, indices+8, 3, 4, 5)
    entry = mt_arc.Entry('pawn\\pl\\pl00\\model\\pl0000', 0, 0, 0, 0, zlib.compress(raw))
    archive = mt_arc.build(mt_arc.Arc(7, [entry]))
    result = motion.sample_compare(archive, raw)
    assert result['native']['mesh_indices'] == [0, 1]
    assert result['native']['vertex_count'] == 6
    assert result['native']['model_sha256'] == result['candidate']['model_sha256']
    assert result['native']['triangles'] == [[0, 1, 2], [3, 4, 5]]
    with pytest.raises(motion.MotionError, match='exactly one'):
        motion.sample_compare(archive, raw, model_name='pl0100')
