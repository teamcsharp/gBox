"""Any library donor on any reviewed enemy archive: donor metadata, rig checks, fits and the second Majini class.

Synthetic fixtures only (the Majini-shaped archive and donor of `test_re5_enemy_writer`); no game asset is read.
"""
import hashlib
import json
import os
import zlib

import numpy as np
import pytest

from gbox import mt_arc, mt_model, re5_enemy_writer as W
from tests.test_re5_enemy_writer import donor, enemy_arc, enemy_mod, skeleton  # noqa: F401  (donor: fixture)

ROLES = dict(W.SOURCE_ROLES)


def library_entry(folder, slug='toon', roles=None, model=b'synthetic donor', model_name='model.glb', **meta):
    entry = folder / slug
    entry.mkdir(parents=True)
    (entry / 'model.glb').write_bytes(model)
    (entry / 'meta.json').write_text(json.dumps({
        'slug': slug, 'name': slug.title(), 'model': model_name,
        'source': {'game_title': 'Synthetic Game', 'platform': 'test', 'files': ['a.bin']},
        'extraction_tool': 'tests', 'rig': {'roles': ROLES if roles is None else roles}} | meta), encoding='utf-8')
    return entry


def test_reviewed_em1100_table_and_the_archive_registry():
    ids = W.EM1100.group_ids()
    assert sorted(ids) == [1, 2, 3, 5, 6, 8, 9, 15, 16, 18] and 0 not in ids
    assert {slot: {g % 10 for g in groups} for slot, groups in W.EM1100.groups} == {
        'head': {1}, 'arm_skin': {2}, 'leg_skin': {3}, 'shirt': {5}, 'skirt': {6}, 'head_cloth': {8}, 'sandals': {9}}
    assert [(name.rsplit('\\', 1)[-1], mod, mrl) for name, mod, mrl in W.EM1100.models] == [('em1100', 89, 69)]
    assert (W.EM1100.albedo[0], W.EM1100.normal[0], W.EM1100.mask[0]) == (45, 47, 46)
    assert W.EM1100.albedo[1].endswith('gof01_08_BM') and W.SETS['em1100'] is W.EM1100
    ten, eleven = W.ARCHIVES['uEm10'], W.ARCHIVES['uEm11']
    assert ten.sha256 == W.ARCHIVE_SHA256 and eleven.sha256.startswith('a33ae046') and eleven.path.endswith('uEm11.arc')
    assert [t.name for t in ten.targets()] == ['em1000'] and [t.name for t in eleven.targets()] == ['em1100']
    assert [t.name for t in ten.targets(('em1000', 'em1001'))] == ['em1000', 'em1001']
    for wrong in (('em1001', 'em1000'), ('em1100',), (), ('em1000', 'em1000')):
        with pytest.raises(W.EnemyWriterError, match='reviewed sets'):
            ten.targets(wrong)
    # the model that is measured but not built is named with its reasons, not silently skipped
    assert 'em1101' in W.UNBUILT_MODELS['uEm11'] and 'em1101' in eleven.not_replaced


def majini_women_skeleton():
    """The em1100 shapes: an origin bone above the body root (both carry animation id 0), a childless helper stacked
    on the wrist beside the hand, and under each thigh a helper chain as deep as the leg."""
    bones = [('ground', 0, None, (0, 0, 0))]
    for name, animation, parent, point in skeleton():
        bones.append((name, animation, parent if parent is not None else 'ground', point))
        if name.endswith('_thigh'):
            side, sign = name[0], (1 if name[0] == 'l' else -1)
            bones += [(f'{side}_skirt1', 92, name, (11 * sign, 85, 5)), (f'{side}_skirt2', 93, f'{side}_skirt1', (11 * sign, 70, 6)),
                      (f'{side}_skirt3', 94, f'{side}_skirt2', (11 * sign, 60, 7))]
        if name.endswith('_hand'):
            side, sign = name[0], (1 if name[0] == 'l' else -1)
            bones += [(f'{side}_finger', 40, name, (78 * sign, 150, 0)), (f'{side}_twist', 191, f'{side}_wrist', (70 * sign, 150, 0))]
    seen, out = {}, []
    for name, animation, parent, point in bones:                      # helper ids must not repeat a role id
        if animation in (40, 92, 93, 94, 191):
            seen[animation] = seen.get(animation, 0) + 1
            animation = animation + 100 * (seen[animation] - 1) if seen[animation] > 1 else animation
            animation = animation % 250
        out.append((name, animation, parent, point))
    return out


