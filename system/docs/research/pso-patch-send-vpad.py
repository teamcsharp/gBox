"""Route the bot's input through the plane's send_input, which uses the virtual pad when it exists.

This is the whole mechanism, read out of the code:

```python
# adapters.py, the Windows Dolphin adapter
if self.vpad is not None and self._vpad_works():
    return self.vpad.apply(events)          # focus-independent XInput pad
...                                          # otherwise the keyboard path
```

and `_setup_vpad` has a documented failure mode that matches this session exactly: *"ViGEm releases the previous session's pad asynchronously, so a
launch right after a stop can fail to create one ... `_setup_vpad` returned None, the INI fell back to the keyboard, and **every gBox press was
silently dropped for the whole session**"*.

So the bot must not send keys itself at all: `win_send_keys` is the *keyboard* branch, the one that is dropped. The plane's own `send_input` is the
branch that reaches the pad, so `send` now goes through the session RPC. That also removes the focus dependency entirely - the pad is polled every frame
whether or not the window is focused - so the focus gate in `send` goes with it.

Kept deliberately narrow: the events are the same `[{key, down}]` rows as before, so every caller of `send` keeps working unchanged.
"""
import pathlib

path = pathlib.Path(r"C:\_tools\gBox\.tmp\game_input.py")
text = path.read_text(encoding="utf-8")

start = text.find("def send(")
end = text.find("def win_send_keys(")
if start < 0 or end < 0:
    raise SystemExit("send() block not found")

body = '''def send(events, attempts=2):
    """Deliver input through the plane's send_input, which uses the virtual XInput pad when one exists.

    The keyboard branch (`win_send_keys`) is only reached by the plane when no working pad exists, and that is the branch whose presses are silently
    dropped on this machine. Going through the RPC means the bot uses whichever branch the plane has working, and needs no focus either way.
    """
    import session as S
    rows = [{"key": str(event.get("key")), "down": bool(event.get("down"))} for event in events
            if event.get("key")]
    if not rows:
        return False
    for attempt in range(attempts):
        try:
            S.rpc("send_input", {"events": rows}, timeout=30)
            return True
        except Exception as exc:                                  # noqa: BLE001
            message = str(exc)
            if "must be active" in message or "isn't open" in message:
                time.sleep(0.15)
                continue
            if attempt == attempts - 1:
                raise
            time.sleep(0.15)
    return False


'''
text = text[:start] + body + text[end:]
path.write_text(text, encoding="utf-8")
print("send now routes through the plane's send_input (the virtual-pad branch)")
