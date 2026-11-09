# RE5 Switch: more characters per round — sixteen carriers on uEm10, the four other Majini classes, a series over every donor

2026-11-09. Follow-up to [re5-enemy-cast.md](re5-enemy-cast.md) and [re5-cast-pool-writer.md](re5-cast-pool-writer.md),
for the operator's "I want even more character variety mixed into the game encompassing all the extracted characters."

**Nothing in this note has been booted.** What has been seen live before and beside it: the ten-donor pants mix on
`uEm10` loaded and drew donors (enemy-mix-v1); a library donor (Ryo) was drawn as the player through
`uPl00ChrisCos2.arc` (cast pool 03); and, reported by the coordinator on 2026-11-09 22:00 UTC, the `enemy-pool-01`
build (`uEm10` `315260a4…` + `uEm11` `5981edc7…`) booted and won a No Mercy round on Public Assembly (400 routed, SS)
with Link (OoT) seen live as a Majini - so an edited `uEm11.arc` loads, and the pants-carrier reading drew at least
that donor. Every overlay below passes the offline re-read checks and has CPU pictures; none is known to load or to
look right in the game.

| | |
|---|---|
| Writer changes | `system/gbox/re5_enemy_writer.py`: `MixTable` over several categories (`EM1000_WIDE`, 16 carriers; `EM1000_SHIRTS`, 15), the reviewed sets and tables of `em1200`, `em1300`, `em1400`, `em2100`, the boss sets `em2000`, `em2200`, `em2300`, `em2400`, `em2600`, `em3400`, `em9200` (`roles_by_ids`, `shared_atlas`), `UNBUILDABLE_CLASSES`, `account_mix` as an exact-cover check, `measure_roles` reading past a detached root, `role_map(allow_ids)` with `check_role_geometry`, per-set LOD masks, donor records told apart by mesh id, a mask map the codec cannot rewrite kept native and named, samplers in range and winding reversal as the player writer has them. `mtf_mrl._is_albedo_name` (`_BM_NN`), `re5_mesh_import` round-trip tolerance of one quantisation step |
| Cast changes | `system/gbox/re5_enemy_cast.py`: `--table`, `--mix`, `--pool-size auto`, `donor_from_pool`, the survey over resolved donors; `system/gbox/re5_cast_writer.py`: the Chris label table (`LABEL_ARCHIVES`, `LABEL_EVIDENCE`) |
| New module | `system/gbox/re5_cast_series.py`: `plan_series`, `build_series`, CLI |
| Tests | `system/tests/test_re5_cast_variety.py` (12, synthetic fixtures; one opt-in test on the real class archives with `GBOX_RE5_CLASS_ARCHIVES`), updates in `test_re5_enemy_mix.py`, `test_re5_cast_writer.py` |
| Outputs (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\assets\variety-uEm10-wide-v1\`, `variety-uEm12-v1\`, `variety-uEm13-v1\`, `variety-uEm14-v1\`, `variety-uEm21-v1\`, the boss classes `variety-uEm20-v1\` … `variety-uEm92-v1\`, `pool-series\` (manifest + four builds) |
| Working files (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\variety\` (the six originals in one folder, the table re-read `table-check.json`, the enemy go/no-go over the 650 donors, build logs) |

## 1. More donors per round: the carriers are an exact cover, not a category

The first mix put one donor on each of the twelve pants groups of `em1000` (ten textures, so ten donors) because
every drawn montage draws exactly one pants group. That is one way to satisfy the only condition a mix needs: **every
drawn montage draws exactly one carrier group**, so a spawn shows one donor, once. The condition does not care which
category a carrier comes from. So the question became: which set of option groups, drawn from any categories, is an
exact cover of the 47 drawn montages and holds the most distinct albedo textures?

**Measured.** `uEm10.arc` entry 763 (`MTG`, 61 parts, 51 montages, 4 empty). Per group, the montages that draw it under
the montage reading, and the albedo of the material of its largest near record (the texture a donor's atlas would
replace). `account_mix` re-reads this on every model of the set (`em1000`, `em1000_low`, `em1000_mid`).

**Searched.** An exhaustive backtracking over the 47 drawn montages (pick the uncovered montage with the fewest usable
groups, try each) enumerates every exact cover: **431** of them. Distinct albedo textures per cover: 5 (108 covers),
6 (180), 7 (99), 8 (18), 9 (2), 10 (4), 11 (7), 12 (5), 13 (3), 14 (1), 15 (2), **16 (2)**. The pants table is one of
the four 10-texture covers. No cover holds more than 16 textures, because textures are shared inside the skin and leg
categories (five textures for ten groups each) and the head category has seven for eight.

**The two 16-carrier covers.** The shirt category (10) has 14 groups with 14 distinct textures but is not a cover by
itself: montages 14 and 34 draw no shirt at all (the bare-torso arm skin 222 is drawn exactly in those two), and
shirts 4 and 14 are drawn in montages {0, 2, 6} and {1, 3}, which are exactly the montages of pants 5 {0, 1, 6},
15 {2} and 25 {3}. Hence:

| cover | carriers | groups | shares if the montages are uniform (of 47) |
|---|---|---|---|
| `em1000-wide` (default) | 16 | shirts 104, 184, 74, 114, 54, 64, 124, 174, 194, 84, 154, 164; pants 5, 15, 25; arm skin 222 | 6, 5, 4, 4, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 1, 1 |
| the same with head 131 for 222 | 16 | as above, head 131 in place of arm skin 222 | the same |
| `em1000-shirts` | 15 | all fourteen shirts (4 and 14 for the three pants) and arm skin 222 | 6, 5, 4, 4, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2 |
| `em1000-pants` (the first table) | 10 | the twelve pants groups | 13, 8, 7, 5, 4, 3, 3, 2, 1, 1 |

The arm skin was taken over the head: a head the game hides (a burst head) would take the whole donor with it, a
torso skin is not hidden. The wide table is the default (`MIXES['uEm10']`); `--table uEm10=em1000-shirts` or
`em1000-pants` selects the others. The shares are flatter than the pants table's, which matters as much as the count:
sixteen donors with the most-drawn on 6 of 47 against ten with the most-drawn on 13.

**Why 15 exists.** Pants 5 keeps `gam01_005_BM`, and that texture is also the pants of `em2100` — the second Public
Assembly class — both in `uEm10.arc` (its own `em2100`, not replaced) and in `uEm21.arc`. Which copy the game samples
when both archives are loaded is not known. The 15-carrier table uses no texture that `uEm21.arc` carries (it still
neutralises `gam01_022_NM`/`_MM`, the leg maps, which `uEm21.arc` also has; a flat normal on a leg is cosmetic). The
pants table has the same exposure through carrier 5/55, and it is the one queued live, so the first Public Assembly
round on it already tells whether the em2100 of a round wears a donor atlas.

**Proof the enemy agent's check still holds.** `account_mix` now checks the exact-cover condition directly: for every
montage of the table, the carrier groups it draws (in any category) are counted; a drawn montage with zero or two is a
refusal. It runs inside `author_mix` on each of the three models before anything is written, and
`verify`/`_check_model` re-read the written models: donor records exist only in the carrier groups, one per group,
LOD mask 0xFF, every native record blanked, one donor's groups carrying one donor's bytes. `table-check.json` in the
working folder is the same re-read run from a fresh process on all six archives (every set, every model, every
table): all exact covers hold, all materials bind, all role maps agree with the animation ids.

Every albedo of the wide table is sampled either by one material or by the LOD0/LOD1 pair of the same part, and all
such pairs bind the same normal and mask maps (`gam01_054_NM_HQ` + `gam01_054_MM` for the shirts 54–194 except 84's
own mask, `em1000_104_NM_HQ` + `_MM` for the three `ShirtEri`, `gam01_005_NM` + `_MM` for the three pants,
`gam01_022_NM` + `_MM` for the arm skin); the groups the covers leave out of those categories (`uncarried_groups`) are
blanked like everything else and listed in the receipt.

`uEm11` stays at two: its table has 8 exact covers, four with 2 textures ({5, 15}, {6, 16}, {6, 18}, {15, 8}) and
four with 1. The shirt pair is kept.

## 2. The other classes

All four share the `em10` motion set, bind the fifteen roles on the same animation ids at the same bind positions as
`em1000` (hip 0, 114, 0; head 0, 165, −2.34; wrists ±70.4; ankles ±9.2, 13.5 — `em1300` differs only in the leg
spread, ±10.5, and its shin height 53.33), and have a native record in the donor's vertex format to use as template.
What each needed, in order of stage coverage:

| class (No Mercy spawns) | archive, SHA-256 | models (MOD / MRL) | what blocked it | what was found | carriers |
|---|---|---|---|---|---|
| `uEm12` Village 325, Ancient Ruins 386 | `4224faf2…`, 622 entries | `em1200` 93/74, `_low` 94/75, `_mid` 95/76; 81/31/63 bones, 19 groups | "bones not parents-first"; a zero row in the montage table; LOD mask 255 on native records | the bones ARE parents-first; the skeleton has a **second root**: a childless, unskinned bone at the origin with animation id 250 (bone 80 / 30 / 62). The montage table (entry 606, 24 parts, 16 montages) has one all-zero part row. The `_low` and `_mid` models carry a tongue (and an eye) record with mask 255 in head group 1 | body 2, 12, 22, 32 (`em1200_01/11/21/31_BM`, 1024×2048): **4**, 4 montages each. Heads would also give 4 |
| `uEm14` Experimental Facility 227 | `52399b0b…`, 656 entries | `em1400` 124/106, `_low` 125/107, `_mid` 126/108; 81/30/55 bones, 41 groups incl. group 0 | the same second root; group 0; no category draws one group per montage | table entry 642 (41 parts, 56 montages, none empty); masks with several bits, so a value draws several groups (boots 13 in every montage, body skin 1 in 26). 26 exact covers; the largest has 9 textures | tops 1, 14, 15, 17–22 (body skin, two jackets, six shirts): **9**; shares 26, 5, 5, 5, 4, 3, 3, 3, 2 of 56 |
| `uEm13` Mines 22, Prison 28 (and Reunion Public Assembly) | `1db1a79a…`, 135 entries | `em1300` 49/39; 89 bones, 4 groups | LOD masks 3 and 254 | the mask is one bit per level: 3 = near+middle (`gam_Eyes_LOD0_LOD1`), 254 = middle+far (`gam_Mouth_LOD1_LOD2`), the LOD2 body materials carry 252; a ground bone above the body root as `em1100`. Its mask maps are `_CMM` textures in format 0x13, which `mtf_tex` does not decode | pants 3, 13 (`em1302_BM` 1024×512, `em1304_BM` 512×512): **2**, one montage each |
| `uEm21` Public Assembly 1 | `3c01b16d…`, 146 entries | `em2100` 26/25 (under the `em10` model folder, the same name as the em2100 inside `uEm10.arc`); 90 bones, 7 groups | LOD mask 254; groups to review | table entry 139 (8 parts, 3 montages): shirt 254 and pants 255 drawn in all three, montages 1 and 2 draw no head, montage 1 names a body group the model lacks. Group 4 is not in the table and holds the shirt's far-LOD records alone | shirt 254 (`gam01_254_BM`, 1024×1024, the one texture `uEm10.arc` does not also carry): **1** |

What the writer learned from them, all of it in `re5_enemy_writer`:

- **A detached root.** `measure_roles` now separates roots with children (exactly one, the body) from childless roots
  (listed as `detached_bones`); a second root with children is still refused. The motion sampler already treated a
  parentless bone as hanging off the virtual root, so the posed previews of `em1200` and `em1400` needed nothing.
- **LOD masks are unions of levels.** Each `EnemySet` declares the masks its records were measured to use
  (`lod_masks`); `account_groups` refuses anything else. Donor records are no longer told from native ones by the mask
  (a native tongue in `em1200_low` has 255 too) but by the mesh id, which follows the native ids; `_check_model`,
  `preview` and `posed_preview` were changed accordingly (`preview` takes the original to know the native count).
- **A montage table may carry an all-zero part.** `parse_montage` keeps it and reports it (`empty_parts`); a part with a
  group and no mask is still refused.
- **A mask map in a format the codec cannot rewrite stays native and is named** (`secondary_maps_kept_native`:
  `em1302_CMM`, `em1304_CMM` for `uEm13`). The donor's UVs then sample a native mask; what that does to the surface is
  listed under the uEm13 first-boot risks. A BC7 albedo passed as a map is refused, not kept.
- **Group 0** is allowed where the set declares it (`em1400`).
- **The sampler rule and the winding** now match the player writer: `strict_samplers='in_range'`, `samplers_in_range`,
  and a `cw` donor has each triangle turned (`Donor.winding`, riders may carry it as a fifth field). This is what lets
  the enemy route take the shared survey's donors (DOA, FF7 field models and the others with clamped samplers).

### Overlays

Each folder under `C:\_tools\gBox\.scratch-merc-recovery\assets\` holds `romfs\nativeNXx64\ImgNX\Archive\<class>.arc`,
`receipt.json` (hashes, carriers, shares, `live_test` right/wrong, `first_boot_risks`, `live_verified: false`),
`preview.png`, `preview-posed.png` (em10_g06 clip 105 on the CPU) and one pair of pictures per donor. Hashes recomputed
from the files.

| overlay | archive | SHA-256 | bytes | entries changed / untouched | donors (carrier group, share) |
|---|---|---|---|---|---|
| `variety-uEm10-wide-v1` | `uEm10.arc` | `1b57d030702ef372…` | 77,023,338 | 28 / 759 | Mario SM64 DS (104, 6/47), Sonic (184, 5), Luigi SM64 DS (74, 4), Shadow (114, 4), Tails (5, 3), Amy (54, 3), Rouge (64, 3), Dr. Eggman (124, 3), Tikal (174, 3), Knuckles (194, 3), Ryo (84, 2), HUcast (154, 2), Claude GTA III (164, 2), Voldo (222, 2), Mario SM64 (15, 1), Big the Cat (25, 1) |
| `variety-uEm12-v1` | `uEm12.arc` | `770768ae66a5a5de…` | 30,112,326 | 15 / 607 | Mario SM64 DS (2, 4/16), Sonic (12, 4/16), Ryo (22, 4/16), Claude GTA III (32, 4/16) |
| `variety-uEm13-v1` | `uEm13.arc` | `b27ed02dff24cec4…` | 16,231,162 | 5 / 130 | Shadow (3, 1/2), HUcast (13, 1/2); `em1302_CMM`, `em1304_CMM` kept native |
| `variety-uEm14-v1` | `uEm14.arc` | `6ebbbcbfc7885fbb…` | 41,639,514 | 18 / 638 | Luigi SM64 DS (1, 26/56), Tails (14, 5), Knuckles (15, 5), Amy (22, 5), Voldo (20, 4), Snake TTS (17, 3), Yoshi SM64 (18, 3), Rouge (21, 3), Beat JGR (19, 2) |
| `variety-uEm21-v1` | `uEm21.arc` | `7977e7ba310d955b…` | 12,010,018 | 4 / 142 | Dr. Eggman (254, 3/3) |

Full hashes are in each `receipt.json` (`archives.<class>.output_sha256`). The `posed` rows of the `uEm13` receipt
say `skeleton_displacement_max_cm 106.8`: that is the comparison sampler's lookup meeting the duplicate animation id 0
of the ground bone and the body root (`em1100` shows the same), not a moved joint; the other classes report 0.0.

What a first round of each must show is in every receipt (`live_test.right` / `wrong`, `first_boot_risks`). The short
form: several whole characters of that class at once, none body-less, none doubled, no stock part; for `uEm21`, a stock
em2100 means the game drew the copy inside `uEm10.arc`; for `uEm13`, a patchy surface that follows nothing on the donor
is the native mask sampled through the donor's UVs.

### Every other class the stages place

The operator (2026-11-09 22:00 UTC): "I want any and all enemies in these games replaced." The eleven remaining
classes of the eight stages' layouts were copied from the Spark (read-only, 195 MB) and read the same way. Seven are
standing bipeds with the fifteen role ids at the Majini bind positions and take a donor; four are not bodies a biped
donor can stand in. Spawn counts are No Mercy placements unless marked Reunion.

| class (spawns) | archive, SHA-256, entries | model | what it needed | overlay, donor, SHA-256, bytes, changed / untouched |
|---|---|---|---|---|
| `uEm24` Village 8, Ancient Ruins 13 | `482172df…`, 217 | `em2400` 66/50, 89 bones, 66 records, groups 0 head, 1 body, 2 leg (its textures are `em1200_*` and `em2400_BM_01`), top 195.7 | roles by ids (the chest carries more than two arms and a neck); its albedo is named `em2400_BM_01`, which the MRL binder's `_BM` suffix rule refused - the rule now takes `_BM_NN` | `variety-uEm24-v1`: Knuckles, `aaeb92f2a0f6bb2e…`, 22,774,043, 4 / 213 |
| `uEm22` Ship Deck 14 | `2020d20d…`, 164 | `em2200` 52/40, 98 bones, 38 records, groups 1 head, 2 body, 3 leg, 5 pants, 6 wig, 8 key; masks 254 and 255 | roles by ids; `em22` clip 0 has two tracks for one bone, so the CPU sampler draws no posed picture (the archive is unaffected) | `variety-uEm22-v1`: Fox (Melee), `72d830bcde7229ab…`, 13,989,095, 4 / 160 |
| `uEm20` Public Assembly 6, Prison 4 | `269559f2…`, 166 | `em2000` 59/40, 120 bones, 59 records, one group, mask 254 | roles by ids; the apron atlas (1024 squared, three materials, `shared_atlas`); the sampler cannot read the skin weights of its 0x1580b60c records, so no posed picture | `variety-uEm20-v1`: Astaroth (SoulCalibur), `3f4d1dd0c3193e35…`, 12,611,516, 4 / 162 |
| `uEm34` The Mines 7 | `6050bb81…`, 507 | `em3400` 71/48, 98 bones, 42 records, one group, 4.36 m tall (hip 186 cm, hands +-185) | roles by ids (its neck chain is ambiguous to the measurement); the position round-trip tolerance was 0.01 cm, below one quantisation step of a 4 m span (0.012) - it is now one step of the widest axis, never under 0.01 | `variety-uEm34-v1`: Malprave (007), `9067a5f584bb76e2…`, 18,877,776, 4 / 503 |
| `uEm23` Missile Area 6, Ship Deck Reunion 1 | `4441a22c…`, 187 | `em2300` 81/63, 93 bones, 81 records, groups 0-4 and 205, masks 3 and 4 | measures outright; its masks are `_CMM` (format 0x13) and stay native | `variety-uEm23-v1`: Solid Snake (TTS), `fb2464fd7f23e6ca…`, 16,961,881, 3 / 184 |
| `uEm26` Prison 5 | `31010f45…`, 170 | `em2600` 63/44, the em20 skeleton, 99 records, one group | roles by ids; three native records address a window two vertices inside their range (`min_index = vertex_index + 2`), which the graft and the re-read now allow for native records (donor records stay exact) | `variety-uEm26-v1`: Voldo, `ff63d2fcf55bd1f7…`, 14,658,190, 4 / 166 |
| `uEm92` Public Assembly Reunion 1 | `7da2e478…`, 159 | `em9200` 43/39, 117 bones, 84 records, groups 0 body, 1 hair, 3 head, mask 255; its montage table names one group per category | roles by ids; `evf28xx` cutscene models left native | `variety-uEm92-v1`: Aerith (FF7 field), `842d3be0df1e811e…`, 15,781,669, 4 / 155 |
| `uEm32` Experimental Facility **172** | `42ea8e01…`, 394 | `em3200` + `_low`/`_mid`, 83 bones, 16 records, one group | **no writer**: a crawling body 27 cm tall at the bind pose; the pelvis and spine trunks cannot be told apart and the role ids put the left leg on -X with the feet level with the hips. A standing donor fitted to those joints would lie on the floor in a knot | - |
| `uEm0b` Village 66, Reunion Ruins 5, Reunion Public Assembly 8 | `01a2580b…`, 197 | `em0b00`, 70 bones, 21 records, one group, 86 cm | **no writer**: a quadruped; the role ids name legs that rise and hands below the hips | - |
| `uEm30` The Mines Reunion 13 | `b50b3208…`, 381 | `em3000` 90 bones / 78 records / 7 groups, `em3100` 94 / 90 / 2, 119-132 cm; montage table 4 montages, 3 carriers | **no writer**: the fifteen ids exist but sit on bones whose bind pose is no biped (hip at 16 cm beside the left hand, the "legs" rising to 73 cm, left and right crossed) | - |
| `uEm62` Prison 10, one in every other stage | `984fcb15…`, 83 | `em6200`, 20 bones, 60 records, two groups, 50 cm | **no writer**: a flying body; the leg ids are absent and no record uses the donor's vertex format (no template) | - |

The boss-class overlays are one donor on every option group (the shape the game has drawn), `live_verified: false`,
with the same receipts and pictures as the others (`preview-posed.png` is missing where the sampler refused the clip).
Giants come out as the donor stretched to the class's bind pose: Knuckles 196 cm on `em2400`, Malprave 318 cm on
`em3400` (its head at the Reaper's head joint, 257 cm). What the writer learned from them: `role_map(allow_ids=True)`
with `check_role_geometry` (left on +X, legs descend, arms outward, head over chest over hips), `EnemySet.roles_by_ids`
and `shared_atlas`, the `_BM_NN` albedo names, the native window rule, the round-trip step tolerance, and a posed
preview that fails without taking the archive with it. `re5_cast_series --with-bosses` deals one donor to each of
the seven beside the mix classes (`enemy_slots(singles=True)`); the four series builds below were dealt without them
and keep the six-class deal they started with. `UNBUILDABLE_CLASSES` carries the four blockers with hashes and spawn
counts, and the series manifest lists them under `classes_without_a_writer`.

## 3. A series over every donor

`re5_cast_series.plan_series(seed, donors, enemy_pool=…)` deals the whole library into builds. One build is one
overlay: the six player slots (`re5_donor_pool.plan`, every earlier build as history so unseen donors come first,
franchises in turn) and then every carrier of every class (`uEm10` 16, `uEm11` 2, `uEm12` 4, `uEm13` 2, `uEm14` 9,
`uEm21` 1 = 34) from the enemy-eligible donors without the build's players — 40 donors a build, none twice inside one.
The series ends when every donor of either pool has been dealt once; with the 650 usable donors of the shared survey
that is **17 builds** (16 × 40 new donors, then 10 new and 30 second appearances). The same seed, survey, eligibility
and refusals give the same series.

Eligibility and refusals are part of the plan. Before planning, the enemy go/no-go (`re5_enemy_cast.survey` over the
650 through `donor_from_pool`: importer at 512×256 with samplers in range, `check_rig`, the hole test on the measured
`em1000` joints) left **599** eligible as enemies; the 51 others (32 whose chest joint sits below the hip joint - waist-jointed rigs the enemy fit has no lower-spine mapping for - 5 mirrored, 2 whose head does not rise above its joint, 12 with a height the fitted figure leaves empty) stay in the player pool and are
covered there. A donor a slot refuses while building is recorded against that role (`manifest.refusals`): a player
slot's refusal has the series dealt again from that build on; an enemy class's refusal (the fit collapses a triangle,
a fifth skin influence, a surface the atlas cannot take - things the cheap survey does not see) gives that carrier to
a deterministic `substitute` (from the build seed: an unseen donor of the same franchise first, then any unseen, then
a seen one; never one already in the build) and only that class is built again (`manifest.builds[].substitutions`).
The enemy classes are built one at a time for that reason. So the manifest and the archives agree, and a refusal
costs one class, not a build.

`C:\_tools\gBox\.scratch-merc-recovery\assets\pool-series\manifest.json` lists all SERIES_COUNT builds (donor per slot
and class, which donors appear for the first time), the four that were built (`build-01` … `build-04`, each with its
`romfs\` tree of 12 archives, `receipt.json`, `receipt-players.json`, `receipt-enemies.json`, the player contact sheet,
the enemy rest and posed sheets and one pair per donor), the file-by-file SHA-256 and byte counts (checked against the
receipts and the files on disk), the label table with its evidence, the refusals and the rotation.

SERIES_TABLE

**How the MercMode queue should rotate them.** Until the hot-swap experiment of the task guide's package B has an
answer, a build is a `recovery-*` overlay installed through `switch_mods` and the title restarts to load it, so the
queue plays **one build per N rounds**: install build k, queue N rounds over the six stages, install k + 1. N trades
variety against restarts (each shows loading screens); N = 6 — one round per stage — is the smallest cycle that shows
every class of a build. If the in-place overwrite probe holds, pad every archive of the series to one size per slot,
overwrite at the results screen and advance **one build per round**: 17 builds are a 17-round cycle with all 650
characters. Builds play in index order; the manifest is the queue (build k → its folder); a build a live round refuses
is skipped and recorded, not rebuilt in place. The bot picks players by roster label, so each round can name its
character and the classes it will meet from the manifest.

## 4. The Chris costume labels

Seen live (session `0a61e625f9d844d6-3ddd04616ed846de`, build `recovery-cast-pool-03-chris-test-20261109`): the queue
entry "Chris (Safari)" drew Ryo, whom cast pool 03 had written into `uPl00ChrisCos2.arc` under its "STARS" row. So the
roster's Safari loads Cos2 and its STARS loads Cos1. `re5_cast_writer.SLOTS` now says so (`chris_safari` →
`uPl00ChrisCos2`, `4df4a987…`, models `pl11\model\pl1100` + base; `chris_stars` → `uPl00ChrisCos1`, `fa3f0a85…`,
`pl10\model\pl0000` + base), `LABEL_ARCHIVES` is the label → archive table and `LABEL_EVIDENCE` says which rows were
seen (Chris: live; Sheva's Clubbin → Cos2 / Tribal → Cos1: offline, from the decoded costumes). The pinned vtable list
names Cos2 before Cos1 for all four characters, which fits a roster whose second entry is Cos2 for everyone. The test
pins the table. Cast pools 01–03 were built with the old rows: their "Safari" donor is on the roster's STARS entry and
the other way round; the series builds use the corrected table.

## 5. What was run, what is inferred

Run: the probes over the six archives (every entry recompresses byte-identically at level 6, `mt_arc.build(parse(x))
== x`), the exact-cover enumeration on `em1000` and `em1400`, `table-check.json` (role maps, groups, exact covers,
material bindings on every model of every set), the enemy go/no-go over the 650 donors, the five class overlays and
the four series builds through the writers with `verify` inside each (entry count unchanged, every entry outside the
reviewed indices byte-identical, zlib framing, native tables untouched, donor record shape, bounds, skin weights,
textures in their containers), the file hashes against the receipts, and the test suite (the RE5 writer, mix, cast,
donor, pool, series and variety tests).

Inferred, as before: the montage reading itself (one montage per spawn, parts selected by mask bit), how the game
picks a montage for `-1`, whether code hides a category during damage or death, which archive's copy of a shared
texture the game samples, whether the second root bone or the 255-mask tongue of `em1200` means anything at runtime,
whether `uEm21`'s own em2100 or the one in `uEm10.arc` is drawn. The stage names of `s401`–`s407` are still the menu
order. The game's menu text for the two Chris costumes was not read; the label table maps the bot's labels.

## Reproduce

```powershell
$py = 'C:\_tools\gBox\.venv-session-audit\Scripts\python.exe'
cd C:\_tools\gBox-wt-re5-cast-variety\system
# the class overlays (ORIGINALS holds uEm10 ... uEm21 .arc; LIBRARY the character library)
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --name variety-uEm12-v1 --assign "uEm12=sm64ds_mario+sonic+ryo+gta3_claude"
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --name variety-uEm21-v1 --mix --assign "uEm21=sa2_dr_eggman"
& $py -m gbox.re5_enemy_cast --archives ORIGINALS --library LIBRARY --out OUT --name x --pool 1 --pool-from SURVEY --table uEm10=em1000-shirts
# the series
& $py -m gbox.re5_cast_series --romfs ROMFS --archives ORIGINALS --library LIBRARY --survey library-survey.json `
      --enemy-survey enemy-survey-650.json --seed 20261109-series --out OUT\pool-series --count 4
& $py -m gbox.re5_cast_series ... --plan-only            # the plan alone, nothing written
# the tests
cd ..; $env:PYTHONPATH='system;system/tests'; $env:GBOX_RE5_CLASS_ARCHIVES='ORIGINALS'
& $py -m pytest -q -p no:cacheprovider --disable-warnings system/tests/test_re5_cast_variety.py system/tests/test_re5_enemy_mix.py
```

## Not done

- No boot of anything here; the first-boot order of the enemy-cast note still applies (one class at a time, `uEm10`
  first, the new classes one by one).
- `uEm32` (the Experimental Facility's 172 crawlers), `uEm0b` (the Village dogs), `uEm30` and `uEm62` have no writer:
  their bodies are not bipeds (section 2). A writer for them would be a new fit, not a table.
- The boss overlays have one donor each and no posed picture for `uEm20`, `uEm22`, `uEm26` (the CPU sampler refuses
  their clips or skin layouts); the giants' look at 2-4 m is a guess until a frame shows it.
- The montage distribution per stage is "if uniform" for the `-1` spawns; the census stores the set of explicit
  montage numbers per class and mode, not a count per spawn.
- The series' later builds are planned, not built; a refusal found while building them re-deals from that build on.
- The hot-swap op and the queue generator over accepted rows (task guide packages B and C) are not here; §3 says how
  the series feeds them.
