import json,sys,subprocess,time,os
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx,psutil
from gbox.desktop_local import local_config
from gbox.node_rebuild import redact
from gbox.desktop_supervisor import directory
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token()},timeout=10) as c:
 for route in ('/api/workers','/api/sessions','/api/mercmode'):
  r=c.get(route);r.raise_for_status();v=r.json()
  if route=='/api/workers':v=[{k:w.get(k) for k in ('id','name','online')} for w in v]
  if route=='/api/sessions':
   v=[{k:s.get(k) for k in ('session_id','state','title','agent_owned','autoplay','detail')} for s in v if s.get('state')=='running']
   for s in v:
    t=c.get('/api/autoplay/telemetry/'+s['session_id']).json();s['telemetry']={k:x for k,x in t.items() if k!='stats'};s['stats']={k:x for k,x in (t.get('stats') or {}).items() if k in ('screen','rounds','round_evidence_id','operator_control','stop_reason','status','mission','mercmode_rotate_requested','mercmode_boundaries_delivered')}
    s['detail']={k:s['detail'].get(k) for k in ('pid','process_created','worker_name','local_window')}
  if route=='/api/mercmode':
   v={'hosts':[{k:x for k,x in h.items() if k not in ('titles','preparation','desired_settings')} for h in v.get('hosts',[]) if h.get('name')=='i9-NUC']}
  print(route,json.dumps(v)[:6500],flush=True)
print('git',subprocess.run(['git','-C','C:/_tools/gBox','rev-parse','HEAD'],capture_output=True,text=True,timeout=10).stdout.strip(),flush=True)
print('recovery_dir',str(directory(cfg)),flush=True)
for p in psutil.process_iter(['pid','ppid','name']):
 if p.pid not in (12300,62160,65152):continue
 try:print('network_env',p.pid,json.dumps({k:redact(v) for k,v in p.environ().items() if 'PROXY' in k.upper() or k.startswith(('PIP_','UV_','GIT_'))}),flush=True)
 except Exception as e:print(type(e).__name__,flush=True)
