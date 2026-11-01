import json,sys,time,os
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import psutil,httpx
from gbox.desktop_local import local_config
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token()},timeout=10) as c:
 r=c.get('/api/jobs');r.raise_for_status();rows=r.json()
 if isinstance(rows,dict):rows=rows.get('jobs',[])
 jobs=[j for j in rows if j.get('tool')=='rebuild_node' and (j.get('origin') or {}).get('desktop_admin',{}).get('job_id')=='a9ca2b83b9284b5e']
 print('matching_jobs',json.dumps([{k:j.get(k) for k in ('id','state','cancel')} for j in jobs]),flush=True)
 assert len(jobs)==1
 j=jobs[0]
 if j['state']=='running':
  r=c.post('/api/jobs/'+j['id']+'/cancel');r.raise_for_status()
  p=psutil.Process(12300)
  assert p.ppid()==62160 and abs(p.create_time()-1793350706.516010)<.1
  assert p.cmdline()[1:4]==['-m','pip','install']
  assert psutil.Process(62160).ppid()==65152
  p.terminate();p.wait(timeout=10)
  print('terminated_exact_cancelled_pip',12300,flush=True)
 settings=json.loads((Path(os.environ['APPDATA'])/'gbox-desktop/settings.json').read_text(encoding='utf-8-sig'))
 if settings.get('token'):
  assert settings['apiUrl'].rstrip('/')=='http://10.89.1.246:8765'
  r=c.post('/api/desktop-local/bridge',json={'remote_url':settings['apiUrl'],'token':settings['token']});r.raise_for_status()
  print('pairing',r.json().get('admin_pairing'),flush=True)
 else:print('pairing_requires_desktop_refresh',flush=True)
