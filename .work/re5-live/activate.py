import json, subprocess, sys, time
from pathlib import Path
import httpx

root=Path('/home/ehm_eckx/gBox/system')
headers={'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()}
def api(method,path,body=None):
    r=httpx.request(method,'http://127.0.0.1:8765'+path,headers=headers,json=body,timeout=20)
    r.raise_for_status(); return r.json()

old=next(s for s in api('GET','/api/sessions?include_ended=false') if s.get('state')=='running' and 'Resident Evil 5' in s.get('title',''))
receipt={'previous_session':old['session_id'],'game_id':old['game_id'],'deployment':'re5-navigation'}
dest=root/'gbox-data/re5-navigation-activation.json'
dest.write_text(json.dumps(receipt,indent=2))
print('Restarting service to activate deployed code; RE5 will be relaunched',flush=True)
subprocess.run(['sudo','-n','systemctl','restart','gbox.service'],check=True,timeout=60)
for _ in range(60):
    try:
        workers=api('GET','/api/workers')
        worker=next(w for w in workers if w['name']=='lilspark' and w.get('online'))
        if worker['id'] != old['session_id'].split('-')[0]:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise RuntimeError('New Spark worker did not register')
print('New Spark worker registered: '+worker['id'],flush=True)
# Older sessions have lost their emulator in the controlled service restart. Mark the old watched RE5 as ended
# so its heartbeat cannot prevent relaunching the same game on the new worker.
sys.path.insert(0,str(root))
from gbox.config import load
from gbox.store import Store
cfg=load(root/'gbox.toml'); store=Store(cfg.data_dir)
previous=store.get('session',old['session_id']) or old
store.put('session',old['session_id'],previous|{'state':'ended','ended':time.time()})
job=api('POST',f"/api/games/{old['game_id']}/launch?node=lilspark&autoplay=true")
receipt['launch_job']=job['id'];receipt['worker_id']=worker['id'];dest.write_text(json.dumps(receipt,indent=2))
print('RE5 launch queued: '+job['id'],flush=True)
for _ in range(180):
    job=api('GET','/api/jobs/'+job['id'])
    if job['state'] not in ('queued','running'):
        break
    time.sleep(1)
if job['state']!='succeeded':
    raise RuntimeError(json.dumps({k:job.get(k) for k in ('id','state','error','admission_wait')}))
sessions=api('GET','/api/sessions?include_ended=false')
new=next(s for s in sessions if s.get('state')=='running' and s.get('game_id')==old['game_id'] and s['session_id'].startswith(worker['id']+'-'))
sid=new['session_id'];receipt['session_id']=sid
previous=store.get('session',old['session_id']) or old
store.put('session',old['session_id'],previous|{'state':'ended','replaced_by':sid,'ended':time.time()})
receipt['launched']=True;dest.write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt),flush=True)
