"""Reset / Restart / Hard reset as one server operation (POST /api/sessions/{sid}/reset). Synthetic transport: no game.

2026-10-13, Twin Snakes on Dolphin (JAYBUILTFINALE): Reset -> session_op reset "Unsupported: dolphin has no reset:
relaunch the game instead" -> the client's session_op stop_game succeeded -> its relaunch never came; no game left.
Now: the emulator's reset where it has one, else the same game + build relaunched on the same worker BESIDE the running
copy (launch_game keep_session), which is closed only after the new one runs. Linux RPCS3 instead must confirm an exact
session stop before reusing its exclusive profile; a failed or ambiguous stop must not launch another copy.
"""
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gbox import server
from gbox.config import Config


def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


@pytest.fixture
def reset_route(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    app = server.create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'ts', 'title': 'MGS: The Twin Snakes', 'platform': 'wii',
                           'source_paths': [], 'format': 'iso'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'ts', 'state': 'running', 'adapter': 'dolphin',
                                    'mod': 'tts_sonic_full_cast', 'collection_mod': 'tts_sonic_full_cast',
                                    'staged_mod': 'tts_sonic_full_cast~9a1b', 'launch_mod': 'tts_sonic_full_cast~9a1b',
                                    'started': 1})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/reset')
    reset_job = enclosed(route.endpoint, 'reset_job').cell_contents
    session_reset = enclosed(reset_job, 'session_reset').cell_contents
    # the endpoint runs the reset synchronously here (no dispatch thread): body validation + the real reset logic
    enclosed(route.endpoint, 'reset_job').cell_contents = lambda sid, mode, actor, origin=None: session_reset(sid, actor, mode)
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    return cfg, app, store, session_reset


def transport(reset_route, *, native=None, launch_fails=False):
    _, _, store, session_reset = reset_route
    calls = []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'session_op' and inp['op'] == 'reset':
            if native is None:
                raise HTTPException(409, 'session_op failed: Unsupported: dolphin has no reset of its own')
            return {'result': native}
        if tool == 'launch_game':
            if launch_fails:
                raise HTTPException(409, 'launch_game failed: RuntimeError: Dolphin exited 1')
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts', 'state': 'running',
                                           'mod': inp.get('mod', ''), 'adapter': 'dolphin'})
            return {'session_id': 'w-new'}
        if tool == 'session_op' and inp['op'] == 'stop_game':
            if inp['session_id'] == 'w-live' and not store.get('session', 'w-new'):   # a cloud-card game: closed first (#3052)
                assert any(c[0] == 'launch_game' for c in calls) is False
            return {'ended': True}
        if tool == 'prepare_mod':
            return {'ready': True, 'mod': inp['mod']}
        if tool == 'state_transfer' and inp['op'] == 'snapshot':   # last played: the moment before a relaunch
            return {'result': {'artifact': 'm' * 64}}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(session_reset, '_run_job').cell_contents = run
    return calls


def post(reset_route, **body):
    cfg, app = reset_route[0], reset_route[1]
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        return client.post('/api/sessions/w-live/reset', json=body)


def test_native_reset_keeps_the_session_and_launches_nothing(reset_route):
    calls = transport(reset_route, native={'reset': True, 'via': 'Dolphin hotkey (F13 lane)'})
    r = post(reset_route)
    assert r.status_code == 200, r.text
    assert r.json()['mode'] == 'native' and r.json()['session_id'] == 'w-live'
    assert [t for t, _ in calls] == ['session_op'] and calls[0][1]['op'] == 'reset'
    assert reset_route[2].get('session', 'w-live')['state'] == 'running'


