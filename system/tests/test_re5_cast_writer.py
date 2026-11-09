"""Generic RE5 player-slot writer, on synthetic player-shaped fixtures only: no game asset or donor file is read.

The fixture mirrors what was measured on the six Mercenaries archives: a body in option group 0 beside a head group, a
skeleton that carries gear, face and twist bones beside the fifteen role bones, MOD and MRL entries sharing a name, a
costume archive holding two models with the same basename, and the same animation ids at different bone indices.
"""
import hashlib
import json
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, mtf_mrl, mtf_tex, re5_cast_writer as W
from tests.test_re5_enemy_writer import FULL, ONE, PROXY, bone_block, enemy_mrl, pack, skeleton, tex

BASE, COSTUME = 'pawn\\pl\\pl00\\model\\', 'pawn\\pl\\pl10\\model\\'
MATERIALS = ('skin', 'sandal', 'cloth')
ROLES = {'hip': 'skl_root', 'chest': 'spin', 'head': 'head:root'}
for _s in 'lr':
    ROLES |= {f'{_s}_upper': f'arm_{_s}1', f'{_s}_fore': f'arm_{_s}2', f'{_s}_hand': f'wrist_{_s}1',
              f'{_s}_thigh': f'leg_{_s}1', f'{_s}_shin': f'leg_{_s}2', f'{_s}_foot': f'ankle_{_s}1'}


def player_skeleton(shuffled=False):
    """The role skeleton plus what a player model adds: gear on the chest and pelvis, a necklace, face and twist bones."""
    bones = skeleton()
    extra = [('gear_r', 116, 'chest', (-9., 148., -18.)), ('gear_r_tip', 117, 'gear_r', (-9., 146., -18.)),
             ('gear_l', 114, 'chest', (11., 155., -15.)), ('gear_l_tip', 115, 'gear_l', (11., 152., -15.)),
             ('necklace', 130, 'chest', (0., 144., 4.)), ('necklace_tip', 131, 'necklace', (0., 144., 7.)),
             ('holster', 110, 'pelvis', (-12., 101., -10.)), ('holster_tip', 111, 'holster', (-12., 99., -10.)),
             ('l_twist', 76, 'l_upper', (18., 150., 0.)), ('r_twist', 70, 'r_upper', (-18., 150., 0.)),
             ('brow', 56, 'head', (-3., 172., 7.)), ('hair', 126, 'head', (0., 185., 3.))]
    if shuffled:                            # a costume model stores the same bones in another order
        head = [b for b in bones if b[0] in ('neck', 'head')]
        rest = [b for b in bones if b[0] not in ('neck', 'head')]
        chest = next(i for i, b in enumerate(rest) if b[0] == 'chest')
        bones = rest[:chest + 1] + head + rest[chest + 1:]
    return bones + extra


