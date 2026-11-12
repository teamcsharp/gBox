"""The shared RE5 donor pool, on synthetic rigs only: no library model, game asset or image is read."""
import json

import numpy as np
import pytest

from gbox import re5_donor_pool as P

JOINTS = {'root': (0., 5., 0.), 'hip': (0., 6., 0.), 'chest': (0., 7., 0.), 'head': (0., 11., 0.)}
PARENT = {'hip': 'root', 'chest': 'hip', 'head': 'chest'}
for _side, _sign in (('l', 1.), ('r', -1.)):
    JOINTS |= {f'{_side}_upper': (2. * _sign, 10., 0.), f'{_side}_fore': (4. * _sign, 10., 0.),
               f'{_side}_hand': (6. * _sign, 10., 0.), f'{_side}_tip': (7. * _sign, 10., 0.),
               f'{_side}_thigh': (1.4 * _sign, 6., 0.), f'{_side}_shin': (1.4 * _sign, 3.4, 0.),
               f'{_side}_foot': (1.4 * _sign, 1.4, 0.), f'{_side}_toe': (1.4 * _sign, .2, 1.5)}
    PARENT |= {f'{_side}_upper': 'chest', f'{_side}_fore': f'{_side}_upper', f'{_side}_hand': f'{_side}_fore',
               f'{_side}_tip': f'{_side}_hand', f'{_side}_thigh': 'hip', f'{_side}_shin': f'{_side}_thigh',
               f'{_side}_foot': f'{_side}_shin', f'{_side}_toe': f'{_side}_foot'}
ROLES = {role: role for role in P.ROLES}


def rig(skin=None, joints=None, flip=False):
    """(gltf, world, vertices, triangles): one triangle on every skinned joint, soles on y 0, facing +Z."""
    joints = dict(joints or JOINTS)
    names = list(joints)
    nodes = [{'name': name, 'children': [names.index(c) for c, p in PARENT.items() if p == name and c in joints]}
             for name in names]
    world = []
    for name in names:
        matrix = np.eye(4)
        matrix[:3, 3] = joints[name]
        world.append(matrix)
    vertices, triangles = [], []

    def triangle(corners):
        order = (0, 2, 1) if flip else (0, 1, 2)
        triangles.append(tuple(len(vertices) + i for i in order))
        for point, name in corners:
            vertices.append({'position': point, 'normal': (0., 0., 1.), 'uv': (.25, .25),
                             'source_joints': (names.index(name),), 'source_weights': (1.,)})
    for name in (skin if skin is not None else P.ROLES):
        x, y, z = joints[name]
        triangle([((x, y, z), name), ((x + .3, y, z), name), ((x, y + .3, z), name)])
    for side, sign in (('l', 1.), ('r', -1.)):
        foot = f'{side}_foot'
        if skin is None or foot in skin:
            triangle([((1.1 * sign, 0., .2), foot), ((1.7 * sign, 0., .2), foot), ((1.4 * sign, .3, 1.4), foot)])
    return {'nodes': nodes, 'skins': [{'joints': list(range(len(names)))}], 'images': [{}]}, world, vertices, triangles


def test_a_complete_rig_is_measured():
    measured = P.rig_check(*rig(), ROLES)
    assert measured['role_joints'] == ROLES and measured['winding'] == 'ccw' and measured['facing'] == '+Z'
    assert measured['skin_weight_by_role']['l_foot'] == 6. and measured['skin_weight_by_role']['head'] == 3.
    assert measured['floor_y'] == 0. and measured['height'] == pytest.approx(11.3)
    assert measured['spine'] == {'hip_to_chest': 1., 'chest_to_head': 4.} and measured['torso'] == 'spine'
    # a torso that hangs on one joint at the waist is a usable rig; the writer maps it onto the native lower spine
    assert P.rig_check(*rig(joints=JOINTS | {'chest': (0., 6.05, 0.)}), ROLES)['torso'] == 'waist'
    assert measured['max_roles_per_vertex'] == 1 and measured['blended_vertex_share'] == 0.
    assert P.rig_check(*rig(flip=True), ROLES)['winding'] == 'cw'


