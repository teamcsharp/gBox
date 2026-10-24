import struct
from types import SimpleNamespace
import pytest

from gbox import re5_mods_tool as T
from gbox.mercs.titles import re5_mines as M
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401
read_ground = M.ground_mines


@pytest.fixture(autouse=True)
def observed_ground(monkeypatch):
    ground = {}
    monkeypatch.setattr(M, 'ground_mines', lambda _: ground)
    return ground


def deployed(ground):
    ground[0x30800000] = {'pos': (0,0,0), 'arming_s': 2.8, 'detonating': False}


def template_game():
    m = FakeRE5()
    for b in range(T.TEMPLATE_BLOCKS):
        for i,grid in enumerate((3,1,5,0,2,7,4,6,8,9,10,11)):
            item = T.TEMPLATE_SIGNATURE[1] if grid==9 else 0x100 if grid==11 else 0x112 if grid==3 else 0x304 if grid==7 else 0
            m.put(T.TEMPLATE+b*T.TEMPLATE_BLOCK+i*T.TEMPLATE_REC,
                  struct.pack(">11I",item,0xffffffff,0xffffffff,0xffffffff,0xffffffff,grid,int(grid==3),0,0,0,0))
    raw=m.read_memory(T.TEMPLATE,10*T.TEMPLATE_BLOCK)
    for address in M.ORIGINAL_BANKS:
        m.put(address,raw)
        m.u32(address+9*T.TEMPLATE_REC,M.ORIGINAL_KNIVES[address])
        m.u32(address+11*T.TEMPLATE_REC,0x100)
        for index in range(10):m.put(M.ORIGINAL_DESCRIPTORS[address]+8*index,struct.pack('>2I',address+index*T.TEMPLATE_BLOCK,12))
    for index,address in enumerate(T.TEMPLATE_DESCRIPTORS):m.put(address,struct.pack('>2I',T.TEMPLATE+index*T.TEMPLATE_BLOCK,12))
    return m


