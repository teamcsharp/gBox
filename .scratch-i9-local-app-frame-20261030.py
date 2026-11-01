import json,sys,time,os,hashlib
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx
from gbox.desktop_local import local_config
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
folder=Path(os.environ['APPDATA'])/'gbox-desktop'
for p in folder.glob('client-view-*.json'):
 v=json.loads(p.read_text(encoding='utf-8-sig'));print('view',json.dumps({k:v.get(k) for k in ('origin','at','state','compactBounds')}),flush=True)
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token()},timeout=15) as c:
 w=next(w for w in c.get('/api/workers').json() if w['name']=='i9-NUC' and w['online'])
 with c.stream('GET','/api/workers/'+w['id']+'/desktop/stream?view=app') as r:
  r.raise_for_status();buf=b'';started=time.monotonic()
  for chunk in r.iter_bytes():
   buf+=chunk;a=buf.find(b'\xff\xd8');b=buf.find(b'\xff\xd9',a+2) if a>=0 else -1
   if a>=0 and b>a:
    p=Path('C:/_tools/gBox/.scratch-i9-app-pip-20261030.jpg');p.write_bytes(buf[a:b+2]);print('image',str(p),flush=True);break
   if len(buf)>8_000_000 or time.monotonic()-started>25:raise TimeoutError('No bounded app frame')
