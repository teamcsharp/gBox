# Super Mario 64 DS character reader

`gbox/sm64ds_chars.py` reads the cast of **Super Mario 64 DS (USA)** (catalog `917483267d246594`, the owned
`Super Mario 64 DS (USA).7z` in the HyperSpin library) straight from the cartridge and exports each character as a
rigged, textured GLB with body roles. It is registered in `characters.DEDICATED` as `sm64ds`, so
`characters op=collect game_id=917483267d246594` fills the collection with `sm64ds_*` entries. Those entries pass the
whole-cast swap's donor gate (`gbox/cast_swap.py`) and get replacement readiness like every other reader's
(`gbox/replacement_readiness.py`).

Inbox request #1652 ("extract all of the characters of Super Mario 64 DS") introduced it. The same request built a
Dead or Alive 2 disc with them; see `docs/doa2_mixed_random.md`.

## What the cartridge holds

The owned dump is `0037 - Super Mario 64 DS (U)(Trashman).nds`, 16 MiB, game code `ASME`, SHA-256
`916056a27ffb07d1bae2ce0ca6f6464c1621c737dc96657a7b9eab4d3bccfc87`. It has 1,833 files:
535 `.bin`, 492 `.bca` (animations), **450 `.bmd` (models)**, 241 `.kcl` (collision), 105 `.btp` (texture
animations), 8 `.narc` archives and the sound archive.

**Super Mario 64 DS doesn't use NSBMD or NSBTX.** It predates the NITRO-System G3D formats. Its models are `.bmd`,
the game's own container (bones, display lists, materials, textures and palettes in one file). The geometry is
still drawn with the DS geometry engine's GX command lists, the same ones an NSBMD `MDL0` carries, and its textures
use the same seven DS texel formats. Those decoders live in `gbox/formats/nitro.py` so a later NSBMD reader can use
them as they are. Only the container is specific to this game.

| Layer | Implementation |
|---|---|
| Cartridge file system | `nitro.NitroROM`: header, FAT, and FNT with the directory table. Each directory's files take consecutive ids from that directory's `first_id`. |
| Archives | `nitro.narc`: `BTAF` (FAT), `BTNF` (an FNT with the same layout), `GMIF` (file image). The player models are in `ARCHIVE/arc0.narc`. |
| Compression | `nitro.decompress`: an `LZ77` tag followed by a Nintendo LZ10 stream (the shared `lz.lz10_decompress`). LZ11 is also decoded. Untagged files are returned as they are. |
| Textures | `nitro.decode_texture`: A3I5, 4/16/256-colour palettes (with colour 0 transparent when bit 29 is set), 4x4 compressed (all four modes), A5I3, direct colour. |
| Geometry | `nitro.decode_display_list`: packed GX commands. It runs MTX_RESTORE, BEGIN/END_VTXS (triangles, quads, triangle and quad strips with DS winding), VTX_16/10/XY/XZ/YZ/DIFF, TEXCOORD, NORMAL and COLOR. It records the matrix-stack slot each vertex was emitted under. |

`SM64DSRom` puts every NARC member under its own path, so `data/player/mario_model.bmd` resolves inside
`arc0.narc`, and loose files resolve in the cartridge.

## BMD

All offsets are absolute in the decompressed file. The header is 15 u32 words:

| Offset | Field |
|---|---|
| 0x00 | scale shift: vertex coordinates are multiplied by `1 << shift`; bone translations are not |
| 0x04 / 0x08 | bone count / offset, 0x40 bytes per bone |
| 0x0C / 0x10 | display-list count / offset: 8 bytes each, the second word points at a 16-byte descriptor `{matrix count, -> u8 transform ids, GX size, -> GX data}` |
| 0x14 / 0x18 | textures: `{name, data, size, u16 w, u16 h, TEXIMAGE_PARAM}` (0x14 bytes) |
| 0x1C / 0x20 | palettes: `{name, data, size, u32}` (0x10 bytes) |
| 0x24 / 0x28 | materials (0x30 bytes): name, texture id, palette id (0xFFFFFFFF = none), texture scale s/t (20.12), rotation, translation, TEXIMAGE_PARAM (repeat and flip bits), POLYGON_ATTR, DIF_AMB, SPE_EMI |
| 0x2C | transform -> bone map, one u16 per transform id |

A **bone** is: u32 id, name pointer, s16 parent offset (relative bone index, 0 = root), u16 has-children,
s32 sibling offset, scale xyz (20.12), rotation xyz (s16, 4096 = 360 degrees), translation xyz (20.12), the number
of (material, display list) pairs and pointers to the two u8 lists, then flags. The local matrix is
`T * Rz * Ry * Rx * S`.