def test_no_native_reset_relaunches_the_same_build_beside_the_running_copy(reset_route):
    calls = transport(reset_route)
    r = post(reset_route)
    assert r.status_code == 200, r.text
    out, store = r.json(), reset_route[2]
    assert out['mode'] == 'relaunch' and out['session_id'] == 'w-new' and out['from'] == 'w-live'
    assert any('relaunched instead' in n for n in out['notes'])
    assert [(t, i.get('op')) for t, i in calls] == [('session_op', 'reset'), ('state_transfer', 'snapshot'), ('launch_game', None),
                                                    ('session_op', 'stop_game')]
    launch = calls[2][1]
    # the exact folder the running copy booted (no rebuild, no staging), started beside it
    assert launch['mod'] == 'tts_sonic_full_cast~9a1b' and launch['keep_session'] == 'w-live'
    new = store.get('session', 'w-new')
    assert (new['mod'], new['collection_mod'], new['launch_mod']) == ('tts_sonic_full_cast', 'tts_sonic_full_cast', 'tts_sonic_full_cast~9a1b')
    old = store.get('session', 'w-live')
    assert old['state'] == 'ended' and old['replaced_by'] == 'w-new' and old['exit']['via'] == 'relaunch'
    assert old['checkpoint'] == 'm' * 64, 'the moment before the relaunch is kept (Reload with your last moment)'


def test_a_relaunch_that_fails_after_the_game_is_gone_is_recorded_for_last_played(reset_route):
    store = reset_route[2]
    calls = transport(reset_route, launch_fails=True)
    run = enclosed(reset_route[3], '_run_job').cell_contents

    def gone(tool, inp, *a, **k):                      # the emulator died while the replacement was starting
        if tool == 'launch_game':
            store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended'})
        return run(tool, inp, *a, **k)
    enclosed(reset_route[3], '_run_job').cell_contents = gone
    r = post(reset_route, mode='restart')
    assert r.status_code == 409 and 'use Play again' in r.json()['detail']
    assert store.get('session', 'w-live')['exit']['via'] == 'relaunch_failed'
    assert not any(i.get('op') == 'stop_game' for _, i in calls)


def test_a_failed_relaunch_never_stops_the_game_and_says_so(reset_route):
    calls = transport(reset_route, launch_fails=True)
    r = post(reset_route)
    assert r.status_code == 409
    assert 'could not be relaunched' in r.json()['detail'] and 'still running as it was' in r.json()['detail']
    assert not any(i.get('op') == 'stop_game' for _, i in calls)
    assert reset_route[2].get('session', 'w-live')['state'] == 'running'


def test_restart_always_relaunches_and_hard_reset_needs_its_intent(reset_route):
    calls = transport(reset_route, native={'reset': True})
    r = post(reset_route, mode='restart')
    assert r.status_code == 200 and r.json()['mode'] == 'relaunch'
    assert [t for t, _ in calls][:2] == ['state_transfer', 'launch_game'], 'restart applies launch settings: no console reset'
    reset_route[2].put('session', 'w-live', reset_route[2].get('session', 'w-live') | {'state': 'running'})
    assert post(reset_route, mode='hard').status_code == 422          # a stray request can't throw the mods away
    calls.clear()
    r = post(reset_route, mode='hard', intent='hard_reset')
    assert r.status_code == 200 and r.json()['mode'] == 'hard'
    launch = next(i for t, i in calls if t == 'launch_game')
    assert launch['mod'] == '' and launch['keep_session'] == 'w-live'          # the original game, still beside the old copy
    assert not any(i.get('op') == 'reset' for _, i in calls)


def test_a_hot_swapped_model_is_restarted_through_a_swap_that_keeps_the_old_copy_until_up(reset_route):
    store = reset_route[2]
    store.put('session', 'w-live', store.get('session', 'w-live') | {'live_mod': 'tts_sonic_as_snake'})
    calls = transport(reset_route, native={'reset': True})
    r = post(reset_route)
    assert r.status_code == 200, r.text
    assert not any(i.get('op') == 'reset' for _, i in calls), "the console reset would boot the disc's own model"
    launch = next(i for t, i in calls if t == 'launch_game')
    assert launch['mod'] == 'tts_sonic_as_snake' and launch['keep_session'] == 'w-live'


def test_an_emulator_that_cannot_run_twice_relaunches_without_keep_session(reset_route):
    store = reset_route[2]
    store.put('session', 'w-live', store.get('session', 'w-live') | {'adapter': 'mgba'})
    calls = transport(reset_route)
    assert post(reset_route).status_code == 200
    assert 'keep_session' not in next(i for t, i in calls if t == 'launch_game')


