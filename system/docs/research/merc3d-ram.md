# Resident Evil: The Mercenaries 3D: runtime RAM

The build: the catalog's game `0ed22ae742e1b56b` ("(USA)" in its name, but the image inside the 7z is the EUR one:
product CTR-P-ABMP, title 0004000000038B00, exheader name `biomerce`). Its decompressed .code has sha256 `85a34c86...821be`,
the build `gbox.merc3d_exe` pins. It runs in RetroArch with the citra_libretro core, on the Spark (Linux aarch64,
Dynarmic's arm64 JIT) and on the Windows PCs.

## Reading guest memory

The citra core gives RetroArch no libretro memory map (`memory_descriptors = "false"` in its .info), so
`READ_CORE_MEMORY` and `READ_CORE_RAM` fail. `gbox/citra_memory.py` reads the guest straight from the RetroArch process:

- **FCRAM** is one 256 MiB `std::make_unique<u8[]>` block: an anonymous read-write mapping on Linux, a private
  VirtualAlloc block on Windows.
- The game's .code begins at guest `0x00100000`. Its first 64 bytes, from the image's own ExeFS, are found in that block.
- **Citra's page table** (`PageTable::pointers.raw[1 << 20]`, one host pointer per 4 KiB guest page) is the
  8-byte-aligned slot that holds that page's host address. Entry `0x100` holds the page, entry 0 is null, and entry
  `0x101` also points into FCRAM.
- After that, a guest read is `raw[va >> 12] + (va & 0xFFF)`.

Live on the Spark (2026-10-27): attaching takes 0.9 s. The mapped guest ranges are:

| Range | What |
|---|---|
| `0x100000`-`0x92F000` | text, ro, data, bss |
| `0x08000000` (+14 MiB) | heap |
| `0x14000000`+ | linear heap |
| `0x1F000000`+ | VRAM |

A scan of every object in the heap takes 1.7 s.

## Classes and singletons (static, from the .code)

MT Framework Mobile registers every class through `MtDTI::MtDTI(this, name, parent, size, ...)` at `0x478E44`. The
static initialisers pass the name with `add r1, pc, #imm`. A class's vtable has its `getDTI` at slot 5, and getDTI is a
3-word stub (`ldr r0, [pc]; bx lr; .word DTI`). That gives the class name of any object from its vtable: 1,989 DTIs,
listed by the agent's `alldti.py`.

The singletons' `mpInstance` (set by each DTI's newInstance or the constructor it tail-calls):

