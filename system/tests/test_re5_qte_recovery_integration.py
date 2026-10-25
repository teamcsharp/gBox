"""instant_qte recovery lifecycle across native events and adapter/controller changes."""
import struct

import pytest

from gbox import re5_mods_tool as M
from gbox.mercs.titles import re5_controls as C, re5_ps3 as R, re5_qte as Q, re5_qte_recovery as RC
from test_re5_mods import fresh_originals
from test_re5_qte import adapter_scene, AB
from test_re5_qte_recovery import scene, recovered, PL, BTN, GS, GAME, HP_OPD, F


@pytest.fixture
def runtime(monkeypatch):
    adapter, game, _ = adapter_scene()
    adapter.b.update(scene().b)
    for offset in R.QTE_UNITS: adapter.put(AB+offset+5, b'\0')
    now = [10.]
    monkeypatch.setattr(Q.time, 'monotonic', lambda: now[0])
    Q.configure(game, True)
    def maintain(owner='bot', *, active=True):
        hp = struct.unpack('>h', adapter.read_memory(PL+F.P_HP, 2))[0]
        snapshot = {'player': {'ptr': PL, 'hp': hp}, 'recovery_active': hp == 1}
        C.publish(game.orig, owner, snapshot, active)
        return Q.maintain(adapter, snapshot, owner=owner)
    def recover():
        memory = scene(); memory.b = adapter.b
        recovered(memory)
    def next_event():
        adapter.put(PL+F.P_HP, struct.pack('>hh', 1, 1000))
        adapter.f32(PL+F.P_PROGRESS, 2.)
        adapter.put(PL+F.P_RECOVER_FLAG, b'\0')
        adapter.put(BTN+F.BUTTON_ACTIVE, b'\1')
        adapter.put(BTN+F.BUTTON_CONSUMED, b'\0')
        adapter.put(BTN+0x0D, b'\0')
    return adapter, game, now, maintain, recover, next_event


def test_coverage_separates_general_modes_from_special_solo_circle_recovery(runtime):
    adapter, game, now, maintain, _, _ = runtime
    cap = Q.capability(game)
    assert cap['native_modes'] == [4, 6]
    assert cap['solo_recovery']['available'] and cap['solo_recovery']['button_mode'] == 5
    assert cap['solo_recovery']['key_index'] == 25 and cap['solo_recovery']['game_modes'] == [2, 5]
    result = maintain()
    assert result['kind'] == 'solo_recovery' and result['phase'] == 'submitted'
    assert result['solo_recovery']['available'] and result['solo_recovery']['current']
    assert not result['completed'] and not result['native_recovered']
    assert adapter.writes == [(PL+F.P_PROGRESS, 4)]


def test_recovery_outcome_then_healthy_gameplay_rearms_a_new_event(runtime):
    adapter, game, now, maintain, recover, next_event = runtime
    maintain(); recover(); now[0] += .2
    result = maintain()
    assert result['completed'] and result['native_recovered'] and result['verified']
    assert not result['native_accepted']  # general button-consumed flags are a different witness
    now[0] += .1
    idle = maintain()
    assert not idle['completed'] and not idle['solo_recovery']['completed']
    assert idle['solo_recovery']['last_outcome']['completed']
    next_event(); now[0] += .2
    assert maintain()['phase'] == 'submitted'
    assert adapter.writes == [(PL+F.P_PROGRESS, 4)]*2


def test_timer_expiry_cookie_changes_and_toggles_do_not_retry_same_event(runtime):
    adapter, game, now, maintain, _, next_event = runtime
    maintain(); now[0] += 4.
    assert maintain()['phase'] == 'timeout'
    next_event(); adapter.u32(BTN+0x68, 99)
    Q.configure(game, False)
    assert not maintain()['enabled']
    Q.configure(game, True)
    assert maintain()['phase'] == 'timeout'
    assert len(adapter.writes) == 1


def test_owner_change_blocks_old_event_until_observed_healthy_gameplay(runtime):
    adapter, game, now, maintain, recover, next_event = runtime
    maintain(); now[0] += .1
    assert maintain('new-bot')['phase'] == 'blocked'
    assert len(adapter.writes) == 1
    recover(); now[0] += .1
    maintain('new-bot')
    next_event(); now[0] += .1
    assert maintain('new-bot')['phase'] == 'submitted'
    assert len(adapter.writes) == 2


