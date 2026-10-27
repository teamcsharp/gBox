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

## Weapons, the inventory and the fire rate (2026-10-26 evening)

- **The weapon definition table**: main+0x1D08680, records of 0x140 (the PS3's stride), index = weapon id, 0x2C player
  weapons then the enemies'. A constructor fills it at boot: no relocation points at the "WPnn NAME" strings, and the
  records were found by scanning main's data for pointers to them. Each record has +0x0 its class's vtable, +0x8 -> the
  name, +0x10 class (2 handgun, 4 machine gun, 5 shotgun, 7 magnum), +0x18 1 = automatic, and +0x1C 1 = needs no ammo
  (only the Gatling; the PS3's +0x14). +0x24 holds class bits (0x201 ...). +0x90 f32 is the fire interval offset (-10
  handguns, +5 machine guns, -2 shotguns, -5 magnums).
- **The upgrade table**: main+0x1D13B28, 0x210 a weapon (8 groups of 0x40: a pointer, then 14 values). Firepower is at
  +0x18 (M92F 150 ... 250), firing speed at +0x58 (M92F 26 frames), reload at +0x98, capacity (s32) at +0xD8 (10 ... 100).
- **The inventory**: in the player, slots of 0x38 from +0x30F0. Each slot has +0x8 the id word 0x0TII (T 1 weapon, 2 ammo,
  3 recovery), +0xC rounds, +0x10 capacity, +0x1C grid position, +0x20 1 = in hand, +0x24..+0x27 its four upgrade levels.
  Chris (BSAA) in No Mercy carries handgun ammo 50, hand grenades 5, machine-gun ammo 30, the M92F (50 / 50, firepower
  level 5, capacity level 10), the Ithaca 20, a First Aid Spray (grid 7) and the knife.
- **The fire action** (main 0x96E2C8-0x96E340): it takes the in-hand slot's weapon, interval = firing speed[level] + the
  definition's +0x90, and re-arms the trigger (player +0x37B0 = 1) once the shot motion's frame (player +0x93C) reaches
  it. Before the ammo check it tests +0x1C (0x96E22C).
- **Measured** (round starts, the M92F, ZR held; shots counted from the in-hand rounds): 2.7 shots/s held or tapped.
  The interval offset at -60 and the definition's other 1.0 fields (+0xA0, +0xA4, +0xAC, +0xB0, +0xB4) left it at
  2.7: the shot motion itself sets the pace. The player's time scale (+0x1A08, 1.0, read by 966 sites) does move it:
  4.7 at x2, 8.7 x4, 15.3 x8, 16.7 x32, 24.7 x80 (the frame rate caps it; Citron ran 40-60 fps beside other loads).
  With +0x1C = 1 the M92F's rounds stayed at 50 while it fired.

`gbox.mercs.titles.re5_switch_mods` (the profile's playing_ops, applied when a round starts) puts these to use.
infinite_ammo sets +0x1C on every gun and grenade (33 of them, by name; the originals are kept). fire_rate x80 raises
the time scale only while the shot motion plays (+0x8F8 = 29), so aiming, walking and turning keep the game's speed.
The driver's snapshot maintains it and puts the game's pace back when the shot ends, the round ends or the bot stops,
never writing into a player object its round has freed. The bot holds ZR while the laser is on a Majini and does not
steer during the shot. Live round with both (private Citron, real damage): **29 kills, 13,540 points, max combo 24,
alive at the end** (v2 without them: about 10 / 3,200). Frames: docs/evidence/switch-citron/re5-switch-rapid-fire.jpg.

## You Are Dead - Continue? and dying

uIdGameover00 +0x1CC is the cursor (0 Yes, 1 No); +0x1EC reads 2 once the dialog takes input. Yes replays the same
round at once, and No saves ("Save successful") and goes on to the results flow. Blind presses could land on Yes
(round m80a restarted inside one engine call, two rounds counted as one), so the bot and the menus walk now press A
only with the cursor read on No. A forced death (health 0 in the private session) went dialog, D-pad right until the
cursor read No, A, "Save successful". Dying (health 1) shows "Resuscitate" with A: the bot mashes A then; a hold shows
"Break free" with the left stick, which it shakes.

**The pace** (re5_switch.REPLAY_ON_DEATH, as re5_ps3.Pace does on PS3; operator: "match to match to match without
these loading screens and waiting"): No Mercy here is always the same stage and character, so a death now answers
**Yes**. That is the same round again at once, with no save, no selects and no loading; No would cost the save and
both selects. The answer still goes in only with the cursor read on it, for the bot and for the menus walk alike. The
engine publishes MercMode's round boundary at the death (terminal witness "dead") and closes that round's evidence.
The bot counts the replay as the next round: stats rounds +1, deaths_continued, round_start_via "dead/retry", and a
new _round_started marker for the engine, on the first tick alive with the clock within 3 s of its full time (a time
bonus raising the clock is not a new round).

## Survival (2026-10-27)

**Baseline**, from the first MercMode RE5 Switch turn (22:46-22:58, the round notebook
`mercs/curriculum/010018100CD46000/rounds.jsonl`): 6 rounds, of which 5 were deaths and 1 completed (0.83 deaths a round).
Time alive in a death round, as 120 s minus the clock left (a floor, since time bonuses add): 81, 95, 72, 89, 93 s
(mean 86 s). Kills a round 7-14 (mean 10.7), score mean 3,617; up to 7 holds and 4 dying episodes in a round; 18-28
back-offs a round. Most deaths came swarmed.

- **Crowd control** (live in the bot, tuned 2026-10-27):
  - A ring leaves no gap of 150 deg between the Majini's bearings. The bot runs out through the widest gap for 1.2 s
    (left stick + B, Type D's own "Run") only when the ring is tight: 4+ within 2.5 m or 3+ within 1.8 m. Hurt (under
    60 % health), the looser 3+ within 3 m also counts. At most every 4 s and 6 times a round, quick-turning first when
    the gap is behind him.
  - The first rule, 3 within 3 m at any health, escaped up to 13 times in a round: that round completed, but with only
    9 kills. The rapid fire clears a loose crowd better than running from it.
  - A crowd in front is 2 or more within 2.2 m inside 60 deg of his facing. The bot fires a 0.8 s burst, then lowers the
    gun and backs off for 0.5 s (he cannot move while aiming), then fires the next burst. The burst runs from the
    first pull after the gun comes up, across the targets it drops. Timed per continuous pull, the rapid fire dropped
    a target before 0.8 s, and the back-off fired 0-1 times a round.
  - A back-off under way always finishes.
- **After** (the survival code live 23:34-23:45, heals from 23:38): 6 rounds, 3 deaths (0.50 a round, from 0.83), 3
  completed (from 1 in 6). Time alive in the death rounds 75, 91, 94 s (mean 87 s, flat). Kills mean 13.0, score mean
  4,718. Heals: 3 starts, 2 healed, 1 not.
- **Healing** (`HEAL_ENABLED`, on since 2026-10-27): the PS3 bot's rules. A heal starts below 40 % health with no
  Majini within 4 m, or below 25 % anyway. The First Aid Spray (0x304) or a herb (0x305, 0x307, 0x309) comes up from
  its D-pad slot (grid 1 / 3 / 5 / 7 = up / left / right / down), and Y uses it, every 0.35 s, for at most 4 s. It
  counts as done when the item's count falls or health rises by 50, then the gun comes back from its slot. The use key
  comes from the game's own Controller Settings for Type D
  (docs/evidence/switch-citron/re5-switch-controls-type-d.jpg): stick: strafe, stick + B: run, L + ZR: knife, ZL + ZR:
  fire / throw, ZL + B: reload, X: inventory, right stick: rotate, R: map, ZR: locate partner, A: partner action, and
  Y unassigned. Those buttons sit where the PS3's do (X = Triangle, A = Circle, B = Cross), so Y is the PS3 manual's
  Square, "use recovery item". A live press has not been seen yet, so the live telemetry watches heal_failures against
  heals; the bounded try gives the gun back after 4 s if the key were wrong.
- **Infinite spray** (`re5_switch_mods` op `infinite_spray`, off, not in the profile). A read-only look at the live
  MercMode session around a heal (2026-10-27 23:55) settled the slot record: +0x00 a static class pointer into main,
  +0x08 id, +0x0C count, +0x10 capacity (1 for the spray), +0x1C grid, +0x20 in hand, +0x2C a flag, +0x30 -> the item's
  own object (heap). The heal took the count from 1 to 0 with the spray in hand, and two seconds later the game cleared
  the slot (id 0, grid 13) and zeroed +0x30, releasing the object. So a replay of the saved record, as the PS3's
  maintain_spray does, would point the slot at a freed object, and that version is gone. The op now keeps the round's
  live spray (id 0x304, count 1 or more, +0x30 set) at count and capacity 2: a use leaves one, and the game never
  clears the slot. It writes only those two ints, never a count of 0 (a use under way), an emptied slot or a slot
  without its object. A private live run comes before it goes into the profile.
- **A fix from #1253**: after each Continue Yes, the notebook got a phantom "ended" row (clock 119.9, no kills) about
  22 s later. The engine already opens the replay's round when the death closes the old one; the bot then moved its
  `_round_started` marker, so the engine closed and reopened it. The marker is now set once per bot.

## The RomFS: player models (for LayeredFS builds, docs/switch-mods.md)

The program NCA (15af72f2..., 20.0 GB) holds the RomFS under `nativeNXx64/`. Each player costume is one MT Framework
ARC v7 (header `ARC\0`, version 7, a count, then 0x50-byte entries: a 64-byte path, the type hash, the compressed and
decompressed sizes (top 3 bits flags), the offset; zlib blobs packed back to back from 0x8000). The files are named
after the player classes the RAM shows: `ImgNX/Archive/uPl00ChrisNormal.arc` (Chris BSAA, 327 entries, 43 MB),
uPl00ChrisCos1-4 / Plain / Ep1 / ArmorA-F, uPl01ShebaNormal.arc (332 entries) and her costumes, uPl02Jill, uPl03Wesker,
uPl04Josh, uPl05Excella, uPl06Barry and uPl07Rebecca. Inside, resources are named by path (`pawn\pl\pl00\model\pl00arm_BM`
...), and Chris's code asks for `pl00` names, so another character's archive under his name would miss them. Of Chris's
own costumes, Cos1 shares 323 of the 327 entries byte for byte; only the model entries differ (`pawn\pl\pl00\model\pl00`,
`pl0000`). A texture swap of equal size (same TEX header) is safe. For the #1227 live check, Chris's shirt (`pl00Shats_BM`)
got Sheva's arm skin (`pl0100_05Arm_BM`), and his face got hers, both 1,400,384 bytes. The files were read from the NSP with
a scratch reader using the Spark's own prod.keys (gBox itself has no NCA decryption).

## MercMode's warm pool (2026-10-26, one private Citron run of 162 s)

`gbox.mercs.warm_boot` boots the next MercMode game in the background, pauses it (SIGSTOP) at a stable native menu,
and later drives its menus to a round's first frame and parks it there paused, so the swap lands in a round. RE5 Switch
has its own reader, `re5_switch.warm_probe`, which warm_boot finds through the RAM map (`title_probe`). It pins the
build by main's 64-byte signature and calls these ready: the title (below), "Load successful", main menu, PLAY GAME,
The Mercenaries United, and the stage and character selects. Each is tokened by its unit, never while NOW LOADING is up.

- **Boot**: uIdAlert00 (8.6 s), + uIdNowLoading00 (9.6 s), then uIdAlert00 + uIdTitle00 (10.6 s), with the screen still
  black (frame at 18.7 s). The only state change while it waits is a pointer at uIdTitle00 +0x18, set about 6 s after
  the unit (+0x28 is a float that animates throughout). Title ready = the unit with +0x18 set; nothing is pressed there.
  The menus need 0.3 s presses: a 0.15 s A after the title pause did nothing, and the walk's 0.3 s presses went title,
  "Load successful", the menus, the intro in 28 s.
- **The park**: the menus' `screen()` calls the round's intro "playing" (player in the stage, phase 0, no NOW LOADING;
  the HUD units are up, the timer reads 120.0). The prepare walk stops there, before the clock runs, as on the PS3. The
  engine's own screen keeps "loading" for the intro and waits through it.
- **Pause and resume** (the adapter's SIGSTOP / SIGCONT): 20 s at the title and 60 s in the intro were both clean.
  After the long pause the intro carried on for 10.5 s, then phase 1 started at 119.84 and counted at the normal rate.
  There is no clock jump: the paused minute does not come off the round. PulseAudio's sink inputs (PipeWire) were the
  same before and after (the stream survived), and Citron's log had no error, audio, Vulkan or "lost" line.
  Frames (black title at 18.7 s, the parked intro, 15 s after resume):
  docs/evidence/switch-citron/re5-switch-warm-park.jpg.
