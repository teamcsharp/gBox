# Metal Gear Solid: VR Missions (PS1, USA) — what is known

Requests: #1082 (mark the current mission complete), #1085 (decompile VR Missions completely), #848 (character
writer), #1117 (pick whip: Aya Brea onto the player), #1597 (Sonic as Snake came out broken; Snake and the soldiers
as Sonic characters on the fly and with the pick whip). Game ids `afd2fc507bb69843` / `f55555ee6513391b`.

Everything below was read from the operator's own disc with capstone (MIPS R3000, little endian) and checked
against pcsx_rearmed save states of a real run, unless marked *inferred*. Code: `gbox/mgs_vr_tool.py` (live mission
tool, pick), `gbox/mgs_vr_unlock.py`, `gbox/mgs_vr_swap.py` (character writer: Snake, soldiers, the other figures),
`gbox/mgs_kmd.py` (models), `gbox/mgs_pcc.py` (textures), `gbox/mgs_vr_tex.py` (texture repaint). Tests:
`tests/test_mgs_vr_tool.py`, `tests/test_mgs_vr_tex.py`, `tests/test_mgs_kmd.py`, `tests/test_mgs_vr_swap.py`
(synthetic KMD / PCC / STAGE.DIR / RAM; two owned-disc checks), `tests/test_pickwhip_dispatch.cjs`.

## Disc

Redump "Metal Gear Solid - VR Missions (USA)", single MODE2/2352 track, 492,487,632 bytes.

| File | LBA | Size | Contents |
| --- | --- | --- | --- |
| `SYSTEM.CNF` | 23 | 70 | `BOOT = cdrom:\SLUS_009.57;1`, TCB 4, EVENT 16, STACK 0x801FFFF0 |
| `SLUS_009.57` | 24 | 643,072 | PS-X EXE, text at 0x80010000, size 0x9C800, entry 0x80099908 |
| `MGS/SLUS_009.57` | 547 | 643,072 | the same executable |
| `MGS/STAGE.DIR` | 861 | 72,593,408 | every stage (below) |
| `MGS/BRF.DAT`, `VOX.DAT`, `ZMOVIE.STR` | | | briefings, voice, FMV |
| `MGS/DEMO.DAT`, `FACE.DAT`, `RADIO.DAT` | | 61 each | stubs |
| `DUMMY3M.DAT` | 195740 | 27,648,001 | padding |

### STAGE.DIR

`u32 header size (0x4EC)`, then `{char name[8]; u32 sector}` per stage, sector = 2048-byte unit inside STAGE.DIR
(`mgs_vr_tool.stage_dir`). 105 stages:

| Prefix | Count | What (from the menu and result strings) |
| --- | --- | --- |
| `init` | 1 | resident data: player model DAR, texture DAR, start script |
| `vr_sud01..15` | 15 | Sneaking mode levels (No Weapon and SOCOM share the maps) |
| `vr_scm/fms/grn/cfr/clm/nkt/psg/stg 01..05` | 40 | Weapon mode: SOCOM, FA-MAS, Grenade, C4, Claymore, Nikita, PSG-1, Stinger |
| `vab_*` | 9 | Advanced mode (one per weapon + sneaking) |
| `vcd_n01..06`, `vefgh_01..10`, `vijkl_01..10` | 26 | Special: mystery / variety / puzzle / VS. battle stages (*family names inferred*) |
| `photo_m1, m2, n1..n3` | 5 | Photograph mode |
| `vrtitle`, `selectvr`, `select`, `vrsave`, `opening`, `option`, `camera`, `movie`, `sound` | 9 | title, mission select, save, menus |

A `.stg` is `u8 1, u8 0, u16 sectors`, then 8-byte entries `{u16 hash, u8 mode, u8 ext, u32 size}` up to an
all-zero entry; the streamed entries (modes `s`, `n`, `r`) are stored in order from +0x800, each sector aligned
(`mgs_vr_tool.stg_entry`, `mgs_vr_swap.stage_files`). A run of mode `c` (cached) entries is one block that starts at
the next sector boundary: each entry's size field is its offset in the block and the run ends with a hash-0 entry
(ext 0xFF) whose size is the block length; the next streamed entry follows the block, sector aligned. Checked
against MetalMintSolid's extraction of `vr_sud03` (every file at the computed offset, byte for byte). `init.stg`: entry 0 =
`0_0.dar` models (156,784 bytes), entry 1 = `1_0.dar` textures (141,656), then a `.pcc`, `59988.gcx` (script) and a
`.wvx`. A mission `.stg`: entry 0 = the stage's code overlay `*.bin`, then DARs, KMDs, OARs (motion), HZM (hit
zones), CON, LIT, the `59988.gcx` script, WVX/EFX/MT3.

