import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re4_switch_mines as M
from gbox.mercs.native.re4_82c2a04a import code as C

BASE, PLAYER, ARRAY, STACK = 0x10000000, 0x20000000, 0x30000000, 0x40000000


def memory():
    mem = {}
    def put(at, data): mem.update({at + i: b for i, b in enumerate(data)})
    def rd(at, n): return bytes(mem.get(at+i, 0) for i in range(n))
    put(BASE + M.POOL + 8, struct.pack('<QII', ARRAY, 4, M.STRIDE))
    for i in range(4):
        at = ARRAY + i * M.STRIDE
        put(at, struct.pack('<QI', BASE + M.VTABLE, 0x2000061))
        put(at + 0x110, struct.pack('<I', 10 + i))
        put(at + 0x114, bytes([1, 4, 1, 0, 0x5F, i]))
        put(at + 0xA4, struct.pack('<3f', 10000 + i, 0, 10000))
    return SimpleNamespace(base=BASE, rd=rd), put


def test_only_real_mine_darts_are_read_not_the_two_rocket_subtypes():
    ctl, put = memory()
    rows = M.read_mines(ctl)
    assert [r['subtype'] for r in rows] == [0, 1]
    put(ARRAY + 0x115, b'\6')  # already exploding, not another detonation
    assert len(M.read_mines(ctl)) == 1
    put(ARRAY + M.STRIDE + 8, struct.pack('<I', 0x201))  # released allocation
    assert M.read_mines(ctl) == []


def test_invalid_pool_layout_is_refused_without_scanning_arbitrary_memory():
    ctl, put = memory()
    put(BASE + M.POOL + 0x14, struct.pack('<I', 0x999))
    with pytest.raises(ValueError, match='pool layout'):
        M.read_mines(ctl)


def test_three_second_fuses_track_new_native_generations_and_never_replay():
    f = M.Fuses()
    raw = [{'ptr': ARRAY, 'generation': 1}]
    rows = f.observe('player-1', raw, 10)
    assert not f.claim(rows, 12.99)
    assert f.claim(f.observe('player-1', raw, 13), 13) == rows
    assert not f.claim(rows, 13.1, manual=True)
    # Reuse of the address must start a new fuse, not inherit an old deadline.
    rows = f.observe('player-1', [{'ptr': ARRAY, 'generation': 2}], 14)
    assert not f.claim(rows, 16.99)
    assert f.claim(rows, 17)
    # A player change also discards pending fuse state.
    rows = f.observe('player-2', raw, 20)
    assert rows[0]['fuse_due_at'] == 23
    assert f.claim(rows, 20, manual=True)
    assert not f.claim(rows, 23)


def emulate_wrapper(mutate=None, wall=False):
    U = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC
    u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
    u.mem_map(BASE, 0x1400000)
    for at in (PLAYER, ARRAY, STACK): u.mem_map(at, 0x10000)
    def put(at, fmt, *values): u.mem_write(at, struct.pack(fmt, *values))
    game = BASE + 0x1274338
    u.mem_write(BASE + C.MINE_DETONATE_AT, C.MINE_DETONATE[4])
    put(BASE + 0xB1AE08, '<Q', game)
    put(BASE + 0x11310F0, '<Q', PLAYER)
    put(PLAYER + 0x110, '<I', 5)
    put(game + 0x78, '<I', 1 << 30)
    put(game + 0x5028, '<H', 1000)
    put(BASE + M.POOL + 8, '<QII', ARRAY, 4, M.STRIDE)
    put(ARRAY, '<QI', BASE + M.VTABLE, 0x2000061)
    put(ARRAY + 0x110, '<I', 7)
    u.mem_write(ARRAY + 0x114, bytes([1, 4, 1, 0, 0x5F, 1]))
    put(ARRAY + 0x540, '<B', int(wall))
    put(ARRAY + 0xA4, '<3f', 8000., 0., 0.)
    u.reg_write(UC_ARM64_REG_X0, ARRAY)
    u.reg_write(UC_ARM64_REG_X1, 7)
    u.reg_write(UC_ARM64_REG_X2, PLAYER)
    u.reg_write(UC_ARM64_REG_X3, 5)
    u.reg_write(UC_ARM64_REG_SP, STACK + 0x8000)
    u.reg_write(UC_ARM64_REG_LR, BASE + 0x655FF0)
    calls = []
    def call(uc, address, size, data):
        if address == BASE + M.DETONATE:
            calls.append(uc.reg_read(UC_ARM64_REG_X0))
            put(ARRAY + 0x114, '<I', 0x501 if wall else 0x601)
            uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))
    u.hook_add(U.UC_HOOK_CODE, call)
    if mutate: mutate(u, put, game)
    u.emu_start(BASE + C.MINE_DETONATE_AT, BASE + 0x655FF0, count=200)
    return calls, u.reg_read(UC_ARM64_REG_X0)


