"""Native mine work runs beside combat and remains fenced to one live round."""
import json
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_native_mine_tactic as N, re5_proximity_native as P
from gbox.mercs.titles import re5_switch as R, re5_switch_mines as M

PLAYER, UNIT, BASE, SU = 0x50000000, 0x51000000, 0x30000000, 0x52000000


@pytest.fixture(autouse=True)
def verified_test_backend(monkeypatch, tmp_path):
    # The fake native backend proves scheduling,
    # never the game's placement, animation, arming or damage behavior.
    monkeypatch.setattr(P, 'LIVE_VERIFIED', True)
    monkeypatch.setattr(N, 'ROOT', tmp_path)


def scene():
    return {'player': {'ptr': PLAYER, 'generation': 1, 'pos': (0., 0., 0.), 'rot': 0.,
                       'hp': 1000, 'hp_max': 1000, 'motion': 1},
            'enemies': [{'ptr': 55, 'hp': 800, 'pos': (0., 0., 1000.)}],
            'mercenaries_phase': R.PHASE_PLAYING, 'ground_mines': [], 'inventory': []}


def stats():
    return {'round_evidence_id': 'round-one', 'source_session_id': 'session', 'screen': 'playing'}


def memory():
    return SimpleNamespace(adapter=SimpleNamespace(address_mode='direct'))


def receipt(state='confirmed', armed=True, count=1):
    row = {'unit': UNIT, 'generation': 42, 'pos': (0., 0., 0.), 'armed_observed': armed,
           'state_accepted': True, 'active': True}
    rows = [dict(row, unit=UNIT+i*0x1000, generation=42+i, pos=pos)
            for i, pos in enumerate(P.points((0., 0., 0.), count))]
    return {'state': state, 'verified': state == 'confirmed', 'weapon_unchanged': True, 'requested': count,
            'placed': count, 'armed': count*int(armed), 'mines': rows, 'prepared': rows}


def travel(m, mem, s, end=30):
    for i in range(4):
        s['player']['pos'] = (-210. * i, 0., 0.)
        m.observe_native(mem, s, end - 1.5 + i * .5)


def test_production_gate_never_uses_probe_override_or_legacy_fallback(monkeypatch):
    mem, s, st, calls = memory(), scene(), stats(), []
    m = M.Mines(st)
    monkeypatch.setattr(P, 'LIVE_VERIFIED', False)
    m.observe_native(mem, s, 0)
    assert m.native is None
    flight = N.Flight(mem, run=lambda *a, **kw: calls.append(a))
    assert not flight.submit(s, st, 30)
    assert not calls and flight.job is None


def test_native_weapon_handover_defers_mine_allocation_until_movement_can_resume():
    import time
    mem,s,st,calls = memory(),scene(),stats(),[]
    st['native_weapon_pending'] = {'player':PLAYER,'generation':1,'until':time.monotonic()+60}
    flight = N.Flight(mem,run=lambda *a,**kw: calls.append(a))
    assert not flight.submit(s,st,30,reason='hit',count=5,center=s['player']['pos'])
    assert not calls and flight.job is None
    assert 'handover' in st['native_mine_admission_pause']


def test_native_api_uses_one_drop_expected_life_and_nonblocking_lock(monkeypatch):
    calls = []
    ctl = SimpleNamespace(proximity_mines=lambda **kw: calls.append(kw) or receipt())
    mem = memory()
    mem.adapter._re5_native_flash = ctl
    allowed = lambda: True
    assert N._run(mem, (PLAYER, 1), allowed)['placed'] == 1
    assert calls == [{'count': 1, 'expected': (PLAYER, 1), 'allowed': allowed, 'wait_for_lock': False, 'center': None, 'on_deployed': None}]


