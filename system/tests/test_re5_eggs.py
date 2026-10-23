"""Native egg supply changes pickup source data; never fake carried weapon identities."""
import struct
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from gbox import re5_mods_tool as M
from gbox import mercs_bot as MB
from gbox.mercs.titles import re5_eggs as E,re5_ps3 as R
from test_re5_mods import FakeRE5,PLAYER,fresh_originals
from test_re5_mods_loadout import with_template

MANAGER,ARRAY,ACTOR,VOLUME=0x31A00000,0x31A01000,0x31B00000,0x31C00000

def memory():
    ad=with_template(FakeRE5());ad.u32(E.EGG_DEF,0x157C4D0);ad.u32(E.EGG_DEF+4,E.EGG_NAME)
    ad.put(E.EGG_NAME,b'WP36 EGG_X\t\t\0')
    for address,raw in E.NATIVE_SIGNATURES.items():ad.put(address,raw)
    ad.u32(R.S_ITEM,MANAGER);ad.u32(MANAGER,E.MANAGER_VT)
    ad.u32(MANAGER+0x28,1);ad.u32(MANAGER+0x34,ARRAY);ad.u32(ARRAY,ACTOR)
    ad.u32(ACTOR,0x15BC398);ad.u32(ACTOR+0x1110,968);ad.u32(ACTOR+0x111C,0)
    ad.put(ACTOR+0x30,struct.pack('>3f',100.,0.,0.));ad.u32(ACTOR+0x1BC0,E.SOURCE_VT)
    ad.put(ACTOR+0x1C36,struct.pack('>H',0x210));ad.u32(ACTOR+0x1C38,6)
    ad.u32(ACTOR+0x1C60,VOLUME);ad.u32(ACTOR+0x1C6C,ACTOR)
    ad.put(VOLUME,struct.pack('>3I',E.VOLUME_VT,ACTOR,0x07021000)+b'\1\0\0\0')
    g=M.RE5(ad);ad.writes.clear()
    snap={'player':{'ptr':PLAYER,'hp':1000,'hp_max':1000,'pos':(0.,0.,0.)},
          'nav':SimpleNamespace(route_avoiding_hazards=lambda start,end,hazards:[end]),'enemies':[]}
    return ad,g,snap

def test_native_supply_changes_only_ownerless_ammo_serialized_id_and_count():
    ad,g,snap=memory();E.state(g)['on']=True
    inventory=ad.read_memory(PLAYER+R.P_INV,24*R.INV_SLOT+4)
    row=E.prepare_pickup(g,snap)
    assert row['id']==0x136 and row['converted'] and row['handle']==968
    assert ad.writes==[(ACTOR+0x1C38,4),(ACTOR+0x1C36,2)]
    assert ad.read_memory(PLAYER+R.P_INV,len(inventory))==inventory
    assert g.u32(ACTOR)==0x15BC398 and g.u32(VOLUME+8)==0x07021000
    assert E.state(g).get('native_equipped') is not True
    assert 'waiting' in E.state(g)['status']

@pytest.mark.parametrize('what',['mine','medicine','owned','handle','source','volume','disabled','hazard','crowd','wrongcode'])
def test_unsafe_unrelated_or_unowned_pickup_source_is_never_converted(what):
    ad,g,snap=memory();E.state(g)['on']=True
    if what=='mine':ad.u32(ACTOR,0x162E5F8);ad.put(ACTOR+0x1C36,struct.pack('>H',0x10A))
    elif what=='medicine':ad.u32(ACTOR,0x15BBE28);ad.put(ACTOR+0x1C36,struct.pack('>H',0x304))
    elif what=='owned':ad.u32(ACTOR+0x111C,PLAYER)
    elif what=='handle':ad.u32(ACTOR+0x1110,0)
    elif what=='source':ad.u32(ACTOR+0x1BC0,0)
    elif what=='volume':ad.u32(VOLUME+4,ACTOR+4)
    elif what=='disabled':E.state(g)['on']=False
    elif what=='hazard':snap['nav'].route_avoiding_hazards=lambda *args:None
    elif what=='crowd':snap['enemies']=[{'hp':800,'pos':(80.,0.,0.)}]
    elif what=='wrongcode':ad.put(next(iter(E.NATIVE_SIGNATURES)),b'BAD!')
    assert E.prepare_pickup(g,snap) is None and not ad.writes

def test_disappearing_source_before_id_write_is_not_relabelled():
    ad,g,snap=memory();E.state(g)['on']=True;original=ad.write_memory
    def write(address,data):
        out=original(address,data)
        if address==ACTOR+0x1C38:ad.u32(MANAGER+0x28,0)
        return out
    ad.write_memory=write
    assert E.prepare_pickup(g,snap) is None
    assert ad.writes==[(ACTOR+0x1C38,4)]
    assert struct.unpack('>H',ad.read_memory(ACTOR+0x1C36,2))[0]==0x210

def test_native_game_created_weapon_pointer_and_owner_required_for_carried_confirmation():
    ad,g,snap=memory();item={'slot':5,'id':0x136,'rounds':5,'grid':0,'hand':True}
    assert E.carried(g,PLAYER,[item]) is None
    weapon=0x31D00000;ad.u32(PLAYER+R.P_INV+5*R.INV_SLOT+0x30,weapon)
    ad.u32(PLAYER+R.P_INV+5*R.INV_SLOT+8,0x136)
    ad.u32(PLAYER+R.P_INV+5*R.INV_SLOT+0x0C,5)
    ad.u32(PLAYER+R.P_INV+5*R.INV_SLOT+0x20,1)
    ad.put(PLAYER+R.P_INV+5*R.INV_SLOT+0x2D,b'\1')
    ad.u32(weapon,E.EGG_VT);ad.u32(weapon+0x111C,PLAYER)
    assert E.carried(g,PLAYER,[item]) is item
    ad.u32(weapon+0x111C,PLAYER+4)
    assert E.carried(g,PLAYER,[item]) is None


