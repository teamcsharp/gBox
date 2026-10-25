"""Native QTE assistance must preserve callback execution and reject stale events."""
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_ps3 as R, re5_qte as Q
from test_re5_mercs import PLAYER, SPLAYER, with_prompt, world

AB, BUTTON, UNIT = 0x38838370, 0x328E1FE0, 0x38838370+R.QTE_UNITS[0]
SCOPE = ('process', 17, 29, 'solo-bot')


def scene(mode=6, *, progress=2., target=10, action=R.P_GRABBED):
    memory = with_prompt(world(action=action), 0, PLAYER, 0, mode=mode, index=20 if mode==6 else 1)
    for address, signature in Q.SIGNATURES.items():
        memory.put(address, signature)
    memory.u32(BUTTON+0x28, target)
    memory.put(UNIT+Q.PROGRESS, struct.pack('>2f', progress, target))
    memory.writes = []
    def write(address, data):
        memory.writes.append((address, data))
        memory.put(address, data)
        return True
    memory.wr = write
    return memory


def step(helper, memory, now=0., **kw):
    return helper.step(memory, {'player': {'ptr': PLAYER}}, now, scope=kw.pop('scope', SCOPE), **kw)


@pytest.mark.parametrize('mode', [4, 6])
def test_progress_reaches_exact_native_target_without_success_or_consumed_writes(mode):
    memory = scene(mode)
    helper = Q.ProgressHook(SCOPE)
    before = memory.rd(BUTTON, 0x74)
    result = step(helper, memory)
    assert result['phase'] == 'submitted' and result['progress_verified']
    assert not result['verified'] and not result['completed'] and not result['native_accepted']
    assert memory.writes == [(UNIT+Q.PROGRESS, struct.pack('>f', 10.))]
    assert memory.rd(BUTTON, 0x74) == before
    assert step(helper, memory, .1)['phase'] == 'pending'
    assert len(memory.writes) == 1


def test_native_acceptance_is_distinct_from_observed_release_from_grab():
    memory = scene()
    helper = Q.ProgressHook(SCOPE)
    step(helper, memory)
    memory.put(BUTTON+0x0B, b'\1\1')  # emulator/native routine, never our writer
    result = step(helper, memory, .1)
    assert result['phase'] == 'native_accepted' and result['native_accepted']
    assert not result['completed']
    memory.put(PLAYER+R.P_ACTION, b'\0')
    result = step(helper, memory, .2)
    assert result['phase'] == 'completed' and result['completed']
    assert len(memory.writes) == 1


def test_disappeared_prompt_or_changed_player_is_not_success():
    for change in ('hidden', 'player', 'descriptor'):
        memory = scene(); helper = Q.ProgressHook(SCOPE); step(helper, memory)
        if change == 'hidden':
            memory.put(UNIT+5, b'\0')
        elif change == 'player':
            memory.u32(SPLAYER+0x28, PLAYER+0x10000)
        else:
            memory.u32(BUTTON+0x40, 0x33000000)
        result = step(helper, memory, 4.)
        assert not result['completed'] and not result['native_accepted']
        assert result['phase'] in ('timeout', 'ended_unconfirmed', 'native_ready')
        assert len(memory.writes) == 1


@pytest.mark.parametrize('mode', [1, 2, 3, 5, 7, 8, 9])
def test_non_accumulator_modes_retain_input_fallback(mode):
    memory = scene(mode)
    result = step(Q.ProgressHook(SCOPE), memory)
    assert result['phase'] == 'waiting' and memory.writes == []


@pytest.mark.parametrize('offset', [0x0B, 0x0C, 0x0D])
def test_native_accepted_consumed_or_reset_requests_are_never_changed(offset):
    memory = scene(); memory.put(BUTTON+offset, b'\1')
    assert step(Q.ProgressHook(SCOPE), memory)['phase'] == 'waiting'
    assert memory.writes == []