def test_pending_drop_never_returns_pad_actions_or_duplicates_and_receipt_merges_once():
    gate, entered = threading.Event(), threading.Event()
    s, st, mem, calls = scene(), stats(), memory(), []
    def run(memory, expected, allowed, **kw):
        calls.append(expected)
        entered.set()
        assert gate.wait(3)
        assert allowed()
        return receipt()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=run)
    try:
        travel(m, mem, s)
        assert m.tick(s['player'], s, s['enemies'], 30) is None
        assert entered.wait(3)
        job = m.native.job
        for t in (30.1, 30.2, 30.3):
            m.observe_native(mem, s, t)
            assert m.tick(s['player'], s, s['enemies'], t) is None
            assert m.state == 'idle'  # no neutral/equip/place/rearm phase
        assert calls == [(PLAYER, 1)] and st['mine_attempts'] == 1 and st['mines_placed'] == 0
        gate.set(); assert job['done'].wait(3)
        assert st['mines_placed'] == 0  # worker never writes gameplay counters
        m.observe_native(mem, s, 30.4)
        assert st['mines_placed'] == 1 and m.bombs[UNIT] == (0., 0., 0.)
        m.observe_native(mem, s, 30.5)
        assert st['mines_placed'] == 1
        record = json.loads(job['path'].read_text())
        assert record['owner'] == ['round-one', PLAYER, 1] and record['receipt']['armed'] == 1
    finally:
        gate.set()


@pytest.mark.parametrize('change', ['round', 'life', 'menu', 'operator', 'closed_round', 'close', 'stale', 'disabled'])
def test_pending_request_cancels_and_preserves_its_original_receipt(change, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    s, st, mem = scene(), stats(), memory()
    def run(memory, expected, allowed, **kw):
        entered.set()
        assert gate.wait(3)
        assert not allowed()
        return receipt('uncertain')
    flight = N.Flight(mem, run=run)
    try:
        assert flight.submit(s, st, 30)
        assert entered.wait(3)
        job = flight.job
        if change == 'round': st['round_evidence_id'] = 'round-two'
        elif change == 'life': s['player']['generation'] = 2
        elif change == 'menu': st['screen'] = 'select_stage'
        elif change == 'operator': st['operator_control'] = True
        elif change == 'closed_round': st['round_evidence_closed'] = True
        elif change == 'close': flight.close()
        elif change == 'disabled': st['automine_enabled'] = False
        if change != 'stale': flight.observe(s, st)
        else: flight.seen -= N.OBSERVER_FRESH_S + 1
        gate.set(); assert job['done'].wait(3)
        packet = flight.poll(s, st)
        if change in ('round', 'life'):
            assert packet is None and st['native_mine_retired']['owner'][0] == 'round-one'
        else:
            assert packet['receipt']['state'] == 'uncertain'
            assert flight.blocked_owner == packet['owner']
        assert 'mines_placed' not in st
        record = json.loads(job['path'].read_text())
        assert record['owner'] == ['round-one', PLAYER, 1]
    finally:
        gate.set()


def test_uncertain_partial_drop_retains_hazard_without_auto_replay():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *args, **kw: receipt('uncertain', armed=False))
    travel(m, mem, s)
    assert m.tick(s['player'], s, s['enemies'], 30) is None
    assert m.native.job['done'].wait(3)
    m.observe_native(mem, s, 31)
    assert st['mines_placed'] == 0 and st['mine_unconfirmed'] == 1 and UNIT in m.bombs
    s['player']['pos'] = (0., 0., -2000.)
    assert m.tick(s['player'], s, s['enemies'], 65) is None
    assert m.native.job is None and st['mine_attempts'] == 1


def test_distance_drop_waits_for_travel_but_never_for_pursuers_to_leave():
    s, st, mem, calls = scene(), stats(), memory(), []
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: calls.append(a) or receipt())
    m.flash_until = 999
    s['player']['motion'] = R.MOTION_AIMED
    m.observe_native(mem, s, 30)
    assert m.tick(s['player'], s, s['enemies'], 30) is None and not calls
    assert st['automine_distance_cm'] == 0
    s['player']['motion'] = 1
    s['enemies'][0]['pos'] = (0., 0., 100.)
    m.cadence.distance = N.DISTANCE_CM
    m.observe_native(mem, s, 90)
    assert m.native.job['done'].wait(3)
    assert len(calls) == 1 and st['automine_request_reason'] == 'distance'
    assert m.automatic(s['player'], s, s['enemies'], 90) is None


