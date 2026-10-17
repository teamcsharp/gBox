"""Cross-version dispatch: old workers must never reinterpret a SaveMGO bundle as a generic PS3 game."""
import copy

from fastapi.testclient import TestClient
import pytest

from gbox import savemgo
from gbox.server import create_app


def game(platform='ps3', kind='savemgo_bundle'):
    return {'game_id': 'mgo-owned', 'title': 'Metal Gear Online', 'platform': platform,
            'source_paths': ['owned/SaveMGO.zip'], 'format': 'savemgo_bundle', 'profile_id': 'mgo-owned',
            'launch': {'kind': kind, 'path': 'owned/SaveMGO.zip', 'source_fingerprint': 'a' * 64}}


def register(client, wid='old-i9', *, tools=None, os='windows'):
    body = {'id': wid, 'name': 'i9-NUC', 'os': os, 'tools': tools or ['launch_game'],
            'unavailable': {}, 'idle_seconds': 600, 'active_jobs': 0}
    response = client.post('/api/workers/register', json=body)
    assert response.status_code == 200, response.text


def queue(client, entry, **kw):
    response = client.post('/api/jobs', json={'tool': 'launch_game', 'input': {'game': entry}, **kw})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def plane(cfg):
    app = create_app(cfg)
    return TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}), app.state.store


def test_old_pinned_worker_leaves_exact_job_queued_until_refreshed_worker_claims_once(plane):
    client, store = plane
    register(client)
    job = queue(client, game(), require_worker='old-i9', require_os='windows')
    original = copy.deepcopy(store.get('job', job['id'])['input'])
    assert client.post('/api/workers/old-i9/claim').status_code == 204
    pending = client.get('/api/jobs/' + job['id']).json()
    assert pending['state'] == 'queued' and pending['worker_id'] is None and pending['started'] is None
    assert pending['input'] == original and pending['require_worker'] == 'old-i9'
    assert pending['admission_wait']['code'] == 'savemgo_worker_refresh_required'
    assert 'Restart the idle gBox app' in pending['admission_wait']['reason']
    assert client.post('/api/workers/old-i9/claim').status_code == 204
    # A normal restart re-registers a new process id; the existing alias path retargets the same queued job.
    register(client, 'fresh-i9', tools=['launch_game', 'savemgo_assets'])
    claim = client.post('/api/workers/fresh-i9/claim')
    assert claim.status_code == 200, claim.text
    claimed = claim.json()
    assert claimed['id'] == job['id'] and claimed['worker_id'] == 'fresh-i9' and claimed['state'] == 'running'
    assert claimed['input'] == original and 'admission_wait' not in claimed
    assert client.post('/api/workers/fresh-i9/claim').status_code == 204
    assert len(store.all('job')) == 1


@pytest.mark.parametrize('platform', ['ps3', 'nes'])
def test_generic_launch_is_unchanged_on_an_old_worker(plane, platform):
    client, _store = plane
    register(client)
    entry = game(platform, 'emulator')
    job = queue(client, entry, require_worker='old-i9')
    response = client.post('/api/workers/old-i9/claim')
    assert response.status_code == 200, response.text
    assert response.json()['id'] == job['id'] and 'admission_wait' not in response.json()


def test_blocked_bundle_does_not_starve_other_eligible_launches(plane):
    client, store = plane
    register(client)
    blocked = queue(client, game(), require_worker='old-i9')
    generic = queue(client, game('nes', 'emulator'), require_worker='old-i9')
    response = client.post('/api/workers/old-i9/claim')
    assert response.status_code == 200 and response.json()['id'] == generic['id']
    assert store.get('job', blocked['id'])['state'] == 'queued'


def test_bundle_never_claims_on_non_windows_even_if_marker_is_advertised(plane):
    client, store = plane
    register(client, os='linux', tools=['launch_game', 'savemgo_assets'])
    job = queue(client, game(), require_worker='old-i9')
    assert client.post('/api/workers/old-i9/claim').status_code == 204
    pending = store.get('job', job['id'])
    assert pending['state'] == 'queued' and 'Windows PC' in pending['admission_wait']['reason']


def test_guard_scope_is_only_the_builtin_bundle_launch_contract():
    assert savemgo.claim_reason({}, {'tool': 'launch_game', 'input': {'game': game()}})
    assert savemgo.claim_reason({'os': 'windows', 'tools': ['launch_game', 'savemgo_assets']},
                               {'tool': 'launch_game', 'input': {'game': game()}}) is None
    assert savemgo.claim_reason({}, {'tool': 'savemgo_assets', 'input': {'game': game()}}) is None
    assert savemgo.claim_reason({}, {'tool': 'launch_game', 'input': {'game': game(kind='emulator')}}) is None
    assert savemgo.claim_reason({}, {'tool': 'read_memory', 'input': {}}) is None
