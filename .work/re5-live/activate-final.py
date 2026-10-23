import json,sqlite3,subprocess,sys,time
from pathlib import Path
import httpx

root=Path('/home/ehm_eckx/gBox/system')
headers={'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()}
def api(method,path,body=None):
    response=httpx.request(method,'http://127.0.0.1:8765'+path,headers=headers,json=body,timeout=20)
    response.raise_for_status();return response.json()
old=next(s for s in api('GET','/api/sessions?include_ended=false')
         if s.get('state')=='running' and 'Resident Evil 5' in s.get('title',''))
receipt={'previous_session':old['session_id'],'game_id':old['game_id'],'commit':'4cdcc283','repaired':[]}
dest=root/'gbox-data/re5-learning-activation.json'
dest.write_text(json.dumps(receipt,indent=2))
job=api('POST','/api/jobs',{'tool':'autoplay','require_worker':old['session_id'].split('-')[0],
    'input':{'session_id':old['session_id'],'op':'stop'}})
for _ in range(60):
    status=api('GET','/api/jobs/'+job['id'])
    if status['state']=='succeeded':break
    if status['state'] not in ('queued','running'):raise RuntimeError('Autoplay stop failed')
    time.sleep(.5)
else:raise RuntimeError('Autoplay stop timed out')
for _ in range(40):
    telemetry=api('GET','/api/autoplay/telemetry/'+old['session_id'])
    if telemetry.get('running') is False and telemetry.get('age_s',999)<10:break
    time.sleep(.5)
print('Autoplay stopped; activating final fixes and repairing retained round maps',flush=True)
subprocess.run(['sudo','-n','systemctl','stop','gbox.service'],check=True,timeout=60)
try:
    # The old worker and every atlas writer are now stopped, so no active round can be misidentified as an orphan.
    from gbox.mercs.atlas import NavigationAtlas
    atlas_root=root/'gbox-data/mercs/navigation'
    db_path=atlas_root/'BLUS30491/atlas.sqlite'
    backup=root/'gbox-data/deploy-backups'/('atlas-recovery-'+time.strftime('%Y%m%d-%H%M%S',time.gmtime()))
    backup.mkdir(parents=True)
    with sqlite3.connect(db_path) as source,sqlite3.connect(backup/'atlas.sqlite') as target:source.backup(target)
    receipt['atlas_backup']=str(backup)
    notebook=sqlite3.connect(root/'gbox-data/mercs/curriculum/BLUS30491/rounds.sqlite')
    atlas=NavigationAtlas(atlas_root,'BLUS30491')
    try:
        rows=atlas.db.execute('SELECT id,stage,started FROM rounds WHERE outcome IS NULL').fetchall()
        for rid,stage,started in rows:
            if atlas.db.execute('SELECT outcome FROM rounds WHERE id=?',(rid,)).fetchone()[0] is not None:continue
            ended=atlas.db.execute('SELECT MAX(at) FROM samples WHERE round_id=?',(rid,)).fetchone()[0] or started
            prior=notebook.execute('SELECT stage,outcome,data,ts FROM rounds WHERE id=?',(rid.split(':')[0],)).fetchone()
            outcome,metrics='interrupted_unfinalized',{'recovered_from_persisted_observations':True,
                'recovery_reason':'original writer did not finalize; terminal outcome unknown'}
            if prior and prior[0]==stage and prior[3]>=ended:
                outcome=prior[1]
                metrics={k:v for k,v in json.loads(prior[2]).items() if isinstance(v,(str,int,float,bool,type(None)))}
                metrics['recovered_from_notebook_id']=rid.split(':')[0];ended=prior[3]
            atlas.active[rid]={'stage':stage}
            result=atlas.finish(rid,ended,outcome,metrics)
            receipt['repaired'].append({'id':rid,'outcome':outcome,'json':result['json'],'map':result['map']})
    finally:atlas.close();notebook.close()
except Exception as exc:
    receipt['repair_error']=str(exc)
finally:
    dest.write_text(json.dumps(receipt,indent=2))
    subprocess.run(['sudo','-n','systemctl','start','gbox.service'],check=True,timeout=60)
for _ in range(60):
    try:
        worker=next(w for w in api('GET','/api/workers') if w['name']=='lilspark' and w.get('online')
                    and w['id']!=old['session_id'].split('-')[0]);break
    except Exception:time.sleep(1)
else:raise RuntimeError('New Spark worker did not register')
from gbox.config import load
from gbox.store import Store
store=Store(load(root/'gbox.toml').data_dir)
previous=store.get('session',old['session_id']) or old
store.put('session',old['session_id'],previous|{'state':'ended','ended':time.time()})
job=api('POST',f"/api/games/{old['game_id']}/launch?node=lilspark&autoplay=true")
receipt.update(launch_job=job['id'],worker_id=worker['id'])
print('RE5 relaunch queued '+job['id'],flush=True)
for _ in range(180):
    job=api('GET','/api/jobs/'+job['id'])
    if job['state'] not in ('queued','running'):break
    time.sleep(1)
if job['state']!='succeeded':raise RuntimeError('RE5 relaunch failed: '+str(job.get('error')))
new=next(s for s in api('GET','/api/sessions?include_ended=false') if s.get('state')=='running'
         and s.get('game_id')==old['game_id'] and s['session_id'].startswith(worker['id']+'-'))
sid=new['session_id'];receipt.update(session_id=sid,launched=True)
previous=store.get('session',old['session_id']) or old
store.put('session',old['session_id'],previous|{'state':'ended','replaced_by':sid,'ended':time.time()})
dest.write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True)
