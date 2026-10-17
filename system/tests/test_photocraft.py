"""Texture drafts are bounded, revisioned and exported only to separate donors."""
import base64
import copy
import io
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from gbox import attachments as A, characters as C, photocraft as P
from gbox.store import Store


def png(size=(8, 4), color=(20, 60, 120, 128)):
    stream = io.BytesIO()
    Image.new('RGBA', size, color).save(stream, 'PNG')
    return stream.getvalue()


def data_url(raw, kind='image/png'):
    return 'data:' + kind + ';base64,' + base64.b64encode(raw).decode()


def model(path):
    first, second = png(), png(color='green')
    blob = first + second
    gl = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(blob)}],
          'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(first)},
                          {'buffer': 0, 'byteOffset': len(first), 'byteLength': len(second)}],
          'images': [{'bufferView': 0, 'mimeType': 'image/png', 'name': 'Face'},
                     {'bufferView': 1, 'mimeType': 'image/png', 'name': 'Body'}],
          'textures': [{'source': 0, 'sampler': 0}, {'source': 1}],
          'samplers': [{'magFilter': 9728, 'minFilter': 9728}],
          'materials': [
              {'name': 'Head', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}, 'normalTexture': {'index': 0}},
              {'name': 'Shared face', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}},
              {'name': 'Body', 'pbrMetallicRoughness': {'baseColorTexture': {'index': 1}}}],
          'nodes': [{'name': 'Unchanged head', 'skin': 0}], 'skins': [{'joints': [0]}],
          'animations': [{'name': 'Original animation', 'channels': [], 'samplers': []}]}
    path.write_bytes(A.glb_bytes(copy.deepcopy(gl), blob))
    return gl


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.delenv('GBOX_CHARACTERS', raising=False)
    root = tmp_path / 'cache' / 'characters'
    (root / 'donor').mkdir(parents=True)
    source = root / 'donor' / 'model.glb'
    model(source)
    C.put_meta(root, {'slug': 'donor', 'name': 'Original donor', 'model': 'model.glb', 'source': {},
                     'rig': {'roles': {'head': 'Head'}}, 'targets': {'old-game': [{'mod': 'original'}]},
                     'selfie_photo': 'f' * 64, 'tags': ['selfie:' + 'f' * 64]})
    store = Store(tmp_path / 'data')
    app = FastAPI()
    def auth(authorization: str = Header(default=''), x_gbox_actor: str = Header(default='operator')):
        if authorization != 'Bearer test':
            raise HTTPException(401, 'bad token')
        return x_gbox_actor
    config = SimpleNamespace(cache=tmp_path / 'cache', data_dir=tmp_path / 'data')
    P.routes(app, store, auth, config)
    with TestClient(app, headers={'Authorization': 'Bearer test'}) as client:
        yield SimpleNamespace(client=client, store=store, config=config, source=source, root=root)


