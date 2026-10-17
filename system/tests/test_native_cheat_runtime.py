import copy
import json
import threading
from types import SimpleNamespace

import pytest

from gbox import native_cheat_runtime as NCR, tools as T

REAL_THREAD = threading.Thread


def row(address=16, value=1, kind=1, **extra):
    return {'handler': '1', 'memory_search_size': '4', 'address': str(address),
            'value': str(value), 'cheat_type': str(kind), 'enable': False,
            'desc': f'Native {address}', **extra}


class Adapter:
    def __init__(self, entries):
        self.cheats = copy.deepcopy(entries)
        self.actual = [bool(e['enable']) for e in self.cheats]
        self.commands, self.writes, self.memory = [], [], {}
        self.events, self.artifacts = [], []
        self.config = None
        self.fail_index = None

    def cheat_set(self, index, on):
        # Same shadow-state no-op guard as RetroArchAdapter: a migration that
        # forgets to restore actual state before calling this silently fails.
        if self.cheats[index]['enable'] == on:
            return {'changed': False}
        if index == self.fail_index:
            raise RuntimeError('test command failure')
        runtime = getattr(self, '_gbox_native_cheats', None)
        if runtime is not None:
            assert not any(c['on'].is_set() for c in runtime.mine
                           if c.get('native_runtime') is runtime)
        self.commands.append((index, on))
        self.actual[index] = self.cheats[index]['enable'] = on
        return {'changed': True, 'enabled': on}

    def write_memory(self, address, data):
        self.events.append(("write", address, data))
        self.writes.append((address, data))
        self.memory.update({address + i: b for i, b in enumerate(data)})

    def read_memory(self, address, length):
        self.events.append(("read", address, length))
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def frame(self):
        # Independent, minimal RA ordering oracle: inactive/core-handler rows
        # do not consume a false condition; skipping a condition skips only it.
        run = True
        for index, entry in enumerate(self.cheats):
            if not self.actual[index] or not NCR.is_native(entry):
                continue
            if not run:
                run = True
                continue
            address = 0x8c000000 + int(entry['address'])
            value = int(entry['value'])
            kind = int(entry['cheat_type'])
            if kind == 4:
                run = int.from_bytes(self.read_memory(address, 2), 'little') == value
            elif kind == 1:
                self.write_memory(address, value.to_bytes(2, 'little'))


@pytest.fixture
def session(monkeypatch):
    sid = 'native-cheat-unit-test'
    threads = []
    class QueuedThread:
        def __init__(self, target, args, **kwargs):
            self.target, self.args = target, args
        def start(self):
            threads.append(self)
    monkeypatch.setattr(T.threading, 'Thread', QueuedThread)
    monkeypatch.setitem(T.GCHEATS, sid, [])
    ctx = SimpleNamespace(artifact=lambda *a, **k: None)
    def install(entries):
        adapter = Adapter(entries)
        def artifact(name, data, *args, **kwargs):
            adapter.events.append(('artifact', name))
            adapter.artifacts.append((name, data, kwargs))
        ctx.artifact = artifact
        monkeypatch.setitem(T.SESSIONS, sid, (adapter, {'platform': 'dreamcast'}))
        def call(op='list', index=None, **kw):
            return T.cheats_tool(T.CheatIn(session_id=sid, op=op, index=index, **kw), ctx)['result']
        return adapter, call, threads, T.GCHEATS[sid], sid
    return install


def test_native_without_code_halfword_repeated_enable_and_fresh_event(session):
    ad, call, threads, mine, _sid = session([row()])
    first = call('enable', 0)
    assert first['engine'] == 'gbox' and not ad.commands and len(threads) == 1
    assert mine[0]['ops'] == [('w', 0x8c000010, b'\x01\x00')]
    assert ad.writes == [(0x8c000010, b'\x01\x00')]
    assert 'addr 16 = 1' in mine[0]['lines']
    assert call()['cheats'][0]['engine'] == 'gbox'
    assert not call('enable', 0)['changed'] and len(threads) == 1
    old = mine[0]['on']
    call('disable', 0)
    call('enable', 0)
    assert not old.is_set() and mine[0]['on'] is not old and len(threads) == 2


