# Goal round 6: the root cause - the game is launched with a GC KEYBOARD on port 1

## The evidence

The launch line the app builds contains:

```
-C Dolphin.Core.SIDevice0=6
```

`6` is Dolphin's **`SIDEVICE_GC_KEYBOARD`**. So controller port 1 is a **GameCube keyboard**, not a controller - and **the keyboard device is exactly the
path that has not worked for four rounds**.

That single value explains everything measured so far:

* **no keyboard delivery reaches the game** - virtual keys, scancodes, every target window, focused and unfocused. The device is a keyboard, but it is
  not receiving;
* **the operator's controller still works** - because the app forwards it through its own path, not through dolphin's port-1 device;
* **the game is otherwise healthy** - 80 threads, CPU active, in the field, 91 entities, responding.

## The virtual pad, proven working, and its slot

`XInputGetState` on all four slots:

```
before the bot's pad:   slot 0 connected   slot 1 connected   slot 2 not   slot 3 not
after creating vpad:    slot 2 CONNECTED
while pressing A+up:    slot 2  buttons=0x1000  LY=32767   -> A down, stick up
```

So the bot's pad is a **real XInput device**, visible to any poller, on **slot 2** (slots 0 and 1 are the operator's two controllers).

The emulator's own config bound controller port 1 to **slot 1** - one of the operator's controllers - so the bot's pad was never read.

**That is now fixed**: `GCPad1` reads `XInput/2/Gamepad`, with a backup (`GCPadNew.ini.bak-before-slot2-193728`) so it is reversible in one copy.

## What that leaves

Two settings decide whether the bot can drive, and they must agree:

| setting | who controls it | state |
|---|---|---|
| `GCPad1` device | the config file | **done: XInput slot 2 (the bot's pad)** |
| `SIDevice0` (the port-1 device type) | **the app's launch options** | **6 = GC keyboard - must become a standard controller (1)** |

With port 1 declared a **keyboard**, Dolphin never reads `GCPad1` at all, so the slot fix alone cannot take effect. **The app must launch with a standard
controller on port 1** - after which `GCPad1` = `XInput/2/Gamepad` is the bot's virtual pad, and the bot drives the game the way a controller does, with no
keyboard and no focus.

## Why this is the answer and not another guess

It is the only explanation consistent with **all** the measurements at once: a keyboard device that receives nothing, a controller path that works, a
healthy emulator, and an input path that ignores every encoding. It is also independently verifiable - the launch line states it in plain text.

## State

| item | state |
|---|---|
| root cause | **`SIDevice0=6` = GC keyboard on port 1** |
| bot's virtual pad | **working and visible on XInput slot 2** |
| `GCPad1` | **rebound to slot 2**, backed up |
| needed | **launch with a standard controller on port 1** |
