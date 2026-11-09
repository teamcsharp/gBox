"""Enemy casts: seeded pools, the library seam, and the overlay tree with its receipt. Synthetic fixtures only."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from gbox import re5_enemy_cast as C, re5_enemy_writer as W
from tests.test_mtf_motion import translation_lmt
from tests.test_re5_enemy_mix import mix_arc
from tests.test_re5_enemy_writer import donor, enemy_arc  # noqa: F401  (donor: fixture)

POOL = {'mario': 'Mario', 'luigi': 'Mario', 'yoshi': 'Mario', 'wario': 'Mario', 'peach': 'Mario', 'toad': 'Mario',
        'sonic': 'Sonic', 'tails': 'Sonic', 'shadow': 'Sonic', 'snake': 'Metal Gear', 'ryo': 'Shenmue',
        'link': 'Zelda', 'ivy': 'SoulCalibur', 'taki': 'SoulCalibur'}


def test_plan_is_seeded_never_repeats_a_donor_and_mixes_franchises():
    slots = {'uEm10': 6, 'uEm11': 2}
    first = C.plan(7, slots, POOL)
    assert first == C.plan(7, slots, dict(reversed(list(POOL.items()))))          # a pure function of its arguments
    dealt = [slug for slugs in first.values() for slug in slugs]
    assert {enemy: len(slugs) for enemy, slugs in first.items()} == slots and len(set(dealt)) == 8
    for seed in range(40):
        picks = [slug for slugs in C.plan(seed, slots, POOL).values() for slug in slugs]
        assert len(set(picks)) == 8 and set(picks) <= set(POOL)
        by_franchise = {}
        for slug in picks:
            by_franchise[POOL[slug]] = by_franchise.get(POOL[slug], 0) + 1
        assert max(by_franchise.values()) <= 2 and len(by_franchise) >= 4        # a quarter of the overlay at most
    assert len({json.dumps(C.plan(seed, slots, POOL), sort_keys=True) for seed in range(12)}) >= 10   # seeds differ
    # six Mario entries do not crowd out the single-character franchises: over many seeds each is dealt
    seen = {slug for seed in range(60) for slugs in C.plan(seed, slots, POOL).values() for slug in slugs}
    assert seen == set(POOL)
    # a pool of one franchise still deals (the cap gives way when nothing else can serve)
    assert sorted(C.plan(1, {'uEm10': 3}, {'a': 'x', 'b': 'x', 'c': 'x'})['uEm10']) == ['a', 'b', 'c']
    with pytest.raises(C.CastError, match='9 different donors were asked for and the pool holds 3'):
        C.plan(1, {'uEm10': 9}, {'a': 'x', 'b': 'x', 'c': 'y'})
    for bad in ({}, {'uEm10': 0}):
        with pytest.raises(C.CastError, match='at least one donor'):
            C.plan(1, bad, POOL)


def library(folder, slug, model, roles=None, game='Synthetic Game'):
    entry = Path(folder) / slug
    entry.mkdir(parents=True)
    (entry / 'model.glb').write_bytes(model)
    (entry / 'meta.json').write_text(json.dumps({
        'slug': slug, 'name': slug.title(), 'model': 'model.glb', 'source': {'game_title': game, 'platform': 'test'},
        'rig': {'roles': dict(W.SOURCE_ROLES) if roles is None else roles}}), encoding='utf-8')
    return entry


def test_find_donor_takes_the_first_library_and_holds_a_reviewed_slug_to_its_revision(tmp_path, monkeypatch):
    library(tmp_path / 'one', 'toon', b'first')
    library(tmp_path / 'two', 'toon', b'second')
    library(tmp_path / 'two', 'other', b'other', game='Another Game')
    found = C.find_donor('toon', [tmp_path / 'one', tmp_path / 'two'])
    assert found.sha256 == hashlib.sha256(b'first').hexdigest() and C.franchise(found) == 'Synthetic Game'
    assert C.franchise(C.find_donor('other', [tmp_path / 'one', tmp_path / 'two'])) == 'Another Game'
    monkeypatch.setitem(C.DONORS, 'toon', hashlib.sha256(b'second').hexdigest())
    with pytest.raises(W.EnemyWriterError, match='not the reviewed model revision'):
        C.find_donor('toon', [tmp_path / 'one'])
    assert C.find_donor('toon', [tmp_path / 'two']).model.read_bytes() == b'second'
    for bad in ('absent', '../one/toon', ''):
        with pytest.raises(C.CastError):
            C.find_donor(bad, [tmp_path / 'one'])
    assert C.DONORS['sm64ds_mario'] == W.SOURCE_SHA256                       # the proven donor stays pinned
    assert all(enemy in W.ARCHIVES and fit in W.FITS for rows in C.CASTS.values() for enemy, _, fit in rows)
    assert all(len({slug for _, slug, _ in rows}) == len(rows) for rows in C.CASTS.values())


def test_parse_assignment_reads_one_donor_or_a_mix(tmp_path):
    for slug in ('alpha', 'beta'):
        library(tmp_path, slug, slug.encode())
    one = C.parse_assignment('uEm10=alpha', [tmp_path])
    assert (one.enemy, [d.slug for d in one.donors], one.fits, one.mix, one.models) == (
        'uEm10', ['alpha'], (W.NATIVE_HEIGHT,), False, None)
    big = C.parse_assignment('uEm11=alpha@proportional', [tmp_path], {'uEm11': ('em1100',)})
    assert big.fits == (W.PROPORTIONAL,) and big.models == ('em1100',)
    mix = C.parse_assignment('uEm10=alpha+beta@proportional', [tmp_path])
    assert [d.slug for d in mix.donors] == ['alpha', 'beta'] and mix.mix and mix.fits == (W.NATIVE_HEIGHT, W.PROPORTIONAL)
    for bad in ('uEm99=alpha', 'alpha', 'uEm10=', 'uEm10=alpha@huge', 'uEm10=gamma'):
        with pytest.raises(C.CastError):
            C.parse_assignment(bad, [tmp_path])


def test_survey_says_which_entries_can_be_enemy_donors_and_why_not(donor, tmp_path, monkeypatch):
    library(tmp_path, 'whole', donor.read_bytes())
    library(tmp_path, 'stub', b'x', roles={role: joint for role, joint in W.SOURCE_ROLES.items() if role != 'head'})
    library(tmp_path, 'renamed', b'y', roles=dict(W.SOURCE_ROLES) | {'l_hand': 'no_such_joint'})
    # the fixture donor is loose triangles: fitted on the Majini joints it is far from a whole figure
    loose = {row['slug']: row for row in C.survey([tmp_path], ['whole'])}['whole']
    assert not loose['usable'] and 'does not fit the Majini skeleton well: nothing of it is drawn between' in loose['reason']
    assert set(loose['scales']) == {'limbs', 'torso', 'head', 'hands'}
    monkeypatch.setattr(W, 'vertical_holes', lambda points, triangles, low, high: [])
    rows = {row['slug']: row for row in C.survey([tmp_path])}
    assert rows['whole'] == rows['whole'] | {'usable': True, 'franchise': 'Synthetic Game', 'vertices': 57,
                                             'triangles': 19, 'roles_without_vertices': []}
    assert not rows['stub']['usable'] and rows['stub']['reason'].endswith('names no joint for head')
    assert not rows['renamed']['usable'] and "l_hand ('no_such_joint': 0 joints)" in rows['renamed']['reason']
    assert [row['slug'] for row in C.survey([tmp_path], ['whole', 'absent'])] == ['whole', 'absent']
    # with an original archive the survey also builds the donor once and keeps the writer's own verdict
    archive, target = enemy_arc()
    monkeypatch.setitem(W.SETS, 'body', target)
    monkeypatch.setitem(W.ARCHIVES, 'uOne', W.EnemyArchive('uOne', 'nativeNXx64/ImgNX/Archive/uOne.arc',
                                                           hashlib.sha256(archive).hexdigest(), ('body',), ('body',),
                                                           (9, 2, (1.,)), ()))
    assert C.survey([tmp_path], ['whole'], trial=(archive, 'uOne'))[0] == rows['whole'] | {'trial': 'built on body'}

    def collapse(*args, **kwargs):
        raise ValueError('retarget produced an undefined surface normal')
    monkeypatch.setattr(W.re5_mesh_import, 'build_archive', collapse)
    tried = C.survey([tmp_path], ['whole'], trial=(archive, 'uOne'))[0]
    assert not tried['usable'] and tried['reason'] == ('whole cannot be fitted on body: retarget produced an undefined '
                                                       'surface normal')


@pytest.fixture
def classes(monkeypatch):
    """Two synthetic classes registered the way uEm10 and uEm11 are: one with a posed clip, one with a mix table."""
    plain, plain_target = enemy_arc(translation_lmt())
    mixed, mixed_target, mix = mix_arc()
    monkeypatch.setitem(W.SETS, 'body', plain_target)
    monkeypatch.setitem(W.SETS, 'mixbody', W.EnemySet('mixbody', *list(vars(mixed_target).values())[1:]))
    monkeypatch.setitem(W.ARCHIVES, 'uOne', W.EnemyArchive(
        'uOne', 'nativeNXx64/ImgNX/Archive/uOne.arc', hashlib.sha256(plain).hexdigest(), ('body',), ('body',),
        (9, 2, (1., 11.)), ('other',)))
    monkeypatch.setitem(W.ARCHIVES, 'uTwo', W.EnemyArchive(
        'uTwo', 'nativeNXx64/ImgNX/Archive/uTwo.arc', hashlib.sha256(mixed).hexdigest(), ('mixbody',), ('mixbody',),
        (9, 2, (1.,)), ()))
    monkeypatch.setitem(W.MIXES, 'uTwo', W.MixTable(mix.name, 'mixbody', mix.montage, mix.category, mix.slot,
                                                    mix.carriers))
    monkeypatch.setitem(C.FIRST_BOOT_RISKS, 'uOne', ['never loaded'])
    return {'uOne': plain, 'uTwo': mixed}


def donors(tmp_path, source, *slugs):
    return [W.load_donor(library(tmp_path / 'library', slug, source.read_bytes() + slug.encode(), game=f'Game of {slug}'))
            for slug in slugs]


@pytest.fixture
def real_load():
    """The glTF loader before the `donor` fixture replaces it (ask for this fixture first)."""
    return W.characters._load


def test_build_cast_writes_the_overlay_tree_with_a_receipt_and_previews(real_load, donor, classes, tmp_path,
                                                                        monkeypatch):
    alpha, beta, gamma = donors(tmp_path, donor, 'alpha', 'beta', 'gamma')
    seen = []
    real_preview, real_posed = W.preview, W.posed_preview

    def preview(archive, png, **options):                       # the pictures are drawn through the real loader
        seen.append(('rest', Path(png).name, options.get('carrier')))
        with monkeypatch.context() as scope:
            scope.setattr(W.characters, '_load', real_load)
            return real_preview(archive, png, **options | {'size': 48})

    def posed(original, candidate, png, **options):
        seen.append(('posed', Path(png).name, options['clip'], options['sampled'] is not None))
        with monkeypatch.context() as scope:
            scope.setattr(W.characters, '_load', real_load)
            return real_posed(original, candidate, png, **options | {'size': 48})
    out = tmp_path / 'assets' / 'enemy-test-v1'
    plain = [C.Assignment('uOne', (alpha,), (W.NATIVE_HEIGHT,))]
    monkeypatch.setattr(W, 'preview', preview)
    monkeypatch.setattr(W, 'posed_preview', posed)
    receipt = C.build_cast('enemy-test-v1', plain, classes, out)
    written = out / 'romfs' / 'nativeNXx64' / 'ImgNX' / 'Archive' / 'uOne.arc'
    row = receipt['archives']['uOne']
    assert hashlib.sha256(written.read_bytes()).hexdigest() == row['output_sha256'] and row['output_bytes'] == written.stat().st_size
    assert written.read_bytes() == W.build_donor(classes['uOne'], alpha, W.ARCHIVES['uOne'])[0]
    assert receipt == receipt | {'recipe': 're5_enemy_cast', 'name': 'enemy-test-v1', 'title_id': '010018100CD46000',
                                 'game_id': '52d15709be0fda1a', 'live_verified': False, 'gameplay_verified': False,
                                 'overlay_files': ['romfs/nativeNXx64/ImgNX/Archive/uOne.arc']}
    assert receipt['donors'] == {'uOne': [{'slug': 'alpha', 'name': 'Alpha', 'sha256': alpha.sha256,
                                           'fit': 'native_height', 'height_cm': round(row['fit']['height_cm'], 1),
                                           'groups': 'every option group'}]}
    assert row == row | {'kind': 'one donor on every option group', 'source_sha256': W.ARCHIVES['uOne'].sha256,
                         'models': ['body', 'body_low'], 'not_replaced': ['other'], 'live_verified': False,
                         'option_groups_handled': [1, 2, 7, 11], 'first_boot_risks': ['never loaded'],
                         'option_group_slots': {'head': [1, 11], 'body': [2], 'feet': [7]}}
    assert row['role_map']['bones']['body']['l_foot'] + 1 == row['role_map']['bones']['body_low']['l_foot']
    assert set(row['fit']['scales']) == {'limbs', 'torso', 'head', 'hands'} and row['counts']['donor_triangles'] == 19
    assert json.loads((out / 'receipt.json').read_text(encoding='utf-8'))['archives']['uOne']['output_sha256'] == row['output_sha256']
    assert seen == [('rest', 'preview-uOne-alpha.png', None), ('posed', 'preview-uOne-alpha-posed.png', 2, False)]
    assert Image.open(out / 'preview.png').size == (144, 48) and Image.open(out / 'preview-posed.png').size == (192, 48)
    assert row['previews']['alpha']['posed']['evaluation_mode'] == 'sampled_fk' and 'sampled' not in row['previews']['alpha']['posed']

    # a mix on the second class beside it: one picture row per donor, no clip in that archive -> no previews asked
    seen.clear()
    both = plain + [C.Assignment('uTwo', (beta, gamma), (W.PROPORTIONAL, W.PROPORTIONAL), mix=True)]
    receipt = C.build_cast('enemy-test-v2', both, classes, tmp_path / 'assets' / 'enemy-test-v2', previews=False)
    mix = receipt['archives']['uTwo']
    assert mix == mix | {'kind': 'mix', 'slot': 'head', 'carrier_groups': [1, 11], 'option_groups_handled': [1, 2, 7, 11]}
    assert [(c['donor'], c['groups'], c['share_if_montages_are_uniform']) for c in mix['carriers']] == [
        ('beta', [11], '2 of 3'), ('gamma', [1], '1 of 3')]
    assert receipt['donors']['uTwo'] == [
        {'slug': 'beta', 'name': 'Beta', 'sha256': beta.sha256, 'fit': 'proportional', 'groups': [11],
         'share_if_montages_are_uniform': '2 of 3'},
        {'slug': 'gamma', 'name': 'Gamma', 'sha256': gamma.sha256, 'fit': 'proportional', 'groups': [1],
         'share_if_montages_are_uniform': '1 of 3'}]
    assert set(mix['live_test']) == {'right', 'wrong', 'evidence_to_keep'}
    assert 'Beta (2 of 3 outfits)' in mix['live_test']['right'][0] and any('no body' in line for line in mix['live_test']['wrong'])
    assert mix['montage_table']['inferred'] and mix['montage_table']['unknown'] and seen == []
    assert sorted(receipt['overlay_files']) == ['romfs/nativeNXx64/ImgNX/Archive/uOne.arc',
                                                'romfs/nativeNXx64/ImgNX/Archive/uTwo.arc']
    assert not (tmp_path / 'assets' / 'enemy-test-v2' / 'preview.png').exists()


def test_build_cast_refuses_before_it_writes_anything(donor, classes, tmp_path):
    alpha, beta = donors(tmp_path, donor, 'alpha', 'beta')
    out = tmp_path / 'assets' / 'broken'
    one = C.Assignment('uOne', (alpha,), (W.NATIVE_HEIGHT,))
    cases = [([], 'at least one class'), ([one, one], 'each class once'),
             ([one, C.Assignment('uTwo', (alpha,), (W.NATIVE_HEIGHT,), mix=True)], 'a donor may appear once'),
             ([C.Assignment('uOne', (alpha,), (W.NATIVE_HEIGHT,), models=('missing',))], 'uOne <- alpha: body has no reviewed models'),
             ([one, C.Assignment('uTwo', (beta, alpha), (W.NATIVE_HEIGHT,) * 2, mix=True)], 'a donor may appear once')]
    for assignments, message in cases:
        with pytest.raises(C.CastError, match=message):
            C.build_cast('broken', assignments, classes, out)
    with pytest.raises(C.CastError, match='original archives of uOne were not given'):
        C.build_cast('broken', [one], {}, out)
    with pytest.raises(C.CastError, match='plain folder name'):
        C.build_cast('../broken', [one], classes, out)
    wrong = dict(classes) | {'uOne': classes['uOne'] + b'x'}
    with pytest.raises(C.CastError, match='uOne <- alpha: uOne needs the exact measured original'):
        C.build_cast('broken', [one], wrong, out)
    assert not out.exists()


def test_cli_builds_reviewed_casts_assignments_and_seeded_pools(tmp_path, monkeypatch, capsys):
    for slug, game in (('sm64ds_mario', 'Mario'), ('sm64ds_luigi', 'Mario'), ('sonic', 'Sonic'), ('ryo', 'Shenmue')):
        library(tmp_path / 'library', slug, slug.encode(), game=game)
    monkeypatch.setattr(C, 'DONORS', {})
    archives = tmp_path / 'archives'
    archives.mkdir()
    (archives / 'uEm10.arc').write_bytes(b'ten')
    (archives / 'uEm11.arc').write_bytes(b'eleven')
    calls = []

    def build_cast(name, assignments, originals, out, *, previews=True, secondary='neutral'):
        calls.append((name, [(a.enemy, [d.slug for d in a.donors], [f.name for f in a.fits], a.mix, a.models)
                             for a in assignments], dict(originals), Path(out).name, previews))
        Path(out).mkdir(parents=True, exist_ok=True)
        return {'donors': {a.enemy: [d.slug for d in a.donors] for a in assignments},
                'archives': {a.enemy: {'output_sha256': 'abc', 'output_bytes': 3} for a in assignments}}
    monkeypatch.setattr(C, 'build_cast', build_cast)
    base = ['--archives', str(archives), '--library', str(tmp_path / 'library'), '--out', str(tmp_path / 'out')]
    assert C.main(base + ['--cast', 'enemy-cast-a-v1', '--no-preview']) == 0
    assert calls.pop() == ('enemy-cast-a-v1', [('uEm10', ['sm64ds_mario'], ['native_height'], False, None),
                                              ('uEm11', ['sm64ds_luigi'], ['native_height'], False, None)],
                           {'uEm10': b'ten', 'uEm11': b'eleven'}, 'enemy-cast-a-v1', False)
    assert json.loads(capsys.readouterr().out)['archives']['uEm11'] == {'sha256': 'abc', 'bytes': 3}
    assert C.main(base + ['--name', 'high-only', '--assign', 'uEm10=sm64ds_mario@proportional',
                          '--only-models', 'uEm10=em1000']) == 0
    assert calls.pop() == ('high-only', [('uEm10', ['sm64ds_mario'], ['proportional'], False, ('em1000',))],
                           {'uEm10': b'ten'}, 'high-only', True)
    assert C.main(base + ['--name', 'mix', '--assign', 'uEm10=sonic+ryo']) == 0
    assert calls.pop()[1] == [('uEm10', ['sonic', 'ryo'], ['native_height', 'native_height'], True, None)]
    survey = tmp_path / 'survey.json'
    survey.write_text(json.dumps([{'slug': slug, 'usable': True, 'franchise': game, 'vertices': 900}
                                  for slug, game in (('sm64ds_mario', 'Mario'), ('sm64ds_luigi', 'Mario'),
                                                     ('sonic', 'Sonic'), ('ryo', 'Shenmue'))]
                                 + [{'slug': 'heavy', 'usable': True, 'franchise': 'Big', 'vertices': 99999},
                                    {'slug': 'broken', 'usable': False, 'reason': 'x'}]), encoding='utf-8')
    capsys.readouterr()
    pool = ['--name', 'pool', '--pool-from', str(survey), '--pool-size', 'uEm10=2,uEm11=1']
    assert C.main(base + pool + ['--pool', '5']) == 0
    name, dealt, _, _, _ = calls.pop()
    slugs = [slug for _, donors_, _, _, _ in dealt for slug in donors_]
    assert len(set(slugs)) == 3 and set(slugs) <= {'sm64ds_mario', 'sm64ds_luigi', 'sonic', 'ryo'}
    assert all(mix for _, _, _, mix, _ in dealt)                             # a pool is carried by the mix carriers
    written = json.loads((tmp_path / 'out' / 'pool' / 'receipt.json').read_text(encoding='utf-8'))
    assert written['pool'] == written['pool'] | {'seed': 5, 'pool_donors': 4, 'max_vertices': 4500,
                                                 'sizes': {'uEm10': 2, 'uEm11': 1}}
    assert C.main(base + pool + ['--pool', '5']) == 0 and calls.pop()[1] == dealt   # the same seed, the same deal
    assert C.main(base + pool + ['--pool', '5', '--pool-exclude', 'Mario']) == 1    # two donors left for three slots
    assert 'pool holds 2' in capsys.readouterr().err
    for bad in (['--cast', 'enemy-cast-a-v1', '--assign', 'uEm10=sonic'], ['--assign', 'uEm10=sonic'], []):
        assert C.main(base + bad) == 1
    (archives / 'uEm11.arc').unlink()
    assert C.main(base + ['--cast', 'enemy-cast-a-v1']) == 1 and 'uEm11.arc is missing' in capsys.readouterr().err
    assert calls == []
