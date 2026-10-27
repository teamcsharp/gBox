# RE6 Switch: what locks The Mercenaries, the unlock, and the RAM map (title 01002A000CD48000, update v131072)

Resident Evil 6 on Nintendo Switch, base title 01002A000CD48000 played with its update 01002A000CD48800 v131072 (the
game shows 1.0.2). Main build id 061D2A06CD700785E987C42CE2D72231. Catalog ids: base `115f9cdbba115432`, update
`5d50031f5c8057b1`.

Measured on 2026-10-26 on the Spark. The emulator was Citron NEO nightly 56dad8119: multi-core, NCE, Vulkan
(`Renderer.backend=0`), the update passed through the external content folders, a private home, Xvfb :98, nice +10,
and the `libusb_init` LD_PRELOAD shim. Under NCE a guest address is the host address, so `/proc/<pid>/mem` reads it
directly (as in docs/research/re5-switch-ram.md).

For the static side, Citron's `dump_nso` dumped the main NSO (sha256 `e42734cc...5d99`; the update's ExeFS `main` is
`8b81f49f...8a3a`). I disassembled it with capstone. The tools are in `~/gBox_alt/scratch/agent/re6sw/tools` on the
Spark: the other agent's `nsodis.py` / `nso2elf.py` / `strrefs.py` / `addrrefs.py`, plus `dtiscan.py` (inline MtDTI
definitions), `props.py` (MtProperty registrations), `vtof.py` (vtable to class), `fieldrefs.py` and `funcof.py`.
A Ghidra headless import of the ELF was started, then stopped before its auto-analysis finished, because the Spark was
loaded (load average 40-50). Nothing here depends on it.

## The short answer

1. **The Mercenaries and No Mercy have no unlock flag of their own in this release.** EXTRA CONTENT (`uIdStartUp02`)
   always enables mode 1 (THE MERCENARIES) and mode 2 (THE MERCENARIES NO MERCY), and all ten stages and the four
   starting characters are open.
2. **The lock is that a fresh save never reaches the main menu.** After PRESS ANY BUTTON, the title runs the brightness
   screen and starts the Prologue. Quitting the Prologue brings back the title, which starts the Prologue again. The
   main menu (PLAY GAME > EXTRA CONTENT) opens only once the Prologue is cleared.
3. **"Prologue cleared" is bit 0 of `cSystemInfo.mTempData.mHistory.mUnlockFlag`.** A fresh save holds 0x10. With the
   bit set while the title is up, the title's own "main menu" byte (`uIdTitle00+0x20A`) turns 1 on the next frame, and
   A opens the main menu.

Frames are in `docs/evidence/re6-switch-unlock/`. 01-02 show the lock (the title leads to brightness, then the
forced Prologue). 03-09 are the fresh-save proof run: the main menu right after the unlock, EXTRA CONTENT with both
Mercenaries modes, the No Mercy menu, character select, a No Mercy round at 1'54" and then 9 kills / 3,890 / combo 2,
and the results. 10 is the second launch (the flag came from the save). 11 is the same unlock run through gBox's own
entry point (`game_unlocks.session_start` on a `SwitchLinuxAdapter` bound to the Citron process), again from a fresh
save.

## How the gate was found

- **The name.** main's strings include `mTempData.mHistory.mUnlockFlag`. Its only reference
  (main+0x112C830) is in `cSystemInfo::createProperty` (main+0x112A620, slot 4 of cSystemInfo's vtable
  main+0x288BF40), which registers it as a u32 at cSystemInfo+0xB8. Next to it are mUserPlate +0xBC, mUserEmblem
  +0xC0, mUserTitle +0xC4, mSkillPoint +0x6F4, mSkillSetNo[0] +0x760, the mOption block +0x24..+0xAC (mBrightness_Console
  +0x78 = 30, mBrightness_Handheld +0x7C = 25) and the play records from +0x20C8.
