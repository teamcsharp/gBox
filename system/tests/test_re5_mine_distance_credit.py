"""A proved inactive refusal restores travel once, without a catch-up burst."""
import pytest

from gbox.mercs.titles import re5_native_mine_tactic as N, re5_switch_mines as M
from gbox.mercs.titles import re5_mine_refusal as F, re5_proximity_native as P
from test_re5_native_mine_tactic import scene, stats
from test_re5_mine_refusal import fixture, completed


def cadence(credit=279.4):
    c, s, st = N.Cadence(), scene(), stats()
    c.observe(s, st, 0.)
    c.distance = credit
    st['automine_event'] = {'id': 'hit-one', 'kind': 'hit', 'owner': list(c.owner), 'at': 1.}
    c.claimed(('hit', 'hit-one'), 1., request_id='request-one')
    return c, s, st


def release(c, request='request-one'):
    return {'state': 'verified_inactive', 'id': request, 'owner': c.owner}


def test_restore_preserves_travel_since_claim_and_keeps_hit_consumed():
    c, s, st = cadence()
    c.observe(s, st, 1.)
    s['player']['pos'] = (1.1, 0., 0.)
    c.observe(s, st, 1.1)
    assert c.distance == pytest.approx(1.1)
    assert c.reconcile(release(c), st)
    assert c.distance == pytest.approx(280.5)
    assert c.event_id == 'hit-one' and c.last_request == 1.
    assert c.demand(s, st, 1.2) is None and c.demand(s, st, 4.) is None
    assert st['automine_credit_restore']['restored_cm'] == 279.4
    assert not c.reconcile(release(c), st)
    assert c.distance == pytest.approx(280.5) and st['automine_credit_restorations'] == 1


def test_combined_credit_is_capped_at_one_drop_without_resetting_request_gap():
    c, s, st = cadence(N.DISTANCE_CM)
    c.distance = N.DISTANCE_CM  # one capped credit already earned while the worker was pending
    assert c.reconcile(release(c), st)
    assert c.distance == N.DISTANCE_CM
    assert c.demand(s, st, 3.99) is None
    assert c.demand(s, st, 4.) == ('distance', None)
    c.claimed(('distance', None), 4., request_id='request-two')
    assert c.distance == 0 and c.demand(s, st, 10.) is None
    assert not c.reconcile(release(c), st)  # the old release cannot refill the next drop


@pytest.mark.parametrize('change', ['round', 'player', 'life', 'request', 'unknown', 'unsafe', 'busy'])
def test_unmatched_or_unproved_release_does_not_restore_credit(change):
    c, s, st = cadence()
    result = release(c)
    if change in ('round', 'player', 'life'):
        owner = list(c.owner)
        index = ('round', 'player', 'life').index(change)
        owner[index] = 'other-round' if index == 0 else owner[index] + 1
        result['owner'] = tuple(owner)
    elif change == 'request':
        result['id'] = 'previous-request'
    else:
        result['state'] = change
    assert not c.reconcile(result, st)
    assert c.distance == 0 and 'automine_credit_restorations' not in st


@pytest.mark.parametrize('change', ['round', 'life', 'off'])
def test_new_owner_or_toggle_off_discards_the_reserved_credit(change):
    c, s, st = cadence()
    old = release(c)
    if change == 'round': st['round_evidence_id'] = 'round-two'
    elif change == 'life': s['player']['generation'] += 1
    c.observe(s, st, 2., enabled=change != 'off')
    c.observe(s, st, 3., enabled=True)
    assert c.reserved_credit is None and not c.reconcile(old, st)
    assert c.distance == 0


def test_new_claim_replaces_old_reserve_without_inheriting_it():
    c, s, st = cadence(500.)
    old = release(c)
    c.distance = 100.
    c.claimed(('qte', 'event-two'), 5., request_id='request-two')
    assert not c.reconcile(old, st)
    assert c.reconcile(release(c, 'request-two'), st)
    assert c.distance == 100. and c.event_id == 'event-two'


