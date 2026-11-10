# RE5 Switch fire rate: static reading (milestone 1, not live-verified)

Request #9420. Source: the decompressed main NSO on lilspark (`~/gBox_alt/scratch/agent/switch/re5/main-EBFFDB22...nso`, not in git). `main+X` is file offset `0x100+X`; decoded with python capstone (AArch64), throwaway script outside `system/gbox`. Machine-readable twin: `re5-switch-fire-rate.json`.

## What the fire action does (read, 0x96E2C8-0x96E340, inside the function at 0x96CD30)
```
0x96E2E8  level = u8 [slot+0x25]
0x96E2F0  fs  = f32 [main+0x1D13B28 + id*0x210 + level*4 + 0x58]     firing-speed table (0.0 if id>=0x150)
0x96E310  ofs = f32 [main+0x1D08680 + id*0x140 + 0x90]               interval offset
0x96E32C  frm = f32 [[x25]+0x93C]    x25 = sPlayer::mpInstance (main+0x1CF1C98), the shot-motion frame
0x96E330  if frm >= fs+ofs: u8 [player+0x37B0] = 1                   trigger re-armed
```
So the repeat is limited by *shot-motion frame >= firing speed + offset*. There is no fps constant: the PS3's "timer 60 -> 4800" has no table on Switch. The pace is the frame delta (`[[main+0x1CF08A0]+0x34]`) times the player's time scale (`+0x1A08`), as at 0x96E350-0x96E368 for the action's own timer `[x19+0x48]`.

## PS3 -> Switch map
| PS3 | Switch | read from | stock values |
|---|---|---|---|
| fire timer (60 fps const) | none; frame delta x player+0x1A08 | 0x96E350-0x96E368 | n/a |
| firing-speed table | main+0x1D13B28, 0x210/weapon, +0x58 + level*4 | 0x96E2F0-0x96E300 | not determined: zero in the file (filled at runtime, constructor not found) |
| interval offset | main+0x1D08680, 0x140/weapon, +0x90 | 0x96E310-0x96E320 | -10 handgun, +5 MG, -2 shotgun, -5 magnum (live read in re5-switch-ram.md, not from this file) |
| firing animation layers | candidate: player +0x900/+0xA60/+0xBC0 (stride 0x160), frame at layer+0x3C = +0x93C | indirect | not determined |

## Why 5x
The 5x is **the mod's own cap**: `FIRE_MAX = 5.0` (re5_switch_mods.py:80) and `k = min(k, FIRE_MAX)` (line 223), set by the operator on 2026-10-28. The game does not stop there: live figures already in the docs go 2.7 (x1), 8.7 (x4), 15.3 (x8), 16.7 (x32), 24.7 (x80) shots/s. The flattening past x8 is consistent with one re-arm per fire-action update (a single trigger byte per update) so the update rate is the ceiling: inferred, not verified.

## Per weapon class
Limiting fields are the same for all: frame (+0x93C) vs firing speed[level] + offset, and the time scale through the frame advance. Classes (record +0x10): handgun 2, machine gun 4, shotgun 5, magnum 7; rifle class not determined. A write of firing speed or of the offset (lower) re-arms earlier, with a floor of one shot per update; a time-scale write shortens the whole motion. Whether the magnums use motion 29 (scaled shot motion) is not determined; a live read of the three layers during a magnum shot, or decoding the layer update that adds the delta into layer+0x3C, would settle it. Stock per-weapon values need either the table constructor or a live read.

## Not determined
- stock table values from the executable; rifle class id; writer of [action+0x48]; magnum motion/layers.
