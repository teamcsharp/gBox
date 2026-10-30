import hashlib
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox.mercs import interventions as I
from gbox.mercs.titles import re5_switch_native as N, re6_switch_native as N6


def controller():
    ctl = N.Controller.__new__(N.Controller)
    ctl.base = 0x100000000
    ctl.player, ctl.sp, ctl.heap = 0x200000000, 0x210000000, 0x220000000
    ctl.original = ctl.base + 0x1C290C8  # Jill, not the Chris bootstrap prototype
    ctl.generation = 0x100000002
    ctl.lock = threading.RLock()
    ctl.failed = False
    ctl.ad = SimpleNamespace(paused=False)
    ctl.mem, ctl.writes = {}, []
    def put(at, data):
        ctl.mem.update({at+i: b for i, b in enumerate(data)})
    def read(at, n):
        return bytes(ctl.mem.get(at+i, 0) for i in range(n))
    def write(at, data):
        ctl.check()
        ctl.writes.append((at, data))
        put(at, data)
    ctl.rd, ctl.write, ctl.put = read, write, put
    ctl.check = lambda: None
    ctl.check_build = lambda: None
    put(ctl.player, struct.pack('<Q', ctl.original))
    put(ctl.base + N.R.S_PLAYER, struct.pack('<Q', ctl.sp))
    put(ctl.sp + N.R.P_FIRST, struct.pack('<Q', ctl.player))
    put(ctl.player + 0x1A00, struct.pack('<Q', ctl.generation))
    put(ctl.player + N.R.P_HP, struct.pack('<h', 1000))
    put(ctl.original, N.table_bytes(ctl.base, ctl.original))
    put(ctl.heap + 0x6A0, b'GBXNC502')
    put(ctl.heap + 0x60, struct.pack('<Q', ctl.base + N.DISPATCH))
    put(ctl.heap + 0x680, struct.pack('<4Q', ctl.original, ctl.base + N.UPDATE, ctl.player, ctl.generation))
    put(ctl.heap + 0x6A8, struct.pack('<I', 3))
    for off, name, _, _ in N.CODE:
        put(ctl.base + off, N.IMAGES[name])
    return ctl


def test_assets_and_all_ten_character_method_tables_are_pinned():
    assert len(N.PLAYER_TABLES) == 10
    assert len(N.BASE_ENTRIES) == 149
    ends = []
    for off, name, size, digest in N.CODE:
        assert 0x118E5B0 <= off < off + size <= 0x118F000
        data = N.IMAGES[name]
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
        ends.append((off, off + size))
    assert all(a[1] <= b[0] for a, b in zip(ends, ends[1:]))
    for vt in N.PLAYER_TABLES:
        entries = struct.unpack('<149Q', N.table_bytes(0x100000000, 0x100000000 + vt))
        assert entries[12] == 0x100000000 + N.UPDATE
        assert all(0 < e - 0x100000000 < 0x118E5B0 for e in entries)
    with pytest.raises(N.Unavailable, match='player class'):
        N.table_bytes(0x100000000, 0x100000001)


def test_player_class_change_reuses_heap_without_rewriting_bootstrap():
    ctl = controller()
    ctl.stopped = lambda _: pytest.fail('Subsequent clicks must not stop the game')
    ctl.attach()
    assert ctl.q(ctl.player) == ctl.heap
    assert ctl.q(ctl.heap + 0x680) == ctl.original
    assert ctl.q(ctl.heap + 0x698) == 0x100000002
    entries = bytearray(N.table_bytes(ctl.base, ctl.original))
    struct.pack_into('<Q', entries, 0x60, ctl.base + N.DISPATCH)
    assert ctl.rd(ctl.heap, len(entries)) == entries
    assert all(at in (ctl.player, ctl.heap, ctl.heap + 0x680) for at, _ in ctl.writes)


def test_foreign_player_vtable_is_refused_before_publication():
    ctl = controller()
    ctl.put(ctl.original + 24, struct.pack('<Q', 123))
    with pytest.raises(N.Unavailable, match='modified'):
        ctl.attach()
    assert not ctl.writes


@pytest.mark.parametrize('state', [1, 2])
def test_pending_or_executing_mailbox_cannot_be_rebound(state):
    ctl = controller()
    ctl.put(ctl.heap + 0x6A8, struct.pack('<I', state))
    with pytest.raises(N.Unavailable, match='incomplete'):
        ctl.attach()
    assert not ctl.writes