def test_new_native_round_rearms_but_playing_phase_change_alone_does_not(runtime):
    adapter, game, now, maintain, _, next_event = runtime
    maintain(); next_event(); now[0] += .1
    adapter.u32(GS+R.GS_PHASE, 2)
    assert maintain()['phase'] == 'rejected'
    assert len(adapter.writes) == 1
    adapter.u32(GS+0x348, 2)
    assert maintain()['phase'] == 'rejected'
    assert len(adapter.writes) == 1
    new_game = GAME+0x10000
    from test_re5_qte_recovery import AREA
    adapter.put(new_game, adapter.read_memory(GAME, M.GAME_CLOCK+4))
    adapter.u32(AREA+M.AREA_GAME, new_game)
    assert maintain()['phase'] == 'submitted'
    assert len(adapter.writes) == 2


def test_unconfirmed_write_never_retries_without_event_transition(runtime):
    adapter, game, now, maintain, _, next_event = runtime
    def uncertain(address, data):
        adapter.writes.append((address, len(data)))
        return {'written': 0}
    adapter.write_memory = uncertain
    assert maintain()['phase'] == 'write_unconfirmed'
    next_event(); now[0] += .2
    assert maintain()['phase'] == 'pending'
    assert len(adapter.writes) == 1


@pytest.mark.parametrize('change', ['owner', 'player', 'guest', 'cancel', 'callback'])
def test_adapter_writer_repeats_scope_and_event_guard_after_primitive_fence(runtime, monkeypatch, change):
    adapter, game, now, maintain, _, _ = runtime
    original = RC.event_fence; calls = [0]
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:  # the adapter writer's independent final fence
            if change == 'owner': game.orig['controller']['owner'] = 'other'
            elif change == 'player': game.orig['controller']['player'] += 4
            elif change == 'guest': adapter._mem = (4321, 0x200000000)
            elif change == 'cancel': game.orig['qte_assist']['enabled'] = False
            else: adapter.u32(HP_OPD, RC.HP_CALLBACK_ENTRY+4)
        return result
    monkeypatch.setattr(RC, 'event_fence', changed)
    result = maintain()
    assert calls[0] >= 2 and not adapter.writes
    assert not result['completed'] and not result['verified']


@pytest.mark.parametrize('change', ['owner', 'player', 'guest', 'stop'])
def test_late_scope_change_invalidates_top_and_nested_current_recovery(runtime, monkeypatch, change):
    adapter, game, now, maintain, recover, _ = runtime
    maintain(); recover(); now[0] += .2
    original = RC.Controller.step
    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        assert result['completed']
        if change == 'owner': game.orig['controller']['owner'] = 'other'
        elif change == 'player': game.orig['controller']['player'] += 4
        elif change == 'guest': adapter._mem = (4321, 0x200000000)
        else: game.orig['controller']['active'] = False
        return result
    monkeypatch.setattr(RC.Controller, 'step', changed)
    result = maintain()
    assert result['phase'] == 'rejected' and not result['completed'] and not result['verified']
    assert not result['solo_recovery']['completed'] and not result['solo_recovery']['verified']


def test_code_mismatch_retains_other_qte_input_fallback(runtime):
    adapter, game, now, maintain, _, _ = runtime
    adapter.put(next(iter(RC.CALLBACK_SIGNATURES)), b'bad!')
    Q.configure(game, True)
    result = maintain()
    assert not result['solo_recovery']['available']
    assert result['native_modes'] == [4, 6] and not adapter.writes


def test_terminal_hp_is_reported_as_failed_not_healthy_or_rearmed(runtime):
    adapter, game, now, maintain, _, _ = runtime
    maintain(); now[0] += .2
    adapter.put(PL+F.P_HP, b'\0\0')
    assert maintain()['phase'] == 'failed'
    assert len(adapter.writes) == 1


