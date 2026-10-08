from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from gbox import characters as C
from gbox.character_collection import AutoCollection
from gbox.store import Store


def test_launch_collection_deduplicates_and_keeps_operator_parent(tmp_path):
    store = Store(tmp_path)
    automatic = AutoCollection(store, None)
    store.put('setting', 'auto_character_collection', {'enabled': True, 'parent_request_id': 'operator-root'})
    game = {'game_id': 'mario', 'title': 'Super Mario 64', 'platform': 'n64'}
    submitted = []
    def submit(request):
        submitted.append(request)
        job = {'id': 'collection-job', 'state': 'queued', **request}
        store.put('job', job['id'], job)
        return job
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: automatic.after_launch({'input': {'game': game}}, {'session_id': 'w-1'}, submit), range(16)))
    assert len(submitted) == 1
    assert submitted[0]['parent_request_id'] == 'operator-root'
    assert submitted[0]['require_os'] == 'linux'
    assert not store.all('request')
    store.put('job', 'collection-job', {'id': 'collection-job', 'state': 'succeeded',
              'output': {'result': {'status': 'partial', 'collected': 1, 'total': 2}}})
    assert automatic.status('mario')['result']['status'] == 'partial'
    automatic.after_launch({'input': {'game': game}}, {}, submit)
    assert len(submitted) == 1  # partial extraction never loops each launch


def test_disabled_and_unsupported_do_not_queue(tmp_path):
    store = Store(tmp_path)
    automatic = AutoCollection(store, None)
    def unexpected(_):
        raise AssertionError('should not queue')
    game = {'game_id': 'unknown', 'title': 'Unknown', 'platform': 'n64'}
    automatic.after_launch({'input': {'game': game}}, {}, unexpected)
    assert automatic.status('unknown')['state'] == 'unsupported'
    store.put('setting', 'auto_character_collection', {'enabled': False})
    game = {'game_id': 'mario', 'title': 'Super Mario 64', 'platform': 'n64'}
    automatic.after_launch({'input': {'game': game}}, {}, unexpected)
    assert automatic.status('mario')['state'] == 'not_started'


def test_collect_reports_failed_and_unrigged_models(monkeypatch, tmp_path):
    game = {'game_id': 'fixture', 'title': 'Fixture', 'platform': 'test'}
    entries = [{'slug': s, 'name': s, 'aliases': []} for s in ('good', 'unrigged', 'broken')]
    entries.append({'slug': 'vehicle', 'name': 'vehicle', 'kind': 'vehicle'})
    monkeypatch.setattr(C, 'DEDICATED', [('fixture', lambda t,p: True, lambda: entries, None)])
    monkeypatch.setattr(C, '_game', lambda ctx, inp: game)
    monkeypatch.setattr(C, 'library_root', lambda cfg: tmp_path)
    called = []
    def extract(ctx, game, slug, root, prepared):
        called.append(slug)
        if slug == 'broken':
            raise ValueError('corrupt native model')
        return {'status': 'in_collection', 'entry': {'slug': slug}}
    monkeypatch.setattr(C, 'extract_dedicated', extract)
    monkeypatch.setattr(C, 'get', lambda root, slug: {'slug': slug, 'name': slug,
                         'rig': {'roles': {'hip': 'hip'}} if slug == 'good' else {}})
    monkeypatch.setattr(C, 'verify_entry', lambda root, meta: {'ok': True})
    ctx = SimpleNamespace(config=None, progress=lambda *args: None)
    result = C.collect(ctx, C.CharIn(op='collect'))
    assert called == ['good', 'unrigged', 'broken']
    assert result['status'] == 'partial'
    assert result['collected'] == 2 and result['retargetable'] == 1
    assert result['entries'][2]['error'] == 'corrupt native model'
    entries[:] = entries[:2]
    assert C.collect(ctx, C.CharIn(op='collect'))['status'] == 'partial'  # all meshes exist, one lacks a rig


def test_policy_api_does_not_match_character_slug(plane):
    response = plane.get('/api/character-collection/policy')
    assert response.status_code == 200 and response.json()['enabled']
    assert plane.post('/api/character-collection/policy', json={'parent_request_id': 'missing'}).status_code == 422
    assert plane.post('/api/character-collection/policy', json={'enabled': False}).status_code == 200


def test_successful_launch_result_schedules_collection_on_control_plane(tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    game = {'game_id': 'sm64', 'title': 'Super Mario 64', 'platform': 'n64',
            'source_paths': ['mario.z64'], 'format': 'z64', 'profile_id': 'sm64'}
    app.state.store.upsert_catalog([game])
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {cfg.token()}'
        client.post('/api/workers/register', json={'id':'windows-worker', 'name':'Windows',
                    'os':'windows', 'tools':['launch_game']}).raise_for_status()
        launch = client.post('/api/jobs', json={'tool':'launch_game', 'input':{'game':game},
                    'require_worker':'windows-worker', 'parent_request_id':'operator-parent'}).json()
        assert client.post('/api/workers/windows-worker/claim').json()['id'] == launch['id']
        accepted = client.post('/api/workers/windows-worker/result', json={'job_id':launch['id'],
                    'ok':True, 'output':{'session_id':'windows-worker-1', 'adapter':'retroarch',
                    'capabilities':{}, 'detail':{'_game':{'game_id':game['game_id'], 'title':game['title']}}}})
        assert accepted.json()['state'] == 'succeeded'
        jobs = app.state.store.all('job')
        collection = next(j for j in jobs if j['tool'] == 'characters')
        assert collection['input']['op'] == 'collect'
        assert collection['require_os'] == 'linux' and collection['require_worker'] is None
        assert collection['parent_request_id'] == 'operator-parent'
        assert client.get('/api/games/sm64/roster').json()['collection']['job_id'] == collection['id']


def test_parallel_builds_preserve_all_character_targets(plane, cfg):
    import json
    root = C.library_root(cfg)
    C.put_meta(root, {'slug': 'shared', 'targets': {}})
    def save_target(i):
        response = plane.post('/api/characters/shared/targets', json={
            'game_id': f'game-{i}', 'slot':'player', 'mod':f'mod-{i}', 'nodes':['linux']})
        assert response.status_code == 200, response.text
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save_target, range(24)))
    meta = json.loads((root / 'shared' / 'meta.json').read_text())
    assert len(meta['targets']) == 24
