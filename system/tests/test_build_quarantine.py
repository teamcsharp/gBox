"""Broken ROM evidence is temporary, verified, and cannot be purged by closing a ticket alone."""
import copy
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import build_quarantine as Q
from gbox import filemods


class Memory:
    def __init__(self): self.docs = {}; self.lock = threading.RLock()
    def get(self, kind, key): return copy.deepcopy(self.docs.get((kind, key)))
    def put(self, kind, key, value): self.docs[kind, key] = copy.deepcopy(value)
    def all(self, kind): return [copy.deepcopy(v) for (k, _), v in self.docs.items() if k == kind]
    def audit(self, *args): pass


def setup(tmp_path):
    cfg = SimpleNamespace(cache=tmp_path)
    folder = filemods.mod_dir(cfg, 'game', 'bad')
    folder.mkdir(parents=True)
    (folder / '.gbox-mod.json').write_text('{"image":"game.iso"}')
    (folder / 'game.iso').write_bytes(b'broken game')
    store = Memory()
    r = {'key':'game/bad', 'game_id':'game', 'name':'bad', 'node':'PC', 'state':'preserved', 'request_id':'r'}
    a = Q.preserve(store, cfg, 'game', 'bad')
    r['archives'] = [a['id']]
    store.put(Q.KIND, r['key'], r)
    store.put('request', 'r', {'status':'open'})
    return cfg, store, folder, r, a


def test_purge_requires_analysis_resolution_and_completed_ticket(tmp_path):
    cfg, store, folder, r, a = setup(tmp_path)
    assert not Q.purge(store, cfg, r)
    store.put('request', 'r', {'status':'done'})
    assert not Q.purge(store, cfg, r), 'closing ticket must not destroy unexamined evidence'
    r['analysis'] = {'findings':'bad topology'}
    assert not Q.purge(store, cfg, r)
    r['analysis']['resolution'] = 'repaired topology; verified the replacement in game'
    assert Q.purge(store, cfg, r)
    assert not folder.exists() and not Path(a['path']).exists()
    assert store.get(Q.KIND, r['key'])['analysis'] == r['analysis']
    assert store.get(Q.EVIDENCE, a['id'])['deleted']


def test_archive_is_independent_and_repaired_same_name_survives(tmp_path):
    cfg, store, folder, r, a = setup(tmp_path)
    (folder / 'game.iso').write_bytes(b'repaired replacement')
    assert (Path(a['path']) / 'game.iso').read_bytes() == b'broken game'
    r['analysis'] = {'findings':'bad mesh', 'resolution':'repaired and verified'}
    store.put('request', 'r', {'status':'done'})
    assert Q.purge(store, cfg, r)
    assert (folder / 'game.iso').read_bytes() == b'repaired replacement'


def test_seal_rejects_corruption_and_extra_files(tmp_path):
    cfg, store, folder, r, a = setup(tmp_path)
    payload = Path(a['path']) / 'game.iso'
    payload.write_bytes(b'wrong bytes')
    with pytest.raises(ValueError, match='checksum'): Q.seal(store, cfg, a['id'])
    payload.write_bytes(b'broken game')
    (payload.parent / 'unexpected').write_bytes(b'x')
    with pytest.raises(ValueError, match='checksum'): Q.seal(store, cfg, a['id'])


def test_paths_cannot_escape_archive(tmp_path):
    cfg, store, folder, r, a = setup(tmp_path)
    for outside in [tmp_path, tmp_path.parent / 'outside']:
        with pytest.raises(ValueError): Q.safe_tree(tmp_path, outside)
    files = Q.manifest(folder)
    files[0]['path'] = '../escape'
    with pytest.raises(ValueError): Q.begin(store, cfg, 'game', 'bad', 'bad', files)


def test_upload_checks_hash_then_seals_and_running_build_defers_purge(tmp_path):
    cfg, store, folder, r, a = setup(tmp_path)
    # A local-only variant differs from Spark; upload only the missing exact file.
    (folder / 'game.iso').write_bytes(b'new evidence')
    rows = Q.manifest(folder)
    (folder / 'game.iso').write_bytes(b'broken game')
    app = FastAPI()
    tick = Q.routes(app, store, cfg, lambda:'operator', lambda *a:None, lambda:[], lambda:None)
    with TestClient(app) as c:
        got = c.post('/api/build-quarantine/archive', json={'game_id':'game','name':'bad','copy':'bad~local','files':rows})
        assert got.status_code == 200, got.text
        archive = got.json(); assert archive['missing'] == ['game.iso']
        url = f'/api/build-quarantine/{archive["id"]}'
        assert c.put(url+'/file/game.iso', content=b'bad').status_code == 422
        assert c.post(url+'/seal').status_code == 409
        assert c.put(url+'/file/game.iso', content=b'new evidence').status_code == 200
        assert c.post(url+'/seal').json()['sealed']
        assert c.put(url+'/file/game.iso', content=b'new evidence').status_code == 409
        assert c.post('/api/builds/game/bad/broken/analysis', json={'findings':'bad'}).status_code == 422
        assert c.post('/api/builds/game/bad/broken/analysis', json={'findings':'bad','resolution':'fixed and validated'}).status_code == 200
        store.put('request','r',{'status':'done'})
        store.put('session','s',{'state':'running','game_id':'game','mod':'bad~local'})
        tick(); assert folder.exists()
        store.put('session','s',{'state':'ended','game_id':'game','mod':'bad~local'})
        tick(); assert not folder.exists()


