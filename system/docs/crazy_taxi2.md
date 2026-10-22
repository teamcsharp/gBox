# Crazy Taxi 2 (Dreamcast): driver reader and writer

Request #1482. Code: `gbox/crazy_taxi2.py` (reader, `characters.DEDICATED` row `crazy_taxi2`) and
`gbox/crazy_taxi2_swap.py` (writer, `characters op=use`). Tests: `tests/test_crazy_taxi2*.py` (synthetic data,
`tests/ct2_synth.py`).

Catalog entries (all matched by title, `crazy_taxi2.title_test`): 45e9455ca5487e7d `Crazy Taxi 2` (QuickSwap2
`Crazy Taxi 2.cdi`, DiscJuggler repack), b5dfa0c44de0ba90 `Crazy Taxi 2 (USA)` (HyperSpin GD-ROM CHD), 6a286986fe83b44a,
8b1922d90b5008c5, e3f480866acf7465, bed50bf430125ec7 (PAL repack `2004-06-28-Crazy-Taxi-2-Pal-DCP`).

## Discs

| image | 1ST_READ.BIN | size | tables |
|---|---|---|---|
| QuickSwap2 `Crazy Taxi 2.cdi` (MK-51136 V1.000 2001-05-24) | `69f7bd24...` | 1460116 | known |
| HyperSpin `Crazy Taxi 2 (USA).chd` (GD-ROM, unpacked by `gbox.chd`) | `8057a8e3...` | 1452148 | known |

The two executables are different builds (every table 0x1F30 bytes apart); all `POL*` / `TEX*` files are identical
(sha256 checked for the player files). The CDI is read-only (`gdrom.patch_gdi` writes GDI sets), so the writer builds
from the GD-ROM. `gbox.chd.track_layout` needed a fix for this CHD: its CHGD records carry `PAD:150` / `PAD:44024`
(the GD-ROM gap, not stored); the layout now falls back to the 4-frame CD padding when that is what adds up to the
CHD's stored frame count (track 3 at frame 45004, not 89174).

## pol*.bin (models)

NAOMI-library objects, little endian, PowerVR TA words stored verbatim (`walk`, unchanged from #225):

* object: `u32 1, u32 1` (an empty slot: `0xFFFFFFFF, 3`), `f32` centre xyz + radius, meshes, `u32 0`, `u32` vertex
  entries (full vertices + references);
* mesh, 0x50-byte header: PCW, ISP/TSP, TSP, TCW @0x00; f32 centre + radius @0x10; u32 texture index @0x20
  (0xFFFFFFFF = none); u32 @0x24; f32 0.75 @0x28; base ARGB + offset ARGB (8 f32) @0x2C; u32 strip-data bytes @0x4C;
* strip data: `u32 flags, i32 count` records; `flags & 8` = triangle list of `count` triangles (stock 0x6A / 0x69 /
  0x6B), else a strip of `count` vertices (stock 0xF2 most often, 0xF1 / 0x72 / 0xF3 / 0x73 ...);
* an entry is a full vertex (8 f32: position, normal, u, v; UVs 0..1 top-left) or an 8-byte reference: a word with
  top nibble 5 and a signed byte offset from the end of the reference to an earlier full vertex of the same mesh. The
  reference word's low 20 bits are `-32 x` an index distance into the game's transformed-vertex buffer: for 32549 of
  the 45721 references in all pol files it is the entry distance inside the mesh; the rest count 1 to 5 more (an
  unknown extra per some strip boundary). The writer therefore emits full vertices only.

Mesh headers' TSP sizes / TCW formats disagree with the texture table in places (polPP2A texture 4: TSP 64x64, table
128x128 VQ); TCW addresses are 0. The loader fills them from the texture table; the table is authoritative.

## 1ST_READ.BIN tables

The executable's own pointers use the 0x0C010000 mirror of its load address (0x8C010000). `yam_modelpack.c`'s loader
(0x0C05AD20 in the CDI build) switches on the model group (0x000 basic, 0x100 car, 0x200 car parts, 0x300 player,
0x400 player high) and indexes four parallel arrays by the model number (PP1A..PP2D = 0..7):

| array | CDI build | GD build | entry |
|---|---|---|---|
| slot-table pointers, normal / high | 0x0C135D78 / 0x0C135D98 | 0x0C133E48 / 0x0C133E68 | -> u32 object offsets |
| slot counts, normal / high | 0x0C135DF4 / 0x0C135E14 | 0x0C133EC4 / 0x0C133EE4 | 47, 48 (Gus), 41 (polPP2CH) |
| texture-table pointers, normal / high | 0x0C13F3F4 / 0x0C13F414 | 0x0C13D4C4 / 0x0C13D4E4 | -> 16-byte entries |
| pol buffer words, normal / high | 0x0C135E70 / 0x0C135E90 | 0x0C133F40 / 0x0C133F60 | file size rounded to 32 bytes, / 4 |
| file names | 0x0C13301C (pol), 0x0C13303C (tex) ... | | |