def test_native_wrapper_executes_real_mine_transition_only_after_guards():
    assert emulate_wrapper() == ([ARRAY], 1)
    assert emulate_wrapper(wall=True) == ([ARRAY], 1)


@pytest.mark.parametrize('change', [
    lambda u,p,g:p(ARRAY + 0x110, '<I', 8),  # reused mine
    lambda u,p,g:p(PLAYER + 0x110, '<I', 6), # reused player
    lambda u,p,g:p(ARRAY, '<Q', BASE + M.VTABLE + 8),
    lambda u,p,g:p(ARRAY + 8, '<I', 0x201),
    lambda u,p,g:p(ARRAY + 0x118, '<B', 0x5E),
    lambda u,p,g:p(ARRAY + 0x119, '<B', 2),
    lambda u,p,g:p(ARRAY + 0x119, '<B', 3),
    lambda u,p,g:p(ARRAY + 0x115, '<B', 6),
    lambda u,p,g:p(g + 0x86FF, '<B', 1),
    lambda u,p,g:p(g + 0x5028, '<H', 0),
    lambda u,p,g:p(g + 0x78, '<I', 0),
    lambda u,p,g:p(BASE + M.POOL + 0x10, '<I', 513),
    lambda u,p,g:p(BASE + M.POOL + 0x14, '<I', M.STRIDE + 8),
    lambda u,p,g:p(BASE + M.POOL + 8, '<Q', ARRAY + 1),
])
def test_native_wrapper_refuses_stale_foreign_or_paused_objects(change):
    assert emulate_wrapper(change) == ([], 0)


def test_wrapper_source_reproduces_the_pinned_executable():
    from gbox.mercs.native.re4_82c2a04a.build_dispatch import assemble_mine_detonate
    assert assemble_mine_detonate() == C.MINE_DETONATE[4]


@pytest.mark.parametrize('distance,power', [(2999.,0),(3000.,0),(4999.,1),(6999.,2)])
def test_native_wrapper_defers_live_player_inside_blast_radius(distance, power):
    def move(u, put, game):
        put(ARRAY + 0xA4, '<3f', distance, 0., 0.)
        put(ARRAY + 0x541, '<B', power)
    assert emulate_wrapper(move) == ([], 2)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_native_wrapper_refuses_nonfinite_projectile_positions(value):
    assert emulate_wrapper(lambda u,p,g:p(ARRAY + 0xA4, '<f', value)) == ([], 0)


@pytest.mark.parametrize('result', ['timeout', 'too_close'])
def test_per_mine_claims_keep_unattempted_or_explicitly_deferred_darts_eligible(monkeypatch,result):
    from gbox.mercs.titles import re4_switch_native as N
    ctl=N.Controller.__new__(N.Controller)
    ctl.base=BASE;ctl.player=PLAYER;ctl.player_id=5
    ctl.ensure_attached=lambda:None
    ctl.rd=lambda at,n:C.MINE_DETONATE[4]
    ctl._mine_fuses=M.Fuses()
    rows=ctl._mine_fuses.observe('life',[{'ptr':ARRAY,'generation':1},{'ptr':ARRAY+M.STRIDE,'generation':2}],10)
    monkeypatch.setattr(N.time,'monotonic',lambda:14.)
    calls=[]
    def call(off,ptr,*args):
        calls.append(ptr)
        if ptr==ARRAY:
            if result=='timeout':raise N.Uncertain('lost native acknowledgment')
            return 2
        return 1
    ctl.call=call
    receipt=ctl._detonate_mine_rows(rows,14.)
    assert receipt['verified'] is False
    if result=='timeout':
        assert calls==[ARRAY] and receipt['state']=='uncertain'
        assert ctl._mine_fuses.submitted=={(ARRAY,1)}
    else:
        assert calls==[ARRAY,ARRAY+M.STRIDE] and receipt['initiated']==1
        assert ctl._mine_fuses.submitted=={(ARRAY+M.STRIDE,2)}
        assert receipt['mines'][0]['state']=='deferred_player_in_range'
    assert receipt['mines'][-1].get('late_s',1.)==1.


def test_incomplete_pool_scan_never_presents_partial_mine_census():
    ctl,put=memory();read=ctl.rd
    ctl.rd=lambda at,n:read(at,n-1) if at==ARRAY else read(at,n)
    with pytest.raises(ValueError,match='incomplete'):
        M.read_mines(ctl)
