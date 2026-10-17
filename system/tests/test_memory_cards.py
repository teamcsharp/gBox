"""Native card bytes stay revisioned and single-writer across PCs and restarts."""
import base64
import hashlib
import json
import os
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import memory_card_emulators as N, memory_cards as C
from gbox.store import Store


def client_for(store, cfg):
    app = FastAPI()
    C.routes(app, store, cfg, lambda: 'operator')
    return TestClient(app, raise_server_exceptions=False)


def setup(tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path / 'data')
    store = Store(cfg.data_dir)
    store.upsert_catalog([
        {'game_id': 'pso-dc', 'title': 'Phantasy Star Online Ver. 2', 'platform': 'dreamcast', 'system': 'Dreamcast', 'library_id': 'test'},
        {'game_id': 'pso-gc', 'title': 'PSO Plus', 'platform': 'gamecube', 'system': 'GameCube', 'library_id': 'test'},
    ])
    for wid in ('w1', 'w2'):
        store.put('worker', wid, {'id': wid, 'name': wid, 'last_seen': 1})
    return client_for(store, cfg), store, cfg


def create(client, platform='dreamcast', **kw):
    response = client.post('/api/memory-cards', json={'platform': platform, 'name': 'My card', **kw})
    assert response.status_code == 200, response.text
    return response.json()


def owner(wid='w1', suffix='session'):
    return {'owner': wid + '-' + suffix, 'worker_id': wid}


def sync_body(raw, revision=1, **kw):
    return owner() | {'base_revision': revision, 'data_b64': base64.b64encode(raw).decode(), **kw}


def changed_vmu(raw, value=1):
    data = bytearray(raw)
    data[0] = value  # Free native data block; FAT/root/directory remain valid.
    assert N.describe(bytes(data), 'dreamcast')['formatted']
    return bytes(data)


def test_both_native_cards_roundtrip_capacity_and_persistent_identity(tmp_path):
    client, store, cfg = setup(tmp_path)
    for platform, free in (('dreamcast', 200), ('gamecube', 251)):
        card = create(client, platform)
        result = client.get('/api/memory-cards/' + card['id'] + '/data')
        assert result.status_code == 200
        assert hashlib.sha256(result.content).hexdigest() == card['sha256']
        assert result.headers['x-memory-card-revision'] == '1'
        assert result.headers['etag'] == card['sha256']
        assert card['capacity']['formatted'] and card['capacity']['free_blocks'] == free
        assert card['capacity']['total_blocks'] == free
        # A new backend Store can reopen the exact same native serial/card bytes.
        restarted = client_for(Store(cfg.data_dir), cfg)
        assert restarted.get('/api/memory-cards/' + card['id'] + '/data').content == result.content


def test_dedicated_selection_is_per_game_and_does_not_change_active_session(tmp_path):
    client, store, cfg = setup(tmp_path)
    original = {'state': 'running', 'game_id': 'pso-dc', 'worker_id': 'w1',
                'detail': {'memory_cards': {'slots': [{'slot': 'A1', 'card_id': 'old-local-card'}]}}}
    store.put('session', 'w1-session', original)
    dc = create(client, game_id='pso-dc')
    gc = create(client, 'gamecube', game_id='pso-gc')
    listed = client.get('/api/memory-cards', params={'platform': 'dreamcast', 'session_id': 'w1-session'}).json()
    assert listed['selection'] == {'A1': dc['id']}
    assert [c['id'] for c in listed['cards']] == [dc['id']]
    assert listed['session'] == original['detail']['memory_cards']
    assert store.get('session', 'w1-session') == original
    assert client.post('/api/memory-cards/selection', json={
        'game_id': 'pso-dc', 'platform': 'dreamcast', 'slot': 'A1', 'card_id': gc['id']}).status_code == 422
    assert client.post('/api/memory-cards/selection', json={
        'game_id': 'pso-dc', 'platform': 'dreamcast', 'slot': 'Z9', 'card_id': dc['id']}).status_code == 422
    assert client.post('/api/memory-cards', json={'platform': 'gamecube', 'name': 'Wrong game', 'game_id': 'pso-dc'}).status_code == 422


