# The virtual pad's direction release is broken - and it explains the whole session

## The measurement

One event at a time, reading XInput slot 0 between each:

```
start:                  btn 0  lx      0  ly      0
up    down=True   ->    btn 0  lx      0  ly  32767    correct
up    down=False  ->    btn 0  lx -32768  ly      0    WRONG - pins the stick fully LEFT
down  down=True   ->    btn 0  lx      0  ly -32768    correct
down  down=False  ->    btn 0  lx  32767  ly      0    WRONG - pins it fully RIGHT
left  down=True   ->    btn 0  lx -32768  ly      0    correct
left  down=False  ->    btn 0  lx      0  ly      0    correct
right down=True   ->    btn 0  lx  32767  ly -32768    WRONG - both axes at once
right down=False  ->    btn 0  lx      0  ly -32768    WRONG - leaves "down" held
all four down=False ->  btn 0  lx      0  ly      0    THE ONLY SEQUENCE THAT RETURNS TO NEUTRAL
```

**Releasing a direction moves the wrong axis to an extreme.** `up:False` holds the stick **fully left**; `down:False` holds it **fully right**; `right:True` sets both axes; `right:False` leaves "down"
held. Only releasing **all four together** produces neutral.

## Why this matters more than anything else found today

Every `hold(key, seconds)` in every controller I wrote ended with a **single-key release** - so **every movement left a stick pinned in a direction nobody asked for**. That one fault is behind:

* **the "freezes"** - a pinned stick means continuous turning, and the next input is swallowed; the character looks frozen while the game runs at 30 fps;
* **the wandering between rooms** - it was not exploring, it was being dragged by a held direction;
* **the heading "oscillation"** (-65 / +174) that I twice blamed on Dragon knockback and on my own turn formula;
* **the 0.0-unit movement samples** that made me conclude "blocked direction", "ledge", and "menu open".

**Three of my conclusions this session were wrong because of this bug**, and I retract them: the ledge theory explained one case at most, the "START opened a menu" theory was based on a **stale frame**
(the MJPEG uploader has been serving the same image - every capture for the last several checks has the identical sha256), and "the input is dead" was never true.

## The fix, in place

`endless.py` now has a single rule - **never release a direction alone**:

```python
DIRECTIONS = ("up", "down", "left", "right")

def release_all(pad):
    pad.send([{"key": key, "down": False} for key in DIRECTIONS])

def hold(pad, key, seconds):
    pad.send([{"key": key, "down": True}])
    time.sleep(seconds)
    release_all(pad)
```

and the unstick now presses **`b` first** (a cancel, never START - which *opens* the pause menu) before testing directions.

## What is still not working, stated plainly

After the fix the stick does return to `(0, 0)`, but the character **still did not move** in the last test - `up`, `left`, `right`, `down` each produced **0.0 units** from `(416.9, 303.5)`, room 12,
HP 68/68, with the pad reporting neutral before and after. So a **second** fault sits behind this one, and I can no longer see it: **the frame uploader is stale**, which removes the one diagnostic
that showed what PSO thinks is happening.

The next step is therefore to restore the picture - the worker's still/stream upload for this session - because everything since the frame went stale has been diagnosed from memory alone, and that is
how the last three wrong conclusions were reached.
