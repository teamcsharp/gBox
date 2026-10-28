"""Dispatch from the app: start / stop / switch MercMode on any PC and its PiP there, with per-PC checks (no emulator).

Operator 2026-10-27: "i want to be able to dispatch autoplay titles happening on different instance of gbox from gbox. So
the first request is to play mercenaries 3d on that computer pip mode".
"""
import time

import pytest
from fastapi.testclient import TestClient

from gbox import mercmode as M, screensaver as S
from gbox.server import create_app
from tests.test_mercmode import RE4, RE5, playing, rig
from tests.test_screensaver import worker

MERC3D = M.TITLES['merc3d']['game_ids'][0]
AUTH = 'authority'


# --- the real control plane: POST /api/mercmode ---

def plane(cfg, *, name='lilspark', os='linux', paired=False, features=(), wid='w1'):
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    w = worker(now, name=name, os=os) | {'id': wid, 'last_seen': now, 'tools': ['launch_game', 'autoplay', 'mercmode'],
                                         'features': list(features)}
    if paired:
        w['federation'] = {'authority': AUTH, 'scheduler_owner': 'local'}
    store.put('worker', w['id'], w)
    store.upsert_catalog([{'game_id': RE5, 'title': 'Resident Evil 5', 'platform': 'ps3', 'source_paths': ['re5']},
                          {'game_id': RE4, 'title': 'Resident Evil 4', 'platform': 'gamecube', 'source_paths': ['re4']},
                          {'game_id': MERC3D, 'title': 'Resident Evil: The Mercenaries 3D', 'platform': '3ds',
                           'source_paths': ['merc3d']}])
    client = TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()})
    return app, store, w, client


def launched_here(store, w, gid):
    """ROM access on that PC: a launch of that exact game there."""
    sid = w['id'] + '-prior-' + gid
    store.put('session', sid, {'session_id': sid, 'game_id': gid, 'state': 'ended'})


def listed_in_paired_library(store, gid, seen=None):
    """A paired PC's bridge listed that game's file as present on that PC (gbox.federation snapshot catalog)."""
    store.put('federation_catalog', AUTH + ':' + gid, {'authority': AUTH, 'worker_id': 'w1', 'game_id': gid,
                                                       'last_seen': time.time() if seen is None else seen})


def test_operator_dispatch_starts_one_title_on_a_pc_named_by_worker_id_and_asks_for_its_pip(cfg):
    app, store, w, client = plane(cfg)
    launched_here(store, w, RE5)
    response = client.post('/api/mercmode', json={'host': w['id'], 'command': 'start', 'title': 're5',
                                                   'rounds_per_title': 3, 'pip': True})
    assert response.status_code == 200, response.text
    cfg_ = M.settings(store, 'lilspark')
    assert cfg_['enabled'] is True and cfg_['titles'] == ['re5'] and cfg_['rounds_per_title'] == 3
    row = store.get(M.DISPATCH, 'lilspark')
    assert row['command'] == 'start' and row['title'] == 're5' and row['pip'] is True
    assert row['operator'] is True and row['by'] == 'operator' and row['worker_id'] == w['id']
    assert M.operator_dispatch(store, 'lilspark') is True
    host = next(h for h in response.json()['hosts'] if h['name'] == 'lilspark')
    assert host['dispatch']['id'] == row['id'] and host['dispatch']['pip'] is True
    assert host['operator_pc'] is False


def test_a_title_this_pc_cannot_play_is_refused_with_its_reason(cfg):
    app, store, w, client = plane(cfg)
    launched_here(store, w, RE5)
    # no copy of Merc3D on this PC (no launch, no probe, not a paired library): nothing is saved or started
    response = client.post('/api/mercmode', json={'host': 'lilspark', 'command': 'start', 'title': 'merc3d'})
    assert response.status_code == 422
    assert 'Resident Evil: The Mercenaries 3D is not playable on lilspark' in response.json()['detail']
    assert 'ROM access has not been verified' in response.json()['detail']
    response = client.post('/api/mercmode', json={'host': 'lilspark', 'command': 'start', 'titles': ['re5', 're3']})
    assert response.status_code == 422 and 'Resident Evil 3' in response.json()['detail']
    assert M.settings(store, 'lilspark')['enabled'] is False and store.get(M.DISPATCH, 'lilspark') is None
    # bad requests: unknown PC, unknown command, switch without its title, pip without a command
    assert client.post('/api/mercmode', json={'host': 'nobody', 'command': 'start'}).status_code == 422
    assert client.post('/api/mercmode', json={'host': 'lilspark', 'command': 'reboot'}).status_code == 422
    assert client.post('/api/mercmode', json={'host': 'lilspark', 'command': 'switch'}).status_code == 422
    assert client.post('/api/mercmode', json={'host': 'lilspark', 'pip': True}).status_code == 422