def test_import_is_idempotent_and_never_reformats_original_bytes(tmp_path):
    client, store, cfg = setup(tmp_path)
    raw = changed_vmu(N.blank('dreamcast'), 17)
    source = 'a' * 64
    first = create(client, data_b64=base64.b64encode(raw).decode(), source_key=source)
    again = create(client, data_b64=base64.b64encode(raw).decode(), source_key=source, name='Renamed local file')
    assert first['id'] == again['id'] and len(store.all(C.KIND)) == 1
    assert client.get('/api/memory-cards/' + first['id'] + '/data').content == raw
    assert 'source_key' not in again
    mismatch = client.post('/api/memory-cards', json={'platform': 'gamecube', 'name': 'Mismatch', 'source_key': source})
    assert mismatch.status_code in (409, 422), mismatch.text


def test_lease_is_exclusive_and_identity_is_bound_to_its_worker(tmp_path):
    client, store, cfg = setup(tmp_path)
    card = create(client); url = '/api/memory-cards/' + card['id']
    assert client.post(url + '/lease', json=owner()).status_code == 200
    assert client.post(url + '/lease', json=owner()).status_code == 200
    assert client.post(url + '/lease', json=owner('w2')).status_code == 409
    assert client.post(url + '/release', json=owner('w2')).status_code == 409
    assert client.post(url + '/lease', json={'owner': 'w1-session', 'worker_id': 'w2'}).status_code == 403
    assert client.post(url + '/lease', json={'owner': 'missing-session', 'worker_id': 'missing'}).status_code == 403
    assert client.post(url + '/release', json=owner()).status_code == 200
    assert client.post(url + '/lease', json=owner('w2')).status_code == 200


def test_native_sync_uses_cas_keeps_old_versions_and_does_not_churn_unchanged_cards(tmp_path):
    client, store, cfg = setup(tmp_path)
    card = create(client); url = '/api/memory-cards/' + card['id']
    before = client.get(url + '/data').content
    assert client.post(url + '/lease', json=owner()).status_code == 200
    same = client.post(url + '/sync', json=sync_body(before))
    assert same.status_code == 200 and same.json()['revision'] == 1
    updated = changed_vmu(before)
    accepted = client.post(url + '/sync', json=sync_body(updated))
    assert accepted.status_code == 200 and accepted.json()['revision'] == 2
    assert client.get(url + '/data', params={'revision': 1}).content == before
    assert client.get(url + '/data', params={'revision': 2}).content == updated
    rejected = client.post(url + '/sync', json=sync_body(changed_vmu(before, 2), release=True))
    assert rejected.status_code == 409
    current = store.get(C.KIND, card['id'])
    assert current['revision'] == 2 and len(current['versions']) == 2 and current['lease']
    assert client.get(url + '/data').content == updated
    assert client.get(url + '/data', params={'revision': 999}).status_code == 404
    final = client.post(url + '/sync', json=sync_body(updated, revision=2, release=True))
    assert final.status_code == 200 and final.json()['lease'] is None


def test_invalid_native_uploads_never_change_current_cloud_revision_or_lease(tmp_path):
    client, store, cfg = setup(tmp_path)
    card = create(client); url = '/api/memory-cards/' + card['id']
    client.post(url + '/lease', json=owner())
    for raw in (b'', b'truncated', bytes(128 * 1024)):
        result = client.post(url + '/sync', json=sync_body(raw))
        assert result.status_code == 422, result.text
        assert store.get(C.KIND, card['id'])['revision'] == 1
        assert store.get(C.KIND, card['id'])['lease']['owner'] == owner()['owner']
        result = client.post('/api/memory-cards', json={'name': 'Bad', 'platform': 'dreamcast',
                                                     'data_b64': base64.b64encode(raw).decode()})
        assert result.status_code == 422, result.text
    assert client.post(url + '/sync', json=sync_body(b'') | {'data_b64': 'not base64!'}).status_code == 422
    assert len(store.all(C.KIND)) == 1