def open_model(api, **kwargs):
    response = api.client.post('/api/photocraft/sessions', json={'character': 'donor', 'image': 0, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def save(api, session, **kwargs):
    response = api.client.post('/api/photocraft/sessions/' + session['id'] + '/revisions', json={
        'expected_revision': session['revision'], 'png_data_url': data_url(png(color='red')), **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def test_original_and_revisions_are_immutable_and_project_reopens(api):
    before = api.source.read_bytes()
    session = open_model(api)
    assert session['revision'] == 0 and session['current'] == session['original']
    assert [session['width'], session['height']] == [8, 4]
    assert session['materials'] == ['Head', 'Shared face']
    assert session['model_url'] == '/api/artifacts/' + session['model']
    project = b'opaque PhotoCraft project bytes, never executed or unpacked'
    updated = save(api, session, project_data_url=data_url(project, 'application/octet-stream'), project_format='pcraft')
    assert updated['revision'] == 1 and updated['original'] == session['original']
    assert updated['current'] != session['original'] and updated['project_format'] == 'pcraft'
    assert api.store.read_artifact(updated['project']) == project
    assert api.store.read_artifact(session['original']) == png()
    assert api.source.read_bytes() == before
    reopened = api.client.get('/api/photocraft/sessions/' + session['id']).json()
    assert reopened == updated
    next_revision = save(api, updated, png_data_url=data_url(png(color='blue')))
    assert next_revision['revision'] == 2 and next_revision['project'] is None
    assert next_revision['revisions'][1]['project'] == updated['project']
    stale = api.client.post('/api/photocraft/sessions/' + session['id'] + '/revisions', json={
        'expected_revision': 0, 'png_data_url': data_url(png())})
    assert stale.status_code == 409
    assert api.client.get('/api/photocraft/sessions/' + session['id']).json()['revision'] == 2


def test_color_maps_only_are_scoped_and_shared_materials_are_explicit(api):
    result = api.client.get('/api/characters/donor/photocraft/maps')
    assert result.status_code == 200, result.text
    maps = result.json()['maps']
    assert len(maps) == 2 and maps[0]['materials'] == ['Head', 'Shared face']
    assert maps[0]['material_indices'] == [0, 1] and maps[0]['size'] == [8, 4]
    assert api.store.read_artifact(maps[0]['artifact']) == png()
    alias = api.client.post('/api/photocraft/sessions', json={'character': 'donor', 'map_index': 1})
    assert alias.status_code == 200 and alias.json()['image'] == 1
    for image in (2, -1):
        assert api.client.post('/api/photocraft/sessions', json={'character': 'donor', 'image': image}).status_code == 422


def test_export_replaces_only_selected_color_image_and_creates_separate_donor(api):
    before = api.source.read_bytes()
    original, blob = A.read_gltf(api.source)
    session = save(api, open_model(api))
    response = api.client.post('/api/photocraft/sessions/' + session['id'] + '/donor',
                               json={'revision': 1, 'name': 'My painted donor'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['variant'] != 'donor' and result['name'] == 'My painted donor'
    variant = C.get(api.root, result['variant'])
    assert variant['variant_of'] == 'donor' and variant['selfie_photo'] == 'f' * 64
    assert variant['tags'] == ['selfie:' + 'f' * 64] and 'targets' not in variant
    assert variant['rig'] == {'roles': {'head': 'Head'}}
    assert variant['verification']['status'] == 'unverified'
    exported, exported_blob = A.read_gltf(api.root / result['variant'] / 'model.glb')
    assert api.source.read_bytes() == before
    assert exported_blob[:len(blob)] == blob
    for key in ('nodes', 'skins', 'animations', 'samplers'):
        assert exported[key] == original[key]
    assert exported['materials'][0]['normalTexture'] == {'index': 0}
    assert exported['materials'][2] == original['materials'][2]
    for index in (0, 1):
        ref = exported['materials'][index]['pbrMetallicRoughness']['baseColorTexture']['index']
        assert ref != 0
        image_index = exported['textures'][ref]['source']
        assert P.map_bytes(exported, exported_blob, image_index) == api.store.read_artifact(session['current'])
    assert exported['images'][:2] == original['images']
    again = api.client.post('/api/photocraft/sessions/' + session['id'] + '/donor', json={'revision': 1})
    assert again.json() == result and len(list(api.root.iterdir())) == 2


def test_changed_source_cannot_export_stale_texture_donor(api):
    session = save(api, open_model(api))
    gl, blob = A.read_gltf(api.source)
    gl['nodes'][0]['name'] = 'Changed source'
    api.source.write_bytes(A.glb_bytes(gl, blob))
    response = api.client.post('/api/photocraft/sessions/' + session['id'] + '/donor', json={'revision': 1})
    assert response.status_code == 409
    assert len(list(api.root.iterdir())) == 1


def test_export_can_use_exact_older_reviewed_revision(api):
    first = save(api, open_model(api))
    second = save(api, first, png_data_url=data_url(png(color='blue')))
    response = api.client.post('/api/photocraft/sessions/' + second['id'] + '/donor', json={'revision': 1})
    assert response.status_code == 200, response.text
    assert response.json()['texture'] == first['current'] and first['current'] != second['current']
    assert api.client.post('/api/photocraft/sessions/' + second['id'] + '/donor', json={'revision': 3}).status_code == 422


def test_image_artifact_and_uploaded_png_work_without_model_binding(api):
    source = api.store.put_artifact(png(), 'face.png', 'image/png', {'photo_skin_source': True}).sha256
    for body in ({'artifact': source}, {'png_data_url': data_url(png())}):
        response = api.client.post('/api/photocraft/sessions', json=body)
        assert response.status_code == 200, response.text
        session = save(api, response.json())
        assert not session.get('character')
        assert api.client.post('/api/photocraft/sessions/' + session['id'] + '/donor', json={'revision': 1}).status_code == 422
    assert api.store.get('artifact', source)['provenance'] == {'photo_skin_source': True}


@pytest.mark.parametrize('body', [
    {}, {'character': 'donor', 'artifact': 'a' * 64}, {'character': '../donor'},
    {'path': 'C:/secret.png'}, {'artifact': '../secret'}, {'png_data_url': 'data:text/html;base64,PGh0bWw+'},
    {'png_data_url': data_url(b'not png')}, {'artifact': 'a' * 64},
])
def test_open_rejects_unbound_or_nonimage_sources(api, body):
    assert api.client.post('/api/photocraft/sessions', json=body).status_code == 422
    assert api.store.all('photocraft_session') == []


@pytest.mark.parametrize('change', [
    {'png_data_url': data_url(png(size=(4, 4)))},
    {'png_data_url': data_url(b'not an image')},
    {'png_data_url': data_url(png(), 'image/jpeg')},
    {'project_data_url': data_url(b'project', 'application/octet-stream')},
    {'project_format': 'psd'},
    {'command': 'run me'},
])
def test_save_rejects_resize_invalid_png_or_unpaired_project_without_new_revision(api, change):
    session = open_model(api)
    response = api.client.post('/api/photocraft/sessions/' + session['id'] + '/revisions', json={
        'expected_revision': 0, 'png_data_url': data_url(png()), **change})
    assert response.status_code == 422, response.text
    assert api.client.get('/api/photocraft/sessions/' + session['id']).json()['revision'] == 0


def test_authenticated_sessions_are_actor_scoped(api):
    session = open_model(api)
    for method, path, body in (
        ('get', '/api/characters/donor/photocraft/maps', None),
        ('post', '/api/photocraft/sessions', {'character': 'donor'}),
        ('get', '/api/photocraft/sessions/' + session['id'], None),
    ):
        result = api.client.request(method, path, json=body, headers={'Authorization': ''})
        assert result.status_code == 401
    assert api.client.get('/api/photocraft/sessions/' + session['id'], headers={'x-gbox-actor': 'foreign'}).status_code == 404
    assert api.client.post('/api/photocraft/sessions/' + session['id'] + '/revisions',
        headers={'x-gbox-actor': 'foreign'}, json={'expected_revision': 0, 'png_data_url': data_url(png())}).status_code == 404


def test_pack_rejects_collection_resource_escape(api):
    outside = api.root / 'secret.png'
    outside.write_bytes(png())
    source = api.root / 'donor' / 'unsafe.gltf'
    source.write_text('{"asset":{"version":"2.0"},"images":[{"uri":"../secret.png"}]}')
    meta = C.get(api.root, 'donor')
    C.put_meta(api.root, meta | {'model': 'unsafe.gltf'})
    assert api.client.post('/api/photocraft/sessions', json={'character': 'donor'}).status_code == 422
    assert api.store.all('photocraft_session') == []


def test_alternate_image_binding_never_silently_edits_fallback_texture(api):
    gl, blob = A.read_gltf(api.source)
    # A renderer can prefer this extension image over the fallback source. A
    # plain source-index patch would otherwise produce an unchanged game model.
    gl['textures'][0]['extensions'] = {'KHR_texture_basisu': {'source': 1}}
    api.source.write_bytes(A.glb_bytes(gl, blob))
    response = api.client.post('/api/photocraft/sessions', json={'character': 'donor', 'image': 0})
    assert response.status_code == 422 and 'alternate compressed image binding' in response.text
    assert api.store.all('photocraft_session') == []


def test_size_budget_checked_before_decoding(api, monkeypatch):
    monkeypatch.setattr(P, 'PNG_LIMIT', 32)
    source = api.store.put_artifact(png(), 'image.png', 'image/png', {}).sha256
    assert api.client.post('/api/photocraft/sessions', json={'artifact': source}).status_code == 422
    with pytest.raises(ValueError):
        P.data_bytes(data_url(b'x' * 33), 32)


def test_multi_map_export_keeps_all_reviewed_texture_edits(api):
    first = save(api, open_model(api))
    second = save(api, open_model(api, image=1), png_data_url=data_url(png(color='blue')))
    body = {'sessions': [{'id': first['id'], 'revision': 1}, {'id': second['id'], 'revision': 1}],
            'name': 'Face and body painted'}
    response = api.client.post('/api/photocraft/donors', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['edits']) == 2 and result['name'] == 'Face and body painted'
    gl, blob = A.read_gltf(api.root / result['variant'] / 'model.glb')
    for material_index, session in ((0, first), (1, first), (2, second)):
        texture = gl['materials'][material_index]['pbrMetallicRoughness']['baseColorTexture']['index']
        image = gl['textures'][texture]['source']
        assert P.map_bytes(gl, blob, image) == api.store.read_artifact(session['current'])
    assert gl['materials'][0]['normalTexture'] == {'index': 0}
    meta = C.get(api.root, result['variant'])
    assert meta['photocraft_edit']['edits'] == result['edits']
    # Reordering the UI selection still identifies the same immutable batch.
    assert api.client.post('/api/photocraft/donors', json=body | {'sessions': body['sessions'][::-1]}).json() == result


def test_multi_map_export_rejects_duplicate_image_and_different_source(api):
    first = save(api, open_model(api))
    duplicate = save(api, open_model(api))
    selections = [{'id': first['id'], 'revision': 1}, {'id': duplicate['id'], 'revision': 1}]
    assert api.client.post('/api/photocraft/donors', json={'sessions': selections}).status_code == 422
    gl, blob = A.read_gltf(api.source)
    gl['nodes'][0]['name'] = 'Changed source'
    api.source.write_bytes(A.glb_bytes(gl, blob))
    changed = save(api, open_model(api, image=1))
    selections[1]['id'] = changed['id']
    assert api.client.post('/api/photocraft/donors', json={'sessions': selections}).status_code == 422
    assert len(list(api.root.iterdir())) == 1


def test_runtime_serves_only_pinned_allowlist_and_reports_missing_or_corrupt(api, monkeypatch):
    files = {'photocraft.js': b'export default "fixture";', 'photocraft.wasm': b'\0asm-fixture'}
    manifest = {'version': '0.9.0', 'tag': P.RUNTIME_VERSION, 'runtime_dir': 'photocraft/runtime/v0.9.0',
                'files': {name: {'size': len(data), 'sha256': P.digest(data),
                          'mime': 'application/wasm' if name.endswith('.wasm') else 'text/javascript'}
                          for name, data in files.items()}}
    monkeypatch.setattr(P, 'runtime_manifest', lambda: manifest)
    assert api.client.get('/api/photocraft/status').json()['ready'] is False
    directory = api.config.data_dir / manifest['runtime_dir']
    directory.mkdir(parents=True)
    for name, data in files.items():
        (directory / name).write_bytes(data)
    status = api.client.get('/api/photocraft/status').json()
    assert status['ready'] and status['installed'] and status['version'] == '0.9.0'
    assert status['js_url'] == '/photocraft/runtime/photocraft.js'
    assert status['wasm_url'] == '/photocraft/runtime/photocraft.wasm'
    # Static engine files are public; no application token or arbitrary paths.
    response = api.client.get(status['wasm_url'], headers={'Authorization': ''})
    assert response.status_code == 200 and response.content == files['photocraft.wasm']
    assert response.headers['content-type'] == 'application/wasm'
    assert response.headers['x-content-type-options'] == 'nosniff'
    (directory / 'private.txt').write_text('not public')
    assert api.client.get('/photocraft/runtime/private.txt').status_code == 404
    (directory / 'photocraft.wasm').write_bytes(b'x' * len(files['photocraft.wasm']))
    assert api.client.get('/api/photocraft/status').json()['ready'] is False
    assert api.client.get(status['wasm_url']).status_code == 404


def test_runtime_manifest_has_one_official_pinned_engine_and_license_files():
    manifest = P.runtime_manifest()
    assert manifest['tag'] == 'v0.9.0'
    assert manifest['repository'] == 'https://github.com/storytold/photocraft'
    assert len([name for name in manifest['files'] if name.endswith('.js')]) == 1
    assert len([name for name in manifest['files'] if name.endswith('.wasm')]) == 1
    assert 'LICENSE-MIT' in manifest['files'] and 'LICENSE-APACHE' in manifest['files']


def test_draft_budget_counts_unique_artifacts_and_rejects_without_pruning(api, monkeypatch):
    opened = api.client.post('/api/photocraft/sessions', json={'png_data_url': data_url(png())}).json()
    assert opened['storage_bytes'] == len(png())
    assert opened['storage_limit'] == 256 * 1024**2
    # Repeated identical images share one artifact rather than consuming the
    # budget repeatedly. A new layered project must fit before anything is saved.
    monkeypatch.setattr(P, 'SESSION_LIMIT', len(png()) + len(png(color='red')) + 4)
    unchanged = save(api, opened, png_data_url=data_url(png()))
    assert unchanged['storage_bytes'] == len(png())
    project = b'project that is larger than the remaining four bytes'
    artifact_count = len(api.store.all('artifact'))
    rejected = api.client.post('/api/photocraft/sessions/' + opened['id'] + '/revisions', json={
        'expected_revision': unchanged['revision'], 'png_data_url': data_url(png(color='red')),
        'project_data_url': data_url(project, 'application/octet-stream'), 'project_format': 'pcraft'})
    assert rejected.status_code == 409
    current = api.client.get('/api/photocraft/sessions/' + opened['id']).json()
    assert current == unchanged and len(api.store.all('artifact')) == artifact_count
    assert api.store.read_artifact(opened['original']) == png()
    saved = save(api, current)
    assert saved['storage_bytes'] == len(png()) + len(png(color='red'))