- **The object.** cSystemInfo's DTI gives a class size of 0xAA28. sInfoMan (instance pointer main+0x28E9BE0)
  holds four cSystemInfo from +0x48, and the current one is chosen by its +0x2C. This is compiled inline as
  `ldrsw x, [sInfoMan, #0x2c]; mov w, #0xaa28; madd`, so the flag is read at `[madd result + 0x100]`
  (0x48 + 0xB8). Live, cSystemInfo is a vtable followed by two 0x5510-byte copies of its data (+0x8 and +0x5518),
  which the game copies into each other (memcpy 0x5510 at main+0xFB57E0 and others). The flag therefore sits at
  cSystemInfo+0xB8 and at +0x55C8.
- **Readers of bit 0.** `uIdTitle00`'s update (main+0xAD5D40; the check at main+0xAD5D6C) sets the unit's +0x20A each
  frame from bit 0. `cDemoTitle` (main+0xFC2BA4) and `uIdStartUp1a` (main+0xA8F8E0) branch on it, and so do cDemoBase
  (main+0xFAE9AC) and cArea (main+0x2085F4).
- **Writers.** The game ORs bit 0 in when the Prologue is cleared: main+0xFB5834 in cDemoStartUp's flow (called from
  its update at main+0xFB24C4), and main+0xFB6874 in the function next to it, both under sInfoMan's lock. main+0x21F9A0
  also sets it. Bits 1 and 2 come from cArea (main+0x215458, +0x2156AC), and a
  generic `1 << n` setter sits at main+0xB267B4. Bit 1 is read by `uIdSkillSet10` (main+0xA67124).
- **No Mercy.** `uIdStartUp02`'s update (main+0xA83450) builds its enabled mask (+0x58) over its mode list (+0x1C4,
  count +0x54) through a jump table at main+0x2176F88. Modes 1 and 2 are enabled unconditionally. Modes 0 and 3-6
  (Agent Hunt, Survivors, Onslaught, Predator, Siege) are enabled unless both sBioStorage +0x8C and +0x88 have bit 31
  set. Live on the fresh save the mask was 0x7F. The chosen entry is stored in sGameMan+0x54 (1 THE MERCENARIES,
  2 NO MERCY), which also selects the mode's title art from main+0x2682B80 (`merce_title`, `merce_title`,
  `hyper_merce_title`, `sur_title`, `ons_title`, `pre_title`, `sie_title`).
- **Live confirmation.** On a fresh save the flag was 0x10 and `uIdTitle00+0x20A` was 0; A led to the brightness
  screen and the Prologue. With the flag set to 0x11 at the title, +0x20A was 1 at the next poll and A opened the main
  menu. Leaving a No Mercy round (Continue? No, then the post-round save) wrote 0x11 into SAVEDATA. The next boot
  loaded it and went to the main menu with no write (the watcher reported `already_unlocked`).

## The unlock in gBox (`gbox/re6_switch_unlock.py`)

- **Where it plugs in.** `gbox.re_switch.unlock_profile` registers profile `re6-switch-prologue-gate-ram-v1`
  (verified) with this evidence chain: title, update and catalog ids, the build id, the main NSO and ExeFS hashes,
  the module signature, the routine addresses, and the live acceptance.
- **Before boot.** `game_unlocks.pre_launch` only reports `armed`. Nothing can be written then, because the flag lives
  in a save the game has not loaded yet.
- **Starting the watcher.** `game_unlocks.session_start` is called from `tools._launch_game` once the session runs.
  It starts `re6_switch_unlock.watch` on a daemon thread. It does this only when four things hold: the profile is
  verified, the worker grants `memory_write`, the adapter maps guest memory (the Eden `SwitchLinuxAdapter`; Yuzu on
  Windows reports `unsupported`), and the operator's RE6 switch `everything_unlocked` is not off. The record goes to
  `game_unlocks.WATCHES[sid]` and to the launch detail `unlock_watch`.
- **What the watcher does.** It finds main by 64 bytes of its read-only data at main+0x2151000, then refuses the build
  unless main+0xAD5D6C holds the title gate's exact code. It waits for `uIdTitle00` (by vtable, on sUnit's lines),
  reads mUnlockFlag (both copies), ORs in bit 0, and reads each write back. It finishes once the title's +0x20A is 1
  (`applied`, or `already_unlocked` when the save had it) or a menu unit is up. If a save load clears the flag again,
  the watcher sets it again. It also gives up on another build, when the session ends, or after its timeout.
