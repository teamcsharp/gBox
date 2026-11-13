"""Actual run displacement earns one native bomb; old bombs retain priority."""
import struct
import types

import pytest

from gbox.mercs import re6_remote_control as C, re6_bomb_deadlines as D
from gbox.mercs.titles import re6_switch as R, re6_switch_native as N
from tests.test_re6_bomb_drop import drop_controller, native  # noqa: F401

TITLE, OWNER = '01002A000CD48000', ('round-1', 0x200000000, 7)


def stats(**kw):
    return dict(round_evidence_id=OWNER[0], screen='playing', **kw)


def snap(x=0., *, units=(), **player):
    p = dict(ptr=OWNER[1], generation=OWNER[2], pos=[x, 0., 0.], hp=900,
             state=0, equipped=0, action='cPlAction_pl_act_walk')
    p.update(player)
    return dict(player=p, enemies=[], throwables=list(units) if units is not None else None)


def bomb(unit=10, x=0., action=D.SETTING):
    return dict(unit=unit, generation=1, kind='remote', pos=[x, 0., 0.], action=action)


def placed(unit=10, x=609.6, at=100.75):
    return dict(unit=unit, generation=1, pos=[x, 0., 0.], armed=True, verified=True,
                placed_at=at, detonate_deadline_at=at + 5.)


class Flight:
    """Deterministic boundary between input ticks and the native worker."""
    def __init__(self):
        self.busy, self.result, self.cancelled = False, None, False
        self.requests = []

    def submit(self, owner, operation, metadata=None):
        assert not self.busy
        self.owner, self.operation, self.busy = owner, operation, True
        self.requests.append(metadata)
        return True

    def finish(self, receipt=None):
        self.result = receipt if receipt is not None else self.operation(lambda: self.cancelled)

    def poll(self, owner):
        if not self.busy or self.result is None:
            return None
        out, self.result, self.busy = self.result, None, False
        return out if owner == self.owner else None

    def close(self):
        self.cancelled = True


@pytest.fixture(autouse=True)
def clean_placement_records():
    D._PLACED.clear()
    yield
    D._PLACED.clear()


@pytest.fixture
def lane(monkeypatch):
    flight = Flight()
    monkeypatch.setattr(C, 'RingFlight', lambda: flight)
    step = C.control(object(), {'map_id': TITLE})
    return step, stats(), flight


def travel(step, st, start=100., base=0., **player):
    out = None
    for i, x in enumerate((0., 200., 400., 609.6)):
        out = step(snap(base + x, **player), st, start + .25 * i,
                   lambda _: pytest.fail('native drop must not release movement'))
    return out


def test_twenty_feet_of_measured_run_drops_one_bomb_and_waits_for_escape(lane, monkeypatch):
    step, st, flight = lane
    calls = []
    monkeypatch.setattr(C, 'single_drop_now', lambda *a, **k: calls.append(a[1]) or
                        dict(op='bomb_trail', state='confirmed', placed=1, units=[placed()]))
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: calls.append('flag') or
                        dict(verified=True, count=1, detonated=[10], triggered_at=104.))
    out = travel(step, st)
    assert out['op'] == 'bomb_trail' and out['pending'] and not calls
    assert flight.requests == [dict(count=1, radius_cm=0., reason='travel', travel_cm=609.6,
                                   player_pos=[609.6, 0., 0.], session=None)]
    flight.finish()
    step.observe(snap(609.6), st, 100.8)  # pre-allocation census still empty
    assert calls == [OWNER] and st['mine_trail_drops'] == 1
    assert st['mine_escape_required'] and st['mine_deadline_at'] == 105.75
    assert st['mine_timing_source'] == 'native_placed_armed'
    step(snap(800., units=[bomb(x=609.6)]), st, 101.)
    assert len(flight.requests) == 1 and calls == [OWNER]
    step(snap(1800., units=[bomb(x=609.6)]), st, 104.)
    assert calls == [OWNER, 'flag'] and st['mine_flag_detonations'] == 1
    assert st['mine_deadline_pending'] == 1  # flag is not an observed blast
    step.observe(snap(1800., units=[bomb(x=609.6, action=D.BLAST)]), st, 104.1)
    assert st['mine_blasts_observed'] == 1 and not st['mine_deadline_pending']


