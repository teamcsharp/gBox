# Mercenaries diagnostics, 2026-10-26 (RE5 PS3 BLUS30491 and RE4 GameCube G4BE08)

Every round since 10:00 Spark time (CST) up to about 16:45: 44 RE5 round maps (131 min of play), 704 RE5 damage events from the player-damage ledger (to 16:21), and 15 RE4 round maps (45 min) plus the RE4 learned maps and stuck logs. Numbers only; the method and its limits are at the end. The tables below cover 10:00-16:20 (42 RE5 and 10 RE4 maps); the rounds after the 16:13 restart are in their own section.

## Summary

1. **RE5: the laser sight was lost in busy rounds, and then a garbage ray steered the aim.** The same gun was "laserless" for 2 % of its gun-up time in one round and 100 % in the next (VZ61 7 % / 100 %, S&W M29 2 % / 67 %, Lightning Hawk 1 % / 76 %). The cause is in `re5_ps3.laser()`: it walked at most 64 units of the FX line, which grows through a round. When the walk ran out on a valid unit that was not the laser, it cached that unit and returned its fields as the ray. "No ray at the trigger" was the #2 miss cause (163 misses), and after the 16:13 restart the bot hit 1 of 25 shots (Missile Area 16:31: 1/18, 76 % laserless; Prison 16:36: 0/7, 96 %).
2. **RE5: the gun-down swing is where the damage happens.** 184 of 387 damage incidents (48 %, 44 % of the HP lost) began while the combat line said "swinging round to him (gun down)". 82 % of incidents had a Majini within 1.5 m, and the nearest Majini was beside or behind the player in 57 % of them (pre-hit facing). Across all rounds the bot spent 1639.5 s of 4660.5 s of fighting (35 %) turning with the gun down. After 16:13, with no laser read, it was 100 s of 157 s (hit 5 of 6 times) and 50 s of 69 s.
3. **RE5 hit rate 42 %** (462 of 1102 resolved shots). The close-threat blast hit 36 % of its 500 shots. Top miss causes: "dot off him" 235, "no ray at the trigger" 163, "wild error" 84, "gun down / turning" 68. Shots fired during a swing hit 15 %.
4. **RE5: a First Aid Spray in hand is fought as a shotgun.** 69 damage events (29 incidents) happened with item 0x304 in hand, 62 of them in clear_nearby. The spray's inventory record is {id 0x304, type 3, item 4}. The combat layer reads `item` 4 as the Ithaca M37 shotgun, so it aims and "fires" the spray: 85 shot rows today carry weapon 4 across 11 characters, and "0x4 Ithaca M37" hit 13 % of 45 shots.
5. **RE5 deaths (30):** 23 had a heal deferred, 24 had 3+ Majini within 5 m, 20 took the dying blow during a gun-down swing, and 17 still had a recovery item in the inventory. The trigger was down less than 20 % of the last 10 s in 26. 14 began their last 10 s at 1-3 HP (8 at exactly 1 HP, where `Bot._heal` does nothing), so the decisive moment was usually the earlier deferred heal. The heal was deferred down to 15 % of health, but 91 % of hits take 84-196 HP, so one more hit killed.
6. **RE5 laserless controller:** 188 damage events (19 % of HP) happened under the laserless path, mostly Sheva (Tribal)'s longbow and Chris (Warrior)'s Lightning Hawk. Apart from the longbow, these are laser guns caught by finding 1. That path holds the trigger until the camera aim is within 6 deg (yaw) / 7 deg (pitch), and at point blank the yaw limit still applies. The RE5 loadout never hands out a rifle (`re5_mods_tool.replace_long_guns` turns rockets and rifles into magnums), and Sheva (Tribal) carries no laser gun at all (longbow, grenade launcher, grenades).
7. **RE4: no gun in his hands for whole rounds.** 13:00 r400 and, right after the 16:13 restart (#1215, fire_x 80), three rounds in a row: 16:21 r400, 16:24 r400 and 16:27 r402 read "item 0x800" all round. That gave 0 shots and 25 + 38 hits taken. Nothing read the loadout back in the round. When the gun was there, presses capped it at ~6 shots a second whatever its x80 class interval: 174 shots in 28.7 min to 16:20 (6.1 a minute).
8. **RE4: the character never changed after a death.** On "You Are Dead" the in-round tick pressed A, which is Continue = Yes: the same stage and the same character. The menus' own "No, back to Select Player, draw a new character" step never got the screen. Round reports name the character on 6 of 25 RE4 rounds since 12:18 (Leon, Krauser, Wesker, Wesker, Wesker, HUNK); the rest are "Unknown" (the bot started inside the round after a separate menu walk).
9. **RE4 damage:** 80 of 131 hits (61 %) were Ganado swings. 66 of the 131 landed while he stood aiming or firing (35 on target, 31 still aiming at the head band) and 26 while he ran out of an attack. 29 hits (22 %) named an attacker that cannot have landed (over 3 m away or over 2 s from landing).
10. **RE4 navigation (units are mm):** 5.5 stuck events a minute in the round maps. 24 % of today's 750 stucks (r402 55 %) had the goal behind him: he was turning on the spot and the stuck test counted it. Each false stuck pressed A (vault), then a detour: 0.8 s of running with the stick held left or right, which is the "running and then veering off to the right into a wall" the operator saw. The learned maps held 2466 effective walls, 850 of them in 40 cm cells he had walked (r400: 524 of 1814, block counts up to 3777). The per-tick ray fan wrote the disc's walls into the learned grid, and runs took detours round that floor. r402 Castle and r403 Base have no navmap at all (straight runs at targets, no line of sight for shots).
11. **Round maps file a round under the previous room:** the 16:03 "r403" RE4 map is r404 (386 of 386 samples outside r403's bounds), so its chainsaw death is a Waterworld death.

## Rounds after the 16:13 restart

| round (Spark time) | title / room | s | shots | hits | hits taken | weapon in hand | note |
|---|---|---|---|---|---|---|---|
| 16:13 | RE4 r400 | 396 | 50 | 31 | 15 | Handcannon | 9.7 stucks a minute, 117 s standing still; died to a swing at 1054 mm |
| 16:21 | RE4 r400 | 136 | 0 | 0 | 15 | item 0x800 (none) | no gun all round |
| 16:24 | RE4 r400 | 138 | 0 | 0 | 5 | item 0x800 (none) | no gun all round |
| 16:27 | RE4 r402 | 153 | 0 | 0 | 18 | item 0x800 (none) | no gun all round (no navmap) |
| 16:31 | RE5 Missile Area | 199 | 18 | 1 | 6 | Lightning Hawk | 76 % of gun-up time without a laser ray; 100 s of 157 s fighting turning gun-down |
| 16:36 | RE5 Prison | 90 | 7 | 0 | 1 | AK-74 | 96 % without a laser ray; 50 s of 69 s gun-down |
| 16:43 | RE4 r400 | 126 | 8 | 4 | 7 | Handcannon | died to a swing at 628 mm |

## RE5 ballistics

1108 shots over the 42 rounds: 462 hits, 640 misses, hit rate 42 %. Exact shot records (PR #1210) exist for the 8 rounds since 15:38 (114 shots, 39 %); the other 34 rounds use the run lessons' shot rows joined with the 0.25 s state samples (994 shots, 42 %). 190 longbow firing observations are not shots with a known outcome and are left out. No RE5 round started after 16:13, so the front-first targeting (#1212) is not in this data; 15:39 onwards (quick turn live) has 116 shots, 39 % (before: 992 shots, 42 %).

By distance (ground distance at the trigger; '?' = no distance in the record):

| distance (m) | shots | hits | misses | hit rate |
|---|---|---|---|---|
| 0-2 | 479 | 218 | 261 | 46 % |
| 2-5 | 301 | 128 | 173 | 42 % |
| 5-10 | 101 | 53 | 48 | 52 % |
| 10-20 | 10 | 3 | 7 | 30 % |
| ? | 217 | 60 | 151 | 28 % |

By weapon:

| weapon | shots | hits | misses | hit rate |
|---|---|---|---|---|
| 0xb S&W M29 | 249 | 108 | 141 | 43 % |
| 0x1a Lightning Hawk | 148 | 59 | 89 | 40 % |
| 0x16 Benelli M3 | 121 | 71 | 50 | 59 % |
| 0x15 Gatling gun | 119 | 36 | 83 | 30 % |
| 0x3 VZ61 | 97 | 41 | 56 | 42 % |
| 0x1b S&W M500 | 90 | 46 | 44 | 51 % |
| 0x1d AK-74 | 69 | 30 | 39 | 44 % |
| 0x9 SIG 556 | 65 | 29 | 36 | 45 % |
| 0x4 Ithaca M37 | 45 | 6 | 39 | 13 % |
| 0x2 M92F | 29 | 9 | 20 | 31 % |
| 0x10 H&K P8 | 28 | 11 | 17 | 39 % |
| 0x19 Hydra | 19 | 11 | 8 | 58 % |

By the fire gate at the trigger (numbers in gate text folded to #):

| gate | shots | hits | misses | hit rate |
|---|---|---|---|---|
| threat: blasting | 500 | 181 | 319 | 36 % |
| no line: hold fire | 242 | 114 | 128 | 47 % |
| laserless gun: corridor, alignment and loaded rounds require | 207 | 115 | 92 | 56 % |
| line to him | 68 | 26 | 42 | 38 % |
| laserless gun: aimed hold | 36 | 14 | 22 | 39 % |
| ? | 15 | 3 | 12 | 20 % |
| dot off him: hold fire | 13 | 5 | 8 | 38 % |
| on him | 8 | 2 | 6 | 25 % |
| longbow: aligning camera aim; hold fire | 6 | 1 | 1 | 50 % |

By aim state at the trigger:

| aim state | shots | hits | misses | hit rate |
|---|---|---|---|---|
| aim | 618 | 245 | 373 | 40 % |
| laserless | 256 | 131 | 119 | 52 % |
| readying | 135 | 70 | 65 | 52 % |
| swing | 80 | 12 | 68 | 15 % |
| stale | 14 | 3 | 11 | 21 % |
| reacquire | 4 | 1 | 3 | 25 % |
| ? | 1 | 0 | 1 | 0 % |

Miss causes (first match of gbox.mercs.ballistics.MISS_CAUSES; contributing = every cause that applied):

| cause | primary | contributing |
|---|---|---|
| dot off him | 235 | 250 |
| no ray at the trigger | 163 | 247 |
| wild error | 84 | 84 |
| gun down / turning | 68 | 68 |
| dot on him (moved / late) | 57 | 72 |
| line blocked | 19 | 25 |
| fired while turning | 12 | 12 |
| target moving fast | 2 | 3 |

In the exact records alone: no ray at the trigger 23, dot off him 20, fired while turning 12, dot on him (moved / late) 5, wild error 5, line blocked 3, target moving fast 2.

By stage (round maps; damage events per minute of round-map time):

| stage | rounds | minutes | shots | hits | hit rate | damage events | per minute | deaths |
|---|---|---|---|---|---|---|---|---|
| Experimental Facility | 7 | 37.5 | 410 | 163 | 40 % | 109 | 2.91 | 4 |
| Ancient Ruins | 8 | 20.0 | 57 | 24 | 42 % | 222 | 11.1 | 7 |
| Prison | 6 | 17.4 | 233 | 102 | 44 % | 85 | 4.87 | 5 |
| The Mines | 6 | 16.4 | 177 | 82 | 46 % | 98 | 5.96 | 6 |
| Village | 5 | 13.6 | 119 | 43 | 36 % | 71 | 5.23 | 3 |
| Missile Area | 2 | 7.3 | 31 | 16 | 52 % | 38 | 5.18 | 1 |
| Ship Deck | 5 | 7.0 | 34 | 12 | 38 % | 26 | 3.74 | 3 |
| Public Assembly | 3 | 6.9 | 47 | 20 | 43 % | 55 | 7.94 | 1 |

## RE5 damage

704 HP losses (72797 HP) in 387 incidents (a chain of hits less than 2.5 s apart counts once, classified by its first hit): 344 single hits, 22 chains of 6+ (grabs: 43 incidents, 201 events in the grabbed state). Facing is the nearest living Majini's bearing from the player's heading 0.1-0.3 s before the hit (the hit reaction turns the player). Shares are of incidents; the last column weighs them by HP lost.

| aim state at the hit / nearest Majini | incidents | share | share of HP lost |
|---|---|---|---|
| swing / side (45-100) | 77 | 20 % | 17 % |
| swing / behind (>100) | 72 | 19 % | 18 % |
| aim / front (<45) | 55 | 14 % | 13 % |
| laserless / front (<45) | 44 | 11 % | 12 % |
| swing / front (<45) | 35 | 9 % | 9 % |
| readying / front (<45) | 29 | 8 % | 6 % |
| readying / behind (>100) | 14 | 4 % | 5 % |
| aim / behind (>100) | 12 | 3 % | 3 % |
| laserless / side (45-100) | 11 | 3 % | 4 % |
| laserless / behind (>100) | 10 | 3 % | 3 % |
| aim / side (45-100) | 10 | 3 % | 4 % |
| readying / side (45-100) | 9 | 2 % | 2 % |
| reacquire / front (<45) | 3 | 1 % | 2 % |
| other / side (45-100) | 2 | 0 % | 0 % |

| phase at the hit | incidents | share | share of HP lost |
|---|---|---|---|
| clear_nearby | 295 | 76 % | 77 % |
| stand | 16 | 4 % | 4 % |
| gather_time | 14 | 4 % | 3 % |
| healing_inventory | 12 | 3 % | 2 % |
| healing | 10 | 3 % | 1 % |
| break_for_time | 9 | 2 % | 2 % |
| fight | 9 | 2 % | 3 % |
| boss_range | 9 | 2 % | 2 % |
| pursue | 8 | 2 % | 5 % |
| seek_health | 5 | 1 % | 1 % |

| nearest Majini | incidents | share | share of HP lost |
|---|---|---|---|
| <1.5 m | 318 | 82 % | 81 % |
| 1.5-2.5 m | 31 | 8 % | 7 % |
| 4-7 m | 15 | 4 % | 4 % |
| 12 m+ | 10 | 3 % | 5 % |
| 2.5-4 m | 7 | 2 % | 2 % |
| 7-12 m | 6 | 2 % | 1 % |

| Majini within 4 m | incidents | share | share of HP lost |
|---|---|---|---|
| 3-4 | 116 | 30 % | 27 % |
| 5+ | 90 | 23 % | 21 % |
| 1 | 82 | 21 % | 22 % |
| 2 | 65 | 17 % | 19 % |
| 0 | 34 | 9 % | 11 % |

| the bot's target | incidents | share | share of HP lost |
|---|---|---|---|
| target = nearest Majini | 221 | 57 % | 58 % |
| target = another Majini | 111 | 29 % | 30 % |
| no target | 55 | 14 % | 12 % |

| fire gate at the hit | incidents | share | share of HP lost |
|---|---|---|---|
| no line: hold fire | 121 | 31 % | 30 % |
| threat: blasting | 89 | 23 % | 21 % |
| line to him | 70 | 18 % | 18 % |
| laserless gun: turning; hold fire | 33 | 8 % | 8 % |
| laserless gun: corridor, alignment and loaded rounds required; hold fi | 23 | 6 % | 6 % |
| longbow: aligning camera aim; hold fire | 15 | 4 % | 4 % |
| longbow: aimed press/release | 13 | 3 % | 4 % |
| dot off him: hold fire | 5 | 1 % | 2 % |

Under way at the first hit: turn 184 incidents (44 % of HP); route 40 incidents (12 % of HP); heal 27 incidents (3 % of HP); reload 1 incidents (0 % of HP). (turn = a gun-down swing; route = gather_time / break_for_time / pursue / hunt_spawns / boss_range ...; heal = healing / healing_inventory / seek_health; reload = an empty gun or L1+cross held.)

A boss was within 7 m in 94 incidents. Before 15:39 the nearest Majini was behind in 91 of 340 incidents; after it (quick turn live) in 18 of 47 (too few to call a change).

Weapon in hand at the hit (events):

| weapon | events | share | share of HP lost |
|---|---|---|---|
| uWp1a Lightning Hawk | 142 | 20 % | 7 % |
| VZ61 | 78 | 11 % | 12 % |
| M29 (S&W M29) | 75 | 11 % | 9 % |
| uWp0f longbow | 70 | 10 % | 12 % |
| item 0x304 First Aid Spray | 69 | 10 % | 9 % |
| Gatling gun | 53 | 8 % | 6 % |
| uWp1d AK-74 | 46 | 6 % | 8 % |
| uWp09 SIG 556 | 30 | 4 % | 6 % |
| uWp1b S&W M500 | 28 | 4 % | 8 % |
| uWp19 Hydra | 22 | 3 % | 4 % |
| uWp16 Benelli M3 | 21 | 3 % | 4 % |
| M92F | 21 | 3 % | 5 % |

First Aid Spray in hand (item 0x304): 69 events, 29 incidents; weapon policy at those hits: "recovery item in hand outside a heal: back to a gun" 40, "shotgun" 16, "laserless gun: corridor, alignment and loaded rounds required" 10, "switch to S&W M29: range/crowd/boss fit" 2, "unknown weapon" 1; 14 under the laserless controller. The policy "recovery item in hand outside a heal: back to a gun" means the switch back was asked for and did not happen (switch cooldown); "shotgun" is the combat layer treating the spray as weapon 4.

Laserless controller: 188 events (19 % of HP): uWp0f / Sheva (Tribal) 64, uWp1a / Chris (Warrior) 63, Gatling / Chris (Heavy Metal) 14, VZ61 / Sheva (BSAA) 13, item / Chris (Warrior) 11, item / Sheva (Tribal) 7, Gatling / Rebecca 4, M29 / Barry 2. Gates: "laserless gun: corridor, alignment and loaded rounds require" 69, "laserless gun: aimed hold" 44, "longbow: aligning camera aim; hold fire" 35, "longbow: aimed press/release" 23, "line to him" 5, "no line: hold fire" 4.

## RE5 deaths

30 deaths (HP to 0), each in a different round, on every stage. Phase at the death: clear_nearby 20, seek_health 1, healing 4, healing_inventory 1, boss_range 2, break_for_time 1, pursue 1. Median hits in the last 10 s: 2. The last 10 s of each (the ledger's 0.2 s history) as pattern counts:

| pattern in the last 10 s | deaths |
|---|---|
| trigger down < 20% of the last 10 s | 26 |
| 3+ Majini within 5 m at the death | 24 |
| a heal was deferred (Majini near) at the death | 23 |
| dying blow during a gun-down swing | 20 |
| died with a recovery item in the inventory | 17 |
| a boss within 7 m at the death | 17 |
| healing (inventory/use) in the last 10 s | 10 |
| laserless / longbow controller at the death | 4 |
| 4+ hits in the last 10 s (a chain) | 3 |
| turned > 360 deg in the last 10 s | 3 |
| the First Aid Spray in hand at the death | 2 |
| grabbed at some point in the last 10 s | 1 |

HP when the last 10 s began: 1, 1, 1, 1, 1, 1, 1, 1, 3, 3, 3, 3, 3, 3, 20, 20, 34, 41, 130, 132, 151, 188, 207, 244, 263, 384, 412, 916, 1000, 1000 - 14 of 30 began at 1-3 HP (8 at exactly 1 HP: the dying state, where Bot._heal returns without acting).

## Standstills over 5 s

RE5: 322 stretches, 6798.7 s of 7571.2 s of round time (the stand and firing from where he stands both count as standing still). By phase:

| phase | stretches | seconds |
|---|---|---|
| clear_nearby | 186 | 3292.5 |
| stand | 16 | 1653.2 |
| gather_time | 31 | 645.6 |
| waiting_round_start | 34 | 528.7 |
| break_for_time | 9 | 182.7 |
| healing_inventory | 13 | 167.1 |
| fight | 13 | 154.2 |
| pursue | 8 | 61.9 |

| combat line during the stretch (numbers folded) | stretches | seconds |
|---|---|---|
| swinging round to him (gun down): # deg | 86 | 1573 |
| readying: action=# laser=no tracking FIRE | 53 | 1008.2 |
| barry w#xb body dot None yaw # pitch # rapid hold FIRE | 5 | 664.7 |
| vt#x#a#f# w#x#a body dot None yaw # pitch # rapid hold FIRE | 5 | 617.6 |
| turning toward a front candidate | 13 | 484.4 |
| laserless gun yaw # pitch # release / tracking | 11 | 207.6 |

Longest: 20261026-114932 Experimental_Facility 577.6 s stand (line to him); 20261026-112220 Experimental_Facility 571.9 s stand (line to him); 20261026-134842 Ancient_Ruins 156.4 s clear_nearby (no line: hold fire); 20261026-135713 Missile_Area 155.5 s gather_time (threat: blasting).

RE4: 28 stretches, 310.7 s of 1724.5 s. By phase: take_bonus 11 (176 s), fight 16 (117.4 s), run_to_target 1 (17.3 s). Longest: 20261026-153038 r400 51.8 s take_bonus; 20261026-125403 r400 37.7 s take_bonus; 20261026-134114 r404 18.4 s take_bonus; 20261026-140711 r403 17.3 s run_to_target.

## RE4 rounds, damage and deaths

| round (Spark time) | room | s | shots | hits | acc. | kills | hits taken | deaths | weapon in hand | stuck / min | still s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 20261026-125403 | r400 | 106.1 | 15 | 7 | 47 % | 9 | 10 | 1 | Handcannon (0x37) | 6.2 | 56.6 |
| 20261026-125644 | r400 | 201.2 | 26 | 16 | 62 % | 21 | 10 | 1 | Handcannon (0x37) | 8.1 | 49.6 |
| 20261026-130037 | r400 | 145.8 | 0 | 0 | - | 0 | 25 | 0 | item 0x800 (0x800) | 1.2 | 85.2 |
| 20261026-130352 | r400 | 166.5 | 14 | 14 | 100 % | 32 | 18 | 0 | Handcannon (0x37) | 5 | 22.3 |
| 20261026-151808 | r400 | 160.9 | 9 | 6 | 67 % | 32 | 14 | 0 | Handcannon (0x37) | 1.5 | 14.4 |
| 20261026-153038 | r400 | 364.8 | 43 | 17 | 40 % | 20 | 14 | 1 | Handcannon (0x37) | 9.4 | 161.1 |
| 20261026-140711 | r403 | 138.2 | 18 | 13 | 72 % | 37 | 7 | 0 | Handcannon (0x37) | 5.2 | 48.5 |
| 20261026-160340 | r403 (really r404) | 152.5 | 15 | 9 | 60 % | 44 | 3 | 1 | TMP (0x30) | 5.5 | 48.2 |
| 20261026-134114 | r404 | 148 | 10 | 7 | 70 % | 36 | 16 | 0 | Mine Thrower (0x36) | 3.6 | 48.1 |
| 20261026-160635 | r404 | 140.5 | 24 | 11 | 46 % | 31 | 14 | 0 | TMP (0x30) | 3.4 | 31.6 |

Totals: 10 rounds, 28.7 min, 174 shots (6.1 a minute), 100 hits, 262 kills, 131 hits taken, 4 deaths. The counters are per run in the stats; per round = last sample minus first.

Hits taken (131, from the hits_taken counter and last_hit_by at that sample):

| attacker kind (the Tracker's landing threat) | hits | share |
|---|---|---|
| swing | 80 | 61 % |
| dynamite | 13 | 10 % |
| throw | 12 | 9 % |
| boss chainsaw (closing in) | 10 | 8 % |
| boss boss dynamite | 7 | 5 % |
| hold | 6 | 5 % |
| near | 2 | 2 % |
| boss boss swing | 1 | 1 % |

| the bot just before the hit | hits | share |
|---|---|---|
| on target, FIRE | 35 | 27 % |
| aiming (not yet on target) | 31 | 24 % |
| run_out (evading) | 26 | 20 % |
| run_to_target | 20 | 15 % |
| turning, gun down | 16 | 12 % |
| take_bonus | 1 | 1 % |
| fight: evade grab # away (eta # s) | 1 | 1 % |
| fight: evade swing # away (eta # s) | 1 | 1 % |

| attacker distance (units) | hits | share |
|---|---|---|
| 700-1200 | 41 | 31 % |
| 1200-2000 | 32 | 24 % |
| 3000+ | 29 | 22 % |
| 2000-3000 | 15 | 12 % |
| <700 | 14 | 11 % |

29 hits (22 %) name an attacker more than 3000 units away or more than 2 s from landing (e.g. "boss chainsaw slot 25 ... at 39771 (eta 15.71)"): the Tracker records the threat closest to landing when Leon's routine goes to 1, which is not the attacker when no attack was seen.

Deaths:

- 20261026-125403 r400: killed by swing slot 52 id 0x16 type 0x4 hp 3000/1800 at 595 (eta 0.0)
- 20261026-125644 r400: killed by swing slot 47 id 0x16 type 0x3 hp 1800/1800 at 1437 (eta 0.0); 5 boss(es) on the field, nearest boss chainsaw 0x16 hp 6500/6500 dist 450
- 20261026-153038 r400: killed by swing slot 48 id 0x16 type 0x3 hp 1800/1800 at 1099 (eta 0.0); 2 boss(es) on the field, nearest boss chainsaw 0x16 hp 6500/6500 dist 500
- 20261026-160340 r403: killed by boss chainsaw slot 25 id 0x20 type 0x16 hp 3500/3500 at 39771 (eta 15.71); 6 boss(es) on the field, nearest boss chainsaw 0x20 hp 5000/5000 dist 1537;

## RE4 navigation

| room | stuck events today | goal behind | vault / detour / back | est. stuck / active min | effective walls | of them in walked cells | walked 10+ times | cells blocked > 100x |
|---|---|---|---|---|---|---|---|---|
| r400 | 548 | 23 % | 275 / 185 / 88 | 8.29 | 1814 | 524 | 186 | 73 |
| r402 | 51 | 55 % | 31 / 17 / 3 | 9.12 | 227 | 153 | 106 | 0 |
| r403 | 57 | 23 % | 38 / 15 / 4 | 3.15 | 110 | 70 | 29 | 0 |
| r404 | 94 | 15 % | 44 / 34 / 16 | 4.59 | 315 | 103 | 24 | 13 |

An effective wall is a learned cell with blocked x 40 > walked (LearnedMap.wall). The ray fan (_raycast_fan, 5 rays x 20 Hz) marks the 40 cm cell holding each ray's hit point (RE4 world units are mm), so cells beside every wall Leon runs at pile up block counts in the thousands, including floor he walks; _around / _round_walls then plan A* detours round them. Goal direction at each stuck: r400 right 20-90 98, behind (>90) 127, left 20-90 116, ahead (<20) 207; r402 right 20-90 14, behind (>90) 28, left 20-90 3, ahead (<20) 6; r403 ahead (<20) 16, left 20-90 12, right 20-90 16, behind (>90) 13; r404 left 20-90 32, right 20-90 24, ahead (<20) 24, behind (>90) 14. 'Goal behind' stucks come from _go's stuck test, which also runs while he turns on the spot without running. Only 159 of 750 stuck-log events fall inside a round map's time; the rest come from RE4 play without a round map in gbox-data.

r400 and r404 have disc navmaps (profiles/gamedata); r402 (Castle) and r403 (Base) have none, so the bot runs straight at its target there and learns walls only by hitting them.

## Fixes in this change

Every file is a hot-reloadable bot module (`gbox.hot_reload.classify` answers "reload"). The r402 / r403 navmaps are data under `profiles/`, which forces a service restart, so they are on a follow-up branch (`re4-navmaps-castle-base`) to go in with the next restart.

| fix | cause it answers | where | metric that should move |
|---|---|---|---|
| The laser sight is walked up to 1024 FX units. The vtable is checked before a unit is cached or read, and a failed walk repeats at most every 0.3 s. | Finding 1: no ray in busy rounds, then another unit's fields read as the ray | `re5_ps3.laser`, `LASER_WALK_MAX`, `LASER_RESCAN_S` | "no ray at the trigger" misses, the audit's laserless share, the RE5 hit rate, gun-down turning share |
| A laserless gun within 3 m and 60 deg keeps the gun up and fires while the aim corrects (`threat: blasting (laserless)`), instead of lowering it to turn or waiting for a 6 deg alignment. | Finding 2 / 6: gun-down swings with a laserless gun (coordinator (b)) | `re5_combat._laserless_tick`, `LASERLESS_BLAST_R` / `_CONE` | hits taken during "laserless gun: lower weapon and turn", the laserless gate's hit rate |
| A gun up 2 s without a ray is laserless. Inside 8 m a loaded laser gun in a quick slot takes over, even with Majini close, and the bow keeps its range. | Coordinator (a) | `re5_combat.laserless_now`, `re5_weapons.best_quick_slot(laserless=)`, `re5_ps3._tick` | time under the laserless controller at close range |
| A non-weapon in hand (the First Aid Spray) is no gun: no weapon 4, and its use is not a shot. | Finding 4 | `re5_combat._in_hand`, `observe` | shot rows as 0x4; the round's accuracy is no longer diluted by spray "shots" |
| A heal starts with Majini near under 25 % of health (was 15 %), and the "near" radius is 4 m (was 5 m). Each stage raises its own threshold to its heaviest hit x 1.25 (at most 35 %). | Finding 5: deaths with the heal deferred | `re5_ps3.HEAL_CRITICAL` / `HEAL_SAFE_R`, `_heal_critical`, `impact_lessons` | deaths with a heal deferred; deaths at 1-3 HP |
| Every RE5 hit is a round-map `hit` event with: the loss, the attacker kind (melee / close / boss / ranged / unseen), distance, angle off his facing and side, the crowd within 4 m, phase + combat line + fire gate, the heal state and the weapon. Each hit is also a stage lesson. | Missing diagnostics | `re5_ps3._impact_watch`, `gbox.mercs.impact_lessons` | the per-damage classification without the server ledger |
| The round's gun is read back 6 s into every RE4 round: the gun in his hands and its class's five fire intervals. A missing or wrong gun is equipped (`equip_item`) and a slow class gets x80 again (`weapon_mod`), at most 2 repairs a round. `round_loadout` (gun, equipped, intervals, verified, reason) goes into stats and the round map. | Finding 7: rounds with no gun, x80 unverified | `re4_merc_bot.LoadoutCheck`, `apply_round(stats=)`, `arm_round` | rounds with "item 0x800", the audit's "loadout not verified" |
| A verified x80 gun has A held on target (the game repeats at the gun's ~1-frame interval). If nothing fires and no health falls in 0.8 s, the round falls back to presses. Held-fire shots are counted from the fire motion restarting. | Finding 7: presses capped the rate at ~6 a second | `Bot._pull`, `_rapid_ok`, `_shot_seen`, `snapshot` `mframe` | RE4 shots a minute (6.1 before), `trigger_mode`, kills a round |
| "You Are Dead" is answered No (D-pad right, A): back through Select Player for a new random character and gun. A round the MercMode DJ asked for keeps Yes. | Finding 8 | `Bot._continue_answer` | the audit's "character unchanged"; characters per run |
| A swing / grab / rush landing within 1 s inside 1.5 m is shot as soon as the aim is anywhere in his body (700-1650 mm above his feet), not only the head band. The gun stays up to aim-turn only within 0.55 rad (was 0.8); past that it comes down to turn at ~170 deg/s. | Finding 9: hits while still aiming | `URGENT_BAND`, `_combat`, `_fight`, `AIM_KEEP_ERR` | hits taken while "aiming", attacks prevented |
| Every RE4 hit is a round-map `hit` event with the attack, distance, angle and side, and what he was doing. A pick that cannot have landed is "unattributed". A melee hit while he stood shooting that very attacker raises the room's evade margin for that attack by 0.05 s (at most 0.6 s); an attack killed in its wind-up lowers it by 0.01 s. | Finding 9, coordinator "train from every impact" | `Bot._impact`, `_evade_margin`, `gbox.mercs.impact_lessons` | swings landing while "on target FIRE" |
| A stuck is only a run that does not move. Turning on the spot, a fight, a vault or a step back in between are not counted. | Finding 10: 24 % false stucks, each a vault, a sideways detour and a false wall | `Bot._go` | stucks a minute; vaults / detours / backoffs a minute |
| The ray fan no longer writes the disc's walls into the learned map. Old maps are cleaned on load: a blocked cell he stood in twice is floor, and other counts are capped at 3. | Finding 10: false walls and detours | `_raycast_fan`, `LearnedMap._migrate`, `LEARNED_VERSION` | detours a minute; `learned_walls` |
| With the disc's map, a waypoint is skipped as soon as the run to the next one is clear at his shoulders' width. The 0.65 m drop stays as before. | Operator: "run linearly in a straight path" | `Bot._passed`, `_clear_run` | `waypoints_skipped`, wall bumps a minute |
| A round map started before the room was read is filed under the room played. | Finding 11 | `Bot._round` | correct `r4xx` folders |
| Every round map carries an `audit` (`OK` or `problems`) and stats carry `round_audit`. The checks: character unchanged / unknown; loadout not verified; fire rate not applied; no gun in his hands; rapid fire fell back to presses; RE5 laser ray missing over 25 % of gun-up time (with the hit rate); rapid fire unverified; gun-down turning over 30 % of the fight; accuracy under 40 % (5+ shots); over 12 hits taken; each standstill over 5 s; over 3 wall bumps a minute; a death and its cause. | Coordinator: "an automatic per-round audit" | `gbox.mercs.round_audit`, `RoundTrace.auditor` / `annex` | the verdicts themselves |

Navigation, measured on today's own data:
- The learned-map cleanup on today's maps: effective walls r400 1814 -> 1389, r402 227 -> 87, r403 110 -> 44, r404 315 -> 225. Walls in cells he walked: 524 -> 99, 153 -> 13, 70 -> 4, 103 -> 13.
- The false stucks removed: 123 of 548 (r400), 26 of 51 (r402), 13 of 57 (r403) and 12 of 94 (r404) had the goal more than 92 deg off. That is 22 % of the stucks, each followed by a vault, a detour or a backoff.
- A kinematic replay of the run controller over every pair of time bonuses on the disc maps is crude (3.3 m/s, 3 rad/s, no wall sliding). With the look-ahead, wall contacts in r400 fall from 75.7 to 51.1 a minute and 27 of 30 runs arrive instead of 25. r402 / r403 / r404 are unchanged. The live check is the audit's wall bumps a minute (before: r400 8.3, r402 9.1, r403 3.2, r404 4.6 stucks a minute).

Tests: `tests/test_re4_diagnostics_fixes.py` and `tests/test_re5_diagnostics_fixes.py` cover each fix, and `tests/test_mercs_round_audit.py` covers the audit and the lessons. Updated: the death answer, the ray fan, the stuck tests (the fake Leon's turns on the spot now turn him), the aim-keep angle and the heal radius text.

Needs live confirmation:
- RE4 holding A auto-repeats at the class interval (a live note from 2026-10-20 says so; the 0.8 s proof falls back to presses otherwise).
- The player's motion frame sits at the Ganados' offset (+0x290). Without it, only shots entering the fire state are counted while A is held.
- The death screen's No is D-pad right, as `re4_menus.RandomSelections` already assumed.

## Method and data notes

- Data: Spark gbox-data/mercs/round_maps/BLUS30491/<stage>/ and G4BE08/r<room>/ (files since 10:00), gbox-data/mercs/lessons/BLUS30491/runs/*-combat.jsonl (shot rows), the player_damage ledger (gbox.sqlite3 docs kind player_damage, 704 since 10:00, each joined with its report-moment artifact: telemetry, snapshot, 12 s history), runtime re4_learned/r4xx.json and r4xx-stuck.jsonl. Read only.
- RE5 shots: exact records where the round map has them (8 rounds), else gbox.mercs.ballistics.records_from_lessons (the lessons' per-shot result / dot / distance, the aim from the state sample before the shot), else records_from_trace. Aim state and gate for the joined records are the 0.25 s sample's, so they are approximate.
- RE5 damage: an event is one observed HP drop (several game hits between two reads count once). Attacker = nearest living Majini (hp_max > 1); the ledger does not record the attacker. 160 events fall outside the copied round maps' time windows (they still count in the damage tables).
- RE5 deaths: hp_after = 0; patterns from the death event's telemetry and history.
- RE4: hits from the hits_taken counter; attacker from last_hit_by (the Tracker's record); before-hit state from the previous 0.25 s sample's phase / combat line. Room labels are the round map's own; one map is mislabelled (above).
- Times are Spark local time (CST); 10:00 = epoch 1793030400. The rounds after the 16:13 restart (5 RE4, 2 RE5) were copied at about 16:50 and are summarized in their own section; the ledger extract ends at 16:21.
- RE4 world units are mm (Leon ~1800 tall): ARRIVE 650 = 0.65 m, the learned map's cells 400 = 40 cm, run speed ~3300 a second. RE5 units are cm.
- The RE4 character per round comes from the round reports (mercs_round_report); the RE4 bot only learns it when it walks Select Player itself.
