import json,time,httpx
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def send(key,down):c.post('/api/sessions/'+sid+'/input',json={'events':[{'key':key,'down':down,'src':'agent'}]}).raise_for_status()
print('before',[w for w in R.snapshot(m).get('inventory',[]) if w['id']==0x10a],flush=True)
send('l1',True);time.sleep(.35);send('r1',True);time.sleep(.3);send('r1',False);send('l1',False)
for _ in range(12):
 q=R.selected_prompt(m)
 print('prompt',q,'target_vtable',hex(R.u32(m,q['target'])) if q and R.ptr_ok(q['target']) else None,flush=True)
 if q:
  Path('gbox-data/re5-mine-pickup-request.json').write_text(json.dumps({'request':q,'vtable':hex(R.u32(m,q['target'])),'target':m.rd(q['target'],512).hex()}))
 time.sleep(.25)
print('after',[w for w in R.snapshot(m).get('inventory',[]) if w['id']==0x10a],flush=True);Path('gbox-data/re5-probe.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
