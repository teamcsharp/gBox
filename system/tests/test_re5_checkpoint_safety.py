from types import SimpleNamespace

from gbox.mercs.titles import re5_mines as M, re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh


def state():
    nav = NavMesh([(-1000.,0.,-1000.),(1000.,0.,-1000.),(1000.,0.,1000.),(-1000.,0.,1000.)],
                  [(0,1,2),(0,2,3)], [[(1,2,1.)],[(0,0,1.)]])
    p = {"ptr":0x303f8a00,"pos":(100.,0.,0.),"rot":0.,"hp":1000,"hp_max":1000,"action":0}
    foe = {"ptr":0x30700000,"slot":0,"pos":(100.,0.,250.),"hp":800,"hp_max":800}
    return {"player":p,"nav":nav,"timer":100.,"kills":0,"enemies":[foe],
            "bonuses":[{"ptr":77,"pos":(800.,0.,0.),"kind":"time","seconds":60}]},foe


def test_normal_health_crowd_clearing_has_bounded_checkpoint_movement_and_hard_refusals(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    bot.stats.update(immunity_verified=False,hit_immunity=False)
    snap,foe = state()
    assert not bot._checkpoint_walk_allowed(snap,[foe],0.)
    snap['kills']=1  # native kill increase; stable HP still needs its own observation window.
    assert not bot._checkpoint_walk_allowed(snap,[foe],1.)
    assert not bot._checkpoint_walk_allowed(snap,[foe],2.)
    assert bot._checkpoint_walk_allowed(snap,[foe],2.3)
    assert bot._checkpoint_walk_allowed(snap,[foe],3.)
    assert not bot._checkpoint_walk_allowed(snap,[foe],3.2)
    assert not bot._checkpoint_walk_allowed(snap | {"prompt":"mash:circle"},[foe],3.3)
    near=foe | {"pos":(100.,0.,50.)}
    assert not bot._checkpoint_walk_allowed(snap | {'enemies':[near]},[near],3.4)
    imminent = {1:{"pos":(100.,0.,100.),"arming_s":.2,"detonating":False}}
    assert not bot._checkpoint_walk_allowed(snap | {"ground_mines":imminent},[foe],3.5)


def test_continuous_exposed_enemy_still_allows_real_checkpoint_route_ticks(tmp_path):
    now = [10.]
    bot = R.Bot(clock=lambda:now[0],learn_dir=tmp_path)
    bot.stats.update(immunity_verified=False,hit_immunity=False)
    snap,foe = state()
    bot._tick(snap)
    assert bot.stats["phase"] == "clear_nearby"
    now[0]=11.
    snap['kills']=1
    bot._tick(dict(snap))
    now[0] = 12.3
    action = bot._tick(dict(snap))
    assert bot.stats["phase"] == "gather_time"
    assert bot.route_for == 77 and bot._following_route
    assert "r1" not in action.get("hold",())
    now[0] = 12.4
    blocked = dict(snap,enemies=[foe | {"pos":(100.,0.,50.)}])
    bot._tick(blocked)
    assert bot.stats["phase"] == "clear_nearby"


def test_normal_health_departure_never_advances_towards_enemy_or_after_damage(tmp_path):
    bot=R.Bot(learn_dir=tmp_path)
    snap,foe=state()
    ahead=foe | {'pos':(350.,0.,0.)}
    snap['enemies']=[ahead]
    for at in (0.,1.,2.,3.,4.):
        snap['kills']=int(at>0)
        assert not bot._checkpoint_walk_allowed(snap,[ahead],at)
    snap['enemies']=[foe]
    snap['kills']=2
    assert not bot._checkpoint_walk_allowed(snap,[foe],4.1)
    assert bot._checkpoint_walk_allowed(snap,[foe],5.4)
    hurt=snap | {'player':snap['player'] | {'hp':999}}
    assert not bot._checkpoint_walk_allowed(hurt,[foe],5.5)
    low=snap | {'player':snap['player'] | {'hp':300}}
    assert not bot._checkpoint_walk_allowed(low,[foe],6.5)


def test_safe_departure_without_kill_requires_separation_and_fresh_hp_samples(tmp_path):
    bot=R.Bot(learn_dir=tmp_path)
    snap,foe=state()
    foe=foe | {'pos':(100.,0.,300.)}
    snap['enemies']=[foe]
    assert not bot._checkpoint_walk_allowed(snap,[foe],0.)
    assert not bot._checkpoint_walk_allowed(snap,[foe],1.)
    assert bot._checkpoint_walk_allowed(snap,[foe],2.3)
    assert not bot._checkpoint_walk_allowed(snap,[foe],8.)  # missing observations reset safety window.
    off=snap | {'player':snap['player'] | {'pos':(2000.,0.,0.)}}
    assert not bot._checkpoint_walk_allowed(off,[foe],8.1)


def test_departure_checks_committed_checkpoint_instead_of_nearest_other_bonus(tmp_path):
    bot=R.Bot(learn_dir=tmp_path)
    snap,foe=state()
    ahead=foe | {'pos':(400.,0.,0.)}
    snap['enemies']=[ahead]
    snap['bonuses'].append({'ptr':88,'pos':(-500.,0.,0.),'kind':'time','seconds':60})
    bot.bonus_commitment.choose(77,[77,88],0.,700.)
    for at in (0.,1.,2.,3.):
        snap['kills']=int(at>0)
        assert not bot._checkpoint_walk_allowed(snap,[ahead],at)
    assert bot.bonus_commitment.goal==77  # closer alternate away from foe cannot authorize this unsafe held route.


def test_offmesh_mine_escape_uses_existing_bounded_recovery(tmp_path,monkeypatch):
    bot = R.Bot(learn_dir=tmp_path)
    snap,_ = state()
    p = snap["player"] | {"pos":(1010.,0.,0.)}
    bot.mines = SimpleNamespace(escape={"pos":(1000.,0.,0.),"actor":123,"at":0.},clear_escape=lambda *a:False)
    observed = []
    monkeypatch.setattr(bot,"_recover_nav",lambda player,nav,at:observed.append((player,nav,at)) or {"hold":set()})
    assert bot._mine_retreat(p,snap,2.) == {"hold":set()}
    assert observed and observed[0][1] is snap["nav"]
    assert bot.mines.escape is not None


def test_controller_player_scope_reset_discards_old_escape_and_inventory_operations(monkeypatch):
    monkeypatch.setattr(M,"ground_mines",lambda _: {})
    monkeypatch.setattr(M,"settings",lambda:dict(M.DEFAULT))
    controller = M.Controller(SimpleNamespace(),{},lambda *a:None)
    controller.scope_player = 111
    controller.pending = {"old":True}
    controller.restore = (1,2)
    controller.escape = {"actor":9,"pos":(0,0,0),"at":0}
    controller.owned = {9:{"pos":(0,0,0)}}
    controller.detonating = {9}
    controller.tick({"player":{"ptr":222,"hp":1000,"pos":(0,0,0),"action":0}},10.)
    assert controller.scope_player == 222
    assert controller.pending is controller.restore is controller.escape is None
    assert not controller.owned and not controller.detonating
    assert controller.events[0]["kind"] == "scope_reset"
    assert controller.events[0]["abandoned_escape"]


def test_new_round_resets_controller_even_when_player_pointer_is_reused(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    calls = []
    bot.mines = SimpleNamespace(reset_round=lambda *args:calls.append(args))
    snap,_ = state()
    bot.observe_round(snap,"playing",0.)
    bot.observe_round(dict(snap),"dead",1.)
    bot.observe_round(dict(snap),"playing",2.)
    assert calls == [(0.,snap["player"]["ptr"]),(2.,snap["player"]["ptr"])]


def test_exact_detonation_and_removal_release_escape_without_false_success(monkeypatch):
    ground = {9:{'pos':(0,0,0),'arming_s':0.,'detonating':True}}
    monkeypatch.setattr(M,'ground_mines',lambda _:ground)
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT))
    stats = {}
    controller = M.Controller(SimpleNamespace(),stats,lambda *a:None)
    controller.escape = {'actor':9,'pos':(0,0,0),'at':0.}
    snap = {'player':{'ptr':111,'hp':1000,'pos':(0,0,1),'action':0}}
    controller.tick(snap,1.)
    assert controller.escape is not None
    ground.clear()
    controller.tick(snap,2.)
    assert controller.escape is None and stats['mine_escapes_unachieved']==1
    assert not stats.get('mine_retreats_completed')
    assert any(event['kind']=='retreat_hazard_removed' and not event['escape_completed'] for event in controller.events)
    controller.escape = {'actor':10,'pos':(0,0,0),'at':3.}
    controller.tick(snap,4.)
    assert controller.escape is not None  # unexplained disappearance alone cannot release it


def test_preflight_rejects_trapped_placement_before_equip_and_accepts_supported_escape(tmp_path,monkeypatch):
    bot = R.Bot(learn_dir=tmp_path)
    snap,_ = state()
    snap['enemies'] = []
    assert bot._mine_placement_preflight(snap,0.)
    trapped = NavMesh([(0.,0.,0.),(100.,0.,0.),(0.,0.,100.)],[(0,1,2)],[[]])
    assert not bot._mine_placement_preflight({'player':snap['player'] | {'pos':(20.,0.,20.)},'nav':trapped},1.)
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    calls = []
    controller = M.Controller(SimpleNamespace(),{},lambda *a:calls.append(a) or {'tap':'ddown'})
    mine = {'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':False}
    guarded = snap | {'inventory':[mine],'mine_placement_safe':False}
    controller.tick(guarded,0.);controller.tick(guarded,3.);controller.tick(guarded,5.)
    assert not calls and controller.pending is None