@pytest.mark.parametrize('motion', [1, 4, 7])
def test_twenty_feet_is_measured_travel_not_wall_time_or_held_movement_buttons(motion):
    c, s, st = N.Cadence(), scene(), stats()
    s['player']['motion'] = motion
    c.observe(s, st, 0)
    for i in range(1, 20):
        c.observe(s, st, i * .1)                  # face against a wall, walking motion but no distance
    assert c.distance == 0 and c.demand(s, st, 2) is None
    for i in range(1, 4):
        s['player']['pos'] = (i * 200., 0., 0.)
        c.observe(s, st, 2 + i * .5)
    assert c.distance == 600 and c.demand(s, st, 3.5) is None
    s['player']['pos'] = (610., 0., 0.)
    c.observe(s, st, 3.6)
    assert c.demand(s, st, 3.6) == ('distance', None)
    c.claimed(('distance', None), 3.6)
    assert c.demand(s, st, 30) is None and c.distance == 0


def test_observed_sprint_motion_admits_one_native_drop_after_twenty_feet():
    # Ship Deck 0ab55576: native action4 with B+LUP moved ~3m over
    # 1794569039.78..1794569040.92. Restricting travel to1/7 missed running.
    s, st, mem, calls = scene(), stats(), memory(), []
    s['player']['motion'] = 4
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: calls.append(a) or receipt())
    travel(m, mem, s)
    assert m.native.job['done'].wait(3)
    assert len(calls) == 1 and st['automine_request_reason'] == 'distance'
    assert m.automatic(s['player'], s, s['enemies'], 30) is None


@pytest.mark.parametrize('change', ['gap', 'warp', 'life', 'off', 'menu', 'operator', 'aimed'])
def test_distance_never_accumulates_across_invalid_observations(change):
    c, s, st = N.Cadence(), scene(), stats()
    c.observe(s, st, 0)
    s['player']['pos'] = (500., 0., 0.)
    now, on = .5, True
    if change == 'gap': now = 20
    elif change == 'warp': s['player']['pos'] = (10000., 0., 0.)
    elif change == 'life': s['player']['generation'] = 2
    elif change == 'off': on = False
    elif change == 'menu': st['screen'] = 'select_stage'
    elif change == 'operator': st['operator_control'] = True
    elif change == 'aimed': s['player']['motion'] = R.MOTION_AIMED
    c.observe(s, st, now, on)
    assert c.distance == 0 and c.demand(s, st, now) is None


@pytest.mark.parametrize('kind', ['hit', 'qte'])
def test_one_native_reaction_per_damage_or_qte_event_without_equipment_use(kind):
    s, st, mem, calls = scene(), stats(), memory(), []
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: calls.append(kw) or receipt(count=kw['count']))
    m.observe_native(mem, s, 0)
    s['enemies'][0]['pos'] = (0., 0., 100.)
    if kind == 'qte': s['player']['motion'] = next(iter(R.MOTION_HELD))
    else: s['player']['hp'] = 800
    m.observe_native(mem, s, .1)
    assert m.native.job['done'].wait(3)
    assert len(calls) == 1 and st['automine_request_reason'] == kind
    action = m.automatic(s['player'], s, s['enemies'], .1)
    if kind == 'hit':
        assert action and 'dup' not in action.get('hold', ()) and calls[0]['count'] == 5
        assert calls[0]['center'] == s['player']['pos']
    else:
        assert action is None and calls[0]['count'] == 1
    m.observe_native(mem, s, .2)
    for t in (1, 4, 8):
        m.observe_native(mem, s, t)
    assert len(calls) == 1 and st['mines_placed'] == (5 if kind == 'hit' else 1)


