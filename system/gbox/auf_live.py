"""Owned GW7E69 revision 1 native live controls; no addresses shared with other 007 games.

Evidence: Bond.elf SHA256 1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f.
The dispatcher changes a data vtable slot, never rewrites a warm native function.
"""
from __future__ import annotations

import hashlib
import math
import re
import struct
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager

from pydantic import BaseModel, Field, StrictBool

from .models import Permission
from .registry import Unsupported, tool

GAME_ID = '65b7187589166b26'
GAME_IDS = frozenset((GAME_ID,'a8a1484cf7ac7ce1'))
ELF_SHA256 = '1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f'
VT, HOOK, ORIGINAL = 0x80254E70, 0x80254FC4, 0x800DE1A4
CAVE, HEADER, QUEUE, BUFFER, END = 0x80004000, 0x800043F0, 0x80004400, 0x80004500, 0x80004800
LEVEL_MS = 0x803EFD74
RESOURCE_TABLE = 0x804E3CE0
NATIVE_PAUSED = 0x804E34DC
NATIVE_MENU_OFFSET = 0x40A
F_GIVE, F_END = 0x8011B39C, 0x800E6400
F_GIVE_GADGET = 0x8011B1F4
F_COMPLETE_SUBMAP, GI_COMPLETE_SUBMAP = 0x8001A314, 0x803F0154
UI_FLOW_PENDING, UI_COMPLETED_SUBMAPS, IS_END_OF_MISSION = 0x804E35A0, 0x804E35B0, 0x804E3244
FINGERPRINTS = (
    (0x800DC450,336,'84292490e958d566f6b6378fff28fcfdd00874f6a60db5ded368ea17588c235b'),
    (0x8014B524,108,'f0e2bfe9f79e6007c314a53c0d3384e59f13658574ba81613ec93929379c04a8'),
    (ORIGINAL,172,'73d0e8a16ea7fb585586127d6637a71958db5bf2c2bbfe38be2c0108706e9e7a'),
    (F_GIVE,1120,'fdb5d0270dd8908b9659655eef1c2939c410c850e11e0c453bcb13961c2f6cb9'),
    (F_GIVE_GADGET,424,'9a28e6217812f8c8edcb1f96970db8eab1f873d102ea8fec5f12befbc61627df'),
    (0x80118610,196,'10425afbe73554d1247d4ede22c670d258147ae2cf7549496342817210331836'),
    (0x80099F10,8,'5ee15fb44bf4254a4071428049f6816299cb2e8b6bb620a5ed6fda1a82ae3c4d'),
    (0x800B1B48,936,'aa5d82508db1ec2af069c216309c34d8a927d42215c6c3c498d4e453a25d9a45'),
    (0x800DD950,96,'70120cf88f15c91536d368bada54a4954c9d88f03962372afce54d5193ae961f'),
    (0x800DD9B0,76,'706a0860be406e67d38db05191e9a501cd3d9b88e4d6852db2ca05485db4daa4'),
    (F_END,484,'0132033afd23f4f93f175a3a1a188472387ce52c94919f2c61d30a4c1060e90e'),
    (0x801AEE38,148,'403e3fb7e0cea70d4a3d3fb600ec8389ce3e8cdb60720dd107b3e91a40b915c5'),
    (0x801AEF64,248,'65e5dd6fb679061df856b7e1a9ea412d68b8afc42cc685ac237a80bbacb9db42'),
    (0x8014BEC8,3240,'84088123450a04fe7d11effc946e388bcef7f652cc0e089bb2f23cf9564ecb35'),
    (0x80147960,296,'45cb94b05742afbe0e9edfe97020022faea5e955fc05c50191287ed26bd497d2'),
    (0x80147794,368,'3f0f0f9b93f27536f1496373e9540d5421ce4b728e198dd5ea1ec8275a0c5ffd'),
    (0x8000AED4,180,'958fad0b479d8cb20dd5ada634c5a8e58bb39efdee44decdf7e02769a72d7287'),
    (0x8000ADAC,296,'c47746e4ae7122ae5c8ea3ca88845ccf0a8e716dd00433fc487d837660e93bbc'),
    (0x800D3FB0,24,'cf9bc2f8ebcea8a54a8097d4b699e81e68f8844d3e11f23001c7ff1a96a7ba05'),
    (0x800D3F60,80,'d89772dd633e6d9a2045795d8db39bd646dc7a3d04a8799762f9d49728976ec3'),
    (F_COMPLETE_SUBMAP,260,'89a761867c4228609f2beba5abcd08ce6215bd47c4f975cc50af93231f7b6011'),
    (0x8012DE50,284,'bdb3aefa9d43a5182ccc352116b8481f1bfbb8c60a8352ba969dac74892da657'),
)
ITEMS = {
    'p2k':'P2K pistol (silenced)', 'p2kns':'P2K pistol', 'goldengun':'Golden Gun',
    'defender':'Defender pistol','viper':'Viper pistol','ka57':'KA-57', 'ks7':'KS7',
    'fsu4':'FSU-4','d17':'D17','ugw':'UGW','ingalls':'Ingalls','ps100':'PS100',
    'calypso':'Calypso','frinesi':'Frinesi shotgun','ssr4000':'SSR 4000 sniper rifle',
    'mrl22':'MRL-22 rocket launcher','rpg':'Rocket launcher','grenadelauncher':'Grenade launcher',
    'fraggrenade':'Frag grenade','goldengrenade':'Golden grenade','fist':'Fists',
    'qclaw':'Q-Claw grappling hook','qlaser':'Q-Laser','qdecryptor':'Q-Decryptor',
    'qremote':'Q-Remote','qcamera':'Q-Camera','qjet':'Q-Jet',
    'qspecs':'Q-Specs (X-ray glasses)','keycard':'Keycard','keycard2':'Keycard 2',
    'pcodegen':'Access code generator','dartgun':'Dart gun',
}
GADGET_MODELS = {
    'qlaser':'gadget_qlaser.men','qdecryptor':'gadget_qdecryptor.men',
    'qremote':'gadget_qremote.men','qcamera':'gadget_qcamera.men','qjet':'gadget_qjet.men',
    'qspecs':'xrayglasses_large.men','keycard':'gadget_keycard.men','keycard2':'gadget_keycard2.men',
    'pcodegen':'gadget_pcodegen.men',
}
ITEM_MODELS = {key:GADGET_MODELS.get(key,key+'_pickup.men') for key in ITEMS}
ITEM_NAMES = {key:{'pcodegen':'pcodegen','fist':'fist'}.get(key,model[:-4]) for key,model in ITEM_MODELS.items()}
OPS = frozenset(('inspect','noclip','give_item','finish_level','next_checkpoint','infinite_ammo','rocket_pistol'))
_locks, _receipts, _guard = {}, {}, threading.Lock()