def test_stale_lease_can_only_be_recovered_after_owner_is_no_longer_running(tmp_path):
    client, store, cfg = setup(tmp_path)
    card = create(client); url = '/api/memory-cards/' + card['id']
    client.post(url + '/lease', json=owner())
    row = store.get(C.KIND, card['id']); row['lease']['updated'] = 0; store.put(C.KIND, card['id'], row)
    store.put('session', 'w1-session', {'state': 'running', 'worker_id': 'w1'})
    assert client.post(url + '/lease', json=owner('w2')).status_code == 409
    store.put('session', 'w1-session', {'state': 'ended', 'worker_id': 'w1'})
    assert client.post(url + '/lease', json=owner('w2')).status_code == 200
    # Queued launches reserve their card before a session document exists.
    other = create(client); other_url = '/api/memory-cards/' + other['id']
    client.post(other_url + '/lease', json=owner(suffix='launchjob'))
    row = store.get(C.KIND, other['id']); row['lease']['updated'] = 0; store.put(C.KIND, other['id'], row)
    store.put('job', 'launchjob', {'state': 'queued'})
    assert client.post(other_url + '/lease', json=owner('w2')).status_code == 409


def test_independent_backend_connections_cannot_both_acquire_or_commit(tmp_path):
    client, store, cfg = setup(tmp_path)
    second = client_for(Store(cfg.data_dir), cfg)
    card = create(client); url = '/api/memory-cards/' + card['id']
    barrier = threading.Barrier(2)

    def acquire(c, wid):
        barrier.wait(timeout=5)
        return c.post(url + '/lease', json=owner(wid)).status_code

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(acquire, client, 'w1'), pool.submit(acquire, second, 'w2')]
        statuses = [f.result(timeout=10) for f in futures]
    assert sorted(statuses) == [200, 409]
    lease = store.get(C.KIND, card['id'])['lease']
    own = {k: lease[k] for k in ('owner', 'worker_id')}
    raw = client.get(url + '/data').content
    barrier = threading.Barrier(2)

    def commit(c, value):
        barrier.wait(timeout=5)
        data = changed_vmu(raw, value)
        return c.post(url + '/sync', json=sync_body(data) | own), data

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(commit, client, 3), pool.submit(commit, second, 4)]
        answers = [f.result(timeout=10) for f in futures]
    assert sorted(r.status_code for r, _ in answers) == [200, 409]
    winner = next(data for response, data in answers if response.status_code == 200)
    assert client.get(url + '/data').content == winner
    assert store.get(C.KIND, card['id'])['revision'] == 2
    assert len(store.get(C.KIND, card['id'])['versions']) == 2


def test_one_card_cannot_be_selected_as_two_independent_writable_copies(tmp_path):
    client, store, cfg = setup(tmp_path)
    card = create(client, game_id='pso-dc')
    result = client.post('/api/memory-cards/selection', json={
        'game_id': 'pso-dc', 'platform': 'dreamcast', 'slot': 'A2', 'card_id': card['id']})
    assert result.status_code in (409, 422), result.text
    assert store.get('memory_card_selection', 'pso-dc-dreamcast')['slots'] == {'A1': card['id']}


