# Dead Or Alive ++ (arcade, Tecmo TPS) character pipeline

Ticket #1340 (GAP: character writer for Dead Or Alive ++ (Japan)). Catalog: `a19b4e641b155364` "Dead Or Alive ++
(Japan)" = MAME `doapp` (parent; "Japan/USA/Export", region set in the test menu), `59c55e95af61abbe` = `doappk`
(Korea clone, only the two program ROMs differ). It is **arcade PlayStation hardware without a disc**: Tecmo TPS
(ZN-1 board, BIOS set `coh1002m`, MAME driver `zn2p`, `src/mame/sony/zn.cpp`). There is no SLPS executable and no
ISO9660; everything lives in the 0x2800000-byte `bankedroms` region the CPU sees through an 8 MiB window at
0x1f000000 (bank byte written to 0x1fb00006).

| Stage | State | Where |
| --- | --- | --- |
| Inventory (identity, files, fighter index) | done, verified against the owned ROMs | `gbox/doapp_inventory.py`, `gbox/zn_tps_boot.py` |
| Format analysis | file table, model container, mesh sections + primitives, motion banks, skeleton build | this document |
| Reader (rigged GLB) | done: 44/44 costumes verified, registered in `characters.DEDICATED` (`doapp`) | `gbox/doapp_chars.py`, `gbox/doapp_motion.py`, `gbox/doapp_models.py` |
| Writer | done: any collection character on a fighter's 15 bones, rebuilt doapp set; read back through the game's skeleton build; MAME check pending | `gbox/doapp_swap.py` |

## Owned source

`collections/Mame/roms/doapp.zip` (13.7 MB) + `coh1002m.zip` (BIOS `m534002c-61.ic353`, CPU-board CAT702 `mg01`) on
the HyperSpin share (`//10.89.1.125/HyperSpin Attraction/Arcade/collections/Mame/roms`). All MAME dat SHA1s match.

## The program is encoded, the file table is inside it

`bankedroms[0:0x88880]` = `0x0000020b`, the SCEI licence string, then an encoded image (entropy 7.95). The TPS BIOS
decodes it into RAM 0x80010000..0x80097e18 and jumps to 0x800107d8. The BIOS strings name the modules
(`decode.c`, `decodesce.c`, `decodetecmo2.c`, `ramsec.c`): the decode exchanges bytes with the two CAT702 security
chips over SIO0 (mg01 on the CPU board, mg05 on the ROM board), selected through `znsecsel` 0x1fa10300 (bit 2 / bit 3,
active low). The kernel itself is stored encoded in the BIOS at 0x30000 (header 0x08100080 = 8 x 16 x 128-byte
blocks) and the BIOS routine 0xbfc0638c decodes it into RAM 0x500 with chip mg01; the game is decoded by kernel
function B0:0x63 (0x800021a8 -> 0x80001328).

`gbox/zn_tps_boot.py` reproduces this without re-implementing the cipher: a small R3000 interpreter runs the BIOS's
own code (kernel decode, then B0:0x63) against a CAT702 model taken from MAME's `cat702.cpp` (byte-level form,
checked against a clock-level model in `tests/test_zn_tps_boot.py`). ~10 M instructions, ~35-40 s of CPython. The
decoders call `rand()` for their work order (seeded from timers); the output does not depend on it.

Evidence that the decode is right: the decoded image is code (jr ra / addiu sp density across 0x10000-0x90000), the
returned entry 0x800107d8 is inside it, its loader at 0x800ff5a4 (in the plain overlay) indexes the table at
0x800515a4, and the 280 table records tile the data ROMs exactly (consecutive offsets + sizes, zero gaps except bank
boundaries) and agree with every content signature (TIM `0x10`, VAB `pBAV`, SEQ `pQES`, model containers below).

## File table (`doapp_inventory.FILE_TABLE`)

12-byte records at RAM 0x800515a4: `u8 bank (+3 pad), u32 offset in the 8 MiB bank, u32 size`; 280 entries. The
loader reads 0x800-byte units from 0x1f000000 + offset after writing the bank to 0x1fb00006. Files are packed back to
back, so a file can only be replaced in place within its own size (`file_room()` gives the bytes up to the next
file; only the last file of a 4 MiB ROM has slack).