def player_mod(bones, groups=(0, 1)):
    """A model with a body in option group 0 (a proxy, the four-weight template, a low-detail part) and a head group."""
    b = {name: i for i, (name, *_) in enumerate(bones)}
    quad = [(-4., 170., 0.), (4., 170., 0.), (-4., 178., 0.), (4., 178., 0.)]
    body = [(-15., 110., 5.), (15., 110., 5.), (-15., 150., 5.), (15., 150., 5.)]
    rows = [dict(group=1, material=0, lod=255, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['head'], points=quad),
            dict(group=0, material=1, lod=1, kind=0x1020, mode=132, fmt=PROXY, flags=25, bone=b['chest'], points=body),
            dict(group=0, material=1, lod=1, kind=0xFFFF, mode=4, fmt=FULL, flags=25, bone=b['chest'], points=body),
            dict(group=0, material=2, lod=252, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['pelvis'], points=body[:3])]
    ids = [3, 1, 2, 4]                               # a permutation of 1..count, not the table order
    records, vertices, words, envelopes = b'', b'', [], b''
    for number, row in enumerate(rows):
        stride = 28 if row['fmt'] == FULL else 20
        strip = list(range(len(row['points'])))
        record = bytearray(56)
        struct.pack_into('<HHI', record, 0, row['kind'], len(row['points']),
                         row['group'] | row['material'] << 12 | row['lod'] << 24)
        record[8:12] = bytes((row['flags'], 0, stride, row['mode']))
        struct.pack_into('<II', record, 0x0C, 0, len(vertices))
        struct.pack_into('>I', record, 0x14, row['fmt'])
        struct.pack_into('<III', record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into('<HHH', record, 0x26, ids[number], 0, len(row['points']) - 1)
        records += record
        vertices += pack(row['fmt'], row['points'], row['bone'])
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(row['bone'], row['points'])
    indices = struct.pack(f'<{len(words)}H', *words) + bytes((2 * len(words)) % 4)
    tail = struct.pack('<12f', 0, 90, 0, 120, -80, 0, -20, 0, 80, 190, 20, 0) + struct.pack('<5I', 500, 1000, 3, 0,
                                                                                         len(rows))
    group_block = b''.join(struct.pack('<I12x4f', group, 0, -10, 0, 58) for group in groups)
    material_block = b''.join(name.encode().ljust(128, b'\0') for name in MATERIALS)
    blocks = (bone_block(bones), group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0x28 + 56 + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack('<3H', len(bones), len(rows), len(MATERIALS))
    out += struct.pack('<3I2I2I', sum(len(r['points']) for r in rows), len(words), 9, len(vertices), 0, len(groups), 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    model = mt_model.parse_mod(out)
    assert model.split_valid() and model.header()['weight_bound_count'] == len(rows)
    return out


def mrl(folder):
    """The enemy fixture's MRL with its texture paths moved into `folder`."""
    raw = bytearray(enemy_mrl(MATERIALS))
    for i in range(4):
        slot = raw[40 + 88 * i + 24:40 + 88 * i + 88]
        path = folder.encode() + bytes(slot).split(b'\0', 1)[0].rsplit(b'\\', 1)[-1]
        raw[40 + 88 * i + 24:40 + 88 * i + 88] = path.ljust(64, b'\0')
    return bytes(raw)


def slot_archive(monkeypatch, costume=False):
    """(archive, slot): a base body, and for a costume archive the costume's own body under the same basename."""
    contents = [(BASE + 'sandal_BM', tex(0x30)), (BASE + 'sandal_MM', tex(0x19)), (BASE + 'sandal_NM', tex(0x1F)),
                (BASE + 'skin_BM', tex(0x30)), (BASE + 'body', mrl(BASE)), ('untouched', b'\x02\0\0\0preserved'),
                (BASE + 'body', player_mod(player_skeleton())), ('pawn\\pl\\pl00\\motion\\pl00wp00', b'LMT\0motion')]
    models = [W.SlotModel(BASE + 'body', 6, 4, 'sandal', (0, BASE + 'sandal_BM'), (2, BASE + 'sandal_NM'),
                          (1, BASE + 'sandal_MM'), 'costume body' if costume else 'body')]
    if costume:
        contents += [(COSTUME + 'sandal_BM', tex(0x30)), (COSTUME + 'sandal_MM', tex(0x19)),
                     (COSTUME + 'sandal_NM', tex(0x1F)), (COSTUME + 'skin_BM', tex(0x30)), (COSTUME + 'body', mrl(COSTUME)),
                     (COSTUME + 'body', player_mod(player_skeleton(shuffled=True)))]
        models = [W.SlotModel(COSTUME + 'body', 13, 12, 'sandal', (8, COSTUME + 'sandal_BM'), (10, COSTUME + 'sandal_NM'),
                              (9, COSTUME + 'sandal_MM'), 'costume body'),
                  W.SlotModel(BASE + 'body', 6, 4, 'sandal', (0, BASE + 'sandal_BM'), (2, BASE + 'sandal_NM'),
                              (1, BASE + 'sandal_MM'), 'base body')]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data)) for name, data in contents]
    archive = mt_arc.build(mt_arc.Arc(7, entries))
    slot = W.Slot('test', 'Test (Costume)' if costume else 'Test', 'uPlTest', hashlib.sha256(archive).hexdigest(),
                  len(entries), tuple(models), 'synthetic')
    signature = W.material_signature(mrl(BASE), 1)
    monkeypatch.setattr(W, 'STANDARD_STATE', signature['state'])
    monkeypatch.setattr(W, 'STANDARD_COMMANDS_SHA256', signature['commands_sha256'])
    monkeypatch.setattr(W, 'SLOTS', {'test': slot})
    return archive, slot


