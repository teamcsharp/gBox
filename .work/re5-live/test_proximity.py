import json,time,httpx,struct
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
report={'session':sid,'samples':[],'events':[]};started=time.time();last=0;placed_at=None;restored=False;last_kills=0;world_before={};seen=set()
def restore():
 global restored
 j=c.post('/api/jobs',json={'tool':'re5_mods','require_worker':sid.split('-')[0],'input':{'session_id':sid,'op':'mines','multiplier':60,'on':True}}).json();report['restore_job']=j['id'];restored=True;print('Restoring gunplay and 60-second mine cadence',flush=True)
def units():
 su=R.u32(m,R.S_UNIT);out={}
 if not R.ptr_ok(su):return out
 for line in range(32):
  u=R.u32(m,su+R.UNIT_LINES+line*R.LINE_STRIDE+R.LINE_FIRST);n=0
  while R.ptr_ok(u) and n<600:
   if R.u32(m,u)==0x15b44b8:out[u]=struct.unpack('>3f',m.rd(u+0x30,12))
   u=R.u32(m,u+R.UNIT_NEXT);n+=1
 return out
try:
 while time.time()-started<200:
  now=time.time()
  q=R.selected_prompt(m,include_item_pickups=True)
  if q:
   sig=(q.get('label'),q.get('owner'),q.get('target'))
   if sig not in seen:
    seen.add(sig);print('interaction',q,flush=True);report['events'].append({'interaction':q})
  if now-last>=2:
   last=now;t=c.get('/api/autoplay/telemetry/'+sid).json();st=t.get('stats',{});x=R.snapshot(m);inv=x.get('inventory',[]);world=units()
   sample={k:st.get(k) for k in ('screen','character','kills','shots','finishers','mines_placed','mine_refill_verified','mine_pickups_avoided','mine_status','weapon_switch_status','mine_interval_s','mines_only','kill_time_added_s')};sample.update(hand=[w['id'] for w in inv if w['hand']],mine_stacks=[(w['rounds'],w['grid']) for w in inv if w['id']==0x10a],world_mines={hex(p):pos for p,pos in world.items()});print(json.dumps(sample),flush=True);report['samples'].append(sample)
   if (st.get('mines_placed') or 0)>0:placed_at=placed_at or now
   kills=st.get('kills') or 0
   if kills>last_kills and not restored:
    report['events'].append({'kills_without_firearms':kills,'shots':st.get('shots'),'finishers':st.get('finishers'),'mines':st.get('mines_placed'),'disappeared_world_mines':[hex(p) for p in set(world_before)-set(world)]})
    Path('gbox-data/re5-proximity-detonation.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
    if placed_at and not st.get('shots') and not st.get('finishers'):report['mine_only_kills_observed']=kills;restore()
   last_kills=kills;world_before=world
   if placed_at and now-placed_at>50 and not restored:restore()
   if restored and any(w['hand'] and w['item'] in R.re5_weapons.WEAPONS and R.re5_weapons.WEAPONS[w['item']].family in R.re5_weapons.DIRECT for w in inv):
    report['returned_to_gunplay']=True
    if not report.get('gun_at'):report['gun_at']=now
    elif now-report['gun_at']>12:break
  time.sleep(.1)
finally:
 if not restored:restore()
 report['latest']=report['samples'][-1] if report['samples'] else None
 Path('gbox-data/re5-proximity-acceptance.json').write_text(json.dumps(report,indent=2));Path('gbox-data/re5-probe.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content);print('saved proximity acceptance',flush=True)
