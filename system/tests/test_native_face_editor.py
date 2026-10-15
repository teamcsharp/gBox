import base64
import copy
import io
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from gbox import native_face_editor as F, doa2_faces as D
from gbox.store import Store
from test_doa2_textures import fixture


@pytest.fixture
def surface(monkeypatch):
    raw, bank = fixture([(32, 32, 2, 1), (8, 8, 1, 1)])
    bank = D.T.replace(raw, bank, {0: Image.new('RGBA', (32, 32), (90, 80, 70, 255))})
    tex = D.T.descriptors(raw, bank)[0]
    key = 'DOA2/TST00.CHR'
    profile = {'head_model': 0, 'texture': 0, 'sha256': F.digest(bank[tex.offset:tex.offset+tex.size]),
               'crop': [0, 0, 1, 1], 'bounds': [-1, -1, 1, 1]}
    monkeypatch.setattr(F, 'profiles', lambda: {key: profile})
    mesh = {'vertices': [(-1, 1, 1, 0, 0, 1, 0, 0), (1, 1, 1, 0, 0, 1, 1, 0),
                         (1, -1, 1, 0, 0, 1, 1, 1), (-1, -1, 1, 0, 0, 1, 0, 1)],
            'triangles': [[0, 1, 2], [0, 2, 3]], 'texture_id': 0}
    monkeypatch.setattr(D.B, 'resolve_archive_binding', lambda *a: {'sections': {'primary': [0, 0]}, 'render_slot': 1, 'costume': 0})
    monkeypatch.setattr(D.G, 'decode_chr', lambda *a: {'models': [{'meshes': [mesh]}]})
    class Disc:
        def read(self, name):
            return {'1ST_READ.BIN': b'owned-executable', key: raw, key[:-4]+'.BIN': bank}[name]
    return Disc(), key, profile, bank, tex