def test_mines_use_spawn_templates_preserving_existing_items_and_live_inventory():
    m=template_game(); g=T.RE5(m)
    before_live=g.rd(0x303f8a00+T.INV_OFS,24*T.SLOT)
    result=M.templates(g)
    assert result["verified"] and result["mine_loadout_blocks"]==50
    records=T.template_records(g.rd(T.TEMPLATE,T.TEMPLATE_BLOCKS*T.TEMPLATE_BLOCK))
    for b in range(30):
        group=[r for r in records if r[0]//T.TEMPLATE_BLOCK==b]
        assert any(r[1]==0x10a and r[3]==7 and r[2]==5 for r in group)
        assert any(r[1]==0x304 and r[3]!=7 for r in group)
        assert any(r[1]==0x112 and r[3]==3 and r[4]==1 for r in group)
    assert g.rd(0x303f8a00+T.INV_OFS,24*T.SLOT)==before_live
    assert g.u32(T.DEF_TABLE+10*T.DEF_STRIDE+T.DEF_NOAMMO)==1


def test_empty_grid_seven_stub_cannot_hide_mine_behind_a_shotgun():
    m=template_game();g=T.RE5(m)
    base=M.ORIGINAL_BANKS[0]+5*T.TEMPLATE_BLOCK
    empty=[0,0xffffffff,0xffffffff,0xffffffff,0xffffffff,7,0,0,0,0,0]
    gun=[0x108,3,0xffffffff,0xffffffff,0xffffffff,7,0,0x01020304,9,8,7]
    m.put(base+T.TEMPLATE_REC,struct.pack('>11I',*empty))
    m.put(base+8*T.TEMPLATE_REC,struct.pack('>11I',*gun))
    assert M.templates(g)['verified']
    raw=g.rd(base,T.TEMPLATE_BLOCK)
    rows=[struct.unpack_from('>11I',raw,i*T.TEMPLATE_REC) for i in range(12)]
    carried=[row for row in rows if row[0] and row[5]<9]
    assert len({row[5] for row in carried})==len(carried)
    assert rows[1][0]==0x10a and rows[1][5]==7
    assert rows[8][:5]==tuple(gun[:5]) and rows[8][6:]==tuple(gun[6:]) and rows[8][5]!=7
    assert M.templates(g)['verified'] and g.rd(base,T.TEMPLATE_BLOCK)==raw


def test_mine_controller_does_not_count_a_press_or_interrupted_attempt(monkeypatch):
    monkeypatch.setattr(M,"settings",lambda:dict(M.DEFAULT,interval_s=2))
    stats={}; c=M.Controller(SimpleNamespace(),stats,lambda *a:{"tap":"ddown"})
    mine={"id":0x10a,"item":10,"type":1,"slot":2,"grid":7,"rounds":5,"hand":True}
    snap={"player":{"ptr":0x303f8a00,"pos":(0,0,0),"hp":1000,"action":0},"inventory":[mine]}
    assert c.tick(snap,0) is None
    assert c.tick(snap,3)=={"hold":{"l1"}}
    assert c.tick(snap,3.4)=={"hold":{"l1"}}
    assert stats.get("mines_placed",0)==0
    assert c.tick(dict(snap,prompt="mash"),3.5) is None
    assert stats.get("mines_placed",0)==0
    c.tick(snap,9)
    assert stats.get("mines_placed",0)==0 and "unconfirmed" in stats["mine_status"]


def test_loadout_with_no_grid_seven_uses_an_empty_constructor_record():
    m=template_game();g=T.RE5(m)
    for b in range(T.TEMPLATE_BLOCKS):
        # Four live costumes omit an empty grid-seven record.
        address=T.TEMPLATE+b*T.TEMPLATE_BLOCK+5*T.TEMPLATE_REC
        m.put(address,struct.pack('>11I',0,0xffffffff,0xffffffff,0xffffffff,0xffffffff,4,0,0,0,0,0))
    result=M.templates(g)
    assert result['mine_loadout_blocks']==50
    records=T.template_records(g.rd(T.TEMPLATE,T.TEMPLATE_BLOCKS*T.TEMPLATE_BLOCK))
    assert sum(r[1]==0x10a and r[3]==7 for r in records)==30


def test_deployed_mine_pickup_is_blocked_but_bonus_and_traversal_prompts_remain(monkeypatch):
    from gbox.mercs.titles import re5_ps3 as R
    raw=FakeRE5();m=T.RE5(raw);target=0x30500000
    request={'kind':R.BTN_STAGE,'token':'mash:square','target':target}
    monkeypatch.setattr(R,'selected_prompt',lambda _,**kwargs:request)
    for vtable in R.MINE_VTABLES:
        raw.u32(target,vtable)
        assert R.prompt(m) is None and not R.stage_prompt(m)
    for vtable in (R.HOURGLASS_VT,0x015a0000):
        raw.u32(target,vtable)
        assert R.prompt(m)=='mash:square' and R.stage_prompt(m)
    bot=object.__new__(R.Bot);bot.m=m;bot.stats={}
    raw.u32(target,next(iter(R.MINE_VTABLES)))
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}

    assert bot._leave_deployed_mines({'hold':{'l1','r1'}})=={'hold':{'l1','r1'}}
    raw.u32(target,R.HOURGLASS_VT)
    assert bot._leave_deployed_mines({'tap':'square'})=={'tap':'square'}


def test_mine_consumption_is_acknowledged_once(monkeypatch, observed_ground):
    monkeypatch.setattr(M,"settings",lambda:dict(M.DEFAULT,interval_s=2))
    stats={}; c=M.Controller(SimpleNamespace(),stats,lambda *a:None)
    mine={"id":0x10a,"item":10,"type":1,"slot":2,"grid":7,"rounds":5,"hand":True}
    snap={"player":{"ptr":0x303f8a00,"pos":(0,0,0),"hp":1000,"action":0},"inventory":[mine]}
    c.tick(snap,0);c.tick(snap,3)
    mine["rounds"]=4
    deployed(observed_ground)
    c.tick(snap,4);c.tick(snap,4.2)
    assert stats["mines_placed"]==1


