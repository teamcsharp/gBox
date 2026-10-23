"""Exact-build playback only for mine placement and rotten-egg FIRE.

Native A12200/A18CD0 select051D for ID10A during item_put first/second.
The shared firing setup A08E68 selects051D for ordinary weapon FIRE.
Engine DFBA3C/E0128C proves +24 is playback rate; ownership and all three
motion IDs are reread before each float write. No action flags, clocks,
health, explosion immunity, or input are changed here.
"""
from . import re5_fire_animation as F

MINE_ACTIONS = frozenset({0x0163D7E0,0x0163D7A8})
MINE_VT, EGG_VT = 0x0162E5F8,0x0162E7F0
MINE_RATE, EGG_MAX_RATE = 5.,20.
MINE_LAYERS = ((0x300,0x051D),(0x3E0,0x0540))
MINE_SIGNATURES = {
    0x00A12200:bytes.fromhex('f821ff617c0802a6fba10078fbc10080dbc100907c7d1b78'),
    0x00A18CD0:bytes.fromhex('f821ff417c0802a6fbc100a8fbe100b0dbe100b87c7f1b78'),
}


def _weapon(memory,player,action,hand,*,item,vtable,placement=False):
    slot,word=hand
    if word!=item:
        raise F._Reject('item identity changed')
    if F._u32(memory,player+F.P_INVENTORY+slot*F.INVENTORY_STRIDE+0xC)<=0:
        raise F._Reject('item stock unavailable')
    # cItem begins four bytes after the manager; its +2C is the game-created
    # uWeapon pointer, not the inventory ID. Never create/relabel this pointer.
    weapon=F._u32(memory,player+F.P_INVENTORY+slot*F.INVENTORY_STRIDE+0x30)
    if not F._heap(weapon,0x1120) or F._u32(memory,weapon)!=vtable \
            or F._u32(memory,weapon+0x111C)!=player:
        raise F._Reject('game-created item weapon/owner unverified')
    if placement and F._u32(memory,action+0x1C)!=item:
        raise F._Reject('native placement action has not selected the mine')
    return weapon,vtable,player


def mine_view(memory,snapshot):
    if any(memory.rd(a,len(raw))!=raw for a,raw in MINE_SIGNATURES.items()):
        raise F._Reject('native mine placement code differs')
    return F._view(memory,snapshot,weapon_words={0x10A},action_vts=MINE_ACTIONS,
        max_multiplier=MINE_RATE,label='proximity mine',action_clock_offsets=(),layers=MINE_LAYERS,extra_guard=lambda m,p,a,h:
        _weapon(m,p,a,h,item=0x10A,vtable=MINE_VT,placement=True))


def egg_view(memory,snapshot):
    return F._view(memory,snapshot,weapon_words={0x136},max_multiplier=EGG_MAX_RATE,
        label='rotten egg',extra_guard=lambda m,p,a,h:
        _weapon(m,p,a,h,item=0x136,vtable=EGG_VT))


def mine_helper():
    return F.FireAnimation(observer=mine_view,max_multiplier=MINE_RATE,label='mine placement')


def egg_helper():
    return F.FireAnimation(observer=egg_view,max_multiplier=EGG_MAX_RATE,label='rotten egg throw')
