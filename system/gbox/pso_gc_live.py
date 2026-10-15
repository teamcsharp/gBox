"""Native PSO GameCube 3OE2 controls. Exact revision guards, game-thread calls, no DC addresses."""
import math
import struct
import time
from .registry import Unsupported

DOL_SHA256='1f80fb82b41c05b26b6d0545b1ba9c0aa60b52e6589cf32fbb2ffe644692a61a'
PLAYER=0x8050EA10
PHASE=0x804FE120
VT_UPDATE=0x804C3BC8
ORIGINAL_UPDATE=0x801BB330
CAVE,QUEUE,BUF,END=0x80004000,0x80004400,0x80004900,0x80005000
HEADER=CAVE+0x3F0
NEXT_ID=CAVE+0x3E0
FLUSH=CAVE+0x300
SURVIVAL=CAVE+0x340
QMAX,QSZ=20,40
ID_BASE=0x00F00000
FLOOR=0x805D5FC0
FLOOR_TABLE,FLOOR_COUNTS=0x805D541C,0x805D5420
F_CREATE,F_DELETE,F_INVENTORY,F_EQUIP,F_UNEQUIP=0x801057A8,0x80103748,0x801B8310,0x801B9F40,0x801B9D50
EQUIP_PATCH=0x801050E4
GUARDS={F_CREATE:bytes.fromhex('9421ffe07c0802a690010024bf810010'),
        F_DELETE:bytes.fromhex('9421fff07c0802a69001001493e1000c'),
        F_EQUIP:bytes.fromhex('9421ffe07c0802a690010024bfa10014'),
        ORIGINAL_UPDATE:bytes.fromhex('9421fff07c0802a69001001493e1000c')}
GUARDS.update({
    0x801B8310: bytes.fromhex('9421fff07c0802a69001001480630d00'),
    0x801B9D50: bytes.fromhex('9421fff07c0802a690010014bfc10008'),
    0x801D4F14: bytes.fromhex('9421fff07c0802a69001001438000000'),
    0x801D5764: bytes.fromhex('9421fff07c0802a69001001493e1000c'),
    0x801B3038: bytes.fromhex('9421ffe07c0802a690010024bf810010'),
    0x801B63AC: bytes.fromhex('9421ffe07c0802a690010024dbe10018'),
    0x8010C740: bytes.fromhex('4e8000209421ffe07c0802a690010024'),
    0x8010CCB0: bytes.fromhex('4e8000204e8000209421fff07c0802a6'),
    0x80102AC0: bytes.fromhex('9421fff07c0802a69001001448002961'),
    0x801B8E68: bytes.fromhex('9421ffd07c0802a690010034bfa10024'),
    0x8010B46C: bytes.fromhex('9421fff07c0802a69001001493e1000c'),
    0x8010B198: bytes.fromhex('9421fff07c0802a69001001493e1000c'),
})


def d(op,rt,ra,imm):return op<<26|rt<<21|ra<<16|(imm&0xffff)


