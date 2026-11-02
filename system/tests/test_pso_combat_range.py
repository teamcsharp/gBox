from pso_owned_evidence import original_test_path
import copy
import math
from pathlib import Path
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox import pso_coop as C, pso_coop_combat as W, pso_campaign as P
from gbox.registry import Unsupported


def state(distance=9., y=0., angle=0.):
    players = {s: dict(ptr=f'80D0{s}000', kind='player', **{'class':'TObjPlayer'}, entity_id=s-1,
        room=s, x=0., y=0., z=0., heading_deg=angle, hp=100, hp_max=100) for s in (1,2)}
    enemies = [dict(ptr=f'80E0{s}000', kind='enemy', **{'class':'TObjEneBeast'}, room=s,
        x=0., y=y, z=distance, hp=100, hp_max=100) for s in (1,2)]
    return dict(verified=True, phase=14, episode=1, floor=1, difficulty=0,
                players=players, player=players[1], entities=list(players.values())+enemies)


def table():
    # Frozen exact owned PMT entries, independent of the optional local disc.
    raw={0:'41500000419000000000127d0000127d00000001',
         1:'41600000419000000000127d0000127d00000001',
         0x1e:'4334000041f000000000071c0000199900000001',
         0xa2:'41600000419000000000127d000018e300000001'}
    result={}
    for key,data in raw.items():
        horizontal,vertical,angle,elevation,_=struct.unpack('>ffIII',bytes.fromhex(data))
        result[key]=dict(horizontal=horizontal,vertical=vertical,
                        horizontal_half_angle=angle*360/65536,vertical_half_angle=elevation*360/65536)
    return result


def envelope(code, player):
    base=table()[bytes.fromhex(code)[1]]
    return dict(base, horizontal=base['horizontal']*.85, vertical=base['vertical']*.85,
        horizontal_half_angle=min(35.,base['horizontal_half_angle']*.8),
        vertical_half_angle=min(60.,base['vertical_half_angle']*.8), verified=True,
        code=code,item_id=player,player_ptr=f'80D0{player}000')


