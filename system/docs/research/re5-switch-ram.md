# RE5 Switch RAM map (title 010018100CD46000, v1.0.0, main build EBFFDB223149A725A93CD9B60979F6AA)

Measured live on 2026-10-26 on the Spark. The emulator was Eden v0.2.1 in single-core mode with NCE, so a guest
address is the host address and `/proc/<pid>/mem` reads it directly. The run was a direct Eden run with a private
home, reniced to +10, playing The Mercenaries United > No Mercy, Public Assembly, Chris (BSAA). The driver is
`gbox/mercs/titles/re5_switch.py` and the profile is `profiles/gamedata/010018100CD46000-ram.json`.

## Finding main

ASLR moves main every boot (seen at 0x3CA89C3000). `module_base()` searches the guest's read-only rows for 64 bytes of
main at offset +0x1191000 (part of its RELA table, unique in the module). The search reads under 100 MB and takes
about 0.1 s. Every address below is relative to main.

Statics came from the main NSO (Eden `dump_nso`, the 0x100-byte header plus the image at vaddr 0). Each class's
`MtDTI::MtDTI(this, name, parent, size, ...)` call (0xBD28D0) in the static initialisers gives its DTI. A singleton's
instance pointer is the hottest 64-bit global next to its DTI. Where code reaches a static through the GOT (sMain,
sUnit), the slot is resolved from its R_AARCH64_RELATIVE addend. MtDTI is 0x38 bytes: +0 vtable, +8 name, +0x10 next,
+0x18 child, +0x20 parent, +0x30 size>>2 in bits 0-22, +0x34 id. An object's class comes from vtable slot 5
(getDTI): `adrp x0 / add x0 / ret`, or `adrp x0 / ldr x0 / ret` through the GOT.

| what | address | notes |
|---|---|---|
| sMain::mpInstance (sBioMain) | +0x26A1BA8 | 3031 code refs through GOT 0x1CD2BE0; class size 0x585C0 |
| cGameSys | [sBioMain + 0x584E0] | stored by sBioMain's init at 0x17B034 after `new cGameSys` (0xA88 bytes) |
| sPlayer::mpInstance | +0x1CF1C98 | 2461 refs, one store (its constructor, 0x1EB208) |
| sEnemy::mpInstance | +0x1CF04B8 | 683 refs |
| sUnit::mpInstance | +0x26A3270 | through GOT 0x1CD2C38 |

## The round (cGameSys)

| field | offset | checked |
|---|---|---|
| phase | +0x944 s32 | 0 during the load / intro, 1 playing, 3 over. It stays 3 in the menus until the next load |
| seconds left | +0x948 f32 | 120.0 at the start; counts real time (-3.004 in 3.0 s), also when the emulator runs slow |
| round time | +0x94C f32 | 120.0 |
| kills | +0x96C s32 | 9 = "Enemies Routed 9" on the results screen (+0x858 counts the same) |
| combo on | +0x970 s32 | 0 / 1 |
| combo | +0x974 s32 | rises with each kill in the window |
| max combo | +0x978 s32 | "Max combo 6x" |
| combo window | +0x97C f32 | about 10 s, refreshed on each kill |
| combo bonus | +0x98C s32 | accumulated bonus points |
| score | +0x990 s32 | "Score 3,060" |

Relative to the timer, this is the PS3 layout (gbox/mercs/titles/re5_ps3.py: timer +0x3E0, kills +0x3F4 ...) with
0x10 bytes inserted after the round time.

## The player and the enemies

- sPlayer +0x30 points to the player (uPl00ChrisNormal). The pointer is 0 once the round is over (the results, or
  "Save successful" after Continue? No). Player fields: +0x60 position (x, y up, z; cm), +0x70 rotation quaternion
  (heading = 2 atan2(qy, qw); forward = (sin, 0, cos)), +0x1EB8 s16 health, +0x1EBA s16 maximum (1000).
- sEnemy: +0x38 u32 count (40-47 alive in No Mercy), +0x48 points to the enemy pointers (uEm10 / uEm11 Majini, uEm21,
  uEm62). Enemy fields: +0x60 position, +0x70 quaternion, +0x1EB8 / +0x1EBA health (Majini 800 or 700, uEm21 1400,
  uEm62 1).
- These match the PS3 fields (+0x30 position, +0x14A4 health), moved by the 64-bit object layout.

## The native menus (sUnit interface units)

sUnit move lines sit at +0x18 + 0x30 * line, each holding that line's first unit. A unit's +0x18 is the next unit in
its line; on the PS3 these were +0x30 + 0x20 * line and +8.

| unit | screen | fields |
|---|---|---|
| uIdStartUp00 | main menu | cursor +0x74 (PLAY GAME 0) |
| uIdStartUp01 | PLAY GAME | cursor +0x74 (EPISODES 0, EXTRA CONTENT 1); +0x1C4 != 0 means its EXTRA CONTENT list, cursor +0x1D8 (THE MERCENARIES UNITED 0) |
| uIdStartUp29 | The Mercenaries United | +0x1C4 = 1 means the mode list, cursor +0x1C8 (SINGLE PLAYER 0, CO-OP 1, SPLIT-SCREEN 2, NO MERCY 3) |
| uIdStartUp21 | STAGE SELECT | cursor +0x74 (Public Assembly 0) |
| uIdStartUp22 | CHARACTER SELECT | cursor +0x1D0 (Chris BSAA 0) |
| uIdMerce00 | the round's HUD | with uIdCockpit00, uIdMap00, uIdPause00, uIdScope00, uIdWpSlot00 |
| uIdMerceEd00 | results | "(+) OK" |
| uIdGameover00 | You Are Dead - Continue? | Yes first |
| uIdNowLoading00 | NOW LOADING | |
| uIdAlert00 | dialogs | +0x68 != 0 while one is up; +0x6C is the PS3's id: 0x33 "Connect to the Leaderboards?" (B), 0x09 "Save successful" (A), 0x08 "Load successful" (A) |

