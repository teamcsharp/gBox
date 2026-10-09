import base64
import json
import struct

import pytest
from fastapi.testclient import TestClient

from gbox.config import Config
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
    assert {a['name'] for a in page['items']} == {'Mario', 'Mario · texture.png', 'Castle', 'Sword', 'captured.glb'}
    assert all('_path' not in a and a['preview_url'] for a in page['items'])


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
    page = client.get('/api/assets?sort=copied').json()
    assert page['items'][0]['name'] == 'Copied image' and page['items'][0]['kind'] == 'texture'
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
