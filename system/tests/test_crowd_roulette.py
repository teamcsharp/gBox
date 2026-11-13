"""Periodic crowd variety preserves native proof, emergency priority and lifetime."""
import threading

import pytest

from gbox.mercs import crowd_roulette as C, grenade_ring as G, async_flash_ring as A


class Native:
    SCATTER_KINDS = ('flash', 'hand')
    def __init__(self, kinds=('flash', 'hand'), *, background=False):
        self.kinds, self.calls = kinds, []
        self.async_flash_ring = background

    def grenade_kinds(self):
        return [{'kind': k, 'available': True} for k in self.kinds]+[
            {'kind': 'shell1304', 'available': False}, {'kind': 'mine', 'available': False}]

    launcher_kinds = grenade_kinds

    def grenade_ring(self, kind, **kw):
        self.calls.append(('ring', kind, kw))
        return {'state': 'confirmed', 'kind': kind, 'verified': True,
                'requested': kw.get('count', 10), 'detonated': kw.get('count', 10)}

    def grenade_scatter(self, kind, **kw):
        self.calls.append(('scatter', kind, kw))
        return {'state': 'confirmed', 'kinds': list(kw['kinds']), 'verified': True,
                'requested': kw.get('count', 8), 'detonated': kw.get('count', 8)}


def scene(scale=1.):
    return {'player': {'ptr': 101, 'generation': 7, 'pos': (0., 0., 0.), 'hp': 1000},
            'enemies': [{'ptr': i, 'hp': 500, 'pos': (i*100.*scale, 0., 800.*scale)} for i in (1, 2)],
            'game': {'phase': 'playing', 'in_control': True}, 'throwables': []}


def stats():
    return {'round_evidence_id': 'round-a', 'screen': 'playing', 'kills': 0}


def setup(title=C.RE6):
    s, st, ctl = scene(), stats(), Native()
    q = C.Roulette(title)
    q.observe(s, st, 0.)
    return q, s, st, ctl


def choose(q, s, st, ctl, now=120., **kw):
    policy = kw.pop('policy', G.policy(stats=st))
    normal = kw.pop('normal', G.decide(s, st, now, policy))
    return q.decide(s, st, now, normal, policy, G.scatter_policy(stats=st), lambda: ctl, **kw)


def test_independent_due_clock_survives_routine_rings_without_another_shared_cooldown():
    q, s, st, ctl = setup()
    for t in range(10, 120, 10):
        q.observe(s, st, t)
        st['ring_last_at'] = t
        assert choose(q, s, st, ctl, t) is None
    # The last ordinary ring was only 10s ago, inside its 20/90s
    # cooldown. The independent 120s volley is now due.
    assert q.next_at == 120.
    assert choose(q, s, st, ctl)['roulette']


def test_extra_volley_keeps_short_physical_separation_from_any_ring():
    q, s, st, ctl = setup()
    st['ring_last_at'] = 119.
    assert choose(q, s, st, ctl)['roulette_wait']
    assert q.next_at == 120.
    assert choose(q, s, st, ctl, 125.)['roulette']


def test_only_verified_ring_and_separately_verified_scatter_kinds_are_drawn():
    ctl = Native(('flash', 'hand', 'shell1302'))
    assert set(C.capabilities(ctl)) == {('ring', 'flash'), ('ring', 'hand'), ('ring', 'shell1302'),
                                        ('scatter', 'flash'), ('scatter', 'hand')}
    assert set(C.capabilities(ctl, background=True)) == {('ring', 'flash'), ('scatter', 'flash')}


def test_random_choice_does_not_repeat_previous_tactic_when_another_is_available():
    q, s, st, ctl = setup()
    q.previous = ('ring', 'flash')
    choices = []
    class First:
        def choice(self, options):
            choices.append(options)
            return options[0]
    q.rng = First()
    result = choose(q, s, st, ctl)
    assert ('ring', 'flash') not in choices[0]
    assert result['roulette']['kind'] in ('hand', 'flash')


@pytest.mark.parametrize('flag', ['reactive', 'traversal', 'defend', 'dangerous'])
def test_emergency_defense_is_not_replaced_or_counted_as_periodic(flag):
    q, s, st, ctl = setup()
    normal = G.decide(s, st, 120.) | {flag: True, 'fire': True}
    assert choose(q, s, st, ctl, normal=normal) is None
    assert q.next_at == 120. and q.pending is None


