import struct
from types import SimpleNamespace

import pytest
from gbox import pso_gc_extras as E,pso_modes as M
from gbox.registry import Unsupported
from test_pso_gc_live import RAM
from gbox import pso_gc_live as G


def memory():
 ram=RAM()
 for a,b in E.EXTRA_GUARDS.items():ram.put(a,b)
 for a,b in E.LEGENDARY.items():ram.put(a,b)
 ram.put(0x801334DC,bytes.fromhex('806300a44e800020'))
 return ram


def test_extended_revision_guard_cannot_enable_autorevival_on_unknown_code():
 ram=memory();ram.put(E.REVIVE,b'bad!');m=E.Extras(ram)
 with pytest.raises(Unsupported):m.survival(True)
 assert not ram.writes


def test_survival_flag_is_idempotent_and_requires_no_inventory_item():
 ram=memory();m=E.Extras(ram)
 m.inventory=lambda:pytest.fail('A virtual Doll must not consume inventory')
 assert m.survival(True)['verified']
 assert m.u32(E.SURVIVAL)==1
 assert m.survival(False)['verified'] and m.u32(E.SURVIVAL)==0


def test_mag_rejects_stale_identity_and_overlevel_without_writes():
 ram=memory();m=E.Extras(ram);obj=0x80db0000
 ram.put(obj+0x198,struct.pack('>6H4B',0,40,500,0,0,0,0,0,14,0))
 m.equipped_mag=lambda item_id=None:(ram.player,obj,{})
 with pytest.raises(ValueError,match='total level'):
  m.mag_set(1,{'pow':200})
 with pytest.raises(ValueError):m.mag_set(1,{'synchro':float('nan')})
 assert not ram.writes
 m=E.Extras(ram);m.inventory=lambda:[{'equipped':True,'code':'020005','id':1}]
 with pytest.raises(ValueError,match='changed'):m.mag_set(2,{'pow':10})
 assert not ram.writes


def test_randomizer_uses_native_equip_and_bounds_generated_inventory():
 class Gear:
  def __init__(self):self.rows=[{'id':1,'code':'000100','equipped':True}];self.serial=0;self.removed=[]
  def check(self):return 1
  def u16(self,a):return 1
  def inventory(self):return self.rows[:]
  def give(self,code):
   self.serial+=1;i=0xf00000+self.serial;self.rows.append({'id':i,'code':code,'equipped':False});return {'ids':[i],'verified':True}
  def equip_id(self,i):
   for r in self.rows:r['equipped']=r['id']==i
   return True
  def remove_generated(self,i):self.removed.append(i);self.rows=[r for r in self.rows if r['id']!=i]
 m=Gear();state={'on':True,'due':0,'interval':15,'categories':['weapon'],'character_class':'HUmar',
  'catalog':[{'code':'001000','rare':True,'classes':['HUmar']}],'generated':{},'cycles':0}
 for n in range(100):M.tick(m,state,n*15)
 assert len(m.rows)==2 and m.rows[0]['id']==1
 assert state['cycles']==100 and len(m.removed)==99
 M.tick(m,state,1485)
 assert state['cycles']==100 # no backlog/catch-up bursts


def test_generated_cleanup_refuses_original_item_ids():
 ram=memory()
 with pytest.raises(ValueError,match='gBox-generated'):E.Extras(ram).remove_generated(65538)
 assert not ram.writes


def test_rewind_does_not_delete_generated_ids_from_a_different_state_branch():
 ram=memory();m=E.Extras(ram)
 state={'on':True,'due':0,'epoch':bytes(16).hex(),'owned':{0xf00001:'weapon'},'original':{},'generated':{}}
 M.new_epoch(m,state);ram.put(M.MARKER,bytes(16));ram.writes.clear()
 with pytest.raises(ValueError,match='state load/reset'):M.tick(m,state,1)
 with pytest.raises(ValueError,match='state load/reset'):M.cleanup(m,state)
 assert not ram.writes


@pytest.mark.parametrize('survival',[False,True])
@pytest.mark.parametrize('unhooked',[False,True])
def test_known_legacy_state_moves_code_without_overwriting_warm_entry(survival,unhooked):
 ram=memory();m=E.Extras(ram)
 version=b'GBPSOGC2' if survival else b'GBPSOGC1'
 old=G.dispatcher(survival,G.OLD_HEADER,G.OLD_SURVIVAL)
 ram.put(G.OLD_CAVE,old);ram.put(G.OLD_HEADER,version+struct.pack('>II',G.ORIGINAL_UPDATE,G.VT_UPDATE))
 ram.word(G.VT_UPDATE,G.ORIGINAL_UPDATE if unhooked else G.OLD_CAVE);ram.word(G.OLD_NEXT,G.ID_BASE+42)
 ram.word(G.OLD_SURVIVAL,int(survival))
 ram.put(G.CAVE,b'previous inventory export')
 m.hook()
 assert m.u32(G.VT_UPDATE)==G.CAVE and m.u32(G.NEXT_ID)==G.ID_BASE+42
 assert m.u32(G.SURVIVAL)==int(survival)
 assert ram.read_memory(G.OLD_CAVE,len(old))==old
 assert G.BUF+30*28<=G.CAVE


@pytest.mark.parametrize('damage',['code','header','pending','vtable'])
def test_legacy_migration_refuses_unknown_or_pending_hooks_without_writes(damage):
 ram=memory();m=E.Extras(ram)
 ram.put(G.OLD_CAVE,G.dispatcher(False,G.OLD_HEADER,G.OLD_SURVIVAL))
 ram.put(G.OLD_HEADER,b'GBPSOGC1'+struct.pack('>II',G.ORIGINAL_UPDATE,G.VT_UPDATE));ram.word(G.VT_UPDATE,G.OLD_CAVE)
 if damage=='code':ram.put(G.OLD_CAVE,b'xxxx')
 if damage=='header':ram.put(G.OLD_HEADER,b'unknown!')
 if damage=='pending':ram.word(G.QUEUE,G.F_CREATE)
 if damage=='vtable':ram.word(G.VT_UPDATE,0x80002000)
 with pytest.raises((Unsupported,RuntimeError)):m.hook()
 assert not ram.writes


def test_fresh_hook_refuses_an_occupied_command_or_inventory_buffer():
 for address in (G.QUEUE,G.BUF):
  ram=memory();ram.put(address,b'occupied')
  with pytest.raises(Unsupported,match='scratch'):E.Extras(ram).hook()
  assert not ram.writes


def test_legendary_changes_only_offline_menu_code_and_flushes_reversibly(monkeypatch):
 ram=memory();calls=[]
 monkeypatch.setattr(E.GC,'call',lambda self,batch:calls.extend(batch) or [0]*len(batch))
 assert E.legendary(ram,True)['verified']
 assert all(ram.read_memory(a,len(b))==E.ULTIMATE_RETURN[:len(b)] for a,b in E.LEGENDARY.items())
 assert E.legendary(ram,False)['verified']
 assert all(ram.read_memory(a,len(b))==b for a,b in E.LEGENDARY.items())
 assert ram.read_memory(0x801334DC,8)==bytes.fromhex('806300a44e800020')
 assert all(a in E.LEGENDARY for a,b in ram.writes)
 assert len(calls)==8 # include both cache lines of the eligibility patch; never patch the shared getter