@pytest.mark.parametrize('change', ['inactive', 'stale', 'owner', 'player', 'guest', 'maintenance_inactive'])
def test_status_cannot_republish_completed_as_current_after_scope_ends(runtime, change):
    adapter, game, now, maintain, recover, _ = runtime
    maintain(); recover(); now[0] += .2
    assert maintain()['completed']
    if change == 'inactive': game.orig['controller']['active'] = False
    elif change == 'stale': now[0] += C.FRESH_S+1
    elif change == 'owner': game.orig['controller']['owner'] = 'other'
    elif change == 'player': game.orig['controller']['player'] += 4
    elif change == 'guest': adapter._mem = (4321, 0x200000000)
    else: Q.maintain(adapter, {'player': {'ptr': PL}}, owner='bot', enabled=False)
    result = Q.status(game.orig)
    assert not result['completed'] and not result['verified']
    assert not result['solo_recovery']['completed'] and not result['solo_recovery']['verified']
    assert result['last_outcome']['completed']
    # Becoming active again without a new event cannot resurrect that receipt.
    if change == 'inactive':
        game.orig['controller']['active'] = True
        assert not Q.status(game.orig)['completed']


@pytest.mark.parametrize('change', ['threshold', 'increment', 'partner', 'controller_busy', 'scale', 'timestep', 'profile'])
def test_actual_writer_rechecks_all_native_threshold_and_solo_gates(runtime, monkeypatch, change):
    adapter, game, now, maintain, _, _ = runtime
    from test_re5_recovery import PARAM, STEP, PROF
    original = RC.event_fence; calls = [0]
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            if change == 'threshold': adapter.f32(PARAM+F.PARAM_THRESHOLD, 1000.)
            elif change == 'increment': adapter.f32(PARAM+F.PARAM_INCREMENT, 100.)
            elif change == 'partner': adapter.u32(PL+F.P_PARTNER, 0x31000000)
            elif change == 'controller_busy':
                adapter.u32(PL+F.P_CONTROLLER, 0x31000000)
                adapter.u32(0x31000000+F.CONTROLLER_BUSY, 1)
            elif change == 'scale': adapter.f32(PL+F.P_SCALE, 10.)
            elif change == 'timestep': adapter.f32(STEP+0x2C, .5)
            else:
                adapter.u32(F.S_PROFILE, PROF+0x1000)
                adapter.u32(PROF+0x1000+F.PROFILE_INDEX, 0)
        return result
    monkeypatch.setattr(RC, 'event_fence', changed)
    result = maintain()
    assert not adapter.writes and not result['verified'] and not result['completed']


def test_hp_one_without_owned_recovery_preserves_existing_wiggle_accumulator(runtime):
    adapter, game, now, maintain, _, _ = runtime
    from test_re5_qte import UNIT
    adapter.u32(PL+F.P_BUTTON, 0)
    adapter.put(UNIT+5, b'\1')
    result = maintain()
    assert result['kind'] == 'accumulation' and result['phase'] == 'submitted'
    assert not result['solo_recovery']['current']
    assert adapter.writes == [(UNIT+Q.PROGRESS, 4)]


def test_unknown_recovery_after_a_progress_attempt_cannot_fall_through_to_another_hook(runtime):
    adapter, game, now, maintain, _, _ = runtime
    from test_re5_qte import UNIT
    maintain(); now[0] += .1
    adapter.u32(PL+F.P_BUTTON, 0)
    adapter.put(UNIT+5, b'\1')
    result = maintain()
    assert result['kind'] == 'solo_recovery' and result['phase'] == 'pending'
    assert adapter.writes == [(PL+F.P_PROGRESS, 4)]


def test_configuration_retains_exact_process_object_identity(runtime):
    adapter, game, now, maintain, _, _ = runtime
    assert game.orig['qte_assist']['process_object'] is adapter.proc


@pytest.mark.parametrize('context', ['missing_clock', 'campaign', 'callback_code'])
def test_nonapplicable_recovery_context_does_not_block_existing_hp_one_qte(runtime, context):
    adapter, game, now, maintain, _, _ = runtime
    from test_re5_qte import UNIT
    adapter.u32(PL+F.P_BUTTON, 0)
    adapter.put(UNIT+5, b'\1')
    if context == 'missing_clock': adapter.u32(M.S_AREA, 0)
    elif context == 'campaign': adapter.u32(GS+F.GAMESYS_MODE, 1)
    else: adapter.put(next(iter(RC.CALLBACK_SIGNATURES)), b'bad!')
    result = maintain()
    assert result['kind'] == 'accumulation' and result['phase'] == 'submitted'
    assert adapter.writes == [(UNIT+Q.PROGRESS, 4)]