def test_automine_off_cancels_pending_then_on_does_not_replay_damage_while_off():
    gate, entered = threading.Event(), threading.Event()
    s, st, mem = scene(), stats(), memory()
    def run(memory, expected, allowed, **kw):
        entered.set(); assert gate.wait(3)
        assert not allowed()
        return {'state': 'unavailable', 'reason': 'cancelled before allocation'}
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=run)
    try:
        travel(m, mem, s)
        assert entered.wait(3)
        job = m.native.job
        s['mine_settings'] = {'automine': False}
        s['player']['hp'] = 800
        m.observe_native(mem, s, 30.1)
        assert job['cancel'].is_set() and st['automine_enabled'] is False
        gate.set(); assert job['done'].wait(3)
        m.observe_native(mem, s, 30.2)
        s['mine_settings'] = {'automine': True}
        m.observe_native(mem, s, 35)
        assert m.native.job is None and st['mine_attempts'] == 1
    finally:
        gate.set()


def test_damage_ring_keeps_hit_position_and_flees_before_arming_without_claiming_placement():
    gate, entered = threading.Event(), threading.Event()
    s, st, mem, calls = scene(), stats(), memory(), []
    result = receipt(count=5)
    def run(memory, expected, allowed, **kw):
        calls.append(kw)
        for row in result['mines']:
            kw['on_deployed'](dict(row, armed_observed=False))
        entered.set()
        assert gate.wait(3)
        return result
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=run)
    try:
        m.observe_native(mem, s, 0)
        st['ring_async_pending'] = True
        s['player']['hp'] = 800
        m.observe_native(mem, s, .1)              # hit at origin; flash gets the native controller first
        assert m.native.job is None
        s['player']['pos'] = (400., 0., 0.)
        st['ring_async_pending'] = False
        m.observe_native(mem, s, .2)
        assert entered.wait(3)
        job = m.native.job
        assert calls[0]['count'] == 5 and calls[0]['center'] == (0., 0., 0.)
        assert not m.bombs and st['mines_placed'] == 0  # callback thread never mutates the combat state
        assert m.automatic(s['player'], s, [], .2) is not None  # flee immediately, before queue drain
        m.observe_native(mem, s, .3)
        assert len(m.bombs) == 5 and st['mines_placed'] == 0 and st['native_mine_deployed_hazards'] == 5
        s['ground_mines'] = [{'ptr': r['unit'], 'pos': r['pos']} for r in result['mines']]
        assert m.automatic(s['player'], s, [], 7.) is not None  # no enemies/old six-second cap do not mean safe
        assert st['native_mine_escape_required'] and st['mine_retreats_completed'] == 0
        assert st['native_mine_escape_blocked']['required_cm'] == M.RETREAT_CM
        s['player']['pos'] = (0., 0., -2200.)
        assert m.automatic(s['player'], s, [], 7.1) is None
        assert st['mine_retreats_completed'] == 1 and not st['native_mine_escape_required']
        gate.set(); assert job['done'].wait(3)
        m.observe_native(mem, s, 7.2)
        assert st['mines_placed'] == 5 and m._native_escape is None  # late receipt cannot restart completed escape
    finally:
        gate.set()


def test_manual_early_hazards_are_owned_deduplicated_and_keep_one_ring_center():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('manual observation must not allocate'))
    rows = receipt(count=5)['mines']
    owned = [{'id': 'manual', 'owner': list(N.identity(s, st)), 'center': (0., 0., 0.),
              'mine': dict(row, armed_observed=False)}
             for row in rows]
    foreign = dict(owned[0], id='old', owner=['old-round', PLAYER, 1])
    st['native_mine_force_hazards'] = [foreign, owned[0], owned[0], *owned[1:]]
    m.observe_native(mem, s, 1.)
    assert len(m.bombs) == 5 and st['mines_placed'] == 0 and st['native_mine_force_hazards'] == []
    assert st['native_mine_deployed_hazards'] == 5
    center = m.site
    assert center == (0., 0., 0.)  # actual commit centre, not the first offset mine
    s['player']['pos'] = (700., 0., 0.)
    assert m.automatic(s['player'], s, [], 2.) is not None and m.site == center
    s['player']['pos'] = (-700., 0., 0.)
    assert m.automatic(s['player'], s, [], 3.) is not None and m.site == center


def test_old_owner_deployment_queue_cannot_create_a_new_round_hazard():
    s, st, mem = scene(), stats(), memory()
    f = N.Flight(mem)
    f.observe(s, st)
    f.deployments.put_nowait({'id': 'old', 'owner': ('old-round', PLAYER, 1), 'mine': receipt()['mines'][0]})
    assert f.take_deployments() == []


