"""3OE2 offline enemy loot, reversible collision bypass and native boss travel."""
import struct
import time

from .pso_gc_live import GC, PHASE, FLOOR, FLUSH, d
from .registry import Unsupported

DROP_ENTRY = 0x8010663C
DROP_ORIGINAL = bytes.fromhex('9421ffe0')
CODE_ADDRESS, CONFIG, HEADER = 0x80006000, 0x80006400, 0x800067E0
REGION_END = 0x80006800
WARP = 0x801BAB1C
EPISODE = 0x8001E5C8
SET_TARGET, BEGIN_TRAVEL, TRAVEL_STATE, TRAVELLING = 0x80228540, 0x8000F998, 0x80515BA0, 0x805D49B8
GUARDS = {
    WARP: bytes.fromhex('9421ffe07c0802a690010024bfc10018'),
    EPISODE: bytes.fromhex('806dba604e800020'),
    DROP_ENTRY+4: bytes.fromhex('7c0802a690010024bf810010'),
    0x8011C3D4: bytes.fromhex('806daef87fe6fb7838a5ffff90a100084bfea259'),
    SET_TARGET: bytes.fromhex('9421fff07c0802a69001001493e1000c'),
    BEGIN_TRAVEL: bytes.fromhex('38000001900da3b84e800020'),
}
# Published Plus collision recipe, independently matched to the owned 3OE2 DOL.
COLLISION = {
    0x80079338: ('418001ec', '60000000'),
    0x80079358: ('418001cc', '60000000'),
    0x80079368: ('418001bc', '60000000'),
    0x80079964: ('4835f05d', '60000000'),
    0x80079974: ('4082000c', '60000000'),
    0x801423E8: ('c0240000', '4e800020'),
}
BOSSES = {
    0: [('dragon', 'Dragon / Sil Dragon', 11), ('de_rol_le', 'De Rol Le / Dal Ra Lie', 12),
        ('vol_opt', 'Vol Opt', 13), ('dark_falz', 'Dark Falz', 14)],
    1: [('barba_ray', 'Barba Ray', 14), ('gol_dragon', 'Gol Dragon', 15),
        ('gal_gryphon', 'Gal Gryphon', 12), ('olga_flow', 'Olga Flow', 13)],
}


def branch(source, target):
    delta = target-source
    if delta % 4 or not -(1 << 25) <= delta < (1 << 25):
        raise ValueError('PPC branch is out of range')
    return 0x48000000 | (delta & 0x03FFFFFC)


def drop_code():
    """Leaf override for the enemy generator only; native boxes/shops stay stock.

    The caller supplies ItemData* in r6 and assigns the floor ID afterward. No
    callbacks, host polling or synthetic floor spawns occur for an enemy kill.
    """
    code, labels, fixes = [], {}, []
    def emit(*words): code.extend(words)
    def jump(word, label): fixes.append((len(code), label)); emit(word)
    emit(d(15,12,0,(PHASE+0x8000)>>16),d(32,0,12,PHASE&0xFFFF),d(11,0,0,14))
    jump(0x40820000,'stock')
    emit(d(11,0,6,0)); jump(0x41820000,'stock')
    emit(d(15,12,0,CONFIG>>16),d(24,12,12,CONFIG&0xFFFF),d(32,0,12,0),d(11,0,0,1))
    jump(0x41800000,'stock')
    emit(d(11,0,0,20)); jump(0x41810000,'stock')
    emit(d(32,7,12,4),0x7C070040)  # cmplw r7,r0: corrupted/high indices wrap to zero
    jump(0x41800000,'selected')
    emit(d(14,7,0,0))
    labels['selected']=len(code)
    emit(d(7,8,7,20),d(14,9,12,32),0x7D294214)  # record = pool + index*20
    for offset in range(0,20,4): emit(d(32,8,9,offset),d(36,8,6,offset))
    emit(d(14,7,7,1),d(36,7,12,4),d(32,8,12,8),d(14,8,8,1),d(36,8,12,8),d(36,4,12,12),0x4E800020)
    labels['stock']=len(code)
    emit(int.from_bytes(DROP_ORIGINAL,'big'))
    emit(branch(CODE_ADDRESS+len(code)*4,DROP_ENTRY+4))
    for index,label in fixes: code[index]|=((labels[label]-index)*4)&0xFFFC
    result=struct.pack('>'+str(len(code))+'I',*code)
    assert len(result)<0x300
    return result


