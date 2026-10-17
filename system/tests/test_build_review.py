import base64,json,time
from types import SimpleNamespace
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from gbox import build_feedback as F,build_quarantine as Q,cast_swap as CS
from gbox.server import JobRequest
from tests.test_builds import fixture,GID
from tests.test_build_report_images import b64,png
from tests.test_build_quarantine import setup as quarantine_setup


def test_report_and_images_survive_removal_and_gate_subsequent_builds(tmp_path):
    cfg,app,store,h=fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        route=f'/api/builds/{GID}/g1_patch'
        response=c.post(route+'/report',headers=h,json={'reason':'detail_loss','note':'Face detail is destroyed; preserve eyes.',
            'images':[{'b64':b64('red'),'role':'screenshot'},{'b64':b64('green'),'role':'reference'}]})
        assert response.status_code==200,response.text
        rid=response.json()['id'];feedback=store.get(F.KIND,rid)
        assert len(feedback['attachments'])>=2 and 'Face detail' in feedback['note']
        assert all(a['url'].startswith('/api/artifacts/') for a in feedback['attachments'])
        assert c.post(route+'/review-cleanup',headers=h,json={'report_id':'wrong','scope':'all'}).status_code==409
        saved=c.post(route+'/review-cleanup',headers=h,json={'report_id':rid,'scope':'all'})
        assert saved.status_code==200,saved.text
        assert (cfg.cache/'mods'/GID/'g1_patch').exists(),'cleanup is queued, not immediate'
        body={'tool':'characters','input':{'op':'cast_swap','target_game':GID,'source':'donors'}}
        denied=c.post('/api/jobs',headers=h,json=body)
        assert denied.status_code==409,denied.text
        assert denied.json()['detail']['code']=='build_feedback_review_required'
        assert not store.all('job')
        ack={rid:feedback['revision']}
        F.check(store,JobRequest(**(body|{'input':body['input']|{'feedback_ack':ack}})))
        F.record(store,store.get('request',rid),GID,'g1_patch','New detail: torn torso')
        with pytest.raises(HTTPException):F.check(store,JobRequest(**(body|{'input':body['input']|{'feedback_ack':ack}})))
        analyzed=c.post(route+'/broken/analysis',headers=h,json={'findings':'Budget removed eye geometry','resolution':'Preserve eyes before decimation; visual retest required'})
        assert analyzed.status_code==200,analyzed.text
        learned=store.get(F.KIND,rid)
        assert learned['analysis']['findings']=='Budget removed eye geometry'
        assert learned['revision']==3
        assert learned['previous_notes'][0]['note']=='Face detail is destroyed; preserve eyes.'
        # Remove a synthetic build payload and confirm feedback and artifact bytes stay available.
        from gbox import filemods
        filemods.delete_build(cfg,GID,'g1_patch',[])
        assert F.rows(store,GID)[0]['request_id']==rid
        assert store.read_artifact(feedback['attachments'][0]['sha256'])
        assert c.get('/api/build-feedback',headers=h,params={'game_id':GID}).json()['replacement_preference']=='whole_cast'


@pytest.mark.parametrize('images',[[{'b64':'bad'}],[{'b64':b64(),'role':'fake'}],[{'b64':b64()}]*5])
def test_invalid_review_images_never_create_feedback_or_cleanup(tmp_path,images):
    cfg,app,store,h=fixture(tmp_path)
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        before=store.all('request')
        response=c.post(f'/api/builds/{GID}/g1_patch/report',headers=h,json={'note':'bad','images':images})
        assert response.status_code==422,response.text
        assert store.all('request')==before and not store.all(F.KIND) and not store.all(Q.KIND)


@pytest.mark.parametrize('delete_collection',[True,False])
def test_review_cleanup_preserves_until_analysis_then_purges_archives_only_as_selected(tmp_path,delete_collection):
    cfg,store,folder,r,archive=quarantine_setup(tmp_path)
    r.update(review_cleanup=True,nodes=[],cleanup_jobs={},archives=[],state='queued',delete_collection=delete_collection)
    store.put(Q.KIND,r['key'],r)
    store.put('session','active',{'session_id':'pc-active','game_id':'game','mod':'bad','state':'running'})
    app=FastAPI();tick=Q.routes(app,store,cfg,lambda:'operator',lambda *a:None,lambda:[],lambda:None)
    tick();assert store.get(Q.KIND,r['key'])['state']=='queued'
    store.put('session','active',{'state':'ended'})
    tick();assert store.get(Q.KIND,r['key'])['state']=='preserved' and folder.exists()
    r=store.get(Q.KIND,r['key']);r['analysis']={'findings':'mesh bad','resolution':'writer repaired and tested'}
    store.put(Q.KIND,r['key'],r);store.put('request','r',{'status':'done'})
    tick()
    assert store.get(Q.KIND,r['key'])['state']=='deleted'
    assert folder.exists() is not delete_collection
    assert not archive['path'] or not __import__('pathlib').Path(archive['path']).exists()


