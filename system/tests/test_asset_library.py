import base64
import json
import struct
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gbox import asset_library
from gbox.config import Config
from gbox.asset_library import AssetLibrary, _IndexMetadata
from gbox.server import create_app


def glb():
    doc = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{'nodes': []}], 'scene': 0, 'nodes': []}).encode()
    doc += b' ' * (-len(doc) % 4)
    return b'glTF' + struct.pack('<II', 2, 20 + len(doc)) + struct.pack('<I4s', len(doc), b'JSON') + doc


@pytest.fixture
def assets(tmp_path, monkeypatch):
    monkeypatch.delenv('GBOX_CHARACTERS', raising=False)
    monkeypatch.delenv('GBOX_ENVIRONMENTS', raising=False)
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    app = create_app(cfg)
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        yield app, client, cfg


def collection(cfg, slug='mario', name='Mario', game='Super Mario 64', added=100):
    p = cfg.cache / 'characters' / slug
    p.mkdir(parents=True)
    (p / 'model.glb').write_bytes(glb())
    (p / 'preview.png').write_bytes(b'preview')
    (p / 'meta.json').write_text(json.dumps({'slug': slug, 'name': name, 'kind': 'character',
        'model': 'model.glb', 'preview': 'preview.png', 'source': {'game_title': game}, 'added': added}))
    return p


def test_unified_collection_includes_companions_packages_and_extracted_artifacts(assets):
    app, client, cfg = assets
    p = collection(cfg)
    (p / 'texture.png').write_bytes(b'texture')
    env = cfg.cache / 'environments' / 'castle'; env.mkdir(parents=True)
    (env / 'scene.glb').write_bytes(glb())
    (env / 'meta.json').write_text(json.dumps({'name': 'Castle', 'model': 'scene.glb', 'kind': 'environment'}))
    package = cfg.data_dir / 'uap' / 'sword'; package.mkdir(parents=True)
    (package / 'manifest.json').write_text(json.dumps({'name': 'Sword', 'source': {'game_title': 'Zelda'}}))
    app.state.store.put_artifact(glb() + b'variant', 'captured.glb', 'model/gltf-binary', {'tool': 'scene_capture'})
    app.state.store.put_artifact(b'image', 'unrelated-screenshot.png', 'image/png', {'request': 'report'})
    page = client.get('/api/assets').json()
    assert page['total_all'] == 5
    assert {'character', 'model', 'environment', 'texture'} <= set(page['kinds'])
    assert {a['name'] for a in page['items']} == {'Mario', 'Castle', 'Sword', 'captured.glb'}
    assert next(a for a in page['items'] if a['name'] == 'Mario')['texture_count'] == 1
    flat = client.get('/api/assets?nest=false').json()
    assert {a['name'] for a in flat['items']} == {'Mario', 'Mario · texture.png', 'Castle', 'Sword', 'captured.glb'}
    assert all('_path' not in a and a['preview_url'] for a in flat['items'])


