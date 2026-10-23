import os,sys,json,struct
from pathlib import Path
os.environ['GHIDRA_INSTALL_DIR']='/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC'
os.environ['JAVA_HOME']='/usr/lib/jvm/java-25-openjdk-arm64'
import pyghidra
base=Path('/home/ehm_eckx/gBox/system/gbox-data/analysis/re5-live-menu')
blob=(base/'re5-live-01.01.elf').read_bytes()[0x1000:]
u=lambda a:struct.unpack_from('>I',blob,a-0x10000)[0]
targets=set(int(a,0) for a in sys.argv[1:] if a not in ('scan','saveflags'))
if 'saveflags' in sys.argv:
 for a in range(0x10000,0x13b0000,4):
  if u(a)>>26==7 and u(a)&65535==0x7eb8:
   for start in range(a-4,a-2000,-4):
    x=u(start)
    if x==0x4e800020:targets.add(start+4);break
    if x>>26==62 and (x>>21)&31==1 and (x>>16)&31==1:targets.add(start);break
if 'scan' in sys.argv:
 for a in range(0xb0000,0x110000,4):
  w=u(a)
  if (w>>26==36 and w&65535==0x20) or (w>>26==38 and w&65535==0x23):
   for start in range(a,a-3500,-4):
    x=u(start)
    if x>>26==62 and (x>>21)&31==1 and (x>>16)&31==1:
     targets.add(start);break
print('targets',len(targets),flush=True)
out=[]
with pyghidra.open_program(base/'re5-live-01.01.elf',project_location=base,project_name='RE5-live-menu',language='PowerPC:BE:64:64-32addr',nested_project_location=False,analyze=False) as api:
 from ghidra.app.decompiler import DecompInterface
 from ghidra.util.task import TaskMonitor
 from java.math import BigInteger
 p=api.getCurrentProgram();fm=p.getFunctionManager();dc=DecompInterface();dc.openProgram(p)
 for a in sorted(targets):
  f=fm.getFunctionAt(api.toAddr(a))
  if f is None:api.disassemble(api.toAddr(a));f=api.createFunction(api.toAddr(a),None)
  if f:
   p.getProgramContext().setValue(p.getRegister('r2'),f.getBody().getMinAddress(),f.getBody().getMaxAddress(),BigInteger('171c590',16))
   r=dc.decompileFunction(f,15,TaskMonitor.DUMMY)
   out.append({'address':hex(a),'c':str(r.getDecompiledFunction().getC()) if r.decompileCompleted() else str(r.getErrorMessage())})
 dc.dispose()
Path('/home/ehm_eckx/gBox/system/gbox-data/re5-query-ghidra.json').write_text(json.dumps(out))
print('saved',len(out),flush=True)
