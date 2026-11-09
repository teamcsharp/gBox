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


# --- the operator's click on an enemy, the double click on a spot (2026-11-09) ----------------------------------------
# "If I click on an enemy on the map, I want the bot to navigate to that enemy and dispatch [it] ... I want that enemy
# to be targeted and I want the bot to dispatch them ASAP no matter what. Anywhere I double click on the map, I want the
# bot navigating to that area. And then if I just leave it, they just take control and just go back to whatever they
# were doing."
import math

from gbox.mercs.titles import re5_switch as SW


def switch_frame(round='c'*32):
    return {'v': 1, 'screen': 'playing', 'stage': 'switch.test', 'goal_round': round,
            'goal_capabilities': ['enemy', 'point'], 'player': {'pos': [0, 150, 0]},
            'enemies': [{'id': 3, 'kind': 'Majini', 'pos': [1600, 400, 0]}]}


def test_the_map_takes_an_enemy_and_a_spot_as_goals_only_from_a_bot_that_offers_them():
    now = [100.]; store = TM.Store(clock=lambda: now[0]); f = switch_frame(); store.put_frame('w-s', f)
    base = {'round': f['goal_round'], 'stage': f['stage'], 'seq': 1}
    goal = store.command('w-s', base | {'kind': 'enemy', 'id': 3})
    assert goal['kind'] == 'enemy' and goal['entity_id'] == 3 and goal['pos'] == [1600, 400, 0]
    assert goal['label'] == 'Dispatch Majini' and store.put_frame('w-s', f)['operator_goal'] == goal
    spot = store.command('w-s', base | {'kind': 'point', 'x': -820, 'z': 2400.5})
    assert spot['kind'] == 'point' and spot['entity_id'] == 0 and spot['pos'] == [-820.0, 150.0, 2400.5]
    assert store.put_frame('w-s', f)['operator_goal'] == spot          # the newest mark is the one in force
    for bad in ({'kind': 'enemy', 'id': 9}, {'kind': 'enemy', 'id': True}, {'kind': 'point', 'x': 1},
                {'kind': 'point', 'x': float('nan'), 'z': 0}, {'kind': 'point', 'x': 0, 'z': 0, 'id': 3}):
        with pytest.raises(ValueError): store.command('w-s', base | bad)
    old = TM.Store(clock=lambda: now[0]); g = frame(); old.put_frame('w-s', g)           # a bot of bonuses and items only
    with pytest.raises(ValueError, match='does not take map targets'):
        old.command('w-s', {'round': g['goal_round'], 'stage': g['stage'], 'seq': 1, 'kind': 'enemy', 'id': 3})


def test_a_marked_enemy_is_followed_until_he_is_down_and_a_marked_spot_until_he_stands_on_it():
    goals = Goals()
    value = {'id': 'g1', 'round': goals.round, 'stage': 's', 'kind': 'enemy', 'entity_id': 3, 'pos': [1600, 0, 0],
             'label': 'Dispatch Majini', 'state': 'queued'}
    goals.receive(value, 10.)
    foe = {'slot': 3, 'ptr': 0xA0, 'pos': (1700., 0., 0.), 'hp': 800}
    snap = {'player': {'pos': (0., 0., 0.)}, 'enemies': [foe]}
    assert goals.resolve(snap, 11.) is foe and goals.public()['state'] == 'active'       # wherever he has walked to
    assert goals.resolve(dict(snap, enemies=[dict(foe, ptr=0xB0)]), 12.) is None         # another unit in the slot
    assert goals.public()['state'] == 'completed'
    goals.receive(dict(value, id='g2'), 20.)
    assert goals.resolve(dict(snap, enemies=[dict(foe, hp=0)]), 21.) is None and goals.public()['state'] == 'completed'
    goals.receive(dict(value, id='g3', kind='point', entity_id=0, pos=[500, 0, 0], label='Go to the marked spot'), 30.)
    assert goals.resolve(snap, 31.) == {'kind': 'point', 'pos': (500, 0, 0)}
    assert goals.resolve({'player': {'pos': (420., 0., 60.)}}, 32.) is None and goals.public()['state'] == 'completed'
    goals.receive(dict(value, id='g4', kind='point', entity_id=0, pos=[500, 0, 0]), 40.)
    assert goals.resolve(snap, 40. + 121.) is None and goals.public()['state'] == 'expired'


def switch_bot():
    b = object.__new__(SW.Bot)
    b.stats, b.mines, b._now, b.target, b.target_at, b._goal_dy = {}, None, 5.0, None, None, None
    b._mesh, b._nav, b.doing, b.why = None, None, '', ''
    b._gun_down = lambda: None
    b._gun_back = lambda snap, now: None
    b._turn = lambda err, tol=0.0: () if abs(err) <= tol else (('rleft',) if err > 0 else ('rright',))
    b._set_target = lambda key, now: setattr(b, 'target', key)
    b.fought = []
    b._decide = lambda p, live, flat, near_e, near, snap, now: b.fought.append([e['ptr'] for e in live]) or {'hold': ('zl', 'zr')}
    return b


