"""Warm rotation changes the watched picture without replacing emulator identity."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from gbox import autoplay_resume, mercmode as M, screensaver as S
from gbox.server import create_app
from tests.test_mercmode import RE4, ops
from tests.test_mercmode_adopt_warm import adopted, park


@pytest.fixture
def rotation(adopted):
    e=adopted
    e.run['mercmode_last_round']={'round_id':'a'*32}
    row=park(e)
    for job in e.calls:
        e.store.put('job',job['id'],job|{'state':'succeeded','worker_id':e.w['id']})
    e.now[0]+=5
    sid=e.w['id']+'-next'
    target={'session_id':sid,'game_id':RE4,'state':'running','adapter':'dolphin',
            'started':e.now[0]-2,'worker_id':e.w['id'],'detail':{'pid':4321}}
    e.store.put('session',sid,target)
    e.store.put('job','next',{'id':'next','tool':'launch_game','state':'succeeded','actor':S.ACTOR,
        'agent_use':True,'created':e.now[0]-2,'worker_id':e.w['id'],'require_worker':e.w['id'],
        'input':{'game':{'game_id':RE4}},'output':{'session_id':sid}})
    e.store.put('job','next-start',{'id':'next-start','tool':'autoplay','state':'succeeded',
        'actor':S.ACTOR,'agent_use':True,'created':e.now[0]-1,'worker_id':e.w['id'],'require_worker':e.w['id'],
        'input':{'session_id':sid,'op':'start'}})
    run={'worker':e.w['name'],'worker_id':e.w['id'],'session_id':sid,'game_id':RE4,'job':'next',
         'title':'RE4','phase':'playing','started':e.now[0]-2,'autoplay_job':'next-start',
         'mercmode':{'title':'re4'},'mercmode_last_round':{'round_id':'b'*32}}
    e.store.put(S.STATE,e.w['name'],run)
    e.target=target;e.target_run=run;e.parked=row
    return e


def links(e):
    return M.display_successors(e.store,[e.w],e.store.running_sessions())


def test_parked_view_follows_current_turn_then_back_without_persisted_cycles(rotation):
    e=rotation;source=e.session['session_id'];target=e.target['session_id']
    assert links(e)=={source:target}
    assert 'replaced_by' not in e.store.get('session',source)
    e.saver._park(e.w,e.target_run,e.now[0]+1,'verified native round boundary: next MercMode title')
    assert links(e)=={}  # no accepted successor while between turns
    for job in e.calls:
        e.store.put('job',job['id'],job|{'state':'succeeded','worker_id':e.w['id']})
    e.now[0]+=5
    pick={'title':'re5','name':'RE5','game_id':e.session['game_id'],'map_id':'BLUS30491'}
    e.saver._resume_warm(e.w,pick,M.settings(e.store,e.w['name']),e.now[0])
    assert links(e)=={}  # resume and autoplay must both land first
    resumed=e.store.get(S.STATE,e.w['name'])
    resume=ops(e.calls,source,'resume')[-1]
    e.store.put('job',resume['id'],resume|{'state':'succeeded','worker_id':e.w['id']})
    e.saver._advance(e.w,resumed,S.settings(e.store),e.store.running_sessions(),e.now[0]+1)
    start=e.calls[-1]
    e.store.put('job',start['id'],start|{'state':'succeeded','worker_id':e.w['id']})
    assert links(e)=={target:source}
    assert all('replaced_by' not in e.store.get('session',s) for s in (source,target))


@pytest.mark.parametrize('change',['disabled','offline','foreign_worker','prelaunch','pause_pending','pause_failed',
    'resume_pending','start_pending','start_failed','source_human','target_human','source_pid','source_started',
    'source_control','target_control','source_pause','target_pause','handoff','round_missing','target_replaced'])
def test_only_current_owned_and_acknowledged_rotation_changes_picture(rotation,change):
    e=rotation;source=e.session['session_id'];target=e.target['session_id']
    if change=='disabled':M.configure(e.store,e.w['name'],{'enabled':False})
    elif change=='offline':e.w['online']=False
    elif change=='foreign_worker':e.w['id']='different'
    elif change=='prelaunch':
        M.keep_warm(e.store,e.w['name'],'re5',e.parked|{'state':'prelaunch'})
    elif change.startswith('pause_'):
        job=e.store.get('job',e.parked['pause_job'])
        e.store.put('job',job['id'],job|{'state':change[6:]})
    elif change=='resume_pending':
        e.store.put(S.STATE,e.w['name'],e.target_run|{'warm_resume_job':'pending'})
    elif change.startswith('start_'):
        job=e.store.get('job','next-start');e.store.put('job',job['id'],job|{'state':change[6:]})
    elif change.endswith('_human'):
        e.store.put('slabel',source if change.startswith('source') else target,{'owner':'you'})
    elif change in ('source_pid','source_started'):
        patch={'detail':{'pid':9999}} if change=='source_pid' else {'started':e.session['started']+1}
        e.store.put('session',source,e.session|patch)
    elif change.endswith('_control') or change.endswith('_pause'):
        sid=source if change.startswith('source') else target
        pause=change.endswith('_pause')
        e.store.put('job','manual',{'id':'manual','tool':'session_op' if pause else 'autoplay','state':'queued',
            'created':e.now[0]+1,'actor':'operator','require_worker':e.w['id'],
            'input':{'session_id':sid,'op':'pause' if pause else 'stop'}})
    elif change=='handoff':
        e.store.put(autoplay_resume.HANDOFF,target,{'source_job_id':'next-start'})
    elif change=='round_missing':
        M.keep_warm(e.store,e.w['name'],'re5',e.parked|{'display_park':{}})
    elif change=='target_replaced':
        e.store.put('session',target,e.target|{'replaced_by':'other'})
    assert links(e)=={}


def test_sessions_api_projects_view_link_without_changing_canonical_identity(cfg,rotation):
    e=rotation;app=create_app(cfg);store=app.state.store
    for kind,key,body in e.store.db.execute('SELECT kind,id,body FROM docs').fetchall():
        store.put(kind,key,json.loads(body))
    store.put('worker',e.w['id'],e.w|{'last_seen':time.time(),'tools':['launch_game','autoplay']})
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    result=client.get('/api/sessions?include_ended=false')
    assert result.status_code==200,result.text
    rows={r['session_id']:r for r in result.json()}
    source=e.session['session_id'];target=e.target['session_id']
    assert rows[source]['replaced_by']==target and rows[source]['mercmode_display_successor'] is True
    assert rows[source]['state']=='running' and 'replaced_by' not in rows[target]
    assert 'replaced_by' not in store.get('session',source)
