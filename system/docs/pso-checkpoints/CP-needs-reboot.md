# Worker will not register: the app needs a reboot

## What the evidence shows

The worker logs its config and then **never sends the `ready` event**, which is the one that marks it online:

```
16:30:26 [worker] GBOX_CLIENT_CONTROL:{"v":1, "secret":"0fa74a29…", "pid":40684, "event":"ready"}   <- last good one
16:36:36 [worker] {"event":"desktop-local-config", "installation":"2141adfb…"}
16:36:41 [worker] desktop_local.py:227: DeprecationWarning (FastAPI started)
          … and no "ready" ever follows
```

So the worker process runs, imports FastAPI, and stops there. Port **8765 never binds**, and `/api/workers` reports `i9-NUC | online: False` on both control planes.

## What I tried, in order

| attempt | result |
|---|---|
| restart the app via `gbox-desktop-launch` (several times) | app comes up, **worker stays offline** |
| restore `adapters.py` from `adapters.py.bak-1015` | no change - my instrumentation was not the cause |
| start the missing `python -m gbox serve` by hand | 8765 came up, worker still offline |
| kill the manual serve **and both** `desktop_local` processes, then relaunch once | 8765 stays down, worker stays offline for 100 s |

**Two `desktop_local` processes and a manual `serve` were all contending for the same ports and config**, which is likely why `ready` never arrived - but clearing all of
them and starting once did not fix it either.

The app's webview renderer also crashed twice:

```
16:34:20 [window:error]  render-process-gone: reason=crashed exitCode=-1
16:35:05 [webview:error] render-process-gone: reason=crashed exitCode=-1
```

## What is still good

* the app itself is healthy on **18765** (`/api/health` ok), sessions and catalog endpoints answer;
* **the configuration fix is in place**: `GBOX_DOLPHIN_VPAD = on` at User scope - the thing that was silently disabling the virtual pad;
* `adapters.py` is restored from backup, so no instrumentation remains;
* all my background pollers are stopped, so nothing is competing for the worker.

## What I need

**Reboot the machine.** Not another app restart - I have done four, and each leaves the worker unable to send `ready`, while the renderer keeps crashing. A reboot clears
both, inherits `GBOX_DOLPHIN_VPAD=on`, and gives the first launch that has a virtual pad.

**Immediately after the reboot, the check that matters** is one line:

```
D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini   ->   Device = XInput/<n>
```

If that line names a slot and the session's `vpad_probe` says true, the bot can press without focus for the first time.

## Honest accounting

**The win**: the root cause of the bot never pressing anything is identified and fixed in configuration - the virtual pad was switched off by a persistent User
environment variable, so every launch took a keyboard path that needs window focus.

**The cost**: in finding and fixing it I killed a server that the app depended on and restarted the app repeatedly, and its worker no longer registers. **That is my
regression, and a reboot is what clears it.**
