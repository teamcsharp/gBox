"""An explicit adoption can park its exact manual launch, but cannot acquire another owner."""
import random
from types import SimpleNamespace

import pytest

from gbox import autoplay_resume, mercmode as M, screensaver as S
from gbox.store import Store
from tests.test_mercmode import adoptable, ops


@pytest.fixture
def adopted(tmp_path):
    original,w,session,telemetry,now=adoptable()
    store=Store(tmp_path)
    for (kind,key),value in original.docs.items(): store.put(kind,key,value)
    w['features']=[M.WARM_FEATURE]
    M.configure(store,w['name'],{'keep_warm':2,'rounds_per_title':5})
    calls=[]
    def submit(req,actor,origin):
        now[0]+=.1
        j={'id':'own'+str(len(calls)),'tool':req.tool,'input':req.input,'actor':actor,
           'state':'queued','created':now[0],'require_worker':req.require_worker,'agent_use':req.agent_use}
        calls.append(j);store.put('job',j['id'],j);return j
    saver=S.Screensaver(store,SimpleNamespace(runs=lambda **kw:[]),submit,lambda:[w],rng=random.Random(2))
    run=M.adopt_current(store,w,session,telemetry,now=now[0])
    yield SimpleNamespace(store=store,w=w,session=session,telemetry=telemetry,now=now,calls=calls,saver=saver,run=run)
    store.db.close()


def park(e):
    e.saver._park(e.w,e.run,e.now[0]+1,'verified native round boundary: next MercMode title')
    return M.warm_pool(e.store,e.w['name'])['re5']


def test_explicit_manual_launch_parks_and_resumes_after_active_run_is_removed(adopted):
    e=adopted;sid=e.session['session_id']
    assert e.saver._warm_owned(e.w,e.run,[e.session])==e.session
    row=park(e)
    assert not e.store.get(S.STATE,e.w['name'])
    assert row['warm_adoption']==e.run['warm_adoption'] and row['job']=='current'
    assert ops(e.calls,sid,'pause') and not ops(e.calls,sid,'stop_game')
    assert e.saver._warm_owned(e.w,row,[e.session])==e.session
    pause=ops(e.calls,sid,'pause')[-1]
    e.store.put('job',pause['id'],pause|{'state':'succeeded','worker_id':e.w['id']})
    pick={'title':'re5','name':'RE5','game_id':e.session['game_id'],'map_id':'BLUS30491'}
    assert 'kept warm' in e.saver._resume_warm(e.w,pick,M.settings(e.store,e.w['name']),e.now[0]+2)
    resumed=e.store.get(S.STATE,e.w['name'])
    assert resumed['warm_adoption']==row['warm_adoption'] and resumed['job']=='current'
    resume=ops(e.calls,sid,'resume')[-1]
    e.store.put('job',resume['id'],resume|{'state':'succeeded','worker_id':e.w['id']})
    e.saver._advance(e.w,resumed,S.settings(e.store),[e.session],e.now[0]+3)
    playing=e.store.get(S.STATE,e.w['name'])
    assert playing['phase']=='playing' and e.calls[-1]['tool']=='autoplay' and e.calls[-1]['input']['op']=='start'
    assert e.saver._warm_owned(e.w,playing,[e.session])==e.session
    assert not any(c['tool']=='launch_game' for c in e.calls)
    assert not ops(e.calls,sid,'stop_game')


@pytest.mark.parametrize('change',['missing_receipt','forged_proof','pid','started','adapter','worker','game',
    'replaced','human_label','handoff','new_start','new_stop','manual_pause','manual_reset'])
def test_revoked_adoption_neither_parks_nor_stops_a_human_or_replaced_game(adopted,change):
    e=adopted;sid=e.session['session_id'];session=dict(e.session)
    if change=='missing_receipt':e.store.delete(M.ADOPTION,sid)
    elif change=='forged_proof':e.run['warm_adoption']='untrusted'
    elif change=='pid':session['detail']={'pid':9999}
    elif change=='started':session['started']+=1
    elif change=='adapter':session['adapter']='other'
    elif change=='worker':e.w=e.w|{'id':'another-worker'}
    elif change=='game':session['game_id']='other'
    elif change=='replaced':session['replaced_by']='w1-new'
    elif change=='human_label':e.store.put('slabel',sid,{'owner':'you'})
    elif change=='handoff':e.store.put(autoplay_resume.HANDOFF,sid,{'source_job_id':'active'})
    elif change in ('new_start','new_stop'):
        e.store.put('job','new-control',{'id':'new-control','tool':'autoplay','state':'succeeded','created':e.now[0]+1,
            'actor':'operator','require_worker':e.w['id'],'worker_id':e.w['id'],
            'input':{'session_id':sid,'op':change[4:]}})
    else:
        e.store.put('job','manual',{'id':'manual','tool':'session_op','state':'queued','created':e.now[0]+1,
            'actor':'operator','require_worker':e.w['id'],'input':{'session_id':sid,'op':change[7:]}})
    e.store.put('session',sid,session)
    assert e.saver._warm_owned(e.w,e.run,[session]) is None
    e.saver._park(e.w,e.run,e.now[0]+2,'boundary')
    assert not e.calls and not M.warm_pool(e.store,e.w['name'])


def test_new_control_after_parking_revokes_durable_pool_receipt(adopted):
    e=adopted;row=park(e);before=len(e.calls);sid=e.session['session_id']
    e.store.put('job','manual-start',{'id':'manual-start','tool':'autoplay','state':'queued',
        'created':e.now[0]+1,'actor':'operator','require_worker':e.w['id'],
        'input':{'session_id':sid,'op':'start'}})
    assert not e.saver._warm(e.w,[e.session],e.now[0]+2)
    assert len(e.calls)==before


def test_manual_launch_without_explicit_adoption_has_no_warm_ownership(adopted):
    e=adopted
    row={k:v for k,v in e.run.items() if k!='warm_adoption'}
    assert e.saver._warm_owned(e.w,row,[e.session]) is None


def test_revoked_active_adoption_is_released_before_scheduler_actions(adopted):
    e=adopted;e.store.put(autoplay_resume.HANDOFF,e.session['session_id'],{'source_job_id':'active'})
    assert 'left untouched' in e.saver._advance(e.w,e.run,S.settings(e.store),[e.session],e.now[0]+1)
    assert not e.calls and not e.store.get(S.STATE,e.w['name'])


def test_adopt_api_uses_current_worker_after_same_name_restart(cfg):
    import time
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    source,w,session,telemetry,now=adoptable()
    app=create_app(cfg);store=app.state.store
    for (kind,key),value in source.docs.items():store.put(kind,key,value)
    # Registration history keeps an offline predecessor before its successor.
    store.put('worker','old',w|{'id':'old','last_seen':time.time()-1000,'tools':['launch_game','autoplay']})
    store.put('worker',w['id'],w|{'last_seen':time.time(),'tools':['launch_game','autoplay']})
    store.put('slabel',session['session_id'],{'owner':'you','ts':time.time()-100})
    S.telemetry_put(session['session_id'],telemetry)
    try:
        client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
        result=client.post('/api/mercmode/adopt',json={'host':w['name'],'session_id':session['session_id']})
        assert result.status_code==200,result.text
        run=result.json()['run']
        assert run['worker_id']==w['id'] and run['job']=='current' and run['warm_adoption']
        assert store.get('slabel',session['session_id'])['owner']=='agent'
    finally:
        S.TELEMETRY.pop(session['session_id'],None)
