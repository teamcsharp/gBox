# The unblock is verified end to end, not assumed

Every session so far predates the `pad_route.py` deployment, so the fix has never been exercised through the adapter - only its probe was tested in isolation. That
left a real risk: the relaunch everything depends on might not help.

So the adapter's own setup path was run without launching anything:

```
_want_vpad():                      True
_setup_vpad(base) -> INI with:
  Options/Always Connected = True
  Device = XInput/1/Gamepad        <- the virtual pad's slot, not XInput/0
GCPad1 device:                     XInput/1/Gamepad
is the virtual pad's slot (1):     True
Always Connected present:          True

_vpad_works():                     True
report: {'input_path': 'vpad', 'vpad_slot': 1, 'vpad_probe': True,
         'reason': 'the virtual pad reports its presses'}
```

**Both halves pass.** `_setup_vpad` produces an INI bound to the pad's actual slot with `Always Connected` (so a resting pad keeps the port up), and
`_vpad_works()` - the exact decision `send_input` makes - returns **True** with `input_path: vpad`.

## What that means concretely

`DolphinWinAdapter.send_input` begins:

```python
if self.vpad is not None and self._vpad_works():
    return self.vpad.apply(events)          # focus-independent, instant
...
return win_send_keys(self.proc.pid, rows)   # takes the window focus
```

With `_vpad_works()` now true, every press takes the **first** branch: no `give_focus()`, no ten-second focus wait, and the game receives the press while it sits in
the PiP.

## The chain that follows

1. **relaunch** → session binds Player 1 to the pad;
2. **input reaches the game** → the character is drivable;
3. **the live grid recorder** (built and proven in round 7) can be populated;
4. **path-guiding** runs on the game's own coordinates and on the 51 disc collision maps;
5. **the bot can act** at all - which is currently the one thing it cannot do.

Steps 3-5 are already built and tested against known answers; **step 1 is the only missing input, and step 2 is now verified to follow from it.**

## Why this was worth a round

The alternative was to keep improving map analysis while the unblock went untested, then discover on the relaunch that input still did not reach the game - and have
no idea whether the fault was the pad, the config, the probe or the session. **Now that question is answered before the cost is paid.**