def test_textures_are_listed_under_their_character_only_on_request(assets):
    app, client, cfg = assets
    p = collection(cfg, 'doa2_gen', 'Gen Fu', 'Dead or Alive 2 - Limited Edition (Japan)', 500)
    (p / 'GEN00_parts.glb').write_bytes(glb())
    for i in range(3):
        (p / f'tex{i:03}.png').write_bytes(b'png%d' % i)
    package = cfg.data_dir / 'uap' / 'sword'; package.mkdir(parents=True)
    (package / 'manifest.json').write_text(json.dumps({'name': 'Sword', 'source': {'game_title': 'Zelda'}}))
    (package / 'blade.png').write_bytes(b'blade')
    app.state.store.put_artifact(b'image', 'loose.png', 'image/png', {'tool': 'scene_capture'})
    page = client.get('/api/assets').json()
    names = {a['name'] for a in page['items']}
    # The default top level contains models; unowned textures remain in the explicit filter.
    assert names == {'Gen Fu', 'Gen Fu · GEN00_parts.glb', 'Sword'}
    gen = next(a for a in page['items'] if a['name'] == 'Gen Fu')
    sword = next(a for a in page['items'] if a['name'] == 'Sword')
    assert gen['texture_count'] == 3 and sword['texture_count'] == 1
    assert page['nested'] == 4 and page['hidden_textures'] == 5
    assert page['total'] + page['hidden_textures'] == page['total_all']
    # A package's human name can differ from its filenames; searching it retains all its textures.
    sword_search = client.get('/api/assets', params={'q': 'Sword', 'kind': 'model'}).json()
    assert len(sword_search['items']) == 1 and sword_search['items'][0]['texture_count'] == 1
    assert sword_search['nested'] == 1
    sword_tree = client.get('/api/assets', params={'owner': sword_search['items'][0]['id']}).json()
    assert [a['name'] for a in sword_tree['items']] == ['blade.png']
    groups = client.get('/api/asset-groups').json()['groups']
    assert {g['title']: g['count'] for g in groups}['Dead or Alive 2 - Limited Edition (Japan)'] == 2
    tree = client.get('/api/assets', params={'owner': gen['id'], 'sort': 'name'}).json()
    assert [a['name'] for a in tree['items']] == ['Gen Fu · tex000.png', 'Gen Fu · tex001.png', 'Gen Fu · tex002.png']
    assert all(a['kind'] == 'texture' and a['owner'] == gen['id'] for a in tree['items'])
    # A type filter keeps the character's tree; the texture filter and search list textures directly.
    assert client.get('/api/assets?kind=character').json()['items'][0]['texture_count'] == 3
    textures = client.get('/api/assets?kind=texture').json()
    assert textures['total'] == 5 and all('texture_count' not in a for a in textures['items'])
    found = client.get('/api/assets?q=tex001').json()
    assert [a['name'] for a in found['items']] == ['Gen Fu · tex001.png']


def test_owned_textures_paginate_without_leaking_into_model_pages(assets):
    app, client, cfg = assets
    folder = collection(cfg, 'many', 'Many textures')
    for i in range(205):
        (folder / f'tex{i:03}.png').write_bytes(bytes([i % 256]))
    page = client.get('/api/assets?limit=1').json()
    assert page['total'] == 1 and page['nested'] == 205 and not page['has_more']
    owner = page['items'][0]
    assert owner['texture_count'] == 205
    first = client.get('/api/assets', params={'owner': owner['id'], 'sort': 'name', 'limit': 200}).json()
    last = client.get('/api/assets', params={'owner': owner['id'], 'sort': 'name', 'offset': 200, 'limit': 200}).json()
    assert first['total'] == last['total'] == 205 and first['has_more'] and not last['has_more']
    assert len(first['items']) == 200 and len(last['items']) == 5
    assert len({a['id'] for a in first['items'] + last['items']}) == 205
    assert all(a['kind'] == 'texture' and a['owner'] == owner['id'] and '_path' not in a for a in first['items'] + last['items'])


def test_unowned_textures_are_discoverable_without_default_texture_cards(assets):
    app, client, cfg = assets
    app.state.store.put_artifact(b'loose', 'loose.png', 'image/png', {'tool': 'scene_capture', 'title': 'Loose game'})
    default = client.get('/api/assets').json()
    assert default['total'] == 0 and default['hidden_textures'] == 1 and default['nested'] == 0
    assert 'texture' in default['kinds']
    assert client.get('/api/asset-groups').json()['groups'] == []
    for params in ({'kind': 'texture'}, {'nest': 'false'}, {'q': 'loose.png'}):
        page = client.get('/api/assets', params=params).json()
        assert [a['name'] for a in page['items']] == ['loose.png']


