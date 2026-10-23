"""Equip an existing recovery item from any carried grid using ordinary pad input.

BLUS30491 01.01: Ghidra a01038/state3, a015f8, 9fddc0 and 9fda94;
uPlayer+2794 owns the inventory controller. No memory writes or item creation.
Capcom PS3 manual p20: Triangle opens inventory; L1 equips the highlighted item
and closes inventory. Existing Bot healing confirms Square consumption and HP.
https://static.capcom.com/manuals/re5/RE5_PS3_DMNL_EN.pdf
"""
import math
import struct

PLAYER_ROOT, PLAYER_INVENTORY_UI = 0x017FEB34, 0x2794
HEAL_IDS = frozenset({0x304,0x305,0x307,0x309})
QUICK_GRIDS = frozenset({1,3,5,7})
SIGNATURES = {
    0x009FDA94:bytes.fromhex('fbc1fff0880300683960000183c28a10'),
    0x009FDDC0:bytes.fromhex('f821ff717c0802a6388422e0fbe10088'),
    0x009FE4C4:bytes.fromhex('f821fea17c0802a6fbc1015083c28a10'),
    0x00A01038:bytes.fromhex('f821ff117c0802a6fbc100e083c28a10'),
}
GRID_TABLE=0x013AA240
GRID_NEIGHBORS=((-1,3,-1,1),(-1,4,0,2),(-1,5,1,-1),(0,6,-1,4),(1,7,3,5),
                (2,8,4,-1),(3,-1,-1,7),(4,-1,6,8),(5,-1,7,-1))


def _pointer(value):
    return type(value) is int and 0x30000000<=value<0x40000000


def read_state(memory, player):
    """Read exact-build native menu state and owner; unknown layouts disable input."""
    try:
        if not _pointer(player) or any(memory.rd(address,len(data))!=data for address,data in SIGNATURES.items()):
            return None
        grid=struct.unpack('>36i',memory.rd(GRID_TABLE,144))
        if grid!=tuple(n for row in GRID_NEIGHBORS for n in row):
            return None
        manager=struct.unpack('>I',memory.rd(PLAYER_ROOT,4))[0]
        if not _pointer(manager) or struct.unpack('>I',memory.rd(manager+0x28,4))[0]!=player:
            return None
        pointer=struct.unpack('>I',memory.rd(player+PLAYER_INVENTORY_UI,4))[0]
        if not _pointer(pointer):
            return None
        raw=memory.rd(pointer,0x80)
        cursor,owner=struct.unpack_from('>I',raw,8)[0],struct.unpack_from('>I',raw,0x10)[0]
        fade,delay=struct.unpack_from('>2f',raw,0x50)
        if len(raw)!=0x80 or not 0<=cursor<9 or owner not in (0,1) or raw[0x68] not in (0,1) \
                or not all(math.isfinite(v) for v in (fade,delay)):
            return None
        if struct.unpack('>I',memory.rd(manager+0x28,4))[0]!=player \
                or struct.unpack('>I',memory.rd(PLAYER_ROOT,4))[0]!=manager:
            return None
        return {'pointer':pointer,'player':player,'state':raw[4],'cursor':cursor,'owner':owner,
                'open':raw[0x68]==1,'fade':fade,'input_delay':delay,'context_open':bool(raw[0x7c])}
    except (AttributeError,ValueError,TypeError,IndexError,OSError,struct.error):
        return None


