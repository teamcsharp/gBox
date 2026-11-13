# The freeze, diagnosed: a blocked direction on a ledge - and the measuring unstick

## What the diagnosis ruled out

The character froze at `(490.6, 380.7)` for forty rounds while enemies moved around it. Four candidate causes were tested and **ruled out**:

| candidate | test | verdict |
|---|---|---|
| the input path is dead | held keys and read XInput slot 0 mid-press: `up -> ly 32767`, `left -> lx -32768`, `a -> buttons 4096`, each releasing to zero | **input is healthy** |
| `walk_through` embedded it in geometry | turned it off and repeated the identical movement test | **no change** - off gives 0.0 too |
| a menu or dialogue is up | captured the screen | **no menu, HUD live, HP 68/68** |
| the game is paused | the enemies kept moving (their distance varied 188-240 every round) | **world is live** |

## What it actually is

`y = 16.234`. The character was standing on a **raised ledge**, and the direction being pressed was blocked. A 2-second hold then moved it **109.4 units** with `y` going **15.4 -> 13.3** - it walked off the ledge. **Retrying one blocked direction forever looks exactly like a dead bot**, and that is what every "stuck" episode in this session had in common: the ledge, the wall corner, and the NPC conversation where A advanced the text but nothing moved.

## The fix, and that it works

The old unstick was a fixed dance (`START`, `B`, `down`, `right`) that assumed a menu or a wall. The new one **measures**: it tries each direction in turn and keeps the one that produces movement, only falling back to `START`/`B`/`A` when no direction moves the character at all.

Verified freeing it repeatedly:

```
[18:27:55] unstick: up freed it (31.3 units)
[18:28:56] unstick: up freed it (29.5 units)
[18:29:10] unstick: up freed it (30.9 units)
```

## And it explores, and it crosses rooms

```
MOVEMENT over 30s: 413.3 units     rooms: [15, 16]
x 452 -> 432 -> 466 -> 436 -> 477 -> 485 -> 443 -> 400 -> 335 -> 303 -> 284
y  13 -> 12.7 -> 12.1 -> 12.2 -> 12.1 -> 11.3 -> 8.9 -> 11.7 -> 16.2 -> 21.5 -> 24.2 -> 25.3
```

**413 units in thirty seconds and a change of room** - that is exploration, not standing around, and the `y` column shows it walking down into a dip and up the far side.

## Still open

**Combat does not land.** `kill.py` closes to melee range and swings, but it has no unstick - so when the character is stuck it cannot turn (the log shows heading error pinned at -122 to -162 degrees, i.e. facing away) and it never gets within reach. The loop's `play()` **does** have the unstick and does target enemies, so it is the better driver; but the character can still reach spots where **no direction moves it at all**, which is what the final movement sample (0.0 units over 20 s) shows.

**So the precise remaining problem is narrower than "combat is broken"**: the character can end up in a position from which *every* direction is refused, and then nothing - movement, turning or attacking - can proceed. That is the thing to solve, and it is geometry, not input.
