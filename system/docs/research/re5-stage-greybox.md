# RE5 Switch: the stage as a greybox, and a prop replaced by a grid box

2026-11-09. The operator wants to replace the assets of a level itself - tables, boxes, the walls - and to be able to
draw a whole level like a UE blueprint / blockout. This note is the first pass on RE5 Switch (title `010018100CD46000`)
for the Mercenaries stage Public Assembly (`s400.arc`): what the stage archive holds, how its geometry, materials and
textures are laid out, a writer that redraws every stage albedo as an Unreal-style grid, the list of objects the stage
places, and one object (the wooden crate) rewritten as a grid box.

**Nothing here has been booted.** Both candidates pass the offline checks (byte-identical rebuild of everything not
replaced, native container headers, receipts with SHA-256) and have CPU pictures. Neither has been loaded by the game.
Every receipt says `live_verified: false`. What a first boot must show, and how it can fail, is at the end.

| | |
|---|---|
| Writer | `system/gbox/re5_stage_greybox.py` (`measure`, `classify`, `plan`, `grid_image`, `greybox_texture`, `build`, `verify`, `render_stage`, `box_model`, `build_prop_box`, `render_model`, CLI) |
| Tests | `system/tests/test_re5_stage_greybox.py` - 14 tests on synthetic fixtures (bone-less stage MOD in the measured formats, MRL v34, BC7 TEX with the Tegra mip storage, a one-bone object with a depth proxy) |
| Inputs (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\stage\inputs\s400.arc` (SHA-256 `246e3dd4…`, 75,672,496 bytes) and `inputs\uom\uOm*.arc` (the 32 object archives s400 references, 57 MB), copied read-only from the host |
| Outputs (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\assets\stage-greybox-s400-v1\` and `assets\prop-box-crate-v1\` - see [Overlays](#overlays) |
| Shared code touched | none; `mt_arc`, `mt_model`, `mtf_author.mesh_triangles`, `mtf_mrl`, `mtf_tex` are used as they are |

## 1. What `s400.arc` is

590 entries, ARC version 7. Every entry is a wrapped zlib stream that recompresses byte-identically at level 6, every tag
is `0x40000000 | uncompressed length`, and `mt_arc.build(mt_arc.parse(x)) == x`. By type (the entry's hash word):

| entries | type | what |
|---|---|---|
| 264 | TEX `241f5deb` | textures (below) |
| 57 | MOD `58a15856` | 44 scene pieces under `stage\s400\scr\scr01\`, 2 under `scr00` (`s400h_scr`, `s400h_eff`, one texture, materials that bind no texture - read as hit / effect geometry), 8 effect models `effect\mod\…`, 3 `s114_Smodel*` shadow models |
| 56 | MRL `2749c8a8` | one per MOD, same entry name |
| 62 | XFS `15302ef4` | 44 enemy layouts (`sNNN_emXX`, the census of [re5-enemy-cast.md](re5-enemy-cast.md)), `scr00\s400_IDo00_Ins` (the placed static objects), per mode `s400_IDF00_Ins` / `s400_IDF01_Ins` (the interactive objects) and `s400_Item*` (item pickups) |
| 25 + 15 | XFS `25f4d5ad`, `65b275e5` | per mode the FSM files (`EmSetArea*`, `fix\…`) and `s400_fsm`, `s400_noitem`, `s400_sce` |
| 32 | `79c47b59` | stage sounds |
| 24 | SDL `4c0db839` | light links and scene lists |
| 16 + 15 + 6 | SRQR, EFL, EAN | sound requests, effect lists, effect animations |
| 1 | NAV `67a9300b` | the navigation mesh (314 KB) |
| 1 | `36e29465` | Havok collision (230 KB) |
| rest | cube map list, radio BGM, map images, light settings | |

Each stage archive is self-contained: the textures of the Public Assembly scenery are inside `s400.arc` (their names
say `s114`, the campaign chapter the stage was cut from), so a greybox of one stage touches one file.

### Textures

264 TEX. Header bytes 4-7 are `a1 80 00 20` on 257 of them and `a1 80 00 60` on the 7 cube maps (6 faces).

| format | count | what | writer |
|---|---|---|---|
| `0x30` BC7 | 174 | 159 `_BM` albedos under `scr01`, 6 effect sheets, 7 effect-model albedos, 2 map images | `mtf_tex.parse` accepts every `scr01` one; `mtf_tex.replace_image` rewrites it |
| `0x13` BC1 | 38 | 31 `_LM` light maps, 7 `_CM` cube maps | kept native (not measured for writing) |
| `0x19` BC4 | 29 | `_MM` masks, one `_AM` alpha map | kept |
| `0x1F` BC5 | 20 | `_NM` normal maps | kept |
| `0x15` | 2 | two non-power-of-two map images | kept |
| `0x07` | 1 | a local `NullWhite` | kept |

The RE5 Switch TEX is the layout `mtf_tex` already measured (`TEX\0 a1 80 00 20`, packed mips / width / height,
`00 01 <format> 01`, one mip offset table, Tegra block-linear GOBs): it is the same container as RE6's with revision
byte `0x80`, and the stage albedos are **BC7**, not RE6's BC3 Y'CbCr. `re6_switch_tex.encode_albedo` is therefore not
the path; `mtf_tex.replace_image` (the BC7 path the live Sonic and Mario atlases went through) is.

### Geometry: the stage vertex formats

The 44 `scr01` MODs have **no bones** (bones offset 0, the group table at 164) and 1,850 mesh records in eight vertex
formats. Measured on all of them (`fvf` survey, 339,000 vertices): position is three `float32` at +0 on every format;
a signed-byte normal with `w = -1` sits at +12 (unit length on 99-100 % of vertices; agreement with the geometric face
normal 97.8-100 %); a signed-byte tangent with `w = 127` at +16; the albedo UV as two half floats at +20.

| format | stride | meshes | +24 | +28 | family of the materials using it |
|---|---|---|---|---|---|
| `0x287029D8` | 24 | 586 | - | - | `XfB`, `a_XfBAL`, some `XfB_L` / `XfB_W` |
| `0x29F0B449` | 28 | 686 | RGBA8 colour (alpha 255) | - | `XfB_W*`, `XfBAW`, `XfB_N__EW*` - vertex-lit, no light map |
| `0x2AE06DB8` | 32 | 523 | light-map UV (half2, all inside 0..1) | constant 0 | `XfB_L*`, `XfBAL`, `XfB_N__EL*` - lightmapped |
| `0x2ED06F92` | 32 | 38 | second UV | RGBA8 colour | `XfB_N__EW`, `XfB_W` |
| `0x2FC0B663` | 36 | 9 | second UV | light-map UV | `XfB_N__EL_S` |
| `0x32305512` | 32 | 2 | second UV | light-map UV | `XfB_L_A` (not in `mt_model`'s stride table; measured here) |
| `0x37607D20` | 24 | 3 | does not follow this layout | | skipped |

The material name carries the shader: `polySurface21509SG3.mikabe.XfB_L_` → family `XfB_L`. `L` = lightmapped (the
material binds an `_LM` in slot `0xAA6F0` and the mesh carries a light-map UV), `W` = vertex-lit (colour at +24),
`A` after `XfB` = alpha-tested (fences, wires, leaves, grass), `N__E` = normal map + environment cube. 523 of the 535
lightmapped meshes use `0x2AE06DB8`; 676 of the 678 vertex-lit ones use `0x29F0B449`.

Index words are absolute inside the mesh's vertex window (`[vertex_index, vertex_index + count - 1]`, 1,700 meshes)
or already local when `vertex_index` is 0 (147); `mtf_author.mesh_triangles` decodes the strips. With that winding,
`cross(p1 - p0, p2 - p0)` points along the vertex normal, so front faces are counter-clockwise seen from outside.

### Materials: which texture goes where

`mtf_mrl.parse` accepts 51 of the 56 MRLs (v34, shader `0x7BE0E51F`). The five it refuses (`s400h_*`, `s114_Smodel*`)
have one texture and commands that index outside that table - geometry without a drawn surface. The texture slots by
shader hash, measured on all 51: `0xCD06F` albedo (`_BM`), `0xAA6F0` light map (`_LM` or `NullWhite`), `0x22660`
normal (`_NM`), `0x0ED1B` mask (`_MM`), `0x1698A` alpha map (`_AM`), `0x64C43` environment (`DefaultCube_CM`), and two
slots always on `NullWhite` (`0x9333B`, `0x05F2A`). Every one of the 1,312 measured meshes resolves to an albedo
(`unbound_materials: 0`).

## 2. The greybox look

`re5_stage_greybox.build(archive, stage='s400')` rewrites the 159 BC7 albedos under `stage\s400\scr\scr01\`. Every
other entry - MODs, MRLs, light maps, normal and mask maps, the alpha map, cube maps, layouts, sounds, the navigation
mesh - is byte-identical, and so is each albedo's TEX header, mip table, size and **alpha channel** (decoded from the
native mip 0 and written back under the grid), so the alpha-tested fences, wires and foliage keep their cut-outs.

### How a texture is classified and scaled

For every mesh of every scene piece the writer decodes positions, vertex normals, the albedo UV and the triangles, and
charges each triangle to the albedo its material binds (`measure`). Per albedo it then has:

- the area shares of triangles facing up (`normal.y > 0.5`), sideways (`|normal.y| <= 0.5`) and down;
- the centimetres one UV tile spans along u and along v: the UV→world Jacobian of each triangle (`|T|`, `|B|`),
  area-weighted median and quartiles over the triangles that sample the texture.

`classify` decides in this order, and the receipt records which rule fired:

1. the name says sky (`sky`) → **sky**, a flat pale blue-grey; the name says roof (`yane`) → **other** (a roof faces up
   like a floor; a blockout does not paint it as one);
2. **geometry**: up share ≥ 0.6 → **floor**; side share ≥ 0.6 → **wall**; down share ≥ 0.6 → **other** (ceilings);
3. where the geometry is mixed, the **name**: `jimen`, `yuka`, `miti`, `doro`, `suna`, `dobu`, `soko`, `jiso`, `asiba`,
   `kaidan`, `dote` (ground, floor, road, mud, sand, ditch, bottom, scaffold, stairs, bank) → floor; `kabe`, `heki`,
   `totan`, `renga`, `saku`, `hei`, `mon`, `tobira`, `door`, `mado`, `window`, `yatai`, `biru`, `bill`, `ie`, `koya`
   (wall, corrugated iron, brick, fence, gate, door, window, stall, building, house, hut) → wall;
4. otherwise **other** (checker).

On s400 the geometry alone decided 120 of 159 (95 side, 24 up, 1 down), the name 12 (4 roof, 3 `kabe`, 2 sky, `dobu`,
`bill`, `koya`, `ie`), and 26 fell to the checker default (mixed props: pots, cloth, cables, planks, fish, a TV
aerial). One albedo (`y-s114-skyA_BM`) is bound by no `scr01` material; it is drawn as sky by name.

**Grid scale.** One major cell per metre of the tile span: `cells = round(tile_cm / 100)` clamped to 1..32, separately
along u and v, so a wall texture that tiles every 16 m × 5 m gets a 16 × 5 grid and a ground texture that tiles every
19 m × 27 m gets 19 × 27 - in the world both are 1 m squares. Below 1.5 m the whole tile is one cell and the label
gives the true span (`0.5 m`, `8 cm`). Minor lines quarter each cell where they stay readable. Labels: floors carry the
pixel width (`1024`, `512`, …) in the Kenney / UE prototype style with the metre span small in a corner; walls and the
checker carry the span (`04 m`, `16 m x 05 m`).

**How consistent the UV scale is per surface class.** The receipt has the quartiles of every texture's tile span. The
ratio of the upper to the lower quartile along u is 1.29 at the median; 75 % of the textures are within ×1.5, so one
grid per texture is a fair grid for three quarters of them. The worst are the big ground sheets whose artists scaled
the UV per patch (`y_jimetesuB_BM` 10-36 m per tile, ratio 3.5; `y-s114-gomigakeA_BM` 9-21 m; `n-bill02_BM` ×3.7) -
there the metre grid will be right on the median patch and off by up to ×2 on the others. Per surface class the
medians are: floors 0.75-22 m per tile (the large sheets), walls 0.5-20 m, props 0.2-9 m. A per-mesh UV rescale (edit
the UVs so every patch of one texture has the same density) would make the grid exact everywhere; it is a MOD edit this
pass does not make.

### The 159 albedos of s400

Sizes, mips, class (rule), cells, tile span (median and quartiles in cm), area shares, shader families, and whether the
alpha is a cut-out (`XfBA*`) or merely kept. All are BC7 (`0x30`).

| albedo (`scr01\`) | px | mips | variant (rule) | grid cells u x v | tile span u / v (cm, median; quartiles) | shares up/side/down | shader families | alpha |
|---|---|---|---|---|---|---|---|---|
| `misetukueB_BM` | 512x256 | 10 | floor (geometry:up) | 2 x 1 | 244 (228-260) / 109 (93-124) | 0.63/0.31/0.06 | XfB_W | kept |
| `s100_t_yuka02_BM` | 1024x512 | 11 | floor (geometry:up) | 6 x 6 | 633 (628-633) / 649 (649-718) | 0.92/0.08/0.00 | XfB_L | kept |
| `s100_y_yukaAa_BM` | 512x512 | 10 | floor (geometry:up) | 4 x 4 | 402 (322-468) / 384 (279-542) | 0.79/0.00/0.21 | XfB_L | kept |
| `y-s114-akayuka_BM` | 512x512 | 10 | floor (geometry:up) | 4 x 3 | 355 (355-355) / 342 (342-342) | 1.00/0.00/0.00 | XfB_L | kept |
| `y-s114-dobudote_BM` | 1024x512 | 11 | floor (name:dobu) | 7 x 3 | 661 (510-691) / 309 (256-408) | 0.42/0.58/0.00 | XfB_L | kept |
| `y-s114-dobudoteheri_BM` | 1024x512 | 11 | floor (geometry:up) | 4 x 2 | 386 (371-449) / 153 (99-171) | 0.84/0.15/0.00 | XfBAL | cut-out |
| `y-s114-dobusoko_BM` | 1024x512 | 11 | floor (geometry:up) | 6 x 4 | 561 (555-590) / 364 (321-364) | 1.00/0.00/0.00 | XfB_L | kept |
| `y-s114-gomigakeA_BM` | 1024x1024 | 11 | floor (geometry:up) | 17 x 11 | 1705 (944-2108) / 1065 (777-1336) | 0.95/0.05/0.00 | XfB_L, XfB_L_A | kept |
| `y-s114-jimetesuDa_BM` | 1024x1024 | 11 | floor (geometry:up) | 10 x 6 | 1007 (503-1047) / 572 (568-985) | 1.00/0.00/0.00 | XfB_L | kept |
| `y-s114-jimetesuF_BM` | 512x1024 | 11 | floor (geometry:up) | 3 x 6 | 292 (248-351) / 614 (466-730) | 1.00/0.00/0.00 | XfBAL | cut-out |
| `y-s114-jinajimiA_BM` | 512x256 | 10 | floor (geometry:up) | 2 x 1 | 215 (194-275) / 120 (88-137) | 0.96/0.04/0.00 | XfBAL | cut-out |
| `y-s114-kaidanA_BM` | 256x256 | 9 | floor (geometry:up) | 2 x 3 | 232 (222-239) / 284 (174-387) | 0.81/0.18/0.01 | XfB_L | kept |
| `y-s114-kamajimen_BM` | 512x512 | 10 | floor (geometry:up) | 6 x 4 | 600 (400-600) / 400 (400-410) | 1.00/0.00/0.00 | XfBAL | cut-out |
| `y-s114-konku_BM` | 1024x512 | 11 | floor (geometry:up) | 10 x 9 | 969 (768-1525) / 858 (611-1691) | 0.79/0.07/0.14 | XfB_L, XfB_L_S, XfB_W | kept |
| `y-s114-najimiyuka_BM` | 512x128 | 10 | floor (geometry:up) | 3 x 1 | 349 (300-385) / 122 (102-122) | 1.00/0.00/0.00 | XfBAL, XfBAL_S | cut-out |
| `y-s114-sotoyuka_BM` | 1024x256 | 11 | floor (geometry:up) | 6 x 1 | 599 (430-712) / 146 (131-196) | 0.85/0.15/0.00 | XfB_L, XfB_L_S | kept |
| `y-s114-suramubackC_BM` | 1024x1024 | 11 | floor (geometry:up) | 22 x 21 | 2170 (2170-2194) / 2132 (1824-2714) | 0.79/0.18/0.03 | XfB_L | kept |
| `y_gomi_BM` | 128x128 | 8 | floor (geometry:up) | 1 x 1 | 75 (66-75) / 74 (73-75) | 1.00/0.00/0.00 | XfB_W | kept |
| `y_jimeheriA_bak_BM` | 512x256 | 10 | floor (geometry:up) | 2 x 1 | 196 (122-264) / 118 (96-124) | 1.00/0.00/0.00 | XfBAL | cut-out |
| `y_jimetesuB_BM` | 1024x1024 | 11 | floor (geometry:up) | 19 x 27 | 1922 (1035-3633) / 2725 (1443-4428) | 1.00/0.00/0.00 | XfB_L | kept |
| `y_okujyoAa_BM` | 256x256 | 9 | floor (geometry:up) | 3 x 3 | 305 (305-305) / 307 (307-307) | 1.00/0.00/0.00 | XfB_N__EL_S | kept |
| `y_s103_bloodA_BM` | 256x256 | 9 | floor (geometry:up) | 1 x 2 | 146 (106-160) / 217 (167-217) | 0.79/0.21/0.00 | XfBAW | cut-out |
| `y_s103doramu_ue_BM` | 256x256 | 9 | floor (geometry:up) | 1 x 1 | 70 (70-70) / 72 (72-72) | 0.60/0.09/0.31 | XfB_N__EW, XfB_W | kept |
| `y_syokumatA_BM` | 256x256 | 9 | floor (geometry:up) | 2 x 1 | 185 (172-185) / 127 (126-127) | 0.93/0.06/0.00 | XfB_W | kept |
| `yakkyou_BM` | 64x64 | 7 | floor (geometry:up) | 1 x 1 | 9 (9-9) / 13 (13-13) | 1.00/0.00/0.00 | XfB_L | kept |
| `k_om_cableB01_01_BM` | 512x16 | 10 | other (default) | 13 x 1 | 1273 (1087-1885) / 20 (20-20) | 0.25/0.50/0.25 | XfBAW | cut-out |
| `nidai02_BM` | 256x512 | 10 | other (default) | 1 x 2 | 108 (104-129) / 211 (142-242) | 0.28/0.42/0.30 | XfB_W | kept |
| `om_nabeA01_01_BM` | 256x256 | 9 | other (default) | 1 x 1 | 125 (122-129) / 64 (64-64) | 0.49/0.41/0.10 | XfB_N__EW | kept |
| `om_nunoD01_01_BM` | 256x32 | 9 | other (default) | 1 x 1 | 22 (21-26) / 5 (5-6) | 0.33/0.33/0.33 | XfB_W | kept |
| `s100_t_ki04_BM` | 512x32 | 10 | other (default) | 2 x 1 | 226 (83-242) / 20 (13-21) | 0.35/0.29/0.36 | XfB_L | kept |
| `s100_t_nuno02_BM` | 256x256 | 9 | other (default) | 3 x 1 | 255 (213-278) / 112 (99-121) | 0.60/0.00/0.40 | XfB_L, XfB_W | kept |
| `s100_t_tetu01_BM` | 512x512 | 10 | other (default) | 1 x 1 | 129 (128-136) / 136 (135-143) | 0.37/0.26/0.36 | XfB_W | kept |
| `s101_y_kiB_BM` | 128x1024 | 11 | other (default) | 1 x 1 | 12 (10-19) / 141 (111-282) | 0.30/0.48/0.22 | XfB_L, XfB_L_S, XfB_W | kept |
| `s114_18_BM` | 256x256 | 9 | other (default) | 4 x 1 | 351 (331-420) / 98 (94-103) | 0.50/0.00/0.50 | XfB_L | kept |
| `sitaihukuro_BM` | 512x512 | 10 | other (default) | 2 x 2 | 175 (157-204) / 152 (108-180) | 0.30/0.40/0.30 | XfB_W | kept |
| `tyoA_BM` | 64x256 | 9 | other (default) | 1 x 1 | 22 (17-27) / 66 (44-70) | 0.50/0.50/0.00 | XfB_W | kept |
| `y-s114-17_BM` | 512x256 | 10 | other (default) | 7 x 3 | 721 (714-768) / 289 (282-306) | 0.22/0.47/0.31 | XfB_L | kept |
| `y-s114-basue_BM` | 1024x512 | 11 | other (default) | 6 x 3 | 564 (462-908) / 298 (271-534) | 0.39/0.34/0.27 | XfB_N__EL_S, XfB_W | kept |
| `y-s114-em1a00_BM` | 512x256 | 10 | other (default) | 2 x 1 | 197 (145-250) / 133 (124-186) | 0.18/0.56/0.26 | XfB_N__EW | kept |
| `y-s114-mawaku_BM` | 64x512 | 10 | other (default) | 1 x 2 | 36 (31-37) / 182 (151-274) | 0.24/0.52/0.24 | XfB_W | kept |
| `y-s114-silver_house_BM` | 512x512 | 10 | other (default) | 9 x 4 | 886 (776-940) / 404 (355-437) | 0.24/0.52/0.24 | XfB_L, XfB_W | kept |
| `y-s114-yagurakiA_BM` | 1024x512 | 11 | other (default) | 3 x 1 | 261 (219-307) / 138 (107-166) | 0.38/0.31/0.31 | XfB_L, XfB_W | kept |
| `y-s114-yane_BM` | 1024x256 | 11 | other (name:roof) | 10 x 6 | 1012 (952-1252) / 596 (528-612) | 0.74/0.00/0.26 | XfB_L | kept |
| `y-s114-yaneura_BM` | 256x512 | 10 | other (name:roof) | 3 x 3 | 312 (267-322) / 294 (293-300) | 0.00/0.07/0.93 | XfB_L | kept |
| `y_donou_BM` | 256x512 | 10 | other (default) | 1 x 1 | 95 (81-105) / 120 (112-140) | 0.38/0.24/0.38 | XfB_N__EW | kept |
| `y_haigyoA_BM` | 1024x128 | 11 | other (default) | 2 x 1 | 203 (186-223) / 58 (48-69) | 0.34/0.28/0.38 | XfB_N__EW | kept |
| `y_keikouA_BM` | 512x32 | 10 | other (default) | 1 x 1 | 141 (141-143) / 8 (8-8) | 0.33/0.34/0.33 | XfB_W | kept |
| `y_kiD_BM` | 512x64 | 10 | other (default) | 3 x 1 | 279 (160-389) / 12 (10-20) | 0.26/0.49/0.26 | XfB_L, XfB_W | kept |
| `y_kiDa_BM` | 512x32 | 10 | other (default) | 2 x 1 | 173 (68-314) / 4 (2-7) | 0.39/0.44/0.17 | XfB_L, XfB_L_S, XfB_W | kept |
| `y_nawaA_BM` | 256x32 | 9 | other (default) | 1 x 1 | 20 (16-30) / 6 (4-6) | 0.30/0.41/0.30 | XfB_W | kept |
| `y_s103danmenB_BM` | 512x128 | 10 | other (default) | 1 x 1 | 85 (68-118) / 29 (24-40) | 0.43/0.42/0.15 | XfB_L, XfB_W | kept |
| `y_taigerfish_BM` | 128x256 | 9 | other (default) | 1 x 1 | 45 (43-55) / 113 (109-114) | 0.40/0.21/0.40 | XfB_N__EW | kept |
| `y_ugari_BM` | 128x256 | 9 | other (default) | 1 x 1 | 44 (39-53) / 52 (48-57) | 0.31/0.40/0.30 | XfB_N__EW | kept |
| `y_yaneAa_BM` | 256x256 | 9 | other (name:roof) | 5 x 3 | 472 (398-480) / 323 (238-558) | 0.50/0.00/0.50 | XfB_L | kept |
| `ya_ienakaCa_BM` | 512x512 | 10 | other (geometry:down) | 5 x 5 | 503 (499-504) / 471 (288-471) | 0.00/0.00/1.00 | XfB_L, XfB_L_S | kept |
| `yane5_BM` | 512x512 | 10 | other (name:roof) | 5 x 5 | 495 (441-550) / 489 (416-539) | 0.69/0.02/0.30 | XfBAL, XfB_L, XfB_W | cut-out |
| `y-s114-skyA_BM` | 2048x1024 | 12 | sky (name:sky) | 1 x 1 | - / - | 0.00/0.00/0.00 | - | kept |
| `y-s400-skyA_BM` | 2048x1024 | 12 | sky (name:sky) | 32 x 32 | 33649 (26704-37300) / 22788 (14821-23665) | 0.00/0.42/0.58 | XfB | kept |
| `misetukueA_BM` | 256x256 | 9 | wall (geometry:side) | 1 x 1 | 124 (99-170) / 92 (88-102) | 0.00/1.00/0.00 | XfB_L, XfB_W | kept |
| `misetukueD_BM` | 256x256 | 9 | wall (geometry:side) | 2 x 1 | 205 (154-206) / 91 (86-94) | 0.00/1.00/0.00 | XfB_W | kept |
| `n-bill00_BM` | 512x512 | 10 | wall (geometry:side) | 9 x 12 | 914 (884-1123) / 1196 (1196-1469) | 0.16/0.84/0.00 | XfB_L | kept |
| `n-bill02_BM` | 512x512 | 10 | wall (name:bill) | 18 x 11 | 1779 (1230-4593) / 1148 (1000-3589) | 0.14/0.58/0.28 | XfB_L | kept |
| `nidai01_BM` | 512x256 | 10 | wall (geometry:side) | 1 x 1 | 131 (112-174) / 66 (53-83) | 0.07/0.86/0.07 | XfB_L, XfB_L_S, XfB_W | kept |
| `om_hiraA01_01_BM` | 512x64 | 10 | wall (geometry:side) | 3 x 1 | 252 (251-252) / 29 (29-29) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `om_kanbanC01_01_BM` | 512x256 | 10 | wall (geometry:side) | 4 x 2 | 434 (368-550) / 201 (141-210) | 0.07/0.87/0.07 | XfB_L, XfB_W | kept |
| `om_nunoD01_02_BM` | 256x256 | 9 | wall (geometry:side) | 1 x 1 | 49 (47-50) / 112 (95-113) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `om_nunoD01_03_BM` | 256x256 | 9 | wall (geometry:side) | 1 x 1 | 53 (50-65) / 100 (68-109) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `om_nunoD01_04_BM` | 256x512 | 10 | wall (geometry:side) | 1 x 1 | 114 (94-114) / 118 (94-161) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `om_posterA01_01_BM` | 512x128 | 10 | wall (geometry:side) | 3 x 1 | 311 (276-340) / 64 (57-70) | 0.00/1.00/0.00 | XfB_W | kept |
| `om_posterA01_02_BM` | 128x128 | 8 | wall (geometry:side) | 1 x 1 | 80 (61-99) / 82 (67-91) | 0.00/1.00/0.00 | XfB_W | kept |
| `om_posterB01_01_BM` | 128x128 | 8 | wall (geometry:side) | 1 x 1 | 46 (40-46) / 66 (56-66) | 0.00/1.00/0.00 | XfB_W | kept |
| `perayasi_BM` | 256x512 | 10 | wall (geometry:side) | 5 x 10 | 511 (457-513) / 1020 (929-1044) | 0.00/1.00/0.00 | XfBAL | cut-out |
| `s100_t_fence02_BM` | 1024x512 | 11 | wall (geometry:side) | 4 x 1 | 409 (351-491) / 123 (118-132) | 0.03/0.94/0.03 | XfBAW | cut-out |
| `s100_t_kabe08_BM` | 1024x512 | 11 | wall (geometry:side) | 9 x 3 | 882 (531-1077) / 277 (270-280) | 0.03/0.95/0.01 | XfB_L, XfB_N__EW | kept |
| `s100_t_kabe14_BM` | 512x512 | 10 | wall (name:kabe) | 5 x 3 | 482 (434-605) / 290 (290-562) | 0.28/0.50/0.22 | XfB_L | kept |
| `s100_t_nuno01_BM` | 256x128 | 9 | wall (geometry:side) | 1 x 1 | 106 (96-114) / 26 (25-27) | 0.12/0.80/0.08 | XfBAL, XfBAW | cut-out |
| `s100_t_nuno03_BM` | 512x256 | 10 | wall (geometry:side) | 3 x 1 | 259 (221-282) / 71 (67-73) | 0.05/0.92/0.03 | XfBAL, XfBAW | cut-out |
| `s100_t_tetu02_BM` | 64x512 | 10 | wall (geometry:side) | 1 x 3 | 12 (11-15) / 277 (140-502) | 0.17/0.66/0.17 | XfB_W | kept |
| `s100_t_tetu03_BM` | 64x512 | 10 | wall (geometry:side) | 1 x 1 | 14 (14-14) / 135 (129-136) | 0.00/1.00/0.00 | XfB_W | kept |
| `s100_y_minkaCa_BM` | 512x512 | 10 | wall (geometry:side) | 3 x 3 | 338 (294-390) / 321 (320-333) | 0.07/0.89/0.03 | XfB_L | kept |
| `s100_y_minkaCb_BM` | 512x128 | 10 | wall (geometry:side) | 5 x 2 | 461 (461-498) / 187 (186-187) | 0.01/0.98/0.01 | XfB_L | kept |
| `s100_y_minkaCc_BM` | 512x512 | 10 | wall (geometry:side) | 4 x 3 | 384 (374-448) / 303 (290-304) | 0.02/0.97/0.01 | XfB_L | kept |
| `s100_y_minkaCd_BM` | 128x512 | 10 | wall (geometry:side) | 1 x 2 | 147 (145-147) / 240 (239-240) | 0.01/0.97/0.02 | XfB_L | kept |
| `s100_y_pipeA_BM` | 32x512 | 10 | wall (geometry:side) | 1 x 1 | 8 (6-10) / 125 (64-197) | 0.13/0.74/0.13 | XfB_N__EW, XfB_N__EW_S | kept |
| `s101_midotaiyaAa_BM` | 64x128 | 8 | wall (geometry:side) | 1 x 1 | 24 (16-24) / 30 (30-53) | 0.26/0.67/0.08 | XfB_N__EL, XfB_N__EW | kept |
| `s101_midotaiya_BM` | 256x128 | 9 | wall (geometry:side) | 1 x 1 | 126 (121-130) / 131 (128-132) | 0.00/1.00/0.00 | XfB_N__EL, XfB_N__EW | kept |
| `s101_y_tutikabeAa_BM` | 1024x512 | 11 | wall (geometry:side) | 9 x 3 | 871 (871-1071) / 347 (347-347) | 0.02/0.69/0.28 | XfB_L | kept |
| `s102_T_kabe107_BM` | 512x512 | 10 | wall (geometry:side) | 7 x 3 | 682 (546-683) / 328 (237-349) | 0.06/0.92/0.03 | XfB_L, XfB_W | kept |
| `s102_T_kabe67_BM` | 1024x512 | 11 | wall (geometry:side) | 6 x 3 | 616 (614-756) / 313 (310-315) | 0.16/0.74/0.10 | XfB_W | kept |
| `s102_T_mon01_BM` | 256x512 | 10 | wall (geometry:side) | 1 x 1 | - / - | 0.00/1.00/0.00 | XfB_L | kept |
| `s102_T_sen04_BM` | 256x64 | 9 | wall (geometry:side) | 1 x 1 | 140 (88-164) / 18 (15-18) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `s114_21_BM` | 1024x512 | 11 | wall (geometry:side) | 7 x 2 | 650 (508-802) / 230 (170-262) | 0.01/0.98/0.01 | XfBAW, XfBA_W | cut-out |
| `s114_22_BM` | 512x512 | 10 | wall (geometry:side) | 1 x 2 | 110 (88-129) / 176 (135-228) | 0.12/0.76/0.12 | XfB_W | kept |
| `s114_23_BM` | 256x64 | 9 | wall (geometry:side) | 1 x 1 | 97 (63-121) / 18 (15-18) | 0.00/1.00/0.00 | XfBAW, XfBA_W | cut-out |
| `test49_BM` | 128x1024 | 11 | wall (geometry:side) | 1 x 6 | 31 (27-34) / 561 (520-765) | 0.17/0.80/0.03 | XfB_N__EW | kept |
| `test5_BM` | 256x256 | 9 | wall (geometry:side) | 2 x 2 | 224 (200-238) / 196 (174-452) | 0.21/0.68/0.11 | XfB_N__EW | kept |
| `y-s114-Wtest_BM` | 512x512 | 10 | wall (geometry:side) | 3 x 3 | 326 (277-333) / 272 (272-272) | 0.01/0.98/0.01 | XfB_N__EL_S | kept |
| `y-s114-aoiekabeA_BM` | 1024x512 | 11 | wall (geometry:side) | 6 x 3 | 563 (439-582) / 274 (274-281) | 0.00/0.99/0.01 | XfB_L | kept |
| `y-s114-basA_BM` | 512x512 | 10 | wall (geometry:side) | 4 x 3 | 356 (345-384) / 305 (266-345) | 0.04/0.84/0.12 | XfB_N__EL_S | kept |
| `y-s114-bas_BM` | 1024x1024 | 11 | wall (geometry:side) | 5 x 3 | 504 (350-505) / 278 (278-279) | 0.00/0.99/0.01 | XfB_N__EL_S, XfB_W | kept |
| `y-s114-bill11_BM` | 512x512 | 10 | wall (geometry:side) | 17 x 7 | 1732 (1412-1860) / 691 (592-742) | 0.06/0.89/0.06 | XfB_L | kept |
| `y-s114-borobiru_BM` | 1024x1024 | 11 | wall (geometry:side) | 11 x 7 | 1075 (971-1076) / 733 (733-876) | 0.02/0.96/0.02 | XfB_L | kept |
| `y-s114-danyakuhako_BM` | 512x512 | 10 | wall (geometry:side) | 1 x 1 | 68 (65-68) / 109 (97-157) | 0.20/0.62/0.18 | XfB_L | kept |
| `y-s114-itibaCa_BM` | 256x64 | 9 | wall (geometry:side) | 3 x 1 | 345 (263-394) / 29 (29-34) | 0.02/0.86/0.12 | XfB_L_S | kept |
| `y-s114-jyutakuA_BM` | 512x512 | 10 | wall (geometry:side) | 11 x 3 | 1082 (952-1310) / 300 (293-300) | 0.00/0.90/0.10 | XfB_L | kept |
| `y-s114-kabe71_BM` | 512x512 | 10 | wall (geometry:side) | 16 x 5 | 1627 (1345-1722) / 505 (505-506) | 0.00/0.93/0.07 | XfB_L | kept |
| `y-s114-kaidanAa_BM` | 256x256 | 9 | wall (geometry:side) | 2 x 2 | 217 (147-411) / 180 (162-191) | 0.13/0.87/0.00 | XfB_L | kept |
| `y-s114-kiikanban_BM` | 512x128 | 10 | wall (geometry:side) | 5 x 1 | 550 (550-550) / 106 (106-106) | 0.00/1.00/0.00 | XfB_W | kept |
| `y-s114-koyaA_BM` | 1024x1024 | 11 | wall (geometry:side) | 2 x 3 | 216 (216-226) / 325 (262-337) | 0.00/1.00/0.00 | XfB_L | kept |
| `y-s114-matikabeA_BM` | 1024x1024 | 11 | wall (geometry:side) | 4 x 2 | 373 (372-403) / 250 (250-265) | 0.04/0.96/0.00 | XfB_L, XfB_L_A | kept |
| `y-s114-maturinunoC_BM` | 256x512 | 10 | wall (geometry:side) | 1 x 1 | 137 (134-141) / 98 (77-106) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `y-s114-monB_BM` | 512x512 | 10 | wall (geometry:side) | 3 x 2 | 308 (283-316) / 179 (174-196) | 0.29/0.68/0.03 | XfB_W | kept |
| `y-s114-roujokabeAa_BM` | 512x128 | 10 | wall (geometry:side) | 5 x 1 | 514 (511-774) / 72 (66-72) | 0.00/1.00/0.00 | XfB_L_S | kept |
| `y-s114-roujokabeAb_BM` | 512x512 | 10 | wall (geometry:side) | 4 x 3 | 374 (248-489) / 281 (281-281) | 0.28/0.72/0.00 | XfB_L_S | kept |
| `y-s114-roujokabeAc_BM` | 256x64 | 9 | wall (geometry:side) | 1 x 1 | 147 (100-147) / 45 (45-45) | 0.03/0.94/0.03 | XfB_L_S | kept |
| `y-s114-roujokabeAdd_BM` | 1024x512 | 11 | wall (geometry:side) | 6 x 3 | 626 (614-676) / 292 (290-294) | 0.14/0.80/0.06 | XfB_L_S | kept |
| `y-s114-roujokabeAe_BM` | 1024x512 | 11 | wall (geometry:side) | 6 x 3 | 582 (505-614) / 288 (280-288) | 0.05/0.94/0.01 | XfB_N__EL_S | kept |
| `y-s114-roujokabeB_BM` | 512x128 | 10 | wall (geometry:side) | 5 x 1 | 501 (357-529) / 105 (105-105) | 0.00/1.00/0.00 | XfB_L | kept |
| `y-s114-sentakuti_BM` | 512x256 | 10 | wall (geometry:side) | 2 x 1 | 180 (166-196) / 68 (65-73) | 0.01/0.99/0.00 | XfB_W | kept |
| `y-s114-sirotansA_BM` | 512x128 | 10 | wall (geometry:side) | 1 x 1 | 100 (82-146) / 36 (31-48) | 0.16/0.68/0.16 | XfB_L | kept |
| `y-s114-sirotansB_BM` | 512x64 | 10 | wall (geometry:side) | 1 x 1 | 105 (71-145) / 6 (4-7) | 0.01/0.83/0.16 | XfB_L | kept |
| `y-s114-sirotans_BM` | 512x128 | 10 | wall (geometry:side) | 1 x 1 | 74 (71-96) / 56 (39-82) | 0.02/0.96/0.02 | XfB_L | kept |
| `y-s114-sotoieC_BM` | 1024x256 | 11 | wall (geometry:side) | 10 x 3 | 974 (958-977) / 343 (343-343) | 0.08/0.89/0.03 | XfB_L | kept |
| `y-s114-sotoieD_BM` | 512x512 | 10 | wall (geometry:side) | 9 x 4 | 940 (940-1206) / 361 (361-361) | 0.02/0.71/0.27 | XfB_L | kept |
| `y-s114-sotokoyaA_BM` | 1024x256 | 11 | wall (geometry:side) | 10 x 5 | 1046 (1041-1050) / 458 (458-460) | 0.00/1.00/0.00 | XfB_L | kept |
| `y-s114-sotokoyaB_BM` | 1024x512 | 11 | wall (geometry:side) | 8 x 4 | 771 (758-998) / 404 (404-404) | 0.00/1.00/0.00 | XfB_L | kept |
| `y-s114-sotokoya_BM` | 1024x512 | 11 | wall (name:koya) | 8 x 4 | 820 (783-930) / 414 (350-1125) | 0.38/0.58/0.04 | XfB_L | kept |
| `y-s114-suramubackA_BM` | 1024x512 | 11 | wall (geometry:side) | 20 x 8 | 1997 (1991-1997) / 846 (844-890) | 0.24/0.76/0.00 | XfBAL, XfB_L | cut-out |
| `y-s114-suramubackB_BM` | 512x512 | 10 | wall (geometry:side) | 9 x 4 | 922 (921-1008) / 422 (396-452) | 0.14/0.85/0.01 | XfB_L | kept |
| `y-s114-tetukabeA_BM` | 1024x1024 | 11 | wall (name:kabe) | 6 x 5 | 626 (310-764) / 534 (300-560) | 0.54/0.29/0.17 | XfB_L, XfB_N__EL_S, XfB_W | kept |
| `y-s114-tetukabeC_BM` | 1024x1024 | 11 | wall (geometry:side) | 3 x 2 | 285 (261-319) / 231 (214-246) | 0.11/0.78/0.11 | XfB_L, XfB_N__EL_S, XfB_N__EW_S, XfB_W | kept |
| `y-s114-tyaie_BM` | 512x512 | 10 | wall (geometry:side) | 5 x 3 | 486 (476-645) / 343 (342-343) | 0.04/0.96/0.00 | XfB_L | kept |
| `y-s204peradekakiB_BM` | 512x512 | 10 | wall (geometry:side) | 8 x 10 | 784 (783-1022) / 983 (983-983) | 0.00/1.00/0.00 | a_XfBAL | cut-out |
| `y_M000_145a_BM` | 512x256 | 10 | wall (geometry:side) | 2 x 1 | 207 (164-230) / 83 (80-98) | 0.00/1.00/0.00 | XfB_L, XfB_W | kept |
| `y_akadoorA_BM` | 256x512 | 10 | wall (geometry:side) | 2 x 3 | 182 (141-183) / 289 (230-290) | 0.04/0.91/0.04 | XfB_N__EW_S | kept |
| `y_ami1b_BM` | 64x64 | 7 | wall (geometry:side) | 1 x 1 | 5 (5-6) / 5 (5-5) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `y_boronuno_BM` | 512x256 | 10 | wall (geometry:side) | 2 x 1 | 234 (168-259) / 98 (87-115) | 0.00/1.00/0.00 | XfBAW | cut-out |
| `y_gomikoyaA_BM` | 1024x512 | 11 | wall (geometry:side) | 11 x 4 | 1084 (706-1097) / 374 (371-480) | 0.00/0.99/0.00 | XfB_L | kept |
| `y_hisisaku_BM` | 64x256 | 9 | wall (geometry:side) | 1 x 1 | 25 (22-26) / 77 (72-78) | 0.00/1.00/0.00 | XfB_W | kept |
| `y_ieBda_BM` | 256x256 | 9 | wall (name:ie) | 5 x 5 | 495 (370-595) / 467 (315-742) | 0.56/0.00/0.44 | XfB_N__EL, XfB_N__EW | kept |
| `y_iekabeAa_BM` | 512x512 | 10 | wall (geometry:side) | 4 x 3 | 372 (287-382) / 305 (282-360) | 0.13/0.79/0.08 | XfB_L | kept |
| `y_karekiC_BM` | 256x512 | 10 | wall (geometry:side) | 1 x 2 | 57 (41-78) / 210 (153-263) | 0.11/0.78/0.11 | XfB_W | kept |
| `y_kiF_BM` | 64x512 | 10 | wall (geometry:side) | 1 x 2 | 16 (13-21) / 186 (135-293) | 0.23/0.62/0.16 | XfB_L, XfB_L_S, XfB_W | kept |
| `y_kiG_BM` | 512x64 | 10 | wall (geometry:side) | 2 x 1 | 218 (144-329) / 12 (10-28) | 0.18/0.63/0.19 | XfB_L, XfB_W | kept |
| `y_koyakabeDa_BM` | 512x512 | 10 | wall (name:kabe) | 4 x 3 | 356 (215-570) / 288 (228-1337) | 0.24/0.52/0.24 | XfB_L, XfB_W | kept |
| `y_mitikabe_BM` | 512x512 | 10 | wall (geometry:side) | 3 x 1 | 268 (230-323) / 124 (114-156) | 0.13/0.80/0.08 | XfB_W | kept |
| `y_penpenAs_a_BM` | 128x256 | 9 | wall (geometry:side) | 1 x 1 | 47 (38-61) / 114 (93-137) | 0.00/0.99/0.00 | XfBAW | cut-out |
| `y_rekebeA_BM` | 512x512 | 10 | wall (geometry:side) | 2 x 3 | 235 (223-302) / 300 (225-300) | 0.03/0.94/0.03 | XfB_L | kept |
| `y_s101_borodora_BM` | 512x512 | 10 | wall (geometry:side) | 2 x 1 | 159 (158-160) / 128 (126-129) | 0.22/0.72/0.06 | XfB_N__EW, XfB_W | kept |
| `y_s103_boronuno_BM` | 1024x512 | 11 | wall (geometry:side) | 4 x 2 | 426 (392-467) / 224 (194-254) | 0.01/0.98/0.01 | XfB_W | kept |
| `y_s103_donoA_BM` | 256x256 | 9 | wall (geometry:side) | 1 x 1 | 98 (86-111) / 102 (93-125) | 0.19/0.61/0.20 | XfB_W | kept |
| `y_s103_doramu_mid_BM` | 512x512 | 10 | wall (geometry:side) | 1 x 1 | 115 (111-118) / 126 (123-132) | 0.25/0.72/0.03 | XfB_N__EW | kept |
| `y_sekizai_BM` | 256x128 | 9 | wall (geometry:side) | 1 x 1 | 113 (98-119) / 100 (73-106) | 0.21/0.64/0.14 | XfB_N__EW, XfB_N__EW_S | kept |
| `y_siroki_BM` | 64x256 | 9 | wall (geometry:side) | 1 x 1 | 14 (13-16) / 100 (90-108) | 0.05/0.91/0.05 | XfB_W | kept |
| `y_syokukaidanA_BM` | 512x128 | 10 | wall (geometry:side) | 3 x 1 | 346 (346-346) / 83 (83-83) | 0.00/1.00/0.00 | XfB_W | kept |
| `y_syokukan_BM` | 256x64 | 9 | wall (geometry:side) | 4 x 1 | 358 (358-434) / 87 (87-95) | 0.02/0.95/0.02 | XfB_W | kept |
| `y_syokunikaiAaa_BM` | 512x512 | 10 | wall (geometry:side) | 3 x 3 | 273 (227-296) / 255 (189-258) | 0.09/0.82/0.09 | XfB_L, XfB_W | kept |
| `y_totanCa_BM` | 512x256 | 10 | wall (geometry:side) | 2 x 2 | 161 (148-190) / 186 (158-201) | 0.00/0.90/0.10 | XfB_L, XfB_N__EW | kept |
| `ya_sakuA_BM` | 256x256 | 9 | wall (geometry:side) | 2 x 1 | 187 (170-223) / 100 (100-105) | 0.11/0.86/0.03 | XfB_L | kept |

## 3. The objects Public Assembly places

The stage places objects from two layout families, both XFS `15302ef4` trees of `mSetInfos` rows (decoded with
`re5_stage_enemies.read_xfs`):

- `stage\s400\scr\scr00\s400_IDo00_Ins`: 63 rows of class `uIm` (instanced model) whose `mName` is
  `omNNNN_IDo00_UNNN` - static scenery drawn from `uOmNNNN.arc`, with position, Euler angles and a uniform scale
  (banana trees at ×1.1-1.5, the water tank at ×1.4). 244 empty rows pad the table.
- per mode `stage\s400\soft\<mode>\s400_IDF00_Ins` and `s400_IDF01_Ins`: rows of class `uOmNNNN` with
  `cSetInfoInsModel` (`mLife`, `PatternNo`) - the interactive objects: barrels, crates, the item chests, the hourglass
  time bonus - and `uOmf201` with `cSetInfoOmLadderV`, the ladders.

32 object archives, all copied and measured (`mt_arc.build(parse(x)) == x` on every one). Each holds the object's
`pawn\om\omNNNN\model\omNNNN` MOD + MRL, its `om_<thing>A01_NN_BM/_NM/_MM` textures, an `LMT` motion, a Havok `HIT`
shape, an `OBJA` / `XFS` definition and often a `_01` broken form and effect models (`effect\mod\…`) with `tx00NN_BM`
particle sheets. The reading of each is from its texture names (Japanese romaji). Sizes are the model bounds in cm.

| archive | bytes | SHA-256 | models (bounds, cm) | textures | what | placed in s400 |
|---|---|---|---|---|---|---|
| `uOm002b.arc` | 1,168,759 | `c817c952…` | om002B 85x11x375 | om_hashigoshortA01 | short ladder (hashigo) | 1 static |
| `uOm0100.arc` | 2,896,721 | `3d3b8597…` | om0100 14x27x14 | sunadokei | **hourglass time bonus** (sunadokei); `mLife` 60 or 30 is the seconds it gives | 8 per mode (9 Reunion, 5 Versus slayers) |
| `uOm0805.arc` | 2,418,617 | `409a5242…` | om0805 194x246x190 | om_parasol01 | parasol | 2 static |
| `uOm0811.arc` | 400,743 | `2f1e8fa8…` | om0811 206x227x221 | om_satoukibi01 | sugar cane (satoukibi) | 2 static |
| `uOm0816.arc` | 392,857 | `ac13ae1f…` | om0816 354x426x366 | om_bananatreeA01 | banana tree | 7 static, scaled 1.1-1.5 |
| `uOm0818.arc` | 1,114,196 | `933387ac…` | om0818 481x237x73 | om_sentaku01 | washing line (sentaku) | 1 static |
| `uOm082b.arc` | 484,235 | `c1f7ec16…` | om082B 32x68x55 | om_polytankA01 | jerry can (poly tank) | 2 static |
| `uOm083f.arc` | 1,885,217 | `97a4f96b…` | om083f 89x60x94 | om_grapefruitA01 | grapefruit crate (29 bones: the fruit scatters) | 2 static |
| `uOm0840.arc` | 600,763 | `cb9bf0cf…` | om0840 80x34x79 | om_tomatoA01 | tomato crate (23 bones) | 2 static |
| `uOm0847.arc` | 1,327,200 | `379ccd69…` | om0847 343x255x256 | om_yataiA01 | market stall A (yatai) | 1 static |
| `uOm0848.arc` | 997,921 | `61160c1c…` | om0848 332x258x213 | om_yataiB01 | market stall B | 2 static |
| `uOm0849.arc` | 376,324 | `7b2918f3…` | om0849 90x55x70 | om_danbollA01 | **cardboard box** (danbooru) - already a 24-vertex, 12-triangle box | 5 static |
| `uOm084a.arc` | 473,185 | `771ee8fe…` | om084A 65x57x65 | om_kagoA01 | basket (kago) | 2 static |
| `uOm084b.arc` | 1,394,833 | `8789e4df…` | om084B 20x23x28 | om_gaikotuA01 | skull (gaikotu) | 2 static |
| `uOm084c.arc` | 3,485,064 | `c6e8258b…` | om084C 353x320x212 | om_yataiC01, s100_t_04_oke | market stall C with tubs (oke) | 3 static |
| `uOm0857.arc` | 1,495,499 | `76dc3700…` | om0857 200x100x150; om0857_01 (23 bones) | om_deskB01 | **desk / table** (deskB); `_01` is the broken form | 2 static |
| `uOm0859.arc` | 2,113,034 | `88bd2280…` | om0859 335x297x44; om0859_01 (35 bones) | om_kabeA01 | wall panel (kabe), breakable | 4 static |
| `uOm0867.arc` | 304,421 | `c5e00a7c…` | om0867 264x290x264 | om_parasolB01 | parasol B | 2 static |
| `uOm0886.arc` | 6,203,461 | `3fa9b592…` | om0886 81x129x81 | om_reddrumA01 + 8 `tx*` sheets | **red oil drum** (explosive; the sheets are its explosion) | 4 per mode, `IDF00` |
| `uOm0889.arc` | 1,838,562 | `281185ea…` | om0889 66x63x96; om0889_01 (9 bones) | om_kibakoC01 | **wooden crate** (kibako); `_01` is its debris | 2 per mode, `IDF01`, at (1254, 159, −2611) and (1933, 166, −718) |
| `uOm088a.arc` | 936,762 | `2b6e61a7…` | om088A 126x82x79 | om_takarabakoA01 | **item chest** (takarabako) | 4 per mode, `IDF01` |
| `uOm0890.arc` | 3,488,093 | `123e1804…` | om0890 72x121x72; om0890_01 (9 bones) | om_taruA01 | **wooden barrel** (taru), breakable | 9 per mode, `IDF01` |
| `uOm0894.arc` | 2,984,201 | `a60be376…` | om0894 85x61x59 | om_tvA01 | television (glass break effect) | 1 static |
| `uOm0933.arc` | 4,825,842 | `63f1937f…` | om0933 106x128x79 | om_chikudenA01 | battery / accumulator (chikuden) | 2 static |
| `uOm0934.arc` | 4,094,205 | `4fa42172…` | om0934 137x109x87 | om_oilA01 | oil tank | 2 static |
| `uOm094b.arc` | 504,721 | `d5ef1d73…` | om094B 102x132x68 | om_hikidashiA01 | chest of drawers (hikidashi) | 3 static |
| `uOm094e.arc` | 265,248 | `55c6e6fa…` | om094E 1593x160x637 | om_nunoD01 | cloth awning (nuno), alpha-tested | 1 static |
| `uOm094f.arc` | 284,459 | `10559f00…` | om094F 1662x480x2852 | om_nunoD01 | large cloth awning | 1 static |
| `uOm100c.arc` | 1,499,473 | `ec480c78…` | om100C 153x262x7 | om_door100C | door | 3 static |
| `uOm1103.arc` | 2,383,492 | `77cd4b17…` | om1103 130x140x10 | om_window1103 | window with breaking glass | 4 static |
| `uOm1315.arc` | 4,510,813 | `cb3dbd95…` | om1315 515x161x203 | om_carA01 | car (`uOm1315_Break.arc` beside it) | 4 static |
| `uOmf201.arc` | 212,625 | `03f57e80…` | none (6 LMT + 1 XFS) | - | the ladder behaviour (`cSetInfoOmLadderV`); no model | 5 per mode, `IDF00` |

Not in these archives: the stage's own furniture that is scenery, not an object - `tans` (a dresser, `y-s114-sirotans*`
and the ammo box `y-s114-danyakuhako`), `misetukue*` (shop tables), `nidai*` (stands), `yagura` (the tower), `bas`
(the bus), `sakuA-E` (fences), `koyaA`, `L_koyaB` (huts), the houses `L_ie*` / `V_ie*`, `jimen` / `sotojimen` (the
ground). Those are scene pieces in `scr01` and are covered by the greybox textures above.

### Object model layout

Every drawn object has pairs of mesh records: a **depth proxy** (format `0x133098B0`, stride 12: short position +
bone id, mesh type `0x1020`, render mode 132) and the **drawn part** (`0x18B0FAA8`, stride 20: short position, bone id
at +6, normal +8, tangent +12, UV +16 - the layout `mt_model` already confirms; mesh type `0xFFFF`, mode 4), per LOD
(masks 1 and 254; the desk has one pair with mask 255). Positions are quantised through the root bone's
`inverse_bind × local` matrix (`om0889`: scale 111.08, origin at the bounds minimum). The crate's MRL binds per
material `_NM`, `_BM`, two `NullWhite`, the light-map slot on `NullWhite`, `DefaultCube_CM` and `_MM`.

## 4. The prop path: the crate as a grid box

`build_prop_box(uOm0889.arc, CRATE)` rewrites `pawn\om\om0889\model\om0889` **in place**: for every part of LOD 0 and
LOD 1 (both the proxy and the drawn part), the first 24 vertex slots of the native allocation receive the eight
corners × three faces of an axis-aligned box over the model's native bounds (66 × 63 × 96 cm), the remaining slots
repeat the last vertex, and the index allocation receives six quad strips with restart words (29 words) followed by
`0xFFFF` padding. Header, part table, bounds, skeleton, materials and every other byte are unchanged
(`parse_mod(result).meshes() == parse_mod(native).meshes()`), which follows the measured lesson in
`mt_model.replace_part`: a moved vertex buffer hung the game even when all bytes agreed, so nothing moves. The drawn
part's normals and tangents are the face's; its UVs put one tile per metre, centred on each face, so the grid is
world-true (the crate shows two thirds of a tile) and the label sits mid-face. Both albedos
(`om_kibakoC01_01_BM` 512², `om_kibakoC01_02_BM` 256²) become the orange **prop** grid labelled `CRATE` with the
native alpha; the debris model `om0889_01` is untouched and samples the same albedo, so shooting the box gives
grid-textured native splinters.

The writer checks its own output: the decoded strips give exactly 12 triangles per part, every face is wound outward,
and every decoded position is within 0.6 cm of the intended corner after quantisation. `render_model` draws the
native and the written archive with the albedos each material binds (`native.png`, `candidate.png`); the native
picture is the measured decode of the object formats, not an assumption.

A **library static model** (the other half of the operator's wish) is the same path with other vertices: fit the model
into the native bounds, pack it through `pack_vertices` into the allocation, keep the proxy as the box or as the model.
The allocation is the limit - 864 vertices and 1,086 index words on the crate's drawn LOD 0, 36 / 45 on LOD 1 - so a
library model would need decimation to the far LOD, or the grown-table path the enemy writer uses (which moves buffers
and has only been proven on skinned character models). Not built here.

## Overlays

Both under `C:\_tools\gBox\.scratch-merc-recovery\assets\`, each with `romfs\nativeNXx64\ImgNX\Archive\<archive>`,
`receipt.json` (every changed entry with its payload SHA-256, the measurement, what must be seen, failure signs) and
PNGs. Hashes recomputed from the files; `verify` re-run from a fresh process on the stage overlay.

| overlay | archive | SHA-256 | bytes | changes |
|---|---|---|---|---|
| `stage-greybox-s400-v1` | `s400.arc` | `f26d283605658a10bead2ec0ff03d6da4cdfe38a60b0d72bdfaa99172b4c4bb2` | 30,759,743 (from 75,672,496: grids compress far better than photographs; every uncompressed size and tag is unchanged) | 159 albedos redrawn (25 floor, 101 wall, 31 other, 2 sky); 431 entries byte-identical |
| `prop-box-crate-v1` | `uOm0889.arc` | `4812b7541e2dc46e56ef68a8865f169f9ba9b43c58a4714d4fc26fb2d61aaf2c` | 1,469,494 | `om0889` boxed in place (MOD payload `5a96568e…`; source archive `281185ea…`, 1,838,562 bytes), 2 albedos redrawn (`270c8cc1…`, `d43858fb…`); 37 entries byte-identical |

Pictures: `textures.png` (every written albedo, mip 0), `stage-view.png` (the arena from above, orthographic, written
albedos on the native LOD-0 geometry, flat shade - no light maps, no alpha test, so the trees are dark fans) and
`stage-close.png` (a 40 m window around the centre); `native.png` / `candidate.png` for the crate.

## First boot: risks and order

Cheapest information first:

1. **`prop-box-crate-v1`** alone (one 1.4 MB file). It tests the in-place MOD edit on the simplest object. Two crates
   stand in every mode at (1254, 159, −2611) and (1933, 166, −718). An orange box of the crate's size, breakable, with
   grid splinters, is the pass. Invisible crate → the index words or the winding; native crate → the albedo entry;
   hang at stage load → the in-place edit itself (bisect: albedos only, then LOD 1 only).
2. **`stage-greybox-s400-v1`** alone. 159 TEX rewrites through the same `replace_image` that wrote the live Sonic and
   Mario atlases, but on 1024² and 2048×1024 surfaces with 11 mips and on alpha-tested surfaces for the first time.
   Black screen or hang → bisect by variant (`--override name=…` builds a variant subset; or rebuild with the sky
   left native first, since 2048×1024 is the largest surface ever rewritten). Solid slabs where fences and wires were →
   alpha was lost. One surface still a photograph → its albedo is bound from outside `scr01` (effects, `scr00`).
3. Both together. They are separate files and compose by being in one overlay folder.

What a live frame must show for the greybox to be right: the whole arena in blue and grey grid tiles under the native
lighting (light maps are native, so shadows and sun stay), floors blue with `1024`/`512` and a metre tag, walls grey
with their metre spans, roofs and clutter checkered, fences and wires still see-through, the sky a flat pale tone,
enemies and players untouched, score and kills advancing. A boot is not acceptance; a title screen is not gameplay.

Known cosmetic limits by design: labels and grids mirror or rotate with the surface's UVs; thin trims (tile spans
under 1.5 m) carry one cell with the true span as label; where artists varied the UV density across a texture's
patches the grid is right on the median patch and off by up to ×2 on the others (the quartiles say where).

## Generalising to s401..s407

`build(archive, stage='s401')` is the same code: the scope is `stage\sNNN\scr\scr01\`, every rule is measured per
archive, nothing is keyed to s400's names except the Japanese words of the tie-breaker. It was **not** run on the
other seven stages: only `s400.arc` was copied (the other seven are 43-99 MB each, 460 MB in all, within the transfer
budget but not needed for the method). Before running it there, the fvf survey should be repeated on each (a format
outside the six measured ones is skipped, not guessed, and the survey says how many meshes that is) and the `_BM`
format checked (anything not BC7 is left native and listed).

## Reproduce

```powershell
$py = 'C:\_tools\gBox\.venv-session-audit\Scripts\python.exe'
cd C:\_tools\gBox-wt-re5-greybox\system
& $py -m gbox.re5_stage_greybox survey INPUTS\s400.arc > survey.json           # the plan, nothing written
& $py -m gbox.re5_stage_greybox build  INPUTS\s400.arc --stage s400 --out OUT\stage-greybox-s400-v1
& $py -m gbox.re5_stage_greybox build  INPUTS\s400.arc --out OUT2 --override y-s114-yane_BM=wall --no-preview
& $py -m gbox.re5_stage_greybox verify --original INPUTS\s400.arc --candidate OUT\...\s400.arc --receipt OUT\receipt.json
& $py -m gbox.re5_stage_greybox prop   INPUTS\uom\uOm0889.arc --target crate --out OUT\prop-box-crate-v1
```

The stage build takes about three minutes (159 BC7 encodes through `ispc_texcomp`, then two CPU renders of 214,000
triangles). Built twice in separate processes, `s400.arc` came out byte-identical (`f26d2836…`).

## Not done, and why

- **No boot.** Offline work only, by the brief.
- **The seven other stages**: not copied, not built (see above).
- **A library model as a prop**: the allocation limit and the unproven grown-table path on objects; the box is the
  proof of the in-place path.
- **Per-mesh UV rescale** for an exact grid everywhere: a MOD edit beyond this pass.
- **Light maps, normal and mask maps** stay native by design; a "flat" blockout without baked shadows would need the
  `_LM` (BC1) writer that does not exist yet, or a `NullWhite` rebind in the MRL (`mtf_mrl.bind_albedo` binds albedo
  slots only).
- **`scr00` and effect geometry** (`s400h_*`, `effect\mod\…`): no drawn albedo found to replace; if the live frame
  shows a photograph somewhere, that is where to look.