def photo():
    a = np.zeros((64, 64, 4), dtype=np.uint8)
    yy, xx = np.mgrid[:64, :64]
    a[..., 0] = xx * 4
    a[..., 1] = yy * 4
    a[..., 2] = ((xx // 8 + yy // 8) % 2) * 240
    a[..., 3] = 255
    return Image.fromarray(a)


def deformation():
    return {'version': 1, 'strokes': [{'x': .5, 'y': .5, 'dx': .09, 'dy': -.02, 'radius': .5}]}


def test_native_preview_and_builder_use_identical_edited_payload(surface):
    disc, key, profile, bank, tex = surface
    bundle = F.extract_surface(disc, key)
    initial = F.render(bundle, photo())
    edited = F.render(bundle, photo(), {'deformation': deformation()})
    assert initial['native'] != edited['native']
    assert initial['original'] == edited['original'] and initial['layer'] == edited['layer']
    assert initial['coverage'] == edited['coverage']
    profiles = {key: profile | edited['settings']}
    changes, report = D.prepare(disc, photo(), profiles, expected_payloads={key: F.digest(edited['native'])})
    actual = changes[key[:-4]+'.BIN']
    assert actual[tex.offset:tex.offset+tex.size] == edited['native']
    assert actual[tex.offset+tex.size:] == bank[tex.offset+tex.size:]
    assert report[0]['geometry_modified'] is False
    with pytest.raises(ValueError, match='exact accepted editor preview'):
        D.prepare(disc, photo(), profiles, expected_payloads={key: '0'*64})


def test_surface_cannot_change_native_descriptor_payload_or_profile(surface):
    disc, key, *_ = surface
    bundle = F.extract_surface(disc, key)
    for edit in ({'profile_key': 'foreign'}, {'profile_sha256': '0'*64}, {'payload': base64.b64encode(b'foreign').decode()}):
        with pytest.raises(ValueError):
            F.render(bundle | edit, photo())
    with pytest.raises(ValueError, match='Only face placement'):
        F.render(bundle, photo(), {'texture': 99})
    with pytest.raises(ValueError):
        F.render(bundle, photo(), {'deformation': {'version': 1, 'strokes': [{'x': .5, 'y': .5, 'dx': 1, 'dy': 0, 'radius': .1}]}})


@pytest.fixture
def api(tmp_path, surface):
    disc, key, *_ = surface
    store = Store(tmp_path)
    app = FastAPI()
    F.routes(app, store, lambda: 'operator')
    bundle = F.canonical(F.extract_surface(disc, key))
    sha = store.put_artifact(bundle, 'native-face-surface.json', 'application/json', {}).sha256
    store.put('native_face_inspection', sha, {'game_id': F.GAME, 'profile_key': key})
    source = store.put_artifact(F.png(photo()), 'photo.png', 'image/png', {'photo_skin_source': True}).sha256
    return TestClient(app), store, sha, source


def test_preview_requires_explicit_acceptance_and_saves_exact_recipe(api):
    client, store, inspection, source = api
    body = {'inspection': inspection, 'photo': source, 'settings': {'deformation': deformation()}}
    response = client.post('/api/native-faces/preview', json=body)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['native_quantized'] and store.read_artifact(preview['native_sha256'])
    assert not store.all('native_face_recipe')
    accepted = client.post('/api/native-faces/recipes', json={'candidate': preview['candidate']})
    assert accepted.status_code == 200, accepted.text
    recipe = accepted.json()
    assert recipe['approved'] and recipe['settings'] == preview['settings']
    assert recipe['inspection'] == inspection and recipe['photo'] == source
    assert recipe['implementation'] == F.IMPLEMENTATION
    assert client.get('/api/native-faces/recipes/'+recipe['id']).json()['id'] == recipe['id']
    assert len(client.get('/api/native-faces/recipes', params={'game_id': F.GAME, 'photo': source}).json()['recipes']) == 1
    # A new preview does not mutate the approved exact recipe or latest choice.
    second = client.post('/api/native-faces/preview', json=body | {'settings': {'opacity': .5}}).json()
    assert second['candidate'] != recipe['id']
    assert store.get('native_face_recipe', recipe['id'])['native_sha256'] == preview['native_sha256']
    assert store.all('native_face_recipe_latest')[0]['id'] == recipe['id']


def test_preview_and_accept_reject_uninspected_or_nonphoto_sources(api):
    client, store, inspection, source = api
    body = {'inspection': inspection, 'photo': source}
    assert client.post('/api/native-faces/preview', json=body | {'inspection': '0'*64}).status_code == 422
    foreign = store.put_artifact(F.png(photo()), 'not-a-photo.png', 'image/png', {}).sha256
    assert client.post('/api/native-faces/preview', json=body | {'photo': foreign}).status_code == 422
    assert client.post('/api/native-faces/recipes', json={'candidate': '0'*64}).status_code == 422


def test_tool_artifact_validation_cannot_register_foreign_output(surface):
    disc, key, *_ = surface
    raw = F.canonical(F.extract_surface(disc, key))
    _, tex, payload = F.validate_surface(json.loads(raw))
    original = F.png(D.T.decode(tex, payload))
    out = F.EditorOut(result={'op': 'inspect', 'inspection': F.digest(raw), 'game_id': F.GAME, 'profile_key': key, 'original': F.digest(original)})
    artifacts = {'native-face-surface.json': raw, 'native-face-original.png': original}
    assert F._validate(out, artifacts) == []
    assert F._validate(out, artifacts | {'native-face-original.png': b'blank'})
    out.result['profile_key'] = 'foreign'
    assert F._validate(out, artifacts)


def test_build_rejects_unapproved_foreign_or_changed_recipe_before_baking(api, surface, monkeypatch, tmp_path):
    import gbox.characters as characters
    client, store, inspection, source = api
    disc, key, *_ = surface
    preview = client.post('/api/native-faces/preview', json={'inspection': inspection, 'photo': source}).json()
    recipe = client.post('/api/native-faces/recipes', json={'candidate': preview['candidate']}).json()
    monkeypatch.setattr(characters, '_dc_gdi', lambda *a: tmp_path/'owned.gdi')
    monkeypatch.setattr(F, 'read_surface', lambda *a: F.extract_surface(disc, key))
    monkeypatch.setattr(D, 'build', lambda *a, **k: pytest.fail('Rejected recipe must never bake a ROM'))
    edited = copy.deepcopy(recipe)
    def api_get(ctx, method, path):
        if path.startswith('/api/catalog/'):return {'game_id': F.GAME}
        if path.startswith('/api/artifacts/'):return store.read_artifact(source)
        return edited
    monkeypatch.setattr(characters, '_api', api_get)
    inp = F.EditorIn(op='build', game_id=F.GAME, photo=source, recipes=[recipe['id']])
    ctx = SimpleNamespace(config=SimpleNamespace(), progress=lambda *a: None)
    for change in ({'approved': False}, {'photo': '0'*64}, {'implementation': {}}, {'inspection': '0'*64}, {'native_sha256': '0'*64}):
        edited.clear();edited.update(copy.deepcopy(recipe) | change)
        with pytest.raises(ValueError):F.run(inp, ctx)


def test_build_uses_only_explicit_approved_faces_and_the_exact_edited_recipe(api, surface, monkeypatch, tmp_path):
    import gbox.characters as characters
    import gbox.filemods as filemods
    client, store, inspection, source = api
    disc, key, profile, *_ = surface
    preview = client.post('/api/native-faces/preview', json={'inspection': inspection, 'photo': source,
                         'settings': {'deformation': deformation()}}).json()
    recipe = client.post('/api/native-faces/recipes', json={'candidate': preview['candidate']}).json()
    # Another valid catalog entry must never be included through defaults.
    monkeypatch.setattr(F, 'profiles', lambda: {key: profile, 'DOA2/OTHER00.CHR': profile})
    monkeypatch.setattr(characters, '_dc_gdi', lambda *a: tmp_path/'owned.gdi')
    monkeypatch.setattr(F, 'read_surface', lambda *a: F.extract_surface(disc, key))
    monkeypatch.setattr(filemods, 'mod_dir', lambda cfg, gid, name: tmp_path/name)
    def api_get(ctx, method, path):
        if path.startswith('/api/catalog/'):return {'game_id': F.GAME}
        if path.startswith('/api/artifacts/'):return store.read_artifact(source)
        return recipe
    monkeypatch.setattr(characters, '_api', api_get)
    built = []
    def build(gdi, folder, name, photo_image, selected, **kwargs):
        assert list(selected) == [key]
        assert selected[key]['deformation'] == recipe['settings']['deformation']
        changes, reports = D.prepare(disc, photo_image, selected, expected_payloads=kwargs['expected_payloads'])
        assert reports[0]['result_texture_sha256'] == recipe['native_sha256']
        folder.mkdir()
        (folder/'build-report.json').write_text(json.dumps({'faces': reports}))
        (folder/'.gbox-mod.json').write_text('{}')
        built.append(changes)
        return {'mod': name, 'image': str(folder/'edited.gdi')}
    monkeypatch.setattr(D, 'build', build)
    ctx = SimpleNamespace(config=SimpleNamespace(), progress=lambda *a: None, artifact=lambda *a: None)
    out = F.run(F.EditorIn(op='build', game_id=F.GAME, photo=source, recipes=[recipe['id']]), ctx)['result']
    assert len(built) == 1 and out['face_editor']['approved_recipes'] == [recipe['id']]
    assert list(out['face_editor']['profiles']) == [key]
    assert out['face_editor']['profiles'][key]['settings'] == recipe['settings']
