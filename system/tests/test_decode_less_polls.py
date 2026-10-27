"""Stream stalls on the Spark (2026-10-27): the control plane froze 0.4-0.9 s several times a minute, and every MJPEG
view with it. One thread at a time ran alone on the GIL: full garbage collections over the 5.8 GB heap, set off by the
garbage of whole-kind decodes (inspection_builds decoded all 4,526 requests, 47.5 MB, for each of 4 plans every 15 s;
GET /api/mercmode the 4.9 MB session archive; each federation snapshot the 3 MB worker kind; the round-report thread
and session observers the 5.9 MB Hermes work-queue file). These reads now pick rows and fields in SQLite or keep the
parsed file while it is unchanged; the answers must stay exactly what the whole-kind code returned."""
import pytest

from gbox import federation, hermes_work_queue as q, inspection_builds as I, mercmode
from gbox.store import Store


def _old_request_revisions(store, gid):
    """inspection_builds.request_revisions before the SQL filter, verbatim."""
    result = {}
    for r in store.all('request'):
        c = r.get('context') or {}
        if c.get('game_id') != gid and not str(c.get('build') or '').startswith(gid + '/'):
            continue
        if r.get('automated') and not c.get('build_report'):
            continue
        messages = [{k: m.get(k) for k in ('text', 'attachments')} for m in r.get('messages', [])
                    if m.get('author') in ('operator', 'user', 'you')]
        result[r['id']] = I.digest({'body': r.get('body'), 'image': r.get('image'), 'messages': messages})
    return result


REQUESTS = [
    {'id': 'a', 'body': 'by game', 'context': {'game_id': 'g1'}, 'messages': [{'author': 'operator', 'text': 'hi'}]},
    {'id': 'b', 'body': 'by build', 'context': {'build': 'g1/cast_v2', 'build_report': True}},
    {'id': 'c', 'body': 'another game whose id starts the same', 'context': {'game_id': 'g10', 'build': 'g10/x'}},
    {'id': 'd', 'body': 'build is the bare id', 'context': {'build': 'g1'}},
    {'id': 'e', 'body': 'automated without a build report', 'automated': True, 'context': {'game_id': 'g1'}},
    {'id': 'f', 'body': 'automated build report', 'automated': True, 'context': {'game_id': 'g1', 'build_report': 1}},
    {'id': 'g', 'body': 'no context'},
    {'id': 'h', 'body': 'null context', 'context': None},
    {'id': 'i', 'body': 'numeric game id', 'context': {'game_id': 7}},
    {'id': 'j', 'body': 'object build', 'context': {'build': {'game': 'g1'}}},
    {'id': 'k', 'body': 'build mid-string', 'context': {'build': 'x/g1/y'}},
    {'id': 'l', 'body': 'unicode', 'context': {'game_id': 'gé'}, 'image': 'f' * 64},
    {'id': 'm', 'body': 'unicode build', 'context': {'build': 'gé/v1'}, 'messages': [
        {'author': 'agent', 'text': 'not counted'}, {'author': 'you', 'text': 'counted', 'attachments': ['x']}]},
    {'id': 'n', 'body': 'numeric build', 'context': {'build': 12}},
    {'id': 'o', 'body': 'empty game id', 'context': {'game_id': ''}},
]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    try:
        yield s
    finally:
        s.close()


def test_request_revisions_filtered_in_sqlite_match_the_whole_kind_scan(store):
    for r in REQUESTS:
        store.put('request', r['id'], r)
    store.put('request', 'a', REQUESTS[0] | {'body': 'rewritten (new rowid)'})   # INSERT OR REPLACE moves it last
    for gid in ('g1', 'g10', 'gé', '7', 'x', 'g', ''):
        assert I.request_revisions(store, gid) == _old_request_revisions(store, gid), gid
        assert list(I.request_revisions(store, gid)) == list(_old_request_revisions(store, gid)), 'same order'
    assert set(I.request_revisions(store, 'g1')) == {'a', 'b', 'f'}


def test_requests_for_game_decodes_only_candidates(store):
    for r in REQUESTS:
        store.put('request', r['id'], r)
    for i in range(50):
        store.put('request', f'other{i}', {'id': f'other{i}', 'context': {'game_id': 'zz'}, 'messages': []})
    picked = [r['id'] for r in store.requests_for_game('g1')]
    assert picked == ['a', 'b', 'e', 'f', 'j'], 'game id or build prefix (and object builds), in rowid order'


def test_request_revisions_falls_back_to_the_whole_kind_when_sqlite_cannot_parse_a_body(store):
    for r in REQUESTS[:3]:
        store.put('request', r['id'], r)
    expected = _old_request_revisions(store, 'g1')

    class Broken:
        def requests_for_game(self, gid):
            raise __import__('sqlite3').OperationalError('malformed JSON')

        def all(self, kind):
            return store.all(kind)
    assert I.request_revisions(Broken(), 'g1') == expected