@pytest.fixture
def donor(tmp_path, monkeypatch):
    """A fifteen-joint donor through the real loaders' seams: skin on every joint, soles on y 0, a root above the hip."""
    joints = {'top': (0., 6., 0.), 'skl_root': (0., 6., 0.), 'spin': (0., 7., 0.), 'head:root': (0., 11., 0.)}
    for side, sign in (('l', 1.), ('r', -1.)):
        joints |= {f'arm_{side}1': (2. * sign, 10., 0.), f'arm_{side}2': (4. * sign, 10., 0.),
                   f'wrist_{side}1': (6. * sign, 10., 0.), f'leg_{side}1': (1.4 * sign, 6., 0.),
                   f'leg_{side}2': (1.4 * sign, 3.4, 0.), f'ankle_{side}1': (1.4 * sign, 1.4, 0.)}
    names = list(joints)
    parent = {'skl_root': 'top', 'spin': 'skl_root', 'head:root': 'spin'}
    for side in 'lr':
        parent |= {f'arm_{side}1': 'spin', f'arm_{side}2': f'arm_{side}1', f'wrist_{side}1': f'arm_{side}2',
                   f'leg_{side}1': 'skl_root', f'leg_{side}2': f'leg_{side}1', f'ankle_{side}1': f'leg_{side}2'}
    nodes = [{'name': name, 'children': [names.index(c) for c, p in parent.items() if p == name]} for name in names]
    world = []
    for name in names:
        matrix = np.eye(4)
        matrix[:3, 3] = joints[name]
        world.append(matrix)
    state = {'vertices': [], 'triangles': [], 'calls': []}

    def triangle(corners):
        state['triangles'].append(tuple(range(len(state['vertices']), len(state['vertices']) + 3)))
        for point, joint in corners:
            state['vertices'].append({'position': point, 'normal': (0., 0., 1.), 'uv': (.25, .25),
                                      'source_joints': (names.index(joint),), 'source_weights': (1.,)})
    for name, (x, y, z) in joints.items():
        if name != 'top':
            triangle([((x, y, z), name), ((x + .3, y, z), name), ((x, y + .3, z), name)])
    for side, sign in (('l', 1.), ('r', -1.)):
        ankle = f'ankle_{side}1'
        triangle([((1.1 * sign, 0., .2), ankle), ((1.7 * sign, 0., .2), ankle), ((1.4 * sign, .3, 1.4), ankle)])
    triangle([((0., 11., 0.), 'head:root'), ((.3, 11., 0.), 'head:root'), ((0., 14., 0.), 'head:root')])   # the head, last
    source = tmp_path / 'donor.glb'
    source.write_bytes(b'synthetic donor')
    gltf = {'nodes': nodes, 'skins': [{'joints': list(range(len(names)))}], 'images': [{}]}
    monkeypatch.setattr(W.characters, '_load', lambda _: (gltf, None, None, world))

    def mesh(_, atlas_size, **options):
        state['calls'].append((atlas_size, options))
        return ([dict(v) for v in state['vertices']], list(state['triangles']), Image.new('RGBA', atlas_size, 'red'),
                {'materials': 1, 'texture_scale': 1., 'face_normal_fallback_corners': 0})
    monkeypatch.setattr(W.mtf_materials, 'source_mesh', mesh)
    monkeypatch.setattr(W.mtf_tex, 'replace_image',
                        lambda data, image: mtf_tex.replace_blocks(data, bytes([7]) * 1024, 0))
    state.update(source=source, names=names, add=triangle)
    return state


def test_the_six_reviewed_slots_name_distinct_archives_models_and_entries():
    assert [slot.label for slot in W.SLOTS.values()] == [
        'Chris (BSAA)', 'Chris (Safari)', 'Chris (STARS)', 'Sheva (BSAA)', 'Sheva (Clubbin)', 'Sheva (Tribal)']
    assert len({slot.sha256 for slot in W.SLOTS.values()}) == len({slot.player_class for slot in W.SLOTS.values()}) == 6
    # the costume the archive holds was read from its own model: Sheva's Cos1 is the tribal outfit, Cos2 the club one
    assert (W.SLOTS['sheva_tribal'].player_class, W.SLOTS['sheva_clubbin'].player_class) == ('uPl01ShebaCos1', 'uPl01ShebaCos2')
    assert W.SLOTS['chris_bsaa'].archive == 'nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc'
    for slot in W.SLOTS.values():
        indices = [i for m in slot.models for i in (m.mod, m.mrl, m.albedo[0], m.normal[0], m.mask[0])]
        assert len(set(indices)) == len(indices) and len(slot.models) == (1 if slot.player_class.endswith('Normal') else 2)
        assert [m.drawn for m in slot.models] == (['body'] if len(slot.models) == 1 else ['costume body', 'base body'])
        assert all(m.albedo[1].endswith('_BM') and m.normal[1].endswith('_NM') and m.mask[1].endswith('_MM')
                   for m in slot.models)
    assert set(W.SEGMENTS) | set(W.SEGMENTS.values()) <= set(W.ROLES) and len(W.ROLES) == 15
    with pytest.raises(W.CastWriterError, match='unknown slot'):
        W.slot_for(b'not a reviewed archive')