| Singleton | mpInstance | Vtable | Size |
|---|---|---|---|
| sPlayer | `0x8D5898` (a second registration: `0x8D56D4`) | `0x891DE0` | 0x2C |
| sEnemy | `0x8D5948` | `0x891A04` | 0x114 |
| sMission | `0x8D58D0` | `0x898350` | 0x130 |
| sUnit (an sGameUnit) | `0x8BE82C` | `0x880E40` | 0x1440 |
| sSaveDataMerce | `0x8D5888` | `0x880B4C` | 0x20E8 |
| sIDCockpit | `0x8D56B4` | | 0x18 |
| sBioGUI | `0x8B5CA8` | `0x87E3E4` | 0xB0 |
| sMain | (frame timing: `[0x8BE7E8]` +0x5C / +0x2C is the frame's delta) | | |

## The flow state machines (live)

The game's screens are flow states: one object per state class, held by a `cFlowStateManager` (vtable `0x87FBCC`):

| Offset | Field |
|---|---|
| +0x04 | the owner |
| +0x18 | the states array |
| +0x1C | the count |
| +0x20 | the current index |
| +0x24 | the previous index |

**The title** is aMerceTitle (vtable `0x87F0D8`, its manager at +0x1C). It has 12 states:

| Index | State |
|---|---|
| 0 | Init |
| 1 | Main |
| 2 | Final |
| 3 | SystemCheck |
| 4 | GoreWarning (A passes it) |
| 5 | CapcomLogo |
| 6 | PressStart (A) |
| 7 | Demo |
| 8 | MainMenu |
| 9 | Special |
| 10 | OptionMain |
| 11 | Dummy |

**The Mercenaries menus** use the cMerceMain* states: Init, Main, MissionSelect, CharacterSelect, DuoMenu, Record,
AutoSave, Final.

**The round** uses the cMerceStage* states: Init, Start, Main, End, Failed, YouAreDead, Final.

## The menus (live, both screens shown)

- **The title.** The gore warning takes A. The Capcom logo passes by itself. PRESS START takes START; A there is
  ignored, and the attract demo (cMerceTitleDemoState) follows until START.
- **The Mercenaries main menu** is aMerceMain in cMerceMainMainState. The top screen shows the character, the
  loadout and "LEVEL n-m". The keys:

| Key | What it does |
|---|---|
| R | opens the mission select (cMerceMainMissionSelectState, index 4) |
| L | opens the character select (cMerceMainCharacterSelectState, index 5) |
| START | launches the mission sMission names |
| B | autosaves ("Saved.", cMerceMainAutoSaveState) and drops to the title, so the driver never presses it there |

- **The mission select.** The bottom screen lists LV.1-LV.5. The GUI is uGUI_MissionSelectSub, the flow state's +0x8:

| Offset | Field |
|---|---|
| +0x328 | the level cursor (down/up) |
| +0x32C | how many levels are open (1 on a fresh save: LV.1) |
| +0x330 | the number of levels (5) |
| +0x334 | the mission tab (right/left), once A opened a level |
| +0x338 | the number of tabs (0 on the level list; LV.1 has 3: missions 1-1, 1-2, 1-3) |

  A on a tab writes `sMission.mMissionID = (level << 8) | tab` (0x5D9B4C maps level and tab to it) and returns to the
  main menu. B on the level list returns to the main menu.
- **The character select.** The GUI is uGUI_CharacterSelectSub; its cursor is +0x188 (right/left). On this save the
  roster shows Chris; the other slots are "?" silhouettes. The LV.1 mission page lists Chris, Jill and HUNK.

## Rounds

- **Mission 1-1** is the tutorial: Chris only, no enemies, 150 s. Time up without the objective ends in
  cMerceStageFailedState.
- **Mission 1-3** ("Take down all hostiles") has Majini from the start.
- **sEnemy's unit lists.** +0x1C is a list object: +0x24 the first node, +0x28 the last, +0x20 the sentinel the last
  node's link points back to. A node is `{vtable 0x8995B8, +0x4 prev, +0x8 next, +0xC vtable, +0x10 the unit}`. A unit
  sits in several lists (a second node 0x28 further on links it into the list at +0x5C).
- **The player's list** (sPlayer +0x18) uses a node with the unit at +0x14.

## The save (statics, checked against MER_SAVE.dat)

- The 8,400-byte save image sits in RAM at sSaveDataMerce+0x18.
- **Rank table.** sSaveDataMerce+0x60 is laid out `mode * 0x1E0 + costume * 0x1E + mission` (16 costumes, 30
  missions). 0xFF means never cleared. 0x4E7498 returns the best rank over the costumes.
- **"New" marks.** +0x1E60 holds the character select's "new" bits.
- **Bit fields.** +0x1E64 and +0x1E68 are flag words.
- **Ranks don't open levels.** Writing ranks for Chris did not open LV.2; the open-level count (+0x32C) comes from
  elsewhere. Clearing LV.1 in play opens the next level the native way.

## Controls (measured so far)

The left stick moves: up ran +398 cm in 1 s along +x while facing +x. R raises the gun.

## The player's body and the aim (statics, to confirm live)

- **Upper-body states.** The upper body runs its own states, named by DTI: Upper::WaitState, AimState, FireState,
  ReloadState, ChangeWeaponState, UseItemState and FullMoveWaitState.
- **uPlayer properties:** mActiveStatus +0xD48, mLowerStatus +0xD4A, mUpperStatus +0xD4B, mRotateStatus +0xD4C,
  mPlayerFlag +0xD64.
- **The laser sight** is uLaserSight, a uWeapon subclass: DTI 0x8DB4A8, vtable 0x8823F4, size 0x1080, class id
  0x80050A00. It is the aim ray (muzzle to dot) that the bot's "fire only on a confirmed line" needs.
- **Roster** (the uPl< ... > classes): Chris, Jill, HUNK, Rebecca, Barry, Claire, Wesker and Krauser. Each has a Cos2
  costume except Krauser.
- **Round end.** Missions such as 1-3 end on their objective ("Take down all hostiles"), often with time left, in
  cMerceStageEndState. The driver's `mission_complete` reports that state. MercMode accepts such a round as finished
  only for titles marked `native_complete` (merc3d).