Hashes are `GV_StrCode`: 16-bit, `h = rotl5(h) + c` per character (`snake` = 39213, `sna_chest4` = 47255).

### DAR (PSX)

Flat entries `{u16 hash, u8 ext, u8 0, u32 size}` followed by the data padded to 4 bytes (`mgs_vr_tex.parse_dar`,
`pack_dar`; repacking the original `1_0.dar` is byte identical).

## Executable (SLUS_009.57)

MGS1 engine ("GV" actors, "GM" game state, GCL scripts). Debug strings are kept (`loader.c`, `camera.c`, ...).

| Address | What |
| --- | --- |
| 0x80018070 / 0x800180AC | GV actor link / `GV_NewActor(level, size)` |
| 0x80018114 | `GV_SetNamedActor(actor, act, die, source name)`: actor +8 act, +0xC die, +0x14 name |
| 0x800ADA28 | actor system: 9 levels x 0x44 bytes (head sentinel at +0, tail at +0x20); node +0 prev, +4 next |
| 0x80017F50 | per-frame actor loop (walks each level via +4) |
| 0x80019D08 | `GV_StrCode` |
| 0x800195E8 | receive an actor's messages (0x14-byte records, +4 = message hash) |
| 0x80023B5C / 0x80023BDC / 0x80023C98 | GCL: get param by letter / read int / next value |
| 0x80024910 | GCL: run a proc |
| 0x800240A0 | memory-card save loader (0xA38-byte body, CRC by 0x80023DA8; see below) |
| 0x8005DDC0 | player actor init: model = GCL param `m`, default `GV_StrCode("snake")`; motion `snake` |
| 0x8009060C / 0x800905AC / 0x80090300 | libgpu `StoreImage` / `LoadImage` / `DrawSync` |
| 0x8008C8F0 | debug printf |
| 0x800AC1E4 | `GM_GameStatus` (bit 0x10000000 = mission ended) |
| 0x800AC7F8 | play time (frames) |
| 0x800AC820 | `GM_PlayerPosition` (SVECTOR) |
| 0x800B5B98 | current stage name (8 chars, e.g. `vr_sud03`) |
| 0x800B5BA8 / 0x800B52D8 | GCL game-state shorts (0xC0 bytes, live / checkpoint copy) |
| 0x800B5398 / 0x800B4AD8 | GCL variables (0x800 bytes, live / checkpoint): from +0x16, 538 s16 record slots; negative = the stock record of an uncleared slot (*sign meaning inferred*) |
| 0x800BECC8 | 0x140-byte tail of the save body |

Save body read by 0x800240A0 (offsets from body start): +0 = 0x60, +4 = 0x800, +8 play time, +0x18 stage name,
+0x28 16 bytes (to 0x8002D978), +0x38..0xF8 game state, +0xF8..0x8F8 variables, +0x8F8..0xA38 tail; CRC of
0xA38 bytes stored before it. The VR save (selectvr 0x800D9630) also stores the clear grid (below) and bumps
game state +0xB0 (save count).

## Stage overlays

Every stage's code overlay loads unrelocated at **0x800C4350** (checked for `vr_sud01`, `vr_sud03`, `vr_sud05`,
`vrtitle` in save states). It starts with the stage's GCL actor table `{u16 hash, u16 0, init function}`. Each
stage ships its own build, so addresses differ per stage: tools find code by instruction signature.

### Mission manager (`vr.c`) and how a mission ends

In `vr_sud03` (24428.bin):

* Constructor 0x800DA200: `GV_NewActor(5, 0x11C)`, act 0x800D9878, die 0x800D9FF8, name `vr.c`.
* Mission state word 0x800E2BB0 (overlay BSS): 1 running, 2 cleared, 4 result (clear sequence done), 5 over.
* Goal test, every frame while running (0x800D9F14 -> 0x800D8964): player (0x800AC820) within ±500 x and z of
  the goal point at actor +0x24, and status allows it -> clear routine. Mode 3 missions also need flag 0x100.
* Messages (0x800D95A8): `clear` -> clear routine; `vrover`/`voiceover` -> over; others start the timer and
  targets.
