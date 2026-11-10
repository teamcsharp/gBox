# RE6 Switch: enemy identities settled from the game files (request #9343)

Read-and-report. Source: extracted RomFS `~/gBox_alt/switch/romfs/01002A000CD48000/nativeNXx64/arc/NX/` on lilspark. No game data is copied here; every number below was produced by the repository parsers in a throwaway script (outside `system/gbox`). JSON companion: `re6-switch-enemy-identities.json`.

## Levels

- **verified**: the class archive itself carries the name (an entry spelled `juavo`, `zonbie`, `parachute`).
- **matched**: the game's own creature name (message file) is tied to the class by class-specific content (motions, sounds, textures, embedded models, tip text) but no archive spells the name. This is evidence, not a literal link.
- **not determined**: the files do not decide; the note says what would.

No table in the extracted files linking a `uEmNNNN` id to a message-string index was found (searched: the 34 class archives and all 11 `Msg_*.arc`). That link is what would turn every `matched` into `verified`.

## Method (how each column was obtained)

1. **Candidate classes**: `gbox.mercs.enemy_identity.TABLE[RE6]` entries whose level is not `verified` (34: 21 unconfirmed + 13 inferred).
2. **Archive entries/strings**: `gbox.mt_arc.parse(<class>.arc)`; entry names are the resolved path names of the archive index (motion, sound, effect, texture, model). The same archives were also byte-scanned (zlib-decompressed per entry) for the candidate creature names: no uEm archive contains any of them, so names do not come from the class archives.
3. **Skeleton and height**: `gbox.re6_switch_models.model_entries` + `gbox.mt_model.parse_mod(...).bounds()` on the model named `em<NNNN>` (else the largest skinned model, flagged). MOD files hold bone ids, not names, so "bone names" are **not available**; bone count and the bind-pose bounding box (x,y,z extents; y is the height axis) are reported. Bind-pose size is not a gameplay hitbox.
4. **Stage placements**: `gbox.re6_switch_enemies.stage_census` over `s1200Soft..s1209Soft` (Mercenaries sets, stage names from `re6_stage_greybox.STAGE_NAMES`) and `s1210Soft..s1219Soft` (No Mercy sets): one count per `mUnitClass` row naming the class in the XFS enemy layouts. 0 placements means the class is spawned by script or by mutation of another enemy, not laid out.
5. **Text**: `Msg_eng.arc` -> `soft\message\mes_file_eng` (GMD, UTF-8, NUL-separated). Cited as `string #N` = 0-based index in the NUL-split list. Creature-name list: strings #6297-#6362 (Chrysalid, Glava-Sluz/-Smech/-Begunats/-Dim, Ruka-Srp/-Khvatanje/-Bedem, Noga-Trchanje/-Let/-Skakanje/-Oklop, Telo-Eksplozija/-Krljusht/-Magla, Strelats, Mesets, Napad, Gnezdo, Lepotitsa, Iluzija, Ubistvo, Rasklapanje, ..., Ustanak, Haos, Zombie variants, Bloodshot, Shrieker, Whopper, Whopper Supreme, Zombie Dog C, Brzak, Ogroman). The names are real game strings, so the old guesses were not invented; what was unproven was which class each one is.
6. **Order check**: in the list, Strelats..Gnezdo (4 names) line up 1:1 with uEm3000/3100/3200/3300 and each of Strelats, Napad, Gnezdo has class-specific evidence; Glava-Dim/Ruka-Srp/Ruka-Bedem/Noga-Let/Telo-Eksplozija also line up with smoke/sickle/shield/wing/bomb entries. Order alone is never accepted as a match.

## Result