def d(op, rt, ra, imm):
    return op << 26 | rt << 21 | ra << 16 | (imm & 0xFFFF)


def dispatcher():
    """Preserve EABI state and tail-chain the native input preprocessor exactly once.

    A single command is bound to this player and an in-game millisecond deadline.
    fn is cleared BEFORE entry, so failures/timeouts cannot execute twice.
    """
    words, labels, fixups = [], {}, []
    def emit(*v): words.extend(v)
    def branch(word,label): fixups.append((len(words),label)); emit(word)
    # +8..+0x28 belongs to the EABI outgoing argument home area. Native
    # callees may spill their incoming registers there, so backups begin at +0x30.
    emit(d(37,1,1,-0x140),0x7C0802A6,d(36,0,1,0x144),d(47,3,1,0x30),0x7C000026,d(36,0,1,0xA8))
    for r in range(1,14): emit(d(54,r,1,0xB0+(r-1)*8))
    emit(d(15,30,0,QUEUE>>16),d(24,30,30,QUEUE&0xFFFF),d(32,12,30,0),d(11,0,12,0));branch(0x41820000,'done')
    emit(d(32,0,30,44),0x7C001840);branch(0x40820000,'done')  # cmpw r0,r3: pinned this
    emit(d(15,11,0,(RESOURCE_TABLE+0x8000)>>16),d(32,11,11,RESOURCE_TABLE&0xFFFF),d(32,0,30,56),0x7C0B0040)
    branch(0x40820000,'expired')
    emit(d(15,11,0,(LEVEL_MS+0x8000)>>16),d(32,11,11,LEVEL_MS&0xFFFF),d(32,0,30,60),0x7C0B0040)
    branch(0x41800000,'expired')  # a restarted/rewound level cannot consume this command
    emit(d(32,0,30,48),0x7C0B0040)
    branch(0x41810000,'expired')  # cmplw r11,r0; bgt
    emit(d(14,0,0,0),d(36,0,30,0),d(14,0,0,1),d(36,0,30,40))
    for r in range(3,11): emit(d(32,r,30,4+(r-3)*4))
    emit(0x7D8903A6,0x4E800421,d(36,3,30,36),d(14,0,0,2),d(36,0,30,40));branch(0x48000000,'done')
    labels['expired']=len(words)
    emit(d(14,0,0,0),d(36,0,30,0),d(14,0,0,3),d(36,0,30,40))
    labels['done']=len(words)
    for r in range(1,14): emit(d(50,r,1,0xB0+(r-1)*8))
    emit(d(32,0,1,0xA8),0x7C0FF120,d(46,3,1,0x30),d(32,0,1,0x144),0x7C0803A6,d(14,1,1,0x140),
         d(15,12,0,ORIGINAL>>16),d(24,12,12,ORIGINAL&0xFFFF),0x7D8903A6,0x4E800420)
    for index,label in fixups:
        mask=0x3FFFFFC if words[index]>>26==18 else 0xFFFC
        words[index]|=((labels[label]-index)*4)&mask
    blob=struct.pack('>'+str(len(words))+'I',*words)
    assert len(blob)<HEADER-CAVE
    return blob


