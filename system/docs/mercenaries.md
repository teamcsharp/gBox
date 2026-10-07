# The Mercenaries, every release in the library

What gBox can do in each Mercenaries mode the operator owns: unlocks (A), collection-character swaps (B) and
the extra Mercenaries mods. Status as of 2026-10-07. "Verified" means checked in the running game with screenshots
(kept in `gbox-data/verify/mercenaries/`).

## Shared op names (use these in every Mercenaries release)

| what the operator says | op | notes |
|---|---|---|
| "unlock everything in Mercenaries" | `unlock_all` (on=false reverts) | characters, stages, modes (+ costumes/weapons where the game gates them) |
| "start with the Killer7 and a rocket launcher" | `merc_loadout character=<name\|any> items=[...]` | applied when a round starts |
| "triple my melee time bonus" | `merc_time_bonus multiplier=N [melee_only]` | |
| "punches explode" | `explosive_melee on=true kind=grenade\|flash\|rocket` | player-owned blast, never hurts the player |
| "punch them hundreds of feet in the air" | `super_melee on=true force=<feet> direction=up\|away\|both` | explodes on landing with explosive_melee |
| "machine-gun hand cannon" | `weapon_mod item=handcannon fire_rate=auto` (+ `infinite_ammo`) | |
| "spin while firing" | `auto_spin on=true speed=<deg/s> target=fire\|aim\|always` | |
| "turn faster while aiming" | `aim_turn_speed multiplier=N` | |
| "play as Aya" | `characters op=use character=Aya game=<release>` | builds/launches the swap mod |

Tools: `re_mods` (RE4 GameCube + Wii), `re6` (RE6 X360: today `unlock`, `give`/`set_loadout`/`auto`; aliases
`unlock_all` / `merc_loadout` would match this table), `re4r` (RE4 2023: `set`/`freeze`/hooks; blocked until the
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
| RE6 X360 (0871eee3b68cdea3) | Xenia PC | `re6 op=unlock` (prologue skip + modes); stage/character ranks not mapped | `re6_<slug>` (Aya, SM64 Mario verified) | loadouts (`give/set_loadout/auto`), **verified**: infinite_health, infinite_ammo, give_now (ammo/herbs/grenades mid-match), auto_qte (default on). See docs/re6.md |
| RE4 2023 Steam (steam-2050650) | native + REFramework | by the RE4R agent; blocked on Capcom's EULA (operator) | by the RE4R agent | live stats/hooks |

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

## Still to do

PS2 / X360 / UHD unlock flags; RE3 clear-save crafting (PSX memory card, DC VMU, GC card); Mercs 3D save edit;
Wii ports of the dispatcher ops; kick hook for explosive/super melee; world-item editing (`items_here` /
`item_replace` / `drop_table_set`) and the loadout pop-up (reuse the RE6 picker once it lands in the desktop app).
