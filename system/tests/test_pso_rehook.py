"""PSO reconnect repairs only its memory connection and verified native dispatcher."""
import struct
import time
from types import SimpleNamespace

import pytest

from gbox import adapters, debug, pso_controls as C, pso_gc_live as G, pso_mods_tool as DC
from gbox import pso_rehook as R
from test_pso_gc_live import RAM
from test_pso_mods import FakeDC


GC_GAME = {'platform': 'gamecube', 'title': 'Phantasy Star Online Episode I & II Plus'}
DC_GAME = {'platform': 'dreamcast', 'title': 'Phantasy Star Online Ver. 2 (USA)'}


def context():
    return SimpleNamespace(pso_expires=time.time()+10)


def forbid_lifecycle(ad):
    def forbidden(*args, **kwargs):
        raise AssertionError('Reconnect must not change the operator game lifecycle or save state')
    for name in ('launch_game', 'stop_game', 'reset', 'pause', 'resume', 'save_state', 'load_state',
                 'checkpoint_save', 'checkpoint_load', 'send_input'):
        setattr(ad, name, forbidden)
    return ad


def gc_memory():
    ram = forbid_lifecycle(RAM())
    ram.dbg.info = lambda: {'halted': False}
    return ram


@pytest.fixture
def defaults(monkeypatch):
    calls = []
    prefs = {'equip_any': True, 'always_hit': True}
    monkeypatch.setattr(C, 'preferences', lambda ctx: prefs)
    def apply(*args):
        calls.append(args)
        return {'state': 'applied'}
    monkeypatch.setattr(C, 'apply_defaults', apply, raising=False)
    return calls, prefs


def test_gc_reconnect_installs_dispatcher_and_applies_saved_defaults_once(defaults):
    ram = gc_memory()
    ctx = context()
    result = R.recover('operator', ram, GC_GAME, ctx)
    assert result['ready'] and result['verified'] and result['supported']
    assert result['session_id'] == 'operator'
    assert result['capabilities']['version'] == 'gc'
    assert [s['stage'] for s in result['steps']] == ['memory', 'revision', 'hook', 'defaults']
    assert all(s['state'] == 'ok' for s in result['steps'])
    assert defaults[0] == [('operator', ram, GC_GAME, ctx, defaults[1])]
    assert G.GC(ram).u32(G.VT_UPDATE) == G.CAVE
    assert ram.read_memory(G.CAVE, len(G.CODE)) == G.CODE
    first = len(ram.writes)
    assert R.recover('operator', ram, GC_GAME, context())['ready']
    assert len(ram.writes) == first


@pytest.mark.parametrize('damage', ['revision', 'executable', 'online', 'player'])
def test_gc_unverified_or_uninitialized_game_is_never_written(defaults, damage):
    ram = gc_memory()
    if damage == 'revision': ram.put(0x80000007, b'\x01')
    if damage == 'executable': ram.put(G.F_CREATE, b'xxxx')
    if damage == 'online': ram.word(G.PHASE, 15)
    if damage == 'player': ram.word(G.PLAYER, 0)
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and not result['verified'] and not result['supported']
    assert result['message'] and result['steps'][-1]['state'] == 'blocked'
    assert ram.writes == [] and defaults[0] == []


@pytest.mark.parametrize('slot', [0, G.QMAX-1])
@pytest.mark.parametrize('installed', [False, True])
def test_gc_pending_first_or_last_command_is_preserved_before_rehook(defaults, slot, installed):
    ram = gc_memory()
    if installed: G.GC(ram).hook()
    ram.word(G.QUEUE+slot*G.QSZ, G.F_CREATE)
    before = bytes(ram.data)
    ram.writes.clear()
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and result['supported']
    assert 'pending' in result['message'] and 'not cleared or replayed' in result['message']
    assert bytes(ram.data) == before and ram.writes == [] and defaults[0] == []


@pytest.mark.parametrize('pause', ['native', 'debugger'])
def test_paused_game_is_not_resumed_or_written(defaults, pause):
    ram = gc_memory()
    if pause == 'native': ram.paused_tids = [123]
    else: ram.dbg.info = lambda: {'halted': True}
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and 'paused' in result['message']
    assert ram.writes == [] and defaults[0] == []


def test_expired_reconnect_never_installs_dispatcher(defaults):
    ram = gc_memory()
    result = R.recover('operator', ram, GC_GAME, SimpleNamespace(pso_expires=0))
    assert not result['ready'] and 'expired' in result['message']
    assert ram.writes == [] and defaults[0] == []


def test_unrecognized_dispatcher_is_preserved(defaults):
    ram = gc_memory()
    G.GC(ram).hook()
    ram.put(G.CAVE, b'other dispatcher')
    before = bytes(ram.data)
    ram.writes.clear()
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and 'dispatcher' in result['message']
    assert bytes(ram.data) == before and ram.writes == [] and defaults[0] == []


