"""The actual desktop input wrapper and bounded PSO menu/planner failures."""
import inspect
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from gbox import desktop_input_lease as L, pso_campaign as P, pso_coop as C, tools as T
from gbox.pso_coop_menu import MenuProgress


def test_attached_desktop_adapter_preserves_polite_delivery_to_both_real_entry_points():
    sent = []
    class Adapter:
        name = 'dolphin'
        def send_input(self, events, polite=False):
            sent.append((1, polite, events))
            return {'sent':len(events)}
        def send_input_player(self, events, player=1, polite=False):
            sent.append((player, polite, events))
            return {'sent':len(events)}
    ad = Adapter()
    L.attach(ad, 'test-secret')
    assert 'polite' in inspect.signature(ad.send_input).parameters
    assert 'polite' in inspect.signature(ad.send_input_player).parameters
    stats = {}
    inputs = C.Inputs(ad, lambda:False, polite=True, send_primary=T._demo_send(ad), stats=stats)
    inputs.hold([(1, ['a'], .02), (2, ['a'], .02)])
    assert {p for p, polite, rows in sent if any(r['down'] for r in rows)} == {1, 2}
    assert all(polite for _,polite,_ in sent)
    assert stats['input_down_events_acknowledged'] == 2
    assert all(not row['down'] for _,_,rows in sent[-2:] for row in rows)


def test_psocampaign_runs_existing_idle_focus_setup_before_start(monkeypatch):
    from gbox import autoplay, mercs
    from gbox.mercs import warm_boot
    ad = SimpleNamespace()
    game = {'game_id':'436e0bb84d5337d1','platform':'gamecube'}
    sid = 'worker-pso-test'
    monkeypatch.setitem(T.SESSIONS, sid, (ad, game))
    monkeypatch.setattr(T, 'AUTOPLAY', {})
    monkeypatch.setattr(T, '_session_game_id', lambda *_:game['game_id'])
    monkeypatch.setattr(autoplay, 'Driver', lambda *_args,**_kw:SimpleNamespace())
    monkeypatch.setattr(warm_boot, 'autoplay_control', lambda *_:False)
    order = []
    monkeypatch.setattr(P, 'preflight', lambda *_:order.append('preflight') or {})
    monkeypatch.setattr(T, '_demo_front', lambda *_:order.append('idle_focus'))
    monkeypatch.setattr(T, '_start_playbook', lambda *_:order.append('start') or {})
    ctx = SimpleNamespace(server='http://example.invalid', headers={'authorization':'Bearer test'}, agent_use=True)
    T._autoplay(T.AutoplayIn(session_id=sid, op='start', mode='playbook', campaign=P.CAMPAIGN,
                            demo=True, owns_keyboard=False), ctx)
    assert order == ['preflight', 'idle_focus', 'start']


def license_plan(selected='Disagree', intended='Agree'):
    return {'screen':'menu','menu_title':'Software license','selected_option':selected,
            'intended_option':intended,'selection_evidence':'Orange highlight is under '+selected}


def test_menu_cannot_confirm_intention_instead_of_highlight_or_combine_navigation():
    guard = MenuProgress()
    commands, reason = guard.review(license_plan(), [(1,['a'],.1)], (1,))
    assert not commands and 'Move the highlight' in reason
    commands, reason = guard.review(license_plan(), [(1,['up'],.1)], (1,))
    assert commands and not reason
    commands, reason = guard.review(license_plan('Agree'), [(1,['up','a'],.1)], (1,))
    assert not commands and 'separate' in reason
    commands, reason = guard.review(license_plan('Agree'), [(1,['a'],.1)], (1,))
    assert commands and not reason


def test_menu_requires_evidence_and_stops_repeated_unproductive_attempts():
    guard = MenuProgress()
    for _ in range(6):
        commands, reason = guard.review({'screen':'menu'}, [(1,['a'],.1)], (1,))
        assert not commands
    assert guard.stalled and 'Six unchanged' in reason
    assert guard.previous['input_delivery_verified'] is False
    guard.review({'screen':'loading'}, [], (2,))
    assert not guard.stalled


def test_failed_future_is_cleared_and_new_observation_is_requested(monkeypatch, tmp_path):
    clock = [10.]
    plans = [httpx.ReadTimeout('first'), ValueError('bad JSON'),
             {'thought':'Inspect setup','screen':'menu','needs_operator':True,'actions':[]}]
    calls = []
    class Planner:
        def __call__(self, frame, context):
            calls.append(context)
            result = plans.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        def close(self):
            pass
    class Executor:
        def __init__(self, **kwargs):
            pass
        def submit(self, fn, *args):
            future = Future()
            try: future.set_result(fn(*args))
            except Exception as exc: future.set_exception(exc)
            return future
        def shutdown(self, **kwargs):
            pass
    monkeypatch.setattr(C, 'ThreadPoolExecutor', Executor)
    monkeypatch.setattr(C.time, 'monotonic', lambda:clock[0])
    monkeypatch.setattr(P, 'wait', lambda *_:clock.__setitem__(0, clock[0]+9))
    monkeypatch.setattr(P, 'Planner', lambda *_:Planner())
    monkeypatch.setattr(C, 'Reader', lambda _:SimpleNamespace(snapshot=lambda:{'phase':1,'verified':False,'players':{},'entities':[]}))
    monkeypatch.setattr(C, 'SpeedSampler', lambda *_:SimpleNamespace(observe=lambda _:None, invalidate=lambda:None, failure=None))
    sent = []
    ad = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), get_frame=lambda:b'frame',
                         send_input_player=lambda rows,player:sent.append((player,rows)) or {'sent':len(rows)})
    stats = C.play(ad, lambda rows:ad.send_input_player(rows,1), lambda:False,
                   driver=SimpleNamespace(), session_id='test')
    assert len(calls) == 3 and stats['planner_requests'] == 3 and stats['planner_failures'] == 2
    assert stats['planner_responses'] == 1 and stats['campaign_state'] == 'needs_operator'
    assert not any(row['down'] for _,rows in sent for row in rows)
