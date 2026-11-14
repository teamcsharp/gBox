"""Read-only retries retain one native publication and its original deadline."""
import struct

import pytest

from tests.test_re5_switch_equip import fixture, BASE, R, E


def running():
    g, p, writes, write = fixture()
    clock = [1.0]
    g.wr = write
    stats = {'source_session_id': 'owned-re5'}
    control = E.Controller(g, stats, clock=lambda: clock[0])
    assert control.select(3, 0x119)['state'] == 'requested'
    return g, p, writes, clock, stats, control


def attached(g, p):
    g.i32(p + R.P_INV + R.INV_HAND, 0)
    g.i32(p + R.P_INV + R.INV_SLOT + R.INV_HAND, 1)
    g.put(p + E.PENDING, b'\0')


@pytest.mark.parametrize('offset,data,field', [
    (R.P_MOTION, b'\x01', 'motion'), (R.P_HP, struct.pack('<h', 900), 'hp'),
    (E.PREVIOUS, struct.pack('<i', 2), 'previous_action'),
    (E.RESET, struct.pack('<I', 1), 'reset'),
])
def test_native_dynamic_change_rereads_same_request_then_confirms_without_writes(offset, data, field):
    g, p, writes, clock, stats, control = running()
    attached(g, p)
    request, deadline, before = control.pending, control.deadline, len(writes)
    rd, seen = g.rd, [0]
    def race(address, size):
        if address == p + offset:
            seen[0] += 1
            if seen[0] == 2:
                g.put(address, data)
        return rd(address, size)
    g.rd = race
    result = control.tick()
    assert result == {'state': 'waiting', 'reason': 'native_readback_retry',
                      'readback_reason': 'changed_witness', 'readback_field': field}
    assert control.pending is request and control.deadline == deadline
    assert control.tick()['state'] == 'equipped'
    assert control.pending is None and control.failed is None
    assert len(writes) == before


def test_native_hand_changes_during_sample_wait_for_coherent_native_completion():
    g, p, writes, clock, stats, control = running()
    g.put(p + E.PENDING, b'\0')
    rd, seen = g.rd, [0]
    def race(address, size):
        if address == p + R.P_INV:
            seen[0] += 1
            if seen[0] == 2:
                attached(g, p)
        return rd(address, size)
    g.rd = race
    before = len(writes)
    result = control.tick()
    assert result['reason'] == 'native_readback_retry' and result['readback_field'] == 'inventory_state'
    assert control.tick()['state'] == 'equipped' and len(writes) == before


@pytest.mark.parametrize('cause', ['short_read', 'read_budget'])
def test_bounded_sampling_failure_keeps_owned_request_without_resetting_deadline(cause):
    g, p, writes, clock, stats, control = running()
    attached(g, p)
    request, deadline, before = control.pending, control.deadline, len(writes)
    rd, first = g.rd, [True]
    def transient(address, size):
        data = rd(address, size)
        if first[0]:
            first[0] = False
            if cause == 'short_read':
                return data[:-1]
            clock[0] += E.MAX_SECONDS + .001
        return data
    g.rd = transient
    result = control.tick()
    assert result == {'state': 'waiting', 'reason': 'native_readback_retry', 'readback_reason': cause}
    assert control.pending is request and control.deadline == deadline
    assert control.tick()['state'] == 'equipped'
    assert len(writes) == before


def test_every_proven_identity_change_is_terminal_even_when_memory_reverts_immediately():
    probe = running()[-1].pending.witness
    for index in range(len(probe.anchors)):
        g, p, writes, clock, stats, control = running()
        attached(g, p)
        request, before = control.pending, len(writes)
        at, expected, label = request.witness.anchors[index]
        rd, first = g.rd, [True]
        def aba(address, size):
            data = bytearray(rd(address, size))
            if first[0] and address <= at < address + size:
                first[0] = False
                data[at-address] ^= 1  # backing memory already has the original again
            return bytes(data)
        g.rd = aba
        result = control.tick()
        assert not first[0], label
        assert result['state'] == 'unknown' and result['readback_reason'] == 'ownership_changed', label
        assert result['readback_field'] == label
        assert control.pending is None and len(writes) == before
        assert request.observe('owned-re5') == result  # no ABA recovery of this request


def test_partial_read_cannot_hide_an_observed_wrong_generation():
    g, p, writes, clock, stats, control = running()
    rd = g.rd
    def bad_partial(address, size):
        data = rd(address, size)
        if address == p + E.GENERATION:
            return bytes([data[0] ^ 1])
        return data
    g.rd = bad_partial
    result = control.tick()
    assert result['state'] == 'unknown' and result['readback_reason'] == 'ownership_changed'
    assert result['readback_field'] == 'player_generation'