def test_native_busy_before_allocation_is_not_uncertain_or_an_invisible_escape():
    from gbox.mercs.titles.re5_switch_native import ControllerBusy
    s, st, mem = scene(), stats(), memory()
    def run(*a, **kw):
        raise ControllerBusy('known no allocation')
    m = M.Mines(st); m.new_round(0); m.native = N.Flight(mem, run=run)
    m.observe_native(mem, s, 0)
    s['player']['hp'] = 800
    m.observe_native(mem, s, .1)
    assert m.native.job['done'].wait(3)
    m.observe_native(mem, s, .2)
    assert m.native.blocked_owner is None and not m.bombs
    assert m.automatic(s['player'], s, [], .3) is None
    assert not st['native_mine_escape_required'] and st['mine_retreats_completed'] == 0


def test_manual_five_mine_receipt_is_owned_armed_deduplicated_and_becomes_a_hazard():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('manual receipt must not start a new drop'))
    result = receipt()
    result.update(requested=5, placed=5, armed=5,
        mines=[dict(result['mines'][0], unit=UNIT+i*0x1000, generation=42+i) for i in range(5)])
    packet = {'id': 'manual-ring', 'owner': list(N.identity(s, st)), 'receipt': result}
    st['native_mine_force_receipts'] = [dict(packet, id='old', owner=['old-round', PLAYER, 1]), packet, packet]
    m.observe_native(mem, s, 1)
    assert st['native_mine_force_receipts'] == [] and st['mines_placed'] == 5
    assert len(m.bombs) == 5 and m.state == 'retreat'
    assert m.automatic(s['player'], s, s['enemies'], 1)['hold'][:2] == M.RUN
    assert len(m.bombs) == 5                       # snapshot predates the newer receipt


def test_automine_does_not_depend_on_legacy_inventory_supply_enabled():
    s, st, mem, calls = scene(), stats(), memory(), []
    s['mine_settings'] = {'enabled': False, 'automine': True}
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: calls.append(a) or receipt())
    travel(m, mem, s)
    assert m.native.job['done'].wait(3)
    assert not m.enabled and st['automine_enabled'] and len(calls) == 1


def test_same_census_at_later_clock_cannot_retire_a_newer_receipt_but_next_read_can():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('receipt test must not place'))
    st['native_mine_force_receipts'] = [
        {'id': 'manual-drop', 'owner': list(N.identity(s, st)), 'receipt': receipt()}]
    m.observe_native(mem, s, 1.)                # engine observer consumes receipt after snapshot was taken
    m.watch(s['player'], dict(s), 1.04)         # Bot's shallow decision copy and a later clock
    assert UNIT in m.bombs and st['mines_gone'] == 0 and st['mine_blasts'] == 0
    m.watch(s['player'], dict(s), 1.1)
    assert UNIT in m.bombs and st['mines_gone'] == 0
    fresh = dict(s, ground_mines=[])
    m.watch(fresh['player'], fresh, 1.2)        # a genuinely newer empty native census
    assert not m.bombs and st['mines_gone'] == 1 and st['mine_blasts'] == 0
    assert st['native_mine_removals_unattributed'] == 1 and st['native_mine_triggers_observed'] == 0
    assert not m._native_receipt_census


def test_new_round_drops_census_references_and_rejects_the_previous_round_receipt():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('receipt test must not place'))
    old = {'id': 'old-drop', 'owner': list(N.identity(s, st)), 'receipt': receipt()}
    st['native_mine_force_receipts'] = [old]
    m.observe_native(mem, s, 1.)
    assert UNIT in m.bombs and m._native_receipt_census
    st['round_evidence_id'] = 'round-two'
    s['player']['generation'] = 2
    m.new_round(2.)
    st['native_mine_force_receipts'] = [dict(old, id='late-old-drop')]
    m.observe_native(mem, s, 2.1)
    assert not m.bombs and not m._native_receipt_census
    assert st['mines_placed'] == 1 and st['native_mine_force_receipts'] == []


