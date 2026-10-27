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
| uIdGameover00 | +0x2683608 | YOU ARE DEAD, CONTINUE? YES / NO | YES restarts the round; Right + A = NO, then Save successful, then STAGE |
| uIdResult30 | +0x2686750 | RESULTS (Kills, Max Combo, Score, Rank) | with uIdResultBg; "(+) End game" |
| uIdSave00 | +0x2686968 | saving | |
| uIdAlert00 | +0x2681440 | dialogs (always on line 0) | +0x1CC = 1 while one is up, +0x1C8 its id: 0x41 "Connect to the Leaderboards...?" (B = No), 0x0C "Now saving", 0x09 "Save successful" (A) |

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

## What an RE6 Switch driver still needs

1. **A title driver** (`gbox/mercs/titles/re6_switch.py`) on the shared engine. It needs `snapshot()` from the tables
   above, `screen()` / `step()` for the menu walk, including the title wait on +0x20A and the results / Continue
   flows, a brain (ZL + ZR shots; RE6's melee is strong, so ZR alone at arm's length), and tests on these measured
   values. After that, a `profiles/gamedata/01002A000CD48000-ram.json`.
2. **The authoritative round timer** for writes. sGameMan +0x3DF0 is good to read but is copied every frame.
3. **Unmeasured pieces:**
   - the aim direction while aiming (the laser / camera);
   - an enemy's state and grab detection;
   - item drops;
   - the time-bonus pickups;
   - the `uIdGameover00` cursor;
   - the Load successful dialog id.
4. **Eden.** gBox's `SwitchLinuxAdapter` runs Eden, single-core for RE6 (`EDEN_TITLE_SETTINGS`), but everything here
   was measured on Citron NEO. The guest layout is the game's, not the emulator's. Only the way it is read depends on
   the emulator: NCE direct addressing through the HostMemory memfd, which both share. The integration check ran
   gBox's real `SwitchLinuxAdapter` memory path against Citron's maps. RE6's frame rate on gBox's Eden path still needs
   a run before MercMode leans on it.
5. **The MercMode edition.** `re_switch.normalize_preferences` accepts RE5 only. RE6 Switch No Mercy becomes a
   MercMode edition (map 01002A000CD48000) once the driver has logged a complete round.
