"""Embed a native emulator window into the gBox app window (Windows).

Long-running helper driven by the Electron main process over stdin/stdout (one JSON object per line):
  {"op": "attach", "pid": 1234, "parent": <HWND>}   find the game window of that process (or its children) and re-parent it
  {"op": "move", "x":.., "y":.., "w":.., "h":..}     physical pixels, relative to the parent's client area
  {"op": "hide"} / {"op": "detach"}
  {"op": "watch", "app": <HWND>}                    the gBox window: reply {"ok": true, "front": bool}, then report changes
  {"op": "appchrome", "app": <HWND>, "pid": <gBox PID>, "on": true|false}   temporarily hide only gBox's caption controls
Replies: {"ok": true, ...} or {"ok": false, "error": "..."}.
Events: {"event": "foreground", "front": bool} whenever gBox (or the game docked in it) gains or loses the foreground.

Input scope: nothing here swallows or reacts to keyboard/mouse input aimed at another application. The low-level hooks below
only act when the window under the cursor (WindowFromPoint -> GA_ROOTOWNER) is gBox or its docked game, and the modifier
gestures (Ctrl+click, Alt+drag, ~ push-to-talk) also need gBox in front; everything else goes on untouched.
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
u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
u32.SetParent.restype = wintypes.HWND
u32.GetParent.argtypes = [wintypes.HWND]
u32.GetParent.restype = wintypes.HWND
u32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
u32.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
g32.CreateRectRgn.restype = wintypes.HRGN
g32.CombineRgn.argtypes = [wintypes.HRGN, wintypes.HRGN, wintypes.HRGN, ctypes.c_int]
g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetAncestor.argtypes, u32.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
u32.WindowFromPoint.argtypes, u32.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
GA_ROOTOWNER = 3                  # parent/owner chain: a docked child or a window gBox owns -> the gBox window

out_lock = __import__("threading").Lock()


def emit(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


state = {"hwnd": None, "style": None, "exstyle": None, "pid": None, "parent": None, "rect": None, "shown": True, "mode": "native",
         "app": None, "front": None, "compact": False, "app_chrome": None, "source_aspect": None}
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


def find_window(pid: int, hidden=False, parent=None):
    pids, best = descendants(pid), [None, 0]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        wpid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value in pids and (hidden or u32.IsWindowVisible(h)):
            t = ctypes.create_unicode_buffer(256); u32.GetWindowTextW(h, t, 256)
            if t.value.startswith(("DIEmWin", "__wgl", "NVOGL", "Default IME", "MSCTFIME")):
                return True                     # driver/input helper windows are not the game's GPU surface
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
            if " | " in t.value:                             # Dolphin's game window ("Dolphin 2609 | JIT64 DC | ..."), not its menu window
                area *= 100
            if area > best[1]:
                best[0], best[1] = h, area
        return True
    u32.EnumWindows(cb, 0)
    if parent and u32.IsWindow(parent):
        u32.EnumChildWindows(parent, cb, 0)     # recover a game already docked by an earlier helper
    return best[0]


def attach(pid: int, parent: int):
    if not parent or not u32.IsWindow(parent):
        hide()
        return {'ok': False, 'error': 'The gBox parent window is no longer available'}
    if state["hwnd"] and state["pid"] == pid and u32.IsWindow(state["hwnd"]) and u32.GetParent(state['hwnd']) == parent and u32.GetWindowLongPtrW(state['hwnd'], GWL_STYLE) & WS_CHILD:
        return {"ok": True, "hwnd": state["hwnd"], "already": True}
    detach()
    h = None
    for _ in range(150):                                     # the emulator may still be creating its window
        h = find_window(pid, parent=parent) or find_window(pid, hidden=True, parent=parent)
        if h:
            break
        time.sleep(0.1)
    if not h:
        return {"ok": False, "error": f"no window for pid {pid}"}
    if u32.IsIconic(h):
        u32.ShowWindow(h, 4)                                 # SW_SHOWNOACTIVATE: un-minimize before docking
    u32.RemovePropW(h, "GBoxCompositedSurface")
    source_rect = wintypes.RECT()
    u32.GetClientRect(h, ctypes.byref(source_rect))
    source_width, source_height = source_rect.right-source_rect.left, source_rect.bottom-source_rect.top
    state['source_aspect'] = source_width/source_height if source_width > 0 and source_height > 0 else None
    # the emulator starts fully transparent (gBox launches it that way so it never flashes on the desktop): opaque from here
    state.update(hwnd=h, pid=pid, parent=parent, holes=None, mode="native", style=u32.GetWindowLongPtrW(h, GWL_STYLE),
                 exstyle=u32.GetWindowLongPtrW(h, GWL_EXSTYLE) & ~0x00080000)   # WS_EX_LAYERED
    style = (state["style"] & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINMAX)) | WS_CHILD | WS_VISIBLE | 0x04000000   # WS_CLIPSIBLINGS
    u32.SetWindowLongPtrW(h, GWL_STYLE, style)
    u32.SetWindowLongPtrW(h, GWL_EXSTYLE, state["exstyle"] & ~WS_EX_APPWINDOW)   # no separate taskbar button
    u32.SetParent(h, parent)
    if u32.GetParent(h) != parent:
        u32.ShowWindow(h, SW_HIDE)
        state.update(hwnd=None, pid=None, parent=None)
        return {'ok': False, 'error': 'Game window could not be docked; hidden to prevent a desktop popup'}
    x, y, w, hh = state["rect"] or (0, 0, 640, 480)
    u32.SetWindowPos(h, 0, int(x), int(y), max(1, int(w)), max(1, int(hh)), SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW | 0x0010)   # NOACTIVATE
    if not state["shown"]:
        u32.ShowWindow(h, SW_HIDE)
    return {"ok": True, "hwnd": h}


def capture_position(warm=False):
    h, parent = state.get("hwnd"), state.get("parent")
    x, y = -16000, -16000
    if warm and parent and u32.IsWindow(parent) and not u32.IsIconic(parent):
        r = wintypes.RECT(); u32.GetWindowRect(parent, ctypes.byref(r))
        x, y = r.left + 20, r.top + 60
    if h and u32.IsWindow(h):
        r = wintypes.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
        if r.left != x or r.top != y:
            u32.SetWindowPos(h, 1, x, y, 0, 0, 0x0001 | 0x0010)


def captured(pid):
    if state.get("mode") != "capture" or state.get("pid") != pid:
        return {"ok": False, "error": "Stale capture source"}
    state["warm_until"] = 0
    capture_position()
    return {"ok": True}


def status(pid):
    """Only the already attached native surface proves liveness, never an API outage."""
    if state.get('pid') != pid:
        return {'ok': False, 'error': 'The requested PID is not the attached game'}
    window = state.get('hwnd')
    return {'ok': True, 'pid': pid, 'alive': bool(window and u32.IsWindow(window)),
            'mode': state.get('mode')}


def capture(pid: int, parent: int, w=1280, h=960, warm=False):
    """Keep the GPU window off the desktop; Chromium presents its live captured surface.

    A child HWND cannot be captured by Chromium. Make the source a borderless
    window off-screen, without changing the emulator's graphics driver or process.
    Never resize a healthy source when a menu opens or its video element moves.
    """
    if not parent or not u32.IsWindow(parent):
        return {"ok": False, "error": "The gBox window is no longer available"}
    if state.get("mode") == "capture" and state.get("pid") == pid and state.get("hwnd") and u32.IsWindow(state["hwnd"]):
        state["shown"] = True
        if not u32.IsWindowVisible(state["hwnd"]):
            u32.ShowWindow(state["hwnd"], SW_SHOWNA)
        if warm:
            state["warm_until"] = time.monotonic() + 15
            capture_position(True)
        return {"ok": True, "hwnd": state["hwnd"], "sourceId": f'window:{state["hwnd"]}:0'}
    found = state["hwnd"] if state.get("pid") == pid and state["hwnd"] and u32.IsWindow(state["hwnd"]) else None
    found = found or find_window(pid, hidden=True, parent=parent)
    if not found:
        return {"ok": False, "error": f"no capture window for pid {pid}"}
    if state["hwnd"] and state["hwnd"] != found:
        detach()
    if u32.IsIconic(found):
        u32.ShowWindow(found, 4)                 # a minimized source cannot start a live GPU capture
    u32.ShowWindow(found, SW_HIDE)
    style = u32.GetWindowLongPtrW(found, GWL_STYLE)
    exstyle = u32.GetWindowLongPtrW(found, GWL_EXSTYLE)
    u32.SetWindowLongPtrW(found, GWL_STYLE, (style & ~(WS_CHILD | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINMAX)) | WS_POPUP | WS_VISIBLE)
    u32.SetWindowLongPtrW(found, GWL_EXSTYLE, exstyle & ~(WS_EX_APPWINDOW | WS_EX_TOOLWINDOW | 0x00080000))
    u32.SetParent(found, None)
    u32.SetWindowRgn(found, None, False)
    u32.SetPropW(found, "GBoxCompositedSurface", 1)
    w, h = max(320, min(1920, int(w))), max(240, min(1080, int(h)))
    # Capture reconnect needs an initial DWM frame. The source fits completely
    # behind the opaque host at HWND_BOTTOM until both Chromium streams decode.
    pr = wintypes.RECT(); u32.GetWindowRect(parent, ctypes.byref(pr))
    w, h = min(w, max(1, pr.right - pr.left - 40)), min(h, max(1, pr.bottom - pr.top - 80))
    state.update(hwnd=found, pid=pid, parent=parent, style=style, exstyle=exstyle,
                 mode="capture", holes=None, placed=None, shown=True, rect=(0, 0, w, h),
                 warm_until=time.monotonic() + 15 if warm else 0)
    # HWND_BOTTOM + NOACTIVATE: even an interrupted capture cannot cover the app.
    u32.SetWindowPos(found, 1, -16000, -16000, w, h, SWP_FRAMECHANGED | SWP_SHOWWINDOW | 0x0010)
    capture_position(warm)
    if u32.GetParent(found):
        u32.ShowWindow(found, SW_HIDE)
        return {"ok": False, "error": "The emulator window could not become a capture source"}
    return {"ok": True, "hwnd": found, "sourceId": f"window:{found}:0", "width": w, "height": h}


def move(x, y, w, h, holes=()):
    if state.get("mode") == "capture":          # failed media capture: restore the native dock safely
        pid, parent = state["pid"], state["parent"]
        state["mode"] = "native"
        result = attach(pid, parent)
        if not result.get("ok"):
            return result
    r = (int(x), int(y), max(1, int(w)), max(1, int(h)))
    moved = r != state.get("placed")
    state.update(rect=(x, y, w, h), shown=True, placed=r)
    # emulators recreate their window on a video-mode change (RetroArch's PS2 core after boot, fullscreen toggles): the
    # docked child is gone or replaced by a new top-level one. A docked window isn't top-level, so any visible top-level
    # window of the game's process is a fresh one: dock it instead of leaving it loose on the desktop.
    # At most once a second (#1081): the scan (process snapshot + every top-level window) takes ~50 ms, and a pop-up
    # opening over the game must be cut out now, not after it.
    if state.get("pid") and state.get("parent") and time.monotonic() >= state.get("fresh_check", 0):
        state["fresh_check"] = time.monotonic() + 1.0
        # Include the working dock in the ranking. A top-level Warning dialog is
        # not a replacement rendering window and must not take over the dock.
        fresh = find_window(state["pid"], parent=state["parent"])
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
    key = (r[2], r[3], tuple(map(tuple, holes or ())))
    if key != state.get("holes"):                           # cut app panels out of the game window (they show through)
        state["holes"] = key
        if holes:
            rgn = g32.CreateRectRgn(0, 0, int(w), int(h))
            for hx, hy, hw, hh in holes:
                cut = g32.CreateRectRgn(int(hx), int(hy), int(hx + hw), int(hy + hh))
                g32.CombineRgn(rgn, rgn, cut, 4)            # RGN_DIFF
                g32.DeleteObject(cut)
            u32.SetWindowRgn(state["hwnd"], rgn, False)      # the window owns the region now; the game repaints itself next frame
        else:
            u32.SetWindowRgn(state["hwnd"], None, False)
    return {"ok": True}


def focus():
    """Give the docked game the keyboard/controller focus (RetroArch only reads input while its window has focus)."""
    if state.get("mode") == "capture":
        return {"ok": True}                    # video input is delivered by the app; keep Chromium's focus
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
        # Switching views or game processes must never release a visible desktop popup.
        u32.ShowWindow(h, SW_HIDE)
        # Leave it parented: restoring top-level styles lets some emulators show it again.
        # The worker stops old games; releasing a dock must not resurrect their windows.
    state.update(hwnd=None, pid=None, parent=None, holes=None, placed=None, mode="native")
    return {"ok": True}


def watchdog():
    """Emulators that restart in-process (RPCS3 load state / restart) destroy the docked window and open a new top-level
    one: dock the replacement in the same place."""
    while True:
        time.sleep(0.5)
        with lock:
            pid, parent, h = state["pid"], state["parent"], state["hwnd"]
            if state.get("mode") == "capture":
                # Source stays below the host during reconnect, then off-screen.
                capture_position(time.monotonic() < state.get("warm_until", 0))
                continue                        # a replaced source is recovered by the renderer's media lifecycle
            if h and u32.IsWindow(h) and state["shown"] and state["rect"] and not u32.IsWindowVisible(h):
                u32.ShowWindow(h, SW_SHOWNA)               # RPCS3 hides its window while it reloads a save state
            if pid and parent and not (h and u32.IsWindow(h)) and find_window(pid):
                state["hwnd"] = None
                attach(pid, parent)


__import__("threading").Thread(target=watchdog, daemon=True).start()


def gbox_in_front(fg, fg_root, app, game) -> bool:
    """The foreground window is gBox's own window or the game docked in it (a docked child that has the keyboard reports
    its gBox root as the foreground window; a GPU-captured source is a top-level window of its own). Never another app."""
    if not fg or not app:
        return False
    return fg == app or fg_root == app or bool(game and (fg == game or fg_root == game))


def gesture_target(pt_root, in_game: bool, app, game, front: bool, needs_front: bool, *, game_hit: bool = False):
    """Who a mouse gesture at a screen point belongs to: "game" (the docked game is what's under the cursor), "app" (the gBox
    window), or None: another application's window is the one under the point (it covers gBox there), or the gesture uses a
    keyboard modifier (Ctrl+click, Alt+drag) while another application has the foreground. None = pass it on untouched."""
    if not app or not pt_root or pt_root not in (app, game):
        return None
    if needs_front and not front:
        return None
    # The app and docked game share a root. A popup revealed by a clipped game
    # region is still inside its bounding rectangle; only the actual hit proves game input.
    return "game" if in_game and game_hit else "app"


def front_now() -> bool:
    fg = u32.GetForegroundWindow()
    return gbox_in_front(fg, u32.GetAncestor(fg, GA_ROOTOWNER) if fg else None, state.get("app") or state.get("parent"), state.get("hwnd"))


def report_front(force=False):
    """Emit {"event": "foreground"} when gBox's foreground state changed (main.js holds its game hotkeys only while true)."""
    if not state.get("app"):
        return None
    now = front_now()
    if force or now != state.get("front"):
        state["front"] = now
        if not force:
            emit({"event": "foreground", "front": now})
    return now


