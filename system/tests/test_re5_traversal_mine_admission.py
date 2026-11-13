"""Landing events enter the native queue once without relocating their mine."""
import json
import threading

import pytest

from gbox.mercs.titles import re5_native_mine_tactic as N, re5_switch_mines as M
from test_re5_native_mine_tactic import scene, stats, memory, receipt, verified_test_backend


def landing(s, st, at=1., ident=1):
    event = dict(id=ident, kind='traversal', at=at, owner=list(N.identity(s, st)),
                 pos=list(s['player']['pos']), traversal='ladder', entered_at=at-2.,
                 native_action='cPlAction_pl_act_ladder_v_climb',
                 completed_action='cPlAction_pl_act_walk', completion_flag_seen=True,
                 evidence='native owned action exit and stable landing')
    st['traversal_mine_event'] = event
    return event


def test_landing_has_its_own_deduplication_namespace_and_precedes_travel():
    s, st, cadence = scene(), stats(), N.Cadence()
    cadence.observe(s, st, 1.)
    cadence.distance = N.DISTANCE_CM
    landing(s, st)
    st['automine_event'] = dict(id=1, kind='hit', at=1., owner=list(cadence.owner))
    assert cadence.demand(s, st, 1.) == ('hit', 1)
    cadence.claimed(('hit', 1), 1.)
    assert cadence.demand(s, st, 2.) is None
    assert cadence.demand(s, st, 4.) == ('traversal', 1)
    cadence.claimed(('traversal', 1), 4.)
    assert cadence.demand(s, st, 7.) is None
    landing(s, st, at=7., ident=2)
    assert cadence.demand(s, st, 7.) == ('traversal', 2)


@pytest.mark.parametrize('change', ['expired', 'future', 'round', 'life', 'invalid_pos', 'disabled'])
def test_invalid_or_disabled_landing_cannot_replay(change):
    s, st, cadence = scene(), stats(), N.Cadence()
    cadence.observe(s, st, 1.)
    event = landing(s, st)
    if change == 'expired': event['at'] = -5.
    elif change == 'future': event['at'] = 5.
    elif change == 'round': event['owner'][0] = 'old-round'
    elif change == 'life': event['owner'][2] = 2
    elif change == 'invalid_pos': event['pos'][0] = float('nan')
    elif change == 'disabled':
        cadence.observe(s, st, 1., enabled=False)
        cadence.observe(s, st, 1.1, enabled=True)
    assert cadence.demand(s, st, 1.2) is None


def test_landing_queues_one_armed_mine_at_original_exit_and_counts_only_receipt():
    s, st, mem, calls = scene(), stats(), memory(), []
    mine = M.Mines(st); mine.new_round(0.)
    gate, entered = threading.Event(), threading.Event()
    def run(memory, expected, allowed, **kwargs):
        calls.append(kwargs); entered.set()
        assert gate.wait(3.) and allowed()
        return receipt()
    mine.native = N.Flight(mem, run=run)
    mine.observe_native(mem, s, 0.)
    event = landing(s, st)
    st['ring_async_pending'] = True
    mine.observe_native(mem, s, 1.)
    assert mine.native.job is None
    s['player']['pos'] = (400., 0., 0.)
    st['ring_async_pending'] = False
    try:
        mine.observe_native(mem, s, 1.2)
        assert entered.wait(3.)
        job = mine.native.job
        assert calls[0]['count'] == 1 and calls[0]['center'] == (0., 0., 0.)
        assert st['mine_landing_requests'] == 1 and st.get('mine_landing_drops', 0) == 0
        assert st['mines_placed'] == 0 and not mine.bombs
        assert mine.automatic(s['player'], s, [], 1.3) is None
        gate.set(); assert job['done'].wait(3.)
        mine.observe_native(mem, s, 1.4)
        assert st['mine_landing_drops'] == st['mines_placed'] == 1
        assert st['mine_landing_last']['confirmed_armed'] == 1
        assert st['mine_landing_last']['center'] == (0., 0., 0.)
        archive = json.loads(job['path'].read_text())
        assert archive['reason'] == 'traversal' and archive['traversal']['id'] == event['id']
        assert archive['traversal']['pos'] == [0., 0., 0.]
        mine.observe_native(mem, s, 4.3)
        assert len(calls) == 1 and st['mine_landing_drops'] == 1
    finally:
        gate.set()