CODE=dispatcher()
METADATA=b'GBAUF001'+struct.pack('>II',ORIGINAL,HOOK)


class Native:
    def __init__(self,ad):
        self.ad,self.read,self._write=ad,ad.read_memory,ad.write_memory
        self.expires=None
        self.owned=ad.__dict__.setdefault('_auf_live_owned',{})

    def write(self,address,data):
        if self.expires is not None:deadline(self.expires)
        return self._write(address,data)

    def ptr(self,address,size=4,alignment=4):
        if address%alignment or size<0 or not 0x80000000<=address<=0x81800000-size:
            raise Unsupported('The Agent Under Fire pointer is outside MEM1')
        return address

    def u32(self,address):return struct.unpack('>I',self.read(address,4))[0]

    def text(self,address,limit=160):
        self.ptr(address,limit,1)
        raw=self.read(address,limit)
        if b'\0' not in raw:raise Unsupported('Native string is not terminated')
        return raw.split(b'\0',1)[0].decode('ascii','strict')

    def check(self):
        if self.read(0x80000000,8)!=b'GW7E69\0\1':
            raise Unsupported('These native controls require Agent Under Fire GameCube GW7E69 revision 1')
        for address,size,digest in FINGERPRINTS:
            if hashlib.sha256(self.read(address,size)).hexdigest()!=digest:
                raise Unsupported(f'Agent Under Fire executable differs at {address:#x}; no action was applied')
        if self.u32(0x804E3068)!=1 or self.u32(0x804E34CC)!=0:
            raise Unsupported('Use the local single-player campaign; multiplayer and attract modes are excluded')
        if self.u32(0x804E34C8):raise Unsupported('Wait for playable campaign gameplay; the attract demonstration is excluded')
        game_type=self.ptr(self.u32(0x804E38E4),0x24)
        if self.u32(game_type+0x20)!=0:raise Unsupported('Agent Under Fire controls require single-player campaign mode')
        table=self.ptr(self.u32(0x804E38B0),0x2B0)
        p=self.ptr(self.u32(table+0x24C),0x840)
        client=self.ptr(self.u32(0x804E3530),0x860)
        if (self.u32(table+0x1E4)!=1 or self.u32(p+4)!=VT or self.u32(p+0x14)!=table
                or self.u32(p+0x18)!=client or self.u32(table+0x1E0)!=client or self.u32(p+0x10)!=0):
            raise Unsupported('Enter a playable campaign level before applying Agent Under Fire controls')
        health=struct.unpack('>f',self.read(p+0x180,4))[0]
        if not math.isfinite(health) or not 0<health<100000 or self.u32(client+0xC)&0x100 or self.u32(p+0x2A4):
            raise Unsupported('Wait for living, on-foot campaign gameplay outside a cinematic')
        self.player,self.table,self.client=p,table,client
        resources=self.ptr(self.u32(RESOURCE_TABLE),0x50)
        identity=(table,p,client,resources,hashlib.sha256(self.read(resources,0x50)).digest())
        level_ms=self.u32(LEVEL_MS)
        if self.owned.get('identity')!=identity or level_ms<self.owned.get('level_ms',0):
            epoch=self.owned.get('epoch',0)+1
            self.owned.clear();self.owned.update(identity=identity,epoch=epoch)
        self.owned['level_ms']=level_ms
        return p

    def native_call_reason(self):
        if self.u32(NATIVE_PAUSED) or self.read(self.player+NATIVE_MENU_OFFSET,1)!=b'\0':
            return "Close the game's pause/options menu before using native item or level commands"
        if self.u32(UI_FLOW_PENDING):
            return "Wait for the game's current results or level transition to finish"
        return None

    def require_native_call(self):
        reason=self.native_call_reason()
        if reason:raise Unsupported(reason)

    def finish_start_reason(self):
        if self.u32(GI_COMPLETE_SUBMAP)!=F_COMPLETE_SUBMAP:
            return 'The level-exit callback differs from the verified game revision; no level command was applied'
        if self.owned.get('finish_attempt')==(self.owned['identity'],self.owned['epoch']):
            return 'A level exit has already started in this mission; wait for a new section or restart the mission before requesting another exit'
        return None

    @contextmanager
    def paused(self):
        state=(self.ad.query_runtime() or {}).get('state')
        if state not in ('PLAYING','PAUSED'):raise Unsupported('The emulator pause state is unavailable')
        owned=state!='PAUSED'
        if owned:self.ad.pause()
        try:
            if (self.ad.query_runtime() or {}).get('state')!='PAUSED':raise RuntimeError('The emulator did not pause; no action was applied')
            yield
        finally:
            if owned:self.ad.resume()

    def changes(self,changes):
        """Paused compare-before-write transaction, with checked rollback of our writes."""
        undo=[]
        try:
            for address,old,new in changes:
                if self.read(address,len(old))!=old:raise RuntimeError('The native value changed; no retry was attempted')
                undo.append((address,old,new));self.write(address,new)
                if self.read(address,len(new))!=new:raise RuntimeError('Native write read-back failed')
        except Exception:
            for address,old,new in reversed(undo):
                if self.read(address,len(new))==new:self._write(address,old)
            raise

    def resources(self):
        table=self.ptr(self.u32(RESOURCE_TABLE),16);count=self.u32(table)
        if not 1<=count<=16384:raise Unsupported('The level resource table is not initialized')
        data=self.read(self.ptr(table+16,count*16),count*16)
        records=[struct.unpack_from('>4I',data,i*16) for i in range(count)]
        names=[self.ptr(row[0],1,1) for row in records]
        lo,hi=min(names),max(names)+160
        if hi-lo>2*1024*1024:raise Unsupported('Native resource names exceed the bounded table layout')
        strings=self.read(self.ptr(lo,hi-lo,1),hi-lo);out={}
        for row in records:
            off=row[0]-lo;raw=strings[off:off+160]
            if b'\0' not in raw:raise Unsupported('The native resource name is not terminated')
            name=raw.split(b'\0',1)[0].decode('ascii','strict').lower()
            self.ptr(row[1],row[2],1)
            out[name]=row
        return out

    def inventory(self):
        """Read native Item names from the checked Sentient entity-ID container."""
        count=self.u32(self.player+0x2C0)
        if count>256:raise Unsupported('The native inventory exceeds the reviewed bounded layout')
        if not count:return {}
        raw=self.read(self.ptr(self.u32(self.player+0x2BC),count*4),count*4)
        result={}
        for entity_id in struct.unpack('>'+str(count)+'I',raw):
            if not 1<=entity_id<4096:raise Unsupported('The native inventory entity number is invalid')
            entity=self.ptr(self.table+entity_id*0x2B0,0x2B0)
            item=self.ptr(self.u32(entity+0x24C),0x2E0)
            if (self.u32(entity+0x1E4)!=1 or self.u32(item+0x10)!=entity_id
                    or self.u32(item+0x14)!=entity or self.u32(item+0x278)!=self.player):
                raise Unsupported('The native inventory ownership changed; refresh before applying an item')
            name_data=self.ptr(self.u32(item+0x2D8),16)
            name=self.text(self.u32(name_data)).lower()
            result.setdefault(name,[]).append(item)
        return result

    def items(self,resources=None):
        resources=self.resources() if resources is None else resources
        rows=[{'id':key,'name':name,'model':ITEM_MODELS[key]} for key,name in ITEMS.items()
              if 'models/'+ITEM_MODELS[key] in resources]
        try:inventory=self.inventory()
        except (Unsupported,UnicodeError,ValueError,struct.error):return rows
        equipped=self.equipped_items()
        for row in rows:
            owned=inventory.get(ITEM_NAMES[row['id']],[])
            row.update(owned=bool(owned),equipped=bool(equipped.intersection(owned)))
        return rows

    def equipped_items(self):
        # StartExtraGadget/StopExtraGadget use a separate simultaneous gadget slot.
        return {self.u32(self.player+0x29C),self.u32(self.player+0x7A4)}-{0}

    def weapon(self):
        w=self.u32(self.player+0x29C)
        if not w:return None
        w=self.ptr(w,0x500)
        if self.u32(w+0x278)!=self.player:return None
        model_data=self.ptr(self.u32(w+0x28),16)
        model=self.text(self.u32(model_data)).lower()
        if 'p2k' not in model:return None
        if self.u32(w+0x394) not in (1,2):return None
        return w

    def inspect(self):
        p=self.check();resources=self.resources();weapon=self.weapon();rocket=self.owned.get('rocket_pistol')
        active=bool(rocket and weapon==rocket['weapon'] and all(self.read(a,len(new))==new for a,old,new in rocket['changes']))
        if weapon and self.u32(weapon+0x394)==2 and self.u32(weapon+0x3F0)==BUFFER+0xE0 and not active:
            raise Unsupported('A restored rocket-pistol patch has no checked original mapping in this worker; reload an unmodified checkpoint before toggling it')
        ammo=self.ptr(self.u32(0x804E390C),0x24)
        mode=self.u32(p+0xA4);ammo_value=self.u32(ammo+0x20)
        if mode not in (1,5) or ammo_value not in (0,1):raise Unsupported('Native movement/ammo state is not supported')
        call_reason=self.native_call_reason()
        finish_reason=call_reason or self.finish_start_reason()
        item_rows=self.items(resources)
        give_reason=call_reason
        if not give_reason and any(type(row.get('owned')) is not bool for row in item_rows):
            give_reason='Inventory could not be verified; wait for playable gameplay and reload the controls'
        return {'verified':True,'switches':{'noclip':mode==1,'infinite_ammo':bool(ammo_value),'rocket_pistol':active},
                'items':item_rows,'available':{'noclip':True,'infinite_ammo':True,'give_item':give_reason is None,
                'finish_level':finish_reason is None,'next_checkpoint':False,'rocket_pistol':bool(weapon and 'models/mrl22_projectile.men' in resources)},
                'unavailable_reasons':{'next_checkpoint':'The native timed checkpoint triggers are not an ordered mission/save checkpoint route; no safe next checkpoint has been verified.',
                    **({op:call_reason for op in ('give_item','finish_level')} if call_reason else {}),
                    **({'give_item':give_reason} if give_reason else {}),
                    **({'finish_level':finish_reason} if finish_reason else {}),
                    **({} if weapon else {'rocket_pistol':'Equip the P2K pistol in a level containing the native MRL-22 projectile first.'})},
                'player':hex(p),'revision':'GW7E69 disc 0 revision 1','scope':'Offline on-foot campaign only; driving and multiplayer use different native systems.'}

    def toggle(self,key,on):
        if type(on) is not bool:raise ValueError('Switch state must be a boolean')
        p=self.player
        if key=='noclip':address=p+0xA4;off,on_value=5,1
        else:address=self.ptr(self.u32(0x804E390C),0x24)+0x20;off,on_value=0,1
        old=self.read(address,4);value=struct.unpack('>I',old)[0]
        if value not in (off,on_value):raise Unsupported('The native switch has an unexpected state')
        previous=self.owned.get(key)
        if on:
            new=struct.pack('>I',on_value)
            if not previous:self.owned[key]=(address,old,new)
        else:
            if previous and previous[0]==address:
                if old!=previous[2]:raise RuntimeError('This switch changed outside gBox; its original value was not overwritten')
                new=previous[1]
            else:new=struct.pack('>I',off)
        self.changes([(address,old,new)])
        if not on:self.owned.pop(key,None)
        return {'verified':True,'switch':key,'on':struct.unpack('>I',new)[0]==on_value}

    def install(self):
        slot=self.u32(HOOK);head=self.read(HEADER,16)
        if slot==CAVE:
            if head!=METADATA or self.read(CAVE,len(CODE))!=CODE:raise Unsupported('An unknown Agent Under Fire dispatcher owns the hook')
            return
        if slot!=ORIGINAL:raise Unsupported('The Agent Under Fire input slot is modified by another tool')
        if any(self.read(CAVE,END-CAVE)):raise Unsupported('The bounded Agent Under Fire scratch region is occupied')
        self.changes([(CAVE,bytes(len(CODE)),CODE),(HEADER,bytes(16),METADATA),
                      (HOOK,struct.pack('>I',ORIGINAL),struct.pack('>I',CAVE))])

    def call(self,fn,args,expires,prepared=None):
        self.expires=expires
        if (self.ad.query_runtime() or {}).get('state')!='PLAYING':
            raise Unsupported('Resume the emulator before submitting a native item or level command')
        with self.paused():
            p=self.check();self.require_native_call();deadline(expires)
            if fn not in (F_GIVE,F_GIVE_GADGET,F_END,F_COMPLETE_SUBMAP) or not args or args[0]!=p:
                raise Unsupported('The prepared player changed before submission; no command was published')
            if fn==F_END:
                reason=self.finish_start_reason()
                if reason:raise Unsupported(reason)
            if fn==F_COMPLETE_SUBMAP and (self.u32(GI_COMPLETE_SUBMAP)!=fn or self.u32(IS_END_OF_MISSION)!=1):
                raise Unsupported('The prepared level exit changed before transition; no transition command was published')
            if prepared:
                identity,epoch,buffer=prepared
                if self.owned['identity']!=identity or self.owned['epoch']!=epoch or self.read(BUFFER,len(buffer))!=buffer:
                    raise Unsupported('The prepared mission or arguments changed before submission; no command was published')
            self.idle_queue();deadline(expires)
            level_ms=self.u32(LEVEL_MS)
            remaining=max(1,min(3000,int((expires-time.time())*1000)))
            if level_ms>0xFFFFFFFF-remaining:raise Unsupported('The native level timer is wrapping; retry after it settles')
            nonce=(self.u32(QUEUE+52)+1)&0xFFFFFFFF
            packet=struct.pack('>16I',0,*[int(x)&0xFFFFFFFF for x in args],*([0]*(8-len(args))),0,0,p,level_ms+remaining,nonce,self.u32(RESOURCE_TABLE),level_ms)
            self.write(QUEUE,packet)
            deadline(expires)
            if fn==F_END:self.owned['finish_attempt']=(self.owned['identity'],self.owned['epoch'])
            self.write(QUEUE,struct.pack('>I',fn))
        until=time.monotonic()+4
        while time.monotonic()<until:
            data=self.read(QUEUE,64);pending=struct.unpack_from('>I',data)[0];status=struct.unpack_from('>I',data,40)[0]
            if data[4:36]!=packet[4:36] or data[44:64]!=packet[44:64] or pending not in (0,fn) or status not in (0,1,2,3):
                raise RuntimeError('The native command mailbox changed unexpectedly; outcome unknown and no retry was attempted')
            if pending==0 and status==2:return struct.unpack_from('>I',data,36)[0]
            if pending==0 and status==3:raise TimeoutError('The command expired or its mission changed on the native game thread before execution')
            time.sleep(.01)
        # Withdraw only a command that has not started. Never submit it again.
        with self.paused():
            current=self.read(QUEUE,64)
            if current[4:]==packet[4:] and self.u32(QUEUE)==fn:self._write(QUEUE,bytes(4))
        raise RuntimeError('The native command outcome is unknown; no automatic retry was attempted')

    def idle_queue(self):
        self.install()
        if self.u32(QUEUE) or self.u32(QUEUE+40)==1:
            raise RuntimeError('A native command is pending or uncertain; no action was retried')

    def give(self,item,expires):
        self.expires=expires
        if item not in ITEMS:raise ValueError('Choose an item from this game\'s dropdown')
        instructions=('Use D-pad left/right to select gadgets, then B to use them.' if item in GADGET_MODELS or item=='qclaw'
                      else 'Use D-pad up/down to select weapons, then R to fire.')
        if (self.ad.query_runtime() or {}).get('state')!='PLAYING':
            raise Unsupported('Resume the emulator before submitting a native item command')
        with self.paused():
            self.check();self.require_native_call();rows={x['id']:x for x in self.items()}
            if item not in rows:raise Unsupported('This item is not packaged in the loaded mission; no missing assets were synthesized')
            inventory=self.inventory();existing=inventory.get(ITEM_NAMES[item],[])
            if existing:
                deadline(expires);equipped=bool(self.equipped_items().intersection(existing))
                return {'verified':True,'item':item,'name':ITEMS[item],'already_owned':True,'equipped':equipped,
                        'message':ITEMS[item]+(' is already equipped.' if equipped else ' is already in your inventory.')+
                        ' '+instructions+' Giving an item does not auto-equip it.'}
            deadline(expires);self.idle_queue()
            name=rows[item]['model'].encode('ascii')+b'\0';self.write(BUFFER,name)
            prepared=(self.owned['identity'],self.owned['epoch'],name)
        fn=F_GIVE_GADGET if item in GADGET_MODELS else F_GIVE
        args=[self.player,BUFFER,0,0] if fn==F_GIVE_GADGET else [self.player,BUFFER,0,0,0xFFFFFFFF,0xFFFFFFFF,0]
        result=self.call(fn,args,expires,prepared)
        if not 0x80000000<=result<=0x817FFB00:raise RuntimeError('The native item grant returned no item; no retry was attempted')
        with self.paused():
            self.check()
            if self.owned['identity']!=prepared[0] or self.owned['epoch']!=prepared[1]:
                raise RuntimeError('The mission changed after the native grant; outcome unknown and no retry was attempted')
            if self.u32(result+0x278)!=self.player:raise RuntimeError('The native item owner read-back did not match; no retry was attempted')
            if result not in self.inventory().get(ITEM_NAMES[item],[]):
                raise RuntimeError('The native item inventory/name read-back did not match; no retry was attempted')
            equipped=result in self.equipped_items()
        return {'verified':True,'item':item,'name':ITEMS[item],'native_item':hex(result),'native_function':hex(fn),
                'already_owned':False,'equipped':equipped,
                'message':ITEMS[item]+' was restored to your inventory. '+instructions+' Giving an item does not auto-equip it.'}

    def finish(self,expires):
        self.expires=expires
        if (self.ad.query_runtime() or {}).get('state')!='PLAYING':
            raise Unsupported('Resume the emulator before submitting a native level command')
        with self.paused():
            self.check();self.require_native_call()
            reason=self.finish_start_reason()
            if reason:raise Unsupported(reason)
            completed=self.u32(UI_COMPLETED_SUBMAPS)
            deadline(expires);self.idle_queue();self.write(BUFFER,bytes(48))
            prepared=(self.owned['identity'],self.owned['epoch'],bytes(48))
        self.call(F_END,[self.player,BUFFER],expires,prepared)
        # The authored exit finalizes player statistics, then requests the UI's
        # deferred map transition. EndLevel alone never leaves gameplay.
        self.call(F_COMPLETE_SUBMAP,[self.player],expires,prepared)
        if self.u32(UI_COMPLETED_SUBMAPS)!=(completed+1)&0xFFFFFFFF:
            raise RuntimeError('The game did not acknowledge its deferred level exit; no retry was attempted')
        return {'verified':True,'native_functions':[hex(F_END),hex(F_COMPLETE_SUBMAP)],
                'note':'The game queued its normal level-exit results and progression flow.'}

    def rocket(self,on):
        w=self.weapon()
        if not w:raise Unsupported('Equip the P2K pistol before changing its projectile')
        previous=self.owned.get('rocket_pistol')
        if not previous and self.u32(w+0x3F0)==BUFFER+0xE0:
            raise Unsupported('The rocket-pistol patch has no original mapping in this worker; reload an unmodified checkpoint')
        if not on:
            if not previous:return {'verified':True,'switch':'rocket_pistol','on':False}
            if previous['weapon']!=w:raise Unsupported('The equipped pistol changed; the previous object was not overwritten')
            old_sd,old_data,old_text=previous['original_string']
            if self.u32(old_sd)!=old_data or self.text(old_data)!=old_text or not 0<self.u32(old_sd+4)<0x1000000:
                raise Unsupported('The original pistol string allocation changed; no freed pointer was restored')
            self.changes([(a,new,old) for a,old,new in reversed(previous['changes'])]);self.owned.pop('rocket_pistol',None)
            return {'verified':True,'switch':'rocket_pistol','on':False}
        if previous:
            if previous['weapon']!=w or any(self.read(a,len(new))!=new for a,old,new in previous['changes']):
                raise Unsupported('The pistol changed outside gBox; refresh instead of overwriting it')
            return {'verified':True,'switch':'rocket_pistol','on':True}
        if 'models/mrl22_projectile.men' not in self.resources():raise Unsupported('This mission does not package the MRL-22 projectile')
        if self.u32(w+0x3F0)==BUFFER+0xE0:
            raise Unsupported('The rocket-pistol patch has no original mapping in this worker; reload an unmodified checkpoint')
        old_sd=self.ptr(self.u32(w+0x3F0),16);old_data=self.u32(old_sd);old_text=self.text(old_data)
        if not 0<self.u32(old_sd+4)<0x1000000:raise Unsupported('The original pistol projectile string has an invalid reference count')
        self.install()
        # A native strdata with a retained reference count: the engine may decrement
        # this shared string on a weapon change, but must never free scratch memory.
        text=BUFFER+0x100;sd=BUFFER+0xE0;name=b'mrl22_projectile.men\0'
        blob=struct.pack('>4I',text,0x100000,64,len(name)-1)
        for a,b in ((sd,blob),(text,name)):
            current=self.read(a,len(b))
            if any(current) and current!=b:raise Unsupported('The rocket-pistol scratch string is occupied')
            self.write(a,b)
        changes=[(w+0x394,self.read(w+0x394,4),struct.pack('>I',2)),
                 (w+0x3F0,self.read(w+0x3F0,4),struct.pack('>I',sd))]
        self.changes(changes);self.owned['rocket_pistol']={'weapon':w,'changes':changes,'original_string':(old_sd,old_data,old_text)}
        return {'verified':True,'switch':'rocket_pistol','on':True,'note':'P2K primary fire uses the loaded MRL-22 projectile; secondary fire and its native ammunition remain unchanged.'}


