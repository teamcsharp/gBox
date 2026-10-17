"""3OE2 offline survival, native MAG editing/feeding and bounded equipment cycling."""
import struct

from .pso_gc_live import GC, BUF, SURVIVAL, F_EQUIP, GUARDS
from .registry import Unsupported

REVIVE=0x801B4340
REMOVE=0x801D4A6C
FEED=0x80112A3C
MAG_APPLY=0x80112C90
MAG_VTABLE=0x8049F478
EXTRA_GUARDS={
 REVIVE:bytes.fromhex('9421fff07c0802a69001001493e1000c'),
 REMOVE:bytes.fromhex('9421ffe07c0802a690010024bf810010'),
 FEED:bytes.fromhex('9421ffc07c0802a690010044bfa10034'),
 MAG_APPLY:bytes.fromhex('9421fff07c0802a690010014bfc10008'),
 0x80100D9C:bytes.fromhex('988300ed4e800020'),
 0x801123F8:bytes.fromhex('9421fff07c0802a69001001493e1000c'),
 0x800113E4:bytes.fromhex('9421fff07c0802a690010014b083032c'),
 0x801117C0:bytes.fromhex('9421fff07c0802a69001001493e1000c'),
 0x80102C78:bytes.fromhex('b083032e4e800020'),
 0x800193A8:bytes.fromhex('a803032420000003'),
}
FOODS={'030000':'Monomate','030001':'Dimate','030002':'Trimate',
       '030100':'Monofluid','030101':'Difluid','030102':'Trifluid',
       '030300':'Antidote','030400':'Antiparalysis','030500':'Sol Atomizer',
       '030600':'Moon Atomizer','030700':'Star Atomizer'}
LEGENDARY={0x80132F9C:bytes.fromhex('9421fff07c0802a6'),
           0x80133084:bytes.fromhex('48000459'),0x80133098:bytes.fromhex('48000445'),
           0x801330C0:bytes.fromhex('4800041d')}
ULTIMATE_RETURN=bytes.fromhex('386000034e800020')


def legendary(ad,on):
 """Offline TLevelSelect eligibility/selection only; never rewrite a loaded area's difficulty."""
 m=GC(ad)
 if m.read(0x80000000,8)!=b'GPOE8P\0\x02':raise Unsupported('Legendary requires GameCube Plus US revision 2')
 for address,expected in GUARDS.items():
  if m.read(address,len(expected))!=expected:raise Unsupported('GameCube executable fingerprint differs')
 if m.read(0x801334DC,8)!=bytes.fromhex('806300a44e800020'):raise Unsupported('The shared menu getter is modified; leave other menus intact')
 for address,original in LEGENDARY.items():
  if m.read(address,len(original)) not in (original,ULTIMATE_RETURN[:len(original)]):raise Unsupported('Difficulty selector is already modified')
 changed=[]
 for address,original in LEGENDARY.items():
  want=ULTIMATE_RETURN[:len(original)] if on else original
  if m.read(address,len(original))!=want:m.write(address,want);changed.append(address)
 if changed:
  # Mid-session preference changes can flush on the guest thread. At boot these routines
  # have not run; do not start a dispatcher or force a state load just for a menu default.
  try:m.check()
  except Unsupported:pass
  else:
   from .pso_gc_live import FLUSH
   lines=sorted({line for a in changed for line in (a&~31,(a+len(LEGENDARY[a])-1)&~31)})
   m.call([(FLUSH,a) for a in lines])
 return {'legendary':bool(on),'verified':all(m.read(a,len(b))==(ULTIMATE_RETURN[:len(b)] if on else b) for a,b in LEGENDARY.items()),
         'note':('Next offline game selects Ultimate.' if on else 'Normal difficulty selection restored.')+' The current loaded area is unchanged.'}