def test_review_cleanup_handles_multiple_selected_pcs_and_offline_wait(tmp_path):
    cfg,store,folder,r,archive=quarantine_setup(tmp_path)
    r.update(review_cleanup=True,nodes=['i9','jay'],cleanup_jobs={},archives=[],state='queued',delete_collection=False)
    store.put(Q.KIND,r['key'],r)
    local=[{'game_id':'game','name':'bad'}]
    ws=[{'name':'i9','id':'w1','online':True,'local_builds':local}, {'name':'jay','id':'w2','online':False,'local_builds':local}]
    calls=[]
    def submit(body,actor):
        jid='j'+str(len(calls));calls.append(body);store.put('job',jid,{'state':'queued'});return {'id':jid}
    app=FastAPI();tick=Q.routes(app,store,cfg,lambda:'operator',submit,lambda:ws,lambda:None)
    tick();assert len(calls)==1 and calls[0]['require_worker']=='w1'
    store.put('job','j0',{'state':'succeeded','output':{'result':{'archives':[archive['id']]}}})
    tick();assert store.get(Q.KIND,r['key'])['state']!='preserved'
    ws[1]['online']=True;tick();assert len(calls)==2 and calls[1]['require_worker']=='w2'
    store.put('job','j1',{'state':'succeeded','output':{'result':{'archives':[archive['id']]}}})
    tick();assert store.get(Q.KIND,r['key'])['state']=='preserved'
    assert folder.exists()


def test_full_cast_request_does_not_silently_become_one_player():
    game={'game_id':'002b9dca58a18ea1','title':'Grand Theft Auto - Liberty City Stories (USA)','platform':'ps2'}
    result=CS.plan(game,[],'SA2',slots='all')
    assert result['status']=='unsupported_cast' and result['mod'] is None and result['assignments']==[]
    assert 'whole-cast' in result['message']



def test_historical_reports_are_backfilled_with_durable_image_links(tmp_path):
    cfg,app,store,h=fixture(tmp_path)
    image=store.put_artifact(png('green'),'old-issue.png','image/png',{})
    request={'id':'history','number':90,'body':'The old model has bad eyes.','context':{'build_report':True,'build':f'{GID}/old'},
        'messages':[{'author':'operator','text':'The old model has bad eyes.','attachments':[{'sha256':image.sha256,'name':image.name,'type':'image/png'}]}]}
    store.put('request','history',request)
    api=FastAPI();F.routes(api,store,lambda:'operator')
    row=store.get(F.KIND,'history')
    assert row['note']=='The old model has bad eyes.' and row['attachments'][0]['sha256']==image.sha256
    assert store.read_artifact(image.sha256)==png('green')
    again=FastAPI();F.routes(again,store,lambda:'operator')
    assert store.get(F.KIND,'history')['revision']==1,'startup must not invalidate every acknowledgement again'


def test_cleanup_retry_only_retries_failed_jobs_for_the_same_report_and_targets(tmp_path):
    cfg,app,store,h=fixture(tmp_path)
    F.record(store,{'id':'saved','number':47},GID,'g1_patch','Bad mesh')
    key=f'{GID}/g1_patch';row={'key':key,'game_id':GID,'name':'g1_patch','state':'blocked','review_cleanup':True,
        'nodes':['i9-NUC'],'cleanup_scope':'pcs','request_id':'saved','cleanup_jobs':{'i9-NUC':'failed-job'},'error':'failed'}
    store.put(Q.KIND,key,row);store.put('job','failed-job',{'state':'failed'})
    with TestClient(app) as c:
        assert app.state.built_mods.wait(10)
        route=f'/api/builds/{key}/review-cleanup'
        response=c.post(route,headers=h,json={'report_id':'saved','scope':'pcs','nodes':['i9-NUC']})
        assert response.status_code==200,response.text
        assert response.json()['state']=='queued' and response.json()['cleanup_jobs']=={}
        assert c.post(route,headers=h,json={'report_id':'saved','scope':'all'}).status_code==409


