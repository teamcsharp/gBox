"""Revision guards, exact native command ownership, and reversible AUF switches.

Fake RAM verifies transaction safety; native execution evidence is recorded separately.
"""
import hashlib
import struct
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gbox import auf_live as A
from gbox.models import Permission
from gbox.registry import Unsupported


class Adapter:
    def __init__(self):
        self.data=bytearray(0x1800000);self.writes=[];self.state='PLAYING'
        self.pauses=0;self.resumes=0;self.native_calls=[];self.auto_ack=True;self.ack_mutator=None
        self.player,self.table,self.client=0x80A00000,0x80900000,0x80B00000
        self.put(0x80000000,b'GW7E69\0\1');self.put(0x80010000,b'owned routine')
        for a,v in ((0x804E3068,1),(0x804E34CC,0),(0x804E38E4,0x80C00000),
                    (0x804E38B0,self.table),(self.table+0x24C,self.player),
                    (0x804E3530,self.client),(self.table+0x1E4,1),(self.player+4,A.VT),
                    (self.player+0x14,self.table),(self.player+0x18,self.client),
                    (self.table+0x1E0,self.client),(self.player+0xA4,5),
                    (0x804E390C,0x80C00040),(A.HOOK,A.ORIGINAL),(A.LEVEL_MS,10000),
                    (A.GI_COMPLETE_SUBMAP,A.F_COMPLETE_SUBMAP),
                    (A.RESOURCE_TABLE,0x80D00000)):
            self.word(a,v)
        self.put(self.player+0x180,struct.pack('>f',100))
        self.load_resources(('models/p2k_pickup.men','models/mrl22_pickup.men','models/mrl22_projectile.men'))
        self.weapon=0x80E00000;self.word(self.player+0x29C,self.weapon)
        self.word(self.weapon+0x278,self.player)
        self.word(self.weapon+0x28,0x80E01000);self.word(0x80E01000,0x80E01101)
        self.put(0x80E01101,b'models/p2k_pickup.men\0')
        self.word(self.weapon+0x394,1);self.word(self.weapon+0x3F0,0x80E01200)
        self.put(0x80E01200,struct.pack('>4I',0x80E01301,1,16,0));self.put(0x80E01301,b'\0')

    def load_resources(self,names):
        self.word(0x80D00000,len(names));at=0x80D01001
        for index,name in enumerate(names):
            self.put(at,name.encode()+b'\0')
            self.put(0x80D00010+16*index,struct.pack('>4I',at,0x80D02000+index*16,4,index))
            at+=len(name)+1

    def put(self,address,data):
        off=address-0x80000000
        assert 0<=off<=len(self.data)-len(data)
        self.data[off:off+len(data)]=data

    def word(self,address,value):self.put(address,struct.pack('>I',value))
    def read_memory(self,address,size):
        off=address-0x80000000
        assert 0<=off<=len(self.data)-size
        return bytes(self.data[off:off+size])
    def write_memory(self,address,data):self.writes.append((address,bytes(data)));self.put(address,data)
    def add_item(self,name,address=None):
        count=struct.unpack('>I',self.read_memory(self.player+0x2C0,4))[0]
        entity_id=count+1;item=address or 0x80E10000+count*0x1000
        entity=self.table+entity_id*0x2B0;sd=0x80E40000+count*0x100
        self.word(entity+0x24C,item);self.word(entity+0x1E4,1)
        for offset,value in ((0x10,entity_id),(0x14,entity),(0x278,self.player),(0x2D8,sd)):
            self.word(item+offset,value)
        self.word(sd,sd+16);self.put(sd+16,name.encode()+b'\0')
        self.word(self.player+0x2BC,0x80E30000)
        self.word(0x80E30000+count*4,entity_id);self.word(self.player+0x2C0,count+1)
        return item
    def query_runtime(self):return {'state':self.state}
    def pause(self):self.pauses+=1;self.state='PAUSED'
    def resume(self):
        self.resumes+=1;self.state='PLAYING'
        if not self.auto_ack or self.read_memory(A.HOOK,4)!=struct.pack('>I',A.CAVE):return
        fn=struct.unpack('>I',self.read_memory(A.QUEUE,4))[0]
        target=struct.unpack('>I',self.read_memory(A.QUEUE+44,4))[0]
        if fn and target==self.player:
            packet=self.read_memory(A.QUEUE,64);self.native_calls.append(packet)
            self.word(A.QUEUE,0);self.word(A.QUEUE+40,1)
            result=0
            if fn in (A.F_GIVE,A.F_GIVE_GADGET):
                model=self.read_memory(A.BUFFER,80).split(b'\0',1)[0].decode()
                native_name={'gadget_pcodegen.men':'pcodegen','fist_pickup.men':'fist'}.get(model,model[:-4])
                result=self.add_item(native_name)
            elif fn==A.F_END:self.word(A.IS_END_OF_MISSION,1)
            elif fn==A.F_COMPLETE_SUBMAP:
                self.word(A.UI_COMPLETED_SUBMAPS,struct.unpack('>I',self.read_memory(A.UI_COMPLETED_SUBMAPS,4))[0]+1)
                self.word(A.UI_FLOW_PENDING,2)
            self.word(A.QUEUE+36,result);self.word(A.QUEUE+40,2)
            if self.ack_mutator:self.ack_mutator(self)