class Extras(GC):
 def check(self,player=True):
  p=super().check(player)
  for address,expected in EXTRA_GUARDS.items():
   if self.read(address,len(expected))!=expected:
    raise Unsupported(f'PSO extended control fingerprint differs at {address:#x}')
  return p

 def survival(self,on):
  self.check();self.hook();self.write(SURVIVAL,struct.pack('>I',int(on)))
  return {'permanent_scape':bool(on),'verified':self.u32(SURVIVAL)==int(on),
          'note':'Virtual Scape Doll: native revival on death, no inventory slot or consumable required.'}

 def revive(self):
  p=self.check()
  if self.u16(p+0x32c):return {'verified':True,'message':'Your character is already alive.'}
  self.write(p+0x324,struct.pack('>H',3)) # the same revival kind used by a consumed Scape Doll
  self.call([(REVIVE,p)])
  hp=self.u16(p+0x32c)
  return {'verified':hp>0,'hp':hp,'tp':self.u16(p+0x32e),'message':'Native revival applied.' if hp else 'Revival did not restore HP.'}

 def equipped_mag(self,item_id=None):
  p=self.check();rows=self.inventory()
  row=next((r for r in rows if r['equipped'] and r['code'].startswith('02')),None)
  if not row:raise ValueError('Equip a MAG first')
  if item_id is not None and row['id']!=item_id:raise ValueError('Your equipped MAG changed; refresh before editing')
  obj=self.item_object(row['id'])
  if self.u32(obj+0x18)!=MAG_VTABLE:raise Unsupported('Unexpected MAG object type')
  return p,obj,row

 def mag(self):
  _,obj,row=self.equipped_mag();raw=self.read(obj+0x198,16)
  iq,synchro,defense,power,dex,mind=struct.unpack_from('>6H',raw)
  stats={'def':defense/100,'pow':power/100,'dex':dex/100,'mind':mind/100,
         'iq':iq,'synchro':synchro,'color':raw[14]}
  stage=self.call([(0x801117C0,obj)])[0]
  return {'mag':{'id':row['id'],'form':int(row['code'][2:4],16),'stage':stage,'level':sum(int(stats[k]) for k in ('def','pow','dex','mind')),
                 **stats},'verified':True}

 def mag_set(self,item_id,changes):
  allowed={'def','pow','dex','mind','iq','synchro','color','form'}
  if not changes or set(changes)-allowed:raise ValueError('Choose supported MAG properties')
  p,obj,row=self.equipped_mag(item_id);raw=bytearray(self.read(obj+0x198,16))
  offsets={'iq':0,'synchro':2,'def':4,'pow':6,'dex':8,'mind':10}
  for name,value in changes.items():
   if name=='form':
    if type(value) not in (int,float) or int(value)!=value or not 0<=value<=0x42:raise ValueError('Choose a native MAG form')
    continue
   cap=120 if name=='synchro' else 18 if name=='color' else 200
   if type(value) not in (int,float) or not 0<=value<=cap:raise ValueError(f'{name} must be between 0 and {cap}')
   if name in ('iq','synchro','color') and int(value)!=value:raise ValueError(f'{name} must be a whole number')
   if name=='color':raw[14]=int(value)
   else:struct.pack_into('>H',raw,offsets[name],round(value*100) if name in ('def','pow','dex','mind') else int(value))
  if sum(struct.unpack_from('>H',raw,i)[0]//100 for i in (4,6,8,10))>200:raise ValueError('MAG total level cannot exceed 200')
  # Retain PBs/flags/identity. The native path recomputes level, equipment effects and evolution.
  before=self.read(obj+0x198,16);self.write(obj+0x198,raw);self.write(BUF,bytes(16))
  self.call([(MAG_APPLY,obj,BUF),(0x801B63AC,p)])
  if 'form' in changes:self.call([(0x80100D9C,obj,int(changes['form'])),(0x801123F8,obj),(0x801B63AC,p)])
  result=self.mag();result['before']=before.hex()
  if any(abs(result['mag'][k]-v)>.021 for k,v in changes.items()):
   raise RuntimeError('MAG read-back differs from the requested values; refresh before making another edit')
  return result

 def mag_feed(self,item_id,food):
  if food not in FOODS:raise ValueError('Choose a native MAG food')
  p,obj,_=self.equipped_mag(item_id);before=self.mag()['mag']
  self.write(BUF,bytes.fromhex(food)+bytes(17));accepted=self.call([(FEED,obj,BUF)])[0]
  if accepted!=1:raise RuntimeError('The game refused MAG feeding')
  self.call([(0x801B63AC,p)])
  return self.mag()|{'food':FOODS[food],'before':before,'note':'Native food effects/evolution; panel feeding does not consume your inventory food.'}

 def equip_id(self,item_id):
  p=self.check();row=next((r for r in self.inventory() if r['id']==item_id),None)
  if not row or not (row['code'].startswith(('00','02','0101','0102'))):raise ValueError('Choose equippable inventory gear')
  obj=self.item_object(item_id);self.call([(F_EQUIP,p,obj,0),(0x801B63AC,p)])
  return any(r['id']==item_id and r['equipped'] for r in self.inventory())

 def remove_generated(self,item_id):
  from .pso_gc_live import ID_BASE
  if not ID_BASE<=item_id<ID_BASE+0x100000:raise ValueError('Only gBox-generated equipment can be removed')
  p=self.check();rows=self.inventory()
  if not any(r['id']==item_id for r in rows):return
  inv=self.ptr(self.u32(p+0xD00),0x1cc);node=self.call([(0x801D4F14,inv,item_id)])[0]
  self.call([(REMOVE,inv,p,self.ptr(node,32)),(0x801B63AC,p)])
  if any(r['id']==item_id for r in self.inventory()):raise RuntimeError('Generated item removal was not acknowledged')
