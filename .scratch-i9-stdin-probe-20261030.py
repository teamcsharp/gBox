import os,sys,threading,ctypes,msvcrt,time,subprocess,json
from ctypes import wintypes
sys.path.insert(0,'C:/_tools/gBox/system')
from gbox.node_rebuild import _spawn_command
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.GetStdHandle.argtypes=[wintypes.DWORD];k.GetStdHandle.restype=wintypes.HANDLE
k.SetStdHandle.argtypes=[wintypes.DWORD,wintypes.HANDLE];k.SetStdHandle.restype=wintypes.BOOL
old=k.GetStdHandle(-10 & 0xffffffff)
r,w=os.pipe();assert k.SetStdHandle(-10 & 0xffffffff,msvcrt.get_osfhandle(r))
entered=threading.Event()
def read():
 entered.set();os.read(r,1)
reader=threading.Thread(target=read,daemon=True);reader.start();entered.wait();time.sleep(.1)
try:
 for mode in ('inherited','devnull'):
  start=time.monotonic();kwargs={} if mode=='inherited' else {'stdin':subprocess.DEVNULL}
  p,stop=_spawn_command([sys.executable,'-I','-c','print(123,flush=True)'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW,**kwargs)
  try:
   out=p.communicate(timeout=3)[0];print(json.dumps({'mode':mode,'rc':p.returncode,'seconds':time.monotonic()-start,'out':out}),flush=True)
  except subprocess.TimeoutExpired:print(json.dumps({'mode':mode,'timed_out':True}),flush=True)
  finally:stop();p.communicate(timeout=3)
finally:
 k.SetStdHandle(-10 & 0xffffffff,old);os.write(w,b'x');reader.join(2);os.close(r);os.close(w)
