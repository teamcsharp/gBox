import math
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_ps3 as R,re5_eggs as E
from gbox.mercs.titles.re5_nav import NavMesh


def scene(tmp_path):
    nav=NavMesh([(-1200.,0.,-1200.),(1200.,0.,-1200.),(1200.,0.,1200.),(-1200.,0.,1200.)],
                [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    bot=R.Bot(learn_dir=tmp_path)
    bot._control_state={'rotten_eggs':{'on':True,'status':'waiting for safe native supply'}}
    p={'ptr':0x303F8A00,'hp':1000,'hp_max':1000,'pos':(0.,0.,0.),'rot':math.pi,'action':0}
    foe={'ptr':0x30700000,'slot':0,'hp':800,'hp_max':800,'pos':(0.,0.,250.)}
    gun={'id':0x10B,'item':0x0B,'type':1,'slot':0,'grid':3,'rounds':6,'cap':6,'hand':True}
    snap={'player':p,'nav':nav,'inventory':[gun],'enemies':[foe],'timer':100.,'kills':0,'bonuses':[],'ground_mines':{}}
    return bot,snap,foe


def test_pending_egg_mode_departs_supported_floor_without_firing_or_fake_supply(tmp_path):
    bot,snap,foe=scene(tmp_path)
    action=bot._egg_action(snap['player'],snap,0.)
    assert action is not None and bot.stats['phase']=='egg_supply_departure'
    goal=bot._egg_departure['goal']
    assert math.dist(goal,foe['pos'])>=450.
    assert bot._following_route and bot._route_learn is False
    assert not bot.stats['egg_native_equipped'] and snap['rotten_egg_only']
    assert not ({'r1','l1','square'} & action['hold'])
    # Actual body alignment then permits movement on the verified next segment.
    snap['player']['rot']=R.heading(bot.route[0][0],bot.route[0][2])
    action=bot._egg_action(snap['player'],snap,.1)
    assert 'lup' in action['hold'] and bot._egg_departure['goal']==goal
    assert bot.stats['egg_supply_departure_routes']==1
    assert 'r1' not in action['hold']


@pytest.mark.parametrize('blocked',['qte','stage','recovery','animation','dying','heal','mine_escape','contact','offmesh','mine_margin'])
def test_pending_departure_preserves_mandatory_actions_health_and_mine_safety(tmp_path,blocked):
    bot,snap,foe=scene(tmp_path)
    if blocked=='qte':snap['prompt']='mash:circle'
    elif blocked=='stage':snap['stage_prompt']=True
    elif blocked=='recovery':snap['recovery_active']=True
    elif blocked=='animation':snap['player']['action']=6
    elif blocked=='dying':snap['player']['hp']=1
    elif blocked=='heal':bot.healing={'active':True}
    elif blocked=='mine_escape':bot.mines=SimpleNamespace(escape={'actor':123})
    elif blocked=='contact':foe['pos']=(0.,0.,50.)
    elif blocked=='offmesh':snap['player']['pos']=(1500.,0.,0.);foe['pos']=(1500.,0.,250.)
    elif blocked=='mine_margin':snap['ground_mines']={123:{'pos':(0.,0.,0.)}}
    action=bot._pending_egg_departure(snap['player'],snap,0.)
    assert action is None or action=={'hold':set()}
    assert not bot._following_route


def test_pending_departure_rechecks_new_enemy_before_sending_existing_route(tmp_path):
    bot,snap,foe=scene(tmp_path)
    bot._pending_egg_departure(snap['player'],snap,0.)
    goal=bot._egg_departure['goal']
    blocker={'ptr':0x30700100,'slot':1,'hp':800,'hp_max':800,'pos':tuple(v*.5 for v in goal)}
    snap['enemies'].append(blocker)
    action=bot._pending_egg_departure(snap['player'],snap,.1)
    if action and action['hold']:
        assert bot.route and bot._egg_departure['goal']!=goal
        assert all(snap['nav'].hazard_segment_clear(a,b,[(e['pos'],350.) for e in snap['enemies']],departing=True)
                   for a,b in zip([snap['player']['pos']]+bot.route,bot.route))
    assert 'r1' not in (action or {}).get('hold',())


def test_departure_no_progress_is_bounded_and_safe_clearance_releases_supply_retry(tmp_path):
    bot,snap,foe=scene(tmp_path)
    bot._pending_egg_departure(snap['player'],snap,0.)
    goal=bot._egg_departure['goal']
    assert bot._pending_egg_departure(snap['player'],snap,3.1)=={'hold':set()}
    assert 'no measured progress' in bot.stats['egg_supply_departure_status']
    snap['player']['pos']=goal
    assert bot._pending_egg_departure(snap['player'],snap,3.2) is None
    assert bot._egg_departure is None and 'clearance established' in bot.stats['egg_supply_departure_status']


def test_safe_departure_enables_original_conversion_guard_without_relaxing_it(tmp_path):
    from test_re5_eggs import memory,ACTOR
    ad,g,seed=memory()
    bot,snap,foe=scene(tmp_path)
    snap['player']['ptr']=seed['player']['ptr']
    ad.put(ACTOR+0x30,__import__('struct').pack('>3f',-600.,0.,-500.))
    E.state(g)['on']=True
    assert E.prepare_pickup(g,snap) is None and not ad.writes
    bot._pending_egg_departure(snap['player'],snap,0.)
    snap['player']['pos']=bot._egg_departure['goal']
    assert bot._pending_egg_departure(snap['player'],snap,.5) is None
    row=E.prepare_pickup(g,snap)
    assert row and row['id']==E.EGG_ID
    assert ad.writes==[(ACTOR+0x1C38,4),(ACTOR+0x1C36,2)]