def test_diagnostic_receipt_is_not_a_credit_release():
    c, s, st = cadence()
    st['native_mine_refusal_retry'] = dict(release(c), verified_actors=5)
    st['native_mine_refusal_recoveries'] = 100
    c.observe(s, st, 2.)
    assert c.distance == 0 and c.reserved_credit is not None


def test_real_inactive_proof_yields_exactly_one_private_release(monkeypatch):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    assert flight.poll(snap, st)['receipt']['placed'] == 0
    released = flight.take_refusal_release()
    assert released == {'state': 'verified_inactive', 'id': 'floor-refused', 'owner': owner}
    assert flight.take_refusal_release() is None


@pytest.mark.parametrize('change', ['active', 'uncertain', 'partial', 'operator_after_proof'])
def test_incomplete_or_no_longer_admitted_proof_cannot_release_credit(monkeypatch, change):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    if change == 'active':
        ctl.put(receipt['prepared'][0]['unit'] + 0x27B9, b'\1')
    elif change == 'uncertain':
        receipt['state'] = 'uncertain'
    elif change == 'partial':
        receipt['placed'] = 1
    else:
        original = F.verify
        def pause(*args, **kw):
            result = original(*args, **kw)
            assert result['state'] == 'verified_inactive'
            st['operator_control'] = True
            return result
        monkeypatch.setattr(F, 'verify', pause)
    flight.poll(snap, st)
    assert flight.blocked_owner == owner and flight.take_refusal_release() is None


@pytest.mark.parametrize('change', ['owner', 'close'])
def test_private_release_is_discarded_after_new_owner_or_close(monkeypatch, change):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    flight.poll(snap, st)
    if change == 'owner':
        st['round_evidence_id'] = 'next-round'
        flight.observe(snap, st)
    else:
        flight.close()
    assert flight.take_refusal_release() is None


def test_floor_refused_hit_ring_restores_credit_then_one_travel_drop_after_cooldown(monkeypatch, tmp_path):
    # Actual Cadence -> Mines -> Flight -> native place/refusal verifier path.
    # The fixture's native calls model allocation/arming; this is not live proof.
    ctl, memory, owner, old_receipt = fixture(monkeypatch)
    monkeypatch.setattr(P, 'LIVE_VERIFIED', True)
    monkeypatch.setattr(N, 'ROOT', tmp_path)
    s, st = scene(), stats()
    s['player'].update(ptr=owner[1], generation=owner[2])
    mines = M.Mines(st); mines.new_round(0.)
    mines.observe_native(memory, s, 0.)
    mines.cadence.distance = 279.4
    s['player']['hp'] = 800
    mines.observe_native(memory, s, 1.)
    refused = mines.native.job
    assert refused is not None and refused['requested'] == 5 and refused['reason'] == 'hit'
    assert refused['done'].wait(3)
    assert refused['result']['floor_refused'] and refused['result']['placed'] == refused['result']['armed'] == 0
    assert mines.cadence.distance == 0
    # Physical flight since submission is retained in addition to saved credit.
    s['player']['pos'] = (340., 0., 0.)
    mines.observe_native(memory, s, 1.5)
    assert mines.cadence.distance == N.DISTANCE_CM
    assert st['automine_credit_restore']['id'] == refused['id']
    assert st['automine_credit_restorations'] == 1 and st['mines_placed'] == 0
    assert mines.native.blocked_owner is None and mines.native.job is None
    mines.automatic(s['player'], s, [], 1.5)  # zero real hazards clears predicted-only retreat
    assert mines._native_escape is None
    ctl.call = ctl.fixture_native_call
    mines.observe_native(memory, s, 4.49)
    assert mines.native.job is None  # 3 s retry delay from the observed refusal
    mines.observe_native(memory, s, 4.5)
    placed = mines.native.job
    assert placed is not None and placed['requested'] == 1 and placed['reason'] == 'distance'
    assert placed['done'].wait(3)
    mines.observe_native(memory, s, 4.7)
    assert st['mines_placed'] == st['native_mines_placed'] == 1
    assert st['mine_attempts'] == 2 and st['automine_credit_restorations'] == 1
    assert len(ctl.units) == 5  # reuse one proved inactive actor; no second five-mine ring
    assert mines.cadence.distance == 0 and mines.native.job is None
