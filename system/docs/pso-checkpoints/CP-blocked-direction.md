# The freeze is a blocked direction - proven - and the steerer still wanders

## The probe caught it and named it

```
*** FROZEN ***  position (202,219)  y 17.7  room 11  |  nearest: TObjEneBeast at 12.2 units
    up   :   0.0 units      <- blocked
    down :  53.9 units
    left :  90.6 units      <- free, and far
    right:  38.0 units
  up again afterwards: 75.8 units
VERDICT: a blocked direction - down freed it
```

**The character is never locked.** Forward is blocked by whatever is in front of it - here an enemy at 12.2 units - and **the other three directions are wide open**, `left` alone covering **90 units**. The bot only ever pressed `up`, got 0, and to a viewer that is precisely "walking around struggling".

That also re-frames every earlier "freeze": the **ledges**, the **walls**, the **box at 14 units** - all the same thing, an obstacle in the one direction being pressed.

## Fix in place

`steer_to` now **measures its forward step** and, if it did not move, **turns ~90 degrees with counted taps and takes a sideways step** - using the direction the probe proves is free. That turns a stall into a detour.

## But it still does not converge

Tested against a box **119.9 units** away:

```
 0: dist 118.2     5: dist 167.0     10: dist 121.6
 1: dist 131.1     6: dist 147.7     11: dist 116.5
 2: dist 122.4     7: dist 121.1     12: dist 119.7
 3: dist 145.1     8: dist 124.2     13: dist 115.0
```

**It wanders between 115 and 167 and never closes.** The obstacle avoidance stops it grinding into walls, but the heading it turns to is not reliably the one it thinks it is - the tap rotation measured **~11 deg left but ~8 deg right**, and the **first tap after idle was erratic** (+30.5 and then +179.4 in the same calibration). So a counted-tap turn accumulates error proportional to the number of taps, and an 18-tap correction can land anywhere in a 60-degree arc.

## What that means

**The remaining problem is dead-reckoning without a reliable compass.** `heading_deg` is derived from the character's raw `angle`, and every attempt to use it for closed-loop turning has produced inconsistent results - five separate steering algorithms in this session have failed the same way.

**The way forward is not another steering formula; it is to stop needing one.** Two options that do not depend on the heading at all:

1. **`map_step` already returns a waypoint on the safe grid** - if the character could be *moved* to successive waypoints rather than *steered* to them, the heading becomes irrelevant. The teleport primitive (`write_memory(ptr+0x38, x,y,z)`) does exactly that, and it is **proven**: it moved the character 20 units, 311 units, and freed it from wedges repeatedly. Walking a route by successive small teleports (say 10 units per hop, along safe cells) would be **deterministic**, avoid all collision and all steering error, and use the map exactly as the objective asked.
2. Or let the **operator's controller** drive, which is what it is for.

**Option 1 is worth one round**: the map already produces the route, the teleport already works, and neither needs the heading. It is the only navigation method in this session that has never failed.
