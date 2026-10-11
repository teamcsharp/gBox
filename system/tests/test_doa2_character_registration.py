"""Functional regressions for explicit rig import and complete-source cache refresh.

"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import characters, doa2_chars, doa2_rig, doa2_swap, uap
from gbox.doa2_native_export import complete
from gbox.doa2_weighted_retarget import load_rig

C = characters


GAME = {'game_id': '1de2e7634f3161ff', 'title': 'Dead or Alive 2 - Limited Edition (Japan)',
        'platform': 'dreamcast'}
ROSTER = [{'key': 'GEN', 'slug': 'doa2_gen', 'name': 'Gen Fu', 'costumes': ['00'],
           'aliases': ['GEN', 'Gen Fu'], 'kind': 'character'}]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.delenv('GBOX_CHARACTERS', raising=False)
    cfg = SimpleNamespace(cache=tmp_path/'cache', data_dir=tmp_path/'data')
    cfg.cache.mkdir()
    C.library_root(cfg).mkdir()
    messages = []
    context = SimpleNamespace(config=cfg, progress=lambda *args: messages.append(args))
    monkeypatch.setattr(C, 'render_preview', lambda path, output, **kwargs: Path(output).write_bytes(b'preview'))
    monkeypatch.setattr(C, 'check_preview', lambda path: {'ok': True})
    return context


def fixture_model(tmp_path, suffix='glb'):
    model = uap.Manifest(name='rig import fixture', source={'extraction_method': 'synthetic'},
        skeleton=[uap.Bone(name='source_hip'),
                  uap.Bone(name='source_head', parent=0, translation=[0, 1, 0])],
        meshes=[uap.Mesh(name='triangle', positions=[[-.5, 0, 0], [.5, 0, 0], [0, 2, 0]],
                        normals=[[0, 0, 1]]*3, uvs=[[0, 0], [1, 0], [.5, 1]], indices=[0, 1, 2],
                        joints=[[0, 0, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]],
                        weights=[[1, 0, 0, 0]]*3)],
        nodes=[uap.Node(name='body', mesh=0, skinned=True)], roots=[0])
    path = tmp_path/f'source.{suffix}'
    if suffix == 'gltf':
        path.write_text(json.dumps(uap.to_gltf(model)))
    else:
        path.write_bytes(uap.to_glb(model, tmp_path))
    return path


def verified_cache(ctx):
    cache = Path(ctx.config.data_dir)/'analysis'/'doa2'/GAME['game_id']/'native-cloth-cache'
    cache.mkdir(parents=True)
    (cache/'verification.json').write_text(json.dumps({'status': 'verified'}))
    return cache


def previous_entry(ctx, tmp_path, marker=None, tool='gbox.doa2_chars native NaomiLib decoder'):
    path = fixture_model(tmp_path)
    metadata = C.add(C.library_root(ctx.config), 'doa2_gen', 'Gen Fu', [path],
                     {'game_id': GAME['game_id'], 'game_title': GAME['title']}, tool,
                     aliases=['GEN', 'Gen Fu'], rig={'roles': {'hip': 'source_hip', 'head': 'source_head'}},
                     targets={'target_game': [{'slot': 'player', 'mod': 'old-partial-mod', 'nodes': ['jay']} ]},
                     extra={'native_source_assembly': marker} if marker else None)
    return metadata


def fake_reader(ctx, monkeypatch):
    calls = []
    def run(context, game, entry, work):
        calls.append(entry['slug'])
        model = fixture_model(work)
        return {'files': [model], 'tool': 'gbox.doa2_chars native NaomiLib decoder',
                'source_files': ['DOA2/GEN00.CHR'],
                'roles': {'hip': 'source_hip', 'head': 'source_head'},
                'extra': {'native_source_assembly': 'complete_native_source'}}
    monkeypatch.setattr(C, 'DEDICATED', [('doa2', lambda title, platform: platform == 'dreamcast',
                                       lambda: ROSTER, run)])
    monkeypatch.setattr(C, '_game', lambda context, inp: GAME)
    monkeypatch.setattr(C, '_session', lambda context, session_id: None)
    return calls


@pytest.mark.parametrize('suffix', ['glb', 'gltf'])
def test_explicit_add_roles_survive_json_and_weighted_donor_loading(ctx, tmp_path, suffix):
    source = fixture_model(tmp_path, suffix)
    roles = {'hip': 'source_hip', 'head': 'source_head'}
    inp = C.CharIn(op='add', character='Imported fighter', path=str(source), rig_roles=roles)
    result = C.add_model(ctx, inp)
    meta = C.get(C.library_root(ctx.config), result['entry']['slug'])
    assert meta['rig']['roles'] == roles
    assert meta['rig']['joints'] == 2
    model = C.library_root(ctx.config)/meta['slug']/meta['model']
    donor = load_rig(model, meta['rig']['roles'])
    assert donor['roles'] == {'hip': 0, 'head': 1}
    assert sum(len(p['tris']) for p in donor['prims']) == 1
    assert np.allclose(donor['prims'][0]['W'].sum(axis=1), 1)


def test_add_without_roles_keeps_unidentified_rig(ctx, tmp_path):
    source = fixture_model(tmp_path)
    result = C.add_model(ctx, C.CharIn(op='add', character='Unmapped import', path=str(source)))
    assert 'roles' not in result['entry']['rig']


@pytest.mark.parametrize('marker', [None, 'partial_core', 'unassembled_parts'])
def test_public_extract_refreshes_native_partial_entry_and_invalidates_old_targets(ctx, tmp_path, monkeypatch, marker):
    previous_entry(ctx, tmp_path, marker)
    verified_cache(ctx)
    calls = fake_reader(ctx, monkeypatch)
    result = C.extract(ctx, C.CharIn(op='extract', character='Gen Fu', game_id=GAME['game_id']))
    assert result['status'] == 'extracted'
    assert result['route'] == 'dedicated:doa2'
    assert calls == ['doa2_gen']
    meta = C.get(C.library_root(ctx.config), 'doa2_gen')
    assert meta['native_source_assembly'] == 'complete_native_source'
    assert meta['targets']['target_game'][0]['mod'] == 'old-partial-mod'
    assert meta['targets']['target_game'][0]['needs_rebuild'] is True


def test_direct_dedicated_refresh_has_same_behavior(ctx, tmp_path, monkeypatch):
    previous_entry(ctx, tmp_path, 'partial_core')
    verified_cache(ctx)
    calls = fake_reader(ctx, monkeypatch)
    result = C.extract_dedicated(ctx, GAME, 'Gen Fu', C.library_root(ctx.config))
    assert result['status'] == 'extracted'
    assert result['entry']['native_source_assembly'] == 'complete_native_source'
    assert calls == ['doa2_gen']


@pytest.mark.parametrize('has_cache,marker,tool', [
    (False, 'partial_core', 'gbox.doa2_chars native NaomiLib decoder'),
    (True, 'complete_native_source', 'gbox.doa2_chars native NaomiLib decoder'),
    (True, None, 'characters op=add (edited model)'),
])
def test_existing_full_or_unready_or_user_edited_model_is_retained(ctx, tmp_path, monkeypatch, has_cache, marker, tool):
    previous_entry(ctx, tmp_path, marker, tool)
    if has_cache:
        verified_cache(ctx)
    calls = fake_reader(ctx, monkeypatch)
    public = C.extract(ctx, C.CharIn(op='extract', character='Gen Fu', game_id=GAME['game_id']))
    direct = C.extract_dedicated(ctx, GAME, 'Gen Fu', C.library_root(ctx.config))
    assert public['status'] == direct['status'] == 'in_collection'
    assert calls == []
    meta = C.get(C.library_root(ctx.config), 'doa2_gen')
    assert not meta['targets']['target_game'][0].get('needs_rebuild')


def test_no_refresh_for_unrelated_title(ctx, tmp_path):
    meta = previous_entry(ctx, tmp_path)
    verified_cache(ctx)
    other = dict(GAME, title='Sonic Adventure 2', game_id='different-owned-title')
    assert C._doa2_needs_refresh(ctx, other, meta) is False


def test_doacanonical_reader_publishes_exact_assembly_marker(ctx, tmp_path, monkeypatch):
    cache = verified_cache(ctx)
    received = []
    def export(gdi, output, key, costume, **kwargs):
        received.append(kwargs['native_cache'])
        return {'files': ['GEN00_rigged.gltf'], 'roles': {'hip': 'hip', 'head': 'head'},
                'assembly': 'complete_native_source',
                'manifest': {'source': {'resource_ids': ['DOA2/GEN00.CHR']},
                             'container_facts': {'n_models': 55, 'n_textures': 73}}}
    monkeypatch.setattr(doa2_chars, 'export', export)
    monkeypatch.setattr(C, '_dc_gdi', lambda context, game: tmp_path/'owned.gdi')
    result = C._doa2_run(ctx, GAME, ROSTER[0], tmp_path/'out')
    assert received == [cache]
    assert result['extra'] == {'native_source_assembly': 'complete_native_source'}


def test_native_source_and_target_have_same_fifteen_body_roles():
    assert complete.ROLES == doa2_rig.ROLES
    assert set(complete.ROLES) == doa2_swap.REQUIRED_ROLES
    assert len(complete.ROLES) == 15
    assert set(complete.ROLES.values()) == set(range(15))
    assert complete.ROLES['head'] == 1
    assert complete.ROLES['hip'] == 2


@pytest.mark.parametrize('mapped_name', ['body', 'missing_joint', ''])
def test_invalid_role_mapping_is_rejected_before_library_entry(ctx, tmp_path, mapped_name):
    source = fixture_model(tmp_path)
    inp = C.CharIn(op='add', character='Bad mapping', path=str(source),
                   rig_roles={'hip': 'source_hip', 'head': mapped_name})
    with pytest.raises(ValueError, match='skin joint'):
        C.add_model(ctx, inp)
    assert list(C.library_root(ctx.config).glob('*/meta.json')) == []
    assert list(C.library_root(ctx.config).iterdir()) == []


def test_ambiguous_joint_name_is_rejected_before_library_entry(ctx, tmp_path):
    source = fixture_model(tmp_path, 'gltf')
    gl = json.loads(source.read_text())
    for joint in gl['skins'][0]['joints']:
        gl['nodes'][joint]['name'] = 'duplicate_name'
    source.write_text(json.dumps(gl))
    inp = C.CharIn(op='add', character='Ambiguous mapping', path=str(source),
                   rig_roles={'hip': 'duplicate_name'})
    with pytest.raises(ValueError, match='skin joint'):
        C.add_model(ctx, inp)
    assert list(C.library_root(ctx.config).iterdir()) == []


def test_same_joint_referenced_by_two_skins_is_not_ambiguous(ctx, tmp_path):
    source = fixture_model(tmp_path, 'gltf')
    gl = json.loads(source.read_text())
    gl['skins'].append(dict(gl['skins'][0]))
    source.write_text(json.dumps(gl))
    roles = {'hip': 'source_hip', 'head': 'source_head'}
    assert C.validate_rig_roles(source, roles) == roles


@pytest.mark.parametrize('bad_index', [-1, 999, 1.5])
def test_invalid_skin_joint_index_is_rejected(ctx, tmp_path, bad_index):
    source = fixture_model(tmp_path, 'gltf')
    gl = json.loads(source.read_text())
    gl['skins'][0]['joints'] = [bad_index]
    source.write_text(json.dumps(gl))
    with pytest.raises(ValueError, match='skin joint'):
        C.validate_rig_roles(source, {'head': 'source_head'})