def test_dangerous_enemy_inside_shared_cooldown_does_not_block_due_volley():
    q, s, st, ctl = setup()
    st['ring_last_at'] = 110.
    normal = G.decide(s, st, 120.) | {'dangerous': 1, 'fire': False}
    assert choose(q, s, st, ctl, normal=normal)['roulette']


@pytest.mark.parametrize('key', ['native_mine_pending', 'ring_async_pending', 'mine_ring_pending',
    'mine_deadline_pending', 'mine_escape_required', 'native_mine_escape_required'])
def test_pending_native_action_and_bomb_escape_block_roulette_without_queueing(key):
    q, s, st, ctl = setup()
    st[key] = True
    assert choose(q, s, st, ctl)['roulette_wait']
    assert q.pending is None and not ctl.calls


def test_existing_remote_actor_blocks_new_periodic_work_even_before_deadline_census():
    q, s, st, ctl = setup()
    s['throwables'] = [{'kind': 'remote', 'action': 'moving'}]
    assert choose(q, s, st, ctl)['roulette_wait']
    assert q.pending is None


def test_flash_cooldown_reserves_periodic_slot_so_routine_flashes_cannot_starve_it(monkeypatch):
    q, s, st, ctl = setup()
    ctl.kinds = ('flash',)
    st['native_flash_confirmed_at'] = 119.
    policy = G.policy() | {'flash_gap_s': 60.}
    monkeypatch.setattr(G.time, 'time', lambda: 120.)
    assert choose(q, s, st, ctl, policy=policy)['roulette_wait']
    assert q.next_at == 120.
    monkeypatch.setattr(G.time, 'time', lambda: 180.)
    assert choose(q, s, st, ctl, 180., policy=policy)['roulette']['kind'] == 'flash'


def test_no_crowd_on_same_floor_keeps_periodic_due_without_firing():
    q, s, st, ctl = setup()
    s['enemies'][1]['pos'] = (200., 1000., 800.)
    assert choose(q, s, st, ctl) is None
    assert 'player floor' in st['crowd_roulette_wait']


def test_round_and_player_lifetime_change_retire_pending_receipt():
    q, s, st, ctl = setup()
    decision = choose(q, s, st, ctl)
    s['player']['generation'] = 8
    q.observe(s, st, 121.)
    q.finish(s, st, 122., decision, {'state': 'confirmed', 'kind': 'flash', 'detonated': 10})
    assert st['crowd_roulette_last']['state'] == 'retired'
    assert q.next_at == 241. and not st.get('crowd_roulette_executed')
    assert 'ring_flash_at' not in st


@pytest.mark.parametrize('receipt', [
    {'state': 'confirmed', 'kind': 'flash', 'detonated': 0},
    {'state': 'confirmed', 'kind': 'hand', 'detonated': 10},
    {'state': 'uncertain', 'kind': 'flash', 'detonated': 2},
    {'state': 'refused', 'kind': 'flash', 'reason': 'native actor unavailable'}])
def test_spawn_partial_mismatched_or_refused_receipt_never_reports_execution_or_mines(receipt):
    q, s, st, ctl = setup()
    ctl.kinds = ('flash',)
    ctl.SCATTER_KINDS = ()
    q.rng = type('First', (), {'choice': lambda self, options: options[0]})()
    decision = choose(q, s, st, ctl)
    q.finish(s, st, 121., decision, receipt)
    assert not st.get('crowd_roulette_executed')
    assert 'ring_flash_at' not in st and 'crowd_roulette_mine_event' not in st
    assert q.pending is None and q.next_at == 241.


def reactive(q, s, st, ctl, now=120., **overrides):
    policy, scatter = G.policy(), G.scatter_policy()
    d = G.decide(s, st, now, policy) | {'fire': True, 'kind': 'flash', 'reactive': True,
        'reactive_event': {'id': 42, 'owner': list(q.owner), 'kind': 'hit'}, **overrides}
    return q.coalesce(s, st, now, d, policy, scatter, lambda: ctl)


def test_due_reactive_flash_is_one_explicit_coalesced_volley_without_duplicate_mines():
    q, s, st, ctl = setup(C.RE5)
    st.update(ring_last_at=119., native_flash_confirmed_at=119.)
    decision = reactive(q, s, st, ctl)
    assert decision['roulette']['coalesced'] == 'reactive_flash'
    assert decision['roulette']['source_event']['id'] == 42
    assert 'followup_mines' not in decision['roulette']
    q.finish(s, st, 121., decision, {'state': 'confirmed', 'verified': True, 'kind': 'flash',
                                  'requested': 10, 'detonated': 10})
    assert st['crowd_roulette_executed'] == st['crowd_roulette_coalesced'] == 1
    assert 'crowd_roulette_mine_event' not in st and 'ring_flash_at' not in st
    assert not ctl.calls                            # accounting never creates a native operation


