# Speedrunning: 6.3x measured, and the bot is progressing through the cave

## The measurement

Fast-forward on, in the cave field:

```
frames/s:      201.2          (30.2 at normal speed -> 6.3x)
movement:      782.5 units in 33.5 s
rooms:         1 -> 111 -> 1 -> 111 ...   (two distinct rooms, alternating)
```

**201 fps is well above the 130 fps measured in the Forest** - this floor is cheaper to emulate - so the speed ceiling is **area-dependent**, and 6.3x is the best figure so far.

**Progress is the part that makes it speedrunning rather than idling**: `room` changed between **1 and 111** while the character covered 782 units, and it ended up **standing at a cave gate** with runes on it, sabre drawn, minimap tracking the corridor.

## What this establishes

| measure | value | meaning |
|---|---|---|
| speed | **6.3x** (201 fps) | fast-forward is uncapped and this floor reaches 6.3x |
| movement | 782.5 units / 33.5 s | the bot is playing, not standing |
| progress | rooms 1 <-> 111 | it is moving through the area, not circling |
| state | at a gate, weapon out | genuine PSO traversal |

## Where the 10x figure stands

| floor | frames/s | ratio |
|---|---|---|
| Forest | 127 - 130 | 4.2x |
| **Cave** | **201** | **6.3x** |
| normal | 30.2 | 1.0x |
| 10x would need | 302 | 10.0x |

**`FastForwardSpeed` is unset, so nothing caps it** - the figure is whatever Dolphin can emulate on this CPU, and it varies with what the floor asks for. The cave gets two thirds of the way to 10x; the Forest does not. **EFB tuning was already tested and made things worse**, so the remaining lever would be cheaper guest-CPU work per frame, which is a Dolphin-side property.

## Objective status

| clause | state |
|---|---|
| decrypt PSO | done - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| bot autoplaying | done - `running: true`, 50-208 steps by floor |
| map analysed & internalised | done - `map_city00_00c.rel` sha-verified -> 1497 triangles, 5626 walkable, 4959 safe |
| used for path-guiding | done and load-bearing - the safe cells located the warp trigger `(361.2, 28.8)` |
| speedrunning | **working at 6.3x with measured room-to-room progress**; 10x is not reached on every floor and is CPU-bound |