@pytest.mark.parametrize('roles, reason', [
    ({k: v for k, v in ROLES.items() if k != 'l_hand'}, 'lacks l_hand'),
    (ROLES | {'tail': 'root'}, 'unknown roles tail'),
    (ROLES | {'head': 'skull'}, "names joint 'skull', which the model has 0 times"),
    (ROLES | {'head': 'chest'}, 'two roles name the same joint'),
    (ROLES | {'l_fore': 'l_hand', 'l_hand': 'l_fore'}, 'does not hang below'),
    ({k: v.replace('l_', 'x_').replace('r_', 'l_').replace('x_', 'r_') for k, v in ROLES.items()}, 'sides are swapped'),
])
def test_a_wrong_role_profile_is_refused_with_the_reason(roles, reason):
    with pytest.raises(ValueError, match='incomplete rig: .*' + reason):
        P.rig_check(*rig(), roles)


def test_an_incomplete_rig_is_refused_with_the_reason():
    with pytest.raises(ValueError, match="joint 'root' carries skin but neither it nor an ancestor"):
        P.rig_check(*rig(skin=P.ROLES + ('root',)), ROLES)
    with pytest.raises(ValueError, match='no vertex follows l_fore'):
        P.rig_check(*rig(skin=[r for r in P.ROLES if r != 'l_fore']), ROLES)
    with pytest.raises(ValueError, match='no vertex follows l_foot, r_foot'):
        P.rig_check(*rig(), ROLES | {'l_foot': 'l_toe', 'r_foot': 'r_toe'})
    with pytest.raises(ValueError, match='the head joint sits on the chest joint .* no length to span'):
        P.rig_check(*rig(joints=JOINTS | {'head': (0., 7.05, 0.)}), ROLES)
    backwards = {name: (x, y, -z) for name, (x, y, z) in JOINTS.items()}
    gltf, world, vertices, triangles = rig(joints=backwards)
    turned = [v | {'position': (v['position'][0], v['position'][1], -v['position'][2])} for v in vertices]
    with pytest.raises(ValueError, match='does not face \\+Z'):
        P.rig_check(gltf, world, turned, triangles, ROLES)
    gltf, world, vertices, triangles = rig()
    mixed = triangles[:8] + [(a, c, b) for a, b, c in triangles[8:]]
    with pytest.raises(ValueError, match='the winding is inconsistent'):
        P.rig_check(gltf, world, vertices, mixed, ROLES)
    with pytest.raises(ValueError, match='no skinned surface'):
        P.rig_check(gltf, world, [], [], ROLES)


def test_two_measured_repairs_move_a_profile_onto_the_joints_that_carry_the_skin():
    gltf, world, vertices, triangles = rig(skin=P.ROLES + ('root',))
    assert P._repaired(gltf, vertices, ROLES)[0]['hip'] == 'root'
    tips = ROLES | {'l_foot': 'l_toe', 'r_foot': 'r_toe'}
    repaired, note = P._repaired(*rig()[::2], tips)
    assert (repaired['l_foot'], repaired['r_foot']) == ('l_foot', 'r_foot') and 'raised from the tip l_toe' in note
    assert P.rig_check(*rig(), repaired)['skin_weight_by_role']['l_foot'] == 6.
    assert P._repaired(*rig()[::2], ROLES) is None                    # nothing to repair, nothing changed


