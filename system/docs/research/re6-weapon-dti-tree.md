# RE6 Switch weapon class tree (main 061D2A06...), request #9437

Recovered statically by `gbox/mercs/re6_dti_emu.py` (tracks adrp/add/mov/movk constants through the MtDTI static
initialiser at main+0x13C000..0x145000; DTI layout: +0x08 name, +0x20 parent DTI, +0x30 size, +0x34 id).
Full table: `re6-weapon-dti-tree.json` (229 DTIs; 31 anonymous entries dropped).
Check: uWp1091 -> parent uWpBomb, id 0x07011301; uWpBomb -> uWeapon; uWpLauncher -> uPlWeapon (all match the
earlier vtable work). Weapon item id = (dti id >> 8) & 0xFFFF; bomb variants add +1 in the low byte.

| class | dti (main+) | parent | id | item | note |
|---|---|---|---|---|---|
| uWpLauncher | 0x29509a0 | uPlWeapon | - | - | size 0xE28 |
| uWp1080 | 0x2951260 | uWpLauncher | 0x7011200 | 0x112 Grenade Launcher | |
| uWp1120 | 0x2951458 | uWpLauncher | 0x7011b00 | 0x11B Rocket Launcher | size 0xE2C |
| uWpShellLauncher | 0x2950b98 | uWpShell | - | - | size 0xE5C |
| uWp1302/1303/1304 | 0x2952098/0x29520d0/0x2952108 | uWpShellLauncher | 0x7013300/400/500 | shells 0x133-0x135 | projectiles of the launchers |
| uWpBomb | 0x2953028 | uWeapon | - | - | size 0xEAC |
| uWp1091/1093/1095/1097 | 0x2951490/0x29514c8/0x2951500/0x2951538 | uWpBomb | 0x7011301/401/501/601 | 0x113-0x116 hand/incendiary/flash/remote | |

The launcher weapon objects are 0xE28 bytes (no extra fields over uPlWeapon) so a grenade-launcher uWp1080 can be
swapped by slot id alone; the round objects are uWpShellLauncher subclasses. Not verified at runtime.

## The launcher rounds cannot ride the bomb detonation wrapper (measured 2026-11-10)

Our own detonation wrapper (`gbox/mercs/native/re6_061d2a06/code.py`, image at `main+0x18F29C0`) was written for a
thrown bomb and its disassembly shows why parameterising the class is not enough for a launcher round:

```
word 30  ldr  x0, [x19, #0x13F0]        ; the unit's action object
word 31  cbz  x0, refuse
word 32  ldr  x1, [x0]
word 33  adrp x0, #0x288c000
word 34  add  x0, x0, #0x9a0
word 35  cmp  x1, x0                    ; must be the bomb action class
word 36  b.ne refuse
...
word 52  ldr  x1, [x1]
word 53  adrp x0, #0x288c000
word 54  add  x0, x0, #0x868            ; the explosion class the wrapper reports
word 55  cmp  x1, x0
```

A `uWpShellLauncher` round (uWp1302/1303/1304, items 0x133-0x135, DTIs `0x2952098/0x29520d0/0x2952108`) carries the
launcher's action object, not the bomb's, so the wrapper returns 0 - a clean refusal, not a crash, but also not an
explosion. The round is a **projectile the weapon spawns with a velocity**, so the right path is the launcher's own
fire/explode, not this wrapper. `gbox/mercs/native/re6_061d2a06/classes.py` now pins the shell, launcher and shell-family
DTIs/items/sizes (`SHELLS`, `SHELL_FAMILY`, `LAUNCHERS`, `LAUNCHER_ROUNDS`, `shell_for_item`, `shell_rounds`) and the
test cross-checks every row against this file's JSON, so the addresses are ready when that path is built.