@pytest.mark.parametrize('change', ['class', 'generation', 'owner'])
def test_projectile_allocation_change_is_not_an_explosion(change):
    ctl = controller()
    unit, born = 0x230000000, 0x100000003
    ctl.put(unit, struct.pack('<Q', ctl.base + 0x1C5EF58))
    ctl.put(unit + 0x1A00, struct.pack('<Q', born))
    ctl.put(unit + 0x1A10, struct.pack('<Q', ctl.player))
    ctl.projectile(unit, born)
    at = {'class': unit, 'generation': unit+0x1A00, 'owner': unit+0x1A10}[change]
    ctl.put(at, struct.pack('<Q', 3 if change == 'generation' else 0))
    with pytest.raises(N.AllocationLost):
        ctl.projectile(unit, born)


@pytest.mark.parametrize('hp,paused,phase', [(1, False, 1), (0, False, 1), (1000, True, 1), (1000, False, 3)])
def test_readiness_rejects_dying_paused_or_finished_round(monkeypatch, hp, paused, phase):
    ctl = controller()
    ctl.ad.paused = paused
    ctl.put(ctl.player + N.R.P_HP, struct.pack('<h', hp))
    gs = 0x240000000
    monkeypatch.setattr(N.R, 'game_sys', lambda *_: gs)
    ctl.put(gs + N.R.GS_PHASE, struct.pack('<I', phase))
    with pytest.raises(N.Unavailable):
        ctl.ready()
    assert not ctl.writes


@pytest.mark.parametrize('exploded', [False, True])
def test_flash_requires_native_effect_flag_and_always_restores_class_table(exploded):
    ctl = controller()
    ctl.ready = lambda: (ctl.player, ctl.generation)
    unit, born = 0x230000000, 9001
    ctl.put(unit, struct.pack('<Q', ctl.base + 0x1C5EF58))
    ctl.put(unit + 0x1A00, struct.pack('<Q', born))
    ctl.put(unit + 0x1A10, struct.pack('<Q', ctl.player))
    ctl.put(unit + 0x1B28, struct.pack('<I', 29))
    ctl.put(unit + 0x1B88, b'\1')
    ctl.put(unit + 0x28A0, bytes([exploded]))
    calls = []
    def call(off, *args):
        calls.append((off, args))
        return unit if off == 0x118E820 else 1
    ctl.call = call
    if exploded:
        result = ctl.flash()
        assert result['verified'] and result['state'] == 'confirmed'
    else:
        with pytest.raises(N.Uncertain, match='explosion flag'):
            ctl.flash()
        assert ctl.failed and not ctl.recoverable
    assert calls == [(0x118E820, (ctl.player, ctl.generation)),
                     (0x118E9D0, (unit, born, ctl.player, ctl.generation))]
    assert ctl.q(ctl.player) == ctl.original
    # The only player write is the temporary virtual dispatch pointer.
    assert all(not ctl.player < at < ctl.player + 0x5000 for at, _ in ctl.writes)


def test_shared_controller_detects_re5_and_reuses_the_mods_instance(monkeypatch):
    ad = SimpleNamespace()
    def unsupported(_): raise N.Unavailable('unsupported RE6 executable')
    monkeypatch.setattr(N6, 'Controller', unsupported)
    ctl = SimpleNamespace()
    created = []
    monkeypatch.setattr(N, 'Controller', lambda a: (created.append(a), ctl)[1])
    assert I.native_controller(ad) is ctl
    assert I.native_controller(ad) is ctl
    assert ad._re5_native_flash is ctl and created == [ad]


def test_mod_flash_routes_to_native_without_inventory_or_mod_lock(monkeypatch):
    from gbox.mercs.titles import re5_switch_mods as M
    ad = object()
    monkeypatch.setattr(N, 'flash_now', lambda a: {'verified': a is ad})
    monkeypatch.setattr(M, 'RE5Switch', lambda _: pytest.fail('Flash must not open an inventory editor'))
    assert M.tool_run(ad, 'flash_now') == {'verified': True}


@pytest.mark.parametrize('failure', [False, True])
def test_prepare_installs_once_without_a_projectile_and_restores_player(failure):
    ctl = controller()
    heap = ctl.heap
    ctl.heap = None
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.call = lambda *_: pytest.fail('Preparation must not create or detonate any item')
    def attach():
        ctl.write(ctl.player, struct.pack('<Q', ctl.base + N.TEMP))
        if failure:
            raise N.Uncertain('bootstrap timeout')
        ctl.heap = heap
        ctl.write(ctl.player, struct.pack('<Q', heap))
    ctl.attach = attach
    if failure:
        with pytest.raises(N.Uncertain, match='bootstrap timeout'):
            ctl.prepare()
        assert ctl.failed and not ctl.recoverable
    else:
        ctl.prepare()
        ctl.attach = lambda: pytest.fail('Preparation must not repeat an installed bootstrap')
        ctl.prepare()
    assert ctl.q(ctl.player) == ctl.original
