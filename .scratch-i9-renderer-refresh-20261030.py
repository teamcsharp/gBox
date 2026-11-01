import ctypes, json, time
from ctypes import wintypes as w
from pathlib import Path
import psutil

receipt = Path('C:/_tools/gBox/.scratch-i9-renderer-refresh-20261030.receipt.json')
if receipt.exists():
    raise SystemExit(0)
u = ctypes.WinDLL('user32', use_last_error=True)
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.IsWindowVisible.argtypes = [w.HWND]
u.IsWindowVisible.restype = w.BOOL
u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.PostMessageW.restype = w.BOOL
cbtype = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [cbtype, w.LPARAM]
expected = 'c:\\users\\maste\\appdata\\local\\gbox\\app\\gbox.exe'
found = []
def visit(hwnd, _):
    pid = w.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        p = psutil.Process(pid.value)
        if p.exe().lower() != expected or not u.IsWindowVisible(hwnd):
            return True
        title, cls = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, title, len(title))
        u.GetClassNameW(hwnd, cls, len(cls))
        if cls.value == 'Chrome_WidgetWin_1' and title.value.lower() == 'gbox':
            found.append({'hwnd': hwnd, 'pid': pid.value, 'birth': p.create_time(), 'title': title.value, 'class': cls.value})
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return True
u.EnumWindows(cbtype(visit), 0)
assert len(found) == 1, ('Expected one owned gBox window', found)
v = found[0]
assert psutil.Process(v['pid']).create_time() == v['birth']
v.update(at=time.time(), action='one owned-window F5, no foreground or global keyboard changes')
# Record before dispatch: never issue a second F5, which could force a runtime restart.
receipt.write_text(json.dumps(v))
v['keydown'] = bool(u.PostMessageW(v['hwnd'], 0x100, 0x74, 1 | (0x3f << 16)))
v['keyup'] = bool(u.PostMessageW(v['hwnd'], 0x101, 0x74, 1 | (0x3f << 16) | (3 << 30)))
receipt.write_text(json.dumps(v))