def watch(app: int):
    state["app"] = app if app and u32.IsWindow(app) else None
    return {"ok": bool(state["app"]), "front": bool(report_front(force=True))}


def appchrome(app: int, pid: int, on: bool, restore_bits=None):
    """Change caption bits on the already registered gBox HWND only; never the game.

    Keep WS_THICKFRAME so normal edge resizing works. Restore just the saved
    chrome bits rather than overwriting visibility/maximize changes made later.
    """
    known = state.get('app') or state.get('parent')
    if not app or app != known or not u32.IsWindow(app):
        return {'ok': False, 'error': 'The registered gBox window is unavailable'}
    actual_pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(app, ctypes.byref(actual_pid))
    if not pid or actual_pid.value != pid:
        return {'ok': False, 'error': 'The gBox window process does not match'}
    bits = WS_CAPTION | WS_SYSMENU | WS_MINMAX
    current = u32.GetWindowLongPtrW(app, GWL_STYLE)
    saved = state.get('app_chrome')
    if saved and saved['hwnd'] != app:
        return {'ok': False, 'error': 'The compact gBox window has changed'}
    if on:
        if saved is None:
            # A helper started while gBox was already compact (the previous one stopped answering) takes the original
            # bits from the trusted main process; the window's current bits no longer have them.
            original = int(restore_bits) & bits if restore_bits is not None else current & bits
            saved = {'hwnd': app, 'pid': pid, 'bits': original}
        desired = current & ~bits
    else:
        # The trusted main process retains the snapshot too, allowing recovery
        # if this helper restarted while the live app stayed compact.
        original = saved['bits'] if saved else int(restore_bits) & bits if restore_bits is not None else current & bits
        desired = (current & ~bits) | original
    u32.SetWindowLongPtrW(app, GWL_STYLE, desired)
    u32.SetWindowPos(app, 0, 0, 0, 0, 0, SWP_NOZORDER | SWP_FRAMECHANGED | 0x0001 | 0x0002 | 0x0010)
    if u32.GetWindowLongPtrW(app, GWL_STYLE) & bits != desired & bits:
        u32.SetWindowLongPtrW(app, GWL_STYLE, current)
        u32.SetWindowPos(app, 0, 0, 0, 0, 0, SWP_NOZORDER | SWP_FRAMECHANGED | 0x0001 | 0x0002 | 0x0010)
        return {'ok': False, 'error': 'Windows did not apply the gBox caption change'}
    state['app_chrome'] = saved if on else None
    state['compact'] = bool(on)
    return {'ok': True, 'on': bool(on), 'aspect': state.get('source_aspect'), 'bits': saved['bits'] if saved else desired & bits}


