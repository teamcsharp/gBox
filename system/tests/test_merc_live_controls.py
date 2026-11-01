"""Pine live controls exercise fake game state and the real MCP dispatcher."""
import asyncio
import copy
import json
import uuid
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import merc_live_controls as LC

SID='pc-round'
class Plane:
    def __init__(self):
        self.session={'session_id':SID,'state':'running','game_id':'115f9cdbba115432','adapter':'eden','title':'RE6'}
        self.run={'session_id':SID,'game_id':self.session['game_id'],'phase':'playing'}
        self.worker={'id':'pc','online':True}
        self.posts,self.jobs=[],{}
        self.queued=False
        self.actual=None
        self.status={'fire_rate_x':2.0,'infinite_ammo':True}
        self.view={'verified':True,'title':'re6','knobs':[{'name':'FLASH_R','label':'Flash radius','group':'Crowd',
            'kind':'float','min':200,'max':900,'step':25,'value':500.0}]}
    def answer(self,method,path,body=None):
        if path=='/api/registry':return {'tools':[]}
        if path=='/api/sessions':return [self.session]
        if path=='/api/workers':return [self.worker]
        if path=='/api/mercmode':return {'hosts':[{'id':'pc','online':self.worker['online'],'current_run':self.run}]}
        if path==f'/api/sessions/{SID}/interventions':
            if method=='POST':
                self.posts.append((path,body));return {'request':{'id':body['request_id'],'state':'queued','op':body['op']}}
            return {'available':True,'capabilities':['flash_now','equip_primary'],'options':{'weapons':[{'item':25,'weapon':'Hydra'}]},'requests':[]}
        if path=='/api/jobs' and method=='POST':
            self.posts.append((path,body));inp=body['input']
            if inp['op']=='bot_logic':
                for k in self.view['knobs']:
                    if k['name'] in inp['values']:k['value']=self.actual if self.actual is not None else inp['values'][k['name']]
                result=copy.deepcopy(self.view)
            elif inp['op']=='live_controls':result={'verified':True,'view':copy.deepcopy(self.view),'status':dict(self.status)}
            else:
                self.status[inp['op']+'_x']=self.actual if self.actual is not None else inp.get('multiplier')
                result={'verified':True,'status':dict(self.status)}
            jid='job'+str(len(self.jobs));job={**body,'id':jid,'state':'queued' if self.queued else 'succeeded','output':{'result':result}}
            self.jobs[jid]=job;return copy.deepcopy(job)
        if path.startswith('/api/jobs/'):return copy.deepcopy(self.jobs[path.rsplit('/',1)[1]])
        raise AssertionError((method,path,body))
    async def get(self,path,**kw):
        if path=='/api/sessions':assert kw=={'include_ended':'false'}
        assert path!='/api/workers', 'live controls must not read the full worker inventory'
        return self.answer('GET',path)
    async def post(self,path,body):return self.answer('POST',path,body)
    def transport(self,r):
        assert r.headers['authorization']=='Bearer fixture'
        if r.method=='POST':assert r.headers['x-gbox-actor']=='pine-live-controls'
        if r.url.path=='/api/sessions':assert r.url.params['include_ended']=='false'
        assert r.url.path!='/api/workers'
        return httpx.Response(200,json=self.answer(r.method,r.url.path,json.loads(r.content) if r.content else None))
async def no_delay(_):pass


def test_direct_ammo_toggle_preserves_boolean_and_session_identity():
    async def check():
        p = Plane()
        c = LC.Controls(p.get, p.post, sleep=no_delay)
        rid = str(uuid.uuid4())
        result = await c.call({'session_id': SID, 'op': 'set_infinite_ammo', 'enabled': True, 'request_id': rid})
        assert result['action']['state'] == 'queued'
        assert p.posts == [(f'/api/sessions/{SID}/interventions',
            {'op': 'set_infinite_ammo', 'request_id': rid, 'args': {'enabled': True}})]
        for invalid in (1, 'true', None):
            with pytest.raises(ValueError):
                await c.call({'session_id': SID, 'op': 'set_infinite_ammo', 'enabled': invalid, 'request_id': str(uuid.uuid4())})
        assert len(p.posts) == 1
    asyncio.run(check())