- **Save effect.** The game's next save records bit 0 (file offset 0xE8). That is the same state a cleared Prologue
  leaves. `set_save_flag(data, False)` takes it out of a backup copy again, as a rollback.

## The save

The save is `save:/SAVEDATA` (Citron: `nand/user/save/0000000000000000/<user>/01002A000CD48000/SAVEDATA`). Its layout:

- 0x7050 bytes, with a u32 checksum at 0x30: the sum of the u32 words from 0x34 to the end. This was checked on four
  saves.
- cSystemInfo copy A starts at file offset 0x38 (file offset = cSystemInfo offset + 0x30), so mUnlockFlag is at 0xE8.
- The header is `00.. 08.. 18.. 98e77fc30c`, then `2870` (the data size 0x7028) and a build stamp `05180712`.

When the game saves:

- after creating the save,
- after the privacy dialog,
- after Continue? No in a round,
- after a round's results (+ End game, then "Now saving", then "Save successful").

## Finding main and the singletons

- **ASLR.** ASLR may move main. All four Citron boots put it at 0x3CA7C04000, but the driver must not rely on that.
  `module_base()` searches the read-only rows for the 64-byte signature at main+0x2151000 (unique in main, absent from
  rtld / sdk / subsdk0), which takes about 0.03 s.
- **How the DTIs are built.** RE6 inlines `MtDTI::MtDTI` in its static initialisers:
  `stp x<vtable>, x<name>, [x<dti>]`, the parent at `[dti, #0x20]`, and `stp w<size>, w<id>, [dti, #0x30]`
  (size>>2 in bits 0-22). `dtiscan.py` finds 8433 classes. An object's class comes from vtable slot 5 (getDTI:
  `adrp x0 / add x0 / ret`), as in RE5. Each instance pointer below is the hottest 64-bit global next to its DTI, and
  each was confirmed live by its class.

| singleton | instance pointer | notes |
|---|---|---|
| sMain (sBioMain) | main+0x2A5F580 | 3506 loads |
| sGameMan | main+0x28E9B10 | 3178 loads; the Mercenaries round |
| sPlayer | main+0x28EAC10 | 4352 loads |
| sEnemy | main+0x28E9AA8 | 836 loads |
| sInfoMan | main+0x28E9BE0 | cSystemInfo x4 (the unlock flag) |
| sBioStorage | main+0x28EAE68 | 338 loads; online / option state |
| sSavedata | main+0x2A52C48 | |
| sUnit (an sBioUnit) | main+0x2A60780 | 1163 loads; the units |
| sId | main+0x28E9B78 | 708 loads |
| sDLC | main+0x2A52B18 | |

## The round (sGameMan = [main+0x28E9B10])

The table is from a No Mercy run on Urban Chaos with Leon. The HUD agreed at "009/300", "Score 3,890" (rolling up
to 4,540) and "002 COMBO".

| field | offset | checked |
|---|---|---|
| extra mode | +0x54 s32 | 1 THE MERCENARIES, 2 NO MERCY (written by EXTRA CONTENT) |
| phase | +0x3DEC s32 | 1 while playing (from the first frame of the round), 3 when the time is up (results) |
| seconds left | +0x3DF0 f32 | counts real time from 120. It is a per-frame copy: a write there is overwritten (+0x4698 tracks it too) |
| last time bonus | +0x3DF8 s32 | 5 with "+05 Sec." on screen |
| kills | +0x408C s32 | HUD 009/300 (+0xA8C counts the same) |
| combo on | +0x4090 s32 | 0 / 1 |
| combo | +0x4094 s32 | HUD "002 COMBO" |
| max combo | +0x4098 s32 | 7 |
| combo window | +0x409C f32 | about 15 s left after a kill |
| running combo bonus | +0x40AC s32 | 1840 during a 7-combo, 0 once it is banked |
| score | +0x40B0 s32 | base + banked combo bonuses (4540 = 2700 + 1840); the HUD rolls up to it |
| base points | +0x40BC s32 | 300 per kill (2100 at 7, 2700 at 9, 3000 at 10) |
| enemies appeared | +0xA84 s32 | 21 at the start, 47 after about 25 s (+0xA88 the same) |