def test_the_operators_pc_is_started_only_by_the_operator(cfg):
    app, store, w, client = plane(cfg, name='JAYBUILTFINALE', os='windows')
    launched_here(store, w, RE5)
    agent = {'x-gbox-actor': 'agent'}
    for body in ({'command': 'start', 'title': 're5'}, {'enabled': True}, {'command': 'stop'}):
        response = client.post('/api/mercmode', json={'host': 'JAYBUILTFINALE', **body}, headers=agent)
        assert response.status_code == 403, body
        assert "operator's own PC" in response.json()['detail']
    for actor in ('hermes', 'mcp', 'autoplay-screensaver', 'worker:JAYBUILTFINALE'):
        response = client.post('/api/mercmode', json={'host': 'JAYBUILTFINALE', 'command': 'start', 'title': 're5'},
                               headers={'x-gbox-actor': actor})
        assert response.status_code == 403, actor
    assert M.settings(store, 'JAYBUILTFINALE')['enabled'] is False and store.get(M.DISPATCH, 'JAYBUILTFINALE') is None
    # the operator chooses it in the app: allowed
    response = client.post('/api/mercmode', json={'host': 'JAYBUILTFINALE', 'command': 'start', 'title': 're5'})
    assert response.status_code == 200, response.text
    assert next(h for h in response.json()['hosts'] if h['name'] == 'JAYBUILTFINALE')['operator_pc'] is True


def test_automation_dispatches_only_to_pcs_ticked_for_background_testing_and_keeps_their_admission(cfg):
    app, store, w, client = plane(cfg, name='i9-NUC', os='windows')
    launched_here(store, w, RE5)
    store.put('setting', 'background_testing', {'excluded': ['i9-NUC']})
    response = client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'start', 'title': 're5'},
                           headers={'x-gbox-actor': 'agent'})
    assert response.status_code == 403 and 'not ticked for background testing' in response.json()['detail']
    store.put('setting', 'background_testing', {'excluded': []})
    response = client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'start', 'title': 're5'},
                           headers={'x-gbox-actor': 'agent'})
    assert response.status_code == 200, response.text
    row = store.get(M.DISPATCH, 'i9-NUC')
    assert row['operator'] is False and row['by'] == 'agent'
    assert M.operator_dispatch(store, 'i9-NUC') is False       # the PC's own idle / tick admission still applies


def test_a_paired_pc_gets_the_dispatch_relayed_once_with_its_id_and_an_older_gbox_is_told_to_update(cfg):
    app, store, w, client = plane(cfg, name='i9-NUC', os='windows', paired=True,
                                  features=[M.WARM_FEATURE, M.STALEMATE_FEATURE, M.COOP_FEATURE])
    listed_in_paired_library(store, MERC3D)
    response = client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'start', 'title': 'merc3d', 'pip': True})
    assert response.status_code == 409 and 'relaunch gBox on that PC' in response.json()['detail']
    assert not [j for j in store.all('job') if j['tool'] == 'mercmode']
    w['features'] = w['features'] + [M.DISPATCH_FEATURE]
    store.put('worker', w['id'], w | {'last_seen': time.time()})
    response = client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'start', 'title': 'merc3d', 'pip': True})
    assert response.status_code == 200, response.text
    jobs = [j for j in store.all('job') if j['tool'] == 'mercmode']
    assert len(jobs) == 1 and jobs[0]['require_worker'] == w['id'] and jobs[0]['agent_use'] is False
    row = store.get(M.DISPATCH, 'i9-NUC')
    inp = jobs[0]['input']
    assert inp['op'] == 'configure' and inp['host'] == 'i9-NUC' and inp['enabled'] is True and inp['titles'] == ['merc3d']
    assert inp['command'] == 'start' and inp['title'] == 'merc3d' and inp['pip'] is True and inp['dispatch_id'] == row['id']
    assert store.get(M.COMMAND, 'i9-NUC')['dispatch'] == row['id']
    host = next(h for h in response.json()['hosts'] if h['name'] == 'i9-NUC')
    assert host['dispatch']['applied'] is False                 # on its way to that PC's own scheduler
    # the same dispatch again is relayed again (a command, not a setting that is already there)
    client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'start', 'title': 'merc3d', 'pip': True})
    assert len([j for j in store.all('job') if j['tool'] == 'mercmode']) == 2
    # automation's relay waits for that PC's admission
    client.post('/api/mercmode', json={'host': 'i9-NUC', 'command': 'stop'}, headers={'x-gbox-actor': 'agent'})
    assert [j for j in store.all('job') if j['tool'] == 'mercmode'][-1]['agent_use'] is True


