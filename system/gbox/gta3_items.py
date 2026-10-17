"""Exact-build GTA III PS2 weapons, through the existing verified EE call queue.

Inventory layout and routine identities are from the owned SLUS-20062 ELF,
SHA256 2a1322e74cfa41067fdbd3c7ec10b87c1b784e224f6f2c0a69cc36548dc06762.
GetWeaponSlot computes ped + type*20 + 0x3ac. GiveWeapon updates total ammo
at +0x0c and initializes new weapons through the game's own CWeapon routine.
"""
import hashlib
import struct
import threading

from pydantic import BaseModel, Field

from .models import Permission
from .registry import Unsupported, tool

SLOT_BASE, SLOT_SIZE, SLOT_COUNT, CURRENT = 0x3AC, 20, 13, 0x4B4
GIVE_WEAPON = 0x1D8950
FINGERPRINTS = (
    (0x1D8950,188,'35db9d607d35094ead22261d805dd1d85bea0d13360146fa0283e313c709747b'),
    (0x1D8910,52,'2bf47d2605df79ace2e5e970413c106095fae3ca31531168a30ac0addebe8a32'),
    (0x2E1F00,584,'46765470f658f4ec7a21039d717506e57a427f6880de64dbc4fcba206e419190'),
    (0x2DE230,964,'1eed4cc95c79a7205c808a6e0893d3acac88a73c8d804eccfb708c4e7ee86f29'),
    (0x291560,44,'09e6a9cbad0658b8f30a808aaa5949c650364dbe1bfbe7f768777c5c9f4bb313'),
)
# Native weapon enum and drawable model IDs in the owned DATA/DEFAULT.IDE.
WEAPONS = (
    ('Unarmed',None),('Baseball bat',172),('Pistol',173),('Uzi',178),('Shotgun',176),
    ('AK-47',171),('M16',180),('Sniper rifle',177),('Rocket launcher',175),
    ('Flamethrower',181),('Molotov',174),('Grenade',170),('Detonator',None),
)
ALIASES={'bat':1,'colt45':2,'colt':2,'handgun':2,'ak47':5,'sniper':7,'rpg':8,'rocket':8,
         'flame':9,'molotovcocktail':10,'grenades':11}
_locks={}
_guard=threading.Lock()


def weapon_id(value):
    key=''.join(c for c in str(value).lower() if c.isalnum())
    if key.isdigit() and 0<=int(key)<SLOT_COUNT:return int(key)
    for i,(name,_) in enumerate(WEAPONS):
        if key==''.join(c for c in name.lower() if c.isalnum()):return i
    if key in ALIASES:return ALIASES[key]
    raise ValueError('Choose a GTA III weapon from the list')


def check(m,game):
    from .gta_games import GAMES
    if game.get('platform')!='ps2' or game.get('game_id') not in ('265819390074bb4e','82173dff3bf1ad6d'):
        raise Unsupported('Weapon inventory is verified for GTA III PS2 SLUS-20062 only')
    for addr,size,digest in FINGERPRINTS:
        if hashlib.sha256(m.rd(addr,size)).hexdigest()!=digest:
            raise Unsupported(f'GTA III weapon routine at {addr:#x} does not match the owned executable')
    from .gta_mods_tool import player_ped
    ped=player_ped(m,GAMES['gta3'])
    if ped%16 or not 0x100000<=ped<=0x2000000-0x5B0:
        raise Unsupported('Enter GTA III gameplay before changing weapons')
    return ped,GAMES['gta3']


def inventory(m,ped):
    data=m.rd(ped+SLOT_BASE,SLOT_SIZE*SLOT_COUNT)
    selected=m.rd(ped+CURRENT,1)[0]
    rows=[]
    for slot,(name,model) in enumerate(WEAPONS):
        typ,state,clip,total,timer=struct.unpack_from('<5I',data,slot*SLOT_SIZE)
        if typ not in (0,slot) or state>5 or total>99999 or clip>99999:
            raise Unsupported('Native GTA III weapon inventory is not initialized or has an unsupported layout')
        rows.append({'slot':slot,'name':name,'present':typ==slot,'type':typ,'state':state,
                     'clip':clip,'ammo':total,'equipped':selected==slot,'model':model})
    return rows