def test_roles_measure_through_a_ground_bone_stacked_helpers_and_helper_chains():
    bones = majini_women_skeleton()
    index = {name: i for i, (name, *_) in enumerate(bones)}
    model = mt_model.parse_mod(enemy_mod(bones))
    measured, extra = W.measure_roles(model)
    assert extra['ground_bones'] == [index['ground']] and extra['root'] == index['root']
    assert measured['l_hand'] == index['l_hand'] and measured['r_hand'] == index['r_hand']      # not the wrist
    assert measured['l_shin'] == index['l_shin'] and measured['r_shin'] == index['r_shin']      # not the skirt chain
    roles, evidence = W.role_map(model)
    assert roles == measured == W.roles_by_animation_id(model) and evidence['bone_count'] == len(bones)
    # a second leg that reaches the floor is still ambiguous: the tie-break is anatomy, not a guess
    twin = [(n, a, p, (x, y - 58, z) if n.endswith(('_skirt2', '_skirt3')) else (x, y, z)) for n, a, p, (x, y, z) in bones]
    with pytest.raises(W.EnemyWriterError):
        W.role_map(mt_model.parse_mod(enemy_mod(twin)))


def test_load_donor_reads_library_metadata_and_names_what_is_missing(tmp_path):
    entry = library_entry(tmp_path)
    loaded = W.load_donor(entry)
    assert (loaded.slug, loaded.name, loaded.model.name) == ('toon', 'Toon', 'model.glb')
    assert loaded.roles == ROLES and loaded.sha256 == hashlib.sha256(b'synthetic donor').hexdigest()
    assert loaded.provenance == {'game': 'Synthetic Game', 'platform': 'test', 'files': ['a.bin'],
                                 'extraction_tool': 'tests', 'licence': None}
    assert W.load_donor(entry, sha256=loaded.sha256).sha256 == loaded.sha256
    with pytest.raises(W.EnemyWriterError, match='not the reviewed model revision'):
        W.load_donor(entry, sha256='0' * 64)
    partial = {role: joint for role, joint in ROLES.items() if role not in ('l_hand', 'r_foot')} | {'neck': 'face_1'}
    with pytest.raises(W.EnemyWriterError, match=r'incomplete rig.*l_hand, r_foot$'):
        W.load_donor(library_entry(tmp_path, 'stub', partial))
    with pytest.raises(W.EnemyWriterError, match=r'incomplete rig.*l_fore, l_upper share a joint'):
        W.load_donor(library_entry(tmp_path, 'fused', ROLES | {'l_fore': ROLES['l_upper']}))
    with pytest.raises(W.EnemyWriterError, match='incomplete rig'):
        W.load_donor(library_entry(tmp_path, 'unrigged', {}))
    with pytest.raises(W.EnemyWriterError, match='no model file'):
        W.load_donor(library_entry(tmp_path, 'escape', model_name='../toon/model.glb'))
    with pytest.raises(W.EnemyWriterError, match='readable meta.json'):
        W.load_donor(tmp_path / 'absent')


def body():
    """Joint positions and vertices of a small upright donor: left on +X, toes to +Z, arms out."""
    joints = {'hip': (0., 6., 0.), 'chest': (0., 7., 0.), 'head': (0., 11., 0.)}
    for side, sign in (('l', 1.), ('r', -1.)):
        joints |= {f'{side}_upper': (2. * sign, 10., 0.), f'{side}_fore': (4. * sign, 10., 0.),
                   f'{side}_hand': (6. * sign, 10., 0.), f'{side}_thigh': (1.4 * sign, 6., 0.),
                   f'{side}_shin': (1.4 * sign, 3.4, 0.), f'{side}_foot': (1.4 * sign, 1.4, 0.)}
    vertices, owners = [], []
    for role, (x, y, z) in joints.items():
        vertices.append({'position': (x, y, z)})
        owners.append({role})
    for side, sign in (('l', 1.), ('r', -1.)):
        vertices += [{'position': (1.4 * sign, 0., 1.2)}, {'position': (1.4 * sign, 0., -.2)}]
        owners += [{f'{side}_foot'}, {f'{side}_foot'}]
    vertices.append({'position': (0., 14., 0.)})                      # the top of the head
    owners.append({'head'})
    return joints, vertices, owners


