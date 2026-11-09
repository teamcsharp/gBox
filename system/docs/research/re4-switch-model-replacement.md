# RE4 (Switch) Mercenaries: how a player model is replaced

2026-11-09. Title `010099A00BC1E000`, RomFS extracted at `~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/` on the
game host (read only; 196 MB of it copied to a scratch folder for this work).

**Nothing here has been booted.** Every file below was built and checked offline. A file that parses and rebuilds
is not a working mod; the four overlays carry `live_verified: false` and each says what a round must show.

Three kinds of statement are kept apart:

* **measured** - run in this pass on the real files (parsers, byte comparisons, offline renders);
* **live, earlier** - seen in a running round by the session of 2026-11-07/08 (`plan-of-record-after-answers.md`,
  `re4-switch-mod-boot.md`), not repeated here;
* **inferred** - not checked by either.

Code: `gbox/re4_switch_assets.py` (file formats), `gbox/re4_switch_models.py` (the writers), 39 tests on synthetic
fixtures (`tests/test_re4_switch_assets.py`, `tests/test_re4_switch_models.py`).

## 1. The RomFS

5,275 files, 12,934,747,107 bytes, all under `bio4/` (measured from a `find` listing).

| directory | files | bytes | what it holds |
|---|---:|---:|---|
| `em/` | 162 | 326,433,344 | character packs: 82 `emXX` enemies/NPCs, 27 `plXX` player-side packs, 53 `wepXX` weapons - model, texture table, animation and effect slots in one `.udas` each |
| `imagepackhd/` | 1,813 | 6,144,462,613 | every texture's pixels, one `.pack.fen` per pack id |
| `st1`..`st5/` | 165 | 1,940,653,728 | rooms (`rNNN.udas`, some with `rNNN_NN.dat`); `st4/r400..r411` are the Mercenaries-era rooms (inferred from the numbering the bot's room ids use) |
| `evd/` | 304 | 959,239,748 | `.evd.fen` cutscene/event data (not opened) |
| `movie/` | 57 | 2,103,332,672 | `.usm` video |
| `snd/`, `bgm/` | 873 | 712,441,623 | CRI `.acb`/`.awb` sound, music tables |
| `ss/` | 1,489 | 304,747,944 | status-screen/inventory models and tables (`item/idmNNN.bin+tpl`, per-language `.tpl`, `cmn/*.dat`) |
| `option/`, `ranking/`, `achievement/`, `title/` | 75 | 413,542,536 | menu screens as `.fix` |
| `etc/` | 52 | 4,773,504 | `core.udas`, 20 enemy lists `emleon*.esl`/`omake*.esl`, loose `plXXYY.bin/.tpl` (Ashley/armour parts and hands) |
| `rel/` | 146 | 23,909,848 | GameCube-era code modules by pack name (not opened; the code runs from `main`) |
| the rest (`font`, `text`, `op`, `iww`, `info`, `gradients`, `sv`, `texture`, 7 loose files) | 139 | 1,209,547 | fonts, message tables, credits art |

By extension (count, bytes): `pack.fen` 1,813 / 6,144,462,613 - `udas` 331 / 2,261,489,152 - `usm` 57 /
2,103,332,672 - `evd.fen` 304 / 959,239,748 - `awb` 433 / 698,797,207 - `fix` 76 / 414,108,624 - `dat` 445 /
298,975,108 - `bin` 242 / 24,195,976 - `rel` 146 / 23,909,848 - `acb` 433 / 3,344,000 - `tpl` 870 / 121,120 -
`esl` 20 / 163,264 - and 15 small types (`eff`, `t3d`, `dct`, `mdt`, `fnt`, `hed`, `dds`, `uwf`, `csv`, `tga`,
`snd`, `ini`, `acf`) under 3 MB together.

### Who is in which player pack (measured: the pack's own textures decoded and looked at, plus its slot layout)

| pack | art | layout | |
|---|---|---|---|
| `pl08` | Leon, shirt and holster | playable, 133 slots, 119 bones | **Mercenaries Leon** (live, earlier: scaling this pack alone changed the player) |
| `pl06` | HUNK (gas mask, black fatigues) | playable, 133 slots, 119 bones | **HUNK** |
| `pl0a` | Krauser (camouflage, war paint, blade arm) | playable, 150 slots, 127 bones | **Krauser** |
| `pl0d` | Wesker (sunglasses, black leather) | playable, 133 slots, 112 bones | **Wesker** |
| `pl0b` | Ada, plain red dress | playable, 148 slots, 81 bones | **Ada - inferred**: `pl0c` (tactical) and `pl16` (butterfly dress) have the same layout and cannot be told apart offline |
| `pl00`, `pl09`, `pl10`, `pl19` | Leon: jacket, vest, R.P.D., mafia | playable | story costumes; `pl00`/`pl10` share `pl08`'s skeleton exactly, `pl09` within 1.1 units, `pl19` has 111 bones |
| `pl01/05/11/15/17/18/21` | Ashley and her costumes | partner and playable variants | |
| `pl02`, `pl12`, `pl14`, `pl03` | Ada (225 bones), a 64-bone woman, Luis, a 19,626-vertex Leon | NPC/cutscene | not playable layouts |
| `pl04`, `pl07` | Salazar; the two policemen + Salazar | NPC | |
| `pl0e`, `pl0f`, `pl1a` | jet-ski, boat, Leon as a rider (38 bones) | vehicles | |

The pack id is not a character id: it is only the file name. Which pack a Mercenaries character loads is decided in
`main` (per-pack code names `pl06`, `pl0a`, `pl0b`, `pl0c`, `pl0d` exist as `rel/*.rel` strings); that table was not
read out. Leon's entry is the only one confirmed in a running round.

**Ganado** (measured): `em10`..`em17` are one family - each has exactly 698 slots with the same meaning, `em10` the
full set (120 models) and `em11`..`em17` subsets (33-48 models). `em16` decodes to a male villager body (slot 476,
2,139 vertices, 34 bones), a female one (457), separate heads (461 ...) and the head parasite (629), textured from
`imagepackhd/00000016.pack.fen`. That `em16` is the pack the village round draws is live, earlier (a scale test).

### A playable pack's slots (measured on pl06, pl08, pl0a, pl0b, pl0d: same indices, same kinds)

| slot | Leon (`pl08`) | note |
|---|---|---|
| 0 | body: 6,591 vertices, 4,577 triangles, 119 bones, 25 materials, headless and handless | the character's skeleton, ids 0..118 |
| 1 | texture table, 9 images | also used by slots 6, 9, 12 (their texture count says 9; inferred binding) |
| 2, 4, 5 | head shell, face (with morph data), hair | skinned to the body's skeleton **by bone id** (they list ids 2, 3, 4, 26-33, 64-85) |
| 3 | texture table for the head pieces | |
| 8 | one-bone "far" head, in its own space | |
| 6, 9, 12 | sheath, knife, grip | |
| 14-21 | eight hand poses, two bones each (ids 9, 10) | |
| 22, 23-101 | effects; `FCV` animations and `SEQ` tables | |
| 102+ | shared items (rocket, harpoon ...) with their one-image tables | |

HUNK's pack leaves slots 4, 5, 6, 9-12, 15, 18-21 empty; Ada's and Krauser's put tables where Leon has models (5/6,
9, 12). So the layout is per character code, and a model can only go where the target's code expects that kind.

