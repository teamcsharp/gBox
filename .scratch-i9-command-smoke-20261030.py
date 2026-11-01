import sys,subprocess,time,json,os
sys.path.insert(0,'C:/_tools/gBox/system')
from gbox.node_rebuild import _spawn_command,scrubbed_env
os.environ['PYTHONPATH']='C:/_tools/gBox/system'
commands=[[sys.executable,'-c','print(123,flush=True)'],[sys.executable,'-m','pip','--version'],['git','-C','C:/_tools/gBox','status','--porcelain','-uno']]
for cmd in commands:
 for mode in ('normal','job'):
  at=time.monotonic();p=None;stop=lambda:None
  try:
   kw=dict(cwd='C:/_tools/gBox/system',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=scrubbed_env(),text=True,creationflags=subprocess.CREATE_NO_WINDOW)
   if mode=='normal':p=subprocess.Popen(cmd,**kw);stop=p.kill
   else:p,stop=_spawn_command(cmd,**kw)
   out=p.communicate(timeout=8)[0]
   print(json.dumps({'mode':mode,'cmd':cmd,'rc':p.returncode,'seconds':round(time.monotonic()-at,2),'out':out[-1500:]}),flush=True)
  except Exception as e:print(json.dumps({'mode':mode,'cmd':cmd,'error':type(e).__name__,'seconds':round(time.monotonic()-at,2)}),flush=True)
  finally:
   if p is not None:
    stop()
    try:p.communicate(timeout=2)
    except Exception:pass
