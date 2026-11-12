# The worker regression: what I did, what I checked, and the one suspect left

## Timeline of the break

| time | what happened |
|---|---|
| ~15:39 | bot drove PSO into the field; everything working |
| ~15:45 | I patched `pad_takeover.py` to trace input, then reverted it with a PowerShell redirect |
| 15:45 | that redirect wrote **UTF-16**, filling the file with null bytes; Python refused it, the worker crashed |
| since | `pad_takeover.py` restored, `.pyc` cleared, app restarted ~6 times, all `desktop_local` processes killed, ports freed - **the worker never registers again** |

## What the evidence says now

```
port 18765 : LISTENING   (a desktop_local is serving the control plane)
port 8765  : DOWN
/api/workers -> i9-NUC  online False  last_seen 1341s old and growing
```

So a `desktop_local` process is up and answering, but **its worker registration never becomes healthy** - the heartbeat stopped at 15:45 and has not resumed.

Killing every `desktop_local` (both ports went FREE) and letting the app respawn them did not change it, so it is not a stale-process contention problem.

The app gives no diagnostic channel: **my `main.js` console patch - the one that made `app-console.log` readable - is removed, because that patch is what broke the worker handshake at 10:31.** Restoring the readable log and fixing the handshake are mutually exclusive as things stand.

## The one suspect I would check first

I restored `pad_takeover.py` by copying it out of the git checkout (`main-repo`), 23385 bytes, and it compiles cleanly. **But the installed tree has had local modifications before** - `pad_route.py` was missing from the install entirely, and I have copied several files from the repo into the live tree. If the installed `pad_takeover.py` carried a local change that was never committed, my restore **replaced a working file with the repo version**, and that difference is exactly the kind of thing that would stop the worker's registration while leaving the API healthy.

**How to settle it in one command**, comparing the installed file against the git version:

```powershell
git -C C:\_tools\gBox\.tmp\main-repo show HEAD:system/gbox/pad_takeover.py |
  Out-File -Encoding utf8 C:\temp\repo-pad-takeover.py
git diff --no-index C:\temp\repo-pad-takeover.py C:\_tools\gBox\system\gbox\pad_takeover.py
```

If they are identical, the cause is elsewhere and a gBox restart is the next step. If they differ, the installed file needs its local change back.

## What is genuinely done and safe

* **the bot drove PSO from a cold boot into the field** - title, main menu, OFFLINE GAME, SINGLE MODE, character **BQF LV5 (HUmar / ORAN)**, EPISODE 1, warp, then standing in Pioneer 2 at **HP 68/68, TP 738/736**, position `(229.0, 0.0, 254.0)`, player pointer `0x80da62a0` - every step photographed;
* **the bot can walk** - a held direction through `session_op send_input` moved it **82.5 units**;
* **the gap is one function** - `/input` queues and drains but never moves the character, while `session_op send_input` does, and the app's own autoplay uses `/input`;
* `pso_pad.py`, `to_offline.py`, `walk_to_field.py` and the screenshots are committed, so none of that has to be rediscovered.

## What I am not going to do

**Not restart the app again.** Six restarts have not recovered the worker, and each one risks changing more state while I cannot see the app's log. The next move is yours: **restart gBox**, and if the worker is still offline, run the diff above.