def rpcs3_transport(reset_route, *, stop_output=None, stop_error=False, frozen=False, launch_fails=False):
    _, _, store, reset = reset_route
    store.put('worker', 'w', store.get('worker', 'w') | {'os': 'linux'})
    store.put('session', 'w-live', store.get('session', 'w-live') | {'adapter': 'rpcs3'})
    calls = []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'session_op' and inp['op'] == 'reset':
            raise HTTPException(409, 'session_op failed: running' if frozen else 'Unsupported: rpcs3 reset')
        if tool == 'state_transfer':
            assert inp == {'session_id': 'w-live', 'op': 'snapshot'}
            raise HTTPException(409, 'Unsupported: no safe RPCS3 snapshot')
        if tool == 'session_op' and inp['op'] == 'stop_game':
            assert inp['session_id'] == 'w-live'
            assert not store.get('session', 'w-new'), 'close only the exact old session before launch'
            if stop_error:
                raise HTTPException(409, 'session_op failed: running')
            return stop_output if stop_output is not None else {'session_id': 'w-live', 'ended': True}
        if tool == 'launch_game':
            assert store.get('session', 'w-live')['state'] == 'ended'
            assert 'keep_session' not in inp
            if launch_fails:
                raise HTTPException(409, 'launch_game failed: running')
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts', 'state': 'running', 'adapter': 'rpcs3'})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(reset, '_run_job').cell_contents = run
    return calls


@pytest.mark.parametrize('mode,frozen', [('restart', False), ('hard', False), ('reset', False), ('reset', True)])
def test_linux_rpcs3_confirms_exact_stop_before_relaunch(reset_route, mode, frozen):
    calls = rpcs3_transport(reset_route, frozen=frozen)
    response = post(reset_route, mode=mode, **({'intent': 'hard_reset'} if mode == 'hard' else {}))
    assert response.status_code == 200, response.text
    operations = [(tool, inp.get('op')) for tool, inp in calls]
    assert operations[-2:] == [('session_op', 'stop_game'), ('launch_game', None)]
    assert sum(inp.get('op') == 'stop_game' for _, inp in calls) == 1
    assert sum(tool == 'state_transfer' for tool, _ in calls) == (0 if frozen else 1)
    launch = calls[-1][1]
    assert launch['mod'] == ('' if mode == 'hard' else 'tts_sonic_full_cast~9a1b')
    assert reset_route[2].get('session', 'w-live')['replaced_by'] == 'w-new'


@pytest.mark.parametrize('output', [{}, {'ended': False, 'session_id': 'w-live'},
                                     {'ended': 1, 'session_id': 'w-live'}, {'ended': True},
                                     {'ended': True, 'session_id': 'other-live'}, 'unstructured'])
def test_linux_rpcs3_unconfirmed_stop_never_launches(reset_route, output):
    calls = rpcs3_transport(reset_route, stop_output=output)
    response = post(reset_route, mode='restart')
    assert response.status_code == 409 and 'stop of session w-live was not confirmed' in response.json()['detail']
    assert not any(tool == 'launch_game' for tool, _ in calls)
    assert reset_route[2].get('session', 'w-live')['state'] == 'running'


@pytest.mark.parametrize('frozen', [False, True])
def test_linux_rpcs3_stop_failure_aborts_even_frozen_restart(reset_route, frozen):
    calls = rpcs3_transport(reset_route, stop_error=True, frozen=frozen)
    response = post(reset_route, mode='reset')
    assert response.status_code == 409 and 'not confirmed' in response.json()['detail']
    assert not any(tool == 'launch_game' for tool, _ in calls)


def test_linux_rpcs3_launch_failure_truthfully_records_old_session_stopped(reset_route):
    calls = rpcs3_transport(reset_route, launch_fails=True)
    response = post(reset_route, mode='restart')
    assert response.status_code == 409
    assert 'previous copy is no longer running' in response.json()['detail']
    assert 'still running as it was' not in response.json()['detail']
    assert sum(tool == 'launch_game' for tool, _ in calls) == 1
    assert reset_route[2].get('session', 'w-live')['exit']['via'] == 'relaunch_failed'