def test_late_start_from_previous_enable_cannot_borrow_new_event(session):
    ad, call, threads, mine, _sid = session([row()])
    call('enable', 0)
    old = threads[0]
    call('disable', 0)
    call('enable', 0)
    def caught_write(address, data):
        ad.writes.append((address, data))
        mine[0]['on'].clear()  # keeps the regression bounded if the old loop writes
    ad.write_memory = caught_write
    before = list(ad.writes)
    old.target(*old.args)
    assert ad.writes == before and mine[0]['on'].is_set()


def test_conditional_transfer_across_disabled_and_core_rows_and_alias_disable(session):
    ad, call, threads, mine, _sid = session([
        row(0, 1, 4), row(2), {'handler': '0', 'code': '01000020 00000001', 'enable': False},
        row(16), row(18)])
    call('enable', 3)
    call('enable', 4)
    assert not ad.commands
    assert call('enable', 0)['engine'] == 'emulator'
    assert ad.commands == [(0, True), (3, True), (4, True)]
    assert not any(c['on'].is_set() for c in mine)
    ad.writes.clear()
    ad.frame()
    assert ad.writes == [(0x8c000012, b'\x01\x00')]
    listed = call()['cheats']
    assert all(listed[i]['engine'] == 'emulator' for i in (0, 3, 4, 5, 6))
    assert listed[5]['enabled']
    result = call('disable', 5)   # existing db3 alias keeps its index after migration
    assert result['database_index'] == 3 and result['index'] == 5
    assert ad.commands[-1] == (3, False) and not call()['cheats'][5]['enabled']
    call('disable', 0)
    call('enable', 3)
    assert len(threads) == 2 and ad.commands[-1] == (3, True)  # sticky emulator ownership


def test_enabled_conditional_chain_is_not_flattened(session):
    ad, call, _threads, _mine, _sid = session([row(0, 1, 4), row(2), row(4, 2, 4), row(16)])
    call('enable', 3)
    call('enable', 0)
    call('enable', 2)
    ad.writes.clear()
    ad.frame()                        # first false => skip second condition, then write
    assert ad.writes == [(0x8c000010, b'\x01\x00')]
    ad.writes.clear()
    ad.memory[0x8c000000] = 1         # first true, second false => skip write
    ad.frame()
    assert not ad.writes


@pytest.mark.parametrize('unsupported', [row(20, kind=2), row(20, repeat_count='2'),
                                        row(20, memory_search_size='2'), row(20, rumble_type='1')])
def test_unsupported_native_transfers_whole_table(session, unsupported):
    ad, call, threads, mine, _sid = session([row(16), unsupported])
    call('enable', 0)
    result = call('enable', 1)
    assert result['engine'] == 'emulator' and ad.commands == [(0, True), (1, True)]
    assert len(threads) == 1 and not mine[0]['on'].is_set()


def test_startup_enabled_native_table_stays_emulator_owned(session):
    ad, call, threads, mine, _sid = session([row(0, 1, 4, enable=True), row(16)])
    assert call('enable', 1)['engine'] == 'emulator'
    assert ad.commands == [(1, True)] and not threads and not mine
    assert not call('enable', 1)['changed'] and ad.commands == [(1, True)]


def test_custom_and_core_code_indices_and_writers_survive_transfer(session):
    ad, call, _threads, mine, _sid = session([row(0, 1, 4), row(16),
                                            {'handler': '0', 'code': '01000030 00000002', 'enable': False}])
    custom = call('add', codes=['01000020 00000003'], desc='custom')['index']
    call('enable', 2)                 # existing non-native coded DB path remains gBox
    call('enable', 1)
    call('enable', 0)
    assert custom == 3 and len(mine) == 3
    assert mine[0]['on'].is_set() and mine[1]['on'].is_set() and not mine[2]['on'].is_set()
    before = list(ad.commands)
    call('disable', custom)
    assert not mine[0]['on'].is_set() and ad.commands == before
    call('enable', custom)
    assert mine[0]['on'].is_set() and ad.commands == before


def test_overlapping_native_constants_keep_emulator_order(session):
    ad, call, _threads, mine, _sid = session([row(16, 1), row(17, 2)])
    call('enable', 0)
    assert call('enable', 1)['engine'] == 'emulator'
    assert ad.commands == [(0, True), (1, True)] and not mine[0]['on'].is_set()


