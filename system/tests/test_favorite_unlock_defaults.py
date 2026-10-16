import copy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import custom_build_unlocks as U, live_controls as L, tools
from tests.test_custom_build_unlocks import rig, profile


def favorite_rig(tmp_path):
    store, rows, client, reconcile, created, dispatched, sha = rig(tmp_path)
    games = {'g': {'game_id': 'g', 'title': 'Favorite', 'platform': 'psx', 'size': 100, 'hashes': {}}}
    store.favorites = lambda: [{'game_id': gid, 'title': game['title'], 'in_catalog': True} for gid, game in games.items()]
    store.catalog_get = lambda gid: copy.deepcopy(games.get(gid))
    return store, rows, client, reconcile, created, dispatched, sha, games


def publish_boot(store, client, sha):
    live = {'game_id': 'g', 'revision': 'b' * 64, 'executable_sha256': 'a' * 64,
            'guards': [{'address': 1, 'hex': '11' * 16}],
            'actions': [{'id': 'all_content', 'category': 'unlocks', 'parameters': [],
                         'guards': [{'address': 40, 'hex': '22'}],
                         'binding': {'kind': 'native', 'tool': 'mgs_vr', 'input': {'op': 'unlock_all'}}}]}
    store.put(L.PROFILE, 'g', live)
    body = profile(sha)
    body['boot_apply'] = {'kind': 'live_control', 'revision': live['revision'], 'action': 'all_content',
                          'values': {}, 'coverage': copy.deepcopy(body['inventory']), 'runtime_artifacts': [sha]}
    response = client.post('/api/custom-build-unlocks/g/profile', json=body)
    assert response.status_code == 200, response.text
    return body, live


def verify_base(client, sha):
    body = client.get('/api/custom-build-unlocks/g/@original/manifest').json()
    response = client.post('/api/custom-build-unlocks/g/@original/verify', json=body | {
        'runtime_artifacts': [sha], 'notes': 'Exact native executable: complete inventory available after fresh boot.'})
    assert response.status_code == 200, response.text
    return response.json()


def test_default_is_persisted_and_favorite_originals_use_existing_tasks(tmp_path):
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    assert store.get(U.POLICY, 'default')['favorites_enabled'] is True
    assert store.get(U.POLICY, 'default')['default_boot'] is True
    reconcile(); reconcile()
    assert len(created) == len(dispatched) == 1
    task = store.get(U.TASK, 'g')
    assert set(task['versions']) == {'one', 'two', U.BASE}
    assert created[0]['context']['no_automatic_launch'] and created[0]['context']['no_rom_copy']
    assert 'Prefer built-in custom-ROM changes' not in created[0]['body']
    assert 'implement a reusable step in the' not in created[0]['body']
    assert 'boot_apply' in created[0]['body']
    status = client.get('/api/custom-build-unlocks').json()
    assert status['favorites'][0]['unlocks']['status'] == 'pending'
    assert client.get('/api/custom-build-unlocks/g/boot-plan').json()['status'] == 'pending'
    assert client.post('/api/custom-build-unlocks/policy', json={'excluded_games': ['g']}).status_code == 200
    assert client.get('/api/custom-build-unlocks/g/boot-plan').json()['required'] is False
    assert client.get('/api/custom-build-unlocks').json()['favorites'] == []


def test_base_acceptance_needs_reusable_complete_recipe_and_exact_catalog_revision(tmp_path):
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    client.post('/api/custom-build-unlocks/g/profile', json=profile(sha))
    body = client.get('/api/custom-build-unlocks/g/@original/manifest').json()
    assert client.post('/api/custom-build-unlocks/g/@original/verify', json=body | {
        'runtime_artifacts': [sha], 'notes': 'Generic verified flag'}).status_code == 409
    publish_boot(store, client, sha); verify_base(client, sha)
    ready = client.get('/api/custom-build-unlocks/g/boot-plan').json()
    assert ready['status'] == 'ready' and set(ready['inventory']) == set(U.CATEGORIES)
    assert ready['live_profile']['actions'][0]['binding']['tool'] == 'mgs_vr'
    games['g']['hashes'] = {'sha256': 'c' * 64}
    assert client.get('/api/custom-build-unlocks/g/boot-plan').json()['status'] == 'pending'