def controller(monkeypatch,tmp_path,observed,codes=None):
    clock=[100.]; sent=[]
    monkeypatch.setattr(C.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(P,'wait',lambda *_:None)
    inputs=SimpleNamespace(hold=lambda commands:sent.append(copy.deepcopy(commands)),speed=lambda:1,stopped=lambda:False)
    result=C.Controller(SimpleNamespace(snapshot=lambda:copy.deepcopy(observed)),inputs,C.Maps(tmp_path))
    if codes:
        result.weapon_ranges=SimpleNamespace(for_player=lambda state,slot:envelope(codes[slot],slot))
    return result,clock,sent


def test_owned_pmt_projectile_claw_and_unarmed_ranges_and_integrity():
    parsed=table()
    assert parsed[0]['horizontal']==13.
    assert parsed[0x1e]['horizontal']==180.
    assert parsed[0xa2]['horizontal']==14.
    assert parsed[0x1e]['horizontal_half_angle']==pytest.approx(9.99755859375)
    with pytest.raises(Unsupported): W.pmt_ranges(b'fake PMT')


def test_actual_owned_pmt_matches_frozen_cases_when_local_artifact_present():
    path=original_test_path('../pso-control-suite/owned/gc.pmt')
    parsed=W.pmt_ranges(path.read_bytes())
    assert all(parsed[key]==value for key,value in table().items())
    assert min(r['horizontal'] for r in parsed.values())==12.


def test_claw_closes_from_old_27_range_but_projectile_can_attack(monkeypatch,tmp_path):
    observed=state(26.)
    bot,_,sent=controller(monkeypatch,tmp_path,observed,{1:'001e00',2:'00a201'})
    assert bot.tick(observed)
    commands=sent[-1]
    assert (1,['a'],.12) in commands
    assert all(keys!=['a'] for slot,keys,_ in commands if slot==2)
    assert bot.combat_status[2]['range']['horizontal']==pytest.approx(11.9)
    assert bot.combat_status[1]['damage_attribution']=='shared_target_hp_only'


def test_unknown_weapon_approaches_instead_of_attacking_at_27(monkeypatch,tmp_path):
    observed=state(26.)
    bot,_,sent=controller(monkeypatch,tmp_path,observed)
    bot.tick(observed)
    assert not any(keys==['a'] for _,keys,_ in sent[-1])
    assert not bot.combat_status[1]['range']['verified']


@pytest.mark.parametrize('distance,height,angle',[(9.,30.,0.),(9.,15.,0.),(100.,0.,20.)])
def test_vertical_and_narrow_projectile_cone_never_fire(monkeypatch,tmp_path,distance,height,angle):
    observed=state(distance,height,angle)
    bot,_,sent=controller(monkeypatch,tmp_path,observed,{1:'001e00',2:'001e00'})
    bot.tick(observed)
    assert not any(keys==['a'] for batch in sent for _,keys,_ in batch)


def test_small_angular_error_turns_instead_of_rounding_to_forward(monkeypatch,tmp_path):
    observed=state(100.,angle=-12.)
    bot,_,sent=controller(monkeypatch,tmp_path,observed,{1:'001e00',2:'001e00'})
    bot.tick(observed)
    assert all(keys==['lleft'] for _,keys,_ in sent[-1])
    assert all(.02<=secs<=.12 for _,_,secs in sent[-1])


def test_stalled_turn_is_bounded_without_attacks_or_wall_learning(monkeypatch,tmp_path):
    observed=state(100.,angle=-12.)
    bot,clock,sent=controller(monkeypatch,tmp_path,observed,{1:'001e00',2:'001e00'})
    for _ in range(7):
        bot.tick(observed);clock[0]+=1.
    assert bot.cooldown[(1,observed['entities'][2]['ptr'])]>clock[0]
    assert not any(keys==['a'] for batch in sent for _,keys,_ in batch)
    assert not bot.blocked


def test_unchanged_hp_repositions_then_defers_without_wall_learning(monkeypatch,tmp_path):
    observed=state(9.)
    bot,clock,sent=controller(monkeypatch,tmp_path,observed,{1:'00a201',2:'00a201'})
    for _ in range(35):
        bot.tick(observed);clock[0]+=.8
    assert bot.engagements.recoveries>=3 and bot.engagements.deferred>=1
    assert any(any(keys!=['a'] and keys!=['l'] for _,keys,_ in batch) for batch in sent)
    assert bot.damage==0 and bot.kills==0
    assert bot.blocked==0
    for player in observed['players'].values():
        nav=bot.maps.get(observed,player)
        assert not nav.blocked and not nav.failures


def test_other_player_damage_resets_stall_but_does_not_claim_own_hit():
    current=state(); tracker=W.Engagements(); target=current['entities'][2]; bounds=dict(W.FALLBACK)
    row=tracker.observe(current,1,target,bounds,0.)
    row['attempts']=4
    target['hp']=80  # could be the buddy's attack
    updated=tracker.observe(current,1,target,bounds,3.)
    assert updated['attempts']==0 and updated['recoveries']==0
    assert tracker.recovery(updated,current['players'][1],target,bounds,3.)==(None,None)
    assert not hasattr(tracker,'hits')


def test_actor_weapon_or_area_change_cannot_reuse_stall_attempts():
    current=state(); tracker=W.Engagements(); target=current['entities'][2]
    for key,value in [('item_id',2),('code','000100')]:
        first=tracker.observe(current,1,target,dict(W.FALLBACK),1.);first['attempts']=4
        assert tracker.observe(current,1,target,dict(W.FALLBACK,**{key:value}),2.)['attempts']==0
    current['floor']=2
    assert tracker.observe(current,1,target,dict(W.FALLBACK),3.)['attempts']==0


def test_clean_live_forward_vector_preserves_positive_x_bearing():
    before=(309.192,242.545); after=(310.955,227.649)
    heading=math.degrees(math.atan2(after[0]-before[0],after[1]-before[1]))
    assert heading==pytest.approx(173.25,abs=.05)
    assert C.movement_keys(dict(x=before[0],z=before[1],heading_deg=173.2),after)==['lup']


class Native:
    def __init__(self,owner,**kwargs):self.owner=owner;self.slot=kwargs['player_index'];self.read=self._read;self.checks=0
    def check(self):
        self.checks+=1
        if getattr(self.owner,'post_error',False) and self.checks>1:raise Unsupported('Area changed after completed call')
        return self.owner.pointer
    def u32(self,address):return {W.EPISODE:0,W.FLOOR:1,W.DIFFICULTY:0,W.TRAVELLING:0}[address]
    def _read(self,address,size): return self.owner.active
    def inventory(self):
        self.owner.calls+=1
        if self.owner.error:raise RuntimeError('Publication may have completed')
        if self.owner.mutate:self.owner.active=bytes(52)
        return copy.deepcopy(self.owner.rows)
    def item_object(self,item_id):return 0x80f00000


def sampler():
    ad=SimpleNamespace(_pso_verified_player_slots={0,1},pointer=0x80d01000,
        active=struct.pack('>13I',0x80f00000,*([0]*12)), calls=0,error=False,mutate=False,
        rows=[dict(code='001e00',id=4,equipped=True)])
    clock=[100.]
    return ad,W.WeaponRanges(ad,table=table(),factory=Native,clock=lambda:clock[0]),clock


def test_native_cache_requires_unique_equipped_and_stable_active_object():
    ad,reader,clock=sampler();current=state()
    first=reader.for_player(current,1)
    assert first['verified'] and first['code']=='001e00' and ad.calls==1
    assert reader.for_player(current,1)==first and ad.calls==1
    ad.active=bytes(52)
    assert not reader.for_player(current,1)['verified'] and ad.calls==2
    ad.rows.append(dict(code='000100',id=5,equipped=True));clock[0]+=2
    assert not reader.for_player(current,1)['verified']


def test_native_transport_uncertainty_latches_and_never_retries():
    ad,reader,_=sampler();ad.error=True
    assert not reader.for_player(state(),1)['verified']
    assert reader.failure and ad.calls==1
    ad.error=False
    assert not reader.for_player(state(),1)['verified'] and ad.calls==1


def test_native_changed_equipment_midread_is_rejected():
    ad,reader,_=sampler();ad.mutate=True
    assert not reader.for_player(state(),1)['verified']


def test_completed_call_then_area_change_does_not_latch_forever():
    ad,reader,clock=sampler();ad.post_error=True
    assert not reader.for_player(state(),1)['verified'] and reader.failure is None
    ad.post_error=False;clock[0]+=2
    assert reader.for_player(state(),1)['verified']


def test_ambiguous_stacked_weapon_reads_are_rate_bounded():
    ad,reader,clock=sampler();ad.rows.append(dict(code='000100',id=5,equipped=True))
    for _ in range(10): assert not reader.for_player(state(),1)['verified']
    assert ad.calls==1
    clock[0]+=2
    assert not reader.for_player(state(),1)['verified'] and ad.calls==2


def test_native_actor_mismatch_and_pause_reject_before_call():
    ad,reader,_=sampler();ad.pointer+=0x1000
    assert not reader.for_player(state(),1)['verified'] and ad.calls==0
    ad.pointer-=0x1000;ad._pso_timing_paused=True
    assert not reader.for_player(state(),1)['verified'] and ad.calls==0


def test_shared_dispatcher_busy_never_calls_native():
    ad,reader,_=sampler();lock=W.dispatcher_lock(ad);ready=threading.Event();done=threading.Event()
    def owner():
        with lock:ready.set();done.wait(5)
    thread=threading.Thread(target=owner);thread.start();assert ready.wait(2)
    try:
        assert not reader.for_player(state(),1)['verified'] and ad.calls==0
    finally:done.set();thread.join()
