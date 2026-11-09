"""Group-aware RE5 enemy writer, on synthetic Majini-shaped fixtures only: no game asset or donor file is read.

The fixture mirrors what was measured on uEm10.arc: MOD and MRL entries sharing a name, a skeleton whose role bones
carry the RE5 animation ids, no option group 0, several records per group with native LOD masks, a depth-only proxy
record, a shared vertex buffer, strips with inner restart markers and an odd index count.
"""
import hashlib
import os
import struct
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, mtf_mrl, mtf_tex, re5_enemy_writer as W

COMPRESSION = np.diag([400., 400., 400., 1.])
COMPRESSION[3, :3] = (-150., -10., -150.)
FULL, ONE, PROXY = 0x2000D414, 0x18B0FAA8, 0x1580B60C
MODEL = 'pawn\\em\\model\\'
GROUPS = (('head', (1, 11)), ('body', (2,)), ('feet', (7,)))


def skeleton(helper=False):
    """(name, animation id, parent, bind position); `helper` adds a leaf that shifts every later bone index."""
    bones = [('root', 0, None, (0, 100, 0)), ('pelvis', 15, 'root', (0, 100, 0))]
    for side, sign, base in (('r', -1, 16), ('l', 1, 20)):
        bones += [(f'{side}_thigh', base, 'pelvis', (10 * sign, 90, 0))]
        if helper and side == 'r':
            bones += [('r_knee_helper', 68, 'r_thigh', (-10, 50, 0))]
        bones += [(f'{side}_shin', base + 1, f'{side}_thigh', (10 * sign, 50, 0)),
                  (f'{side}_foot', base + 2, f'{side}_shin', (10 * sign, 10, 0)),
                  (f'{side}_toe', base + 3, f'{side}_foot', (10 * sign, 2, 12))]
    bones += [('spine', 1, 'root', (0, 105, 0)), ('chest', 2, 'spine', (0, 130, 0))]
    for side, sign, base in (('r', -1, 5), ('l', 1, 10)):
        bones += [(f'{side}_clav', base, 'chest', (5 * sign, 145, 0)),
                  (f'{side}_upper', base + 1, f'{side}_clav', (18 * sign, 150, 0)),
                  (f'{side}_fore', base + 2, f'{side}_upper', (45 * sign, 150, 0)),
                  (f'{side}_wrist', base + 3, f'{side}_fore', (70 * sign, 150, 0)),
                  (f'{side}_hand', base + 4, f'{side}_wrist', (70 * sign, 150, 0))]
    return bones + [('neck', 3, 'chest', (0, 155, 0)), ('head', 4, 'neck', (0, 165, 0))]


def bone_block(bones):
    index = {name: i for i, (name, *_) in enumerate(bones)}
    headers, local, inverse = b'', b'', b''
    for name, animation, parent, point in bones:
        headers += bytes((animation, 255 if parent is None else index[parent], 0, 0)) + bytes(20)
        world, relative = np.eye(4), np.eye(4)
        world[3, :3] = point
        relative[3, :3] = np.subtract(point, bones[index[parent]][3]) if parent else point
        local += struct.pack('<16f', *relative.ravel())
        inverse += struct.pack('<16f', *(COMPRESSION @ np.linalg.inv(world)).ravel())
    return headers + local + inverse + bytes(256)


def pack(fmt, points, bone):
    transform = tuple(COMPRESSION.ravel())
    if fmt == FULL:
        data = bytearray(mt_model.pack_vertices(
            [{'position': p, 'normal': (0., 0., 1.), 'uv': (.5, .5), 'bones': [bone, 0, 0, 0], 'weights': [0., 0.]}
             for p in points], FULL, 28, position_transform=transform))
        for i in range(len(points)):
            struct.pack_into('<h', data, i * 28 + 6, 32767)
        return bytes(data)
    if fmt == ONE:
        return mt_model.pack_vertices([{'position': p, 'normal': (0., 0., 1.), 'uv': (.5, .5), 'bones': [bone]}
                                       for p in points], ONE, 20, position_transform=transform)
    return mt_model.pack_vertices([{'position': p, 'bones': [bone, 0, 0, 0], 'weights': [1., 0., 0., 0.]}
                                   for p in points], PROXY, 20, position_transform=transform)