def test_a_paired_pcs_own_library_listing_is_its_copy_of_the_game(cfg):
    app, store, w, client = plane(cfg, name='i9-NUC', os='windows', paired=True, features=[M.DISPATCH_FEATURE])
    assert M.title_reason(store, w, 'merc3d') == 'ROM access has not been verified on this PC'
    listed_in_paired_library(store, MERC3D, seen=time.time() - 2 * M.LIBRARY_EVIDENCE_S)      # long gone from there
    assert M.title_reason(store, w, 'merc3d') is not None
    listed_in_paired_library(store, MERC3D)
    assert M.title_reason(store, w, 'merc3d') is None
    row = next(r for r in M.inventory(store, w) if r['title'] == 'merc3d')
    assert row['playable'] and row['rom_access']['source'] == 'paired_local_library'
    # another authority's listing proves nothing for this PC
    store.put('federation_catalog', AUTH + ':' + MERC3D, {'authority': 'other', 'game_id': MERC3D, 'last_seen': time.time()})
    assert M.title_reason(store, w, 'merc3d') is not None


def test_the_relayed_dispatch_keeps_the_operator_only_inside_the_operators_own_job(cfg):
    app, store, w, client = plane(cfg, name='i9-NUC', os='windows')
    launched_here(store, w, MERC3D)
    store.put('job', 'relay', {'id': 'relay', 'tool': 'mercmode', 'actor': 'operator', 'agent_use': False, 'state': 'running'})
    tool = {'x-gbox-parent-job': 'relay', 'x-gbox-actor': 'worker:i9-NUC'}
    body = {'host': 'i9-NUC', 'command': 'start', 'title': 'merc3d', 'pip': True, 'dispatch_id': 'a' * 32}
    assert client.post('/api/mercmode', json=body, headers=tool).status_code == 200
    row = store.get(M.DISPATCH, 'i9-NUC')
    assert row['operator'] is True and row['id'] == 'a' * 32 and row['pip'] is True
    # an agent's job (or a dispatch id without a relay) is not the operator's
    store.put('job', 'agentjob', {'id': 'agentjob', 'tool': 'mercmode', 'actor': 'agent', 'agent_use': True, 'state': 'running'})
    assert client.post('/api/mercmode', json=body | {'dispatch_id': 'b' * 32},
                       headers={'x-gbox-parent-job': 'agentjob'}).status_code == 200
    assert store.get(M.DISPATCH, 'i9-NUC')['operator'] is False
    assert client.post('/api/mercmode', json=body | {'dispatch_id': 'c' * 32}).status_code == 200
    assert store.get(M.DISPATCH, 'i9-NUC')['id'] != 'c' * 32


