# Sonic & Mario Donor Audit — gbox-cache/characters

Request 62783173f5f04b62 (#9077) · 2026-11-09 · measured with the repo's own parser (`gbox.characters._load`).

## Scope & method
- Scanned **1447** library entries under `gbox-cache/characters`.
- Classification: name-token match on slug/name/aliases (Sonic: sonic, tails, knuckles, amy, shadow, rouge, eggman/robotnik, tikal, cream, chaos, echidna, big[game Sonic], metal sonic; Mario: mario, luigi, peach, bowser, yoshi, toad, wario, waluigi, daisy, big[game Mario]).
- False-positive overrides: `{'slug': 'auf_superthug_body', 'family_would_be': [], 'reason': '007 Agent Under Fire thug, no Sonic/Mario relation'}` (), `{'slug': 'auf_superthug_body_a8a1484cf7ac7ce1', 'family_would_be': [], 'reason': '007 Agent Under Fire thug, no Sonic/Mario relation'}` (), `{'slug': 'ff7_chaos', 'family_would_be': [], 'reason': "Final Fantasy VII enemy 'Chaos', not the Sonic Adventures Chaos"}` (), `{'slug': 'mgs2_snake_bigshell', 'family_would_be': [], 'reason': 'Metal Gear Solid 2 weapon system, not Big the Cat'}` (), `{'slug': 'mgs2_snake_bigshell_7473dc814d0cf869', 'family_would_be': [], 'reason': 'Metal Gear Solid 2 weapon system, not Big the Cat'}` (), `{'slug': 'nm_big_boss_man', 'family_would_be': [], 'reason': 'Metal Gear entry (Big Boss), not Sonic/Mario'}` (), `{'slug': 'sc2_yoshimitsu', 'family_would_be': ['mario'], 'reason': 'Tekken fighter Yoshimitsu, not a Yoshi'}` (), `{'slug': 'sc2_yoshimitsu_e08e8a0c1b3c9060', 'family_would_be': ['mario'], 'reason': 'Tekken fighter Yoshimitsu, not a Yoshi'}` (), `{'slug': 'sc_yoshimitsu', 'family_would_be': ['mario'], 'reason': 'Tekken fighter Yoshimitsu, not a Yoshi'}` (), `{'slug': 'sd2_big_boss_man', 'family_would_be': [], 'reason': 'Metal Gear entry (Big Boss), not Sonic/Mario'}` ()
- **Tier 1 (ranked)** = name-token character match: **68** entries. **Tier 2 (review only)** = same-game entries without a character-name token: **17** entries.
- Per entry: GLB tris/verts, NORMAL coverage, joint count, texture count, bbox (local units), sha256, cross-check vs `meta.stats`, role resolution against the reference set (23 roles: chest, head, hip, l_clav, l_foot, l_fore, l_hand, l_hand_end, l_shin, l_thigh, l_toe, l_upper, neck, pelvis, r_clav, r_foot, r_fore, r_hand, r_hand_end, r_shin, r_thigh, r_toe, r_upper).

## Ranked shortlist (tier 1, best donor per character first)

Roles resolved against the 23-role reference set. Heights are local source units — scale normalisation is required for any Mercs swap.

### sonic (7 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_sonic | 15 | 74 | all (16/16 prims) | 1001 | undetermined (n=16) | 10.0828 | 587bf36e97587da9 |  |
| sonic | 15 | 62 | all (4/4 prims) | 1369 | undetermined (n=4) | 10.8055 | 5dd7cc07f3116a8f |  |
| s3k_sonic | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sk_sonic | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sonic1_shadow | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sonic2_sonic | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sonic2_tails | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### super_sonic (2 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_super_sonic | 15 | 74 | all (15/15 prims) | 1046 | undetermined (n=15) | 11.0274 | 6ef44819928737a9 |  |
| sa2_super_sonic | 15 | 62 | all (4/4 prims) | 1369 | undetermined (n=4) | 10.7999 | a2fe5100cb09202f |  |

### shadow (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_shadow | 15 | 62 | all (5/5 prims) | 1543 | undetermined (n=5) | 11.4142 | b9ec4c6b2d365128 |  |

### super_shadow (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_super_shadow | 15 | 62 | all (4/4 prims) | 1543 | undetermined (n=4) | 11.0986 | 71d378d1d17fa26c |  |

### tails (3 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_tails | 15 | 69 | all (14/14 prims) | 997 | undetermined (n=14) | 9.4043 | 2497f8bee301e5d9 |  |
| sa2_tails | 15 | 62 | all (3/3 prims) | 1180 | undetermined (n=3) | 8.4022 | fc4b6d2a61ba93aa |  |
| s3k_tails | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### knuckles (4 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_knuckles | 15 | 74 | all (13/13 prims) | 981 | undetermined (n=12) | 10.9715 | 55d7cf95a43e50a9 |  |
| sa2_knuckles | 15 | 62 | all (3/3 prims) | 1241 | undetermined (n=3) | 10.6396 | dae6438d36ace21a |  |
| s3k_knuckles | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sk_knuckles | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### amy (2 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_amy | 15 | 79 | all (30/30 prims) | 1000 | undetermined (n=29) | 9.2344 | 1e721bb7b48f9487 |  |
| sa2_amy_rose | 15 | 62 | all (7/7 prims) | 1384 | undetermined (n=7) | 10.3466 | 689510f291459a23 |  |

### rouge (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_rouge | 15 | 62 | all (8/8 prims) | 1280 | undetermined (n=8) | 11.0044 | 5fb3b28d369c5b58 |  |

### eggman (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_dr_eggman | 15 | 46 | all (8/8 prims) | 1264 | undetermined (n=8) | 15.866 | 5fbffee7538fef7b |  |

### tikal (2 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_tikal | 15 | 104 | all (16/16 prims) | 948 | undetermined (n=16) | 9.2394 | baa07b4b03264e1a |  |
| sa2_tikal | 15 | 62 | all (14/14 prims) | 938 | undetermined (n=14) | 10.4806 | 5e88b11f8a3edfb7 |  |

### metal_sonic (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_metal_sonic | 15 | 62 | all (8/8 prims) | 1316 | undetermined (n=8) | 10.7845 | efaa75ed5ffbcb3c |  |

### chaos (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_chaos_0 | 15 | 62 | all (3/3 prims) | 1648 | undetermined (n=3) | 11.3282 | ee39944f3fc690fc |  |

### big (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa1_big | 15 | 74 | all (30/30 prims) | 1134 | undetermined (n=29) | 31.4829 | 8294bdff171db5c7 |  |

### mario (8 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_mario | 18 | 61 | all (52/52 prims) | 5908 | undetermined (n=40) | 1.5122 | 2e8a1a994b419700 |  |
| mario_hd | 18 | 21 | all (15/15 prims) | 19422 | undetermined (n=3) | 1.4928 | 38d8a3938d1853dc |  |
| sm64_mario | 18 | 21 | all (11/11 prims) | 752 | undetermined (n=5) | 1.5 | 0f8187777193c33e |  |
| sm64ds_mario | 16 | 17 | none (0/3 prims) | 452 | undetermined (n=3) | 18.7759 | ea509bdf870190e7 |  |
| mario | 15 | 20 | all (11/11 prims) | 752 | undetermined (n=5) | 600.0059 | 701635400b9c9616 | DUP |
| mario_66062703301f4969 | 15 | 20 | all (11/11 prims) | 752 | undetermined (n=5) | 600.0059 | 701635400b9c9616 | DUP |
| smb3_mario | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| tetris_ds_ct_mario3 | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### super_mario (2 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| tetris_ds_super_mario | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| tetris_ds_super_mario3 | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### luigi (3 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_luigi | 18 | 61 | all (49/49 prims) | 5947 | undetermined (n=34) | 1.5075 | d3e4f5646616cc20 |  |
| luigi_hd | 18 | 21 | all (16/16 prims) | 20684 | undetermined (n=3) | 1.5152 | 1ad0c8aa7dd1c62e |  |
| sm64ds_luigi | 16 | 17 | none (0/3 prims) | 455 | undetermined (n=3) | 19.7703 | b3ccbd7a99c4583e |  |

### peach (4 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_peach | 18 | 114 | all (54/54 prims) | 6344 | undetermined (n=34) | 1.6581 | e4b3079833294893 |  |
| peach_hd | 18 | 28 | all (13/13 prims) | 23992 | undetermined (n=4) | 1.9502 | 29489efddb22125a |  |
| sm64_peach | 18 | 28 | all (10/10 prims) | 776 | undetermined (n=7) | 1.9656 | f174f53b01acf4b5 |  |
| sm64ds_peach | 15 | 21 | none (0/18 prims) | 798 | undetermined (n=18) | 18.3096 | 2437b114788a6a75 |  |

### bowser (4 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_bowser | 18 | 76 | all (53/53 prims) | 6201 | undetermined (n=29) | 5.0914 | 95b0d2c0bac8be8b |  |
| bowser_hd | 18 | 46 | all (24/24 prims) | 42492 | undetermined (n=22) | 5.9739 | 799169bdec1d3997 |  |
| sm64_bowser | 18 | 46 | all (18/18 prims) | 1002 | undetermined (n=16) | 6.3052 | 6a166ed43e1ff160 |  |
| sm64ds_bowser | 15 | 18 | none (0/2 prims) | 975 | undetermined (n=2) | 79.7371 | 96c75a216a9b9ec5 |  |

### gigabowser (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_gigabowser | 18 | 76 | all (76/76 prims) | 5345 | undetermined (n=40) | 4.9398 | 72a0e10bfea53395 |  |

### yoshi (5 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_yoshi | 18 | 70 | all (53/53 prims) | 6082 | undetermined (n=22) | 1.7021 | b5fa4a51a25cf94f |  |
| yoshi_hd | 18 | 25 | all (9/9 prims) | 8407 | undetermined (n=2) | 2.375 | d13740668711d650 |  |
| sm64_yoshi | 18 | 25 | all (7/7 prims) | 676 | undetermined (n=2) | 2.3217 | 42411cb11053a0d9 |  |
| sm64ds_yoshi | 16 | 20 | none (0/3 prims) | 428 | undetermined (n=3) | 19.9471 | 6202bfb4885213cf |  |
| tetris_ds_yoshieye | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

### toad (3 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| toad_hd | 18 | 23 | all (7/7 prims) | 4928 | undetermined (n=1) | 1.2409 | 96adbe873cd1e478 |  |
| sm64_toad | 18 | 23 | all (6/6 prims) | 316 | undetermined (n=2) | 1.1235 | 4559cd02c2290216 |  |
| sm64ds_toad | 6 | 6 | none | 301 | undetermined (n=1) | 12.9219 | 7e591ddd4eb9bc31 |  |

### wario (3 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| wario_hd | 18 | 21 | all (15/15 prims) | 18676 | undetermined (n=3) | 1.4637 | adcd4b1e81595d27 |  |
| sm64ds_wario | 16 | 17 | none (0/3 prims) | 429 | undetermined (n=3) | 26.8108 | 8e8a1886ea5ae36b |  |
| sm64ds_metal_wario | 15 | 16 | none (0/14 prims) | 513 | undetermined (n=14) | 27.9878 | 4253bc03d5ed73f3 |  |

### dr_mario (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| melee_drmario | 18 | 86 | all (55/55 prims) | 5830 | undetermined (n=41) | 1.5116 | 51de14e6b8ef9713 |  |

### big_boo (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sm64ds_big_boo | 3 | 3 | none (0/6 prims) | 204 | undetermined (n=6) | 63.5898 | c5bdec22dcaaf0b9 |  |

### big_bully (1 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sm64ds_big_bully | 3 | 6 | none (0/2 prims) | 130 | undetermined (n=2) | 43.0003 | 9368ac3d91fa9e18 |  |

### other (5 entries)

| slug | roles/23 | joints | normals | tris | largest tex | height (u) | sha256:16 | notes |
|---|---|---|---|---|---|---|---|---|
| sa2_cyclone | 15 | 33 | all (16/16 prims) | 1724 | undetermined (n=16) | 23.5172 | 958b568cfc874227 |  |
| sprite_photo_b7aecee966090bfa_0e0cf249d7 | 0 | 20 | all (10/10 prims) | 752 | undetermined (n=4) | 600.0059 | 614a5b0f2d4c6e12 |  |
| smb3_all_tiles | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sprite_photo_49b6a2f65aca26a2_ad2d4ec25f | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |
| sprite_photo_938e4ca5b120e344_e36151c201 | None | None | None | None | None | None |  | UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p |

## Data quality flags

- Duplicates (identical sha256): `701635400b9c9616…` → mario / mario_66062703301f4969
- Model-pack / non-source-game flags: `bowser_hd`, `luigi_hd`, `mario_hd`, `peach_hd`, `toad_hd`, `wario_hd`, `yoshi_hd`
- meta.stats mismatch vs measured: none — all measured entries match their meta stats
- Measurement failures (16): `s3k_knuckles` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `s3k_sonic` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `s3k_tails` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sk_knuckles` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sk_sonic` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `smb3_all_tiles` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `smb3_mario` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sonic1_shadow` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sonic2_sonic` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sonic2_tails` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sprite_photo_49b6a2f65aca26a2_ad2d4ec25f` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `sprite_photo_938e4ca5b120e344_e36151c201` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `tetris_ds_ct_mario3` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `tetris_ds_super_mario` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `tetris_ds_super_mario3` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p; `tetris_ds_yoshieye` — UnicodeDecodeError: 'utf-32-be' codec can't decode bytes in position 4-7: code p
- Scale anomalies: entries with height > 100 local units (e.g. `mario` / `mario_66062703301f4969` at 600.0, `sm64ds_dorrie` at 163.4) come from non-SSB pipelines — re-scale before any swap.

## Key findings

1. **SSB Melee family is the strongest Mario-side donor block**: `melee_mario/luigi/peach/bowser/yoshi/gigabowser/drmario` — 18/23 roles, 61–114 joints, 100% vertex normals, ~5–6k tris, consistent ~1.5 local-unit height. Humanoid topology compatible with a Mercs rig bind.
2. **`_hd` reworks** (`mario_hd`, `luigi_hd`, `peach_hd`, `bowser_hd`, `toad_hd`, `wario_hd`): 18/23 roles, ~20k tris, all normals — higher-poly alternates for the same characters.
3. **Sonic side**: `sa1_*`/`sa2_*` (gbox.sa1_chars/gbox.sa2_chars + gbox.ninja exports) measured fine with full geometry; `s3k_*`/`sk_*`/`sonic1_*`/`sonic2_*` entries failed GLB measurement with the repo parser — see measurement failures; `sprite_photo_*` and `tetris_ds_*`/`smb3_mario` are sprite/face assets, not 3D donors.
4. Dedupe before use: `mario` ≡ `mario_66062703301f4969` (same sha256).

## Next acceptance step

Operator selects top donors per Mercs character from the shortlist (recommendation: Melee family for Mario humanoids; `sa2_shadow`-class export for Sonic humanoids, with the s3k/sk GLB parser failure fixed first for the s3k block). Then cast_swap recipes (launch:false) with change_id + writer dependencies, then live acceptance on an idle i9-NUC/Spark test session at 2% audio.

_Generated 2026-11-09T20:19:16Z; re-aggregated 2026-11-09T22:47:08Z. Raw evidence: `donor-audit-sonic-mario-2026-11-09.json` (full per-entry measurements, sha256, role lists)._