import json,time,httpx,struct
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));sid=s['session_id'];m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
report={'session':sid,'observations':[]};end=time.time()+160;last=0;restored=False;success_at=None;seen=set()
while time.time()<end:
 now=time.time()
 try:
  ab=R.u32(m,R.S_ACTION)
  if R.ptr_ok(ab):
   for ofs in R.QTE_UNITS:
    raw=m.rd(ab+ofs,28);btn=struct.unpack_from('>I',raw,12)[0]
    if raw[4] and raw[5] and R.ptr_ok(btn):
     b=m.rd(btn,116);target=struct.unpack_from('>I',b,64)[0];vt=R.u32(m,target) if R.ptr_ok(target) else 0
     item={'vt':hex(vt),'kind':struct.unpack_from('>I',b,20)[0],'mode':struct.unpack_from('>I',b,24)[0],'label':struct.unpack_from('>I',b,36)[0]};sig=tuple(item.values())
     if sig not in seen:
      seen.add(sig);report['observations'].append(item);print('interaction',json.dumps(item),flush=True)
  if now-last>=4:
   last=now;t=c.get('/api/autoplay/telemetry/'+sid).json();st=t.get('stats',{});sp=R.u32(m,R.S_PLAYER);p=R.u32(m,sp+0x28) if R.ptr_ok(sp) else 0;inv=R.inventory(m,p) if R.ptr_ok(p) else []
   status={k:st.get(k) for k in ('screen','character','kills','mine_status','mines_placed','mine_refill_verified','mine_pickups_avoided','weapon_switch_status','kill_time_added_s')};status['hand']=[w['id'] for w in inv if w['hand']];status['mine_stacks']=[(w['rounds'],w['grid']) for w in inv if w['id']==0x10a];print(json.dumps(status),flush=True);report['latest']=status
   if (st.get('mines_placed') or 0)>0 and not restored:
    j=c.post('/api/jobs',json={'tool':'re5_mods','require_worker':sid.split('-')[0],'input':{'session_id':sid,'op':'mines','multiplier':60,'on':True}}).json();report['default_cadence_job']=j['id'];restored=True;print('Restoring 60-second cadence',flush=True)
   if restored and any(w['hand'] and w['item'] in R.re5_weapons.WEAPONS and R.re5_weapons.WEAPONS[w['item']].family in R.re5_weapons.DIRECT for w in inv):
    success_at=success_at or now
    if now-success_at>12:report['verified_place_then_gun']=True;break
 except Exception as e:print(type(e).__name__,str(e)[:160],flush=True)
 time.sleep(.15)
Path('gbox-data/re5-mine-live-acceptance.json').write_text(json.dumps(report,indent=2));print('saved acceptance',json.dumps({k:v for k,v in report.items() if k!='observations'}),flush=True)
Path('gbox-data/re5-probe.jpg').write_bytes(c.get('/api/sessions/'+sid+'/frame.jpg').content)