def test_wall_input_or_waiting_minutes_does_not_earn_bombs(lane):
    step, st, flight = lane
    for i in range(1200):
        step(snap(), st, 100. + i * .1)
    assert not flight.requests and st['mine_travel_cm'] == 0.


@pytest.mark.parametrize('override', [dict(hp=0), dict(state=8), dict(equipped=12),
                                     dict(action='cPlAction_pl_act_damage')])
def test_non_running_character_actions_cannot_earn_travel_drops(lane, override):
    step, st, flight = lane
    travel(step, st, **override)
    assert not flight.requests and st['mine_travel_cm'] == 0.


def test_warps_operator_input_and_unknown_position_reset_travel(lane):
    step, st, flight = lane
    step(snap(), st, 100.)
    step(snap(400.), st, 100.4)
    step(snap(20000.), st, 100.5)
    assert st['mine_travel_cm'] == 0.
    st['operator_control'] = True
    travel(step, st, 101., 20000.)
    assert not flight.requests
    st['operator_control'] = False
    step(snap(pos=None), st, 102.)
    step(snap(50000.), st, 102.1)
    assert st['mine_travel_cm'] == 0. and not flight.requests


def test_engine_duplicate_observation_does_not_erase_real_run_motion(lane):
    step, st, flight = lane
    for i, x in enumerate((0., 200., 400., 609.6)):
        s, now = snap(x), 100. + i * .25
        step.observe(s, st, now)
        step(s, st, now)
    assert len(flight.requests) == 1 and flight.requests[0]['count'] == 1


def test_nearby_old_bombs_block_both_travel_and_emergency_production(lane, monkeypatch):
    step, st, flight = lane
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: dict(verified=False, reason='unsafe old bomb'))
    for i in range(11):
        s = snap(i * 100., units=[bomb(x=500.)])
        s['enemies'] = [dict(hp=100, pos=[i * 100., 0., 10.])] * 4
        step(s, st, 100. + .2 * i)
    assert not flight.requests and st['mine_deadline_pending'] == 1
    assert st['mine_escape_required'] and st['mine_clearance_cm'] == 500.


def test_a_released_qte_ring_may_be_laid_while_an_old_bomb_is_out(lane, monkeypatch):
    # The operator wants the area mined after every survived QTE, even when an earlier set is still lying. The QTE
    # ring is admitted up to QTE_RING_MAX_OUTSTANDING outstanding bombs; the flag gate still refuses detonation below
    # the rule's clearance.
    from gbox.mercs import remote_mines as RULES
    step, st, flight = lane
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: dict(verified=False, reason='old bomb pending'))
    st['mine_deadline_pending'] = 1
    step(snap(100., units=[bomb(x=0.)]), st, 100., lambda _: None)
    assert not flight.requests                      # ordinary production still waits for the old bomb
    st['qte_escape_mines_due'] = 'episode-1'
    out = step(snap(100., units=[bomb(x=0.)]), st, 100.5, lambda _: None)
    assert flight.requests and flight.requests[0]['reason'] == 'qte_escape'
    assert flight.requests[0]['count'] == RULES.FLASH_COMBO_MINES
    assert st['mine_qte_rings'] == 1 and 'qte_escape_mines_due' not in st

@pytest.mark.parametrize('flash', [False, True])
def test_unavailable_crowd_ring_cannot_starve_earned_travel_drop(lane, monkeypatch, flash):
    step, st, flight = lane
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: dict(verified=False, reason='old bomb pending'))
    for i, x in enumerate((0., 200., 400., 609.6)):
        s = snap(x, units=[bomb(x=-100.)])
        s['enemies'] = [dict(hp=100, pos=[x, 0., 10.])] * 4
        if flash:
            st['ring_flash_at'] = 100. + .25 * i
        out = step(s, st, 100. + .25 * i)
    assert out['op'] == 'bomb_trail' and out['pending']
    assert flight.requests[0]['count'] == 1
    assert flight.requests[0]['reason'] == 'travel'
    assert st['mine_trail_chained'] == 1
    assert not st.get('mine_surround_rings') and not st.get('mine_flash_combos')
    assert not st.get('mine_flash_combo_at')