def parts(bones):
    """Native records in table order (sorted by material): group, material, LOD mask, type, mode, format, flags."""
    b = {name: i for i, (name, *_) in enumerate(bones)}
    quad = [(-4., 170., 0.), (4., 170., 0.), (-4., 178., 0.), (4., 178., 0.)]
    return [
        dict(group=1, material=0, lod=1, kind=0x1020, mode=132, fmt=PROXY, flags=33, bone=b['head'], points=quad,
             strips=[[0, 1, 2, 3]]),
        dict(group=1, material=0, lod=1, kind=0xFFFF, mode=4, fmt=FULL, flags=33, bone=b['head'],
             points=quad + [(0., 185., 3.)], strips=[[0, 1, 2], [2, 3, 4]]),
        dict(group=1, material=0, lod=2, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['head'], points=quad[:3],
             strips=[[0, 1, 2]]),
        dict(group=1, material=0, lod=252, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['neck'], points=quad[1:],
             strips=[[0, 1, 2]], shared=True),
        dict(group=11, material=0, lod=1, kind=0xFFFF, mode=4, fmt=FULL, flags=33, bone=b['head'], points=quad[:3],
             strips=[[0, 1, 2]]),
        dict(group=7, material=1, lod=1, kind=0xFFFF, mode=4, fmt=FULL, flags=33, bone=b['l_foot'],
             points=[(8., 0., 0.), (12., 0., 0.), (10., 0., 14.)], strips=[[0, 1, 2]]),
        dict(group=7, material=1, lod=2, kind=0xFFFF, mode=4, fmt=FULL, flags=33, bone=b['r_foot'],
             points=[(-8., 0., 0.), (-12., 0., 0.), (-10., 0., 14.)], strips=[[0, 1, 2]]),
        dict(group=2, material=2, lod=252, kind=0xFFFF, mode=4, fmt=FULL, flags=33, bone=b['chest'],
             points=[(-15., 110., 5.), (15., 110., 5.), (-15., 150., 5.), (15., 150., 5.)], strips=[[0, 1, 2, 3, 3]]),
    ]


