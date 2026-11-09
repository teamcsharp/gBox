"""The blueprint look (operator 2026-11-09): a MercMode setting that plays each queue entry on its build's blueprint
companion `<build>-blueprint` while on and the plain build when off, switching at the next round boundary."""
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gbox import mercmode as M, screensaver as S
from gbox.mercmode_tool import MercModeIn
from gbox.server import create_app
from test_mercmode import rig, worker, playing, boundary


def test_default_off_and_strictly_boolean():
    assert M.DEFAULT['blueprint_look'] is False
    assert M.normalize({})['blueprint_look'] is False
    assert M.normalize({'blueprint_look': True})['blueprint_look'] is True
    for value in (0, 1, 'true', [], {}):
        with pytest.raises(ValueError, match='blueprint_look'):
            M.normalize({'blueprint_look': value})
        with pytest.raises(ValidationError):
            MercModeIn(blueprint_look=value)
    assert MercModeIn(blueprint_look=True).blueprint_look is True
    assert S.MercModeSettings(host='x', blueprint_look=False).blueprint_look is False


def test_companion_names_and_the_effective_build():
    assert M.BLUEPRINT_SUFFIX == '-blueprint'
    assert M.blueprint_name('sonic-test') == 'sonic-test-blueprint'
    assert M.blueprint_name('sonic-test-blueprint') == 'sonic-test-blueprint'
    assert M.plain_mod('sonic-test-blueprint') == 'sonic-test' and M.plain_mod('sonic-test') == 'sonic-test'
    assert M.plain_mod(None) is None and M.blueprint_name('') == ''
    on, off = {'blueprint_look': True}, {'blueprint_look': False}
    assert M.effective_mod(on, 'sonic-test') == 'sonic-test-blueprint'
    assert M.effective_mod(off, 'sonic-test') == 'sonic-test'
    assert M.effective_mod(on, None) is None                      # the stock game has no companion
    assert M.effective_mod(off, 'sonic-test-blueprint') == 'sonic-test-blueprint'   # an explicit companion stays
    # the running build versus the queue head: same while the effective build runs; a toggle flip is a restart
    assert M.same_build(off, 'sonic-test', 'sonic-test') is True
    assert M.same_build(on, 'sonic-test', 'sonic-test-blueprint') is True
    assert M.same_build(on, 'sonic-test', 'sonic-test') is False
    assert M.same_build(off, 'sonic-test', 'sonic-test-blueprint') is False
    assert M.same_build(on, 'sonic-test', 'sonic-test', {'blueprint_fallback': True}) is True   # no companion yet
    assert M.same_build(on, None, 'sonic-test') is False and M.same_build(on, 'sonic-test', None) is False


def test_default_mod_hands_the_companion_to_the_round_when_on():
    row = {'title': 're5', 'selection': {'mode': 'mercenaries', 'character': 'Chris (BSAA)', 'stage': 0, 'mod': 'sonic-test'}}
    assert M.default_mod({'blueprint_look': True}, row)['selection']['mod'] == 'sonic-test-blueprint'
    assert M.default_mod({'blueprint_look': False}, row)['selection']['mod'] == 'sonic-test'
    by_title = {'blueprint_look': True, 'default_mods': {'re5': 're5_cast'}}
    assert M.default_mod(by_title, {'title': 're5'})['selection']['mod'] == 're5_cast-blueprint'
    assert M.default_mod(by_title, row)['selection']['mod'] == 'sonic-test-blueprint'      # the DJ's build wins
    assert M.default_mod({'blueprint_look': True}, {'title': 're5'}) == {'title': 're5'}     # stock: unchanged