@pytest.mark.parametrize('change', ['small', 'hand', 'wrong_owner', 'dead', 'operator', 'no_crowd',
    'high_floor', 'native_pending', 'escape', 'unverified_kind', 'bad_radius', 'foreign_event'])
def test_coalescing_never_weakens_ownership_full_volley_crowd_or_clearance(change):
    q, s, st, ctl = setup()
    opts = {}
    if change == 'small': opts['count'] = 1
    if change == 'hand': opts['kind'] = 'hand'
    if change == 'wrong_owner': s['player']['generation'] += 1
    if change == 'dead': s['player']['hp'] = 0
    if change == 'operator': st['operator_control'] = True
    if change == 'no_crowd': s['enemies'] = s['enemies'][:1]
    if change == 'high_floor': s['enemies'][1]['pos'] = (200., 1000., 800.)
    if change == 'native_pending': st['native_mine_pending'] = True
    if change == 'escape': st['native_mine_escape_required'] = True
    if change == 'unverified_kind': ctl.kinds = ('hand',)
    if change == 'bad_radius': opts['radius_cm'] = 3000.
    if change == 'foreign_event': opts['reactive_event'] = {'owner': ['old', 101, 7], 'id': 1}
    assert 'roulette' not in reactive(q, s, st, ctl, **opts)
    assert q.pending is None and not ctl.calls


@pytest.mark.parametrize('receipt', [
    {'state': 'refused', 'verified': False, 'detonated': 0},
    {'state': 'uncertain', 'verified': False, 'detonated': 3},
    {'state': 'confirmed', 'verified': True, 'detonated': 3},
    {'state': 'confirmed', 'verified': False, 'detonated': 10},
    {'state': 'confirmed', 'verified': True, 'detonated': 10, 'requested': 8},
])
def test_coalesced_emergency_requires_full_verified_matching_receipt(receipt):
    q, s, st, ctl = setup(C.RE5)
    decision = reactive(q, s, st, ctl)
    q.finish(s, st, 121., decision, {'kind': 'flash', **receipt})
    assert not st.get('crowd_roulette_executed') and not st.get('crowd_roulette_coalesced')
    assert 'crowd_roulette_mine_event' not in st


def test_known_unsubmitted_refusal_retries_bounded_without_replaying_uncertainty():
    q, s, st, ctl = setup()
    decision = reactive(q, s, st, ctl)
    q.finish(s, st, 121., decision, {'state': 'failed', 'native_not_submitted': True})
    assert q.next_at == 131. and not st.get('crowd_roulette_executed')
    assert 'roulette' not in reactive(q, s, st, ctl, 130.)
    decision = reactive(q, s, st, ctl, 131.)
    q.finish(s, st, 132., decision, {'state': 'uncertain', 'native_not_submitted': True})
    assert q.next_at == 252.


def test_repeated_re5_emergencies_complete_due_accounting_with_no_additional_native_calls(tmp_path, monkeypatch):
    from gbox.mercs.titles import re5_switch as R
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    ctl, st, s = Native(('flash',), background=True), stats(), scene()
    s['mercenaries_phase'] = R.PHASE_PLAYING
    s['player']['motion'] = 0
    st['ring'] = {'cooldown_s': 90.}
    step = G.control(None, {'map_id': C.RE5, 'menus': 'gbox.mercs.titles.re5_switch'}, ring=ctl)
    try:
        assert step.react(s, st, 0.) is None
        for now in (10., 60., 110., 120., 130., 240., 241.):
            s['player']['hp'] -= 10
            assert step.react(s, st, now)['pending']
            job = step.observe.__self__.job
            assert job['done'].wait(3)
            result = step.react(s, st, now+.1)
            assert result['fired']
            assert len(ctl.calls) == int(st['reactive_ring_requests'])
        # 120.0 fulfils the first opportunity; 240.0 precedes the next
        # receipt-relative deadline, 241.0 fulfils it. Every flash is reactive.
        assert len(ctl.calls) == 7
        assert st['crowd_roulette_executed'] == st['crowd_roulette_coalesced'] == 2
        assert 'crowd_roulette_mine_event' not in st
        assert st['automine_event']['id'] == 7
    finally:
        step.close()


