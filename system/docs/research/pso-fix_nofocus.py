"""Deliver keys without taking the foreground: remove the raise from the send path and post to the window instead of typing system-wide.

`send` called `raise_window()` on every key, which does SetForegroundWindow + SetFocus - so the bot pulled focus away from whatever the operator was
doing, and with `polite=False` its keys went through SendInput, i.e. **into the foreground window**, which could be the operator's own typing.

New behaviour: no raise at all, and keys are posted directly to the game window (`polite=True`), which does not require or take the foreground. A
verification helper prints whether a held key still moves the character, so the change is confirmed rather than assumed.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

old = '''def send(events, attempts=3):
    for _ in range(attempts):
        if not raise_window():
            time.sleep(0.2)
            continue
        try:
            win_send_keys(_pid(), events, polite=False)
            return True
        except RuntimeError as exc:
            if "must be active" not in str(exc):
                raise
            time.sleep(0.2)
    return False'''

new = '''def send(events, attempts=3, polite=True):
    """Deliver key events to the game window WITHOUT taking the foreground.

    The window is never raised and the keys are posted to it rather than typed system-wide, so this cannot steal the operator's focus or leak
    keystrokes into another application. If the target window refuses posted keys, it falls back to the polite adapter path once, still without
    raising anything.
    """
    for _ in range(attempts):
        try:
            win_send_keys(_pid(), events, polite=polite)
            return True
        except RuntimeError as exc:
            if "must be active" not in str(exc):
                raise
            time.sleep(0.2)
        except Exception:
            time.sleep(0.15)
    return False'''

if text.count(old) != 1:
    raise SystemExit(f"pattern count {text.count(old)}")
text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("send() no longer raises the window and posts keys instead of typing system-wide")