@pytest.fixture
def ad(monkeypatch):
    monkeypatch.setattr(A,'FINGERPRINTS',((0x80010000,13,hashlib.sha256(b'owned routine').hexdigest()),))
    return Adapter()


@pytest.mark.parametrize('damage',('disc','revision','code','multiplayer','attract','gametype','player','client','cinematic','vehicle','dead'))
def test_exact_campaign_guard_rejects_before_writing(ad,damage):
    if damage=='disc':ad.put(0x80000000,b'GXYZ69')
    if damage=='revision':ad.put(0x80000007,b'\0')
    if damage=='code':ad.put(0x80010000,b'x')
    if damage=='multiplayer':ad.word(0x804E3068,4)
    if damage=='attract':ad.word(0x804E34C8,1)
    if damage=='gametype':ad.word(0x80C00020,2)
    if damage=='player':ad.word(ad.player+4,0x802482C0)
    if damage=='client':ad.word(ad.player+0x18,ad.client+4)
    if damage=='cinematic':ad.word(ad.client+0xC,0x100)
    if damage=='vehicle':ad.word(ad.player+0x2A4,0x80F00000)
    if damage=='dead':ad.put(ad.player+0x180,struct.pack('>f',0))
    with pytest.raises(Unsupported):A.Native(ad).check()
    assert ad.writes==[]


def test_inspect_lists_only_loaded_items_and_marks_unproven_checkpoint_unavailable(ad):
    m=A.Native(ad)
    with m.paused():result=m.inspect()
    assert result['switches']=={'noclip':False,'infinite_ammo':False,'rocket_pistol':False}
    assert [row['id'] for row in result['items']]==['p2k','mrl22']
    assert not result['available']['next_checkpoint']
    assert ad.writes==[] and ad.state=='PLAYING'


@pytest.mark.parametrize('switch',('noclip','infinite_ammo'))
def test_toggle_reads_back_and_restores_original_value(ad,switch):
    m=A.Native(ad)
    with m.paused():
        m.check();before=bytes(ad.data);assert m.toggle(switch,True)['on']
        assert m.inspect()['switches'][switch]
        assert not m.toggle(switch,False)['on']
        assert ad.data==before
    assert ad.state=='PLAYING' and ad.pauses==ad.resumes==1


def test_operator_pause_is_retained_even_on_failure(ad):
    ad.state='PAUSED';m=A.Native(ad)
    with pytest.raises(Unsupported):
        with m.paused():ad.word(ad.player+4,0);m.check()
    assert ad.state=='PAUSED' and ad.resumes==0 and ad.pauses==0


def test_movement_mode_changed_elsewhere_is_not_overwritten_on_restore(ad):
    m=A.Native(ad);m.check();m.toggle('noclip',True);ad.word(ad.player+0xA4,5)
    count=len(ad.writes)
    with pytest.raises(RuntimeError,match='changed outside'):m.toggle('noclip',False)
    assert len(ad.writes)==count


def test_dispatcher_owned_slot_is_idempotent_and_foreign_scratch_never_overwritten(ad):
    m=A.Native(ad);m.check();ad.put(A.CAVE+0x250,b'foreign')
    with pytest.raises(Unsupported,match='occupied'):m.install()
    assert not ad.writes
    ad.put(A.CAVE+0x250,bytes(7));m.install();n=len(ad.writes);m.install()
    assert len(ad.writes)==n and m.u32(A.HOOK)==A.CAVE
    ad.put(A.CAVE,b'else')
    with pytest.raises(Unsupported,match='unknown'):m.install()