* Clear routine 0x800D87A8: `state = 2; GM_GameStatus |= 0x10000000; if (actor[0x10B] == 0) actor[0x10B] = 1`.
  Actor +0x10B is the step counter of the clear sequence 0x800D9384 (jump table of 8 steps): jingle, freeze,
  result screen.
* Failure 0x800D94D0 / 0x800D9054: state 5, the same status bit.

Real run (save states 60 -> 61, Sneaking No Weapon Level 03): manager at 0x801408F4, goal (7000, 1000, -9000);
on the CLEARED screen the player stands at (6831, 1117, -8830), step = 8, state = 4.

All 91 overlays with `vr.c` (90 missions + `vrsave`) have exactly one clear routine, always act - 0x10D0, step
byte always +0x10B (`find_clear_handler`). Photograph stages have no `vr.c`.

### Result screen (`vrclear.c`) and the clear grid

`vrclear` takes GCL param `s` (area, stage) and calls 0x800DC254: `StoreImage(RECT{160,224,12,16}) -> BSS
0x800E2C20`, set bit `area` of row `stage-1` (`clearflags[stage][area]`, 6 words per row), `LoadImage` back. The
grid (16 rows x 6 words, 384 bytes) lives in **VRAM** so it survives stage loads; RetroArch cannot address it.
Each of the 90 mission overlays has this store exactly once (`mgs_vr_unlock.find_flag_store`).

### Mission select (`selectvr`, 33127.bin)

* RAM mirror of the grid at 0x800E543C; filled from VRAM at menu entry (0x800DE9B8), written back at 0x800DE960,
  zeroed for a new game (0x800DE828); the memory-card save copies it (0x800D9630) and loading copies it back
  (0x800D5538).
* Count 0x800DE8C0: one per set bit, row 12 word 4 bit 12 counts 10; compared with 300 (0x12C).
* Entry (category c, level l) is open when bit `base[c] + l` of row `rows[c] - 1` is set: tables 0x800D1DF0
  (rows), 0x800D1E38 (base), 0x800D1F34 (count). Their union is 277 bits (`MENU_BITS`); 23 of the 300 marks
  belong to categories whose count is 0 in the table (photo / variety extras, *unresolved*).
* Derived unlock flags: u16 bit array 0x800C445C (set 0x800DF2B0, test 0x800DF2F0), computed by 0x800DFD2C and
  0x800E03A4 from the grid; 0x800DF3B8 opens the next level of a cleared one (item word |= 0x40000000).

## Models (KMD) and slots

`gbox/mgs_kmd.py` documents the KMD layout and the game's contract (16 objects = 16 motion bones, word-aligned
SVECTOR arrays, weld export flags). Character models with 16 objects (every one has Snake's object tree, parents
`[-1,0,1,2,3,1,5,1,7,8,0,10,11,0,13,14]`, so one role map fits them all):

| Slot | Model | Bytes | Where | Loaded by |
| --- | --- | --- | --- | --- |
| `player` | 39213 `snake` | 13,608 | init.stg 0_0.dar | player actor `../snake_vr/sna_init.c` (exe 0x8005DDC0); no mission script passes `m`, so every stage uses it (Sneaking included) |
| `enemy:soldier` | 38582 | 9,936 | a cached file of 88 mission stages (identical bytes everywhere) | soldier actor `watcher.c` of each overlay (`GM_InitObject(.., 38582, 0x32D, motion GV_StrCode("enemy") 0xA8A1)`, 0x800C5D7C in vr_sud03) |
| `enemy:soldier` | 55267 | 6,060 | the same 88 stages | the soldier actor when its GCL param `y` = 1: the same soldier with fewer triangles |
| `enemy:ninja` | 37617 | 14,252 | vcd_n01..03 | a figure with a long sword in its right hand (object 4): the ninja (*inferred from the mesh; the actor name is not read yet*) |
| `model:46243`, `model:37567` | 46243 / 37567 | 9,352 / 6,264 | vijkl_01/03/06/10 | stage-specific figures (high / low detail) |
| `model:31475` | 31475 (`camera_def2` / `mel_wlf` by hash) | 13,932 | vcd_n05 | a long-haired figure |
| `model:26944` | 26944 | 10,328 | vefgh_10 | a soldier variant (bigger head object) |

