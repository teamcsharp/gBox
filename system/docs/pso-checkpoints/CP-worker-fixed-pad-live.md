# The worker is fixed, the virtual pad exists - and the title still does not advance

## Win 1: the worker was broken by my own `main.js` console patch

After the machine reboot the app was healthy but the worker still never sent `ready`. The only `main.js` change on this machine is mine - the commit that made the
server output readable added `CONSOLE_FILE`, an `appendFileSync` inside `logPush`, and **a wrapper around `console.log/warn/error`**.

I restored `main.js` from git at the commit's **parent** (`ec73b7a6^`) and restarted:

```
+  5s health=True workers=[('i9-NUC', True)]

VERDICT: the worker registers with the pre-patch main.js - my console patch was the cause
```

**The worker came online in five seconds.** Everything from 10:31 onward - the queue that never dispatched, the "no online worker", the launches that hung - was my
console patch interfering with the Electron main process's worker handshake. The pre-patch file is now installed and the patched copy is kept at
`main.js.bak-prepatch-test`.

**This is the regression I owned, and it is now identified and fixed.**

## Win 2: the virtual pad exists and is bound correctly

With `GBOX_DOLPHIN_VPAD=on` in place and a working worker, a fresh launch produced:

```
XInputGetState:
  slot 0: connected  buttons=0x0000  lx=0 ly=0 lt=0 rt=0     <- a pad at rest, not the operator's controller
  slot 1..3: absent

GCPadNew.ini:
  [GCPad1] Options/Always Connected = True   Device = XInput/0/Gamepad
```

**The pad is on slot 0 at neutral and the config binds slot 0.** Before the environment fix, `_want_vpad()` returned false and the keyboard INI was written instead. **That
fix is confirmed working.**

## What still does not work

Presses do not advance PSO's title, through **either** path:

* `PUT /api/sessions/{sid}/input` (the HTTP queue) - START and A, 14 rounds, no change;
* `session_op` with `op: send_input` (straight to the adapter's `send_input`, which takes the `vpad.apply` branch) - 10 presses, no change.

So the hardware path is right and the presses still do nothing visible.

## What I could not determine, and why

**I could not see the screen**, which is what would settle it:

* `session_op` `op: get_frame` **works** and returns a PNG, but the job output is **truncated to 200 characters** - too short to decode;
* `op: screenshot` is **refused**: `ValueError: op screenshot not allowed via session_op`;
* reading the MJPEG stream directly produced no JPEG.

**The game counter at `0x805D53A4` does not advance at the title** (`2649 -> 2649`). That may simply be a game-level counter that only ticks in gameplay, so it does
**not** prove a freeze - and the emulator is definitely alive: pid **25640**, process name **`gBox Dolphin`**, `runtime: PLAYING`. (My earlier `Get-Process Dolphin*`
missed it because the process is named `gBox Dolphin`.)

`resume` succeeded and `pause` exists but takes no arguments, so the pause state is not obviously the cause.

## The next step, precisely

**Get one frame out of the emulator intact.** The frame exists - `get_frame` returns it - the only problem is the 200-character output cap. Any of these settles it:

* raise or bypass the job output cap for that one op;
* a worker-side op that writes the frame to a file (as `screenshot` does) and returns the path;
* the web client's own stream, which renders the same frames.

Once the screen is readable, the title's requirement is a matter of reading it: a "press START" prompt, a memory-card prompt, or an error dialog each need a different
answer, and right now that is a guess rather than a measurement.

## State

* **worker online** (`i9-NUC`), app healthy, `GBOX_DOLPHIN_VPAD=on`, pad bound to `XInput/0`;
* one live session, PSO at the title, emulator process alive;
* memory card `i9-NUC · recovered local A` exists and parses (`free_blocks: 2010 / 2043`).