def test_replaced_linux_rpcs3_sid_cannot_redirect_restart_to_new_game(reset_route):
    calls = rpcs3_transport(reset_route)
    store = reset_route[2]
    store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended', 'replaced_by': 'w-new'})
    store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts', 'state': 'running', 'adapter': 'rpcs3'})
    response = post(reset_route, mode='restart')
    assert response.status_code == 409 and 'session was replaced' in response.json()['detail']
    assert calls == [] and store.get('session', 'w-new')['state'] == 'running'


@pytest.mark.parametrize('adapter,os_name', [('rpcs3', 'windows'), ('dolphin', 'linux')])
def test_nonexclusive_restart_still_launches_beside(reset_route, adapter, os_name):
    store = reset_route[2]
    store.put('worker', 'w', store.get('worker', 'w') | {'os': os_name})
    store.put('session', 'w-live', store.get('session', 'w-live') | {'adapter': adapter})
    calls = transport(reset_route)
    assert post(reset_route, mode='restart').status_code == 200
    assert next(inp for tool, inp in calls if tool == 'launch_game')['keep_session'] == 'w-live'
    assert calls[-1][1]['op'] == 'stop_game'


@pytest.mark.parametrize('state,os_name,online,adapter,available', [
    ('running', 'linux', True, 'rpcs3', True), ('ended', 'linux', True, 'rpcs3', False),
    ('running', 'windows', True, 'rpcs3', False), ('running', 'linux', False, 'rpcs3', False),
    ('running', 'linux', True, 'dolphin', False),
])
def test_restart_capability_is_exact_read_only_and_loaded_server_scoped(reset_route, state, os_name, online, adapter, available):
    cfg, app, store, reset = reset_route
    store.put('worker', 'w', store.get('worker', 'w') | {'os': os_name, 'last_seen': time.time() if online else 1})
    store.put('session', 'w-live', store.get('session', 'w-live') | {
        'state': state, 'adapter': adapter, 'replaced_by': 'w-new'})
    store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'different', 'state': 'running', 'adapter': 'rpcs3'})
    enclosed(reset, '_run_job').cell_contents = lambda *a, **k: pytest.fail('Capability must not dispatch')
    jobs = store.all('job')
    with TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        response = client.get('/api/sessions/w-live/restart-capability')
        assert client.get('/api/sessions/missing/restart-capability').status_code == 404
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result['session_id'], result['game_id'], result['worker_id']) == ('w-live', 'ts', 'w')
    assert result['available'] is available
    assert result['capability'] == 'rpcs3_exclusive_restart_v1'
    if available:
        assert result['ordering'] == 'stop_before_launch'
    assert store.all('job') == jobs


def test_an_ended_game_is_not_reset(reset_route):
    store = reset_route[2]
    store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended'})
    transport(reset_route)
    r = post(reset_route)
    assert r.status_code == 409 and 'Play again' in r.json()['detail']


def test_reset_is_an_in_server_job_retired_after_a_restart():
    from gbox.job_maintenance import SERVER_TOOLS
    assert 'session_reset' in SERVER_TOOLS


def test_a_frozen_game_is_closed_and_started_fresh_without_a_moment_save(reset_route):
    """#2369: SC2 froze and its console reset never answered. Reset must not spend the full wait, a moment save and a
    copy beside the frozen emulator: the frozen copy is closed first and the same build started fresh."""
    _, _, store, session_reset = reset_route
    calls = []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'session_op' and inp['op'] == 'reset':
            raise HTTPException(409, 'session_op failed: running')       # the wait ran out: no answer from the emulator
        if tool == 'session_op' and inp['op'] == 'stop_game':
            store.put('session', 'w-live', store.get('session', 'w-live') | {'state': 'ended'})
            return {'ended': True}
        if tool == 'launch_game':
            assert 'keep_session' not in inp, 'a frozen copy is closed before the fresh one starts'
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts', 'state': 'running',
                                           'mod': inp.get('mod', ''), 'adapter': 'dolphin'})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)
    enclosed(session_reset, '_run_job').cell_contents = run
    r = post(reset_route)
    assert r.status_code == 200, r.text
    assert [(t, i.get('op')) for t, i in calls] == [('session_op', 'reset'), ('session_op', 'stop_game'), ('launch_game', None)]
    assert r.json()['session_id'] == 'w-new' and any('did not answer' in n for n in r.json()['notes'])
    assert calls[2][1]['mod'] == 'tts_sonic_full_cast~9a1b', 'the same build comes back'
    assert store.get('session', 'w-live')['replaced_by'] == 'w-new'


