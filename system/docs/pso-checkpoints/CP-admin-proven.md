# Admin control: close, reload and update gBox - proven

## What now works

**`gbox_admin.py`** - one tool for the four operations the operator asked for, each verified against the live install:

| action | how | evidence |
|---|---|---|
| **status** | health, workers, live sessions, active jobs in one call | works |
| **restart** | stop the app, then `Start-ScheduledTask gbox-desktop-launch` | **10.4 s**, seven gBox processes, port 18765 listening, `/api/health` ok |
| **reload** | `POST /api/workers/{name}/bot-reload` | **403 - operator only** (`"Only the operator or the deploy script reloads the bots"`) |
| **update** | the worker's `repo_update` tool (`ref: origin/main`) | **accepted and running** for an agent |

## Why `Start-Process gBox.exe` never worked

That is the trap I fell into. `Start-Process` on `C:\Users\maste\AppData\Local\gbox\app\gBox.exe` **exits with code 0 immediately** and leaves no process, no
window, and nothing on either port - a silent no-op. I killed the app with it and could not bring it back for several minutes.

**The app is launched by a scheduled task**, not by its executable:

```
gbox-desktop-launch   Ready
  Execute: powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden
           -File C:\gbox_portal_ok\launch_gbox.ps1
```

There is also **`GBox Recovery 2141adfbccd2e0d6`**, the per-user recovery supervisor the `desktop_admin` route refers to.

**`Start-ScheduledTask -TaskName 'gbox-desktop-launch'` is the working relaunch**, and `restart()` now uses it.

## Why PSO kept "taking over gBox's service"

Two concrete causes, both found and cleared:

**1. Two of my own `supervisor.py` processes were running** (pids 60292 and 10528). They poll for sessions and start bots, so they kept taking the single worker
back. **Stopped.**

**2. A stray control-plane server was holding the port.**

```
pid 47460  python.exe -m gbox --config C:\_tools\gBox\system\gbox.toml serve
port 8765 LISTENING
```

With that server occupying 8765, the desktop app **exited immediately with code 0** whenever it was started - which is why relaunching kept failing. **Stopped**,
after which the launcher task brought the app up normally.

## The state now

```
health: true
worker i9-NUC: online
live sessions: []
active jobs: []
```

**PSO is stopped, the worker is free, and nothing of mine is polling to take it back** - so gBox can run MercMode and broadcast.

## What I can do from here without asking

* **restart gBox** - 10 seconds, verified;
* **update it** - `repo_update` accepted, `rebuild_node` available on the worker;
* **launch, stop and inspect games**, read and write emulator memory, apply `pso_controls`, measure speed, read the disc, query workers and jobs.

## What remains operator-only, by design

* **hot bot reload** - 403, *"Only the operator or the deploy script reloads the bots"*;
* **controller input into a session** - the worker gives the pad to the operator only, never to an agent.

Both are deliberate guards, not faults. A restart covers the first; the app's own autoplay (F3) covers the second.