| class | old guess (level) | new answer | level | model (bones; bbox x,y,z) | placements (Mercenaries / No Mercy) |
|---|---|---|---|---|---|
| uEm1200 | J'avo (Lanshiang) (unconfirmed) | J'avo | verified | 29; [173.3, 182.6, 64.9] | Requiem for War 153; Steel Beast 145 / Requiem for War 298; Steel Beast 286 |
| uEm1370 | J'avo mutant (uEm1370) (unconfirmed) | Chrysalid | matched | 57; [174.5, 187.4, 113.2] | Liquid Fire 3 / Liquid Fire 3 |
| uEm1400 | J'avo (Neo-Umbrella) (inferred) | J'avo | verified | 35; [173.3, 182.2, 115.3] | Creature Workshop 148; Liquid Fire 147 / Creature Workshop 284; Liquid Fire 321 |
| uEm2010 | J'avo mutation (head) (unconfirmed) | not determined | not determined | 42; [120.0, 124.3, 53.0] | - / - |
| uEm2030 | J'avo mutation (head) (unconfirmed) | Glava-Dim | matched | 27; [148.7, 71.9, 125.9] | - / - |
| uEm2100 | J'avo mutation (arm) (unconfirmed) | Ruka-Srp | matched | 16; [509.1, 69.9, 29.3] | - / - |
| uEm2120 | J'avo mutation (arm) (unconfirmed) | Ruka-Khvatanje | matched | 63; [813.4, 59.3, 60.9] | - / - |
| uEm2140 | J'avo mutation (arm) (unconfirmed) | Ruka-Bedem | matched | 37; [308.9, 61.7, 117.9] | - / - |
| uEm2200 | J'avo mutation (legs) (unconfirmed) | Noga-Trchanje | matched | 32; [330.0, 178.5, 73.1] | - / - |
| uEm2210 | J'avo mutation (legs) (unconfirmed) | Noga-Let | matched | 43; [375.2, 307.1, 205.4] | - / - |
| uEm2230 | J'avo mutation (legs) (unconfirmed) | not determined | not determined | 12; [75.3, 135.2, 42.4] | - / - |
| uEm2300 | Chrysalid (inferred) | Telo-Eksplozija | matched | 17; [102.8, 137.4, 111.8] | - / - |
| uEm3000 | Strelats (unconfirmed) | Strelats | matched | 83; [321.5, 229.7, 234.1] | Mining the Depths 1; The Catacombs 1 / Mining the Depths 3; The Catacombs 2 |
| uEm3100 | Mesets (unconfirmed) | Mesets | matched | 64; [457.1, 145.4, 199.3] | Liquid Fire 3 / Liquid Fire 6 |
| uEm3200 | Napad (unconfirmed) | Napad | matched | 41; [321.5, 219.0, 125.5] | Urban Chaos 1; Steel Beast 7; Rooftop Mission 1; Creature Workshop 8; Liquid Fire 1 / Rail Yard 6; Urban Chaos 3; High Seas Fortress 4; Steel Beast 20; Rooftop Mission 6; Creature Workshop 5; Liquid Fire 4 |
| uEm3300 | Gnezdo (inferred) | Gnezdo | matched | 23; [1.7, 4.3, 4.5] | Requiem for War 1; High Seas Fortress 1; Steel Beast 1 / Requiem for War 1; High Seas Fortress 1; Steel Beast 1 |
| uEm3301 | J'avo mutant (em1370 body) (unconfirmed) | Gnezdo | matched | 57; [174.5, 187.4, 113.2] | - / - |
| uEm3320 | Gnezdo (core) (unconfirmed) | not determined | not determined | 13; [40.0, 56.9, 51.8] | - / - |
| uEm4100 | Lepotitsa (unconfirmed) | not determined | not determined | 90; [198.6, 181.1, 58.5] | The Catacombs 2 / The Catacombs 3 |
| uEm4300 | Ubistvo (unconfirmed) | Ubistvo | matched | 56; [262.3, 195.5, 96.9] | Rail Yard 1; Rooftop Mission 3; Creature Workshop 1 / Rail Yard 2; Rooftop Mission 5; Creature Workshop 1 |
| uEm4700 | Rasklapanje (inferred) | Rasklapanje | matched | 83; [282.9, 225.4, 159.2] | Liquid Fire 2 / Liquid Fire 3 |
| uEm4701 | Rasklapanje (torso) (inferred) | Rasklapanje (torso part) | matched | 72; [282.9, 94.8, 159.2] | - / - |
| uEm4710 | Rasklapanje (hand) (inferred) | Rasklapanje (hand part) | matched | 25; [18.7, 16.0, 89.5] | - / - |
| uEm4800 | Ogroman (unconfirmed) | Ogroman | matched | 77; [1495.6, 1105.7, 568.3] | Requiem for War 2 / Requiem for War 3 |
| uEm5000 | Zombie (Mining the Depths) (unconfirmed) | Zombie | matched | 25; [171.8, 182.2, 44.0] | Mining the Depths 77; Rooftop Mission 23 / Mining the Depths 159; Rooftop Mission 46 |
| uEm5050 | Zombie (miner) (inferred) | Zombie | matched | 26; [173.3, 183.5, 56.3] | Urban Chaos 17; Rooftop Mission 24 / Urban Chaos 34; Rooftop Mission 72 |
| uEm5060 | Zombie (miner) (inferred) | Zombie | matched | 26; [173.3, 183.5, 56.3] | Mining the Depths 27 / Mining the Depths 54 |
| uEm5181 | Zombie (police) (inferred) | Zombie | matched | 27; [171.7, 183.9, 43.1] | Urban Chaos 19 / Urban Chaos 68 |
| uEm5191 | Zombie (firefighter) (inferred) | Zombie | matched | 27; [173.6, 184.1, 55.7] | Urban Chaos 23; Mining the Depths 19; Rooftop Mission 22 / Urban Chaos 46; Mining the Depths 38; Rooftop Mission 46 |
| uEm5400 | Zombie (The Catacombs) (unconfirmed) | Zombie | verified | 25; [169.9, 180.9, 41.9] | The Catacombs 148 / The Catacombs 307 |
| uEm5500 | Zombie special (uEm5500) (unconfirmed) | Shrieker | matched | 33; [167.9, 193.7, 77.1] | Mining the Depths 4 / Mining the Depths 7 |
| uEm5600 | Whopper (inferred) | Whopper | matched | 36; [171.6, 181.9, 82.0] | Urban Chaos 3; The Catacombs 2; Rooftop Mission 7 / Urban Chaos 11; The Catacombs 4; Rooftop Mission 14 |
| uEm5700 | Zombie Dog (inferred) | Zombie Dog C | matched | 41; [32.0, 124.1, 142.4] | Urban Chaos 20; Mining the Depths 26; Rooftop Mission 18 / Urban Chaos 40; Mining the Depths 52; Rooftop Mission 18 |
| uEm9906 | Parachute (inferred) | Parachute | verified | 22; [768.6, 1127.0, 720.0] | - / - |