## The player and the enemies

- **Player.** sPlayer +0x30 points to the player (`uPl00LeonAsia` for Leon). Player fields:
  - +0x60 position (x, y up, z; cm);
  - +0x70 rotation quaternion (0, qy, 0, qw), the same layout as RE5, though its heading sign is not checked against
    movement;
  - +0x90..+0x10F a 3x4 matrix (right, up, forward, position);
  - +0x1368 s16 health and +0x136A s16 maximum. Leon's maximum is 900, which is six blocks of 150; a hit took 300 to
    150.

  The pointer is 0 once the results load.
- **Enemies.** sEnemy +0x40 is a u32 count (21 at the start of No Mercy Urban Chaos) and +0x50 points to the enemy
  pointers (`uEm5200`, `uEm5210` zombies there). Enemy fields: +0x60 position, and +0x1368 / +0x136A health / maximum
  (700 or 400). This is the same object layout as the player.

## The menus (sUnit = [main+0x2A60780], an sBioUnit)

Move line N starts at sBioUnit + 0x268 + 0x30 * N, and each unit's +0x20 is the next unit in its line (RE5: +0x18 +
0x30 * N and +0x18). The units sit on these lines:

- line 0: the title and the dialogs;
- line 1: `uIdExtra`, behind the Mercenaries menus;
- line 18: menus and the HUD;
- line 19: `uIdCountDown` at game over;
- line 26: `uIdPrim`;
- line 30: `uIdFade`.

The units are named by vtable (main + offset):

| unit | vtable | screen | fields |
|---|---|---|---|
| uIdTitle00 | +0x269B390 | title (logo, PRESS ANY BUTTON) | +0x20A = 1: A opens the main menu (else the Prologue) |
| uIdStartUp00 | +0x2698958 | main menu | cursor +0x50: PLAY GAME 0, OPTIONS 1, MANUAL 2, CREDITS 3, RECORDS 4, SPECIAL FEATURES 5, PRIVACY POLICY 6 |
| uIdStartUp01 | +0x26988B0 | PLAY GAME | cursor +0x50: CAMPAIGN 0, CYCLE MODE 1, FRIEND MATCH 2, EXTRA CONTENT 3, DOG TAGS 4 |
| uIdStartUp02 | +0x2698808 | EXTRA CONTENT | cursor +0x50: AGENT HUNT 0, THE MERCENARIES 1, NO MERCY 2, SURVIVORS 3, ONSLAUGHT 4, PREDATOR 5, SIEGE 6; +0x54 count, +0x58 enabled mask, +0x1C4 mode ids |
| uIdStartUp30 | +0x269A080 | THE MERCENARIES (NO MERCY) | cursor +0x50: SOLO 0, CREATE GAME (DUO) 1, JOIN GAME (DUO) 2, SPLIT 3, SKILL SETTINGS 4, LEADERBOARDS 5 |
| uIdStartUp31 | +0x2699F30 | STAGE | cursor +0x50: Urban Chaos 0, Steel Beast 1, Mining the Depths 2, Rail Yard 3, High Seas Fortress 4, The Catacombs 5, Requiem for War 6, Liquid Fire 7, Rooftop Mission 8, Creature Workshop 9 |
| uIdStartUp32 | +0x2699E88 | CHARACTER SELECT | cursor +0x1CC: Leon 0, Chris 1, Jake 2, Agent 3 |
| uIdMerceUI | +0x2685650 | the round's HUD | with uIdLife00, uIdGoal, uIdScope, uIdWpSlot00, uIdArmSelector00, uIdGadget00 ... |
| uIdGameover00 | +0x2683608 | YOU ARE DEAD, CONTINUE? YES / NO | cursor +0x50 (YES 0, NO 1) once +0x248 points at its YES / NO menu (about 4 s after the death); YES restarts the same round at once, NO goes "Now saving", "Save successful", STAGE |
| uIdResult30 | +0x2686750 | RESULTS (Kills, Max Combo, Score, Rank) | with uIdResultBg; "(+) End game" |
| uIdSave00 | +0x2686968 | saving | |
| uIdAlert00 | +0x2681440 | dialogs (always on line 0) | +0x1CC = 1 while one is up, +0x1C8 its id: 0x41 "Connect to the Leaderboards...?" (B = No), 0x0C "Now saving", 0x09 "Save successful" (A), 0x08 "Load successful" (A), 0x0F the autosave notice (A), 0x0D the "create new save data?" notice (A) |