def test_defaults_failure_and_final_hook_readback_cannot_claim_success(monkeypatch, defaults):
    ram = gc_memory()
    def fail(*args): raise RuntimeError('Saved mod defaults were unavailable')
    monkeypatch.setattr(C, 'apply_defaults', fail)
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and not result['verified']
    assert 'defaults were unavailable' in result['message']
    def changed_hook(*args):
        ram.word(G.VT_UPDATE, G.ORIGINAL_UPDATE)
        return {'state': 'applied'}
    monkeypatch.setattr(C, 'apply_defaults', changed_hook)
    result = R.recover('operator', ram, GC_GAME, context())
    assert not result['ready'] and not result['verified']
    assert 'read-back verification' in result['message']


def test_unsupported_defaults_do_not_report_ready_even_with_valid_hook(monkeypatch, defaults):
    ram = gc_memory()
    monkeypatch.setattr(C, 'apply_defaults', lambda *args: {
        'state': 'unsupported', 'reason': 'The executable changed while applying defaults'})
    result = R.recover('operator', ram, GC_GAME, context())
    assert G.GC(ram).u32(G.VT_UPDATE) == G.CAVE
    assert ram.read_memory(G.CAVE, len(G.CODE)) == G.CODE
    assert result['supported'] and not result['ready'] and not result['verified']
    assert result['message'] == 'The executable changed while applying defaults'
    assert result['steps'][-1]['state'] == 'blocked'


def test_dc_reconnect_uses_native_dc_dispatcher_and_defaults(defaults):
    ad = forbid_lifecycle(FakeDC())
    result = R.recover('dc-operator', ad, DC_GAME, context())
    assert result['ready'] and result['capabilities']['version'] == 'dcv2'
    assert DC.PSO(ad.read_memory, ad.write_memory).u32(DC.VT_UPDATE) == DC.CAVE
    assert ad.read_memory(DC.CAVE, len(DC.stub_code())) == DC.stub_code()
    assert len(defaults[0]) == 1


def test_dc_pending_count_is_not_erased_by_stub_install(defaults):
    ad = forbid_lifecycle(FakeDC())
    ad.put(DC.QUEUE, struct.pack('<I', DC.QMAX))
    before = dict(ad.m)
    result = R.recover('dc-operator', ad, DC_GAME, context())
    assert not result['ready'] and 'pending' in result['message']
    assert ad.m == before and defaults[0] == []


def test_dc_full_patch_fingerprint_blocks_writes(defaults):
    ad = forbid_lifecycle(FakeDC())
    ad.put(DC.PATCHES['equip_any'][0], b'xx')
    before = dict(ad.m)
    result = R.recover('dc-operator', ad, DC_GAME, context())
    assert not result['supported'] and not result['ready']
    assert ad.m == before and defaults[0] == []


def memory_handle(ram, events, label, *, wrong_revision=False, broken=False):
    def read(address, length):
        events.append((label, 'read', address, length))
        if broken: raise ConnectionError('stale memory mapping')
        if wrong_revision and address == 0x80000000: return bytes(length)
        return ram.read_memory(address, length)
    def write(address, data):
        ram.write_memory(address, data)
        return {'written': len(data)}
    return SimpleNamespace(read=read, write=write, info=lambda: {'halted': False},
                           close=lambda: events.append((label, 'close')))


def dolphin(kind, old):
    ad = object.__new__(kind)
    ad.proc = SimpleNamespace(pid=2345, poll=lambda: None)
    ad.platform, ad.port, ad.dbg = 'gamecube', 54321, old
    return forbid_lifecycle(ad)


def test_windows_reopens_same_live_pid_and_swaps_only_after_signature_probe(monkeypatch, defaults):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', broken=True)
    new = memory_handle(ram, events, 'new')
    ad = dolphin(adapters.DolphinWinAdapter, old)
    def opened(pid):
        events.append(('open', pid))
        return new
    def close_old():
        assert ad.dbg is new
        events.append(('old', 'close'))
    old.close = close_old
    monkeypatch.setattr(debug, 'DolphinProcMem', opened)
    monkeypatch.setattr(debug, 'GdbDebugger', lambda *a, **k: pytest.fail('Windows must not attach GDB'))
    result = R.recover('operator', ad, GC_GAME, context())
    assert result['ready'] and ad.proc.pid == 2345 and ad.dbg is new, result
    assert events[:3] == [('open', 2345), ('new', 'read', 0x80000000, 8), ('old', 'close')]
    assert ('new', 'close') not in events


def test_windows_rejected_mapping_closes_candidate_and_preserves_old_handle(monkeypatch, defaults):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old')
    new = memory_handle(ram, events, 'new', wrong_revision=True)
    ad = dolphin(adapters.DolphinWinAdapter, old)
    monkeypatch.setattr(debug, 'DolphinProcMem', lambda pid: new)
    result = R.recover('operator', ad, GC_GAME, context())
    assert not result['ready'] and ad.dbg is old and ad.proc.pid == 2345
    assert events == [('new', 'read', 0x80000000, 8), ('new', 'close')]
    assert ram.writes == [] and defaults[0] == []


