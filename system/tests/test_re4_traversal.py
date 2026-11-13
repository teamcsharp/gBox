import struct

import pytest

from gbox.mercs.titles import re4_switch as R, re4_traversal as T
from gbox.mercs import grenade_ring as GR
from tests.test_re5_switch_aim import Guest
from tests.test_re4_switch_game_state import PLAYING, merc_bytes, cd_bytes


BASE, PLAYER = R.KNOWN_BASES[0], 0x5D55000000


def native_scene():
    g=Guest();pg=BASE+R.PG_OBJ
    g.put(BASE+T.DISPATCH,T.DISPATCH_BYTES);g.q(BASE+T.TABLE_GOT,BASE+T.TABLE)
    g.put(BASE+T.TABLE,struct.pack('<21Q',*(BASE+h if h else 0 for h in T.HANDLERS)))
    g.q(BASE+R.S_PLAYER,PLAYER);g.q(BASE+R.S_PLAYER_2,PLAYER)
    g.q(PLAYER,BASE+0xB0C0A0);g.put(PLAYER+R.U_ID,struct.pack('<I',7))
    g.put(PLAYER+R.U_POS,struct.pack('<3f',100.,2000.,300.))
    g.put(PLAYER+T.ROUTINE,b'\0\x10\x03\0')
    g.put(BASE+R.PLAYER_LIFE-2,struct.pack('<3H',0,900,1000))
    g.q(BASE+R.PG_PTR_VAR,pg);g.put(pg+R.PG_STEP,b'\x03')
    g.put(pg+R.PG_SYSTEM,struct.pack('<I',PLAYING['system']))
    g.put(pg+R.PG_STOP,struct.pack('<I',PLAYING['stop']))
    g.put(pg+R.PG_SPEED,struct.pack('<f',.5))
    g.put(pg+R.PG_STATUS,struct.pack('<4I',*PLAYING['status']))
    g.put(BASE+R.MERC_WORK,merc_bytes(PLAYING));g.put(BASE+R.COUNTDOWN,cd_bytes(PLAYING))
    p=R.player_unit(g,BASE);p['hp']=900
    return g,{'module_base':BASE,'player':p,'game':R.game_state(g,BASE)}


def test_native_dispatch_table_and_real_player_reader_identify_ladder():
    g,snap=native_scene();out=T.read(g,snap)
    assert out['routine']==(0,16,3,0) and out['handler']==0x30F380
    assert out['kind']=='ladder' and out['pos']==(100.,2000.,300.)
    assert not g.writes


@pytest.mark.parametrize('bad',['dispatch','got','table','slot','generation','foreign_vtable','damage',
                               'object_action','unknown_handler','dead','nan','menu','stage'])
def test_reader_rejects_wrong_build_owner_and_nontraversal_native_states(bad):
    g,snap=native_scene()
    if bad=='dispatch':g.put(BASE+T.DISPATCH,b'\0'*4)
    if bad=='got':g.q(BASE+T.TABLE_GOT,BASE+T.TABLE+8)
    if bad=='table':g.q(BASE+T.TABLE+16*8,BASE+0x30E170)
    if bad=='slot':g.q(BASE+R.S_PLAYER,0);g.q(BASE+R.S_PLAYER_2,0)
    if bad=='generation':snap['player']['id']=8
    if bad=='foreign_vtable':g.q(PLAYER,BASE+R.ENEMY_CLASSES[0])
    if bad=='damage':g.put(PLAYER+T.ROUTINE,b'\1\x10\3\0')
    if bad=='object_action':g.put(PLAYER+T.ROUTINE,b'\4\0\0\0')
    if bad=='unknown_handler':g.put(PLAYER+T.ROUTINE,b'\0\x0a\0\0')
    if bad=='dead':g.put(BASE+R.PLAYER_LIFE,struct.pack('<H',0))
    if bad=='nan':g.put(PLAYER+R.U_POS,struct.pack('<f',float('nan')))
    if bad=='menu':g.put(BASE+R.PG_OBJ+R.PG_SYSTEM,struct.pack('<I',0))
    if bad=='stage':snap['game']['stage']=99
    assert T.read(g,snap) is None and not g.writes


@pytest.mark.parametrize('bad',['generation','routine','vtable','slot','phase','stage'])
def test_reader_rechecks_native_lifetime_and_routine_after_position(bad):
    g,snap=native_scene();rd=g.rd
    def race(a,n):
        out=rd(a,n)
        if a==PLAYER+R.U_POS and n==12:
            if bad=='generation':g.put(PLAYER+R.U_ID,struct.pack('<I',8))
            if bad=='routine':g.put(PLAYER+T.ROUTINE,b'\0\0\0\0')
            if bad=='vtable':g.q(PLAYER,BASE+0xB09A60)
            if bad=='slot':g.q(BASE+R.S_PLAYER,0);g.q(BASE+R.S_PLAYER_2,0)
            if bad=='phase':g.put(BASE+R.PG_OBJ+R.PG_SYSTEM,struct.pack('<I',0))
            if bad=='stage':g.put(BASE+R.MERC_WORK+R.MW_STAGE,struct.pack('<I',2))
        return out
    g.rd=race
    assert T.read(g,snap) is None


