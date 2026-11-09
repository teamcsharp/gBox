# RE5 Switch: an enemy cast — any library donor on the Majini, several characters in one round

2026-11-09. Follow-up to [re5-mario-enemy-writer.md](re5-mario-enemy-writer.md). The goal is the operator's: the
Mercenaries horde drawn as characters from the model library, several different ones in a round, different ones
across rounds.

**What has and has not been seen in the game.** One archive of this family has been booted, by the coordinating
session, not by this work: the first candidate (SM64 DS Mario on `em1000`, every option group carrying the donor)
loaded, played Public Assembly and showed Marios in a gameplay frame. Everything in this note was built and checked
offline after that. No overlay listed here has been booted. `uEm11.arc` has never been loaded with an edit, no donor
other than Mario has been drawn, the new fit has not been drawn, and the mix rests on an inferred reading of a table.
A structurally valid archive is not a visible character.

| | |
|---|---|
| Writer | `system/gbox/re5_enemy_writer.py` (`build_donor`, `build_mix`, `load_donor`, `check_rig`, `Fit`, `parse_montage`) |
| Overlays, pools, survey | `system/gbox/re5_enemy_cast.py` (`build_cast`, `plan`, `survey`, CLI) |
| Stage census | `system/gbox/re5_stage_enemies.py` (`read_xfs`, `spawns`, `census`, CLI) |
| Shared code touched | `mtf_retarget.transfer` and `re5_mesh_import.build_archive` gained `role_scales`, `role_offsets`, `orphan_role` (all optional, `native_segments` only); `mtf_motion._rig` settles a duplicate animation id through the bone map. The group-0 guard of `re5_mesh_import` is unchanged |
| Tests | `test_re5_enemy_donors.py`, `test_re5_enemy_mix.py`, `test_re5_enemy_cast.py`, `test_re5_stage_enemies.py`, `test_mtf_retarget_roles.py` (35 tests on synthetic fixtures, plus one opt-in test on the owned `uEm11.arc`) |
| Outputs (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\assets\<name>\` — see [Overlays](#overlays) |

## 1. Which stage spawns which enemy class

Read offline from the eight Mercenaries stage archives. Each `sNNN.arc` holds, per game mode, the enemy layouts
`stage\sNNN\soft\<mode>\sNNN_emXX` (type `0x15302EF4`, an XFS object tree). A placed enemy is a `mSetInfos` row with
`mUnitClass` (the class and the archive stem), `mModelType` and `mMontageNo`. All 372 enemy layouts of `s400`–`s407`
(and the 166 item and object layouts beside them) were decoded to their last byte; only the `soft` byte ranges of the
archives were copied (13 MB in total).

Numbers are placed spawns in the layouts of that mode — what the mode *can* spawn, not what one round does. Bold
classes are built by this writer.

| stage | The Mercenaries (`merce`) | No Mercy (`merceex`) | Reunion (`mercedc`) adds |
|---|---|---|---|
| `s400` Public Assembly | **uEm10** 121, **uEm11** 24, uEm20 3, uEm21 1, uEm62 1 | **uEm10** 320, **uEm11** 72, uEm20 6, uEm21 1, uEm62 1 | uEm0b 8, uEm13 9, uEm92 1 |
| `s401` The Mines | **uEm10** 138, uEm13 7, uEm34 3, uEm62 2 | **uEm10** 369, uEm13 22, uEm34 7, uEm62 2 | uEm30 13 |
| `s402` Village | uEm12 125, uEm0b 26, uEm24 4, uEm62 1 | uEm12 325, uEm0b 66, uEm24 8, uEm62 1 | — |
| `s403` Ancient Ruins | uEm12 144, uEm24 5, uEm62 1 | uEm12 386, uEm24 13, uEm62 1 | uEm0b 5 |
| `s404` Experimental Facility | uEm14 77, uEm32 72, uEm62 1 | uEm14 227, uEm32 172, uEm62 1 | — |
| `s405` Missile Area | **uEm10** 146, uEm23 3, uEm62 1 | **uEm10** 393, uEm23 6, uEm62 1 | — |
| `s406` Ship Deck | **uEm10** 142, uEm22 7, uEm62 1 | **uEm10** 385, uEm22 14, uEm62 1 | uEm23 1 |
| `s407` Prison | **uEm10** 130, uEm13 14, uEm20 2, uEm26 3, uEm62 1 | **uEm10** 353, uEm13 28, uEm20 4, uEm26 5, uEm62 10 | — |

So a `uEm10` replacement covers most of the horde in five stages (Public Assembly, The Mines, Missile Area, Ship
Deck, Prison); `uEm11` adds the women of Public Assembly; Village and Ancient Ruins need `uEm12`; Experimental
Facility needs `uEm14` and `uEm32`. Every stage also has one or two boss classes (`uEm20`–`uEm26`, `uEm34`).

How sure each part is:

- **Class lists per stage and mode: measured.** They are the layouts' own strings. The Public Assembly row agrees with
  the live RAM census of the handover (uEm10 27–28 and uEm11 7–8 of 40, plus uEm20/uEm21/uEm62).
- **Stage names:** `s400` = Public Assembly is established (navigation mesh work). `s401`–`s407` are assigned by menu
  order; the enemy families fit (two stages share the tribal class and its boss, one stage has the only `uEm32`),
  but no file read here carries a stage title. Treat the names of `s401`–`s407` as probable.
- **Mode names:** `merce`, `merceex`, `mercedc` are the game's folder names. `merceex` = No Mercy (it has 15–20
  enemy layouts, most of 30 enemies, where `merce` has 7–8) and `mercedc` = Reunion are readings of the content, not labels.
- **Upper bound, not a round:** which layouts a round activates is decided by the mode's FSM files
  (`fsm\EmSetArea*`, `fix\BossEmSet`, `fix\StartEmSet`), which were not decoded. No layout names a class outside
  this table, so a build that replaces the listed archives replaces everything a layout can place. Whether code
  spawns anything without a layout (a Plaga out of a burst head, for instance) is unknown.
- **Human names of the classes** (executioner, dogs, lickers …) are deliberately not given: nothing read here names
  them. The live frame identifies `uEm20` in Public Assembly as the executioner.

What a RAM census would still settle: the per-round class counts in the seven stages other than Public Assembly
(walk `sEnemy +0x48` and name each vtable as the handover describes), and for the mix the per-enemy option groups.

Every `uEm10` spawn in every mode of every stage has `mModelType 0` and `mMontageNo -1`; `uEm11` has model type 0
and montage 0, 1 or -1. With the live result (only `em1000` replaced, donors drawn) model type 0 is the `xx00`
model: `em1001` and `em1101` are not what Mercenaries draws. For `uEm11` that is an inference by analogy.

### The other Majini classes, measured but not built

Copied and measured the same way (`uEm12`, `uEm13`, `uEm14`, `uEm21`; 118 MB). All four share the `em10` motion set
and have a native record in the donor's vertex format.

| class | models | what already holds | what a reviewed table still needs |
|---|---|---|---|
| `uEm13` (Mines, Prison) | `em1300`, 89 bones, 31 records, groups 1, 2, 3, 13 | role map measures and agrees with the ids; same bind pose as `em1000`; montage table parses (2 montages) | LOD masks 3 and 254 occur beside 1, 2, 252 — the writer refuses them until they are understood |
| `uEm21` (one per Public Assembly round) | `em2100`, 90 bones, 38 records, groups 4, 7, 22, 23, 101, 254, 255 | role map agrees; same bind pose; montage table parses (3 montages) | LOD mask 254; group slots to review |
| `uEm12` (Village, Ancient Ruins) | `em1200` / `_low` / `_mid`, 81 / 31 / 63 bones, 197 records, 19 groups | animation ids resolve | bones are not stored parents-first, so the bind-pose measurement refuses the skeleton; the montage table has a zero row the parser refuses; LOD mask 255 on native records |
| `uEm14` (Experimental Facility) | `em1400` / `_low` / `_mid`, 81 / 30 / 55 bones, 373 records, 41 groups | animation ids resolve; montage table parses (56 montages) | same skeleton order problem; it HAS a group 0; no montage category has exactly one group in every montage, so a mix needs per-montage reasoning |

The boss and animal classes were not copied or measured.

## 2. The second Majini class: `uEm11.arc`

SHA-256 `a33ae046d908254053b9d8bb00cc3542057efb967986143c7990e3481b7f44dc`, 24,538,107 bytes, 397 entries, every
entry a wrapped zlib stream that recompresses identically at level 6; `mt_arc.build(parse(x)) == x`.

- Models: `em1100` (MOD 89 / MRL 69), `em1101` (90 / 70), and three small `evf23xx` head models. There is no `_mid` or
  `_low` file; one model carries all LODs as records with masks 1, 2 and 252.
- `em1100`: 85 bones, 64 records, 15 materials, **10 option groups and no group 0**. The last digit is the slot again:

  | slot | groups | evidence |
  |---|---|---|
  | head | 1 | Head/Eye/Teeth materials, y 138–181 |
  | arm and torso skin | 2 | `zof_body`, x to ±89 |
  | leg skin | 3 | y 0–117 |
  | shirt | 5, 15 | `syatu`, y 115–157 |
  | skirt | 6, 16 | `skart`, y 13–117 |
  | head cloth | 8, 18 | `head_nuno`, y 163–184 |
  | sandals | 9 | y −2…10 |

- **Skeleton shape.** Bone 0 is an origin bone whose only child is the body root at hip height; both headers carry
  animation id 0 and the 256-byte bone map names the body root. A childless helper is stacked on each wrist beside
  the hand. `measure_roles` now reads through a ground bone and tells the hand from the helper; on `em1101` it also
  tells the leg from the skirt chain under each thigh by which one reaches the floor. All eight Majini models
  (six in `uEm10`, two in `uEm11`) measure from the bind pose alone and agree with the animation ids.

  | role | `em1100` bone | bind position (cm) |
  |---|---|---|
  | hip / chest / head | 2 / 16 / 78 | 0, 114.0 / 131.2 / 164.7 |
  | l_upper / l_fore / l_hand | 18 / 22 / 25 | 12.96 / 41.67 / 69.88, 150.67, −1.90 |
  | r_upper / r_fore / r_hand | 48 / 52 / 56 | mirrored |
  | l_thigh / l_shin / l_foot | 10 / 12 / 13 | 9.2, 101.0 / 57.47 / 13.5 |
  | r_thigh / r_shin / r_foot | 5 / 6 / 7 | mirrored |

- **Atlas.** The donor atlas goes to the head cloth of group 8 (`gof01_08_BM`, entry 45, 512×256 BC7; normal 47,
  mask 46): the only 512×256 albedo that exactly one `em1100` material samples. The sandal albedo is 128×128, which
  halves or quarters even SM64 DS textures. The head-cloth descriptor has the same blend, depth and raster state and
  the same command list as the `em1000` sandal material that has drawn a donor; one flag field differs (0x216 against
  0x21A) and its constants are its own. The proven sandal material had never drawn the donor's vertex format either.
- **Motion.** `uEm11.arc` carries the `em10` motion set (`em10_g00`…`g09`); the posed preview uses entry 100 clip 105,
  one of the few clips that need no engine IK.
- **`em1101` is measured and not built**, on purpose: none of its drawn records is in the donor vertex format (they use
  `0x2270D877`, `0x1E5013A0`, `0x1AC0F6CB`, each 4 bytes wider than the format the donor is written in), three
  materials sample every albedo, and its legs have another bind pose. No Mercenaries layout asks for model type 1.
  The other models that sample the head-cloth texture (`em1101`) would show the atlas there if they were drawn —
  that is also the marker that the archive loaded but the game draws the other model.

## 3. How a spawn selects option groups: the montage table

The first note said nothing in the archive records the selection. That was wrong: beside each model there is an `MTG`
resource (type `0x4E2FEF36`): `uEm10.arc` entry 763 for `em1000` (1,540 bytes) and `uEm11.arc` entry 383 for `em1100`.

**Measured layout (version 2).** A 32-byte header (`MTG\0`, version, part count, montage count, two u64 offsets);
8 bytes per part: u16 option group, u16 category, u32 mask; 20 bytes per montage: 16 bytes, one value per category
index, and a float between 1.0 and 1.04.

**Inferred reading.** A montage draws, in each category, the parts whose mask holds bit `value`; a value with no part
draws nothing there. It is consistent with every row checked:

- `em1000`: 61 parts, 51 montages. Categories 1 head (8 groups), 2 arm skin (10), 3 leg skin (10), 10 shirt, 11 pants,
  13 sandals. Montage 0 is all zeros = groups 1, 2, 3, 4, 5, 7, the base outfit. The montages whose arm skin is group
  222 (arms and bare torso) have a shirt value with no part. The pants values used are 0–2 and 4–12, exactly the
  twelve pants groups of `em1000` (value 3 is group 35, which only `em1001` has). Four montages (25–28) are 0x1F in
  every category and draw nothing.
- `em1100`: 10 parts, 3 montages: (shirt 5, skirt 6, cloth 8), (shirt 15, skirt 6, no cloth), (shirt 15, skirt 16,
  cloth 18). The layouts use montage numbers 0, 1 and -1 for `uEm11`, i.e. indices into this table.
- `uEm14`'s layouts use montage numbers up to 50 and its table has 56 montages.

**Unknown.** How the game picks a montage for `mMontageNo -1` (every `uEm10` spawn): uniformly, from a stage list, or
not from this table at all. Whether code hides or swaps a category during damage or death. What the float is (a body
scale is the likely reading). None of this can be settled offline.

### The mix: several donors on one model

If the reading is right, a spawn draws exactly one group of some categories. For `em1000` the **pants** category is the
one to carry donors: every montage that draws anything draws exactly one of the twelve pants groups (47 of 51),
nothing in the layouts removes pants, and the pants have separate albedo textures — so each donor gets its own native
material and its own atlas. A head category would also give eight variants, but a head the game hides would take the
whole character with it.

`build_mix` therefore blanks every native record exactly as before and writes donor records **only in the carrier
groups**: one record per pants group instead of one per option group. A spawn then draws one donor, once (no
overlapping copies). `account_mix` refuses a table where a drawn montage would draw no carrier or two.

| carrier (albedo entry) | pants groups | atlas | montages that draw it (of 47) |
|---|---|---|---|
| `em1000_205_BM` (24) | 205 | 512×512 | 13 |
| `em1000_215_BM` (28) | 215 | 512×512 | 8 |
| `gam01_005_BM` (105) | 5, 55 | 512×512 | 7 |
| `gam01_125_BM` (160) | 125 | 512×256 | 5 |
| `em1000_225_BM` (29) | 225 | 512×512 | 4 |
| `gam01_115_BM` (156) | 115 | 512×256 | 3 |
| `gam01_035_BM` (125) | 15, 65 | 512×512 | 3 |
| `gam01_135_BM` (161) | 135 | 512×256 | 2 |
| `gam01_105_BM` (148) | 105 | 512×256 | 1 |
| `gam01_025_BM` (122) | 25 | 512×512 | 1 |

Seven of the ten textures are sampled by one material; three by the two LOD materials of the same pants (the first in
table order is used; all native records are blank, so nothing else shows the atlas). The three shared normal maps
(27, 107, 151) and mask maps (25, 106, 149) are neutralised. `em1100` has a two-carrier table on the shirts
(15 → montages 1 and 2, 5 → montage 0), so the women can be two characters.

**What a live round must show for the idea to be right:** `uEm10` enemies of one round are several different
characters at once; each is one whole character (no Majini part, no second figure inside it, nothing missing); an
enemy keeps its character from far to near. Counting them gives the montage picture: with uniform picking the shares
are the last column; another stable ratio means a stage list, which is still the idea working.

**What it shows when the idea is wrong:** every `uEm10` enemy is the same character (the game does not vary pants as
read); or some enemies have **no body** — they can be hit and cast a shadow but nothing is drawn (a spawn selected no
carrier group; groups are not chosen from this table as read) — watch for this first; or one enemy shows two
characters (two carrier groups selected); or stock Majini parts appear (the offline decoder says they cannot).

## 4. Any donor: metadata, rig check, fit

`load_donor(entry)` reads a library entry (`meta.json` beside its model) and takes the fifteen role joints from
`rig.roles`. Nothing is guessed: a rig whose metadata lacks roles is refused with the missing roles named
(`stub has an incomplete rig: its metadata names no joint for l_hand, r_foot`), as is one where two roles share a
joint. The reviewed, explicit group tables per model are unchanged in kind (`EM1000`, `EM1001`, `EM1100`, the mix
carriers); a donor needs no table.

`check_rig` then refuses a donor whose named joints cannot be the roles they claim — metadata is trusted for which
joint is which, never for whether the result is a body: shoulders and hips must be on opposite sides and agree (a rig
whose legs are labelled the other way round would be built with crossed legs — `sm64_bowser`, `bowser_hd`), the
legs must descend, every limb segment must have a length, vertices must hang on the feet (they show the ground and
the front), and a rig that faces −Z or is mirrored is refused. Where the arms point is a pose, not a fault. A joint
with no role joint above it (a root above the hips, a prop) is carried by the hips and reported in the receipt.

**Fit.** Bind joints never move, so the body below the neck is as tall as the Majini's whatever the donor. The first
candidate used one cross-section scale from ground contact and came out about 2.4 m (Mario's head is 45 % of his
height). `Fit` now sizes the parts between the joints separately, and every scale is in the receipt:

| part | `native_height` (default) | `proportional` (the first candidate) |
|---|---|---|
| limbs and feet | ground contact: soles on model y 0 | the same |
| torso (hip, chest) | donor shoulder joints land on the native ones, so arms meet the body however narrow the donor is | the limb scale |
| hands | the limb scale, never above the torso scale | the limb scale |
| head | its top ends at the native model's top; a donor without a neck spans from the native shoulder height to that top and is moved down accordingly (it still turns on the native head joint); never above the body scale | the limb scale |

`Fit(height=1.25)` or explicit numbers size a donor that is meant to be large or small; the library metadata read
here has no field that says so, so no donor is treated as large automatically. Examples of the default fit on
`em1000`: Mario limbs 9.87 / torso 7.60 / head 4.16 / hands 7.60, 185.6 cm; Sonic 6.70 / 23.48 / 5.74 / 6.70, 187.0 cm;
Shadow 6.37 / 23.48 / 6.46 / 6.37, 185.3 cm. A character on a human skeleton is that character with human proportions:
long legs, a head a third of its cartoon size. That is a consequence of the pinned skeleton, not a defect of a file.

**What the fit does not guarantee.** The parts are sized around their joints; nothing bridges them. On some donors
the chest part ends above where the hip part begins (seen in the previews of the VR Missions Snake and of Axel: a
strip at the waist with nothing drawn), or a wide torso rises around the head. The survey therefore fits every
donor on the measured `em1000` joints and leaves out of a pool any donor with a height between the ankles and the
head joint that no triangle spans (`vertical_holes`). It does not judge looks: a donor that passes can still be an
odd figure. An explicit `--assign` builds any donor the rig check accepts; the receipt records the scales and where
the torso top and the head middle end up. An attempt to enlarge the torso until hip and chest meet was withdrawn: it
misjudged donors whose trousers are carried by the thighs (the SM64 DS family) and would have changed fits that
look right.

## 5. Which library entries can be donors

Host library, metadata only (read with one read-only command): 1,447 entries with a `meta.json`, **1,023 name all
fifteen roles**, under 50 source-game titles, several of them regional duplicates (wrestling games, 007, Dead or
Alive, SoulCalibur, Metal Gear Solid, Resident Evil, Def Jam, Stranglehold, Jet Grind Radio, Sonic, Mario, Phantasy
Star Online and more).

`re5_enemy_cast.survey` gives the go/no-go for entries whose model is on this machine. 88 entries were surveyed (the
local mirror plus 33 models copied from the host, 14.5 MB): **41 usable**, in 13 source games (Sonic Adventure 1
and 2, Super Mario 64 and 64 DS, Melee, SoulCalibur, Twin Snakes, Ocarina of Time, Shenmue, GTA III, Phantasy Star
Online, Jet Grind Radio, and the Render96 model pack, which is not an extracted game donor).

| refused because | entries | what would lift it |
|---|---|---|
| metadata names fewer than fifteen roles | 18 | role metadata (not humanoid in most cases) |
| the atlas importer accepts repeat samplers only | 10 (Dead or Alive ++, FF7 field, MGS2, RE2) | baking clamp / mirror samplers in the shared importer; its own test pins the refusal, so it was left alone |
| the fitted figure has a height where nothing is drawn | 4 (`mgs_vr_snake`, `ct2_axel`, `sa1_e102`, `sm64ds_yoshi`) | a fit that bridges the parts |
| no vertex hangs on a foot (dress, hover) | 4 | another ground and facing cue |
| arms and legs labelled on different sides | 2 | corrected role metadata |
| a leg that does not descend, joints not stacked | 4 | corrected role metadata |
| the head does not rise above its joint | 2 | corrected role metadata |
| vertex colours, duplicate joint names, UV tiling beyond the atlas | 3 | importer work |

`sm64ds_yoshi` is in `enemy-mix-v1`, which was built before the hole test existed: his boots end 7 cm below his legs.

With `--archives` the survey also **trial-builds** every usable donor on `em1000` and keeps the writer's verdict,
because a fit can still fail where no survey rule looks. Of the 33 pool candidates 30 built; `sc_mitsurugi` and
`sc_nightmare` collapse a surface normal in the fit, and `sm64ds_koopa_troopa` leaves the model's position range.

Usable but coarse on a 512×256 atlas: Melee and Twin Snakes models (40–50 materials, texture scale 1/8 to 1/16); on
the 512×512 pants carriers of a mix they get twice that.

**Seam for the shared donor module.** The writer needs only a `re5_enemy_writer.Donor` (slug, name, model path,
SHA-256, the fifteen role joints, provenance). `re5_enemy_cast.find_donor` and `re5_enemy_cast.survey` are the two
functions a shared donor survey / role-profile module replaces; `re5_enemy_writer.check_rig` stays as the writer's own
last check.

## 6. Pools

`plan(seed, {class: count}, {slug: franchise})` deals donors over the classes of one overlay with no donor used twice.
It is a pure function of its arguments. Each pick draws a franchise first and then one of its donors, so a game with
fifty entries does not crowd out one with a single character, and no franchise gets more than a quarter of an overlay
while another can still serve. A pool overlay is a mix on every class (ten donors on the `uEm10` pants, two on the
`uEm11` shirts). The three pools here were dealt from the 30 donors that passed the trial build: at most 4,500
vertices, without the Render96 model pack and without the Melee models (40 to 50 materials each on one atlas);
11 source games. A deal is reproducible from the seed and this list:
`gta3_claude`, `hucast`, `jgr_char04`, `oot_link_adult`, `ryo`, `sa1_big`, `sa2_amy_rose`, `sa2_chaos_0`,
`sa2_dr_eggman`, `sa2_knuckles`, `sa2_rouge`, `sa2_shadow`, `sa2_super_shadow`, `sa2_super_sonic`, `sa2_tails`,
`sa2_tikal`, `sc_voldo`, `sm64_mario`, `sm64_yoshi`, `sm64ds_bowser`, `sm64ds_luigi`, `sm64ds_mario`,
`sm64ds_metal_wario`, `sm64ds_wario`, `sonic`, `tts_65729f`, `tts_mrl_def`, `tts_psy_def`, `tts_rev_coat_def`,
`tts_snake_def`.

Passing the survey is not a judgement of looks. In the pool previews Beat's head sits inside a tall torso, and
Wario's feet are scaled by ground contact to twice the size of his body parts; both are whole figures and both are
odd ones.

## Overlays

All under `C:\_tools\gBox\.scratch-merc-recovery\assets\<overlay>\`, each with
`romfs\nativeNXx64\ImgNX\Archive\<class>.arc`, `receipt.json`, `preview.png` (rest pose, one row per donor),
`preview-posed.png` (one native clip on the CPU) and the per-donor pictures. None has been booted; every receipt says
`live_verified: false`. Hashes below were recomputed from the files. In a mix row the number after a donor is how
many of the 47 drawn `em1000` montages (or of the 3 `em1100` montages) select its carrier.

| overlay | archive | SHA-256 | bytes | what it carries |
|---|---|---|---|---|
| `enemy-mix-v1` | `uEm10.arc` | `a8b7fdde15632c947f3a70c62b4e9bbef2fa7a5664abcbd657d76c09d9ae74e0` | 79,895,643 | mix on the pants groups: Mario (Super Mario 64 DS) (13), Sonic (8), Luigi (7), Shadow (5), Tails (4), Amy Rose (3), Yoshi (3), Rouge (2), Dr. Eggman (1), Tikal (1) |
| `enemy-cast-a-v1` | `uEm10.arc` | `7488673f031dbfa06a9c2e0c941639bca78aa4f09ef132d9a87b5251e5e413e3` | 83,663,161 | Mario (Super Mario 64 DS) on every option group of em1000, em1000_low, em1000_mid; fit native_height, 186 cm |
| `enemy-cast-a-v1` | `uEm11.arc` | `60c22ab0f6516b3e9ae0459fac6fd71b936c98d2b981f851d1ef02f5121c6443` | 24,441,709 | Luigi on every option group of em1100; fit native_height, 184 cm |
| `enemy-cast-b-v1` | `uEm10.arc` | `e43274f8803c98c7c9606ee86f5f91e4b85e5304a287ff4435d3445ccd748209` | 86,298,208 | Shadow on every option group of em1000, em1000_low, em1000_mid; fit native_height, 185 cm |
| `enemy-cast-b-v1` | `uEm11.arc` | `3497545e88700d3ebee75fd460da84b13f1b1cecc3f46bdd4c686291cb6ae926` | 24,566,219 | Amy Rose on every option group of em1100; fit native_height, 190 cm |
| `enemy-cast-c-v1` | `uEm10.arc` | `342da605cf0b6ac02b9bc0a07fe1393f446fc23949e65a7a25131d592b607e73` | 85,560,487 | Sonic on every option group of em1000, em1000_low, em1000_mid; fit native_height, 187 cm |
| `enemy-cast-c-v1` | `uEm11.arc` | `9a766daf5ba6893e06d878b5e1745d13ea130a44ade692421b5b731279c69548` | 24,372,269 | Tails on every option group of em1100; fit native_height, 184 cm |
| `enemy-pool-01` | `uEm10.arc` | `315260a4f062e3821ff10b7c509010b5df584a19e22889b9b2954a5cbf306d6f` | 80,241,907 | mix on the pants groups: Link (adult, OoT) (13), Ryo Hazuki (8), Yoshi (Super Mario 64) (7), Mario (Super Mario 64) (5), HUcast (4), Big the Cat (3), Super Shadow (3), Voldo (2), Rouge (1), Beat (JGR ereki, ID 0) (1) |
| `enemy-pool-01` | `uEm11.arc` | `5981edc7323dd2e62d4b19a2f4ea028c3f48ddc0137ef38b60f306972bf1a132` | 24,092,046 | mix on the shirt groups: Amy Rose (2), Claude (GTA III) (1) |
| `enemy-pool-02` | `uEm10.arc` | `71ad7575943878e4b4b3522f852e2aefd054c030ac2a1a30e8f736270776d3ea` | 80,214,181 | mix on the pants groups: Claude (GTA III) (13), Link (adult, OoT) (8), HUcast (7), Tikal (5), Big the Cat (4), Voldo (3), Super Shadow (3), Wario (2), Ryo Hazuki (1), Mario (Super Mario 64 DS) (1) |
| `enemy-pool-02` | `uEm11.arc` | `bfa7c13de1bf92f270d25b53869452813a522004eabc1c8633f85b6f2acdb1d8` | 24,058,101 | mix on the shirt groups: Beat (JGR ereki, ID 0) (2), Yoshi (Super Mario 64) (1) |
| `enemy-pool-03` | `uEm10.arc` | `c3dae7c764c5b01b3b5c21c979a2c9378113268a13c2bcc8f3626f5c396fd0e2` | 80,230,844 | mix on the pants groups: Solid Snake (Twin Snakes) (13), Voldo (8), Ryo Hazuki (7), Beat (JGR ereki, ID 0) (5), Mario (Super Mario 64 DS) (4), HUcast (3), Yoshi (Super Mario 64) (3), Tails (2), Big the Cat (1), Luigi (1) |
| `enemy-pool-03` | `uEm11.arc` | `65ec770ad8d093120e71686803aaef60aefff2ed5781553c03c3329dfc915d58` | 24,061,489 | mix on the shirt groups: Link (adult, OoT) (2), Metal Wario (1) |
| `mario-em10-high-model-only-v1` | `uEm10.arc` | `81d124866ae63faed12870e4f889c48efe2612ff6b0a50a40694a1977490f11d` | 82,741,256 | Mario (Super Mario 64 DS) on every option group of em1000; fit proportional, 238 cm |

Every `uEm10` archive changes 6 entries when one donor rides on every group (three MODs, the sandal albedo, normal
and mask) and 19 in a mix (three MODs, ten albedos, three normals, three masks); every `uEm11` archive changes 4
(one MOD, the head-cloth albedo, normal and mask) or 5 in a mix (one MOD, two shirt albedos, their normal and mask).
All other entries are byte-identical to the originals, the montage tables included. In every written model all
native records decode to zero triangles.

`mario-em10-high-model-only-v1` is the first candidate's recipe on `em1000` alone: its four changed entries are
byte-identical to the same entries of the candidate that was booted, and `em1000_mid` / `em1000_low` are native.


## First boot: risks and order

Suggested order, cheapest information first:

1. **`enemy-mix-v1`** (one file, `uEm10.arc`). It tests the montage reading. Load risk is the proven grown-table
   shape with fewer donor records; the new elements are ten pants materials that have never drawn a donor. A missing
   body is the failure to look for first.
2. **`enemy-cast-a-v1`** with only its `uEm10.arc` (Mario at native height): the proven shape with the new fit.
3. Add its **`uEm11.arc`**: the first edit of that archive ever loaded. A hang or black screen is new information;
   removing the one file returns to step 2. Stock women with a donor atlas on their head cloth mean the archive
   loaded and the game draws `em1101`.
4. The pools: more donors, more materials, both classes mixed. A wrong surface on one character points at its carrier
   material; a broken silhouette on one character points at that donor's rig or fit, not at the format.

If a `uEm10` build of this family ever hangs at load, `mario-em10-high-model-only-v1` replaces `em1000` alone and
leaves `_mid` / `_low` native. The other two bisect builds of the original brief (one group per slot, native records
left drawing) were not built: the coordinator withdrew them after the first candidate loaded.

For every donor: rigid donors crease at joints, shading is faceted where the donor has no smooth normals, there are
no fingers or face animation, and the visible head of a toon donor is not the native head hit zone.

Acceptance needs what the handover asks for any replacement: build and session ids, the class census from RAM,
frames in which the drawn enemies are visibly the donors while fighting, advancing score and kills, and which of
the points above were seen. A boot is not acceptance.

## Reproduce

Run from `system` with the audit interpreter; inputs are hash-checked, nothing is installed.

```powershell
$py = 'C:\_tools\gBox\.venv-session-audit\Scripts\python.exe'
# originals: a folder holding the measured uEm10.arc and uEm11.arc; libraries: folders of <slug>\meta.json + model
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --cast enemy-cast-a-v1
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --name enemy-mix-v1 `
    --assign "uEm10=sm64ds_mario+sonic+sm64ds_luigi+sa2_shadow+sa2_tails+sa2_amy_rose+sm64ds_yoshi+sa2_rouge+sa2_dr_eggman+sa2_tikal"
& $py -m gbox.re5_enemy_cast --library LIBRARY --survey > survey.json            # go/no-go, nothing built
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --survey --slugs a,b,c > survey-pool.json
                                                                                 # also trial-builds each on em1000
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --name enemy-pool-01 `
    --pool 1 --pool-from survey-pool.json
& $py -m gbox.re5_stage_enemies PATH\s400.arc PATH\s401.arc      # the census as JSON
```

`enemy-mix-v1` was built twice in separate processes and came out byte-identical. `re5_enemy_writer.build` still
reproduces the first candidate `322c58a1…` byte for byte.

## Not done, and why

- **No boot of anything here.** Offline work only.
- **`uEm12`, `uEm13`, `uEm14`, `uEm21` and every boss or animal class** have no reviewed table (see section 1).
- **`em1101` and `em1001`** are not replaced; no Mercenaries layout asks for model type 1.
- **Most of the library is not usable yet**: of the entries surveyed, the sampler rule of the shared atlas importer is
  the largest single blocker, and only models copied to this machine were surveyed (88 of 1,447).
- **No donor is fitted as "large" or "small" from metadata**: no such field was found; `Fit(height=…)` is the knob.
- **Player-and-horde alternation** (Sonic as the horde while Mario is the player) needs the player-cast work; the
  overlays here change enemy archives only and compose with any player archive by being separate files.
- **The FSM files** that choose layouts per round were not decoded; the stage table is per mode, not per round.