def test_launch_plays_the_companion_when_on_and_the_plain_build_when_off():
    store, w, saver, calls, now, tick = rig()
    M.configure(store, w['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0, 'repeat_queue': True,
                                   'blueprint_look': True,
                                   'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    tick()
    assert calls[0]['tool'] == 'launch_game' and calls[0]['input']['mod'] == 'sonic-test-blueprint'
    assert calls[0]['input']['game']['launch']['mercmode']['selection']['mod'] == 'sonic-test-blueprint'
    assert store.get(S.STATE, w['name'])['mod'] == 'sonic-test-blueprint'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'sonic-test'          # the queue keeps the plain name
    store2, w2, saver2, calls2, now2, tick2 = rig()
    M.configure(store2, w2['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0, 'repeat_queue': True,
                                     'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    tick2()
    assert calls2[0]['input']['mod'] == 'sonic-test'


def test_launch_falls_back_to_the_plain_build_while_the_companion_does_not_exist_yet():
    store, w, saver, calls, now, tick = rig()
    saver.builds = lambda gid: [{'name': 'sonic-test', 'game_id': gid}]           # this PC's index: no companion
    M.configure(store, w['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0, 'repeat_queue': True,
                                   'blueprint_look': True,
                                   'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    tick()
    assert calls[0]['input']['mod'] == 'sonic-test'
    state = store.get(S.STATE, w['name'])
    assert state['mod'] == 'sonic-test' and state['blueprint_fallback'] is True
    assert state['mercmode']['selection']['mod'] == 'sonic-test'
    # once the index knows the companion, the next cold launch takes it
    saver.builds = lambda gid: [{'name': 'sonic-test', 'game_id': gid}, {'name': 'sonic-test-blueprint', 'game_id': gid}]
    store2, w2, saver2, calls2, now2, tick2 = rig()
    saver2.builds = saver.builds
    M.configure(store2, w2['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0, 'repeat_queue': True,
                                     'blueprint_look': True,
                                     'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    tick2()
    assert calls2[0]['input']['mod'] == 'sonic-test-blueprint'


def test_toggling_restarts_at_the_next_round_boundary_and_a_matching_companion_plays_on():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run['mercmode']['title']
    character = 'Ada' if title == 're4' else 'Chris (BSAA)'
    # the companion runs and the look is on: the same build, no restart (the selection goes to the live menus)
    run['mod'] = 'sonic-test-blueprint'
    store.put(S.STATE, w['name'], run)
    M.configure(store, w['name'], {'titles': [title], 'repeat_queue': True, 'blueprint_look': True,
                                   'queue': [{'title': title, 'character': character, 'mod': 'sonic-test'}]})
    before = len(calls)
    assert saver.round_boundary(boundary(run, now[0]) | {'round_id': 'b' * 32}, job, now[0])['rotate_requested'] is False
    assert [c['input'].get('op') for c in calls[before:]] == ['mercs_select']
    # the look goes off while the companion runs: the next boundary restarts into the plain build
    now[0] += 30
    S.telemetry_put(run['session_id'], {'running': True, 'stats': {}}, now=now[0])
    M.configure(store, w['name'], {'blueprint_look': False})
    run = store.get(S.STATE, w['name'])
    assert saver.round_boundary(boundary(run, now[0]) | {'round_id': 'c' * 32}, job, now[0])['rotate_requested'] is True
    assert store.get(S.STATE, w['name'])['mercmode_mod_rotate']
    tick(1)
    assert calls[-1]['input']['op'] == 'stop_game'
    store.put('session', run['session_id'], store.get('session', run['session_id']) | {'state': 'ended'})
    tick(1)
    assert calls[-1]['tool'] == 'launch_game' and calls[-1]['input']['mod'] == 'sonic-test'


def test_the_plain_build_running_with_the_look_on_restarts_into_the_companion():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run['mercmode']['title']
    character = 'Ada' if title == 're4' else 'Chris (BSAA)'
    run['mod'] = 'sonic-test'
    store.put(S.STATE, w['name'], run)
    M.configure(store, w['name'], {'titles': [title], 'repeat_queue': True, 'blueprint_look': True,
                                   'queue': [{'title': title, 'character': character, 'mod': 'sonic-test'}]})
    assert saver.round_boundary(boundary(run, now[0]) | {'round_id': 'b' * 32}, job, now[0])['rotate_requested'] is True
    tick(1)
    assert calls[-1]['input']['op'] == 'stop_game'
    store.put('session', run['session_id'], store.get('session', run['session_id']) | {'state': 'ended'})
    tick(1)
    assert calls[-1]['tool'] == 'launch_game' and calls[-1]['input']['mod'] == 'sonic-test-blueprint'
    # a recorded fallback (no companion on this PC) is not a restart loop
    run = store.get(S.STATE, w['name'])
    run2 = run | {'mod': 'sonic-test', 'blueprint_fallback': True, 'phase': 'playing', 'session_id': 'w1-fb',
                  'mercmode': {'title': title, 'map_id': M.TITLES[title]['map_id'], 'rounds_per_title': 1}}
    assert M.same_build(M.settings(store, w['name']), 'sonic-test', run2['mod'], run2) is True


@pytest.mark.parametrize('supported', [False, True])
def test_api_forwards_blueprint_look_only_to_a_capable_local_scheduler(cfg, supported):
    app = create_app(cfg)
    store = app.state.store
    w = worker(time.time(), name='LocalOwner', os='linux')
    store.put('worker', w['id'], w | {'last_seen': time.time(), 'tools': ['mercmode'],
                                      'features': [M.BLUEPRINT_FEATURE] if supported else [],
                                      'federation': {'authority': 'authority', 'scheduler_owner': 'local'}})
    client = TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()})
    response = client.post('/api/mercmode', json={'host': w['name'], 'blueprint_look': True})
    assert response.status_code == (200 if supported else 409), response.text
    jobs = [j for j in store.all('job') if j['tool'] == 'mercmode']
    if supported:
        assert len(jobs) == 1 and jobs[0]['input']['blueprint_look'] is True
        assert M.settings(store, w['name'])['blueprint_look'] is True
    else:
        assert jobs == [] and M.settings(store, w['name'])['blueprint_look'] is False


def test_api_stores_the_setting_for_this_control_planes_own_pc_and_reports_it(cfg):
    app = create_app(cfg)
    store = app.state.store
    w = worker(time.time(), name='lilspark', os='linux')
    store.put('worker', w['id'], w | {'last_seen': time.time(), 'tools': ['mercmode', 'launch_game', 'autoplay'],
                                      'features': [M.BLUEPRINT_FEATURE]})
    client = TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()})
    response = client.post('/api/mercmode', json={'host': 'lilspark', 'blueprint_look': True})
    assert response.status_code == 200, response.text
    host = next(h for h in response.json()['hosts'] if h['name'] == 'lilspark')
    assert host['settings']['blueprint_look'] is True
    assert client.post('/api/mercmode', json={'host': 'lilspark', 'blueprint_look': 'yes'}).status_code == 422
    assert M.settings(store, 'lilspark')['blueprint_look'] is True
    assert M.BLUEPRINT_FEATURE == 'mercmode_blueprint_look'       # the name gbox.worker advertises
