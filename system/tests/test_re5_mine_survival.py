from types import SimpleNamespace

from gbox.mercs.titles import re5_mines as M, re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh, Traversal
from test_re5_checkpoint_safety import state


def test_mine_preflight_rechecks_approaching_enemies_even_when_floor_route_is_cached(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    snap,foe = state()
    snap['enemies'] = []
    assert bot._mine_placement_preflight(snap,0.)
    snap['enemies'] = [foe]
    assert not bot._mine_placement_preflight(snap,.1)
    assert snap['mine_placement_safe'] is False
    assert f'{R.MINE_ENEMY_CM:g}cm' in bot.stats['mine_placement_safety_reason']
    assert not bot.stats.get('immunity_verified')


def test_mine_preflight_checks_full_exit_corridor_for_enemies_and_other_bombs(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    snap,foe = state()
    snap['enemies'] = []
    assert bot._mine_placement_preflight(snap,0.)
    origin = snap['player']['pos']
    endpoint = bot._mine_preflight['route'][-1]
    beyond = tuple(origin[k]+1.2*(endpoint[k]-origin[k]) for k in range(3))
    snap['enemies'] = [foe | {'pos':beyond}]
    assert not bot._mine_placement_preflight(snap,.1)
    assert 'escape corridor' in bot.stats['mine_placement_safety_reason']
    snap['enemies'] = []
    snap['ground_mines'] = {8:{'pos':endpoint,'arming_s':0.,'detonating':False}}
    assert not bot._mine_placement_preflight(snap,.2)
    assert 'ground bomb' in bot.stats['mine_placement_safety_reason']


def test_verified_mine_escape_moves_during_restore_delay_and_can_restore_gun_without_waiting_to_walk(tmp_path,monkeypatch):
    snap,_ = state()
    snap['enemies'] = []
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:1.)
    bot.mines = SimpleNamespace(escape={'actor':9,'pos':(0.,0.,0.),'at':0.},pending=None,
        cadence=SimpleNamespace(only=False,enabled=True),tick=lambda *a:{'tap':'dleft'})
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    monkeypatch.setattr(bot,'_mine_retreat',lambda *a:{'hold':{'lup'}})
    monkeypatch.setattr(bot,'_tick',lambda _: (_ for _ in ()).throw(AssertionError('optional gunplay interrupted escape')))
    assert bot.tick(snap)=={'hold':{'lup','dleft'}}
    bot.mines.tick = lambda *a:{'hold':set()}
    assert bot.tick(dict(snap))=={'hold':{'lup'}}


def test_approaching_enemy_releases_pending_place_button_without_claiming_a_plant(tmp_path,monkeypatch):
    snap,_ = state()
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:1.)
    bot.mines = SimpleNamespace(escape=None,pending={'slot':2},cadence=SimpleNamespace(only=False,enabled=True),
                                tick=lambda *a:{'hold':{'l1'}})
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    assert bot.tick(snap)=={'hold':set()}
    assert bot.stats.get('mines_placed',0)==0


def test_leaving_a_verified_bomb_precedes_optional_healing_and_gunplay(tmp_path,monkeypatch):
    snap,_ = state()
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:1.)
    monkeypatch.setattr(bot,'_mine_retreat',lambda *a:{'hold':{'lup'}})
    monkeypatch.setattr(bot,'_heal',lambda *a: (_ for _ in ()).throw(AssertionError('healing delayed escape')))
    assert bot._tick(snap)=={'hold':{'lup'}}


def grid_mesh():
    points = [(float(x*1000),0.,float(z*1000)) for z in range(4) for x in range(4)]
    triangles = []
    for z in range(3):
        for x in range(3):
            a = z*4+x
            triangles.extend(((a,a+1,a+5),(a,a+5,a+4)))
    links,edges = [[] for _ in triangles],{}
    for u,tri in enumerate(triangles):
        for edge in range(3):
            pair = frozenset((tri[edge],tri[(edge+1)%3]))
            if pair in edges:
                v,other = edges[pair]
                links[u].append((v,edge,1.))
                links[v].append((u,other,1.))
            else:
                edges[pair] = u,edge
    return NavMesh(points,triangles,links)


def test_current_ground_bomb_gets_a_supported_alternate_route_and_full_barrier_stays_blocked():
    mesh = grid_mesh()
    start,goal = (100.,0.,1400.),(2900.,0.,1400.)
    hazard = [((1500.,0.,1500.),600.)]
    original = mesh.route(start,goal)
    assert not all(mesh.hazard_segment_clear(a,b,hazard) for a,b in zip([start]+original,original))
    route = mesh.route_avoiding_hazards(start,goal,hazard)
    assert route and route[-1]==goal
    assert all(mesh.floor_segment(a,b) and mesh.hazard_segment_clear(a,b,hazard) for a,b in zip([start]+route,route))
    barrier = [((1500.,0.,float(z)),1000.) for z in (0,1500,3000)]
    assert mesh.route_avoiding_hazards(start,goal,barrier) is None
    assert mesh.route_avoiding_hazards(start,goal,[])==original  # removal restores original topology


def test_follower_rejects_new_bomb_on_cached_segment_then_replans_without_learning_a_wall(tmp_path):
    mesh = grid_mesh()
    start,goal = (100.,0.,1400.),(2900.,0.,1400.)
    bot = R.Bot(learn_dir=tmp_path)
    bot.route_for,bot.route,bot.route_since,bot.route_at = 77,[goal],10.,10.
    bot.nav_dynamic_mines = {9:{'pos':(1500.,0.,1500.)}}
    p,target = {'pos':start,'rot':0.,'action':0},{'ptr':77,'pos':goal}
    assert bot._follow(p,target,mesh,False,10.1)=={'hold':set()}
    assert not bot.blocked_links and not bot.nav_learning.link_penalties(mesh)
    bot._follow(p,target,mesh,False,10.2)
    assert bot.route
    hazards = [((1500.,0.,1500.),600.)]
    assert all(mesh.hazard_segment_clear(a,b,hazards) for a,b in zip([start]+bot.route,bot.route))