| Files | Content |
| --- | --- |
| 0 | plain overlay (fight code + data) loaded at 0x80097e18, 0x90930 bytes |
| 1 | second overlay, 0x12721 bytes |
| 4-14, 15-25, 38-48 | per-fighter small files (tables `small_a`, `small_b`, `small_c`) |
| 27-37 | per-fighter motion banks (`motion`, 250-410 KiB, pointer table relocated at +0x1010..0x1020) |
| 49-103 | fighter models: 11 groups of 5 table slots = 4 costumes + 1 zero-size slot |
| 104-120 | stages (table at 0x80087bcc) |
| 121-133, 145-177 (odd) | VAB sound banks (`pBAV`); 146-176 (even) SEQ music (`pQES`) |
| 134-144 | per-fighter `bank_c` |
| 178-279 | TIM images (UI, portraits; 233-243 and 267-277 are per-fighter) |

## Fighters (`doapp_inventory.FIGHTERS`)

Internal fighter ids from the ranking tables at 0x80087940 (u8 id + name): 0 ZACK, 1 TINA, 2 JANN LEE, 4 HAYABUSA,
5 KASUMI, 6 GEN FU, 8 BAYMAN, 9 BASS, 11 RAIDOU, 12 LEI FANG, 13 AYANE (3, 7, 10 are unused ids whose table rows
alias Kasumi). Model file per costume: `u16` at 0x80087334 + 4 * (id * 19 + costume); costumes 0-3 are distinct
files, slot 4 is a zero-size record, 5-18 repeat costume 0. Six more one-file-per-fighter tables (`CHAR_TABLES`).
The fight loader (0x8006c300) reads player record 0x80096340 + 0x60 * player: byte 1 = fighter id, byte 2 = costume.

## Model container (files 49-102)

```
u32 tim_offset                       -> run of standard PS1 TIMs (4 bpp + CLUT) to the end of the file
14 x section, each 4-byte aligned:   u32 dest (0 = absent, 4 bytes only) ; u32 length ; payload
```

`dest` is the offset in the per-player work buffer (player 0: 0x801e8000; the 14 section pointers are stored at the
start of that buffer). Sections 0, 1, 2, 11, 13 are copied raw; 3-10 and 12 are packed and expanded by 0x8006c718
(stream of 16-bit units: odd = one s16 value, even = low half of a 32-bit value whose high half follows; `length`
is the expanded size). The expander's output starts with the marker 0x42.

* section 0 (female fighters only): SVECTOR-like 8-byte offsets (secondary/physics joints).
* sections 1, 2: u16 arrays, per drawn part the vertex count and first vertex used by the renderer
  (read at part-record +0x530 / +0x534 by 0x800ab828).
* sections 3-10, 12: meshes. `[0x42][header size][vertex block offset][group count]{count, chunk offsets[count]}`,
  vertex block = SVECTOR (s16 x, y, z, pad) to the end of the section. A chunk is `u16 count, u16 kind`
  (kinds 0x8018 / 0x8019 / 0x801a / 0x801b / 0x803a / 0x805a / 0x29 ...) followed by prebuilt GPU packets
  (e.g. 0x0c000000-tagged GT4 0x3c packets with UV / CLUT / tpage filled in), per-primitive vertex pointers into the
  transformed-vertex buffer (0x1f800000 + 8 * i, spilling to 0x802a6800 after 126 vertices) and 4.12 normals.

Renderer: 0x800ab828 (overlay) sets the bone matrix (32-byte matrices, bone index from a per-part byte table) and
calls 0x800abe94(section, count, first) which RTPT-transforms the vertex block into that buffer, then walks the chunk
list dispatching on the chunk kind.

### Vertex batches and bones (`gbox/doapp_models.py`)

Sections 1 and 2 hold 13 u16 counts / first-vertex indices per mesh slot (slot k = section 3 + k). The renderer
transforms batch p of slot k with bone matrix `BONE_SLOTS[k][p]` (the 13-byte tables at overlay 0x80103ed0; the
body uses 0x80103f2c when it has 10 groups) into the shared transformed-vertex buffer at the batch's own first index,
so primitives can join vertices of different bones (rigid one-bone-per-vertex skinning, seams included). Checked on
all 44 costume models: the batches cover every vertex of every mesh exactly, and the mesh group count equals the
batch count (one more in slots 0, 1 and 3 when those carry an extra group). Bones 0-14 are the main skeleton (15 matrices, post-processed by 0x800ad810), 15-26 are
costume accessory chains (hair, ribbons; mesh slot 7, matrices from the chain solver 0x800aa1c0 driven by the
per-fighter/costume table at 0x80103ab8). Bone roles, now from the skeleton build (below): 2 pelvis, 0 upper body,
1 head; left arm 8 / 4 / 5 (upper, forearm, hand), right arm 14 / 10 / 11, left leg 6 / 7 / 3 (thigh, shin, foot),
right leg 12 / 13 / 9 ("left" = the fighter's left at facing +1: +x in the game frame; 0x80102238 is the game's
left/right swap table for facing -1). Slots 2 and 4 hold three alternative hand shapes, one drawn per frame (u8 at
0x8011d40d / 0x8011d40c + 2 * player).

