"""Read-only identity and native-emission boundaries; no synthetic HP hit proof."""
import copy
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re4_discharge_witness as D, re4_weapons as W, re4_switch as R
from gbox.mercs.core import aim_book as A

BASE, P, WEAPON, OBJ = 0x3CA7C04000, 0x5D50000000, 0x5D50100000, 0x5D50200000


class Mem:
    def __init__(self):
        self.blocks = {}
    def rd(self, at, n):
        for start, data in self.blocks.items():
            if start <= at and at+n <= start+len(data):
                return bytes(data[at-start:at-start+n])
        raise ValueError('unmapped')
    def put(self, at, fmt, *vals):
        data = struct.pack(fmt, *vals)
        for start, block in self.blocks.items():
            if start <= at and at+len(data) <= start+len(block):
                block[at-start:at-start+len(data)] = data
                return
        self.blocks[at] = bytearray(data)


def world(kind='shotgun'):
    m = Mem()
    m.blocks[P] = bytearray(0x940)
    m.blocks[WEAPON] = bytearray(0x40)
    m.blocks[OBJ] = bytearray(0x420)
    m.put(P, '<QI', BASE+D.PLAYER_CLASSES[0], 1)
    m.put(P+0x110, '<I4B', 2, 0, 6, 2, 0)
    m.put(P+0x938, '<Q', WEAPON)
    m.put(WEAPON+0x38, '<Q', OBJ)
    m.put(OBJ+0x110, '<I', 7)
    cls, item, handler = (7, 0x2C, 0x3351A0) if kind=='shotgun' else (5, 0x29, 0x3270F0)
    m.put(OBJ+0x400, '<HB', item, 3)
    m.put(BASE+W.GAME_OBJ+W.G_CLASS, '<B', cls)
    m.put(BASE+W.ITEM_MGR+W.M_EQUIPPED_ID, '<H', item)
    m.put(BASE+D.HANDLER, '<Q', BASE+handler)
    s = {'player': {'ptr': P, 'id': 2}, 'aim': {'obj': OBJ}, 'enemies': []}
    return m, s


@pytest.mark.parametrize('kind', ['shotgun', 'magnum'])
def test_actual_handler_identity_and_completion_edge(kind):
    m,s = world(kind)
    before = D.read(m, BASE, s, 10.)
    assert before['family'] == kind and before['identity'][4] == 7
    m.put(P+0x117, '<B', 1)
    after = D.read(m, BASE, s, 10.05)
    assert D.edge(before, after, 10.05)
    assert not D.edge(after, after, 10.05)


@pytest.mark.parametrize('at,fmt,val', [
    (P,'<Q',BASE+0x1110), (P+8,'<I',0), (P+0x110,'<I',3),
    (P+0x938,'<Q',0), (WEAPON+0x38,'<Q',0), (OBJ+0x400,'<H',0x29),
    (BASE+D.HANDLER,'<Q',BASE+0x333000),
    (BASE+W.GAME_OBJ+W.G_CLASS,'<B',8),
    (BASE+W.ITEM_MGR+W.M_EQUIPPED_ID,'<H',0x2D),
])
def test_wrong_or_reused_identity_is_not_evidence(at,fmt,val):
    m,s = world();m.put(at,fmt,val)
    assert D.read(m,BASE,s,10.) is None


def test_torn_native_read_is_refused():
    m,s=world();rd=m.rd
    def changing(at,n):
        raw=rd(at,n)
        if at==BASE+D.HANDLER:
            m.put(OBJ+0x110,'<I',8)
        return raw
    m.rd=changing
    assert D.read(m,BASE,s,10.) is None


@pytest.mark.parametrize('change', ['owner', 'gap', 'stale', 'entry', 'state', 'raising'])
def test_no_confirm_on_missing_fast_cycle_owner_change_or_stale_read(change):
    m,s=world();before=D.read(m,BASE,s,10.)
    after=copy.deepcopy(before);after.update(at=10.1,routine=(0,6,2,1))
    now=10.1
    if change=='owner':after['identity']=tuple(list(after['identity'][:-1])+[0x3270F0])
    if change=='gap':after['at']=now=10.5
    if change=='stale':now=11.
    if change=='entry':before['routine']=(0,6,1,1)
    if change=='state':after['object_state']=1
    if change=='raising':before['routine']=(0,6,0,0)
    assert not D.edge(before,after,now)


def test_ring_clocks_are_event_ids_and_never_subtracted_from_monotonic_time():
    bot=SimpleNamespace(stats={})
    assert D.unconfounded(bot,{},10.)
    bot.stats['ring_last_at']=1794576000.
    assert not D.unconfounded(bot,{},10.1)
    assert not D.unconfounded(bot,{},16.)
    assert D.unconfounded(bot,{},16.2)
    bot.stats['mine_darts_live']=1
    assert not D.unconfounded(bot,{},20.)
    bot.stats['mine_darts_live']=0
    assert not D.unconfounded(bot,{},25.)
    assert D.unconfounded(bot,{},26.1)


