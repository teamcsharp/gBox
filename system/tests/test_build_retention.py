import json
import os
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import build_retention as R


def build(cfg, game, name, created):
    folder = cfg.cache / 'mods' / game / name
    folder.mkdir(parents=True)
    (folder / '.gbox-mod.json').write_text(json.dumps({'created': created}))
    (folder / 'game.bin').write_bytes(bytes(100))
    return folder


def test_default_three_and_per_game_override_keep_newest_created_not_downloaded(cfg):
    for g in ('a', 'b'):
        for i in range(5): build(cfg, g, f'b{i}', i + 1)
    result = R.apply(cfg, {'games': {'b': 1}}, dry_run=True)
    assert len(result['remove']) == 6 and not result['removed']
    assert len(R.inventory(cfg)) == 10
    result = R.apply(cfg, {'games': {'b': 1}})
    assert len(result['removed']) == 6 and result['freed_bytes'] >= 600
    assert {(r['game_id'], r['name']) for r in R.inventory(cfg)} == {('a', 'b2'), ('a', 'b3'), ('a', 'b4'), ('b', 'b4')}


def test_running_old_build_is_protected_and_saves_and_unmarked_folders_survive(cfg):
    old = build(cfg, 'a', 'old~1', 1)
    (old / '.gbox-staged-of').write_text('old')
    build(cfg, 'a', 'new', 2)
    unmarked = cfg.cache / 'mods/a/incomplete'; unmarked.mkdir()
    (unmarked / 'partial').write_text('pending download')
    saves = cfg.cache / 'states'; saves.mkdir(); (saves / 'game.s01').write_text('save')
    result = R.apply(cfg, {'default': 1}, busy={('a', 'old')})
    assert not result['removed'] and len(result['protected']) == 1
    assert old.exists() and unmarked.exists() and (saves / 'game.s01').read_text() == 'save'


def test_shared_files_do_not_claim_freed_bytes_and_linked_build_is_refused(cfg, monkeypatch):
    old = build(cfg, 'a', 'old', 1)
    new = build(cfg, 'a', 'new', 2)
    os.link(old / 'game.bin', new / 'shared.bin')
    real = R.linked
    monkeypatch.setattr(R, 'linked', lambda p: p.name == 'game.bin' or real(p))
    result = R.apply(cfg, {'default': 1})
    assert not result['removed'] and result['errors'] and old.exists()
    monkeypatch.setattr(R, 'linked', real)
    result = R.apply(cfg, {'default': 1})
    assert result['freed_bytes'] < 100
    assert (new / 'shared.bin').read_bytes() == bytes(100)


def test_changed_build_is_not_deleted(cfg, monkeypatch):
    old = build(cfg, 'a', 'old', 1); build(cfg, 'a', 'new', 2)
    original = R.plan
    def changed(*a, **kw):
        result = original(*a, **kw)
        (old / '.gbox-mod.json').write_text('{}')
        return result
    monkeypatch.setattr(R, 'plan', changed)
    assert R.apply(cfg, {'default': 1})['errors'] and old.exists()


def test_policy_defaults_are_per_pc_and_invalid_limits_never_queue():
    class Store:
        lock = threading.RLock()
        def __init__(self): self.rows = {}
        def get(self, k, n): return self.rows.get((k, n))
        def put(self, k, n, v): self.rows[k, n] = v
        def all(self, k): return [v for (kind, n), v in self.rows.items() if kind == k]
        def audit(self, *a): pass
    store, app, jobs = Store(), FastAPI(), []
    workers = lambda: [{'id': 'w', 'name': 'PC', 'os': 'windows', 'online': True, 'local_builds':
                        [{'game_id':'a','name':f'b{i}','built':i} for i in range(4)]},
                       {'id': 's', 'name': 'Spark', 'os': 'linux', 'online': True}]
    def submit(j, actor): jobs.append(j); return {'id': str(len(jobs))}
    R.routes(app, store, lambda: 'operator', submit, workers)
    with TestClient(app) as c:
        assert c.get('/api/build-retention?node=PC').json()['default'] == 3
        assert c.post('/api/build-retention', json={'node': 'PC', 'game_id': 'g', 'limit': 10}).status_code == 200
        got = c.get('/api/build-retention?node=PC').json()
        assert got['default'] == 3 and got['games'] == {'g': 10} and got['enabled']
        assert jobs[0]['input'] == {'game_id': 'a', 'name': 'b0', 'op': 'delete_build', 'retention_node': 'PC'}
        for limit in (0, 11, True, '3'):
            assert c.post('/api/build-retention', json={'node': 'PC', 'limit': limit}).status_code == 422
        assert c.post('/api/build-retention', json={'node': 'Spark', 'limit': 1}).status_code == 422
        assert len(jobs) == 1


@pytest.mark.parametrize('n', [0, 11, True, '3'])
def test_policy_rejects_invalid_limits(n):
    with pytest.raises(ValueError): R.policy({'games': {'a': n}})


def test_gallery_wait_during_retention_does_not_block_unrelated_store_requests(tmp_path):
    from gbox.store import Store
    store, app = Store(tmp_path), FastAPI()
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    def gallery():
        entered.set()
        assert release.wait(5)
        return {'items': []}
    app.state.built_mods_current = gallery
    R.routes(app, store, lambda: 'operator', lambda *a: {'id': 'j'},
             lambda: [{'id': 'w', 'name': 'PC', 'os': 'windows', 'online': True}])
    responses = []
    with TestClient(app) as client:
        saving = threading.Thread(target=lambda: responses.append(client.post('/api/build-retention', json={'node': 'PC', 'limit': 4})))
        saving.start()
        try:
            assert entered.wait(2)
            def other_request():
                store.put('probe', 'health', {'ok': True})
                observed.set()
            reading = threading.Thread(target=other_request, daemon=True)
            reading.start()
            assert observed.wait(1), 'A slow Mods gallery must not hold the global database lock'
        finally:
            release.set()
            saving.join(5)
        assert not saving.is_alive() and responses[0].status_code == 200
