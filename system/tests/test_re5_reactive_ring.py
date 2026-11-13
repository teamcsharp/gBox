import json
import time

import pytest

from gbox.mercs import async_flash_ring as A, grenade_ring as G
from gbox.mercs.re5_reactive_ring import Reactions, observe_event
from gbox.mercs.titles import re5_switch as R, re5_switch_prompt as P
from test_re5_grenade_ring import ring_controller


def scene(hp=1000, *, motion=0, prompt=None, generation=0x100000002):
    return {'mercenaries_phase': R.PHASE_PLAYING, 'screen': 'playing',
            'player': {'ptr': 0x200000000, 'generation': generation, 'pos': [0, 0, 0],
                       'hp': hp, 'motion': motion}, 'prompt': prompt, 'enemies': []}


def state():
    return {'round_evidence_id': 'one', 'screen': 'playing', 'ring_last_at': 10,
            'native_flash_confirmed_at': time.time()}


def test_two_observers_share_one_event_for_each_real_hit():
    st = state()
    assert observe_event(scene(), st, 10) is None
    hit = observe_event(scene(900), st, 10.1)
    assert hit['id'] == 1 and hit['kind'] == 'hit' and hit['damage'] == 100
    assert observe_event(scene(900), st, 10.1) == hit
    assert observe_event(scene(900), st, 10.2) == hit
    next_hit = observe_event(scene(800), st, 10.3)
    assert next_hit['id'] == 2 and next_hit['damage'] == 100
    observe_event(scene(1000), st, 10.4)
    assert observe_event(scene(950), st, 10.5)['id'] == 3
    json.dumps(st)                                  # no observer object enters round telemetry


@pytest.mark.parametrize('prompt,motion', [({'label': P.LABEL_BREAK_FREE, 'mode': 6}, 99),
    ({'kind': P.KIND_ENEMY, 'mode': 7, 'label': 500}, 0), (None, 100)])
def test_one_qte_event_per_real_grab_including_native_prompt_with_unmapped_motion(prompt, motion):
    st = state()
    observe_event(scene(), st, 10)
    event = observe_event(scene(900, motion=motion, prompt=prompt), st, 10.1)
    assert event['kind'] == 'qte' and event['damage'] == 100
    assert observe_event(scene(900, motion=motion, prompt=prompt), st, 10.2)['id'] == 1
    observe_event(scene(900), st, 10.3)
    assert observe_event(scene(900, motion=motion, prompt=prompt), st, 10.4)['id'] == 2


def test_pickup_place_and_traversal_prompts_are_not_combat_qte_events():
    st = state()
    for label in (P.LABEL_PICKUP, P.LABEL_PLACE, *P.TRAVERSE_LABELS):
        assert observe_event(scene(prompt={'kind': P.KIND_PLAYER, 'label': label, 'mode': 1}), st, 10) is None
    assert 'automine_event' not in st


@pytest.mark.parametrize('change', ['round', 'generation', 'operator', 'menu', 'dead', 'invalid_hp'])
def test_round_boundaries_and_nonplaying_observations_do_not_invent_damage(change):
    st, snap = state(), scene(400)
    observe_event(scene(), st, 10)
    if change == 'round': st['round_evidence_id'] = 'two'
    if change == 'generation': snap['player']['generation'] += 1
    if change == 'operator': st['operator_control'] = True
    if change == 'menu': snap['mercenaries_phase'] = -1
    if change == 'dead': snap['player']['hp'] = 0
    if change == 'invalid_hp': snap['player']['hp'] = float('nan')
    assert observe_event(snap, st, 10.1) is None
    assert 'automine_event' not in st


def test_consumed_or_expired_events_are_not_replayed_after_refusal():
    st, observer = state(), Reactions()
    observer.observe(scene(), st, 10)
    event = observer.observe(scene(900), st, 10.1)
    observer.consume(event, st, 'submitted')
    assert observer.observe(scene(900), st, 10.2) is None
    observe_event(scene(800), st, 10.3)
    assert observer.observe(scene(800), st, 14) is None
    assert st['reactive_ring_last_event']['state'] == 'expired before native admission'