def test_a_relaunched_agent_session_stays_the_agents(tmp_path, monkeypatch):
    """2026-10-20: an agent's RE4 test session relaunched through reset came back as the operator's game, so every
    desktop offered 'Reload with your last moment' over the screensaver. The relaunch keeps the agent label."""
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    app = server.create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{'game_id': 'ts', 'title': 'MGS: The Twin Snakes', 'platform': 'gamecube',
                           'source_paths': [], 'format': 'iso'}])
    store.put('worker', 'w', {'id': 'w', 'name': 'lilspark', 'os': 'linux', 'last_seen': time.time()})
    store.put('session', 'w-live', {'session_id': 'w-live', 'game_id': 'ts', 'state': 'running', 'adapter': 'dolphin',
                                    'started': 1})
    store.put('slabel', 'w-live', {'owner': 'agent', 'task': 'RE4 Mercenaries playbook test'})
    route = next(r for r in app.routes if getattr(r, 'path', '') == '/api/sessions/{sid}/reset')
    reset_job = enclosed(route.endpoint, 'reset_job').cell_contents
    monkeypatch.setattr(server.time, 'sleep', lambda _: None)
    transport((cfg, app, store, enclosed(reset_job, 'session_reset').cell_contents))
    job = reset_job('w-live', 'reset', 'operator')
    import threading
    for _ in range(200):
        if (store.get('job', job.id) or {}).get('state') in ('succeeded', 'failed'):
            break
        threading.Event().wait(0.01)
    assert store.get('job', job.id)['state'] == 'succeeded', store.get('job', job.id)
    label = store.get('slabel', 'w-new')
    assert (label['owner'], label['task']) == ('agent', 'RE4 Mercenaries playbook test')
    from gbox import last_played
    assert last_played.is_agent_session(store, store.get('session', 'w-new'))


def test_a_cloud_card_game_closes_the_running_copy_first_so_the_card_is_free(reset_route):
    """#3052 (RE4 Reset, i9-NUC): a copy started beside the running one asked for the same cloud memory card and
    was refused ("This card is already inserted in another session"). The moment is saved, the old copy closed
    (which syncs and releases the card), then the fresh copy launched without keep_session."""
    store = reset_route[2]
    store.upsert_catalog([{'game_id': 'ts', 'title': 'Resident Evil 4', 'platform': 'gamecube', 'source_paths': [], 'format': 'iso'}])
    calls = transport(reset_route)
    r = post(reset_route)
    assert r.status_code == 200, r.text
    assert [(t, i.get('op')) for t, i in calls] == [('session_op', 'reset'), ('state_transfer', 'snapshot'),
                                                    ('session_op', 'stop_game'), ('launch_game', None)]
    assert 'keep_session' not in calls[3][1]
    assert store.get('session', 'w-live')['state'] == 'ended' and store.get('session', 'w-live')['replaced_by'] == 'w-new'


def test_only_cloud_card_adapters_hold_a_card():
    assert server.holds_cloud_card({'platform': 'gamecube'}, {'adapter': 'dolphin'})
    assert server.holds_cloud_card({'platform': 'dreamcast'}, {'adapter': 'retroarch'})
    assert not server.holds_cloud_card({'platform': 'wii'}, {'adapter': 'dolphin'})
    assert not server.holds_cloud_card({'platform': 'gamecube'}, {'adapter': 'rpcs3'})