def test_native_grant_uses_loaded_model_and_verifies_owner(ad):
    m=A.Native(ad)
    result=m.give('mrl22',time.time()+15)
    assert result['verified'] and result['name']=='MRL-22 rocket launcher'
    assert len(ad.native_calls)==1
    packet=struct.unpack('>16I',ad.native_calls[0])
    assert packet[0]==A.F_GIVE and packet[1:8]==(ad.player,A.BUFFER,0,0,0xFFFFFFFF,0xFFFFFFFF,0)
    assert ad.read_memory(A.BUFFER,17).startswith(b'mrl22_pickup.men\0')
    assert ad.state=='PLAYING' and ad.pauses==ad.resumes


def test_unloaded_or_unknown_item_is_rejected_without_install(ad):
    m=A.Native(ad)
    with pytest.raises(Unsupported,match='not packaged'):m.give('ssr4000',time.time()+15)
    with pytest.raises(ValueError,match='dropdown'):m.give('arbitrary/path.men',time.time()+15)
    assert not ad.writes and not ad.native_calls


@pytest.mark.parametrize('item,model,function',(
    ('qclaw','qclaw_pickup.men',A.F_GIVE),
    ('qlaser','gadget_qlaser.men',A.F_GIVE_GADGET),
    ('qdecryptor','gadget_qdecryptor.men',A.F_GIVE_GADGET),
    ('qremote','gadget_qremote.men',A.F_GIVE_GADGET),
    ('qcamera','gadget_qcamera.men',A.F_GIVE_GADGET),
    ('qjet','gadget_qjet.men',A.F_GIVE_GADGET),
    ('qspecs','xrayglasses_large.men',A.F_GIVE_GADGET),
    ('keycard','gadget_keycard.men',A.F_GIVE_GADGET),
    ('keycard2','gadget_keycard2.men',A.F_GIVE_GADGET),
    ('pcodegen','gadget_pcodegen.men',A.F_GIVE_GADGET),
    ('dartgun','dartgun_pickup.men',A.F_GIVE),
    ('fist','fist_pickup.men',A.F_GIVE),
))
def test_native_gadget_grant_uses_its_reviewed_model_and_correct_native_path(ad,item,model,function):
    ad.load_resources(('models/'+model,))
    m=A.Native(ad);result=m.give(item,time.time()+15)
    assert result['verified'] and not result['already_owned'] and not result['equipped']
    assert 'does not auto-equip' in result['message']
    assert len(ad.native_calls)==1
    packet=struct.unpack('>16I',ad.native_calls[0])
    assert packet[:5]==(function,ad.player,A.BUFFER,0,0)
    assert packet[5:9]==((0,0,0,0) if function==A.F_GIVE_GADGET else (0xFFFFFFFF,0xFFFFFFFF,0,0))
    assert m.text(A.BUFFER)==model
    native_name={'pcodegen':'pcodegen','fist':'fist'}.get(item,model[:-4])
    assert m.inventory()[native_name]==[int(result['native_item'],16)]
    assert m.u32(ad.player+0x29C)==ad.weapon


@pytest.mark.parametrize('item',tuple(A.GADGET_MODELS)+('qclaw','dartgun'))
def test_gadgets_never_grant_assets_absent_from_the_loaded_mission(ad,item):
    with pytest.raises(Unsupported,match='not packaged'):A.Native(ad).give(item,time.time()+15)
    assert not ad.writes and not ad.native_calls


def test_profile_exposes_reviewed_gadget_catalog_and_explains_selection():
    profile=A.reviewed_profile(['b'*64],['c'*64],{'give_item'})
    action=profile['actions'][0];options=action['parameters'][0]['options']
    assert set(A.GADGET_MODELS)|{'qclaw','dartgun'} <= {row['value'] for row in options}
    assert 'weapon or gadget' in action['label'] and 'does not auto-equip' in action['notes']