def dispatcher():
    """PPC EABI wrapper: preserve update args/CR/FPRs, run bounded calls, tail-chain stock update."""
    code=[];labels={};fix=[]
    def emit(*words):code.extend(words)
    def branch(word,label):fix.append((len(code),label));emit(word)
    emit(d(37,1,1,-0x100),0x7c0802a6,d(36,0,1,0x104),d(47,3,1,8),0x7c000026,d(36,0,1,0x80))
    for r in range(1,14):emit(d(54,r,1,0x88+(r-1)*8))
    # Virtual Scape Doll: only this local offline player, on the guest game thread.
    emit(d(15,12,0,SURVIVAL>>16),d(32,0,12,SURVIVAL&0xffff),d(11,0,0,1));branch(0x40820000,'commands')
    emit(d(15,12,0,(PHASE+0x8000)>>16),d(32,0,12,PHASE&0xffff),d(11,0,0,14));branch(0x40820000,'commands')
    emit(d(15,12,0,(PLAYER+0x8000)>>16),d(32,0,12,PLAYER&0xffff),0x7c001840);branch(0x40820000,'commands')
    emit(d(40,0,3,0x32c),d(11,0,0,0));branch(0x40820000,'commands')
    emit(d(14,0,0,3),d(44,0,3,0x324))  # native Scape Doll revival kind
    emit(d(15,12,0,0x801b),d(24,12,12,0x4340),0x7d8903a6,0x4e800421)
    labels['commands']=len(code)
    emit(d(15,30,0,QUEUE>>16),d(24,30,30,QUEUE&0xffff),d(14,31,0,QMAX))
    labels['loop']=len(code)
    emit(d(32,12,30,0),d(11,0,12,0));branch(0x41820000,'next')
    for r in range(3,11):emit(d(32,r,30,4+(r-3)*4))
    emit(0x7d8903a6,0x4e800421,d(36,3,30,36),d(14,0,0,0),d(36,0,30,0))
    labels['next']=len(code)
    emit(d(14,30,30,QSZ),d(14,31,31,-1),d(11,0,31,0));branch(0x40820000,'loop')
    for r in range(1,14):emit(d(50,r,1,0x88+(r-1)*8))
    emit(d(32,0,1,0x80),0x7c0ff120,d(46,3,1,8),d(32,0,1,0x104),0x7c0803a6,d(14,1,1,0x100),
         d(15,12,0,(HEADER+8+0x8000)>>16),d(32,12,12,(HEADER+8)&0xffff),0x7d8903a6,0x4e800420)
    for index,label in fix:code[index]|=((labels[label]-index)*4)&0xfffc
    out=struct.pack('>'+str(len(code))+'I',*code)
    assert len(out)<0x300
    return out


CODE=dispatcher()
FLUSH_CODE=bytes.fromhex('7c00186c7c0004ac7c001fac4c00012c4e800020')


