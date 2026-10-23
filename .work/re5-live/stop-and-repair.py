import json,sqlite3,time
from pathlib import Path
import httpx
from gbox.mercs.atlas import NavigationAtlas

root=Path('/home/ehm_eckx/gBox/system')
client=httpx.Client(base_url='http://127.0.0.1:8765',headers={
    'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()},timeout=20)
def api(method,path,body=None):
    response=client.request(method,path,json=body)
    response.raise_for_status()
    return response.json()
session=next(s for s in api('GET','/api/sessions?include_ended=false')
             if 'Resident Evil 5' in s.get('title','') and s.get('state')=='running')
sid=session['session_id']
job=api('POST','/api/jobs',{'tool':'autoplay','require_worker':sid.split('-')[0],
    'input':{'session_id':sid,'op':'stop'}})
deadline=time.monotonic()+40
while time.monotonic()<deadline:
    status=api('GET','/api/jobs/'+job['id'])
    if status['state']=='succeeded':break
    if status['state'] not in ('queued','running'):raise RuntimeError('Autoplay stop failed')
    time.sleep(.5)
else:raise RuntimeError('Autoplay stop did not finish')
deadline=time.monotonic()+30
while time.monotonic()<deadline:
    telemetry=api('GET','/api/autoplay/telemetry/'+sid)
    if telemetry.get('running') is False and telemetry.get('age_s',999)<10:break
    time.sleep(.5)
else:raise RuntimeError('No fresh stopped-bot acknowledgement; repair refused')
print('Autoplay stopped and released input; repairing retained evidence',flush=True)
atlas_root=root/'gbox-data/mercs/navigation'
db_path=atlas_root/'BLUS30491/atlas.sqlite'
stamp=time.strftime('%Y%m%d-%H%M%S',time.gmtime())
backup=root/'gbox-data/deploy-backups'/('atlas-recovery-'+stamp)
backup.mkdir(parents=True)
with sqlite3.connect(db_path) as source,sqlite3.connect(backup/'atlas.sqlite') as target:
    source.backup(target)
notebook=sqlite3.connect(root/'gbox-data/mercs/curriculum/BLUS30491/rounds.sqlite')
atlas=NavigationAtlas(atlas_root,'BLUS30491')
receipt={'session':sid,'backup':str(backup),'repaired':[]}
try:
    rows=atlas.db.execute('SELECT id,stage,started FROM rounds WHERE outcome IS NULL').fetchall()
    for rid,stage,started in rows:
        if atlas.db.execute('SELECT outcome FROM rounds WHERE id=?',(rid,)).fetchone()[0] is not None:continue
        last=atlas.db.execute('SELECT MAX(at) FROM samples WHERE round_id=?',(rid,)).fetchone()[0] or started
        prior=notebook.execute('SELECT stage,outcome,data,ts FROM rounds WHERE id=?',(rid.split(':')[0],)).fetchone()
        outcome,metrics='interrupted_unfinalized',{'recovered_from_persisted_observations':True,
            'recovery_reason':'original atlas writer did not finalize; no terminal outcome inferred'}
        if prior and prior[0]==stage and prior[3]>=last:
            outcome=prior[1]
            metrics={k:v for k,v in json.loads(prior[2]).items() if isinstance(v,(str,int,float,bool,type(None)))}
            metrics['recovered_from_notebook_id']=rid.split(':')[0]
            last=prior[3]
        atlas.active[rid]={'stage':stage}
        result=atlas.finish(rid,last,outcome,metrics)
        receipt['repaired'].append({'id':rid,'outcome':outcome,'json':result['json'],'map':result['map']})
finally:
    atlas.close();notebook.close()
(root/'gbox-data/re5-atlas-recovery.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt),flush=True)