### Primitives (`doapp_models.primitives`)

A chunk record holds the same prebuilt GPU packet twice (double buffer), then the corner pointers, then per-kind data
(layouts from the draw routines 0x800acd08 / 0x800aca74 / 0x800ac2cc / 0x800ac010 / 0x800ac8c8 / 0x800ac6ec /
0x800acbd4 / 0x800ac51c):

| kind | record | packet | corners | after the pointers | drawing |
| --- | --- | --- | --- | --- | --- |
| 0x8018 | 0x54 | FT3 | +0x40.. | 1 normal | culled, flat lit |
| 0x8019 | 0x68 | FT4 | +0x50.. | 1 normal | culled, flat lit |
| 0x801a | 0x74 | GT3 | +0x50.. | 3 normals | culled, gouraud lit |
| 0x801b | 0x98 | GT4 | +0x68.. | 4 normals | culled, gouraud lit |
| 0x803a / 0x803b | as 0x801a / 0x801b | GT3 / GT4 | | | double-sided |
| 0x29 | 0x60 | FT4 | +0x50.. | — | double-sided, unlit |
| 0x805a | 0x74 | GT3 | +0x50.. | 3 x 2 colour pointers | seam triangles (below) |
| 1 | 0x70 | FT4 | 4 inline SVECTORs | — | section 12 only (effect quads drawn on a player flag) |

CLUT = high half of packet word 3, tpage = high half of word 5 (GT) / 4 (FT). All 27258 primitives of the 44 costume
models parse, every chunk tiles to the next, every vertex index is in range, and every primitive samples texels and a
palette of the model's own TIMs (4 triangles of Lei Fang costume 3's hands run 4 texels past their TIM). The 0x805a
triangles (the last group of slots 0, 1, 3) are the only primitives joining two batches: the seams between bones,
reusing vertices the slot's other batches transformed and borrowing their neighbours' lit colours. Drawn corner order
(0, 1, 2) + (1, 3, 2) faces into the mesh in the game's y-down frame; the reader reverses it.

## Motion banks (files 27-37, `gbox/doapp_motion.py`)

Loaded per player at *(0x80087288 + 4p) (0x80196800 / 0x80226800) and relocated by the fight loader 0x8006c618:

```
+0x0000  4 x 0x404   IK bend tables (s16[0x202]; entry ((dist + 3) * 512) // 1000 = elbow / knee bend)
+0x1010  4 x u32     their offsets
+0x1020  u32 list    0-terminated motion record offsets (265 for Tina; records can be shared)
record   9 x u32     rot track x3 | limb track x4 | curve block | twist keys (0 = none)
```

* rotation track: one u32 per frame, x = (w >> 20) & 0xffe, y = (w >> 9) & 0xffc, z = (w << 1) & 0xffe (4096 = 360
  degrees); tracks 0 / 1 / 2 feed rotation slots 0 (upper body), 1 (head), 2 (pelvis); facing +1 uses (x, -y, z).
* limb track: 5 bytes per frame, four big-endian 10-bit fields << 2 = the end bone's rotation (x, -y, z) and the
  limb's twist angle. The game's limbs 0..3 (right arm, left arm, right leg, left leg) read record words 6, 4, 5, 3
  (0x80100118; 0x80100128 when mirrored), and the rotation slot a limb writes is the same number.
* curve block: 15 s16 halfword offsets; curves 0..2 = root x, y, z (x / z applied as deltas), 3+3k..5+3k = IK target
  (x, y, z) of limb k in player space. A curve is a run of segments, type = low 3 bits of the first halfword:
  0 = quadratic (frames in bits 3..11, 20-bit acceleration, start), 4 = linear, 2/6 = short quadratic (3..10 frames),
  1/5 = one-frame hold, 3/7 = end. Frame t of a segment is ((a t + b) t >> 10) + start / 4 with
  b = ((end - start) << 8) / frames - a frames, end = the next segment's start (handlers 0x80100210 / 0x801001d0 /
  0x801001b0 / 0x801001f0, lengths 0x80100230). The motion lasts until the root-x curve reaches its end segment.
