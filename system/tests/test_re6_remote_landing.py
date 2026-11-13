"""Native traversal exit drops once, on the floor, without changing the gun."""
import struct

import pytest

from gbox.mercs import re6_remote_control as C, re6_traversal as T
from gbox.mercs.titles import re6_switch as R, re6_switch_native as N
from tests.test_re6_remote_travel import (
    OWNER, bomb, controller, lane, native, placed, snap, stats,  # noqa: F401
)

CLIMB, WALK = 'cSmVLadderEventCh_Climb', 'cPlAction_pl_act_walk'


@pytest.fixture
def mesh():
    return R.NavMesh([(-2000., 0., -2000.), (2000., 0., -2000.), (0., 0., 2000.)],
                     [(0, 1, 2)], [[]], 'test_floor')


def sample(mesh, x=0., y=0., action=WALK, **kw):
    s = snap(pos=[x, y, 0.], action=action, **kw)
    s['navmesh'] = mesh
    return s


def climb(step, st, mesh, *, action=CLIMB, start=100., units=()):
    out = []
    for dt, x, y, act in ((0., 0., -300., action), (.5, 0., -100., action),
                           (1., 100., .11, WALK), (1.15, 110., .11, WALK)):
        out.append(step(sample(mesh, x, y, act, units=units), st, start + dt))
    return out


@pytest.mark.parametrize('action', sorted(T.TRAVERSAL_ACTIONS))
def test_traversal_requires_action_exit_displacement_and_two_floor_observations(lane, mesh, action):
    step, st, flight = lane
    out = climb(step, st, mesh, action=action)
    assert not any(v.get('pending') for v in out[:3])
    assert out[-1]['op'] == 'bomb_landing' and out[-1]['pending']
    assert len(flight.requests) == 1
    request = flight.requests[0]
    assert request['count'] == 1 and request['radius_cm'] == 0
    assert request['reason'] == 'traversal_landing'
    assert request['traversal']['entry_action'] == action
    assert request['traversal']['exit_action'] == WALK
    assert request['traversal']['landing_pos'] == [110., .11, 0.]
    assert st['mine_landing_requests'] == 1 and not st['mine_landing_ready']


def test_landing_receipt_keeps_native_five_second_deadline_and_old_bomb_gate(lane, mesh, monkeypatch):
    step, st, flight = lane
    monkeypatch.setattr(C, 'landing_drop_now', lambda *a: dict(op='bomb_landing', state='confirmed',
                        placed=1, units=[placed(x=110., at=101.2)]))
    climb(step, st, mesh)
    flight.finish()
    step.observe(sample(mesh, 120.), st, 101.25)
    assert st['mine_landing_drops'] == 1 and st['mine_deadline_at'] == 106.2
    assert st['mine_escape_required'] and st['mine_deadline_pending'] == 1
    for i in range(5):
        step(sample(mesh, 120. + i * 100., units=[bomb(x=110.)]), st, 101.3 + i * .1)
    assert len(flight.requests) == 1


def test_unchanged_or_midair_exit_never_becomes_a_landing(lane, mesh):
    step, st, flight = lane
    step(sample(mesh, 0., 0., CLIMB), st, 100.)
    step(sample(mesh, 0., 0.), st, 100.2)
    step(sample(mesh, 0., 0.), st, 100.4)
    assert not flight.requests  # no displacement
    step(sample(mesh, 0., -300., CLIMB), st, 101.)
    step(sample(mesh, 100., 100.), st, 101.2)
    step(sample(mesh, 120., 80.), st, 101.4)
    step(sample(mesh, 130., 20.), st, 101.6)  # near floor, still descending
    step(sample(mesh, 140., .11), st, 101.8)
    assert not flight.requests
    step(sample(mesh, 150., .11), st, 102.)
    assert len(flight.requests) == 1