def test_check_rig_trusts_metadata_for_names_and_not_for_anatomy():
    joints, vertices, owners = body()
    report = W.check_rig(vertices, owners, joints, 'toon')
    assert report == report | {'left_side': '+X', 'facing': '+Z', 'roles_without_vertices': []}
    hanging = joints | {'l_fore': (2., 8., 0.), 'l_hand': (2., 6.2, 0.), 'r_fore': (-2., 8., 0.), 'r_hand': (-2., 6.2, 0.)}
    assert W.check_rig(vertices, owners, hanging, 'toon')['facing'] == '+Z'       # arms at the sides are a pose
    crossed = joints | {'l_thigh': joints['r_thigh'], 'r_thigh': joints['l_thigh']}
    with pytest.raises(W.EnemyWriterError, match='toon has an incomplete rig: l_thigh and r_thigh are not on the sides'):
        W.check_rig(vertices, owners, crossed, 'toon')
    backwards = [{'position': (x, y, -z)} for x, y, z in (v['position'] for v in vertices)]
    with pytest.raises(W.EnemyWriterError, match='mirrored rig'):
        W.check_rig(backwards, owners, joints, 'toon')
    turned = {role: (-x, y, -z) for role, (x, y, z) in joints.items()}
    spun = [{'position': (-x, y, -z)} for x, y, z in (v['position'] for v in vertices)]
    with pytest.raises(W.EnemyWriterError, match='faces -Z'):
        W.check_rig(spun, owners, turned, 'toon')
    footless = [owner - {'l_foot', 'r_foot'} or {'hip'} for owner in owners]
    with pytest.raises(W.EnemyWriterError, match='no vertex is carried by a foot'):
        W.check_rig(vertices, footless, joints, 'toon')
    knee = joints | {'l_shin': (1.4, 7., 0.)}
    with pytest.raises(W.EnemyWriterError, match='the l leg does not descend'):
        W.check_rig(vertices, owners, knee, 'toon')
    flat = joints | {'r_fore': joints['r_upper']}
    with pytest.raises(W.EnemyWriterError, match='a r limb segment has no length'):
        W.check_rig(vertices, owners, flat, 'toon')


NATIVE = {'hip': (0., 114., 0.), 'chest': (0., 132., 0.), 'head': (0., 165., 0.),
          'l_upper': (17., 150., 0.), 'r_upper': (-17., 150., 0.), 'l_foot': (9., 14., 0.), 'r_foot': (-9., 14., 0.)}


def test_fit_scales_keep_the_first_fit_uniform_and_bring_a_donor_to_the_native_height():
    joints, vertices, owners = body()
    limbs, scales, offsets, report = W.fit_scales(W.PROPORTIONAL, vertices, owners, joints, NATIVE, 186.)
    assert limbs == pytest.approx(10.) and scales == {} and offsets == {}          # soles on the ground, one scale
    assert report['limbs_source'] == 'measured ground contact' and report['head'] == report['torso'] == limbs
    limbs, scales, offsets, report = W.fit_scales(W.NATIVE_HEIGHT, vertices, owners, joints, NATIVE, 186.)
    assert limbs == pytest.approx(10.)
    assert scales['hip'] == scales['chest'] == pytest.approx(34. / 4.)             # shoulders land on the native ones
    assert scales['l_hand'] == scales['r_hand'] == pytest.approx(8.5)              # never above the torso scale
    # head: standing on the joint it could be 21 / 3 = 7; sunk to the shoulder line (150) it is 36 / 3 = 12 over the
    # whole head, capped at the body scale 10 - so it ends below the native top and is moved down to start at 150
    assert report['head'] == pytest.approx(10.) and 'head' not in scales and 'kept at the body scale' in report['head_rule']
    assert offsets['head'] == pytest.approx((0., 186. - (165. + 10. * 3.), 0.))
    tall = vertices + [{'position': (0., 21., 0.)}]                                # a hat: 10 above the joint
    limbs, scales, offsets, report = W.fit_scales(W.NATIVE_HEIGHT, tall, owners + [{'head'}], joints, NATIVE, 186.)
    assert scales['head'] == pytest.approx(36. / 10.) and 'spanning down' in report['head_rule']
    assert 165. + offsets['head'][1] + scales['head'] * 10. == pytest.approx(186.)  # the top is the native top
    assert 165. + offsets['head'][1] + scales['head'] * 0. == pytest.approx(150.)   # the base is the shoulder line
    low = [dict(v) for v in tall] + [{'position': (0., -20., 0.)}]                  # hair to the ground: the joint wins
    _, scales, offsets, report = W.fit_scales(W.Fit('x', limbs=10., head='native_top'), low, owners + [{'head'}] * 2,
                                              joints, NATIVE, 186.)
    assert scales['head'] == pytest.approx(21. / 10.) and offsets == {} and 'standing on the native head joint' in report['head_rule']
    big = W.Fit('big', torso='shoulders', head='native_top', height=1.25)
    assert W.fit_scales(big, tall, owners + [{'head'}], joints, NATIVE, 186.)[3]['head'] == pytest.approx((232.5 - 150.) / 10.)
    explicit = W.Fit('x', limbs=4., torso=5., head=6., hands=7.)
    limbs, scales, offsets, _ = W.fit_scales(explicit, vertices, owners, joints, NATIVE, 186.)
    assert (limbs, scales['hip'], scales['head'], scales['l_hand'], offsets) == (4., 5., 6., 7., {})
    for bad in (W.Fit('x', limbs=0.), W.Fit('x', head=float('nan')), W.Fit('x', torso='wide'), W.Fit('x', head='tall'),
                W.Fit('x', hands='small')):
        with pytest.raises(W.EnemyWriterError):
            W.fit_scales(bad, vertices, owners, joints, NATIVE, 186.)
    with pytest.raises(W.EnemyWriterError, match='does not rise above its joint'):
        W.fit_scales(W.NATIVE_HEIGHT, vertices[:-1], owners[:-1], joints | {'head': (0., 30., 0.)}, NATIVE, 186.)