def compact_click(previous, point, when, window, enabled, limit, extent):
    """Pure native double-click detection, scoped before calling this helper."""
    if not enabled or not window:
        return None, False
    x, y = point
    current = (x, y, when, window)
    if previous:
        px, py, pt, pw = previous
        if pw == window and 0 <= when-pt <= limit and abs(x-px) <= extent[0]/2 and abs(y-py) <= extent[1]/2:
            return None, True
    return current, False


def foreground_watch():
    """EVENT_SYSTEM_FOREGROUND (out of context, every process) + a 100 ms recheck: report gBox gaining/losing the front."""
    WINEVENT = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, ctypes.c_long, ctypes.c_long,
                                  wintypes.DWORD, wintypes.DWORD)
    u32.SetWinEventHook.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.HMODULE, WINEVENT, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.UINT]
    u32.SetWinEventHook.restype = wintypes.HANDLE

    @WINEVENT
    def on_foreground(*_):
        report_front()
    foreground_watch.proc = on_foreground                       # keep the callback alive
    u32.SetWinEventHook(0x0003, 0x0003, None, on_foreground, 0, 0, 0x0000)   # EVENT_SYSTEM_FOREGROUND, WINEVENT_OUTOFCONTEXT
    msg = wintypes.MSG()
    while True:
        u32.MsgWaitForMultipleObjects(0, None, False, 100, 0x04FF)          # QS_ALLINPUT: win events arrive as messages
        while u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):           # PM_REMOVE
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
        report_front()                                                      # fallback poll (missed event, re-docked game)