def test_native_read_retains_150ms_budget(monkeypatch):
    g,snap=native_scene();ticks=iter((10.,10.151))
    monkeypatch.setattr(T.time,'monotonic',lambda:next(ticks))
    assert T.read(g,snap) is None


def observer(monkeypatch):
    snap={'player':{'ptr':PLAYER,'id':7,'hp':900,'pos':[0,0,0]},'game':{'phase':'playing'}}
    stats={'round_evidence_id':'round-a','screen':'playing','ring_last_at':10}
    rows=[None];monkeypatch.setattr(T,'read',lambda *args:rows[0])
    def see(now,r1=16,pos=(0.,2000.,0.),phase='playing'):
        rows[0]=None if r1 is None else {'routine':(0,r1,1,0),'handler':T.HANDLERS[r1],
            'kind':T.TRAVERSALS.get(r1),'pos':pos,'phase':phase,'stage':3,'mode':2}
        return T.observe(None,snap,stats,now)
    return see,snap,stats


@pytest.mark.parametrize('r1,kind',sorted(T.TRAVERSALS.items()))
def test_landing_after_each_native_traversal_emits_once_in_mm(monkeypatch,r1,kind):
    see,snap,stats=observer(monkeypatch)
    assert see(1.,r1) is None
    assert see(1.4,r1,(0.,1000.,100.)) is None
    assert see(1.6,3,(0.,0.,300.)) is None
    event=see(1.9,3,(0.,0.,1200.))
    assert event['traversal']==kind and event['pos']==[0.,0.,1200.] and event['units']=='mm'
    assert event['owner']==['round-a',PLAYER,7] and event['native_handler']==T.HANDLERS[r1]
    assert see(2.,3,(0.,0.,1300.)) is None
    assert stats['traversal_completions']==1
    assert T.claim_ring(snap,stats,2.)['kind']=='hand'
    assert T.claim_ring(snap,stats,2.1) is None


def test_landing_must_stop_descending_and_no_ring_while_native_traversal_runs(monkeypatch):
    see,snap,stats=observer(monkeypatch)
    for t in (1.,1.3,1.6,1.9):
        assert see(t,14,(0.,3000.-t*500,0.)) is None
        assert T.claim_ring(snap,stats,t) is None
    see(2.1,3,(0.,600.,0.));assert see(2.4,3,(0.,300.,0.)) is None
    assert see(2.7,3,(0.,0.,0.)) is None
    assert see(3.,3,(0.,0.,1000.))


@pytest.mark.parametrize('cause',['unavailable','damage','death','menu','round','generation','operator','gap','clock','closed'])
def test_interrupted_traversal_cannot_become_a_landing_event(monkeypatch,cause):
    see,snap,stats=observer(monkeypatch);see(1.)
    if cause=='unavailable':see(1.1,None)
    if cause=='damage':see(1.1,None)
    if cause=='death':snap['player']['hp']=0;see(1.1);snap['player']['hp']=900
    if cause=='menu':snap['game']['phase']='intro';see(1.1);snap['game']['phase']='playing'
    if cause=='round':stats['round_evidence_id']='round-b'
    if cause=='generation':snap['player']['id']=8
    if cause=='operator':stats['operator_control']=True;see(1.1);stats['operator_control']=False
    if cause=='closed':stats['round_evidence_closed']=True;see(1.1);stats['round_evidence_closed']=False
    now=2.2 if cause=='gap' else .5 if cause=='clock' else 1.2
    assert see(now,3,(0.,0.,0.)) is None
    assert see(now+.3,3,(0.,0.,1000.)) is None
    assert 'traversal_ring_event' not in stats


def landed(monkeypatch):
    see,snap,stats=observer(monkeypatch)
    see(10.);see(10.2,3,(0.,0.,0.));see(10.5,3,(0.,0.,1000.))
    return see,snap,stats


def test_pending_landing_defense_never_fires_during_a_new_jump(monkeypatch):
    see,snap,stats=landed(monkeypatch)
    see(10.6,19,(0.,1000.,1000.))
    assert T.claim_ring(snap,stats,10.6) is None


@pytest.mark.parametrize('interruption', [None, 19, 16])
def test_old_landing_event_cannot_fire_on_first_ground_sample_after_interruption(monkeypatch, interruption):
    see, snap, stats = landed(monkeypatch)
    see(10.6, interruption, (0., 1000., 1000.))
    see(10.7, 3, (0., 0., 1100.))
    assert T.claim_ring(snap, stats, 10.7) is None
    assert 'traversal_ring_event' not in stats


