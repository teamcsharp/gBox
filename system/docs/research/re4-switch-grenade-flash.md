# RE4 Switch grenade / flash blast anchors (request #9436)

Method: capstone over `main.bin` (mem = file offset - 0x100), bounded scans, no live process. Static evidence only; not run live.
Guided by the GC recipe (`GRENADE_AT_CODE` / `FLASH_AT_CODE` in `gbox/re_games.py`): effect, effect, sound, area attack.

* `0x33b770` area attack `(x0=0, pos*, pos*, w3=class, w4=0, s0=radius)`; 18 callers pass class 0x13, matches the GC call shape.
* `0x1f7dc0` effect spawn `(0, -1, pos, 0, 0, w5=id, 0, 0, stack 0,0)`; `0x261c20` sound `(1, id, pos, 0, 0, 0)`.
* Object pos is `obj+0xa4` (y `+0xa8`). Blast sets `game+0x5090 |= 0x800000` and `game+0x5094 |= 0x20000000`, then stores pos at `game+0x4fa4/0x4fac`, byte `+0x4fb0 = 1`.

| blast | fn | vtable slot (rodata) | effects | sound | class | radius |
|---|---|---|---|---|---|---|
| hand grenade | `0x2e48b0` | `0x67b3f0` | 0x1a (cond.), 0x0d | 0x14 | 0x13 | 6000 (`0x6e8bbc`) |
| simple blast | `0x2e4aa0` | `0x67b408` | none | 0x17 | 0x13 | 6000 |
| flash grenade | `0x2e4e50` | `0x67b5a0` | 0x3f, 0x0c | 0x13 | 0x17 | 15000 (`0x6e8a74`), pos.y += 500 (`0x6e8964`) |

The sibling fns `0x2e4ba0` (vtable `0x67b4c8`) is a variant with the same ground check. The ground/type check (`obj+0x3cc == 0xd6`, `obj+0x3d0`) skips effects for some owners.
Not done: a Switch one-shot blast recipe (call `0x2e4aa0`-style code with a vec3 object) and a live check on i9-NUC/Spark. Code table and byte check: `gbox/mercs/titles/re4_switch_blasts.py`, `tests/test_re4_switch_blasts.py`.