def test_exited_process_is_not_replaced_or_launched(monkeypatch, defaults):
    ram, events = gc_memory(), []
    ad = dolphin(adapters.DolphinWinAdapter, memory_handle(ram, events, 'old'))
    ad.proc.poll = lambda: 1
    monkeypatch.setattr(debug, 'DolphinProcMem', lambda pid: pytest.fail('Exited process must not be opened'))
    result = R.recover('operator', ad, GC_GAME, context())
    assert not result['ready'] and 'exited' in result['message']
    assert ram.writes == [] and events == [] and defaults[0] == []


def test_linux_reconnects_only_broken_debugger_with_short_budget(monkeypatch, defaults):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', broken=True)
    new = memory_handle(ram, events, 'new')
    ad = dolphin(adapters.DolphinAdapter, old)
    def connect(*args, **kwargs):
        events.append(('connect', args, kwargs))
        return new
    monkeypatch.setattr(debug, 'GdbDebugger', connect)
    result = R.recover('operator', ad, GC_GAME, context())
    assert result['ready'] and ad.dbg is new, result
    assert ('old', 'close') in events
    assert ('connect', ('127.0.0.1', 54321, 'ppc'), {'connect_timeout': .5}) in events
    events.clear()
    assert R.recover('operator', ad, GC_GAME, context())['ready']
    assert not any(e[0] == 'connect' for e in events)


@pytest.mark.parametrize('pause_source', ['running', 'info'])
def test_linux_paused_broken_debugger_is_not_read_closed_or_reconnected(monkeypatch, defaults, pause_source):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', broken=True)
    old.running = pause_source != 'running'
    old.info = lambda: {'halted': pause_source == 'info'}
    ad = dolphin(adapters.DolphinAdapter, old)
    monkeypatch.setattr(debug, 'GdbDebugger', lambda *a, **k: pytest.fail('Paused debugger must not reconnect'))
    result = R.recover('operator', ad, GC_GAME, context())
    assert not result['ready'] and not result['verified'] and 'paused' in result['message']
    assert ad.dbg is old and events == [] and ram.writes == [] and defaults[0] == []


def test_linux_wrong_rom_header_does_not_close_healthy_debugger_or_reconnect(monkeypatch, defaults):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', wrong_revision=True)
    ad = dolphin(adapters.DolphinAdapter, old)
    monkeypatch.setattr(debug, 'GdbDebugger', lambda *a, **k: pytest.fail('Revision mismatch is not a failed transport'))
    result = R.recover('operator', ad, GC_GAME, context())
    assert not result['ready'] and not result['verified']
    assert 'verified PSO revision' in result['message']
    assert ad.dbg is old and events == [('old', 'read', 0x80000000, 8)]
    assert ram.writes == [] and defaults[0] == []


@pytest.mark.parametrize('error_type', [OSError, debug.Unavailable])
def test_linux_known_running_debugger_reconnects_when_info_socket_is_closed(monkeypatch, defaults, error_type):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', broken=True)
    old.running = True
    def closed_info():
        events.append(('old', 'info'))
        raise error_type('debug stub closed the connection')
    old.info = closed_info
    new = memory_handle(ram, events, 'new')
    ad = dolphin(adapters.DolphinAdapter, old)
    def connect(*args, **kwargs):
        events.append(('connect', args, kwargs))
        return new
    monkeypatch.setattr(debug, 'GdbDebugger', connect)
    result = R.recover('operator', ad, GC_GAME, context())
    assert result['ready'] and result['verified'] and ad.dbg is new, result
    assert events[:4] == [('old', 'info'), ('old', 'read', 0x80000000, 8), ('old', 'close'),
                          ('connect', ('127.0.0.1', 54321, 'ppc'), {'connect_timeout': .5})]
    assert len(defaults[0]) == 1


def test_linux_unknown_run_state_keeps_old_debugger_if_info_socket_is_closed(monkeypatch, defaults):
    ram, events = gc_memory(), []
    old = memory_handle(ram, events, 'old', broken=True)
    def closed_info():
        events.append(('old', 'info'))
        raise debug.Unavailable('debug stub closed the connection')
    old.info = closed_info
    ad = dolphin(adapters.DolphinAdapter, old)
    monkeypatch.setattr(debug, 'GdbDebugger', lambda *a, **k: pytest.fail('Unknown run state must not reconnect'))
    result = R.recover('operator', ad, GC_GAME, context())
    assert not result['ready'] and not result['verified'] and ad.dbg is old
    assert result['message'] == 'debug stub closed the connection'
    assert events == [('old', 'info')] and ram.writes == [] and defaults[0] == []
