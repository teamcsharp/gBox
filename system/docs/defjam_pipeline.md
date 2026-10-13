# Def Jam: Vendetta (PS2) model pipeline

Tickets: #1305 (extract the character in the middle of the screen), #1339 (character writer), #1374 (session observer
"invalid actors"). Code: `gbox/defjam_inventory.py` (disc + data.bin index), `gbox/defjam_models.py` (reader, rigged
GLB export, model-slot codec), `gbox/defjam_writer.py` (collection character into a wrestler), registered as the
`defjam_vendetta_ps2` entry of `characters.DEDICATED` and the `defjam_writer` entry of `char_coverage.WRITERS`.
The GameCube build (GDTE69, catalog `8b37766f557e1f5f`) keeps its own reader, `gbox/defjam_vendetta.py`.

## Build

| | |
|---|---|
| Catalog | `deabd11481aa5a0c`, quickswap-ps2 `Def Jam - Vendetta (USA).iso`, 2216034304 bytes |
| Boot | `SYSTEM.CNF`: `cdrom0:\SLUS_206.39;1`, VER 1.00, NTSC |
| ELF | `SLUS_206.39`, 1733616 bytes, sha256 `d071213bce13a1fe8ef2f7b241f6cb1da20e66b78b7776f23299ce81b51cb28d`, one load segment (file 0x1000 = vaddr 0x100000) |
| Data | `DATA/DATA.BIN` at LBA 408, 237606912 bytes (116019 sectors, no slack before `ICON/OUT.ICO`) |

The readers and the writer refuse anything but this exact build (`identify()["exact_build"]`).

## data.bin

The ELF opens `data/data.bin` (string at file 0x189E30) and logs `load wrestler buffer %d ( id = %d )`,
`load arena buffer`, `load audience buffer`. Its file table is at vaddr 0x256F40 (file 0x157F40): 293 x
`{u32 sector, u32 sectors}`, contiguous from sector 0 to the end of the file. Kinds by the first word:

| kind | count | entries |
|---|---|---|
| `WRS ` fighter containers | 58 | 198..255 |
| `TIM2` portraits | 120 | 5..124 |
| `0x00000080` GS texture packets | 43 | 0..4, 134..139, 141..197 (odd), 284, 285, 292 |
| `PAK ` arenas, `AUD ` crowds | 15, 14 | 125, 126, 128, 129, 258..280; 256..279 |
| `PRM `, `WAZA` move tables | 6, 1 | 286..291, 127 |
| other (count-prefixed tables, not decoded) | 36 | 130..133, 140..196 (even), 281..283 |

