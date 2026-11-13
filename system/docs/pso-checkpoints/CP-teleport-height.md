# The freeze: my own teleport was burying the character in terrain

## What the struct dump showed

The character had been frozen for **seventy consecutive `up` presses** - 0.00 units each - so this was a stable state worth reading rather than guessing about. A 256-byte dump from `player_ptr`
with the position at `+0x38` (three big-endian floats, the same layout `go_to_field` writes):

```
+0x38  483.3489   <- position x
+0x3C   32.3319   <- position y
+0x40   26.3430   <- position z
+0x44  483.3489   <- the same triple again (render/interpolated position)
+0x60   30279     <- angle
```

and over two seconds **only one word changed** (`+0xC0`, a countdown ticking 16.8 -> 5.6 -> 4.0). So the game was not paused and nothing was animating: the character was simply locked where it
stood, **on a ledge 32.3 units above the floor**.

## The bug that caused it (mine)

The unstuck teleport did this:

```python
landed = teleport(pad, hx, 0.1, hz)      # "drop to ground level"
```

**`y = 0.1` is wrong when the character is standing at `y = 32.3`.** It writes the character *into the terrain* - which is why earlier logs said `drop landed` and the character still would not
move: **the write succeeded and the destination was invalid.**

## The fix, and proof it works

Relocate a short distance **at the character's own height**:

```
before:                 (483.3, 32.3, 26.3)
write (+15 x, same y):  (498.3, 33.0, 26.3)
after holding up:        8.9 units moved
```

**Relocation frees it, and it then walks normally.** The unstuck tries four same-height offsets in turn (forward, back, left, right) and stops at the first that actually produces movement -
checking the movement, not just trusting the write.

## Why this matters more than any single fix so far

Every "the bot is frozen" episode in this session was ultimately this: a character wedged in geometry, with a recovery that **wrote an invalid position and called it a success**. The pad was
healthy the whole time (`(0,0)` neutral, `up` -> `ly 32767`), the game was running (30 fps), and the character was alive (HP 68/68) - so every external sign said "should be moving", and the
one thing that could have fixed it was silently landing the character inside a hillside.

## Verified in the loop

```
[21:17:26]   walk_through : succeeded
[21:17:30]   give 009d00: succeeded      <- DARK FLOW
[21:17:31]   give 003200: succeeded      <- TSUMIKIRI J-SWORD
[21:17:33]   give 004400: succeeded      <- RED HANDGUN
[21:17:34]   survival : succeeded
[21:17:59] unstick: left freed it (31.5 units)
[21:19:28] unstick: left freed it (56.1 units)
[21:19:38] played 120s, 22.0 travel steps
[21:20:16] unstick: down freed it (38.2 units)
[21:21:39] unstick: down freed it (38.3 units)
```

No stderr, 21-22 travel steps per window, and the unstick freeing it **four times** by 31-56 units.

## Honest remaining gaps

* **`gates approached 0, crossed 0`** in these windows - the room had no gates within reach, so the A-at-the-gate sequence has still not been exercised end to end.
* **`closest approach 202-553`** - no enemies in reach in that window either.
* The boss wall is unchanged: **1300 HP with knockback against 68 max HP**, and every `stat` op refused.

The bot now boots, arms fully, moves, frees itself from geometry, targets gates and targets enemies. **What it has not yet done is complete one verified room-to-room crossing with an A press at
the door** - the next thing to watch for, and the first meaningful proof of progression.
