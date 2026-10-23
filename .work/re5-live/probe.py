import sys,json,time,struct
from pathlib import Path
import httpx
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30)
s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''))
sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def job(tool,inp):
 j=c.post('/api/jobs',json={'tool':tool,'input':dict(session_id=sid,**inp),'require_worker':sid.split('-')[0]}).json()
 for _ in range(40):
  if j['state'] not in ('queued','running'):break
  time.sleep(.5);j=c.get('/api/jobs/'+j['id']).json()
 print(json.dumps({'job':j['id'],'state':j['state'],'error':j.get('error'),'output':j.get('output')}),flush=True)
op=sys.argv[1] if len(sys.argv)>1 else 'inspect'
if op in ('start','stop'):job('autoplay',{'op':op,'mode':'playbook','demo':True})
elif op=='press':
 for key in sys.argv[2:]:
  for down in (True,False):
   c.post('/api/sessions/'+sid+'/input',json={'events':[{'key':key,'down':down,'src':'agent'}]}).raise_for_status();time.sleep(.10 if key.startswith('d') else .25)
  time.sleep(.5)
elif op=='mod':job('re5_mods',{'op':sys.argv[2],**(json.loads(sys.argv[3]) if len(sys.argv)>3 else {})})
elif op=='unlockplay':
 ui=R.ui_units(m,range(32)); p=ui.get('uIdStartUp01')
 if not p or R.u32(m,p)!=0x15ac5a8:raise ValueError('not in verified Play Game menu')
 gs=R.u32(m,R.u32(m,R.S_MAIN)+R.MAIN_GAMESYS)
 if not R.ptr_ok(gs):raise ValueError('no verified game system')
 mask=R.u32(m,gs+0x20)
 if mask != R.u32(m,p+0x180):raise ValueError('menu availability source changed')
 job('write_memory',{'address':gs+0x20,'hex_bytes':struct.pack('>I',mask|64).hex()})
elif op=='unlocksave':
 toc=R.u32(m,0x1714c1c); save=R.u32(m,R.u32(m,toc-0x7fec))
 index=R.u32(m,save+0x24)
 if not R.ptr_ok(save) or index>3:raise ValueError('invalid save manager')
 print('save',hex(save),'index',index)
 for offset,mask in ((0xa4,0x10),(0x108,0x3ff)):
  address=save+index*0x7eb8+offset
  job('write_memory',{'address':address,'hex_bytes':struct.pack('>I',R.u32(m,address)|mask).hex()})
elif op=='enteroriginal':
 ui=R.ui_units(m,range(32));p=ui.get('uIdStartUp01')
 if not p or R.u32(m,p+0x44)!=6:raise ValueError('not at original Mercenaries entry')
 gs=R.u32(m,R.u32(m,R.S_MAIN)+R.MAIN_GAMESYS)
 addresses=[gs+0x20,p+0x180]
 try:
  for a in addresses:job('freeze_memory',{'address':a,'hex_bytes':struct.pack('>I',R.u32(m,a)|64).hex(),'interval_ms':10})
  for down in (True,False):
   c.post('/api/sessions/'+sid+'/input',json={'events':[{'key':'cross','down':down,'src':'agent'}]});time.sleep(.35)
  time.sleep(1)
 finally:
  for a in addresses:job('freeze_memory',{'address':a,'hex_bytes':'','enabled':False})
ui=R.ui_units(m,range(32));gs=R.u32(m,R.u32(m,R.S_MAIN)+R.MAIN_GAMESYS)
print(json.dumps({'sid':sid,'screen':R.screen(m),'gs':hex(gs),
 'game_fields':{hex(x):R.u32(m,gs+x) for x in (0x58,0x340,0x360,0x364,0x368,0x384)},
 'ui':{n:{hex(x):R.u32(m,p+x) for x in (0x17,0x3c,0x44,0x174,0x178,0x17c,0x180,0x184,0x188)} for n,p in ui.items() if n.startswith('uIdStartUp') or n=='uIdAlert00'}}))
Path('gbox-data/re5-probe.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