def test_offmesh_recovery_never_probes_toward_an_observed_bomb(tmp_path):
    snap,_ = state()
    bot = R.Bot(learn_dir=tmp_path)
    p = snap['player'] | {'pos':(1010.,0.,0.),'rot':0.}
    bot.nav_dynamic_mines = {9:{'pos':(800.,0.,0.)}}
    bot.nav_recovery = {'origin':p['pos'],'points':[(900.,0.,0.)], 'index':0,'started':0.,'walking':None}
    assert bot._recover_nav(p,snap['nav'],.1)=={'hold':set()}
    assert bot.nav_recovery['index']==1
    assert 'bomb margin' in bot.stats['nav_recovery']


def test_protection_used_earlier_in_round_remains_latched_after_operator_disables_it(tmp_path,monkeypatch):
    from gbox import re5_mods_tool as mods
    from gbox.mercs.titles import re5_controls
    snap,_ = state()
    bot = R.Bot(learn_dir=tmp_path)
    bot.m = SimpleNamespace(adapter=object())
    health = {'unlimited_health':True,'verified':True,'active':True,'hit_immunity':True,'immunity_verified':True}
    monkeypatch.setattr(mods,'maintain_health',lambda *a:health)
    monkeypatch.setattr(mods,'maintain_fire_animation',lambda *a,**kw:{})
    monkeypatch.setattr(mods,'maintain_kill_time',lambda *a,**kw:{})
    monkeypatch.setattr(re5_controls,'publish',lambda *a:None)
    bot.observe_round(snap,'playing',0.)
    assert bot.stats['round_used_health_protection'] is True
    health.update(unlimited_health=False,verified=False,active=False,hit_immunity=False,immunity_verified=False)
    bot.observe_round(dict(snap),'playing',1.)
    assert bot.stats['round_used_health_protection'] is True
    bot.observe_round(snap | {'timer':0.},'results',2.)
    bot.observe_round(dict(snap),'playing',3.)
    assert bot.stats['round_used_health_protection'] is False


def test_stage_action_and_engine_prompt_cannot_land_on_a_current_ground_bomb(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    snap,_ = state()
    crossing = Traversal((900.,0.,0.),snap['player']['pos'],(700.,0.,0.))
    bot.route = [crossing]
    bomb = {9:{'pos':(900.,0.,0.)}}
    bot.nav_dynamic_mines = bomb
    assert not bot.prompt_ok('square',snap | {'stage_prompt':True,'ground_mines':bomb},1.)
    assert bot.prompt_ok('circle',snap | {'stage_prompt':True,'ground_mines':bomb},1.)
    assert bot._traverse(snap['player'],{'ptr':77},snap['nav'],crossing,True,1.)=={'hold':set()}
    assert not bot.blocked_links


def test_removed_bomb_dead_end_uses_real_checkpoint_route_without_waiving_departure(tmp_path,monkeypatch):
    mesh=grid_mesh();bot=R.Bot(learn_dir=tmp_path)
    player={'pos':(100.,0.,1400.),'rot':0.,'action':0}
    bonus={'ptr':77,'kind':'time','pos':(2900.,0.,1400.)}
    escape={'actor':9,'pos':(0.,0.,1400.),'at':0.,'removal_recorded':True}
    bot.mines=SimpleNamespace(escape=escape,clear_escape=lambda *args:False)
    snap={'nav':mesh,'player':player,'bonuses':[bonus],'ground_mines':{}}
    monkeypatch.setattr(mesh,'retreat',lambda *args,**kwargs:None)
    calls=[]
    monkeypatch.setattr(bot,'_follow',lambda *args,**kwargs:calls.append((args,kwargs)) or {'hold':{'lup'}})
    assert bot._mine_retreat(player,snap,1.)=={'hold':{'lup'}}
    assert calls[-1][0][1]['pos']==bonus['pos'] and calls[-1][1]['retreat_from'] is None
    assert bot.mines.escape is escape and escape['checkpoint_exit']
    # Before positive detonation/removal evidence the same turnaround is unsafe.
    escape.pop('removal_recorded');bot.route=None
    # Before removal evidence the checkpoint turnaround is unsafe; with no measured way off it he still walks straight
    # away from the bomb, never stands on it (operator 2026-10-24)
    act=bot._mine_retreat(player,snap,2.)
    assert act is not None and 'walking straight away' in bot.stats['mine_retreat_status']
    assert len(calls)==1


def test_blocked_escape_walks_away_and_never_allows_another_plant(tmp_path,monkeypatch):
    snap,_=state();snap['enemies']=[]
    bot=R.Bot(learn_dir=tmp_path,clock=lambda:1.)
    escape={'actor':9,'pos':snap['player']['pos'],'at':0.}
    bot.mines=SimpleNamespace(escape=escape,pending=None,clear_escape=lambda *args:False,
        cadence=SimpleNamespace(only=False,enabled=True),tick=lambda *args:None)
    monkeypatch.setattr(snap['nav'],'retreat',lambda *args,**kwargs:None)
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    monkeypatch.setattr(bot,'_tick',lambda _: {'hold':{'l1','r1'}})
    act=bot.tick(snap)
    assert act!={'hold':{'l1','r1'}} and act.get('hold')                    # off the bomb first (operator 2026-10-24)
    assert bot.mines.escape is escape and 'walking straight away' in bot.stats['mine_retreat_status']