class Controller:
    """One bounded, acknowledged menu sequence; it equips but never uses an item."""
    def __init__(self, stats=None, reader=read_state, *, allowed_ids=None, prefix='inventory_heal'):
        self.stats=stats if stats is not None else {}
        self.reader=reader
        self.allowed_ids=HEAL_IDS if allowed_ids is None else frozenset(allowed_ids)
        self.prefix=prefix
        self.pending=None
        self.retry_at=-math.inf

    @property
    def active(self):
        return self.pending is not None

    def reset(self):
        self.pending=None

    def _finish(self, status, now, ui=None):
        pending,self.pending=self.pending,None
        self.retry_at=now+2.
        self.stats[self.prefix+'_status']=status
        if pending and pending['opened'] and ui and ui['open']:
            return {'tap':'triangle'}
        return None

    def tick(self, memory, snap, item, now):
        """Return pad action/None. After success, ordinary Bot._heal sees the item in hand."""
        player=snap.get('player') or {}
        if not math.isfinite(now) or player.get('hp',0)<=1 or snap.get('recovery_active') or snap.get('prompt'):
            self.reset()
            return None
        ui=self.reader(memory,player.get('ptr'))
        if ui is None:
            return self._finish('inventory layout/ownership unverified',now)
        state=self.pending
        if state is None:
            if now<self.retry_at or not isinstance(item,dict) or item.get('id') not in self.allowed_ids \
                    or item.get('rounds',0)<=0 or type(item.get('grid')) is not int \
                    or not 0<=item['grid']<9 or item['grid'] in QUICK_GRIDS or item.get('hand'):
                return None
            if ui['open'] or ui['state'] not in (0,1,2):
                self.stats[self.prefix+'_status']='existing menu belongs to another input sequence'
                return None
            state=self.pending={'player':player['ptr'],'pointer':ui['pointer'],'slot':item.get('slot'),
                'id':item['id'],'grid':item['grid'],'started':now,'last':-math.inf,'opened':False,
                'opens':0,'equips':0,'moves':0,'waiting_cursor':None,
                # Native grid selection can equip either existing identical storage
                # record. Only siblings observed before opening are equivalent.
                'equivalent_slots':frozenset(row['slot'] for row in snap.get('inventory',())
                    if type(row.get('slot')) is int and 0<=row['slot']<24
                    and row.get('id')==item['id'] and row.get('grid')==item['grid']
                    and row.get('rounds',0)>0)}
        if state['player']!=player.get('ptr') or state['pointer']!=ui['pointer']:
            return self._finish('inventory player/controller changed',now)
        if ui['open'] and state['opens']:
            state['opened']=True
        target=next((row for row in snap.get('inventory',()) if row.get('slot')==state['slot']
                     and row.get('id')==state['id'] and row.get('grid')==state['grid']
                     and row.get('rounds',0)>0),None)
        if target is None:
            return self._finish('recovery item moved or became unavailable',now,ui)
        held=next((row for row in snap.get('inventory',())
                   if row.get('slot') in state['equivalent_slots']
                   and row.get('id')==state['id'] and row.get('grid')==state['grid']
                   and row.get('rounds',0)>0 and row.get('hand')),None)
        if state['equips'] and held is not None and not ui['open']:
            self.stats[self.prefix+'_equips_confirmed']=self.stats.get(self.prefix+'_equips_confirmed',0)+1
            self.stats[self.prefix+'_equipped_slot']=held['slot']
            return self._finish('recovery item confirmed in hand; ordinary use may resume',now)
        if now-state['started']>=4. or state['moves']>=8:
            return self._finish('bounded inventory equip timed out',now,ui)
        if player.get('action')==2 or now-state['last']<.18:
            return {'hold':set()}
        if not ui['open']:
            if state['opened'] or state['equips']:
                return {'hold':set()}  # wait for in-hand acknowledgement; never reopen after L1
            if ui['state']==2 and state['opens']<2 and now-state['last']>=.75:
                state['last'],state['opens']=now,state['opens']+1
                self.stats[self.prefix+'_status']='opening ordinary inventory'
                return {'tap':'triangle'}
            return {'hold':set()}
        if state['opens']==0:
            return self._finish('unowned inventory opening',now)
        state['opened']=True
        if ui['state']!=3 or ui['owner']!=0 or ui['context_open']:
            return self._finish('inventory not in owned normal cursor state',now,ui)
        if ui['fade']<=0 or ui['input_delay']>0:
            return {'hold':set()}
        cursor=ui['cursor']
        if state['waiting_cursor'] is not None:
            if cursor==state['waiting_cursor']:
                if now-state['last']<.75:
                    return {'hold':set()}
                return self._finish('inventory cursor did not acknowledge input',now,ui)
            state['waiting_cursor']=None
        if cursor!=state['grid']:
            row,col=divmod(cursor,3);want_row,want_col=divmod(state['grid'],3)
            key='dup' if row>want_row else 'ddown' if row<want_row else 'dleft' if col>want_col else 'dright'
            state['last'],state['waiting_cursor']=now,cursor
            state['moves']+=1
            self.stats[self.prefix+'_status']='moving observed inventory cursor'
            return {'tap':key}
        if state['equips']>=2:
            return {'hold':set()}
        state['last'],state['equips']=now,state['equips']+1
        self.stats[self.prefix+'_status']='L1 equip; waiting for selected item in hand'
        return {'tap':'l1'}