def test_inventory_bounds_readback_and_operator_jobs():
    async def check():
        p=Plane();c=LC.Controls(p.get,p.post,sleep=no_delay);out=await c.call({'session_id':SID})
        fire=next(x for x in out['controls'] if x['id']=='mod.fire_rate')
        assert fire['value']==2 and fire['available'] and fire['max']==80
        assert not next(x for x in out['controls'] if x['id']=='mod.infinite_tablets')['available']
        out=await c.call({'session_id':SID,'op':'set','control':'behavior.FLASH_R','value':700})
        assert out['action']['state']=='confirmed'
        assert next(x for x in out['controls'] if x['id']=='behavior.FLASH_R')['value']==700
        assert p.posts[-1][1]=={'tool':'re5_mods','agent_use':False,'require_worker':'pc','input':{'session_id':SID,'op':'bot_logic','values':{'FLASH_R':700}}}
        count=len(p.posts)
        for key,value in [('behavior.FLASH_R',901),('behavior.FLASH_R',True),('arbitrary.poke',1),('mod.infinite_ammo',1)]:
            with pytest.raises(ValueError):await c.call({'session_id':SID,'op':'set','control':key,'value':value})
        assert len(p.posts)==count
        p.actual=3
        with pytest.raises(ValueError,match='did not confirm'):await c.call({'session_id':SID,'op':'set','control':'mod.fire_rate','value':4})
    asyncio.run(check())

def test_pending_poll_does_not_resubmit_or_expose_other_session_job():
    async def check():
        p=Plane();p.queued=True;c=LC.Controls(p.get,p.post,sleep=no_delay)
        out=await c.call({'session_id':SID});jid=out['pending_job']['id']
        for _ in range(3):assert (await c.call({'session_id':SID,'job_id':jid}))['pending_job']['id']==jid
        assert len(p.posts)==1
        p.jobs[jid]['state']='succeeded';out=await c.call({'session_id':SID,'job_id':jid})
        assert 'pending_job' not in out and len(p.posts)==1
        p.jobs['foreign']=dict(p.jobs[jid],input={'session_id':'other-round','op':'live_controls'})
        with pytest.raises(ValueError,match='does not belong'):await c.call({'session_id':SID,'job_id':'foreign'})
    asyncio.run(check())

@pytest.mark.parametrize('change',['warm','ended','offline','next_run','wrong_game','preparing'])
def test_no_writes_to_stale_or_warmed_session(change):
    async def check():
        p=Plane();c=LC.Controls(p.get,p.post,sleep=no_delay)
        if change=='warm':p.session['warm']=True
        if change=='ended':p.session['state']='ended'
        if change=='offline':p.worker['online']=False
        if change=='next_run':p.run['session_id']='pc-next'
        if change=='wrong_game':p.run['game_id']='other'
        if change=='preparing':p.run['phase']='preparing'
        with pytest.raises(ValueError):await c.call({'session_id':SID,'op':'flash_now','request_id':str(uuid.uuid4())})
        assert not p.posts
    asyncio.run(check())

def test_mcp_dispatch_dynamic_inventory_click_identity_and_unknown_fields(monkeypatch):
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    p=Plane();original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(*a,**kw,transport=httpx.MockTransport(p.transport)))
    async def check():
        async with Client(build('http://fixture','fixture')) as c:
            assert 'game_live_controls' in {t.name for t in (await c.list_tools()).tools}
            out=await c.call_tool('game_live_controls',{'session_id':SID})
            assert not out.is_error and json.loads(out.content[0].text)['controls'][-1]['id']=='behavior.FLASH_R'
            rid=str(uuid.uuid4());out=await c.call_tool('game_live_controls',{'session_id':SID,'op':'equip_primary','request_id':rid,'item':25})
            assert not out.is_error and p.posts[-1][1]=={'op':'equip_primary','request_id':rid,'args':{'item':25}}
            count=len(p.posts);out=await c.call_tool('game_live_controls',{'session_id':SID,'op':'set','control':'mod.fire_rate','value':3,'tool':'poke'})
            assert out.is_error and len(p.posts)==count
    asyncio.run(check())