def test_native_trigger_observation_is_counted_once_without_inventing_blast_damage():
    s, st, mem = scene(), stats(), memory()
    m = M.Mines(st); m.new_round(0)
    m.native = N.Flight(mem, run=lambda *a, **kw: pytest.fail('observation must not place'))
    st['native_mine_force_receipts'] = [
        {'id': 'manual-drop', 'owner': list(N.identity(s, st)), 'receipt': receipt()}]
    m.observe_native(mem, s, 1.)
    fresh = dict(s, ground_mines=[], ground_mine_observations=[
        {'ptr': UNIT, 'generation': 42, 'native_owner': PLAYER, 'active': True, 'trigger_observed': True}])
    m.watch(fresh['player'], fresh, 1.2)
    m.watch(fresh['player'], fresh, 1.4)
    assert st['native_mine_triggers_observed'] == st['native_mine_removals_observed'] == 1
    assert st['native_mine_removals_unattributed'] == st['mine_blasts'] == st['mine_blast_hp_loss'] == 0


def test_prompt_observation_starts_round_before_qte_request_and_flee_waits_for_release(monkeypatch):
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    s, st = scene(), stats()
    s['player']['motion'] = next(iter(R.MOTION_HELD))
    s['enemies'][0]['pos'] = (0., 0., 100.)
    b = R.Bot(stats=st, clock=lambda: .1)
    b.observe_reactions(s, 0.)
    assert b._round_started == 0. and b.escape is None
    assert st['automine_event']['kind'] == 'qte'
    s['player']['motion'] = 1
    b.observe_reactions(s, .1)
    assert b.escape is not None and st['reactive_escape_requests'] == 1
    escape = b.escape
    b.observe_reactions(s, .2)
    assert b.escape == escape and st['reactive_escape_requests'] == 1
    s['player']['hp'] = 800                       # a new hit cannot reset an escape underway
    b.observe_reactions(s, .3)
    assert b.escape == escape and st['reactive_escape_requests'] == 1


@pytest.mark.parametrize('busy', ['escape', 'reposition', 'fire'])
def test_unavailable_native_automine_never_equips_or_steals_existing_plan(busy, monkeypatch):
    from tests.test_re5_switch_mines import GUN, BOMB, bot_snap
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    b = R.Bot(stats={}, clock=lambda: 31.)
    s = bot_snap([dict(GUN), dict(BOMB)])
    b.mines.new_round(0)
    if busy == 'escape': b.escape = (1.2, 33.)
    elif busy == 'reposition': b._aim_wait = {'until': 33.}
    else: b.fire_down = True
    old_escape, old_fire, old_step = b.escape, b.fire_down, getattr(b, '_aim_wait', None)
    assert b._mine_action(s['player'], s, s['enemies'], 31.) is None
    assert (b.escape, b.fire_down, getattr(b, '_aim_wait', None)) == (old_escape, old_fire, old_step)
    assert b.mines.state == 'idle' and b.stats['mine_attempts'] == 0


class Memory:
    def __init__(self):
        self.data, self.reads = {}, []
    def put(self, addr, data):
        self.data.update((addr+i, byte) for i, byte in enumerate(data))
    def q(self, addr, value):
        self.put(addr, struct.pack('<Q', value))
    def rd(self, addr, size):
        self.reads.append((addr, size))
        return bytes(self.data.get(addr+i, 0) for i in range(size))


def mine_memory():
    mem, s = Memory(), scene()
    mem.q(PLAYER+0x1A00, 1)
    mem.q(BASE+R.S_UNIT, SU)
    mem.q(SU+R.UNIT_LINES+R.LINE_STRIDE*R.MINE_LINE, UNIT)
    mem.q(UNIT, BASE+P.VTABLE); mem.q(UNIT+0x1A00, 42); mem.q(UNIT+0x1A10, PLAYER)
    mem.put(UNIT+0x27B9, b'\1')
    mem.put(UNIT+R.E_POS, struct.pack('<3f', 10., 20., 30.))
    setattr(mem, N.GUARD_ATTRIBUTE, {'owner': ('round-one', PLAYER, 1), 'actors': {},
                                   'seen': N.time.monotonic(), 'needs_scan': True, 'pending': False})
    return mem, s


