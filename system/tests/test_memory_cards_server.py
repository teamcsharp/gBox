"""Real server authentication/live RPC wiring and launch safety without an emulator."""
import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import memory_card_sessions as M, tools
from gbox.models import CatalogEntry
from gbox.registry import Ctx
from gbox.server import create_app


def setup(cfg, current=True):
    app = create_app(cfg); store = app.state.store
    store.upsert_catalog([{'game_id': 'pso', 'title': 'Phantasy Star Online', 'platform': 'dreamcast'}])
    source_root = Path(M.__file__).parent
    sources = {f'gbox/{name}': hashlib.sha256((source_root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
               for name in ('memory_card_sessions.py', 'memory_card_emulators.py', 'tools.py', 'adapters.py')}
    if not current:
        sources['gbox/memory_card_sessions.py'] = 'stale'
    store.put('worker', 'w1', {'id': 'w1', 'name': 'Test PC', 'last_seen': time.time(), 'build_sources': sources})
    store.put('session', 'w1-session', {'session_id': 'w1-session', 'worker_id': 'w1', 'game_id': 'pso', 'state': 'running'})
    headers = {'Authorization': 'Bearer ' + cfg.token()}
    return TestClient(app, headers=headers), app


def command(**kw):
    return {'op': 'memory_cards', 'args': {'command_id': str(uuid.uuid4()), 'expires': time.time() + 8,
                                         'input': {'op': 'status', **kw}}}


def test_real_server_registers_authenticated_cloud_card_routes(cfg):
    client, app = setup(cfg)
    anonymous = TestClient(app)
    assert anonymous.get('/api/memory-cards', params={'platform': 'dreamcast'}).status_code == 401
    assert anonymous.post('/api/memory-cards', json={'name': 'Private', 'platform': 'dreamcast'}).status_code == 401
    response = client.post('/api/memory-cards', json={'name': 'Dedicated PSO', 'platform': 'dreamcast', 'game_id': 'pso'})
    assert response.status_code == 200, response.text
    card = response.json()
    assert card['capacity']['formatted'] and card['capacity']['free_blocks'] == 200
    listed = client.get('/api/memory-cards', params={'platform': 'dreamcast', 'session_id': 'w1-session'}).json()
    assert listed['selection'] == {'A1': card['id']} and listed['cards'][0]['id'] == card['id']
    assert anonymous.get('/api/memory-cards/' + card['id'] + '/data').status_code == 401
    assert hashlib.sha256(client.get('/api/memory-cards/' + card['id'] + '/data').content).hexdigest() == card['sha256']


def test_current_worker_card_status_roundtrips_over_real_session_rpc(cfg):
    client, app = setup(cfg); body = command(); sid = 'w1-session'
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(client.post, f'/api/sessions/{sid}/rpc', json=body)
        queued = client.get(f'/api/sessions/{sid}/input', params={'wait': 1}).json()
        assert len(queued) == 1 and queued[0]['op'] == 'memory_cards'
        assert queued[0]['args'] == body['args']
        assert app.state.store.all('job') == []
        actual = {'supported': True, 'live_switch': False, 'slots': [{'slot': 'A1', 'sync_state': 'synced'}]}
        answer = client.post(f'/api/sessions/{sid}/rpc/{queued[0]["rpc"]}',
                             json={'ok': True, 'data': actual, 'pso_command': True})
        assert answer.status_code == 200
        response = future.result(timeout=5)
    assert response.status_code == 200 and response.json() == actual
    assert client.get(f'/api/sessions/{sid}/input').json() == []


def test_stale_worker_is_rejected_before_rpc_is_queued(cfg):
    client, app = setup(cfg, current=False)
    result = client.post('/api/sessions/w1-session/rpc', json=command())
    assert result.status_code == 422 and 'idle update' in result.text
    assert client.get('/api/sessions/w1-session/input').json() == []
    assert app.state.store.all('job') == []


def test_memory_card_rpc_enforces_stage_permission_and_command_expiry(cfg):
    client, app = setup(cfg)
    expired = command(); expired['args']['expires'] = time.time() - 1
    assert client.post('/api/sessions/w1-session/rpc', json=expired).status_code == 422
    cfg.granted_permissions = ['read', 'execute']
    denied = client.post('/api/sessions/w1-session/rpc', json=command())
    assert denied.status_code == 403 and 'stage permission' in denied.text
    assert client.get('/api/sessions/w1-session/input').json() == []


def launch_fixture(cfg, tmp_path, monkeypatch, platform='nes', monitor_error=False,
                   adapter_name='synthetic', server=None):
    from gbox import gameplay_replay, tas
    rom = tmp_path / 'fixture.rom'; rom.write_bytes(b'owned synthetic test bytes')
    game = CatalogEntry(game_id='fixture', title='Fixture', platform=platform,
                        source_paths=[str(rom)], format='rom', profile_id='fixture')
    calls = []
    ad = SimpleNamespace(name=adapter_name, launch_game=lambda path: calls.append(path) or {'pid': 1234},
                         get_capabilities=lambda: {})
    monkeypatch.setattr(tools.adapters, 'for_game', lambda *args, **kwargs: ad)
    monkeypatch.setattr(tools, 'rom_path', lambda *args: rom)
    monkeypatch.setattr(tools, 'SESSIONS', {})
    monkeypatch.setattr(tools, '_close_previous_games', lambda *args, **kwargs: [])
    monkeypatch.setattr(tools, 'track_emulator', lambda *args, **kwargs: None)
    monkeypatch.setattr(tools, '_pump', lambda *args, **kwargs: None)
    for module in (tools.rewind, tools.ring_record, tools.ghost_runs, gameplay_replay, tas):
        monkeypatch.setattr(module, 'start', lambda *args, **kwargs: {})
    if monitor_error:
        def checked_out(*args, operator_cards=False):
            ad.memory_card_context = {'platform': platform, 'slots': {}}
        def failed_monitor(*args):
            raise RuntimeError('Card monitor interrupted after game started')
        monkeypatch.setattr(M, 'checkout', checked_out)
        monkeypatch.setattr(M, 'watch', failed_monitor)
    else:
        def no_cloud(*args, **kwargs):
            raise AssertionError('Non-card launch must not contact card cloud')
        monkeypatch.setattr(M, 'api', no_cloud)
    ctx = Ctx(cfg, job_id='launch', worker='w1')
    ctx.server = server
    ctx.progress = lambda *args, **kwargs: None
    result = tools.launch_game(tools.LaunchIn(game=game), ctx)
    return result, calls, ad


def test_non_card_game_launch_keeps_working_without_cloud_memory_cards(cfg, tmp_path, monkeypatch):
    result, calls, ad = launch_fixture(cfg, tmp_path, monkeypatch)
    assert len(calls) == 1 and result['session_id'] == 'w1-launch'
    assert 'memory_cards' not in result['detail']
    assert tools.SESSIONS[result['session_id']][0] is ad


def test_card_monitor_error_cannot_fail_an_already_running_game(cfg, tmp_path, monkeypatch):
    result, calls, ad = launch_fixture(cfg, tmp_path, monkeypatch, 'dreamcast', monitor_error=True)
    assert len(calls) == 1 and result['session_id'] == 'w1-launch'
    detail = result['detail']['memory_cards']
    assert detail['supported'] is False and 'monitor interrupted' in detail['reason']
    assert tools.SESSIONS[result['session_id']][0] is ad and ad.memory_card_context


def test_unverified_gamecube_region_skips_cloud_cards_but_keeps_game_launch_and_reports_reason(cfg, tmp_path, monkeypatch):
    reason = 'Cannot verify the GameCube region of this compressed RVZ image'
    def unsupported_region(*args, **kwargs):
        raise ValueError(reason)
    monkeypatch.setattr(M.native, 'gc_region', unsupported_region)
    # launch_fixture makes every card-cloud call fail: verification must stop
    # management before acquiring any lease, while normal emulator boot proceeds.
    result, calls, ad = launch_fixture(cfg, tmp_path, monkeypatch, 'gamecube',
                                     adapter_name='dolphin', server='http://unused-test-cloud')
    assert len(calls) == 1 and result['session_id'] == 'w1-launch'
    assert tools.SESSIONS[result['session_id']][0] is ad
    assert ad.memory_card_unavailable == reason and not getattr(ad, 'memory_card_context', None)
    with pytest.raises(RuntimeError, match='Cannot verify the GameCube region'):
        M.attach(result['session_id'], ad, {'platform': 'gamecube'}, SimpleNamespace(worker='w1'))