def library(tmp_path, monkeypatch, entries):
    """Folders with metadata and a stand-in model file; the loaders are replaced at their seams."""
    rigs = {}
    for slug, (meta, parts) in entries.items():
        folder = tmp_path / slug
        folder.mkdir()
        if meta is not None:
            (folder / 'meta.json').write_text(json.dumps({'slug': slug, 'name': slug.title(), 'kind': 'character',
                                                          'model': 'model.glb'} | meta), encoding='utf-8')
        if parts is not None:
            (folder / 'model.glb').write_bytes(parts.pop('bytes', slug.encode()))
            rigs[slug] = parts
    monkeypatch.setattr(P.characters, '_load', lambda path: (
        rigs[path.parent.name]['rig'][0], None, None, rigs[path.parent.name]['rig'][1]))

    def mesh(path, atlas_size, strict_samplers=True):
        assert atlas_size == P.SURVEY_ATLAS and strict_samplers == 'in_range'
        part = rigs[path.parent.name]
        if 'surface_error' in part:
            raise P.mtf_materials.MaterialError(part['surface_error'])
        return part['rig'][2], part['rig'][3], None, {}
    monkeypatch.setattr(P.mtf_materials, 'source_mesh', mesh)

    def tree(path):
        found = rigs[path.parent.name].get('tree')
        if found is None:
            raise ValueError('no skeleton')
        return found
    monkeypatch.setattr(P.characters, 'tree_roles', tree)
    return tmp_path


SONIC = {'source': {'game_title': 'Sonic Adventure 2 (USA)', 'platform': 'dreamcast'}, 'extraction_tool': 'gbox.sa2_chars',
         'rig': {'roles': ROLES}}


def test_resolve_takes_the_metadata_profile_then_the_joint_tree_and_names_each_refusal(tmp_path, monkeypatch):
    bare = rig()
    bare[0].pop('images')
    unskinned = rig()
    unskinned[0]['skins'] = []
    root = library(tmp_path, monkeypatch, {
        'sonic': (SONIC, {'rig': rig()}),
        'tips': (SONIC | {'rig': {'roles': ROLES | {'l_foot': 'l_toe', 'r_foot': 'r_toe'}}}, {'rig': rig()}),
        'tree': ({'source': {'game_title': 'Soulcalibur II'}, 'rig': {'roles': {'hip': 'hip'}}}, {'rig': rig(), 'tree': ROLES}),
        'nometa': (None, {'rig': rig(), 'tree': ROLES}),
        'sprite': ({'kind': 'sprites', 'model': ''}, None),
        'gone': (SONIC, None),
        'statue': (SONIC, {'rig': unskinned}),
        'grey': (SONIC, {'rig': bare}),
        'clamped': (SONIC, {'rig': rig(), 'surface_error': 'a clamped or mirrored sampler is used outside the 0..1 UV range'}),
        'partial': ({'rig': {'roles': {'hip': 'hip', 'head': 'head'}}}, {'rig': rig()}),
        'onepiece': (SONIC, {'rig': rig(joints=JOINTS | {'head': (0., 7.05, 0.)})}),
        'big': (SONIC | {'size': 'large'}, {'rig': rig(), 'bytes': b'big'}),
    })
    donor, measured = P.resolve(root / 'sonic')
    assert (donor.slug, donor.game, donor.franchise, donor.platform) == ('sonic', 'Sonic Adventure 2', 'Sonic', 'dreamcast')
    assert donor.roles_from == 'library metadata' and donor.role_names() == ROLES and measured['triangles'] == 17
    assert donor.provenance == 'Sonic Adventure 2 (USA); gbox.sa2_chars' and (donor.size, donor.height_factor) == ('native', 1.)
    assert len(donor.sha256) == 64 and donor.model == 'model.glb'
    assert 'l_foot raised from the tip l_toe' in P.resolve(root / 'tips')[0].roles_from
    assert P.resolve(root / 'tree')[0].roles_from == 'joint-tree measurement'
    assert P.resolve(root / 'tree')[0].franchise == 'SoulCalibur'
    assert P.resolve(root / 'nometa')[0].game == 'unknown'
    assert (P.resolve(root / 'big')[0].size, P.resolve(root / 'big')[0].height_factor) == ('large', 1.15)
    for slug, category in (('sprite', 'no_model'), ('gone', 'model_unreadable'), ('statue', 'no_rig'),
                           ('grey', 'no_textures'), ('clamped', 'unsupported_surface'), ('partial', 'no_roles'),
                           ('onepiece', 'rig_refused')):
        with pytest.raises(P.DonorError) as refused:
            P.resolve(root / slug)
        assert refused.value.category == category and category in P.REASONS, slug
    monkeypatch.setattr(P, 'MAX_VERTICES', 10)
    with pytest.raises(P.DonorError, match='51 vertices') as refused:
        P.resolve(root / 'sonic')
    assert refused.value.category == 'too_large'


