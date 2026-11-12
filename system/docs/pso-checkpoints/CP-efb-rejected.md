# 10x investigated and closed: EFB tuning rejected, and the unstick fixed

## The last speed lever was tested and it made things worse

Dolphin is bound by serial work (1.24 of 16 cores, 31.6% total CPU), and the only part of that serial work which could be reduced is the GPU thread's per-frame cost. So
`GFX.ini` was given:

```
EFBAccessEnable = False      # EFB peeks force a GPU->CPU sync every frame
EFBToTextureEnable = True
EFBCopyEnable = True
VSync = False
InternalResolution = 1
```

Result, on the **title screen**:

```
baseline (new settings):        25.6 fps     (was 30.2)
fast-forward (new settings):    27.8 fps     (was 127.2 - 130.2)
settled:                         0.0 fps
```

**Far worse, then stalled.** `EFBAccessEnable = False` breaks PSO. The file was **reverted to its original empty state** (the backup was taken before the change) and the relaunch
restored normal behaviour.

**Honest caveat about that measurement**: the counter at `0x805D53A4` does **not tick at the title** (0.0 fps at rest confirms it), so title-screen numbers are not comparable
with the Forest numbers - the 130 fps reference was measured in gameplay. The stall at 0 fps is the real signal that the setting was harmful, and the revert stands
regardless.

**Conclusion: 4.2x is the ceiling, and it is a property of Dolphin's serial emulation on this CPU, not of any setting.**

## The bot was stuck in a corner, and the reason was the unstick itself

The mover reported "stuck" and pressed START and turned - but the character was **physically wedged in a corner facing a wall**, with no menu open, so turning alone could not free
it: `up` just pressed it into the wall.

The unstick now **backs off first**:

```python
tap(pad, "start")        # in case a pause menu is what "stuck" means
hold(pad, "down", 0.7)   # reverse, so there is room to rotate
hold(pad, "right", 0.6)
hold(pad, "up", 0.6)
```

and it works:

```
stuck at (304.5,259.3) - backing off, pressing START, then turning
warp 247.1 away - heading for it
```

**Measured: 39.0 units of movement over 16 s**, and the bot is walking toward the warp again.

## Boot timing, now understood properly

The sequence that reliably reaches gameplay:

```
wait ~32 s (logo, licence, title)
START  -> main menu
DOWN   -> OFFLINE GAME
A      -> SELECT GAME MODE
A      -> SELECT CHARACTER      (BQF, LV5, HUmar, ORAN)
A      -> Confirm / Cancel / Recreate
A      -> SELECT EPISODE
A      -> warp tunnel
then   WAIT through the intro cutscene (~20-30 s, the close-up of the character with a rifle)
then   A presses until the semantic player exists
```

The cutscene is why earlier boots "returned to PRESS START": the player entity does not exist during it, a 3-4 s wait ran out, and the remaining presses landed on whatever
followed.

## Where the objective stands

| clause | state |
|---|---|
| decrypt PSO | **done** - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| bot autoplaying | **done** - reached `running: true`, **208 steps**, 499 units in 24 s, in the Forest |
| map analysed & internalised | **done** - `map_city00_00c.rel`, sha verified, 1497 triangles -> 5626 walkable cells |
| used for path-guiding | **done** - 29 waypoints to the warp platform; that route is how the bot reached the Forest |
| speedrunning at 10x | **4.2x measured and stable**; 10x is CPU-serial bound, and the one remaining lever (EFB) is now tested and rejected |