def test_default_cards_exclude_data_and_audio_but_keep_explicit_access(assets):
    app, client, cfg = assets
    folder = collection(cfg)
    (folder / 'mesh.bin').write_bytes(b'mesh')
    (folder / 'voice.wav').write_bytes(b'voice')
    page = client.get('/api/assets').json()
    assert [a['name'] for a in page['items']] == ['Mario']
    assert page['total_all'] == 3 and page['hidden_assets'] == 2 and page['hidden_textures'] == 0
    assert {'data', 'audio'} <= set(page['kinds'])
    assert client.get('/api/asset-groups').json()['groups'][0]['count'] == 1
    assert client.get('/api/assets?kind=data').json()['items'][0]['format'] == 'BIN'
    assert client.get('/api/assets?kind=audio').json()['items'][0]['format'] == 'WAV'
    assert client.get('/api/assets?q=mesh.bin').json()['items'][0]['format'] == 'BIN'
    assert client.get('/api/assets?nest=false').json()['total'] == 3


def test_cold_asset_query_does_not_wait_behind_job_store_lock(assets):
    app, client, cfg = assets
    collection(cfg)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        # A frame/job write owns this lock; listing committed assets must still respond.
        with app.state.store.lock:
            response = pool.submit(client.get, '/api/asset-groups').result(timeout=2)
            assert response.status_code == 200
            assert response.json()['groups'][0]['count'] == 1
    finally:
        pool.shutdown(wait=True)


def test_index_metadata_is_read_only_and_consistent_during_new_commits(assets):
    app, client, cfg = assets
    store = app.state.store
    with _IndexMetadata(store.dir) as snapshot:
        assert snapshot.all('asset_copy') == []
        store.put('asset_copy', 'new', {'id': 'new', 'ts': 123})
        assert snapshot.get('asset_copy', 'new') is None
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            snapshot.db.execute("INSERT INTO docs VALUES ('asset_copy','bad','{}')")
    with _IndexMetadata(store.dir) as refreshed:
        assert refreshed.get('asset_copy', 'new')['ts'] == 123
        assert refreshed.get('asset_copy', 'bad') is None


def test_pagination_exposes_entire_collection_and_sorts_before_slicing(assets):
    app, client, cfg = assets
    for i in range(245):
        collection(cfg, f'char{i}', f'Character {i:03}', 'Game A' if i % 2 else 'Game B', i + 1)
    ids = set()
    for offset in range(0, 245, 60):
        page = client.get('/api/assets', params={'offset': offset, 'limit': 60}).json()
        ids.update(a['id'] for a in page['items'])
    assert len(ids) == 245
    assert client.get('/api/assets?limit=1').json()['items'][0]['name'] == 'Character 244'
    assert client.get('/api/assets?sort=oldest&limit=1').json()['items'][0]['name'] == 'Character 000'
    assert client.get('/api/assets?q=CHARACTER%20024&game=Game%20B&kind=character').json()['total'] == 1
    assert client.get('/api/assets?offset=-1').status_code == 422
    assert client.get('/api/assets?sort=unknown').status_code == 422


def test_copy_tracks_original_asset_persists_and_does_not_duplicate_collection_model(assets):
    app, client, cfg = assets
    collection(cfg, added=1)
    collection(cfg, 'sonic', 'Sonic', 'Sonic Adventure 2', 200)
    mario = next(a for a in client.get('/api/assets').json()['items'] if a['name'] == 'Mario')
    response = client.post('/api/assets/' + mario['id'] + '/copy')
    assert response.status_code == 200 and response.json()['kind'] == 'gltf'
    assert app.state.store.get('clipboard', 'current')['meta']['asset_id'] == mario['id']
    page = client.get('/api/assets?sort=copied').json()
    assert page['items'][0]['name'] == 'Mario' and page['items'][0]['copied'] > 0
    assert page['total_all'] == 2
    app.state.assets.invalidate()
    assert client.get('/api/assets?sort=copied').json()['items'][0]['id'] == mario['id']
    download = client.get(mario['file_url'])
    assert download.content[:4] == b'glTF' and '.glb' in download.headers['content-disposition']
    assert client.get(mario['preview_url']).content == b'preview'