@pytest.mark.parametrize('dispatched,expected', [(False, 204), (True, 200)])
def test_an_operator_dispatch_launches_on_a_busy_unticked_pc_with_memory_headroom(cfg, dispatched, expected):
    app, store, w, client = plane(cfg, name='i9-NUC', os='windows')
    now = time.time()
    w['resources'].update(cpu_percent=96, gpus=[{'name': 'GPU', 'utilization_percent': 99}])
    store.put('worker', w['id'], w | {'last_seen': now, 'idle_seconds': 0})
    store.put('setting', 'background_testing', {'excluded': ['i9-NUC']})
    M.configure(store, 'i9-NUC', {'enabled': True})
    if dispatched:
        M.record_dispatch(store, w, command='start', title='re4', actor='operator', operator=True)
    job = {'id': 'owned-launch', 'tool': 'launch_game', 'state': 'queued', 'actor': S.ACTOR, 'require_os': None,
           'require_worker': w['id'], 'agent_use': True, 'low_priority': True, 'created': now,
           'input': {'game': {'game_id': RE4, 'launch': {'mercmode': {'random_characters': True, 'random_stages': True}}}}}
    store.put('job', job['id'], job)
    store.put(S.STATE, 'i9-NUC', {'worker_id': w['id'], 'phase': 'launching', 'job': job['id'], 'game_id': RE4,
                                  'mercmode': {'title': 're4'}})
    response = client.post('/api/workers/' + w['id'] + '/claim', json={'idle_seconds': 0, 'active_jobs': 0})
    assert response.status_code == expected, response.text


# --- this PC's own scheduler (Screensaver.dispatch) ---

def test_operator_dispatch_starts_now_without_the_idle_wait_but_never_over_a_running_game():
    store, w, saver, calls, now, tick = rig()
    w.update(os='windows', idle_seconds=0)
    M.configure(store, w['name'], {'enabled': True, 'keep_warm': 0})
    assert 'without operator input' in tick()[w['name']] and not calls          # MercMode alone waits for idle time
    store.put('setting', 'background_testing', {'excluded': [w['name']]})
    store.put('session', 'w1-other', {'session_id': 'w1-other', 'game_id': 'x', 'state': 'running'})
    M.record_dispatch(store, w, command='start', actor='operator', operator=True)
    assert 'already running' in tick(1)[w['name']] and not calls                # never over another game there
    store.put('session', 'w1-other', {'session_id': 'w1-other', 'game_id': 'x', 'state': 'ended'})
    out = tick(1)[w['name']]
    assert out.startswith('launching') and calls[0]['tool'] == 'launch_game'
    assert saver.notes[w['name']] == out
    # automation's dispatch keeps the PC's admission
    store2, w2, saver2, calls2, now2, tick2 = rig()
    w2.update(os='windows', idle_seconds=0)
    M.configure(store2, w2['name'], {'enabled': True, 'keep_warm': 0})
    M.record_dispatch(store2, w2, command='start', actor='agent', operator=False)
    assert 'without operator input' in tick2()[w2['name']] and not calls2


def test_stop_closes_only_the_game_mercmode_launched_here():
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'enabled': False})
    assert saver.dispatch(w, {'command': 'stop'}).startswith('ended: MercMode stopped from the app')
    stop = calls[-1]
    assert stop['tool'] == 'session_op' and stop['input'] == {'session_id': run['session_id'], 'op': 'stop_game', 'args': {}}
    assert stop['actor'] == S.ACTOR and stop['require_worker'] == w['id'] and store.get(S.STATE, w['name']) is None


@pytest.mark.parametrize('change', ['handover', 'yours', 'operator_launch', 'adopted'])
def test_stop_never_closes_the_operators_or_an_adopted_game(change):
    store, w, saver, calls, now, tick, run, job = playing()
    if change == 'handover':
        store.put(S.STATE, w['name'], run | {'handover': 'pad'})
    elif change == 'yours':
        store.put('slabel', run['session_id'], {'owner': 'you'})
    elif change == 'operator_launch':
        store.put('job', run['job'], store.get('job', run['job']) | {'actor': 'operator'})
    else:
        store.put(S.STATE, w['name'], run | {'warm_adoption': 'proof'})
    before = len(calls)
    out = saver.dispatch(w, {'command': 'stop'})
    assert not [c for c in calls[before:] if (c.get('input') or {}).get('op') == 'stop_game'], out
    assert store.get(S.STATE, w['name']) is None and 'MercMode stopped from the app' in out


