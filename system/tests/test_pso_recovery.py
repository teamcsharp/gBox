import copy
import struct
from types import SimpleNamespace
import pytest
from gbox import pso_coop_combat as W
from gbox.pso_gc_live import F_EQUIP, F_INVENTORY
from gbox.models import Permission

def item(ident, code='001e00', equipped=True):
    raw=bytearray(20);raw[:3]=bytes.fromhex(code);struct.pack_into('>I',raw,12,ident)
    return dict(id=ident,code=code,data=raw.hex(),equipped=equipped)

class Native:
    def __init__(self,ad,player_index=0,pin_player=False):
        assert pin_player
        self.ad=ad;self.slot=player_index+1
    def check(self):return self.ad.pointers[self.slot]
    def u32(self,address):return {W.EPISODE:self.ad.episode-1,W.FLOOR:self.ad.floor,W.DIFFICULTY:0,W.TRAVELLING:self.ad.travel}[address]
    def u16(self,address):return self.ad.hp[self.slot]
    def read(self,address,length):return struct.pack('>13I',self.ad.active[self.slot],*([0]*12))
    def call(self,calls):
        self.ad.calls.append((self.slot,copy.deepcopy(calls)))
        for call in calls:
            if call[0]==F_EQUIP:
                self.ad.equips.append((self.slot,call[2]))
                if self.ad.accept:
                    for row in self.ad.rows[self.slot]:row['equipped']=row['id']==call[2]
                    self.ad.active[self.slot]=self.ad.objects[self.slot]
            if self.ad.fail_on==call[0]:raise RuntimeError('Outcome unknown')
        self.ad.on_call(calls)
        return [0]*len(calls)
    def inventory(self):
        self.call([(F_INVENTORY,self.check(),0)])
        return copy.deepcopy(self.ad.rows[self.slot])
    def equip_id(self,item_id):
        self.call([(F_EQUIP,self.check(),item_id,0)])
        return self.ad.accept
    def item_object(self,item_id):
        self.call([(0x801D4F14,self.check(),item_id)])
        return self.ad.objects[self.slot]+self.ad.object_drift

@pytest.fixture
def rig(monkeypatch):
    from gbox import tools,pad_takeover
    sid='equipment-proof';driver=SimpleNamespace(stopped=False)
    ad=SimpleNamespace(proc=SimpleNamespace(poll=lambda:None),coop_players=2,
        _pso_verified_player_slots={0,1},_pso_coop_new_card={'session_id':sid,'isolated':True},
        config=SimpleNamespace(granted_permissions={Permission.MEMORY_WRITE}),
        pointers={1:0x80D01000,2:0x80D02000},objects={1:0x80F01000,2:0x80F02000},
        rows={1:[item(65542)],2:[item(2162694,'00a201')]},active={1:0x80F01000,2:0x80F02000},
        hp={1:100,2:100},floor=1,episode=1,travel=0,calls=[],equips=[],accept=True,fail_on=None,
        on_call=lambda _:None,object_drift=0)
    run={'driver':driver,'took_over':False}
    monkeypatch.setitem(tools.SESSIONS,sid,(ad,{'platform':'gamecube'}))
    monkeypatch.setitem(tools.AUTOPLAY,sid,run)
    human=[False];monkeypatch.setattr(pad_takeover,'active',lambda _:human[0])
    now=[10.]
    recovery=W.EquipmentRecovery(ad,sid,driver,lambda:driver.stopped,factory=Native,clock=lambda:now[0])
    state=dict(verified=True,phase=14,episode=1,floor=1,difficulty=0,travelling=False,
        players={slot:dict(ptr=f'{ad.pointers[slot]:08X}',hp=100) for slot in (1,2)})
    for slot in (1,2):recovery.remember(state,slot,ad.rows[slot][0])
    return SimpleNamespace(ad=ad,driver=driver,run=run,human=human,now=now,recovery=recovery,state=state)

def death(r,slot=1):
    r.state['players'][slot]['hp']=0;r.ad.hp[slot]=0
    for row in r.ad.rows[slot]:row['equipped']=False
    r.ad.active[slot]=0
    r.recovery.observe(r.state)
    r.state['players'][slot]['hp']=100;r.ad.hp[slot]=100

@pytest.mark.parametrize('slot',[1,2])
def test_observed_death_restores_only_exact_prior_item_to_correct_native_owner(rig,slot):
    r=rig;before=copy.deepcopy(r.ad.rows[3-slot]);death(r,slot)
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert r.ad.equips==[(slot,r.ad.rows[slot][0]['id'])]
    assert r.ad.rows[3-slot]==before
    assert r.recovery.status['players'][str(slot)]['verified']
    r.now[0]+=20
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert len(r.ad.equips)==1

def test_no_observed_death_does_not_undo_manual_unequip(rig):
    r=rig;r.ad.rows[1][0]['equipped']=False;r.ad.active[1]=0
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.calls

def test_unattested_starting_unarmed_does_not_choose_an_inventory_weapon(rig):
    r=rig;r.recovery.known.clear();death(r)
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.calls

@pytest.mark.parametrize('kind',['same','other','stacked'])
def test_existing_equipped_choice_is_preserved(rig,kind):
    r=rig;death(r)
    if kind=='same':r.ad.rows[1][0]['equipped']=True
    else:r.ad.rows[1].append(item(65536,'000600'))
    if kind=='stacked':r.ad.rows[1][0]['equipped']=True
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.equips and 1 not in r.recovery.pending

