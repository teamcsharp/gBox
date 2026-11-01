import ctypes,json,psutil
from pathlib import Path
from ctypes import wintypes as w
u=ctypes.WinDLL('user32',use_last_error=True)
u.GetParent.argtypes=[w.HWND];u.GetParent.restype=w.HWND
u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
u.GetWindowRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
u.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int];u.GetWindowLongW.restype=w.LONG
u.IsWindowVisible.argtypes=[w.HWND];u.IsWindowVisible.restype=w.BOOL
cbtype=ctypes.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
u.EnumWindows.argtypes=[cbtype,w.LPARAM];u.EnumChildWindows.argtypes=[w.HWND,cbtype,w.LPARAM]
owners={p.pid:p.info['name'] for p in psutil.process_iter(['name']) if p.info['name'].lower() in ('gbox.exe','retroarch.exe')}
seen=set();windows=[]
def visit(hwnd,_):
 if hwnd in seen:return True
 seen.add(hwnd);pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
 if pid.value in owners:
  rect=w.RECT();u.GetWindowRect(hwnd,ctypes.byref(rect))
  windows.append({'hwnd':hwnd,'pid':pid.value,'name':owners[pid.value],'parent':u.GetParent(hwnd),'visible':bool(u.IsWindowVisible(hwnd)),'style':hex(u.GetWindowLongW(hwnd,-16)&0xffffffff),'exstyle':hex(u.GetWindowLongW(hwnd,-20)&0xffffffff),'rect':[rect.left,rect.top,rect.right,rect.bottom]})
 return True
callback=cbtype(visit)
def top(hwnd,_):
 visit(hwnd,0);u.EnumChildWindows(hwnd,callback,0);return True
u.EnumWindows(cbtype(top),0)
Path('C:/_tools/gBox/.scratch-i9-window-ownership-20261030.json').write_text(json.dumps(windows))
