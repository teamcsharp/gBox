import json, sys, time, struct
from pathlib import Path
import httpx
sys.path.insert(0, '/home/ehm_eckx/gBox/system')
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
from gbox.mercs import tactical

root = Path('/home/ehm_eckx/gBox/system')
c = httpx.Client(base_url='http://127.0.0.1:8765', headers={'authorization': 'Bearer ' + (root/'gbox-data/api_token').read_text().strip()}, timeout=20)
sessions = c.get('/api/sessions?include_ended=false').json()
s = next(s for s in sessions if s.get('state') == 'running' and 'Resident Evil 5' in s.get('title', ''))
pid = s['detail']['pid']
m = ProcMem(pid, rpcs3_guest_base(pid))
tracker = tactical.Tracker('BLUS30491')
snap = R.snapshot(m)
frame = tracker.frame(snap, {}, 'playing')
out = {'session': s, 'telemetry': c.get('/api/autoplay/telemetry/'+s['session_id']).json(),
       'screen': R.screen(m), 'snapshot': frame, 'stages': tracker.stages}
dest = root/'gbox-data/re5-live-inspection.json'
dest.write_text(json.dumps(out, indent=2))
print(json.dumps({'session':s['session_id'], 'pid':pid, 'screen':out['screen'],
                 'player':frame.get('player'), 'enemies':len(frame.get('enemies', [])),
                 'mesh_triangles':len(snap['nav'].tris) if snap.get('nav') else None,
                 'telemetry':{k:v for k,v in out['telemetry'].items() if k!='stats'},
                 'stats':{k:out['telemetry'].get('stats',{}).get(k) for k in ('rounds','character','phase','stuck','nav_failed_portals','navigation_log','routes_blocked','kills','score','local_log_errors','navigation_trace_errors')},
                 'tables':{hex(a):m.rd(a,48).hex() for a in (0x015AC5A8,0x015AC608,0x015ACCF0)},
                 'evidence':str(dest)}))
