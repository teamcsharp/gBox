import json,time,struct,subprocess,httpx
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def send(key,down):subprocess.run(['xdotool','keydown' if down else 'keyup',key],env={'DISPLAY':':90'},check=True)
def inspect():
 x=R.snapshot(m);su=R.u32(m,R.S_UNIT);out=[]
 for line in range(32):
  u=R.u32(m,su+R.UNIT_LINES+line*R.LINE_STRIDE+R.LINE_FIRST)
  for _ in range(300):
   if not R.ptr_ok(u):break
   if R.u32(m,u)==0x162e5f8:out.append([hex(u),m.rd(u+0x1cf9,1).hex(),m.rd(u+0x1de5,1).hex(),struct.unpack('>f',m.rd(u+0x1db4,4))[0],struct.unpack('>3f',m.rd(u+0x30,12))])
   u=R.u32(m,u+R.UNIT_NEXT)
 print(json.dumps({'timer':x.get('timer'),'hp':(x.get('player') or {}).get('hp'),'action':(x.get('player') or {}).get('action'),'inventory':[w for w in x.get('inventory',[]) if w['hand'] or w['id']==0x10a],'prompt':R.selected_prompt(m,include_item_pickups=True),'mines':out}),flush=True)
for key in ('q','e','z','Down'):send(key,False)
print('before',flush=True);inspect()
send('Down',True);time.sleep(.5);send('Down',False);time.sleep(1.2);inspect()
send('q',True)
for _ in range(8):time.sleep(.4);inspect()
send('q',False)
for _ in range(8):time.sleep(.5);inspect()
Path('gbox-data/re5-l1-place.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
