"""Embed a native emulator window into the gBox app window (Windows).

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

u32, k32, g32 = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.gdi32
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP = 0x40000000, 0x10000000, 0x80000000
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU, WS_MINMAX = 0x00C00000, 0x00040000, 0x00080000, 0x00030000
WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = 0x00040000, 0x00000080
SWP_NOZORDER, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0004, 0x0020, 0x0040
SW_HIDE, SW_SHOW, SW_SHOWNA = 0, 5, 8      # SHOWNA: show without activating (never steal the keyboard)
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
u32.SetParent.restype = wintypes.HWND
g32.CreateRectRgn.restype = wintypes.HRGN
g32.CombineRgn.argtypes = [wintypes.HRGN, wintypes.HRGN, wintypes.HRGN, ctypes.c_int]
g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]

out_lock = __import__("threading").Lock()


def emit(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


state = {"hwnd": None, "style": None, "exstyle": None, "pid": None, "parent": None, "rect": None, "shown": True}
lock = __import__("threading").Lock()


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
            if u32.IsIconic(h):                              # minimized (emulators started minimized): its normal size
                class WP(ctypes.Structure):
                    _fields_ = [("len", wintypes.UINT), ("flags", wintypes.UINT), ("show", wintypes.UINT),
                                ("mn", wintypes.POINT), ("mx", wintypes.POINT), ("rc", wintypes.RECT)]
                wp = WP(); wp.len = ctypes.sizeof(WP)
                u32.GetWindowPlacement(h, ctypes.byref(wp)); r = wp.rc
            else:
                u32.GetWindowRect(h, ctypes.byref(r))
            area = (r.right - r.left) * (r.bottom - r.top)
            t = ctypes.create_unicode_buffer(256); u32.GetWindowTextW(h, t, 256)
            if " | " in t.value:                             # Dolphin's game window ("Dolphin 2609 | JIT64 DC | ..."), not its menu window
                area *= 100
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
    if u32.IsIconic(h):
        u32.ShowWindow(h, 4)                                 # SW_SHOWNOACTIVATE: un-minimize before docking
    state.update(hwnd=h, pid=pid, parent=parent, holes=None, style=u32.GetWindowLongPtrW(h, GWL_STYLE), exstyle=u32.GetWindowLongPtrW(h, GWL_EXSTYLE))
    style = (state["style"] & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINMAX)) | WS_CHILD | WS_VISIBLE | 0x04000000   # WS_CLIPSIBLINGS
    u32.SetWindowLongPtrW(h, GWL_STYLE, style)
    u32.SetWindowLongPtrW(h, GWL_EXSTYLE, state["exstyle"] & ~WS_EX_APPWINDOW)   # no separate taskbar button
    u32.SetParent(h, parent)
    x, y, w, hh = state["rect"] or (0, 0, 640, 480)
    u32.SetWindowPos(h, 0, int(x), int(y), max(1, int(w)), max(1, int(hh)), SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW | 0x0010)   # NOACTIVATE
    if not state["shown"]:
        u32.ShowWindow(h, SW_HIDE)
    return {"ok": True, "hwnd": h}


def move(x, y, w, h, holes=()):
    r = (int(x), int(y), max(1, int(w)), max(1, int(h)))
    moved = r != state.get("placed")
    state.update(rect=(x, y, w, h), shown=True, placed=r)
    # emulators recreate their window on a video-mode change (RetroArch's PS2 core after boot, fullscreen toggles): the
    # docked child is gone or replaced by a new top-level one. A docked window isn't top-level, so any visible top-level
    # window of the game's process is a fresh one: dock it instead of leaving it loose on the desktop.
    if state.get("pid") and state.get("parent"):
        fresh = find_window(state["pid"])
        if fresh and fresh != state["hwnd"]:
            pid, parent = state["pid"], state["parent"]
            state["hwnd"] = None
            attach(pid, parent)
            state["placed"] = None
            r2 = (int(x), int(y), max(1, int(w)), max(1, int(h)))
            if state["hwnd"]:
                u32.SetWindowPos(state["hwnd"], 0, *r2, 0x0004 | 0x0010 | 0x0200)
                state["placed"] = r2
    if not state["hwnd"] or not u32.IsWindow(state["hwnd"]):
        return {"ok": False, "error": "not attached"}
    if not u32.IsWindowVisible(state["hwnd"]):
        u32.ShowWindow(state["hwnd"], SW_SHOWNA)
    if moved:                                               # repainting an unmoved window every sync made it flicker
        u32.SetWindowPos(state["hwnd"], 0, *r, 0x0004 | 0x0010 | 0x0200)   # NOZORDER | NOACTIVATE | NOOWNERZORDER
    key = tuple(map(tuple, holes or ()))
    if key != state.get("holes"):                           # cut app panels out of the game window (they show through)
        state["holes"] = key
        if key:
            rgn = g32.CreateRectRgn(0, 0, int(w), int(h))
            for hx, hy, hw, hh in key:
                cut = g32.CreateRectRgn(int(hx), int(hy), int(hx + hw), int(hy + hh))
                g32.CombineRgn(rgn, rgn, cut, 4)            # RGN_DIFF
                g32.DeleteObject(cut)
            u32.SetWindowRgn(state["hwnd"], rgn, False)      # the window owns the region now; the game repaints itself next frame
        else:
            u32.SetWindowRgn(state["hwnd"], None, False)
    return {"ok": True}


def focus():
    """Give the docked game the keyboard/controller focus (RetroArch only reads input while its window has focus)."""
    h = state["hwnd"]
    if not (h and u32.IsWindow(h) and u32.IsWindowVisible(h)):
        return {"ok": False, "error": "not attached"}
    me, them = k32.GetCurrentThreadId(), u32.GetWindowThreadProcessId(h, None)
    u32.AttachThreadInput(me, them, True)
    u32.SetFocus(h)
    u32.AttachThreadInput(me, them, False)
    return {"ok": True}


def unfocus():
    """Hand the keyboard back to gBox (a text box was clicked while the game window held Windows focus)."""
    p, h = state["parent"], state["hwnd"]
    if not p:
        return {"ok": False, "error": "no parent"}
    me = k32.GetCurrentThreadId()
    them = [t for t in {u32.GetWindowThreadProcessId(x, None) for x in (p, h) if x and u32.IsWindow(x)} if t != me]
    for t in them:
        u32.AttachThreadInput(me, t, True)
    u32.SetFocus(p)
    for t in them:
        u32.AttachThreadInput(me, t, False)
    return {"ok": True}


def kill():
    """Close the docked game NOW (the operator confirmed): hide it, then end the emulator process."""
    h, pid = state["hwnd"], state.get("pid")
    if h and u32.IsWindow(h):
        u32.ShowWindow(h, SW_HIDE)
    if pid:
        import subprocess
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    state.update(hwnd=None, pid=None, holes=None, placed=None)
    return {"ok": True}


def hide():
    state["shown"] = False
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
    state.update(hwnd=None, pid=None, parent=None, holes=None)
    return {"ok": True}


def watchdog():
    """Emulators that restart in-process (RPCS3 load state / restart) destroy the docked window and open a new top-level
    one: dock the replacement in the same place."""
    while True:
        time.sleep(0.5)
        with lock:
            pid, parent, h = state["pid"], state["parent"], state["hwnd"]
            if h and u32.IsWindow(h) and state["shown"] and state["rect"] and not u32.IsWindowVisible(h):
                u32.ShowWindow(h, SW_SHOWNA)               # RPCS3 hides its window while it reloads a save state
            if pid and parent and not (h and u32.IsWindow(h)) and find_window(pid):
                state["hwnd"] = None
                attach(pid, parent)


__import__("threading").Thread(target=watchdog, daemon=True).start()


def rclick_hook():
    """Right button over the docked game window -> {"event": "rclick", x, y} (physical px, parent client area); the
    click is swallowed so the emulator doesn't also act on it. ponytail: emulators here don't use the right button;
    add a per-game opt-out if a mouse-driven PC game gets docked."""
    WH_MOUSE_LL, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_LBUTTONDOWN, WM_LBUTTONUP = 14, 0x204, 0x205, 0x201, 0x202

    class MS(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
    PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u32.CallNextHookEx.restype = ctypes.c_ssize_t
    u32.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, wintypes.HINSTANCE, wintypes.DWORD]
    u32.SetWindowsHookExW.restype = ctypes.c_void_p

    def over(pt):
        h = state["hwnd"]
        if not (h and state["shown"] and u32.IsWindow(h) and u32.IsWindowVisible(h)):
            return False
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        return r.left <= pt.x < r.right and r.top <= pt.y < r.bottom

    whip = {"on": False, "t": 0.0}

    def over_app(pt):                                # the gBox window (sidebar cards): only while a game is docked in it
        p = state.get("parent")
        if not (p and state["hwnd"] and u32.IsWindow(state["hwnd"])):
            return False
        r = wintypes.RECT()
        u32.GetWindowRect(p, ctypes.byref(r))
        return r.left <= pt.x < r.right and r.top <= pt.y < r.bottom

    def rel(pt):
        o = wintypes.POINT(0, 0)
        u32.ClientToScreen(state["parent"], ctypes.byref(o))
        return pt.x - o.x, pt.y - o.y

    @PROC
    def proc(code, wp, lp):
        if code == 0 and (whip["on"] or wp == WM_LBUTTONDOWN):   # Alt + drag = pick whip: "swap this with that"
            m = ctypes.cast(lp, ctypes.POINTER(MS)).contents
            if whip["on"]:
                if wp == 0x200:                                    # WM_MOUSEMOVE, ~60 updates/s
                    now = time.time()
                    if now - whip["t"] > 0.016:
                        whip["t"] = now
                        x, y = rel(m.pt)
                        emit({"event": "whip", "phase": "move", "x": x, "y": y})
                elif wp == WM_LBUTTONUP:
                    whip["on"] = False
                    x, y = rel(m.pt)
                    emit({"event": "whip", "phase": "end", "x": x, "y": y})
                    return 1
            elif u32.GetAsyncKeyState(0x12) & 0x8000 and (over(m.pt) or over_app(m.pt)):
                whip["on"] = True
                x, y = rel(m.pt)
                emit({"event": "whip", "phase": "start", "x": x, "y": y})
                return 1
        if code == 0 and wp == WM_LBUTTONUP and not whip["on"]:               # a drag from the sidebar dropped on the game
            mu = ctypes.cast(lp, ctypes.POINTER(MS)).contents
            if over(mu.pt):
                x, y = rel(mu.pt)
                emit({"event": "gameup", "x": x, "y": y})
        if code == 0 and wp in (WM_LBUTTONDOWN, 0x207) and not whip["on"]:    # any click on the game (left / middle):
            m0 = ctypes.cast(lp, ctypes.POINTER(MS)).contents                  # the app closes its open menus/pop-ups
            if over(m0.pt):
                emit({"event": "gameclick"})
        ctrl = wp in (WM_LBUTTONDOWN, WM_LBUTTONUP) and u32.GetAsyncKeyState(0x11) & 0x8000   # Ctrl+click = eyedrop this spot
        if code == 0 and (wp in (WM_RBUTTONDOWN, WM_RBUTTONUP) or ctrl):
            m = ctypes.cast(lp, ctypes.POINTER(MS)).contents
            if over(m.pt):
                if wp in (WM_RBUTTONUP, WM_LBUTTONUP):
                    o = wintypes.POINT(0, 0)
                    u32.ClientToScreen(state["parent"], ctypes.byref(o))
                    emit({"event": "rclick" if wp == WM_RBUTTONUP else "ctrlclick", "x": m.pt.x - o.x, "y": m.pt.y - o.y})
                return 1
        return u32.CallNextHookEx(None, code, wp, lp)
    rclick_hook.proc = proc                                     # keep the callback alive
    u32.SetWindowsHookExW(WH_MOUSE_LL, proc, None, 0)
    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass


__import__("threading").Thread(target=rclick_hook, daemon=True).start()


def ptt_hook():
    """Hold ~ (the key under Esc) = push-to-talk to gBox, even while the docked game has the keyboard. Swallowed so the
    emulator doesn't see it."""
    WH_KEYBOARD_LL, VK_OEM_3 = 13, 0xC0

    class KB(ctypes.Structure):
        _fields_ = [("vk", wintypes.DWORD), ("scan", wintypes.DWORD), ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("extra", ctypes.c_size_t)]
    PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    u32.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, wintypes.HINSTANCE, wintypes.DWORD]
    held = [False]

    @PROC
    def proc(code, wp, lp):
        if code == 0:
            k = ctypes.cast(lp, ctypes.POINTER(KB)).contents
            if k.vk == VK_OEM_3 and state["parent"] and u32.GetForegroundWindow() == state["parent"]:
                down = wp in (0x100, 0x104)                     # WM_KEYDOWN / WM_SYSKEYDOWN
                if down != held[0]:
                    held[0] = down
                    emit({"event": "ptt", "down": down})
                return 1
        return u32.CallNextHookEx(None, code, wp, lp)
    ptt_hook.proc = proc
    u32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)
    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass


__import__("threading").Thread(target=ptt_hook, daemon=True).start()


for line in sys.stdin:
    try:
        m = json.loads(line)
        op = m.get("op")
        with lock:
            r = (attach(int(m["pid"]), int(m["parent"])) if op == "attach" else move(m["x"], m["y"], m["w"], m["h"], m.get("holes")) if op == "move"
                 else hide() if op == "hide" else focus() if op == "focus" else kill() if op == "kill" else unfocus() if op == "unfocus" else detach() if op == "detach" else {"ok": False, "error": f"unknown op {op}"})
    except Exception as e:
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    emit(r)
