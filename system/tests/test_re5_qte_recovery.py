"""Scoped solo recovery: native transition evidence, never an HP-only success."""
import struct

import pytest

from gbox import re5_mods_tool as M
from gbox.mercs.titles import re5_ps3 as R, re5_recovery as F, re5_qte_recovery as Q
from test_re5_recovery import dying, PL, BTN, MAIN, GS, PARAM, STEP, SP

AREA, GAME = 0x38020000, 0x38030000
PLAYER_VT, HP_OPD = 0x016198F8, 0x016EE090
SCOPE = ('rpcs3', 17, 0x100000000, 'bot', 23)


def scene():
    m = dying()
    m.u32(M.S_AREA, AREA); m.u32(AREA, M.AREA_VT); m.u32(AREA+M.AREA_GAME, GAME)
    m.u32(GAME, M.GAME_VT); m.u32(GAME+M.GAME_CLOCK_STATE, 0)
    m.f32(GAME+M.GAME_CLOCK, 60.); m.f32(GS+R.GS_TIMER, 60.); m.f32(GS+R.GS_START, 120.)
    m.u32(GS+R.GS_PHASE, 1); m.u32(GS+0x348, 1); m.u32(GS+0x364, 5)
    m.u32(GS+R.GS_KILLS, 2); m.u32(GS+R.GS_SCORE, 1000)
    m.u32(PL, PLAYER_VT); m.u32(PLAYER_VT+0x128, HP_OPD)
    m.u32(HP_OPD, Q.HP_CALLBACK_ENTRY); m.u32(HP_OPD+4, Q.HP_CALLBACK_TOC)
    for address, signature in Q.CALLBACK_SIGNATURES.items(): m.put(address, signature)
    m.wr = m.write
    return m


def step(helper, m, now=0., **kw):
    snapshot = kw.pop('snapshot', {'player': {'ptr': PL}})
    return helper.step(m, snapshot, now, scope=kw.pop('scope', SCOPE),
                       scope_valid=kw.pop('scope_valid', lambda: True), **kw)


def recovered(m):
    m.put(PL+F.P_HP, struct.pack('>hh', 3, 1000))
    m.f32(PL+F.P_PROGRESS, 0.)
    m.put(PL+F.P_RECOVER_FLAG, b'\0')
    m.put(BTN+F.BUTTON_ACTIVE, b'\0')


def test_only_progress_written_above_threshold_and_next_native_decay():
    m = scene(); helper = Q.SoloRecovery(SCOPE)
    before = m.rd(BTN, 0x74), m.rd(PL+F.P_HP, 4), m.rd(PL+F.P_RECOVER_FLAG, 1)
    result = step(helper, m)
    assert result['phase'] == 'submitted' and result['progress_verified']
    assert not result['verified'] and not result['completed']
    assert len(m.writes) == 1 and m.writes[0][0] == PL+F.P_PROGRESS
    target = struct.unpack('>f', m.writes[0][1])[0]
    assert target-helper.pending['decay'] > helper.pending['threshold']
    assert before == (m.rd(BTN, 0x74), m.rd(PL+F.P_HP, 4), m.rd(PL+F.P_RECOVER_FLAG, 1))
    assert step(helper, m, .1)['phase'] == 'pending' and len(m.writes) == 1


def test_all_native_recovery_witnesses_required_before_success():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m)
    m.put(PL+F.P_HP, struct.pack('>hh', 3, 1000))
    assert step(helper, m, .1)['phase'] == 'pending'
    m.f32(PL+F.P_PROGRESS, 0.)
    assert step(helper, m, .2)['phase'] == 'pending'
    m.put(PL+F.P_RECOVER_FLAG, b'\1')  # not the value stored by the audited native path
    m.put(BTN+F.BUTTON_ACTIVE, b'\0')
    assert step(helper, m, .3)['phase'] == 'pending'
    m.put(PL+F.P_RECOVER_FLAG, b'\0')
    result = step(helper, m, .4)
    assert result['completed'] and result['native_recovered'] and result['verified']
    assert len(m.writes) == 1
    previous = step(helper, m, .5)
    assert previous['phase'] == 'historical' and not previous['completed']
    assert previous['last_outcome']['completed']


def test_timeout_precedes_late_hp_change_and_never_rewrites():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m)
    recovered(m)
    result = step(helper, m, Q.TIMEOUT_S)
    assert result['phase'] == 'timeout' and not result['completed']
    assert step(helper, m, 20.)['phase'] == 'timeout' and len(m.writes) == 1


@pytest.mark.parametrize('change', ['player', 'main', 'area', 'game', 'mode', 'phase', 'stage', 'character',
                                    'start', 'clock_reset', 'kills_reset', 'score_reset', 'terminal', 'coop'])
