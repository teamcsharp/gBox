"""GameCube revision/memory guards and bounded native command behavior; real-game evidence lives in docs."""
import struct
from types import SimpleNamespace

import pytest
from gbox import pso_gc_live as G, pso_controls
from gbox.registry import Unsupported


class RAM:
    def __init__(self):
        self.data = bytearray(0x1800000)
        self.writes = []
        self.put(0x80000000, b'GPOE8P\0\x02')
        for address, expected in G.GUARDS.items():
            self.put(address, expected)
        self.word(G.VT_UPDATE, G.ORIGINAL_UPDATE)
        self.put(G.EQUIP_PATCH, bytes.fromhex('881d0000'))
        self.word(G.PHASE, 14)
        self.player = 0x80DA62A0
        self.word(G.PLAYER, self.player)
        self.word(self.player, 0x80430000)
        self.put(0x80430000, b'TObjPlayer\0')
        self.word(self.player+0x18, G.VT_UPDATE-12)
        self.word(G.FLOOR, 1)
        self.word(G.FLOOR_COUNTS, 0x81000000)
        self.word(G.FLOOR_TABLE, 0x81000100)
        self.dbg = SimpleNamespace(write=self.write_memory)

    def put(self, address, data):
        off = address-0x80000000
        assert 0 <= off <= len(self.data)-len(data)
        self.data[off:off+len(data)] = data

    def word(self, address, value):
        self.put(address, struct.pack('>I', value))

    def read_memory(self, address, length):
        assert 0x80000000 <= address <= 0x81800000-length
        return bytes(self.data[address-0x80000000:address-0x80000000+length])

    def write_memory(self, address, data):
        self.writes.append((address, data))
        self.put(address, data)


@pytest.mark.parametrize('damage', ['revision','executable','online','player','scratch','vtable'])
def test_guard_refuses_without_any_writes(damage):
    ram=RAM()
    if damage=='revision': ram.put(0x80000007,b'\x01')
    if damage=='executable': ram.put(G.F_CREATE,b'xxxx')
    if damage=='online': ram.word(G.PHASE,15)
    if damage=='player': ram.word(G.PLAYER,0)
    if damage=='scratch': ram.put(G.CAVE+80,b'occupied')
    if damage=='vtable': ram.word(G.VT_UPDATE,0x80002000)
    with pytest.raises((Unsupported, RuntimeError)):
        G.GC(ram).hook()
    assert ram.writes==[]


def test_exact_gc_revision_enables_panel_without_dc_reads():
    ram=RAM()
    from gbox import pso_gc_adventure as A
    from gbox import pso_accuracy as H
    for a,b in A.GUARDS.items():ram.put(a,b)
    ram.put(A.DROP_ENTRY,A.DROP_ORIGINAL)
    for a,b in H.GUARDS.items():ram.put(a,b)
    for a,_,_,b in H.SITES:ram.put(a,b)
    cap=pso_controls.capabilities({'title':'Phantasy Star Online Episode I & II Plus','platform':'gamecube'},ram.read_memory)
    assert cap['supported'] and all(cap['features'].values())
    assert 'GameCube' in cap['label']
    assert len(cap['classes'])==12


def test_dispatcher_hook_is_idempotent_and_restores_only_its_own_slot():
    ram=RAM();m=G.GC(ram)
    m.hook();count=len(ram.writes);m.hook()
    assert len(ram.writes)==count
    assert m.u32(G.VT_UPDATE)==G.CAVE
    assert G.CAVE+len(G.CODE)<=G.FLUSH<G.HEADER<G.END
    assert G.BUF+30*28<=G.CAVE
    assert G.QUEUE+G.QMAX*G.QSZ<=G.BUF
    m.unhook()
    assert m.u32(G.VT_UPDATE)==G.ORIGINAL_UPDATE
    ram.word(G.VT_UPDATE,0x80001000);m.unhook()
    assert m.u32(G.VT_UPDATE)==0x80001000


def test_pending_native_batch_is_not_republished_or_retried():
    ram=RAM();m=G.GC(ram);m.hook();ram.word(G.QUEUE,G.F_CREATE)
    before=len(ram.writes)
    with pytest.raises(RuntimeError,match='still pending'):
        m.call([(G.F_CREATE,G.BUF,0)])
    assert len(ram.writes)==before


def test_timeout_has_unknown_outcome_and_does_not_retry():
    ram=RAM();m=G.GC(ram)
    with pytest.raises(RuntimeError,match='outcome unknown'):
        m.call([(G.F_CREATE,G.BUF,0)],timeout=0)
    publications=[data for address,data in ram.writes if address==G.QUEUE and data==struct.pack('>I',G.F_CREATE)]
    assert len(publications)==1 and m.u32(G.QUEUE)==G.F_CREATE


def test_clear_uses_native_delete_only_for_gbox_ids():
    ram=RAM();m=G.GC(ram);items=[(G.ID_BASE,'000100'),(0x10001,'001000')];packets=[]
    m.floor_items=lambda:list(items)
    def native(calls):
        for fn,address in calls:
            assert fn==G.F_DELETE
            packet=m.read(address,12);packets.append(packet)
            _,_,_,item_id,floor=struct.unpack('<BBHII',packet)
            assert floor==1
            items[:]=[r for r in items if r[0]!=item_id]
        return [0]*len(calls)
    m.call=native
    assert m.floor_clear()['removed']==1
    assert items==[(0x10001,'001000')]
    assert packets[0][:4]==b'\x63\x03\0\0'


def test_item_ids_are_reserved_before_publish_and_not_reused_after_clear():
    ram=RAM();m=G.GC(ram);items=[];m.floor_items=lambda:list(items)
    def native(calls):
        for fn,address,_ in calls:
            rec=m.read(address,36);item_id=struct.unpack_from('>I',rec,28)[0]
            assert m.u32(G.NEXT_ID)>item_id
            items.append((item_id,rec[16:19].hex()))
        return [0x80DB0000]*len(calls)
    m.call=native
    first=m.floor_spawn(['000100'])['ids'][0];items.clear()
    second=m.floor_spawn(['000100'])['ids'][0]
    assert second==first+1


def test_inventory_give_verifies_a_consumable_merged_into_an_existing_stack():
    ram=RAM();m=G.GC(ram)
    def row(amount):
        data=bytearray(20);data[:3]=bytes.fromhex('030000');data[5]=amount
        return {'code':'030000','id':0x10003,'data':data.hex()}
    results=iter([[row(4)],[row(5)]])
    m.inventory=lambda:next(results)
    m.call=lambda calls:[0x80DB0000]*len(calls)
    result=m.give('030000')
    assert result['created']==1 and result['verified'] and result['ids']==[]


def test_mag_give_uses_form_identity_not_the_level_byte():
    ram=RAM();m=G.GC(ram)
    data=bytes.fromhex('02010500f40100000000000000f000002800000e')
    results=iter([[],[{'code':'020105','id':G.ID_BASE,'data':data.hex()}]])
    m.inventory=lambda:next(results);m.call=lambda calls:[0x80DB0000]*len(calls)
    result=m.give('020100')
    assert result['created']==1 and result['verified'] and result['ids']==[G.ID_BASE]
