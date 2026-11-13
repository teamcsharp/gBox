"""Confirmed-flash demands use the existing native mine worker and escape gate."""
import pytest

from gbox.mercs.titles import re5_native_mine_tactic as N, re5_proximity_native as P, re5_switch_mines as M
from test_re5_native_mine_tactic import scene, stats, memory, receipt


@pytest.fixture(autouse=True)
def backend(monkeypatch, tmp_path):
    monkeypatch.setattr(P, 'LIVE_VERIFIED', True)
    monkeypatch.setattr(N, 'ROOT', tmp_path)


def request(s, st, *, count=1, at=120.):
    st['crowd_roulette_mine_event'] = {'id': 'flash-one', 'kind': 'roulette_flash',
        'owner': list(N.identity(s, st)), 'count': count, 'pos': list(s['player']['pos']), 'at': at}


def test_one_owned_flash_demand_is_consumed_once_and_yields_to_hit():
    s, st, cadence = scene(), stats(), N.Cadence()
    cadence.observe(s, st, 120.)
    request(s, st)
    assert cadence.demand(s, st, 120.) == ('roulette_flash', 'flash-one')
    st['automine_event'] = {'id': 'hit', 'kind': 'hit', 'owner': list(N.identity(s, st)), 'at': 120.}
    assert cadence.demand(s, st, 120.) == ('hit', 'hit')
    st.pop('automine_event')
    cadence.claimed(('roulette_flash', 'flash-one'), 120.)
    assert cadence.demand(s, st, 124.) is None


@pytest.mark.parametrize('change', ['owner', 'stale', 'future', 'kind', 'count', 'position'])
def test_bad_flash_demand_is_not_admitted(change):
    s, st, cadence = scene(), stats(), N.Cadence()
    cadence.observe(s, st, 120.)
    request(s, st)
    e = st['crowd_roulette_mine_event']
    if change == 'owner': e['owner'][2] += 1
    if change == 'stale': e['at'] = 110.
    if change == 'future': e['at'] = 121.
    if change == 'kind': e['kind'] = 'attempted_flash'
    if change == 'count': e['count'] = 99
    if change == 'position': e['pos'] = [0., float('nan'), 0.]
    assert cadence.demand(s, st, 120.) is None


def test_disabling_automine_consumes_the_old_event_instead_of_replaying_after_enable():
    s, st, cadence = scene(), stats(), N.Cadence()
    request(s, st)
    cadence.observe(s, st, 120., enabled=False)
    cadence.observe(s, st, 121., enabled=True)
    assert cadence.demand(s, st, 121.) is None


@pytest.mark.parametrize('count', [1, 5])
def test_flash_followup_places_only_after_native_receipt_and_preserves_weapon(count):
    s, st, mem, calls = scene(), stats(), memory(), []
    mines = M.Mines(st)
    mines.new_round(0.)
    mines.observe_native(mem, s, 120.)
    def run(memory, expected, allowed, **kw):
        assert allowed()
        calls.append((expected, kw['count'], kw['center']))
        return receipt(count=count)
    mines.native = N.Flight(mem, run=run)
    mines.native.observe(s, st)
    request(s, st, count=count)
    mines._request_native(s, 120.)
    job = mines.native.job
    assert job is not None and st['crowd_roulette_mine_status'] == 'submitted'
    assert st['mines_placed'] == 0
    if count == 5:
        assert mines._native_escape is not None  # guarded route starts for predicted hazards immediately
    assert job['done'].wait(3)
    mines.observe_native(mem, s, 120.2)
    assert calls == [((s['player']['ptr'], 1), count, tuple(s['player']['pos']))]
    assert st['mines_placed'] == count and st['crowd_roulette_mine_status'] == 'executed'
    assert st['crowd_roulette_mine_receipt']['weapon_unchanged'] is True
    mines._request_native(s, 124.)
    assert len(calls) == 1


@pytest.mark.parametrize('block', ['escape', 'flash_pending', 'automine_disabled', 'uncertain_owner'])
def test_existing_mine_gates_cannot_be_bypassed_by_roulette(block):
    s, st, mem, calls = scene(), stats(), memory(), []
    mines = M.Mines(st)
    mines.new_round(0.)
    mines.observe_native(mem, s, 120.)
    mines.native = N.Flight(mem, run=lambda *a, **kw: calls.append(1) or receipt())
    mines.native.observe(s, st)
    request(s, st, count=5)
    if block == 'escape': mines._native_escape = {'id': 'older-mines'}
    if block == 'flash_pending': st['ring_async_pending'] = True
    if block == 'automine_disabled': mines.automine = False
    if block == 'uncertain_owner': mines.native.blocked_owner = N.identity(s, st)
    mines._request_native(s, 120.)
    assert mines.native.job is None and not calls and not st['mines_placed']


def test_native_worker_independently_rechecks_flash_event_identity_and_age():
    s, st, mem = scene(), stats(), memory()
    request(s, st)
    flight = N.Flight(mem, run=lambda *a, **kw: pytest.fail('must not publish native allocation'))
    st['crowd_roulette_mine_event']['owner'][2] += 1
    assert not flight.submit(s, st, 120., reason='roulette_flash', center=s['player']['pos'])
    request(s, st, at=110.)
    assert not flight.submit(s, st, 120., reason='roulette_flash', center=s['player']['pos'])
    assert flight.job is None
