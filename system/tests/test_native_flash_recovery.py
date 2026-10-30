"""Actual controller state machines against bounded simulated guest RAM."""
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch_native as N5, re6_switch_native as N6


@pytest.fixture(params=[N5, N6], ids=['re5', 're6'])
def ctl(request):
    module=request.param
    c=module.Controller.__new__(module.Controller)
    c.base=0x100000000;c.player=0x200000000;c.heap=0x210000000;c.generation=77
    c.manager=c.player+0x13A8;c.original=c.base+0x1C290C8
    c.lock=threading.RLock();c.failed=c.recoverable=True
    c.mem={};c.writes=[]
    def put(at,data):c.mem.update({at+i:b for i,b in enumerate(data)})
    c.put=put;c.rd=lambda at,n:bytes(c.mem.get(at+i,0) for i in range(n))
    c.check_build=lambda:None;c.check=lambda:None
    def write(at,data):c.writes.append((at,data));put(at,data)
    c.write=write
    c.state_at=c.heap+(0x6A8 if module is N5 else 0xA8)
    c.owner_at=c.player if module is N5 else c.manager
    c.table=c.original if module is N5 else c.base+N6.VT
    put(c.owner_at,struct.pack('<Q',c.table))
    if module is N5:
        put(c.heap+0x6A0,b'GBXNC502');put(c.heap+0x60,struct.pack('<Q',c.base+N5.DISPATCH))
        put(c.heap+0x680,struct.pack('<4Q',c.original,c.base+N5.UPDATE,c.player,c.generation))
    else:
        put(c.heap+0xA0,b'GBXNC001');put(c.heap+0x48,struct.pack('<Q',c.base+N6.DISPATCH))
        put(c.heap+0x80,struct.pack('<Q',c.table))
        put(c.heap+0x90,struct.pack('<QI',c.player,c.generation))
    c.call=lambda *a:pytest.fail('Never replay the previous operation')
    return c


@pytest.mark.parametrize('state',[1,2])
def test_timeout_keeps_dispatch_until_the_original_call_completes(ctl,state):
    ctl.put(ctl.owner_at,struct.pack('<Q',ctl.heap))
    ctl.put(ctl.state_at,struct.pack('<I',state))
    ctl.detach_completed()
    assert ctl.q(ctl.owner_at)==ctl.heap and not ctl.writes
    assert not ctl.recover_completed_call()
    ctl.put(ctl.state_at,struct.pack('<I',3))  # native callback completes later
    assert ctl.recover_completed_call()
    assert ctl.q(ctl.owner_at)==ctl.table
    assert ctl.writes==[(ctl.owner_at,struct.pack('<Q',ctl.table))]
    assert not ctl.failed


def test_completed_old_player_does_not_permanently_disable_the_next_round(ctl):
    ctl.put(ctl.state_at,struct.pack('<I',3))
    def changed():raise N6.Unavailable('player allocation changed')
    ctl.check=changed
    assert ctl.recover_completed_call()  # read-only; old table already restored
    assert not ctl.writes


def test_never_restore_a_table_into_a_replaced_player(ctl):
    ctl.put(ctl.state_at,struct.pack('<I',3));ctl.put(ctl.owner_at,struct.pack('<Q',ctl.heap))
    def changed():raise N6.Unavailable('player allocation changed')
    def write(*_):changed()
    ctl.write=write
    with pytest.raises(N6.Unavailable,match='player allocation'):ctl.recover_completed_call()
    assert ctl.failed


@pytest.mark.parametrize('state,ok',[(0,False),(1,False),(2,True),(3,True),(4,False)])
def test_publish_accepts_only_native_consumption_as_readback(ctl,state,ok):
    writes=[]
    def consumed(at,data):
        writes.append((at,data));ctl.put(at,struct.pack('<I',state))
        raise RuntimeError('memory write not confirmed by read-back')
    ctl.write=consumed
    if ok:ctl.publish_call(ctl.state_at)
    else:
        with pytest.raises(RuntimeError):ctl.publish_call(ctl.state_at)
    assert writes==[(ctl.state_at,b'\1\0\0\0')]


def test_foreign_mailbox_never_clears_failure(ctl):
    ctl.put(ctl.state_at,struct.pack('<I',3));ctl.put(ctl.heap+0xA0,b'corrupt!');ctl.put(ctl.heap+0x6A0,b'corrupt!')
    with pytest.raises(N6.Unavailable,match='identity'):ctl.recover_completed_call()
    assert ctl.failed and not ctl.writes
