import json,time,struct,httpx
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def send(key,down):c.post('/api/sessions/'+sid+'/input',json={'events':[{'key':key,'down':down,'src':'agent'}]}).raise_for_status()
def inspect():
 x=R.snapshot(m);su=R.u32(m,R.S_UNIT);u=R.u32(m,su+R.UNIT_LINES+10*R.LINE_STRIDE+R.LINE_FIRST);out=[]
 for _ in range(300):
  if not R.ptr_ok(u):break
  if R.u32(m,u)==0x162e5f8:out.append([hex(u),m.rd(u+0x1cf9,1).hex(),m.rd(u+0x1de5,1).hex(),struct.unpack('>f',m.rd(u+0x1db4,4))[0],struct.unpack('>3f',m.rd(u+0x30,12))])
  u=R.u32(m,u+R.UNIT_NEXT)
 print(json.dumps({'hp':(x.get('player') or {}).get('hp'),'action':(x.get('player') or {}).get('action'),'inventory':[w for w in x.get('inventory',[]) if w['hand'] or w['id']==0x10a],'prompt':R.selected_prompt(m,include_item_pickups=True),'mines':out}),flush=True)
for key in ('l1','r1','square','ddown'):send(key,False)
send('ddown',True);time.sleep(.4);send('ddown',False);time.sleep(1);inspect()
send('l1',True)
for _ in range(10):time.sleep(.3);inspect()
send('l1',False)
for _ in range(10):time.sleep(.4);inspect()
Path('gbox-data/re5-l1-place.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
