"""Native traversal exit is an observation, never an airborne mine command."""
import struct

import pytest

from gbox.mercs.titles import re5_switch as R, re5_traversal as T
from tests.test_re5_switch_aim import Guest, BASE, PLAYER, final_read_scene


ACT, VT, DTI, NAME = (0x5D75000000+i*0x10000 for i in range(4))
GETTER = BASE+0x1100


def native_scene(monkeypatch, name=T.PREFIX+'jump_down', indirect=False):
    g, snap, loc = final_read_scene(monkeypatch)
    # Real bounded ADRP x0 / ADD (or GOT LDR) x0 / RET MtDTI getter.
    page = (GETTER & ~0xFFF)+0x2000
    immediate = (page-(GETTER & ~0xFFF)) >> 12
    adrp = 0x90000000 | ((immediate & 3) << 29) | ((immediate >> 2) << 5)
    dti = DTI if indirect else page+0x80
    second = 0xF9400000 | (0x80//8 << 10) if indirect else 0x91000000 | (0x80 << 10)
    if indirect:
        g.q(page+0x80, dti)
    g.q(PLAYER+T.ACTION, ACT); g.q(ACT, VT); g.q(VT+8*R.GET_DTI_SLOT, GETTER)
    g.q(ACT+T.ACTOR_OWNER, PLAYER); g.q(ACT+T.PLAYER_OWNER, PLAYER)
    g.put(GETTER, struct.pack('<III', adrp, second, 0xD65F03C0))
    g.q(dti+R.DTI_NAME, NAME); g.put(NAME, name.encode()+b'\0')
    g.put(ACT+T.STEP, b'\x02')
    g.put(PLAYER+T.COMPLETE, struct.pack('<I', T.COMPLETE_MASK))
    return g, snap, loc


@pytest.mark.parametrize('indirect', [False, True])
def test_reader_decodes_exact_native_names_and_owns_both_action_bases(monkeypatch, indirect):
    name=T.PREFIX+'coop_jump_broad_6m_jump'
    g, snap, _ = native_scene(monkeypatch, name, indirect)
    out=T.read(g, snap)
    assert {key: out[key] for key in ('name','action','step','complete','player','generation','pos')} == {
        'name': name, 'action': ACT, 'step': 2, 'complete': True,
        'player': PLAYER, 'generation': 12, 'pos': (20., 10., 30.)}
    assert out['action_vtable'] == VT and out['layout'] == 'cpl_action' and out['scene'] is None
    assert not g.writes


@pytest.mark.parametrize('bad', ['truncated_name','unknown_name','getter','actor_owner','player_owner',
                                'slot','generation','dead','position','phase','player_index'])
def test_reader_rejects_foreign_stale_or_unknown_native_state(monkeypatch, bad):
    g, snap, loc=native_scene(monkeypatch)
    if bad=='truncated_name':g.put(NAME, b'x'*96)
    if bad=='unknown_name':g.put(NAME, (T.PREFIX+'jump_down_unsafe').encode()+b'\0')
    if bad=='getter':g.put(GETTER+8, struct.pack('<I', 0))
    if bad=='actor_owner':g.q(ACT+T.ACTOR_OWNER, PLAYER+8)
    if bad=='player_owner':g.q(ACT+T.PLAYER_OWNER, PLAYER+8)
    if bad=='slot':g.q(loc['sp']+R.P_FIRST, PLAYER+8)
    if bad=='generation':snap['player']['generation']=13
    if bad=='dead':g.put(PLAYER+R.P_HP, struct.pack('<h',0))
    if bad=='position':g.put(PLAYER+R.P_POS, struct.pack('<f',float('nan')))
    if bad=='phase':g.put(loc['gs']+R.GS_PHASE, struct.pack('<i',-1))
    if bad=='player_index':g.mercs_player_index=-1
    assert T.read(g,snap) is None and not g.writes


@pytest.mark.parametrize('field', ['generation','action','vtable','actor_owner','player_owner','slot','phase'])
def test_reader_revalidates_identity_after_native_observation(monkeypatch, field):
    g,snap,loc=native_scene(monkeypatch);rd=g.rd
    def race(address,size):
        data=rd(address,size)
        if address==PLAYER+T.COMPLETE:
            address,size,value={
                'generation':(PLAYER+0x1A00,8,13), 'action':(PLAYER+T.ACTION,8,ACT+8),
                'vtable':(ACT,8,VT+8), 'actor_owner':(ACT+T.ACTOR_OWNER,8,PLAYER+8),
                'player_owner':(ACT+T.PLAYER_OWNER,8,PLAYER+8),
                'slot':(loc['sp']+R.P_FIRST,8,PLAYER+8), 'phase':(loc['gs']+R.GS_PHASE,4,0),
            }[field]
            g.put(address,struct.pack('<Q' if size==8 else '<I',value))
        return data
    g.rd=race
    assert T.read(g,snap) is None


def test_slow_native_sample_is_unavailable(monkeypatch):
    g,snap,_=native_scene(monkeypatch)
    ticks=iter((10.,10.151));monkeypatch.setattr(T.time,'monotonic',lambda:next(ticks))
    assert T.read(g,snap) is None


def test_coop_reader_uses_selected_slot_and_native_player_index(monkeypatch):
    g,snap,loc=native_scene(monkeypatch)
    g.mercs_player_index=1;g.mercs_coop=True
    g.q(loc['sp']+R.P_FIRST,PLAYER+0x10000)
    g.q(loc['sp']+R.P_FIRST+8,PLAYER);g.put(PLAYER+R.P_INDEX,b'\x01')
    assert T.read(g,snap)['player']==PLAYER
    g.put(PLAYER+R.P_INDEX,b'\x00')
    assert T.read(g,snap) is None


def observer(monkeypatch):
    snap={'mercenaries_phase':R.PHASE_PLAYING,'player':{'ptr':PLAYER,'generation':12,'hp':800}}
    stats={'round_evidence_id':'round-a','screen':'playing'}
    latest=[None]
    monkeypatch.setattr(T,'read',lambda *args:latest[0])
    def see(now,name='jump_down',pos=(0.,0.,0.),complete=False,action=None):
        latest[0]=None if name is None else {'name':T.PREFIX+name,'step':0,'complete':complete,
            'action':action if action is not None else ACT+(0 if T.PREFIX+name in T.TRAVERSALS else 0x100),
            'pos':pos,'player':PLAYER,'generation':12}
        return T.observe(None,snap,stats,now)
    return see,snap,stats


@pytest.mark.parametrize('native,kind', [('jump_down','drop'),('jump_broad_3m','jump'),
    ('fence','vault'),('ladder_v_climb','ladder'),('climb_cliff','climb')])
def test_one_mine_event_after_native_exit_and_stable_landing(monkeypatch,native,kind):
    see,snap,stats=observer(monkeypatch)
    assert see(1.,native,(0.,300.,0.)) is None
    assert see(1.4,native,(0.,50.,80.),complete=True) is None
    assert see(1.5,'run',(0.,0.,100.)) is None
    assert see(1.65,'run',(0.,0.,150.)) is None
    event=see(1.75,'run',(0.,0.,200.))
    assert event['id']==1 and event['kind']=='traversal' and event['traversal']==kind
    assert event['pos']==[0.,0.,200.] and event['completion_flag_seen']
    assert event['owner']==['round-a',PLAYER,12]
    assert see(1.8,'run',(0.,0.,220.))==event
    assert stats['traversal_completions']==1 and '_re5_traversal' not in stats


def test_complete_flag_alone_never_places_airborne_mine(monkeypatch):
    see,_,stats=observer(monkeypatch)
    for i in range(12):
        assert see(i*.15,'jump_down',(0.,400.-i*10,0.),complete=True) is None
    assert 'traversal_mine_event' not in stats


def test_landing_requires_stable_height_and_latest_position(monkeypatch):
    see,_,_=observer(monkeypatch)
    see(1.,pos=(0.,400.,0.));see(1.2,'run',(0.,200.,0.))
    assert see(1.45,'run',(0.,100.,0.)) is None
    assert see(1.7,'run',(0.,0.,0.)) is None
    event=see(1.95,'run',(0.,0.,100.))
    assert event['pos']==[0.,0.,100.]


@pytest.mark.parametrize('interruption',['unavailable','death','operator','round','generation','menu','closed','clock_gap','clock_backwards'])
def test_interruption_cannot_be_reinterpreted_as_completed_traversal(monkeypatch,interruption):
    see,snap,stats=observer(monkeypatch)
    see(1.,pos=(0.,300.,0.))
    if interruption=='unavailable':see(1.1,None)
    if interruption=='death':snap['player']['hp']=0;see(1.1);snap['player']['hp']=800
    if interruption=='operator':stats['operator_control']=True;see(1.1);stats['operator_control']=False
    if interruption=='round':stats['round_evidence_id']='round-b'
    if interruption=='generation':snap['player']['generation']=13
    if interruption=='menu':snap['mercenaries_phase']=-1;see(1.1);snap['mercenaries_phase']=R.PHASE_PLAYING
    if interruption=='closed':stats['round_evidence_closed']=True;see(1.1);stats['round_evidence_closed']=False
    now=2.1 if interruption=='clock_gap' else .5 if interruption=='clock_backwards' else 1.2
    assert see(now,'run',(0.,0.,100.)) is None
    assert see(now+.3,'run',(0.,0.,100.)) is None
    assert 'traversal_mine_event' not in stats


def test_in_place_cancel_or_same_native_object_cannot_emit(monkeypatch):
    see,_,_=observer(monkeypatch)
    see(1.);see(1.2,'wait');assert see(1.5,'wait') is None
    see(2.);see(2.2,'run',(0.,0.,100.),action=ACT)
    assert see(2.5,'run',(0.,0.,150.)) is None


def test_missing_single_frame_completion_bit_does_not_miss_valid_native_exit(monkeypatch):
    see,_,_=observer(monkeypatch)
    see(1.,pos=(0.,300.,0.));see(1.2,'run',(0.,0.,0.))
    event=see(1.5,'run',(0.,0.,100.))
    assert event and event['completion_flag_seen'] is False


def test_event_expires_and_cannot_cross_player_lifetimes(monkeypatch):
    see,snap,stats=observer(monkeypatch)
    see(1.,pos=(0.,300.,0.));see(1.2,'run');event=see(1.5,'run')
    assert event
    assert see(4.6,'run')==event  # ordinary three-second native request gap can finish
    assert see(6.6,'run') is None
    stats['traversal_mine_event']=event;snap['player']['generation']=13
    assert see(1.6,'run') is None and 'traversal_mine_event' not in stats


def test_second_distinct_traversal_has_new_id_and_landing_anchor(monkeypatch):
    see,_,_=observer(monkeypatch)
    see(1.,pos=(0.,300.,0.));see(1.2,'run');first=see(1.5,'run')
    see(2.,'fence');see(2.2,'run',(200.,0.,0.));second=see(2.5,'run',(250.,0.,0.))
    assert second['id']==first['id']+1 and second['traversal']=='vault'
    assert second['pos']==[250.,0.,0.]


@pytest.mark.parametrize('next_action', [None, 'ladder_v_climb', 'jump_down', 'fence'])
def test_uncommitted_landing_event_is_invalidated_by_lost_grounding(monkeypatch, next_action):
    see, _, stats = observer(monkeypatch)
    see(1., pos=(0., 300., 0.)); see(1.2, 'run')
    assert see(1.5, 'run')
    assert see(1.6, next_action) is None
    assert 'traversal_mine_event' not in stats


# Frozen addresses from the 674c8828 ELF registrations/allocators/vtables,
# independently specified rather than generated from the reader's allowlist.
OBJECT_LAYOUTS = [
    ('cOmWindowEvent_dive', 0x1C222E0, 0x1D700A0, 0x1D6FF18, 'uOmWindow', 0x38, 1),
    ('cOmLadderEvent_climb', 0x1BDF3C0, 0x1D64C00, 0x1D64928, 'uOmLadder', 0x28, 3),
    ('cOmLadderEventV_climb', 0x1BDF350, 0x1D64C38, 0x1D64960, 'uOmLadderV', 0x28, 2),
]
SCENE, SCENE_VT, SCENE_NAME = ACT+0x80000, BASE+0x1900000, NAME+0x10000


def put_rtti(g, obj, vt, getter, dti, name_address, name):
    delta = ((dti & ~0xFFF)-(getter & ~0xFFF)) >> 12
    imm = delta & ((1 << 21)-1)
    adrp = 0x90000000 | ((imm & 3) << 29) | ((imm >> 2) << 5)
    add = 0x91000000 | ((dti & 0xFFF) << 10)
    g.q(obj, vt); g.q(vt+8*R.GET_DTI_SLOT, getter)
    g.put(getter, struct.pack('<III', adrp, add, 0xD65F03C0))
    g.q(dti+R.DTI_NAME, name_address); g.put(name_address, name.encode()+b'\0')


def object_scene(monkeypatch, layout=OBJECT_LAYOUTS[0], derived=False):
    g,snap,loc=native_scene(monkeypatch)
    name,vt,dti,scene_dti,scene_name,step_off,terminal=layout
    put_rtti(g,ACT,BASE+vt,GETTER,BASE+dti,NAME,name)
    child_dti=BASE+0x1D70148 if derived else BASE+scene_dti
    put_rtti(g,SCENE,SCENE_VT,GETTER+0x100,child_dti,SCENE_NAME,'uOm1103' if derived else scene_name)
    if derived:g.q(child_dti+0x20,BASE+scene_dti)
    g.q(SCENE+0x1A00,77);g.put(SCENE+0x10,struct.pack('<I',1))
    g.q(ACT+0x18,SCENE);g.q(ACT+0x30,5)  # Native event layout, deliberately not PLAYER.
    g.put(ACT+0x2C,struct.pack('<I',1));g.put(ACT+step_off,struct.pack('<I',terminal))
    g.put(PLAYER+0x8FA,b'\x04')
    return g,snap,loc


@pytest.mark.parametrize('layout',OBJECT_LAYOUTS)
def test_frozen_native_object_layout_owns_player_and_live_scene(monkeypatch,layout):
    g,snap,_=object_scene(monkeypatch,layout)
    out=T.read(g,snap)
    assert out['name']==layout[0] and out['step']==layout[-1] and out['complete']
    assert out['action_vtable']==BASE+layout[1] and out['layout']=='om_event'
    assert out['scene']['ptr']==SCENE and out['scene']['generation']==77
    assert not g.writes


@pytest.mark.parametrize('index,getter_rva,code',[
    (0,0x786A60,'40af00d000800291c0035fd6'),
    (1,0x6DFB80,'20b400b000003091c0035fd6'),
    (2,0x6DEB00,'20b400d000e03091c0035fd6'),
])
def test_exact_getter_bytes_from_pinned_elf_resolve_native_event_metadata(monkeypatch,index,getter_rva,code):
    layout=OBJECT_LAYOUTS[index]
    g,snap,_=object_scene(monkeypatch,layout)
    g.q(BASE+layout[1]+8*R.GET_DTI_SLOT,BASE+getter_rva)
    g.put(BASE+getter_rva,bytes.fromhex(code))
    assert T.read(g,snap)['name']==layout[0]


def test_scene_subclass_requires_bounded_native_parent_chain(monkeypatch):
    g,snap,_=object_scene(monkeypatch,derived=True)
    assert T.read(g,snap)['scene']['name']=='uOm1103'
    g.q(BASE+0x1D70148+0x20,BASE+0x1D70148)
    assert T.read(g,snap) is None


@pytest.mark.parametrize('bad',['scene_owner','scene_is_player','scene_phase','scene_generation',
    'wrong_scene_type','wrong_event_vtable','wrong_event_dti','unknown_event_name','actor_type','status','step'])
def test_object_layout_refuses_unproved_or_foreign_ownership(monkeypatch,bad):
    g,snap,_=object_scene(monkeypatch)
    if bad=='scene_owner':g.q(ACT+0x18,SCENE+8)
    if bad=='scene_is_player':g.q(ACT+0x18,PLAYER)
    if bad=='scene_phase':g.put(SCENE+0x10,struct.pack('<I',3))
    if bad=='scene_generation':g.q(SCENE+0x1A00,0)
    if bad=='wrong_scene_type':put_rtti(g,SCENE,SCENE_VT,GETTER+0x100,BASE+0x1D64928,SCENE_NAME,'uOmLadder')
    if bad=='wrong_event_vtable':g.q(ACT,VT);g.q(VT+8*R.GET_DTI_SLOT,GETTER)
    if bad=='wrong_event_dti':put_rtti(g,ACT,BASE+0x1C222E0,GETTER,BASE+0x1D700D8,NAME,'cOmWindowEvent_dive')
    if bad=='unknown_event_name':g.put(NAME,b'cOmWindowEvent_emBang\0')
    if bad=='actor_type':g.put(ACT+0x34,struct.pack('<I',3))
    if bad=='status':g.put(ACT+0x2C,struct.pack('<I',4))
    if bad=='step':g.put(ACT+0x38,struct.pack('<I',9))
    assert T.read(g,snap) is None and not g.writes


@pytest.mark.parametrize('field',['scene_owner','scene_vtable','scene_generation','scene_phase',
                                'scene_parent','event_rtti','event_phase','event_status','actor_type'])
def test_object_layout_rechecks_scene_lifetime_and_action_state(monkeypatch,field):
    g,snap,_=object_scene(monkeypatch,derived=True);rd=g.rd
    def race(address,size):
        data=rd(address,size)
        if address==PLAYER+R.P_HP:
            address,size,value={
                'scene_owner':(ACT+0x18,8,SCENE+8),
                'scene_vtable':(SCENE,8,SCENE_VT+8),
                'scene_generation':(SCENE+0x1A00,8,78),
                'scene_phase':(SCENE+0x10,4,3),
                'scene_parent':(BASE+0x1D70148+0x20,8,0),
                'event_rtti':(BASE+0x1D700A0+R.DTI_NAME,8,SCENE_NAME),
                'event_phase':(ACT+0x38,4,0),
                'event_status':(ACT+0x2C,4,4),
                'actor_type':(ACT+0x34,4,1),
            }[field]
            g.put(address,struct.pack('<Q' if size==8 else '<I',value))
        return data
    g.rd=race
    assert T.read(g,snap) is None


@pytest.mark.parametrize('layout',OBJECT_LAYOUTS)
def test_object_completion_uses_native_terminal_phase_and_animation_not_player_flag(monkeypatch,layout):
    g,snap,_=object_scene(monkeypatch,layout)
    g.put(PLAYER+T.COMPLETE,struct.pack('<I',0))
    assert T.read(g,snap)['complete']
    g.put(PLAYER+0x8FA,b'\0')
    assert not T.read(g,snap)['complete']
    g.put(PLAYER+T.COMPLETE,struct.pack('<I',T.COMPLETE_MASK))
    assert not T.read(g,snap)['complete']


def test_native_active_fact_has_fresh_owner_action_and_scene_and_clears_on_menu(monkeypatch):
    g,snap,_=object_scene(monkeypatch)
    stats={'round_evidence_id':'round-a','screen':'playing'}
    T.observe(g,snap,stats,10.)
    fact=stats['traversal_observation']
    assert fact['active'] and fact['owner']==['round-a',PLAYER,12] and fact['at']==10.
    assert fact['action']==ACT and fact['action_vtable']==BASE+0x1C222E0
    assert fact['sampled_at'] and fact['scene']['ptr']==SCENE
    snap['mercenaries_phase']=-1
    T.observe(g,snap,stats,10.1)
    assert not stats['traversal_observation']['active']


@pytest.mark.parametrize('completion',[False,True])
def test_object_event_requires_native_completion_before_grounded_exit(monkeypatch,completion):
    see,snap,stats=observer(monkeypatch)
    latest={'name':'cOmWindowEvent_dive','action':ACT,'step':1,'complete':completion,
            'player':PLAYER,'generation':12,'pos':(0.,200.,0.),'scene':{'ptr':SCENE,'generation':77}}
    monkeypatch.setattr(T,'read',lambda *args:latest)
    assert T.observe(None,snap,stats,1.) is None
    latest.update(name=T.PREFIX+'run',action=ACT+0x100,pos=(0.,0.,100.),scene=None)
    assert T.observe(None,snap,stats,1.2) is None
    event=T.observe(None,snap,stats,1.5)
    assert bool(event)==completion
    if event:assert event['scene']=={'ptr':SCENE,'generation':77} and event['completion_flag_seen']


def test_object_scene_reuse_resets_completion_witness(monkeypatch):
    see,snap,stats=observer(monkeypatch)
    latest={'name':'cOmWindowEvent_dive','action':ACT,'step':1,'complete':True,
            'player':PLAYER,'generation':12,'pos':(0.,200.,0.),'scene':{'ptr':SCENE,'generation':77}}
    monkeypatch.setattr(T,'read',lambda *args:latest)
    T.observe(None,snap,stats,1.)
    latest.update(complete=False,scene={'ptr':SCENE,'generation':78})
    T.observe(None,snap,stats,1.1)
    latest.update(name=T.PREFIX+'run',action=ACT+0x100,pos=(0.,0.,100.),scene=None)
    T.observe(None,snap,stats,1.2)
    assert T.observe(None,snap,stats,1.5) is None