@pytest.mark.parametrize('progress', [float('nan'), float('inf'), -1., 1_000_001.])
def test_invalid_progress_is_not_clamped(progress):
    memory = scene(progress=progress)
    assert step(Q.ProgressHook(SCOPE), memory)['phase'] == 'waiting'
    assert memory.writes == []


@pytest.mark.parametrize('change', ['zero', 'negative', 'huge', 'copied_target', 'unit_mode', 'duplicate',
                                    'hidden', 'owner', 'build', 'input_table', 'dead', 'p2', 'no_modifications', 'selection_cookie'])
def test_invalid_target_build_selection_or_player_cannot_write(change):
    memory = scene()
    if change in ('zero', 'negative', 'huge'):
        target = {'zero':0, 'negative':-1, 'huge':1_000_001}[change]
        memory.put(BUTTON+0x28, struct.pack('>i', target))
        memory.put(UNIT+Q.TARGET, struct.pack('>f', target))
    elif change == 'copied_target': memory.put(UNIT+Q.TARGET, struct.pack('>f', 11.))
    elif change == 'unit_mode': memory.u32(UNIT+0x10, 4)
    elif change == 'duplicate': memory.put(AB+R.QTE_UNITS[1], memory.rd(UNIT, 0x44))
    elif change == 'hidden': memory.put(UNIT+5, b'\0')
    elif change == 'owner': memory.u32(BUTTON, 0x01000000)
    elif change == 'build': memory.put(next(iter(Q.SIGNATURES)), b'bad!')
    elif change == 'input_table': memory.put(R.QTE_INPUT_TABLE, b'bad!')
    elif change == 'dead': memory.put(PLAYER+R.P_HP, b'\0\0')
    elif change == 'p2': memory.mercs_player_index = 1
    elif change == 'no_modifications': memory.mercs_no_modifications = True
    elif change == 'selection_cookie': memory.u32(BUTTON+0x68, 123)
    assert step(Q.ProgressHook(SCOPE), memory)['phase'] == 'waiting'
    assert memory.writes == []


def test_scope_change_and_disable_forbid_writes_and_never_restore_old_progress():
    memory = scene(); helper = Q.ProgressHook(SCOPE)
    assert step(helper, memory, scope=('different-guest-mapping',))['phase'] == 'rejected'
    assert not memory.writes
    step(helper, memory)
    assert step(helper, memory, .1, enabled=False)['phase'] == 'disabled'
    assert step(helper, memory, .2, scope=None)['phase'] == 'rejected'
    assert len(memory.writes) == 1


def test_callback_or_reset_flag_change_between_full_fences_rejects(monkeypatch):
    for change in ('callback', 'reset', 'progress_reset'):
        memory = scene(); original = Q.view; reads = [0]
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            reads[0] += 1
            if reads[0] == 1:
                if change == 'callback': memory.u32(BUTTON+0x3C, 0x01700000)
                elif change == 'reset': memory.put(BUTTON+0x0D, b'\1')
                else: memory.put(UNIT+Q.PROGRESS, struct.pack('>f', 0.))
            return result
        with monkeypatch.context() as patch:
            patch.setattr(Q, 'view', changed)
            assert step(Q.ProgressHook(SCOPE), memory)['phase'] == 'waiting'
        assert memory.writes == []


def test_natural_threshold_completion_needs_no_write_and_failed_write_is_not_retried():
    memory = scene(progress=10.)
    assert step(Q.ProgressHook(SCOPE), memory)['phase'] == 'native_ready'
    assert not memory.writes
    memory = scene(); helper = Q.ProgressHook(SCOPE)
    memory.wr = lambda *_: False
    assert step(helper, memory)['phase'] == 'write_unconfirmed'
    memory.wr = lambda *_: pytest.fail('same event must not retry an uncertain write')
    assert step(helper, memory, 4.)['phase'] == 'timeout'