## Evidence per class

### uEm1200: J'avo (verified); was J'avo (Lanshiang) (unconfirmed)
- `uEm1200.arc` / `data\chara\textures\JvUpper_damage_CH_BM`: texture named "jvupper"/"jveye"/"jvpants" = J('a)v(o) body parts
- `uEm1200.arc` / `sound\se\em\em1200\source\em1200_juavo_mask_break`: entry carries the romanised name "juavo"
- NOTE: qualifier '(Lanshiang)' not determined: no entry or string ties this class to a campaign; stage placement only (s1201/s1206 in the Mercenaries set).

### uEm1370: Chrysalid (matched); was J'avo mutant (uEm1370) (unconfirmed)
- `uEm1370.arc` / `data\chara\em\em1370\model\em1370_mayu_NM (+3 similar)`: "mayu" = cocoon (Japanese) texture of this class
- `uEm1370.arc` / `sound\se\em\em1370\source\em1370_kneedown_after_pupa (+2 similar)`: motion "crunchy_mvmt_after_pupa" = pupa stage
- `uEm1370.arc` / `sound\se\em\em1370\source\em1370_hukurami_start`: "hukurami" = swelling, cocoon start
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6297: "Chrysalid")`: game name for the cocoon stage (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6911: "Hatching Chrysalids")`: Agent Hunt tutorial title: Strelats/Napad/Gnezdo hatch from Chrysalids
- NOTE: Name is matched by meaning (cocoon/pupa motions + the Chrysalid string), not by a literal 'chrysalid' entry. uEm3000/3100/3200/3300 each embed the same 57-bone em1370 model (the pupa body) and carry 'pupa' sound cues.

### uEm1400: J'avo (verified); was J'avo (Neo-Umbrella) (inferred)
- `uEm1400.arc` / `sound\se\em\em1400\source\em1400_juavo_mask_break`: entry carries the romanised name "juavo"
- `uEm1400.arc` / `data\chara\em\em1400\model\em1400_head3_NM (+2 similar)`: extra head variants (head2/head3) over the same 35-bone body
- NOTE: qualifier '(Neo-Umbrella)' not determined: the message file has a separate "Neo-Umbrella J'avo Controls" string but nothing links it to uEm1400 vs uEm1200.