@pytest.mark.parametrize('shuffled', [False, True])
def test_roles_are_measured_past_gear_face_and_twist_bones_and_agree_with_the_animation_ids(shuffled):
    bones = player_skeleton(shuffled)
    index = {name: i for i, (name, *_) in enumerate(bones)}
    model = mt_model.parse_mod(player_mod(bones))
    measured, extra = W.measure_roles(model)
    expected = {'hip': 'pelvis', 'chest': 'chest', 'head': 'head'} | {
        f'{s}_{part}': f'{s}_{part}' for s in 'lr' for part in ('upper', 'fore', 'hand', 'thigh', 'shin', 'foot')}
    assert measured == {role: index[bone] for role, bone in expected.items()}
    assert extra['facing'] == '+Z' and extra['left_side'] == '+X' and extra['neck'] == index['neck']
    roles, evidence = W.role_map(model)
    assert roles == measured == W.roles_by_animation_id(model) and evidence['bone_count'] == len(bones)
    assert evidence['skeleton']['spine'] == index['spine']
    assert evidence['bind_position']['head'] == [0., 165., 0.] and evidence['animation_ids']['hip'] == 15


def test_the_same_animation_ids_sit_at_other_bone_indices_in_a_costume_model():
    base = W.role_map(mt_model.parse_mod(player_mod(player_skeleton())))[0]
    costume = W.role_map(mt_model.parse_mod(player_mod(player_skeleton(shuffled=True))))[0]
    assert base['head'] != costume['head'] and base['l_hand'] != costume['l_hand'] and base['hip'] == costume['hip']


def test_role_map_refuses_a_skeleton_whose_ids_and_positions_disagree():
    bones = player_skeleton()
    swapped = [(name, {11: 6, 6: 11}.get(animation, animation), parent, point) for name, animation, parent, point in bones]
    with pytest.raises(W.CastWriterError, match='disagree'):
        W.role_map(mt_model.parse_mod(player_mod(swapped)))
    one_arm = [bone for bone in bones if not bone[0].startswith('l_') or bone[0] in ('l_thigh', 'l_shin', 'l_foot', 'l_toe')]
    with pytest.raises(W.CastWriterError):
        W.measure_roles(mt_model.parse_mod(player_mod(one_arm)))


def test_author_replaces_the_body_with_one_group_zero_record_and_touches_nothing_else(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch)
    output, receipt = W.author(archive, donor['source'], ROLES)
    before, after = mt_arc.parse(archive), mt_arc.parse(output)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if (a.data, a.tag) != (b.data, b.tag)]
    assert changed == [0, 1, 2, 6] and [e.name for e in after.entries] == [e.name for e in before.entries]
    assert all(zlib.compress(zlib.decompress(after.entries[i].data), 6) == after.entries[i].data for i in changed)
    native_raw, raw = (zlib.decompress(arc.entries[6].data) for arc in (before, after))
    native, model = mt_model.parse_mod(native_raw), mt_model.parse_mod(raw)
    old, new = native.header()['offsets'], model.header()['offsets']
    record = model.meshes()[0]
    assert model.header()['mesh_count'] == 1 and (record['group_index'], record['material_index'],
                                                   record['level_of_detail'], record['mesh_id']) == (0, 1, 0xFF, 1)
    assert (record['mesh_type'], record['vertex_format'], record['vertex_flags']) == (0xFFFF, FULL, 33)
    assert raw[new['bones']:new['groups']] == native_raw[old['bones']:old['groups']]            # the skeleton is native
    assert raw[new['materials']:new['meshes']] == native_raw[old['materials']:old['meshes']]
    assert raw[new['groups'] + 32:new['materials']] == native_raw[old['groups'] + 32:old['materials']]   # head group kept
    assert raw[new['groups']:new['groups'] + 16] == native_raw[old['groups']:old['groups'] + 16]
    assert raw[new['groups'] + 16:new['groups'] + 32] != native_raw[old['groups'] + 16:old['groups'] + 32]
    assert struct.unpack_from('<I', raw, 0xA0)[0] == record['vertex_group_count'] == 15
    roles = W.role_map(native)[0]
    assert {row['bone'] for row in model.weight_bounds()} == set(roles.values())
    assert len(mtf_author.mesh_triangles(model, 0)) == len(donor['triangles']) == receipt['counts']['triangles'] == 18
    assert mtf_tex.parse(zlib.decompress(after.entries[0].data)) == mtf_tex.parse(zlib.decompress(before.entries[0].data))
    assert receipt['checks']['changed_entries'] == changed and receipt['checks']['untouched_entries_byte_identical'] == 4
    assert receipt['live_verified'] is False and receipt['gameplay_verified'] is False
    assert receipt['fit']['bind_joints_moved'] is False and receipt['fit']['native_motion_edited'] is False
    assert receipt['role_map']['bones'][f'6:{BASE}body'] == roles and receipt['role_map']['source_roles'] == ROLES
    assert donor['calls'][0] == ((32, 32), {'strict_samplers': 'in_range'})
    assert W.verify(archive, output, slot)['models'][f'6:{BASE}body']['envelope_count'] == 15