def test_unreadable_memory_never_becomes_success():
    memory = scene(); helper = Q.ProgressHook(SCOPE); step(helper, memory)
    memory.rd = lambda *_: (_ for _ in ()).throw(OSError('read failed'))
    assert step(helper, memory, .1)['phase'] == 'pending'
    assert step(helper, memory, 4.)['phase'] == 'timeout'
    assert len(memory.writes) == 1


def test_identical_request_rearms_only_after_observed_native_acceptance_then_reset():
    memory = scene(); helper = Q.ProgressHook(SCOPE); step(helper, memory)
    memory.put(UNIT+Q.PROGRESS, struct.pack('>f', 0.))
    assert step(helper, memory, .1)['phase'] == 'pending'
    assert len(memory.writes) == 1  # progress reset by itself is not a new event
    memory.put(BUTTON+0x0B, b'\1\1')
    assert step(helper, memory, .2)['phase'] == 'native_accepted'
    memory.put(BUTTON+0x0B, b'\0\0')
    assert step(helper, memory, .3)['phase'] == 'submitted'
    assert len(memory.writes) == 2


def test_late_action_change_does_not_manufacture_escape_success():
    memory = scene(); helper = Q.ProgressHook(SCOPE); step(helper, memory)
    memory.put(BUTTON+0x0B, b'\1\1')
    assert step(helper, memory, .2)['native_accepted']
    memory.put(PLAYER+R.P_ACTION, b'\0')
    result = step(helper, memory, 30.)
    assert result['native_accepted'] and not result['completed']


def test_first_native_acceptance_seen_after_deadline_is_not_attributed_to_this_write():
    memory = scene(); helper = Q.ProgressHook(SCOPE); step(helper, memory)
    assert step(helper, memory, 3.)['phase'] == 'timeout'
    memory.put(BUTTON+0x0B, b'\1\1')
    memory.put(PLAYER+R.P_ACTION, b'\0')
    result = step(helper, memory, 10.)
    assert result['phase'] == 'timeout'
    assert not result['native_accepted'] and not result['completed']


@pytest.mark.parametrize('offset', [0x3C, 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58])
def test_every_native_callback_field_is_in_event_identity(offset):
    memory = scene(); before = Q.view(memory)
    memory.u32(BUTTON+offset, 0x31000000)
    assert Q.view(memory)['identity'] != before['identity']


def adapter_scene():
    from gbox import re5_mods_tool as mods
    from gbox.mercs.titles import re5_controls as C
    from test_re5_mods import FakeRE5
    adapter = FakeRE5()
    adapter.b.update(scene().b)
    adapter.proc = SimpleNamespace(pid=1234)
    adapter._mem = (1234, 0x100000000)
    adapter._guest = lambda: adapter._mem
    game = mods.RE5(adapter)
    snapshot = {'player': {'ptr': PLAYER}}
    C.publish(game.orig, 'bot', snapshot, True)
    return adapter, game, snapshot


def test_configure_is_not_event_completion_and_maintenance_uses_only_current_adapter():
    adapter, game, snapshot = adapter_scene()
    assert Q.capability(game)['available']
    configured = Q.configure(game, True)
    assert configured['configured'] and not configured['native_outcome_verified']
    result = Q.maintain(adapter, snapshot, owner='bot')
    assert result['phase'] == 'submitted' and not result['completed']
    assert adapter.writes == [(UNIT+Q.PROGRESS, 4)]
    Q.configure(game, False)
    assert Q.maintain(adapter, snapshot, owner='bot')['phase'] == 'disabled'
    assert len(adapter.writes) == 1


@pytest.mark.parametrize('change', ['guest', 'process', 'owner', 'stopped', 'snapshot', 'expired'])
def test_maintenance_refuses_changed_process_guest_or_owner(change):
    adapter, game, snapshot = adapter_scene(); Q.configure(game, True)
    if change == 'guest': adapter._mem = (4321, 0x200000000)
    elif change == 'process': adapter.proc = SimpleNamespace(pid=4321)
    elif change == 'owner': game.orig['controller']['owner'] = 'another-bot'
    elif change == 'stopped': game.orig['controller']['active'] = False
    elif change == 'snapshot': snapshot['player']['ptr'] += 4
    elif change == 'expired': game.orig['controller']['seen'] -= 100.
    assert Q.maintain(adapter, snapshot, owner='bot')['phase'] == 'rejected'
    assert not adapter.writes


