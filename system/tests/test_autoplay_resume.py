"""Explicit Restart retains an active bot; Stop and changed session identity win."""
import time

import pytest

from gbox import autoplay_resume as A, screensaver
from tests.test_session_reset import reset_route, enclosed, transport, post


def control(store, *, op='start', state='succeeded', continuous=False, at=10, ident='start', sid='w-live'):
    store.put('job', ident, {'id': ident, 'tool': 'autoplay', 'state': state, 'created': at,
        'input': {'session_id': sid, 'op': op, 'mode': 'auto', 'continuous': continuous,
                  'style': {'pace': 1.2}, 'owns_keyboard': True}})


def resume_transport(reset_route, monkeypatch, *, live=True, on_launch=None):
    calls = transport(reset_route)
    reset = reset_route[3]
    run = enclosed(reset, '_run_job').cell_contents
    monkeypatch.setattr(screensaver, 'telemetry_get', lambda sid, **kw: {'running': live, 'age_s': 1})
    def wrapped(tool, inp, *args, **kw):
        if tool == 'autoplay':
            calls.append((tool, dict(inp)))
            return {'result': {'started': 'playbook: mercs_bot'}}
        out = run(tool, inp, *args, **kw)
        if tool == 'launch_game' and on_launch:
            on_launch()
        return out
    enclosed(reset, '_run_job').cell_contents = wrapped
    return calls


def test_restart_resumes_active_bot_with_settings_on_verified_replacement(reset_route, monkeypatch):
    control(reset_route[2])
    calls = resume_transport(reset_route, monkeypatch)
    response = post(reset_route, mode='restart')
    assert response.status_code == 200, response.text
    assert response.json()['autoplay_resumed']
    tool, inp = calls[-1]
    assert tool == 'autoplay' and inp['session_id'] == 'w-new' and inp['op'] == 'start'
    assert inp['style'] == {'pace': 1.2} and inp['owns_keyboard'] and inp['reset'] is False
    assert next(i for i, row in enumerate(calls) if row[1].get('op') == 'stop_game') < len(calls)-1


@pytest.mark.parametrize('state', ['queued', 'running', 'succeeded', 'failed'])
def test_latest_stop_intent_prevents_resume_even_with_stale_running_telemetry(reset_route, monkeypatch, state):
    control(reset_route[2], continuous=True)
    control(reset_route[2], op='stop', state=state, at=20, ident='stop')
    calls = resume_transport(reset_route, monkeypatch)
    response = post(reset_route, mode='restart')
    assert response.status_code == 200 and not response.json()['autoplay_resumed']
    assert not A.continuous(reset_route[2], 'w-live')
    assert not any(tool == 'autoplay' for tool, _ in calls)


def test_stop_during_launch_cancels_captured_resume_intent(reset_route, monkeypatch):
    control(reset_route[2], continuous=True)
    calls = resume_transport(reset_route, monkeypatch, on_launch=lambda:
        control(reset_route[2], op='stop', at=20, ident='stop'))
    assert not post(reset_route, mode='restart').json()['autoplay_resumed']
    assert not any(tool == 'autoplay' for tool, _ in calls)


@pytest.mark.parametrize('continuous', [False, True])
def test_only_continuous_opt_in_resumes_an_already_stopped_bot(reset_route, monkeypatch, continuous):
    control(reset_route[2], continuous=continuous)
    calls = resume_transport(reset_route, monkeypatch, live=False)
    assert A.continuous(reset_route[2], 'w-live') is continuous
    assert post(reset_route, mode='restart').json()['autoplay_resumed'] is continuous
    assert any(tool == 'autoplay' for tool, _ in calls) is continuous


def test_replacement_must_match_original_game(reset_route):
    store = reset_route[2]
    control(store, continuous=True)
    capture = A.snapshot(store, 'w-live', {})
    store.put('session', 'w-live', store.get('session', 'w-live') | {'replaced_by': 'w-new'})
    store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'other', 'state': 'running'})
    assert A.replacement_input(store, 'w-live', 'w-new', capture) is None


def test_reconciliation_order_cannot_resurrect_an_old_start(reset_route):
    store = reset_route[2]
    control(store, continuous=True)
    control(store, op='stop', at=20, ident='stop')
    store.put('job', 'start', store.get('job', 'start') | {'updated': time.time()})
    assert not A.continuous(store, 'w-live')


@pytest.mark.parametrize('op', ['start', 'stop'])
def test_new_session_control_during_launch_prevents_captured_resume(reset_route, monkeypatch, op):
    control(reset_route[2], continuous=True)
    calls = resume_transport(reset_route, monkeypatch, on_launch=lambda:
        control(reset_route[2], sid='w-new', op=op, at=20, ident='new-intent'))
    assert not post(reset_route, mode='restart').json()['autoplay_resumed']
    assert not any(tool == 'autoplay' for tool, _ in calls)


def test_human_takeover_during_launch_cancels_captured_resume(reset_route, monkeypatch):
    control(reset_route[2], continuous=True)
    calls = resume_transport(reset_route, monkeypatch, on_launch=lambda:
        A.note_handoff(reset_route[2], 'w-live', 'start'))
    assert not post(reset_route, mode='restart').json()['autoplay_resumed']
    assert not any(tool == 'autoplay' for tool, _ in calls)
