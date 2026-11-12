# Goal round 5: the bot is now a controller

## The missing input path, built

Three rounds established that no keyboard delivery reaches this session - virtual keys, scancodes, every target window, focused and unfocused - while the
operator's **controller** always works, and the app's own pad module says what it forwards: *"the view forwards the operator's controller to the session
it shows"*.

So the bot becomes a controller.

**`vpad.py`** - a virtual Xbox pad over ViGEmBus, which is installed and running on this machine and which the plane itself uses (`pso_coop_setup.xinput_pad`
builds *"a focus-independent XInput virtual pad"*). Verified this round:

```
virtual pad ready
  press a: True      press b: True
  stick up/down/left/right: sent
  reset: ok
```

It calibrates the stick against the character - four directions, measured, because PSO is camera-relative - and then `move(dx, dz)` holds the stick in
whichever measured direction actually moves toward the target.

**`play_pad.py`** - the same room loop, driven **entirely through the pad**: switches found up to 120 units and flipped with `press("a")` while stepping
toward them, enemies fought with A at range and B beyond melee, rooms walked with the stick. **Nothing in it imports `pso_input`**, so nothing in it
depends on which window has focus or whether a window exists at all.

## The supervisor now uses it

```
script = "play_background.py" if works else "play_pad.py"
```

Restarted and waiting:

```
19:35:53 === supervisor starting
19:35:53 no live session - waiting for the game to be launched
```

On the next launch it will test whether the keyboard path works; if it does not - and it has not for three rounds - it starts **the pad loop**, which does
not need it.

## Why this is the right shape for "to completion without fail"

Every previous blocker in this goal was the same shape: the bot could only act while a fragile condition held (focus, a window, a working relay). The pad
removes that class of failure - it is the channel the operator's own controller uses, it is independent of focus, and it is what the plane's co-op mode
was built around.

## State

| item | state |
|---|---|
| virtual pad | **working**: buttons, sticks, reset |
| pad-driven loop | **written**, calibrates then flips switches / fights / walks rooms |
| supervisor | **restarted**, pad fallback in place, waiting |
| game | not running - launch pending |
| keyboard path | unchanged (still dead) - no longer required |