@pytest.mark.parametrize('change', ['guest', 'owner', 'player', 'cancel'])
def test_last_writer_fence_catches_changes_after_event_validation(monkeypatch, change):
    adapter, game, snapshot = adapter_scene(); Q.configure(game, True)
    original = Q.view; calls = [0]
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:
            if change == 'guest': adapter._mem = (4321, 0x200000000)
            elif change == 'owner': game.orig['controller']['owner'] = 'different'
            elif change == 'player': game.orig['controller']['player'] += 4
            else: game.orig['qte_assist']['enabled'] = False
        return result
    monkeypatch.setattr(Q, 'view', changed)
    result = Q.maintain(adapter, snapshot, owner='bot')
    assert result['phase'] == 'rejected' and not result['completed']
    assert not adapter.writes


@pytest.mark.parametrize('change', ['guest', 'owner', 'player', 'stopped'])
def test_outcome_from_changed_scope_is_not_published_as_verified(monkeypatch, change):
    adapter, game, snapshot = adapter_scene(); Q.configure(game, True)
    write = adapter.write_memory
    def native_callback(address, data):
        result = write(address, data)
        adapter.put(BUTTON+0x0B, b'\1\1')
        adapter.put(PLAYER+R.P_ACTION, b'\0')
        return result
    adapter.write_memory = native_callback
    original = Q.ProgressHook.step
    def switched(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        assert result['completed']
        if change == 'guest': adapter._mem = (4321, 0x200000000)
        elif change == 'owner': game.orig['controller']['owner'] = 'different'
        elif change == 'player': game.orig['controller']['player'] += 4
        else: game.orig['controller']['active'] = False
        return result
    monkeypatch.setattr(Q.ProgressHook, 'step', switched)
    result = Q.maintain(adapter, snapshot, owner='bot')
    assert result['phase'] == 'rejected'
    assert not result['verified'] and not result['native_accepted'] and not result['completed']
    assert adapter.writes == [(UNIT+Q.PROGRESS, 4)]


def test_operator_configuration_retains_off_override_and_revert_disables_hook():
    from gbox import re5_mods_tool as mods
    adapter, game, snapshot = adapter_scene()
    result = mods.run(adapter, 'instant_qte', on=True, operator=True)
    assert result['configured'] and not result['native_outcome_verified']
    assert result['status']['capabilities']['instant_qte']['native_modes'] == [4, 6]
    assert result['status']['qte_assist']['enabled'] and not adapter.writes
    mods.run(adapter, 'instant_qte', on=False, operator=True)
    assert not mods.run(adapter, 'instant_qte', on=True)['configured']
    mods.run(adapter, 'auto_qte', on=True, operator=True)
    assert mods.run(adapter, 'revert_all')['reverted']['instant_qte']
    assert not Q.status(game.orig)['enabled'] and not adapter.writes


def test_round_observation_maintains_qte_even_when_fast_prompt_skips_tick(tmp_path):
    adapter, game, snapshot = adapter_scene()
    Q.configure(game, True)
    memory = scene()
    memory.b, memory.adapter = adapter.b, adapter
    bot = R.Bot(memory, learn_dir=tmp_path)
    snapshot = R.snapshot(memory)
    assert snapshot['prompt'] == 'mash:wiggle'
    bot.observe_round(snapshot, 'playing', 1.)
    assert bot.stats['qte_native']['phase'] == 'submitted'
    assert bot.stats['qte_native_progress_writes'] == 1
    assert adapter.writes == [(UNIT+Q.PROGRESS, 4)]