* half-rate motions (tracks hold about half as many frames as the curves; the move script's 0x6666 opcode sets the
  flag at 0x8011d430): the stepper 0x80099fa4 shows each track frame, then the wrapped midpoint to the next one, and
  applies the twist keys (record word 8: u16 frame markers with bit 15, keys with bit 14 for limb h & 0x3fff followed by
  an s16 twist << 4; 0x8009abac). Full-rate motions use 0x8009adbc.
* `doapp_motion.channels()` decodes all of this in Python; checked frame by frame against the game's own stepper
  state (rotation slots, twists, IK targets, root height) for every motion of all 11 fighters: 3045 motion list
  entries, 285347 frames, 0 mismatches.

The neutral move (move 0, script in `small_a` sub-table 0x15) plays motion 0, a loop (its last frame equals its first)
at one motion frame per game frame (the script sets speed 0x1000; 60 fps).

## Skeleton build (the "motion evaluator")

There is no per-bone keyframe data: per frame the game builds the 15 matrices from the channels above. 0x800a0ce8
(per-player update) loads the player transform (position + root height, facing yaw) into the GTE and calls 0x800a1710
(IK targets to world) and 0x800a4848, which:

1. rotates by the pelvis slot (X, Y, Z order, 0x8002f634 / 0x8002f6e4 / 0x8002f574) -> bone 2;
2. translates by the fighter's torso offset (0x801011d8 + 8 * s16 0x80102248[fighter]) and rotates by the upper-body
   slot -> bone 0;
3. places the IK roots at the fighter's joint offsets (same table, entries +0x70 / +0x40 in the torso frame for the
   shoulders, +0x60 / +0x30 in the pelvis frame for the hips) with pole points (-154, 265, 0) / (154, 265, 0) in the
   torso frame and (-76, -17, 26) / (76, -17, 26) in the pelvis frame; head look 0x800a6cb4 -> bone 1;
4. 0x800ace28: for each limb, the distance to the target (sqrt 0x800ad7a0), clamped to the limb's reach (lengths
   0x80101b80 + 32 * fighter), bend angle from the IK table, aim (atan2 0x800ad624), twist; writes upper / end / lower
   bones from the table at 0x80103f44 (14/11/10, 8/5/4, 12/9/13, 6/3/7) with the end bone's rotation slot;
5. 0x800aa1c0: accessory chain physics (bones 15+, state initialised by the fight init 0x800a996c from 0x80103ab8),
   then 0x800ad810 (hit spheres; does not change the matrices).

Output: 32-byte PS1 MATRIX records (s16 3x3 4.12 + s32 translation) at 0x8011ca60 + 0x340 * player, world space, y
down. Transforming each batch with its bone's matrix assembles the fighter (checked visually and by the seam triangles
on all 44 costumes).

`doapp_motion.Rig` runs exactly this code: a 4 MiB ZN RAM (`zn_tps_boot.ZNMemory(ram_size=0x400000)`) with the
decoded program, both players' `small_a` (relocated by 0x8006a754), motion bank and model (expanded by 0x8006c718 into
the work buffer *(0x8008775c + 4p) = 0x801fe800 / 0x8028e800), the fight init 0x800a860c, then 0x8009f0a8 (set
motion) / 0x800996f4 (tick) / the build, on `zn_tps_boot.R3000` with the GTE model `gbox/psx_gte.py` (MVMVA, RTPS/RTPT,
NCLIP, SQR, OP, AVSZ, GPF/GPL; lighting commands raise).

## Reader (`gbox/doapp_chars.py`)

Per costume: bind pose = frame 0 of motion 0 after one full loop (so the chains have settled); joints = the 15 body
bones (pelvis root, roles hip / chest / head / l_upper / l_fore / l_hand / r_... / l_thigh / l_shin / l_foot /
r_...) plus the accessory bones the mesh uses (chain links parented to their anchor / previous link from 0x80103ab8;
other accessory bones to the nearest body bone); one joint per vertex; per (tpage, CLUT, sidedness) a texture page
cropped to what its primitives sample; glTF frame (x, -y, -z) x 0.001 m, facing +Z. A 'stance' clip (motion 0 at 60
fps) is included; any motion can be exported (`--clips name=index`). Verification: every vertex has a bone, every
primitive's texels come from the model's TIMs, seam-triangle edges <= 400 units, feet on the ground (within 60), height
1300-2000 units. All 44 costumes pass (`python -m gbox.doapp_chars <roms dir> <out dir>`).