def test_hit_and_qte_flash_bypass_cooldowns_and_keep_combat_input(monkeypatch, tmp_path):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    ctl, flight, st = ring_controller(), A.Flight(), state()
    ctl.async_flash_ring = True
    monkeypatch.setattr(A, 'Flight', lambda: flight)
    step = G.control(None, {'map_id': '010018100CD46000',
                           'menus': 'gbox.mercs.titles.re5_switch'}, ring=ctl)
    holds = []
    assert step.react(scene(), st, 10) is None
    hit = scene(900)
    assert step.react(hit, st, 10.1)['pending']
    first = flight.job
    assert first['done'].wait(3)
    out = step(hit, st, 10.2, holds.append)
    assert out['fired'] and out['receipt']['verified'] is True and len(ctl.spawns) == 10
    assert st['reactive_ring_receipt']['event']['kind'] == 'hit' and holds == []
    # Unchanged HP and no grab cannot turn a polling cadence into a flash loop.
    step(hit, st, 10.3, holds.append)
    assert len(ctl.spawns) == 10
    grabbed = scene(900, prompt={'label': P.LABEL_BREAK_FREE, 'mode': 6})
    assert step.react(grabbed, st, 10.4)['pending']
    assert flight.job['done'].wait(3)
    assert step.react(grabbed, st, 10.5)['fired']
    assert len(ctl.spawns) == 20 and st['reactive_ring_requests'] == 2 and holds == []
    records = [json.loads(p.read_text()) for p in tmp_path.glob('*.json')]
    assert len(records) == 2 and all(r['receipt']['state'] == 'confirmed' for r in records)


def test_automine_off_does_not_disable_flash_but_ring_off_does(monkeypatch, tmp_path):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    ctl, flight, st = ring_controller(), A.Flight(), state()
    ctl.async_flash_ring = True
    monkeypatch.setattr(A, 'Flight', lambda: flight)
    st['automine_enabled'] = False
    step = G.control(None, {'map_id': '010018100CD46000'}, ring=ctl)
    step.react(scene(), st, 10)
    assert step.react(scene(900), st, 10.1)['pending']
    assert flight.job['done'].wait(3)
    step.react(scene(900), st, 10.2)
    st['ring'] = {'enabled': False}
    assert step.react(scene(800), st, 10.3) is None
    assert len(ctl.spawns) == 10 and st['reactive_ring_last_event']['state'] == 'ring disabled'


def test_uncertain_native_result_is_archived_once_and_not_replayed(monkeypatch, tmp_path):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    ctl, flight, st = ring_controller(), A.Flight(), state()
    ctl.async_flash_ring = True
    calls = []
    def uncertain(kind, **kw):
        calls.append((kind, kw))
        return {'state': 'uncertain', 'verified': False, 'kind': kind, 'requested': 10, 'detonated': 2}
    ctl.grenade_ring = uncertain
    monkeypatch.setattr(A, 'Flight', lambda: flight)
    step = G.control(None, {'map_id': '010018100CD46000'}, ring=ctl)
    step.react(scene(), st, 10)
    step.react(scene(900), st, 10.1)
    assert flight.job['done'].wait(3)
    assert not step.react(scene(900), st, 10.2)['fired']
    assert st['reactive_ring_receipt']['state'] == 'uncertain'
    step(scene(900), st, 10.3)
    assert len(calls) == 1 and not st.get('rings_deployed')


def test_engine_runs_reactions_before_prompt_only_ticks(monkeypatch, tmp_path):
    from gbox.mercs import engine, lessons
    monkeypatch.setattr(lessons, 'ROOT', tmp_path / 'mercs' / 'lessons')
    events, sent, st, index = [], [], {}, [-1]
    sequence = ['playing', 'playing', 'dead']

    class Brain:
        def observe_reactions(self, snap, now): events.append('mines')
        def prompt_ok(self, *args): return True
        def tick(self, snap):
            assert snap['where'] != 'playing', 'a prompt should keep ownership of its controller input'
            return {'hold': ()}
        def save(self): pass

    class Driver:
        frame = None
        def snapshot(self, memory):
            return dict(scene(900 if index[0] < 2 else 0), where=sequence[index[0]])
        def screen(self, memory, snap): return snap['where']
        def progress(self, snap): return {'timer': 60., 'kills': 1, 'score': 100}
        def prompt_source(self, *args): return lambda: None
        def prompt_keys(self, key): return [('y',)]

    class Prompts:
        mashing = True
        def __init__(self, *args, **kwargs): pass
        def step(self, now, **kwargs):
            if sequence[index[0]] != 'playing': return None
            events.append('prompt')
            return [('y',)]

    def ring_step(*args):
        raise AssertionError('ordinary ring step is bypassed by the prompt')
    ring_step.react = lambda *args: events.append('ring')
    monkeypatch.setattr(G, 'control', lambda *args, **kwargs: ring_step)
    monkeypatch.setattr(engine, 'PromptPresser', Prompts)
    def stopped():
        index[0] += 1
        return index[0] >= len(sequence)
    engine.play_round({'map_id': '010018100CD46000'}, object(), sent.extend, stopped, st,
        brain=Brain(), driver=Driver(), clock=lambda: index[0] * .2, sleep=lambda _: None)
    assert events == ['ring', 'mines', 'prompt'] * 2
    assert len([e for e in sent if e['key'] == 'y' and e['down']]) == 2