def test_confirmed_re6_flash_publishes_one_remote_followup_stamp():
    q, s, st, ctl = setup()
    ctl.kinds = ('flash',)
    q.rng = type('First', (), {'choice': lambda self, options: options[0]})()
    decision = choose(q, s, st, ctl)
    receipt = {'state': 'confirmed', 'kind': 'flash', 'detonated': 10, 'verified': True}
    q.finish(s, st, 121., decision, receipt)
    q.finish(s, st, 122., decision, receipt)
    assert st['ring_flash_at'] == 121. and st['crowd_roulette_executed'] == 1
    assert not any(k in st for k in ('mine_ring_requests', 'mines_placed'))


def test_control_scatter_uses_exact_chosen_kind_and_restores_re4_units(monkeypatch):
    ctl, st, s = Native(), stats(), scene(scale=10.)
    monkeypatch.setattr(C.random, 'choice', lambda options: ('scatter', 'hand') if ('scatter', 'hand') in options else options[0])
    step = G.control(None, {'map_id': '010099A00BC1E000', 'units_per_cm': 10}, ring=ctl)
    step(s, st, 0.)
    result = step(s, st, 120., lambda keys: True)
    assert result['fired'] and st['crowd_roulette_executed'] == 1
    operation, kind, options = ctl.calls[-1]
    assert operation == 'scatter' and kind == 'random' and options['kinds'] == ('hand',)
    assert options['toward'] == [(1000., 8000.), (2000., 8000.)]


def test_failed_pad_release_finishes_once_without_native_call(monkeypatch):
    ctl, st, s = Native(), stats(), scene()
    monkeypatch.setattr(C.random, 'choice', lambda options: options[0])
    step = G.control(None, {'map_id': C.RE6}, ring=ctl)
    step(s, st, 0.)
    result = step(s, st, 120., lambda keys: False)
    assert not result['fire'] and not ctl.calls
    assert st['crowd_roulette_refused'] == 1
    assert [e['state'] for e in st['crowd_roulette_events']] == ['chosen', 'refused']


def test_re5_async_receipt_logs_completion_only_after_poll_and_creates_owned_mine_demand(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    monkeypatch.setattr(C.random, 'choice', lambda options: options[0])
    gate, entered = threading.Event(), threading.Event()
    ctl, st, s = Native(('flash',), background=True), stats(), scene()
    base = ctl.grenade_ring
    def ring(kind, **kw):
        entered.set()
        assert gate.wait(3)
        return base(kind, **kw)
    ctl.grenade_ring = ring
    step = G.control(None, {'map_id': C.RE5}, ring=ctl)
    try:
        step(s, st, 0.)
        assert step(s, st, 120.)['pending']
        assert entered.wait(3)
        assert not st.get('crowd_roulette_executed') and 'crowd_roulette_mine_event' not in st
        assert step(s, st, 120.1)['pending']
        assert len(st['crowd_roulette_events']) == 2
        gate.set()
        # Access the flight only through the attached observer's owner.
        flight = step.observe.__self__
        assert flight.job['done'].wait(3)
        result = step.react(s, st, 121.)
        assert result['fired'] and st['crowd_roulette_executed'] == 1
        event = st['crowd_roulette_mine_event']
        assert event['owner'] == ['round-a', 101, 7] and event['count'] in (1, 5)
        assert st['crowd_roulette_mine_status'] == 'requested'
        assert not st.get('mines_placed')
    finally:
        gate.set()
        step.close()


def test_cancelled_async_periodic_job_retires_without_mine_demand_or_permanent_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(A, 'ROOT', tmp_path)
    monkeypatch.setattr(C.random, 'choice', lambda options: options[0])
    gate, entered = threading.Event(), threading.Event()
    ctl, st, s = Native(('flash',), background=True), stats(), scene()
    base = ctl.grenade_ring
    def ring(kind, **kw):
        entered.set()
        assert gate.wait(3)
        return base(kind, **kw)
    ctl.grenade_ring = ring
    step = G.control(None, {'map_id': C.RE5}, ring=ctl)
    try:
        step(s, st, 0.)
        assert step(s, st, 120.)['pending'] and entered.wait(3)
        flight = step.observe.__self__
        job = flight.job
        st['operator_control'] = True
        step.observe(s, st)
        gate.set()
        assert job['done'].wait(3)
        assert not step.react(s, st, 121.)['fire']
        assert st['crowd_roulette_last']['state'] == 'retired'
        assert not st.get('crowd_roulette_mine_event')
        st['operator_control'] = False
        step(s, st, 242.)
        assert st['crowd_roulette_chosen'] == 2
        if flight.job is not None:
            assert flight.job['done'].wait(3)
    finally:
        gate.set()
        step.close()