def test_survey_counts_usable_donors_per_game_and_refusals_per_reason(tmp_path, monkeypatch):
    mgs = {'source': {'game_title': 'Metal Gear Solid 2: Substance (USA)'}, 'rig': {'roles': ROLES}}
    root = library(tmp_path, monkeypatch, {
        'snake': (mgs, {'rig': rig(), 'bytes': b'snake'}),
        'snake_copy': (mgs | {'source': {'game_title': 'Metal Gear Solid 2 - Substance'}}, {'rig': rig(), 'bytes': b'snake'}),
        'sonic': (SONIC, {'rig': rig()}),
        'sprite': ({'kind': 'sprites', 'model': '', 'source': {'game_title': 'Marvel vs. Capcom 2'}}, None),
        'statue': (SONIC, {'rig': rig()[:1] + rig()[1:]}),
    })
    seen = []
    report = P.survey(root, progress=lambda done, total, name, row: seen.append((done, total, name)))
    summary = report['summary']
    assert report['library_entries'] == 5 and seen[-1][:2] == (5, 5)
    assert summary['usable'] == 3 and summary['refused'] == 2
    assert summary['refusals_by_reason'] == {'duplicate': 1, 'no_model': 1}
    assert summary['by_franchise']['Metal Gear'] == {
        'usable': 1, 'refused': 1, 'games': {'Metal Gear Solid 2: Substance': {'usable': 1, 'refused': 1}},
        'refusals': {'duplicate': 1}}
    assert summary['by_franchise']['Sonic']['usable'] == 2 and summary['by_franchise']['Marvel vs. Capcom']['refused'] == 1
    assert report['entries']['snake_copy']['reason'] == 'the same model bytes as snake'
    again = json.loads(json.dumps(report))
    donors = P.donors_of(again)
    assert sorted(d.slug for d in donors) == ['snake', 'sonic', 'statue'] and donors[0].role_names() == ROLES
    monkeypatch.setattr(P, 'resolve', lambda folder: pytest.fail('a known folder was resolved again'))
    assert P.survey(root, known=again['entries'])['summary'] == summary


def test_titles_franchises_and_explicit_sizes():
    assert P.game_of({'source': {'game_title': 'Metal Gear Solid - The Twin Snakes (USA) (Disc 2)'}}) == \
        'Metal Gear Solid: The Twin Snakes'
    assert P.game_of({'source': {'game_title': 'Soulcalibur II'}}) == P.game_of({'source': {'game_title': 'Soul Calibur II (USA)'}})
    assert P.game_of({}) == 'unknown'
    assert [P.franchise_of(g) for g in ('Dead Or Alive ++', 'Super Smash Bros. Melee', 'Super Mario 64 DS', 'Shenmue',
                                        'Phantasy Star Online Ver. 2', 'Some Other Game')] == [
        'Dead or Alive', 'Smash Bros.', 'Mario', 'Shenmue', 'Phantasy Star Online', 'Some Other Game']
    assert P.size_of({'size': 'Small'}) == ('small', .85) and P.size_of({'rig': {'size': 1.2}}) == ('factor 1.2', 1.2)
    assert P.size_of({'notes': 'a large boss', 'rig': {'scale': {'head': 2.}}}) == ('native', 1.)
    assert P.size_of({'size': 9}) == ('native', 1.)


def pool(counts):
    return [P.Donor(slug=f'{franchise.lower()}_{i}', name=f'{franchise} {i}', game=f'{franchise} Game', franchise=franchise,
                    platform='x', model='m.glb', sha256='0' * 64, roles=tuple(ROLES.items()), roles_from='test',
                    provenance='test') for franchise, count in counts.items() for i in range(count)]