def mark(bot, kind, **kw):
    g = bot._goals()
    bot.receive_map_goal({'id': 'm' + kind + str(kw.get('entity_id')), 'round': g.round, 'stage': 's', 'kind': kind,
                          'state': 'queued', 'label': 'mark', **kw})
    return g


def test_the_switch_bot_offers_enemy_and_spot_goals_and_goes_for_the_marked_enemy_ahead_of_the_rest():
    bot = switch_bot()
    plan = T.take_plan(bot)                                  # (through the publisher's own hand-over)
    assert plan['goal_capabilities'] == ['enemy', 'point'] and plan['goal_round'] == bot._goals().round
    frame_ = T.Tracker('Resident Evil 5').frame({'player': {'pos': (0., 0., 0.), 'rot': 0., 'hp': 1000}}, plan, now=5.0)
    assert frame_['goal_capabilities'] == ['enemy', 'point'] and frame_['goal_round'] == plan['goal_round']
    p = {'pos': (0., 0., 0.), 'rot': 0.0, 'hp': 1000}
    flat = lambda e: math.hypot(e['pos'][0], e['pos'][2])
    marked = {'slot': 3, 'ptr': 0xA0, 'pos': (0., 0., 4000.), 'hp': 800}
    close = {'slot': 4, 'ptr': 0xA1, 'pos': (300., 0., 0.), 'hp': 800}                   # another, right beside him
    far = {'slot': 5, 'ptr': 0xA2, 'pos': (900., 0., 0.), 'hp': 800}                     # another, 9 m off
    snap = {'player': p, 'enemies': [marked, close]}
    assert bot._operator_goal(p, snap, [marked, close], flat, 5.0) is None               # no mark: his own play
    mark(bot, 'enemy', entity_id=3, pos=[0, 0, 4000])
    assert bot.stats['map_goals_taken'] == 1
    act = bot._operator_goal(p, snap, [marked, close], flat, 5.1)
    assert act == {'hold': ('zl', 'zr')} and bot.fought == [[0xA1]]                    # the one beside him first
    assert 'fighting through' in bot.why and bot._goals().public()['state'] == 'deferred'
    bot.fought.clear()
    act = bot._operator_goal(p, dict(snap, enemies=[marked, far]), [marked, far], flat, 5.15)
    assert act['hold'][:2] == ('lup', 'b') and "operator's target 40 m" in bot.why       # 9 m off is not in the way
    assert bot.fought == []
    near = dict(marked, pos=(0., 0., 900.))
    act = bot._operator_goal(p, dict(snap, enemies=[near, close]), [near, close], flat, 5.2)
    assert act == {'hold': ('zl', 'zr')} and bot.fought == [[0xA1]]                    # the one beside him still first
    bot.fought.clear()
    act = bot._operator_goal(p, dict(snap, enemies=[near]), [near], flat, 5.25)
    assert act == {'hold': ('zl', 'zr')} and bot.fought == [[0xA0]] and bot.target == 0xA0   # the fight, on him alone
    dead = dict(near, hp=0)
    assert bot._operator_goal(p, dict(snap, enemies=[dead, close]), [close], flat, 5.3) is None   # down: his own play
    assert bot._goals().public()['state'] == 'completed'


def test_a_marked_spot_is_run_to_and_then_he_plays_on_by_himself():
    bot = switch_bot()
    p = {'pos': (0., 0., 0.), 'rot': 0.0, 'hp': 1000}
    flat = lambda e: math.hypot(e['pos'][0], e['pos'][2])
    mark(bot, 'point', entity_id=0, pos=[0, 0, 3000])
    act = bot._operator_goal(p, {'player': p, 'enemies': []}, [], flat, 5.1)
    assert act['hold'][:2] == ('lup', 'b') and "operator's spot" in bot.why
    grabber = {'slot': 4, 'ptr': 0xA1, 'pos': (100., 0., 100.), 'hp': 800}
    act = bot._operator_goal(p, {'player': p, 'enemies': [grabber]}, [grabber], flat, 5.2)
    assert act == {'hold': ('zl', 'zr')} and bot.fought == [[0xA1]]                    # one at arm's length: fought
    assert bot._goals().public()['state'] == 'deferred'
    there = dict(p, pos=(50., 0., 2900.))
    assert bot._operator_goal(there, {'player': there, 'enemies': []}, [], flat, 5.3) is None
    assert bot._goals().public()['state'] == 'completed'