**Skinning:** `MTX_RESTORE(slot)` selects a matrix-stack slot. The slot maps to the display list's transform id,
and the transform id maps to a bone through the header's map. The vertices that follow are in that bone's space. The
DS has no weighted skinning, so every vertex is bound rigidly to one bone (one joint at weight 1 in the GLB).

**UVs** are in texels (12.4) times the material's texture scale. Materials that repeat with the flip bit set get
the mirrored copy baked into the texture, and the UV range is halved. Eyes and Luigi's body use this.

**4x4 textures:** the palette-index data (one u16 per block) follows the texel data, `size / 2` bytes after it.

## Assembly and orientation

- **The playable four** draw their head from a separate model (`*_head_cap.bmd`, `yoshi_head.bmd`) at the body's
  `face_1` bone, as the game does. Yoshi's head model's root *is* `face_1`, so its own transform is cancelled
  instead of stacked. Yoshi's tongue (`tongue1`, `tongue_tip`) is hidden, as it is in game.
- **Koopa Troopa** hangs its arms and head off the hip. A `chest` bone is inserted at the shoulders' midpoint (no
  geometry moves) so the body chains run hip -> chest -> arms.
- Every model is turned about +Y so its left side is at +X and it faces +Z (`Model.face_z`), the convention of the
  swap writers. All SM64DS models already face +Z.

## Roster (owned ROM, verified previews)

26 characters. All 26 are collected, verified and retargetable. Nine are replacement-ready humanoids. The other 17
are creatures; readiness rates them `limited` with the reason recorded in `CHARACTERS[...]["absent"]`.

| slug | name | source | triangles | bones | roles | readiness |
|---|---|---|---|---|---|---|
| `sm64ds_mario` | Mario | `arc0.narc`: player/mario_model.bmd + mario_head_cap.bmd | 452 | 17 | 16 | ready |
| `sm64ds_luigi` | Luigi | `arc0.narc`: player/luigi_model.bmd + luigi_head_cap.bmd | 455 | 17 | 16 | ready |
| `sm64ds_wario` | Wario | `arc0.narc`: player/wario_model.bmd + wario_head_cap.bmd | 429 | 17 | 16 | ready |
| `sm64ds_yoshi` | Yoshi | `arc0.narc`: player/yoshi_model.bmd + yoshi_head.bmd | 428 | 20 | 16 | ready |
| `sm64ds_metal_wario` | Metal Wario | player/wario_metal_model.bmd | 513 | 16 | 15 | ready |
| `sm64ds_peach` | Princess Peach | enemy/peach/peach_high.bmd | 798 | 21 | 15 | ready |
| `sm64ds_bowser` | Bowser | enemy/koopa/koopa_model.bmd | 975 | 18 | 15 | ready |
| `sm64ds_koopa_troopa` | Koopa Troopa | enemy/nokonoko/nokonoko.bmd (+ inserted chest) | 266 | 16 | 15 | ready |
| `sm64ds_ukiki` | Ukiki | enemy/monkey/monkey.bmd | 258 | 14 | 12 | ready |
| `sm64ds_toad` | Toad | enemy/kinopio/kinopio.bmd | 301 | 6 | 6 | limited |
| `sm64ds_king_bobomb` | King Bob-omb | enemy/bombking/bomb_king.bmd | 366 | 13 | 10 | limited |
| `sm64ds_mips` | MIPS | enemy/mip/mip.bmd | 209 | 16 | 10 | limited |
| `sm64ds_penguin` | Penguin | enemy/penguin/penguin.bmd | 250 | 8 | 7 | limited |
| `sm64ds_lakitu` | Lakitu | enemy/jugem/jugem.bmd | 200 | 6 | 2 | limited |
| `sm64ds_shy_guy` | Fly Guy | enemy/propeller_heyho/propeller_heyho.bmd | 208 | 7 | 6 | limited |
| `sm64ds_goomba` | Goomba | enemy/kuribo/kuribo_model.bmd | 214 | 3 | 3 | limited |
| `sm64ds_goomboss` | Goomboss | enemy/kuriking/kuriking_model.bmd | 499 | 11 | 6 | limited |
| `sm64ds_big_boo` | Big Boo | enemy/boss_teresa/boss_teresa.bmd | 204 | 3 | 3 | limited |
| `sm64ds_boo` | Boo | enemy/teresa/teresa.bmd | 75 | 2 | 1 | limited |
| `sm64ds_chief_chilly` | Chief Chilly | enemy/king_ice_donketu/king_ice_donketu_model.bmd | 253 | 5 | 3 | limited |
| `sm64ds_big_bully` | Big Bully | enemy/donketu/boss_donketu.bmd | 130 | 6 | 3 | limited |
| `sm64ds_whomp_king` | Whomp King | enemy/battan_king/battan_king.bmd | 296 | 5 | 5 | limited |
| `sm64ds_bobomb` | Bob-omb | enemy/bombhei/bombhei.bmd | 91 | 6 | 3 | limited |
| `sm64ds_hoot` | Hoot | enemy/owl/owl.bmd | 190 | 7 | 7 | limited |
| `sm64ds_piranha_plant` | Piranha Plant | enemy/pakkun/pakkun_model.bmd | 189 | 8 | 5 | limited |
| `sm64ds_dorrie` | Dorrie | enemy/dossy/dossy.bmd | 252 | 9 | 3 | limited |

