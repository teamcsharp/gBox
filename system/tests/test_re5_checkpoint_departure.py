"""Checkpoint travel, trailing mines and combo opportunities share actual routes."""
import math
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_ps3 as R
from gbox.mercs.titles.re5_nav import NavMesh, Traversal


def scene():
    mesh = NavMesh([(-5000.,0.,-5000.),(5000.,0.,-5000.),(5000.,0.,5000.),(-5000.,0.,5000.)],
                   [(0,1,2),(0,2,3)], [[(1,2,1.)],[(0,0,1.)]])
    return {'player':{'ptr':123,'pos':(0.,0.,0.),'rot':0.,'hp':1000,'hp_max':1000,'action':0},
            'nav':mesh,'timer':100.,'kills':0,'combo':3,'combo_timer':2.,'ground_mines':{},'enemies':[],
            'bonuses':[{'ptr':77,'kind':'time','pos':(2000.,0.,0.),'seconds':60}]}


def committed(tmp_path):
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    bot.bonus_commitment.choose(77,[77],0.,2000.)
    return bot


def test_mine_departure_follows_held_checkpoint_not_arbitrary_retreat(tmp_path,monkeypatch):
    snap,bot = scene(),committed(tmp_path)
    monkeypatch.setattr(snap['nav'],'retreat',lambda *a,**kw:pytest.fail('checkpoint route was abandoned'))
    assert bot._mine_placement_preflight(snap,0.)
    route = snap['mine_escape_route']
    assert math.dist(snap['player']['pos'],route[-1]) == pytest.approx(900.)
    assert route[-1][0] > 0 and route[-1][2] == pytest.approx(0.)
    assert bot.stats['mine_departure_policy']=='held time-checkpoint route'
    assert bot.bonus_commitment.goal==77
    # A trailing attacker can be left behind, but never inside the existing 6m margin.
    snap['enemies']=[{'hp':100,'pos':(-1000.,0.,0.)}]
    assert bot._mine_placement_preflight(snap,.1)
    snap['enemies'][0]['pos']=(-500.,0.,0.)
    assert not bot._mine_placement_preflight(snap,.2)


@pytest.mark.parametrize('failure',['short','traversal','blocked-floor','approaching-enemy','ground-bomb'])
def test_checkpoint_mine_departure_never_waives_safety_or_changes_direction(tmp_path,monkeypatch,failure):
    snap,bot = scene(),committed(tmp_path)
    monkeypatch.setattr(snap['nav'],'retreat',lambda *a,**kw:pytest.fail('unsafe checkpoint must defer planting'))
    if failure=='short':
        snap['bonuses'][0]['pos']=(400.,0.,0.)
    elif failure=='traversal':
        monkeypatch.setattr(snap['nav'],'route',lambda *a,**kw:[Traversal((50.,0.,0.),(80.,0.,0.),(200.,0.,0.)),(2000.,0.,0.)])
    elif failure=='blocked-floor':
        monkeypatch.setattr(snap['nav'],'floor_segment',lambda *a,**kw:False)
    elif failure=='approaching-enemy':
        snap['enemies']=[{'hp':100,'pos':(1100.,0.,0.)}]
    else:
        snap['ground_mines']={8:{'pos':(1100.,0.,0.)}}
    assert not bot._mine_placement_preflight(snap,0.)
    assert snap['mine_escape_route'] is None and bot.bonus_commitment.goal==77


def test_changed_checkpoint_invalidates_cached_mine_exit(tmp_path):
    snap,bot = scene(),committed(tmp_path)
    assert bot._mine_placement_preflight(snap,0.)
    snap['bonuses']=[{'ptr':88,'kind':'time','pos':(0.,0.,2000.)}]
    bot.bonus_commitment.choose(88,[88],.1,2000.)
    assert bot._mine_placement_preflight(snap,.1)
    assert snap['mine_escape_route'][-1][2] == pytest.approx(900.)


@pytest.mark.parametrize('x',[0.,350.])
def test_actual_planted_mine_uses_verified_forward_exit_and_discards_passed_points(tmp_path,monkeypatch,x):
    snap,bot = scene(),committed(tmp_path)
    snap['player']['pos']=(x,0.,0.)
    escape={'actor':9,'pos':(-50.,0.,0.),'at':0.,'geometry':snap['nav'].learning_sig,
            'route':[(300.,0.,0.),(900.,0.,0.)]}
    bot.mines=SimpleNamespace(escape=escape,clear_escape=lambda *a:False)
    monkeypatch.setattr(snap['nav'],'retreat',lambda *a,**kw:pytest.fail('verified forward route was discarded'))
    action=bot._mine_retreat(snap['player'],snap,10.)
    assert bot.route_for=='mine_escape:9' and bot.route[-1]==(900.,0.,0.)
    assert all(point[0]>=x for point in bot.route)
    assert not {'l1','r1'} & action.get('hold',set())
    assert bot.bonus_commitment.goal==77


def test_pursuit_uses_the_same_blocked_links_and_costs_as_navigation(tmp_path,monkeypatch):
    snap,bot = scene(),committed(tmp_path)
    near={'ptr':1,'slot':1,'pos':(100.,0.,0.)}
    reachable={'ptr':2,'slot':2,'pos':(500.,0.,0.)}
    bot.blocked_links={(0,1)}
    monkeypatch.setattr(bot.nav_learning,'link_penalties',lambda mesh:{(1,0):20.})
    def length(start,end,**kw):
        assert kw['blocked_links']=={(0,1)} and kw['link_penalties']=={(1,0):20.}
        return None if end==near['pos'] else 600.
    monkeypatch.setattr(snap['nav'],'route_length',length)
    assert bot._pursuit_target(snap['player'],[near,reachable],snap['nav'],10.,snap)==reachable


@pytest.mark.parametrize('timer,window,enemy_z,shoot',[(100.,2.,1000.,True),(20.,2.,1000.,False),
                                                       (100.,15.,1000.,False),(100.,2.,-1000.,False)])
def test_visible_combo_save_precedes_long_trip_but_does_not_turn_back_or_sacrifice_clock(
        tmp_path,timer,window,enemy_z,shoot):
    snap,bot = scene(),committed(tmp_path)
    snap.update(timer=timer,combo_timer=window)
    enemy={'ptr':55,'slot':0,'hp':800,'hp_max':800,'pos':(0.,0.,enemy_z)}
    snap['enemies']=[enemy]
    bot._observed_snap=snap  # decision fixture: round observation is already complete
    bot.combat=SimpleNamespace(blocked_until={},choose_target=lambda *a:enemy,
                              tick=lambda *a,**kw:{'hold':{'l1','r1'}})
    action=bot._tick(snap)
    assert ('r1' in action.get('hold',())) is shoot
    assert bot.bonus_commitment.goal==77
    if not shoot:
        assert bot._following_route and bot.route_for==77