def test_newest_matches_the_python_sort(store):
    notes = [{'id': 'a', 'ts': 5}, {'id': 'b', 'ts': 9.5}, {'id': 'c'}, {'id': 'd', 'ts': 5}, {'id': 'e', 'ts': 1},
             {'id': 'f', 'ts': 0}, {'id': 'g', 'ts': 12}]
    for n in notes:
        store.put('notify', n['id'], n)
    everything = store.all('notify')
    for limit in (0, 1, 3, 30):
        want = sorted(everything, key=lambda x: -x.get('ts', 0))[:limit]
        assert store.newest('notify', 'ts', limit) == want, limit
    with pytest.raises(ValueError):
        store.newest('notify', "ts') --", 3)


def test_notify_list_answers_the_newest_entries(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    store = app.state.store
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
        for i, ts in enumerate([3, 1, 7, 7, 2]):
            store.put('notify', f'n{i}', {'id': f'n{i}', 'ts': ts, 'title': f'note {i}', 'read': False})
        got = client.get('/api/notify?limit=3')
        assert got.status_code == 200, got.text
        assert [n['id'] for n in got.json()] == ['n2', 'n3', 'n0']
        assert [n['id'] for n in client.get('/api/notify?limit=-2').json()] == ['n2', 'n3', 'n0'], 'old slice'
        assert client.get('/api/notify?limit=0').json() == []
    finally:
        store.db.close()


def test_mercmode_session_rows_keep_inventory_matching(store):
    sessions = [{'session_id': 'w1-a', 'game_id': 'g', 'state': 'ended', 'detail': {'big': 'x' * 1000}},
                {'session_id': 'w2-b', 'game_id': 'g', 'state': 'running'},
                {'game_id': 'g', 'state': 'ended'}]
    for i, s in enumerate(sessions):
        store.put('session', s.get('session_id') or f'none{i}', s)
    rows = mercmode.session_rows(store)
    assert rows == [{'session_id': 'w1-a', 'game_id': 'g', 'state': 'ended'},
                    {'session_id': 'w2-b', 'game_id': 'g', 'state': 'running'},
                    {'session_id': None, 'game_id': 'g', 'state': 'ended'}]

    class Plain:                                    # a store without fields(): whole documents, as before
        def all(self, kind):
            return store.all(kind)
    assert mercmode.session_rows(Plain()) == store.all('session')


def test_federation_reads_worker_ids_and_names_only(store):
    store.put('worker', 'w1', {'id': 'w1', 'name': 'PC', 'build_sources': {'a': 'b' * 64}})
    store.put('worker', 'w2', {'id': 'w2', 'name': 'Other'})
    assert federation._worker_names(store) == [{'id': 'w1', 'name': 'PC'}, {'id': 'w2', 'name': 'Other'}]


def test_work_queue_shared_read_is_reused_until_the_file_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setattr(q, '_shared', (None, None))
    assert q.read_shared() == {'version': 1, 'items': {}, 'last_lane': 'inbox'}, 'no file yet: the default'
    q._save({'version': 1, 'items': {'inbox:x': {'job_id': 'j', 'request_id': 'r', 'dispatch_state': 'queued'}}})
    reads = []
    real = q._read
    monkeypatch.setattr(q, '_read', lambda: reads.append(1) or real())
    first = q.read_shared()
    assert q.read_shared() is first and q.claims() == {'j': 'r'} and len(reads) == 1, 'unchanged file: parsed once'
    q._save({'version': 1, 'items': {}})
    assert q.read_shared() == {'version': 1, 'items': {}} and len(reads) == 2, 'a replaced file is read again'
    assert q.claims() == {}


def test_work_queue_snapshot_copies_what_it_hands_out(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setattr(q, '_shared', (None, None))
    gid = 'a' * 16
    q._save({'version': 1, 'items': {'favorite:' + gid: {
        'game_id': gid, 'lane': 'favorite', 'favorite': True, 'title': 'Game',
        'stages': {'inventory': {'status': 'verified'}}, 'fingerprint': {'summary': 's'}}}})
    snap = q.snapshot(gid)
    snap['games'][0]['stages']['inventory']['status'] = 'changed by a caller'
    assert q.read_shared()['items']['favorite:' + gid]['stages']['inventory']['status'] == 'verified'
    assert q.snapshot(gid)['games'][0]['stages'] == {'inventory': {'status': 'verified'}}
    assert q.item_state(gid)['stages'] == {'inventory': 'verified'}