`mgs_vr_swap.SLOTS` holds this table; every slot has a writer now (below). Soldier textures: 23 names (24 with an
untextured `0` in 38582) in each stage's own texture DAR (entry 1), at y 236/237 with nine CLUT positions; the
pixels are identical in all stages but VRAM places, CLUT places and palettes differ per stage, so a fit is painted
once per stage. 38582 and 55267 share 21 of those names; a fitted face only uses names its own model already uses.
Some stage DARs also hold 8-bit textures (`mgs_pcc` reads only 4-bit); none of their 256-entry palettes overlaps a
soldier CLUT on the disc, and the painter skips any slot whose CLUT row one would overlap.

## Textures (PCC)

`gbox/mgs_pcc.py`: a ZSoft PCX (RLE, 1 bit x 4 planes, 16-colour EGA palette at 0x10) whose filler at 0x4A holds
MGS fields `magic 0x3039, flags, VRAM x, VRAM y, CLUT x, CLUT y, colours`. The decoder matches MetalMintSolid's
PNGs on all 127 textures of `init/1_0.dar`. KMD face UVs (0..255) are scaled into the texture's VRAM rectangle.
PS1 colour 0x0000 is transparent, so opaque texels are kept at least one 5-bit step above black.

Snake names 28 textures (e.g. `sna_chest4` 47255: 20x23 at VRAM 960,80, CLUT 784,226). They use two CLUTs:
(784,226) with 20 Snake slots plus 15620 and 62675, and (768,226) with 8 plus 54560 and 62721 (models 6049,
16964, 57810). Init models 56141, 16964 and 57810 also name some of Snake's textures.

## Character writer: Snake, the soldiers, every 16-object figure (#848, #1117, #1597)

`gbox/mgs_vr_swap.py`. `characters op=use character=<any> game_id=<VR Missions> slot=player | enemy:soldier |
enemy:ninja | model:<hash> | enemies | all` (or `slot=cast pairs=[{slot, character}]`) builds one disc; with
`session_id` it goes into the running game through session_swap. `characters op=cast_swap target_game=afd2fc507bb69843
source=sonic` plans every slot from the Sonic Adventure 1 + 2 cast and builds them into one disc
(`mgs_vr_swap.build_cast`, strategy `pairs`), with fit events per slot.

The fit, per model of a slot (`fit_slot`):

1. `sm64_swap.retarget` onto the model's bind-pose joints, scaled to the model's whole height (`fit_height`);
2. `proportion()`: a head over twice the model's own head height (a chibi head) is seated on the neck (its lowest
   point at the model's head base) and the chest grows up to it; a head that would take the figure over 1.2x the
   model's height is shrunk about its base; a limb segment that stops short of the next joint is stretched along its
   bone; each foot is squashed / stretched about its ankle until the soles stand on the model's ground; then the
   operator's Retarget editor profile and head size (`rig.scale`), which the first writer never passed;
3. every triangle to the object of its bone, in that object's local frame;
4. `decimate()`: quadric edge collapse per object (`auf_swap.decimate`) to per-object triangle targets that share the
   KMD allocation in proportion to the donor's own detail, at least 6 triangles per object that has any, within the
   u8 vertex / 7-bit normal limits;
5. the kept faces' images painted into the model's texture slots (`mgs_vr_tex.paint`, once per texture archive:
   Snake's in init, the soldier's in each stage), more images than slots folded into flat colours, each DAR keeping
   its own size;
6. seam welds (`mgs_kmd.weld_seams`) and `mgs_kmd.check_compatible`.

The container layer is native (`StageDir`): a KMD is rewritten in place at its own size (zero padded), a texture DAR
is repacked to its own size (anything after its last entry kept), and only the changed raw sectors get new EDC/ECC.
For the player this gives the same BIN, byte for byte, as the MetalMintSolid path (`build()`, still used by
`mgs1_swap`); a node without the disc image hands the build to a Windows worker.

### What was wrong with Sonic (2026-10-13)

No Sonic donor ever produced a VR Missions disc through the writer (the job history has only the early
"no writer" answers and the HUcast / Aya builds); run offline on the owned disc, every Sonic Adventure character
failed:

* **The KMD never fitted.** One vertex-cluster cell for the whole body grew until Sonic's head (490-685 triangles of
  1,000-1,540) fitted the 255-vertex / 13,608-byte limits; long before that his hands (8-24 triangles) and feet
  collapsed to nothing, and an object left without triangles failed the fit: "could not fit the model into the
  13608-byte KMD allocation" for sonic, sa1_sonic and the rest.