def test_worker_keeps_local_build_if_preservation_fails(tmp_path, monkeypatch):
    cfg, store, folder, r, a = setup(tmp_path)
    import httpx
    def fail(*a, **k): raise httpx.ConnectError('Spark unavailable')
    monkeypatch.setattr(httpx.Client, 'post', fail)
    ctx = SimpleNamespace(config=cfg, headers={}, server='http://spark', progress=lambda *a:None)
    with pytest.raises(httpx.ConnectError): Q.worker(ctx, 'game', 'bad', [])
    assert folder.exists()
    with pytest.raises(ValueError, match='running'): Q.worker(ctx, 'game', 'bad', ['bad'])
    assert folder.exists()


def test_mark_broken_reuses_ticket_exposes_card_and_blocks_manual_delete(tmp_path, monkeypatch):
    from gbox import hermes_task_mode
    from tests.test_builds import fixture, GID
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'hermes'))
    monkeypatch.setattr(hermes_task_mode, '_job', lambda: {'no_agent': True, 'enabled': True})
    cfg, app, store, headers = fixture(tmp_path)
    key = f'{GID}/g1_hack'
    store.put('build_report', key, {'key':key, 'id':'r7', 'number':7})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        r = c.post(f'/api/builds/{key}/broken', headers=headers, json={'node':'i9-NUC','note':'Model destroyed, game runs'})
        assert r.status_code == 200, r.text
        flag = r.json()
        assert flag['number'] == 7 and flag['request_id'] == 'r7'
        assert flag['state'] == 'preserved' and flag['archives']
        assert len(store.all('request')) == 1
        ticket = store.get('request', 'r7')
        assert ticket['status'] == 'open'
        assert any('findings and resolution' in m['text'] for m in ticket['messages'])
        assert c.post(f'/api/builds/{key}/delete', headers=headers, json={'scope':'all'}).status_code == 409
        assert c.post(f'/api/games/{GID}/launch?mod=g1_hack', headers=headers).status_code == 409
        assert c.post(f'/api/builds/{key}/local', headers=headers, json={'op':'download','node':'i9-NUC'}).status_code == 409
        items = c.get('/api/mods/built', headers=headers).json()['items']
        assert next(m for m in items if m['key'] == key)['broken']['number'] == 7
        again = c.post(f'/api/builds/{key}/broken', headers=headers, json={'node':'i9-NUC'})
        assert again.json()['request_id'] == 'r7' and len(store.all('request')) == 1
        assert not any(j.get('tool') in ('launch_game', 'session_swap') for j in store.all('job'))


def test_worker_verifies_spark_before_removing_local_payloads(tmp_path, monkeypatch):
    cfg, store, folder, r, a = setup(tmp_path / 'local')
    spark = SimpleNamespace(cache=tmp_path / 'spark')
    remote = Memory()
    events = []
    import httpx
    class Response:
        def __init__(self, value): self.value = value
        def raise_for_status(self): pass
        def json(self): return self.value
    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert folder.exists(), 'local deletion happened before preservation'
            if url.endswith('/archive'):
                return Response(Q.begin(remote, spark, json['game_id'], json['name'], json['copy'], json['files']))
            result = Q.seal(remote, spark, url.split('/')[-2])
            events.append('verified')
            return Response(result)
        def put(self, url, content):
            qid, rel = url.split('/build-quarantine/')[1].split('/file/')
            dst = Path(remote.get(Q.EVIDENCE, qid)['path']) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content.read())
            return Response({})
        def get(self, url):
            assert events == ['verified']
            return Response([])
    monkeypatch.setattr(httpx, 'Client', Client)
    ctx = SimpleNamespace(config=cfg, headers={}, server='http://spark', progress=lambda *a:None)
    result = Q.worker(ctx, 'game', 'bad', [])
    assert result['removed'] == ['bad'] and not folder.exists()
    archived = remote.get(Q.EVIDENCE, result['archives'][0])
    assert (Path(archived['path']) / 'game.iso').read_bytes() == b'broken game'


def test_retention_does_not_enqueue_deletion_of_unexamined_build(tmp_path):
    from gbox import build_retention as R
    app, store = FastAPI(), Memory()
    worker = {'id':'pc','name':'PC','os':'windows','online':True,'local_builds':[
        {'game_id':'g','name':'new','built':3}, {'game_id':'g','name':'bad','built':2},
        {'game_id':'g','name':'old','built':1}]}
    store.put(Q.KIND,'g/bad',{'key':'g/bad','state':'queued'})
    jobs = []
    def submit(req, actor): jobs.append(req); return {'id':str(len(jobs))}
    R.routes(app,store,lambda:'operator',submit,lambda:[worker])
    with TestClient(app) as c:
        assert c.post('/api/build-retention',json={'node':'PC','limit':1}).status_code == 200
    assert [j['input']['name'] for j in jobs] == ['old']