@pytest.mark.parametrize('fault',['missing','code','data','duplicate'])
def test_prior_item_identity_or_payload_drift_never_equips(rig,fault):
    r=rig;death(r)
    if fault=='missing':r.ad.rows[1]=[]
    elif fault=='code':r.ad.rows[1][0]['code']='000600'
    elif fault=='data':r.ad.rows[1][0]['data']='00'*20
    else:r.ad.rows[1].append(copy.deepcopy(r.ad.rows[1][0]))
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.equips

@pytest.mark.parametrize('fault',['stop','takeover','run_replaced','session_replaced','process_replaced',
    'process_ended','unmapped','epoch','paused','speed_change','permission','actor','floor','menu','dead'])
def test_revoked_or_changed_context_never_mutates_equipment(rig,monkeypatch,fault):
    r=rig;death(r)
    from gbox import tools
    if fault=='stop':r.driver.stopped=True
    elif fault=='takeover':r.human[0]=True
    elif fault=='run_replaced':r.run['driver']=object()
    elif fault=='session_replaced':monkeypatch.setitem(tools.SESSIONS,r.recovery.sid,(object(),{}))
    elif fault=='process_replaced':r.ad.proc=SimpleNamespace(poll=lambda:None)
    elif fault=='process_ended':r.ad.proc.poll=lambda:0
    elif fault=='unmapped':r.ad._pso_verified_player_slots=set()
    elif fault=='epoch':r.ad._pso_mapping_epoch=1
    elif fault=='paused':r.ad._pso_timing_paused=True
    elif fault=='speed_change':r.ad._autoplay_speed_changing=True
    elif fault=='permission':r.ad.config.granted_permissions=set()
    elif fault=='actor':r.state['players'][1]['ptr']='80D03000'
    elif fault=='floor':r.state['floor']=2
    elif fault=='dead':r.state['players'][1]['hp']=0;r.ad.hp[1]=0
    assert not r.recovery.tick(r.state,menu_allowed=fault!='menu')
    assert not r.ad.calls and not r.ad.equips

@pytest.mark.parametrize('fault',['stop','takeover','area','actor','death'])
def test_context_is_rechecked_after_inventory_before_equip(rig,fault):
    r=rig;death(r)
    def change(_):
        if fault=='stop':r.driver.stopped=True
        elif fault=='takeover':r.human[0]=True
        elif fault=='area':r.ad.floor=2
        elif fault=='actor':r.ad.pointers[1]+=0x1000
        else:r.ad.hp[1]=0
    r.ad.on_call=change
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.equips

@pytest.mark.parametrize('fn',[F_INVENTORY,F_EQUIP])
def test_uncertain_native_outcome_is_not_republished_even_if_it_did_apply(rig,fn):
    r=rig;death(r);r.ad.fail_on=fn
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert r.recovery.failure
    before=copy.deepcopy(r.ad.calls);r.ad.fail_on=None;r.now[0]+=20
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert r.ad.calls==before

@pytest.mark.parametrize('fault',['not_accepted','active_object_mismatch'])
def test_success_requires_inventory_and_active_object_readback(rig,fault):
    r=rig;death(r)
    if fault=='not_accepted':r.ad.accept=False
    else:r.ad.object_drift=4
    assert r.recovery.tick(r.state,menu_allowed=True)
    assert not r.recovery.status['players']['1']['verified']
    r.now[0]+=20;assert not r.recovery.tick(r.state,menu_allowed=True)

@pytest.mark.parametrize('which',['session','dispatcher'])
def test_busy_session_or_dispatcher_does_not_wait_or_issue_work(rig,monkeypatch,which):
    from gbox import pso_controls
    r=rig;death(r)
    fake=SimpleNamespace(acquire=lambda **_:False)
    if which=='session':monkeypatch.setattr(pso_controls,'session_lock',lambda _:fake)
    else:monkeypatch.setattr(W,'dispatcher_lock',lambda _:fake)
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.calls

def test_new_weapon_proof_cancels_prior_death_recovery(rig):
    r=rig;death(r)
    r.recovery.remember(r.state,1,item(65536,'000600'))
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert not r.ad.calls

@pytest.mark.parametrize('fault',[None,'unequipped','stacked','inactive_object'])
def test_real_weapon_range_proof_is_required_to_record_prior_item(rig,fault):
    r=rig;r.recovery.known.clear()
    if fault=='unequipped':r.ad.rows[1][0]['equipped']=False
    elif fault=='stacked':r.ad.rows[1].append(item(65536,'000600'))
    elif fault=='inactive_object':r.ad.active[1]=0
    ranges=W.WeaponRanges(r.ad,table={0x1e:dict(horizontal=180.,vertical=30.,
        horizontal_half_angle=10.,vertical_half_angle=36.)},factory=Native,recovery=r.recovery)
    result=ranges.for_player(r.state,1)
    assert result['verified']==(fault is None)
    assert (1 in r.recovery.known)==(fault is None)
    if fault=='unequipped':assert result['reason']=='No weapon equipped'

def test_uncertain_weapon_range_read_also_blocks_equipment_recovery(rig):
    r=rig;death(r);r.ad.fail_on=F_INVENTORY
    ranges=W.WeaponRanges(r.ad,table={0x1e:dict(horizontal=180.,vertical=30.,
        horizontal_half_angle=10.,vertical_half_angle=36.)},factory=Native,recovery=r.recovery)
    assert not ranges.for_player(r.state,1)['verified']
    assert ranges.failure and r.recovery.failure
    before=copy.deepcopy(r.ad.calls);r.ad.fail_on=None
    assert not r.recovery.tick(r.state,menu_allowed=True)
    assert r.ad.calls==before
