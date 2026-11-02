from copy import deepcopy
from types import SimpleNamespace as NS
import pytest
from gbox import pso_coop as C


def harness(tmp_path, monkeypatch, *, verified=True, menu_paused=False, recover=True):
    calls=[];control={'stop':False,'reads':0};states=[]
    state={'verified':verified,'phase':14,'episode':1,'floor':1,'difficulty':0,
           'players':{n:{'ptr':f'80D0{n}000','hp':20,'hp_max':30,'room':1,'x':n*2.,'y':0.,'z':0.} for n in (1,2)},'entities':[]}
    def snapshot():
        control['reads']+=1;value=deepcopy(state);value['sample']=control['reads'];states.append(value)
        if control['reads']>6:control['stop']=True
        return value
    reader=NS(snapshot=snapshot)
    inputs=NS(release=lambda:calls.append(('release',)),check_speed=lambda:None,speed=lambda:2.,polite=False,has_polite=True)
    def tick(s):
        calls.append(('controller',s['sample']));control['stop']=True
    ranges=NS(cache={1:'old'},attempted={1:'old'},failure='retained_failure')
    engagements=NS(rows={1:'old'},recoveries=0,deferred=0)
    controller=NS(weapon_ranges=ranges,engagements=engagements,tick=tick,goals={1:'old'},approaches={1:'old'},
        damage=0,kills=0,attacks=0,blocked=0,combat_status={},town=NS(status={}),field=NS(status={}))
    class Equipment:
        def __init__(self,*args):self.status={};self.calls=0;self.failure='retained_equipment_failure'
        def observe(self,s):calls.append(('observe',s['sample']))
        def tick(self,s,menu_allowed=False):
            calls.append(('equipment',s['sample'],menu_allowed));self.calls+=1
            return recover and self.calls==1
        def clear(self,reason):calls.append(('clear',reason))
    ledger=NS(status=lambda:{},observe=lambda s:None,target=1,difficulty=0,awaiting_entry=False,boss_zero=False,pending_receipts=[])
    menu=NS(observation={},previous={},repeats=0,stalled=False)
    recovery=NS(waiting=False,observed=lambda:None)
    pending=NS(done=lambda:False,cancel=lambda:True,add_done_callback=lambda f:None)
    planner=NS(close=lambda:None)
    monkeypatch.setattr(C,'Reader',lambda ad:reader)
    monkeypatch.setattr(C,'Inputs',lambda *a,**k:inputs)
    monkeypatch.setattr(C,'Controller',lambda *a:controller)
    monkeypatch.setattr(C,'EquipmentRecovery',Equipment)
    monkeypatch.setattr(C,'Maps',lambda p:NS(save=lambda:None))
    monkeypatch.setattr(C,'Progress',lambda:ledger)
    monkeypatch.setattr(C,'Checkpoint',lambda *a,**k:NS(restore=lambda l:False,save=lambda l:None))
    monkeypatch.setattr(C,'SpeedSampler',lambda *a:NS(invalidate=lambda:None,observe=lambda s:{},failure=None))
    monkeypatch.setattr(C,'MenuProgress',lambda *a,**k:menu)
    monkeypatch.setattr(C,'buddy_context',lambda *a,**k:{'existing_buddies':True})
    monkeypatch.setattr(C,'known_menu_command',lambda *a,**k:None)
    monkeypatch.setattr(C,'observe_menu_controls',lambda *a,**k:menu_paused)
    monkeypatch.setattr(C,'TransientRecovery',lambda *a,**k:recovery)
    monkeypatch.setattr(C,'ThreadPoolExecutor',lambda *a,**k:NS(submit=lambda *a,**k:pending,shutdown=lambda **k:None))
    monkeypatch.setattr(C.solo,'Planner',lambda *a:planner)
    monkeypatch.setattr(C.solo,'wait',lambda *a:None)
    monkeypatch.setattr(C,'planner_input',lambda c:('prompt',{}))
    monkeypatch.setattr(C.mapping_continuity,'restore',lambda *a:{'probe':{},'state':states[-1]})
    monkeypatch.setattr(C.mapping_continuity,'observe',lambda *a:None)
    monkeypatch.setattr(C.mapping_continuity,'diagnostics',lambda ad:{})
    from gbox import pso_coop_access,pso_run_review
    monkeypatch.setattr(pso_coop_access,'AccessPolicy',lambda *a:NS(step=lambda *a,**k:False))
    monkeypatch.setattr(pso_run_review,'Sampler',lambda *a:NS(offer=lambda *a:None))
    ad=NS(config=NS(runtime=tmp_path),paused=False,get_frame=lambda:b'frame',_pso_coop_characters=[
        {'player':1,'name':'LYRA95','class':'RAcast'},{'player':2,'name':'AXIS92','class':'HUnewearl'}])
    stats=C.play(ad,lambda e:None,lambda:control['stop'],driver=NS(),session_id='test-session')
    return calls,controller,stats


def test_native_equipment_work_discards_old_plans_and_reobserves_before_steering(tmp_path,monkeypatch):
    calls,c,stats=harness(tmp_path,monkeypatch)
    work=next(x for x in calls if x[0]=='equipment')
    movement=next(x for x in calls if x[0]=='controller')
    assert work[2] is True and movement[1]>work[1]
    assert not c.goals and not c.approaches and not c.weapon_ranges.cache and not c.weapon_ranges.attempted
    assert not c.engagements.rows
    assert c.weapon_ranges.failure=='retained_failure'
    assert c.weapon_ranges.recovery.failure=='retained_equipment_failure'
    assert calls[-2:]==[('clear','bot_stopped'),('release',)]


@pytest.mark.parametrize('kwargs',[{'verified':False},{'menu_paused':True}])
def test_equipment_work_never_precedes_native_mapping_and_menu_authority(tmp_path,monkeypatch,kwargs):
    calls,_,_=harness(tmp_path,monkeypatch,**kwargs)
    assert any(x[0]=='observe' for x in calls)
    assert not any(x[0] in ('equipment','controller') for x in calls)
    assert calls[-2:]==[('clear','bot_stopped'),('release',)]


def test_no_native_work_does_not_skip_current_control(tmp_path,monkeypatch):
    calls,_,_=harness(tmp_path,monkeypatch,recover=False)
    work=next(x for x in calls if x[0]=='equipment');movement=next(x for x in calls if x[0]=='controller')
    assert work[1]==movement[1]