def deadline(expires):
    if not math.isfinite(expires) or not time.time()<expires<=time.time()+16:
        raise TimeoutError('The Agent Under Fire command expired; no action was applied')


def reviewed_profile(analysis_artifacts,runtime_artifacts,verified_ops):
    """Build a publication candidate from separately registered real evidence.

    The caller supplies only operations actually demonstrated in a private native
    session. Missing operations remain in the shared discovery checklist, disabled.
    This function does not publish or promote unit tests into runtime evidence.
    """
    verified=set(verified_ops)
    if not verified or verified-set(OPS-{'inspect','next_checkpoint'}):
        raise ValueError('Publish only implemented operations with native runtime evidence')
    if not analysis_artifacts or not runtime_artifacts:raise ValueError('Analysis and native runtime artifacts are both required')
    guards=[{'address':0x804E3068,'hex':'00000001'},
            {'address':0x804E34CC,'hex':'00000000'}, {'address':0x804E34C8,'hex':'00000000'}]
    definitions=(
        ('noclip','movement','Walk through walls','Pass through walls. Turn this off in open space; the previous movement setting is restored.'),
        ('give_item','inventory','Give weapon or gadget','Restores a weapon or gadget available in the current mission and reports items already owned. Use D-pad left/right to select gadgets, then B to use them. Giving an item does not auto-equip it. Mission documents and driving items use separate systems.'),
        ('finish_level','levels','Go to end of level','Starts the game\'s normal results and progression flow. Close the pause/options menu first. This does not complete unfinished objectives.'),
        ('infinite_ammo','ammunition','Unlimited ammo','Enables the game\'s own unlimited ammunition setting. Magazines still reload. Turning it off restores the previous setting.'),
        ('rocket_pistol','projectiles','Rocket launcher pistol','Equip the P2K in a mission containing MRL-22 rockets. Primary fire launches those rockets; turning this off restores the previous projectile. The pistol, secondary fire and ammunition keep their existing behavior.'),
    )
    actions=[]
    for op,category,label,notes in definitions:
        if op not in verified:continue
        action={'id':op,'category':category,'label':label,'scope':'GW7E69 rev1, offline on-foot single-player campaign',
                'notes':notes,'guards':guards,'parameters':[],
                'binding':{'kind':'native','tool':'auf_live','input':{'op':op}}}
        if op in ('noclip','infinite_ammo','rocket_pistol'):
            action.update(control='toggle',toggle_parameter='on',parameters=[{'id':'on','label':'Enabled','kind':'boolean','default':False}])
            action['binding']['input']['on']='$on';action['binding']['state_key']=op
        elif op=='give_item':
            action['parameters']=[{'id':'item','label':'Item','kind':'choice','default':'p2k',
                                   'options':[{'value':key,'label':label} for key,label in ITEMS.items()]}]
            action['binding']['input']['item']='$item'
        actions.append(action)
    return {'executable_sha256':ELF_SHA256,'revision_label':'Agent Under Fire GameCube USA GW7E69 revision 1 (Bond.elf)',
            'guards':[{'address':0x80000000,'hex':'4757374536390001'},
                      {'address':ORIGINAL,'hex':'7c0802a6900100049421ffe893e10014'}],
            'ghidra_artifacts':list(analysis_artifacts),'runtime_artifacts':list(runtime_artifacts),'actions':actions,
            'assessments':{'checkpoints':{'status':'unsupported',
                'scope':'Reviewed on-foot campaign maps in this owned revision',
                'reason':'No ordered native mission checkpoint route was found; timed race checkpoint triggers are a different system.'}}}


