# PSO live platform - consolidated handoff after the mastery block

## Checkpoint status

| checkpoint | state | evidence |
|---|---|---|
| CP0-CP16 | **complete** | delivered in earlier rounds (see the CP docs in this folder) |
| **CP17** - floor change by walking | **PASS** | 9 recorded transitions with position and elapsed time; `floor_warp` never issued |
| **CP18** - Dragon defeated | **PASS** | HP 1191 -> 814 -> 727 -> 652 -> 468 -> 390 -> 202 -> 0, entity vanished, player alive |
| **CP19** - Episode I unattended | **pending** | every mechanical piece exists; blocked on background input |

Verification is reproducible: `python verify_mastery.py` reads `evidence/floor-series.jsonl` and `evidence/cp18-boss-series.jsonl` and writes
`evidence/mastery-verdict.json`, which currently reads `cp17: true, cp18: true`.

## What was built this session

### The map pipeline - the operator's "the 2D map is the 3D game"

1. **The disc's file table was cracked.** `GPOE8P`: FST at the u32 in `0x424` (`0x52400`), entry count in the root entry's **size** field (3556),
   strings at `fst + count*12`. That yields 3555 entries, 3510 files, 649 `.rel`, **501 map files** in about a second - without the plane's extract
   operation, which is a job and never dispatches on an operator-owned session.
2. **All 159 collision maps extracted** (35 areas, 32.5 MB), which is every map in the game.
3. **Floors 1-14 mapped**: rooms segmented, heights built and validated (0.16-0.17 units of error), a room database of **244 rooms** with centres,
   bounds, cell lists, heights, contents and connections.
4. **Layout identification**: a floor has several layout variants; the live one is found by matching the live objects to walkable cells - Cave 1's was
   identified at **94 of 94** live doors and containers, a 90-point margin over the next candidate.
5. **The map audit**: floor 1 fully navigable (5696/5701 cells), and the unreachable rooms on other floors documented rather than discovered by
   bumping into walls. **Door-aware pathing** then made Cave 3 (10022/10116) and Mines 2 (10470/10470) fully navigable.
6. **A rendered gallery** of all 14 floors, which made the level design legible: the Dragon's circular arena, De Rol Le's grid platform, Dark Falz's
   three arenas.

### The game layer

* **Live minimap** at `http://127.0.0.1:8802/` - rooms shaded by height, player, enemies, bosses with HP, warps, and a radar fallback for floors
  without a map.
* **Click to move** and **click an enemy to target it** - the map is a control surface, not a picture.
* **Weapon advisor** - wide melee for groups, fast melee for one close enemy, ranged for distant or flying enemies (unit-tested on six situations),
  from the researched weapon rules.
* **Play loops**: one that respects focus and one for background play; both lock a single target, close with short steps, swing continuously, cast
  techniques beyond melee reach, hunt the nearest enemy anywhere, and take an area exit when one exists.

### Combat, measured rather than assumed

Faults found and fixed one at a time, each by measurement: input going to the app shell rather than the docked emulator; a swing too short for the
animation; attacking from outside reach; target switching between several moving enemies; an enemy **4.5 units below the player** on lower ground;
overshooting a moving target; and finally the discovery that **techniques (B) reach 20-69 units**, which is how the operator's own kills happened.

## The one remaining blocker

**Keyboard input lands only in the focused window.** gBox forces its window **fullscreen and always-on-top** and re-asserts it within a second of any
change - I tried clearing `WS_EX_TOPMOST`, `SetWindowPos(HWND_NOTOPMOST)` and a minimize/restore cycle, and it reverts every time. That has two
consequences:

* the window covers the taskbar and its flyouts, so **the volume control cannot be clicked**;
* the play loops pause whenever focus leaves, which is why the bot has been seen standing still.

**Dolphin's `BackgroundInput = True` removes the second problem, and it is already written into both configs** - the root `User\Config` and the live
`gbox-data\pso-buddies\i9-NUC\...` profile. It takes effect at Dolphin's startup, so it needs one restart, and the app restart also rebuilds the
window state that blocks PiP and the taskbar.

**A restart must be done from the app.** A session the agent launches is `agent_owned` and receives **no input at all**, which is the original problem.

## What happens after the restart

1. `play_background.py` - no focus requirement, no window raising, the bot plays while the operator uses the computer.
2. That is the last ingredient CP19 needs: with maps for every floor, exit seeking, weapon selection and a working fight loop, an unattended episode
   becomes a matter of letting it run.