def test_author_fits_a_donor_to_the_native_height_and_reports_the_scale(donor):
    archive, target = enemy_arc()
    plain, first = W.author(archive, donor, target)
    output, receipt = W.author(archive, donor, target, fit=W.NATIVE_HEIGHT, who='toon')
    fit = receipt['fit']
    assert fit['name'] == 'native_height' and first['fit']['name'] == 'proportional' and first['fit']['role_scales'] == {}
    assert fit['scales']['limbs'] == pytest.approx(10. / 1.4) == first['fit']['cross_section_scale']
    assert fit['scales']['torso'] == pytest.approx(36. / 4.) and fit['role_scales']['hip'] == fit['role_scales']['chest']
    assert fit['scales']['hands'] == pytest.approx(10. / 1.4)                       # the torso is wider: no cap
    assert set(fit['rules']) >= {'torso_rule', 'hands_rule', 'head_rule', 'native_top'}
    model = mt_model.parse_mod(zlib.decompress(mt_arc.parse(output).entries[7].data))
    carried = next(r for r in model.meshes() if r['level_of_detail'] == 0xFF)
    points = np.asarray(model.positions(carried['index']))
    native_top = mt_model.parse_mod(zlib.decompress(mt_arc.parse(archive).entries[7].data)).bounds()['max']['y']
    assert points[:, 1].min() == pytest.approx(0., abs=.02)                         # soles still on the ground
    assert points[:, 1].max() <= native_top + .02 and fit['rules']['native_top'] == pytest.approx(native_top)
    assert output != plain and receipt['donor_rig']['joints_outside_the_roles'] == []
    assert receipt['live_verified'] is False
    with pytest.raises(W.EnemyWriterError, match='inside the fit'):
        W.author(archive, donor, target, fit=W.NATIVE_HEIGHT, scale=3.)


def test_a_joint_above_the_hips_is_carried_by_the_hips_and_reported(donor, monkeypatch):
    archive, target = enemy_arc()
    gltf, _, _, world = W.characters._load(donor)
    nodes = gltf['nodes'] + [{'name': 'all_root', 'children': [0]}]                 # a root above skl_root, with skin
    matrix = np.eye(4)
    matrix[:3, 3] = (0., 5.8, 0.)
    vertices, triangles, image, report = W.mtf_materials.source_mesh(donor, atlas_size=(32, 32))
    base = len(vertices)
    vertices += [{'position': p, 'normal': (0., 0., 1.), 'uv': (.25, .25), 'source_joints': (len(nodes) - 1,),
                  'source_weights': (1.,)} for p in ((.3, 5.8, .2), (0., 6.1, .2), (-.3, 5.8, .2))]
    triangles += [(base, base + 1, base + 2)]
    monkeypatch.setattr(W.characters, '_load', lambda _: ({'nodes': nodes}, None, None, world + [matrix]))
    monkeypatch.setattr(W.mtf_materials, 'source_mesh', lambda _, atlas_size: (
        [dict(v) for v in vertices], list(triangles), image.resize(atlas_size), report))
    output, receipt = W.author(archive, donor, target, who='toon')
    assert receipt['donor_rig']['joints_outside_the_roles'] == ['all_root'] and receipt['donor_rig']['carried_by'] == 'hip'
    assert receipt['counts']['donor_triangles'] == 20


@pytest.fixture
def registry(monkeypatch):
    """The synthetic archive registered as a reviewed class, the way uEm10 and uEm11 are."""
    archive, target = enemy_arc()
    monkeypatch.setitem(W.SETS, 'body', target)
    enemy = W.EnemyArchive('uSyn', 'nativeNXx64/ImgNX/Archive/uSyn.arc', hashlib.sha256(archive).hexdigest(),
                           ('body',), ('body',), (9, 2, (1., 11.)), ('other',))
    monkeypatch.setitem(W.ARCHIVES, 'uSyn', enemy)
    return archive, target, enemy


