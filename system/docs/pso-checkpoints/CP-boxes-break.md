# Boxes break - facing was the whole problem

## The test that found it

Fifty-five containers and ten swings each had destroyed **nothing**. The profile reports their `hp` as `None`, so there was no feedback to tell whether the swings connected at all. So instead of guessing, the
character was placed **7 units** from a box and swept a **full circle, three swings at each of twelve headings**:

```
  heading 338: boxes 55
  heading 102: boxes 55
  heading 152: boxes 55
  heading 215: boxes 55
  heading 258: boxes 55
  heading 306: boxes 55
  heading   8: boxes 55
  heading  58: boxes 54   *** BROKE ***
```

**One broke.** So:

* **`TObjContainerItem` is destructible** - boxes are not exempt from damage;
* **the aim cone is the whole story** - a swing only connects inside the game's **8 degrees**, and a fixed heading beside a box misses it;
* **the same explanation covers the enemies**: `TObjEneLappy HIT: 30 -> 1` landed when the approach happened to leave the character pointing at it, and every "untouched after 8 swings" was the same
  miss.

## Why aiming cannot be computed, and what is done instead

`heading_deg` cannot be trusted to steer: presses in one direction produced **+130, +21, 0 and +145 degrees**. So the box branch does not compute a facing - it **sweeps**:

```python
for _ in range(3):
    tap(pad, "b")        # a pause menu eats the swing
    tap(pad, "a")
hold(pad, "left" if ... else "right", 0.2)   # rotate a little each visit
```

Three swings, then a small rotation, repeated. Over a few iterations the cone covers every direction around the character and the box dies when the sweep crosses it - **exactly the behaviour the
successful test used**. Slower than a computed aim would be, but **verified**, and correctness beats elegance when the alternative is a bot that stands beside fifty-five boxes and hits none.

## This also explains the combat record

Every combat result in this session now has one consistent explanation:

| observation | explanation |
|---|---|
| `TObjEneLappy HIT: 30 -> 1` | the approach happened to leave the cone pointing at it |
| `TObjEneBeast untouched after 8 swings` | the cone was pointing elsewhere |
| 12 swings at 8 units, no damage on Ultimate | same miss - plus 1556 HP to get through if it had hit |
| 55 boxes, 0 destroyed | same miss |

**The swing was never the problem. The aim was.**

## In place

`play()`'s box branch now sweeps instead of aiming once, and the loop restarted clean with it:

```
[23:27:20] === cycle 1 ===
[23:27:22]   walk_through : succeeded
[23:27:29]   survival : succeeded
[23:27:30]   difficulty: Normal (already, hp_max 68)
[23:27:31]   floor_rares: succeeded
[23:27:33]   enemy_drops: succeeded
[23:27:33]   gates: floor 1: gates already open
```

with the operator's pad in use, so the bot is standing down for them:

```
[23:27:33]   operator is playing - bot standing down
```

## Still true

The three weapon gifts fail on **"Not enough inventory slots"** because this session has been alive for hours. **A fresh session clears it** - and the operator is currently playing, so it should not be
restarted underneath them.