def test_infinite_game_created_stack_needs_new_ground_actor(monkeypatch, observed_ground):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    ad=FakeRE5(); ad.u32(T.DEF_TABLE+10*T.DEF_STRIDE+T.DEF_NOAMMO,1)
    stats={};c=M.Controller(SimpleNamespace(adapter=ad),stats,lambda *a:None)
    mine={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':True}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine]}
    c.tick(snap,0); c.tick(snap,3); c.tick(snap,3.2)
    assert stats.get('mines_placed',0)==0
    deployed(observed_ground); c.tick(snap,3.5)
    assert stats['mines_placed']==1 and stats['mine_infinite_supply_verified']
    assert mine['rounds']==5 and c.escape['actor']==0x30800000


def test_mine_equipping_keeps_combat_from_cancelling_the_change(monkeypatch):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    attempts=[]
    def switch(*args):
        attempts.append(args)
        return {'tap':'ddown'} if len(attempts)==1 else None
    c=M.Controller(SimpleNamespace(),{},switch)
    mine={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':False}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine]}
    c.tick(snap,0)
    assert c.tick(snap,3)=={'hold':set()}
    assert c.tick(snap,3.3)=={'hold':set()}
    assert c.tick(snap,4.1)=={'tap':'ddown'}
    assert c.tick(snap,4.4)=={'hold':set()}
    assert len(attempts)==1


def test_consumed_mine_restores_a_gun_before_resuming_combat(monkeypatch, observed_ground):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    switched=[]
    def switch(item,now,why):
        switched.append(item['id'])
        return {'tap':'dleft'}
    c=M.Controller(SimpleNamespace(),{},switch)
    mine={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':True}
    gun={'id':0x102,'item':2,'type':1,'slot':0,'grid':3,'rounds':10,'hand':False}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine,gun]}
    c.tick(snap,0);c.tick(snap,3)
    mine['rounds']=4
    deployed(observed_ground)
    assert c.tick(snap,4)=={'hold':set()} and switched==[]
    assert c.tick(snap,4.4)=={'hold':set()} and switched==[]
    assert c.tick(snap,5.3)=={'tap':'dleft'} and switched==[0x102]
    mine['hand']=False;gun['hand']=True
    assert c.tick(snap,5.5) is None and c.restore is None


def test_verified_mine_requires_measured_escape_before_more_placement(monkeypatch, observed_ground):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    stats={}; c=M.Controller(SimpleNamespace(),stats,lambda *a:None)
    mine={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':True}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine]}
    c.tick(snap,0); c.tick(snap,3); mine['rounds']=4; deployed(observed_ground)
    c.tick(snap,3.5)
    assert c.escape['actor']==0x30800000
    assert c.tick(snap,12) is None and stats['mine_attempts']==1
    assert not c.clear_escape(12,(0,0,500))
    assert c.clear_escape(13,(0,0,650)) and c.escape is None
    assert stats['mine_retreats_completed']==1
    assert c.events[-1]['kind']=='retreat_complete' and c.events[-1]['distance']==650


def test_world_mine_pickup_label_cannot_turn_a_bonus_punch_into_recovery():
    from test_re5_mercs import world,with_prompt,PLAYER
    from gbox.mercs.titles import re5_ps3 as R
    target=0x30500000
    memory=with_prompt(world(),R.BTN_STAGE,PLAYER,target)
    memory.u32(target,0x015b44b8)  # uIt050A pickup item; actual deployed weapons are uWp0a
    memory.u32(0x328e1fe0+0x24,0x3b)
    assert R.prompt(memory) is None
    assert R.selected_prompt(memory,include_item_pickups=True)['target']==target
    bot=object.__new__(R.Bot);bot.m=memory;bot.stats={}
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}
    assert bot.stats['mine_pickups_avoided']==1
    memory.u32(0x328e1fe0+R.BTN_TARGET,0)
    memory.u32(0x328e1fe0+R.BTN_OWNER,target)
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}
    # Loose-item requests can be player-owned and carry no mine pointer.
    memory.u32(0x328e1fe0+R.BTN_OWNER,PLAYER)
    memory.u32(0x328e1fe0+0x24,R.LOOSE_ITEM_PICKUP)
    assert R.prompt(memory) is None and not R.stage_prompt(memory)
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}
    # Captured recovery uses a small item handle, not a mine actor pointer.
    memory.u32(0x328e1fe0+0x24,R.PICKUP_LABEL)
    memory.u32(0x328e1fe0+R.BTN_TARGET,36)
    assert R.prompt(memory) is None and not R.stage_prompt(memory)
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}


