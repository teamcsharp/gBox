import math
from types import SimpleNamespace

from gbox.mercs.titles import re5_health as H, re5_mines as M, re5_ps3 as R
from gbox.mercs.titles.re5_inventory_health import Controller as InventoryHealth
from gbox.mercs.titles.re5_nav import NavMesh, Traversal
from test_re5_checkpoint_safety import state
from test_re5_mercs import PLAYER, world, healing_bot


def test_carried_emergency_heal_preempts_pending_mine_selection(tmp_path,monkeypatch):
    snap,_ = state()
    snap['player'].update(hp=100,hp_max=1000)
    snap['inventory'] = [{'slot':1,'id':0x304,'item':4,'type':3,'rounds':1,'grid':1,'hand':True}]
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    bot.mines = SimpleNamespace(escape=None,pending=None,cadence=SimpleNamespace(only=False,enabled=True),
                                tick=lambda *a:{'tap':'ddown'})
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    assert bot.tick(snap)=={'tap':'square'}
    assert snap['mine_placement_safe'] is False and bot.healing is not None


def test_recovery_selection_releases_aim_before_equipping_instead_of_spamming_ignored_dpad(tmp_path):
    bot,m,now = healing_bot(tmp_path,action=2)
    assert bot.tick(R.snapshot(m))=={'hold':set()}
    assert bot.stats.get('heal_equip_attempts',0)==0
    now[0]+=.9
    assert bot.tick(R.snapshot(m))=={'hold':set()}
    now[0]+=.11
    assert bot.tick(R.snapshot(m))=={'tap':'dup'}
    assert bot.stats['heal_equip_attempts']==1


def test_health_route_pauses_checkpoint_and_excludes_mine_and_unusable_red_herb(tmp_path):
    snap,_ = state()
    snap['player'].update(hp=100,hp_max=1000)
    snap['enemies'] = []
    snap['health_items'] = [{'ptr':1,'id':0x10A,'pos':(200.,0.,0.),'evidence':'not health'},
                            {'ptr':2,'id':0x306,'pos':(250.,0.,0.),'evidence':'red alone'},
                            {'ptr':3,'id':0x305,'pos':(800.,0.,0.),'evidence':'native item table'}]
    bot = R.Bot(learn_dir=tmp_path)
    bot.bonus_commitment.goal = 77
    action = bot._seek_health(snap['player'],snap,10.)
    assert action is not None and bot.stats['phase']=='seek_health'
    assert bot.route_for==('health',3) and bot.bonus_commitment.goal==77


def test_exact_health_pickup_is_allowed_but_explicit_mine_actor_stays_blocked(tmp_path,monkeypatch):
    m = world(hp=100)
    health = {'ptr':0x30500000,'handle':21,'id':0x305,'pos':(0.,0.,0.),'evidence':'native item table'}
    request = {'token':'mash:square','kind':R.BTN_STAGE,'label':R.PICKUP_LABEL,'owner':PLAYER,'target':21}
    monkeypatch.setattr(H,'ground_items',lambda _:[health],raising=False)
    monkeypatch.setattr(H,'pickup_request',lambda *a:health,raising=False)
    assert not R.mine_pickup(m,request)
    m.u32(0x30600000,next(iter(R.MINE_VTABLES)))
    assert R.mine_pickup(m,request | {'target':0x30600000})
    monkeypatch.setattr(H,'pickup_request',lambda *a:None,raising=False)
    assert R.mine_pickup(m,request)