def test_retry_ownership_guard_rejects_life_change_after_sample_budget_expires():
    g, p, writes, clock, stats, control = running()
    rd, first = g.rd, [True]
    def expired(address, size):
        data = rd(address, size)
        if first[0]:
            first[0] = False
            clock[0] += E.MAX_SECONDS + .001
            g.q(p + E.GENERATION, 29)
        return data
    g.rd = expired
    result = control.tick()
    assert result['state'] == 'unknown' and result['readback_reason'] == 'read_budget'
    assert result['owner_check_reason'] == 'ownership_changed'
    assert result['owner_check_field'] == 'player_generation'


def test_retry_guard_is_itself_bounded_and_never_repeats_a_read_forever():
    g, p, writes, clock, stats, control = running()
    rd, calls = g.rd, [0]
    def slow(address, size):
        calls[0] += 1
        clock[0] += E.MAX_SECONDS + .001
        return rd(address, size)
    g.rd = slow
    before = len(writes)
    result = control.tick()
    assert result['state'] == 'unknown' and result['owner_check_reason'] == 'read_budget'
    assert calls[0] == 2 and len(writes) == before


def test_repeated_native_races_stop_at_original_deadline_with_last_cause_retained():
    g, p, writes, clock, stats, control = running()
    deadline, before = control.deadline, len(writes)
    rd, seen = g.rd, [0]
    def race(address, size):
        if address == p + R.P_MOTION:
            seen[0] += 1
            g.put(address, bytes([seen[0] % 2]))
        return rd(address, size)
    g.rd = race
    for instant in (1.1, 1.5, 2.0, 2.49):
        clock[0] = instant
        assert control.tick()['reason'] == 'native_readback_retry'
        assert control.deadline == deadline
    clock[0] = deadline
    n = seen[0]
    result = control.tick()
    assert result['reason'] == 'request_timeout' and result['readback_reason'] == 'changed_witness'
    assert result['readback_field'] == 'motion'
    assert control.pending is None and seen[0] == n and len(writes) == before


def test_retry_that_crosses_original_deadline_times_out_instead_of_extending_it():
    g, p, writes, clock, stats, control = running()
    attached(g, p)
    deadline, before = control.deadline, len(writes)
    clock[0] = deadline - .01
    rd, first = g.rd, [True]
    def late(address, size):
        data = rd(address, size)
        if first[0]:
            first[0] = False
            clock[0] += E.MAX_SECONDS + .001
        return data
    g.rd = late
    result = control.tick()
    assert result['reason'] == 'request_timeout' and result['readback_reason'] == 'read_budget'
    assert control.pending is None and control.deadline == deadline and len(writes) == before


def test_hp_crossing_dying_threshold_during_sample_is_not_a_harmless_hp_race():
    g, p, writes, clock, stats, control = running()
    rd, seen = g.rd, [0]
    def dying(address, size):
        if address == p + R.P_HP:
            seen[0] += 1
            if seen[0] == 2:
                g.put(address, struct.pack('<h', R.DYING_HP))
        return rd(address, size)
    g.rd = dying
    result = control.tick()
    assert result['state'] == 'unknown' and result['readback_reason'] == 'changed_witness'
    assert result['readback_field'] == 'hp' and control.pending is None


@pytest.mark.parametrize('change', ['dead', 'foreign_action', 'session'])
def test_unsafe_context_does_not_receive_transient_retries(change):
    g, p, writes, clock, stats, control = running()
    request, before = control.pending, len(writes)
    if change == 'dead':
        g.put(p + R.P_HP, struct.pack('<h', R.DYING_HP))
    elif change == 'foreign_action':
        action = struct.unpack('<Q', g.rd(p + E.CURRENT, 8))[0]
        g.q(action + 0x10, p + 0x10000)
    else:
        stats['source_session_id'] = 'new-session'
    assert control.tick()['state'] == 'unknown'
    assert control.pending is None and len(writes) == before


def test_session_change_during_readback_cannot_confirm_old_hand():
    g, p, writes, clock, stats, control = running()
    attached(g, p)
    rd = g.rd
    def changed(address, size):
        stats['source_session_id'] = 'new-session'
        return rd(address, size)
    g.rd = changed
    result = control.tick()
    assert result == {'state': 'unknown', 'reason': 'session_changed'}