def test_partial_or_unpublished_action_cannot_become_default_unlock_all(tmp_path):
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    body, live = publish_boot(store, client, sha)
    assert client.post('/api/custom-build-unlocks/g/profile', json=body | {
        'boot_apply': body['boot_apply'] | {'coverage': {'characters': body['inventory']['characters']}}}).status_code == 422
    live['actions'][0]['binding']['input']['op'] = 'complete'
    store.put(L.PROFILE, 'g', live)
    assert client.post('/api/custom-build-unlocks/g/profile', json=body).status_code == 422
    live['actions'][0]['binding'] = {'kind': 'memory', 'address': 12, 'value': 1}
    store.put(L.PROFILE, 'g', live)
    assert client.post('/api/custom-build-unlocks/g/profile', json=body).status_code == 422


def test_idle_dispatch_is_one_per_pass_and_hourly_budget_survives_reconciliation(tmp_path):
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    games.update({gid: {'game_id': gid, 'title': gid, 'platform': 'psx'} for gid in ('h', 'i')})
    client.post('/api/custom-build-unlocks/policy', json={'dispatch_per_hour': 2})
    reconcile(); assert len(created) == 3 and len(dispatched) == 1
    reconcile(); assert len(dispatched) == 2
    reconcile(); assert len(dispatched) == 2
    assert len(store.all(U.TASK)) == 3
    assert any(task['reason'] == 'Hourly research budget reached' for task in store.all(U.TASK))
    assert all(task['state'] != 'verified' for task in store.all(U.TASK))


def test_changed_target_waiting_for_budget_is_released_on_a_later_pass(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(U.time, 'time', lambda: clock[0])
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    client.post('/api/custom-build-unlocks/policy', json={'dispatch_per_hour': 1})
    reconcile(); assert len(dispatched) == 1
    rows[0]['meta']['built'] = 2
    reconcile()
    assert store.get(U.TASK, 'g')['dispatched'] is False and len(dispatched) == 1
    clock[0] += 3601
    reconcile()
    assert store.get(U.TASK, 'g')['dispatched'] is True and len(dispatched) == 2
    assert len(created) == 1


def test_quiet_interval_and_paused_resolution_keep_durable_pending_work(tmp_path, monkeypatch):
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(U.time, 'time', lambda: clock[0])
    store.put(U.POLICY, 'idle-state', {'last_busy': clock[0]})
    reconcile(); assert len(created) == 1 and not dispatched
    clock[0] += 299; reconcile(); assert not dispatched
    clock[0] += 1; reconcile(); assert len(dispatched) == 1
    assert client.post('/api/custom-build-unlocks/policy', json={'default_boot': False}).status_code == 200
    assert client.get('/api/custom-build-unlocks/g/boot-plan').json()['status'] == 'disabled'
    for bad in ({'quiet_seconds': 0}, {'dispatch_per_hour': 50}, {'favorites_enabled': 'true'}):
        assert client.post('/api/custom-build-unlocks/policy', json=bad).status_code == 422


def test_real_idle_guard_yields_to_games_jobs_chats_and_stale_resources(tmp_path, monkeypatch):
    from gbox import hermes_activation
    store, *_ = rig(tmp_path)
    sessions, jobs = [], []
    store.running_sessions = lambda: sessions
    store.jobs = lambda **kwargs: jobs
    monkeypatch.setattr(hermes_activation, 'read_cron_snapshot', lambda *a, **k: {'hermes': []})
    now = 1000.0
    worker = {'id': 'w', 'name': 'Spark', 'os': 'linux', 'online': True, 'active_jobs': 0, 'pending_results': 0,
              'resources': {'sampled_at': now, 'cpu_percent': 5, 'memory_percent': 40,
                            'memory_available_bytes': 4 * 1024**3, 'gpus': [{'utilization_percent': 5}]}}
    policy = U.policy_value(store)
    assert U.idle_reason(store, [worker], policy, now=now) == ''
    sessions.append({'session_id': 'w-s'})
    assert 'games' in U.idle_reason(store, [worker], policy, now=now)
    sessions.clear(); jobs.append({'state': 'running'})
    assert 'jobs' in U.idle_reason(store, [worker], policy, now=now)
    jobs.clear(); store.put('chat', 'c', {'busy': True})
    assert 'conversation' in U.idle_reason(store, [worker], policy, now=now)
    store.put('chat', 'c', {'busy': False})
    assert 'admission' in U.idle_reason(store, [worker], policy, now=now + 31)
    assert 'paused' in U.idle_reason(store, [worker], policy | {'idle_resolution': False}, now=now)


def test_boot_reuses_only_exact_accepted_native_recipe_without_launch_or_rom_work(tmp_path, monkeypatch):
    import httpx
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    publish_boot(store, client, sha); verify_base(client, sha)
    plan = client.get('/api/custom-build-unlocks/g/boot-plan').json()
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: copy.deepcopy(plan)))
    calls = []
    monkeypatch.setattr(L, 'operate', lambda ad, p, g, inp, ctx: calls.append((g, inp)) or {'result': {'verified': True}})
    ad = object(); game = {'game_id': 'g', 'mod': ''}
    monkeypatch.setitem(tools.SESSIONS, 'w-boot', (ad, game))
    artifacts = []
    ctx = SimpleNamespace(server='http://control', headers={}, config=SimpleNamespace(granted_permissions=['memory_write']),
                          artifact=lambda *a, **k: artifacts.append(a))
    result = U.on_launch('w-boot', ctx)
    assert result['status'] == 'applied' and result['runtime_verified'] is True
    assert len(calls) == 1 and calls[0][1].session_id == 'w-boot' and artifacts
    ctx.config.granted_permissions = []
    assert U.on_launch('w-boot', ctx)['status'] == 'pending' and len(calls) == 1
    game['mod'] = 'different'
    assert 'identity' in U.on_launch('w-boot', ctx)['reason'] and len(calls) == 1