def test_measured_prison_ladder_faces_entry_portal_not_offset_upper_landing(tmp_path):
    # Read from the actual stalled Prison action link and player foot position.
    approach = (2152.43171141803,-388.11709911521535,88.18433916206767)
    portal = (2181.1845703125,-387.5714569091797,96.72690200805664)
    landing = (2111.230724758858,.3858554135498912,105.26379736875829)
    mesh = NavMesh([(1800.,-388.,-100.),(2400.,-388.,-100.),(2400.,-388.,400.),(1800.,-388.,400.)],
                   [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    crossing = Traversal(landing,approach,portal)
    bot = R.Bot(learn_dir=tmp_path)
    bot.route = [crossing]
    player = {'pos':(2113.596,-394.126,101.288),'rot':-.7379,'action':0}
    target = {'ptr':77,'pos':landing}
    action = bot._traverse(player,target,mesh,crossing,False,0.)
    assert 'lup' not in action.get('hold',())  # first align to the actual lower-floor approach
    player['pos'] = approach
    action = bot._traverse(player,target,mesh,crossing,False,.1)
    assert 'lup' not in action.get('hold',()) and action.get('tap') is None
    player['rot'] = math.atan2(portal[0]-approach[0],portal[2]-approach[2])
    assert bot._traverse(player,target,mesh,crossing,False,.2)=={'hold':{'lup'}}
    assert bot._traverse(player,target,mesh,crossing,True,.3)=={'tap':'square'}


def test_nonquick_carried_spray_uses_owned_inventory_then_existing_consumption_confirmation(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    ui = {'pointer':0x30800000,'player':PLAYER,'state':2,'open':False,'cursor':0,'owner':0,
          'fade':1.,'input_delay':0.,'context_open':False}
    bot.inventory_heal = InventoryHealth(bot.stats,reader=lambda *a:dict(ui))
    spray = {'slot':6,'id':0x304,'type':3,'item':4,'grid':4,'rounds':1,'hand':False}
    gun = {'slot':0,'id':0x10B,'type':1,'item':0x0B,'grid':3,'rounds':6,'hand':True}
    player = {'ptr':PLAYER,'hp':100,'hp_max':1000,'action':0}
    snap = {'player':player,'inventory':[gun,spray]}
    assert bot._heal(player,snap,10.)=={'tap':'triangle'}
    ui.update(state=3,open=True)
    assert bot._heal(player,snap,10.2)=={'tap':'ddown'}
    ui['cursor'] = 3
    assert bot._heal(player,snap,10.4)=={'tap':'dright'}
    ui['cursor'] = 4
    assert bot._heal(player,snap,10.6)=={'tap':'l1'}
    assert bot.stats.get('heals',0)==0
    spray['hand'],gun['hand'] = True,False
    ui.update(state=2,open=False)
    assert bot._heal(player,snap,10.8)=={'tap':'square'}
    assert not bot.inventory_heal.active and bot.healing is not None
    player['hp'] = 1000
    snap['inventory'] = [gun]
    assert bot._heal(player,snap,11.1)=={'tap':'dleft'}
    assert bot.stats['heals']==bot.stats['heal_items_used']==1


def test_recovery_item_in_hand_outside_a_heal_switches_back_to_a_gun(tmp_path,monkeypatch):
    # Live 2026-10-24: the infinite spray's restore left the First Aid Spray in hand; "laserless gun: turning; hold
    # fire" at a Majini in front of him until he died.
    snap,_ = state()
    snap['inventory'] = [{'slot':1,'id':0x304,'item':4,'type':3,'rounds':1,'grid':1,'hand':True},
                         {'slot':0,'id':0x101,'item':0,'type':0,'rounds':12,'grid':0,'hand':False}]
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    monkeypatch.setattr(M,'ground_mines',lambda _: {})
    calls = []
    monkeypatch.setattr(bot,'_heal_return_weapon',lambda inv,st,now: calls.append(inv) or {'tap':'dright'})
    assert bot.tick(snap)=={'tap':'dright'}
    assert calls and bot.stats['weapon_policy'].startswith('recovery item in hand')


def test_back_to_a_gun_tries_another_loaded_gun_while_the_first_switch_waits(tmp_path,monkeypatch):
    # live 2026-10-24: "grid 3 waits 60s" with the First Aid Spray in hand; the other guns were never tried
    from gbox.mercs.titles import re5_weapons as W
    guns = [g for g in W.WEAPONS if W.WEAPONS[g].family in W.DIRECT][:2]
    inv = [{'slot':1,'id':0x304,'item':4,'type':3,'rounds':1,'grid':1,'hand':True},
           {'slot':2,'id':0x100|guns[0],'item':guns[0],'type':1,'rounds':12,'grid':3,'hand':False},
           {'slot':3,'id':0x100|guns[1],'item':guns[1],'type':1,'rounds':12,'grid':5,'hand':False}]
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    monkeypatch.setattr(bot,'_preferred_gun',lambda snap: None)
    bot.switch_blocked[W.inventory_key(inv[1])] = 70.
    picked = []
    monkeypatch.setattr(bot,'_switch_weapon',lambda gun,now,why: picked.append(gun['grid']) or {'tap':'x'})
    assert bot._heal_return_weapon(inv,{'return':None},10.)=={'tap':'x'} and picked==[5]


def test_the_same_ladder_three_times_is_left_alone_and_its_bonus_skipped(tmp_path):
    # operator 2026-10-24: "jumping down the ladder, putting back up the ladder ... repeatedly. They need to progress"
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    bot.plan_target = {'kind':'time','id':0x304029c0,'pos':(900.,0.,0.)}
    foot, top = {'pos':(100.,0.,0.)}, {'pos':(150.,300.,40.)}
    assert not bot._stage_loop(foot,10.) and not bot._stage_loop(foot,10.5)   # one use per prompt
    assert not bot._stage_loop(top,14.)
    assert bot._stage_loop(foot,18.)                                         # third use: banned
    assert bot.bonus_skip[0x304029c0] > 18. and bot.stats['stage_loops_broken'] == 1
    assert bot._stage_loop(top,30.) and not bot._stage_loop({'pos':(2000.,0.,0.)},31.)


def test_a_majini_in_front_on_a_walkway_within_engage_counts_as_in_view():
    # operator 2026-10-24: long-distance rocket Majini on a walkway were never taken on
    p = {'pos':(0.,0.,0.),'rot':0.}
    from gbox.mercs.titles.re5_ps3 import heading
    ahead = R.heading(0.,2600.)
    p['rot'] = ahead
    assert R.Bot._in_view(p, {'pos':(0.,450.,2600.)})                  # 26 m, up on a walkway, straight ahead
    assert not R.Bot._in_view(p, {'pos':(0.,0.,-2600.)})               # behind him
    assert not R.Bot._in_view(p, {'pos':(0.,0.,4000.)})                # beyond ENGAGE


def test_lost_escape_route_keeps_obligation_without_inventing_floor(tmp_path):
    # New placements require a measured route. If it disappears, do not invent a walk through a wall.
    bot = R.Bot(learn_dir=tmp_path,clock=lambda:10.)
    escape = {'actor':0x30800000,'pos':(0.,0.,0.),'at':9.}
    bot.mines = SimpleNamespace(escape=escape, clear_escape=lambda now,pos: False)
    mesh = SimpleNamespace(find=lambda *a,**k: 1, retreat=lambda *a,**k: [], learning_sig='t')
    p = {'ptr':1,'pos':(50.,0.,0.),'rot':0.,'hp':1000,'hp_max':1000,'action':0}
    act = bot._mine_retreat(p, {'nav':mesh,'player':p}, 10.)
    assert act == {'hold':set()} and bot.stats['mine_retreats_blocked'] == 1
    assert bot.mines.escape is escape and 'blocked' in bot.stats['mine_retreat_status']


def test_a_majini_fought_in_place_without_a_shot_is_left_for_the_route(tmp_path):
    # round map 2026-10-26 (Prison): 34 s standing in break_for_time, "no line: hold fire" at one Majini
    bot = R.Bot(world(),learn_dir=tmp_path,clock=lambda:10.)
    bot.stats['shots'] = 5
    p = {'pos':(100.,0.,0.),'rot':0.}
    foe = {'ptr':0x30800000,'pos':(900.,0.,0.),'hp':800}
    assert not any(bot._combat_stalled(p, foe, 10. + i * .1) for i in range(30))   # 3 s: not yet
    bot.stats['shots'] = 6                                                   # a shot left the gun: a fresh start
    assert not any(bot._combat_stalled(p, foe, 14. + i * .1) for i in range(39))   # 3.9 s, 39 ticks
    assert bot._combat_stalled(p, foe, 18.1)                                 # 4 s over 40 ticks, standing: left alone
    assert bot._stalled_until[0x30800000] > 18.1 and bot.combat.blocked_until[0x30800000] > 18.1 and bot.stats['combat_stalls_broken'] == 1
    assert not bot._combat_stalled({'pos':(400.,0.,0.),'rot':0.}, foe, 19.)   # moved: a fresh start


def test_no_heal_starts_with_a_majini_near_unless_health_is_critical(tmp_path):
    # operator 2026-10-26: "Im watching the bot sit idle and be attacked and fail to even dispatch these foes who are 1
    # foot away" (live 13:05: phase healing_inventory with 9 Majini on the field)
    bot = R.Bot(learn_dir=tmp_path)
    ui = {'pointer':0x30800000,'player':PLAYER,'state':2,'open':False,'cursor':0,'owner':0,
          'fade':1.,'input_delay':0.,'context_open':False}
    bot.inventory_heal = InventoryHealth(bot.stats,reader=lambda *a:dict(ui))
    spray = {'slot':6,'id':0x304,'type':3,'item':4,'grid':4,'rounds':1,'hand':False}
    gun = {'slot':0,'id':0x10B,'type':1,'item':0x0B,'grid':3,'rounds':6,'hand':True}
    player = {'ptr':PLAYER,'pos':(0.,0.,0.),'hp':300,'hp_max':1000,'action':0}
    near = {'ptr':0x30700000,'slot':0,'pos':(0.,0.,300.),'hp':800,'hp_max':800}
    snap = {'player':player,'inventory':[gun,spray],'enemies':[near]}
    assert bot._heal(player,snap,10.) is None                       # 30 %: a Majini 3 m away, the fight first
    assert bot.stats['heal_deferred'].startswith('1 Majini within 4 m at 30%')   # HEAL_SAFE_R 400 since 2026-10-26
    assert bot._seek_health(player,snap | {'health_items':[{'ptr':3,'id':0x305,'pos':(800.,0.,0.),'evidence':'native item table'}]},10.) is None
    snap['enemies'] = []
    assert bot._heal(player,snap,10.) == {'tap':'triangle'}        # nobody near: the heal
    assert 'heal_deferred' not in bot.stats
    player['hp'] = 100
    bot2 = R.Bot(learn_dir=tmp_path)
    bot2.inventory_heal = InventoryHealth(bot2.stats,reader=lambda *a:dict(ui))
    assert bot2._heal(player,{'player':player,'inventory':[gun,spray],'enemies':[near]},10.) == {'tap':'triangle'}   # critical: heal anyway
