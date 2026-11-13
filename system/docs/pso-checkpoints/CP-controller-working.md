# Your controller works, and here is why it kept dying

## The root cause of "I still can't use my controller"

Two infrastructure faults, neither in the controller code:

1. **The gBox app was DOWN** - `httpx` to `127.0.0.1:18765` raised `ConnectError`. With no app there is no API, so no session, no input path and no relay target. That is why the UI felt dead.
2. **An orphaned `gBox Dolphin` (PID 36268) was still recorded in `D:\gBox\runtime\gbox-running.json`**, and a live orphan blocks the worker from activating. The manifest even had a second, stale entry (PID 34128) from an earlier session. **A worker that will not come online cannot accept input.**

Recovery was: kill the orphan, move the manifest aside (`gbox-running.json.bak-2301`), restart gBox. Health returned `200`, a session launched immediately, and the relay bound to it.

**This is the same failure mode that bit twice earlier in the session** and the rule is unchanged: **stop the session before restarting gBox**, or the emulator is orphaned and takes the worker down with it.

## And now the controller is genuinely driving the game

```
relay session: 4b8bf1e855324f89-2dc1989a17dc4318
relay watching 'Xbox 360 Controller'
  relayed 5 event(s): ['up', 'down', 'left', 'right', 'up']
  relayed 5 event(s): ['up', 'down', 'left', 'right', 'left']
  operator idle - bot may resume
```

and the bot yielding every time:

```
[23:05:12]   operator is playing - bot standing down
[23:05:22]   operator is playing - bot standing down
[23:05:30]   operator is playing - bot standing down
```

**and the character under the operator's control**, sampled while they played:

```
 1: pos (485.3,  -13.5) | room 8 | hp 68
 2: pos (511.0,  -29.3) | room 8 | hp 68
 3: pos (515.6,  -79.9) | room 8 | hp 68
 6: pos (547.0,  -70.8) | room 8 | hp 68
 7: pos (577.2,  -83.5) | room 8 | hp 68
 8: pos (611.1, -102.8) | room 8 | hp 68
```

**130+ units of travel, driven by the pad, with the bot standing aside.**

## The notes channel also worked in the same run

```
[23:05:07]   NOTE from operator: kill the wolves in this room
[23:05:07]   note internalized: prioritising enemies
```

Read from `D:\gBox\pso-ds\operator-notes.txt` on the iteration after the warp completed, echoed, classified as `fight`, and stored - the note is in effect.

## What to expect now

* **Move the stick or press a button: within a fraction of a second the bot stands down** and your input goes to the game.
* **Stop for four seconds: the bot resumes** and plays on.
* **Type a note in `operator-notes.txt`**: it is picked up next iteration, echoed in the log as `NOTE from operator: ...`, and acted on.

## Standing gaps

* **The UI text box** for notes does not exist yet - the file is the channel for now, and the plumbing behind it is proven.
* **The aggro switch** still needs the Ghidra work; the enemy struct has no field that flips on aggro, so the AI controller has to be read out of the binary.
* **Ultimate** is selected automatically only once `hp_max` passes 250; at 68 the bot plays Normal where it can actually kill.
