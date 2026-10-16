import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from gbox import cast_roster as R, cast_swap as CS, characters as C, char_coverage as CC
from gbox.config import Config

SA2 = {'game_id': next(iter(__import__('gbox.sa2_chars', fromlist=['x']).GAME_IDS)),
       'title': 'Sonic Adventure 2 (USA)', 'platform': 'dreamcast'}
OTHER = {'game_id': '2' * 16, 'title': 'Unregistered title', 'platform': 'psx'}


def meta(slug, game, **changes):
    return {'slug': slug, 'name': 'Sonic', 'kind': 'character', 'model': 'model.glb',
            'rig': {'roles': {'hip': 'root'}}, 'stats': {'triangles': 10},
            'source': {'game_id': game['game_id'], 'game_title': game['title'], 'platform': game['platform']}, **changes}


def write(root, value, *, files=True):
    folder = root / value['slug']
    folder.mkdir(parents=True)
    (folder / 'meta.json').write_text(json.dumps(value))
    if files:
        (folder / 'model.glb').write_bytes(b'recorded model')
        (folder / 'preview.png').write_bytes(b'recorded preview')
    return value


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / 'characters'
    root.mkdir()
    monkeypatch.setattr(C, 'library_root', lambda cfg=None: root)
    monkeypatch.setattr(C, 'verify_entry', lambda *args: {'ok': True})
    return root


def test_sa2_exposes_real_player_and_full_registered_roster_without_whole_cast_claim(library):
    sonic = write(library, meta('sonic', SA2))
    out = R.roster(SA2, [sonic], library, Config(), SA2['game_id'], SA2)
    native = [row for row in out['targets'] if row['slot'] is not None]
    registered = [row for row in out['targets'] if row['slot'] is None]
    assert len(native) == 1 and native[0]['slot'] == 'player' and native[0]['buildable']
    assert native[0]['model_url'] is None and native[0]['preview_url'] is None
    assert len(registered) == len(C.SA2_CHARS) == 14
    assert {'Sonic', 'Shadow', 'Tails', 'Cyclone', 'Egg Walker'} <= {row['name'] for row in registered}
    assert all(row['id'].startswith('roster:') and not row['buildable'] for row in registered)
    sonic_row = next(row for row in registered if row['slug'] == 'sonic')
    assert sonic_row['model_url'] == '/api/characters/sonic/file/model.glb'
    assert out['capability']['status'] == 'partial' and not out['capability']['combined_writer']
    assert out['capability']['native_slots_count'] == 1
    assert any('individual replacements' in reason for reason in out['capability']['blocking_reasons'])
    assert next(row for row in out['donors'] if row['slug'] == 'sonic')['ready']
    shadow = next(row for row in out['donors'] if row['name'] == 'Shadow')
    assert not shadow['ready'] and shadow['model_url'] is None and 'not been extracted' in shadow['reason']
    assert CS.plan(SA2, [sonic], 'sonic')['status'] == 'unsupported_cast'


def test_unsupported_target_keeps_actual_extracted_roster_and_stable_ids(library):
    value = write(library, meta('actual_npc', OTHER, name='Actual NPC'))
    one = R.roster(OTHER, [value], library, Config())
    two = R.roster(OTHER, [value], library, Config())
    assert one['targets'] == two['targets']
    row = one['targets'][0]
    assert row['id'] == 'roster:actual_npc' and row['slot'] is None and not row['buildable']
    assert row['preview_url'] == '/api/characters/actual_npc/preview'
    assert one['capability']['status'] == 'unsupported' and one['capability']['native_slots_count'] == 0


def test_equal_display_names_and_legacy_preview_urls_never_cross_title_provenance(library, monkeypatch):
    other = OTHER | {'title': SA2['title']}
    foreign = write(library, meta('sonic', other, preview_url='/unverified.png', model_url='/unverified.glb'))
    own = write(library, meta('sonic_alt', SA2, name='Sonic'))
    out = R.roster(SA2, [foreign, own], library, Config(), other['game_id'], other)
    target = next(row for row in out['targets'] if row['id'] == 'roster:sonic_' + SA2['game_id'])
    assert target['preview_url'] is None and target['model_url'] is None
    assert all(row['source_game_id'] == SA2['game_id'] for row in out['targets'])
    assert all(row['source_game_id'] == other['game_id'] for row in out['donors'])
    assert next(row for row in out['donors'] if row['slug'] == 'sonic')['preview_url'] == '/api/characters/sonic/preview'
    assert all(row.get('model_url') != '/unverified.glb' for row in out['targets'] + out['donors'])


def test_exact_source_without_assets_returns_registered_pending_roster(library):
    out = R.roster(OTHER, [], library, Config(), SA2['game_id'], SA2)
    assert out['source'] == {'key': SA2['game_id'], 'label': SA2['title']}
    assert len(out['donors']) == len(C.SA2_CHARS)
    assert all(not row['ready'] and row['preview_url'] is None and row['model_url'] is None for row in out['donors'])
    empty = R.roster(SA2, [], library, Config(), OTHER['game_id'], OTHER)
    assert empty['donors'] == [] and any('No extracted donor' in reason for reason in empty['capability']['blocking_reasons'])