def test_duplicate_stale_snapshot_cannot_supply_second_ground_observation(lane, mesh):
    step, st, flight = lane
    step(sample(mesh, 0., -300., CLIMB), st, 100.)
    s = sample(mesh, 100.)
    step.observe(s, st, 100.5)
    step(s, st, 100.5)
    step(s, st, 100.7)
    assert not flight.requests
    step(sample(mesh, 100.), st, 100.8)
    assert len(flight.requests) == 1


def test_recorded_requiem_ladder_exit_is_detected_at_real_observation_cadence(lane):
    # e05026badc8445c99ca42364d31a9dd9, the recorded native action/feet
    # samples; only the small local floor fixture is synthetic.
    mesh = R.NavMesh([(-5000., 0., 2000.), (-3000., 0., 2000.), (-4000., 0., 4000.)],
                     [(0, 1, 2)], [[]], 'requiem_landing_fixture')
    step, st, flight = lane
    rows = ((1794553156.958, CLIMB, [-3786.01, -261.12, 3058.4]),
            (1794553158.124, CLIMB, [-3784., -107.01, 3055.17]),
            (1794553159.416, WALK, [-3904.95, .11, 2938.59]),
            (1794553160.472, 'cPlAction_pl_act_weapon_ready_end', [-4013.47, .11, 2812.35]))
    for stamp, action, pos in rows:
        s = snap(pos=pos, action=action)
        s['navmesh'] = mesh
        step(s, st, stamp)
    assert len(flight.requests) == 1 and flight.requests[0]['reason'] == 'traversal_landing'


def test_weapon_change_between_climb_and_controllable_exit_waits_for_ground(lane, mesh):
    step, st, flight = lane
    step(sample(mesh, 0., -300., CLIMB), st, 100.)
    step(sample(mesh, 100., 0., 'cPlAction_pl_act_weapon_change'), st, 100.5)
    step(sample(mesh, 110.), st, 100.7)
    assert not flight.requests
    step(sample(mesh, 120.), st, 100.85)
    assert len(flight.requests) == 1


def test_prompt_or_damage_fall_without_traversal_action_does_not_drop(lane, mesh):
    step, st, flight = lane
    for i, action in enumerate(('cPlAction_pl_act_damage_fall', 'cPlAction_pl_act_land', WALK, WALK)):
        s = sample(mesh, i * 20., action=action)
        s['prompts'] = [{'type': 'vault', 'button': 'a'}]
        step(s, st, 100. + .2 * i)
    assert not flight.requests


@pytest.mark.parametrize('interruption', ['generation', 'operator', 'disabled', 'round', 'mesh', 'gap'])
def test_interrupted_traversal_cannot_be_reused_in_another_context(lane, mesh, interruption):
    step, st, flight = lane
    step(sample(mesh, 0., -300., CLIMB), st, 100.)
    s = sample(mesh, 100.)
    if interruption == 'generation':
        s['player']['generation'] += 1
    if interruption == 'operator':
        st['operator_control'] = True
    if interruption == 'disabled':
        st['remote_mines'] = {'enabled': False}
    if interruption == 'round':
        st['round_evidence_id'] = 'round-next'
    if interruption == 'mesh':
        s['navmesh'] = R.NavMesh(mesh.V, mesh.T, mesh.N, 'another_floor')
    step(s, st, 103. if interruption == 'gap' else 100.5)
    st.pop('operator_control', None)
    st.pop('remote_mines', None)
    step(sample(mesh, 110.), st, 103.2 if interruption == 'gap' else 100.7)
    assert not flight.requests


def test_old_unsafe_bomb_blocks_landing_and_expired_opportunity_is_not_replayed(lane, mesh):
    step, st, flight = lane
    climb(step, st, mesh, units=[bomb(x=110.)])
    assert st['mine_landing_ready'] and st['mine_deadline_pending'] and not flight.requests
    for i in range(20):
        step(sample(mesh, 110., units=[bomb(x=110.)]), st, 101.2 + i * .1)
    assert not st['mine_landing_ready'] and not flight.requests


