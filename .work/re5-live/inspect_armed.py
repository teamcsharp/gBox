import json,struct,httpx
from pathlib import Path
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
from gbox.mercs.titles import re5_ps3 as R
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+Path('gbox-data/api_token').read_text().strip()},timeout=30);s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''));m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']));su=R.u32(m,R.S_UNIT);out=[]
for line in range(32):
 u=R.u32(m,su+R.UNIT_LINES+line*R.LINE_STRIDE+R.LINE_FIRST);n=0
 while R.ptr_ok(u) and n<600:
  vt=R.u32(m,u)
  if vt in (0x162e5f8,0x1629db0):
   collider=R.u32(m,u+0x1de8)
   out.append({'ptr':hex(u),'line':line,'vt':hex(vt),'pos':struct.unpack('>3f',m.rd(u+0x30,12)),'placed':m.rd(u+0x1cf9,1).hex(),'detonating':m.rd(u+0x1de5,1).hex(),'arming_s':struct.unpack('>f',m.rd(u+0x1db4,4))[0],'collider':hex(collider),'collision':R.u32(m,collider+0x10) if R.ptr_ok(collider) else None})
  u=R.u32(m,u+R.UNIT_NEXT);n+=1
print(json.dumps(out));Path('gbox-data/re5-armed-mine-inspection.json').write_text(json.dumps(out,indent=2))