**From boot to a No Mercy round (with the unlock):**

1. PRESS ANY BUTTON.
2. On a fresh save: create the save, then Save successful (A), then the autosave notice (A), then the privacy policy
   (B), then Save successful (A). On a later boot: Load successful, then the autosave notice.
3. The title. **Wait for `uIdTitle00+0x20A == 1` before pressing A.** An A while it is 0 starts the Prologue.
4. PLAY GAME, then EXTRA CONTENT (3), then NO MERCY (2), then SOLO (0), then the stage, then the character. The round
   starts about 15 s later.

**After a round:**

1. Phase 3, then RESULTS with dialog 0x41 (B).
2. + (End game), then "Now saving" (0x0C), then "Save successful" (0x09, A).
3. STAGE (`uIdStartUp31`) again.

## Controls (Switch default, from the game's own Controls screen)

| input | action |
|---|---|
| ZL | ready weapon / cover |
| ZL + ZR | shoot |
| ZL and ZR together | quick shot |
| ZR alone | physical attack (melee; tapping it killed zombies) |
| L-stick | move |
| R-stick | aim / camera |
| B | solo action / quick recover |
| B with L-stick down | quick turn |
| B with L-stick up | dash |
| R | health tablet |
| R + Y | reload tablet |
| Y | reload / pick up |
| X | item slot |
| A | partner action |
| D-pad | equipment |
| L | route guide |
| - | COMS menu (skip events) |
| + | pause |

gBox's keyboard pad (`yuzu_runtime.SWITCH_KEYS`) reaches all of them; Citron's default keyboard map is the same one.

## The driver (gbox/mercs/titles/re6_switch.py, 2026-10-27)

Measured in short private Citron sessions on the Spark (one at a time, no other agent emulator running, CPU under
65-70 %, Citron at nice 15), on top of the facts above:

- **The camera.** Every camera unit (`uCameraCtrl`, `uEventMotionCamera`, ...) carries uCamera's own properties,
  mCameraPos +0x60, mCameraUp +0x70 and mTargetPos +0x80 (registered by main+0x124DE70). The live one is the
  `uCameraCtrl` on move line 14, about 2 m behind Leon; the one on line 8 sits idle at (0, 200, -700). Its yaw
  (atan2 of target - position) is where the left stick walks him: lup walked him along -123.8 with the camera at
  -123.8. The right stick turns the camera about 174 deg/s with the gun down (rleft = a larger yaw; 0.5 s took -124.6
  to -37.6), and ZL raises the gun along it.
- **The laser sight.** `uLaserSight` sits on move line 22 (the effects line). +0x60 (also +0x100, +0x180, +0x450) is
  the dot, where the aim's ray lands. +0x440 (and +0x570) is the muzzle, about 190 cm up and 30 cm in front of him.
  +0x12C goes from about 0.3 to 0.86 while the gun is up. While aiming, the right stick moves the aim about 70 deg/s in
  yaw (1.0 s of rleft took the dot from -125.1 to -58.0) and faster in pitch.
- **The player's action.** +0x6E2 (u8; a copy at +0x6D2) names what he is doing: 0 free, 1 hit for a moment, 2 / 64 /
  66 a quick shot (64, 66, 2), 3 knocked down, and **8 then 9 / 25 held by a zombie** (its bite took 450 to 300). +0x598
  (u16) is the motion: 84 the aimed shot, 86 its end, 472 / 474 the quick shot, 4012 / 4018 only while held. The
  hold's prompt shows **B** (a live frame); one broke after 2.3 s of the left stick turned round with A mashed (state 8
  -> 1), so the bot now mashes B with the stick going round.
