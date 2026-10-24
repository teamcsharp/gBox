"""Read-only native local-player evidence for BLUS30491 01.01.

FUN001AD7B4/001AE010 index sPlayer+28/+2C with actor byte+2F14.
FUN009C08A4/009C08C4 set GameSys+1F0/+200 per-player controller
type/index. Actor presence alone does not prove a controllable split-screen
teammate: camera and displayed prompt ownership must also be scoped.
"""
import math
import struct

PLAYER_MANAGER_VT = 0x0157C148
PLAYER_INDEX = 0x2F14


def participants(memory, snap=None):
    from . import re5_ps3 as R
    result=[]
    try:
        manager=R.u32(memory,R.S_PLAYER)
        if not R.ptr_ok(manager) or R.u32(memory,manager)!=PLAYER_MANAGER_VT:return []
        if not 0<R.u32(memory,manager+0x38)<=4:return []
        pointers=struct.unpack('>2I',memory.rd(manager+0x28,8))
        if pointers[0] and pointers[0]==pointers[1]:return []
        for index,actor in enumerate(pointers):
            if not R.ptr_ok(actor) or memory.rd(actor+PLAYER_INDEX,1)!=bytes([index]):continue
            pos=struct.unpack('>3f',memory.rd(actor+R.P_POS,12))
            hp,maximum=struct.unpack('>hh',memory.rd(actor+R.P_HP,4))
            if not all(math.isfinite(v) and abs(v)<1e7 for v in pos) or not 0<maximum<=30000 or not 0<=hp<=maximum:continue
            if R.u32(memory,manager+0x28+4*index)!=actor \
                    or memory.rd(actor+PLAYER_INDEX,1)!=bytes([index]):continue
            result.append({'id':f'p{index+1}','slot':index+1,'control':'unknown','actor':actor,
                'ptr':actor,'pos':pos,'hp':hp,'hp_max':maximum,'native_actor_verified':True,
                'provenance':{'kind':'native_ram','read_only':True,'native_actor_verified':True,'title':'BLUS30491',
                    'manager':manager,'slot_address':manager+0x28+4*index,
                    'actor_index_address':actor+PLAYER_INDEX,'actor_index':index,
                    'native_functions':['001AD7B4','001AE010']}})
        if R.u32(memory,R.S_PLAYER)!=manager or memory.rd(manager+0x28,8)!=struct.pack('>2I',*pointers):return []
    except (OSError,ValueError,struct.error,AttributeError,TypeError):return []
    return result


def readiness(memory):
    players=participants(memory)
    second=next((p for p in players if p['slot']==2),None)
    adapter=getattr(memory,'adapter',None)
    try:status=getattr(adapter,'teammate_pad_status',lambda:{})()
    except (OSError,ValueError,RuntimeError):status={}
    return {'p2_verified':False,'p2_actor_verified':second is not None,
        'controller2_verified':False,'controller2_prepared':bool(status.get('verified')),
        'human_observer_verified':any(p['slot']==1 for p in players),
        'camera2_verified':False,'prompt2_verified':False,'active_players':players,
        'reason':('Native Player2 actor is absent; join local split-screen using a prepared second controller'
                  if second is None else 'Native Player2 actor verified; its camera, displayed prompts and live controller2 response remain unverified')}


def for_player(memory, player=2, stats=None):
    """Fail closed until the complete P2 reader/control contract is verified."""
    if stats is not None:
        stats['teammate_runtime_reason']=readiness(memory)['reason']
    return None