def test_owned_gadgets_are_reported_and_not_regranted_or_selected(ad):
    ad.load_resources(('models/qclaw_pickup.men','models/gadget_qlaser.men'))
    claw=ad.add_item('qclaw_pickup');laser=ad.add_item('gadget_qlaser')
    ad.word(ad.player+0x29C,claw)
    m=A.Native(ad);m.check();rows={row['id']:row for row in m.items()}
    assert rows['qclaw']['owned'] is True and rows['qclaw']['equipped'] is True
    assert rows['qlaser']['owned'] is True and rows['qlaser']['equipped'] is False
    result=m.give('qlaser',time.time()+15)
    assert result['already_owned'] is True and result['equipped'] is False
    assert 'already in your inventory' in result['message']
    assert not ad.writes and not ad.native_calls
    assert m.u32(ad.player+0x29C)==claw and laser!=claw


def test_simultaneous_extra_gadget_is_reported_equipped(ad):
    ad.load_resources(('models/gadget_qlaser.men',))
    laser=ad.add_item('gadget_qlaser');ad.word(ad.player+0x7A4,laser)
    m=A.Native(ad);m.check()
    assert m.items()[0]['equipped'] is True
    assert m.give('qlaser',time.time()+15)['equipped'] is True
    assert not ad.writes


@pytest.mark.parametrize('damage',('count','entity','owner','name'))
def test_unknown_inventory_omits_booleans_and_refuses_grants_without_writing(ad,damage):
    ad.load_resources(('models/gadget_qlaser.men',))
    laser=ad.add_item('gadget_qlaser')
    if damage=='count':ad.word(ad.player+0x2C0,257)
    if damage=='entity':ad.word(0x80E30000,4096)
    if damage=='owner':ad.word(laser+0x278,ad.player+4)
    if damage=='name':ad.word(laser+0x2D8,0)
    m=A.Native(ad);m.check();row=m.items()[0]
    assert 'owned' not in row and 'equipped' not in row
    inspected=m.inspect()
    assert inspected['items'][0]['id']=='qlaser'
    assert inspected['available']['give_item'] is False
    assert 'Inventory could not be verified' in inspected['unavailable_reasons']['give_item']
    assert inspected['available']['noclip'] is True and inspected['available']['infinite_ammo'] is True
    with pytest.raises(Unsupported):m.give('qlaser',time.time()+15)
    assert not ad.writes and not ad.native_calls


def test_native_grant_requires_matching_inventory_name_not_only_owner(ad):
    ad.load_resources(('models/gadget_qlaser.men',))
    def corrupt_name(ram):ram.put(0x80E40010,b'wrong_item\0')
    ad.ack_mutator=corrupt_name
    with pytest.raises(RuntimeError,match='inventory/name'):A.Native(ad).give('qlaser',time.time()+15)
    assert len(ad.native_calls)==1


def test_already_owned_result_still_requires_a_fresh_deadline(ad,monkeypatch):
    ad.load_resources(('models/gadget_qlaser.men',));ad.add_item('gadget_qlaser')
    clock=[100.];monkeypatch.setattr(A.time,'time',lambda:clock[0])
    m=A.Native(ad);original=m.resources
    def slow_resources():
        rows=original();clock[0]=116.;return rows
    m.resources=slow_resources
    with pytest.raises(TimeoutError):m.give('qlaser',115.)
    assert not ad.writes and not ad.native_calls


def test_native_finish_uses_valid_empty_event_and_acknowledges_once(ad):
    result=A.Native(ad).finish(time.time()+15)
    assert result['verified'] and len(ad.native_calls)==2
    assert ad.read_memory(A.BUFFER,48)==bytes(48)
    assert struct.unpack_from('>3I',ad.native_calls[0])==(A.F_END,ad.player,A.BUFFER)
    assert struct.unpack_from('>2I',ad.native_calls[1])==(A.F_COMPLETE_SUBMAP,ad.player)
    assert result['native_functions']==[hex(A.F_END),hex(A.F_COMPLETE_SUBMAP)]


@pytest.mark.parametrize('blocked',('callback','transition','attempt'))
def test_native_exit_preconditions_reject_before_any_write(ad,blocked):
    m=A.Native(ad);m.check()
    if blocked=='callback':ad.word(A.GI_COMPLETE_SUBMAP,A.F_COMPLETE_SUBMAP+4)
    if blocked=='transition':ad.word(A.UI_FLOW_PENDING,2)
    if blocked=='attempt':m.owned['finish_attempt']=(m.owned['identity'],m.owned['epoch'])
    with m.paused():
        result=m.inspect()
        assert result['available']['finish_level'] is False
        assert result['unavailable_reasons']['finish_level']
        assert result['available']['give_item'] is (blocked!='transition')
    with pytest.raises(Unsupported):m.finish(time.time()+15)
    assert not ad.writes and not ad.native_calls