def test_existing_clipboard_and_native_blender_copies_are_included(assets):
    app, client, cfg = assets
    collection(cfg)
    app.state.store.put('job', 'native-copy', {'id': 'native-copy', 'tool': 'blender_copy', 'state': 'succeeded',
                        'input': {'character': 'mario'}, 'finished': 999})
    r = client.post('/api/clipboard', json={'kind': 'image', 'name': 'Copied image', 'b64': base64.b64encode(b'image').decode()})
    assert r.status_code == 200
    page = client.get('/api/assets?sort=copied&nest=false').json()
    assert page['items'][0]['name'] == 'Copied image' and page['items'][0]['kind'] == 'texture'
    visible = client.get('/api/assets?sort=copied').json()
    assert [a['name'] for a in visible['items']] == ['Mario']
    assert next(a for a in page['items'] if a['name'] == 'Mario')['copied'] == 999


def test_copied_gltf_inlines_dependencies_and_blocks_escape(assets):
    app, client, cfg = assets
    p = collection(cfg)
    meta = json.loads((p / 'meta.json').read_text()); meta['model'] = 'model.gltf'
    (p / 'model.glb').unlink(); (p / 'meta.json').write_text(json.dumps(meta))
    (p / 'mesh.bin').write_bytes(b'1234')
    (p / 'model.gltf').write_text(json.dumps({'asset': {'version': '2.0'}, 'buffers': [{'uri': 'mesh.bin', 'byteLength': 4}]}))
    model = next(a for a in client.get('/api/assets').json()['items'] if a['name'] == 'Mario')
    copied = client.post(f"/api/assets/{model['id']}/copy").json()
    doc = json.loads(app.state.store.read_artifact(copied['sha256']))
    assert doc['buffers'][0]['uri'].startswith('data:')
    (p / 'model.gltf').write_text(json.dumps({'buffers': [{'uri': '../../private.bin'}]}))
    app.state.assets.invalidate()
    assert client.post(f"/api/assets/{model['id']}/copy").status_code == 422
    assert client.get('/api/assets/missing/file').status_code == 404


def test_sidebar_endpoints_require_authentication(assets):
    app, client, cfg = assets
    client.headers.pop('Authorization')
    assert client.get('/api/assets').status_code == 401


def test_expandable_title_groups_count_all_assets_and_respect_filters(assets):
    app, client, cfg = assets
    collection(cfg, 'mario', 'Mario', 'Super Mario 64', 100)
    collection(cfg, 'luigi', 'Luigi', 'Super Mario 64', 200)
    collection(cfg, 'sonic', 'Sonic', 'Sonic Adventure 2', 300)
    page = client.get('/api/asset-groups').json()
    assert [(g['title'], g['count']) for g in page['groups']] == [('Sonic Adventure 2', 1), ('Super Mario 64', 2)]
    assert page['total'] == 3
    alpha = client.get('/api/asset-groups?sort=game').json()
    assert [g['title'] for g in alpha['groups']] == ['Sonic Adventure 2', 'Super Mario 64']
    filtered = client.get('/api/asset-groups?q=luigi&kind=character').json()
    assert filtered['total'] == 1 and filtered['groups'][0]['title'] == 'Super Mario 64'
    assert client.get('/api/assets?game=Super%20Mario%2064').json()['total'] == 2
    mario = next(a for a in client.get('/api/assets').json()['items'] if a['name'] == 'Mario')
    client.post(f"/api/assets/{mario['id']}/copy")
    recent = client.get('/api/asset-groups?sort=copied').json()
    assert recent['groups'][0]['title'] == 'Super Mario 64' and recent['groups'][0]['copied'] > 0


def test_legacy_package_and_edited_model_keep_their_source_title(assets):
    app, client, cfg = assets
    collection(cfg, 'cloud', 'Cloud', 'Final Fantasy VII (USA) (Disc 1)')
    collection(cfg, 'hucast', 'HUcast', 'Phantasy Star Online Ver. 2 (USA)')
    app.state.store.put_artifact(glb(), 'Cloud edit.glb', 'model/gltf-binary', {'base': 'cloud'})
    package = cfg.data_dir / 'uap' / 'pso_forest'; package.mkdir(parents=True)
    (package / 'manifest.json').write_text(json.dumps({'name': 'Forest', 'source': {'game_disc': 'psov2.gdi'}}))
    page = client.get('/api/asset-groups').json()
    assert {g['title']: g['count'] for g in page['groups']} == {
        'Final Fantasy VII (USA) (Disc 1)': 2, 'Phantasy Star Online Ver. 2 (USA)': 2}