def test_changed_live_profile_and_missing_readback_stay_pending(tmp_path, monkeypatch):
    import httpx
    store, rows, client, reconcile, created, dispatched, sha, games = favorite_rig(tmp_path)
    body, live = publish_boot(store, client, sha); verify_base(client, sha)
    plan = client.get('/api/custom-build-unlocks/g/boot-plan').json()
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: copy.deepcopy(plan)))
    monkeypatch.setitem(tools.SESSIONS, 'w-boot', (object(), {'game_id': 'g', 'mod': ''}))
    monkeypatch.setattr(L, 'operate', lambda *a: {'result': {'success': True}})
    ctx = SimpleNamespace(server='http://control', headers={}, config=SimpleNamespace(granted_permissions=['memory_write']), artifact=lambda *a, **k: None)
    assert U.on_launch('w-boot', ctx)['status'] == 'pending'
    monkeypatch.setattr(L, 'operate', lambda *a: {'verified': True, 'result': {'error': 'native failure'}})
    assert U.on_launch('w-boot', ctx)['status'] == 'pending'
    live['revision'] = 'd' * 64; store.put(L.PROFILE, 'g', live)
    assert client.get('/api/custom-build-unlocks/g/boot-plan').json()['status'] == 'pending'


def test_queue_poll_observation_restarts_quiet_interval_and_rejects_stale_release(tmp_path, monkeypatch):
    busy = ['']
    store, rows, client, reconcile, created, dispatched, sha = rig(tmp_path, admission=lambda: busy[0])
    store.favorites = lambda: [{'game_id': 'g'}]
    clock = [1000.0]
    monkeypatch.setattr(U.time, 'time', lambda: clock[0])
    reconcile()
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['request_ids'] == ['1']
    busy[0] = 'Human gameplay is active'
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['allowed'] is False
    assert store.get(U.POLICY, 'idle-state')['last_busy'] == clock[0]
    busy[0] = ''; clock[0] += 1
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['allowed'] is False
    clock[0] += 300
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['request_ids'] == ['1']
    rows[0]['meta']['built'] = 2
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['request_ids'] == []
    client.post('/api/custom-build-unlocks/policy', json={'idle_resolution': False})
    assert client.get('/api/custom-build-unlocks/dispatch-admission').json()['allowed'] is False