### uEm2010: not determined (not determined); was J'avo mutation (head) (unconfirmed)
- `uEm2010.arc` / `sound\se\em\em2010\source\em2010_hasami_mvmt01 (+1 similar)`: "hasami" = scissors/shears
- `uEm2010.arc` / `data\chara\em\em2010\model\em2010_20_headE_MM`: head-only model
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6299: "Glava-Smech")`: candidate by list position only (creature-name list, strings #6297-6362)
- NOTE: Head-mutation family is established (head-only model, y 97..221). Which of Glava-Sluz / -Smech / -Begunats it is rests on list order alone (uEm2000 carries 'salivaattack'/'stickyprojectile' = Sluz, uEm2030 'smoke_attack' = Dim, leaving Smech/Begunats for 2010/2020). Would be settled by a table linking uEm id to a message string index (EXE or a Core table), or by a kill-count/medal script naming the class.

### uEm2030: Glava-Dim (matched); was J'avo mutation (head) (unconfirmed)
- `uEm2030.arc` / `sound\se\em\em2030\source\em2030_smoke_attack`: motion/sound "smoke_attack" = smoke head attack
- `uEm2030.arc` / `sound\se\em\em2030\source\em2030_mutation_a`: "mutation_a/b" = J'avo mutates into this head type
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6301: "Glava-Dim")`: "Dim" = smoke (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #4895: "Kill 30 Glava-Dims.")`: kill medal

### uEm2100: Ruka-Srp (matched); was J'avo mutation (arm) (unconfirmed)
- `uEm2100.arc` / `soft\chara\em\em1000\motsoft\em1000_gkama`: "kama" = sickle (Japanese)
- `uEm2100.arc` / `sound\se\em\em2100\source\em2100_atk_before_arm01`: arm motions
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6302: "Ruka-Srp")`: "Srp" = sickle (creature-name list, strings #6297-6362)
- NOTE: Name matched by the sickle meaning (Serbian srp = Japanese kama) and list position; not a literal link.

### uEm2120: Ruka-Khvatanje (matched); was J'avo mutation (arm) (unconfirmed)
- `uEm2120.arc` / `sound\se\em\em2120\source\em2120_punch_a (+5 similar)`: arm punch/grab motions
- `uEm2120.arc` / `sound\se\em\em2120\source\em2120_attack_graund_impact`: ground motion
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6303: "Ruka-Khvatanje")`: "Khvatanje" = grabbing (creature-name list, strings #6297-6362)
- NOTE: Matched by elimination: the three arm names are Srp (uEm2100, sickle), Khvatanje, Bedem (uEm2140, shield); this is the remaining arm-type class (63 bones, 813 wide). Also embedded with em2100 inside uEm1370.arc.

### uEm2140: Ruka-Bedem (matched); was J'avo mutation (arm) (unconfirmed)
- `uEm2140.arc` / `data\chara\em\em2140\model\em2140_21_shield_NM (+3 similar)`: "shield" entry
- `uEm2140.arc` / `sound\se\em\em2140\source\em2140_guard_on`: "guard" entry
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6304: "Ruka-Bedem")`: "Bedem" = rampart/bulwark (creature-name list, strings #6297-6362)

### uEm2200: Noga-Trchanje (matched); was J'avo mutation (legs) (unconfirmed)
- `uEm2200.arc` / `sound\se\em\em2200\source\em2200_run_mvmt01 (+2 similar)`: "run" motion (the only leg class with one)
- `uEm2200.arc` / `sound\se\em\em2200\source\em2200_prejump_foley`: "prejump" motion also present
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6305: "Noga-Trchanje")`: "Trchanje" = running (creature-name list, strings #6297-6362)
- NOTE: Weaker than the others: uEm2200 carries both run and prejump motions; the run entry decides it.

### uEm2210: Noga-Let (matched); was J'avo mutation (legs) (unconfirmed)
- `uEm2210.arc` / `sound\se\em\em2210\source\em2210_wingborn_mvmt01 (+2 similar)`: "wingborn" = wings appear
- `uEm2210.arc` / `sound\se\em\em2210\source\em2210_wingmove_small01 (+7 similar)`: wing movement
- `uEm2210.arc` / `sound\se\em\em2210\source\em2210_bodycatch`: body-catch (grab) motion
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6306: "Noga-Let")`: "Let" = flight (creature-name list, strings #6297-6362)

### uEm2230: not determined (not determined); was J'avo mutation (legs) (unconfirmed)
- `uEm2230.arc` / `data\chara\em\em2230\model\em2230_22_film_NM (+2 similar)`: entry "film"
- `uEm2230.arc` / `data\chara\em\em2230\model\em2230_21_Leg_NM (+3 similar)`: "leg" entry
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6308: "Noga-Oklop")`: candidate by list position only (creature-name list, strings #6297-6362)
- NOTE: Leg family only (token "leg", 12 bones, 133 high). Skakanje vs Oklop undecided: no jump or armour entry; position alone is not accepted. Would be settled by the uEm id to message-string link.

### uEm2300: Telo-Eksplozija (matched); was Chrysalid (inferred)
- `uEm2300.arc` / `data\chara\em\em2300\model\em2300_00_bomb01_NM (+2 similar)`: "bomb" sound
- `uEm2300.arc` / `sound\se\em\em2300\source\em2300_exp (+5 similar)`: explosion effect
- `uEm2300.arc` / `data\chara\em\em2300\model\em2300_00_maku00_NM (+2 similar)`: "maku" = membrane
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6309: "Telo-Eksplozija")`: "Eksplozija" = explosion (creature-name list, strings #6297-6362)
- NOTE: The old guess "Chrysalid" is not supported here: the cocoon evidence belongs to uEm1370.

### uEm3000: Strelats (matched); was Strelats (unconfirmed)
- `uEm3000.arc` / `sound\se\em\em3000\source\EM_3000_OM_mv_M_NIIDLE1`: needle attack
- `uEm3000.arc` / `sound\se\em\em3000\source\em3000_large_needle_shot`: needle
- `uEm3000.arc` / `sound\se\em\em3000\source\EM_3000_OM_mv_M_gero`: "gero" = vomit
- `uEm3000.arc` / `sound\se\em\em1370\snd_em1370_body (+1 similar)`: embeds the em1370 pupa body
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6312: "Strelats")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #7073: "Strelats doesn't like martial arts.")`: tip text
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5799: "Mutated into a Strelats.")`: hatches from a Chrysalid
- NOTE: Matched by needle-attack entries (Strelats = shooter) and the 3000..3300 order 1:1 with Strelats, Mesets, Napad, Gnezdo.

### uEm3100: Mesets (matched); was Mesets (unconfirmed)
- `uEm3100.arc` / `sound\se\em\em3100\source\em3100_mv_glide_main (+3 similar)`: glide
- `uEm3100.arc` / `sound\se\em\em3100\source\em3100_v_aatack_hovering1`: hovering
- `uEm3100.arc` / `sound\se\em\em3100\source\em3100_v_tf_hitceiling`: hits ceiling
- `uEm3100.arc` / `sound\se\em\em3100\source\em3100_v_pupaborn_1 (+1 similar)`: born from pupa
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6313: "Mesets")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5800: "Played as Mesets.")`: Agent Hunt
- NOTE: Matched mostly by the 4-class/4-name block (3000..3300 vs Strelats..Gnezdo) with 3000, 3200 and 3300 each evidenced; its flying motions are class-specific.

