import hashlib,json,sys,time
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx
from gbox.desktop_local import local_config
from gbox.mercs.titles.merc3d_3ds import PROGRESS_FILE
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
result={'started':time.time(),'samples':[]}
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-actor':'agent'},timeout=12) as c:
 tested=False
 for _ in range(6):
  r=c.get('/api/mercmode');r.raise_for_status()
  h=next(h for h in r.json()['hosts'] if h['name']=='i9-NUC');run=h.get('current_run') or {};sid=run.get('session_id')
  t=c.get('/api/autoplay/telemetry/'+sid).json() if sid else {};st=t.get('stats') or {}
  row={'at':time.time(),'sid':sid,'phase':run.get('phase'),'handover':run.get('handover'),'rounds':run.get('mercmode_rounds',0),
   'running':t.get('running'),'age_s':t.get('age_s'),'stats':{k:st.get(k) for k in ('screen','stage','mission_id','operator_control','operator_takeovers','round_evidence_id','timer')},
   'progress':json.loads(PROGRESS_FILE.read_text()) if PROGRESS_FILE.exists() else None}
  result['samples'].append(row);print(json.dumps(row),flush=True)
  if not tested and run.get('phase')=='playing' and t.get('running') is True:
   r=c.post('/api/autoplay-screensaver/yield',json={'session_id':sid,'reason':'mouse'});r.raise_for_status()
   result['legacy_mouse_report']={'synthetic_test':True,'at':time.time(),'sid':sid,'response':r.json()}
   assert r.json().get('yielded') is False, 'Desktop activity relinquished MercMode'
   tested=True
  time.sleep(8)
result['ended']=time.time()
for rel in ('gbox/tools.py','gbox/screensaver.py','gbox/mercs/titles/merc3d_3ds.py','clients/desktop/index.html'):
 result.setdefault('source_sha256',{})[rel]=hashlib.sha256((Path('C:/_tools/gBox/system')/rel).read_bytes()).hexdigest()
Path('C:/_tools/gBox/.scratch-i9-perpetual-acceptance-20261030.receipt.json').write_text(json.dumps(result,indent=2))
assert tested and result['samples'][-1]['phase']=='playing' and not result['samples'][-1]['handover'], 'No sustained scheduler-owned gameplay'