def test_the_donor_stands_at_the_native_height_with_its_soles_on_the_floor(monkeypatch, donor):
    archive, _ = slot_archive(monkeypatch)
    output, receipt = W.author(archive, donor['source'], ROLES)
    fit = receipt['fit']
    assert fit['scale_source'] == 'native height, soles on the floor'
    assert fit['top'] == pytest.approx(190., abs=.05) and fit['floor'] == pytest.approx(0., abs=.05)
    assert fit['scale']['native_top'] == 190. and fit['scale']['height_factor'] == 1.
    body, feet = fit['scale']['body_scale'], fit['scale']['feet_vertical_scale']
    assert body == pytest.approx((190. - 165.) / 3., rel=1e-6)           # the head's 3 units reach from y 165 to y 190
    assert feet['l_foot'] == pytest.approx(10. / 1.4, rel=1e-6) == pytest.approx(feet['r_foot'])    # ankle 10 over sole 1.4
    points = np.asarray(mt_model.parse_mod(zlib.decompress(mt_arc.parse(output).entries[6].data)).positions(0))
    assert points[:, 1].max() == pytest.approx(190., abs=.05) and points[:, 1].min() == pytest.approx(0., abs=.05)
    taller = W.author(archive, donor['source'], ROLES, height_factor=1.1)[1]['fit']
    assert taller['top'] == pytest.approx(209., abs=.05) and taller['floor'] == pytest.approx(0., abs=.05)
    uniform = W.author(archive, donor['source'], ROLES, scale=5.)[1]['fit']
    assert uniform['scale_source'] == 'caller' and uniform['top'] == pytest.approx(180., abs=.05)
    with pytest.raises(W.CastWriterError, match='height factor'):
        W.author(archive, donor['source'], ROLES, height_factor=3.)
    donor['triangles'].pop()                         # without its head the stub above the head joint is 0.3 units:
    del donor['vertices'][-3:]                       # the rule would blow the body up to five times the native size
    with pytest.raises(W.CastWriterError, match='far from the native size'):
        W.author(archive, donor['source'], ROLES)


def test_a_torso_on_one_waist_joint_follows_the_native_lower_spine(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch)
    spin = donor['names'].index('spin')
    world = W.characters._load(donor['source'])[3]
    world[spin][1, 3] = 6.05                         # the torso joint now sits beside the hip joint, at the waist
    for vertex in donor['vertices']:
        if vertex['source_joints'] == (spin,):
            vertex['position'] = (vertex['position'][0], vertex['position'][1] - .95, vertex['position'][2])
    output, receipt = W.author(archive, donor['source'], ROLES)
    native = mt_model.parse_mod(zlib.decompress(mt_arc.parse(archive).entries[6].data))
    roles, evidence = W.role_map(native)
    spine = evidence['skeleton']['spine']
    row = receipt['models'][f'6:{BASE}body']
    assert receipt['donor_rig']['torso'] == 'waist' and 'lower spine' in row['torso']
    assert row['roles']['chest'] == spine != roles['chest'] and 'hip' not in receipt['fit']['segments']
    model = mt_model.parse_mod(zlib.decompress(mt_arc.parse(output).entries[6].data))
    bones = {entry['bone'] for entry in model.weight_bounds()}
    assert spine in bones and roles['chest'] not in bones
    assert receipt['fit']['top'] == pytest.approx(190., abs=.05) and receipt['fit']['floor'] == pytest.approx(0., abs=.05)
    assert W.verify(archive, output, slot)['models'][f'6:{BASE}body']['envelope_count'] == 15


def test_a_costume_archive_gets_the_donor_in_both_bodies_by_explicit_entry(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch, costume=True)
    output, receipt = W.author(archive, donor['source'], ROLES)
    before, after = mt_arc.parse(archive), mt_arc.parse(output)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    assert changed == [0, 1, 2, 6, 8, 9, 10, 13] and receipt['counts']['models_written'] == 2
    bones = receipt['role_map']['bones']
    assert bones[f'13:{COSTUME}body']['head'] != bones[f'6:{BASE}body']['head']         # each model's own measured map
    for index in (6, 13):
        model = mt_model.parse_mod(zlib.decompress(after.entries[index].data))
        assert model.header()['mesh_count'] == 1 and model.meshes()[0]['mesh_id'] == 1
    assert W.verify(archive, output, slot)['changed_entries'] == changed
    assert [row['drawn'] for row in receipt['models'].values()] == ['costume body', 'base body']