### uEm3200: Napad (matched); was Napad (unconfirmed)
- `uEm3200.arc` / `sound\se\em\em3200\source\em3200_se_imp_shell_1 (+2 similar)`: "shell" entry (back shell)
- `uEm3200.arc` / `sound\se\em\em3200\source\em3200_attack_charge`: charge attack
- `uEm3200.arc` / `sound\se\em\em3200\source\em3200_palm1`: palm strike
- `uEm3200.arc` / `sound\se\em\em3200\source\em3200_mv_neckhung (+3 similar)`: neck-hang grab
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6314: "Napad")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #7072: "A Napad's weak point is inside the shell on its back.")`: tip text
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #7101: "Napad's scare tactics restore its stamina.")`: tip text
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5801: "Mutated into a Napad.")`: hatches from a Chrysalid

### uEm3300: Gnezdo (matched); was Gnezdo (inferred)
- `uEm3300.arc` / `sound\se\em\em3300\source\EM_3300_OM_mv_M_swarm_up (+8 similar)`: swarm
- `uEm3300.arc` / `sound\se\em\em3300\source\EM_3300_OM_mv_M_bee_loop1 (+6 similar)`: bee
- `uEm3300.arc` / `sound\se\em\em3300\source\EM_3300_OM_mv_M_pl_bitten1`: bitten
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6315: "Gnezdo")`: "Gnezdo" = nest (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5802: "Mutated into a Gnezdo.")`: hatches from a Chrysalid
- NOTE: Model is a ~3-unit point (bbox +-2): an insect swarm, consistent with "nest".

### uEm3301: Gnezdo (matched); was J'avo mutant (em1370 body) (unconfirmed)
- `uEm3301.arc` / `sound\se\em\em3300\source\EM_3300_OM_mv_M_swarm_up (+8 similar)`: swarm
- `uEm3301.arc` / `sound\se\em\em3300\source\EM_3300_OM_mv_M_bee_loop1 (+6 similar)`: bee
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6315: "Gnezdo")`: name (creature-name list, strings #6297-6362)
- NOTE: uEm3301.arc is byte-identical to uEm3300.arc (same SHA-1, 282 entries): the same enemy; the old "J'avo mutant (em1370 body)" guess only reflected the embedded pupa model.

### uEm3320: not determined (not determined); was Gnezdo (core) (unconfirmed)
- `uEm3320.arc` / `sound\se\em\em3320\source\VO\em3320_vox_appear`: only distinctive entry
- NOTE: 13-bone, 40x57x52 model, 81 entries, no name/motion cue, never placed. Would be settled by the parent class that spawns it (stage scripts or the em3300 FSM).

### uEm4100: not determined (not determined); was Lepotitsa (unconfirmed)
- `uEm4100.arc` / `sound\se\em\em4100\source\EM_4100_OM_mv_M_tongue_1`: tongue attack
- `uEm4100.arc` / `sound\se\em\em4100\source\em4100_gas01_FOLEY (+2 similar)`: gas
- `uEm4100.arc` / `sound\se\em\em4100\source\em4100_grip01`: grip
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6316: "Lepotitsa")`: candidate by list position only (creature-name list, strings #6297-6362)
- NOTE: Tongue-grab/gas creature (90 bones) is established; that it is Lepotitsa rests on list order only (Lepotitsa follows Gnezdo; uEm4500 carries "eyelash"/"hair" textures, a rival candidate). Would be settled by the uEm id to message-string link.

### uEm4300: Ubistvo (matched); was Ubistvo (unconfirmed)
- `uEm4300.arc` / `sound\se\em\em4300\source\em4300_chainsaw_loop (+11 similar)`: chainsaw
- `uEm4300.arc` / `sound\se\em\em4300\source\EM_4300_OM_mv_M_stab_a (+6 similar)`: stab
- `uEm4300.arc` / `data\chara\em\em4300\model\em4300_20_larva_OM (+3 similar)`: larva
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6318: "Ubistvo")`: "Ubistvo" = murder (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6773: "Ubistvo on the Attack")`: event title
- NOTE: Matched by the chainsaw weapon entries; the name itself is not in the archive.

### uEm4700: Rasklapanje (matched); was Rasklapanje (inferred)
- `uEm4700.arc` / `sound\se\em\em4700\source\VO\EM_4700_OM_vox_M_A010_COMBINE1`: recombine
- `uEm4700.arc` / `sound\se\em\em4700\source\VO\EM_4700_OM_vox_M_A030_RIPARM_OUCH (+1 similar)`: rip arm off
- `uEm4700.arc` / `sound\se\em\em4700\source\VO\em4700_vox_armthrow`: arm throw
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6319: "Rasklapanje")`: "Rasklapanje" = disassembly (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5794: "Played as a Rasklapanje.")`: Agent Hunt playable

### uEm4701: Rasklapanje (torso part) (matched); was Rasklapanje (torso) (inferred)
- `uEm4701.arc` / `sound\se\em\em4700\source\VO\EM_4700_OM_vox_M_A010_COMBINE1`: recombine
- `uEm4701.arc` / `sound\se\em\em4700\source\VO\EM_4700_OM_vox_M_A030_RIPARM_OUCH (+1 similar)`: rip arm off
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6319: "Rasklapanje")`: name (creature-name list, strings #6297-6362)
- NOTE: Shares 220 identical entries with uEm4700; its model is the torso (y>=130).

### uEm4710: Rasklapanje (hand part) (matched); was Rasklapanje (hand) (inferred)
- `uEm4710.arc` / `soft\chara\em\em4710\em4710 (+12 similar)`: hand model
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6319: "Rasklapanje")`: name (creature-name list, strings #6297-6362)
- NOTE: 25-bone 19x16x90 model; part of the Rasklapanje body (shares the em4700 texture entries md00f3/md00b4).

### uEm4800: Ogroman (matched); was Ogroman (unconfirmed)
- `uEm4800.arc` / `data\chara\em\em4800\model\em4801 (+15 similar)`: child model em4801
- `uEm4800.arc` / `data\chara\em\em4802\model\em4802 (+5 similar)`: child model em4802
- `uEm4800.arc` / `data\chara\em\em4800\model\em4800_02core_NM (+10 similar)`: core entry
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6362: "Ogroman")`: "Ogroman" = huge (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #5974: "Sent a Ogroman over to your opponent's area.")`: Ogroman is a sendable enemy
- NOTE: Matched by size (model 1102 high, 1496 wide, the largest enemy) and the 77/77/51-bone parts; the name is not in the archive.

### uEm5000: Zombie (matched); was Zombie (Mining the Depths) (unconfirmed)
- `uEm5000.arc` / `data\chara\em\em5100\model\em5100_00_Jeans_NM (+2 similar)`: civilian clothing
- `uEm5000.arc` / `data\chara\em\em5000\model\em5000_23_Tshirts_NM (+2 similar)`: civilian clothing
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- NOTE: Same 25-bone, 182-high skeleton as the verified uEm5200/5210 Zombie family.

### uEm5050: Zombie (matched); was Zombie (miner) (inferred)
- `uEm5050.arc` / `data\chara\em\em5900\model\em5900_05armor_NM (+2 similar)`: armour
- `uEm5050.arc` / `data\chara\em\em5050\model\em9300_07Helm_NM (+2 similar)`: helmet
- `uEm5050.arc` / `data\chara\em\em5900\model\em5900_15eqb_NM (+2 similar)`: equipment
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6351: "Zombie - Helmet")`: equipment variants exist
- NOTE: Variant labels 'miner' not determined: no mining entry.

### uEm5060: Zombie (matched); was Zombie (miner) (inferred)
- `uEm5060.arc` / `data\chara\em\em5900\model\em5900_05armor_NM (+2 similar)`: armour
- `uEm5060.arc` / `data\chara\em\em5050\model\em9300_07Helm_NM (+2 similar)`: helmet
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- NOTE: Variant label not determined.

### uEm5181: Zombie (matched); was Zombie (police) (inferred)
- `uEm5181.arc` / `data\chara\em\em5180\model\em5180_26_cap_NM (+3 similar)`: cap
- `uEm5181.arc` / `data\chara\em\em5180\model\em5180_25_Pouch_NM (+2 similar)`: pouch
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- NOTE: Variant label 'police' not determined.

### uEm5191: Zombie (matched); was Zombie (firefighter) (inferred)
- `uEm5191.arc` / `data\chara\em\em5191\model\em5191_03_Helmet_NM (+5 similar)`: helmet
- `uEm5191.arc` / `data\chara\em\em5191\model\em5191_05_glove_NM (+2 similar)`: glove
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6351: "Zombie - Helmet")`: a helmet variant exists
- NOTE: Variant label 'firefighter' not determined.

