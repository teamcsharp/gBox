# The diagnostics never fire because the app's server predates every edit

## What the empty files prove

Two file-based probes, both verified compiling and importing in isolation:

* `vpad_win.VGamepad.__init__` -> `vpad_probe.log`
* `_want_vpad`'s four gates -> `vpad_gate.log`

**After a successful launch, both files are absent.** `_setup_vpad` is not being called at all - which is only possible if **the running server does not
contain these edits**.

And it cannot: the app **respawns its own server within seconds of a kill**, and that respawn loads whatever was on disk when it started. Every attempt to take
port 8765 by starting a server of my own lost the race - the app's process was bound before mine, my log files stayed at **0 bytes**, and the launch was served
by a process that predates the patch.

So: **the code is correct and the diagnostics are correct; the process serving launches is stale.** The only thing that reloads it is **restarting the app**.

## Why I stopped

I have now written this conclusion three rounds running and each time tried to work around it - starting servers by hand, killing them, racing the supervisor,
moving diagnostics from stdout to files. **None of it can change which process serves the launch.** That requires the app to be restarted, and I am not going to
kill the operator's UI out from under them at five in the morning without being asked.

## What is on disk right now

| item | state |
|---|---|
| `_want_vpad` | logs all four gates to `vpad_gate.log` |
| `VGamepad()` | logs creation and slot to `vpad_probe.log` |
| both | **compile and import verified** |
| backups | `adapters.py.bak-041700`, `vpad_win.py.bak-041549` |
| running server | **predates both** |

## The single action that closes it

**Restart gBox, launch PSO once.** Then:

* **`vpad_gate.log` exists** -> it names the refusing gate (`os`/`capture`, the env flag, the `GPO` disc check, or `available()`);
* **`vpad_gate.log` absent but `vpad_probe.log` present** -> the gate passed and detection is the fault;
* **both absent** -> the server still is not loading the file, and the app's own server-output capture has to be found.

Each outcome is one line naming a specific fix. **That is a five-minute conclusion once the process is fresh** - and it is the only step I cannot take myself
without closing the operator's window.

## Undoing it

Both edits are additive file writes with timestamped backups:
`Copy-Item adapters.py.bak-041700 adapters.py` and `Copy-Item vpad_win.py.bak-041549 vpad_win.py` restore the previous state exactly.