class GC:
    def __init__(self,ad):
        self.read,self.write=ad.read_memory,ad.write_memory
        self.publish=getattr(getattr(ad,'dbg',None),'write',None) or self.write

    def u32(self,address):return struct.unpack('>I',self.read(address,4))[0]
    def u16(self,address):return struct.unpack('>H',self.read(address,2))[0]
    def ptr(self,address,size=4):
        if address&3 or not 0x80000000<=address<=0x81800000-size:raise RuntimeError('PSO pointer is outside MEM1')
        return address

    def check(self,player=True):
        if self.read(0x80000000,8)!=b'GPOE8P\0\x02':raise Unsupported('PSO GameCube controls require GPOE8P disc 0 revision 2 (3OE2)')
        for address,expected in GUARDS.items():
            if self.read(address,len(expected))!=expected:raise Unsupported(f'PSO GameCube executable fingerprint differs at {address:#x}')
        patch=self.read(EQUIP_PATCH,4)
        if patch not in (bytes.fromhex('881d0000'),bytes.fromhex('38000005')):raise Unsupported('Unexpected GameCube equipment code')
        if self.u32(PHASE)!=0xE:raise Unsupported('GameCube native actions require an active offline free-play session')
        if not player:return
        p=self.ptr(self.u32(PLAYER),0x1200)
        name=self.ptr(self.u32(p),16)
        if self.read(name,11)!=b'TObjPlayer\0':raise Unsupported('The local PSO player is not initialized')
        if self.u32(p+0x18)!=VT_UPDATE-12:raise Unsupported('Unexpected PSO player vtable')
        return p

    def hook(self):
        self.check()
        head=self.read(HEADER,16)
        if self.u32(VT_UPDATE)==CAVE:
            if head!=b'GBPSOGC2'+struct.pack('>II',ORIGINAL_UPDATE,VT_UPDATE) or self.read(CAVE,len(CODE))!=CODE:
                raise Unsupported('The PSO native dispatcher does not match this build')
            return
        if self.u32(VT_UPDATE)!=ORIGINAL_UPDATE:raise Unsupported('PSO update slot is already modified')
        old=self.read(CAVE,END-CAVE)
        if any(old) and not (head==b'GBPSOGC2'+struct.pack('>II',ORIGINAL_UPDATE,VT_UPDATE) and old[:len(CODE)]==CODE):
            raise Unsupported('PSO scratch region is occupied; leave it intact')
        self.write(CAVE,CODE);self.write(FLUSH,FLUSH_CODE)
        self.write(HEADER,b'GBPSOGC2'+struct.pack('>II',ORIGINAL_UPDATE,VT_UPDATE))
        self.write(SURVIVAL,bytes(4))
        self.write(QUEUE,bytes(QMAX*QSZ))
        self.write(VT_UPDATE,struct.pack('>I',CAVE))  # data pointer: works on an already-running JIT session

    def call(self,calls,timeout=2):
        if not 1<=len(calls)<=QMAX:raise ValueError('Native batch must contain 1–20 calls')
        self.hook()
        if any(self.u32(QUEUE+i*QSZ) for i in range(QMAX)):raise RuntimeError('A previous PSO command is still pending; do not retry it')
        data=b''.join(struct.pack('>10I',0,*[int(v)&0xffffffff for v in args],*([0]*(8-len(args))),0) for fn,*args in calls)
        self.write(QUEUE,data)
        for i,(fn,*_) in enumerate(calls):self.publish(QUEUE+i*QSZ,struct.pack('>I',fn))
        until=time.monotonic()+timeout
        while True:
            raw=self.read(QUEUE,len(calls)*QSZ)
            if all(struct.unpack_from('>I',raw,i*QSZ)[0]==0 for i in range(len(calls))):
                return [struct.unpack_from('>I',raw,i*QSZ+36)[0] for i in range(len(calls))]
            if time.monotonic()>until:raise RuntimeError('PSO did not acknowledge the native batch; outcome unknown, no automatic retry')
            time.sleep(.005)

    def floor_items(self):
        floor=self.u32(FLOOR)
        if not 0<=floor<18:raise RuntimeError('Unexpected PSO floor')
        counts=self.ptr(self.u32(FLOOR_COUNTS),18*4);tables=self.ptr(self.u32(FLOOR_TABLE),18*4)
        count=self.u32(counts+floor*4)
        if not 0<=count<=512:raise RuntimeError('Unexpected PSO floor-item count')
        if not count:return []
        records=self.ptr(self.u32(tables+floor*4),count*36);data=self.read(records,count*36)
        return [(struct.unpack_from('>I',data,i*36+28)[0],data[i*36+16:i*36+19].hex()) for i in range(count)]

    def floor_spawn(self,codes,radius=18,grinds=None):
        p=self.check();self.hook()
        if not 1<=len(codes)<=20 or not math.isfinite(radius) or not 5<=radius<=100:raise ValueError('Use 1–20 items and a finite radius from 5–100')
        if any(len(bytes.fromhex(c))!=3 for c in codes):raise ValueError('Item code must contain three bytes')
        ids={i for i,_ in self.floor_items()};next_id=max(ID_BASE,self.u32(NEXT_ID),max([ID_BASE-1,*[i for i in ids if ID_BASE<=i<ID_BASE+0x100000]])+1)
        if next_id+len(codes)>=ID_BASE+0x100000:raise RuntimeError('gBox item ID range exhausted')
        x,y,z=struct.unpack('>3f',self.read(p+0x38,12));room=self.u16(p+0x28);floor=self.u32(FLOOR)
        if not all(math.isfinite(v) and abs(v)<1e7 for v in (x,y,z)):raise RuntimeError('Invalid player position')
        records=[]
        for index,code in enumerate(codes):
            angle=2*math.pi*index/len(codes);item=bytearray(20);item[:3]=bytes.fromhex(code)
            if code.startswith('00'):item[3]=max(0,min(255,int((grinds or {}).get(code,0))))
            struct.pack_into('>I',item,12,next_id+index)
            records.append(struct.pack('>BBHffHH',floor,1,0,x+radius*math.sin(angle),z+radius*math.cos(angle),room,index)+item)
        self.write(NEXT_ID,struct.pack('>I',next_id+len(codes)))  # reserve before publishing; never reuse after clear/pickup
        self.write(BUF,b''.join(records));objects=self.call([(F_CREATE,BUF+36*i,0) for i in range(len(codes))])
        actual=dict(self.floor_items());confirmed=sum(actual.get(next_id+i)==c for i,c in enumerate(codes))
        return {'spawned':confirmed,'codes':codes,'verified':confirmed==len(codes),'objects':objects,'ids':[next_id+i for i in range(len(codes))]}

    def floor_clear(self):
        self.check();ids=[i for i,_ in self.floor_items() if ID_BASE<=i<ID_BASE+0x100000];floor=self.u32(FLOOR)
        if ids:self.hook()
        for off in range(0,len(ids),QMAX):
            batch=ids[off:off+QMAX]
            self.write(BUF,b''.join(struct.pack('<BBHII',0x63,3,0,i,floor) for i in batch))
            self.call([(F_DELETE,BUF+12*i) for i in range(len(batch))])
        remaining={i for i,_ in self.floor_items()};removed=sum(i not in remaining for i in ids)
        return {'removed':removed,'verified':removed==len(ids),'scope':'only gBox-spawned items'}

    def unhook(self):
        if self.u32(VT_UPDATE)==CAVE:self.write(VT_UPDATE,struct.pack('>I',ORIGINAL_UPDATE))

    def equip_any(self,on):
        self.check();self.hook()
        want=bytes.fromhex('38000005' if on else '881d0000')
        self.write(EQUIP_PATCH,want)
        self.call([(FLUSH,EQUIP_PATCH)])  # guest icbi invalidates Dolphin's already-compiled code
        return {'equip_any':bool(on),'verified':self.read(EQUIP_PATCH,4)==want,'code_cache_flushed':True}

    def inventory(self):
        p=self.check();count=self.call([(F_INVENTORY,p,BUF)])[0]
        if count>30:raise RuntimeError('Unexpected PSO inventory length')
        data=self.read(BUF,count*28);rows=[]
        for i in range(count):
            entry=data[i*28:(i+1)*28];item=entry[8:28]
            rows.append({'slot':i,'code':item[:3].hex(),'id':struct.unpack_from('>I',item,12)[0],
                         'equipped':bool(struct.unpack_from('>I',entry,4)[0]&8),'data':item.hex()})
        return rows

    def item_object(self,item_id):
        p=self.check();inv=self.ptr(self.u32(p+0xD00),0x1cc)
        node=self.call([(0x801D4F14,inv,item_id)])[0]
        if not node:raise ValueError('Item is no longer in your inventory')
        obj=self.call([(0x801D5764,self.ptr(node,32))])[0]
        return self.ptr(obj,0x200)

    def shown_stats(self):
        p=self.check();self.call([(0x801B3038,p,BUF)])
        values=struct.unpack('>6H',self.read(BUF,12))
        return dict(zip(('atp','dfp','mst','ata','evp','lck'),values))|{'hp':self.u16(p+0x2B8)}

    def set_stat(self,name,value):
        offsets={'atp':0,'mst':2,'evp':4,'hp':6,'dfp':8,'ata':10,'lck':12}
        if name not in offsets or not 0<=value<=9999:raise ValueError('Choose a valid stat and a value from 0 to 9999')
        p=self.check();base=self.ptr(self.u32(p+0x2B0),0x24)
        address=base+offsets[name];original=self.read(address,2);before=self.shown_stats()[name]
        if before==value:
            return {'stat':name,'before':before,'shown_now':before,'verified':True}
        if name=='hp':
            low,high=0,32767
            for _ in range(16):
                if low>high:break
                mid=(low+high)//2;self.write(address,struct.pack('>H',mid));self.call([(0x801B63AC,p)])
                shown=self.shown_stats()[name]
                if shown==value:break
                if shown<value:low=mid+1
                else:high=mid-1
        # Solve against the game's displayed value (gear, level and ATA scaling included).
        for _ in range(4):
            shown=self.shown_stats()[name]
            if shown==value:break
            current=self.u16(address);step=(value-shown)*(10 if name=='ata' else 1)
            adjusted=max(0,min(32767,current+step))
            if adjusted==current:break
            self.write(address,struct.pack('>H',adjusted));self.call([(0x801B63AC,p)])
        after=self.shown_stats()[name]
        if after!=value:
            self.write(address,original);self.call([(0x801B63AC,p)])
            raise ValueError('This value cannot be represented with the current equipment and level; original stat restored')
        return {'stat':name,'before':before,'shown_now':after,'verified':True,'scope':'current character RAM; the game controls normal saving'}

    def give(self,code,count=1):
        p=self.check();self.hook()
        if len(bytes.fromhex(code))!=3 or not 1<=count<=20:raise ValueError('Choose 1 to 20 catalog items')
        before=self.inventory()
        if len(before)+count>30:raise ValueError('Not enough inventory slots')
        next_id=max(ID_BASE,self.u32(NEXT_ID));created=[]
        if next_id+count>=ID_BASE+0x100000:raise RuntimeError('gBox item ID range exhausted')
        for index in range(count):
            item=bytearray(20);item[:3]=bytes.fromhex(code);struct.pack_into('>I',item,12,next_id+index)
            if code.startswith('03'):item[5]=1
            if code.startswith('02'):
                item[2]=5;struct.pack_into('<H',item,4,500);item[16]=40;item[19]=14
            self.write(NEXT_ID,struct.pack('>I',next_id+index+1));self.write(BUF,item)
            self.call([(0x8010C740,BUF,0),(0x8010CCB0,BUF)])
            obj=self.call([(0x80102AC0,BUF)])[0]
            if not obj:raise RuntimeError('Game refused the item object')
            self.call([(0x801B8E68,p,self.ptr(obj,0x200))]);created.append(next_id+index)
        after=self.inventory()
        def quantity(rows):
            return sum(max(1,bytes.fromhex(r['data'])[5]) if code.startswith('03') else 1 for r in rows
                       if (r['code'][:4]==code[:4] if code.startswith('02') else r['code']==code))
        added=quantity(after)-quantity(before)
        return {'created':added,'ids':[r['id'] for r in after if r['id'] in created],
                'verified':added==count,'note':'Consumables may merge into an existing stack.'}

    def multi_equip(self,target,on):
        p=self.check();rows=self.inventory()
        row=next((r for r in rows if str(r['slot'])==str(target)),None)
        if not row or not row['code'].startswith('00'):raise ValueError('Choose a weapon slot from the current inventory')
        obj=self.item_object(row['id']);slots=self.read(p+0xD04,13*4)
        if row['equipped']==bool(on):return {'verified':True,'message':'Weapon is already '+('equipped.' if on else 'unequipped.')}
        vt=self.ptr(self.u32(obj+0x18),0x88)
        callback=self.u32(vt+(0x50 if on else 0x54))
        if not 0x80003100<=callback<0x80440000:raise Unsupported('Unexpected weapon callback')
        # The native callbacks accumulate/remove the real weapon effects. Keep the visible weapon slot unchanged.
        if on or obj not in struct.unpack('>13I',slots):self.call([(callback,obj),(0x801B63AC,p)])
        else:self.call([(F_UNEQUIP,p,obj),(0x801B63AC,p)])
        after=next((r for r in self.inventory() if r['id']==row['id']),{})
        return {'verified':after.get('equipped')==bool(on),'message':'Weapon effects '+('stacked.' if on else 'removed.'),
                'active_weapon_unchanged':self.read(p+0xD04,13*4)==slots,
                'note':'One active weapon is drawn; this stacks equipment effects, not dual-wield animation.'}