def test_model_companions_include_raw_animation_audio_and_texture_with_separate_counts(assets):
    app, client, cfg = assets
    folder = collection(cfg, 'ein', 'Ein C1', 'DOA2')
    for name in ('body.bin', 'idle.anim', 'voice.flac', 'skin.png'):
        (folder / name).write_bytes(name.encode())
    page = client.get('/api/assets').json()
    assert page['total'] == 1 and page['total_all'] == 5
    assert page['nested'] == page['hidden_assets'] == 4 and page['hidden_textures'] == 1
    model = page['items'][0]
    assert model['texture_count'] == 1 and model['file_count'] == 3
    tree = client.get('/api/assets', params={'owner': model['id'], 'sort': 'name'}).json()
    assert {a['format'] for a in tree['items']} == {'BIN', 'ANIM', 'FLAC', 'PNG'}
    assert all(a['owner'] == model['id'] for a in tree['items'])
    for kind, expected in [('data', 2), ('audio', 1), ('texture', 1)]:
        direct = client.get('/api/assets', params={'kind': kind}).json()
        assert direct['total'] == expected
        assert all('texture_count' not in a and 'file_count' not in a for a in direct['items'])
    assert client.get('/api/assets?nest=false').json()['total'] == 5


def test_package_raw_audio_companions_follow_owner_search_and_type_filters(assets):
    app, client, cfg = assets
    package = cfg.data_dir / 'uap' / 'blade'; package.mkdir(parents=True)
    (package / 'manifest.json').write_text(json.dumps({'name': 'Named Sword', 'source': {'game_title': 'Zelda'}}))
    for name in ('mesh.bin', 'swing.anim', 'sound.flac', 'surface.png'):
        (package / name).write_bytes(name.encode())
    # Unrelated unsupported file and a directory with a supported suffix are not indexed.
    (package / 'private.txt').write_text('private')
    (package / 'directory.bin').mkdir()
    page = client.get('/api/assets', params={'q': 'Named Sword', 'kind': 'model'}).json()
    assert page['total'] == 1 and page['total_all'] == 5 and page['nested'] == 4
    owner = page['items'][0]
    assert owner['texture_count'] == 1 and owner['file_count'] == 3
    tree = client.get('/api/assets', params={'owner': owner['id']}).json()
    assert {a['name'] for a in tree['items']} == {'mesh.bin', 'swing.anim', 'sound.flac', 'surface.png'}
    found = client.get('/api/assets?q=swing.anim').json()
    assert [a['name'] for a in found['items']] == ['swing.anim']
    default = client.get('/api/asset-groups').json()
    assert default['groups'][0]['count'] == 1 and default['hidden_assets'] == 4


def test_repeat_listing_reuses_the_index_and_new_assets_still_appear(assets, monkeypatch):
    app, client, cfg = assets
    monkeypatch.setattr(asset_library, 'SETTLE_S', 0)     # files written by the test count as settled
    lib = app.state.assets
    lib.wait_for_build(10)                                  # the startup warm-up must not see half-written folders
    collection(cfg)
    assert client.get('/api/asset-groups').json()['total'] == 1
    lib.wait_for_build(10)
    builds = lib.completed
    for _ in range(3):
        assert client.get('/api/asset-groups').json()['total'] == 1
    assert lib.completed == builds, 'an unchanged store is answered from the snapshot, without a rescan'
    app.state.store.put_artifact(glb() + b'new', 'new.glb', 'model/gltf-binary', {'tool': 'scene_capture'})
    assert client.get('/api/asset-groups').json()['total'] == 2
    collection(cfg, 'sonic', 'Sonic', 'Sonic Adventure 2', 300)
    assert {g['title'] for g in client.get('/api/asset-groups').json()['groups']} == {'Super Mario 64', 'Sonic Adventure 2', 'Unknown title'}


