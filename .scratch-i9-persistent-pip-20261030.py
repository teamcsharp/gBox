import json,sys,time
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx
from gbox.desktop_local import local_config
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
p=Path('C:/_tools/gBox/.scratch-i9-persistent-pip-20261030.receipt.json')
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-actor':'agent'},timeout=15) as c:
 if not p.exists():
  r=c.post('/api/mercmode',json={'host':'i9-NUC','command':'start','title':'merc3d','pip':True,'rounds_per_title':5});r.raise_for_status()
  h=next(h for h in r.json()['hosts'] if h['name']=='i9-NUC')
  p.write_text(json.dumps({'at':time.time(),'host':{k:h.get(k) for k in ('id','current_run','dispatch','scheduler_note')}}))
 print(p.read_text(),flush=True)
