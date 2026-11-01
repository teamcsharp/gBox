import json,sys,struct
from pathlib import Path
sys.path.insert(0,'C:/_tools/gBox/system')
import httpx,psutil
from gbox.desktop_local import local_config
from gbox.citra_memory import attach
from gbox.mercs.titles import merc3d_3ds as M
cfg=local_config('C:/_tools/gBox/system/gbox.toml')
with httpx.Client(base_url='http://127.0.0.1:18765',headers={'Authorization':'Bearer '+cfg.token(),'x-gbox-actor':'agent'},timeout=10) as c:
 s=next(s for s in c.get('/api/sessions?include_ended=false').json() if s.get('game_id')=='0ed22ae742e1b56b' and s.get('state')=='running')
 pid=s['detail']['pid'];born=s['detail']['process_created'];assert psutil.Process(pid).create_time()==born
 m=attach(pid,M.CODE_SIGNATURE,writable=False,wide_ok=False)
 se=M._u32(m,M.S_ENEMY);print('manager',hex(se),M.class_name(m,se),flush=True)
 units={};lists=[]
 for off in range(0,0x400,4):
  node=M._u32(m,se+off)
  if not M.ptr_ok(node):continue
  try:
   vt=M._u32(m,node)
   if vt!=M.EN_NODE_VT:continue
   seen=set();ls=[]
   while M.ptr_ok(node) and node not in seen and len(seen)<64 and M._u32(m,node)==vt:
    seen.add(node);u=M._u32(m,node+M.EN_NODE_UNIT)
    if M.ptr_ok(u):
     key=hex(u);ls.append(key)
     units[key]={'class':M.class_name(m,u),'vt':hex(M._u32(m,u)),'pos':struct.unpack('<3f',m.rd(u+M.P_POS,12)),
       'hp':struct.unpack('<f',m.rd(u+M.P_VIT,4))[0],'hp_max':struct.unpack('<f',m.rd(u+M.P_VIT_MAX,4))[0]}
    node=M._u32(m,node+M.NODE_NEXT)
   lists.append({'off':hex(off),'units':ls})
  except (ValueError,OSError,RuntimeError,struct.error):pass
 assert psutil.Process(pid).create_time()==born
 result={'sid':s['session_id'],'pid':pid,'lists':lists,'units':units}
 Path('C:/_tools/gBox/.scratch-i9-merc3d-enemy-lists-20261030.receipt.json').write_text(json.dumps(result,indent=2))
 print(json.dumps(result),flush=True)
