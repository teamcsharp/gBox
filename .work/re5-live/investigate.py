import os, sys, json, struct, re
from pathlib import Path
os.environ['GHIDRA_INSTALL_DIR']='/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC'
os.environ['JAVA_HOME']='/usr/lib/jvm/java-25-openjdk-arm64'
import pyghidra, httpx
sys.path.insert(0,'/home/ehm_eckx/gBox/system')
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
root=Path('/home/ehm_eckx/gBox/system')
c=httpx.Client(base_url='http://127.0.0.1:8765',headers={'authorization':'Bearer '+(root/'gbox-data/api_token').read_text().strip()})
s=next(s for s in c.get('/api/sessions?include_ended=false').json() if 'Resident Evil 5' in s.get('title',''))
m=ProcMem(s['detail']['pid'],rpcs3_guest_base(s['detail']['pid']))
def u32(a): return struct.unpack('>I',m.rd(a,4))[0]
def code(opd):
    x=u32(opd)
    return x or u32(opd+4)
def dti(opd):
    pc=code(opd); regs={i:0 for i in range(32)}; regs[2]=u32(opd+4) if u32(opd) else u32(opd+12)
    for k in range(20):
        ins=u32(pc+4*k); op=ins>>26; rt=(ins>>21)&31; ra=(ins>>16)&31; imm=ins&65535; imm=imm-65536 if imm&32768 else imm
        if ins==0x4e800020: return regs[3]
        if op==15: regs[rt]=(regs[ra] if ra else 0)+(imm<<16)
        elif op==14: regs[rt]=(regs[ra] if ra else 0)+imm
        elif op==32: regs[rt]=u32((regs[ra] if ra else 0)+imm)
        elif op==24: regs[ra]=regs[rt]|(ins&65535)
        elif op==58:
            if ra != 1: regs[rt]=struct.unpack('>Q',m.rd(regs[ra]+(imm&~3),8))[0]
        elif op==62: pass
        else: return 0
    return 0
tables={}
blob=m.rd(0x01590000,0x90000)
for off in range(0,len(blob)-96,4):
    ptrs=struct.unpack_from('>6I',blob,off)
    if not all(0x01690000<=p<0x01730000 for p in ptrs): continue
    try:
        dt=dti(ptrs[5]); nameptr=u32(dt+4)
        if 0x10000<nameptr<0x1c00000:
            name=m.rd(nameptr,90).split(b'\0')[0].decode('ascii')
            if name.startswith(('uIdStartUp','uWp0a','uWp0A')):
                tables[name]=0x01590000+off
    except Exception: pass
tables.update({n:a for n,a in [('uIdStartUp10',0x15ac988),('uIdStartUp11',0x15ac8c0),('uIdStartUp12',0x15ac7f8),('uIdStartUp13',0x15ac730),('uIdStartUp14',0x15ac668),('uIdStartUp20',0x15acdb0),('uIdStartUp21',0x15acd50),('uIdStartUp22',0x15accf0),('uIdStartUp29',0x15aca50)]})
from gbox.mercs.titles import re5_ps3 as R
gs=u32(u32(R.S_MAIN)+R.MAIN_GAMESYS)
tables['cGameSys']=u32(gs)
tables['sMain']=u32(u32(R.S_MAIN))
print(json.dumps({'tables':{n:hex(v) for n,v in tables.items()}}),flush=True)
image=m.rd(0x10000,0x1bb0000-0x10000)
class Frozen:
    def rd(self,a,n): return image[a-0x10000:a-0x10000+n]
m=Frozen()
base=root/'gbox-data/analysis/re5-live-menu'
out={'tables':tables,'methods':{}}
with pyghidra.open_program(base/'re5-live-01.01.elf',project_location=base,project_name='RE5-live-menu',language='PowerPC:BE:64:64-32addr',nested_project_location=False,analyze=False) as api:
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import TaskMonitor
    from java.math import BigInteger
    p=api.getCurrentProgram(); fm=p.getFunctionManager(); dc=DecompInterface(); dc.openProgram(p)
    def decompile(addr):
        f=fm.getFunctionAt(api.toAddr(addr))
        if f is None: api.disassemble(api.toAddr(addr)); f=api.createFunction(api.toAddr(addr),None)
        if not f:return ''
        p.getProgramContext().setValue(p.getRegister('r2'),f.getBody().getMinAddress(),f.getBody().getMaxAddress(),BigInteger('171c590',16))
        r=dc.decompileFunction(f,30,TaskMonitor.DUMMY)
        return str(r.getDecompiledFunction().getC()) if r.decompileCompleted() else str(r.getErrorMessage())
    for name,table in tables.items():
        if name not in ('sMain','cGameSys','uIdStartUp20','uIdStartUp21','uIdStartUp22','uIdStartUp29','uWp0a'): continue
        rows=[]
        for slot in (range(32) if name in ('cGameSys','sMain') else (6,7,8,9,10,11,12,13,14,15)):
            try:
                addr=code(u32(table+4*slot))
                rows.append({'slot':slot,'address':hex(addr),'c':decompile(addr)})
            except Exception as e: rows.append({'slot':slot,'error':str(e)})
        out['methods'][name]=rows
        (root/'gbox-data/re5-roster-ghidra.json').write_text(json.dumps(out,indent=2))
    out['targets']=[]
    targets=[0x110a1c,0x110a4c,0x110c68,0x610698,0x609dd0,0x9c0abc,0x9c1964,
             0x1426ec,0x1426f8,0x143090,0x14273c,0x142744,0x1426f0,0x9c06ac]
    for a in range(0x9c0000,0x9c3000,4):
        ins=u32(a)
        if ins>>26==36 and ins&65535==0x20:
            for start in range(a,a-3000,-4):
                w=u32(start)
                if w>>26==62 and (w>>21)&31==1 and (w>>16)&31==1:
                    targets.append(start);break
    try:
        tb=u32(u32(0x1714c1c)-0x7e24)
        for state in (0,1,2,3,4,10,11,12,13,14,20,21):
            targets.append((tb+struct.unpack('>i',m.rd(tb+state*4,4))[0])&0xffffffff)
        out['char_switch']={'table':hex(tb),'targets':[hex(x) for x in targets]}
    except Exception as e: out['switch_error']=str(e)
    tb=u32(u32(0x1714c14)-0x7e58)
    for state in (0,2,3,10,11):
        targets.append((tb+struct.unpack('>i',m.rd(tb+state*4,4))[0])&0xffffffff)
    for a in range(0x10000,0x13b0000,4):
        ins=u32(a)
        if ins>>26 == 24 and ins&65535 == 64:
            around=[u32(x) for x in range(a-160,a+320,4)]
            if any((x>>26 == 36 and x&65535 == 0x20) or (x>>26 == 38 and x&65535 == 0x23)
                   or (x>>26==62 and x&65532==0x20) for x in around):
                for start in range(a,a-2500,-4):
                    w=u32(start)
                    if w>>26==62 and (w>>21)&31==1 and (w>>16)&31==1:
                        targets.append(start);break
    for a in targets:
        try: out['targets'].append({'address':hex(a),'c':decompile(a)})
        except Exception as e: out['targets'].append({'address':hex(a),'error':str(e)})
    (root/'gbox-data/re5-roster-ghidra.json').write_text(json.dumps(out,indent=2))
    dc.dispose()
print('Ghidra analysis saved',flush=True)