### uEm5400: Zombie (verified); was Zombie (The Catacombs) (unconfirmed)
- `uEm5400.arc` / `sound\se\wp\source\wp1240\wp1240_zonbie_eat_dynamite`: entry spells the name "zonbie"
- `uEm5400.arc` / `sound\se\wp\source\wp1240\wp1240_zonbie_eat_dynamite`: dynamite
- `uEm5400.arc` / `sound\se\wp\source\wp1240\wp1240_doukasen_loop`: "doukasen" = fuse
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6330: "Zombie")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6350: "Zombie - Dynamite")`: dynamite variant exists
- NOTE: The texture 'bloodshot' (eyes) is a texture name, not the Bloodshot creature.

### uEm5500: Shrieker (matched); was Zombie special (uEm5500) (unconfirmed)
- `uEm5500.arc` / `soft\chara\em\em5000\motsoft\em5000_shr`: abbreviation "shr"
- `uEm5500.arc` / `sound\se\em\em5500\source\VO\em5500_v_scream_power_on`: scream
- `uEm5500.arc` / `sound\se\em\em5500\source\em5500_scream_se_L`: scream sound
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6357: "Shrieker")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #7056: "A Shrieker's weak point is its throat.")`: tip text
- NOTE: Matched by scream entries and "_shr" donor texture; 33 bones, 193.5 high.

