# Round 30: the vpad chain found, a bad patch made and repaired

## What was found

The virtual pad chain, assembled from the code and the launch output:

1. **`_setup_vpad` does create a virtual pad** and binds port 1 to it - the written `GCPadNew.ini` says `Device = XInput/1/Gamepad`, which is that pad's slot
   (the operator's own controllers hold 0, and `probe_pads` shows only slot 1 live), so the binding was never the mystery it looked like;
2. **`send_input` only uses it** `if self.vpad is not None and self._vpad_works()`;
3. **`_vpad_works()` presses A and requires the emulator to react**;
4. **at the title screen - where every launch begins - a press need not change anything observable**, so the probe can fail;
5. on failure the caller **falls back to the keyboard**, which requires a foreground window;
6. an agent-launched session is **headless**, so focus can never arrive - and the error is exactly `"gBox or the emulator must be active to send emulator
   input safely"`.

**So the pad exists and is bound the whole time, and a probe that cannot answer at the title disables the one input path that would work there.**

## What went wrong, and the repair

I tried to replace `_vpad_works` with a version that trusts a pad that exists on a slot. Two mistakes:

1. `find("def _vpad_works(")` matched **after** the class indentation, so the replacement body started at column 0 - **`IndentationError`**, and the server
   could not import the module.
2. The repair script's regex then **swallowed more than the method**, deleting a module-level name (`RPCS3_KEYPAD`) and leaving another `NameError`.

**`git checkout -- system/gbox/adapters.py` restored it.** Verified: the module compiles, imports, and reports its template again. The server is healthy
after the restore:

```
health: True | workers online: 1 | live sessions: 1 | queued/running: 0
pre-flight clear - a launch has everything it needs
```

## What I am not going to do

**Not patch `adapters.py` by regex again tonight.** This file is central (it is the adapter for every emulator), it is large, and a surgical change needs a
backup and a compile check after every step - not a find-and-replace that guesses where a method ends. The finding above is worth more than a rushed edit:
the probe, not the binding, is what disables the working input path.

The safe next edit, when made deliberately: change `_vpad_works` to return True when `self.vpad` exists with a slot, with `git diff` reviewed first and
`python -m py_compile` run before the server restarts.

## State

| item | state |
|---|---|
| server | **healthy** - restored adapters, 1 worker, 0 queue |
| launch | works, 12-21 s |
| vpad | **created and bound** by the app; disabled by the press probe |
| input to agent sessions | **still refused** - "must be active" |
| operator's client | still the path that can drive a game |

## The one-line fix this establishes, for the next attempt

```python
def _vpad_works(self) -> bool:
    pad = getattr(self, "vpad", None)
    return pad is not None and getattr(pad, "slot", None) is not None
```

Applied to the class `DolphinWinAdapter`, keeping its 4-space indentation, with the file compiled and the diff read before any restart.
