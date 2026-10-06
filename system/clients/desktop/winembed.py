"""Embed a native emulator window into the G-Box app window (Windows).

Long-running helper driven by the Electron main process over stdin/stdout (one JSON object per line):
  {"op": "attach", "pid": 1234, "parent": <HWND>}   find the game window of that process (or its children) and re-parent it
  {"op": "move", "x":.., "y":.., "w":.., "h":..}     physical pixels, relative to the parent's client area
  {"op": "hide"} / {"op": "detach"}
Replies: {"ok": true, ...} or {"ok": false, "error": "..."}.
"""
import ctypes
import json
import sys
import time
from ctypes import wintypes

u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP = 0x40000000, 0x10000000, 0x80000000
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU, WS_MINMAX = 0x00C00000, 0x00040000, 0x00080000, 0x00030000
WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = 0x00040000, 0x00000080
SWP_NOZORDER, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0004, 0x0020, 0x0040
SW_HIDE, SW_SHOW = 0, 5
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
u32.SetParent.restype = wintypes.HWND

state = {"hwnd": None, "style": None, "exstyle": None, "pid": None}


def descendants(pid: int) -> set[int]:
    """pid + all child processes (RocketLauncher-style launchers spawn the real emulator)."""
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    pe, kids = PE(), {}
    pe.dwSize = ctypes.sizeof(PE)
    ok = k32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        kids.setdefault(pe.th32ParentProcessID, []).append(pe.th32ProcessID)
        ok = k32.Process32NextW(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    out, todo = set(), [pid]
    while todo:
        p = todo.pop()
        if p not in out:
            out.add(p)
            todo += kids.get(p, [])
    return out


def find_window(pid: int):
    pids, best = descendants(pid), [None, 0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        wpid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value in pids and u32.IsWindowVisible(h):
            r = wintypes.RECT()
            u32.GetWindowRect(h, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            if area > best[1]:
                best[0], best[1] = h, area
        return True
    u32.EnumWindows(cb, 0)
    return best[0]


def attach(pid: int, parent: int):
    if state["hwnd"] and state["pid"] == pid and u32.IsWindow(state["hwnd"]):
        return {"ok": True, "hwnd": state["hwnd"], "already": True}
    detach()
    h = None
    for _ in range(150):                                     # the emulator may still be creating its window
        h = find_window(pid)
        if h:
            break
        time.sleep(0.1)
    if not h:
        return {"ok": False, "error": f"no window for pid {pid}"}
    state.update(hwnd=h, pid=pid, style=u32.GetWindowLongPtrW(h, GWL_STYLE), exstyle=u32.GetWindowLongPtrW(h, GWL_EXSTYLE))
    style = (state["style"] & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINMAX)) | WS_CHILD | WS_VISIBLE
    u32.SetWindowLongPtrW(h, GWL_STYLE, style)
    u32.SetWindowLongPtrW(h, GWL_EXSTYLE, state["exstyle"] & ~WS_EX_APPWINDOW)   # no separate taskbar button
    u32.SetParent(h, parent)
    u32.SetWindowPos(h, 0, 0, 0, 640, 480, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    return {"ok": True, "hwnd": h}


def move(x, y, w, h):
    if not state["hwnd"] or not u32.IsWindow(state["hwnd"]):
        return {"ok": False, "error": "not attached"}
    u32.ShowWindow(state["hwnd"], SW_SHOW)
    u32.MoveWindow(state["hwnd"], int(x), int(y), max(1, int(w)), max(1, int(h)), True)
    return {"ok": True}


def hide():
    if state["hwnd"] and u32.IsWindow(state["hwnd"]):
        u32.ShowWindow(state["hwnd"], SW_HIDE)
    return {"ok": True}


def detach():
    h = state["hwnd"]
    if h and u32.IsWindow(h):
        u32.SetParent(h, None)
        u32.SetWindowLongPtrW(h, GWL_STYLE, state["style"])
        u32.SetWindowLongPtrW(h, GWL_EXSTYLE, state["exstyle"])
        u32.SetWindowPos(h, 0, 100, 100, 1280, 960, SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
    state.update(hwnd=None, pid=None)
    return {"ok": True}


for line in sys.stdin:
    try:
        m = json.loads(line)
        op = m.get("op")
        r = (attach(int(m["pid"]), int(m["parent"])) if op == "attach" else move(m["x"], m["y"], m["w"], m["h"]) if op == "move"
             else hide() if op == "hide" else detach() if op == "detach" else {"ok": False, "error": f"unknown op {op}"})
    except Exception as e:
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(r) + "\n")
    sys.stdout.flush()