Not exported: section 12 (effect quads with inline vertices, drawn only when player byte 0x8009638f is set), the two
unused hand shapes of slots 2 / 4, per-vertex lighting colours.

## Writer (`gbox/doapp_swap.py`)

`characters op=use character=<any> game_id=a19b4e641b155364 slot=<fighter>[:<costume 1-4>]` (or `slot=player`: all 11
fighters x 4 costumes, so whoever is picked is the character) builds mod `doapp_<slug>_<slot>`: a folder with a
rebuilt `doapp.zip` (+ a copy of `coh1002m.zip`). The owned zips are only read.

### The section expander and its inverse

0x8006c718 (a0 player, a1 source, a2 destination; an identical copy at overlay 0x800fd674 serves the streaming loader
0x8007eedc) reads a stream of even values (odd halfword = `h & 0xfffe`, even halfword = low half of a 32-bit value
whose high half follows): header size, chunk-area bytes, vertex-block offset, vertex bytes, group count x 4, then per
group its chunk count x 4 and chunk offsets. Chunks follow as `u16 count, u16 kind` + per-kind source records, which
one routine per kind expands into the double-buffered records the drawers use, through one packet template in the
scratchpad (0x1f800000) that keeps its state across chunks and sections:

| source kind | routine | source record | expands to |
| --- | --- | --- | --- |
| 0x801b / 0x803b | 0x8006cc40 | 7 halfwords (code << 8 \| depth mode, CLUT, tpage, 4 UVs), 4 vertex values, 4 normals (normal 1 + u16 flag) | GT4 0x98 |
| 0x801a / 0x803a | 0x8006cf3c | 6 halfwords, 3 vertex values, 3 normals (normal 1 + flag) | GT3 0x74 |
| 0x8019 (0x8039 -> 0x29) | 0x8006d214 | 7 halfwords (low byte of the first unused), 4 vertex values, 1 normal | FT4 0x68 |
| 0x8018 / 0x8038 | 0x8006d490 | 6 halfwords, 3 vertex values, 1 normal | FT3 0x54 |
| 0x29 | 0x8006d6e8 | 7 halfwords, 4 vertex values | FT4 0x60 |
| 0x805a | 0x8006d92c | 6 halfwords, 3 vertex values, 6 colour values (+ destination + header size) | GT3 0x74 |
| 1 | 0x8006dbfc | 7 halfwords, 4 inline SVECTORs | FT4 0x70 |
| 0 | 0x8006ddbc | 6 halfwords, 3 inline SVECTORs | FT3 0x58 |

Vertex value v = 8 x index: `v < 0x3f0` -> 0x1f800000 + v, `v <= 0x803ef` -> 0x802a6410 + v, else a raw address.
Player 2: CLUT |= 0x200 (8 rows down; not for kind 1), tpage |= 0x10 (y + 256). The GT depth byte (packet +0x13) picks
the depth used for sorting (0 average, 1 nearest, 2 farthest); normal 1's flag = 1 makes the drawer light the
primitive even when it is culled, because a seam borrows its colours. The vertex block is 6 bytes per vertex.

`expand_mesh` is a byte-exact port (template included); `pack_mesh` / `mesh_from_expanded` are the inverse pair. On
all 44 costume models the port equals the game's routine byte for byte, and packing the game's expansion reproduces
Tecmo's packed bytes exactly (327 / 327 sections; `tests/test_doapp_swap.py` owned test).

### What the writer builds

* Target: `doapp_motion.Rig` (fight loader walk, fight init, skeleton build) gives the stance frame-0 matrices of the
  15 body bones (the reader's bind pose). Joint positions go to the generic rigid retarget (`sm64_swap.load_rig` +
  `retarget`, roles -> bones 2 / 0 / 1 / 8 4 5 / 14 10 11 / 6 7 3 / 12 13 9), feet are scaled about the ankle onto
  the original model's ground, and every vertex is put in its bone's frame with the inverse bind matrix (game units,
  y down), normals likewise (4.12, outward, against the drawn order's right-hand normal like the game's own data).