Skeleton facts (measured): ids 0-25 are the same tree in all five cast bodies (hip 0, spine 1-4, right arm 5-10,
left arm 11-16, pelvis 17, right leg 18-21, left leg 22-25; x < 0 is the right side, the model faces +z, 1 unit is
about 1 mm - Leon stands 1,837 high). From id 26 on every character differs. Leon's 65 `FCV` animations drive ids
{0-5, 7-11, 13-26, 32, 110} and nothing else; HUNK's and Wesker's packs carry animations with exactly that set
(read from the joint list at the head of each `FCV`, the only part of that format read here).

## 2. The formats (all measured; names marked * come from public UHD tooling, not from a test here)

These are the 2014 "UHD" formats with 64-bit pointers. The containers are the GameCube ones in little-endian.

**UDAS** - `ca b6 be 20` x 8, then 32-byte entries `(type, size, 0, offset)` ending in `0xFFFFFFFF`, all inside the
first 0x400 bytes. Entry 0 is the DAT (at 0x420, or 0x400 in the two single-entry packs). Entry 1 (type 4) points at
a second block with its own 0x400 header (fill in the other byte order, offsets relative to itself) and the sound
data. Between the DAT and that block sit 384-21,152 bytes of build residue (stale copies of header bytes); the
writer carries them verbatim and moves only what follows the DAT.