- **Dying.** Health 1 held for 8.5 s before 0 (the dying crawl); then the death animation and CONTINUE?.
- **The inventory.** 24 cItem slots of 0x28 bytes from player +0x5070 (vtable main+0x2875848; the Ghidra map below
  has all of them): +0x8 1 = in use, +0x9 the slot's index, +0xA the item id, +0xE s16 the rounds in the magazine (P_AMMO +0x507E is slot 0's, the gun in hand
  at the start), +0x14 the capacity (the Wing Shooter 18), +0x16 the carry limit. Slots 0-6 hold the weapons and 7-11
  the items. Slot 7's rounds (+0x5196, s16) are the health tablets (Leon 8 at the start; R took one). Chris: slot 0 his
  assault rifle (id 0x0F, 30 / 30), slot 1 id 0x07 (7 / 7), slot 2 id 0x19 (no magazine), slot 7 the tablets (id
  0x1D, 0 / 12: he starts with none, and R did nothing), slot 8 id 0x20 (0 / 3), slots 9-11 ids 0x13-0x15 (3 / 5,
  0 / 5, 0 / 5).
- **The shot's pace.** The Wing Shooter fires once per ZR press, and every press 0.15 s apart was a shot (20 in 3 s).
  Chris's assault rifle is automatic: ZR held for 2.5 s with the gun up spent 24 rounds (9.6 a second), and tapped,
  every press was a shot.
  The motion layer's speed (+0x5D8, 1.0) does not change it: 20 shots at x1, 20 at x4, 17 at x8 with the same
  presses. No game-side fire-rate multiplier (RE5's player time scale) has been found in RE6.

What the driver does with it:

- **Menus.** `screen()` names every screen from the units above, with cursors and targets. `step()` presses toward
  the target, then A, and presses A at the title only when +0x20A says the main menu is what it opens.
  `wandered()` stops a run whose title stays locked for 45 s (the unlock-on-load did not run). Live: the walk from
  "Load successful" to a round took 64 s, about 19 presses, every one confirmed in RAM.
- **CONTINUE?** YES by the cursor (REPLAY_ON_DEATH, as RE5 Switch): the same round again at once. The engine
  publishes the death's round boundary (terminal witness "dead"); the bot counts the replay as the next round
  (stats rounds, deaths_continued, round_start_via "dead/retry", a new _round_started) on its first tick alive with
  a full clock. The replay's load reports "dead" to the engine for up to 60 s so it is not counted as lost. With
  REPLAY_ON_DEATH off it answers NO, and "Now saving" hands the round back to the menus.
- **The brain.** It picks the zombie to fight by distance and angle from the camera's yaw, turns the camera to him
  (right stick, pulsed when close, the quick turn for one behind), raises the gun inside 25 deg, closes the laser's
  ray (muzzle -> dot) onto his chest and taps ZR while the dot is on a zombie or the ray runs through him. It kicks one
  at arm's length (ZR alone), takes the game's quick shot (ZL + ZR together) at one close in front, backs off when two
  come within 2.6 m, breaks holds read in RAM (B mashed, the stick round), takes a tablet (R) at half health with
  nobody at arm's length (at a third whoever is near) while he is free, counted when the count falls and pressed
  again 1 s after an ignored press, reloads an empty gun (Y), and walks to the next zombie along the camera. stats act / acts name each tick's decision for the watch panel.
- **The round's end.** Time up (phase 3) is "results" to the engine at once (the menus press nothing until the
  RESULTS unit is up), and result_ready closes the evidence when the RESULTS unit shows or the score holds still for
  1 s after 2 s, so MercMode's terminal witness carries tally_ready. The camera and laser units are found by class and
  checked on every read (the camera must ride within 6 m, the muzzle within 4 m); a replay that frees them makes the
  driver look again.