def execute(ad,game,op='list',weapon='',ammo=9999):
    from . import gta_mods_tool as G
    with G.transaction(ad):
        return _execute(ad,game,op,weapon,ammo)


def _execute(ad,game,op='list',weapon='',ammo=9999):
    from . import gta_mods_tool as G
    m=G.Mem(ad);ped,profile=check(m,game)
    before=inventory(m,ped)
    if op=='list':return {'inventory':before,'weapons':[{'id':i,'name':n} for i,(n,_) in enumerate(WEAPONS)],
        'verified':True,'note':'GTA III has weapon slots; mission objects are not a universal inventory.'}
    if op not in ('give','all_weapons'):raise ValueError('Choose list, give or all_weapons')
    if not isinstance(ammo,int) or not 1<=ammo<=99999:raise ValueError('Ammo must be 1–99999')
    wanted=list(range(1,12)) if op=='all_weapons' else [weapon_id(weapon)]
    # A detonator depends on an armed remote vehicle bomb; adding an inert slot
    # is not equivalent to giving the user a functioning mission object.
    if 12 in wanted:raise Unsupported('A working detonator is created by the native remote-car-bomb flow, not a generic weapon grant')
    install=G.install(m,profile)
    def calls(batch):
        if G.player_ped(m,profile)!=ped:raise RuntimeError('The player changed; no new weapon calls were queued')
        if m.u32(G.DATA+G.D_CQ_N):raise RuntimeError('Another GTA command is pending; this operation was not queued or retried')
        return G.call(m,batch,timeout=6)
    models=[WEAPONS[i][1] for i in wanted if WEAPONS[i][1] is not None]
    for offset in range(0,len(models),G.CQ_MAX):
        calls([{'fn':profile['fn']['RequestModel'],'a0':model,'a1':0} for model in models[offset:offset+G.CQ_MAX]])
    if models:calls([{'fn':profile['fn']['LoadAllRequestedModels'],'a0':0}])
    for offset in range(0,len(wanted),G.CQ_MAX):
        calls([{'fn':GIVE_WEAPON,'a0':ped,'a1':i,'a2':ammo if i>1 else 1} for i in wanted[offset:offset+G.CQ_MAX]])
    after=inventory(m,ped)
    missing=[i for i in wanted if not after[i]['present'] or (i>1 and after[i]['ammo']<=0)]
    return {'inventory':after,'before':before,'requested':[WEAPONS[i][0] for i in wanted],
            'missing':[WEAPONS[i][0] for i in missing],'verified':not missing,'install':install,
            'note':'All 11 ordinary carried weapons; original equipped weapon is retained. Remote-bomb detonators and mission objects require their native game flows.',
            'native_function':hex(GIVE_WEAPON)}


class ItemsIn(BaseModel):
    session_id:str
    op:str=Field(default='list',pattern='^(list|give|all_weapons)$')
    weapon:str|int=''
    ammo:int=Field(default=9999,ge=1,le=99999)


class ItemsOut(BaseModel):
    result:dict


@tool('gta3_items','1.0',ItemsIn,ItemsOut,capabilities=['runtime','memory'],permissions=[Permission.READ],timeout_s=40,retries=0)
def gta3_items(inp,ctx):
    """GTA III PS2 SLUS-20062 native weapon inventory: list, give weapon=<name/id> ammo=N,
    all_weapons (11 carried weapons). Uses the verified EE call dispatcher and native
    GiveWeapon with exact executable hashes and inventory read-back. Does not invent a
    universal mission-item inventory; detonators require the remote-bomb game flow.
    Mutations require memory_write. An unknown timeout is never retried.
    """
    from .tools import SESSIONS
    if inp.op!='list' and Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
        raise PermissionError('memory_write permission is required')
    ad,game=SESSIONS[inp.session_id]
    with _guard:lock=_locks.setdefault(inp.session_id,threading.Lock())
    if not lock.acquire(blocking=False):raise RuntimeError('Another GTA III inventory operation is running; no action was queued')
    try:return {'result':execute(ad,game,inp.op,inp.weapon,inp.ammo)}
    finally:lock.release()