def test_local_snapshot_rejects_recent_or_changing_files(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    path = tmp_path / 'working.bin'; raw = N.blank('dreamcast'); path.write_bytes(raw)
    with pytest.raises(RuntimeError, match='writing'):
        S.stable(path, 'dreamcast')
    old = time.time() - 10
    os.utime(path, (old, old))
    monkeypatch.setattr(S.time, 'sleep', lambda _: path.write_bytes(changed_vmu(raw, 31)))
    with pytest.raises(RuntimeError, match='changed'):
        S.stable(path, 'dreamcast')


def local_context(tmp_path):
    path = tmp_path / 'working.bin'; raw = N.blank('dreamcast'); path.write_bytes(raw)
    old = time.time() - 10; os.utime(path, (old, old))
    row = {'slot': 'A1', 'card_id': 'c' * 32, 'name': 'My card', 'revision': 3,
           'sha256': hashlib.sha256(raw).hexdigest(), 'path': str(path), 'capacity': N.describe(raw, 'dreamcast')}
    context = {'platform': 'dreamcast', 'work_dir': str(tmp_path / 'journal'), 'session_id': 'w1-session', 'worker_id': 'w1',
               'game_id': 'pso-dc', 'slots': {'A1': row}, 'pending': {}}
    return context, row, path, raw


def test_failed_snapshot_sync_retains_exact_local_card_revision_and_recovery_journal(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path)
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    def fail(*args, **kwargs):
        raise RuntimeError('A newer cloud save exists; local save kept')
    monkeypatch.setattr(S, 'api', fail)
    errors = S.sync(context, SimpleNamespace(worker='w1'), final=True)
    assert errors and row['sync_state'] == 'conflict' and row['revision'] == 3
    assert path.read_bytes() == raw
    journal = json.loads((tmp_path / 'journal/sync-journal.json').read_text())
    assert journal['slots']['A1']['path'] == str(path)
    assert journal['slots']['A1']['revision'] == 3
    assert 'ctx' not in journal and 'headers' not in journal


def test_successful_final_snapshot_releases_only_after_upload_and_keeps_local_recovery_file(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path); calls = []
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    def accept(ctx, route, body):
        calls.append((route, body))
        assert path.read_bytes() == base64.b64decode(body['data_b64']) == raw
        return {'revision': 4, 'sha256': hashlib.sha256(raw).hexdigest(), 'capacity': row['capacity'], 'lease': None}
    monkeypatch.setattr(S, 'api', accept)
    assert not S.sync(context, SimpleNamespace(worker='w1'), final=True)
    assert calls[0][1]['release'] is True and calls[0][1]['base_revision'] == 3
    assert row['revision'] == 4 and row['sync_state'] == 'synced'
    assert path.read_bytes() == raw


def test_checkout_releases_acquired_lease_when_download_fails(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    raw = N.blank('dreamcast'); cid = 'd' * 32
    card = {'id': cid, 'name': 'Selected card', 'revision': 2, 'sha256': hashlib.sha256(raw).hexdigest(),
            'capacity': N.describe(raw, 'dreamcast')}
    calls = []
    def respond(ctx, path, body=None, raw=False):
        calls.append(path)
        if path.startswith('/api/memory-cards?'):
            return {'selection': {'A1': cid}, 'cards': [card]}
        if path.endswith('/lease'):
            return card
        if '/data?' in path:
            raise RuntimeError('Network interrupted during card download')
        if path.endswith('/release'):
            return card | {'lease': None}
        raise AssertionError(path)
    monkeypatch.setattr(S, 'api', respond)
    ctx = SimpleNamespace(server='http://spark', worker='w1', config=SimpleNamespace(data_dir=tmp_path))
    with pytest.raises(RuntimeError, match='Network interrupted'):
        S.checkout('w1-job', SimpleNamespace(name='retroarch'), {'platform': 'dreamcast', 'game_id': 'pso-dc'}, ctx)
    assert '/api/memory-cards/' + cid + '/release' in calls


def test_finish_never_releases_card_before_emulator_process_has_exited(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path); sid = context['session_id']; calls = []
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None), memory_card_context=context)
    monkeypatch.setattr(S, 'sync', lambda context, ctx, final=False: calls.append(final) or [])
    S._contexts[sid] = context
    try:
        S.finish(sid, ad, SimpleNamespace(worker='w1'))
        assert not calls and sid in S._contexts and not context.get('closed')
        ad.proc.poll = lambda: 0
        S.finish(sid, ad, SimpleNamespace(worker='w1'))
        assert calls == [True] and sid not in S._contexts and context['closed']
        S.finish(sid, ad, SimpleNamespace(worker='w1'))
        assert calls == [True]  # Repeated close notifications cannot upload twice.
    finally:
        S._contexts.pop(sid, None)


def test_post_restart_recovery_uses_original_worker_lease_identity(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path)
    context['work_dir'] = str(tmp_path / 'memory-cards/sessions' / context['session_id'])
    context.update(closed=True, pending_upload=True)
    S.journal(context); calls = []
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    def accept(ctx, route, body):
        calls.append(body)
        return {'revision': 4, 'sha256': hashlib.sha256(raw).hexdigest(), 'capacity': row['capacity'], 'lease': None}
    monkeypatch.setattr(S, 'api', accept)
    ctx = SimpleNamespace(server='http://spark', worker='newworker', config=SimpleNamespace(data_dir=tmp_path))
    S.recover_pending(ctx)
    assert len(calls) == 1 and calls[0]['release'] is True
    assert calls[0]['owner'] == 'w1-session' and calls[0]['worker_id'] == 'w1'
    journal = json.loads((tmp_path / 'memory-cards/sessions/w1-session/sync-journal.json').read_text())
    assert journal['closed'] and journal['pending_upload'] is False
    assert path.read_bytes() == raw


