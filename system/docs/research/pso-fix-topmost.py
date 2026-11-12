"""Never pin a window on top: remove the TOPMOST nudge that made gBox dominate the desktop.

`raise_window` used the classic pair

    SetWindowPos(hwnd, HWND_TOPMOST, ...)
    SetWindowPos(hwnd, HWND_NOTOPMOST, ...)

as a trick to push a window into the foreground. It only works if the second call lands; if it is lost, delayed, or the window manager is busy, the
window **stays always-on-top** and covers everything, including the taskbar and its flyouts - which is what the operator experienced: gBox on top of
every other application, no way to click through, and the volume control unreachable.

The pair is removed. Focus is requested only with the calls that do not pin anything:

    ShowWindow(SW_RESTORE), SetForegroundWindow, BringWindowToTop

and a `clear_topmost` helper is added so an already-pinned window can be released, while the app is still running or afterwards.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def raise_window(")
end = text.find("def _pid(", start)
if start < 0 or end < 0:
    raise SystemExit("raise_window not found")

body = '''def raise_window(hwnd=None, tries=6):
    """Ask the window manager to bring a window forward WITHOUT pinning it on top.

    Deliberately no HWND_TOPMOST here: that is what left gBox covering the whole desktop when the matching NOTOPMOST call was lost.
    """
    hwnd = hwnd or app_window()
    if not hwnd:
        return False
    root = user32.GetAncestor(hwnd, 2)
    for _ in range(tries):
        user32.ShowWindow(hwnd, 9)                       # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        them = user32.GetWindowThreadProcessId(hwnd, None)
        user32.AttachThreadInput(me, them, True)
        user32.SetFocus(hwnd)
        user32.AttachThreadInput(me, them, False)
        time.sleep(0.18)
        if adapters._win_input_in_front(user32, root, False):
            return True
    return False


def clear_topmost(hwnd=None):
    """Release an always-on-top window. Safe to call whether or not it is pinned."""
    hwnd = hwnd or app_window()
    if not hwnd:
        return False
    GWL_EXSTYLE, WS_EX_TOPMOST, HWND_NOTOPMOST = -20, 0x00000008, -2
    released = False
    for target in (hwnd, user32.GetAncestor(hwnd, 2)):
        if not target:
            continue
        style = user32.GetWindowLongW(target, GWL_EXSTYLE)
        if style & WS_EX_TOPMOST:
            user32.SetWindowLongW(target, GWL_EXSTYLE, style & ~WS_EX_TOPMOST)
        user32.SetWindowPos(target, HWND_NOTOPMOST, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0010 | 0x0020)   # NOSIZE|NOMOVE|NOACTIVATE|FRAMECHANGED
        if not (user32.GetWindowLongW(target, GWL_EXSTYLE) & WS_EX_TOPMOST):
            released = True
    return released


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("raise_window no longer uses TOPMOST, and clear_topmost is available")
