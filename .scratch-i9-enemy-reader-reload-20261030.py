import json,sys,time
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx
from gbox.desktop_local import local_config
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
p=Path('C:/_tools/gBox/.scratch-i9-enemy-reader-reload-20261030.receipt.json')
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-actor':'agent'},timeout=12) as c:
 if p.exists():receipt=json.loads(p.read_text())
 else:
  r=c.post('/api/workers/i9-NUC/bot-reload',json={'modules':['gbox.mercs.titles.merc3d_3ds'],'settle_s':5,'wait_s':0});r.raise_for_status()
  receipt=r.json();p.write_text(json.dumps(receipt));print('submitted',json.dumps(receipt),flush=True)
 for _ in range(6):
  r=c.get('/api/jobs/'+receipt['job_id']);r.raise_for_status();job=r.json()
  print(json.dumps({k:job.get(k) for k in ('id','state','error','output')}),flush=True)
  if job.get('state') in ('succeeded','failed','rejected','cancelled','invalid'):
   receipt['job']=job;p.write_text(json.dumps(receipt,indent=2));break
  time.sleep(6)