**DAT** - `count`, 12 zero bytes, `count` u32 offsets, `count` 4-char extensions, slots back to back, each a multiple
of 32 bytes (padding is often `0xCD`). An empty slot has no extension and the next slot's offset.

**BIN** (model) - a 0x98 header, then sections that tile the file, each starting at 0x18 modulo 32:

| at | field |
|---|---|
| 0x00 | u64 bones (= 0x98), 16 B each: `id, parent id, 2 pad, 3 f32` parent-relative bind translation |
| 0x10, 0x18 | u64 colours (RGBA8), u64 UVs (2 f32) |
| 0x20 | u64 weight sets, 8 B each: `b0 b1 b2 count w0 w1 w2 0`, percent, up to 3 bone **ids** |
| 0x28, 0x29, 0x2A | u8 weight-set count (max 255), u8 bone count, u16 material count |
| 0x30 | u64 materials (last section) |
| 0x38, 0x3C | u32 flags (kept), u32 texture count - not always the bound table's count (Wesker: 5 against 6) |
| 0x40, 0x42, 0x44 | u8 "vertex scale"* (kept), u16 weight-set count again, u32 offset of morph data (12 face models) |
| 0x48, 0x50 | u64 positions (3 f32), u64 normals (3 f32) |
| 0x58, 0x5A, 0x5C | u16 vertex count, u16 normal count, u32 version (`0x20030818` 567x, `0x20010801` 180x) |
| 0x60, 0x68 | u64 "bone pair"* table, u64 a per-bone table still in **big-endian** (kept verbatim) |
| 0x70, 0x78 | u64 weight-set index per vertex (u16), and an identical second copy |
| 0x80, 0x84 | u32 copies of the two offsets above minus 0x38 (0x38 = this header minus the PC one) |

A material is 24 header bytes (byte 12 = diffuse image index - measured, the render samples the right art through
it; 11 flag*, 13 bump*, 14 opacity*, 15 specular map*, 16-18 specular colour*, 21 specular scale*, 23 custom
specular*; 0xFF = none), then `u32 block size, u32 triangle count, u32 run count`, then `(u16 type, u16 vertices)`
runs padded to 32. There is no index buffer: runs consume the vertex arrays in order. Type 5 = triangle list, 6 =
**strip** with alternating winding, 8 = quads.

**TPL** - `0x12345678, count, 0x10, 0`; a 16-byte entry per image (u64 header offset, u64 palette = 0); 40-byte
headers `u16 height, u16 width, u32 GX format, u64 reference offset, 4 x u32 sampler, f32, 4 x u8`; then one
`(u32 pack id, u32 index)` per image. No pixels. A loose `.tpl` is not padded; a DAT slot is.

**ImagePackHD** - `<pack id:08x>.pack.fen` = `u32 raw size` + a zlib stream; the body is `pack id, count`, `count`
u64 offsets, then per texture a 16-byte wrapper `(dds size, 0xFFFFFFFF, pack id, 0)` and a complete DDS (DXT3 or
DXT5, full mip chain), every DDS starting on a multiple of 128 bytes.

