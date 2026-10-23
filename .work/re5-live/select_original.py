import json,time,httpx
from pathlib import Path
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30)
s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''))
for inp in ({'op':'mercs_select','mode':'mercenaries','character':'Jill (Battle Suit)','stage':0},{'op':'mines','multiplier':2,'on':True}):
 j=c.post('/api/jobs',json={'tool':'re5_mods','require_worker':s['session_id'].split('-')[0],'input':dict(session_id=s['session_id'],**inp)}).json()
 for _ in range(30):
  if j['state'] not in ('queued','running'):break
  time.sleep(.5);j=c.get('/api/jobs/'+j['id']).json()
 r=j.get('output',{}).get('result',{});print(j['state'],j.get('error'),{k:v for k,v in r.items() if k!='status'})
