"""Persistent build playlists retain explicit roster choices across rounds."""
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gbox import mercmode as M, screensaver as S
from gbox.mercmode_tool import MercModeIn
from gbox.server import create_app
from test_mercmode import rig, worker, playing, boundary


def test_default_queue_consumes_and_repeat_cycles_single_or_multiple_entries():
    store, w, *_ = rig()
    first = {'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}
    second = {'title': 're5', 'character': 'Sheva (BSAA)', 'mod': 'sheva-test'}
    cfg = M.configure(store, w['name'], {'queue': [first, second]})
    assert cfg['repeat_queue'] is False
    M.pop_queue(store, w['name'])
    assert M.settings(store, w['name'])['queue'] == cfg['queue'][1:]
    M.pop_queue(store, w['name'])
    assert M.settings(store, w['name'])['queue'] == []
    for entries in ([first], [first, second]):
        cfg = M.configure(store, w['name'], {'queue': entries, 'repeat_queue': True})
        for step in range(4):
            M.pop_queue(store, w['name'])
            offset = (step + 1) % len(entries)
            assert M.settings(store, w['name'])['queue'] == cfg['queue'][offset:] + cfg['queue'][:offset]


@pytest.mark.parametrize('value', [0, 1, 'true', [], {}])
def test_repeat_flag_is_a_strict_boolean(value):
    with pytest.raises(ValueError, match='repeat_queue'):
        M.normalize({'repeat_queue': value})
    with pytest.raises(ValidationError):
        MercModeIn(repeat_queue=value)


def test_repeat_launch_keeps_the_explicit_build_and_character():
    store, w, saver, calls, now, tick = rig()
    M.configure(store, w['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0,
        'repeat_queue': True, 'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    tick()
    assert calls[0]['input']['mod'] == 'sonic-test'
    assert calls[0]['input']['game']['launch']['mercmode']['selection']['character'] == 'Chris (BSAA)'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'sonic-test'


def test_repeated_same_build_rounds_keep_explicit_character_selection():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run['mercmode']['title']
    character = 'Ada' if title == 're4' else 'Chris (BSAA)'
    run['mod'] = 'sonic-test'
    store.put(S.STATE, w['name'], run)
    M.configure(store, w['name'], {'titles': [title], 'repeat_queue': True,
        'queue': [{'title': title, 'character': character, 'mod': 'sonic-test'}]})
    for rid in ('b' * 32, 'c' * 32):
        receipt = boundary(run, now[0]) | {'round_id': rid}
        assert saver.round_boundary(receipt, job, now[0])['rotate_requested'] is True
        tick(1)
        assert calls[-1]['input']['op'] == 'stop_game'
        session = store.get('session', run['session_id'])
        store.put('session', run['session_id'], session | {'state': 'ended'})
        tick(1)
        launch = calls[-1]
        assert launch['tool'] == 'launch_game' and launch['input']['mod'] == 'sonic-test'
        assert launch['input']['game']['launch']['mercmode']['selection']['character'] == character
        assert M.settings(store, w['name'])['queue'][0]['mod'] == 'sonic-test'
        sid = 'w1-' + launch['id']
        store.put('session', sid, {'session_id': sid, 'game_id': run['game_id'], 'state': 'running'})
        tick(1); tick(S.START_GRACE)
        run = store.get(S.STATE, w['name'])
        job = store.get('job', run['autoplay_job']) | {'state': 'succeeded'}
        store.put('job', job['id'], job)
        S.telemetry_put(sid, {'running': True, 'stats': {}}, now=now[0])


@pytest.mark.parametrize('supported', [False, True])
def test_api_forwards_repeat_only_to_capable_local_scheduler(cfg, supported):
    app = create_app(cfg)
    store = app.state.store
    w = worker(time.time(), name='LocalOwner', os='linux')
    store.put('worker', w['id'], w | {'last_seen': time.time(), 'tools': ['mercmode'],
        'features': [M.REPEAT_QUEUE_FEATURE] if supported else [],
        'federation': {'authority': 'authority', 'scheduler_owner': 'local'}})
    client = TestClient(app, headers={'Authorization': 'Bearer ' + cfg.token()})
    response = client.post('/api/mercmode', json={'host': w['name'], 'repeat_queue': True,
        'queue': [{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'sonic-test'}]})
    assert response.status_code == (200 if supported else 409), response.text
    jobs = [j for j in store.all('job') if j['tool'] == 'mercmode']
    if supported:
        assert len(jobs) == 1 and jobs[0]['input']['repeat_queue'] is True
        assert jobs[0]['input']['queue'][0]['mod'] == 'sonic-test'
    else:
        assert jobs == [] and M.settings(store, w['name'])['repeat_queue'] is False
