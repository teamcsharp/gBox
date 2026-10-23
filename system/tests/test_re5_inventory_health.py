"""Legal nonquick recovery selection is acknowledged from native inventory state."""
import copy
import struct

import pytest

from gbox.mercs.titles import re5_inventory_health as H

PL,MANAGER,UI=0x30400000,0x30100000,0x30500000
HERB={'slot':5,'id':0x305,'type':3,'item':5,'grid':8,'rounds':1,'hand':False}


class Memory:
    def __init__(self):
        self.data={}
        for address,data in H.SIGNATURES.items():self.put(address,data)
        self.put(H.GRID_TABLE,struct.pack('>36i',*(v for row in H.GRID_NEIGHBORS for v in row)))
        self.word(H.PLAYER_ROOT,MANAGER);self.word(MANAGER+0x28,PL);self.word(PL+H.PLAYER_INVENTORY_UI,UI)
        self.set_ui()
    def put(self,address,data):self.data.update({address+i:b for i,b in enumerate(data)})
    def word(self,address,value):self.put(address,struct.pack('>I',value))
    def rd(self,address,size):return bytes(self.data.get(address+i,0) for i in range(size))
    def wr(self,*a):raise AssertionError('memory writes are forbidden')
    def set_ui(self,*,state=2,cursor=4,opened=False,owner=0,context=False,fade=1.,delay=0.):
        data=bytearray(0x80);data[4]=state;data[0x68]=int(opened);data[0x7c]=int(context)
        struct.pack_into('>I',data,8,cursor);struct.pack_into('>I',data,0x10,owner)
        struct.pack_into('>2f',data,0x50,fade,delay);self.put(UI,data)


def snap(item=None):
    return {'player':{'ptr':PL,'hp':250,'hp_max':1000,'action':0},
            'inventory':[copy.deepcopy(item or HERB)]}


def test_native_decoder_requires_exact_code_table_player_and_pointer():
    memory=Memory();state=H.read_state(memory,PL)
    assert state['state']==2 and state['cursor']==4 and state['owner']==0 and not state['open']
    for address,value in ((next(iter(H.SIGNATURES)),b'\0'),(H.GRID_TABLE,b'\0'),
                          (MANAGER+0x28,struct.pack('>I',PL+16)),(PL+H.PLAYER_INVENTORY_UI,b'\0'*4)):
        changed=Memory();changed.put(address,value)
        assert H.read_state(changed,PL) is None


@pytest.mark.parametrize('changes',[{'cursor':9},{'owner':2},{'fade':float('nan')},{'delay':float('inf')}])
def test_invalid_native_menu_fields_disable_inputs(changes):
    memory=Memory();memory.set_ui(**changes)
    assert H.read_state(memory,PL) is None


def test_triangle_observed_cursor_dpad_l1_then_actual_in_hand_confirmation():
    memory=Memory();stats={};ctl=H.Controller(stats);s=snap()
    assert ctl.tick(memory,s,s['inventory'][0],0.)=={'tap':'triangle'}
    assert ctl.tick(memory,s,None,.2)=={'hold':set()}
    memory.set_ui(state=3,opened=True,cursor=4)
    assert ctl.tick(memory,s,None,.4)=={'tap':'ddown'}
    assert ctl.tick(memory,s,None,.6)=={'hold':set()}  # no blind second cursor press
    memory.set_ui(state=3,opened=True,cursor=7)
    assert ctl.tick(memory,s,None,.8)=={'tap':'dright'}
    memory.set_ui(state=3,opened=True,cursor=8)
    assert ctl.tick(memory,s,None,1.)=={'tap':'l1'}
    memory.set_ui(state=2,cursor=8)
    assert ctl.tick(memory,s,None,1.2)=={'hold':set()}
    s['inventory'][0]['hand']=True
    assert ctl.tick(memory,s,None,1.4) is None and not ctl.active
    assert stats['inventory_heal_equips_confirmed']==1 and 'heals' not in stats and 'heal_items_used' not in stats


def test_explicit_egg_inventory_controller_uses_legal_inputs_and_separate_equip_counters():
    memory=Memory();stats={};ctl=H.Controller(stats,allowed_ids={0x136},prefix='inventory_egg')
    s=snap({**HERB,'id':0x136,'grid':4})
    assert ctl.tick(memory,s,s['inventory'][0],0.)=={'tap':'triangle'}
    memory.set_ui(state=3,opened=True,cursor=4)
    assert ctl.tick(memory,s,None,.3)=={'tap':'l1'}
    memory.set_ui(state=2,cursor=4);s['inventory'][0]['hand']=True
    assert ctl.tick(memory,s,None,.6) is None
    assert stats['inventory_egg_equips_confirmed']==1 and 'inventory_heal_equips_confirmed' not in stats


def test_existing_identical_populated_grid_sibling_can_acknowledge_legal_equip():
    memory=Memory();stats={};ctl=H.Controller(stats)
    spray={**HERB,'slot':4,'id':0x304,'grid':4}
    s=snap(spray);s['inventory'].append({**spray,'slot':5})
    assert ctl.tick(memory,s,s['inventory'][0],0.)=={'tap':'triangle'}
    memory.set_ui(state=3,opened=True,cursor=4)
    assert ctl.tick(memory,s,None,.3)=={'tap':'l1'}
    memory.set_ui(state=2,cursor=4);s['inventory'][1]['hand']=True
    assert ctl.tick(memory,s,None,.6) is None and not ctl.active
    assert stats['inventory_heal_equips_confirmed']==1
    assert stats['inventory_heal_equipped_slot']==5
    assert 'heals' not in stats and 'heal_items_used' not in stats
    assert [row['rounds'] for row in s['inventory']]==[1,1]


