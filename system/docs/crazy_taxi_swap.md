# Crazy Taxi (GameCube) character writer

`gbox/crazy_taxi_swap.py` puts a collection character into Crazy Taxi (USA), catalog game `bc02bb68790ce2e7`, as a
driver, as the pedestrians or as the fares. Request #608.

The catalog entry is the HyperSpin GameCube `.gcz` (disc GCTE51, played in Dolphin). It is not the Dreamcast
release, and its models are not Ninja: the people are rigid GX `.shp` parts in `ct/polDC0.all`, read and encoded by
`gbox/crazy_taxi.py`. The PSO/SA2 Ninja code (`ninja_swap`, `pso_player`, `pso_enemy`) does not apply here.

## Slots

`characters op=use character=<slug> game_id=bc02bb68790ce2e7 slot=<slot>`

| slot | replaces | mod |
|---|---|---|
| `player` | the driver this character was last built for in this game, else Axel | `ct_<slug>` (Axel) |
| `driver:<axel\|bd_joe\|gena\|gus>` (aliases: `joe`, `b.d. joe`, `b`, `plyrB` ...) | that driver: every part, hand pose and `sl_` LOD | `ct_<slug>` / `ct_<slug>_<driver>` |
| `drivers` | all four, so the driver-select choice does not matter | `ct_<slug>_drivers` |
| `pedestrian:<group>` / `pedestrians` | one `MP_YH_ppl??` / `Man` group, or all 19 | `ct_<slug>_ped_<group>` / `ct_<slug>_pedestrians` |
| `passenger:<group>` / `passengers` | one `MP_YH_psg??` fare group, or all 31 | `ct_<slug>_psg_<group>` / `ct_<slug>_passengers` |