def test_unequipped_native_egg_can_be_selected_without_an_existing_weapon_pointer():
    ad,g,_=memory();item={'slot':5,'id':0x136,'rounds':5,'grid':0,'hand':False}
    address=PLAYER+R.P_INV+5*R.INV_SLOT
    ad.u32(address+8,0x136);ad.u32(address+0x0C,5);ad.put(address+0x2D,b'\1')
    assert E.inventory_item(g,PLAYER,[item]) is item
    assert E.carried(g,PLAYER,[item]) is None
    ad.u32(address+8,0x10F)
    assert E.inventory_item(g,PLAYER,[item]) is None


def test_later_native_egg_stack_in_hand_is_verified_over_first_unequipped_stack():
    ad,g,_=memory();rows=[{'slot':slot,'id':0x136,'rounds':5,'grid':slot,'hand':slot==5} for slot in (4,5)]
    weapon=0x31D00000
    for row in rows:
        address=PLAYER+R.P_INV+row['slot']*R.INV_SLOT
        ad.u32(address+8,0x136);ad.u32(address+0x0C,5);ad.put(address+0x2D,b'\1')
        ad.u32(address+0x20,int(row['hand']))
    ad.u32(PLAYER+R.P_INV+5*R.INV_SLOT+0x30,weapon)
    ad.u32(weapon,E.EGG_VT);ad.u32(weapon+0x111C,PLAYER)
    assert E.carried(g,PLAYER,rows) is rows[1]

def test_mode_default20_template_and_noammo_flag_restore_without_health_or_inventory_edits():
    ad,g,snap=memory();before=dict(ad.b)
    result=E.configure(g,True)
    assert result['verified'] and result['egg_rate_x']==20 and not result['native_equipped']
    assert g.u32(E.EGG_DEF+0x14)==1 and E.state(g)['on']
    assert result['egg_loadout_blocks']==50
    assert E.configure(g,False)['verified'] and g.u32(E.EGG_DEF+0x14)==0
    assert {a for a in ad.b if ad.b[a]!=before.get(a,0)}==set()
    assert not any(PLAYER<=a<PLAYER+0x3000 for a,n in ad.writes)

def test_egg_template_avoids_duplicate_mine_grid_without_relabelling_guns():
    ad,g,_=memory();base=M.TEMPLATE+24*M.TEMPLATE_BLOCK
    rec=lambda item,grid:struct.pack('>11I',item,5,0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,grid,0,0,0,0,0)
    ad.put(base+M.TEMPLATE_REC,rec(0x10A,7));ad.put(base+2*M.TEMPLATE_REC,rec(0x108,7))
    prior=ad.read_memory(base+2*M.TEMPLATE_REC,M.TEMPLATE_REC)
    assert E.templates(g)['verified']
    egg=struct.unpack('>11I',ad.read_memory(base+M.TEMPLATE_REC,M.TEMPLATE_REC))
    assert egg[0]==0x136 and egg[5]!=7
    assert ad.read_memory(base+2*M.TEMPLATE_REC,M.TEMPLATE_REC)==prior

def test_off_restores_only_unchanged_owned_ammo_source_and_never_retrieves_mine():
    ad,g,snap=memory();E.state(g)['on']=True;E.prepare_pickup(g,snap)
    assert E.configure(g,False)['verified']
    assert struct.unpack('>H',ad.read_memory(ACTOR+0x1C36,2))[0]==0x210
    assert g.u32(ACTOR+0x1C38)==6
    assert all(address not in (PLAYER+M.P_HP,PLAYER+M.P_MUTEKI) for address,size in ad.writes)

@pytest.mark.parametrize('rate',[0,20.01,float('nan'),float('inf')])
def test_egg_rate_is_bounded_before_any_write(rate):
    ad,g,_=memory()
    with pytest.raises(ValueError):E.configure(g,True,rate)
    assert not ad.writes


@pytest.mark.parametrize('seed',[0,1])
def test_first_character_constructor_inputs_keep_egg_after_actual_profile_hook_order(seed,monkeypatch):
    """Boot runs round ops before package; no constructor may see the randomizer's interim templates."""
    from gbox.mercs.titles import re5_mines
    ad,g,_=memory();E.configure(g,True)
    monkeypatch.setattr(re5_mines,'settings',lambda:dict(re5_mines.DEFAULT))
    prof=json.loads((Path(__file__).resolve().parents[1]/'profiles/gamedata/BLUS30491-ram.json').read_text())['mercs']
    prof.update(map_id='BLUS30491',platform='ps3');stats={}
    round_ops=[(op,{**kw,**({'seed':seed} if op=='random_cheats' else {})}) for op,kw in prof['round_ops']]
    assert MB.apply_ops(ad,round_ops,prof,stats)==[]
    assert stats['egg_loadout_blocks']==50
    # Boot's one-time package follows this hook and has no stats argument.
    assert MB.apply_ops(ad,prof['package'],prof)==[]
    for address,blocks in ((M.TEMPLATE,M.TEMPLATE_BLOCKS),*((a,10) for a in re5_mines.ORIGINAL_BANKS)):
        for block in range(blocks):
            rows=[struct.unpack('>11I',g.rd(address+block*M.TEMPLATE_BLOCK+i*M.TEMPLATE_REC,M.TEMPLATE_REC)) for i in range(12)]
            assert any(row[0]==E.EGG_ID and row[1]==5 and row[5]<9 for row in rows)
            assert not any(row[0]==0x10A and row[5]<9 for row in rows)
    assert E.state(g)['on'] and g.u32(E.EGG_DEF+0x14)==1