@pytest.mark.parametrize('phase,allowed', [('wait', True), ('equip', False), ('throw', False), ('mind', False)])
def test_driver_passive_bomb_wait_does_not_block_new_native_ring(monkeypatch, phase, allowed):
    flight = Flight()
    monkeypatch.setattr(C, 'RingFlight', lambda: flight)
    driver = types.SimpleNamespace(bomb_phase=phase, nade=None)
    step = C.control(object(), {'map_id': TITLE}, lambda: driver)
    st, s = stats(ring_flash_at=100.), snap()
    s['enemies'] = [dict(hp=100, pos=[0., 0., 10.])] * 4
    out = step(s, st, 100.)
    assert bool(flight.requests) is allowed
    if allowed:
        assert out['op'] == 'bomb_ring' and flight.requests[0]['count'] == 15


def test_driver_wait_can_chain_but_unknown_census_still_blocks(monkeypatch):
    flight = Flight()
    monkeypatch.setattr(C, 'RingFlight', lambda: flight)
    driver = types.SimpleNamespace(bomb_phase='wait', nade=None)
    step = C.control(object(), {'map_id': TITLE}, lambda: driver)
    st = stats()
    for i, x in enumerate((0., 200., 400., 609.6)):
        step(snap(x, units=None), st, 100. + .25 * i)
    assert not flight.requests
    out = step(snap(620., units=[bomb(x=0.)]), st, 100.8)
    assert out['op'] == 'bomb_trail' and st['mine_trail_chained'] == 1


def test_chained_pair_must_clear_before_another_drop_then_crowd_ring_resumes(lane, monkeypatch):
    step, st, flight = lane
    calls = []
    monkeypatch.setattr(N, 'bomb_detonate_now', lambda *a, **k: calls.append(1) or
                        dict(verified=True, count=2, detonated=[10, 20], triggered_at=103.))
    # Two bombs spaced one travel interval apart. Continual travel must not
    # keep creating a new nearest bomb and prevent ever reaching blast range.
    pair = [bomb(10, -610.), bomb(20, 0.)]
    for i, x in enumerate((0., 200., 400., 609.6, 900.)):
        step(snap(x, units=pair), st, 100. + .25 * i)
    assert not flight.requests and not calls
    out = step(snap(1300., units=pair), st, 103.)
    assert out['fired'] and calls == [1]
    blasting = [dict(u, action=D.BLAST) for u in pair]
    step.observe(snap(1300., units=blasting), st, 103.1)
    assert st['mine_blasts_observed'] == 2 and not st['mine_deadline_pending']
    s = snap(1300.)
    s['enemies'] = [dict(hp=100, pos=[1300., 0., 10.])] * 4
    out = step(s, st, 103.2)
    assert out['op'] == 'bomb_ring' and flight.requests[0]['count'] == 15


def test_a_bomb_left_behind_lets_the_next_twenty_feet_chain_while_it_lies(lane, monkeypatch):
    """The operator's automine asks for a bomb every 20 ft of measured travel.

    Before this, one armed bomb starved the lane (a 4-minute live No Mercy round on 2026-11-13 produced a single
    bomb): the bot fought and never covered the rule's 1100 cm escape distance in one run. A bomb already behind
    him is escaped, so the next 20 ft travel drop chains while it lies there. Safety is unchanged: detonation
    reads every actual bomb, and a bomb nearer than TRAIL_CHAIN_CM still blocks all production, as do the
    emergency rings (they wait for the old set).
    """
    step, st, flight = lane
    calls = []
    monkeypatch.setattr(C, 'single_drop_now', lambda *a, **k: calls.append(k) or
                        dict(op='bomb_trail', state='confirmed', placed=1, units=[placed()]))
    # The bomb lies far behind him; no enemies (no emergency, no landing).
    for i, x in enumerate((0., 200., 400., 609.6)):
        step(snap(x, units=[bomb(x=-1200.)]), st, 100. + .25 * i, lambda _: None)
    assert st['mine_deadline_pending'] == 1
    assert len(flight.requests) == 1 and flight.requests[0]['reason'] == 'travel'
    flight.finish()                                   # the worker runs the native drop outside the input tick
    assert calls and calls[0].get('allow_existing') is True
    assert st['mine_trail_chained'] == 1
    # An emergency ring still waits for the bomb out, even with it far behind.
    sent = len(flight.requests)
    st['ring_flash_at'] = 102.
    step(snap(700., units=[bomb(x=-1200.)]), st, 102.1, lambda _: None)
    assert len(flight.requests) == sent


