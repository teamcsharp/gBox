"""#1369: a reader deployed after an 'unsupported' verdict is collected, and the observer records it without a gap."""
from gbox.character_collection import AutoCollection, registered
from gbox.config import Config
from gbox.session_observers import SessionObservers
from gbox.store import Store

CT = {'game_id': 'bc02bb68790ce2e7', 'title': 'Crazy Taxi (USA)', 'platform': 'gamecube'}
STALE = {'state': 'unsupported', 'updated': 1.0, 'message': 'No native model reader registered for this game.'}


def _catalog(store, *games):
    rows = {g['game_id']: g for g in games}
    store.catalog_get = lambda gid: rows.get(gid)  # the real lookup reads the scanned library catalog


def _jobs(store, submitted):
    def submit(request):
        submitted.append(request)
        job = {'id': 'ct-collect-%d' % len(submitted), 'state': 'queued', **request}
        store.put('job', job['id'], job)
        return job
    return submit


def test_crazy_taxi_gc_reader_is_registered():
    assert registered(CT)
    assert not registered(CT | {'platform': 'dreamcast'})
    assert not registered({'game_id': 'x', 'title': 'Unknown', 'platform': 'n64'})


def test_stale_unsupported_verdict_reports_not_started_and_requeues_once(tmp_path):
    store = Store(tmp_path)
    _catalog(store, CT)
    store.put('character_collection', CT['game_id'], STALE)
    auto = AutoCollection(store, None)
    status = auto.status(CT['game_id'])
    assert status['state'] == 'not_started'
    assert status['stale_unsupported_since'] == 1.0
    assert 'No native model reader' not in status['message']
    submitted = []
    for _ in range(3):
        auto.after_launch({'input': {'game': CT}}, {'session_id': 'w-1'}, _jobs(store, submitted))
    assert len(submitted) == 1
    assert submitted[0]['tool'] == 'characters'
    assert submitted[0]['input'] == {'op': 'collect', 'game_id': CT['game_id']}
    assert submitted[0]['require_os'] == 'linux'
    assert auto.status(CT['game_id'])['state'] == 'queued'


def test_unregistered_or_uncatalogued_game_keeps_unsupported(tmp_path):
    store = Store(tmp_path)
    other = {'game_id': 'x', 'title': 'Unknown', 'platform': 'n64'}
    _catalog(store, other)
    store.put('character_collection', 'x', STALE)
    store.put('character_collection', 'missing', STALE)
    auto = AutoCollection(store, None)
    assert auto.status('x')['state'] == 'unsupported'
    assert auto.status('missing')['state'] == 'unsupported'


def _observer(store, tmp_path, api):
    return SessionObservers(store, Config(data_dir=tmp_path), api, clock=lambda: 1000, observe=lambda *_: {})


def _session(store):
    session = {'session_id': 'worker-launch', 'game_id': CT['game_id'], 'title': CT['title'],
               'state': 'running', 'last_frame_age': 1}
    store.put('session', session['session_id'], session)
    return session


def test_observer_records_completed_crazy_taxi_collection_without_gap(tmp_path):
    store = Store(tmp_path)
    _catalog(store, CT)
    session = _session(store)
    store.put('character_collection', CT['game_id'], {'state': 'queued', 'job_id': 'e945d617e6a14cf0', 'updated': 2.0})
    store.put('job', 'e945d617e6a14cf0', {'id': 'e945d617e6a14cf0', 'state': 'succeeded', 'output': {'result': {
        'status': 'complete', 'collected': 1, 'total': 1, 'extractor': 'crazy_taxi',
        'entries': [{'slug': 'crazy_taxi_yellow', 'kind': 'vehicle', 'verified': True, 'status': 'extracted'}]}}})
    def api(path, body=None, *, binary=False):
        raise AssertionError('completed collection must not queue jobs or file a models gap: ' + path)
    o = _observer(store, tmp_path, api)
    try:
        o._models(session)
    finally:
        o.close()
    models = store.get('session_observer', session['session_id'])['models']
    assert models['state'] == 'succeeded'
    assert models['result']['status'] == 'complete'
    assert 'request_id' not in models


def test_observer_requeues_stale_unsupported_after_reader_deploy(tmp_path):
    store = Store(tmp_path)
    _catalog(store, CT)
    session = _session(store)
    store.put('character_collection', CT['game_id'], STALE)
    submitted = []
    submit = _jobs(store, submitted)
    def api(path, body=None, *, binary=False):
        if path == '/api/jobs':
            return submit(body)
        raise AssertionError('no models gap expected: ' + path)
    o = _observer(store, tmp_path, api)
    try:
        o._models(session)
    finally:
        o.close()
    assert [r['input'] for r in submitted] == [{'op': 'collect', 'game_id': CT['game_id']}]
    models = store.get('session_observer', session['session_id'])['models']
    assert models['state'] == 'queued' and 'request_id' not in models


AUF = {'game_id': '65b7187589166b26', 'title': '007 - Agent Under Fire (USA)', 'platform': 'gamecube'}


def _finished(store, job_id, result):
    store.put('character_collection', AUF['game_id'], {'state': 'queued', 'job_id': job_id, 'updated': 2.0})
    store.put('job', job_id, {'id': job_id, 'state': 'succeeded', 'finished': 9e18, 'output': {'result': result}})


def test_collection_by_an_older_reader_version_is_collected_again_at_launch(tmp_path):
    """AUF reader v1 listed writer slots only (0 of 0 collected); v2 extracts every body: re-queued at the next launch
    (not after the daily partial re-collect), once."""
    from gbox import auf_chars, characters as C
    assert registered(AUF) and C.reader_version('auf') == auf_chars.READER_VERSION >= 2
    store = Store(tmp_path)
    _catalog(store, AUF)
    _finished(store, 'auf-v1', {'status': 'partial', 'collected': 0, 'total': 0, 'extractor': 'auf', 'entries': []})
    auto = AutoCollection(store, None)
    assert auto.status(AUF['game_id'])['stale_reader'] == {'extractor': 'auf', 'collected_with': 1,
                                                           'current': auf_chars.READER_VERSION}
    submitted = []
    for _ in range(3):
        auto.after_launch({'input': {'game': AUF}}, {'session_id': 'w-1'}, _jobs(store, submitted))
    assert [r['input'] for r in submitted] == [{'op': 'collect', 'game_id': AUF['game_id']}]
    assert auto.status(AUF['game_id'])['state'] == 'queued'


def test_collection_by_the_current_reader_is_not_requeued(tmp_path):
    from gbox import auf_chars
    store = Store(tmp_path)
    _catalog(store, AUF)
    _finished(store, 'auf-v2', {'status': 'complete', 'collected': 45, 'total': 45, 'extractor': 'auf',
                                'reader_version': auf_chars.READER_VERSION, 'entries': []})
    auto = AutoCollection(store, None)
    assert 'stale_reader' not in auto.status(AUF['game_id'])
    submitted = []
    auto.after_launch({'input': {'game': AUF}}, {'session_id': 'w-1'}, _jobs(store, submitted))
    assert submitted == [] and auto.status(AUF['game_id'])['state'] == 'succeeded'
