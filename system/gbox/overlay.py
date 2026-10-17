"""Cross-game picture: one game's UI drawn over another game's live scene (Windows).

The guest window (e.g. Puyo Puyo Tetris in RPCS3) becomes a borderless always-on-top window over the host window
(e.g. Stranglehold), clipped by SetWindowRgn to the guest's UI rectangles (playfields, score), so everything else shows
the host. Rectangles are fractions of the guest picture (x, y, w, h in 0..1), measured once per game.
"""
import ctypes
import ctypes.wintypes as w

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_POPUP, WS_VISIBLE, WS_CHILD = 0x80000000, 0x10000000, 0x40000000
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU = 0x00C00000, 0x00040000, 0x00080000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080
HWND_TOPMOST, SWP_SHOWWINDOW, SWP_FRAMECHANGED = -1, 0x0040, 0x0020

_saved: dict[int, tuple] = {}                               # hwnd -> (parent, style, exstyle, rect) for restore
_u32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None
if _u32:                                                    # 64-bit-safe signatures for style / parent / region calls
    _u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _u32.SetParent.argtypes = [w.HWND, w.HWND]
    _u32.SetParent.restype = w.HWND
    _u32.GetParent.restype = w.HWND
    _u32.SetWindowRgn.argtypes = [w.HWND, w.HANDLE, w.BOOL]
    _u32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]


def game_window(pid: int) -> int | None:
    """RPCS3's game window ("FPS: ... | TITLE [ID]"), top-level or docked inside the gBox app."""
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def cb(h, _):
        p = w.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            t = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, t, 256)
            if "FPS" in t.value:
                found.append(h)
        return True
    u.EnumChildWindows(u.GetDesktopWindow(), cb, 0)
    return found[0] if found else None


def scaled(rects: list[list[float]], width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Fractional rects -> pixel (left, top, right, bottom) inside a width x height picture."""
    return [(round(x * width), round(y * height), round((x + rw) * width), round((y + rh) * height)) for x, y, rw, rh in rects]


def overlay_on(guest_pid: int, host_pid: int, rects: list[list[float]]) -> dict:
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    gh, hh = game_window(guest_pid), game_window(host_pid)
    if not gh or not hh:
        raise RuntimeError("both game windows must be open")
    r = w.RECT()
    u.GetWindowRect(hh, ctypes.byref(r))                    # cover the host's picture exactly
    x, y, wd, ht = r.left, r.top, r.right - r.left, r.bottom - r.top
    if gh not in _saved:
        old = w.RECT()
        u.GetWindowRect(gh, ctypes.byref(old))
        _saved[gh] = (u.GetParent(gh), u.GetWindowLongPtrW(gh, GWL_STYLE), u.GetWindowLongPtrW(gh, GWL_EXSTYLE), old)
    u.SetParent(gh, None)
    u.SetWindowLongPtrW(gh, GWL_STYLE, WS_POPUP | WS_VISIBLE)
    u.SetWindowLongPtrW(gh, GWL_EXSTYLE, WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
    u.SetWindowPos(gh, HWND_TOPMOST, x, y, wd, ht, SWP_SHOWWINDOW | SWP_FRAMECHANGED)
    rgn = None
    for left, top, right, bottom in scaled(rects, wd, ht):  # union of the UI rectangles = the only visible part
        part = g.CreateRectRgn(left, top, right, bottom)
        if rgn is None:
            rgn = part
        else:
            g.CombineRgn(rgn, rgn, part, 2)                 # RGN_OR
            g.DeleteObject(part)
    u.SetWindowRgn(gh, rgn, True)                           # the window now owns the region
    return {"guest_window": gh, "host_window": hh, "area": [x, y, wd, ht], "rects": len(rects)}


def pip_box(box: list[float], x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Fractional (x, y, w, h) box inside a host picture at (x, y, width, height) -> screen (left, top, w, h)."""
    bx, by, bw, bh = box
    return x + round(bx * width), y + round(by * height), round(bw * width), round(bh * height)


def pip_on(guest_pid: int, host_pid: int, box: list[float]) -> dict:
    """Picture-in-picture: the whole guest window, borderless and on top, in a box of the host's picture (the host is
    frozen behind it). overlay_off restores the guest window."""
    u = ctypes.windll.user32
    gh, hh = game_window(guest_pid), game_window(host_pid)
    if not gh or not hh:
        raise RuntimeError("both game windows must be open")
    r = w.RECT()
    u.GetWindowRect(hh, ctypes.byref(r))
    left, top, wd, ht = pip_box(box, r.left, r.top, r.right - r.left, r.bottom - r.top)
    if gh not in _saved:
        old = w.RECT()
        u.GetWindowRect(gh, ctypes.byref(old))
        _saved[gh] = (u.GetParent(gh), u.GetWindowLongPtrW(gh, GWL_STYLE), u.GetWindowLongPtrW(gh, GWL_EXSTYLE), old)
    u.SetParent(gh, None)
    u.SetWindowLongPtrW(gh, GWL_STYLE, WS_POPUP | WS_VISIBLE)
    u.SetWindowLongPtrW(gh, GWL_EXSTYLE, WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
    u.SetWindowRgn(gh, None, True)
    u.SetWindowPos(gh, HWND_TOPMOST, left, top, wd, ht, SWP_SHOWWINDOW | SWP_FRAMECHANGED)
    return {"guest_window": gh, "host_window": hh, "area": [left, top, wd, ht]}


def overlay_off(guest_pid: int) -> dict:
    u = ctypes.windll.user32
    gh = game_window(guest_pid)
    if not gh:
        return {"restored": False}
    u.SetWindowRgn(gh, None, True)
    if gh in _saved:
        parent, style, exstyle, r = _saved.pop(gh)
        u.SetWindowLongPtrW(gh, GWL_STYLE, style)
        u.SetWindowLongPtrW(gh, GWL_EXSTYLE, exstyle)
        if parent:
            u.SetParent(gh, parent)                         # back inside the gBox app
        u.SetWindowPos(gh, -2, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_SHOWWINDOW | SWP_FRAMECHANGED)   # HWND_NOTOPMOST
    return {"restored": True}


def _selftest():
    assert scaled([[0.25, 0.1, 0.5, 0.8]], 1280, 720) == [(320, 72, 960, 648)]
    assert pip_box([0.5, 0.0, 0.5, 0.5], 100, 50, 1280, 720) == (740, 50, 640, 360)
    print("overlay selftest ok")


if __name__ == "__main__":
    _selftest()