def test_consumption_without_a_ground_mine_is_not_placement(monkeypatch):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    stats={};c=M.Controller(SimpleNamespace(),stats,lambda *a:None)
    mine={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':True}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine]}
    c.tick(snap,0);c.tick(snap,3);mine['rounds']=4
    assert c.tick(snap,3.7)=={'hold':set()}
    c.tick(snap,9)
    assert stats.get('mines_placed',0)==0 and 'unconfirmed' in stats['mine_status']


def test_equipped_stack_and_new_actor_verify_placement_and_detonation(monkeypatch, observed_ground):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    stats={};c=M.Controller(SimpleNamespace(),stats,lambda *a:None)
    first={'id':0x10a,'item':10,'type':1,'slot':2,'grid':7,'rounds':5,'hand':False}
    held=dict(first,slot=6,hand=True)
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[first,held]}
    c.tick(snap,0);assert c.tick(snap,3)=={'hold':{'l1'}}
    held['rounds']=4;deployed(observed_ground);c.tick(snap,3.8)
    assert stats['mines_placed']==1
    observed_ground[0x30800000].update(arming_s=0,detonating=True)
    c.tick(snap,4);c.tick(snap,4.1)
    assert stats['mine_detonations_observed']==1


def test_place_label_is_not_a_pickup_request():
    from gbox.mercs.titles import re5_ps3 as R
    assert not R.mine_pickup(SimpleNamespace(),{'token':'mash:l1','label':R.PLACE_LABEL})


def test_switch_cooldown_does_not_repeatedly_block_gunplay(monkeypatch):
    monkeypatch.setattr(M,'settings',lambda:dict(M.DEFAULT,interval_s=2))
    calls=[]
    c=M.Controller(SimpleNamespace(),{},lambda *a:calls.append(a))
    mine={'id':0x10a,'slot':2,'grid':7,'rounds':5,'hand':False}
    snap={'player':{'ptr':0x303f8a00,'pos':(0,0,0),'hp':1000,'action':0},'inventory':[mine]}
    c.tick(snap,0);c.tick(snap,3)
    assert c.tick(snap,3.5)=={'hold':set()} and not calls
    assert c.tick(snap,4.1) is None and len(calls)==1
    assert c.tick(snap,5) is None and c.tick(snap,8) is None and len(calls)==1


def test_ground_reader_excludes_held_weapons_and_reads_arming_and_explosion():
    from gbox.mercs.titles import re5_ps3 as R
    raw=FakeRE5();m=T.RE5(raw);manager=0x30400000;held=0x30500000;ground=0x30600000
    raw.u32(R.S_UNIT,manager)
    raw.u32(manager+R.UNIT_LINES+10*R.LINE_STRIDE+R.LINE_FIRST,held)
    for ptr,nxt in ((held,ground),(ground,0)):
        raw.u32(ptr,0x0162e5f8);raw.u32(ptr+R.UNIT_NEXT,nxt)
        raw.put(ptr+M.PLACED,b'\x00');raw.put(ptr+M.DETONATING,b'\x00')
        raw.put(ptr+M.ARMING,struct.pack('>f',3))
    assert read_ground(m)=={}
    raw.put(ground+M.PLACED,b'\x01');raw.put(ground+0x30,struct.pack('>3f',1,2,3))
    assert read_ground(m)=={ground:{'pos':(1,2,3),'arming_s':3,'detonating':False}}
    raw.put(ground+M.ARMING,struct.pack('>f',0));raw.put(ground+M.DETONATING,b'\x01')
    assert read_ground(m)[ground]['detonating']