def test_native_hazards_without_inventory_are_discovered_once_then_read_by_owned_identity():
    mem, s = mine_memory()
    rows = N.ground(mem, BASE, s['player'])
    assert rows == [{'ptr': UNIT, 'generation': 42, 'pos': (10., 20., 30.), 'native_owner': PLAYER,
                     'active': True, 'trigger_observed': False, 'primary_enabled': None, 'proximity_enabled': None}]
    mem.reads.clear()
    assert N.ground(mem, BASE, s['player']) == rows
    assert all(addr != BASE+R.S_UNIT for addr, size in mem.reads)
    mem.q(UNIT+0x1A00, 43)
    assert N.ground(mem, BASE, s['player']) == []  # reused native actor is no longer this mine


@pytest.mark.parametrize('change', ['other_owner', 'inactive', 'triggered', 'stale', 'wrong_player', 'cycle'])
def test_native_observation_never_treats_an_inactive_or_foreign_actor_as_a_hazard(change):
    mem, s = mine_memory()
    if change == 'other_owner': mem.q(UNIT+0x1A10, PLAYER+1)
    elif change == 'inactive': mem.put(UNIT+0x27B9, b'\0')
    elif change == 'triggered': mem.put(UNIT+0x28C1, b'\1')
    elif change == 'stale': getattr(mem, N.GUARD_ATTRIBUTE)['seen'] -= 10
    elif change == 'wrong_player': s['player']['generation'] = 2
    elif change == 'cycle': mem.q(UNIT+R.UNIT_NEXT, UNIT)
    rows = N.ground(mem, BASE, s['player'])
    assert rows is None if change in ('stale', 'wrong_player', 'cycle') else rows == []


def test_native_observation_read_failure_is_unknown_not_a_false_empty_blast_census():
    mem, s = mine_memory()
    assert N.ground(mem, BASE, s['player'])
    def unreadable(*args): raise OSError('temporary read loss')
    mem.rd = unreadable
    assert N.ground(mem, BASE, s['player']) is None
    assert getattr(mem, N.GUARD_ATTRIBUTE)['actors'] == {UNIT: 42}
    assert N.ground_observations(mem, s['player']) is None


def test_owned_raw_mine_states_include_disabled_primary_and_trigger_transition():
    mem, s = mine_memory()
    primary, proximity = 0x53000000, 0x54000000
    mem.q(UNIT+0x2710, primary); mem.q(UNIT+0x28C8, proximity)
    mem.put(primary+0x14, b'\0'); mem.put(proximity+0x14, b'\1')
    rows = N.ground(mem, BASE, s['player'])
    assert rows[0]['primary_enabled'] is False and rows[0]['proximity_enabled'] is True
    assert N.ground_observations(mem, s['player']) == rows
    mem.put(primary+0x14, b'\1'); mem.put(UNIT+0x28C1, b'\1')
    assert N.ground(mem, BASE, s['player']) == []
    observed = N.ground_observations(mem, s['player'])
    assert len(observed) == 1 and observed[0]['trigger_observed'] is True
    assert observed[0]['primary_enabled'] is observed[0]['proximity_enabled'] is True
    assert getattr(mem, N.GUARD_ATTRIBUTE)['actors'] == {}


def test_inactive_owned_mine_is_evidence_but_not_a_hazard_and_invalid_volume_is_not_dereferenced():
    mem, s = mine_memory()
    assert N.ground(mem, BASE, s['player'])
    mem.put(UNIT+0x27B9, b'\0'); mem.q(UNIT+0x2710, 1); mem.q(UNIT+0x28C8, 2)
    mem.reads.clear()
    assert N.ground(mem, BASE, s['player']) == []
    observed = N.ground_observations(mem, s['player'])
    assert observed[0]['active'] is False and observed[0]['primary_enabled'] is None
    assert all(at not in (1+0x14, 2+0x14) for at, size in mem.reads)