def test_an_unknown_slot_or_an_incomplete_rig_is_refused_with_the_reason(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch)
    with pytest.raises(W.CastWriterError, match='unknown slot'):
        W.author(archive + b'\0', donor['source'], ROLES)
    with pytest.raises(W.CastWriterError, match='incomplete rig: the role profile lacks head'):
        W.author(archive, donor['source'], {k: v for k, v in ROLES.items() if k != 'head'})
    with pytest.raises(W.CastWriterError, match="incomplete rig: l_hand names joint 'glove'"):
        W.author(archive, donor['source'], ROLES | {'l_hand': 'glove'})
    donor['add']([((0., 6., 0.), 'top'), ((.3, 6., 0.), 'top'), ((0., 6.3, 0.), 'top')])
    with pytest.raises(W.CastWriterError, match="joint 'top' carries skin but neither it nor an ancestor"):
        W.author(archive, donor['source'], ROLES)
    assert W.author(archive, donor['source'], ROLES | {'hip': 'top'})[1]['counts']['triangles'] == 19
    wrong = W.Slot(slot.key, slot.label, slot.player_class, slot.sha256, slot.entries,
                   (W.SlotModel(BASE + 'body', 6, 4, 'sandal', (3, BASE + 'skin_BM'), (2, BASE + 'sandal_NM'),
                                (1, BASE + 'sandal_MM'), 'body'),), 'synthetic')
    with pytest.raises(W.CastWriterError, match='does not bind the reviewed albedo, normal and mask'):
        W.author(archive, donor['source'], ROLES | {'hip': 'top'}, slot=wrong)
    plain = W.Slot(slot.key, slot.label, slot.player_class, slot.sha256, slot.entries,
                   (W.SlotModel(BASE + 'body', 6, 4, 'skin', (3, BASE + 'skin_BM'), (2, BASE + 'sandal_NM'),
                                (1, BASE + 'sandal_MM'), 'body'),), 'synthetic')
    with pytest.raises(W.CastWriterError, match="'skin' is not the measured standard material"):
        W.author(archive, donor['source'], ROLES | {'hip': 'top'}, slot=plain)
    moved = W.Slot(slot.key, slot.label, slot.player_class, slot.sha256, slot.entries,
                   (W.SlotModel(BASE + 'body', 5, 4, 'sandal', (0, BASE + 'sandal_BM'), (2, BASE + 'sandal_NM'),
                                (1, BASE + 'sandal_MM'), 'body'),), 'synthetic')
    with pytest.raises(W.CastWriterError, match='entry 5 is not the reviewed'):
        W.author(archive, donor['source'], ROLES | {'hip': 'top'}, slot=moved)
    monkeypatch.setattr(W, 'STANDARD_COMMANDS_SHA256', '0' * 64)
    with pytest.raises(W.CastWriterError, match='not the measured standard material'):
        W.author(archive, donor['source'], ROLES | {'hip': 'top'})


def test_verify_refuses_a_written_archive_that_breaks_a_measured_rule(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch)
    output, _ = W.author(archive, donor['source'], ROLES)
    parsed = mt_arc.parse(output)
    raw = zlib.decompress(parsed.entries[6].data)
    offsets = mt_model.parse_mod(raw).header()['offsets']

    def with_model(data):
        return mtf_author.replace_archive_model(output, 6, bytes(data))
    assert W.verify(archive, output, slot)['entry_count'] == 8
    with pytest.raises(W.CastWriterError, match='outside the reviewed indices'):
        W.verify(archive, mtf_author.replace_archive_model(output, 5, b'\x02\0\0\0changed'), slot)
    with pytest.raises(W.CastWriterError, match='a reviewed model was not replaced'):
        W.verify(archive, archive, slot)
    stale = bytearray(raw)
    struct.pack_into('<I', stale, 0xA0, 3799)
    with pytest.raises(W.CastWriterError, match='count at 0xA0'):
        W.verify(archive, with_model(stale), slot)
    numbered = bytearray(raw)
    struct.pack_into('<H', numbered, offsets['meshes'] + 0x26, 2)
    with pytest.raises(W.CastWriterError, match='mesh id 1'):
        W.verify(archive, with_model(numbered), slot)
    grouped = bytearray(raw)
    struct.pack_into('<I', grouped, offsets['meshes'] + 4, 1 | 1 << 12 | 0xFF << 24)
    with pytest.raises(W.CastWriterError, match='option group 0'):
        W.verify(archive, with_model(grouped), slot)
    shrunk = bytearray(raw)
    struct.pack_into('<f', shrunk, offsets['groups'] + 28, 1.)
    with pytest.raises(W.CastWriterError, match='sphere of option group 0'):
        W.verify(archive, with_model(shrunk), slot)
    boned = bytearray(raw)
    boned[offsets['bones']] ^= 1
    with pytest.raises(W.CastWriterError, match='skeleton is native'):
        W.verify(archive, with_model(boned), slot)
    deflated = zlib.compress(raw, 6)[2:-4]
    with pytest.raises(W.CastWriterError, match='shipped zlib framing'):
        W.verify(archive, mt_arc.replace_at(output, 6, deflated, tag=parsed.entries[6].tag), slot)


