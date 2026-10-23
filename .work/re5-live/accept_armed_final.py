import json,time,httpx
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
from gbox.mercs.titles.re5_mines import ground_mines
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']));receipt={'sid':sid,'samples':[]};start=time.time();confirmed=None;restored=False

def restore():
 j=c.post('/api/jobs',json={'tool':'re5_mods','require_worker':sid.split('-')[0],'input':{'session_id':sid,'op':'mines','multiplier':60,'on':True}}).json();receipt['restore_job']=j['id'];print('restore60',j['id'],flush=True)
try:
 for i in range(1800):
  tel=c.get('/api/autoplay/telemetry/'+sid).json();st=tel.get('stats',{});x=R.snapshot(m);g=ground_mines(m)
  row={'seconds':round(time.time()-start,1),'screen':R.own_screen(x),'hp':(x.get('player') or {}).get('hp'),'kills':x.get('kills'),'ground':g,'held':[w['id'] for w in x.get('inventory',[]) if w['hand']], 'mine_stacks':[w for w in x.get('inventory',[]) if w['id']==0x10a], 'request':R.selected_prompt(m,include_item_pickups=True),'stats':{k:v for k,v in st.items() if k.startswith('mine') or k in ('shots','weapon','rounds','menu_last','screen','character','stage','kill_time_seconds_added','kill_time_s')}}
  receipt['samples'].append(row)
  if i%30==0 or g:print(json.dumps(row),flush=True)
  if st.get('mines_placed',0)>0 and confirmed is None:
   confirmed=time.time();restore();restored=True
  if confirmed and time.time()-confirmed>40:break
  if time.time()-start>300:break
  time.sleep(.15)
finally:
 if not restored:restore()
 Path('gbox-data/re5-armed-proximity-acceptance.json').write_text(json.dumps(receipt,indent=2))
 print('saved acceptance; samples',len(receipt['samples']),flush=True)

