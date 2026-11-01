import json,os,sys,time
import psutil
print('interpreter',sys.executable,flush=True)
for p in psutil.process_iter(['pid','ppid','name','exe']):
    if p.info['name'].lower() not in ('python.exe','pythonw.exe','gbox.exe','retroarch.exe'):continue
    try:
        cmd=p.cmdline()
        if 'gbox' not in ' '.join(cmd).lower() and p.ppid() not in (65152,62160):continue
        from pathlib import Path
        sys.path.insert(0,'C:/_tools/gBox/system')
        from gbox.node_rebuild import redact
        print(json.dumps({**p.info,'cmd':redact(' '.join(cmd)), 'cwd':p.cwd(),'env':{k:v for k,v in p.environ().items() if k.startswith('PYTHON') or k in ('GBOX_CONFIG','VIRTUAL_ENV','HOME','USERPROFILE')},'connections':[{'remote':str(c.raddr),'status':c.status} for c in p.net_connections()]}),flush=True)
    except Exception as e:print('error',p.pid,type(e).__name__,str(e),flush=True)
