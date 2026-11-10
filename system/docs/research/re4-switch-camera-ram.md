# RE4 Switch: the camera in RAM (static reading, request #9386)

Read from the decrypted `main.bin` (lilspark, `~/gBox_alt/switch/work/re4-nsp/main.bin`) with capstone AArch64; file offset = module vaddr + 0x100. No game session was touched. Full tables: `re4-switch-camera-ram.json`.

## Chain from a global
```
p1 = *(u64*)(module + 0xb25d78)      # GOT slot (the "game state" global); = module+0xb1ae08
pG = *(u64*)p1                        # fdc4: adrp x22,#0xb25000; ldr x22,[x22,#0xd78]; ldr x21,[x22]
camera = pG + 0xa8                    # 0xf8-byte CAMERA block
```
`pG` itself was not read live (MercMode playing): not determined.

## The render copy (measured)
Function `0xfdc4` (per frame): `add x20,x23,#0xa8 ; add x1,x19,#0x88 ; mov w2,#0xf8 ; bl 0x653c90` = memcpy(pG+0xa8, CamCtrl+0x88, 0xf8), where CamCtrl is GOT slot `0xb25e30`; guarded by `pG[0x5091]&1` and `!(pG[0x87]&0x10)`. The projection is then built from this block: `ldr s0,[x21,#0x168]` (Fovy) and `add x0,x21,#0x10c` (ProjMat) at `0xfe90-0xfeb0`/`0xfec0-0xfef0`.

The GameCube `CAMERA` struct (gc-decomp `camera.h`) is 0xF8 bytes at pG+0x74; the Switch block sits at pG+0xa8, i.e. **+0x34**. That shift reproduces four independently measured offsets (block 0xa8, ProjMat 0x10c, Fovy 0x168, Look 0x178), so the rest are taken from the GC layout.

| field | pG offset | type | basis |
|---|---|---|---|
| Camera.mat (4x3 matrix) | `0xa8` | Mtx 48B | **measured (instruction)** — 0xfe10 add x20,x23,#0xa8 = destination of memcpy(pG+0xa8, CamCtrl+0x88, 0xf8) |
| Camera.v_mat | `0xd8` | Mtx 48B | **layout-derived** — GC layout: block+0x30 |
| Camera.ProjMat (Mtx44) | `0x10c` | float[16] | **measured (instruction)** — 0xfeac/0xfec4 add x0,x21,#0x10c passed to the perspective builder at 0xff10 (x21=pG) |
| Camera.Campos | `0x14c` | Vec f32[3] | **layout-derived** — block+0xa4 per GC CAMERA.param layout; block start and ProjMat/Fovy offsets measured, so it sits immediately after the 64-byte ProjMat |
| Camera.Target | `0x158` | Vec f32[3] | **layout-derived** — block+0xb0 (GC layout) |
| Camera.Roll | `0x164` | f32 | **layout-derived** — block+0xbc (GC layout) |
| Camera.Fovy | `0x168` | f32 | **measured (instruction)** — 0xfe90 ldr s0,[x21,#0x168]; 0xfec0 same; first float arg of the perspective builder |
| Camera.Up | `0x16c` | Vec f32[3] | **measured (instruction)** — getter 0xff70: x0=CamCtrl-camera, ldr [x0,#0xc4] (=0x16c-0xa8) |
| Camera.Look | `0x178` | Vec f32[3] | **measured (instruction)** — getter 0xff90: ldr [x0,#0xd0]/[#0xd8] (block+0xd0 = pG+0x178) |
| Camera.Right | `0x184` | Vec f32[3] | **layout-derived** — block+0xdc (GC layout) |
| Camera.Distance | `0x19c` | f32 | **layout-derived** — block+0xf4 (GC layout); getter at 0xffb0..0xffc8 reads block+0xd0/0xd4/0xd8 only |

Column "basis": *measured (instruction)* = seen in Switch code; *layout-derived* = GC offset + 0x34, not seen in a Switch instruction.

## Camera-to-player distance
- `d_target = |Campos - Target|` (pG+0x14c, pG+0x158), or the stored `Distance` f32 at pG+0x19c (layout-derived; its Switch store not located).
- `d_player = |Campos - PlayerPos|` using the known heap player triple. Units/axes between the two: **not determined** (needs one live dump of pG+0xa8..0x1a0 next to the player triple).
- Wall pull-in has no own field: the engine's `cameraHitCheck` moves the camera nearer the target, so a live `|Campos-Target|` below the nominal value signals a wall press.

## Nominal (un-pulled) distances
`g_readyOfs[16][2][3]` (0x2C-byte rows: campos[2], target, roll, fovy) found by exact float match of GC values at module vaddr `0xae2ab0` (copies 12/13/14 at `0xae3710/0xae3818/0xae3920`). 45 non-zero rows are in the JSON with `dist_campos0_target` (Python `math.dist` over the parsed f32). Table 0 row 0 gives 3920.8, row 2 gives 1952.1; these are player-space offsets, frame/units not determined, and which row is active is not determined.

## Not determined
- pG runtime value
- store instruction for Distance (0x19c)
- Campos/Target units vs player mm
- which table row is active for the Leon shoulder camera
- Campos/Target/Roll/Up/Right offsets are layout-derived, not seen in a Switch instruction (only block, ProjMat, Fovy, Up/Look getters are)

Next check: one read-only runtime dump of pG+0xa8..0x1a0 (0xf8 bytes) with the player triple; expect Fovy ~45-60 at +0x168 and |Campos-Target| == f32 at +0x19c.