@pytest.mark.parametrize('key', ['_uc_throw', '_mine_ring'])
def test_ongoing_explosive_action_blocks_learning(key):
    bot=SimpleNamespace(stats={});setattr(bot,key,{'phase':'firing'})
    assert not D.unconfounded(bot,{},10.)


def test_confirmation_before_ledger_resolution_never_labels_blast_damage_a_gun_hit(tmp_path):
    core=A.AimCore(R.combat_profile(),{},root=tmp_path,log=False,verified_only=True)
    m,s=world();before=D.read(m,BASE,s,10.)
    enemy={'ptr':20,'pos':(0,0,5000),'hp':100,'class':0xAE7050}
    s['enemies']=[enemy]
    origin=(0,1100,0);plan=core.plan(enemy,origin,'shotgun',10.,weapon=0x2C)
    identity=before['identity']
    core.shot(10.,enemy,plan,origin=origin,at=(0,1100,5000),contact=True,los=True,
        extra={'fire_identity':identity,'aim_settled':True,'unconfounded':True})
    bot=SimpleNamespace(stats={},_native_fire_seen=before)
    bot.stats['ring_last_at']=1794576000.
    m.put(P+0x117,'<B',1);s['fire_witness']=D.read(m,BASE,s,10.05)
    D.observe(bot,s,10.05,core)
    shot=core.ledger.open[-1]
    assert shot['discharge_confirmed']
    assert shot['discharge_source']=='native_post_emission_step'
    assert shot['learning_eligible'] is False
    assert bot.stats['native_discharge_last']['impact_confirmed'] is False
    enemy['hp']=0
    core.tick(11.,[enemy])
    assert not core.book.cells


def test_missing_read_resets_edge_history():
    m,s=world();before=D.read(m,BASE,s,10.)
    bot=SimpleNamespace(stats={},_native_fire_seen=before)
    class Core:
        def confirm_discharge(self,*args,**kwargs):
            raise AssertionError('no witnessed transition')
    D.observe(bot,s,10.03,Core())
    m.put(P+0x117,'<B',1);s['fire_witness']=D.read(m,BASE,s,10.05)
    D.observe(bot,s,10.05,Core())
    assert not bot.stats.get('native_discharge_observations')


def hooked_world():
    m,s=world()
    clone=BASE+0x1700730
    ctl=SimpleNamespace(base=BASE,player=P,player_id=2,original=BASE+D.PLAYER_CLASSES[0],
        clone_address=clone,attached=lambda:True,check=lambda:None)
    m.ad=SimpleNamespace(_re4_switch_harness=ctl)
    m.put(P,'<Q',clone)
    return m,s,ctl


def test_owned_rate_hook_clone_retains_actual_discharge_evidence():
    m,s,ctl=hooked_world()
    before=D.read(m,BASE,s,10.)
    assert before is not None
    m.put(P+0x117,'<B',1)
    after=D.read(m,BASE,s,10.05)
    assert D.edge(before,after,10.05)
    assert after['identity']==before['identity']


@pytest.mark.parametrize('field,value',[
    ('base',BASE+0x1000),('player',P+0x1000),('player_id',3),
    ('original',BASE+0x1110),('clone_address',BASE+0x1700738),('attached',lambda:False),
])
def test_unknown_or_predecessor_clone_never_authorizes_discharge(field,value):
    m,s,ctl=hooked_world();setattr(ctl,field,value)
    assert D.read(m,BASE,s,10.) is None


def test_clone_without_this_reader_controller_is_unknown():
    m,s,_=hooked_world();del m.ad
    assert D.read(m,BASE,s,10.) is None


def test_clone_process_change_and_torn_original_class_are_unknown():
    m,s,ctl=hooked_world()
    def changed_process():raise RuntimeError('emulator process changed')
    ctl.check=changed_process
    assert D.read(m,BASE,s,10.) is None
    ctl.check=lambda:None
    rd=m.rd
    def changed_original(at,n):
        data=rd(at,n)
        if at==BASE+D.HANDLER:ctl.original=BASE+D.PLAYER_CLASSES[1]
        return data
    m.rd=changed_original
    assert D.read(m,BASE,s,10.) is None


@pytest.mark.parametrize('cls',D.PLAYER_CLASSES)
def test_known_character_vtables_share_the_verified_weapon_emission_handler(cls):
    m,s=world('magnum');m.put(P,'<Q',BASE+cls)
    assert D.read(m,BASE,s,10.)['family']=='magnum'