* **Slot table**: one u32 object offset per slot, the slots **sorted by part name** (ASCII): `atama`, `kakato_l`,
  `kakato_r`, `kata_l`, `kata_r`, `koshi`, `momo_l`, `momo_r`, `mune`, `sune_l`, `sune_r`, `te_l`, `te_l_ch`,
  `te_l_gu`, `te_l_ok`, `te_r` ... `ude_l`, `ude_r`, with empty objects standing in for the names a driver lacks (the
  25 before `kakato`, `muneB`). Evidence: Gus's extra part (polPP1D, x 2.04..2.50 = the GameCube game's
  `plyrD_ude_lB` wristband) sits between `ude_l` and `ude_r`; polPP2CH (41 slots) has no gesture hands. The file's
  object order differs per driver (polPP2C swaps the left/right objects), so names come from the table only.
* **Texture table**: `u16 w, u16 h, u8 pixel format (0 ARGB1555, 1 RGB565, 2 ARGB4444), u8 PVR data format
  (1 twiddled, 2 twiddled + mipmaps, 3 VQ, 4 VQ + mipmaps, 0x0D twiddled rectangle), u16 0, u32 address in the
  0x0CB60000 load buffer, u32 0`; four 0xFFFFFFFF end it. Textures are 32-byte aligned and lay the tex file out to
  its exact end (`textures` checks). Sizes (`tex_size`): 16 bpp mipmaps start with the 1x1 level at offset 6; VQ =
  2048-byte codebook + one index byte per 2x2 block, mipmaps first (1x1 and 2x2 one byte each).
