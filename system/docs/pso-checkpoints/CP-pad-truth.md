# Why the bot cannot press anything: no virtual pad, and the operator's stick claims the pad

## What the hardware actually shows

```
XInputGetState available: True
  slot 0: connected  buttons=0x0000  lx=-316 ly=689 lt=0 rt=0
  slot 1: absent
  slot 2: absent
  slot 3: absent

[GCPad1] Options/Always Connected = True   Device = XInput/0/Gamepad
log: padstate: mirroring the operator's pad on XInput slot 0
```

Two facts follow directly.

**1. There is no virtual pad.** Slots 1-3 are **absent**, so `_setup_vpad` did not produce a pad for this session. `Always Connected` in the INI came from the co-op path,
not the vpad path. Without a vpad, `send_input` falls back to `win_send_keys`, which needs the game window in front - and in the PiP it is not. **That is why twelve
START/A presses moved nothing.**

**2. The operator's controller is on slot 0 with its stick pushed** - `lx=-316, ly=689`, far from neutral. PSO reads slot 0. And `pad_takeover` gives the pad to the
operator the moment their controller moves:

```python
def local(sid, keys, *, now=None):
    ...
    return lz.local_state(set(keys), now)      # a new press or a held stick claims the lease
```

While that lease is active, `inputs()` **drops the bot's events**:

```python
if lz.active(now):
    return [e for e in events if not bot_event(e)]
```

So a held controller suppresses every bot press by design.

## What this means

The bot is **not** blocked by a missing feature or by my code. It is blocked because:

* **no virtual pad exists on this PC right now**, so the only input path is the keyboard, which needs focus;
* **and the operator's controller holds the pad lease**, which suppresses bot events even when they would otherwise arrive.

## What actually works - and it was measured

**The app's own autoplay injects inside the worker**, so it is not subject to either restriction once the game is in gameplay. That is what moved the character
**258 units** in an earlier round, on a session where a character was already in the field.

So the sequence that works is:

1. **get into the field** with a character standing in an area;
2. **let go of the controller** - a held stick claims the pad and the bot lets go;
3. **autoplay plays** (F3, or the `autoplay` tool on a session the operator owns).

## Why the virtual pad is missing, and what would fix it

`_setup_vpad` was verified working in isolation (round 10: `_want_vpad()` true, `Device = XInput/1/Gamepad`, `_vpad_works()` true). At launch it produced nothing here -
slots 1-3 absent. The most likely cause is a **ViGEm slot conflict with `padstate`**, which already mirrors the operator's pad onto slot 0.

That is the next thing to fix, and it is a real one: with a working vpad the bot could press without focus and without the operator's controller mattering. But it is
**not** what blocks the bot today - the operator's own autoplay path already works once the game is in the field.

## State

* **0 live sessions** - the worker is free for MercMode to broadcast;
* the app is healthy, the worker online, no jobs queued;
* the bad PSO jump state is retired, so the next launch boots normally instead of landing on a menu.
