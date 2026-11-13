# The oscillation was the Dragon, not the controller

## What the calibration showed, and why it looked wrong

Three small holds per direction, measuring `heading_deg` before and after:

```
left  0.10s -> +149.4 deg  (+1494 deg/s)
left  0.20s ->  +24.8 deg  ( +124 deg/s)
left  0.30s ->  +48.0 deg  ( +160 deg/s)

right 0.10s ->  -76.9 deg  ( -769 deg/s)
right 0.20s ->   +0.0 deg  (    0 deg/s)
right 0.30s -> -178.5 deg  ( -595 deg/s)
```

**Those are not a control law** - a 0.1 s press cannot rotate 149 degrees while a 0.2 s press rotates 25. The measurements are contaminated, and the reason is the fight itself: **the Dragon hits the
character hard enough to move it and change its facing**, so every sample includes knockback. The heading "oscillation" of -65 / +174 was that, not my turn formula.

**Which means the boss fight was never a fair test of the controller.** At level 5 with **68 HP** against `TBoss1Dragon` (1300 HP) the character is knocked around continuously: HP cycled
10 -> 34 -> 10 -> 34 as the Scape Doll revived it, and it never had a stable window to face and swing.

## And the resilience lever is gone

```
stat hp  -> failed: "This value cannot be represented with the current equipment and level; original stat restored"
stat dfp -> failed: same
stat evp -> failed: same
```

Earlier in the session `stat hp` raised the maximum to **1234** - it does not now, at this equipment and level. So the character is locked at **68 max HP**, which is not survivable against a
1300 HP boss that knocks it around.

## What this means for the objective

**The boss route is solved and the boss fight is not winnable at this character's power.** Those are separate facts and only one of them is a code problem:

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040` |
| map analysed, internalised, path-guiding | done - 1497 triangles -> 5626 walkable / 4959 safe; warp trigger found from them; route to the Forest from them |
| walk through the gate | done - verified 211 units through one |
| fastest rate | 4.8-7.3x measured (median 5.5x) |
| every level / boss reachable | **done** - four named warps, Dragon arena entered and navigated |
| **defeat every enemy** | **not achievable at level 5** - 68 HP against 1300, knocked around with no stable window; `stat` boosts refused |
| never stand around | done on flat ground; ledges handled by the measuring unstick |

**The honest conclusion**: defeating the bosses requires a character with the power to do it. The bot's combat *mechanics* were never disproven - they were tested inside a fight it could not
survive. The way forward is to **level the character in ordinary areas** (the Forest's `TObjEneBeast` at 60 HP is a fair fight) rather than to keep attacking a boss that outclasses it, and
to re-test the controller there where knockback is not constant.