The wrestler table is at vaddr 0x27E100 (file 0x17F100): 32-byte records `{char *name, char *short, char *height,
char *weight, u32 id, u32 id2, u32 id3, u32 data.bin index}`. 59 named records cover the 58 buffers (Ludacris has two
records on 238; D-Mob's costumes are swapped, 234 then 233), then four "Character A..D" placeholders with index 0.
Briggs, Tank, Proof and Spider (the story heroes) have three costumes each (198..209); Peewee, Ruffneck, Sketch, Razor,
D-Mob and Manny two. `python -m gbox.defjam_inventory <iso>` prints the list.

## WRS container

`"WRS "`, u32 size, f32 scale (1.0), u32 0, then 32 self-relative u32 slot offsets at 0x10 + 4*i (0xFFFFFFFF =
empty). Slots start at 0x10 mod 0x80. Names 0..7 are the ELF's debug dump strings (file 0x18E531).

| slot | content |
|---|---|
| 0 SHADOW | shadow mesh (another layout; kept as is) |
| 1 BODY | body without the face, 42-node tree (the fight model) |
| 2 BODY2 | a denser body that also contains the head (96..100 % of FACE's vertices lie within 0.05 of a BODY2 vertex) |
| 3 FACE | face, 11-node tree (expressions) |
| 4 / 5 L HAND / R HAND | hands, 13-node trees (fingers) |
| 6 / 7 ALPHA1 / ALPHA2 | blended layers (hair cards, sheer cloth); 9 and 15 of the 58 containers carry one |
| 8 .. 13 | 32 bytes per node of BODY / FACE x 3 / hands x 2 (42, 11, 11, 11, 13, 13 records); not decoded |
| 14 .. 17 | per-node keyed s16 data (face animation candidates); not decoded |
| 18 | the fighter's texture: one GS packet |

## Model slots (1..5)

Header `{u32 geometry offset, u32 geometry size, u32 node count, u32 0}`; node records of 0x190 bytes from +0x10:
`{i32 first child, i32 next sibling, i32 palette slot (-1 = no vertices), u32 0, f32[16] A, f32[16] local bind,
0x100 zero bytes}`. Matrices are row-vector (translation in row 3). Forward kinematics of the local matrices
gives the T-pose, the same tree in all 58 containers: pelvis y 10.56, head end y 20.71, wrists x +-8.58, feet y 0
(game units, y-up, facing +Z, the wrestler's left at +X). Matrix A is not the inverse bind and is not needed.

Geometry is a VIF stream, identical in shape in all 290 model slots:
`BASE 0x100, OFFSET 0x100, NOP, UNPACK V4-32 @0x39 (static: 3-qword GIF template + 4 zero qwords + 8 qwords per
palette slot), FLUSH, MSCALF 0, NOP`, then per batch `UNPACK V4-32 FLG @0, FLUSH, MSCALF 0xB, NOP` (the last one
ends `FLUSH, MSCALF 0xB, FLUSH, NOP`); slots are padded to 0x80. A batch:

```
qword  {n_single, n_weighted, n_strips, 0x8000 | n_loose}
n_single   x {ST: f32 s, t, 1.0, u32 matrix address}  {N: xyz, 1.0}  {P: xyz, 1.0}
n_weighted x {ST: s, t, 1.0, 1.0} {N} {P} {u32 matrix a, f32 weight a, u32 matrix b, f32 weight b}
u32 strips: {length, length x VU address}, then n_loose x 3 VU addresses (independent triangles), zero padded
```

Matrix address = 64 + 8 * palette slot; the node holding that slot is the joint. A VU address is the vertex's ST
qword in the double buffer of the batch's parity: 0x200 + offset for even batches, 0x100 + offset for odd ones (all
4413 batches on the disc). Limits seen on the disc (the writer keeps to them): 76 vertices, 84 emitted indices
(strip vertices + 3 x loose), 28 loose triangles, 256 qwords per batch. Strips use the usual alternating winding;
triangles whose face normal follows the stored vertex normals are counter-clockwise (winding 0.98..1.0 on BODY).

`decode_batches` / `encode_model` rebuild all 290 model slots byte for byte.

FACE and the hands are in their own root's space; the game attaches them to BODY node 7 (head) and nodes 13 / 19
(left / right wrist). Placed there, every container's face shares 15..34 vertices and every hand 8..14 vertices with
BODY within 0.05 units (the neck and wrist rings); the reader requires 6.

## ALPHA layers (6, 7)

`{u32 node count, u32 vertices, u32 triangles, u32 0}`, 0x10 bytes, node records (0x190, from +0x20), vertices of
0x48 bytes `{f32 position[3], f32 normal[3], f32 s, t, i32 node a, i32 node b (-1), f32 weight a, f32 weight b, 0}`,
then u32 triangle indices. ALPHA2 carries the FACE tree (positions in FACE space, attached to the head); ALPHA1 the
BODY spine (10 nodes = BODY 0..8 and 41, model space): Deja's long hair, for instance, rides nodes 5..7.

## Texture (slot 18)

`u32 0x80, u32 packet size`, 0x78 more header bytes, then a GIF packet: PACKED A+D `{BITBLTBUF, TRXPOS, TRXREG,
TRXDIR}` + IMAGE for the texels and the same for the CLUT. The texels are a 512 x 512 PSMT8 page uploaded as a
256 x 256 PSMCT32 rectangle (DBW 4); `ct32_as_t8` emulates the GS page/block/column swizzle of both formats to read
it. The CLUT is 16 x 16 PSMCT32 in CSM1 order (bits 3 and 4 of the index swapped), alpha 0x80 = opaque. UVs are
`(s, 1 + t)` over the page. The decoded pages are clean (the face, clothes and props of each fighter).

## Reader -> collection

`characters op=extract` on the PS2 game lists 58 entries (names from the wrestler table, e.g. "Briggs (costume 1)",
"DMX", slugs `djv_ps2_<name>[_<costume>]`). Each run reads the WRS from the ISO and writes one GLB: BODY + FACE +
both hands (+ ALPHA layers) on one 79-joint skeleton (BODY 42 + FACE 11 + hands 13 x 2), TRS joints from the game's
local matrices, inverse binds from the T-pose, two weights per vertex, the fighter's page as the base colour, ALPHA
layers in a blended material; 1 game unit = 1/11.7 m. Roles: hip body_02, chest body_05, neck body_06, head body_07,
l/r_clav body_10/16, l/r_upper 11/17, l/r_fore 12/18, l/r_hand 13/19, l/r_thigh 25/35, l/r_shin 26/36, l/r_foot
29/39 (Capone has no vertices on the neck node, so no neck role). 58/58 containers verify (winding, unit normals,
seams, texture); bending the left elbow 90 degrees moves only the left forearm and hand, rigidly about the elbow.

```
python -m gbox.defjam_inventory <iso> [--json inv.json] [--dump DIR [index ...]]
python -m gbox.defjam_models <iso> <out_dir> [data.bin index ...]
```

## Writer (#1339)

`characters op=use character=<slug> game=<PS2 Def Jam> slot=<wrestler | player>` builds `djv_<slug>_as_<slot>`:
a copy of the ISO with the named data.bin entries patched in place (`player` = the 12 story-hero buffers,
198..209). Steps: retarget the donor onto the BODY T-pose with its roles (`sm64_swap.retarget`, JMAP in the module);
cut by joint, weld/decimate (`aki_wrestling._decimate_parts`, Blender when present); bake one 512 x 512 page
(`aki_wrestling._bake_parts`), quantise to 256 colours and write it into the container's own GS packet; encode
BODY and BODY2 as single-matrix vertices (a joint without a palette slot uses its nearest descendant's), loose
triangles, VU limits and parity as above; FACE and hands keep their trees and draw one zero-area triangle; ALPHA
vertices collapse to a point; untouched slots are copied verbatim. The container must fit the entry's sectors (the
file table is not changed): the budget steps down 2000 -> 1700 -> 1450 -> 1250 ... triangles until every target
fits (DMX into the 12 hero buffers: 1273 triangles, 552..570 KB of 573..594 KB). Every container is read back with
the reader before the image is written (triangle count, winding, page, hidden parts), and the patched image is
re-read. **Not yet verified in an emulator** (`verified_in_game: false` in the mod's `.gbox-mod.json`); the
live check is to launch the mod on a test worker and pick Briggs.

## #1305: which character

The request carries no frame or checkpoint (session 752834b708ff4061-a15a771e5d534231 ran without RenderDoc).
The only saved moment for this game, #1339's state70 (artifact 0ae707ac...66e2, a RetroArch RZIP of a PCSX2 state),
was taken during a story cinematic: its GS framebuffer shows the bridge drive FMV, and none of the 58 WRS containers
is in EE RAM (arena packs 125..129, entries 136..139 and the PRM tables are). So the reader cannot tell which
fighter was meant; all 58 are collectable by name.

## #1374: observer

The vision parser already flattens object / mapping / scalar list fields (PR #132). A bare `true` / `false` list
field now carries no item instead of failing "invalid actors"; `tests/test_session_observer_vision.py` replays a
ring / crowd / HUD shaped reply. Acceptance stays the next operator Def Jam session recording observations.