def enemy_mod(bones, materials=('skin', 'sandal', 'cloth'), groups=(1, 2, 7, 11)):
    rows = parts(bones)
    order = sorted(range(len(rows)), key=lambda i: (W.NATIVE_LOD_MASKS.index(rows[i]['lod']), i))
    records, vertices, words, envelopes = b'', b'', [], b''
    offset = index = 0
    for number, row in enumerate(rows):
        stride = 28 if row['fmt'] == FULL else 20
        data = pack(row['fmt'], row['points'], row['bone'])
        if row.get('shared'):                       # same buffer base as the previous record, later window
            index += len(rows[number - 1]['points'])
        else:
            offset, index = len(vertices), 0
        vertices += data
        strip = []
        for k, part in enumerate(row['strips']):
            strip += ([0xFFFF] if k else []) + [v + index for v in part]
        record = bytearray(56)
        struct.pack_into('<HHI', record, 0, row['kind'], len(row['points']),
                         row['group'] | row['material'] << 12 | row['lod'] << 24)
        record[8:12] = bytes((row['flags'], number, stride, row['mode']))
        struct.pack_into('<II', record, 0x0C, index, offset)
        struct.pack_into('>I', record, 0x14, row['fmt'])
        struct.pack_into('<III', record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into('<HHH', record, 0x26, order.index(number) + 1, index, index + len(row['points']) - 1)
        record[0x2C:0x38] = bytes([0xA0 + number]) * 12        # opaque native bytes the writer must carry
        records += record
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(row['bone'], row['points'])
    assert len(words) % 2                                      # like em1000_low: one alignment word follows
    indices = struct.pack(f'<{len(words)}H', *words) + bytes(2)
    tail = struct.pack('<12f', 0, 90, 0, 120, -80, 0, -20, 0, 80, 190, 20, 0) + struct.pack('<5I', 500, 1000, 3, 0,
                                                                                         len(rows))
    group_block = b''.join(struct.pack('<I12x4f', group, 0, 10, 0, 30) for group in groups)
    material_block = b''.join(name.encode().ljust(128, b'\0') for name in materials)
    blocks = (bone_block(bones), group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0x28 + 56 + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack('<3H', len(bones), len(rows), len(materials))
    out += struct.pack('<3I2I2I', sum(len(r['points']) for r in rows), len(words), 9, len(vertices), 0, len(groups), 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    return out


def enemy_mrl(materials=('skin', 'sandal', 'cloth')):
    paths = [MODEL + 'sandal_NM', MODEL + 'sandal_BM', MODEL + 'sandal_MM', MODEL + 'skin_BM']
    binds = {'skin': [(4, mtf_mrl.ALBEDO_HASH)], 'cloth': [(4, mtf_mrl.ALBEDO_HASH)],
             'sandal': [(1, W.NORMAL_HASH), (2, mtf_mrl.ALBEDO_HASH), (3, W.MASK_HASH)]}
    table = 40 + len(paths) * 88
    cursor = (table + 72 * len(materials) + 15) & ~15
    raw = bytearray(cursor + 24 * sum(len(binds[m]) for m in materials))
    struct.pack_into('<4sIIIQQQ', raw, 0, b'MRL\0', 34, len(materials), len(paths), mtf_mrl.RE5_SHADER_VERSION, 40, table)
    for i, path in enumerate(paths):
        raw[40 + i * 88 + 24:40 + i * 88 + 24 + len(path)] = path.encode()
    for i, name in enumerate(materials):
        commands = binds[name]
        struct.pack_into('<QII', raw, table + 72 * i, mtf_mrl.MATERIAL_STD, zlib.crc32(name.encode()) ^ 0xFFFFFFFF,
                         24 * len(commands))
        struct.pack_into('<I', raw, table + 72 * i + 28, len(commands))
        struct.pack_into('<Q', raw, table + 72 * i + 56, cursor)
        for value, shader in commands:
            struct.pack_into('<IIQQ', raw, cursor, 3, 0xCDCDCDCD, value, shader << 12 | 0x375)
            cursor += 24
    return bytes(raw)


def tex(fmt, size=32):
    """A Switch TEX with the measured per-mip Tegra block storage and a non-zero padding pattern."""
    width, offsets, total = {0x19: 8, 0x1F: 16, 0x30: 16}[fmt], [], 0
    for level in range(size.bit_length()):
        blocks = (max(1, size >> level) + 3) // 4
        height = max(1, min(16, (1 << (blocks - 1).bit_length()) // 8))
        offsets.append(total)
        total += ((blocks * width + 63) // 64) * 64 * ((blocks + 8 * height - 1) // (8 * height)) * 8 * height
    header = b'TEX\0\xa1\x80\0\x20' + struct.pack('<3I', len(offsets) | size << 6 | size << 19, 0x10001 | fmt << 8, total)
    return header + struct.pack(f'<{len(offsets)}I', *offsets) + bytes((n * 37 + fmt) % 256 for n in range(total))


def enemy_arc(motion=b'LMT\0motion'):
    """(archive, reviewed set). MOD and MRL share names, as in uEm10.arc; the low model shifts the bone indices."""
    contents = [(MODEL + 'sandal_BM', tex(0x30)), (MODEL + 'sandal_MM', tex(0x19)), (MODEL + 'sandal_NM', tex(0x1F)),
                (MODEL + 'skin_BM', tex(0x30)), (MODEL + 'body', enemy_mrl()), (MODEL + 'body_low', enemy_mrl()),
                ('untouched', b'\x02\0\0\0preserved'), (MODEL + 'body', enemy_mod(skeleton())),
                (MODEL + 'body_low', enemy_mod(skeleton(helper=True))), (MODEL + 'body', motion)]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data)) for name, data in contents]
    target = W.EnemySet(name='body', models=((MODEL + 'body', 7, 4), (MODEL + 'body_low', 8, 5)), groups=GROUPS,
                        albedo=(0, MODEL + 'sandal_BM'), normal=(2, MODEL + 'sandal_NM'), mask=(1, MODEL + 'sandal_MM'))
    return mt_arc.build(mt_arc.Arc(7, entries)), target


@pytest.fixture
def donor(tmp_path, monkeypatch):
    """A fifteen-joint donor through the real loaders' seams: one triangle on every joint, soles on y 0."""
    joints = {'skl_root': (0., 6., 0.), 'spin': (0., 7., 0.), 'head:root': (0., 11., 0.)}
    for side, sign in (('l', 1.), ('r', -1.)):
        joints |= {f'arm_{side}1': (2. * sign, 10., 0.), f'arm_{side}2': (4. * sign, 10., 0.),
                   f'wrist_{side}1': (6. * sign, 10., 0.), f'leg_{side}1': (1.4 * sign, 6., 0.),
                   f'leg_{side}2': (1.4 * sign, 3.4, 0.), f'ankle_{side}1': (1.4 * sign, 1.4, 0.)}
    names = list(joints)
    parent = {'spin': 'skl_root', 'head:root': 'spin'}
    for side in 'lr':
        parent |= {f'arm_{side}1': 'spin', f'arm_{side}2': f'arm_{side}1', f'wrist_{side}1': f'arm_{side}2',
                   f'leg_{side}1': 'skl_root', f'leg_{side}2': f'leg_{side}1', f'ankle_{side}1': f'leg_{side}2'}
    nodes = [{'name': name, 'children': [names.index(c) for c, p in parent.items() if p == name]} for name in names]
    world = []
    for name in names:
        matrix = np.eye(4)
        matrix[:3, 3] = joints[name]
        world.append(matrix)
    vertices, triangles = [], []

    def triangle(corners):
        triangles.append(tuple(range(len(vertices), len(vertices) + 3)))
        for point, joint in corners:
            vertices.append({'position': point, 'normal': (0., 0., 1.), 'uv': (.25, .25),
                             'source_joints': (names.index(joint),), 'source_weights': (1.,)})
    for name, (x, y, z) in joints.items():
        triangle([((x + .3, y, z), name), ((x, y + .3, z), name), ((x, y, z + .3), name)])
    for side, sign in (('l', 1.), ('r', -1.)):                       # soles, and one triangle across three joints
        ankle = f'ankle_{side}1'
        triangle([((1.1 * sign, 0., -.3), ankle), ((1.7 * sign, 0., -.3), ankle), ((1.4 * sign, 0., .9), ankle)])
        triangle([((.2 * sign, 6., .1), 'skl_root'), ((1.4 * sign, 5.6, .1), f'leg_{side}1'), ((0., 7.2, .1), 'spin')])
    source = tmp_path / 'donor.glb'
    source.write_bytes(b'synthetic donor')
    monkeypatch.setattr(W.characters, '_load', lambda _: ({'nodes': nodes}, None, None, world))
    monkeypatch.setattr(W.mtf_materials, 'source_mesh', lambda _, atlas_size: (
        [dict(v) for v in vertices], list(triangles), Image.new('RGBA', atlas_size, 'red'), {'materials': 1}))
    monkeypatch.setattr(W.mtf_tex, 'replace_image',
                        lambda data, image: mtf_tex.replace_blocks(data, bytes([7]) * 1024, 0))
    return source


def one_mesh(model, bone):
    """A donor authored on `model` by the shared one-mesh writer, as `re5_mesh_import` hands it over."""
    points = [(-20., 0., 0.), (20., 0., 0.), (0., 200., 0.), (0., 100., 30.)]
    vertices = [{'position': p, 'normal': (0., 0., 1.), 'uv': (.1 * i, .2), 'bones': [bone], 'weights': [1.]}
                for i, p in enumerate(points)]
    built = mtf_author.build_one_mesh(model, vertices, [(0, 1, 2), (1, 3, 2)], material_index=1, template_index=1,
                                      four_weights=True)
    fitted = {'min': {'x': -20., 'y': 0., 'z': 0.}, 'max': {'x': 20., 'y': 200., 'z': 30.},
              'sphere': {'x': 0., 'y': 100., 'z': 15., 'r': 103.}}
    return mt_model.parse_mod(mt_model.rebuild_mod(mt_model.parse_mod(built), bounds=fitted))


def test_reviewed_em1000_table_accounts_for_all_55_groups_with_explicit_entry_indices():
    ids = W.EM1000.group_ids()
    assert len(ids) == len(set(ids)) == 55 and 0 not in ids
    # the last digit is the selection slot; nothing is on the list by pattern alone, but the pattern must hold
    assert {slot: {g % 10 for g in groups} for slot, groups in W.EM1000.groups} == {
        'head': {1}, 'arm_skin': {2}, 'leg_skin': {3}, 'shirt': {4}, 'pants': {5}, 'sandals': {7}}
    assert [(name.rsplit('\\', 1)[-1], mod, mrl) for name, mod, mrl in W.EM1000.models] == [
        ('em1000', 234, 196), ('em1000_low', 235, 197), ('em1000_mid', 236, 198)]
    assert (W.EM1000.albedo[0], W.EM1000.normal[0], W.EM1000.mask[0]) == (108, 110, 109)
    assert sorted(set(W.EM1001.group_ids()) - set(ids)) == [35] and len(W.EM1001.group_ids()) == 56
    assert W.ARCHIVE_SHA256.startswith('1fa27189') and W.SOURCE_SHA256.startswith('ea509bdf')
    assert set(W.SOURCE_ROLES) == set(W.ROLE_ANIMATION_IDS) and len(W.SOURCE_ROLES) == 15


@pytest.mark.parametrize('helper', [False, True])
def test_roles_are_measured_from_the_bind_pose_and_agree_with_the_animation_ids(helper):
    bones = skeleton(helper)
    index = {name: i for i, (name, *_) in enumerate(bones)}
    model = mt_model.parse_mod(enemy_mod(bones))
    measured, extra = W.measure_roles(model)
    expected = {'hip': 'pelvis', 'chest': 'chest', 'head': 'head'} | {
        f'{s}_{part}': f'{s}_{part}' for s in 'lr' for part in ('upper', 'fore', 'hand', 'thigh', 'shin', 'foot')}
    assert measured == {role: index[bone] for role, bone in expected.items()}
    assert extra['facing'] == '+Z' and extra['left_side'] == '+X' and extra['root'] == 0
    assert bones[measured['l_hand']][3][0] > 0 > bones[measured['r_hand']][3][0]
    roles, evidence = W.role_map(model)
    assert roles == measured == W.roles_by_animation_id(model)
    assert evidence['bind_position']['l_foot'] == [10., 10., 0.] and evidence['animation_ids']['hip'] == 15


def test_role_map_refuses_a_skeleton_whose_ids_and_positions_disagree():
    bones = skeleton()
    swapped = [(name, {11: 6, 6: 11}.get(animation, animation), parent, point) for name, animation, parent, point in bones]
    with pytest.raises(W.EnemyWriterError, match='disagree'):
        W.role_map(mt_model.parse_mod(enemy_mod(swapped)))
    duplicate = [(name, 4 if name == 'neck' else animation, parent, point) for name, animation, parent, point in bones]
    with pytest.raises(W.EnemyWriterError, match='exactly one bone'):
        W.role_map(mt_model.parse_mod(enemy_mod(duplicate)))
    one_arm = [bone for bone in bones if not bone[0].startswith('l_') or bone[0] in ('l_thigh', 'l_shin', 'l_foot', 'l_toe')]
    with pytest.raises(W.EnemyWriterError):
        W.measure_roles(mt_model.parse_mod(enemy_mod(one_arm)))


def test_every_option_group_must_be_on_the_reviewed_list_and_present():
    _, target = enemy_arc()
    model = mt_model.parse_mod(enemy_mod(skeleton()))
    accounted = W.account_groups(model, target)
    assert {g: row['slot'] for g, row in accounted.items()} == {1: 'head', 11: 'head', 2: 'body', 7: 'feet'}
    assert accounted[1]['native_records'] == 4 and accounted[1]['native_lod_masks'] == [1, 2, 252]
    for groups in ((('head', (1,)), ('body', (2,)), ('feet', (7,))),               # 11 is in the model, unreviewed
                   (('head', (1, 11, 21)), ('body', (2,)), ('feet', (7,))),         # 21 is reviewed, absent
                   (('head', (1, 11)), ('body', (2, 0)), ('feet', (7,)))):          # group 0 is the player layout
        with pytest.raises(W.EnemyWriterError):
            W.account_groups(model, W.EnemySet('x', target.models, groups, target.albedo, target.normal, target.mask))


def test_graft_keeps_the_native_table_bytes_and_adds_the_donor_once_per_group():
    bones = skeleton()
    raw = enemy_mod(bones)
    native = mt_model.parse_mod(raw)
    donor = one_mesh(native, 11)
    result, report = W.graft(native, donor, groups=[1, 11, 2, 7], material_index=1)
    model = mt_model.parse_mod(result)
    before, header = native.header(), model.header()
    records, originals = model.meshes(), native.meshes()
    assert report == report | {'native_records': 8, 'donor_records': 4, 'mesh_records': 12, 'inserted_at': 7,
                               'donor_triangles_per_record': 2, 'donor_vertices_per_record': 4}
    assert header['mesh_count'] == 12 and model.split_valid()
    # the skeleton, group table, material names and LOD distances are the native bytes
    old, new = before['offsets'], header['offsets']
    assert result[new['bones']:new['meshes']] == raw[old['bones']:old['meshes']] and result[0x90:0xA0] == raw[0x90:0xA0]
    # native records: 56 bytes (opaque tail included), vertices and envelopes are identical and stay in order
    kept = [i for i, r in enumerate(records) if r['level_of_detail'] != 0xFF]
    added = [i for i, r in enumerate(records) if r['level_of_detail'] == 0xFF]
    assert kept == [0, 1, 2, 3, 4, 5, 6, 11] and added == [7, 8, 9, 10]
    for position, original in zip(kept, range(8)):
        assert (result[new['meshes'] + 56 * position:new['meshes'] + 56 * position + 56]
                == raw[old['meshes'] + 56 * original:old['meshes'] + 56 * original + 56])
        assert model.mesh_bytes(position)[0] == native.mesh_bytes(original)[0]
        assert mtf_author.mesh_triangles(model, position) == []             # every native strip is degenerate now
    assert [mtf_author.mesh_triangles(native, i) != [] for i in range(8)] == [True] * 8
    assert [row['bone'] for row in model.weight_bounds()][:7] == [row['bone'] for row in native.weight_bounds()][:7]
    assert model.weight_bounds()[-1] == native.weight_bounds()[-1]
    # only index values changed: restart markers, counts and the shared-buffer windows are where they were
    words = np.frombuffer(result[new['index_buffer']:new['index_buffer'] + 2 * before['face_count']], '<u2')
    native_words = np.frombuffer(raw[old['index_buffer']:old['index_buffer'] + 2 * before['face_count']], '<u2')
    assert np.array_equal(words == 0xFFFF, native_words == 0xFFFF)
    assert words[originals[3]['face_index']] == originals[3]['min_index'] == 3
    # donor records: one per group, all LODs, one material, ids after the native ones, table still sorted by material
    assert [records[i]['group_index'] for i in added] == [1, 11, 2, 7]
    assert {(records[i]['material_index'], records[i]['level_of_detail'], records[i]['mesh_type'],
             records[i]['vertex_format'], records[i]['vertex_flags'], records[i]['mesh_class']) for i in added} == {
        (1, 0xFF, 0xFFFF, FULL, 33, 0)}
    assert [records[i]['mesh_id'] for i in added] == [9, 10, 11, 12]
    assert sorted(r['mesh_id'] for r in records) == list(range(1, 13))
    assert [r['material_index'] for r in records] == sorted(r['material_index'] for r in records)
    assert result[new['meshes'] + 56 * 7 + 0x2C:new['meshes'] + 56 * 8] == bytes([0xA1]) * 12   # template record 1
    for i in added:
        assert model.mesh_bytes(i)[0] == donor.mesh_bytes(0)[0]
        assert mtf_author.mesh_triangles(model, i) == mtf_author.mesh_triangles(donor, 0)
        assert model.positions(i) == donor.positions(0)
    # header accounting: vertices, faces (+ one separator per record), 144-byte envelopes counted at 0xA0, alignment
    assert header['vertex_count'] == before['vertex_count'] + 4 * 4
    assert header['face_count'] == before['face_count'] + 4 * 8 == sum(r['face_count'] for r in records) + 12
    assert header['weight_bound_count'] == struct.unpack_from('<I', result, 0xA0)[0] == 8 + 4 * 1
    assert new['vertex_buffer'] - new['meshes'] == 56 * 12 + 144 * 12
    assert (new['end'] - new['index_buffer']) % 4 == 0 and result[new['end'] - 2:new['end']] == bytes(2)
    assert model.bounds() == donor.bounds() and model.bounds() != native.bounds()


def test_graft_refuses_a_donor_from_another_skeleton_or_an_unmeasured_native_table():
    native = mt_model.parse_mod(enemy_mod(skeleton()))
    other = mt_model.parse_mod(enemy_mod(skeleton(helper=True)))
    with pytest.raises(W.EnemyWriterError, match='exact skeleton'):
        W.graft(native, one_mesh(other, 12), groups=[1, 11, 2, 7], material_index=1)
    with pytest.raises(W.EnemyWriterError, match='distinct option groups'):
        W.graft(native, one_mesh(native, 11), groups=[1, 1], material_index=1)
    stale = bytearray(native.raw)
    struct.pack_into('<I', stale, 0xA0, 3799)                         # the count that froze loading
    with pytest.raises(W.EnemyWriterError, match='0xA0'):
        W.graft(mt_model.parse_mod(bytes(stale)), one_mesh(native, 11), groups=[1, 11, 2, 7], material_index=1)
    ids = bytearray(native.raw)
    struct.pack_into('<H', ids, native.header()['offsets']['meshes'] + 0x26, 77)
    with pytest.raises(W.EnemyWriterError, match='mesh ids'):
        W.graft(mt_model.parse_mod(bytes(ids)), one_mesh(native, 11), groups=[1, 11, 2, 7], material_index=1)


def test_author_replaces_only_the_reviewed_indices_and_reports_an_unverified_candidate(donor):
    archive, target = enemy_arc()
    output, receipt = W.author(archive, donor, target)
    before, after = mt_arc.parse(archive), mt_arc.parse(output)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    assert changed == [0, 1, 2, 7, 8] == receipt['checks']['changed_entries']
    assert [e.name for e in after.entries] == [e.name for e in before.entries] and len(after.entries) == 10
    assert all(a.data == b.data and a.tag == b.tag for i, (a, b) in enumerate(zip(before.entries, after.entries))
               if i not in changed)                                    # both MRLs, the unrelated TEX, the LMT twin
    for index in changed:                                              # shipped framing: wrapped zlib 6, size tag
        raw = zlib.decompress(after.entries[index].data)
        assert after.entries[index].data[:2] == b'\x78\x9c' and zlib.compress(raw, 6) == after.entries[index].data
        assert after.entries[index].tag == 0x40000000 | len(raw)
    assert W.author(archive, donor, target)[0] == output              # the same inputs give the same bytes
    models = {name: mt_model.parse_mod(zlib.decompress(after.entries[i].data)) for name, i in (('body', 7), ('body_low', 8))}
    for name, model in models.items():
        records = model.meshes()
        carried = [r for r in records if r['level_of_detail'] == 0xFF]
        assert sorted(r['group_index'] for r in carried) == [1, 2, 7, 11] and len(records) == 12
        assert {r['material_index'] for r in carried} == {1}
        assert all(mtf_author.mesh_triangles(model, r['index']) == [] for r in records if r['level_of_detail'] != 0xFF)
        assert all(len(mtf_author.mesh_triangles(model, r['index'])) == 19 for r in carried)
        points = np.asarray(model.positions(carried[0]['index']))
        assert points[:, 1].min() == pytest.approx(0., abs=.02)       # soles on the ground under the native ankles
        assert receipt['models'][name]['donor_records'] == 4 and receipt['models'][name]['native_records'] == 8
    # the native skeletons are untouched, and each model is bound through its own bone indices
    for index, name in ((7, 'body'), (8, 'body_low')):
        old = mt_model.parse_mod(zlib.decompress(before.entries[index].data))
        assert models[name].bone_world() == old.bone_world()
    assert receipt['role_map']['bones']['body']['l_foot'] + 1 == receipt['role_map']['bones']['body_low']['l_foot']
    assert receipt['role_map']['bind_position']['head'] == [0., 165., 0.]
    assert receipt['fit']['cross_section_scale'] == pytest.approx(10. / 1.4) and not receipt['fit']['bind_joints_moved']
    assert receipt['option_groups']['choice'] == 'carry_in_every_group' and receipt['option_groups']['count'] == 4
    assert receipt['option_groups']['groups']['11'] == receipt['option_groups']['groups']['11'] | {
        'slot': 'head', 'native_records': {'body': 1, 'body_low': 1}}
    assert receipt['counts'] == receipt['counts'] | {'donor_triangles': 19, 'donor_vertices': 57,
                                                     'written_donor_triangles': 2 * 4 * 19, 'native_records_blanked': 16}
    assert [row['index'] for row in receipt['entries_replaced']] == changed
    assert receipt['written_sha256'] == hashlib.sha256(output).hexdigest()
    assert receipt['live_verified'] is False and receipt['writer_registered'] is False
    assert receipt['appearance']['mrl_entries_changed'] is False and receipt['appearance']['secondary_maps'] == 'neutral'
    # secondary maps: BC5 flat normal and BC4 zero mask in their native containers
    assert mtf_tex.linear_blocks(zlib.decompress(after.entries[2].data))[:16] == bytes((128, 128)) + bytes(6) + bytes((128, 128)) + bytes(6)
    assert set(mtf_tex.linear_blocks(zlib.decompress(after.entries[1].data))) == {0}


def test_native_secondary_maps_can_be_kept_and_a_second_set_can_follow_the_first(donor):
    archive, target = enemy_arc()
    kept, receipt = W.author(archive, donor, target, secondary='native')
    assert receipt['checks']['changed_entries'] == [0, 7, 8]
    first = W.EnemySet('first', target.models[:1], target.groups, target.albedo, target.normal, target.mask)
    second = W.EnemySet('second', target.models[1:], target.groups, target.albedo, target.normal, target.mask)
    step, _ = W.author(archive, donor, first)
    both, receipt = W.author(step, donor, second)
    assert receipt['checks']['changed_entries'] == [8]               # the textures were already written
    assert both == W.author(archive, donor, target)[0]


def test_author_refuses_anything_that_is_not_the_reviewed_entry(donor):
    archive, target = enemy_arc()
    swapped = W.EnemySet('x', ((MODEL + 'body', 4, 7), target.models[1]), target.groups, target.albedo, target.normal,
                         target.mask)                                 # the MRL index where the MOD is reviewed
    with pytest.raises(W.EnemyWriterError, match='MOD resource'):
        W.author(archive, donor, swapped)
    renamed = W.EnemySet('x', ((MODEL + 'body_low', 7, 4), target.models[1]), target.groups, target.albedo,
                         target.normal, target.mask)                  # right index, another name
    with pytest.raises(W.EnemyWriterError, match='not the reviewed'):
        W.author(archive, donor, renamed)
    fewer = W.EnemySet('x', target.models, GROUPS[:2], target.albedo, target.normal, target.mask)
    with pytest.raises(W.EnemyWriterError, match='reviewed list'):
        W.author(archive, donor, fewer)
    skin = W.EnemySet('x', target.models, target.groups, (3, MODEL + 'skin_BM'), target.normal, target.mask)
    with pytest.raises(W.EnemyWriterError, match='exactly one native material'):
        W.author(archive, donor, skin)                                # two materials sample that texture
    with pytest.raises(W.EnemyWriterError, match='fifteen'):
        W.author(archive, donor, target, source_roles={'hip': 'skl_root'})
    with pytest.raises(W.EnemyWriterError, match='secondary'):
        W.author(archive, donor, target, secondary='guess')


def test_verify_rejects_changes_outside_the_reviewed_scope_and_broken_format_rules(donor):
    archive, target = enemy_arc()
    output, _ = W.author(archive, donor, target)
    assert W.verify(archive, output, target)['untouched_entries_byte_identical'] == 5
    stray = mtf_author.replace_archive_model(output, 6, b'\x02\0\0\0changed')
    with pytest.raises(W.EnemyWriterError, match='outside the reviewed indices'):
        W.verify(archive, stray, target)
    arc = mt_arc.parse(output)
    arc.entries.append(arc.entries[6])
    with pytest.raises(W.EnemyWriterError, match='entry count'):
        W.verify(archive, mt_arc.build(arc), target)
    model = zlib.decompress(mt_arc.parse(output).entries[7].data)
    stale = bytearray(model)
    struct.pack_into('<I', stale, 0xA0, 3799)
    with pytest.raises(W.EnemyWriterError, match='0xA0'):
        W.verify(archive, mtf_author.replace_archive_model(output, 7, bytes(stale)), target)
    drawing = bytearray(model)
    offsets = mt_model.parse_mod(model).header()['offsets']
    struct.pack_into('<3H', drawing, offsets['index_buffer'], 0, 1, 2)       # native record 0 draws again
    with pytest.raises(W.EnemyWriterError, match='draw nothing'):
        W.verify(archive, mtf_author.replace_archive_model(output, 7, bytes(drawing)), target)
    raw_deflate = mt_arc.parse(output)
    raw_deflate.entries[7].data = raw_deflate.entries[7].data[2:-4]           # the wrapper the loader froze on
    with pytest.raises(W.EnemyWriterError, match='zlib framing'):
        W.verify(archive, mt_arc.build(raw_deflate), target)
    level9 = mt_arc.parse(output)
    level9.entries[7].data = zlib.compress(model, 9)
    with pytest.raises(W.EnemyWriterError, match='zlib framing'):
        W.verify(archive, mt_arc.build(level9), target)
    with pytest.raises(W.EnemyWriterError, match='not replaced'):
        W.verify(archive, archive, target)


def test_build_accepts_only_the_measured_donor_and_archive(tmp_path, monkeypatch):
    source = tmp_path / 'source.glb'
    source.write_bytes(b'another donor')
    with pytest.raises(W.EnemyWriterError, match='source revision'):
        W.build(b'archive', source)
    monkeypatch.setattr(W, 'SOURCE_SHA256', hashlib.sha256(source.read_bytes()).hexdigest())
    with pytest.raises(W.EnemyWriterError, match='original uEm10'):
        W.build(b'archive', source)
    monkeypatch.setattr(W, 'ARCHIVE_SHA256', hashlib.sha256(b'archive').hexdigest())
    with pytest.raises(W.EnemyWriterError, match='em1000 set first'):
        W.build(b'archive', source, sets=('em1001',))
    calls = []

    def author(archive, path, target, **options):
        calls.append((target.name, archive))
        return archive + target.name.encode(), {'written_sha256': target.name, 'written_bytes': 1}
    monkeypatch.setattr(W, 'author', author)
    output, receipt = W.build(b'archive', source, sets=('em1000', 'em1001'))
    assert calls == [('em1000', b'archive'), ('em1001', b'archiveem1000')] and output == b'archiveem1000em1001'
    assert receipt['replacement_scope']['complete'] is False and receipt['replacement_scope']['gameplay_verified'] is False
    assert receipt['target']['not_replaced'] == ['em2100', 'uEm11.arc'] and 'em1001' in receipt['additional_sets']
    assert W.build(b'archive', source)[1]['target']['not_replaced'][:3] == ['em1001', 'em1001_low', 'em1001_mid']


def test_preview_draws_the_written_donor_record(donor, tmp_path, monkeypatch):
    archive, target = enemy_arc()
    output, _ = W.author(archive, donor, target)
    monkeypatch.undo()                                  # the preview reads its own glTF through the real loader
    report = W.preview(output, tmp_path / 'preview.png', target=target, size=48)
    assert Image.open(tmp_path / 'preview.png').size == (144, 48)
    assert report['triangles'] == 19 and report['vertices'] == 57 and report['model'] == 'body'
    with pytest.raises(W.EnemyWriterError, match='no donor record'):
        W.preview(archive, tmp_path / 'native.png', target=target)


def test_posed_preview_skins_the_written_record_through_the_comparison_sampler(donor, tmp_path, monkeypatch):
    from tests.test_mtf_motion import translation_lmt
    archive, target = enemy_arc(translation_lmt())                   # animation id 1, the spine, slides sideways
    output, _ = W.author(archive, donor, target)
    monkeypatch.undo()
    report = W.posed_preview(archive, output, tmp_path / 'posed.png', motion_entry=9, clip=2, frames=[1, 11],
                             target=target, size=48)
    assert Image.open(tmp_path / 'posed.png').size == (4 * 48, 48)   # two frames, two views each
    assert report == report | {'evaluation_mode': 'sampled_fk', 'clip': 2, 'frames': [1., 11.], 'donor_copies': 4,
                               'skeleton_displacement_max_cm': 0., 'donor_copies_max_difference_cm': 0.}
    with pytest.raises(W.EnemyWriterError, match='motion resource'):
        W.posed_preview(archive, output, tmp_path / 'no.png', motion_entry=7, clip=2, frames=[1], target=target)


def test_cli_writes_the_overlay_tree_with_its_receipt_and_previews_beside_it(tmp_path, monkeypatch, capsys):
    import json
    (tmp_path / 'in.arc').write_bytes(b'original')
    (tmp_path / 'donor.glb').write_bytes(b'donor')
    seen = {}

    def build(archive, source, *, sets, secondary):
        seen.update(archive=archive, source=source.name, sets=sets, secondary=secondary)
        return b'candidate', {'written_sha256': 'abc', 'live_verified': False}
    monkeypatch.setattr(W, 'build', build)
    monkeypatch.setattr(W, 'preview', lambda archive, png: {'preview': str(png), 'triangles': 1})
    monkeypatch.setattr(W, 'posed_preview', lambda original, candidate, png, **pose: {'preview': str(png)} | pose | {
        'inputs': [original.decode(), candidate.decode()]})
    out = tmp_path / 'candidate'
    assert W.main(['--archive', str(tmp_path / 'in.arc'), '--source', str(tmp_path / 'donor.glb'), '--out', str(out),
                   '--pose', '259:3:0,30']) == 0
    assert seen == {'archive': b'original', 'source': 'donor.glb', 'sets': ('em1000',), 'secondary': 'neutral'}
    assert (out / 'romfs' / 'nativeNXx64' / 'ImgNX' / 'Archive' / 'uEm10.arc').read_bytes() == b'candidate'
    receipt = json.loads((out / 'receipt.json').read_text(encoding='utf-8'))
    assert receipt['output'] == {'path': 'romfs/' + W.ARCHIVE_PATH, 'sha256': 'abc', 'bytes': 9}
    assert receipt['preview'] == {'preview': 'preview.png', 'triangles': 1} and receipt['live_verified'] is False
    assert receipt['posed_preview'] == {'preview': 'preview-posed.png', 'motion_entry': 259, 'clip': 3,
                                        'frames': [0., 30.], 'inputs': ['original', 'candidate']}
    assert json.loads(capsys.readouterr().out)['sha256'] == 'abc'


REAL = (os.environ.get('GBOX_RE5_UEM10_ARC'), os.environ.get('GBOX_SM64DS_MARIO_GLB'))


@pytest.mark.skipif(not all(REAL), reason='set GBOX_RE5_UEM10_ARC and GBOX_SM64DS_MARIO_GLB to build the real candidate')
def test_the_measured_archive_builds_the_reviewed_candidate():
    """Opt-in: the owned 82 MB archive and the library GLB. Offline bytes only; nothing here is a live result."""
    archive = Path(REAL[0]).read_bytes()
    output, receipt = W.build(archive, Path(REAL[1]))
    assert receipt['checks']['changed_entries'] == [108, 109, 110, 234, 235, 236] and receipt['entries'] == 787
    assert {name: row['mesh_records'] for name, row in receipt['models'].items()} == {
        'em1000': 396, 'em1000_low': 398, 'em1000_mid': 402}
    assert receipt['role_map']['bones']['em1000'] == {
        'hip': 1, 'chest': 15, 'head': 81, 'r_thigh': 2, 'r_shin': 4, 'r_foot': 5, 'l_thigh': 7, 'l_shin': 9,
        'l_foot': 10, 'r_upper': 17, 'r_fore': 18, 'r_hand': 20, 'l_upper': 50, 'l_fore': 58, 'l_hand': 63}
    assert receipt['counts']['donor_triangles'] == 452 and receipt['option_groups']['count'] == 55
    assert receipt['live_verified'] is False and receipt['replacement_scope']['complete'] is False
