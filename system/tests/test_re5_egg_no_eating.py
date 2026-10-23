"""Recorded Rebecca failure: displayed stage Square ate136 and HP1000->500.

The fast mash path skips PromptPresser.ok; source and final native equipment
fences must stop eating while preserving actual recovery items/combat QTEs.
"""
from gbox.mercs import reactions
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import world,with_prompt,PLAYER,ENEMIES


def carried(memory,slot,item,grid,hand):
    address=PLAYER+R.P_INV+slot*R.INV_SLOT
    for offset,value in ((R.INV_ID,item),(R.INV_ROUNDS,5),(R.INV_CAP,5),
                         (R.INV_GRID,grid),(R.INV_HAND,int(hand))):
        memory.u32(address+offset,value)
    memory.put(address+R.INV_USED,b'\1')


def scene():
    memory=with_prompt(world(),R.BTN_STAGE,PLAYER,0)
    carried(memory,0,0x136,7,True);carried(memory,1,0x11D,3,False)
    return memory


def test_recorded_stage_square_is_fenced_before_fast_mash_skips_policy(tmp_path):
    memory=scene();request=R.selected_prompt(memory)
    assert request['token']=='mash:square' and request['kind']==R.BTN_STAGE
    assert R.egg_square_blocked(memory,request) is True
    assert R.prompt(memory) is None and R.stage_prompt(memory)
    stats={};driver=R.RE5PS3();bot=R.Bot(memory,stats=stats,learn_dir=tmp_path)
    presser=reactions.PromptPresser(source=driver.prompt_source(memory,stats),keys=driver.prompt_keys,stats=stats)
    assert presser.step(10.,ok=lambda button:bot.prompt_ok(button,R.snapshot(memory),10.)) is None
    assert not presser.mashing and stats.get('qte_presses',0)==0


def test_driver_rechecks_native_egg_even_if_an_older_prompt_token_escaped(monkeypatch):
    memory=scene();monkeypatch.setattr(R,'prompt',lambda _: 'mash:square')
    assert R.RE5PS3().prompt_source(memory,{})() is None


def test_final_square_restores_existing_gun_then_requires_actual_native_hand(tmp_path):
    memory=scene();now=[10.];bot=R.Bot(memory,clock=lambda:now[0],learn_dir=tmp_path)
    bot._control_state={'rotten_eggs':{'on':True}}
    bot._observed_snap=R.snapshot(memory)
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}
    assert not bot.prompt_ok('square',bot._observed_snap,now[0])
    now[0]+=1.1
    assert bot._leave_deployed_mines({'tap':'square'})=={'tap':'dleft'}
    assert bot.stats['egg_square_uses_blocked']==2
    # Pressing D-pad is not confirmation; Square still blocked while136 remains native in hand.
    now[0]+=.1
    assert bot._leave_deployed_mines({'tap':'square'})!={'tap':'square'}
    memory.u32(PLAYER+R.P_INV+R.INV_HAND,0)
    memory.u32(PLAYER+R.P_INV+R.INV_SLOT+R.INV_HAND,1)
    assert bot._leave_deployed_mines({'tap':'square'})=={'tap':'square'}


def test_stale_healing_snapshot_cannot_send_square_to_actual_native_egg(tmp_path):
    memory=scene();bot=R.Bot(memory,learn_dir=tmp_path)
    stale=R.snapshot(memory);stale['inventory'][0].update(id=0x304,type=3,item=4)
    bot._observed_snap=stale
    assert bot._leave_deployed_mines({'tap':'square'})!={'tap':'square'}


def test_actual_native_spray_square_stays_legal_even_if_snapshot_still_says_egg(tmp_path):
    memory=scene();bot=R.Bot(memory,learn_dir=tmp_path);bot._observed_snap=R.snapshot(memory)
    memory.u32(PLAYER+R.P_INV+R.INV_ID,0x304)
    assert R.egg_square_blocked(memory,R.selected_prompt(memory)) is False
    assert bot._leave_deployed_mines({'tap':'square'})=={'tap':'square'}


def test_unreadable_fresh_inventory_blocks_square_even_with_stale_spray_snapshot(tmp_path):
    memory=scene();bot=R.Bot(memory,learn_dir=tmp_path)
    stale=R.snapshot(memory);stale['inventory'][0].update(id=0x304,type=3,item=4)
    bot._observed_snap=stale;read=memory.rd
    def unreadable(address,size):
        if address==PLAYER+R.P_INV:raise OSError('native equipment changed during read')
        return read(address,size)
    memory.rd=unreadable
    assert R.egg_square_blocked(memory,R.selected_prompt(memory)) is None
    assert bot._leave_deployed_mines({'tap':'square'})=={'hold':set()}
    memory.rd=read;memory.u32(PLAYER+R.P_INV+R.INV_ID,0x304)
    assert bot._leave_deployed_mines({'tap':'square'})=={'tap':'square'}


def test_current_enemy_owned_combat_square_qte_remains_allowed_with_native_egg():
    memory=world(action=R.P_GRABBED,enemies=[((0.,0.,150.),800,800)])
    carried(memory,0,0x136,7,True)
    with_prompt(memory,0,ENEMIES[0],PLAYER)
    request=R.selected_prompt(memory)
    assert R.egg_square_blocked(memory,request) is False
    stats={};driver=R.RE5PS3()
    pp=reactions.PromptPresser(source=driver.prompt_source(memory,stats),keys=driver.prompt_keys,stats=stats)
    assert pp.step(10.,ok=lambda _:False)==[('square',)]
    assert pp.mashing