def test_http_auth_requires_header_and_only_bounded_actions(monkeypatch):
    calls=[]
    async def invoke(config,args):calls.append(args);return {'session_id':args['session_id'],'controls':[]}
    monkeypatch.setattr(LC,'call_mcp',invoke)
    app=FastAPI();LC.install(app,SimpleNamespace(token=lambda:'fixture',api_port=8765));c=TestClient(app)
    path=f'/api/sessions/{SID}/live-controls';headers={'Authorization':'Bearer fixture'}
    assert c.get(path).status_code==401
    assert c.get(path+'?token=fixture').status_code==401
    assert c.post(path,json={'op':'flash_now','request_id':str(uuid.uuid4())}).status_code==401
    assert c.get(path+'?job_id=job1',headers=headers).status_code==200
    assert calls==[{'session_id':SID,'op':'status','job_id':'job1'}]
    for body in [{'op':'raw','tool':'poke'},{'op':'set','control':'mod.fire_rate','value':2,'extra':1},{'op':'flash_now'},
                 {'op':'equip_primary','request_id':str(uuid.uuid4()),'item':True}]:
        assert c.post(path,headers=headers,json=body).status_code==409
    assert len(calls)==1
    assert c.post(path,headers=headers,json={'session_id':'foreign','op':'set'}).status_code==422

def test_http_facade_reaches_real_loopback_mcp_transport(monkeypatch):
    pytest.importorskip('mcp')
    pytest.importorskip('httpx2')
    import socket
    import threading
    import time
    import uvicorn
    from gbox.mcp_server import build
    p=Plane();original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda *a,**kw:original(*a,**kw,transport=httpx.MockTransport(p.transport)))
    mcp=build('http://fixture','fixture').streamable_http_app(host='127.0.0.1')
    seen=[]
    async def guarded(scope,receive,send):
        if scope['type']=='http':
            value=dict(scope['headers']).get(b'authorization')
            seen.append(value==b'Bearer fixture')
            if value!=b'Bearer fixture':
                await send({'type':'http.response.start','status':401,'headers':[]})
                await send({'type':'http.response.body','body':b'bad token'})
                return
        await mcp(scope,receive,send)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(guarded,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.01)
    try:
        assert server.started
        out=asyncio.run(LC.call_mcp(SimpleNamespace(token=lambda:'fixture',api_port=port-1),{'session_id':SID}))
        assert out['session_id']==SID and out['controls'][-1]['id']=='behavior.FLASH_R'
        assert seen and all(seen)
    finally:
        server.should_exit=True;thread.join(5);sock.close()

def test_companion_uses_existing_config_and_loopback_without_core_restart(monkeypatch,tmp_path):
    import sys
    import uvicorn
    from gbox import config
    cfg=tmp_path/'gbox.toml';cfg.write_text('api_port = 8765\n')
    data=tmp_path/'data';data.mkdir();(data/'api_token').write_text('fixture')
    monkeypatch.setattr(config,'load',lambda path:SimpleNamespace(data_dir=data,api_port=8765,token=lambda:'fixture'))
    monkeypatch.setattr(sys,'argv',['gbox-controls','--config',str(cfg)])
    captured=[];monkeypatch.setattr(uvicorn,'run',lambda app,**kwargs:captured.append((app,kwargs)))
    LC.main()
    assert captured[0][1]['host']=='127.0.0.1' and captured[0][1]['port']==8767
    assert {r.path for r in captured[0][0].routes}=={f'/api/sessions/{{sid}}/live-controls'}
    assert cfg.read_text()=='api_port = 8765\n'
