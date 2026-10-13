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


def test_favoriting_schedules_one_background_roster_without_launching(tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    game = {'game_id': 'sm64', 'title': 'Super Mario 64', 'platform': 'n64',
            'source_paths': ['mario.z64'], 'format': 'z64', 'profile_id': 'sm64'}
    store.upsert_catalog([game])
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {cfg.token()}'
        off = client.post('/api/catalog/sm64/favorite?on=false').json()
        assert off['collection']['state'] == 'not_started'
        first = client.post('/api/catalog/sm64/favorite').json()
        second = client.post('/api/catalog/sm64/favorite').json()
        jobs = [j for j in store.all('job') if j['tool'] == 'characters']
        assert first['collection']['job_id'] == second['collection']['job_id'] == jobs[0]['id']
        assert len(jobs) == 1 and jobs[0]['input']['op'] == 'collect'
        assert jobs[0]['require_os'] == 'linux' and not store.all('session')
        failed = store.get('job', jobs[0]['id'])
        failed['state'] = 'failed'
        failed['error'] = 'worker restarted'
        store.put('job', failed['id'], failed)
        retry = client.post('/api/catalog/sm64/favorite').json()
        assert retry['collection']['job_id'] != failed['id']
        assert len([j for j in store.all('job') if j['tool'] == 'characters']) == 2


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


def test_collect_counts_sprite_sets_as_done_without_a_rig(monkeypatch, tmp_path):
    """A 2D reader's roster says character but its stored meta says sprites (tetris_ds): no rig is ever expected."""
    game = {'game_id': 'fixture', 'title': 'Fixture', 'platform': 'test'}
    entries = [{'slug': 'sheet', 'name': 'sheet', 'aliases': []}]
    monkeypatch.setattr(C, 'DEDICATED', [('fixture', lambda t, p: True, lambda: entries, None)])
    monkeypatch.setattr(C, '_game', lambda ctx, inp: game)
    monkeypatch.setattr(C, 'library_root', lambda cfg: tmp_path)
    monkeypatch.setattr(C, 'extract_dedicated',
                        lambda ctx, game, slug, root, prepared: {'status': 'in_collection', 'entry': {'slug': slug}})
    monkeypatch.setattr(C, 'get', lambda root, slug: {'slug': slug, 'name': slug, 'kind': 'sprites', 'rig': {'roles': {}}})
    monkeypatch.setattr(C, 'verify_entry', lambda root, meta: {'ok': True})
    ctx = SimpleNamespace(config=None, progress=lambda *args: None)
    result = C.collect(ctx, C.CharIn(op='collect'))
    assert result['status'] == 'complete' and result['characters'] == 0 and result['collected'] == 1
    assert result['entries'][0]['kind'] == 'sprites' and result['entries'][0]['message'] == ''


def test_sprite_preview_of_a_small_sheet_passes_check_preview(tmp_path):
    """Tiny sheets are enlarged pixel-exact so check_preview judges the sprites, not the empty canvas."""
    from PIL import Image, ImageDraw
    sheet = Image.new('RGBA', (64, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for i, colour in enumerate(((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255))):
        draw.rectangle([i * 8, 0, i * 8 + 7, 7], fill=colour)
    sheet.save(tmp_path / 'sheet.png')
    C._sprite_preview(tmp_path / 'sheet.png', tmp_path / 'preview.png')
    assert Image.open(tmp_path / 'preview.png').size == (384, 384)
    assert C.check_preview(tmp_path / 'preview.png')['ok']


def test_collect_scales_each_extractor_progress_across_roster(monkeypatch, tmp_path):
    game = {'game_id': 'fixture', 'title': 'Fixture', 'platform': 'test'}
    entries = [{'slug': s, 'name': s, 'aliases': []} for s in ('first', 'second')]
    monkeypatch.setattr(C, 'DEDICATED', [('fixture', lambda t, p: True, lambda: entries, None)])
    monkeypatch.setattr(C, '_game', lambda ctx, inp: game)
    monkeypatch.setattr(C, 'library_root', lambda cfg: tmp_path)
    def extract(ctx, game, slug, root, prepared):
        ctx.progress(20, 'extracting')
        ctx.progress(85, 'preview')
        return {'status': 'in_collection', 'entry': {'slug': slug}}
    monkeypatch.setattr(C, 'extract_dedicated', extract)
    monkeypatch.setattr(C, 'get', lambda root, slug: {'slug': slug, 'name': slug, 'rig': {'roles': {'hip': 'hip'}}})
    monkeypatch.setattr(C, 'verify_entry', lambda root, meta: {'ok': True})
    events = []
    ctx = SimpleNamespace(config=None, progress=lambda pct, msg: events.append((pct, msg)))
    assert C.collect(ctx, C.CharIn(op='collect'))['status'] == 'complete'
    assert [pct for pct, _ in events] == [0, 10, 42.5, 50, 60, 92.5, 100]
    assert 'second (2/2): preview' in events[-2][1]


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


def test_list_all_skips_entries_without_a_name(tmp_path):
    """A 'shared' folder holding only slug + targets made every /api/characters call 500 (2026-10-13)."""
    import json
    from gbox import characters as C
    (tmp_path / "shared").mkdir(); (tmp_path / "shared" / "meta.json").write_text(json.dumps({"slug": "shared", "targets": {}}))
    (tmp_path / "sonic").mkdir(); (tmp_path / "sonic" / "meta.json").write_text(json.dumps({"slug": "sonic", "name": "Sonic"}))
    assert [m["slug"] for m in C.list_all(tmp_path)] == ["sonic"]

