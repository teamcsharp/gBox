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
| "turn faster while aiming" | `aim_turn_speed multiplier=N` | |
| "play as Aya" | `characters op=use character=Aya game=<release>` | builds/launches the swap mod |

Tools: `re_mods` (RE4 GameCube + Wii), `re5` (RE5 Gold PS3: `unlock_all` save edit, `status`, `revert`), `re6` (RE6 X360: `unlock_all` (= unlock, boot default), `give`/`set_loadout` (= loadout_set)/`auto`, live `give_now`/`remove_item`/`set_slot`), `re4r` (RE4 2023: `set`/`freeze`/hooks; blocked until the
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
| RE5 Gold Edition PS3 (e7ca89bbeb67360d, BLUS30491) | RPCS3 (Windows node) | **built, not live-checked**: `re5 op=unlock_all` = Bonus Features, Files, cutscenes, figurines, every chapter + Professional, BSAA emblems, Item Management (save edit with the published Game Genie offsets + checksum). Mercenaries characters/stages: not confirmed by the source | **missing** | none: no published address for the Mercenaries clock/combo on PS3 (the tool says so) |

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