### What differs from the earlier notes in this repo (and from what public UHD notes would suggest)

* **The texture join is `(pack id, index)`.** A TPL image names the archive `imagepackhd/<pack id:08x>.pack.fen`
  and the entry inside it; `plNN` uses pack id `0x010000NN`, `emNN` uses `0x000000NN`. Measured: 666 of 666 images
  in the 27 player packs and `em16` resolve to an existing entry with the same aspect ratio (the HD surface is 1, 2,
  4, 8 or 16 times the table's nominal size). `re4hd-tex.md` read the pair as "(a constant, a global id)" and
  looked for `00000001.pack.fen`; the player's textures were never missing - Leon's are `01000008.pack.fen`.
* **Normals are plain floats** at a length near 127 x 2^32 (the port kept the GameCube's byte normals unscaled);
  `re4hd-bin.md` read the high 16 bits as integers and could not match them to the geometry. Read as floats, face
  normals agree with them at a mean dot of 0.96.
* **Type 6 is a strip, not a fan**: 0.96 against 0.21 on the same test.
* **Every model decodes.** Read by the header's counts, all 747 models copied here (733 in the 35 `pl`/`em10-17`
  packs, 14 loose) parse with their runs consuming the vertex array exactly. The earlier reader refused 539 of
  2,727 because it located sections by guessing. (Only 35 of the 162 character packs were copied here.)
* **"A rebuilt mesh is not drawn" is not established.** The live rounds that suggested it rebuilt enemy slots with a
  writer that did not know the weight-set, material and texture counts in the header, and never showed which slot
  was the visible body. `native-rewrite-v1` below is the clean test.
* Unlike PC, the header is 0x98 and every section pointer is 64-bit; the big-endian per-bone table was left
  unconverted by the port.

Not decoded: `FCV`/`SEQ` beyond the joint list (frame count u16, node count u8, type u8, 2 bytes per node, then one
bone id per node), the morph data, `EFF`, the paletted TPL variant (one table in `etc/core.udas`), the flags at
0x38, the bone-pair and per-bone tables, `evd.fen`, sound.

### Round trip (parse -> rebuild == original bytes), measured on the real files

| files | result |
|---|---|
| 36 `.udas`: 27 `plXX`, `em10`-`em17`, `etc/core.udas` (73,096,800 B) | 36 identical, with all 734 model BIN and 457 TPL slots re-encoded through their readers (one non-model "BIN" and one paletted TPL in `core.udas` carried as they are) |
| 14 loose `etc/*.bin`, 5 loose `etc/*.tpl` | 19 identical |
| 28 `.pack.fen`: `01000000`-`01000021` and `00000016` (122,904,641 B, 756 DDS) | 28 identical, including the zlib stream (level 6 reproduces it) |

The files the candidates rewrite are `em/pl08.udas` and `imagepackhd/01000008.pack.fen`; both are in that list.

## 3. The candidates

All in `C:\_tools\gBox\.scratch-merc-recovery\assets\re4\<name>\` on JAYBUILTFINALE, each `romfs\bio4\...` plus
`receipt.json`. Stock `pl08.udas` is sha256 `d3390e4e...f3caa` (1,512,608 B). Each replaces that one file (the
last one also the archive); in every pack the sound block and the residue are byte-identical to stock and the
output re-parses and rebuilds to itself.

| name | `pl08.udas` sha256 | what is in it |
|---|---|---|
| `native-swap-v1` | `187b9128...9912` (1,644,960 B) | HUNK's body (`pl06` slot 0, 403,360 B, bytes untouched) in Leon's slot 0; slot 1 = HUNK's 4 images + 5 copies of the first, all naming `01000006.pack.fen`. 131 other slots identical |
| `native-swap-v1-control` | `65b6ff3d...6e8b` (1,464,960 B) | the same with R.P.D. Leon's body (`pl10`), whose skeleton is byte-for-byte `pl08`'s; table names `01000010.pack.fen` |
| `native-rewrite-v1` | `2fe0fe6c...e951` (1,708,256 B) | the control's body decoded and written again by the composer: 11,544 list vertices for the same 3,848 triangles, same weights and materials |
| `sonic-on-leon-v1` | `611db614...a278` (1,408,992 B) + `01000008.pack.fen` `aa22281d...1003` (3,398,077 B) | see section 4 |

What a Mercenaries round as Leon must show, and what failure looks like:

* **`native-swap-v1-control`** - Leon in the dark R.P.D. uniform (long sleeves, lettered vest), his own head and
  hands in place. This is the test of the three things a donor needs: `pl08.udas` is the drawn pack, a container
  with a resized slot loads, and a table may name another pack's archive. *Leon unchanged*: overlay not applied or
  wrong pack. *R.P.D. shape, scrambled dark texture*: the pack id in the table is ignored (textures then have to be
  written into `01000008` itself). *Hang at stage load*: the rebuilt container is refused.
* **`native-swap-v1`** - HUNK's body (black fatigues, vest, knee pads) moving with Leon's animations. Leon's head
  and hands are still drawn; the pieces of the head that hang on ids 26+ (jaw 27/28, eyes 32/33, hair 65-83) will
  probably sit in the wrong place, because HUNK's skeleton is a different tree from id 26 (ids 0-25 match within
  13 units). The knife and sheath take HUNK's texture sheet. A hang here but not in the control means the foreign
  skeleton, not the path.
* **`native-rewrite-v1`** - exactly the control's picture. Any difference is a fault in the writer.
* **`sonic-on-leon-v1`** - a tall thin Sonic, see below. Only worth a boot after the control and the rewrite draw.

Suggested order: control, rewrite, v1, Sonic - four boots, each answering one question. Earlier live work found the
title needs the Mercenaries save and one emulator slot; none of that was touched.

## 4. A donor body (Sonic) on Leon's skeleton

`sonic-on-leon-v1` was built by `re4_switch_models.author_body` from `sonic.glb` (sha256 `5dd7cc07...74df4`, 62
joints, 1,369 triangles, 4 textures).

What the format demands, and what the build did:

| | requirement (measured) | this build |
|---|---|---|
| skeleton | the body BIN is the character's skeleton; parts and animations address it by id | bone table kept byte-identical; **no bind joint moved** (the RE5/RE6 lesson, `re6-switch-handover.md` 2.1) |
| pose | bind pose is a T-pose, arms along x at y = 1,508 | each donor segment rotated onto the native one, stretched to the native length, scaled across by 150 (torso), 80 (head), 100 (limbs, hands, feet); head and feet keep the donor's orientation; soles on y = 0 |
| weights | 3 bone ids per vertex, percent, at most 255 distinct sets | 15 role bones (0, 2, 4, 7, 8, 10, 13, 14, 16, 18, 19, 20, 22, 23, 24), all of them animated; 68 sets at 1 % steps |
| vertices | no index buffer, u16 count | 4,107 list vertices for 1,369 triangles, one material |
| texture | DDS in the pack's archive, named by a table image | the donor's 4 textures as one 1024x1024 DXT5 atlas, **appended** as entry 30 of `01000008.pack.fen`; table image 5 (the shirt, used by the body only) now names it |
| the native head and hands | separate models on the same skeleton | slots 2, 4, 5, 8, 14-21 shrunk to a tenth in place (a same-topology position edit - the one kind of change the earlier rounds saw drawn); the donor's own head and gloves are in the body mesh |

Offline checks that passed: the pack re-parses and rebuilds to itself; 119 slots identical to stock; skeleton and
header constants identical; no degenerate triangle; UVs inside the atlas; the table image resolves to a DDS that
decodes; the grown archive keeps its 30 stock entries and its alignment; skinning the built mesh offline with a
test pose (arms down, elbows and a knee bent, head turned) bends it at the native joints, and the same test on the
stock body gives a plausible Leon, which checks the reading of the weight sets. The build is reproducible (two runs,
same bytes).

What a round must show: a blue Sonic about 2 m tall with Leon's limb lengths (so long thin arms and legs), tan arms
and muzzle, white gloves, red shoes on the ground, no Leon head or hands, the knife and sheath floating where Leon
wears them. *Stock Leon*: overlay not applied. *Body invisible or black, small head specks visible*: the composed
mesh or the appended entry is refused. *Sonic's shape in Leon's shirt texture*: entry 30 is not read. *Hang*: see
`native-rewrite-v1`.

Known weaknesses of v1, by design rather than accident: the proportions are Leon's, not Sonic's; hands are whole
gloves on the wrist bone (no fingers - Leon's hand poses are separate models that are now hidden); nothing rides
the head-side ids 26+ (no facial animation); weapons will sit in Leon's grip, which is not the glove's; normals come
from the donor and the atlas has no bump or specular image.

**Carries over from the RE5/RE6 work:** the donor loaders (`mtf_materials.source_mesh` for surface + atlas,
`characters._load`, `characters.tree_roles` for a rig with no joint names), the role vocabulary, and the fit rule of
`mtf_retarget.transfer` (here with a cross-section per role family). **New for RE4:** the whole file layer (no MTF
archives: UDAS/DAT, BIN without an index buffer, weight-set table, TPL -> archive join), percent weights with a
one-byte set count, and hiding the native head and hands, which are separate skinned models.

## 5. Open questions

1. Is any of this drawn? (All four overlays.)
2. Does the game honour a table's pack id across packs, or derive the archive from the pack being loaded?
3. Which pack is Mercenaries Ada (`pl0b`, `pl0c` or `pl16`), and are HUNK/Krauser/Wesker really `pl06`/`pl0a`/`pl0d`
   in that mode? The art says who they are, not which mode loads them.
4. Does the engine take the skeleton from slot 0, and what do Leon's head pieces do on a foreign one?
5. Does a table need its nominal size to be the HD size over 4, and does the texture count at 0x3C matter?
   (Natives disagree with themselves on the second.)
6. Can a slot be emptied under Leon's code the way HUNK's pack has it (a cleaner way to remove the head)?
7. How are weapons and hand poses attached - what would give a donor a working grip?

## 6. Next three steps

1. **Boot `native-swap-v1-control`, then `native-rewrite-v1`** (one Mercenaries round each as Leon, a frame with the
   round timer on screen). These two answer questions 1, 2 and the "rebuilt mesh" doubt, and nothing else is worth
   doing before them.
2. **Read the character table out of `main`** (the `plXX` loader: the per-pack names at 0x6c2000-0x6c3300 and
   0x6c9254 are the way in) so Ada/HUNK/Krauser/Wesker are facts, and the same writer can be pointed at them.
3. **Give the donor its own proportions and a grip**: either a second fit that keeps Sonic's limb lengths with the
   joints still on Leon's (a hip-height Sonic needs the camera and collision looked at), or bone-pair/hand-pose
   work so a glove holds the pistol - chosen after seeing step 1's frames, not before.

## Reproduce

```
cd system
python -m gbox.re4_switch_assets verify <copied .udas/.bin/.tpl/.pack.fen files>
python -m gbox.re4_switch_assets slots em/pl08.udas
python -m gbox.re4_switch_models native-swap --em <folder with plXX.udas> --target pl08 --donor pl10 --out <overlay>
python -m gbox.re4_switch_models native-swap --em <folder> --target pl08 --donor pl10 --rewrite --out <overlay>
python -m gbox.re4_switch_models author --em <folder> --imagepack <folder with .pack.fen> --target pl08 \
        --source sonic.glb --out <overlay>
```

The scratch scripts that drew the offline pictures and ran the checks (`view2.py`, `pose_check.py`,
`check_candidates.py`, `join_check.py`) are in `C:\_tools\gBox\.scratch-merc-recovery\re4\work\`, outside git.
`author` (the .glb path through `load_donor`) has no unit test - its fit and writer do, on a synthetic donor.