CODE=drop_code()
DROP_BRANCH=struct.pack('>I',branch(DROP_ENTRY,CODE_ADDRESS))
METADATA=b'GBPSOAD1'+struct.pack('>II',DROP_ENTRY,len(CODE))


def item_record(code, grind=0):
    data=bytearray(20);data[:3]=bytes.fromhex(code)
    data[12:16]=b'\xff'*4  # the engine, not gBox, allocates the dropped item's ID
    if code.startswith('00'): data[3]=max(0,min(255,int(grind)))
    if code.startswith('03'): data[5]=1
    if code.startswith('02'):
        data[2]=5;struct.pack_into('<H',data,4,500);data[16]=40;data[19]=14
    return bytes(data)


class Adventure(GC):
    def __init__(self,ad):
        super().__init__(ad)
        self.adapter=ad

    def check(self, player=True):
        p=super().check(player)
        for address,expected in GUARDS.items():
            if self.read(address,len(expected))!=expected:
                raise Unsupported(f'PSO adventure fingerprint differs at {address:#x}')
        if self.read(DROP_ENTRY,4) not in (DROP_ORIGINAL,DROP_BRANCH):
            raise Unsupported('The enemy item generator is already modified')
        return p

    def flush(self, addresses):
        lines=sorted({a&~31 for a in addresses})
        for i in range(0,len(lines),20): self.call([(FLUSH,a) for a in lines[i:i+20]])

    def owned(self):
        return self.read(HEADER,16)==METADATA and self.read(CODE_ADDRESS,len(CODE))==CODE

    def loot_status(self):
        self.check()
        active=self.read(DROP_ENTRY,4)==DROP_BRANCH
        if active and not self.owned(): raise Unsupported('Unknown enemy drop hook; leave it intact')
        count=self.u32(CONFIG) if self.owned() else 0
        if count>20: raise Unsupported('Invalid enemy drop pool')
        return {'on':active,'codes':[self.read(CONFIG+32+i*20,3).hex() for i in range(count)],
                'generated':self.u32(CONFIG+8) if self.owned() else 0,'verified':True}

    def enemy_drops(self,on,codes=(),grinds=None):
        self.check()
        if on and (not 1<=len(codes)<=20 or any(len(c)!=6 or any(x not in '0123456789abcdef' for x in c) for c in codes)):
            raise ValueError('Select 1 to 20 catalog item codes for enemy drops')
        owned=self.owned()
        if self.read(DROP_ENTRY,4)==DROP_BRANCH and not owned: raise Unsupported('Unknown enemy drop hook; leave it intact')
        if not on and not owned: return {'on':False,'verified':True,'message':'Normal enemy drops are active.'}
        if not owned and any(self.read(CODE_ADDRESS,REGION_END-CODE_ADDRESS)):
            raise Unsupported('Enemy loot scratch region is occupied; leave it intact')
        self.hook()
        # Quiesce a previous hook on the guest thread before changing its pool.
        if self.read(DROP_ENTRY,4)==DROP_BRANCH:
            self.write(DROP_ENTRY,DROP_ORIGINAL);self.flush([DROP_ENTRY])
        if not on:
            self.write(CONFIG,bytes(4))
            return {'on':False,'verified':self.read(DROP_ENTRY,4)==DROP_ORIGINAL,'message':'Normal enemy drops restored.'}
        if not owned:
            self.write(CODE_ADDRESS,CODE);self.write(HEADER,METADATA)
            self.flush(range(CODE_ADDRESS,CODE_ADDRESS+len(CODE),32))
        pool=b''.join(item_record(c,(grinds or {}).get(c,0)) for c in codes)
        self.write(CONFIG,struct.pack('>8I',len(codes),0,0,0,0,0,0,0)+pool)
        self.write(DROP_ENTRY,DROP_BRANCH);self.flush([DROP_ENTRY])
        return self.loot_status()|{'message':'Enemies now drop one item per normal enemy drop event, cycling through your selected pool. Boxes are unchanged.'}

    def walk_through(self,on):
        self.check()
        for address,(before,after) in COLLISION.items():
            if self.read(address,4).hex() not in (before,after):
                raise Unsupported(f'Collision code differs at {address:#x}; no collision writes applied')
        changed=[]
        for address,pair in COLLISION.items():
            want=bytes.fromhex(pair[int(on)])
            if self.read(address,4)!=want: self.write(address,want);changed.append(address)
        if changed: self.flush(changed)
        return {'on':bool(on),'verified':all(self.read(a,4).hex()==v[int(on)] for a,v in COLLISION.items()),
                'message':'Walk through collision barriers enabled.' if on else 'Normal collision restored.'}

    def destinations(self):
        self.check()
        episode=self.u32(0x805D6060)
        if episode not in BOSSES: raise Unsupported('Unknown PSO episode')
        floor=self.u32(FLOOR)
        default=next((key for key,_,target in BOSSES[episode] if target==floor),None)
        if default is None:
            index=(0 if floor<=2 else 1 if floor<=5 else 2 if floor<=7 else 3) if episode==0 else (0 if floor<=2 else 1 if floor<=4 else 2 if floor<=9 else 3)
            default=BOSSES[episode][index][0]
        return {'episode':episode+1,'default':default,'bosses':[{'id':key,'name':name,'floor':floor} for key,name,floor in BOSSES[episode]],'verified':True}

    def walk_state(self):
        values=[]
        for address,(before,after) in COLLISION.items():
            actual=self.read(address,4).hex()
            if actual not in (before,after): raise Unsupported('Collision code is modified by another patch')
            values.append(actual==after)
        if any(values) and not all(values):
            raise Unsupported('Collision patch is only partially applied; use the explicit toggle to restore all six sites')
        return all(values)

    def teleport_boss(self,key):
        p=self.check()
        choices=self.destinations()
        boss=next((b for b in choices['bosses'] if b['id']==key),None)
        if not boss: raise ValueError('Choose a boss in the current episode')
        if not self.u16(p+0x32C): raise ValueError('Revive your character before travelling')
        if self.u32(TRAVELLING): raise ValueError('An area transition is already in progress; wait for it to finish')
        if self.u32(FLOOR)==boss['floor']:
            return {'verified':True,'message':'You are already in '+boss['name']+"'s area."}
        # The native porter first sets the shared destination, begins loading,
        # then broadcasts the player's destination. A packet alone does not load a map.
        self.call([(SET_TARGET,TRAVEL_STATE,boss['floor']),(BEGIN_TRAVEL,),(WARP,p,boss['floor'])])
        if self.u32(TRAVEL_STATE+12)!=boss['floor']:
            raise RuntimeError('The native area loader did not acknowledge the destination; do not automatically retry')
        self.adapter._pso_boss_trip={**boss,'started':time.monotonic()}
        return {'verified':True,'requested':True,'arrived':False,'message':'Travelling to '+boss['name']+'; the game is loading the destination.'}

    def travel_status(self):
        trip=getattr(self.adapter,'_pso_boss_trip',None)
        if not trip:return None
        age=time.monotonic()-trip['started']
        loaded=self.u32(FLOOR)==trip['floor'] and self.u32(TRAVELLING)==0
        state='arrived' if loaded else 'unconfirmed' if age>45 else 'loading'
        return {'state':state,'boss':trip['name'],'floor':trip['floor'],'age_s':round(age,1),
                'message':('Boss area loaded: ' if loaded else 'Arrival not confirmed; no automatic retry: ' if age>45 else 'Loading boss area: ')+trip['name']}


def validate_pool(rows,codes,max_grind):
    by_code={r['code']:r for r in rows}
    if not 1<=len(codes)<=20 or len(set(codes))!=len(codes) or any(c not in by_code for c in codes):
        raise ValueError('Select 1 to 20 unique items from this GameCube disc database')
    return list(codes),{c:by_code[c].get('max_grind',0) for c in codes} if max_grind else {}


def apply_preferences(ad,prefs,ctx):
    """Apply the selected policy to supported current/future builds, including after a state load."""
    m=Adventure(ad);m.check()
    want_walk=bool(prefs.get('walk_through',False))
    if m.walk_state()!=want_walk: m.walk_through(want_walk)
    active=m.loot_status()['on'];want=bool(prefs.get('enemy_drops',False))
    if not want:
        if active:m.enemy_drops(False)
        return
    from .pso_live import catalog
    codes,grinds=validate_pool(catalog(ctx,'gc'),prefs.get('enemy_codes',[]),prefs.get('enemy_max_grind',True))
    expected=b''.join(item_record(c,grinds.get(c,0)) for c in codes)
    if not active or m.u32(CONFIG)!=len(codes) or m.read(CONFIG+32,len(expected))!=expected:
        m.enemy_drops(True,codes,grinds)
