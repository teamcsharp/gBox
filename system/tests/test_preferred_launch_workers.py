"""An automatic platform launch must honor the operator's chosen PC."""
import pytest
from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.models import WorkerInfo
from gbox.server import create_app


@pytest.fixture
def routed_client(tmp_path):
    config = Config(data_dir=tmp_path, preferred_launch_workers={'ps4': 'i9-NUC'})
    app = create_app(config)
    store = app.state.store
    # Simulate Play from JAY: the platform preference must win over same-host routing.
    for name, wid, address in [('i9-NUC', 'nucworker', '10.0.0.2'),
                               ('JAYBUILTFINALE', 'jayworker', 'testclient')]:
        worker = WorkerInfo(id=wid, name=name, os='windows', tools=['launch_game'], address=address)
        store.put('worker', wid, worker.model_dump())
    store.upsert_catalog([{
        'game_id': 'ps4-game', 'title': 'PS4 game', 'platform': 'ps4',
        'source_paths': ['C:/Games/CUSA00001/eboot.bin'], 'format': 'ps4_folder', 'profile_id': 'ps4-game',
        'launch': {'kind': 'emulator', 'path': 'C:/Games/CUSA00001/eboot.bin'},
    }])
    client = TestClient(app, headers={'Authorization': f'Bearer {config.token()}'})
    yield config, store, client
    client.close()


@pytest.mark.parametrize('preference', ['i9-NUC', 'i9-nuc', 'nucworker'])
def test_auto_ps4_uses_preferred_worker_before_same_host(routed_client, preference):
    config, _, client = routed_client
    config.preferred_launch_workers['ps4'] = preference
    response = client.post('/api/games/ps4-game/launch')
    assert response.status_code == 200, response.text
    assert response.json()['require_worker'] == 'nucworker'
    assert response.json()['require_os'] is None


@pytest.mark.parametrize('missing', [False, True])
def test_offline_or_unknown_preference_does_not_fall_back_to_jay(routed_client, missing):
    config, store, client = routed_client
    if missing:
        config.preferred_launch_workers['ps4'] = 'unregistered-NUC'
    else:
        worker = store.get('worker', 'nucworker')
        store.put('worker', 'nucworker', worker | {'last_seen': 1})
    response = client.post('/api/games/ps4-game/launch')
    assert response.status_code == 409, response.text
    assert config.preferred_launch_workers['ps4'] in response.json()['detail']
    assert 'choose another node explicitly' in response.json()['detail']
    assert store.all('job') == []


@pytest.mark.parametrize('node', ['JAYBUILTFINALE', 'jayworker', 'windows'])
def test_explicit_node_overrides_offline_platform_preference(routed_client, node):
    _, store, client = routed_client
    worker = store.get('worker', 'nucworker')
    store.put('worker', 'nucworker', worker | {'last_seen': 1})
    response = client.post('/api/games/ps4-game/launch', params={'node': node})
    assert response.status_code == 200, response.text
    assert response.json()['require_worker'] == 'jayworker'
    assert response.json()['require_os'] is None


def test_no_preference_preserves_ps4_same_host_routing(routed_client):
    config, _, client = routed_client
    config.preferred_launch_workers.clear()
    response = client.post('/api/games/ps4-game/launch')
    assert response.status_code == 200, response.text
    assert response.json()['require_worker'] == 'jayworker'


def test_auto_ps4_swap_does_not_reuse_a_session_on_the_other_pc(routed_client):
    _, store, client = routed_client
    session = {'session_id': 'jayworker-existing', 'game_id': 'ps4-game',
               'state': 'running', 'started': 1, 'adapter': 'shadps4'}
    store.put('session', session['session_id'], session)
    response = client.post('/api/games/ps4-game/launch', params={'mod': 'test-mod', 'swap': True})
    assert response.status_code == 200, response.text
    assert response.json()['tool'] == 'launch_game'
    assert response.json()['require_worker'] == 'nucworker'
    assert store.get('session', session['session_id']) == session


@pytest.mark.parametrize('platform,core,expected_worker,expected_os', [
    ('ps3', None, 'jayworker', None),
    ('psp', 'ppsspp', None, 'linux'),
])
def test_other_platform_routing_is_unchanged(routed_client, platform, core, expected_worker, expected_os):
    _, store, client = routed_client
    store.upsert_catalog([{
        'game_id': 'other-game', 'title': 'Other game', 'platform': platform,
        'source_paths': ['test.iso'], 'format': 'iso', 'profile_id': 'other-game', 'core': core,
        'launch': {'kind': 'attract', 'path': 'test.iso'},
    }])
    response = client.post('/api/games/other-game/launch')
    assert response.status_code == 200, response.text
    assert response.json()['require_worker'] == expected_worker
    assert response.json()['require_os'] == expected_os