def test_late_receipt_and_unknown_census_keep_new_and_old_hazards(lane):
    step, st, flight = lane
    travel(step, st)
    step.observe(snap(609.6, units=[bomb(20, 300.)]), st, 100.8)
    flight.finish(dict(op='bomb_trail', state='confirmed', placed=1, units=[placed()]))
    step.observe(snap(609.6, units=None), st, 100.9)
    assert st['mine_deadline_pending'] == 2
    assert sorted(st['mine_avoid_positions']) == [[300., 0., 0.], [609.6, 0., 0.]]
    assert st['mine_deadline_at'] == 105.75
    step.observe(snap(609.6, units=None), st, 106.)
    assert st['mine_deadline_misses'] == 2 and len(flight.requests) == 1


def test_pre_placement_action_cannot_erase_a_confirmed_placement(lane):
    step, st, flight = lane
    travel(step, st)
    flight.finish(dict(op='bomb_trail', state='confirmed', placed=1, units=[placed()]))
    step.observe(snap(609.6, units=[bomb(x=609.6, action='cWpAction_wp_act_throw')]), st, 100.8)
    assert st['mine_deadline_at'] == 105.75 and st['mine_deadline_pending'] == 1
    step.observe(snap(609.6), st, 100.9)
    assert st['mine_deadline_at'] == 105.75 and st['mine_escape_required']


def test_first_census_already_blasting_retains_native_placement_timing(lane):
    step, st, flight = lane
    travel(step, st)
    flight.finish(dict(op='bomb_trail', state='confirmed', placed=1, units=[placed()]))
    step.observe(snap(609.6, units=[bomb(x=609.6, action=D.BLAST)]), st, 101.)
    assert st['mine_blasts_observed'] == 1 and not st['mine_deadline_pending']
    assert st['mine_deadline_last']['blast_confirmed']
    assert st['mine_deadline_last']['placed_at'] == 100.75


def test_uncertain_allocation_is_not_replayed_until_new_player_life(lane):
    step, st, flight = lane
    travel(step, st)
    flight.finish(dict(op='bomb_trail', state='uncertain', placed=0, reason='native completion unknown'))
    step.observe(snap(609.6), st, 100.8)
    travel(step, st, 104., 609.6)
    assert len(flight.requests) == 1 and 'uncertain' in st['mine_allocation_blocked_reason']
    travel(step, st, 110., 0., generation=8)
    assert len(flight.requests) == 2 and 'mine_allocation_blocked_reason' not in st


def test_worker_refuses_if_player_stopped_before_controller_became_available(lane, monkeypatch):
    step, st, flight = lane
    seen = []
    monkeypatch.setattr(C, 'single_drop_now', lambda ad, owner, cancelled, **k:
                        seen.append(cancelled()) or dict(state='unavailable', placed=0))
    travel(step, st)
    step.observe(snap(609.6), st, 101.1)
    flight.finish()
    assert seen == [True]


def test_disabling_policy_cancels_queued_emergency_ring(lane, monkeypatch):
    step, st, flight = lane
    seen = []
    monkeypatch.setattr(C, 'emergency_ring_now', lambda ad, owner, cancelled, count, radius, **k:
                        seen.append(cancelled()) or dict(state='unavailable', placed=0))
    st['ring_flash_at'] = 100.
    step(snap(), st, 100.)
    assert flight.busy
    st['remote_mines'] = {'enabled': False}
    step.observe(snap(), st, 100.1)
    flight.finish()
    assert seen == [True]