def test_invalid_legacy_secondary_card_does_not_block_importing_good_primary(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    client, store, cfg = setup(tmp_path)
    primary = tmp_path / 'legacy-A1.bin'; raw = N.blank('dreamcast'); primary.write_bytes(raw)
    secondary = tmp_path / 'legacy-B1.bin'; secondary.write_bytes(bytes(N.VMU_SIZE))
    old = time.time() - 10
    for path in (primary, secondary):
        os.utime(path, (old, old))
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    monkeypatch.setattr(S.native, 'discover', lambda *args: [
        {'slot': 'A1', 'path': str(primary)}, {'slot': 'B1', 'path': str(secondary)}])
    def local_api(ctx, path, body=None, raw=False):
        response = client.post(path, json=body) if body is not None else client.get(path)
        if response.status_code >= 400:
            raise RuntimeError(response.text)
        return response.content if raw else response.json()
    monkeypatch.setattr(S, 'api', local_api)
    ctx = SimpleNamespace(server='http://spark', worker='w1', config=cfg)
    ad = SimpleNamespace(name='retroarch')
    context = S.checkout('w1-goodprimary', ad,
                         {'platform': 'dreamcast', 'game_id': 'pso-dc', 'title': 'PSO'}, ctx)
    assert set(context['slots']) == {'A1'}
    assert len(context['warnings']) == 1 and context['warnings'][0].startswith('B1:')
    assert primary.read_bytes() == raw and secondary.read_bytes() == bytes(N.VMU_SIZE)
    assert len(store.all(C.KIND)) == 1
    assert store.get('memory_card_selection', 'pso-dc-dreamcast')['slots'] == {
        'A1': context['slots']['A1']['card_id']}
    assert context['slots']['A1']['path'] != str(primary)


def mixed_vmu():
    data = bytearray(N.blank('dreamcast'))
    for index, (name, first, blocks, payload, protected) in enumerate([
        ('PSO_SYSTEM', 0, 3, b'P', True), ('OTHER_SAVE', 3, 2, b'O', False),
    ]):
        off = 253 * 512 + index * 32
        data[off:off + 2] = bytes((0x33, 255 if protected else 0))
        struct.pack_into('<H', data, off + 2, first)
        data[off + 4:off + 16] = name.encode().ljust(12, b'\0')
        struct.pack_into('<HH', data, off + 24, blocks, 0)
        for block in range(first, first + blocks):
            struct.pack_into('<H', data, 254 * 512 + block * 2,
                             block + 1 if block + 1 < first + blocks else 0xfffa)
            data[block * 512:(block + 1) * 512] = payload * 512
    assert N.describe(data, 'dreamcast')['free_blocks'] == 195
    return bytes(data)


def test_dedicated_dreamcast_pso_clone_preserves_pso_payload_and_frees_other_games(tmp_path):
    client, store, cfg = setup(tmp_path); original = mixed_vmu()
    source = create(client, data_b64=base64.b64encode(original).decode())
    result = create(client, name='PSO dedicated', game_id='pso-dc', clone_from=source['id'])
    assert result['id'] != source['id'] and result['copied_from'] == source['id']
    assert result['capacity']['free_blocks'] == 197
    assert result['capacity']['files'] == [{'name': 'PSO_SYSTEM', 'blocks': 3, 'copy_protected': True}]
    copied = client.get('/api/memory-cards/' + result['id'] + '/data').content
    assert copied[:3 * 512] == b'P' * (3 * 512)
    assert client.get('/api/memory-cards/' + source['id'] + '/data').content == original
    assert store.get(C.KIND, source['id'])['revision'] == 1
    complete = create(client, clone_from=source['id'])
    assert client.get('/api/memory-cards/' + complete['id'] + '/data').content == original


def test_gamecube_clone_keeps_native_serial_and_every_byte(tmp_path):
    client, store, cfg = setup(tmp_path)
    original = bytearray(N.blank('gamecube'))
    original[5 * N.GC_BLOCK:5 * N.GC_BLOCK + 4] = b'game'
    original = bytes(original)
    source = create(client, 'gamecube', data_b64=base64.b64encode(original).decode())
    copied = create(client, 'gamecube', name='Dedicated GC PSO', game_id='pso-gc', clone_from=source['id'])
    result = client.get('/api/memory-cards/' + copied['id'] + '/data').content
    assert copied['id'] != source['id'] and copied['sha256'] == source['sha256']
    assert result == original and result[:12] == original[:12]
    assert client.post('/api/memory-cards', json={
        'name': 'Wrong platform', 'platform': 'dreamcast', 'clone_from': source['id']}).status_code == 422
    assert client.post('/api/memory-cards', json={
        'name': 'Ambiguous source', 'platform': 'gamecube', 'clone_from': source['id'],
        'data_b64': base64.b64encode(original).decode()}).status_code == 422


def test_failed_launch_cannot_discard_card_written_before_emulator_exited(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path)
    latest = changed_vmu(raw, 77); path.write_bytes(latest); calls = []
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: 1), memory_card_context=context)
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    def accept(ctx, route, body):
        calls.append((route, body))
        return {'revision': 4, 'sha256': hashlib.sha256(latest).hexdigest(), 'capacity': row['capacity'], 'lease': None}
    monkeypatch.setattr(S, 'api', accept)
    S.abandon(ad, SimpleNamespace(worker='w1'))
    journal = json.loads((tmp_path / 'journal/sync-journal.json').read_text())
    uploaded = [(route, body) for route, body in calls if route.endswith('/sync')]
    assert uploaded or journal.get('pending_upload'), 'Startup writes must upload or remain pending for recovery'
    if uploaded:
        assert base64.b64decode(uploaded[0][1]['data_b64']) == latest
        assert uploaded[0][1]['release'] is True
    assert path.read_bytes() == latest