def test_native_give_rejects_pending_transition_before_any_write(ad):
    ad.word(A.UI_FLOW_PENDING,2)
    with pytest.raises(Unsupported,match='transition'):A.Native(ad).give('p2k',time.time()+15)
    assert not ad.writes and not ad.native_calls


@pytest.mark.parametrize('change',('callback','attempt'))
def test_native_exit_rechecks_start_conditions_after_preparation(ad,change):
    original=ad.resume
    def resume():
        original()
        if ad.resumes!=1:return
        if change=='callback':ad.word(A.GI_COMPLETE_SUBMAP,A.F_COMPLETE_SUBMAP+4)
        else:
            owned=ad._auf_live_owned;owned['finish_attempt']=(owned['identity'],owned['epoch'])
    ad.resume=resume
    with pytest.raises(Unsupported):A.Native(ad).finish(time.time()+15)
    assert not ad.native_calls
    assert not any(A.QUEUE<=address<A.QUEUE+64 for address,data in ad.writes)


def test_native_exit_marker_clears_for_new_section_even_with_pending_statistics(ad):
    m=A.Native(ad);m.check()
    m.owned['finish_attempt']=(m.owned['identity'],m.owned['epoch'])
    ad.word(A.IS_END_OF_MISSION,1)
    with m.paused():assert m.inspect()['available']['finish_level'] is False
    # A section reset is independently detected by the checked native level timer.
    ad.word(A.LEVEL_MS,1)
    with m.paused():assert m.inspect()['available']['finish_level'] is True
    assert m.u32(A.IS_END_OF_MISSION)==1
    assert m.finish(time.time()+15)['verified']
    assert len(ad.native_calls)==2


def test_existing_statistics_flag_does_not_block_a_fresh_world_exit(ad):
    ad.word(A.IS_END_OF_MISSION,1)
    m=A.Native(ad)
    with m.paused():assert m.inspect()['available']['finish_level'] is True
    assert m.finish(time.time()+15)['verified']


def test_uncertain_bookkeeping_arm_retains_mission_attempt_marker(ad):
    original=ad.write_memory
    def write(address,data):
        original(address,data)
        if address==A.QUEUE and data==struct.pack('>I',A.F_END):
            raise RuntimeError('Native arm transport acknowledgement was lost')
    ad.write_memory=write;m=A.Native(ad)
    with pytest.raises(RuntimeError,match='acknowledgement was lost'):m.finish(time.time()+15)
    assert len(ad.native_calls)==1
    writes=len(ad.writes)
    with pytest.raises(Unsupported,match='already started'):m.finish(time.time()+15)
    assert len(ad.writes)==writes and len(ad.native_calls)==1


def test_native_exit_expired_after_bookkeeping_never_arms_transition(ad,monkeypatch):
    clock=[100.];monkeypatch.setattr(A.time,'time',lambda:clock[0])
    ad.ack_mutator=lambda ram:clock.__setitem__(0,116.)
    with pytest.raises(TimeoutError):A.Native(ad).finish(115.)
    assert len(ad.native_calls)==1
    assert not any(a==A.QUEUE and b==struct.pack('>I',A.F_COMPLETE_SUBMAP) for a,b in ad.writes)


