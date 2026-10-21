# The Mercenaries, every release in the library

What gBox can do in each Mercenaries mode the operator owns: unlocks (A), collection-character swaps (B) and
the extra Mercenaries mods. Status as of 2026-10-07. "Verified" means checked in the running game with screenshots
(kept in `gbox-data/verify/mercenaries/`).

## Shared op names (use these in every Mercenaries release)

| what the operator says | op | notes |
|---|---|---|
| "unlock everything in Mercenaries" | `unlock_all` (on=false reverts) | characters, stages, modes (+ costumes/weapons where the game gates them) |
| "start with the Killer7 and a rocket launcher" | `merc_loadout character=<name\|any> items=[...]` | applied when a round starts |
| "triple my melee time bonus" | `merc_time_bonus multiplier=N [melee_only]` | clock time from pickups |
| "triple / quadruple the combo bonus time" | `combo_time multiplier=3\|4` (RE4 GC) | how long a combo stays alive after each kill |
| "grenades don't hurt me" | `grenade_safe on=true` (RE4 GC) | your hand grenades' blast is player-owned |
| "I want to punch enemies" | `punch` (RE4) | a statement: RE4 has no free punch (see below) |
| "start with 200 handgun rounds" | `merc_loadout items=["handgun ammo:200"]` | `name:amount` per item; `merc_loadout_list` shows them |
| "unlock all secret / hidden content" (RE5 Gold) | `re5 op=unlock_all` (on=false reverts) | save edit, takes effect when RE5 loads its save |
| "punches explode" | `explosive_melee on=true kind=grenade\|flash\|rocket` | player-owned blast, never hurts the player |
| "punch them hundreds of feet in the air" | `super_melee on=true force=<feet> direction=up\|away\|both` | explodes on landing with explosive_melee |
| "machine-gun hand cannon" | `weapon_mod item=handcannon fire_rate=auto` (+ `infinite_ammo`) | |
| "spin while firing" | `auto_spin on=true speed=<deg/s> target=fire\|aim\|always` | |
| "turn faster while aiming" | `aim_turn_speed multiplier=N` (RE4); `re5_mods op=turn_speed multiplier=N` (RE5, aimed and not; "max" = 10) | |
| "fire 80 times faster, a pistol like a machine gun" (RE5) | `re5_mods op=fire_rate multiplier=80` | every weapon; semi-auto guns repeat while R1 is held |
| "unlimited ammo" (RE5) | `re5_mods op=infinite_ammo on=true` | the Gatling's no-ammo flag on every gun: the HUD's infinity sign |
| "more powerful bullets" (RE5) | `re5_mods op=bullet_damage multiplier=N` | firepower x N at every upgrade level (not yet seen live) |
| "play as Aya" | `characters op=use character=Aya game=<release>` | builds/launches the swap mod |

