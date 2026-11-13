"""A known inactive floor refusal must not disable all later native mine drops."""
from pathlib import Path
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_mine_refusal as F, re5_native_mine_tactic as N
from gbox.mercs.titles import re5_proximity_native as P, re5_switch as R, re5_switch_mines as M
from test_re5_proximity_native import mine_controller
from test_re5_native_mine_tactic import scene, stats


def fixture(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    ctl.fixture_native_call = original
    def miss(off, *args, **kw):
        out = original(off, *args, **kw)
        return 0 if off == P.GROUND and args[0] == ctl.units[1] else out
    ctl.call = miss
    receipt = P.place(ctl, 5, allow_unverified=True)
    assert receipt['state'] == 'refused' and F.candidate(receipt, 5)
    main, gs = 0x250000000, 0x260000000
    ctl.put(ctl.base+R.S_MAIN, struct.pack('<Q', main))
    ctl.put(main+R.MAIN_GAMESYS, struct.pack('<Q', gs))
    ctl.put(gs+R.GS_PHASE, struct.pack('<I', R.PHASE_PLAYING))
    memory = SimpleNamespace(adapter=SimpleNamespace(address_mode='direct', _re5_native_flash=ctl))
    owner = ('round-one', ctl.player, ctl.generation)
    return ctl, memory, owner, receipt


def completed(monkeypatch):
    ctl, memory, owner, receipt = fixture(monkeypatch)
    monkeypatch.setattr(P, 'LIVE_VERIFIED', True)
    snap, st = scene(), stats()
    snap['player'].update(ptr=owner[1], generation=owner[2])
    flight = N.Flight(memory)
    done = threading.Event(); done.set()
    flight.job = {'id': 'floor-refused', 'owner': owner, 'result': receipt,
                  'done': done, 'cancel': threading.Event(), 'path': Path('unused-test-receipt'),
                  'requested': 5, 'center': (0., 0., 0.), 'reason': 'hit'}
    return ctl, memory, owner, receipt, flight, snap, st


def test_recorded_68ba_floor_refusal_shape_is_only_a_candidate_not_native_proof():
    # Ordinary receipt metadata from round4d2c, not extracted game/model payload.
    rows = [{'index': i, 'unit': unit, 'generation': 77+i, 'resources_ready': True}
            for i, unit in enumerate((400639791520, 400639295648, 400639361184, 400639463024, 400639594112))]
    for row in rows[:2]:
        row.update(calls_completed=['0x7e51a0', '0x793ab0'], grounding='native_raycast_before_activation')
    receipt = dict(state='refused', floor_refused=True, verified=False, requested=5,
                   refused_index=1, placed=0, armed=0, triggered=0, mines=[], prepared=rows)
    assert F.candidate(receipt, 5)
    assert F.verify(SimpleNamespace(), ('4d2c', 400627597472, 1), receipt)['state'] == 'unknown'


@pytest.mark.parametrize('change', ['uncertain', 'configured', 'state3', 'deployed', 'armed', 'triggered',
                                  'detach', 'missing', 'duplicate', 'incomplete', 'foreign_call'])
def test_only_explicit_zero_activation_refusals_can_be_reconciled(monkeypatch, change):
    ctl, memory, owner, receipt = fixture(monkeypatch)
    if change == 'uncertain': receipt['state'] = 'uncertain'
    elif change == 'configured': receipt['prepared'][0]['configured'] = True
    elif change == 'state3': receipt['prepared'][0]['state_accepted'] = True
    elif change == 'deployed': receipt['placed'] = 1
    elif change == 'armed': receipt['armed'] = 1
    elif change == 'triggered': receipt['triggered'] = 1
    elif change == 'detach': receipt['detach_error'] = 'mailbox incomplete'
    elif change == 'missing': receipt.pop('floor_refused')
    elif change == 'duplicate': receipt['prepared'][1].update(unit=receipt['prepared'][0]['unit'], generation=77)
    elif change == 'incomplete': receipt['prepared'].pop()
    else: receipt['prepared'][0]['calls_completed'].append('0x60d6d0')
    # Duplicate exact identity, irrespective of the synthetic generation value.
    if change == 'duplicate': receipt['prepared'][1]['generation'] = receipt['prepared'][0]['generation']
    assert not F.candidate(receipt, 5)
    assert F.verify(memory, owner, receipt)['state'] == 'unsafe'


def test_complete_owned_inactive_batch_and_detached_mailbox_prove_retry_without_writes(monkeypatch):
    ctl, memory, owner, receipt = fixture(monkeypatch)
    before = len(ctl.writes), len(ctl.native_calls)
    proof = F.verify(memory, owner, receipt)
    assert proof['state'] == 'verified_inactive' and proof['verified_actors'] == 5
    assert (len(ctl.writes), len(ctl.native_calls)) == before
    assert receipt['placed'] == receipt['armed'] == 0


@pytest.mark.parametrize('change', ['active', 'primary', 'proximity', 'attached', 'trigger', 'actor_life',
                                  'actor_owner', 'pool', 'pool_owner', 'failed', 'pending', 'executing',
                                  'attached_player', 'player_life', 'dead', 'phase', 'ring_pending'])
def test_uncertain_lifecycle_or_collision_keeps_owner_locked(monkeypatch, change):
    ctl, memory, owner, receipt = fixture(monkeypatch)
    unit = receipt['prepared'][0]['unit']
    if change == 'active': ctl.put(unit+0x27B9, b'\1')
    elif change == 'primary': ctl.put(unit+0x4014, b'\1')
    elif change == 'proximity': ctl.put(unit+0x3014, b'\1')
    elif change == 'attached': ctl.put(unit+0x48, struct.pack('<Q', ctl.player))
    elif change == 'trigger': ctl.put(unit+0x28C1, b'\1')
    elif change == 'actor_life': ctl.put(unit+0x1A00, struct.pack('<Q', 999))
    elif change == 'actor_owner': ctl.put(unit+0x1A10, struct.pack('<Q', ctl.player+16))
    elif change == 'pool': ctl._proximity_prepared['rows'].pop()
    elif change == 'pool_owner': ctl._proximity_prepared['owner'] = (ctl.player, 999)
    elif change == 'failed': ctl.failed = True
    elif change in ('pending', 'executing'): ctl.put(ctl.heap+0x6A8, struct.pack('<I', 1 if change == 'pending' else 2))
    elif change == 'attached_player': ctl.put(ctl.player, struct.pack('<Q', ctl.heap))
    elif change == 'player_life': ctl.put(ctl.player+0x1A00, struct.pack('<Q', 999))
    elif change == 'dead': ctl.put(ctl.player+R.P_HP, b'\0\0')
    elif change == 'phase': ctl.put(0x260000000+R.GS_PHASE, struct.pack('<I', 3))
    else: ctl.ring_projectile_pending = {'stage': 'spawn_requested'}
    before = len(ctl.writes), len(ctl.native_calls)
    assert F.verify(memory, owner, receipt)['state'] == 'unsafe'
    assert (len(ctl.writes), len(ctl.native_calls)) == before


def test_second_pass_detects_native_collision_change_and_short_flags_refuse(monkeypatch):
    for short in (False, True):
        ctl, memory, owner, receipt = fixture(monkeypatch)
        at = receipt['prepared'][0]['unit']+0x3014
        rd, visits = ctl.rd, [0]
        def raced(addr, size):
            if addr == at:
                visits[0] += 1
                if visits[0] >= 2:
                    return b'' if short else b'\1'
            return rd(addr, size)
        ctl.rd = raced
        assert F.verify(memory, owner, receipt)['state'] == 'unsafe'


def test_safe_refusal_is_unblocked_but_not_counted_as_placement(monkeypatch):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    packet = flight.poll(snap, st)
    assert packet['receipt']['state'] == 'refused'
    assert flight.blocked_owner is None and flight.refused_candidate is None
    assert st['native_mine_refusal_recoveries'] == 1
    assert st['native_mine_refusal_retry']['verified_actors'] == 5
    mines = M.Mines(st); mines.new_round(0.); mines.native = flight
    mines._merge_native(packet, 1., census=[])
    assert st['mines_placed'] == 0 and not mines.bombs
    assert mines._retry_at == 1.+M.RETRY_S  # existing cooldown remains


def test_busy_controller_pause_retries_at_bounded_rate_then_recovers(monkeypatch):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    clock = [1.]
    monkeypatch.setattr(N.time, 'monotonic', lambda: clock[0])
    ctl.lock = threading.Lock(); ctl.lock.acquire()
    flight.poll(snap, st)
    assert flight.blocked_owner == owner and st['native_mine_refusal_retry']['state'] == 'busy'
    first = st['native_mine_refusal_retry']
    ctl.lock.release()
    clock[0] += .1; flight.poll(snap, st)
    assert st['native_mine_refusal_retry'] is first and flight.blocked_owner == owner
    clock[0] += .5; flight.poll(snap, st)
    assert flight.blocked_owner is None and st['native_mine_refusal_recoveries'] == 1


def test_refused_ring_allows_later_travel_drop_and_reuses_existing_inactive_actor(monkeypatch, tmp_path):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    monkeypatch.setattr(N, 'ROOT', tmp_path)
    packet = flight.poll(snap, st)
    mines = M.Mines(st); mines.new_round(0.); mines.native = flight
    mines._merge_native(packet, 1., census=[])
    mines.observe_native(memory, snap, 2.)  # owner admission during the existing cooldown
    assert flight.job is None and st['mines_placed'] == 0
    ctl.call = ctl.fixture_native_call  # the later destination has a valid native ground hit
    mines.cadence.distance = N.DISTANCE_CM
    mines.observe_native(memory, snap, 5.)
    job = flight.job
    assert job is not None and job['requested'] == 1 and job['reason'] == 'distance'
    assert job['done'].wait(3)
    mines.observe_native(memory, snap, 6.)
    assert st['mines_placed'] == st['native_mines_placed'] == 1
    assert len(ctl.units) == 5 and len(ctl._proximity_prepared['rows']) == 4
    assert job['result']['mines'][0]['reused_inactive'] is True
    assert job['result']['armed'] == 1 and job['result']['weapon_unchanged'] is True
    assert len(mines.bombs) == 1 and flight.blocked_owner is None


@pytest.mark.parametrize('change', ['round', 'life', 'operator'])
def test_pending_reconciliation_never_crosses_owner_or_operator_control(monkeypatch, change):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    ctl.lock = threading.Lock(); ctl.lock.acquire()
    flight.poll(snap, st); ctl.lock.release()
    if change == 'round': st['round_evidence_id'] = 'next-round'
    elif change == 'life': snap['player']['generation'] += 1
    else: st['operator_control'] = True
    flight.refused_candidate['next'] = 0.
    flight.poll(snap, st)
    assert 'native_mine_refusal_recoveries' not in st
    if change != 'operator': assert flight.refused_candidate is None


@pytest.mark.parametrize('mode', ['operator', 'modifications_off'])
def test_admission_pause_mid_proof_keeps_candidate_for_later_full_owned_recheck(monkeypatch, mode):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    rd, changed = ctl.rd, [False]
    address = receipt['prepared'][0]['unit']+0x27B9
    before = len(ctl.writes), len(ctl.native_calls)
    def pause(addr, size):
        if addr == address and not changed[0]:
            changed[0] = True
            if mode == 'operator': st['operator_control'] = True
            else: memory.mercs_no_modifications = True
        return rd(addr, size)
    ctl.rd = pause
    flight.poll(snap, st)
    assert changed[0] and st['native_mine_refusal_retry']['state'] == 'paused'
    assert flight.blocked_owner == owner and flight.refused_candidate is not None
    st['operator_control'] = False; memory.mercs_no_modifications = False
    flight.refused_candidate['next'] = 0.
    flight.poll(snap, st)
    assert flight.blocked_owner is None and st['native_mine_refusal_retry']['verified_actors'] == 5
    assert (len(ctl.writes), len(ctl.native_calls)) == before


def test_proven_native_process_change_is_not_a_temporary_admission_pause(monkeypatch):
    from gbox.mercs.titles.re5_switch_native import Unavailable
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    def changed():
        raise Unavailable('emulator process changed')
    ctl.check_build = changed
    flight.poll(snap, st)
    assert flight.blocked_owner == owner and flight.refused_candidate is None
    assert st['native_mine_refusal_retry']['state'] == 'unsafe'


def test_independent_malformed_confirmed_receipt_invalidates_safe_refusal_candidate(monkeypatch):
    ctl, memory, owner, receipt, flight, snap, st = completed(monkeypatch)
    ctl.lock = threading.Lock(); ctl.lock.acquire()
    flight.poll(snap, st); ctl.lock.release()
    assert flight.refused_candidate is not None
    mines = M.Mines(st); mines.new_round(0.); mines.native = flight
    mines._merge_native({'id': 'another-operation', 'owner': owner, 'archive': None,
        'receipt': {'state': 'confirmed', 'verified': False, 'mines': [], 'requested': 1}}, 10.)
    assert flight.blocked_owner == owner and flight.refused_candidate is None
