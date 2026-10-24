import pytest

from gbox import tactical_map as TM
from gbox.mercs import tactical as T
from gbox.mercs.map_goals import Goals
from gbox.mercs.titles import re5_ps3 as R
from test_re5_nav import floor_grid


def frame(round='a'*32):
    return {'v':1,'screen':'playing','stage':'BLUS30491.test','goal_round':round,
            'goal_capabilities':['bonus','item'],'player':{'pos':[0,0,0]},
            'bonuses':[{'id':77,'kind':'combo','pos':[200,0,0],'taken':False}],
            'items':[{'id':88,'name':'Green Herb','pos':[400,0,0]}]}


def test_live_entity_command_round_fences_cancellation_and_expiry():
    now=[100.];store=TM.Store(clock=lambda:now[0]);f=frame();store.put_frame('w-s',f)
    body={'round':f['goal_round'],'stage':f['stage'],'seq':1,'kind':'bonus','id':77}
    goal=store.command('w-s',body)
    assert goal['state']=='queued' and goal['entity_id']==77
    assert store.put_frame('w-s',f)['operator_goal']==goal
    cancel=store.command('w-s',{'cancel':True})
    assert cancel['state']=='cancelled' and cancel['id']!=goal['id']
    for patch in ({'id':True},{'id':999},{'round':'b'*32},{'stage':'other'}, {'kind':'enemy'}, {'pos':[0,0,0]}):
        with pytest.raises(ValueError):store.command('w-s',body|patch)
    now[0]+=3.1
    with pytest.raises(ValueError):store.command('w-s',body)
    store.put_frame('w-s',frame('b'*32))
    assert 'operator_goal' not in store.put_frame('w-s',frame('b'*32))


def test_goal_disappearance_is_not_a_pickup_or_a_kill_clock_credit():
    g=Goals();g.receive({'id':'x','round':g.round,'stage':'s','kind':'bonus','entity_id':77,
                        'pos':[100,0,0],'label':'Time bonus'},0.)
    snap={'player':{'pos':[0,0,0]},'timer':100.,'kills':0,
          'bonuses':[{'ptr':77,'pos':[100,0,0],'kind':'time'}]}
    assert g.resolve(snap,0.)['ptr']==77
    missing=snap|{'bonuses':[],'timer':109.9,'kills':1}
    assert g.resolve(missing,.1) is None
    g.resolve(missing,.5)
    assert g.public()['state']=='observed_removed'
    g.reset();g.receive({'id':'y','round':g.round,'kind':'bonus','entity_id':77,'pos':[100,0,0]},1.)
    g.resolve(snap,1.);g.resolve(snap|{'bonuses':[],'timer':159.9},1.1)
    g.resolve(snap|{'bonuses':[],'timer':159.5},1.5)
    assert g.public()['state']=='completed'


def test_reused_actor_new_round_and_expired_goal_are_never_followed():
    g=Goals();request={'id':'x','round':g.round,'kind':'bonus','entity_id':77,'pos':[100,0,0]}
    g.receive(request,0.)
    snap={'player':{'pos':[0,0,0]},'bonuses':[{'ptr':77,'pos':[1000,0,0]}]}
    assert g.resolve(snap,.1) is None and g.public()['state']=='unavailable'
    g.reset();g.receive(request,1.);assert g.goal is None
    g.receive(request|{'round':g.round},1.);assert g.resolve(snap,302.) is None
    assert g.public()['state']=='expired'


def test_publisher_delivers_only_on_engine_thread_to_exact_bot():
    class Bot:
        def __init__(self):self.received=[]
        def plan(self):return {}
        def receive_map_goal(self,g):self.received.append(g)
    class Sink:
        def frame(self,f):return {'operator_goal':{'id':'x'}}
    t=[0.];pub=T.Publisher(Sink(),'BLUS30491',clock=lambda:t[0],threaded=False)
    a,b=Bot(),Bot();pub({},a,'playing');assert not a.received
    t[0]=1.;pub({},b,'playing');assert not a.received and not b.received
    t[0]=2.;pub({},b,'playing');assert b.received==[{'id':'x'}]


def test_clicked_combo_overrides_automatic_bonus_selection_but_not_close_threats(tmp_path,monkeypatch):
    bot=R.Bot(clock=lambda:1.,learn_dir=tmp_path)
    mesh=floor_grid({(x,z) for x in range(7) for z in range(7)})
    snap={'player':{'ptr':1,'pos':(120.,0.,130.),'rot':0.,'hp':1000,'hp_max':1000,'action':0},
          'timer':100.,'timer_start':120.,'enemies':[],'nav':mesh,'bonuses':[
              {'ptr':77,'slot':77,'kind':'combo','pos':(500.,0.,500.)},
              {'ptr':78,'slot':78,'kind':'time','pos':(600.,0.,500.)}]}
    bot.observe_round(snap,'playing',0.)
    bot.receive_map_goal({'id':'x','round':bot.map_goals.round,'kind':'bonus','entity_id':77,
                          'pos':[500,0,500],'label':'Combo bonus'})
    followed=[]
    monkeypatch.setattr(bot,'_follow',lambda p,target,*a,**kw:followed.append(target['ptr']) or {'hold':{'lup'}})
    bot._tick(snap)
    assert followed==[77] and bot.stats['phase']=='operator_collect'
    followed.clear()
    snap['enemies']=[{'ptr':99,'slot':1,'pos':(150.,0.,200.),'hp':800,'hp_max':800}]
    bot._tick(snap)
    assert followed==[] and bot.map_goals.public()['state']=='deferred'


def test_native_boundaries_exclude_open_floor_and_repeated_stalls_back_off(tmp_path):
    from gbox.mercs.titles.re5_nav import Learning
    mesh=floor_grid({(0,0),(1,0)})
    context=mesh.boundary_context((30.,0.,20.))
    assert context['source']=='native_navmesh' and context['floor'] is not None
    assert context['edges'] and all(e['kind']=='mesh_boundary' for e in context['edges'])
    # The x=100 shared edge is open floor, not a wall.
    assert not any(e['a'][0]==e['b'][0]==100. for e in context['edges'])
    learn=Learning(tmp_path/'nav.json');link=(0,mesh.links[0][0][0])
    delays=[]
    for _ in range(6):
        learn.blocked(mesh,link);delays.append(learn.retry_delay(mesh,link))
    assert delays==[8.,16.,32.,64.,120.,120.]
    learn.obstruction(mesh,(30.,0.,20.),(150.,0.,30.),'stationary approach')
    learn.save();loaded=Learning(tmp_path/'nav.json')
    assert loaded.stages[mesh.learning_sig]['obstructions'][0]['source']=='native_navmesh'


def test_collection_endpoint_requires_auth_and_limits_body(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app=create_app(cfg)
    path='/api/autoplay/tactical/w-s/goal'
    f=frame();app.state.tactical_map.put_frame('w-s',f)
    body={'round':f['goal_round'],'stage':f['stage'],'seq':1,'kind':'bonus','id':77}
    assert TestClient(app).post(path,json=body).status_code==401
    c=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    assert c.post(path,json=body).json()['state']=='queued'
    assert c.post(path,json=body|{'pos':[0,0,0]}).status_code==422
    assert c.post(path,json={'extra':'x'*2050}).status_code==413
    assert c.post(path,json={'cancel':True}).json()['state']=='cancelled'