def controller(native, monkeypatch):
    ctl = drop_controller(position=(700., 30., -20.))
    ctl.recover_completed_call = lambda: True
    monkeypatch.setattr(N.R, 'owned_throwables', lambda *a: [])
    monkeypatch.setattr(N.R, 'inventory_guns', lambda *a: {0x107: 0})
    return ctl, types.SimpleNamespace(_re6_native_flash=ctl)


def test_native_travel_drop_uses_live_feet_without_equipment_or_health_writes(native, monkeypatch):
    ctl, ad = controller(native, monkeypatch)
    before = ctl.rd(ctl.player + R.P_HP, 2), ctl.rd(ctl.player + R.P_EQUIPPED, 4)
    out = C.single_drop_now(ad, OWNER, lambda: False)
    assert out['state'] == 'confirmed' and out['verified'] and out['placed'] == 1
    assert out['weapon_before'] == out['weapon_after'] == 7 and out['weapon_unchanged']
    assert out['units'][0]['armed'] and out['units'][0]['pos'] == [700., 30., -20.]
    (code, args), = ctl.calls
    assert code == N.SPAWN_BOMB[0] and args[0] == ctl.player
    assert [struct.unpack('<f', struct.pack('<I', v))[0] for v in args[1:]] == [700., 30., -20.]
    assert before == (ctl.rd(ctl.player + R.P_HP, 2), ctl.rd(ctl.player + R.P_EQUIPPED, 4))


@pytest.mark.parametrize('reason', ['cancelled', 'changed_owner', 'no_gun'])
def test_native_preflight_refuses_stale_owner_or_absent_gun(native, monkeypatch, reason):
    ctl, ad = controller(native, monkeypatch)
    if reason == 'no_gun':
        ctl.current_weapon = lambda: None
    owner = (*OWNER[:2], 8) if reason == 'changed_owner' else OWNER
    out = C.single_drop_now(ad, owner, lambda: reason == 'cancelled')
    assert out['state'] == 'unavailable' and not ctl.calls and not out['placed']


def test_native_census_and_allocation_share_the_controller_lock(native, monkeypatch):
    ctl, ad = controller(native, monkeypatch)
    actual_drop = ctl.drop_bomb
    def census(*args):
        assert ctl.lock._is_owned()
        return []
    def drop(**kw):
        assert ctl.lock._is_owned()
        return actual_drop(**kw)
    monkeypatch.setattr(N.R, 'owned_throwables', census)
    ctl.drop_bomb = drop
    assert C.single_drop_now(ad, OWNER, lambda: False)['verified']


@pytest.mark.parametrize('units', [None, [bomb(action='cWpAction_wp_act_throw')], [bomb()]])
def test_live_census_refuses_new_single_and_emergency_bombs(native, monkeypatch, units):
    ctl, ad = controller(native, monkeypatch)
    monkeypatch.setattr(N.R, 'owned_throwables', lambda *a: units)
    monkeypatch.setattr(N, 'bomb_ring_now', lambda *a, **k: pytest.fail('old live bomb forbids a new ring'))
    for out in (C.single_drop_now(ad, OWNER, lambda: False),
                C.emergency_ring_now(ad, OWNER, lambda: False, 15, 200.)):
        assert out['state'] == 'unavailable' and not out['placed']
    assert not ctl.calls


def test_unarmed_native_allocation_is_uncertain_and_never_claimed_placed(native, monkeypatch):
    ctl, ad = controller(native, monkeypatch)
    ctl.drop_bomb = lambda **k: {**placed(), 'armed': False}
    out = C.single_drop_now(ad, OWNER, lambda: False)
    assert out['state'] == 'uncertain' and not out['placed'] and not out['verified']


def test_equipment_change_after_confirmed_drop_keeps_bomb_for_escape(native, monkeypatch):
    ctl, ad = controller(native, monkeypatch)
    weapons = iter((7, 8))
    ctl.current_weapon = lambda: next(weapons)
    out = C.single_drop_now(ad, OWNER, lambda: False)
    assert out['state'] == 'uncertain' and out['placed'] == 1 and not out['weapon_unchanged']
    assert out['units'][0]['armed'] and not out['verified']