Tools: `re_mods` (RE4 GameCube + Wii), `re5` (RE5 Gold PS3: `unlock_all` save edit, `status`, `revert`), `re5_mods` (RE5 Gold PS3 live: `turn_speed`, `fire_rate`, `infinite_ammo`, `bullet_damage`, `revert_all`, `status`, `addresses`), `re6` (RE6 X360: `unlock_all` (= unlock, boot default), `give`/`set_loadout` (= loadout_set)/`auto`, live `give_now`/`remove_item`/`set_slot`), `re4r` (RE4 2023: `set`/`freeze`/hooks; blocked until the
operator accepts Capcom's EULA in Steam - gBox never accepts it).

## Matrix

| release (catalog id) | runs on | unlocks (A) | swaps (B) | other Mercenaries mods |
|---|---|---|---|---|
| RE4 GameCube disc 1/2 (78ab9efa2e310db4 / e42c9b780c07c437) | Dolphin (PC + Spark) | **verified**: `unlock_all` = 5 characters, 4 stages, Assignment Ada, Professional | **verified** before (Mario, Aya, Sonic, HUcast, Ryo, Cloud, Peach Ganados, Glitch, Melee...) | **verified**: merc_time_bonus (x3: +10 s -> +29.3 s), explosive_melee (knife), super_melee (launch arc + landing blast), auto_spin + machine-gun Handcannon + infinite ammo, aim_turn_speed (~3-4x); merc_loadout, spawn_multiplier, explosive_rounds (older) |
| RE4 Wii Edition (79c3a3eccb34fe62; the image is the PAL disc RB4P08) | Dolphin, Spark | **verified** (re_mods tool): The Mercenaries, 5 characters, 4 stages, Separate Ways, Assignment Ada, Movie Browser, Ada's Report, Professional | **verified**: Aya playable in Mercenaries (`re4wii_aya`); every collection character builds through `characters op=use` (same GC writer; gbox/re4wii.py extracted-disc mod tree) | **verified**: merc_time_bonus x3, weapon_mod tables, merc_timer_freeze, unlimited_health. Not ported: dispatcher ops (give/equip/merc_loadout/blasts/spawns), explosive/super melee, auto_spin, aim speed, infinite ammo |
| RE4 PS2 (109d8ee7747a7dd8) | pcsx2 libretro, Spark (boots, EE RAM readable at 0x0) | **missing**: system unlock flags not located in the PS2 build yet (pSys layout differs) | **missing**: PS2 BIN/pack writer | none yet |
| RE4 HD X360 (2364c91bf295d0c3) | Xenia on the PC (same route as RE6) | **not started** (needs a short PC test; flags will differ from GC) | **missing**: Xenon BIN/tiling writer | none yet |
| RE4 Ultimate HD PC 2014 (0a53cf740fc0f3f7) | native bio4.exe (PC) | **not started**: unlocks live in the Steam-era save (bio4 system data) | **missing**: UHD BIN/TPL in .udas (JADERLINK RE4 UHD tools can read/write them; licence to check before use) | none yet |
| "RE4 UHD" PS4 (4d8b13b6b5657313) | - | n/a: the catalog entry is a copy of the PC .bat in the PS4 folder pointing at a game folder that does not exist there; it is the PC game, not a PS4 dump | - | - |
| RE3 Nemesis PSX (53dd9167ed1df355) | pcsx_rearmed, Spark (RAM readable) | **missing**: Mad Jackal is offered only after loading a cleared game's "Next Game" save, not from the title; the GameShark "secret mode" halfword 0x800D1F32 (=FFE0) does not add it to the title menu (tested). Needs a crafted clear save or a patch of the load/select overlay | **missing**: PLD writer | none |
| RE3 Nemesis Dreamcast (b172dc2d23549d59) | flycast | **missing** (same save-gated unlock) | **missing** | none |
| RE3 Nemesis GameCube (2e2acf3bfe6e5fd3) | Dolphin | **missing** (same) | **missing** | none |
| Mercenaries 3D (0ed22ae742e1b56b) | citra_libretro, Spark (boots to the Capcom logo) | **missing**: unlocks are save-based (the 3DS save cannot be erased in game: back it up first); the core exposes no memory map to gBox, so live flags are not possible here | **missing**: MT Framework Mobile writer | none |
| RE6 X360 (0871eee3b68cdea3) | Xenia PC | **verified**: `re6 op=unlock_all` = boot default "Everything unlocked": all 3 stages on the disc, all 9 characters + EX costumes, Agent Hunt, every campaign/chapter/difficulty, skills (save template from the game's own unlock routine; live too). Boots to the title (logo movie skipped) | `re6_<slug>` (Aya, SM64 Mario verified) | **verified**: any weapon in any character's loadout (EK fired), give_now of guns the stage didn't load (resources preloaded; Lightning Hawk fired), remove_item / set_slot, infinite_health/ammo, auto_qte (default on). No Mercy / DLC stages not on the 360 disc. See docs/re6.md |
| RE4 2023 Steam (steam-2050650) | native + REFramework | by the RE4R agent; blocked on Capcom's EULA (operator) | by the RE4R agent | live stats/hooks |
| RE5 Gold Edition PS3 (e7ca89bbeb67360d, BLUS30491) | RPCS3 (Windows node; Spark arm64 in scratch) | `re5 op=unlock_all` = Bonus Features, Files, cutscenes, figurines, every chapter, BSAA emblems, Item Management (published Game Genie offsets; chapters, bonus features and emblems seen in the menus) **+ The Mercenaries Reunion, Desperate Escape, all 8 Reunion stages and all 8 characters (gBox's own offsets, **verified** live 2026-10-20)**. The original THE MERCENARIES (story-clear gate): not found yet | **missing** | RAM map `profiles/gamedata/BLUS30491-ram.json` (clock, score, kills, combo, combo window, player, enemies) and the Mercenaries engine driver `gbox/mercs/titles/re5_ps3.py` (aims and kills, live); **`re5_mods`** live: turn_speed, fire_rate x80, infinite_ammo (**verified** live 2026-10-21, applied at every round start), bullet_damage (written, not yet seen on an enemy) |

## RE4 notes

* `unlock_all` writes pSys+4 (u32) = FFFFFFFF; byte 0 alone = every extra game + Merc characters/stages
  (`mercenaries_unlock`). Saved with the next system save, so it persists; `on=false` clears it.
* RE4 Mercenaries has no costume choice (each Merc character has one outfit) and no weapon unlocks (fixed
  loadouts: `merc_loadout` changes them, GameCube).
* Time: every Mercenaries time pickup goes through pG+0x4F7E (GC) / +0x4F82 (Wii) (u16 seconds) and one `mulli`
  (x30 frames) in the clock routine; `merc_time_bonus` patches that immediate. RE4 never awards time for melee kills,
  so "melee only" has nothing separate to scale.
* Melee: knife hits reach the impact-effect call (attack class 0x10); explosive/super melee hook there and call the
  game's own grenade/flash sequence with the attack owner set to the player. Kicks/suplexes are context actions that
  do not pass through that call (a flash-stunned Ganado + KICK prompt was reproduced; no impact call was logged):
  hooking them needs the kick damage path, still to find.
* Wii port method (for the remaining ops): data tables match byte-for-byte; code is recompiled, so functions are
  matched with a feature-bag matcher (opcode classes + immediates + field offsets) and confirmed with Dolphin
  watchpoints. Scripts used: `scripts/re4gc_cave_build.py` (keystone, cave code) and the notes in gbox/re_games.py.
* Item lists for the Ctrl+click picker: `profiles/gamedata/<game_id>-items.json` for GC (both discs), Wii, PS2, X360
  and UHD (RE4 ITEM_IDs are shared across releases; Matilda / P.R.L. 412 exist outside the GC build).

## Combo time, safe grenades, punch, loadout amounts (#511 / #512, 2026-10-12)

Found by static analysis of the G4BE08 `main.dol` (read from the operator's disc image, capstone). Nothing here is
live-checked yet; every entry is in `gbox/re_games.py` `MERC_ADDRESS_TABLE` with its source and `live_checked: False`,
and `re_mods op=addresses` prints it. The Wii Edition (RB4P08) has none of them located: `combo_time` and
`grenade_safe` refuse there; other releases are refused by the RE4 version check.

| release | name | address | original | change | source | confidence |
|---|---|---|---|---|---|---|
| GC G4BE08 | COMBO_WINDOW | 0x802B17F0 (.sdata, r13-0x7F90) | 0x0000012C = 300 frames (10 s) | 300 x N | only reader `lwz r9,-0x7F90(r13)` at 0x8001EF38 in the add-kill routine 0x8001EEA8, stored to the combo timer (0x8021392C+0x2C) at 0x8001EF40; Jay007's Gecko "Infinite Combo Time (Mercenaries Mode)" `0401EF40 60000000` patches that same store | high |
| GC G4BE08 | GRENADE_OWNER_A | 0x8003B7BC | `38600000` li r3,0 | `806d98c4` lwz r3,-0x673C(r13) (= the player em) | owner argument of the area attack 0x80142FE8 (class 0x13) in the hand-grenade routine 0x8003B5FC; the owner rule is gBox's live evidence of 2026-10-07 (player-owned blast: HP 1632 -> 1632; owner 0: 1632 -> 912) | high (site), effect inferred |
| GC G4BE08 | GRENADE_OWNER_B | 0x8003B868 | `38600000` | `806d98c4` | same, second hand-grenade path (routine 0x8003B828) | medium-high |

* **combo_time** is what "triple / quadruple the combo bonus time" can mean in RE4: the window a combo stays alive
  after each kill (melee kills included). RE4 never puts time on the clock for melee or combos; clock time only comes
  from hourglasses (`merc_time_bonus multiplier=N`). `on=false` / multiplier=1 restores 300.
* **grenade_safe** leaves enemy dynamite alone. Not patched: the area attack at 0x8003A988 (routine 0x8003A8D4,
  classes 0x19/0x1F/0x20), probably the incendiary grenade's fire, unconfirmed.
* **punch**: not possible as a new button. Leon's only free melee is the knife (GC: hold L, then A). Kicks,
  roundhouses and suplexes (and Krauser / Wesker / HUNK moves) are context actions, offered only after an enemy
  staggers (headshot, knee shot, flash), and they do not pass through the hit routine gBox hooks (0x80143364; live
  2026-10-07: flash-stunned Ganado + KICK, no call). The op returns that statement and offers explosive_melee /
  super_melee on the knife, plus flashbang_loop to make kick prompts frequent.
* **merc_loadout** items take `name:amount` (`"handgun ammo:200"`, `"hand grenade:9"`); each becomes a record
  {character, flags, item id, amount} that gBox's wrapper runs after the game's own loadout routine 0x80018CC4
  (amount 0 = the game's default). `merc_loadout_list` shows the records and each character's default guns;
  `item_ids` is the item id table (RE4 ITEM_IDs, same on every release).

## RE4 GC level data: navigation map + hourglasses (2026-10-20)

`gbox/re4_navmap.py` reads a room straight from the game's files and gives the autoplay a top-down map
(`profiles/gamedata/re4_r400_navmap.json`, ~310 KB, committed; picture: `docs/evidence/re4-navmap/r400.png`, a
rendering of the decoded data, not a game frame). The full format notes are in the module docstring.

* Room archives `St4/r4xx.das` hold a compressed DAT (gBox decoder `das_unpack`, transcribed from main.dol 0x8018f5cc);
  inside: `SAT` player collision (triangles + attribute bits), `EAT` enemy collision, `AEV` events, `ITA` items,
  `RTP` enemy route graph. Spawns are in `etc/omake01.esl` (r400 / r402) and `etc/omake02.esl` (r403 / r404).
* Village r400: 5 Time Bonus hourglasses (item 0x73, the clock gets amount x 30 frames: +90, +90, +90, +30, +30 s)
  and 3 Combo Bonus hourglasses (item 0x75, 30 s of minimum-points kills), each of the latter inside an
  action-button AEV zone - these are the RAM's "small interactive events"; the fourth (AEV[9], type 0x10) is the
  watchtower ladder. The combo hourglass on the left building's loft (y 3000, ITA[23]) has no on-foot way up in the
  SAT; the enemy route graph climbs there at about (-21243, -453) -> (-22220, -1788).
* The map is a layered 200-unit grid (storeys per cell; free / near a wall / vault / wall). Fences and window sills
  (SAT bits 0x20 / 0x40 under a 0x400 invisible wall) are vault edges ("JUMP OVER"); that reading is inferred from
  the collision rules and geometry - check one in game. Closed buildings (walled in the SAT, no door events) count as
  unreachable.
* API for the bot: `stage("r400")`, `path(st, start, goal)` -> `Waypoint(x, y, z, action)` (action `vault` = press A
  at the fence / window, `ladder` = climb), `tour(st, start)` -> hourglass visiting order (exact up to 10),
  `st["grid"].state_at(x, z, y)`, `sight(st, a, b)`; every hourglass event has a `stand` point to walk to.
* Regenerate (disc read only, a GCZ is read in place, ~20 s):
  `python -m gbox.re4_navmap --iso "<RE4 (USA) (Disc 1).gcz>" --room r400 --out profiles/gamedata/re4_r400_navmap.json
  --png docs/evidence/re4-navmap/r400.png`. r402 / r403 / r404 build the same way.

## RE5 Gold Edition (#1104)

RE5 keeps unlocks in its save (DATA0.DAT), so `re5` edits the save, with the Game Genie for PS3 codes published in
Apollo Save Tool's patch database (`bucanero/apollo-patches`, `PS3/BLUS30491.savepatch`; `BLES00816` has the same
lines). RPCS3 stores PS3 saves decrypted under `dev_hdd0/home/<user>/savedata/BLUS30491*/`. Code types 0/1/2 = 8/16/32-bit
big-endian write at the file offset.

| group (default = all but points/money) | Game Genie lines (DATA0.DAT offsets) |
|---|---|
| bonus_features | `200000A4 FFFFFFFF` `200000A8 FFFFFFFF` `200000AC FFFFFFFF` |
| files | `10000082 0000FFFF` |
| cutscenes | `2000008C FFFFFFFF` `20000091 FFFFFFFF` |
| figurines | `20000084 FFFFFFFF` `1000008A 0000FFFF` |
| chapters (+ Professional) | `0000010B 000000FF` `1000010E 0000FFFF` `10000116 0000FFFF` |
| emblems | `20000118 FFFFFFFF` |
| item_management | `20000094 FFFFFFFF` |
| points / money (only when asked) | `200000E4 05F5E0FF` / `200000E0 05F5E0FF` |
| checksum (always) | `dwadd(10,4BBF)` written at 0x8: sum of the big-endian u32 words 0x10..0x4BBF |

The tool checks that checksum rule against the save as the game wrote it before touching anything (mismatch =
encrypted copy or another layout: refused), keeps `DATA0.DAT.gbox-backup`, and `on=false` / `op=revert` restores it.
Unknown serials (original RE5 BLUS30270, Japanese BLJM60199) are refused. Mercenaries characters / stages are not
named by the source. No published address exists for the Mercenaries clock, time bonus or combo timer on PS3 (RPCS3's
patch database has only an FPS unlock for BLUS30491 01.01), so `merc_time` / `combo_time` are refused with that reason;
RE6 (X360) has the same gap, and re6 keeps its verified unlock_all and loadouts.

## RE5 Gold: The Mercenaries Reunion unlock, RAM map and bot (2026-10-20)

Found live on the Spark with a scratch RPCS3 (arm64 0.0.43; RE5 Gold app 01.01). Every save change below was loaded from
the title screen (RPCS3 rereads the host DATA0.DAT at each load) and read off the menus; frames in
`docs/evidence/re5-merc-bot/` (real frames of that RPCS3 display).

* **Where the save is:** Gold writes `savedata/BLUS3027010AE/DATA0.DAT` (the original RE5's name). `re5` looks there too.
* **The Gold block** (DATA0.DAT 0x4BC0-0x566F) comes after the checksummed part, so no checksum covers it:
  * s32 **0x4BC0 > 0** opens DESPERATE ESCAPE and THE MERCENARIES REUNION (1, 2, 0x3E9 and 0x7FFFFFFF open them; -1
    does not). Found by bisecting the block's 682 zero words.
  * u32 **0x5640** = Reunion stage bits (fresh save 1 = Public Assembly; 0xFF = all 8 stages).
  * u32 **0x565C** = Reunion character bits (fresh save 4; 0xFF = all 8 characters).
  * The Reunion records (stage x character score and rank) are in the same block: a 0x01 fill showed 16,843,009 SS,
    0xFF showed -1 D.
* `re5 op=unlock_all` sets them in the `mercenaries_reunion` group (0x4BC0 to at least 1, the masks OR 0xFF).
* **Not found yet:** the original THE MERCENARIES on PLAY GAME. It is not in the published codes, not in any zero word
  of 0x30-0x5670 set to 1 / 0x7F7F7F7F / FFFFFFFF, and not in 0x80-0xDF set to FF.
* **RAM:** RE5 is MT Framework. The managers are singletons with static instance pointers beside their class
  descriptors. An object's class name is what its vtable's getDTI (slot 5) returns. The map has sPlayer (player
  position, rotation, action, health), sEnemy (the enemy array), cGameSys through sBioMain +0x182D4 (clock, kills,
  combo, combo window, score), and sBioCamera +0x104 (the camera's eye and look-at).
  The aim pitch (player +0x1AA0) does not scale linearly with the camera. The bot closes its aim on the camera's look
  ray instead (the crosshair over the shoulder).
* **Bot:** `gbox/mercs/titles/re5_ps3.py` is the Mercenaries engine's title #2.
  * It targets the nearest Majini in front, skipping crows (health 1), rooftops and the dead.
  * It turns with the right stick, aims with L1, puts the crosshair on the head and fires with R1.
  * It steps back when a Majini is on top of it and runs to them when far.
  * From the title into Reunion, and between rounds, it reads the screen from the interface's own units. sUnit
    keeps every unit in move lines (+0x24 + 0x20 per line: +0xC the line's first unit; a unit's +8 is the next).
    Out of a round all lines are walked (the title's menus are not all in the interface lines), and units are told
    apart by their vtables. Each row below was found live (2026-10-21) by pressing one key at a time on a gBox
    session and reading what changed:

    | RAM | Screen | Press |
    |---|---|---|
    | uIdTitle00 +0x1F8 = 0x48, no uIdTopMenu00 | PRESS START | START |
    | uIdAlert00 +0x3C = 0x22 | "... without signing in. Sign in?" | circle (Continue) |
    | uIdAlert00 +0x3C = 0x13 | "Loading content." | none |
    | uIdAlert00 +0x3C = 0x08 | "Load successful." | cross (OK) |
    | uIdStartUp00, cursor +0x44 | the main menu (PLAY GAME = 0) | D-pad to 0, cross |
    | uIdStartUp01, cursor +0x44 | PLAY GAME (EXTRA CONTENT = 7) | up from 0 wraps to 7, cross |
    | uIdStartUp01 +0x174 = 1, cursor +0x188 | EXTRA CONTENT (THE MERCENARIES REUNION = 3) | D-pad to 3, cross |
    | uIdStartUp29 | Reunion's title (START first) | cross |
    | uIdStartUp29 +0x174 = 1 | SOLO / DUO / SPLIT SCREEN (SOLO first) | cross |
    | uIdStartUp21 | STAGE SELECT | cross (the last stage played) |
    | uIdStartUp22 | CHARACTER SELECT | cross (the last character played) |
    | uIdNowLoading00, uIdSaving00 | loading, saving the records | none |
    | uIdTopMenu00 / uIdTitle00 / uIdTitle02 otherwise | the title's menus in between | none |
    | none of these, the clock at 0 | the results | START |
    | uIdMerce00 (with the player) | a round (the HUD) | the bot plays |

    * Health 0 in a round is "You Are Dead - Continue?": cross (Yes).
    * The driver presses nowhere else, so it never starts a story game.
    * `mercs.menus` in the map is the driver module (`screen` / `step` / `wandered`).
    * PLAY GAME's "?????" entry (index 6) is most likely the locked original THE MERCENARIES.
  * The deployment: RE5's mercs block says `"ready": true`, so `mercs_bot` plays it through the engine
    (`title_engine`) while the engine's global READY still waits on RE4's A/B. A plain Autoplay on an RE5 session
    runs it in the worker: the boot / menus from `screen` / `step`, each round through `play_round`.
    * The RAM comes through one open /proc/<pid>/mem (`mercs_bot.ProcMem`).
    * Live: `mercs_bot.play` from the branch, run against a gBox RE5 session, walked the results and the selects
      and played its rounds.
  * Hangs: RPCS3 on the Spark (arm64) can freeze mid-round: the game's clock stops while RPCS3 keeps busy (twice on
    2026-10-21, about an hour into a session each time).
    * The driver gives a round up when its clock stands still for 60 s: its `screen` says "loading", so the engine
      ends the round "lost", and the deployment ends the run hung (gBox's own recovery takes it from there).
    * The scratch session runner did the same by itself: stop the agent session, launch it plainly, walk it from
      the title back into Reunion. It recovered the second hang that way with no help.
  * Grabs: player action 4 (+0x845) means a Majini is holding him, with the "Break free" prompt (left stick) on
    screen. The driver's prompt source answers "wiggle", which the engine mashes (left / right) until he is free.
  * Prompts come from sActionButton. +0x34 bit 1 is set while a prompt is up (bit 0: the weapon is raised).
    +0x2A4 points to the cActionButton on screen: +0x04 its owner, +0x14 its kind, +0x40 the Majini it acts on.
    These were decoded from prompts logged with a frame each:

    | Button | Prompt | The bot |
    |---|---|---|
    | the player's, kind 3, +0x40 = a Majini | melee finisher: "Hook", "Uppercut" (square) | presses square, the gun lowered |
    | the player's, kind 2 | the stage: "Jump over", ladders (square) | leaves it |
    | a Majini's (player action 4) | his grab: "Break free" (left stick) | wiggles |

    Live (2026-10-21, a gBox session): the bot pressed square on finisher prompts and Chris hit the Majini. Each
    finisher kill gave the round **+5 seconds** ("+05 Sec." on the clock, counted as `bonus_s`). Frames:
    `gbox-finisher-pressed-plus-5-sec.jpg`, `gbox-finisher-2-plus-5-sec.jpg`.
  * Time bonuses: the hourglasses (uOm0100; uOm0100.arc's model is "sunadokei_360", hourglass). There are 9 in Public
    Assembly, units of sUnit's move line 12 ("OM") with vtable 0x015EF5E0. Each is a small golden hourglass on the
    ground under a light pillar (frames).
    * +0x30 is its position, +0x250 a bounding sphere (centre 13 cm up, radius 28 cm).
    * +0x194 is 0x0090..01 on 2 of them and 0x00A0..01 on the other 7.
  * Routes: RE5's own navigation mesh, from RAM (`gbox/mercs/titles/re5_nav.py`). The chain is sAI [0x017BD4C8]
    +0x24 cAIPathFinding, +0x14 rNavigationMesh: points at +0x70 / +0x74, triangles at +0x78 / +0x7C (32 bytes each:
    3 vertex indices, links to the neighbours with the shared edge).
    * Public Assembly: 1,638 points and 2,187 triangles, one connected mesh over every level.
    * A* over the triangles, waypoints through the shared edges' midpoints.
    * Live: routes from the start roof to all 9 hourglasses in about 1 ms each. The bot ran a 70 m route across the
      stage in 16 s and took drops with the stage's square prompt.
    * The mesh is the AI's, and some of its drops and climbs are Majini-only (no prompt for the player). The bot
      waits 3 s at one, then avoids it and routes around (it found the ramp instead of a 2 m drop).
  * Taking a time bonus: standing at the hourglass and facing it, the game shows **"□ Time bonus"** (a real frame:
    `docs/evidence/re5-merc-bot/gbox-time-bonus-prompt.jpg`). It is the player's own stage prompt (sActionButton,
    kind 2).
    * What doesn't take one: the Gatling's fire on it from its level at 4-6 m (bullets at its base), low knife
      slashes at 1 m, or walking over it.
    * The bot walks up to it along the navmesh, faces it, and presses square when the prompt shows (`Bot._take`).
      It leaves the bonus for 30 s if the prompt does not come.
    * For now it only goes for a bonus within 15 m on its own level, with no Majini within 7 m. The navmesh's
      crossings between levels are partly Majini-only, so the far ones cost more time than they give.
    * A time bonus taken live is still to come (the clock's jump is counted as `bonus_s`).
  * Live in scratch on Public Assembly with Chris (Heavy Metal), whose Gatling has infinite ammo: three rounds back
    to back (2026-10-21, the Spark's scratch RPCS3) gave 14, 20 and 17 kills; 4,460, 7,460 and 6,260 points; best
    combo 7. A health freeze was on for those rounds (a scratch-only tool, never part of the driver). The first
    version (aim from the player's pitch) got 2-4 kills a round.
  * Live in a gBox session (2026-10-21, the Spark): gBox's RPCS3, the save unlocked with `re5 op=unlock_all`, no
    health freeze. The bot pressed through the Reunion screens itself and played 9 rounds back to back:
    * kills 17, 14, 11, 14, 15, 18, 14, 15, 14;
    * points 6,380, 5,140, 3,490, 4,740, 4,860, 8,640, 4,480, 5,110, 4,780;
    * best combo 12, no deaths.

    RAM came from the session's RPCS3 (/proc, read only) and the presses went through the session's input API.
    In round 10 the emulator froze (the game's clock stopped at 1:48, RPCS3 still busy).
  * Not yet: a time bonus taken live, and routes between levels the player can take (ladders and stairs, not the
    Majini-only drops). Also the enemies' attack states, and item pick-ups ("□ Pick up", the same stage prompt).

## RE5 Gold: live mods, applied at every Mercenaries round start (2026-10-21)

`re5_mods` (gbox/re5_mods_tool.py) writes the running game's data, every write read back, the originals kept
(`revert_all`; a relaunch is the full revert too). The RE5 profile's `mercs` package is `turn_speed x2`,
`fire_rate x80`, `infinite_ammo`, applied in the worker by `mercs_bot` at `select_player` before each run (the
operator's request: "80x fire rate ... even with a pistol he's able to fire it like a machine gun with unlimited
ammo and unlimited rotation speed"). Found in the executable dump (BLUS30491 app 01.01, PPU-a9b0ce57...) and live on
the Spark's RPCS3; the frames in `docs/evidence/re5-mods/` are real frames of the agent session bd055f... that day.

* **Turn speed:** sParameter (the global tunables object, pointer at 0x017FEB08): +0x2C walk/run turn deg/s (110),
  +0x68 / +0x6C the stick-to-turn range (0.2 / 1.2, also the stand-still turn animation's speed), +0x2D0 aim pitch
  deg/s and +0x2D4 aim yaw deg/s (57.9; the aim controller 0x86E1EC scales it by the zoom). Live: the bot's aim yaw
  rate p90 85 -> 140 -> 231 deg/s and the stand-still turn 150 -> 250 -> 398 deg/s at x1 / x2 / x3. Default x2
  because the bot aims on 50 ms pulses (4.5 deg a pulse at x3); the operator can pick x3 or "max" (x10).
* **Fire rate:** the weapon upgrade table (0x01823E1C, 0x1E8 per weapon id, group 1 = frames between shots per
  upgrade level: M92F 26, VZ61 5, M29 45) / N, the definition table's interval offset (0x01817530 + id*0x140 + 0x90:
  -10 handguns, +5 machine guns) set to 0, and the fire action's only frames-per-second constant (0x0169E098, 60.0,
  the re-fire timer of semi-auto weapons) x N. Live x80: Barry's handgun 1.6 -> 8.1 casing ejections/s and 3 -> 6
  kills per 40 s; Sheva's P226 0.65 -> 6.7/s and 0 -> 4 kills in the round's last 41 s, the bot still tapping R1.
* **Infinite ammo:** the definition table's +0x14 = 1, the Gatling's own "needs no ammo" flag, on every gun and
  grenade (knives untouched): the can-fire check (0x9D4DE4) passes and the consume check (0x9D3C70) skips the
  round, the HUD shows the infinity sign. Live: rounds 28/30 and 4/4 untouched through whole phases of fire.
* **Bullet damage:** upgrade group 0 (firepower per level, M92F 150...) x N. Written and read back, not yet seen
  on an enemy's health (next window).
* **Loadout:** the Mercenaries loadout templates are static data (0x01730024: 30 blocks of 12 records x 0x2C, one
  per character / costume, Barry = 24, Chris Heavy Metal = 18; a record = item id 0xTTII, count, -1 x3, grid
  position, in hand, packed upgrade levels, flags). The round start copies the picked character's block into the
  inventory (player+0x22E0, 24 slots x 0x30: +0x8 id, +0xC rounds, +0x10 capacity, +0x20 in hand, byte +0x2D in
  use) and builds the weapons, so `loadout` just changes the ids: every gun (not the knives) becomes a random
  powerful campaign weapon (M500 0x11B, Lightning Hawk 0x11A, Hydra 0x119, Gatling 0x115, RPG 0x10D, PSG-1 0x11C,
  AK-74 0x11D, M3 0x116, grenade launcher 0x10C, Dragunov 0x120), levels reset to 0. Live (the RE5 agent's
  session, its bot reading the inventory at round start): Barry's M29 -> S&W M500 5/5 and Dragunov -> Hydra 4/4,
  built by the game, no crash. Weapon switching needs no write: the d-pad quick-select equips the edge slots.
* **Randomizer:** `random_cheats` = fire x80 always, turn x2 or x3, damage x1 / x3 / x10, infinite ammo, the
  loadout re-drawn (3 in 4); what it picked is the op's "telemetry", which `mercs_bot` shows as stats["cheats"].
  The RE5 profile's `round_ops` runs it at every CHARACTER SELECT visit (the one-time `package` stays).
* **Not done yet**: grenade bullets (the bullet-type word in the definition record is the candidate; needs one live
  shot), self-immunity (the explosive's damage path: not located offline).

## Live checks (to run once, then flip `live_checked`)

1. combo_time, RE4 GC in Dolphin, in a Mercenaries stage: `re_mods op=status` shows `merc_combo_window_x: 1`; run
   `re_mods op=combo_time multiplier=3`; kill two Ganados quickly; `re_mods op=status` right after the second kill
   reads `merc_combo` = 2, and reading 0x8021392C+0x2C gives about 900 (it was about 300 before), counting down 30/s.
2. grenade_safe, RE4 GC: note `hp` in `re_mods op=status`; `re_mods op=grenade_safe on=true`; `give item="hand
   grenade"`, throw one at your own feet: `hp` unchanged and nearby enemies still die. `on=false`, throw again: HP drops.
3. loadout amounts, RE4 GC: `re_mods op=merc_loadout character=any items=["handgun","handgun ammo:200"] on=true`, start
   a Mercenaries run: `re_mods op=list` shows Handgun Ammo 200.
4. RE5 Gold, RPCS3: `re5 op=status` (expect `checksum_ok: true`); `re5 op=unlock_all`; restart RE5 from gBox; Bonus
   Features shows every entry, Chapter Select lists every chapter with Professional, Library > Files is complete.
   Then open The Mercenaries and record which characters/stages are available. `re5 op=revert` returns the save.

## Still to do

PS2 / X360 / UHD unlock flags; RE3 clear-save crafting (PSX memory card, DC VMU, GC card); Mercs 3D save edit;
Wii ports of the dispatcher ops; kick hook for explosive/super melee; world-item editing (`items_here` /
`item_replace` / `drop_table_set`) and the loadout pop-up (reuse the RE6 picker once it lands in the desktop app).