def test_stale_and_missing_files_use_existing_gate_without_refresh_or_invented_urls(library, monkeypatch):
    missing = write(library, meta('sonic', SA2, preview_url='/fake-preview.png'), files=False)
    out = R.roster(OTHER, [missing], library, Config(), 'sonic')
    row = out['donors'][0]
    assert not row['ready'] and row['preview_url'] is None and row['model_url'] is None
    real = write(library, meta('sa2_shadow', SA2, name='Shadow'))
    monkeypatch.setattr(C, 'reader_status', lambda value: {'stale': True, 'extractor': 'fixture', 'entry': 1, 'current': 2})
    monkeypatch.setattr(C, 'extract_dedicated', lambda *args: pytest.fail('GET must not re-extract'))
    stale = R.roster(OTHER, [real], library, Config(), 'sonic')['donors'][0]
    assert not stale['ready'] and 're-extract' in stale['reason']


def test_bad_model_path_cannot_be_exposed_or_marked_ready(library):
    value = write(library, meta('sonic', SA2, model='../outside.glb'))
    (library / 'outside.glb').write_bytes(b'not this character')
    row = R.roster(OTHER, [value], library, Config(), 'sonic')['donors'][0]
    assert row['preview_url'] and row['model_url'] is None and row['model'] is None and not row['ready']


def test_group_donor_without_exact_source_id_has_no_asset_enrichment_or_readiness(library):
    value = meta('sonic', SA2)
    value['source'].pop('game_id')
    write(library, value)
    row = R.roster(OTHER, [value], library, Config(), 'sonic')['donors'][0]
    assert row['source_game_id'] is None and not row['ready']
    assert row['preview_url'] is None and row['model_url'] is None
    assert 'Exact source game_id' in row['reason']


def test_scope_filters_real_slots_and_roster_kinds_without_virtual_writes(library, monkeypatch):
    monkeypatch.setattr(CC, 'writer_for', lambda game: {'writer': 'gbox.auf_swap', 'routed': True})
    monkeypatch.setattr(CS, 'slot_rows', lambda game: [{'slot': 'campaign:guard', 'name': 'Guard', 'kind': 'enemy', 'groups': ['campaign']},
                                                   {'slot': 'player', 'name': 'Player', 'kind': 'player'}])
    value = write(library, meta('actual_enemy', OTHER, name='Extracted guard', kind='enemy', groups=['campaign']))
    scoped = R.roster(OTHER, [value], library, Config(), slots='campaign')
    assert scoped['requested_scope'] == 'campaign'
    assert {row['id'] for row in scoped['targets']} == {'campaign:guard', 'roster:actual_enemy'}
    assert scoped['capability']['native_slots_count'] == 1
    assert next(row for row in scoped['targets'] if row['slot'] is None)['buildable'] is False
    unknown = R.roster(OTHER, [value], library, Config(), slots='unregistered-area')
    assert unknown['targets'] == [] and any('coverage remains pending' in text for text in unknown['capability']['blocking_reasons'])


def test_explicit_native_collection_identity_only_enriches_its_matching_row(library, monkeypatch):
    value = write(library, meta('native_npc', OTHER, name='Native NPC'))
    monkeypatch.setattr(CC, 'writer_for', lambda game: {'writer': 'gbox.auf_swap', 'routed': True})
    monkeypatch.setattr(CS, 'slot_rows', lambda game: [{'slot': 'npc:one', 'name': 'NPC', 'kind': 'npc', 'slug': 'native_npc'},
                                                   {'slot': 'player', 'name': 'Player', 'kind': 'player'}])
    rows = R.roster(OTHER, [value], library, Config())['targets']
    assert len(rows) == 2 and rows[0]['model_url'] == '/api/characters/native_npc/file/model.glb'
    assert rows[1]['model_url'] is None


def test_authenticated_roster_get_is_read_only_and_missing_source_is_pending(library, tmp_path, monkeypatch):
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path / 'data')
    app = create_app(cfg)
    store = app.state.store
    store.upsert_catalog([dict(game, source_paths=[], profile_id=game['game_id'], format='gdi') for game in (SA2, OTHER)])
    monkeypatch.setattr(C, 'list_all', lambda *args: [])
    client = TestClient(app)
    url = f'/api/cast_swap/roster?game_id={OTHER["game_id"]}&source={SA2["game_id"]}'
    assert client.get(url).status_code == 401
    client.headers['Authorization'] = 'Bearer ' + cfg.token()
    before = {kind: store.all(kind) for kind in ('job', 'request', 'session', 'character_collection')}
    reply = client.get(url)
    assert reply.status_code == 200 and len(reply.json()['donors']) == 14
    assert reply.json()['capability']['status'] == 'unsupported'
    assert {kind: store.all(kind) for kind in before} == before
    assert client.get('/api/cast_swap/roster?game_id=absent').status_code == 404
    assert client.get(url + '&slots=' + 'x' * 301).status_code == 422
    assert client.get(f'/api/cast_swap/roster?game_id={OTHER["game_id"]}&source=ambiguous-title').status_code == 422