def test_changed_round_or_clock_never_makes_hp_recovery_success(change):
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m); recovered(m)
    if change == 'player': m.u32(SP+0x28, PL+0x10000)
    elif change == 'main': m.u32(F.S_MAIN, MAIN+0x10000)
    elif change == 'area': m.u32(M.S_AREA, AREA+0x10000)
    elif change == 'game': m.u32(AREA+M.AREA_GAME, GAME+0x10000)
    elif change == 'mode': m.u32(GS+F.GAMESYS_MODE, 2)
    elif change == 'phase': m.u32(GS+R.GS_PHASE, 2)
    elif change == 'stage': m.u32(GS+0x348, 2)
    elif change == 'character': m.u32(GS+0x364, 6)
    elif change == 'start': m.f32(GS+R.GS_START, 150.)
    elif change == 'clock_reset': m.f32(GAME+M.GAME_CLOCK, 61.); m.f32(GS+R.GS_TIMER, 61.)
    elif change == 'kills_reset': m.u32(GS+R.GS_KILLS, 0)
    elif change == 'score_reset': m.u32(GS+R.GS_SCORE, 0)
    elif change == 'terminal': m.u32(GAME+M.GAME_CLOCK_STATE, 1)
    elif change == 'coop': m.u32(GS+0x340, 2)
    result = step(helper, m, .5)
    assert result['phase'] == 'rejected' and not result['completed']
    assert len(m.writes) == 1


@pytest.mark.parametrize('offset', [0x04, 0x18, 0x20, 0x28, 0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58, 0x68])
def test_reused_button_or_changed_callback_does_not_count_as_same_event(offset):
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m); recovered(m)
    m.u32(BTN+offset, 0x31000000)
    result = step(helper, m, .5)
    assert result['phase'] == 'rejected' and not result['completed']


@pytest.mark.parametrize('change', ['signature', 'hp0', 'healthy', 'hidden_reset', 'consumed', 'disabled_button',
                                    'no_player', 'p2', 'no_modifications', 'campaign', 'missing_clock', 'wrong_vtable',
                                    'clock_disagreement', 'nan_clock', 'wrong_snapshot', 'partner', 'busy_controller'])
def test_unverified_or_non_solo_recovery_never_writes(change):
    m = scene(); snapshot = {'player': {'ptr': PL}}
    if change == 'signature': m.put(next(iter(F.SIGNATURES)), b'bad!')
    elif change == 'hp0': m.put(PL+F.P_HP, b'\0\0')
    elif change == 'healthy': m.put(PL+F.P_HP, struct.pack('>h', 300))
    elif change == 'hidden_reset': m.put(BTN+0x0D, b'\1')
    elif change == 'consumed': m.put(BTN+F.BUTTON_CONSUMED, b'\1')
    elif change == 'disabled_button': m.put(BTN+F.BUTTON_ACTIVE, b'\0')
    elif change == 'no_player': m.u32(SP+0x28, 0)
    elif change == 'p2': m.mercs_player_index = 1
    elif change == 'no_modifications': m.mercs_no_modifications = True
    elif change == 'campaign': m.u32(GS+F.GAMESYS_MODE, 1)
    elif change == 'missing_clock': m.u32(M.S_AREA, 0)
    elif change == 'wrong_vtable': m.u32(GAME, 0)
    elif change == 'clock_disagreement': m.f32(GS+R.GS_TIMER, 70.)
    elif change == 'nan_clock': m.f32(GAME+M.GAME_CLOCK, float('nan'))
    elif change == 'wrong_snapshot': snapshot['player']['ptr'] += 4
    elif change == 'partner': m.u32(PL+F.P_PARTNER, 0x31000000)
    elif change == 'busy_controller': m.u32(PL+F.P_CONTROLLER, 0x31000000); m.u32(0x31000000+F.CONTROLLER_BUSY, 1)
    assert step(Q.SoloRecovery(SCOPE), m, snapshot=snapshot)['phase'] == 'rejected'
    assert not m.writes


@pytest.mark.parametrize('change', ['event', 'reset', 'parameter', 'scale', 'clock'])
def test_event_changed_between_full_views_refuses_write(monkeypatch, change):
    m = scene(); original = Q.view; calls = [0]
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            if change == 'event': m.u32(BTN+0x68, 99)
            elif change == 'reset': m.put(BTN+0x0D, b'\1')
            elif change == 'parameter': m.f32(PARAM+F.PARAM_THRESHOLD, 25.)
            elif change == 'scale': m.f32(PL+F.P_SCALE, 2.)
            else: m.f32(GAME+M.GAME_CLOCK, 61.); m.f32(GS+R.GS_TIMER, 61.)
        return result
    monkeypatch.setattr(Q, 'view', changing)
    assert step(Q.SoloRecovery(SCOPE), m)['phase'] == 'rejected' and not m.writes


def test_process_controller_scope_checked_at_write_and_after_native_readback():
    m = scene(); calls = [0]
    def lost_before_write():
        calls[0] += 1
        return calls[0] < 2
    assert step(Q.SoloRecovery(SCOPE), m, scope_valid=lost_before_write)['phase'] == 'rejected'
    assert not m.writes
    m = scene(); helper = Q.SoloRecovery(SCOPE); live = [True]; write = m.wr
    def native_then_changed(address, data):
        result = write(address, data); recovered(m); live[0] = False
        return result
    m.wr = native_then_changed
    result = step(helper, m, scope_valid=lambda: live[0])
    assert result['phase'] == 'rejected' and not result['completed']
    assert len(m.writes) == 1


