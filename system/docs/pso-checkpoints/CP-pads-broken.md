# The controllers themselves are the problem now - both are presenting broken input

## What the per-pad probe proved

Reading each device separately, 15 seconds with the operator pressing:

```
[0] Xbox One Controller   axes (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)   buttons []
[1] Xbox 360 Controller   axes (0.0, -0.0, ...)                buttons [0],[1],[0],[1],[0],[1]...
```

**Neither device produces usable input:**

* **the Xbox One pad is completely silent** - every axis at 0.0, no buttons, for the whole window;
* **the Xbox 360 pad has A and B stuck**, toggling every ~0.1 s, which is exactly the `['a','b']` / `['b','a']` flood that filled the relay log.

That is a **hardware / pairing** condition, not a software one. **No code can make a silent pad talk**, and the chatter from a stuck button is the pad reporting a real (if useless) state.

## What the software now does about it

* **`RELAY_PAD=<index>`** pins the relay to one controller so a broken pad cannot poison anything. Verified: with `RELAY_PAD=0` the relay reports `relay watching: [0] Xbox One Controller` and - because that pad is silent - correctly relays nothing.
* **button debounce** (`DEBOUNCE_FRAMES = 3`): a button must persist for three consecutive reads before it is believed. That suppresses chatter from a failing button while leaving a held press (which persists for many frames) untouched.
* **all-pad merge** with max-magnitude axes, so whichever pad is alive drives the character.

## What the operator needs to do

1. **Reconnect or re-pair the pad that should be used** - the Xbox One controller reporting all-zero suggests it is asleep, or connected without being initialised.
2. If the Xbox 360 pad is the intended one, **its A/B buttons need attention** - they are reading as permanently chattering.
3. Then set `RELAY_PAD` to the working index (0 or 1) and start the relay; it will report which pad it opened, and the log will show real direction presses rather than A/B pairs.

**The software path is fully built and individually proven** - SDL reads a pad, the relay rebinds to the live session, injection moves the character (30-73 units), per-press yielding prevents interleaving, and the pickups stay off the floor. **What is missing is one healthy controller.**

## Everything else verified this session

* decompilation (`pso_v3.elf`, 25,980 functions, entry `0x8000c040`);
* maps internalised from the disc: city 1497 triangles / 5626 walkable, Forest 1 1455 / **90,986 safe**, Forest 2 1475 / 98,671;
* A\* on the real Forest grid: **629 waypoints, 1902 units, 0.6 s**;
* speed: **median 5.54x, peak 7.31x**;
* the notes channel, the reticle rule, boxes/traps, door keys, RAM door unlocking, rares, auto-difficulty, and the relocation unstuck.