def test_slow_first_index_answers_indexing_and_ttl_refresh_serves_the_old_copy(assets, monkeypatch):
    app, client, cfg = assets
    monkeypatch.setattr(asset_library, 'SETTLE_S', 0)
    collection(cfg)
    lib = AssetLibrary(app.state.store, cfg)
    gate, real = threading.Event(), lib._build_index
    monkeypatch.setattr(lib, '_build_index', lambda *args: (gate.wait(10), real(*args))[1])
    lib.wait_s = 0.05
    started = time.monotonic()
    page = lib.page()
    assert time.monotonic() - started < 2
    assert page['indexing'] and page['items'] == [] and page['total'] == 0
    with pytest.raises(HTTPException) as missing:
        lib.get('anything')
    assert missing.value.status_code == 503
    gate.set(); assert lib.wait_for_build(10)
    page = lib.page()
    assert not page['indexing'] and page['total'] == 1
    # Past the TTL the old copy answers at once while a full rescan runs in the background.
    gate.clear(); lib.full_at -= lib.ttl_s + 1
    before = lib.index()
    started = time.monotonic()
    assert lib.index() is before and lib.building and time.monotonic() - started < 2
    gate.set(); assert lib.wait_for_build(10)
    assert time.monotonic() - lib.full_at < 10


def test_fresh_rescans_files_changed_in_place(assets, monkeypatch):
    app, client, cfg = assets
    monkeypatch.setattr(asset_library, 'SETTLE_S', 0)
    app.state.assets.wait_for_build(10)
    p = collection(cfg)
    (p / 'skin.png').write_bytes(b'1')
    assert client.get('/api/assets?kind=texture').json()['items'][0]['size'] == 1
    (p / 'skin.png').write_bytes(b'12345')
    assert client.get('/api/assets?kind=texture&fresh=1').json()['items'][0]['size'] == 5


def test_folder_completed_after_a_scan_is_picked_up_without_a_root_change(assets):
    app, client, cfg = assets
    lib = app.state.assets
    lib.wait_for_build(10)
    folder = cfg.cache / 'characters' / 'late'; folder.mkdir(parents=True)
    (folder / 'model.glb').write_bytes(glb())
    assert client.get('/api/asset-groups').json()['total'] == 0       # no meta.json yet: not an entry
    root_mtime = (cfg.cache / 'characters').stat().st_mtime_ns
    (folder / 'meta.json').write_text(json.dumps({'slug': 'late', 'name': 'Late', 'model': 'model.glb', 'kind': 'character'}))
    assert (cfg.cache / 'characters').stat().st_mtime_ns == root_mtime
    assert client.get('/api/asset-groups').json()['total'] == 1
    (folder / 'skin.png').write_bytes(b'skin')                         # a folder still being written stays watched
    assert client.get('/api/assets?kind=texture').json()['total'] == 1


def test_periodic_refresh_finds_files_added_to_a_settled_folder_and_keeps_an_unchanged_snapshot(assets, monkeypatch):
    app, client, cfg = assets
    monkeypatch.setattr(asset_library, 'SETTLE_S', 0)
    lib = app.state.assets
    lib.wait_for_build(10)
    p = collection(cfg)
    assert client.get('/api/assets?nest=false').json()['total'] == 1
    lib.wait_for_build(10)
    snapshot, lib.refresh_s = lib.index(), -1             # every call re-checks (monotonic() ticks are coarse on Windows)
    lib.index(); lib.wait_for_build(10)
    assert lib.index() is snapshot, 'nothing changed on disk: the refresh keeps the snapshot instead of rebuilding it'
    lib.wait_for_build(10)                                # (that call started another refresh)
    (p / 'skin.png').write_bytes(b'skin')                 # the folder changes, the library root does not
    lib.index(); lib.wait_for_build(10)                   # served the old copy, re-checked folders in the background
    assert client.get('/api/assets?nest=false').json()['total'] == 2
