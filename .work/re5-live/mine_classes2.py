import os, sys, json, struct, re
from pathlib import Path
os.environ['GHIDRA_INSTALL_DIR']='/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC'
os.environ['JAVA_HOME']='/usr/lib/jvm/java-25-openjdk-arm64'
import pyghidra, httpx
sys.path.insert(0,'/home/ehm_eckx/gBox/system')
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
root=Path('/home/ehm_eckx/gBox/system')
c=httpx.Client(timeout=30,base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()})
s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''))
m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def u32(a): return struct.unpack('>I',m.rd(a,4))[0]
def code(opd):
    x=u32(opd)
    return x or u32(opd+4)
def dti(opd):
    pc=code(opd); regs={i:0 for i in range(32)}; regs[2]=u32(opd+4) if u32(opd) else u32(opd+12)
    for k in range(40):
        ins=u32(pc+4*k); op=ins>>26; rt=(ins>>21)&31; ra=(ins>>16)&31; imm=ins&65535; imm=imm-65536 if imm&32768 else imm
        if ins==0x4e800020: return regs[3]
        if op==15: regs[rt]=(regs[ra] if ra else 0)+(imm<<16)
        elif op==14: regs[rt]=(regs[ra] if ra else 0)+imm
        elif op==32: regs[rt]=u32((regs[ra] if ra else 0)+imm)
        elif op==24: regs[ra]=regs[rt]|(ins&65535)
        elif op==58:
            if ra != 1: regs[rt]=struct.unpack('>Q',m.rd(regs[ra]+(imm&~3),8))[0]
        elif op==62: pass
        elif op == 31 and ((ins >> 1) & 1023) == 444: regs[ra] = regs[rt] | regs[(ins >> 11) & 31]
        elif op in (31,36,37): pass
        else: return 0
    return 0
from gbox.mercs.titles import re5_ps3 as R
blob=m.rd(0x01590000,0xc0000);tables={}
for off in range(0,len(blob)-96,4):
 ptrs=struct.unpack_from('>6I',blob,off)
 if not all(0x01690000<=p<0x01730000 for p in ptrs):continue
 try:
  dt=dti(ptrs[5]);np=u32(dt+4)
  if not 0x10000<np<0x1c00000:continue
  name=m.rd(np,90).split(b'\0')[0].decode('ascii')
  if any(x in name.lower() for x in ('bomb','mine','wp0a','omitem')):tables[name]=hex(0x1590000+off)
 except Exception:pass
print('classes',tables);print('prompt',R.selected_prompt(m));x=R.snapshot(m);print('inventory',x.get('inventory'))
j=c.post('/api/jobs',json={'tool':'re5_mods','require_worker':s['session_id'].split('-')[0],'agent_use':False,'input':{'session_id':s['session_id'],'op':'kill_time','multiplier':10,'on':True}}).json();print('kill_time_job',j['id'])
Path('gbox-data/re5-mine-classes.json').write_text(json.dumps(tables))