__import__("threading").Thread(target=foreground_watch, daemon=True).start()


def rclick_hook():
    """Right button over the docked game window -> {"event": "rclick", x, y} (physical px, parent client area); the
    click is swallowed so the emulator doesn't also act on it. ponytail: emulators here don't use the right button;
    add a per-game opt-out if a mouse-driven PC game gets docked.
    Scoped to gBox: a gesture counts only when the window actually under the cursor is gBox / its docked game
    (gesture_target), never by screen rectangle alone, so a click in Blender over the same screen area is never touched;
    Ctrl+click and Alt+drag also need gBox in front."""
    WH_MOUSE_LL, WM_RBUTTONDOWN, WM_RBUTTONUP, WM_LBUTTONDOWN, WM_LBUTTONUP = 14, 0x204, 0x205, 0x201, 0x202

    class MS(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]
    PROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    u32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    u32.IsChild.restype = wintypes.BOOL
    u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u32.CallNextHookEx.restype = ctypes.c_ssize_t
    u32.SetWindowsHookExW.argtypes = [ctypes.c_int, PROC, wintypes.HINSTANCE, wintypes.DWORD]
    u32.SetWindowsHookExW.restype = ctypes.c_void_p

    def in_game_rect(pt):
        h = state["hwnd"]
        if not (h and state["shown"] and u32.IsWindow(h) and u32.IsWindowVisible(h)):
            return False
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        return r.left <= pt.x < r.right and r.top <= pt.y < r.bottom

    whip = {"on": False, "t": 0.0}
    compact = {'click': None, 'release': False, 'hover': False}

    def target(pt, needs_front=False):
        """"game" / "app" (the gBox window, only while a game is docked in it) / None = not gBox's input."""
        p, h = state.get("parent"), state.get("hwnd")
        if not (p and h and u32.IsWindow(h)):
            return None
        hit = u32.WindowFromPoint(wintypes.POINT(pt.x, pt.y))
        root = u32.GetAncestor(hit, GA_ROOTOWNER) if hit else None
        front = front_now() if needs_front else False
        game_hit = bool(hit and (hit == h or u32.IsChild(h, hit)))
        return gesture_target(root, in_game_rect(pt), p, h, front, needs_front, game_hit=game_hit)

    def over(pt, needs_front=False):
        return target(pt, needs_front) == "game"

    def rel(pt):
        o = wintypes.POINT(0, 0)
        u32.ClientToScreen(state["parent"], ctypes.byref(o))
        return pt.x - o.x, pt.y - o.y

    @PROC
    def proc(code, wp, lp):
        if code == 0 and wp == WM_LBUTTONUP and compact['release']:
            compact['release'] = False
            return 1                                      # second half of a compact-mode double click
        if code == 0 and wp in (0x200, WM_LBUTTONDOWN):
            cm = ctypes.cast(lp, ctypes.POINTER(MS)).contents
            enabled = bool(state.get('compact'))
            hit = target(cm.pt) if enabled else None
            if wp == 0x200:
                show = False
                if hit:
                    cx, cy = rel(cm.pt)
                    try:
                        threshold = 32 * u32.GetDpiForWindow(state.get('app') or state['parent']) / 96
                    except AttributeError:
                        threshold = 48
                    show = 0 <= cy < threshold
                if show != compact['hover']:
                    compact['hover'] = show
                    emit({'event': 'compact-hover', 'show': show})
            elif not whip['on']:
                plain = not any(u32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12))
                compact['click'], double = compact_click(compact['click'], (cm.pt.x, cm.pt.y), cm.time,
                    state.get('hwnd'), enabled and hit == 'game' and plain, u32.GetDoubleClickTime(),
                    (u32.GetSystemMetrics(36), u32.GetSystemMetrics(37)))
                if double:
                    compact['release'] = True
                    emit({'event': 'piprestore'})
                    return 1
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
            elif u32.GetAsyncKeyState(0x12) & 0x8000 and target(m.pt, needs_front=True):
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
            if over(m.pt, needs_front=bool(ctrl)):
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
    emulator doesn't see it. Only while a game is docked and gBox (or that game) is the foreground window: in any other
    application ~ is passed on untouched (a ~ released there still ends a talk that began in gBox, without swallowing it)."""
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
            if k.vk == VK_OEM_3 and state["parent"]:
                down = wp in (0x100, 0x104)                     # WM_KEYDOWN / WM_SYSKEYDOWN
                fg = u32.GetForegroundWindow()
                if gbox_in_front(fg, u32.GetAncestor(fg, GA_ROOTOWNER) if fg else None, state["parent"], state["hwnd"]):
                    if down != held[0]:
                        held[0] = down
                        emit({"event": "ptt", "down": down})
                    return 1
                if held[0] and not down:                        # released in another app: stop talking, key goes on
                    held[0] = False
                    emit({"event": "ptt", "down": False})
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
            r = (capture(int(m["pid"]), int(m["parent"]), m.get("w", 1280), m.get("h", 960), m.get("warm", False)) if op == "capture"
                 else captured(int(m["pid"])) if op == "captured"
                 else attach(int(m["pid"]), int(m["parent"])) if op == "attach" else move(m["x"], m["y"], m["w"], m["h"], m.get("holes")) if op == "move"
                 else status(int(m.get('pid') or 0)) if op == 'status'
                 else watch(int(m.get("app") or 0)) if op == "watch"
                 else appchrome(int(m.get('app') or 0), int(m.get('pid') or 0), bool(m.get('on')), m.get('bits')) if op == 'appchrome'
                 else hide() if op == "hide" else focus() if op == "focus" else kill() if op == "kill" else unfocus() if op == "unfocus" else detach() if op == "detach" else {"ok": False, "error": f"unknown op {op}"})
    except Exception as e:
        r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    emit(r)

# Restore the caption if stdin closes while the app itself is still alive.
if state.get('app_chrome'):
    try:
        appchrome(state['app_chrome']['hwnd'], state['app_chrome']['pid'], False)
    except Exception:
        pass
