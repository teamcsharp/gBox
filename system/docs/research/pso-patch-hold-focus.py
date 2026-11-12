"""Hold the app in front while playing, restoring it if it was minimised.

BackgroundInput is confirmed active in this session - the emulator started at 18:55, well after the setting was written at 17:57 - and unfocused keys
still do not arrive, because the app forwards the keyboard into the game only while its own window is foreground. So the loop has to keep that window in
front for as long as it plays.

`ensure_focus` previously only called `raise_window()`, which reports success while the window is **minimised** and focus never arrives. This version
restores the window first (SW_RESTORE), then raises it, then verifies `game_has_focus()` before claiming anything - and it does so at the top of every
cycle, so a window switch by the operator is recovered on the next tick instead of stopping the play.

The operator's pad still wins: a recent pad activity makes the loop wait rather than fight.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\play_rooms.py")
text = path.read_text(encoding="utf-8")

start = text.find("def ensure_focus():")
end = text.find("def main(seconds=3600.0):")
if start < 0 or end < 0:
    raise SystemExit("ensure_focus block not found")

block = '''def ensure_focus():
    """Restore and raise the app window, then confirm it really has focus.

    Returns True only when `game_has_focus()` says so, because `raise_window()` alone reports success on a minimised window while focus never arrives.
    """
    if G.game_has_focus():
        return True
    if OP.operator_active():
        return False
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = G.app_window()
        if hwnd:
            u.ShowWindow(hwnd, 9)                 # SW_RESTORE from minimised
            u.SetForegroundWindow(hwnd)
    except Exception:                                            # noqa: BLE001
        pass
    if not G.game_has_focus():
        G.raise_window()                          # its own attach/focus path
    if G.game_has_focus():
        log("  held the window in front to play")
        return True
    return False


def main(seconds=3600.0):'''
text = text[:start] + block + text[end:]
path.write_text(text, encoding="utf-8")
print("ensure_focus now restores the window and verifies the focus it claims")