Slugs are `sm64ds_<key>` because the N64 reader already owns the plain `mario` slug. `sm64ds_mario` carries
`native_player`, so the cast planner treats him as the game's lead. Not extracted: the other 400-odd `.bmd` files
(courses, items and props), Big Mario `b_mario_*` (a one-bone model) and the animations (`.bca`, `.btp`).

### Open: Koopa Troopa's stray leg vertices (#1748)

`sm64ds_koopa_troopa` is rated `ready`, but its GLB has a few vertices far from the rest of the body. The legs reach
y = -15 and +22 while the head is at about 15 and the feet at about 3, so the library model shows long spikes. Every
writer carries them over: SoulCalibur VOL1 / CER1 get black spikes past the head, the Soul Calibur II Koopa costumes
are a thin, spiky figure, and DOA2's Koopa costumes are likely affected too. Ten vertices of display list 1 cause
this. In bone space they sit 12 to 20 units from their own joint, and a shin is 2.2 long:

| vertex | bone (slot) | VTX_16 words | local position |
|---|---|---|---|
| 142 / 177 | leg_r2 / leg_l2 (0 / 8) | `0x050d5271, 0xfffa` | (20.6, 1.26, 0) |
| 147 / 182 | leg_r1 / leg_l1 (1 / 9) | `0x1b92c7c1, 0xf84d` | (-14.1, 6.9, -1.9) |
| 194, 258, 292, 294, 303, 310 | ankle_r1 / ankle_l1 | | (1.75, 12.3, 0) |

The packed command stream decodes cleanly around them (`gx_commands`), every bone scale is 1 (BMD and
`nokonoko_wait1.bca` frame 0), and no other bone or model space puts them near their strip neighbours. So the
coordinates are what the BMD stores. How the game draws Koopa's legs without the spikes is not known yet: some matrix
the game sets up for those slots and this reader does not model. Until that is found, treat this donor as broken.
On the same test (a vertex's distance from its own joint over the skeleton's joint span), only Koopa Troopa fails:
24 vertices are over 1.0, up to 1.72. The other eight humanoids stay at or below 0.92. Peach's long edges, noted in
soulcalibur_dc.md, are a different defect that this test does not catch.

## Using it

```
characters op=collect game_id=917483267d246594             # all 26
python -m gbox.sm64ds_chars ROM.nds|ROM.7z OUT --char all   # without the collection
```

On the Windows PC the 2026-10-13 collection is at `D:\gBox\cache\characters_mirror\sm64ds_*`
(GBOX_CHARACTERS for local builds). The Spark's collection gets the entries when `characters op=collect` runs there
after this branch is deployed.

## Fingerprint

`gbox.formats.disc.listing` lists `.nds` ROMs (NitroFS, raw heads, decompressed deep samples), and
`assimilate.SIGNATURES` knows the `LZ77` tag. `assimilate op=fingerprint` on the ROM reports *Nintendo DS SDK
formats (1.00)*, 13 NARC containers and 1,292 LZ77 files, and names `gbox.sm64ds_chars` as the nearest title
(`assimilate_kb` entry `sm64ds_nds`). Before this change, listing a DS ROM failed.

Tests: `tests/test_sm64ds_chars.py` (synthetic LZ77/LZ11, FNT/NARC/NitroFS, every texel format and 4x4 mode, GX
lists, a two-bone BMD -> GLB, head attach / chest insert / facing, registration; the owned ROM when present).
