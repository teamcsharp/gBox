import sqlite3,json,sys
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
from gbox.desktop_local import local_config
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
db=sqlite3.connect((cfg.data_dir/'gbox.sqlite3').as_uri()+'?mode=ro',uri=True)
for kind in ('autoplay_screensaver_run','autoplay_screensaver_log','slabel'):
 rows=db.execute('select id,body from docs where kind=? order by rowid desc limit 12',(kind,)).fetchall()
 for key,raw in rows:
  v=json.loads(raw)
  if kind=='slabel' and key!='3f1fe9e383e84ed3-112a70229ad0428e':continue
  print(kind,key,json.dumps(v)[:5000],flush=True)
for jid in ('112a70229ad0428e','8158c0fef3a04066'):
 row=db.execute('select body from docs where kind=? and id=?',('job',jid)).fetchone()
 if row:
  j=json.loads(row[0]);print('job',json.dumps({k:j.get(k) for k in ('id','tool','actor','agent_use','origin','state','input','error','worker_id','require_worker')}),flush=True)