def test_expired_event_or_stale_ground_observation_cannot_dispatch(monkeypatch):
    see,snap,stats=landed(monkeypatch)
    assert T.claim_ring(snap,stats,11.1) is None
    see(16.,3,(0.,0.,1000.))
    assert T.claim_ring(snap,stats,16.) is None


def test_engine_tick_preceding_snapshot_does_not_block_fresh_ground_observation(monkeypatch):
    see,snap,stats=landed(monkeypatch)
    see(10.7,3,(0.,0.,1100.))
    assert T.claim_ring(snap,stats,10.65)['count']==5


class Ring:
    def __init__(self,state='confirmed'):self.calls=[];self.state=state
    def grenade_ring(self,kind,**kwargs):
        self.calls.append((kind,kwargs))
        return {'state':self.state,'kind':kind,'verified':False,'requested':5,'detonated':5 if self.state=='confirmed' else 2,'self_damage':0}


@pytest.mark.parametrize('result',['confirmed','uncertain'])
def test_landing_uses_native_hand_ring_once_and_preserves_receipt_truth(monkeypatch,result):
    _,snap,stats=landed(monkeypatch);ring=Ring(result)
    step=GR.control(None,{'map_id':R.MAP_ID,'units_per_cm':10},ring=ring)
    out=step(snap,stats,10.5)
    assert out['attempted'] and out['fired']==(result=='confirmed')
    assert ring.calls[0][0]=='hand' and ring.calls[0][1]['count']==5
    assert ring.calls[0][1]['ripple_ms']==0 and not ring.calls[0][1]['allow_unverified']
    assert stats['traversal_ring_requested']==1
    assert stats['traversal_ring_receipt']['state']==result and stats['traversal_ring_receipt']['verified'] is False
    assert stats.get('traversal_rings_confirmed',0)==(result=='confirmed')
    step(snap,stats,10.6)
    assert len(ring.calls)==1


def test_grab_damage_and_disabled_policy_keep_priority_over_landing(monkeypatch):
    see,snap,stats=landed(monkeypatch);ring=Ring()
    step=GR.control(None,{'map_id':R.MAP_ID},ring=ring)
    snap['game']['phase']='grabbed'
    assert step(snap,stats,10.5)['kind']=='flash'
    assert not stats.get('traversal_ring_requested')
    snap['game']['phase']='playing';stats['ring']={'enabled':False}
    assert not step(snap,stats,10.6).get('attempted')
    assert not stats.get('traversal_ring_requested')


def test_changed_round_never_replays_same_player_id_landing(monkeypatch):
    _,snap,stats=landed(monkeypatch);stats['round_evidence_id']='round-b'
    assert T.claim_ring(snap,stats,10.6) is None


def test_refused_input_release_has_no_native_effect_or_success_claim(monkeypatch):
    _,snap,stats=landed(monkeypatch);ring=Ring()
    step=GR.control(None,{'map_id':R.MAP_ID},ring=ring)
    out=step(snap,stats,10.5,hold=lambda keys:False)
    assert not out['fire'] and not ring.calls
    assert stats['traversal_ring_receipt']['state']=='refused'
    assert stats['traversal_ring_receipt']['detonated']==0
    assert not stats.get('traversal_rings_confirmed')
    assert not step(snap,stats,10.6).get('attempted')


def test_unexpected_ring_exception_is_uncertain_and_never_replayed(monkeypatch):
    _,snap,stats=landed(monkeypatch);calls=[]
    def fail(*args,**kwargs):calls.append(1);raise RuntimeError('unknown native outcome')
    monkeypatch.setattr(GR,'fire',fail)
    step=GR.control(None,{'map_id':R.MAP_ID},ring=Ring())
    step(snap,stats,10.5);step(snap,stats,10.6)
    assert calls==[1] and stats['traversal_ring_receipt']['state']=='uncertain'
    assert not stats.get('traversal_rings_confirmed')


def test_driver_observes_on_snapshot_even_when_later_prompt_skips_bot(monkeypatch):
    g,snap=native_scene();driver=R.RE4Switch(clock=lambda:10.);driver.stats={'round_evidence_id':'round-a'}
    calls=[]
    monkeypatch.setattr(R,'snapshot',lambda m:snap)
    monkeypatch.setattr(R.re4_nav,'attach',lambda s:s)
    monkeypatch.setattr(R,'watch_into',lambda *a:None)
    monkeypatch.setattr(T,'observe',lambda *a:calls.append(a))
    assert driver.snapshot(g) is snap
    assert calls==[(g,snap,driver.stats,10.)]
