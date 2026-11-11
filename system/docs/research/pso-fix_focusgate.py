"""Send keys only when the game already holds focus - never take focus to do it.

Measured: posted keys (`polite=True`) do not reach the game at all (the character moved 0.0 units), while system-wide input does - but system-wide
input lands in whatever window has focus, which is how the bot was stealing the operator's typing.

The resolution is to gate on focus instead of grabbing it:

  * if the game window is already the foreground window, the keys are sent and land in the game;
  * if it is not, nothing is sent at all - so the operator keeps their focus and their keystrokes while using the PC, and the bot simply waits.

`send` therefore never raises, never focuses, and never types into another application.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

old_start = text.find("def send(")
old_end = text.find("def win_send_keys(")
if old_start < 0 or old_end < 0:
    raise SystemExit("send() or win_send_keys() not found")

new = '''def game_has_focus():
    """True when the game's window is already the foreground window."""
    hwnd = app_window()
    if not hwnd:
        return False
    try:
        root = user32.GetAncestor(hwnd, 2)
        return bool(adapters._win_input_in_front(user32, root, False))
    except Exception:
        return False


def send(events, attempts=2):
    """Deliver keys only if the game already has focus. Never raises, never focuses, never types elsewhere."""
    if not game_has_focus():
        return False
    for _ in range(attempts):
        try:
            win_send_keys(_pid(), events, polite=False)
            return True
        except RuntimeError as exc:
            if "must be active" not in str(exc):
                raise
            time.sleep(0.15)
    return False


'''
text = text[:old_start] + new + text[old_end:]
path.write_text(text, encoding="utf-8")
print("send() is now focus-gated: it sends only when the game already has focus")