def test_partial_transfer_failure_never_resumes_native_freezes(session):
    ad, call, _threads, mine, _sid = session([row(0, 1, 4), row(16)])
    call('enable', 1)
    ad.fail_index = 1
    with pytest.raises(RuntimeError, match='command failure'):
        call('enable', 0)
    assert not mine[0]['on'].is_set()
    assert ad.commands == [(0, True)] and ad.cheats[0]['enable'] and not ad.cheats[1]['enable']
    ad.fail_index = None
    assert call('enable', 1)['engine'] == 'emulator' and ad.commands[-1] == (1, True)


def test_waiting_freeze_iteration_rechecks_event_under_transfer_lock(session):
    ad, call, _threads, mine, sid = session([row(0, 1, 4), row(16)])
    call('enable', 1)
    runtime = ad._gbox_native_cheats
    ad.writes.clear()
    with runtime.lock:
        writer = REAL_THREAD(target=T._gcheat_loop, args=(sid, mine[0]))
        writer.start()               # iteration sees on, then waits for runtime lock
        call('enable', 0)
    writer.join(3)
    assert not writer.is_alive() and not ad.writes
    assert ad.commands == [(0, True), (1, True)]


def test_transfer_waits_for_inflight_write_before_first_emulator_command(session):
    ad, call, _threads, mine, sid = session([row(0, 1, 4), row(16)])
    call('enable', 1)
    ad.writes.clear()
    entered, release, migrated = threading.Event(), threading.Event(), threading.Event()
    original = ad.write_memory
    def blocked_write(address, data):
        entered.set()
        assert release.wait(3)
        original(address, data)
    ad.write_memory = blocked_write
    writer = REAL_THREAD(target=T._gcheat_loop, args=(sid, mine[0]))
    writer.start()
    assert entered.wait(3)
    def transfer():
        call('enable', 0)
        migrated.set()
    migrator = REAL_THREAD(target=transfer)
    migrator.start()
    assert not migrated.wait(0.05) and not ad.commands
    release.set()
    migrator.join(3); writer.join(3)
    assert migrated.is_set() and not writer.is_alive()
    assert ad.writes == [(0x8c000010, b'\x01\x00')]
    assert ad.commands == [(0, True), (1, True)]



def test_replaced_table_retires_old_native_alias_without_touching_new_indices(session):
    ad, call, threads, mine, _sid = session([row(0, 1, 4), row(16)])
    custom = call('add', codes=['01000020 00000003'], desc='custom')['index']
    call('enable', 1)
    old, old_thread = ad._gbox_native_cheats, threads[-1]
    alias = len(ad.cheats) + 1
    ad.cheats = [row(32), row(34)]
    ad.actual = [False, False]
    listed = call()['cheats']
    assert old.retired and not old.enabled(1) and not mine[1]['on'].is_set()
    assert listed[alias]['engine'] == 'retired' and not listed[alias]['enabled']
    assert mine[0]['on'].is_set() and not ad.commands
    # A delayed old thread must not write into either the old or new table.
    before = list(ad.writes)
    old_thread.target(*old_thread.args)
    assert ad.writes == before
    with pytest.raises(ValueError, match='table was replaced'):
        call('enable', alias)
    with pytest.raises(ValueError, match='table was replaced'):
        call('disable', alias)
    assert not ad.commands
    call('disable', custom)
    assert not mine[0]['on'].is_set()
    assert call('enable', 0)['engine'] == 'gbox'
    assert mine[-1]['ops'] == [('w', 0x8c000020, b'\x01\x00')]


def test_replacement_waits_for_old_native_inflight_write(session):
    ad, call, _threads, mine, sid = session([row(16)])
    call('enable', 0)
    old = ad._gbox_native_cheats
    ad.writes.clear()
    entered, release, retired = threading.Event(), threading.Event(), threading.Event()
    original = ad.write_memory
    def blocked_write(address, data):
        entered.set()
        assert release.wait(3)
        original(address, data)
    ad.write_memory = blocked_write
    writer = REAL_THREAD(target=T._gcheat_loop, args=(sid, mine[0], mine[0]['on']))
    writer.start()
    assert entered.wait(3)
    ad.cheats = [row(32)]
    ad.actual = [False]
    def replace():
        call()
        retired.set()
    replacement = REAL_THREAD(target=replace)
    replacement.start()
    assert not retired.wait(0.05)
    release.set()
    replacement.join(3); writer.join(3)
    assert retired.is_set() and old.retired and not writer.is_alive()
    assert ad.writes == [(0x8c000010, b'\x01\x00')] and not ad.commands