def test_plan_is_seeded_never_repeats_a_donor_and_takes_franchises_in_turn():
    donors = pool({'Sonic': 4, 'Mario': 3, 'Wrestling': 40, 'Snake': 2})
    slots = ['a', 'b', 'c', 'd', 'e', 'f']
    first = P.plan(7, slots, donors)
    assert first == P.plan(7, slots, list(reversed(donors))) and list(first) == slots
    assert len(set(first.values())) == 6 and first != P.plan(8, slots, donors)
    by_slug = {d.slug: d.franchise for d in donors}
    spread = [by_slug[s] for s in first.values()]
    assert set(spread) == {'Sonic', 'Mario', 'Wrestling', 'Snake'} and max(spread.count(f) for f in set(spread)) == 2
    assert len({tuple(P.plan(seed, slots, donors).values()) for seed in range(12)}) > 6


def test_plan_puts_recent_donors_last_and_honours_filters():
    donors = pool({'Sonic': 4, 'Mario': 4})
    slots = ['a', 'b', 'c']
    one = P.plan('s1', slots, donors)
    two = P.plan('s2', slots, donors, history=[one])
    assert not set(one.values()) & set(two.values())
    three = P.plan('s3', slots, donors, history=[one, two])
    assert len(set(three.values()) - set(one.values()) - set(two.values())) == 2      # only two donors were left unused
    forgotten = P.plan('s4', slots, donors, history=[list(one.values()), two], avoid_last=1)
    assert not set(forgotten.values()) & set(two.values())
    only = P.plan(1, slots, donors, games=['mario'])
    assert all(slug.startswith('mario') for slug in only.values())
    assert set(P.plan(1, slots, donors, games=['Sonic Game']).values()) <= {f'sonic_{i}' for i in range(4)}
    without = P.plan(1, slots, donors, exclude={'mario_0', 'mario_1', 'sonic_0'})
    assert not set(without.values()) & {'mario_0', 'mario_1', 'sonic_0'}
    with pytest.raises(ValueError, match='cannot fill'):
        P.plan(1, list('abcde'), donors, games=['Mario'])
    with pytest.raises(ValueError, match='distinct slots'):
        P.plan(1, ['a', 'a'], donors)


def _wdonor(slug, franchise):
    return P.Donor(slug=slug, name=slug, game=franchise, franchise=franchise, platform='x', model='m.glb',
                   sha256='0' * 64, roles=(), roles_from='r', provenance='p')


def test_a_cast_weight_biases_the_draw_and_zero_removes_a_franchise():
    """The operator, 2026-11-12: sliders to choose which characters pop up more often (Sonic, Mario).

    Franchise is the axis the deal already rotates, so a weight is a repeat in its turn order. Measured, not assumed:
    even 0.33 each, Sonic at 5.0 -> ~0.67 Sonic, Sonic at 0.0 -> none at all.
    """
    donors = ([_wdonor(f's{i}', 'Sonic') for i in range(4)] + [_wdonor(f'm{i}', 'Mario') for i in range(4)]
              + [_wdonor(f'z{i}', 'Zelda') for i in range(4)])          # a third, so removing one still fills six
    slots = [f'slot{i}' for i in range(6)]

    def share(weights, prefix):
        got = [P.plan(seed, slots, donors, weights=weights).values() for seed in range(60)]
        return sum(1 for row in got for slug in row if slug.startswith(prefix)) / (60 * len(slots))

    even = share(None, 's')
    assert 0.25 < even < 0.42, even
    assert share({'Sonic': 5.0}, 's') > even + 0.15, 'a heavier franchise comes up more often'
    assert share({'Sonic': 0.0}, 's') == 0.0, 'weight 0 keeps it out entirely'
    assert abs(even - share({}, 's')) < 0.12, 'no weights deals as before'
