"""Placement/egg speed touches only verified player-owned playback floats."""
import struct
import pytest
from gbox.mercs.titles import re5_fire_animation as F,re5_item_animation as A
from test_re5_fire_animation import Memory,snapshot,PLAYER,ACTION,SCOPE,rates

WEAPON=0x30600000

def setup(kind):
    m=Memory();s=snapshot();item=0x10A if kind=='mine' else 0x136
    vt=A.MINE_VT if kind=='mine' else A.EGG_VT
    m.pack(PLAYER+F.P_INVENTORY+8,'>I',item)
    m.pack(PLAYER+F.P_INVENTORY+0xC,'>I',5)
    m.pack(PLAYER+F.P_INVENTORY+0x30,'>I',WEAPON)
    m.pack(WEAPON,'>I',vt);m.pack(WEAPON+0x111C,'>I',PLAYER)
    s['inventory'][0]['id']=item
    if kind=='mine':
        m.pack(ACTION,'>I',0x163D7E0);m.pack(ACTION+0x1C,'>I',0x10A)
        m.pack(PLAYER+0x3E0+4,'>H',0x0540)
        m.pack(PLAYER+0x4C0+4,'>H',0xFFFF)
        for address,raw in A.MINE_SIGNATURES.items():m.put(address,raw)
    return m,s,A.mine_helper() if kind=='mine' else A.egg_helper()

@pytest.mark.parametrize('kind,rate',[('mine',5.),('egg',20.)])
def test_exact_owned_actions_write_three_rates_only_and_restore(kind,rate):
    m,s,helper=setup(kind);before=dict(m.data)
    result=helper.update(m,s,enabled=True,multiplier=rate,scope=SCOPE)
    expected=[rate,rate,1.] if kind=='mine' else [rate]*3
    assert result['active'] and result['verified'] and rates(m)==expected
    assert {a for a in m.data if m.data[a]!=before.get(a)}<= {
        PLAYER+base+0x24+n for base,_ in F.LAYERS for n in range(4)}
    assert struct.unpack('>I',m.rd(PLAYER+F.P_INVENTORY+0xC,4))[0]==5
    assert helper.update(m,s,enabled=True,multiplier=rate,scope=SCOPE)['writes']==0
    assert helper.update(m,s,enabled=False,multiplier=rate,scope=SCOPE)['restored']==(2 if kind=='mine' else 3)
    assert rates(m)==[1.]*3


def test_recorded_native_mine_layers_do_not_accelerate_absent_third_or_secondary_fire_layer():
    m,s,h=setup('mine')
    assert h.update(m,s,enabled=True,multiplier=5.,scope=SCOPE)['writes']==2
    assert {address for address,data in m.writes}=={PLAYER+0x324,PLAYER+0x404}
    m,s,h=setup('mine');m.pack(PLAYER+0x3E0+4,'>H',0x051E)
    assert not h.update(m,s,enabled=True,multiplier=5.,scope=SCOPE)['active'] and not m.writes

@pytest.mark.parametrize('kind',['mine','egg'])
@pytest.mark.parametrize('field', ['owner','weapon','id','motion','code','dead','empty'])
def test_unknown_or_reused_action_item_or_motion_never_writes(kind,field):
    m,s,helper=setup(kind)
    if field=='owner':m.pack(WEAPON+0x111C,'>I',PLAYER+4)
    elif field=='weapon':m.pack(WEAPON,'>I',A.EGG_VT if kind=='mine' else A.MINE_VT)
    elif field=='id':m.pack(PLAYER+F.P_INVENTORY+8,'>I',0x10F)
    elif field=='motion':m.pack(PLAYER+0x304,'>H',0x123)
    elif field=='code':m.put(next(iter(A.MINE_SIGNATURES if kind=='mine' else F.SIGNATURES)),b'BAD!')
    elif field=='dead':m.pack(PLAYER+F.P_HP,'>h',1)
    elif field=='empty':m.pack(PLAYER+F.P_INVENTORY+0xC,'>I',0)
    assert not helper.update(m,s,enabled=True,multiplier=5. if kind=='mine' else 20.,scope=SCOPE)['active']
    assert not m.writes

def test_native_mine_second_action_and_rate_bounds_are_separate_from_egg():
    m,s,h=setup('mine');m.pack(ACTION,'>I',0x163D7A8)
    assert h.update(m,s,enabled=True,multiplier=5.,scope=SCOPE)['active']
    m,s,h=setup('mine');m.pack(ACTION+0x20,'>I',0xFFFFFFFF)
    assert h.update(m,s,enabled=True,multiplier=5.,scope=SCOPE)['active']  # item_put fields are not FIRE clocks
    for kind,rate in [('mine',5.01),('egg',20.01)]:
        m,s,h=setup(kind)
        assert not h.update(m,s,enabled=True,multiplier=rate,scope=SCOPE)['verified'] and not m.writes

def test_egg_helper_never_accelerates_bow_or_magnum_and_owner_change_stops_next_write():
    for item in (0x10F,0x11B):
        m,s,h=setup('egg');m.pack(PLAYER+F.P_INVENTORY+8,'>I',item);s['inventory'][0]['id']=item
        assert not h.update(m,s,enabled=True,multiplier=20.,scope=SCOPE)['active'] and not m.writes
    m,s,h=setup('egg');m.after_write=lambda a,b:m.pack(WEAPON+0x111C,'>I',PLAYER+4)
    assert not h.update(m,s,enabled=True,multiplier=20.,scope=SCOPE)['verified']
    assert len(m.writes)==1