@pytest.mark.parametrize('replacement', [[], [{'handler': '0', 'code': '01000020 00000003', 'enable': False}]])
def test_replacement_without_any_native_rows_still_retires_old_writer(session, replacement):
    ad, call, threads, mine, _sid = session([row(16)])
    call('enable', 0)
    old = ad._gbox_native_cheats
    ad.cheats = copy.deepcopy(replacement)
    ad.actual = [False] * len(replacement)
    listed = call()['cheats']
    assert old.retired and not mine[0]['on'].is_set()
    assert listed[-1]['engine'] == 'retired' and not listed[-1]['enabled']
    with pytest.raises(ValueError, match='table was replaced'):
        call('enable', listed[-1]['index'])
    assert not ad.commands


def test_initial_probe_records_original_bytes_before_write_and_readback(session):
    ad, call, threads, mine, _sid = session([row(16)])
    ad.memory.update({0x8c000010: 0xa5, 0x8c000011: 0x5a})
    result = call('enable', 0)
    assert result['enabled'] and len(threads) == 1 and mine[0]['on'].is_set()
    assert [event[0] for event in ad.events] == ['read', 'artifact', 'write', 'read']
    assert ad.artifacts[0][0] == 'cheat_before.json'
    assert json.loads(ad.artifacts[0][1]) == [{'address': '0x8c000010', 'bytes': 'a55a'}]
    count = len(ad.events)
    call('enable', 0)
    assert len(ad.events) == count and len(threads) == 1


@pytest.mark.parametrize('failure', ['read', 'short_read', 'write', 'mismatch'])
def test_failed_first_probe_leaves_no_enabled_state_alias_or_thread(session, failure):
    ad, call, threads, mine, _sid = session([row(16)])
    ad.memory.update({0x8c000010: 0xa5, 0x8c000011: 0x5a})
    original_write = ad.write_memory
    # The first-read failures must stop before recording a misleading rollback
    # or performing any write. Later failures retain the saved original bytes.
    if failure == 'read':
        def failed_read(*args):
            raise RuntimeError('read unavailable')
        ad.read_memory = failed_read
    elif failure == 'short_read':
        ad.read_memory = lambda *args: b'\xa5'
    elif failure == 'write':
        def failed_write(address, data):
            ad.events.append(('write_attempt', address, data))
            raise RuntimeError('write unavailable')
        ad.write_memory = failed_write
    else:
        def wrong_write(address, data):
            original_write(address, data)
            ad.memory[address] ^= 1
        ad.write_memory = wrong_write
    with pytest.raises(RuntimeError):
        call('enable', 0)
    assert not ad.cheats[0]['enable'] and not ad._gbox_native_cheats.enabled(0)
    assert not mine and not threads and not ad.commands
    if failure in ('read', 'short_read'):
        assert not ad.artifacts and not ad.writes
    else:
        assert json.loads(ad.artifacts[0][1]) == [{'address': '0x8c000010', 'bytes': 'a55a'}]
        kinds = [event[0] for event in ad.events]
        assert kinds.index('artifact') < kinds.index('write_attempt' if failure == 'write' else 'write')


def test_failed_reenable_does_not_reactivate_existing_alias(session):
    ad, call, threads, mine, _sid = session([row(16)])
    call('enable', 0)
    call('disable', 0)
    old = mine[0]['on']
    def failed_read(*args):
        raise RuntimeError('memory connection lost')
    ad.read_memory = failed_read
    with pytest.raises(RuntimeError, match='connection lost'):
        call('enable', 1)  # alias follows the same verified enable path
    assert mine[0]['on'] is old and not old.is_set() and len(threads) == 1
    assert not ad.cheats[0]['enable'] and not ad._gbox_native_cheats.enabled(0)