def test_unrelated_games_and_readonly_operations_are_not_blocked_by_feedback(tmp_path):
    cfg,app,store,h=fixture(tmp_path)
    F.record(store,{'id':'report','number':3},GID,'g1_patch','Bad eyes')
    F.check(store,JobRequest(tool='characters',input={'op':'cast_swap','target_game':'ffffffffffffffff','source':'donors'}))
    F.check(store,JobRequest(tool='characters',input={'op':'collect','game_id':GID}))
    F.check(store,JobRequest(tool='characters',input={'op':'cast_swap','target_game':GID,'plan_only':True}))
    F.check(store,JobRequest(tool='get_frame',input={'session_id':'operator'}))
    with pytest.raises(HTTPException) as caught:F.check(store,JobRequest(tool='characters',input={'op':'use','game':'ambiguous alias'}))
    assert caught.value.detail['code']=='build_feedback_game_id_required'


def test_new_feedback_holds_a_previously_queued_build_before_worker_claim(tmp_path):
    cfg,app,store,h=fixture(tmp_path)
    F.record(store,{'id':'report','number':3},GID,'g1_patch','Bad eyes')
    job={'id':'old-queued','tool':'characters','input':{'op':'use','game_id':GID,'character':'donor'},
        'state':'queued','require_os':None,'require_worker':None,'created':time.time(),'agent_use':False}
    store.put('job',job['id'],job)
    with TestClient(app) as c:
        response=c.post('/api/workers/w1/claim',headers=h,json={'idle_seconds':1000,'active_jobs':0})
        assert response.status_code==204,response.text
        held=store.get('job','old-queued')
        assert held['state']=='queued' and held['admission_wait']['code']=='build_feedback_review_required'
        approved=job|{'id':'reviewed-job','input':job['input']|{'feedback_ack':{'report':1}}}
        store.put('job','reviewed-job',approved)
        response=c.post('/api/workers/w1/claim',headers=h,json={'idle_seconds':1000,'active_jobs':0})
        assert response.status_code==200,response.text
        assert response.json()['id']=='reviewed-job'
        assert store.get('job','old-queued')['state']=='queued'


def test_chat_agent_can_review_feedback_and_forward_exact_acknowledgements(monkeypatch):
    import httpx
    from gbox.agent import Agent
    row={'request_id':'report','revision':2,'note':'Bad eyes','attachments':[{'sha256':'image','name':'operator-screenshot-1.png'}]}
    def handler(request):
        assert request.url.path=='/api/build-feedback'
        return httpx.Response(200,json={'items':[row]})
    agent=object.__new__(Agent);agent.api=httpx.Client(base_url='http://fixture',transport=httpx.MockTransport(handler));agent.vision=None
    assert agent.build_feedback('game')['items'][0]['note']=='Bad eyes'
    assert agent.build_feedback('game','report','image')['status']=='vision_unavailable'
    with pytest.raises(ValueError):agent.build_feedback('game','report','unrelated-image')
    calls=[]
    agent._job=lambda tool,inp,**kw:(calls.append(inp) or {'state':'succeeded','output':{'result':{'mod':'cast'}}})
    agent.characters(op='cast_swap',target_game='game',source='donors',feedback_ack={'report':2})
    assert calls[0]['feedback_ack']=={'report':2} and calls[0]['op']=='cast_swap'


def test_mcp_feedback_lookup_and_request_image_tools_work_together(monkeypatch):
    import asyncio,json,httpx
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    def handler(request):
        if request.url.path=='/api/registry':return httpx.Response(200,json={'tools':[]})
        if request.url.path=='/api/build-feedback':
            assert request.url.params['game_id']=='game'
            return httpx.Response(200,json={'items':[{'request_id':'report','revision':2,'attachments':[{'sha256':'image'}]}]})
        if request.url.path=='/api/requests/report':return httpx.Response(200,json={'image':'image','messages':[]})
        if request.url.path=='/api/artifacts/image':return httpx.Response(200,content=png(),headers={'content-type':'image/png'})
        raise AssertionError(request.url.path)
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(*a,**kw,transport=httpx.MockTransport(handler)))
    async def check():
        async with Client(build('http://fixture','fixture')) as client:
            assert 'get_build_feedback' in {t.name for t in (await client.list_tools()).tools}
            result=await client.call_tool('get_build_feedback',{'game_id':'game'})
            assert json.loads(result.content[0].text)['items'][0]['revision']==2
            image=await client.call_tool('read_request_artifact',{'request_id':'report','sha256':'image'})
            assert image.content[0].type=='image'
    asyncio.run(check())