* `find_tables` finds both tables in any other build (the PAL repack) by content: the run of words that is a
  permutation of the pol file's object offsets and that 1ST_READ.BIN points at, and the texture table that lays the
  tex file out exactly (ties broken by the meshes' TCW formats). All 16 player files resolve to the known tables.

## tex*.bin

Headerless PowerVR texture data (`decode_texture`, numpy): Morton twiddle (y in the even bits), rectangles as square
Morton blocks along the long side, VQ codebook entries of 2x2 texels in the order (0,0) (0,1) (1,0) (1,1).

## Drivers

`DRIVERS` (corrected: #225 had them in the select-screen order): polPP1A..D are the first game's drivers, polPP2A..D
the new ones, checked on the decoded, textured models (Axel's green hair and shorts, and polPP1A's part extents equal
the GameCube Axel's: hips x -0.20..2.31, thigh x -0.88..4.23, chest top 4.99; Gus's wristband; Cinnamon's buns).

| file | driver | high-detail triangles (drawn) | textures | joints |
|---|---|---|---|---|
| polPP1AH | Axel | 922 | 14 | 18 |
| polPP1BH | B.D. Joe | 1180 | 11 | 18 |
| polPP1CH | Gena | 861 | 11 | 18 |
| polPP1DH | Gus (+ wristband) | 904 | 14 | 18 |
| polPP2AH | Slash | 1932 | 13 | 18 |
| polPP2BH | Iceman | 2033 | 11 | 18 |
| polPP2CH | Cinnamon | 2243 | 15 | 18 |
| polPP2DH | Hot-D | 2015 | 9 | 18 |

The plain `polPP??` files are the in-race LOD (473..617 triangles); the collection uses the `H` models.

## Rig

The parts are rigid and bone-local: each starts at its own joint with x along the bone, z the character's right; the
frame conventions are the GameCube game's (in-game probe, `gbox.crazy_taxi_look`): koshi, legs, arms, hands, feet x
down / y forward (kakato y toward the toes), mune x up the spine / y backward, atama x forward / y up.

The game poses the parts by IK from `FCVDATA.BIN` (loaded at 0x0C880000, 630 motions back to back) - no stored bone
table was found. FCV motion: `u32 a, u32 channel count (51 = 17 groups x 3; FCVSEL.BIN 57), u32 b, f32 frames`, then
one u32 word offset per channel; a channel is `u32 keys, u32 type (1 position, 2 angle in degrees, 4 scale), u32 0`,
`keys` f32 end frames, `keys` x 4 f32 cubic coefficients (value = ((a t + b) t + c) t + d from the segment start).
The positions are the root and elbow / wrist / knee / ankle targets (the in-cab motion 0: knee-ankle 4.247 on both
sides, elbow-wrist 2.513); the standing select pose puts the root at y 10.59, which matches the derived leg length.

So the rest skeleton is derived (`measures`, `skeleton`), stated as such in every extraction's notes:
bone length = the parent's reach along x + the child's start (negative where the meshes overlap), hip joints where the
thighs' inner sides meet the midline, shoulders at the chest's outer edge, the head at the chest's top centre;
standing, arms hanging, soles on y = 0, facing +Z, left = +X. 18 joints: the 15 parts + `kubi` (neck) and
`sakotsu_l/r` (clavicles) without geometry, so all 18 body roles exist (`ROLES`). Every vertex is weighted 1.0 to its
part's joint; gesture hands (`te_*_ch/gu/ok`) are left out of the GLB (`assemble(hands="gu")` draws them),
accessories ride their base part's joint.

## Writer (`gbox.crazy_taxi2_swap`)

Slots: `player` (Slash), `driver:<axel|bd_joe|gena|gus|slash|iceman|cinnamon|hot_d>`, `drivers` (all eight). Each
driver is written at both detail levels into a copied GD-ROM (mod `ct2_<slug>_<slot>`):

1. retarget: the shared Crazy Taxi v2 fit (`crazy_taxi_look.load_donor / assign_parts / part_maps / split_torso /
   build_atlas / part_geometry`) on the stock part frames and measures (`look_measures`), winding matched to the
   stock part; fit events scale / retarget / weights / decimate / encode;
2. geometry: per part one opaque textured mesh on the stock part's first mesh header (texture index, TSP size, TCW
   pixel format / VQ / mipmap bits from the atlas slot), vertices welded by position + UV, strips (0xF2) + one list
   (0x6A), full vertices only; gesture hands carry the donor's hand, accessories one zero-area triangle at their
   stock centre (so the name table still reads them as accessories). Per-part triangle targets follow the stock
   driver's per-part triangle counts, scaled until the file fits the pol buffer (quadric collapse,
   `auf_swap.decimate`); no object above 678 vertex entries (the largest stock object);
3. textures: the texture table is not changed; the atlas is encoded into the driver's largest slot in that slot's own
   format (twiddled / rectangle / mipmapped RGB565 or ARGB4444, or VQ with a k-means codebook), the tex file keeps
   its length (VRAM unchanged);
4. 1ST_READ.BIN: the slot tables get the new object offsets (counts, texture tables and buffer sizes unchanged);
5. `validate` (PowerVR / loader safety, every written file): PCW type 4 and list type, TSP size and TCW bits equal to
   the texture entry, texture index in range, strip lengths >= 3 and < 65536, finite vertices / UVs, object entries
   <= 678, pol size <= its buffer, power-of-two 8..1024 textures laying the file out, <= 8 MB, slot offsets on object
   starts, part names read back; then the GD-ROM copy is read back file by file and every driver re-assembled.

Checked on the owned GD-ROM: Sonic (SA2) as Slash and SM64DS Mario as all eight drivers write, validate and read back
(Mario: 395..452 high-detail / 204..343 race triangles; Sonic as Slash: 752 / 234; budgets 90176 / 33088 bytes). A full
GD-ROM copy (`python -m gbox.crazy_taxi2_swap disc.gdi <character dir> driver:slash <out> --image ct2_sonic_slash`)
builds in about a minute and reads back.

## Evidence (D:\gBox\research\crazy_taxi2\evidence, offline renders)

* `ct2_reader_ct1_drivers.png`, `ct2_reader_ct2_drivers.png`, `ct2_reader_side_views.png`: the eight drivers read from
  the disc, rigged and textured;
* `ct2_swap_sonic_as_slash_{high,race}.png`, `ct2_swap_mario_as_cinnamon_{high,race}.png`,
  `ct2_swap_mario_as_gus_{high,race}.png`: stock vs written, read back from the written files and drawn on the stock
  driver's skeleton (`assemble(measures_from=...)`, as the game keeps its own rig).

## Not done

* No in-game frame: the writer is unverified in Flycast (the GD-ROM copy builds and reads back; the driver-select
  screen and a race with the swapped driver are untested). Risks: the TCW/TSP fill rule of the loader (assumed from
  the texture table), the transformed-vertex buffer (the writer avoids references and stays within the stock object
  size), the driver's pol buffer (kept).
* The skeleton is derived from the meshes, not decoded: the IK solver and the bone lengths it uses sit in the FCV
  motion player (0x0C05F470 sets a motion on the person object at 0x0C2B9C1C), not yet read. The donor proportions
  follow the shared Crazy Taxi retarget (short-legged donors like Mario get large heads, hands and torsos at the
  driver's leg length).
* Vertex references: the rule for the extra counts in the reference word is unknown; the writer does not need it.
* Pedestrians (polPPL0), fares (polPSG0) and cabs (polPC*) are walked by `walk` but not assembled.

## Owned-build manifest (request #2454, `gbox.crazy_taxi2_cdi_inventory`)

`python3 -m gbox.crazy_taxi2_cdi_inventory "/mnt/gbox/quickswap2/Emulation/_emulation/_dc iso/Crazy Taxi 2.cdi" --out docs/crazy_taxi2_cdi_manifest.json` streams the owned image (sha256 of the 787688567-byte .cdi), walks the member table, hashes every driver bank and every member pinned in `crazy_taxi2.FILES_SHA256`, walks all 35 `POL*.BIN` with `crazy_taxi2.walk`, and resolves the native target slot (Axel, `PP1A` high-detail: `POLPP1AH.BIN` + `TEXPP1AH.BIN`) with its 1ST_READ.BIN slot and texture tables. The image is opened read-only; nothing on the disc or the share is written.