def pool_donor(donor, slug='hero', **changes):
    fields = dict(slug=slug, name=slug.title(), game='Test Game', franchise='Test', platform='test', model='donor.glb',
                  sha256=hashlib.sha256(donor['source'].read_bytes()).hexdigest(), roles=tuple(ROLES.items()),
                  roles_from='test', provenance='Test Game; test tool')
    return W.Donor(**(fields | changes))


def test_build_pins_the_donor_bytes_and_names_the_donor_by_its_own_provenance(monkeypatch, donor):
    archive, slot = slot_archive(monkeypatch)
    output, receipt = W.build(archive, donor['source'], pool_donor(donor))
    assert receipt['donor'] == 'hero' and receipt['source']['provenance'] == 'Test Game; test tool'
    assert receipt['replacement_scope']['complete'] is False and receipt['replacement_scope']['gameplay_verified'] is False
    assert receipt['target']['roster_label'] == 'Test' and receipt['written_sha256'] == hashlib.sha256(output).hexdigest()
    assert receipt['writer_registered'] is False and receipt['acceptance'].startswith('experimental')
    tall = W.build(archive, donor['source'], pool_donor(donor, size='large', height_factor=1.1))[1]
    assert tall['fit']['top'] == pytest.approx(209., abs=.05) and tall['source']['size'] == 'large'
    with pytest.raises(W.CastWriterError, match='needs the exact donor.glb it was resolved from'):
        W.build(archive, donor['source'], pool_donor(donor, sha256='0' * 64))