def test_stop_while_launching_cancels_a_queued_launch_or_closes_it_once_it_is_up():
    store, w, saver, calls, now, tick = rig()
    M.configure(store, w['name'], {'enabled': True, 'keep_warm': 0})
    tick()
    launch = calls[0]
    saver.dispatch(w, {'command': 'stop'})
    assert store.get('job', launch['id'])['state'] == 'cancelled' and store.get(S.STATE, w['name']) is None
    # a launch already claimed: the stop waits for its session, then closes it
    store, w, saver, calls, now, tick = rig()
    M.configure(store, w['name'], {'enabled': True, 'keep_warm': 0})
    tick()
    launch = calls[0]
    store.put('job', launch['id'], store.get('job', launch['id']) | {'state': 'running'})
    assert saver.dispatch(w, {'command': 'stop'}) == 'stopping once its launch is up'
    M.configure(store, w['name'], {'enabled': False})
    sid = 'w1-' + launch['id']
    store.put('session', sid, {'session_id': sid, 'game_id': launch['input']['game']['game_id'], 'state': 'running'})
    tick(1)                                          # up: no next title is preloaded for a game being stopped
    assert [c['tool'] for c in calls] == ['launch_game']
    tick(1)
    assert calls[-1]['input'] == {'session_id': sid, 'op': 'stop_game', 'args': {}} and len(calls) == 2
    assert store.get(S.STATE, w['name']) is None


def test_switch_ends_this_turn_now_and_the_chosen_title_plays_next():
    store, w, saver, calls, now, tick, run, job = playing()
    playing_title = run['mercmode']['title']
    other = 're4' if playing_title == 're5' else 're5'
    M.configure(store, w['name'], {'titles': [playing_title, other]})
    assert saver.dispatch(w, {'command': 'switch', 'title': other, 'id': 'd' * 32}).startswith('switching to')
    assert store.get(M.NEXT, w['name'])['title'] == other
    assert store.get(S.STATE, w['name'])['mercmode_rotate_requested'] is True
    tick(1)                                          # this turn ends (no warm pool here: its game is stopped)
    assert calls[-1]['input'] == {'session_id': run['session_id'], 'op': 'stop_game', 'args': {}}
    store.put('session', run['session_id'], store.get('session', run['session_id']) | {'state': 'ended'})
    tick(1)                                          # its game closed: the chosen title launches
    launches = [c for c in calls if c['tool'] == 'launch_game']
    assert launches[-1]['input']['game']['game_id'] == M.TITLES[other]['game_ids'][0]
    assert store.get(S.STATE, w['name'])['mercmode']['title'] == other
    # switching to the title already playing changes nothing
    assert saver.dispatch(w, {'command': 'switch', 'title': other}).startswith('already playing')


def test_the_operator_taking_a_game_over_at_that_pc_lapses_the_operator_dispatch():
    store, w, saver, calls, now, tick, run, job = playing()
    M.record_dispatch(store, w, command='start', actor='operator', operator=True)
    assert M.operator_dispatch(store, w['name']) is True
    store.put(S.STATE, w['name'], run | {'handover': 'pad'})
    tick(1)
    assert store.get(M.DISPATCH, w['name'])['lapsed'] and M.operator_dispatch(store, w['name']) is False
    M.record_dispatch(store, w, command='start', actor='operator', operator=True)
    M.configure(store, w['name'], {'enabled': False})
    assert M.operator_dispatch(store, w['name']) is False                       # MercMode off there: lapsed too


# --- a paired PC reports its own run to the central (desktop bridge -> federation snapshot) ---