def test_no_retry_or_restore_after_uncertain_write_disable_or_scope_change():
    m = scene(); helper = Q.SoloRecovery(SCOPE); m.wr = lambda *_: False
    assert step(helper, m)['phase'] == 'write_unconfirmed'
    m.wr = lambda *_: pytest.fail('uncertain write must not be repeated')
    assert step(helper, m, .1)['phase'] == 'pending'
    assert step(helper, m, .2, enabled=False)['phase'] == 'disabled'
    assert step(helper, m, .3, scope=('other',))['phase'] == 'rejected'


def test_already_above_threshold_waits_without_mutation_and_invalid_time_refuses():
    m = scene(); m.f32(PL+F.P_PROGRESS, 20.)
    assert step(Q.SoloRecovery(SCOPE), m)['phase'] == 'native_ready' and not m.writes
    assert step(Q.SoloRecovery(SCOPE), m, float('nan'))['phase'] == 'rejected'


def test_natural_native_clock_advance_and_freed_recovery_button_are_valid():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m); recovered(m)
    m.f32(GAME+M.GAME_CLOCK, 59.5); m.f32(GS+R.GS_TIMER, 59.5)
    m.u32(PL+F.P_BUTTON, 0)
    assert step(helper, m, .5)['completed']


def test_unreadable_after_write_is_rejected_and_cannot_retry():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m)
    m.rd = lambda *_: (_ for _ in ()).throw(OSError('unmapped'))
    result = step(helper, m, .5)
    assert result['phase'] == 'rejected' and not result['completed']
    assert len(m.writes) == 1


def test_player_changed_during_outcome_readback_cannot_inherit_old_hp_witness():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m); recovered(m)
    original = m.rd; changed = [False]
    def read(address, size):
        raw = original(address, size)
        if address == PL+F.P_HP and size == 4 and not changed[0]:
            changed[0] = True
            m.u32(SP+0x28, PL+0x10000)
        return raw
    m.rd = read
    result = step(helper, m, .5)
    assert result['phase'] == 'rejected' and not result['completed']


def test_request_reactivated_during_outcome_reads_is_not_completed():
    m = scene(); helper = Q.SoloRecovery(SCOPE); step(helper, m); recovered(m)
    original = m.rd; count = [0]
    def read(address, size):
        raw = original(address, size)
        if address == BTN and size == 0x74:
            count[0] += 1
            if count[0] == 1: m.put(BTN+F.BUTTON_ACTIVE, b'\1')
        return raw
    m.rd = read
    result = step(helper, m, .5)
    assert result['phase'] == 'pending' and not result['completed']


@pytest.mark.parametrize('change', ['hp', 'flag', 'request', 'consumed', 'progress_ready'])
def test_final_event_fence_rechecks_native_transition_after_long_validation(monkeypatch, change):
    m = scene(); original = Q.view; calls = [0]
    def advanced(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:
            if change == 'hp': m.put(PL+F.P_HP, struct.pack('>h', 3))
            elif change == 'flag': m.put(PL+F.P_RECOVER_FLAG, b'\1')
            elif change == 'request': m.u32(PL+F.P_BUTTON, 0)
            elif change == 'consumed': m.put(BTN+F.BUTTON_CONSUMED, b'\1')
            else: m.f32(PL+F.P_PROGRESS, 20.)
        return result
    monkeypatch.setattr(Q, 'view', advanced)
    result = step(Q.SoloRecovery(SCOPE), m)
    assert result['phase'] == ('native_ready' if change == 'progress_ready' else 'rejected')
    assert not m.writes


@pytest.mark.parametrize('change', ['vtable', 'entry', 'toc', 'code'])
def test_current_player_callback_override_rejected_before_write(change):
    m = scene()
    if change == 'vtable': m.u32(PL, 0x31000000)
    elif change == 'entry': m.u32(HP_OPD, Q.HP_CALLBACK_ENTRY+4)
    elif change == 'toc': m.u32(HP_OPD+4, Q.HP_CALLBACK_TOC+4)
    else: m.put(next(iter(Q.CALLBACK_SIGNATURES)), b'bad!')
    assert step(Q.SoloRecovery(SCOPE), m)['phase'] == 'rejected' and not m.writes


@pytest.mark.parametrize('change', ['entry', 'toc'])
def test_callback_changed_after_long_validation_is_caught_by_short_fence(monkeypatch, change):
    m = scene(); original = Q.view; calls = [0]
    def advanced(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:
            m.u32(HP_OPD+(4 if change == 'toc' else 0), 0x01700000)
        return result
    monkeypatch.setattr(Q, 'view', advanced)
    assert step(Q.SoloRecovery(SCOPE), m)['phase'] == 'rejected' and not m.writes