### uEm5600: Whopper (matched); was Whopper (inferred)
- `uEm5600.arc` / `sound\se\em\em5600\source\EM_5600_OM_mv_M_bonebreak_a (+2 similar)`: bone-break sound
- `uEm5600.arc` / `sound\se\em\em5600\source\EM_5600_OM_mv_M_eat_a`: eat
- `uEm5600.arc` / `sound\se\em\em5600\source\EM_5600_OM_mv_M_com_imp_l`: large-impact (heavy)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6358: "Whopper")`: name (creature-name list, strings #6297-6362)
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #7057: "A Whopper can't hurt you if it can't use its legs.")`: tip text
- NOTE: Position between Shrieker (5500) and the dog (5700) in the creature list; no literal.

### uEm5700: Zombie Dog C (matched); was Zombie Dog (inferred)
- `uEm5700.arc` / `sound\se\em\em5700\source\EM_5700_OM_vox_M_bark1`: bark
- `uEm5700.arc` / `sound\se\em\em5700\source\EM_5700_OM_vox_M_bite1`: bite
- `uEm5700.arc` / `sound\se\em\em5700\source\EM_5700_OM_vox_M_growl1`: growl
- `Msg_eng.arc` / `soft\message\mes_file_eng (GMD, NUL-split string #6360: "Zombie Dog C")`: name (creature-name list, strings #6297-6362)
- NOTE: Quadruped proportions (low, long bind-pose bbox; see the measured row).

### uEm9906: Parachute (verified); was Parachute (inferred)
- `uEm9906.arc` / `data\chara\sm\sm5051\model\sm5051_Parachute_NM (+4 similar)`: entry named "parachute"
- `uEm9906.arc` / `data\chara\sm\sm5051\model\sm5051 (+6 similar)`: sm5051 model
- NOTE: A prop, not a creature: 22-bone canopy 768 wide x 1124 high.

## Corrections to the old table

- uEm2300 was "Chrysalid": the cocoon evidence (mayu, pupa, crunchy) is in uEm1370; uEm2300 is Telo-Eksplozija (bomb/exp entries).
- uEm3301 is a byte-identical copy of uEm3300 (Gnezdo), not a J'avo mutant.
- uEm2200/2210 were both "legs" guesses; uEm2210 is the winged Noga-Let, uEm2200 the running Noga-Trchanje (weaker, see note).
- uEm5500 is Shrieker-like (scream entries, `_shr` donor), not "Zombie special"; uEm5050/5060/5181/5191 variant labels (miner/police/firefighter) are not supported by any entry.
- Tiers are not in the files: nothing here settles "boss"/"dangerous"; that remains the table's own judgement.

## Not determined, and what would settle it

- uEm2010: Head-mutation family is established (head-only model, y 97..221). Which of Glava-Sluz / -Smech / -Begunats it is rests on list order alone (uEm2000 carries 'salivaattack'/'stickyprojectile' = Sluz, uEm2030 'smoke_attack' = Dim, leaving Smech/Begunats for 2010/2020). Would be settled by a table linking uEm id to a message string index (EXE or a Core table), or by a kill-count/medal script naming the class.
- uEm2230: Leg family only (token "leg", 12 bones, 133 high). Skakanje vs Oklop undecided: no jump or armour entry; position alone is not accepted. Would be settled by the uEm id to message-string link.
- uEm3320: 13-bone, 40x57x52 model, 81 entries, no name/motion cue, never placed. Would be settled by the parent class that spawns it (stage scripts or the em3300 FSM).
- uEm4100: Tongue-grab/gas creature (90 bones) is established; that it is Lepotitsa rests on list order only (Lepotitsa follows Gnezdo; uEm4500 carries "eyelash"/"hair" textures, a rival candidate). Would be settled by the uEm id to message-string link.
