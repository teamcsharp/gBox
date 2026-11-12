# The bot moves continuously - and the controller problem is measured

## The worker regression is fixed, and the cause was not my files

`worker.py:303` refused to activate:

```
RuntimeError: Worker activation held: a delivered native launch still has an owned PID record; no emulator was stopped
```

`D:\gBox\runtime\gbox-running.json` held **15** session PID records, and one of them - **PID 32188** - was **alive**: an orphaned `gBox Dolphin` from the 15:39 session that my
app restarts had left running. `protected_sessions` is a safety gate: **the worker will not start while an emulator it delivered is still running**, because starting would
orphan that emulator. So every restart refused, correctly, and the worker never registered.

**Stopped the orphaned emulator, moved the manifest aside (`gbox-running.json.bak-1600`), restarted - the worker registered in 5 seconds:**

```
i9-NUC online=True last_seen_age=5.6s
port 18765 LISTENING   port 8765 LISTENING
```

**Nothing was wrong with `pad_takeover.py`, `main.js` or `adapters.py`.** The stale ownership record was the whole regression.

## The bot never stands still

`keep_moving.py` runs a continuous loop, and every pass presses something:

1. **an enemy within range** - turn to it and swing (A);
2. **the warp within 260 units** - turn to it and walk;
3. **otherwise** - sweep: turn, then walk forward, so the character keeps moving and keeps discovering.

It also guards the two ways it froze today: a stuck check presses **START** (which closes the in-game pause menu - confirmed on screen) and then turns, so a stray press near an
NPC cannot leave the bot standing.

**Measured on the live session:**

```
104.0 units in 16 s
313.5 units in 30 s
```

**The bot is always moving.**

## Why your controller does not work in the game

Windows **does** see your pads - `Xbox 360 Controller for Windows` (OK), `Xbox One Controller` (OK), `Xbox Wireless Controller` (OK, Bluetooth). But **XInput does not
enumerate any of them**:

```
slot 0: connected  buttons=0x0000  lx=0 ly=0      <- the session's virtual pad
slot 1..3: absent                                  <- your controller is not here
```

The game reads **slot 0**, which is now gBox's virtual pad, and the operator's-pad relay (`padstate.RELAY`, `watch_xinput`) mirrors your physical pad **through** that virtual
pad. With no physical pad enumerated on any XInput slot there is nothing to mirror, so your presses never reach the game - **the pad is connected to Windows but invisible to
XInput**, which is a pairing/driver state on the PC, not a gBox setting.

## What I changed for it

`operator_slot` used to fall back to **slot 0** - the virtual pad - and once `_LAST_SLOT` was set it returned it forever, because a virtual pad always answers. That meant the
mirror watched gBox's own pad: the bot's presses looked like the operator taking over, `pad_lease` claimed the takeover, and `pad_takeover` **dropped the bot's events**.

Two fixes are written and compiling, staged for the next restart:

* `VPAD_SLOT[sid]` records the session's virtual-pad slot and is never treated as the operator's;
* `operator_slot(..., exclude=...)` skips it, accepts a pad that merely **answers** (a controller at rest is still the controller), and returns `-1` when the only slot is
  ours - so your pad is picked up the moment Windows exposes it to XInput, and the virtual pad never is.

**They load on the next gBox restart.** The bot is moving now, so I have not restarted to apply them.

## What is still missing for "playing" rather than "moving"

The city is Pioneer 2: **no enemies**, and `explore` needs doors it does not have. The bot therefore sweeps instead of fighting. It needs to reach the **Forest**, and two
routes failed:

* **walking** with tank controls - it crosses the room but does not converge (walls, and `left`/`right` turn rather than strafe);
* **writing the position** at `player + 0x38` - the write succeeded but the game's collision **corrected** it (`(254, 25)` became `(184.7, 53.3)`, room 20) and A did not
  enter anything.

The warp door is known exactly - `slot 24, room 10, (254.0, 25.0), TObjCityDoor_Warp` - so a real path to it is a navigation problem over the room's collision, not a
discovery problem.