* Layout = the game's 14-group body (Zack / Jann Lee costume 3): slot 0 holds the 13 body bones as batches in
  0x80103ed0 order plus the seam group (slots 1, 3, 5, 6 absent), so shoulders, elbows, knees and ankles get seams;
  hands are slots 2 / 4 with the three hand shapes sharing one mesh; slot 7 keeps the costume's accessory part count
  with no geometry (the chain physics keep running); sections 0, 11, 12, 13 are kept; sections 1 / 2 rebuilt.
  Triangles inside one bone become GT4 (paired) / GT3 lit primitives (0x801b / 0x801a, code 0x3c / 0x34); triangles
  joining two body bones become 0x805a seams whose colour pointers aim at the lit corner of the same vertex (or the
  nearest lit corner of its bone), and those primitives get the light-when-culled flag. Hand / forearm triangles go
  rigidly to their majority bone (different slots).
* Texture: one 8-bit 256 x H TIM at VRAM (704, 0) (tpage 0x8b) with its 256-colour CLUT at (0, 496): the costume's own
  area (all 44 models upload into x 704..959, y 0..255, CLUT rows 480..503); index 0 = see-through for cut-out alpha.
* Budgets: file bytes <= min(`file_room`, table size) (the loader 0x80050420 copies exactly the table's size, which
  lives in the encoded program); expanded extent <= 0x18000 (player 1's work buffer 0x801fe800 ends where player 2's
  character data 0x80216800 starts; player 2's ends at the vertex spill buffer 0x802a6800); vertices per slot <= the
  most the game's own models use (body 395, hand 82). `fit()` decimates with a quadric half-edge collapse (inside one
  bone, no flips, borders kept) to 100 / 85 / 70 ... % of those caps and tries pages 256 x 256 / 192 / 128, then 96 /
  64; with Blender on the node the donor is first edge-collapsed near the target.
* Container: `u32 TIM offset`, 14 records from dest 0x3c (4-byte aligned), `u32 expanded extent, u32 TIM bytes`, TIMs.
  Files are padded with zeros to the table size; the TIM uploader 0x8002d920 stops at the first word that is not 0x10.