def test_failed_launch_releases_unchanged_checkout_without_creating_a_revision(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path); calls = []
    ad = SimpleNamespace(memory_card_context=context)
    monkeypatch.setattr(S, 'api', lambda ctx, route, body: calls.append((route, body)) or {})
    S.abandon(ad, SimpleNamespace(worker='w1'))
    assert len(calls) == 1 and calls[0][0].endswith('/release')
    assert context['closed'] and not context['pending_upload']
    assert path.read_bytes() == raw


def test_failed_launch_upload_failure_stays_pending_for_later_recovery(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path)
    latest = changed_vmu(raw, 88); path.write_bytes(latest)
    ad = SimpleNamespace(proc=SimpleNamespace(poll=lambda: 1), memory_card_context=context)
    monkeypatch.setattr(S.time, 'sleep', lambda _: None)
    def offline(*args, **kwargs):
        raise RuntimeError('Spark temporarily offline')
    monkeypatch.setattr(S, 'api', offline)
    S.abandon(ad, SimpleNamespace(worker='w1'))
    journal = json.loads((tmp_path / 'journal/sync-journal.json').read_text())
    assert journal['closed'] and journal['pending_upload'] is True
    assert journal['slots']['A1']['revision'] == 3 and journal['slots']['A1']['sync_state'] == 'pending'
    assert path.read_bytes() == latest


def test_boot_process_identity_prevents_recovery_touching_a_live_card(tmp_path, monkeypatch):
    from gbox import memory_card_sessions as S
    context, row, path, raw = local_context(tmp_path)
    context['work_dir'] = str(tmp_path / 'memory-cards/sessions' / context['session_id'])
    # Read the test process identity only; no emulator/window/process is started.
    ad = SimpleNamespace(proc=SimpleNamespace(pid=os.getpid()), memory_card_context=context)
    S.launched(ad)
    journal_path = tmp_path / 'memory-cards/sessions/w1-session/sync-journal.json'
    before = journal_path.read_bytes(); recorded = json.loads(before)
    assert recorded['pid'] == os.getpid() and recorded['process_created'] > 0
    def cannot_upload(*args, **kwargs):
        pytest.fail('Recovery must not upload or release a card while its recorded process is alive')
    monkeypatch.setattr(S, 'api', cannot_upload)
    S.recover_pending(SimpleNamespace(server='http://spark', worker='newworker',
                                     config=SimpleNamespace(data_dir=tmp_path)))
    assert journal_path.read_bytes() == before and path.read_bytes() == raw