def test_build_donor_puts_any_library_donor_on_a_reviewed_archive(donor, registry, tmp_path):
    archive, target, enemy = registry
    entry = library_entry(tmp_path / 'library', model=donor.read_bytes())
    toon = W.load_donor(entry)
    output, receipt = W.build_donor(archive, toon, enemy)
    assert output == W.author(archive, toon.model, target, source_roles=toon.roles, fit=W.NATIVE_HEIGHT)[0]
    assert receipt['source'] == {'slug': 'toon', 'name': 'Toon', 'model': 'model.glb', 'sha256': toon.sha256,
                                 'provenance': toon.provenance}
    assert receipt['target'] == {'archive': enemy.path, 'sha256': enemy.sha256, 'class': 'uSyn',
                                 'models': ['body', 'body_low'], 'not_replaced': ['other'], 'unbuilt': {}}
    assert receipt['replacement_scope']['complete'] is False and receipt['live_verified'] is False
    assert receipt['fit']['name'] == 'native_height'
    assert W.build_donor(archive, toon, enemy, fit=W.PROPORTIONAL)[0] == W.author(archive, donor, target)[0]
    # only the high model: the other one stays byte for byte native (the bisect build)
    high, narrow = W.build_donor(archive, toon, enemy, models=('body',))
    before, after = mt_arc.parse(archive), mt_arc.parse(high)
    assert [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data] == [0, 1, 2, 7]
    assert narrow['target']['models'] == ['body'] and narrow['target']['not_replaced'] == ['body_low', 'other']
    with pytest.raises(W.EnemyWriterError, match='no reviewed models'):
        W.build_donor(archive, toon, enemy, models=('body_mid',))
    with pytest.raises(W.EnemyWriterError, match='exact measured original'):
        W.build_donor(archive + b'x', toon, enemy)
    with pytest.raises(W.EnemyWriterError, match='reviewed sets'):
        W.build_donor(archive, toon, enemy, sets=('em1000',))
    toon.model.write_bytes(b'edited after loading')
    with pytest.raises(W.EnemyWriterError, match='changed on disk'):
        W.build_donor(archive, toon, enemy)


def test_a_donor_the_importer_cannot_fit_is_refused_by_name(donor, registry, monkeypatch):
    archive, target, enemy = registry

    def refuse(*args, **kwargs):
        raise ValueError('retarget produces more than four native influences; none are silently discarded')
    monkeypatch.setattr(W.re5_mesh_import, 'build_archive', refuse)
    with pytest.raises(W.EnemyWriterError, match='toon cannot be fitted on body: retarget produces more than four'):
        W.author(archive, donor, target, who='toon')


REAL = (os.environ.get('GBOX_RE5_UEM11_ARC'), os.environ.get('GBOX_RE5_ENEMY_DONOR'))


@pytest.mark.skipif(not all(REAL), reason='set GBOX_RE5_UEM11_ARC and GBOX_RE5_ENEMY_DONOR (a library entry folder)')
def test_the_measured_uem11_archive_builds_a_library_donor():
    """Opt-in: the owned uEm11.arc and one library entry. Offline bytes only; nothing here is a live result."""
    from pathlib import Path
    archive = Path(REAL[0]).read_bytes()
    output, receipt = W.build_donor(archive, W.load_donor(Path(REAL[1])), W.ARCHIVES['uEm11'])
    assert receipt['checks']['changed_entries'] == [45, 46, 47, 89] and receipt['entries'] == 397
    assert receipt['models']['em1100'] == receipt['models']['em1100'] | {'mesh_records': 74, 'native_records': 64,
                                                                        'donor_records': 10, 'bone_count': 85}
    assert receipt['role_map']['bones']['em1100'] == {
        'hip': 2, 'chest': 16, 'head': 78, 'r_thigh': 5, 'r_shin': 6, 'r_foot': 7, 'l_thigh': 10, 'l_shin': 12,
        'l_foot': 13, 'l_upper': 18, 'l_fore': 22, 'l_hand': 25, 'r_upper': 48, 'r_fore': 52, 'r_hand': 56}
    assert receipt['models']['em1100']['skeleton']['ground_bones'] == [0] and receipt['option_groups']['count'] == 10
    assert receipt['target']['not_replaced'][:1] == ['em1101'] and receipt['live_verified'] is False
    assert W.build_donor(archive, W.load_donor(Path(REAL[1])), W.ARCHIVES['uEm11'])[0] == output
