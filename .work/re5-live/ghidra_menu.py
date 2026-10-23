import os, json, sys
from pathlib import Path
os.environ['GHIDRA_INSTALL_DIR'] = '/home/ehm_eckx/reverse/ghidra_12.1.4_PUBLIC'
import pyghidra
sys.path.insert(0, '/home/ehm_eckx/gBox/system')
sys.path.append('/home/ehm_eckx/gBox/system/.venv-linux-aarch64/lib/python3.12/site-packages')
import urllib.request, struct
from gbox.adapters import rpcs3_guest_base
from gbox.mercs_bot import ProcMem
headers={'authorization':'Bearer '+Path('/home/ehm_eckx/gBox/system/gbox-data/api_token').read_text().strip()}
sessions=json.load(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8765/api/sessions?include_ended=false',headers=headers)))
session=next(s for s in sessions if 'Resident Evil 5' in s.get('title','') and s.get('state')=='running')
pid=session['detail']['pid']; guest=ProcMem(pid,rpcs3_guest_base(pid))
base = Path('/home/ehm_eckx/gBox/system/gbox-data/analysis/re5-live-menu')
base.mkdir(parents=True, exist_ok=True)
binary=base/'re5-live-01.01.elf'
if not binary.exists():
    blob=guest.rd(0x10000,0x1bb0000-0x10000)
    ident=b'\x7fELF\x02\x02\x01'+bytes(9)
    header=struct.pack('>16sHHIQQQIHHHHHH',ident,2,21,1,0x10000,64,0,0,64,56,1,0,0,0)
    ph=struct.pack('>IIQQQQQQ',1,7,0x1000,0x10000,0x10000,len(blob),len(blob),0x1000)
    binary.write_bytes((header+ph).ljust(0x1000,b'\0')+blob)
out = {}
with pyghidra.open_program(binary, project_location=base,
                          project_name='RE5-live-menu', language='PowerPC:BE:64:64-32addr',
                          nested_project_location=False, analyze=False) as api:
    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import TaskMonitor
    program = api.getCurrentProgram()
    out['binary'] = {'name':str(program.getName()), 'sha256':str(program.getExecutableSHA256())}
    mem = program.getMemory()
    dec = DecompInterface(); dec.openProgram(program)
    fm = program.getFunctionManager()
    for label, table in [('play_menu',0x015AC5A8),('main_menu',0x015AC608),('reunion_char',0x015ACCF0)]:
        rows=[]
        for i in range(24):
            try:
                opd = struct.unpack('>I',guest.rd(table+4*i,4))[0]
                descriptor = guest.rd(opd,16)
                code = struct.unpack('>I',descriptor[:4])[0] or struct.unpack('>I',descriptor[4:8])[0]
                f = fm.getFunctionAt(api.toAddr(code))
                if f is None and 0x10000 <= code < 0x13b0000:
                    api.disassemble(api.toAddr(code))
                    f=api.createFunction(api.toAddr(code),None)
                if f:
                    from java.math import BigInteger
                    context=program.getProgramContext()
                    context.setValue(program.getRegister('r2'),f.getBody().getMinAddress(),f.getBody().getMaxAddress(),BigInteger('171c590',16))
                if f:
                    result=dec.decompileFunction(f,30,TaskMonitor.DUMMY)
                    rows.append({'slot':i, 'code':hex(code), 'decompiled':str(result.getDecompiledFunction().getC()) if result.decompileCompleted() else str(result.getErrorMessage())})
                else:
                    rows.append({'slot':i,'code':hex(code),'descriptor':descriptor.hex(),'missing_function':True})
            except Exception as exc:
                rows.append({'slot':i,'error':str(exc)[:100]})
        out[label]=rows
    out['targets']=[]
    for code in (0x605088,0x600a38,0x54bad0,0x54c2cc):
        f=fm.getFunctionAt(api.toAddr(code))
        if f is None:
            api.disassemble(api.toAddr(code)); f=api.createFunction(api.toAddr(code),None)
        if f:
            context.setValue(program.getRegister('r2'),f.getBody().getMinAddress(),f.getBody().getMaxAddress(),BigInteger('171c590',16))
            result=dec.decompileFunction(f,30,TaskMonitor.DUMMY)
            out['targets'].append({'code':hex(code),'decompiled':str(result.getDecompiledFunction().getC()) if result.decompileCompleted() else str(result.getErrorMessage())})
    dec.dispose()
Path('/home/ehm_eckx/gBox/system/gbox-data/re5-menu-ghidra.json').write_text(json.dumps(out,indent=2))
print(json.dumps({'binary':out['binary'], 'methods':{k:len(v) for k,v in out.items() if isinstance(v,list)}}))