- **Mods** (gbox.mercs.titles.re6_switch_mods, the profile's playing_ops). infinite_ammo keeps every gun's magazine
  (the weapon slots 0-6) at its capacity, topped up from the snapshot; the items (the tablets, slots 7-11) are left
  alone. With infinite ammo, every bot press is a shot and none waits on a reload. The game-side fire rate, the
  stamina, the loadouts and the selects' state were found later in Ghidra (next section).

## The Ghidra map for live mods (2026-10-27, main 061D2A06CD700785E987C42CE2D72231)

Ghidra 12.1.4 headless on the Spark (the main ELF imported without analysis, functions decompiled where needed; a
Ghidra address is main + 0x100000) and a full linear disassembly (capstone). Every mod below is a data write into the
running game with a read-back; none patches code.

| what | where | how the game uses it | the op |
|---|---|---|---|
| seconds between shots | weapon table main+0x2962170: 48 records of 0x1A0 (the lookup main+0x10ECE20: the weapon type's low byte, alternate-mode records 0x29-0x2F); +0x1C f32 | main+0xB26F90 returns it (`ldr s8, [x0, #0x1c]` at main+0xB2701C, the only reader of +0x1C) and the fire action stores it in player +0x5AEC each shot (main+0x109A8C8); the player update counts +0x5AEC down by the frame time (main+0xBD3A90); the fire action's automatic loop (main+0x10982D0, weapon classes 0x20 / 0x40 of main+0xF42980 and the types 0x10D / 0x128) fires again once it is <= 0 with the trigger held (main+0x1098508..+0x1098528); a semi-automatic takes its next press once it is below the record's +0x20 (player +0x5590) | fire_rate multiplier=N: the build's value / N for every gun, never below 0.004 s; the grenades, the remote bomb, the knife and the melee weapons keep theirs |
| the combat gauge | player +0x42A0 f32, its maximum +0x42A4, the refill delay +0x42A8 | uIdLife's update (main+0x9FEA90) asks the player's vfunc 0x3F8 (main+0xBD9CD0) for the segments: int((gauge - 300) / 100); vfunc 0x400 gives the maximum's; the player's init (main+0xB18BF4) sets both from the character's level; every spend and refill goes through vfunc 0x3E0 (main+0xB209D0) | infinite_stamina: the gauge kept at its maximum |
| the starting loadouts | main+0x2890088: 16 entries of 0x74 (pointer array main+0x2890008); modes 4-7 read the arrays at +0x7C8, +0x1008, +0x17C8, +0x1F88 | the round set-up main+0x38C740 copies the entry of the costume's loadout index (the costume code table main+0x222B352, 5 bytes a code: character, variant, select id, costume, loadout index; costume 0 has its own entry, 1-3 share the second) into the game's per-player buffer. An entry: u16 id, 900 / 900, 0, 0xFF, 0, 0, 0; 7 (type, rounds) weapon pairs at +0x10; 8 item-wheel pairs at +0x2C; 9 start-list pairs at +0x4C (empty: 0, 0xFFFF). Types: 0x100 + the item id for weapons and items, 0x2xx ammo boxes | merc_loadout (round_ops, at every character select): the rocket launcher (0x117, Ada's first costume) swapped for a random magnum or shotgun, the remote bomb 0x116 and the hand / incendiary / flash grenades 0x113-0x115 at 5 each where the start list has room |
| the inventory | 24 cItem slots of 0x28 at player +0x5070; the getter main+0xB22BB0 finds a slot by its +0x9 index | indexes 0-6 the weapons, 7-14 the item wheel (the tablets 7, the spray 8, the grenades 9-11, the remote bomb 12), 15-23 the start list's items (grenade stacks, ammo boxes); +0xA u16 the type; +0xE s16 the count. The ammo consumer main+0xB25DC0 takes a throw from the smallest stack, frees a stack (and its object) at 0 and writes each wheel count back as its stacks' total. player +0x5064 is the equipped slot's index (the HUD's) | infinite_grenades: every grenade / remote bomb stack kept at 5, the wheel's count at the total |
| the stage select | uIdStartUp31: +0x50 the cursor, +0x54 = 10 stages listed, +0x58 the stages that can start | its update main+0xAAFB20 moves the cursor with up / down over all ten; A starts only a stage whose bit is set | the menus draw a random unlocked stage each visit |
| the character select | uIdStartUp32: +0x1CC the cursor, +0x1D0 / +0x1D4 the select ids listed; + 4 * id: +0x1F8 the costume shown, +0x21C the costumes listed; + 0x10 * id: +0x240 their costume indexes | its update main+0xAAD830: up / down the character, left / right the costume; the confirm writes the costume code to sGameMan +0x3CA4 (sGameMan +0x3C78 is the stage index, +0xCC the set-up's mode) | the menus draw a random listed costume each visit; a MercMode queue pick names the character / stage |
| auto QTE | cSystemInfo mTempData.mExOptAutoActBtn (+0x46B0, copy B +0x9BC0) | read by the QTE sites through sInfoMan (+0x46F8 from the manager) | not written (only the character mask is written in cSystemInfo) |

## Live rounds (2026-10-27, a private Citron NEO session on the Spark)

Seven minutes of the driver as MercMode runs it (gbox.mercs.engine.play_round with this driver, the menus between
rounds from RAM, the profile's playing_ops at each round start), on Leon in Urban Chaos with infinite ammo on:

| round | how it ended | kills | score | max combo | aimed shots (hits) | quick shots | kicks | holds broken |
|---|---|---|---|---|---|---|---|---|
| 1 | died, 62.6 s left | 27 | 26,240 | 23 | 53 (48, 91 %) | 32 | 37 | 13 |
| 2 (the YES replay) | died, 38.8 s left | 7 | 3,340 | 6 | 55 (44, 80 %) | 20 | 15 | 3 |
| 3 (the next YES replay) | playing at the 420 s stop, 41.7 s left | 19 | 5,700 | a 19 combo running | 46 (40, 87 %) | 28 | 28 | 7 |

In all: 154 aimed shots, 132 hits (86 %), no reloads (215 magazine top-ups), 74 backoffs. Both deaths were answered
YES and the replays were counted as the next rounds (stats rounds 2, deaths_continued 2, round_start_via
"dead/retry"). The HUD agreed with RAM in the frames: 027/300 and 00026240 at round 1's death, 007/300 and 00003340
at round 2's. Inventory at the round start (Leon): slot 0 the Wing Shooter (id 0x03, 18 / 18), slot 1 id 0x04 (8 / 8),
slot 7 the tablets (id 0x1D, 8 / 12), slot 8 id 0x20 (0 / 3), slots 9-11 ids 0x13-0x15 (0 / 5 each).

What the run showed:

- **Tablets.** At 1'14" left in round 1 the HUD showed one health block and the tablet count still at 7, after six R
  presses: presses in a crowd were ignored, and Leon died with tablets left. The driver now presses R only while his
  action byte says he is free, counts a tablet only when the count falls (stats tablets, tablet_presses,
  tablet_misses), presses again 1 s after an ignored press, and lowers the gun for it. This is unit-tested, not yet
  measured live.
- **The gun not coming up.** 171 times in seven minutes the laser was not up 0.9 s after ZL (stats reraise), about a
  third of the run. The bot now looks for the laser unit again after each one; the cause (hit reactions in the crowd,
  cover, another laser unit) is not measured.
- **The pace of fire.** The Wing Shooter fired 26 shots from 32 presses in 2.5 s (10.4 a second) with presses 0.04 s
  apart, so the press rate sets the pace up to about 10 a second.
- **No time scale among the most-read fields.** The player's f32 fields that main reads most (tools: loads by
  unsigned offset, at least 60 sites each) and that sat at 1.0, +0xD3C, +0x36D4, +0xD2C, +0xD6C, +0xBD0, +0x688 and
  +0x5D8, were each held at 3.0 for a 1.2 s walk. The game rewrote every one of them each frame, and none moved him
  faster than the baseline's own spread (70 to 240 cm/s).

The frames are in docs/evidence/re6-switch-driver/ (real frames from this session and the measurement sessions,
cropped to the game's window).

## What an RE6 Switch driver still needs

1. **A game-side fire rate.** Found: the weapon table's seconds between shots (the Ghidra map above).
2. **The tablet and the gun up, live.** Measure the confirm-and-retry tablet presses and the reraise cause in a
   round.
3. **The authoritative round timer** for writes. sGameMan +0x3DF0 is good to read but is copied every frame.
4. **Unmeasured pieces:** enemy states (a zombie's attack wind-up for counters), item drops and the time-bonus
   pickups, the staggered-zombie finisher prompt (a ZR icon over him), and whether a tablet heals at once (one was
   taken while a zombie held him).
5. **Eden.** All of this was measured on Citron NEO, the canonical Switch emulator for RE5 / RE6 (#1236). The guest
   layout is the game's; on Eden only the frame rate needs a run.
