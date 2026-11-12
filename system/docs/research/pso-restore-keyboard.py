"""Restore the keyboard path: `win_send_keys` is the one that reaches the game.

The mirror test settles it:

```
slot 0: connected buttons=0x0000   <- before, during and after a bot START press
VERDICT: the mirror does NOT carry the bot's press - it only reflects the operator's pad
```

So this chain is a dead end:

```
game_input.send -> session_op -> padstate.report -> control plane -> the pad mirror
```

The mirror exists so that **the operator's physical controller** drives a remoted session. The bot's events are posted to the control plane and never become a
pad a game reads. **My round-8 change routed all input there** - and that is why, from round 8 onward, no press ever reached a game, while the keyboard path in
round 22 had already walked the bot through Forest 1.

`win_send_keys` sends real key events to the window that forwards them into the emulator. It needs the game (or gBox) to be active - which is the documented,
intended behaviour, and the reason the game must be in front for the bot to play. That constraint is real; it is also the only path that works.

So `send` goes back to the keyboard:
  * target the window `app_window()` finds (the gBox window that relays, or the emulator's own);
  * keep the batched `[down, up]` rows, so one call is still one gesture;
  * report False when the relay refuses (no active window), so failures are visible.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() block not found")

body = '''def send(events, attempts=2):
    """Deliver input as real key events to the window that relays them into the emulator.

    This is the path that works: `win_send_keys` sends key events, and the app forwards them into the game. The `session_op`/padstate route does not carry bot
    input at all - the mirror only reflects the operator's physical pad, proven by reading XInput around a press and seeing no button change.

    It requires the game (or gBox) to be the active window, which is inherent to this path and is why the game must be in front.
    """
    hwnd = app_window()
    if not hwnd:
        return False
    target = _owner_pid(hwnd)
    for attempt in range(attempts):
        try:
            win_send_keys(target, events, polite=False)
            return True
        except RuntimeError as exc:
            message = str(exc)
            if "must be active" not in message and "isn't open" not in message:
                raise
            if attempt == attempts - 1:
                return False
            time.sleep(0.15)
    return False


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("send is back on the keyboard path")
