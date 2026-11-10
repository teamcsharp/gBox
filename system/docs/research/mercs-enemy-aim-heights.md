# RE5 + RE6 Switch: measured enemy aim heights (request #9344)

All values are centimetres above the model origin (y=0, the enemy's position anchor and the reference LOW_BODIES in `re5_switch.py` already uses), read from the bind pose of the main model's skeleton. Milestone 1: human-layout skeletons are measured; creature skeletons are not yet (see *Not determined*).

## Method

1. Archive: RE5 `~/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive/uEmXX.arc`, RE6 `.../01002A000CD48000/nativeNXx64/arc/NX/uEmXXXX.arc`, parsed with `gbox.mt_arc.parse`; entries inflated with zlib where compressed.
2. Main model: the `MOD` entry named `pawn\em\emXX\model\emXX00` (RE5) / `...\emXXXX` (RE6), parsed with `gbox.mt_model.parse_mod`.
3. Skeleton: `bone_table()` (parents, animation ids) and `bone_world_matrices()` (bind pose, row-vector matrices, translation = elements 12..14, **y up**, x lateral, z forward).
4. Roles come from the MT Framework human animation ids, the same in both games: head=4, neck=3, spine(chest)=2, upper arms=6 (L) / 11 (R), thighs=16 / 20, knees=17 / 21. head = bone id 4 (the head joint, not the crown); chest = spine bone id 2 (neck base id 3 is listed in `bones.chest.note`); shoulder = mean y of the two upper-arm joints; knee = mean y of the two knee joints; radius = half the larger of the shoulder width (upper-arm joint x spread) and hip width (thigh x spread).
5. A class counts as human-layout only if all of: ids present; head>=neck>spine>knee; head bone within 0.5..1.05 of the mesh top; mesh bottom within -20..20 cm of the origin; upper arms level (<3 cm) and symmetric; thighs on opposite sides; shoulder above spine. Otherwise it is `not determined`, never filled by estimate.
6. `height` = mesh vertex y range (`m.all_positions()`), max - min. `mesh_top_y`/`mesh_min_y` are relative to the origin. Where the mesh top is far above the head bone a `note` says so.
7. Posture: `upright` for validated human layout. Otherwise by stated rule on bind-pose geometry: >=4 leaf bones within -8..12 cm of the origin plane and mesh top >40 cm = `four-legged`; mesh top <=40 cm and horizontal span >2x top = `crawling`; else `not determined`.
8. Idle pose: every class is `bind pose only`. Each arc carries LMT motion files, and `gbox.mtf_motion` can sample RE5 clips, but clips are numbered not named (no idle marker in the file) and RE5 leg chains need engine IK, so an idle-pose head height cannot be read from the files alone.

Throwaway script: `~/.hermes/cache/scratch/build.py` (outside the repo). Human profile for comparison (`re5_switch.py` line 488): HEAD_H 160, CHEST_H 110, KNEE_H 45, SHOULDER_H 145, BODY_R 36.

Findings:
- The real human skeleton is HEAD 165 / CHEST 132 / KNEE 57.5 / SHOULDER 151 / RADIUS 17 (RE5 Majini); RE6 J'avo/zombies 162 / 129 / 55 / 148 / 16.5. The bot's HUMAN profile has a 36 cm BODY_R (2x the measured half-width), CHEST_H 22 cm below the spine bone and KNEE_H 12 cm below the knee joint.
- Measured classes: RE5 13, RE6 19. Not determined: RE5 7, RE6 18.
- Low classes (mesh top above origin): Licker uEm32 27 cm (existing LOW_BODIES head 45 is above the model's top), dogs uEm0b 86.5 cm, Zombie Dog uEm5700 119 cm (mesh includes ears), Adjule uEm30 119 cm.

## RE5 (sorted by deviation from the human profile, largest first)

| class | name | status | posture | head | chest | knee | shoulder | radius | height | top | bones (anim ids) / note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| uEm32 | Licker β | not determined | crawling | not determined | not determined | not determined | not determined | not determined | 54.8 | 27.2 | not human layout; geometry only |
| uEm0d | Cephalo | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 328.4 | 337.2 | not human layout; geometry only |
| uEm0c | Kipepeo | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 145.3 | 43.2 | not human layout; geometry only |
| uEm62 | Chicken | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 54.6 | 49.7 | not human layout; geometry only |
| uEm0b | Bui Kichwa | not determined | four-legged | not determined | not determined | not determined | not determined | not determined | 96.5 | 86.5 | not human layout; geometry only |
| uEm34 | Reaper | measured | upright | 257.5 | 205.5 | 108.8 | 233.3 | 29.0 | 437.0 | 436.3 | head b32, chest b16, knee b9/b4, shoulder b26/b20, hips b8/b3; mesh top is 178.8 cm above the head bone (other geometry above the head) |
| uEm0e | Duvalia | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 114.6 | 98.0 | not human layout; geometry only |
| uEm30 | Adjule | not determined | four-legged | not determined | not determined | not determined | not determined | not determined | 124.2 | 119.0 | not human layout; geometry only |
| uEm11 | Majini (female) | measured | upright | 164.7 | 131.2 | 57.5 | 150.7 | 13.0 | 185.3 | 183.6 | head b78, chest b16, knee b6/b12, shoulder b48/b18, hips b5/b10 |
| uEm92 | Jill Valentine (enemy) | measured | upright | 164.7 | 131.2 | 57.5 | 150.7 | 13.0 | 184.6 | 182.8 | head b82, chest b18, knee b6/b12, shoulder b49/b20, hips b5/b10 |
| uEm10 | Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 187.3 | 185.6 | head b81, chest b15, knee b4/b9, shoulder b17/b50, hips b2/b7 |
| uEm12 | Wetlands Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 185.1 | 185.1 | head b75, chest b15, knee b4/b9, shoulder b17/b47, hips b2/b7 |
| uEm13 | Big Man Majini | measured | upright | 165.0 | 132.0 | 53.3 | 150.8 | 17.2 | 184.4 | 184.3 | head b82, chest b16, knee b5/b10, shoulder b18/b51, hips b3/b8 |
| uEm14 | Base Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 186.8 | 186.4 | head b75, chest b15, knee b4/b9, shoulder b17/b47, hips b2/b7 |
| uEm20 | Executioner Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 188.3 | 188.2 | head b112, chest b51, knee b33/b38, shoulder b53/b84, hips b31/b36 |
| uEm21 | Agitator Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 186.2 | 184.5 | head b81, chest b15, knee b4/b9, shoulder b17/b50, hips b2/b7 |
| uEm22 | Chainsaw Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 185.3 | 185.4 | head b81, chest b20, knee b5/b10, shoulder b22/b53, hips b3/b8 |
| uEm23 | Gatling Gun Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 186.6 | 186.2 | head b65, chest b3, knee b83/b88, shoulder b5/b36, hips b81/b86 |
| uEm24 | Giant Majini | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 195.7 | 195.7 | head b82, chest b22, knee b5/b10, shoulder b24/b54, hips b3/b8; mesh top is 30.7 cm above the head bone (other geometry above the head) |
| uEm26 | Executioner Majini (red) | measured | upright | 165.0 | 132.0 | 57.5 | 150.8 | 17.2 | 187.0 | 186.9 | head b112, chest b51, knee b33/b38, shoulder b53/b84, hips b31/b36 |

## RE6 (sorted by deviation from the human profile, largest first)

| class | name | status | posture | head | chest | knee | shoulder | radius | height | top | bones (anim ids) / note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| uEm4800 | Ogroman | measured | upright | 962.5 | 687.8 | 297.0 | 855.0 | 174.7 | 1105.7 | 1102.5 | head b64, chest b16, knee b3/b8, shoulder b19/b42, hips b2/b7 |
| uEm3300 | Gnezdo | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 4.3 | 3.4 | not human layout; geometry only |
| uEm4710 | Rasklapanje (hand) | not determined | crawling | not determined | not determined | not determined | not determined | not determined | 16.0 | 8.7 | not human layout; geometry only |
| uEm3320 | Gnezdo (core) | not determined | crawling | not determined | not determined | not determined | not determined | not determined | 56.9 | 12.8 | not human layout; geometry only |
| uEm2200 | J'avo mutation (legs) | not determined | crawling | not determined | not determined | not determined | not determined | not determined | 178.5 | 22.8 | not human layout; geometry only |
| uEm2140 | J'avo mutation (arm) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 61.7 | 53.6 | not human layout; geometry only |
| uEm2100 | J'avo mutation (arm) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 69.9 | 63.3 | not human layout; geometry only |
| uEm2120 | J'avo mutation (arm) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 59.3 | 70.4 | not human layout; geometry only |
| uEm2030 | J'avo mutation (head) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 71.9 | 71.5 | not human layout; geometry only |
| uEm5700 | Zombie Dog | not determined | four-legged | not determined | not determined | not determined | not determined | not determined | 124.1 | 119.0 | not human layout; geometry only |
| uEm3100 | Mesets | not determined | four-legged | not determined | not determined | not determined | not determined | not determined | 145.4 | 127.1 | not human layout; geometry only |
| uEm4700 | Rasklapanje | measured | upright | 202.5 | 163.0 | 62.1 | 174.2 | 18.0 | 225.4 | 225.3 | head b47, chest b2, knee b75/b80, shoulder b26/b4, hips b73/b78 |
| uEm2230 | J'avo mutation (legs) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 135.2 | 133.6 | not human layout; geometry only |
| uEm4701 | Rasklapanje (torso) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 94.8 | 225.3 | not human layout; geometry only |
| uEm3000 | Strelats | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 229.7 | 224.1 | not human layout; geometry only |
| uEm2010 | J'avo mutation (head) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 124.3 | 221.2 | not human layout; geometry only |
| uEm2210 | J'avo mutation (legs) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 307.1 | 151.4 | not human layout; geometry only |
| uEm4300 | Ubistvo | measured | upright | 169.1 | 136.1 | 62.7 | 154.9 | 16.5 | 195.5 | 195.5 | head b43, chest b13, knee b8/b4, shoulder b15/b23, hips b7/b2 |
| uEm5210 | Zombie | measured | upright | 160.1 | 129.1 | 54.6 | 147.9 | 15.3 | 178.8 | 178.1 | head b13, chest b11, knee b7/b3, shoulder b16/b22, hips b6/b2 |
| uEm1000 | J'avo | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 180.7 | 180.5 | head b4, chest b2, knee b24/b20, shoulder b7/b13, hips b23/b19 |
| uEm1200 | J'avo (Lanshiang) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 182.6 | 182.5 | head b25, chest b11, knee b7/b3, shoulder b13/b19, hips b6/b2 |
| uEm1370 | J'avo mutant (uEm1370) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 187.0 | 181.8 | head b4, chest b2, knee b29/b33, shoulder b8/b16, hips b28/b32 |
| uEm1400 | J'avo (Neo-Umbrella) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 182.4 | 182.4 | head b13, chest b11, knee b3/b7, shoulder b18/b24, hips b2/b6 |
| uEm4100 | Lepotitsa | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 181.1 | 180.8 | head b4, chest b2, knee b83/b87, shoulder b19/b40, hips b82/b86 |
| uEm5000 | Zombie (Mining the Depths) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 182.2 | 181.9 | head b4, chest b2, knee b18/b22, shoulder b12/b7, hips b17/b21 |
| uEm5050 | Zombie (miner) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 183.5 | 183.0 | head b4, chest b2, knee b23/b19, shoulder b13/b8, hips b22/b18 |
| uEm5060 | Zombie (miner) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 183.5 | 183.0 | head b4, chest b2, knee b23/b19, shoulder b13/b8, hips b22/b18 |
| uEm5181 | Zombie (police) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 183.9 | 183.7 | head b4, chest b2, knee b20/b24, shoulder b9/b15, hips b19/b23 |
| uEm5191 | Zombie (firefighter) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 184.1 | 183.9 | head b4, chest b2, knee b20/b24, shoulder b9/b15, hips b19/b23 |
| uEm5200 | Zombie | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 183.3 | 182.0 | head b4, chest b2, knee b18/b22, shoulder b12/b7, hips b17/b21 |
| uEm5400 | Zombie (The Catacombs) | measured | upright | 162.1 | 129.1 | 54.6 | 147.9 | 16.5 | 179.5 | 179.5 | head b4, chest b2, knee b18/b22, shoulder b7/b12, hips b17/b21 |
| uEm5500 | Zombie special (uEm5500) | measured | upright | 178.3 | 129.1 | 54.6 | 147.9 | 16.5 | 189.4 | 189.2 | head b20, chest b11, knee b3/b7, shoulder b24/b29, hips b2/b6 |
| uEm5600 | Whopper | measured | upright | 161.9 | 128.9 | 44.6 | 147.7 | 22.5 | 181.9 | 181.1 | head b4, chest b2, knee b29/b33, shoulder b12/b21, hips b28/b32 |
| uEm2300 | Chrysalid | not determined | not determined | not determined | not determined | not determined | not determined | not determined | 137.4 | 198.9 | not human layout; geometry only |
| uEm3200 | Napad | measured | upright | 171.2 | 122.0 | 46.6 | 148.8 | 36.0 | 219.0 | 219.7 | head b22, chest b2, knee b32/b36, shoulder b4/b11, hips b31/b35; mesh top is 48.5 cm above the head bone (other geometry above the head) |
| uEm3301 | J'avo mutant (em1370 body) | not determined | not determined | not determined | not determined | not determined | not determined | not determined | not determined | - | no stand-in MOD for this class |
| uEm9906 | Parachute | not determined | not determined | not determined | not determined | not determined | not determined | not determined | not determined | - | no stand-in MOD for this class |

## Not determined (what would settle it)

- Creature skeletons (uEm32 Licker, uEm0b/uEm5700 dogs, uEm30, uEm0c, uEm0d, uEm0e, uEm62, uEm2xxx mutations, uEm2300, uEm3000, uEm3100, uEm4701/4710, uEm3320): The MOD skeleton carries no bone names, only per-model animation ids whose meaning is class specific (the human ids 2/3/4/6/11/16/17/20/21 do not fit this layout by the validation in the method). Would be settled by this class's hit-zone records (HIT/OBJA entry in the RE5 arc, XFS entry in the RE6 arc, bone-attached spheres) or a motion-labelled rig; not read in this milestone.
- RE6 uEm3300 Gnezdo: the main MOD has 3 vertices (a 4 cm stub); em3310 is not a human layout. uEm3301 and uEm9906: no MOD named after the class (uEm3301 carries em3300/em3310; uEm9906 only `sm5051`), the stand-in model is not the enemy.
- Values for the non-determined creatures in the JSON are geometry only (mesh extent, percentiles of vertex height, leaf bones near the ground, highest bone). They are measurements of the mesh, not head/chest/knee/shoulder heights.
- Idle-pose head height: needs the idle clip's number (not stored in the LMT) and, for RE5 legs, the engine's IK.

## Next milestone

Read the HIT/XFS hit-zone records of the creature classes (bone-attached spheres give head/chest per zone) and add them to the creature rows.
