# Round 260: combat's last blocker is target switching, not movement or the swing

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned, floor 1.

## Three separate faults have been eliminated, each by measurement

1. **Input was going to the app shell**, not the docked emulator - fixed by walking child windows by pid (a held key moved the character 0.0 units
   before, 2.95 after).
2. **The swing was too short and too far** - fixed with a held 0.3 s press inside 5 units, which took an enemy from HP 30 to 0.
3. **The approach now moves**: with `nav_fast` planning, the player travelled from around (135,-2) to near the enemies' area during the test.

## What remains, and it is now precisely visible

`combat_nav.py` planned to the nearest enemy, walked two legs, and swung. The log shows the player moving, but the **target changing between swings**:

```
nearest enemy: 16.7 units  Beast at (137.7, -0.3) hp 42
swing 1: nearest 14.2 units  Beast at (224.6, 10.3) hp 60     <- a different Beast
swing 2: nearest 14.4 units  Beast at (224.6, 10.3) hp 60
swing 4: nearest 16.6 units  Beast at (227.8, 17.6) hp 60
swing 6: nearest 17.0 units  Beast at (230.2, 36.4) hp 60
```

There are **several Beasts in the area**, each moving, and "nearest" re-picks every round. The bot therefore chases whichever is closest at that
instant, switches as soon as another comes nearer, and never stays inside melee range of one long enough to kill it. That is why kills stopped
after the first: the earlier success was a single enemy in isolation.

## The fix, and it is small

**Lock the target**: choose one enemy by pointer, remember it, and pursue only that one until it dies, disappears, or is explicitly given up on.
Only then pick the next. Every layer needed for that already exists - the enemy's pointer is read with its HP, so identity and progress are both
available for the lock and the give-up rule.

## State at the end of this round

| item | state |
|---|---|
| input injection | **working** (child window) |
| swing | **working** (held, inside 5 units, verified kill) |
| approach | **working** (nav-planned, measured movement) |
| target selection | **broken** - re-picks the nearest every round |
| rooms visited | 4 of 11 |
| warp sightings | none |
| character | floor 1, HP full, cannot die (survival verified) |

This is progress of the useful kind: four faults found and closed by measurement, one specific fault left, and its fix is a target pointer rather
than another guess.