@pytest.mark.parametrize('sibling_changes',[
    {'id':0x305}, {'grid':8}, {'rounds':0}, {'slot':24},
])
def test_different_or_empty_sibling_never_acknowledges_equip(sibling_changes):
    memory=Memory();stats={};ctl=H.Controller(stats)
    spray={**HERB,'slot':4,'id':0x304,'grid':4}
    s=snap(spray);s['inventory'].append({**spray,'slot':5,**sibling_changes})
    ctl.tick(memory,s,s['inventory'][0],0.)
    memory.set_ui(state=3,opened=True,cursor=4)
    assert ctl.tick(memory,s,None,.3)=={'tap':'l1'}
    memory.set_ui(state=2,cursor=4);s['inventory'][1]['hand']=True
    assert ctl.tick(memory,s,None,.6)=={'hold':set()} and ctl.active
    assert 'inventory_heal_equips_confirmed' not in stats


def test_new_sibling_or_equipped_sibling_before_own_l1_is_not_sequence_success():
    for appeared_after_opening in (False,True):
        memory=Memory();stats={};ctl=H.Controller(stats)
        spray={**HERB,'slot':4,'id':0x304,'grid':4};s=snap(spray)
        if not appeared_after_opening:s['inventory'].append({**spray,'slot':5})
        ctl.tick(memory,s,s['inventory'][0],0.)
        if appeared_after_opening:
            memory.set_ui(state=3,opened=True,cursor=4)
            assert ctl.tick(memory,s,None,.3)=={'tap':'l1'}
            s['inventory'].append({**spray,'slot':5})
        memory.set_ui(state=2,cursor=4);s['inventory'][1]['hand']=True
        ctl.tick(memory,s,None,.6)
        assert ctl.active and 'inventory_heal_equips_confirmed' not in stats


@pytest.mark.parametrize('item',[
    {**HERB,'id':0x306}, {**HERB,'id':0x10A}, {**HERB,'rounds':0},
    {**HERB,'grid':7}, {**HERB,'grid':None}, {**HERB,'hand':True},
])
def test_unusable_red_herbs_mines_empty_quick_and_held_items_never_open_menu(item):
    ctl=H.Controller();assert ctl.tick(Memory(),snap(item),item,0.) is None and not ctl.active


@pytest.mark.parametrize('changes',[{'owner':1},{'context':True},{'state':0x1e}])
def test_partner_context_and_non_cursor_state_are_closed_without_selecting_or_using(changes):
    memory=Memory();ctl=H.Controller();s=snap()
    assert ctl.tick(memory,s,s['inventory'][0],0.)=={'tap':'triangle'}
    memory.set_ui(state=3,opened=True,**{k:v for k,v in changes.items() if k!='state'})
    if 'state' in changes:memory.set_ui(state=changes['state'],opened=True)
    assert ctl.tick(memory,s,None,.3)=={'tap':'triangle'} and not ctl.active


def test_unowned_open_menu_and_layout_mismatch_never_send_input():
    memory=Memory();memory.set_ui(state=3,opened=True)
    ctl=H.Controller();s=snap()
    assert ctl.tick(memory,s,s['inventory'][0],0.) is None and not ctl.active
    memory=Memory();memory.put(0x9fda94,b'\0')
    assert ctl.tick(memory,s,s['inventory'][0],1.) is None


def test_bounded_failed_cursor_ack_closes_owned_menu_and_relocation_is_not_consumption():
    memory=Memory();ctl=H.Controller();s=snap()
    ctl.tick(memory,s,s['inventory'][0],0.)
    memory.set_ui(state=3,opened=True,cursor=4)
    assert ctl.tick(memory,s,None,.3)=={'tap':'ddown'}
    assert ctl.tick(memory,s,None,1.1)=={'tap':'triangle'} and not ctl.active
    ctl=H.Controller();memory=Memory();ctl.tick(memory,s,s['inventory'][0],2.)
    memory.set_ui(state=3,opened=True,cursor=4);s['inventory'][0]['grid']=6
    assert ctl.tick(memory,s,None,2.3)=={'tap':'triangle'} and 'heals' not in ctl.stats


def test_prompt_death_and_player_replacement_release_helper_without_world_actions():
    for change in ('prompt','death','player'):
        memory=Memory();ctl=H.Controller();s=snap();ctl.tick(memory,s,s['inventory'][0],0.)
        if change=='prompt':s['prompt']='mash'
        elif change=='death':s['player']['hp']=0
        else:s['player']['ptr']=PL+16
        assert ctl.tick(memory,s,None,.3) is None and not ctl.active


def test_aim_is_released_before_opening_and_total_sequence_is_bounded():
    memory=Memory();ctl=H.Controller();s=snap();s['player']['action']=2
    assert ctl.tick(memory,s,s['inventory'][0],0.)=={'hold':set()}
    assert ctl.tick(memory,s,None,4.1) is None and not ctl.active
