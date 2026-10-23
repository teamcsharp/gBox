import json,sys,time
from pathlib import Path
import httpx
root=Path('/home/ehm_eckx/gBox/system')
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()},timeout=20)
sessions=c.get('/api/sessions?include_ended=false').json()
s=next(s for s in sessions if 'Resident Evil 5' in s.get('title','') and s.get('state')=='running')
sid=s['session_id'];wid=sid.split('-')[0]
op=sys.argv[1] if len(sys.argv)>1 else 'status'
if op=='status':
    tel=c.get('/api/autoplay/telemetry/'+sid).json()
    jobs=c.get('/api/jobs?limit=40').json()
    print(json.dumps({'session':sid,'telemetry':tel,'autoplay_jobs':[{k:j.get(k) for k in ('id','state','output','error','admission_wait')} for j in jobs if j.get('tool')=='autoplay'][:4]}))
elif op in ('start','stop'):
    r=c.post('/api/jobs',json={'tool':'autoplay','input':{'session_id':sid,'op':op,'mode':'playbook','demo':True},'require_worker':wid})
    print(r.text)
elif op=='frame':
    r=c.get('/api/sessions/'+sid+'/frame.jpg');r.raise_for_status()
    (root/'gbox-data/re5-current-frame.jpg').write_bytes(r.content);print('saved current frame')
elif op=='pad':
    key=sys.argv[2]
    for down in (True,False):
        r=c.post('/api/sessions/'+sid+'/input',json={'events':[{'key':key,'down':down}]})
        r.raise_for_status();time.sleep(.18)
    print('pressed '+key)