def test_ongoing_research_ignores_only_its_own_canonical_claim_and_worker_jobs(tmp_path, monkeypatch):
    from gbox import hermes_activation, hermes_work_queue
    from gbox import hermes_unlock_guard
    monkeypatch.setattr(hermes_unlock_guard, 'readiness_reason', lambda: '')
    clock = [1000.0]
    monkeypatch.setattr(U.time, 'time', lambda: clock[0])
    cron = [{'id': 'execution-own', 'job_id': 'hermes-own', 'state': 'running'}]
    monkeypatch.setattr(hermes_activation, 'read_cron_snapshot', lambda *a, **k: {'hermes': cron})
    monkeypatch.setattr(hermes_work_queue, 'claims', lambda: {'hermes-own': '1', 'hermes-other': 'other-request'})
    worker = {'id': 'w', 'name': 'Spark', 'os': 'linux', 'online': True, 'active_jobs': 1, 'pending_results': 0,
              'resources': {'sampled_at': clock[0], 'cpu_percent': 5, 'memory_percent': 40,
                            'memory_available_bytes': 4 * 1024**3, 'gpus': [{'utilization_percent': 5}]}}
    store, rows, client, reconcile, created, dispatched, sha = rig(tmp_path, workers=lambda:[worker])
    store.favorites = lambda: [{'game_id': 'g'}]
    jobs = [{'id': 'native-own', 'worker_id': 'w', 'parent_request_id': '1'}]
    sessions = []
    store.jobs = lambda **kwargs: jobs
    store.running_sessions = lambda: sessions
    reconcile()
    gate = client.app.state.custom_build_unlock_job_admission
    assert gate('1') == ''
    cron.append({'id': 'execution-other', 'job_id': 'hermes-other', 'state': 'running'})
    assert 'Hermes' in gate('1')
    cron.pop(); jobs.append({'id': 'native-other', 'worker_id': 'w', 'parent_request_id': 'other-request'})
    assert 'jobs' in gate('1')
    jobs.pop(); sessions.append({'session_id': 'w-human'})
    assert 'games' in gate('1')
    sessions.clear(); clock[0] += 1; worker['resources']['sampled_at'] = clock[0]
    assert 'quiet time' in gate('1')
    clock[0] += 300; worker['resources']['sampled_at'] = clock[0]
    assert gate('1') == ''
    rows[0]['meta']['built'] = 2
    assert 'changed' in gate('1')
    assert 'no current' in gate('another-request')


def test_busy_queue_poll_cannot_be_overwritten_by_overlapping_reconcile(tmp_path, monkeypatch):
    import threading
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    clock = [1000.0]
    monkeypatch.setattr(U.time, 'time', lambda: clock[0])

    def admission():
        if threading.current_thread().name == 'unlock-reconcile-test':
            entered.set(); assert release.wait(3)
            return ''
        observed.set()
        return 'Human gameplay is active'

    store, rows, client, reconcile, created, dispatched, sha = rig(tmp_path, admission=admission)
    store.favorites = lambda: [{'game_id': 'g'}]
    running = threading.Thread(target=reconcile, name='unlock-reconcile-test')
    running.start(); assert entered.wait(3)
    clock[0] = 2000.0
    poll = threading.Thread(target=lambda: client.get('/api/custom-build-unlocks/dispatch-admission'))
    poll.start()
    assert not observed.wait(.05), 'Poll must share the reconciler guard'
    release.set(); running.join(3); poll.join(3)
    assert not running.is_alive() and not poll.is_alive() and observed.is_set()
    assert store.get(U.POLICY, 'idle-state')['last_busy'] == 2000.0