def test_existing_escape_defers_landing_without_consuming_it():
    s, st, mem = scene(), stats(), memory()
    mine = M.Mines(st); mine.new_round(0.)
    mine.native = N.Flight(mem, run=lambda *a, **k: receipt())
    mine.observe_native(mem, s, 0.)
    landing(s, st)
    mine._native_escape = {'id': 'old'}
    mine.observe_native(mem, s, 1.)
    assert mine.native.job is None and mine.cadence.traversal_id is None
    assert 'finish native mine escape' in st['mine_blocked_reason']
    mine._native_escape = None
    mine.observe_native(mem, s, 1.1)
    assert mine.native.job['done'].wait(3.)
    assert mine.cadence.traversal_id == 1


def test_uncertain_landing_does_not_claim_armed_drop_or_retry():
    s, st, mem, calls = scene(), stats(), memory(), []
    mine = M.Mines(st); mine.new_round(0.)
    mine.native = N.Flight(mem, run=lambda *a, **kw: calls.append(kw) or receipt('uncertain', armed=False))
    mine.observe_native(mem, s, 0.)
    landing(s, st)
    mine.observe_native(mem, s, 1.)
    assert mine.native.job['done'].wait(3.)
    mine.observe_native(mem, s, 1.1)
    assert st['mine_landing_drops'] == st['mines_placed'] == 0
    assert st['mine_landing_last']['state'] == 'uncertain' and mine.bombs
    landing(s, st, at=4.2, ident=2)
    mine.observe_native(mem, s, 4.2)
    assert len(calls) == 1 and mine.native.blocked_owner is not None


@pytest.mark.parametrize('change', ['expired', 'missing', 'replaced', 'moved_anchor'])
def test_waiting_native_work_loses_admission_when_landing_evidence_changes(change, monkeypatch):
    s, st, mem = scene(), stats(), memory()
    landing(s, st)
    clock = [100.]
    monkeypatch.setattr(N.time, 'monotonic', lambda: clock[0])
    gate, entered = threading.Event(), threading.Event()
    def run(memory, expected, allowed, **kw):
        entered.set()
        assert gate.wait(3.)
        assert not allowed()
        return {'state': 'unavailable', 'reason': 'landing no longer eligible'}
    flight = N.Flight(mem, run=run)
    try:
        assert flight.submit(s, st, 1., reason='traversal', center=(0., 0., 0.))
        assert entered.wait(3.)
        job = flight.job
        if change == 'expired': clock[0] = 106.
        elif change == 'missing': st.pop('traversal_mine_event')
        elif change == 'replaced': st['traversal_mine_event']['id'] += 1
        else: st['traversal_mine_event']['pos'][0] = 200.
        flight.observe(s, st)  # generic live-player freshness cannot renew a landing
        gate.set(); assert job['done'].wait(3.)
        assert flight.poll(s, st)['receipt']['state'] == 'unavailable'
    finally:
        gate.set()


def test_committed_landing_still_observes_arming_after_token_expires(monkeypatch):
    s, st, mem = scene(), stats(), memory()
    landing(s, st)
    clock = [100.]
    monkeypatch.setattr(N.time, 'monotonic', lambda: clock[0])
    gate, deployed = threading.Event(), threading.Event()
    def run(memory, expected, allowed, **kw):
        assert allowed()
        kw['on_deployed'](receipt()['mines'][0])
        deployed.set()
        assert gate.wait(3.) and allowed()
        return receipt()
    flight = N.Flight(mem, run=run)
    try:
        assert flight.submit(s, st, 1., reason='traversal', center=(0., 0., 0.))
        assert deployed.wait(3.)
        job = flight.job
        st.pop('traversal_mine_event'); clock[0] = 106.
        flight.observe(s, st)
        gate.set(); assert job['done'].wait(3.)
        assert flight.poll(s, st)['receipt']['state'] == 'confirmed'
        assert len(flight.take_deployments()) == 1
    finally:
        gate.set()
