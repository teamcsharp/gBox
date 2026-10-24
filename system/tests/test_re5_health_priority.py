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