def test_a_paired_pcs_live_run_shows_in_the_central_status_and_a_foreign_report_is_dropped():
    store, w, saver, calls, now, tick = rig()
    w['federation'] = {'authority': AUTH, 'scheduler_owner': 'local'}
    run = {'worker': w['name'], 'worker_id': 'w1', 'session_id': 'w1-merc', 'phase': 'playing', 'title': 'Merc3D',
           'mercmode': {'title': 'merc3d'}, 'mercmode_predecessor': {'session_id': 'w1-old'}}
    live = {'run': run, 'warm': [{'title': 're5', 'state': 'parked', 'session_id': 'w1-re5'}], 'next': None,
            'dispatch': {'id': 'e' * 32, 'command': 'start', 'title': 'merc3d', 'pip': True, 'at': now[0]},
            'note': 'playing Merc3D'}
    assert M.valid_live(live, 'w1')
    assert not M.valid_live(live | {'run': run | {'session_id': 'other-merc'}}, 'w1')          # another worker's game
    assert not M.valid_live(live | {'warm': [{'session_id': 'other-x'}]}, 'w1')
    assert not M.valid_live(live | {'launch': {}}, 'w1') and not M.valid_live(live | {'note': 'x' * 400}, 'w1')
    assert not M.valid_live(live | {'run': run | {'phase': 'stopping'}}, 'w1')
    import time as _time
    store.put(M.LIVE, w['name'], {'authority': AUTH, 'worker_id': 'w1', 'at': _time.time(), **live})
    host = saver.status()['mercmode']['hosts'][0]
    assert host['current_run']['session_id'] == 'w1-merc' and host['warm'][0]['session_id'] == 'w1-re5'
    assert host['dispatch']['applied'] is True and host['dispatch']['pip'] is True
    assert host['scheduler_note'] == 'playing Merc3D'
    # stale, or from another authority: not this PC's current run
    store.put(M.LIVE, w['name'], {'authority': 'other', 'worker_id': 'w1', 'at': _time.time(), **live})
    saver._status_cache = (0.0, None)
    assert saver.status()['mercmode']['hosts'][0]['current_run'] is None
    store.put(M.LIVE, w['name'], {'authority': AUTH, 'worker_id': 'w1', 'at': _time.time() - 2 * M.LIVE_TTL_S, **live})
    saver._status_cache = (0.0, None)
    assert saver.status()['mercmode']['hosts'][0]['current_run'] is None


def test_the_federation_snapshot_stores_a_valid_live_run_and_never_fails_on_a_bad_one(cfg):
    from tests.test_federation import AUTH as FED, KEY, WID, plane as fed_plane, snapshot
    app, client = fed_plane(cfg)
    store = app.state.store
    run = {'session_id': WID + '-' + 'd' * 32, 'phase': 'playing', 'title': 'Merc3D', 'mercmode': {'title': 'merc3d'}}
    body = snapshot() | {'scheduler_owner': 'local', 'mercmode_run': {'run': run, 'warm': [], 'next': None,
                                                                       'dispatch': None, 'note': 'playing'}}
    assert client.post('/api/federation/' + FED + '/snapshot', json=body).status_code == 200
    saved = store.get(M.LIVE, 'Owned local fixture')
    assert saved['run']['session_id'] == run['session_id'] and saved['authority'] == FED and saved['worker_id'] == WID
    bad = snapshot() | {'scheduler_owner': 'local', 'mercmode_run': {'run': run | {'session_id': 'ffff-other'}}}
    assert client.post('/api/federation/' + FED + '/snapshot', json=bad).status_code == 200      # the snapshot still lands
    assert store.get(M.LIVE, 'Owned local fixture')['run']['session_id'] == run['session_id']


def test_the_bridge_reports_this_pcs_run_pool_dispatch_and_note():
    store, w, saver, calls, now, tick, run, job = playing()
    M.record_dispatch(store, w, command='start', title='re5', pip=True, actor='operator', operator=True)
    saver.notes[w['name']] = 'playing Resident Evil 5'
    live = M.live_snapshot(store, w['name'], note=saver.notes[w['name']])
    assert live['run']['session_id'] == run['session_id'] and live['run']['phase'] == 'playing'
    assert set(live['run']) <= set(M.LIVE_RUN_KEYS) | {'mercmode_predecessor'}
    assert live['dispatch']['pip'] is True and live['note'] == 'playing Resident Evil 5'
    assert M.valid_live(live, w['id'])


def test_the_worker_tool_accepts_the_dispatch_fields_and_every_title():
    from gbox.mercmode_tool import MercModeIn
    inp = MercModeIn(op='configure', host='i9-NUC', enabled=True, titles=['merc3d'], command='start', title='merc3d',
                     pip=True, dispatch_id='a' * 32)
    assert inp.model_dump(exclude_none=True, exclude={'op'})['command'] == 'start'
    with pytest.raises(ValueError):
        MercModeIn(op='configure', command='reboot')
    import inspect
    from gbox.worker import describe
    assert repr(M.DISPATCH_FEATURE) in inspect.getsource(describe)            # the worker advertises it (the relay checks)