* Checks per built file: the port expands it to exactly the laid-out meshes, the game's 0x8006c718 (4 MiB RAM, real
  work buffer) expands it to the same bytes, and the rebuilt bankedroms go through `doapp_motion.Rig` + the reader's
  `assemble` (every vertex on a bone, every primitive textured from the model's own TIM, seams <= 600 units at the bind
  pose, soles within 60 of the ground, height within 25 % of the fighter's). Traced: the fight init reads only the mesh
  headers / group lists and sections 0 / 11 (and 12's header); the renderer reads the rest.
* ROM set: the files are written over their spans in `doapp-1.217` / `doapp-2.218` (no file of the game straddles two
  chips) and the set is re-zipped with every other member unchanged. Nothing verifies the data ROMs: the TPS BIOS checks
  the SCEI licence of the program ROMs (untouched) and decodes the program, the game has no ROM test (no checksum code
  or strings in the program or BIOS); MAME flags the two chips as incorrect checksums and runs the set.

Examples (owned ROMs, collection donors, read back through the game's skeleton build): Cloud (FF7, 3324 triangles) as
Tina costume 1: 807 triangles, 14 seams, 100104 of 113332 bytes; Leon (RE4, 7980) as Kasumi 2: 855 triangles, 175
seams; DOA2 Kasumi as Ayane 4: 999 triangles, 150 seams; Aya (PE) as Bass 1: 866 triangles, 173 seams; ~20 s per
costume.

## Status

* **Inventory: done.** `python -m gbox.doapp_inventory <roms dir> [--decode] [--extract DIR]`. Tests:
  `tests/test_doapp_inventory.py`, `tests/test_zn_tps_boot.py` (the owned-ROM checks run when `GBOX_DOAPP_ROMS`
  points at the directory with `doapp.zip` + `coh1002m.zip`; they decode the program, ~40 s).
* **Format: container, section expansion, meshes, batches, bones, TIMs done** (`gbox/doapp_models.py`,
  `python -m gbox.doapp_models <roms dir> tina --expand`). The expansion runs the game's own 0x8006c718 on the
  interpreter rather than a port; chunk records decode to primitives (`primitives()`, table above).
* **Motion: format decoded and the evaluator found** (`gbox/doapp_motion.py`): it was not a separate evaluator but
  the skeleton build 0x800a4848 (FK + IK + chains) fed by the track / curve stepper; see the two sections above.
  Tests: `tests/test_doapp_motion.py` (synthetic codecs, curves, half-rate + twist keys; owned: Python decode == the
  game's stepper state, rest pose sanity).
* **Reader (rigged GLB): done** (`gbox/doapp_chars.py`, `characters.DEDICATED` entry `doapp` for the arcade titles
  starting "Dead Or Alive ++"; needs doapp.zip + coh1002m.zip beside the catalog's zip; the program decode is cached
  under `<cache>/doapp/`). Tests: `tests/test_doapp_chars.py` (synthetic primitives / texture page / skeleton / GLB with
  roles and a clip; owned: Tina and Kasumi extract verified).
* **Writer: done, MAME check pending** (`gbox/doapp_swap.py`, section "Writer" above; `char_coverage.WRITERS` +
  `characters op=use` routing; `python -m gbox.doapp_swap build <roms dir> <character dir> <out dir> <slot>`). Tests:
  `tests/test_doapp_swap.py` (synthetic: stream codec, every chunk kind through the port and back, player 2, the
  packet template, container, page, quad pairing, decimation, a full fit of a rigged humanoid onto a 15-bone fighter
  with local frames / seams / batch tables / budgets, the ROM set rebuild; owned: the packer against the game's
  expander on all 44 models, two costumes built and read back through the game's skeleton build and re-zipped,
  player 2's expansion). The program is not re-encoded: in-place replacement needs no change to it.

Next steps: the in-game check in MAME (below), then (optional) the game's renderer 0x800ab828 on the interpreter
(needs the GTE lighting commands in `gbox/psx_gte.py`) as an offline draw check.

## Live check for the maintainer

On the agent test PC, with the HyperSpin MAME roms reachable:

```
copy "\\10.89.1.125\HyperSpin Attraction\Arcade\collections\Mame\roms\doapp.zip" + coh1002m.zip  ->  %TEMP%\doapp\
python -m gbox.doapp_inventory %TEMP%\doapp --decode          # derived.file_table_matches_snapshot: true
python -m gbox.doapp_models %TEMP%\doapp tina --expand        # every mesh: covered == vertices
python -m gbox.doapp_chars %TEMP%\doapp %TEMP%\doapp\glb tina   # 4 GLBs, each line "verified": true
set GBOX_DOAPP_ROMS=%TEMP%\doapp && python -m pytest tests/test_doapp_inventory.py tests/test_doapp_models.py tests/test_doapp_motion.py tests/test_doapp_chars.py tests/test_doapp_swap.py -q
```

Writer, in MAME (not done by an agent: it launches the game):

```
python -m gbox.doapp_swap build %TEMP%\doapp <collection>\cloud %TEMP%\doapp_mod kasumi
    -> %TEMP%\doapp_mod\doapp.zip + coh1002m.zip; the JSON lists the 4 costumes with "read_back": {"ok": true, ...}
       and doapp-1.217 as the changed chip (Kasumi's models are files 79-82; Bass costumes 2-4 and Ayane's live in
       doapp-2.218)
       (checked: Cloud as Kasumi 1-4, 781-784 triangles, 22 seams each, ~99 KB of ~120 KB, ~2 min)
mame doapp -rompath %TEMP%\doapp_mod -skip_gameinfo
    (MAME names the two rebuilt chips "INCORRECT CHECKSUM": expected, the set still runs; without -skip_gameinfo
     press a key on the warning screen)
```

Or through gBox: `characters op=use character=cloud game_id=a19b4e641b155364 slot=kasumi` (mod
`doapp_cloud_kasumi`, built on the node with the collection, then `launch_game mod=doapp_cloud_kasumi`).

In the game: coin, start, pick Kasumi in each of the four costumes (one per selection button), and also as player 2
(both sides Kasumi: player 2 uses the second VRAM copy). Check in the VS screen, the round and the win pose: the
character is drawn instead of Kasumi with its textures, follows Kasumi's motions (guard, strikes, throws, falls),
shoulders / elbows / knees / ankles stay closed (seams), the hands show in every hand shape, nothing of Kasumi's
ponytail is drawn (the chains still run, empty), and the round plays to the end without a hang. Report per costume
what was seen; the hit / effect quads of section 12 are Kasumi's own and may look odd over the new page.
