# Goal round 8: the plane's own virtual pad, and the documented failure that explains this session

## The mechanism, read out of the adapter

```python
# gbox/adapters.py, the Windows Dolphin adapter
def _setup_vpad(self, pad_base):
    """Put Player 1 ... on focus-independent virtual XInput pads (gbox/vpad_win.py) ..."""
    ...
    (user / "Config" / "GCPadNew.ini").write_text(vpad_ini)

# and at input time:
if self.vpad is not None and self._vpad_works():
    return self.vpad.apply(events)          # focus-independent XInput pad
...                                          # else: the keyboard path
```

`vpad_win.py`'s own docstring states the reason it exists, and it is word for word the problem this session has been fighting:

> *"gBox's keyboard input (`win_send_keys`) is delivered with `SendInput` and only reaches the game while the Dolphin window owns the
> foreground/focus ... A virtual **XInput** pad sidesteps focus entirely: Dolphin's XInput backend polls it every frame with
> `Dolphin.Input.BackgroundInput=True` whether or not the window is focused, exactly like a real controller plugged into the PC."*

And `_setup_vpad` documents the exact failure that matches every measurement here:

> *"ViGEm releases the previous session's pad asynchronously, so a launch right after a stop can fail to create one ... `_setup_vpad` returned None,
> the INI fell back to the keyboard, and **every gBox press was silently dropped for the whole session**."*

That is this session: the INI on disk read `Device = XInput/1/Gamepad` - the operator's controller, **no "gBox's virtual pad" comment** - so the
plane's `send_input` took the **keyboard** branch, and every press was accepted and dropped. It explains the zero movement across every method, on every
target, in both encodings, with focus and without.

## What was changed

**`game_input.send` no longer sends keys itself.** It calls the plane's `session_op send_input`, which is the branch that uses the virtual pad when one
exists. Sending keys directly was always choosing the keyboard branch - the broken one.

```python
def send(events, attempts=2):
    rows = [{"key": ..., "down": ...} for ...]
    S.rpc("send_input", {"events": rows}, timeout=30)
```

**`pso_input.allowed()` no longer requires focus.** The gate existed because keyboard presses only land while the game owns the foreground; the pad is
polled every frame regardless. It keeps what still matters: **the operator's pad wins**.

**A verifier (`verify_launch.py`)** answers the two decisive questions on the next launch, with evidence:

1. does `GCPadNew.ini` contain `# gBox: Player 1 bound to XInput slot N (gBox's virtual pad)` - i.e. did the app's pad get created, or did it fall
   back to the keyboard INI;
2. one held direction through `send_input`, and the measured displacement.

## State

| item | state |
|---|---|
| root cause | **`_setup_vpad` fell back to the keyboard INI**, whose presses are dropped |
| input path | **routed through the plane's `send_input`** (the vpad branch) |
| focus requirement | **removed** - the pad does not need it |
| verifier | written, prints both the INI evidence and the movement |
| supervisor | one instance running (a duplicate was stopped), still waiting |
| next launch | **verifier runs first**: pad created? movement? |