`characters op=collect` on this game returns the same list under `slots` (`crazy_taxi_swap.cast_slots()`, through
`char_coverage.cast_slots`). Nothing is extracted. The drivers are bone-local parts with no decoded skeleton (#1369),
so they are not collection characters. `char_coverage.WRITERS` lists the writer, and `characters_tool` routes every
slot above to `crazy_taxi_swap.use`. `crazy_taxi.use` now forwards to it.

## What gets written

* Every part blob of the slot's bank groups gets a new blob of the same size. The bank keeps every name, order and
  size, because main.dol's shape enum addresses bank positions. The built mod is a copy of the disc image with
  `ct/polDC0.all` replaced in its own slot (`filemods.build_image`); the source image is never written.
* **Main parts, `sl_` twins and hand poses** (`_gu/_ch/_ok`) take the donor segment of the same body role
  (`crazy_taxi.CT_ROLE`, `donor_segments`). `fit_points` maps the donor's principal axes onto the part's own
  principal axes, choosing the sign set with the smallest chamfer distance. Each axis is scaled to the part's extent,
  with stretch limited to 2x of the mean scale, and the bounding-box centres are matched. The parts are bone-local
  and the game adds the header centre, so the fit is done on the centre-included cloud and stored
  centre-subtracted. Anything outside the s16 range is shrunk. The vertex count is the largest whose real encoding
  fits the blob.
* **Accessory sub-parts** (a `B/C/D/1` suffix: B.D. Joe's hat, Gena's ponytails, Axel's vest, sleeve cuffs,
  wristbands) are hidden: one zero-area triangle per material.
* **Colours:** the material records carry no colour and every part uses `white.tex`, so the donor's textures cannot
  be written. Donor triangles are dealt to the part's materials by region (`deal_materials`), so the stock colours
  land roughly where they were.
* The header, including radius, centre, scale and format words, is kept byte for byte, so the game quantises the
  new arrays as before. `Shape.frac()` only *guesses* the shift from the radius, so checks must decode a written
  part with the stock part's frac.

### The earlier fit shrank the donor

The first writer (`crazy_taxi.swap_driver`, used for the `ct_hucast` mod launched from #608) fitted with Umeyama on
farthest-point samples. That method pairs points by sample order, not by position. With HUcast on Axel it drew each
part at **13-45 % of its size**: mune 0.14, te_l 0.13, momo_l 0.15, koshi 0.45. The driver became small lumps at
the joints, which may be why no gameplay frame ever showed HUcast. Across the 60 driver parts the mean chamfer
distance relative to part extent fell from 0.50 to 0.30 with `fit_points`, and the size ratio is now 0.97-1.15.
**Rebuild `ct_hucast` (`rebuild=true`) before any live check.**

## Checked offline

Owned bank `ct/polDC0.all`, sha256 `a5171e43...`, with HUcast `pso_hucast_h0_c0.glb`:

| slot | blobs | fitted / hidden | triangles |
|---|---|---|---|
| `driver:axel` (`player`) | 54 | 42 / 12 | 1056 |
| `driver:bd_joe` | 54 | 42 / 12 | 1132 |
| `driver:gena` | 50 | | 1212 |
| `driver:gus` | 50 | | 1214 |
| `pedestrians` | 253 | | 3489 |
| `passengers` | 695 | | 16226 (measured with the old fit; about 10 min) |

With the new fit, every part's centroid lands within 0.23 of its part extent of the stock centroid. The s16-range
shrink is at most 0.88x.

Every blob re-encodes at its stock size and the bank keeps its names and order. Pedestrian parts needed the "smallest
k that keeps a triangle" search, because three clusters collapse every donor triangle. Gena with HUcast runs as a
test (`test_owned_disc_hucast_as_gena`).

Tests: `tests/test_crazy_taxi_swap.py`, run with `python -m pytest tests/test_crazy_taxi_swap.py -q -p no:cacheprovider`.
13 tests are synthetic: hand-built parts and bank, slot parsing, fit round trip, hidden blob, bank swap, `use()` with
a fake disc, registration and routing. 3 more need the owned disc: `GBOX_CT_ISO`, or `GBOX_CT_BANK` for a loose
`polDC0.all`, plus `GBOX_CHARACTERS` for HUcast. Without them those 3 skip. With the disc, all 16 passed.

Offline, without the control plane:
`python -m gbox.crazy_taxi_swap <iso|polDC0.all> <library entry dir> <slot> <out dir>` writes `polDC0.all` and
`report.json`.

## Live check (not done yet)

Use an agent-owned test session, never the operator's.

1. `characters op=use character=hucast game_id=bc02bb68790ce2e7 slot=driver:axel rebuild=true launch=false`.
   Expect `status: built`, mod `ct_hucast`, and a report of 54 blobs, 42 fitted, 12 hidden, about 1056 triangles.
   The HUcast target note for this game is replaced.
2. Launch `ct_hucast` in a new test session (`@launch` with `mod=ct_hucast`, or the same call with `launch=true`
   and no `session_id`).
3. Arcade, then driver select. Axel is the first driver. Capture the select screen: HUcast's segments should be drawn
   at full part size where Axel's head, torso, arms and legs were, in Axel's stock material colours. Axel's vest and
   sleeve cuffs should be gone and nothing should float.
4. Start a run, pick up a fare, and capture gameplay frames while steering and during the hand-gesture animation.
   Pass: the body follows Axel's animation, the hands change pose without stock hands reappearing, and there is no
   crash. Fail: tiny parts (the old mod was not rebuilt), parts at the wrong joints, or exploded parts. Fail cases
   mean a part frame or fit-axis problem; record which part.
5. Post both frames and the build job ID on #608. Repeat with `slot=driver:gena` (mod `ct_hucast_gena`, pick Gena)
   to check a driver with hidden ponytails.

## Drivers, v2: the donor's look (`gbox/crazy_taxi_look.py`)

The v1 writer kept every blob at its stock size and the driver's stock textures, so the Sonic Adventure cast
(`cast_crazy_taxi_usa_sonic_adventure_us_82d27070_fix`) drew "Sonic" as a few blocks in Axel's colours. Driver slots
(`driver:<x>`, `drivers`, and every driver slot of a cast) now go through `crazy_taxi_swap.swap_files`, which calls
`crazy_taxi_look.write_driver` and rewrites **both** `ct/polDC0.all` and `ct/texDC0.all`. Pedestrians and fares keep
v1, because their textures are shared.

What main.dol does (GCTE51 disassembly):

* **The archives can grow.** The archive loader at 0x800066e0 mallocs the file's length, reads the file and registers
  every entry by name at `align32(0x10 + count * 0x44 + 0x1f)` plus the running sum of the sizes. Shapes and
  textures are then looked up by name. Both files may change size and move past the last file on the disc
  (`romexport.gc_put_file` rewrites the FST entry). `sizes.dat` only budgets the per-level banks.
* **Textures are bound per material.** A `.shp` has `header[0x10]` texture entries of 0x2c bytes at 0x11c. The fix-up at
  0x8000b6bc looks each name up and **loops forever if one is missing**, so the validator checks every name.
  Material records (0x24 bytes, `header[0x14..0x1c]` of them in three draw passes) are
  `(list offset, size, texture index, 3 words, draw type, 1 word, RGBA material colour)`. A record whose first word is
  0x38 is the VAT state record. The colour word matters: Gena's jeans parts carry 0x617FB2FF (blue) and Axel's hair
  record 0x004901FF (green), so the writer sets it to white.
* **A .tex** is `w, h, flags, GX format, wrap s, wrap t, mip` with data at 0x60. GXInitTexObj (0x8000d790) reads
  these on first use, so a texture can be resized. The bank holds CMPR and RGBA8.
* **Vertex formats:** POS is s16 × scale / 256 + the header centre, and the header scale/radius are honoured (checked
  in-game). NRM is s16 / 16384. TEX0 is **s16 / 128** (stock UVs span 0..128). CLR0 is RGB8. Display lists use one u16
  per attribute, so POS, NRM and TEX0 are deduplicated separately and the writer emits strips.
* **Part frames** were read off an in-game probe: every part was drawn as an RGB axis gizmo over the stock mesh.
  z is the character's right in every part. koshi points down from the waist and mune points up from it (y back).
  atama has x toward the face and y up. Limbs have x along the bone and y forward. kakato has x down and y toward the
  toes.

The writer (`write_driver`):

1. Every donor triangle goes to a part: the nearest role joint above its owner, plus two adjustments. On SA1 rigs the
   shoe hangs two joints below the role "foot" (`ankle_joint` follows the toe), so the shoe goes to kakato and the
   rest of the foot role to the shin. Hand materials more than 3.25 forearms from the wrist are dropped as held props
   (Amy's hammer).
2. Each part is mapped into its frame. `g` is the driver's leg length divided by the donor's. Thighs, shins and arms
   keep their joints, stretched to the driver's bone lengths with the cross-section at g. The shoe keeps its shape.
   The head is at g, capped at 2× the stock crown height above the neck. The torso runs from the hip sockets to the
   neck, split at the driver's waist.
3. One atlas per driver goes into a texture only that driver uses (`ATLAS`: TY_plyrA_face1, TY_plyrB_fb1,
   TY_plyrC_face1, TY_plyrD_fb1), resized to 256x256 CMPR. Flat colours get 8x8 cells (exact in CMPR and on the TEX0
   grid). Textures are repeated over the UV tiles they use, with a 4-texel gutter. Every part's texture entries are
   renamed to the atlas. TY_plyrA_hada1 (also used by Gena and pplWA) and TY_plyrD_koshi1/momo1 (also used by psgAL)
   are never touched.
4. Main parts, `sl_` twins and hand poses carry the part's geometry, and accessory sub-parts draw nothing. Each blob is
   checked by `check_part` (the growable form of `check_written`): records, groups and VAT kept, lists whole and
   32-byte aligned, every attribute index in range, every texture name loadable.

**The limit is memory, not the format.** The first build wrote unwelded triangle lists, which added 723 KB. The attract
demo's malloc for `recAdvAC.bin` then returned NULL (Dolphin: "Read ... DMABuffer = 00000000", then an invalid write
at 0x800d2350). A gizmo probe that added 412 KB still ran. With deduplicated arrays and strips, the four SA1 drivers
(about 1000 triangles each, every donor triangle) add 34 KB to polDC0.all and 106 KB to texDC0.all, mostly the four
atlases.

Checked in an agent-owned Dolphin 2609a with build `cast_crazy_taxi_usa_sonic_adventure_us_82d27070_v2` (Sonic,
Knuckles, Amy and Gamma). Driver select and cab frames for all four are in
`D:\gBox\research\crazy_taxi\evidence\v2`. Tests: `tests/test_crazy_taxi_look.py` (9 synthetic; 1 needs the owned ISO
via `GBOX_CT_ISO` and a donor via `GBOX_CT_DONOR`).

## Crazy Taxi 2 (Dreamcast) inventory, #1482

Catalog `45e9455ca5487e7d`, QuickSwap2 `Crazy Taxi 2.cdi` (IP.BIN MK-51136 V1.000 2001-05-24). `gbox/crazy_taxi2.py`
and `tests/test_crazy_taxi2.py` (3 synthetic tests; 1 owned-disc test via `GBOX_CT2_CDI` that skips without it;
4/4 passed against the NAS image).

* **Not Ninja and not `.shp`.** The models are 35 `POL*.BIN` files in the Sega NAOMI-library object layout (PowerVR
  TA words, triangle strips and lists, vertex references). The module docstring has the full layout. All 35 walk to
  their exact end, giving 103625 triangles of which 95 have zero area.
* **Drivers:** `polPP1A..D` are Slash, Iceman, Cinnamon and Hot-D; `polPP2A..D` are Axel, B.D. Joe, Gena and Gus.
  Each has an `H` high-detail twin and `texPP*` textures. The mapping follows 1ST_READ.BIN's order and is not checked
  against a frame. Each file has 47 slots, 21 of them drawn (15 parts + 3 hand poses per side). Like the GameCube
  game, the parts are bone-local and no skeleton is decoded.
* Also present: cabs `polPC1A1..PC2F` (6-14 parts each), fares `polPSG0` (1200 slots, 731 drawn, 19113 triangles),
  pedestrians `polPPL0`, and city `polDC0..3`.
* **Not registered as a DEDICATED reader:** no rigged or assembled character can be collected yet. Next step: the
  47-slot node table (parent + offset) and the motion data in 1ST_READ.BIN. After that, a reader and a writer can
  reuse `crazy_taxi_swap`'s fitting (`fit_points`, `deal_materials`) on these parts.
