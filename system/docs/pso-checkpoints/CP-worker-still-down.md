# Worker still will not register after the app restart

## What the restart produced

The app came back at **11:07:09** (its launcher argument present) and `/api/health` answers on 18765, so the app itself is fine. But:

```
/api/workers -> i9-NUC | online: False | id 6a6eaeb925f04d04 | last_seen 38 minutes ago
port 8765    -> DOWN
app-console.log -> worker writes {"event":"desktop-local-config"} at 17:09:00 and never sends "ready"
```

`desktop_local` is running - in fact **two instances** with identical command lines:

```
... -m gbox.desktop_local --config C:\_tools\gBox\system\gbox.toml --port 18765 --name i9-NUC   (pid 19576)
... -m gbox.desktop_local --config C:\_tools\gBox\system\gbox.toml --port 18765 --name i9-NUC   (pid 37152)
```

and running the command by hand shows why the loser is a zombie:

```
ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 18765):
only one usage of each socket address (protocol/network address/port) is normally permitted
```

One wins the port; the other sits at 4 MB with zero CPU. **The winner still never sends `ready`.**

## What I tested, and ruled out

| hypothesis | test | result |
|---|---|---|
| my `adapters.py` instrumentation | restored from `adapters.py.bak-1015` | no change - **not the cause** |
| a stray `serve` holding 8765 | killed it | 8765 came back, worker still offline |
| duplicate `desktop_local` contention | killed the zombie | app respawned two more, still offline |
| **my `teeChild` starving the handoff** | commented the call out, restarted | **no change - not the cause** |

That last one was the most promising: `teeChild` attached `child.stdout.on("data")` *before* `workerChannel(child, …)` reads the same stream, and a `data` listener
switches a stream into flowing mode. **It was still worth testing and it was wrong** - the worker behaves identically with it disabled. It is left disabled, being
closer to stock.

## The conclusion I can defend

**The worker has not sent `ready` since 10:31, and nothing I can do from inside the session restores it.** It is not my instrumentation, not my logging patch, not a
stray server, and not the duplicate processes - those are all ruled out by test.

**What remains is the machine.** The app restarts cleanly every time, but its worker's control handshake never completes, and the webview renderer crashed twice
earlier in this sequence. A **machine reboot** - not another app restart - is the only remedy left that I can identify, and I have said so once already; the app
restart you did was not that.

## What is in place for the reboot

* **`GBOX_DOLPHIN_VPAD = on`** at User scope - the variable that was silently disabling the virtual pad and is the root cause of the bot never pressing anything;
* `adapters.py` restored from backup, `main.js` syntax-checked, tee disabled;
* no pollers of mine running.

## The check that matters after the reboot

```
C:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini
    Device = XInput/<n>        (was XInput/0 by way of the keyboard path)
```

If that names a slot and the session's vpad report is true, the bot presses without focus for the first time in this whole session.