def test_emergency_priority_consumes_same_landing_once(lane, mesh):
    step, st, flight = lane
    step(sample(mesh, 0., -300., CLIMB), st, 100.)
    step(sample(mesh, 100.), st, 100.5)
    st['ring_flash_at'] = 100.65
    out = step(sample(mesh, 110.), st, 100.65)
    assert out['op'] == 'bomb_ring' and flight.requests[0]['reason'] == 'flash'
    flight.finish(dict(op='bomb_ring', state='unavailable', placed=0))
    step(sample(mesh, 120.), st, 100.8)
    assert len(flight.requests) == 1 and not st['mine_landing_ready']


@pytest.mark.parametrize('change', ['midair', 'action', 'away', 'stale'])
def test_queued_landing_worker_cancels_after_landing_evidence_goes_stale(lane, mesh, monkeypatch, change):
    step, st, flight = lane
    seen = []
    monkeypatch.setattr(C, 'landing_drop_now', lambda ad, owner, cancelled, *a:
                        seen.append(cancelled()) or dict(op='bomb_landing', state='unavailable', placed=0))
    climb(step, st, mesh)
    s = sample(mesh, 110., 100. if change == 'midair' else 0.,
               'cPlAction_pl_act_damage' if change == 'action' else WALK)
    if change == 'away':
        s['player']['pos'][0] = 600.
    step.observe(s, st, 104. if change == 'stale' else 101.3)
    flight.finish()
    assert seen == [True]


def live_landing(native, monkeypatch, mesh):
    ctl, ad = controller(native, monkeypatch)
    monkeypatch.setattr(N.R, 'navmesh', lambda *a: mesh)
    monkeypatch.setattr(N.R, 'unit_action', lambda c, u: WALK if u == ctl.player else 'cWpAction_wp_act_setting')
    evidence = dict(landing_pos=[700., 0., -20.], entry_action=CLIMB, entry_at=100.)
    return ctl, ad, evidence


def test_native_landing_rechecks_real_floor_action_and_keeps_gun_and_health(native, monkeypatch, mesh):
    ctl, ad, evidence = live_landing(native, monkeypatch, mesh)
    before = ctl.rd(ctl.player + R.P_HP, 2), ctl.rd(ctl.player + R.P_EQUIPPED, 4)
    out = C.landing_drop_now(ad, OWNER, lambda: False, mesh, evidence)
    assert out['verified'] and out['op'] == 'bomb_landing' and out['placed'] == 1
    assert out['weapon_unchanged'] and out['units'][0]['armed']
    assert before == (ctl.rd(ctl.player + R.P_HP, 2), ctl.rd(ctl.player + R.P_EQUIPPED, 4))


@pytest.mark.parametrize('change', ['air', 'off_floor', 'climb', 'state', 'mesh', 'away'])
def test_native_landing_preflight_blocks_stale_snapshot_before_allocation(native, monkeypatch, mesh, change):
    ctl, ad, evidence = live_landing(native, monkeypatch, mesh)
    if change in ('air', 'off_floor', 'away'):
        pos = {'air': (700., 100., -20.), 'off_floor': (2000., 0., 2000.), 'away': (1000., 0., -20.)}[change]
        ctl.put(ctl.player + R.P_POS, struct.pack('<3f', *pos))
    if change == 'climb':
        monkeypatch.setattr(N.R, 'unit_action', lambda *a: CLIMB)
    if change == 'state':
        ctl.put(ctl.player + R.P_STATE, bytes([8]))
    if change == 'mesh':
        monkeypatch.setattr(N.R, 'navmesh', lambda *a: object())
    out = C.landing_drop_now(ad, OWNER, lambda: False, mesh, evidence)
    assert out['state'] == 'unavailable' and not out['placed'] and not ctl.calls