def test_a_cast_needs_reviewed_slots_and_a_different_donor_in_each(monkeypatch, donor, tmp_path):
    slot_archive(monkeypatch)
    with pytest.raises(W.CastWriterError, match='unknown slots'):
        W.cast(tmp_path, tmp_path, {'jill': 'hero'}, tmp_path / 'out')
    monkeypatch.setattr(W, 'SLOTS', {'a': W.SLOTS['test'], 'b': W.SLOTS['test']})
    with pytest.raises(W.CastWriterError, match='its own donor'):
        W.cast(tmp_path, tmp_path, {'a': 'hero', 'b': 'hero'}, tmp_path / 'out')
    with pytest.raises(W.CastWriterError, match='unknown donor'):
        W.cast(tmp_path, tmp_path, {'a': '../hero'}, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_a_cast_checks_every_fit_before_it_builds_and_writes_the_overlay_with_its_receipt(monkeypatch, donor, tmp_path):
    archive, slot = slot_archive(monkeypatch)
    romfs, library = tmp_path / 'romfs', tmp_path / 'library'
    (romfs / W.ARCHIVE_DIR).mkdir(parents=True)
    (romfs / slot.archive).write_bytes(archive)
    for slug in ('hero', 'rival'):
        (library / slug).mkdir(parents=True)
        (library / slug / 'donor.glb').write_bytes(donor['source'].read_bytes() + slug.encode())
        (library / slug / 'meta.json').write_text(json.dumps({
            'slug': slug, 'name': slug.title(), 'kind': 'character', 'model': 'donor.glb',
            'source': {'game_title': 'Test Game (USA)', 'platform': 'test'}, 'rig': {'roles': ROLES}}), encoding='utf-8')
    monkeypatch.setattr(W, '_preview', lambda written, original, slot, png=None: (
        [Image.new('RGB', (8, 8))], {'model': slot.models[0].name}))
    scales = W.fits(archive, library / 'hero' / 'donor.glb', ROLES)
    receipt = W.cast(romfs, library, {'test': 'hero'}, tmp_path / 'out')
    written = (tmp_path / 'out' / 'romfs' / slot.archive).read_bytes()
    row = receipt['slots']['test']
    assert receipt['assignment'] == {'test': 'hero'} and row['written_sha256'] == hashlib.sha256(written).hexdigest()
    assert row['output'] == {'path': 'romfs/' + slot.archive, 'sha256': row['written_sha256'], 'bytes': len(written)}
    assert row['source']['game'] == 'Test Game' and row['source']['roles_from'] == 'library metadata'
    assert receipt['live_verified'] is False and receipt['replacement_scope']['complete'] is False
    assert scales[f'6:{BASE}body']['body_scale'] == row['fit']['scale']['body_scale']
    assert W.verify(archive, written, slot)['entry_count'] == 8
    assert json.loads((tmp_path / 'out' / 'receipt.json').read_text(encoding='utf-8'))['assignment'] == {'test': 'hero'}
    assert (tmp_path / 'out' / 'contact-sheet.png').is_file()
    # two slots, the second donor does not fit: the refusal names it and nothing is built or written
    monkeypatch.setattr(W, 'SLOTS', {'a': slot, 'b': slot})
    real = W.fits
    monkeypatch.setattr(W, 'fits', lambda archive, source, roles, **options: real(archive, source, roles, **options)
                        if source.parent.name == 'hero' else (_ for _ in ()).throw(W.CastWriterError('no height to solve')))
    monkeypatch.setattr(W, 'build', lambda *a, **k: pytest.fail('a slot was built before every fit was checked'))
    with pytest.raises(W.CastWriterError, match='b <- rival: no height to solve'):
        W.cast(romfs, library, {'a': 'hero', 'b': 'rival'}, tmp_path / 'second')
    assert not (tmp_path / 'second').exists()


def test_a_pool_overlay_is_dealt_again_from_the_same_seed_without_a_donor_a_slot_refused(monkeypatch, donor, tmp_path):
    donors = [pool_donor(donor, slug) for slug in ('ada', 'bob', 'cy', 'dee')]
    calls = []

    def fake_cast(romfs, library, assignment, out, *, plan=None):
        calls.append(dict(assignment))
        if 'bob' in assignment.values():
            slot = next(key for key, slug in assignment.items() if slug == 'bob')
            raise W.CastWriterError(f'{slot} <- bob: the donor surface does not fit the 32x32 atlas of body')
        return {'assignment': assignment, 'plan': plan}
    monkeypatch.setattr(W, 'cast', fake_cast)
    seed = next(s for s in range(50) if 'bob' in W.re5_donor_pool.plan(s, ['x', 'y'], donors).values())
    result = W.pool_cast(tmp_path, tmp_path, donors, seed, tmp_path / 'out', slots=['x', 'y'])
    assert len(calls) == 2 and 'bob' in calls[0].values() and 'bob' not in result['assignment'].values()
    assert list(result['plan']['set_aside']) == ['bob'] and result['plan']['seed'] == seed
    assert result['assignment'] == W.re5_donor_pool.plan(seed, ['x', 'y'], donors, exclude={'bob'})
    monkeypatch.setattr(W, 'cast', lambda *a, **k: (_ for _ in ()).throw(W.CastWriterError('unknown slots [x]')))
    with pytest.raises(W.CastWriterError, match='unknown slots'):
        W.pool_cast(tmp_path, tmp_path, donors, seed, tmp_path / 'out', slots=['x', 'y'])


def test_the_preview_shades_by_vertex_normals_and_writes_one_sheet(tmp_path):
    points = [(-60., 20., 0.), (60., 20., 0.), (0., 200., 0.)]
    atlas = np.zeros((4, 4, 4), np.uint8)
    atlas[...] = (200, 100, 50, 255)
    lit = W.render(points, [(0., 0., 1.)] * 3, [(.5, .5)] * 3, [(0, 1, 2)], atlas, size=(92, 100))
    away = W.render(points, [(0., 0., -1.)] * 3, [(.5, .5)] * 3, [(0, 1, 2)], atlas, size=(92, 100))
    centre = (46, 60)
    assert lit.size == (92, 100) and lit.getpixel(centre)[0] > away.getpixel(centre)[0] > 40
    assert lit.getpixel((2, 2)) == away.getpixel((2, 2))                 # background outside the triangle
    smooth = W._smooth_normals(points + points, [(0., 0., 1.)] * 6, points + points, [(0, 1, 2), (3, 4, 5)])
    assert np.allclose(smooth, (0., 0., 1.))
    W.contact_sheet([('first\nrow', [lit, away]), ('second', [away, lit])], tmp_path / 'sheet.png', title='t',
                    columns=['a', 'b'])
    assert Image.open(tmp_path / 'sheet.png').size == (190 + 2 * 92, 44 + 2 * 100)
    with pytest.raises(W.CastWriterError):
        W.contact_sheet([], tmp_path / 'none.png')
