"""Cover choices use original image bytes and authenticated, bounded image routes."""
from fastapi.testclient import TestClient
import pytest

from gbox import cover_art
from gbox.cover_source import local_image
from gbox.server import create_app

PNG = b'\x89PNG\r\n\x1a\n' + b'original image bytes'
GID = '0123456789abcdef'


def client_for(cfg, monkeypatch):
    app = create_app(cfg)
    monkeypatch.setattr(app.state.store, 'catalog_get', lambda gid:
        {'game_id': gid, 'title': 'Example Game (USA)', 'platform': 'nes'} if gid == GID else None)
    return app, TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()})


def test_search_route_uses_configured_provider_and_nine_result_pages(cfg, monkeypatch):
    app, client = client_for(cfg, monkeypatch)
    calls = []
    def search(query, **kwargs):
        calls.append((query, kwargs))
        return {'items': [], 'page': kwargs['page'], 'has_next': False}
    monkeypatch.setattr(cover_art, 'search', search)
    assert client.get(f'/api/catalog/{GID}/cover/search?source=vimm&page=2').status_code == 200
    assert calls == [('Example Game cover', {'source': 'vimm', 'page': 2, 'searx_url': cfg.agent['searx_url']})]
    assert client.get(f'/api/catalog/{GID}/cover/search?q=Custom+box+art').status_code == 200
    assert calls[-1][0] == 'Custom box art'
    for suffix in ('page=0', 'page=101', 'page_size=20', 'source=unknown', 'q=' + 'x' * 301):
        assert client.get(f'/api/catalog/{GID}/cover/search?{suffix}').status_code == 422
    assert client.get('/api/catalog/missing/cover/search').status_code == 404
    assert TestClient(app).get(f'/api/catalog/{GID}/cover/search').status_code == 401


def test_preview_is_an_authenticated_image_response(cfg, monkeypatch):
    app, client = client_for(cfg, monkeypatch)
    calls = []
    monkeypatch.setattr(cover_art, 'fetch', lambda url, timeout=20: calls.append((url, timeout)) or PNG)
    response = client.get(f'/api/catalog/{GID}/cover/preview', params={'url': 'https://covers.example/game.png'})
    assert response.content == PNG and response.headers['content-type'] == 'image/png'
    assert calls == [('https://covers.example/game.png', 12)]
    assert 'private' in response.headers['cache-control']
    assert TestClient(app).get(f'/api/catalog/{GID}/cover/preview?url=https://example.org').status_code == 401
    monkeypatch.setattr(cover_art, 'fetch', lambda *a, **k: (_ for _ in ()).throw(ValueError('no image')))
    assert client.get(f'/api/catalog/{GID}/cover/preview?url=file:///secret').status_code == 400


def test_gallery_artifact_becomes_cover_without_loopback_or_auth_in_audit(cfg, monkeypatch):
    app, client = client_for(cfg, monkeypatch)
    store = app.state.store
    ref = store.put_artifact(PNG, 'screenshot.png', 'image/png', {})
    source = f'/api/artifacts/{ref.sha256}'
    monkeypatch.setattr(cover_art, 'fetch', lambda *a, **k: pytest.fail('local images must not use HTTP'))
    response = client.post(f'/api/catalog/{GID}/cover', json={'url': source + '?token=secret&w=360'})
    assert response.status_code == 200, response.text
    assert response.json()['source'] == source
    assert client.get(f'/api/media/{GID}/best').content == PNG
    home = app.state.library_home
    assert 'boxart' in home._local_art()[GID]
    home._scan_art()
    assert 'boxart' in home._local_art()[GID]


def test_using_library_image_reads_original_not_thumb_and_invalidates_misses(cfg, monkeypatch):
    app, client = client_for(cfg, monkeypatch)
    art = cfg.data_dir / 'art' / GID
    art.mkdir(parents=True)
    (art / 'snap.png').write_bytes(PNG)
    assert client.get(f'/api/media/{GID}/boxart').status_code == 404
    thumb = cfg.data_dir / 'thumbs' / GID[:2] / f'{GID}-best-360.none'
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.touch()
    result = client.post(f'/api/catalog/{GID}/cover', json={'url': f'/api/media/{GID}/snap?w=360'})
    assert result.status_code == 200, result.text
    assert (art / 'boxart.png').read_bytes() == PNG and not thumb.exists()
    assert client.get(f'/api/media/{GID}/boxart').content == PNG
    monkeypatch.setattr(cover_art, 'fetch', lambda *a, **k: (_ for _ in ()).throw(ValueError('bad')))
    assert client.post(f'/api/catalog/{GID}/cover', json={'url': 'https://bad.example/file'}).status_code == 400
    assert (art / 'boxart.png').read_bytes() == PNG


@pytest.mark.parametrize('url', [
    '/api/characters/name/file/../../secret.png', '/api/characters/name/file/%2e%2e/secret.png',
    '/api/characters/name/file/..%5csecret.png', '//private.example/file',
    '/api/jobs/secret', '/api/artifacts/not-a-hash', 'https://gbox.example/api/media/game/snap',
])
def test_local_source_rejects_unapproved_paths(url):
    with pytest.raises(ValueError):
        local_image(url, store=None, config=None, media_file=lambda *a: pytest.fail('unsafe media'),
                    character_file=lambda *a: pytest.fail('unsafe path'))


def test_local_character_images_keep_original_and_reject_nonimages(tmp_path):
    image = tmp_path / 'face.png'
    image.write_bytes(PNG)
    args = dict(store=None, config=None, media_file=None, character_file=lambda slug, rel: image)
    assert local_image('/api/characters/name/file/face.png?w=90', **args) == ('/api/characters/name/file/face.png', PNG)
    image.write_bytes(b'<html>not an image')
    with pytest.raises(ValueError):
        local_image('/api/characters/name/file/face.png', **args)


def test_built_preview_accepts_real_supported_mod_names(tmp_path, monkeypatch):
    from gbox import built_mods
    file = tmp_path / 'preview.png'
    file.write_bytes(PNG)
    calls = []
    monkeypatch.setattr(built_mods, 'image_path', lambda config, gid, mod, name:
                        calls.append((gid, mod, name)) or file)
    url = '/api/mods/built/game/Bla%20face%20%C3%A9/image/previews/face.png'
    assert local_image(url, store=None, config=None, media_file=None, character_file=None)[1] == PNG
    assert calls == [('game', 'Bla face \u00e9', 'previews/face.png')]