The way into No Mercy from boot is: PRESS ANY BUTTON, Load successful, PLAY GAME, EXTRA CONTENT, THE MERCENARIES
UNITED, START, NO MERCY, stage, character. After a round: Leaderboards? (B), results (+), STAGE SELECT, CHARACTER
SELECT, the round. `re5_switch.screen` / `step` walk all of this from RAM, and the menus need held presses (0.3 s).

## Controls (Type D, from the game's own Controller Settings)

Left stick moves (forward = facing). The right stick turns: rleft raises the heading, about 160 deg/s. ZL aims,
ZL + ZR fires, L + ZR swings the knife, ZL + B reloads, X opens the inventory, R shows the map, A is partner action.
While aiming, the right stick moves the aim instead: rleft about +36 deg/s of yaw, rright about -42 deg/s, rup raises
the pitch about 40 deg/s. Left stick back, then B: the quick turn, 180 deg in 0.3 s (the stick takes about 1.1 s).

## First driver run (2026-10-26)

The menus walked from the Save successful dialog to the selects and into a round on their own. The first-cut brain
(face, aim, fire, break free) played two rounds until Chris died: 4 kills / 1,210 points (109 shots, 42 wiggles) and
1 kill / 300 points (251 shots). Most shots miss: the body's heading is not where the gun points while aiming.

## The laser sight (sUnit line 19)

The effects line (19; the PS3's FxCore line 18) holds a `uLaserSight` unit for the whole round. In a round it held two
units (`uEfCamDying`, `uLaserSight`). While the gun is up, +0x280 is the laser's origin (the muzzle) and +0x60 the dot,
where the ray lands (copies at +0x100 and +0x180). Sampled every 30 ms (`probe_laser.py`): both read zero with the gun
down. They come alive about 0.21 s after ZL goes down and zero again within 30-60 ms of letting it go. A ray that hits
nothing ends 5000 cm out (its range). `re5_switch.laser_unit` walks the line once, names each other vtable once and
checks the cached unit by its vtable on every read.

## Player states (+0x8F8, the motion byte)

One byte at player +0x8F8 (copy at +0x2550) names what the body is doing, measured over rounds v2c-v2f:

| value | state |
|---|---|
| 0 / 1 / 7 | standing / walking / backing up |
| 9, 10 | turning in place |
| 22, 26 | the gun coming up, aimed |
| 29 | a shot |
| 32 | reloading (ZR on an empty magazine) |
| 107 then 106 | grabbed, then held ("Break free", the left stick's prompt); health does not fall, another Majini swings |
| 113, 100, 114 | strangled (health drains about 150 in 1.5 s) |
| 104 | let go |
| 40, 47, 51 | dying (health 1, the PS3's solo DYING) |
| 8 | dead |

In every hold the Majini's position is 0-8 cm from the player's (bodies otherwise stay about 50 cm apart), so the bot
also counts one closer than 25 cm as a hold. +0x1138 looked like the PS3's action byte (0 free, 2 gun, 3 reload, 4 held,
5 hit) in one round. In the next it read 6 from the moment health fell to 216 until death, whatever the body did, so the
bot does not use it.

## Brain v2: the laser aim (2026-10-26)

`re5_switch.Bot` turns the body (the quick turn for a Majini behind), raises the gun, and closes the laser's ray
(muzzle -> dot) onto the Majini's chest (110 cm above his feet). ZR is tapped while the dot sits on a Majini or the ray
runs through him, using the PS3 combat layer's body measures. When the motion byte says held, a Majini is on top of him,
or the stick does not move him, the bot shakes the left stick and mashes A / B. Live rounds in a private Citron session
(Public Assembly, Chris, No Mercy; real damage unless noted):

| run | kills | score | shots | hits | hit rate | end |
|---|---|---|---|---|---|---|
| v1 (heading aim, in gBox) | 4 | 1,240 | 68 | - | - | died, 42 s left |
| v2a (laser; health held full) | 10 | 3,840 | 138 | 39 | 28 % (laser-guided presses 78 %, blind ones 20 %) | time |
| v2b (no blind shots, quick turn) | 7 | 2,160 | 36 | 24 | 67 % | died, 5 s left (held 6.5 s, unseen) |
| v2c (+ break free when the stick does not move him) | 14 | 5,050 | 102 | 64 | 63 % | time |
| v2d | 8 | 2,500 | 53 | 34 | 64 % | died, 29 s left (holds not yet read from RAM) |
| v2e (+ holds from the motion byte) | 10 | 3,050 | 68 | 46 | 68 % | time |
| v2f (+ a Majini on top of him is a hold) | 9 | 3,340 | 63 | 46 | 73 % | died, 12 s left |

A shot here is a ZR press, so the hit rate is a floor. The PS3 bot's hit rate on 2026-10-26 was 42 %
(docs/evidence/mercs-diagnostics-2026-10-26.md). Holds now last about 2 s: they lasted 4 s when the break-free started
1.5 s late, and 6.5 s with no break-free. Frames: docs/evidence/switch-citron/re5-switch-aim-round.jpg (v2c, real
frames of the private Citron session, one every 15 s) and re5-switch-break-free.jpg (a hold, v2e).

Open: health (the bot never heals; the inventory is not mapped yet), the handgun's ~35 shots a minute (rapid fire and
infinite ammo are next), the time bonuses.