def test_native_exit_unknown_transition_never_retries_either_stage(ad,monkeypatch):
    clock=[0.];monkeypatch.setattr(A.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(A.time,'sleep',lambda _:clock.__setitem__(0,clock[0]+5))
    original=ad.resume
    def resume():
        fn=struct.unpack('>I',ad.read_memory(A.QUEUE,4))[0]
        if fn==A.F_COMPLETE_SUBMAP:ad.auto_ack=False
        original()
        if fn==A.F_COMPLETE_SUBMAP:
            ad.native_calls.append(ad.read_memory(A.QUEUE,64))
            ad.word(A.QUEUE,0);ad.word(A.QUEUE+40,1)
    ad.resume=resume;m=A.Native(ad)
    with pytest.raises(RuntimeError,match='outcome is unknown'):m.finish(time.time()+15)
    assert [struct.unpack_from('>I',p)[0] for p in ad.native_calls]==[A.F_END,A.F_COMPLETE_SUBMAP]
    writes=len(ad.writes)
    with pytest.raises(Unsupported,match='already started'):m.finish(time.time()+15)
    assert len(ad.writes)==writes


def test_native_calls_do_not_resume_operator_paused_game(ad):
    ad.state='PAUSED'
    with pytest.raises(Unsupported,match='Resume'):A.Native(ad).give('mrl22',time.time()+15)
    assert not ad.writes and not ad.resumes


@pytest.mark.parametrize('mode',('pause','menu'))
def test_native_menu_readiness_keeps_direct_switches_available(ad,mode):
    if mode=='pause':ad.word(A.NATIVE_PAUSED,1)
    else:ad.put(ad.player+A.NATIVE_MENU_OFFSET,b'\1')
    m=A.Native(ad)
    with m.paused():
        result=m.inspect()
        for op in ('give_item','finish_level'):
            assert result['available'][op] is False
            assert 'pause/options menu' in result['unavailable_reasons'][op]
        assert all(result['available'][op] for op in ('noclip','infinite_ammo','rocket_pistol'))
        assert not ad.writes
        assert m.toggle('noclip',True)['on']
        assert not m.toggle('noclip',False)['on']
    assert ad.state=='PLAYING'
    assert m.u32(A.NATIVE_PAUSED)==(1 if mode=='pause' else 0)


@pytest.mark.parametrize('mode',('pause','menu'))
@pytest.mark.parametrize('op',('give','finish'))
def test_native_menu_rejects_commands_before_any_write(ad,mode,op):
    if mode=='pause':ad.word(A.NATIVE_PAUSED,1)
    else:ad.put(ad.player+A.NATIVE_MENU_OFFSET,b'\1')
    m=A.Native(ad)
    with pytest.raises(Unsupported,match='pause/options menu'):
        if op=='give':m.give('p2k',time.time()+15)
        else:m.finish(time.time()+15)
    assert not ad.writes and not ad.native_calls
    assert ad.state=='PLAYING' and ad.pauses==ad.resumes==1


@pytest.mark.parametrize('mode',('pause','menu'))
def test_native_menu_entered_after_preparation_never_arms_command(ad,mode):
    original=ad.resume
    def resume():
        original()
        if ad.resumes!=1:return
        if mode=='pause':ad.word(A.NATIVE_PAUSED,1)
        else:ad.put(ad.player+A.NATIVE_MENU_OFFSET,b'\1')
    ad.resume=resume
    with pytest.raises(Unsupported,match='pause/options menu'):
        A.Native(ad).give('p2k',time.time()+15)
    assert not ad.native_calls
    assert not any(A.QUEUE<=address<A.QUEUE+64 for address,data in ad.writes)


@pytest.mark.parametrize('offset', (4,44,48,52,56,60))
def test_mailbox_payload_change_is_unknown_and_never_retried(ad,offset):
    ad.ack_mutator=lambda ram:ram.word(A.QUEUE+offset,12345)
    with pytest.raises(RuntimeError,match='mailbox changed'):A.Native(ad).give('mrl22',time.time()+15)
    assert len(ad.native_calls)==1
    assert len([w for w in ad.writes if w==(A.QUEUE,struct.pack('>I',A.F_GIVE))])==1


def test_pending_command_cannot_be_replaced(ad):
    m=A.Native(ad);m.check();m.install();ad.word(A.QUEUE,A.F_END)
    n=len(ad.writes)
    with pytest.raises(RuntimeError,match='pending'):m.call(A.F_GIVE,[ad.player,A.BUFFER],time.time()+15)
    assert len(ad.writes)==n and not ad.native_calls


def test_pending_command_argument_buffer_cannot_be_overwritten(ad):
    m=A.Native(ad);m.check();m.install();ad.word(A.QUEUE,A.F_END);ad.put(A.BUFFER,b'pending native arguments')
    n=len(ad.writes);original=ad.read_memory(A.BUFFER,48)
    with pytest.raises(RuntimeError,match='pending'):m.give('mrl22',time.time()+15)
    assert len(ad.writes)==n and ad.read_memory(A.BUFFER,48)==original


def test_rocket_pistol_uses_loaded_native_projectile_and_restores_pointer(ad):
    m=A.Native(ad);m.check();old=ad.read_memory(ad.weapon+0x3F0,4)
    with m.paused():
        assert m.rocket(True)['on'];assert m.inspect()['switches']['rocket_pistol']
        assert m.u32(ad.weapon+0x394)==2
        assert m.text(m.u32(A.BUFFER+0xE0))=='mrl22_projectile.men'
        assert m.rocket(False)['on'] is False
    assert ad.read_memory(ad.weapon+0x3F0,4)==old and m.u32(ad.weapon+0x394)==1


def test_orphan_rocket_patch_cannot_claim_off_or_guess_original_pointer(ad):
    m=A.Native(ad);m.check();m.rocket(True);ad._auf_live_owned.clear()
    n=len(ad.writes)
    with pytest.raises(Unsupported,match='original mapping'):m.inspect()
    with pytest.raises(Unsupported,match='original mapping'):m.rocket(True)
    with pytest.raises(Unsupported,match='original mapping'):m.rocket(False)
    assert len(ad.writes)==n


def test_level_reset_discards_restoration_record_and_exposes_orphan(ad):
    m=A.Native(ad);m.check();m.rocket(True);ad.word(A.LEVEL_MS,10)
    with pytest.raises(Unsupported,match='original mapping'):m.inspect()
    assert 'rocket_pistol' not in m.owned


def test_freed_original_projectile_string_is_never_restored(ad):
    m=A.Native(ad);m.check();m.rocket(True);ad.word(0x80E01200,0x80E01400)
    n=len(ad.writes)
    with pytest.raises(Unsupported,match='allocation changed'):m.rocket(False)
    assert len(ad.writes)==n


def test_tool_requires_fresh_command_permission_and_deduplicates_native_grant(ad,monkeypatch):
    from gbox import tools
    sid='auf-test-session'
    monkeypatch.setitem(tools.SESSIONS,sid,(ad,{'game_id':A.GAME_ID,'platform':'gamecube'}))
    A._receipts.pop(sid,None)
    ctx=SimpleNamespace(config=SimpleNamespace(granted_permissions=[Permission.READ,Permission.MEMORY_WRITE]))
    base={'session_id':sid,'op':'give_item','item':'mrl22','command_id':'test-command-12345678','expires':time.time()+15}
    with pytest.raises(TimeoutError):A.auf_live(A.LiveIn.model_validate(base|{'expires':time.time()-1}),ctx)
    with pytest.raises(ValueError):A.auf_live(A.LiveIn.model_validate(base|{'command_id':''}),ctx)
    assert not ad.writes
    first=A.auf_live(A.LiveIn.model_validate(base),ctx);second=A.auf_live(A.LiveIn.model_validate(base),ctx)
    assert first==second and len(ad.native_calls)==1
    with pytest.raises(ValueError,match='reused'):A.auf_live(A.LiveIn.model_validate(base|{'item':'p2k'}),ctx)
    assert len(ad.native_calls)==1


def test_switch_uses_strict_boolean():
    for bad in ('true','false',1,0,None):
        with pytest.raises(ValidationError):A.LiveIn(session_id='test',op='noclip',on=bad)


@pytest.mark.parametrize('change',('player','resource_table','arguments','rewind'))
def test_prepared_grant_never_crosses_a_player_or_mission_change(ad,change):
    original=ad.resume
    def resume():
        original()
        if ad.resumes!=1:return
        if change=='player':
            p=ad.player+0x1000;ad.put(p,ad.read_memory(ad.player,0x840));ad.word(ad.table+0x24C,p)
        elif change=='resource_table':ad.word(0x80D0000C,0x12345678)
        elif change=='arguments':ad.put(A.BUFFER,b'changed')
        else:ad.word(A.LEVEL_MS,1)
    ad.resume=resume
    with pytest.raises(Unsupported,match='prepared'):A.Native(ad).give('mrl22',time.time()+15)
    assert not ad.native_calls
    assert not any(a==A.QUEUE and b==struct.pack('>I',A.F_GIVE) for a,b in ad.writes)


def test_delayed_resources_cannot_expire_then_install_or_write(ad,monkeypatch):
    clock=[100.];monkeypatch.setattr(A.time,'time',lambda:clock[0])
    m=A.Native(ad);original=m.resources
    def slow_resources():
        rows=original();clock[0]+=16;return rows
    m.resources=slow_resources
    with pytest.raises(TimeoutError):m.give('mrl22',115.)
    assert not ad.writes


def test_delayed_compare_cannot_expire_then_change_native_switch(ad,monkeypatch):
    clock=[100.];monkeypatch.setattr(A.time,'time',lambda:clock[0])
    m=A.Native(ad);m.check();m.expires=115.;original=m.read
    def delayed_read(address,size):
        raw=original(address,size)
        if address==ad.player+0xA4:clock[0]+=16
        return raw
    m.read=delayed_read
    with pytest.raises(TimeoutError):m.toggle('noclip',True)
    assert not ad.writes


def test_profile_factory_never_promotes_unverified_or_nonexistent_checkpoint(monkeypatch):
    from gbox import live_controls as L
    from tests.test_build_quarantine import Memory
    store=Memory();store.read_artifact=lambda sha:b'proof' if sha=='b'*64 else None
    profile=A.reviewed_profile(['b'*64],['b'*64],{'noclip','give_item'})
    approved=L.validate(profile,store)
    assert [a['id'] for a in approved['actions']]==['noclip','give_item']
    assert approved['actions'][0]['binding']['state_key']=='noclip'
    with pytest.raises(ValueError):A.reviewed_profile(['b'*64],['b'*64],{'next_checkpoint'})
    with pytest.raises(ValueError):A.reviewed_profile(['b'*64],[],{'noclip'})


def test_dispatcher_register_backups_do_not_overlap_native_argument_home_area():
    words=struct.unpack('>'+str(len(A.CODE)//4)+'I',A.CODE)
    decoded=[(w>>26,(w>>21)&31,(w>>16)&31,(w&0xFFFF)-0x10000 if w&0x8000 else w&0xFFFF) for w in words]
    first=decoded[0]
    assert first[:3]==(37,1,1)  # stwu r1,-frame(r1)
    frame=-first[3];assert frame%16==0
    stores=[i for i in decoded if i[:3]==(47,3,1)]
    loads=[i for i in decoded if i[:3]==(46,3,1)]
    assert len(stores)==len(loads)==1 and stores[0][3]==loads[0][3]
    gpr_start=stores[0][3]
    assert gpr_start>=0x30, 'native callees own the outgoing argument home area'
    ranges=[(gpr_start,gpr_start+29*4)]
    for register in range(1,14):
        store=[i for i in decoded if i[:3]==(54,register,1)]
        load=[i for i in decoded if i[:3]==(50,register,1)]
        assert len(store)==len(load)==1 and store[0][3]==load[0][3]
        off=store[0][3];assert off%8==0 and off>=0x30 and off+8<=frame
        ranges.append((off,off+8))
    for index,(lo,hi) in enumerate(ranges):
        assert all(hi<=other_lo or lo>=other_hi for other_lo,other_hi in ranges[index+1:])
    assert (36,0,1,frame+4) in decoded and (32,0,1,frame+4) in decoded
    assert (14,1,1,frame) in decoded and words[-1]==0x4E800420


@pytest.mark.parametrize('game_id',(A.GAME_ID,'a8a1484cf7ac7ce1'))
def test_verified_iso_and_gcz_catalog_aliases_share_exact_native_guards(ad,monkeypatch,game_id):
    from gbox import tools
    sid='auf-alias-session'
    monkeypatch.setitem(tools.SESSIONS,sid,(ad,{'game_id':game_id,'platform':'gamecube'}))
    result=A.auf_live(A.LiveIn(session_id=sid),None)['result']
    assert result['verified'] and result['revision']=='GW7E69 disc 0 revision 1'
    assert not ad.writes


def test_matching_title_never_authorizes_an_unreviewed_catalog_id(ad,monkeypatch):
    from gbox import tools
    sid='auf-unreviewed-title-session'
    monkeypatch.setitem(tools.SESSIONS,sid,(ad,{'game_id':'other','platform':'gamecube','title':'007 - Agent Under Fire (USA)'}))
    with pytest.raises(Unsupported,match='target Agent Under Fire'):A.auf_live(A.LiveIn(session_id=sid),None)
    assert not ad.writes
