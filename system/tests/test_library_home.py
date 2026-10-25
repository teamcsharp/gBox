"""Home joins existing evidence only; no ROM is launched, rewritten or fetched."""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from gbox import characters, library_home as H
from gbox.config import Config
from gbox.store import Store


class Index:
    version = 1

    def __init__(self):
        self.rows = []

    def records(self):
        return self.rows

    def status(self):
        return {'indexing': False}


@pytest.fixture
def home(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    store = Store(cfg.data_dir)
    app = FastAPI()
    app.state.built_mods = Index()

    def auth(authorization: str = Header('')):
        if authorization != 'Bearer test':
            raise HTTPException(401, 'Unauthorized')
        return 'you'

    root = characters.library_root(cfg)
    cache = {'entries': {}, 'refreshing': False, 'at': time.time()}
    monkeypatch.setitem(characters._LIST_CACHE, str(root), cache)
    H.routes(app, store, cfg, auth)
    data = app.state.library_home
    data.art_at = time.monotonic()
    data.characters_at = time.monotonic()
    store.upsert_catalog([
        {'game_id': 'mario', 'title': 'Super Mario Bros.', 'platform': 'nes', 'source_paths': ['C:/secret/original.nes'],
         'rel_path': 'secret/original.nes', 'favorite': True, 'last_played': 100,
         'media': {'boxart': ['private/boxart'], 'cabinet': ['private/cabinet'], 'flyer': ['private/flyer'],
                   'poster': ['private/poster'], 'promotional': ['private/promo'], 'video': ['private/video']}, 'format': 'nes'},
        {'game_id': 'pso', 'title': 'Phantasy Star Online', 'platform': 'gamecube', 'source_paths': [], 'format': 'iso'},
        {'game_id': 'sonic', 'title': 'Sonic the Hedgehog 2', 'platform': 'genesis', 'source_paths': [], 'format': 'bin'},
    ])
    store.put('worker', 'old', {'name': 'JAY', 'local_builds': []})
    store.put('worker_alias', 'retired', {'name': 'i9-NUC', 'to': 'current'})
    client = TestClient(app, headers={'Authorization': 'Bearer test'})
    return SimpleNamespace(store=store, app=app, data=data, client=client, cfg=cfg, models=cache['entries'])


def session(home, sid, gid='pso', **extra):
    home.store.put('session', sid, {'session_id': sid, 'game_id': gid, 'started': 200, 'ended': 250, 'state': 'ended', **extra})


def model(home, slug='hucast', gid='pso', **extra):
    home.models[slug] = {'slug': slug, 'name': 'HUcast', 'source': {'game_id': gid, 'files': ['C:/secret/source.bin']},
        'model': 'model.glb', 'stats': {'vertices': 123, 'triangles': 456}, 'added': 300, **extra}


def build(home, gid='pso', name='bla_all', **extra):
    home.app.state.built_mods.rows.append({'game_id': gid, 'name': name, 'size': 1048576,
        'meta': {'title': 'Bla faces', 'built': 400, 'character': 'bla', 'slot': 'all', 'files': ['C:/private/disc.gdi'], **extra},
        'images': ['before.png', 'sub/after.png', '../secret.png', 'C:/secret.png']})


def test_recent_order_counts_operator_plays_and_device_history(home):
    session(home, 'old-one')
    session(home, 'retired-two', started=600, ended=650, collection_mod='bla_all~staged')
    session(home, 'old-agent', gid='sonic', started=900)
    home.store.put('job', 'agent', {'tool': 'launch_game', 'agent_use': True, 'output': {'session_id': 'old-agent'}})
    session(home, 'old-capture', gid='sonic', started=1000, detail={'capture_session': {'for': 'old-one'}})
    session(home, 'old-owned', gid='mario', started=500)
    home.store.put('slabel', 'old-owned', {'owner': 'you'})
    home.store.put('job', 'owned', {'tool': 'launch_game', 'actor': 'agent', 'agent_use': True})
    rows = home.client.get('/api/home/games').json()['items']
    assert [row['game_id'] for row in rows] == ['pso', 'mario', 'sonic']
    pso, mario, sonic = rows
    assert (pso['plays'], pso['last_played'], pso['last_device']) == (2, 600, 'i9-NUC')
    assert pso['devices'] == [{'name': 'i9-NUC', 'plays': 1, 'last_played': 600}, {'name': 'JAY', 'plays': 1, 'last_played': 200}]
    assert mario['plays'] == 1 and sonic['plays'] == 0 and sonic['last_played'] is None
    detail = home.client.get('/api/home/games/pso').json()
    assert detail['activity'][0]['mod'] == 'bla_all'
    assert detail['counts']['sessions'] == 2


def test_ps4_package_status_reaches_home_without_private_paths(home):
    home.store.upsert_catalog([{'game_id': 're5-ps4', 'title': 'Resident Evil 5', 'platform': 'ps4',
        'format': 'ps4_pkg', 'playable': 'copy_incomplete', 'source_paths': ['C:/private/RE5.pkg'],
        'launch': {'kind': 'ps4_package', 'path': 'C:/private/RE5.pkg'}}])
    row = home.client.get('/api/home/games/re5-ps4').json()['game']
    assert row['format'] == 'ps4_pkg' and row['playable'] == 'copy_incomplete'
    assert 'C:/private' not in json.dumps(row)


def test_search_filters_sorting_and_bounded_paging(home):
    build(home)
    session(home, 'old-one', gid='sonic', started=600)
    session(home, 'old-two', gid='sonic', started=700)
    session(home, 'old-three', gid='pso', started=800)
    response = home.client.get('/api/home/games?sort=plays&limit=1&offset=1').json()
    assert response['total'] == 3 and response['has_more'] is True
    assert [r['game_id'] for r in response['items']] == ['pso']
    assert home.client.get('/api/home/games?has_mods=true').json()['items'][0]['game_id'] == 'pso'
    assert home.client.get('/api/home/games?favorites=true').json()['total'] == 1
    assert home.client.get('/api/home/games?platform=nes&q=super+mar').json()['total'] == 1
    assert home.client.get('/api/home/games?q=nosuchtitle').json()['total'] == 0
    assert home.client.get('/api/home/games?sort=title').json()['items'][0]['game_id'] == 'pso'
    assert home.client.get('/api/home/games?sort=updated').json()['items'][0]['game_id'] == 'pso'
    for query in ('limit=0', 'limit=121', 'offset=-1', 'sort=DROP%20TABLE'):
        assert home.client.get('/api/home/games?' + query).status_code == 422


def test_detail_returns_real_models_builds_reports_and_chronology(home):
    model(home)
    model(home, slug='bad', model='../private.glb')
    model(home, slug='sonic', gid='sonic', model='sheet.png', kind='sprites')
    build(home, requests=[12])
    home.store.put('request', 'r12', {'number': 12, 'title': 'Adjust the eyes', 'status': 'done', 'created': 450,
        'completed': 550, 'context': {}, 'messages': [{'text': 'private thread payload'}]})
    home.store.put('request', 'r13', {'number': 13, 'title': 'Check boots', 'status': 'open', 'created': 500,
        'context': {'game_id': 'pso'}})
    session(home, 'old-one', started=600)
    response = home.client.get('/api/home/games/pso')
    assert response.status_code == 200
    data = response.json()
    assert data['counts'] == {'models': 1, 'builds': 1, 'reports': 2, 'sessions': 1}
    assert data['models'][0] == {'slug': 'hucast', 'name': 'HUcast', 'kind': 'character',
        'model_url': '/api/characters/hucast/file/model.glb', 'preview_url': '/api/characters/hucast/preview',
        'format': 'glb', 'model': 'model.glb', 'file': 'model.glb', 'vertices': 123, 'triangles': 456,
        'source_game_id': 'pso', 'extracted_at': 300}
    assert data['builds'][0]['changes'] == [{'slot': 'all', 'donor': 'bla'}]
    assert data['builds'][0]['available_on'] == ['Spark collection']
    assert [image['url'] for image in data['builds'][0]['images']] == [
        '/api/mods/built/pso/bla_all/image/before.png', '/api/mods/built/pso/bla_all/image/sub/after.png']
    assert [item['kind'] for item in data['timeline']] == ['session', 'report', 'report', 'build', 'model']
    assert data['progress'] == {'status': 'idle', 'active_jobs': [], 'model_url': '/api/characters/hucast/file/model.glb'}
    text = response.text
    assert 'C:/secret' not in text and 'C:/private' not in text and 'private thread payload' not in text


def test_media_uses_known_artwork_and_actual_game_capture_artifacts(home):
    session(home, 'old-one', gid='mario')
    frame = home.store.put_artifact(b'png', 'screenshot.png', 'image/png', {'session': 'old-one'})
    clip = home.store.put_artifact(b'mp4', 'run.mp4', 'video/mp4', {'game': 'mario', 'ts': 500})
    covered = home.store.put_artifact(b'covered', 'desktop.png', 'image/png', {'game_id': 'mario', 'covered': 1})
    wrong = home.store.put_artifact(b'other', 'other.mp4', 'video/mp4', {'game': 'pso'})
    unrelated = home.store.put_artifact(b'selfie', 'selfie.jpg', 'image/jpeg', {'photo_skin_source': True})
    result = home.client.get('/api/home/games/mario').json()
    urls = [item['url'] for item in result['media']]
    assert f'/api/artifacts/{frame.sha256}' in urls and f'/api/artifacts/{clip.sha256}' in urls
    assert all(f'/api/artifacts/{art.sha256}' not in urls for art in (covered, wrong, unrelated))
    assert {item['label'] for item in result['media'] if item['source'] == 'art'} == {'Boxart', 'Cabinet', 'Flyer', 'Poster', 'Promotional'}
    assert not any('/video' in url or 'private/' in url for url in urls)
    assert next(item for item in result['media'] if item['url'].endswith(clip.sha256))['kind'] == 'video'


def test_frame_heavy_capture_does_not_hide_gameplay_video(home):
    clip = home.store.put_artifact(b'clip', 'clip.mp4', 'video/mp4', {'game_id': 'pso'})
    for i in range(25):
        home.store.put_artifact(str(i).encode(), 'frame.png', 'image/png', {'game_id': 'pso'})
    media = home.client.get('/api/home/games/pso').json()['media']
    assert len(media) == 13
    assert any(item['url'].endswith(clip.sha256) and item['kind'] == 'video' for item in media)


def test_local_builds_and_missing_card_builds_report_availability_honestly(home):
    home.store.put('worker', 'old', {'name': 'JAY', 'local_builds': [{'game_id': 'pso', 'name': 'local', 'built': 400},
        {'game_id': 'pso', 'name': 'local~staging_copy', 'staged_of': 'local', 'built': 500}]})
    home.store.put('mod', 'card', {'game_id': 'pso', 'title': 'Unavailable historical build', 'ts': 200,
        'calls': [{'tool': '@launch', 'input': {'mod': 'old_build'}}]})
    data = home.client.get('/api/home/games/pso').json()
    builds = {b['name']: b for b in data['builds']}
    assert data['game']['mods_count'] == 2
    assert builds['local']['available'] is True and builds['local']['available_on'] == ['JAY']
    assert builds['old_build']['available'] is False and builds['old_build']['available_on'] == []


def test_progress_is_actual_title_scoped_and_never_contains_logs_or_paths(home):
    session(home, 'old-one')
    for id, data in [('j1', {'game_id': 'pso'}), ('j2', {'session_id': 'old-one'}), ('j3', {'game_id': 'mario'})]:
        home.store.put('job', id, {'tool': 'characters', 'input': data, 'state': 'running', 'created': 200, 'started': 300,
            'progress': {'pct': 37, 'msg': 'Reading C:/private/model.glb'}, 'progress_log': ['private log']})
    response = home.client.get('/api/home/games/pso')
    progress = response.json()['progress']
    assert progress['status'] == 'running' and {j['id'] for j in progress['active_jobs']} == {'j1', 'j2'}
    assert all(j['progress'] == 37 for j in progress['active_jobs'])
    assert 'C:/private' not in response.text and 'private log' not in response.text


def test_auth_unknown_ids_and_read_only_contract(home):
    assert home.client.get('/api/home/games', headers={'Authorization': ''}).status_code == 401
    assert home.client.get('/api/home/games/pso', headers={'Authorization': ''}).status_code == 401
    for gid in ('unknown', 'bad:id', 'bad%5Cpath'):
        assert home.client.get('/api/home/games/' + gid).status_code == 404
    assert home.client.post('/api/home/games/pso').status_code == 405
    before = home.store.db.total_changes
    data = home.client.get('/api/home/games/sonic').json()
    assert data['models'] == data['builds'] == data['reports'] == data['activity'] == data['timeline'] == data['media'] == []
    assert data['progress'] == {'status': 'idle', 'active_jobs': [], 'model_url': None}
    assert home.store.db.total_changes == before


def test_character_cache_warms_asynchronously_and_refreshes_without_folder_walk(home, monkeypatch):
    root = str(characters.library_root(home.cfg))
    monkeypatch.delitem(characters._LIST_CACHE, root)
    warmed = threading.Event()
    request_thread = threading.get_ident()

    def refresh(root):
        assert threading.get_ident() != request_thread
        warmed.set()

    monkeypatch.setattr(characters, 'list_all', refresh)
    home.data.characters_at = 0
    assert home.client.get('/api/home/games').json()['indexing'] is True
    assert warmed.wait(1)
    monkeypatch.setitem(characters._LIST_CACHE, root, {'entries': home.models, 'refreshing': False})
    model(home)
    monkeypatch.setattr(characters, 'LIST_GENERATION', characters.LIST_GENERATION + 1)
    assert home.client.get('/api/home/games/pso').json()['game']['models_count'] == 1


def test_short_snapshot_ttl_refreshes_reports_and_activity(home, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(H.time, 'monotonic', lambda: now[0])
    assert home.client.get('/api/home/games/pso').json()['game']['plays'] == 0
    session(home, 'old-new', started=1000)
    home.store.put('request', 'new-report', {'title': 'New report', 'created': 1200, 'context': {'game_id': 'pso'}})
    assert home.client.get('/api/home/games/pso').json()['game']['plays'] == 0
    now[0] += H.TTL + .01
    data = home.client.get('/api/home/games/pso').json()
    assert data['game']['plays'] == 1 and data['game']['reports_count'] == 1


def test_large_library_decodes_only_the_requested_page(home, monkeypatch):
    entries = [(f'g{i:06}', None, f'Game {i:06}', 'nes', '', '', json.dumps({
        'game_id': f'g{i:06}', 'title': f'Game {i:06}', 'platform': 'nes', 'source_paths': ['private/path']})) for i in range(64000)]
    with home.store.lock:
        home.store.db.executemany('INSERT INTO catalog VALUES(?,?,?,?,?,?,?)', entries)
        home.store.db.commit()
    monkeypatch.setattr(home.store, 'all', lambda *_: pytest.fail('Do not decode complete archives or catalogs'))
    calls = []
    original = home.data.game

    def count(row, snapshot, art):
        calls.append(row['game_id'])
        return original(row, snapshot, art)

    monkeypatch.setattr(home.data, 'game', count)
    start = time.monotonic()
    response = home.client.get('/api/home/games?sort=title&limit=24&offset=200')
    elapsed = time.monotonic() - start
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 64003 and len(calls) == 24
    assert elapsed < 5, f'Bounded 64k library page took {elapsed:.2f}s'


def test_mod_feed_lists_individual_builds_newest_first_and_scopes_play_history(home):
    build(home, name='old_mod', title='Older Bla faces', built=100)
    build(home, name='new_mod', title='Newest Bla faces', built=800)
    build(home, gid='mario', name='sonic_mario', title='Sonic replaces Mario', built=500)
    build(home, name='undated', title='Undated build', built=None)
    session(home, 'old-original', started=5000)
    session(home, 'old-oldmod', started=4500, mod='old_mod')
    session(home, 'old-newmod', started=900, mod='new_mod')
    session(home, 'retired-staged', started=1000, collection_mod='new_mod~staging', mod='other_value')
    session(home, 'old-agentmod', started=1100, mod='new_mod', agent_use=True)
    data = home.client.get('/api/home/mods').json()
    assert data['feed'] == 'mods' and data['total'] == 4
    assert [row['mod_name'] for row in data['items']] == ['new_mod', 'sonic_mario', 'old_mod', 'undated']
    row = data['items'][0]
    assert (row['key'], row['game_id'], row['title'], row['game_title']) == (
        'pso/new_mod', 'pso', 'Newest Bla faces', 'Phantasy Star Online')
    assert row['plays'] == 2 and row['last_played'] == 1000 and row['last_device'] == 'i9-NUC'
    assert row['mods_count'] == 0 and row['is_mod'] is True and row['launch_node'] == 'auto'
    assert row['available_on'] == ['Spark collection']
    assert [d['name'] for d in row['devices']] == ['i9-NUC', 'JAY']
    assert home.client.get('/api/home/mods?sort=plays').json()['items'][0]['mod_name'] == 'new_mod'
    assert [r['mod_name'] for r in home.client.get('/api/home/mods?sort=updated').json()['items']] == [
        'new_mod', 'sonic_mario', 'old_mod', 'undated']


def test_mod_feed_searches_build_and_parent_titles_with_filters_and_paging(home):
    build(home, name='pso_bla', title='Bla faces', built=800)
    build(home, gid='mario', name='sonic_mario', title='Sonic replaces Mario', built=500)
    build(home, gid='mario', name='bla_mario', title='Bla replaces Mario', built=300)
    assert home.client.get('/api/home/mods?q=phantasy+bla').json()['total'] == 1
    assert home.client.get('/api/home/mods?q=SONIC').json()['items'][0]['key'] == 'mario/sonic_mario'
    assert home.client.get('/api/home/mods?favorites=true').json()['total'] == 2
    assert home.client.get('/api/home/mods?platform=gamecube').json()['total'] == 1
    assert home.client.get('/api/home/mods?q=absent').json()['total'] == 0
    page = home.client.get('/api/home/mods?limit=1&offset=1').json()
    assert page['total'] == 3 and page['has_more'] is True and page['items'][0]['mod_name'] == 'sonic_mario'
    assert home.client.get('/api/home/mods?sort=title').json()['items'][0]['title'] == 'Bla faces'


def test_mod_feed_excludes_missing_historical_cards_and_routes_local_builds_to_actual_worker(home):
    home.store.put('mod', 'missing', {'game_id': 'pso', 'title': 'Gone build', 'ts': 999,
        'calls': [{'tool': '@launch', 'input': {'mod': 'gone'}}]})
    home.store.put('worker', 'old', {'name': 'JAY', 'last_seen': 100,
        'local_builds': [{'game_id': 'pso', 'name': 'local~copy', 'staged_of': 'local', 'built': 500}]})
    home.store.put('worker', 'new', {'name': 'i9-NUC', 'last_seen': 200,
        'local_builds': [{'game_id': 'pso', 'name': 'local', 'built': 500}]})
    data = home.client.get('/api/home/mods').json()
    assert data['total'] == 1
    row = data['items'][0]
    assert row['key'] == 'pso/local' and row['launch_node'] == 'i9-NUC'
    assert row['available_on'] == ['JAY', 'i9-NUC']
    assert len(home.client.get('/api/home/games/pso').json()['builds']) == 2


def test_mod_feed_play_history_uses_the_current_live_build(home):
    build(home, name='boot_build')
    build(home, name='live_build')
    session(home, 'old-live', mod='boot_build~staged', collection_mod='boot_build', live_mod='live_build~preview')
    rows = {row['mod_name']: row for row in home.client.get('/api/home/mods').json()['items']}
    assert rows['live_build']['plays'] == 1 and rows['boot_build']['plays'] == 0
    assert home.client.get('/api/home/games/pso').json()['activity'][0]['mod'] == 'live_build'


def test_mod_feed_uses_build_art_capture_and_donor_preview_without_unrelated_gameplay(home):
    model(home, slug='bla', gid='pso')
    build(home, gid='mario', name='bla', title='Bla Mario', character='bla')
    clip = home.store.put_artifact(b'build clip', 'build.mp4', 'video/mp4', {'game_id': 'mario'})
    shot = home.store.put_artifact(b'build shot', 'shot.png', 'image/png', {'game_id': 'mario'})
    unrelated = home.store.put_artifact(b'other gameplay', 'other.png', 'image/png', {'game_id': 'mario'})
    home.store.put('mod', 'm', {'game_id': 'mario', 'title': 'Bla Mario', 'video': clip.sha256, 'thumb': shot.sha256,
        'calls': [{'tool': '@launch', 'input': {'mod': 'bla'}}]})
    response = home.client.get('/api/home/mods')
    row = response.json()['items'][0]
    assert row['poster_url'] == '/api/mods/built/mario/bla/image/before.png'
    urls = {item['url'] for item in row['media']}
    assert '/api/characters/bla/preview' in urls
    assert f'/api/artifacts/{clip.sha256}' in urls and f'/api/artifacts/{shot.sha256}' in urls
    assert f'/api/artifacts/{unrelated.sha256}' not in urls
    assert '/api/media/mario/boxart' in urls and 'C:/private' not in response.text
    assert [item['kind'] for item in row['media']].count('video') == 1


def test_mod_feed_donor_and_parent_art_fallbacks_and_missing_catalog_title(home):
    model(home, slug='bla')
    home.app.state.built_mods.rows.extend([
        {'game_id': 'pso', 'name': 'bla', 'meta': {'built': 500, 'character': 'bla'}},
        {'game_id': 'mario', 'name': 'plain', 'meta': {'built': 400}},
        {'game_id': 'unknown_alias', 'name': 'local_mod', 'meta': {'built': 300, 'title': 'Alias build', 'game_title': 'Original game title'}},
    ])
    rows = home.client.get('/api/home/mods').json()['items']
    assert rows[0]['poster_url'] == '/api/characters/bla/preview'
    assert rows[1]['poster_url'].startswith('/api/media/mario/')
    assert rows[2]['game_title'] == 'Original game title' and rows[2]['title'] == 'Alias build'


def test_mod_feed_auth_validation_and_decodes_only_paged_titles(home, monkeypatch):
    for index in range(200):
        build(home, name=f'variant_{index}', title=f'Variant {index}', built=index + 1)
    build(home, gid='mario', name='mario', built=300)
    calls = []
    original = home.store.catalog_get

    def get(gid):
        calls.append(gid)
        return original(gid)

    monkeypatch.setattr(home.store, 'catalog_get', get)
    data = home.client.get('/api/home/mods?limit=10&offset=5').json()
    assert data['total'] == 201 and len(data['items']) == 10 and calls == ['pso']
    assert home.client.get('/api/home/mods', headers={'Authorization': ''}).status_code == 401
    for query in ('limit=0', 'limit=121', 'offset=-1', 'sort=unknown'):
        assert home.client.get('/api/home/mods?' + query).status_code == 422