class LiveIn(BaseModel):
    session_id:str
    op:str=Field(default='inspect',pattern='^(inspect|noclip|give_item|finish_level|next_checkpoint|infinite_ammo|rocket_pistol)$')
    on:StrictBool=False
    item:str=Field(default='',max_length=40)
    command_id:str=''
    expires:float=0


class LiveOut(BaseModel):
    result:dict


@tool('auf_live','1.0',LiveIn,LiveOut,capabilities=['runtime','memory'],permissions=[Permission.READ],timeout_s=30,retries=0)
def auf_live(inp,ctx):
    """Agent Under Fire GameCube GW7E69 rev1 offline campaign native controls.
    inspect lists native switches and reviewed weapons/gadgets in the loaded level.
    noclip/infinite_ammo/rocket_pistol accept on. give_item accepts listed item id.
    finish_level invokes native EndLevel. next_checkpoint is unavailable until an
    ordered native route is verified. Mutations require memory_write and never retry.
    """
    from .tools import SESSIONS
    if inp.session_id not in SESSIONS:raise Unsupported('This emulation session ended')
    ad,game=SESSIONS[inp.session_id]
    if game.get('platform')!='gamecube' or game.get('game_id') not in GAME_IDS:
        raise Unsupported('These native controls target Agent Under Fire GameCube GW7E69 revision 1 only')
    if inp.op!='inspect' and Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
        raise PermissionError('memory_write permission is required')
    with _guard:lock=_locks.setdefault(inp.session_id,threading.Lock())
    if not lock.acquire(blocking=False):raise RuntimeError('Another Agent Under Fire action is applying; no action was queued')
    try:
        m=Native(ad)
        if inp.op=='inspect':
            with m.paused():return {'result':m.inspect()}
        command=inp.command_id
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',command):raise ValueError('command_id must be a unique 16 to 64 character token')
        expires=inp.expires;deadline(expires)
        m.expires=expires
        signature=(inp.op,inp.on,inp.item)
        with _guard:
            for sid in set(_receipts)-set(SESSIONS):_receipts.pop(sid,None);_locks.pop(sid,None)
            receipts=_receipts.setdefault(inp.session_id,OrderedDict())
            if command in receipts:
                previous=receipts[command]
                if previous['signature']!=signature:raise ValueError('Command ID was reused with different inputs')
                if 'error' in previous:raise RuntimeError(previous['error'])
                return {'result':previous['result']}
            receipt={'signature':signature};receipts[command]=receipt
            while len(receipts)>128:receipts.popitem(last=False)
        try:
            if inp.op=='next_checkpoint':raise Unsupported('No ordered native checkpoint route has been verified for this mission; no teleport was applied')
            if inp.op in ('give_item','finish_level'):
                result=m.give(inp.item,expires) if inp.op=='give_item' else m.finish(expires)
            else:
                with m.paused():
                    m.check();deadline(expires)
                    result=m.rocket(inp.on) if inp.op=='rocket_pistol' else m.toggle(inp.op,inp.on)
            result['command_id']=command;receipt['result']=result
            return {'result':result}
        except Exception as error:receipt['error']=str(error);raise
    finally:lock.release()
