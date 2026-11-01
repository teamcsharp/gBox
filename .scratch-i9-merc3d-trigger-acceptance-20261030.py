import json,math,sys,time
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx,psutil
from gbox.desktop_local import local_config
from gbox.citra_memory import attach
from gbox.mercs.titles import merc3d_3ds as M
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
out=[]
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-actor':'agent'},timeout=8) as c:
 s=next(s for s in c.get('/api/sessions?include_ended=false').json() if s.get('game_id')=='0ed22ae742e1b56b' and s.get('state')=='running')
 pid=s['detail']['pid'];born=s['detail']['process_created'];sid=s['session_id']
 assert psutil.Process(pid).create_time()==born
 m=attach(pid,M.CODE_SIGNATURE,writable=False,wide_ok=False)
 for i in range(100):
  assert psutil.Process(pid).create_time()==born
  snap=M.snapshot(m);p=snap.get('player');row={'at':time.time(),'mission':snap.get('mission_id'),'timer':snap.get('timer'),'score':snap.get('score')}
  stack=M.areas(m);row['native_state']=M.flow_state(m,stack[-1][0])[0] if stack else None
  row['progress']=json.loads(M.PROGRESS_FILE.read_text()) if M.PROGRESS_FILE.exists() else None
  if p:
   row['player']={k:p.get(k) for k in ('pos','rot','hp')}
   es=[]
   for e in snap.get('enemies') or []:
    if (e.get('hp') or 0)<=0:continue
    dx=e['pos'][0]-p['pos'][0];dz=e['pos'][2]-p['pos'][2]
    es.append({'ptr':hex(e['ptr']),'hp':e['hp'],'class':e['class'],'distance':round(math.hypot(dx,dz),1),'yaw_error':round(math.degrees((math.atan2(dx,dz)-p['rot']+math.pi)%(2*math.pi)-math.pi),1)})
   row['enemies']=sorted(es,key=lambda e:e['distance'])[:8]
  if i%10==0:
   t=c.get('/api/autoplay/telemetry/'+sid).json();row['stats']={k:v for k,v in (t.get('stats') or {}).items() if k in ('doing','why','t_aim','t_turn','t_fire','fire_key','fire_key_tried','fire_key_switches','los_blocks','close_shots','point_blank_shots','screen','rounds','trigger_presses','trigger_releases')};print(json.dumps(row),flush=True)
  out.append(row);time.sleep(1)
 Path('C:/_tools/gBox/.scratch-i9-merc3d-trigger-acceptance-20261030.receipt.json').write_text(json.dumps({'sid':sid,'pid':pid,'created':born,'samples':out},indent=2))

