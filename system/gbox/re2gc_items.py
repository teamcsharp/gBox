"""GHAE08 inventory edits staged in an idle native inventory menu.

Data writes are bounded and reversible until the native close request is resumed.
The game itself reloads equipment assets; post-dispatch uncertainty is never retried
or disguised as a successful rollback. See docs/re2gc-inventory.md.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import time
import uuid
from contextlib import contextmanager

from pydantic import BaseModel, Field, StrictInt
from . import re2gc_state as S
from .emulator_freeze import frozen, memory_guard
from .models import Permission
from .registry import tool

CONTROL = 0x1352c
TASK = 0x1076c
TASK_TABLE = 0x10748
CURRENT_TASK = 0x10868
FRAME_COUNTER = 0x7e78
GAME_FLAGS = 0x80163da4
GAME_PAUSED = 0x80168f82
IDLE = {'leon':0x3a32c, 'claire':0x3a3a4}
CHARACTER = 0x80163e30
LOADED = 0x80163f36
TWO_SLOT = frozenset((14,15,16,17,18))
MENU = {'leon':0x73d6c, 'claire':0x73b78}
WEAPONS = ('Unarmed','Knife','Leon handgun','Claire handgun','Custom handgun','Magnum',
           'Custom magnum','Shotgun','Custom shotgun','Grenade launcher','Flame launcher',
           'Acid launcher','Bow gun','Colt SAA','Spark shot','Submachine gun','Flamethrower',
           'Rocket launcher','Gatling gun','Alternate handgun')
RESOURCE = json.loads(Path(__file__).with_name('re2gc_weapons.json').read_text())['characters']
LABELS = json.loads(Path(__file__).with_name('re2gc_item_labels.json').read_text())
_locks = {}; _guard = threading.Lock()


def digest(data): return hashlib.sha256(data).hexdigest()
def raw(ram, address, size): return S._ram(ram, address, size)
def number(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{label} must be an integer from {lo} through {hi}')
    return value


class Source:
    """Open the actual launched image read-only; bound every filesystem read."""
    def __init__(self, path):
        from .gcdisc import GCDisc
        class BoundedDisc(GCDisc):
            def _r(self, off, n):
                if type(off) is not int or type(n) is not int or off < 0 or not 0 <= n <= 16*1024*1024:
                    raise ValueError('GameCube source request exceeds bounded read')
                data = super()._r(off,n)
                if len(data) != n: raise ValueError('Short GameCube source read')
                return data
        self.path = Path(path)
        self.disc = BoundedDisc.__new__(BoundedDisc)
        try:
            BoundedDisc.__init__(self.disc,self.path)
            self.stamp = self._stamp()
            if self.disc.game_id != S.DISC_ID: raise ValueError('The launched image is not GHAE08')
            off = struct.unpack('>I',self.disc._r(0x420,4))[0]
            hdr = self.disc._r(off,0x100)
            end = max(a+n for a,n in zip(struct.unpack_from('>18I',hdr),struct.unpack_from('>18I',hdr,0x90)) if n)
            if end != S.DOL_SIZE: raise ValueError('Unknown main DOL size')
            dol = self.disc._r(off,end)
            self.builds = {}
            for scenario,size in S.REL_SIZES.items():
                name = scenario+'.rel'
                if self.disc.files.get(name,(0,0))[1] != size: raise ValueError('Unknown scenario REL size')
                self.builds[scenario] = S.Build(dol,self.disc.read(name))
            self.check()
        except BaseException:
            self.close(); raise
    def _stamp(self):
        def sig(s): return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        current,opened = sig(self.path.stat()),sig(os.fstat(self.disc.f.fileno()))
        if current != opened: raise ValueError('Launched source file was replaced')
        return opened
    def check(self):
        if self._stamp() != self.stamp: raise ValueError('Launched source image changed during inventory operation')
    def close(self):
        if getattr(self.disc,'f',None): self.disc.f.close()
    def weapon(self,character,item):
        row = RESOURCE.get(str(character),{}).get(str(item))
        if row is None: raise ValueError('This character has no verified native animation resource for that weapon')
        if self.disc.files.get(row['path'],(0,0))[1] != row['size']:
            raise ValueError('Native weapon resource size differs')
        data = self.disc.read(row['path']); self.check()
        if digest(data) != row['sha256']: raise ValueError('Native weapon resource hash differs from owned evidence')
        return dict(row)


def snapshot(builds,ram):
    errors = []
    for build in builds.values():
        try: return build,build.read_snapshot(ram)
        except ValueError as exc: errors.append(str(exc))
    raise ValueError('Active code/module identity was not verified: '+'; '.join(errors))


def pairs(records,capacity,box=False):
    """Reject malformed two-slot state before editing; fourth bytes are opaque."""
    i = 0
    while i < capacity:
        row = records[i]; item,qty,mark = row[:3]
        if item >= 0x68 or mark > 3: raise ValueError('Unknown inventory record')
        if item == 0:
            if qty or mark: raise ValueError('Empty inventory record contains stale quantity/size')
        elif item in TWO_SLOT:
            if box:
                if mark not in (1,3): raise ValueError('Invalid boxed two-slot weapon marker')
            else:
                if mark != 1 or i+1 >= capacity or records[i+1][:3] != bytes((item,qty,2)):
                    raise ValueError('Broken or out-of-capacity two-slot weapon pair')
                i += 1
        elif mark != 0: raise ValueError('Unexpected size marker for a single-slot item')
        i += 1


def view(build,ram,state=None):
    state = state or build.read_snapshot(ram)
    bss = state['bss_base']; base = state['module_base']; cap = state['capacity']
    control = raw(ram,bss+CONTROL,24); task = raw(ram,bss+TASK,36)
    inv = [raw(ram,S.INVENTORY+4*i,4) for i in range(10)]
    box = [raw(ram,S.ITEM_BOX+4*i,4) for i in range(64)]
    pairs(inv,cap); pairs(box,64,True)
    character = raw(ram,CHARACTER,1)[0]
    reasons = []
    if not int.from_bytes(raw(ram,GAME_FLAGS,4),'big') & 0x40000000 or raw(ram,GAME_PAUSED,1)!=b'\0':
        reasons.append('Resume native gameplay before opening and editing the inventory')
    if character != (0 if build.scenario=='leon' else 1): reasons.append('Only the original Leon/Claire character layouts are mapped')
    if not state['equipped']['coherent']: reasons.append('Equipment does not match carried slots')
    if task[:4] != b'\x00\x01\x00\x01' or int.from_bytes(task[4:8],'big') != base+MENU[build.scenario] or task[8:10] != b'\x01\x00':
        reasons.append('Open the native inventory and wait for its fade to finish')
    current_task=int.from_bytes(raw(ram,bss+CURRENT_TASK,4),'big')
    task_delta=current_task-(bss+TASK_TABLE)
    if not 0<=task_delta<8*36 or task_delta%36:
        reasons.append('The native scheduler task pointer is invalid')
    elif current_task == bss+TASK:
        reasons.append('The inventory callback is still executing; refresh after it yields')
    if control[0:4] != b'\x01\x03\x00\x00' or control[16] != 0 or control[22] != 1:
        reasons.append('Select an item in the native inventory and close any action popup')
    if raw(ram,bss+0xb7ea,1)[0] & 4: reasons.append('The native inventory is exiting')
    if control[9] != control[8] or control[11] != control[10]: reasons.append('Close and reopen the inventory after changing equipment in-game')
    if state['equipped']['loaded_weapon_word'] & 0xfff != control[10]: reasons.append('Loaded weapon and menu equipment differ')
    if control[8] < cap and inv[control[8]][2] == 2: reasons.append('The equipped slot points at the second half of a weapon')
    # Stable data relevant to the transaction. Frame timers and animation state
    # are deliberately excluded, so a fresh ordinary frame is not a stale edit.
    token = digest(json.dumps([build.identity(),base,bss,cap,character,control[:4].hex(),control[8:14].hex(),control[16],control[22],task[4:10].hex(),
         [r.hex() for r in inv],[r.hex() for r in box],state['equipped']['loaded_weapon_word']],sort_keys=True).encode())
    names = {r['id']:r['name'] for r in LABELS['items']}; names.update(enumerate(WEAPONS)); names[0]='Empty'
    def rows(values):
        return [{'slot':i,'item_id':r[0],'quantity':r[1],'size_marker':r[2],
                 'name':names.get(r[0],f'Item 0x{r[0]:02X}'),'equipped':control[8]==i and values is inv}
                for i,r in enumerate(values)]
    return {**build.identity(),'module_base':base,'bss_base':bss,'character_id':character,'capacity':cap,
            'inventory':rows(inv),'item_box':rows(box),'equipped':state['equipped'],
            'inventory_sha256':token,'editable':not reasons,'requirements':reasons,
            'weapons':[{'id':int(i),'name':names[int(i)]} for i in RESOURCE.get(str(character),{})],
            'items':LABELS['items'],'label_source':LABELS['source'],
            'source_code_verified':True,'verified':True,'gameplay_verified':False,'unlock_profile_verified':False}


def plan(build,ram,op,region,slot,item,quantity):
    current = view(build,ram)
    if not current['editable']: raise ValueError('; '.join(current['requirements']))
    if op not in ('set','equip','unequip'): raise ValueError('Unknown inventory operation')
    if region not in ('inventory','box'): raise ValueError('Choose inventory or box')
    cap = current['capacity']; bss = current['bss_base']
    inv = [bytearray(raw(ram,S.INVENTORY+4*i,4)) for i in range(10)]
    box = [bytearray(raw(ram,S.ITEM_BOX+4*i,4)) for i in range(64)]
    equipped = current['equipped']['slot']; equipped_item = current['equipped']['item_id']
    if op == 'set':
        count = cap if region=='inventory' else 64
        number(slot,0,count-1,'Slot'); number(item,0,0x67,'Item'); number(quantity,0,255,'Quantity')
        if item == 0 and quantity != 0: raise ValueError('Empty items require quantity zero')
        if item >= 20 and quantity == 0: raise ValueError('Non-weapon items require a positive quantity')
        records = inv if region=='inventory' else box
        old = {slot}
        if region=='inventory':
            if records[slot][2] == 1: old.add(slot+1)
            elif records[slot][2] == 2: old.add(slot-1); slot -= 1
        for i in old: records[i][:3] = b'\0\0\0'
        if region=='inventory' and item in TWO_SLOT:
            if slot+1 >= cap or (slot+1 not in old and records[slot+1][0] != 0):
                raise ValueError('The two-slot weapon needs an adjacent empty carried slot')
            records[slot][:3] = bytes((item,quantity,1)); records[slot+1][:3] = bytes((item,quantity,2))
        else: records[slot][:3] = bytes((item,quantity,3 if item in TWO_SLOT else 0))
        if region=='inventory' and equipped in old:
            equipped,equipped_item = (slot,item) if 1<=item<20 else (0x80,0)
    elif op == 'equip':
        if region!='inventory': raise ValueError('Only a carried weapon can be equipped')
        number(slot,0,cap-1,'Slot')
        if inv[slot][2] == 2: slot -= 1
        equipped_item = inv[slot][0]; equipped = slot
        if not 1 <= equipped_item < 20: raise ValueError('This carried item is not a native weapon')
    else: equipped,equipped_item = 0x80,0
    if str(equipped_item) not in RESOURCE.get(str(current['character_id']),{}):
        raise ValueError('This character has no verified native animation resource for that weapon')
    pairs(inv,cap); pairs(box,64,True)
    changes = []
    for addr,new in ((S.INVENTORY,b''.join(inv)),(S.ITEM_BOX,b''.join(box)),
                     (bss+S.EQUIPPED_SLOT,bytes((equipped,))),(bss+S.EQUIPPED_ITEM,bytes((equipped_item,)))):
        old = raw(ram,addr,len(new))
        if old != new: changes.append({'address':addr,'before':old.hex(),'after':new.hex()})
    return {'before':current,'changes':changes,'equipped_slot':equipped,'equipped_item':equipped_item,
            'close_address':bss+CONTROL,'inventory':b''.join(inv).hex(),'item_box':b''.join(box).hex()}


def read_all(memory):
    chunks = []
    for offset in range(0,S.RAM_SIZE,1<<20):
        data = memory.read(S.RAM_BASE+offset,1<<20)
        if len(data) != 1<<20: raise ValueError('Short native MEM1 read')
        chunks.append(data)
    return b''.join(chunks)


def apply_staged(memory,planned):
    """Caller owns strict freeze. Restore even partially failed writes before resuming."""
    changes = [*planned['changes'],{'address':planned['close_address'],'before':'01','after':'02'}]
    for row in changes:
        if memory.read(row['address'],len(bytes.fromhex(row['before']))) != bytes.fromhex(row['before']):
            raise ValueError('Native data changed before writing; refresh the inventory')
    touched = []
    try:
        for row in changes:
            touched.append(row)  # include a failing partial write in rollback
            data = bytes.fromhex(row['after']); memory.write(row['address'],data)
            if memory.read(row['address'],len(data)) != data: raise ValueError('Inventory read-back mismatch')
    except BaseException as error:
        failures = []
        for row in reversed(touched):
            try:
                old = bytes.fromhex(row['before']); memory.write(row['address'],old)
                if memory.read(row['address'],len(old)) != old: raise RuntimeError('rollback read-back differs')
            except BaseException as exc: failures.append(str(exc))
        if failures: raise RuntimeError('Inventory write failed; rollback incomplete: '+'; '.join(failures)) from error
        raise RuntimeError('Inventory write failed; original bytes restored before native dispatch') from error


def confirm(build,ram,planned):
    state = build.read_snapshot(ram); bss = state['bss_base']
    if state['module_base'] != planned['before']['module_base'] or bss != planned['before']['bss_base']:
        raise RuntimeError('Scenario/module changed after dispatch')
    if int.from_bytes(raw(ram,bss+TASK,2),'big') != 0: return False
    if int.from_bytes(raw(ram,bss+TASK+4,4),'big') != state['module_base']+IDLE[build.scenario] or raw(ram,bss+TASK+0x13,1)!=b'\x01':
        raise RuntimeError('Inventory task did not finish through its native exit routine')
    if state['equipped']['slot'] != planned['equipped_slot'] or state['equipped']['item_id'] != planned['equipped_item']:
        raise RuntimeError('Equipment differs after native close')
    if state['equipped']['loaded_weapon_word'] & 0xfff != planned['equipped_item']:
        raise RuntimeError('Native close did not load the requested weapon')
    if raw(ram,S.INVENTORY,40).hex()!=planned['inventory'] or raw(ram,S.ITEM_BOX,256).hex()!=planned['item_box']:
        raise RuntimeError('Inventory differs after native close')
    return True


def durable_backup(ctx,report):
    data = (json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
    folder = Path(ctx.config.cache)/'re2gc-inventory-backups'; folder.mkdir(parents=True,exist_ok=True)
    path = folder/(uuid.uuid4().hex+'.json')
    with path.open('xb') as out: out.write(data); out.flush(); os.fsync(out.fileno())
    ctx.artifact('re2gc-inventory-before.json',data,'application/json',game=S.GAME_ID,sha256=digest(data))
    return {'path':str(path),'sha256':digest(data)}


def running(ad):
    if getattr(ad,'paused_tids',None):
        raise ValueError('Resume the game before editing inventory; your existing pause was preserved')


def progress(memory,bss,*,sleep=time.sleep):
    """Observe two advances of the owned main-loop gameplay counter.

    Leon REL+0x3169c and Claire REL+0x316d8 increment BSS+0x7e78
    by 1/2 on each active gameplay iteration. Unlike transient current-task
    pointers, the accumulated counter remains observable between callbacks.
    Caller holds the shared memory/control lock, blocking gBox pause/write races.
    """
    previous=int.from_bytes(memory.read(bss+FRAME_COUNTER,4),'big');advances=0
    for _ in range(80):
        sleep(0.005)
        current=int.from_bytes(memory.read(bss+FRAME_COUNTER,4),'big')
        delta=(current-previous)&0xffffffff
        if 0<delta<1000:advances+=1
        elif delta:raise ValueError('Native gameplay counter changed unexpectedly; no bytes were written')
        if advances>=2:return
        previous=current
    raise ValueError('Native frame progress was not observed. Resume Dolphin, leave the inventory open, then refresh; no bytes were written')


def public_view(view,process):
    return {**view,'inventory_sha256':digest(json.dumps([view['inventory_sha256'],process]).encode()),
            'process':{'pid':process[0],'created':process[1]}}


def execute(ad,game,inp,backup,*,hold=frozen,sleep=time.sleep,clock=time.monotonic,prepare=lambda:None,execution_deadline=None):
    dispatch_deadline=clock()+60
    if execution_deadline is not None:
        dispatch_deadline=min(dispatch_deadline,execution_deadline-15)  # reserve rollback/release/verification time
    if game.get('game_id')!=S.GAME_ID or game.get('platform')!='gamecube':
        raise ValueError('This tool supports exact GHAE08 Resident Evil 2 GameCube only')
    from .debug import DolphinProcMem
    memory = ad.debugger()
    if not isinstance(memory,DolphinProcMem) or memory.pid!=ad.proc.pid:
        raise ValueError('A matching Windows Dolphin direct-memory adapter is required')
    path = game.get('_rom_path')
    if not path: raise ValueError('The actual launched image path is unavailable')
    with _source(path) as source:
        # Resolve the mapping before holding emulator threads. All operations
        # inside hold use direct process memory, never emulator/UI/GDB requests.
        with memory_guard(memory): memory.read(S.RAM_BASE,6)
        with hold(ad) as process:
            ram = read_all(memory); build,state = snapshot(source.builds,ram)
            before = view(build,ram,state)
        if inp.op=='list': return public_view(before,process)
        running(ad)
        if inp.expected_inventory_sha256 != public_view(before,process)['inventory_sha256']:
            raise ValueError('Inventory changed since the sidebar read; refresh before editing')
        planned = plan(build,ram,inp.op,inp.region,inp.slot,inp.item_id,inp.quantity)
        resource = source.weapon(before['character_id'],planned['equipped_item'])
        if not planned['changes']: return {**public_view(before,process),'changed':False,'native_transition_verified':False}
        record = {'source':str(source.path),'process':process,'identity':build.identity(),
                  'plan':planned,'weapon_resource':resource,'automatic_post_dispatch_rollback':False}
        saved = backup(record)  # persist before any mutation and outside suspension
        source.check()
        prepare()  # cancellation/network checkpoint outside the emulator hold
        with memory_guard(memory):
            staged=False
            try:
                running(ad)
                progress(memory,before['bss_base'],sleep=sleep)
                with hold(ad) as again:
                    if again!=process: raise ValueError('Emulator process changed before writing')
                    running(ad)
                    latest = read_all(memory)
                    if view(build,latest)['inventory_sha256']!=before['inventory_sha256']:
                        raise ValueError('Inventory changed while preparing the backup; no bytes written')
                    # Re-evaluate task yield and all native menu gates immediately
                    # before changing bytes, not merely the stable view token.
                    fresh=view(build,latest)
                    if not fresh['editable']:raise ValueError('; '.join(fresh['requirements']))
                    if clock()>=dispatch_deadline:raise TimeoutError('Inventory preparation expired; no bytes were written')
                    apply_staged(memory,planned)
                    staged=True
            except Exception as exc:
                if not staged: raise
                return {**public_view(before,process),'verified':False,'changed':True,'outcome':'unknown',
                        'native_transition_verified':False,'error':str(exc),'backup':saved,'retry_allowed':False,
                        'note':'Staged data was verified, but releasing the emulator hold failed. No retry or byte rollback was sent.'}
            # From here the native game may have replaced models/animation state.
            # A byte-only rollback would be dishonest and can corrupt equipment.
            deadline = clock()+8
            try:
                while clock()<deadline:
                    sleep(0.1)
                    with hold(ad) as again:
                        if again!=process: raise RuntimeError('Emulator process changed after dispatch')
                        task = memory.read(before['bss_base']+TASK,2)
                        if task!=b'\0\0': continue
                        after = read_all(memory)
                        if confirm(build,after,planned):
                            return {**public_view(view(build,after),process),'changed':True,'native_transition_verified':True,'backup':saved}
                raise TimeoutError('The game has not confirmed its inventory-close transition')
            except Exception as exc:
                return {**public_view(before,process),'verified':False,'changed':True,'outcome':'unknown','native_transition_verified':False,
                        'error':str(exc),'backup':saved,'retry_allowed':False,
                        'note':'No retry or post-dispatch byte rollback was sent. Refresh and inspect the native inventory.'}


@contextmanager
def _source(path):
    source = Source(path)
    try: yield source
    finally: source.close()


class ItemsIn(BaseModel):
    session_id:str
    op:str=Field(default='list',pattern='^(list|set|equip|unequip)$')
    region:str=Field(default='inventory',pattern='^(inventory|box)$')
    slot:StrictInt=0
    item_id:StrictInt=0
    quantity:StrictInt=0
    expected_inventory_sha256:str=''

class ItemsOut(BaseModel):
    result:dict

@tool('re2gc_items','1.0',ItemsIn,ItemsOut,capabilities=['runtime','memory'],permissions=[Permission.READ],
      platforms=['windows'],timeout_s=90,retries=0,artifacts=['re2gc-inventory-before.json'])
def re2gc_items(inp,ctx):
    """Exact GHAE08 RE2 GameCube inventory: list, set a carried/box slot, equip or unequip.
    Open the native inventory, select an item and close action popups first. Mutations
    require memory_write, exact code and native weapon resources, a fresh inventory
    token and a durable backup. Uses native close/reload; never retries unknown results.
    Does not unlock modes or claim every item has a usable weapon model.
    """
    from .tools import SESSIONS
    if inp.op!='list' and Permission.MEMORY_WRITE not in ctx.config.granted_permissions:
        raise PermissionError('memory_write permission is required')
    with _guard: lock=_locks.setdefault(inp.session_id,threading.Lock())
    if not lock.acquire(blocking=False): raise RuntimeError('Another RE2 inventory operation is in progress')
    try:
        ad,game=SESSIONS[inp.session_id]
        return {'result':execute(ad,game,inp,lambda report:durable_backup(ctx,report),
                                prepare=lambda:ctx.progress(50,'Verifying native inventory before applying the requested change'),
                                execution_deadline=ctx.execution_deadline_monotonic)}
    finally: lock.release()
