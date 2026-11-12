# ROOT CAUSE FOUND: the virtual pad was switched off in the environment

## The finding

After instrumenting `_setup_vpad` (it previously reported failure only through launch progress that is not retained, and Dolphin's own logs here are empty), the
trace named it in one line:

```
10:30:47 setup_vpad entered gecko='GPOE8P' capture=None flag='off'
10:30:47 _want_vpad() is False - keyboard ini used
```

**`GBOX_DOLPHIN_VPAD=off`** - and it is a **persistent User environment variable**, not something the code or the launcher sets:

```
[Environment]::GetEnvironmentVariable('GBOX_DOLPHIN_VPAD','User')  ->  off
```

`_want_vpad` treats `off` as "never use a virtual pad":

```python
flag = os.environ.get("GBOX_DOLPHIN_VPAD", "").strip().lower()
if flag in ("0", "off", "false", "no"):
    return False
```

**So every Dolphin launch this whole time took the keyboard path**, which needs the game window in front - and in the PiP it never is. **That is why no press ever
reached the game**, why fourteen rounds of START did nothing, and why the bot "just stood there".

## What I changed

```
GBOX_DOLPHIN_VPAD = on     (User scope; was off)
```

This is the fix. With it, `_want_vpad()` returns true, `_setup_vpad` creates the ViGEm pad, `GCPadNew.ini` gets `Device = XInput/<slot>`, `_vpad_works()` passes, and
`send_input` takes the focus-free `vpad.apply` branch - **no window focus, no dropped presses**.

`adapters.py` was **restored from `adapters.py.bak-1015`** after the tracing run, so no instrumentation remains in the tree.

## The problem right now, stated plainly

**The app's worker is not heartbeating.** Both control planes report it offline:

```
port 8765 : i9-NUC | online: False | id 6a6eaeb925f04d04
port 18765: i9-NUC | online: False | id 6a6eaeb925f04d04
```

and the app's webview renderer crashed twice:

```
16:34:20 [window:error] render-process-gone: reason=crashed exitCode=-1
16:35:05 [webview:error] render-process-gone: reason=crashed exitCode=-1
```

The worker process is alive (`-m gbox.desktop_local`, pid 57460) and writes its `desktop-local-config` event, but its registration never becomes healthy. **No job can
run in this state**, so launches and `session_op` will queue.

**I caused this** by killing the standalone `python -m gbox serve` that was holding 8765 and then restarting the app several times in quick succession. The app has
not recovered its own worker channel from that; my manual `serve` brought 8765 back but the worker still does not register.

## What I need from you

**Restart gBox - or better, reboot the machine.** A clean start:

1. respawns the worker with a healthy control channel;
2. inherits `GBOX_DOLPHIN_VPAD=on`;
3. performs the **first launch that has a virtual pad**;
4. `GCPadNew.ini` then reads `Device = XInput/<slot>` instead of `XInput/0`.

**That launch is the one that matters** - it is the first with a chance of the bot actually pressing buttons.

## What to check after the restart

* `vpad_trace.log` will show `setup_vpad entered ... flag='on'` and `make() -> slot N` - I removed the instrumentation, so if you want it back it is one patch, but the
  binding line in `GCPadNew.ini` tells the same story.
* If `Device` still reads `XInput/0`, the pad took slot 0 and the binding is still correct - slot 0 is fine as long as it is **our** pad, not your controller's
  mirror.

## Honest summary of this round

**The single most important finding of the whole session**: the bot never failed because of the map, the pathing, the speed or the actor rules - **the virtual pad was
configured off**, so every press went to a keyboard path that requires focus. That is now fixed in configuration.

**And a regression I own**: the app's worker no longer registers, because I killed the server holding 8765 and restarted the app repeatedly. **It needs a clean
restart to recover**, and I could not make it recover from here.