* **The scale.** Fitted at Snake's head joint, Sonic stood 2,945 units (1.7x Snake's 1,720) with his shoes 450
  units under the floor and his quills 1,300 units behind him; legs at the retarget's 2x stretch limit left gaps
  at the knees and ankles.
* **The operator's adjustments were ignored**: `fit_kmd_textured` called the retarget without `rig.scale`, so the
  Retarget editor profile and head size never reached a VR Missions build.
* Characters with more images than Snake's 28 slots (E-102) crashed the painter (`StopIteration`).

Now (offline, owned disc, as Snake): all 21 Sonic Adventure entries of the collection (sonic, the 8 sa1_* and the
12 sa2_*), HUcast, Aya and the wrestlers fit (12.4-13.5 KB of 13,608, 378-421 triangles, every face textured,
`check_compatible` clean), standing 1,680-2,260 units tall on Snake's ground (Snake: 1,720). A native build of Sonic (SA1) as Snake
and Knuckles as every soldier wrote 4,305 sectors in about three minutes: all 176 soldier KMDs and Snake's read
back clean, 89 texture DARs keep their sizes and decode, and MetalMintSolid extracts the patched STAGE.DIR, init.stg
and vr_sud03.stg and decodes the new KMDs.

Not yet seen on a screen: any of these builds in a live mission (VRAM placement and CLUT upload by the game are
inferred from the headers, the same way MetalMintSolid decodes them). A chibi donor on Snake's skeleton keeps a big
head on long, thin limbs: the game's motions need the joints where Snake has them.

### Pick whip and "on the fly"

`mgs_vr op=pick x y` (live session) lists the player (`../snake_vr/sna_init.c`) and soldier (`watcher.c`) actors:
actor +0x20 is the model root (hip) in world units (CONTROL.mov; Snake's equals GM_PlayerPosition), projected
through the renderer's view matrix at **0x800B280C** (s16 3x3, 4096 = 1.0; s32 translation at +0x14; 0x8001F1C4
loads it into the GTE right before RTPS): `v = m P + t`, picture point `(0.5 + v.x/v.z, 0.5 + v.y/v.z)` of the
320x240 frame. Each figure is a segment from 570 above to 1,150 below its root; the click picks the nearest within
12 picture pixels (letterboxing handled). Checked on four save states (vr_sud01/03/05; side and top-down cameras):
Snake and every visible soldier land where the frame shows them.

`characters op=resolve_slot session_id x y` names the slot (the desktop pick whip asks it when a collection card
is dropped on a VR Missions game and offers "Put <character> in place of <Snake / the Genome soldiers> (running game,
same moment)"); `characters op=live_use` resolves the slot, builds a disc holding the session's current VR Missions
mod plus this replacement (Snake stays replaced when the soldiers are replaced next) and applies it through
session_swap (save the moment, launch the mod on the same PC, load the moment, close the old copy).

Actors of the stage-specific figures (ninja, vijkl, vcd_n05, vefgh_10) are not named yet, so the pick whip resolves
Snake and the soldiers only; the other slots are reachable with `slot=`.

## Live mission tool (`mgs_vr`)

* `status`: stage, family, manager, state, clear step, goal, player position, record summary.
* `complete`: the manager's own clear routine on the live session (three writes, read back). Needs state 1;
  after MISSION FAILED, restart the level first.
* `unlock_all`: inside a running mission: fills the result routine's BSS grid with the 277 menu bits, turns its
  `StoreImage` call into a nop (that code first runs at the result screen, so no recompiler holds a stale copy;
  the overlay is reloaded from disc on the next stage) and completes the mission; the result screen then writes
  the full grid to VRAM. On the menu it only reports the open-entry count.
* `pick x y [window_aspect]`: the Snake / soldier figure drawn at that point (above).

PS1 RAM via RetroArch: main RAM at offsets 0..0x1FFFFF (`address & 0x1FFFFF`).

## Open for #1085

Not yet decoded: GCL bytecode (params are big-endian with typed values, `06 hash` = string), stage geometry and
collision (`.hzm`, map KMDs), enemy placement (GCL `chara` calls in each `59988.gcx`), the actor names of the
ninja and the other stage-specific figures, and the 23 unresolved clear marks. Those are the prerequisites for level
export to Blender tiles, soldier placement, picking the stage-specific figures on screen and switching to Ninja.
