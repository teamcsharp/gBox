# Resident Evil 6 (Xbox 360, Xenia on the Windows PC)

Catalog id `0871eee3b68cdea3`, title 43430819, executable BH6MasterRelease. Tool: `re6` (gbox/re6_tool.py), offline
side in gbox/re6.py, item names/icons in gbox/re6_items.py, API in gbox/re6_api.py. Operator approved live memory work
on 2026-10-07 (offline / solo only, everything revertible: `re6 op=revert_all`). Status 2026-10-07; "verified" =
checked in the running game with frames (kept in `gbox-data/verify/re6/`).

## Boot profile "RE6: Everything unlocked" (default for every RE6 launch through gBox)

Two saved switches (`GET/POST /api/re6/settings`, both **on** by default; tool ops `everything_unlocked on=` /
`boot_to_title on=`):

* **everything_unlocked**: before Xenia starts (`re6_tool.pre_launch`, called by launch_game) the save gets the
  everything-unlocked template; the original save is backed up once (`runtime/re6/save_backup/43430819`) and
  `unlock_all on=false` / `revert_all` put it back. **Verified** from the operator's original save (unlock flag 0x10):
  Campaign > Chapter select shows Leon / Chris / Jake / Ada / Prelude all cleared, every chapter 1-5 with records on
  Amateur / Normal / Veteran / Professional, difficulty up to Professional; Extra Content: Agent Hunt + The Mercenaries;
  Mercenaries: all 3 stages of this disc (Urban Chaos, Steel Beast, Mining the Depths), all 9 characters (Leon, Helena,
  Chris, Piers, Jake, Sherry, Ada, Carla, Agent) with the DEFAULT / COSTUME tab (Leon pirate, Chris samurai seen; Chris
  EX played in a match). Skills, figures, emblems, titles and special features are in the template too (Special
  Features screen not looked at).
* **boot_to_title**: right after boot two 1-word code patches skip the RE6 logo movie after PRESS START (two code paths
  play it, see below), and with no real controller connected gBox presses START / A through PRESS START and the three
  notices (Xbox LIVE / loading content / storage) until the title screen. **Verified** through a real gBox launch (API
  `@launch`, i9-NUC worker): the title (RE6 logo + PRESS START) is up ~20 s after the launch job, no intro movie, no
  prologue (the save's unlock flag skips it). With a pad connected the player presses START once (the game binds to the
  controller that pressed it, so gBox doesn't press for them); the logo movie is still skipped.

Not on this disc (say so): No Hope difficulty, Mercenaries No Mercy, the DLC Mercenaries stages and retro costumes
(title-update / DLC / PC content; this is the July 2012 Xbox 360 build). Campaign-only characters (Deborah, Simmons,
...) can't be Mercenaries characters: the mode only has the 16 character/costume records (8 characters + EX + Carla);
a collection character can replace one of them with a swap mod (`characters op=use`, e.g. Mario in Leon's place).

## Tool ops

| op | what | status |
|---|---|---|
| `unlock_all [on=false]` (= `unlock`) | everything unlocked in the save + live in a running RE6 (save manager data and the save I/O file image, so menus keep it; the game saves it itself); on=false restores the original save (RE6 closed) | **verified** offline (fresh boot) and live (original save, op at the title, Mercenaries menu then fully unlocked) |
| `everything_unlocked on=` | unlock_all + saved as the boot default | |
| `boot_to_title on=` | saved switch, from the next start | verified (see above) |
| `give` / `set_loadout` (= `loadout_set`) / `auto` | Mercenaries start loadouts (table at 0x83C6B8F0, any item incl. story-only guns, any character record) | **verified**: Leon with Elephant Killer + Rocket Launcher shown at character select, EK fired in the match (6 -> 4 rounds) |
| `give_now item= amount=` | the game's own `uPlayer::setItem` (0x82B1C1C8) on the game thread; a gun the stage didn't load gets its resources loaded first; its ammo is added if the case has none; a gun already carried is topped up | **verified**: Lightning Hawk given in Urban Chaos to Chris (not in his loadout), switched to (d-pad), fired (7 -> 6), no freeze; ammo / herbs / grenades verified earlier |
| `remove_item slot=` | empties one slot: case items through setItem (count -2 = clear), a gun is marked not-owned (active 0, how the game keeps guns); the gun in hand is refused | **verified** (duplicate Lightning Hawk removed; in-hand refusal) |
| `set_slot slot= [item=] [amount=]` | changes one slot: amount only = rounds / stack size; item = replace (guns: the game picks the gun slot and the reply says which) | **verified** (9mm stack set to 99; Rocket Launcher replaced by Elephant Killer, landed in gun slot 5) |
| `live_inventory` | the player's 24 inventory slots right now + Life | verified |
| `weapon_classes` | item id -> weapon unit class (uWpNNNN) for every gun | |
| `infinite_health on=` / `infinite_ammo on=` | Life held at LifeMax / every gun and stack full (20 Hz) | verified (earlier) |
| `auto_qte on=` | every QTE prompt succeeds; ON by default at every boot | verified (earlier, grab counter) |
| `settings` | the saved switches: auto_qte, infinite_health, infinite_ammo, everything_unlocked, boot_to_title | |
| `build_mod`, `replace_enemies`, `characters op=use` | swap mods (Leon -> collection character, enemy families) | verified (earlier) |
| `revert_all` | loadout table back, holds/QTE/auto off, everything_unlocked + boot_to_title off, save restored (RE6 closed), gBox's RE6 mod folders deleted | |

Stable JSON for UI helpers (the universal inventory helper calls these through `re_inventory`): every op returns
`{"result": {...}}` with a human `message`; `live_inventory` -> `inventory: [{slot, id, name, count, max,
weapon_object}]`, `life: [hp, max]`; `give_now` -> `{live, slots: [slot], item, name, preloaded, ammo_added | topped_up}`
(`live: false` + `reason` = it went into the Mercenaries loadout instead); `remove_item` -> `{slot, removed: {id, name}}`;
`set_slot` -> `{slot, id, name, count}` or the give_now fields + `replaced`; `set_loadout` -> `{records, characters,
items}`. Errors raise with a plain sentence (e.g. "Elephant Killer is the gun in the player's hands right now: switch to
another weapon first").

UI: the session's **Loadout** button opens the RE6 dialog: Loadout (with **Give now**), Replace enemies, **Switches**
(Auto QTE / Infinite health / Infinite ammo toggles; saved per game, applied live). The agent can also offer them as
`offer_controls` toggles (tool `re6`, input `{session_id, op:'infinite_ammo', on:'{value}'}`).

Ctrl+click picker: the RE6 item list is `profiles/gamedata/0871eee3b68cdea3-items.json` (served at
`/api/gamedata/0871eee3b68cdea3-items`, every carried item with its id); the picker sends "this game's item id N" and the
agent calls `give_now item=N`.

## Weapons the stage didn't load (the give_now freeze, fixed)

A Mercenaries stage loads the resources of the chosen loadout's guns only. Every gun is a unit class `uWpNNNN` whose
models / motions / effects are the archive `nativeXenon/arc/X360/uWpNNNN.arc` (item id -> class from the game's own class
registry: each uWp DTI carries `7 << 24 | item code << 8` at +0x1C; table `WP_CLASS` in re6_tool, op `weapon_classes`).
setItem of another gun created a weapon whose resources never arrived, so the game waited forever (Elephant Killer in
Urban Chaos hung it). Two supported paths now:

1. **Loadout table + start the match from character select** (`set_loadout` / `give`): the stage then loads every gun of
   the record. Continue / Retry restart with the loadout the match started with (live give_now items are gone after a
   Continue), so a new loadout needs character select.
2. **Live** (`give_now` / `set_slot`): gBox first asks the game's resource manager for the archive on the game thread:
   sResource ([0x83D3E9EC]) vtable+0x30 = getResource(this, DTI rArchive 0x83D41424, "arc\\X360\\uWpNNNN", 1) - the call
   the game itself uses for its movies; it loads synchronously (~0.05 s for one gun) and returns the archive, which gBox
   keeps referenced (never released) so it stays resident; then setItem. Trampoline at 0x83C17C40 (constant code:
   r3 = *[0x83D6FD00]; ctr = (*r3)[[0x83D6FD04]]; bctr), path at 0x83D6FD40.

Campaign chapters: the same preload applies (same player structure), not tested in a chapter.

## Save file map (savedata.bin, 0x6000 bytes, u32 at 8 = word sum from 12)

The running game keeps the same bytes at `[0x83CA4F98] + idx * 0x8A04 + 0x30` (save manager; idx = u32 at +0x24, 0 for
player 1), and the file image it read at boot in the save I/O object `[0x83CA53F8] + 0xC910` (magic 0x12071800 at +0; the
menus re-read the manager's data from that image, so live edits must patch both). Accessors 0x83147080-0x8314A828 take
`manager + 0x3C` (file offset 0xC); helper offset + 0xC = file offset.

| file offset | what |
|---|---|
| 0x0BC | u32 mUnlockFlag (bits 0-8; 0xFFFFFFFF = prologue done, Campaign / Mercenaries / Agent Hunt open) |
| 0x0CC-0x6F8 | story / chapter / collection progress (byte arrays 25 / 50 / 301 + u32[301] targets) |
| 0x6F8 | u32 skill points (also total at 0x980) |
| 0x700 | skills owned, 97 bytes (3 = bought); 0x764 skill-set numbers, 0x76C skill sets [8][3], 0x914 Mercenaries skill sets |
| 0x974 / 0x978 | Mercenaries stage mask (10 bits) / character + costume mask (30 bits; 0x10101 = Leon, Chris, Jake) |
| 0x164C | campaign records [7 campaign characters: Leon, Helena, Chris, Piers, Jake, Sherry, Ada; index 7 is folded onto 6][5 chapters][5 difficulties] x 12 {u32 flags (1 cleared, 2, 4), u32 rank (0 best .. 5), f32 time} |
| 0x1FAC / 0x2098 / 0x20E4 | figures (200) / emblems (50) / titles (50) owned |
| 0x235C | Mercenaries records [solo, duo][10 stages][16 character/costume records] x 12 {u8 played, u8 rank (0 = best), u32 score, u8 kills, u8 combo, u8 costume, u8 partner} |
| 0x4AF0 | per-character Mercenaries inventories (8 x 0x70, same records as the loadout table) |

How the template was made: the executable has an unused debug routine 0x824D8800 (`this` = save manager) that unlocks
everything: unlock flag bits 0-8, chapter / story arrays, every skill, Mercenaries stage + character masks, missing
campaign records (rank 5, 19:59'59"), figures / emblems / titles, collection flags. gBox called it once in a match
(trampoline 0x83C17C00: r3 = [0x83CA4F98]; b 0x824D8800, through the give_now call mechanism), let the game write its
save, and stored the changed regions (`profiles/gamedata/0871eee3b68cdea3-unlock.json`, modes: OR masks, byte / u32
max, campaign records only where the player has none). Applying it never lowers anything the player has.

## Memory map (BH6MasterRelease)

* `sPlayer` = [0x83CA52FC]; +0x28.. player character pointers (+0x28 = player 1; Mercenaries and campaign).
* uPlayer: +0x18 cUnit mDeltaTime (reset by the game every frame), +0x50 position x/y/z, +0xF20 s16 Life, +0xF22
  s16 LifeMax, +0x3ED8 current weapon object, +0x3EE8 current slot, +0x3EF0 inventory: 24 `cItem` of 0x1C bytes
  (+4 active, +5 slot no, +6 u16 code = type<<8|id (1 weapon/grenade/recovery, 2 ammo = id-100, 3 herb = id-200),
  +8 mode, +9 mode max, +0xA u16 mNum[3], +0x10 u16 mMax[3], +0x18 weapon object). Slots 0-6 weapons, 7-12 grenade /
  recovery selectors, 15-23 case. setItem (0x82B1C1C8): count < -1 clears a non-weapon slot; a gun reuses an inactive
  record of the same gun. Weapon switch in game: d-pad right / left.
* Save manager [0x83CA4F98], save I/O [0x83CA53F8], resource manager sResource [0x83D3E9EC], DTI rArchive 0x83D41424.
* `sActionButton` = [0x83CA4380]: 8 ButtonMgr (0x330 bytes, at +0x3C), 2 ButtonUnit each (0x84 bytes at mgr+0x214):
  +8 active, +0xC prompt definition (def+0x24 type, def+0x30 id), +0x14 type, +0x1C button mask, +0x2C/+0x30 mash
  target / progress. Update = 0x82446078 (switch on type: press 0x82442180, hold 0x82442248, release 0x82442318, mash
  0x824423E8, timing 0x824424F0, ...).
* Mercenaries menu: stage page 0x82AD4160 (stage mask from 0x974), character list built by 0x82ACFBF8 from
  0x824CCB38 (= u32 0x978 | 0x10101); record writer at the end of a match 0x824C4080.

## How the live parts work

* **Calling game code** (give_now, preload, unlock routine): the player object gets a private copy of its vtable (at
  0x83D6F000) whose slot 9 (+0x24, called once per frame) points to a constant stub in the .text padding (0x83C17800).
  The stub restores the real vtable, calls the requested function with the player as `this` and args from 0x83D6FC00,
  then runs the original slot (the result word is written after the call: gBox waits for it). Lessons: guest stores to
  .text pages fault (data must be in .bss: 0x83D6E000-0x83D70000 is unused), Xenia constant-folds loads from read-only
  pages, the vtable copy must cover the whole table (512 entries), and Xenia compiles guest code once (a stub's bytes
  must never change after first use). Trampolines that change `this`: 0x83C17C00 (unlock routine), 0x83C17C40 (vcall).
* **Auto QTE**: a 1-word branch at 0x8244646C (the join after the per-type checks, r28 = success) to a stub at 0x83C16400
  that sets r28 = 1 unless [0x83D6FFF0] != 0 (runtime off switch) or the prompt is a context action (definition id
  0x1A-0x1F, 0x2A-0x2C, 0x79). Because Xenia compiles 0x82446078 the first time a prompt is processed, gBox writes the
  patch right after boot (`re6_tool.on_launch`, called by launch_game); switching on/off later is the memory flag. If the
  worker restarts while RE6 is already past its first prompt, the patch only takes effect at the next RE6 start (the op
  says so). Xenia's own patch files (`patches/*.patch.toml`) load ("Applying patch") but did not change memory on this
  build, so gBox doesn't use them.
* **Logo movie skip** (boot_to_title, written at boot like Auto QTE): the first-boot title sequence 0x823AF6A0 (state 10)
  loads "movie\re6logo" through sResource vtable+0x30 and, if that returns nothing, goes straight to the title: the bctrl
  at 0x823AF9B0 becomes `li r3, 0`. The opening scene 0x82FD7908 plays movie index 0/1 (bh6logo / re6logo; 2/3 are the
  title loops) through 0x82FD67A0, which already skips an index outside 0-3: `cmpwi r9, 0` at 0x82FD67B4 becomes
  `cmpwi r9, 2`. Leaving the movie file out of a mod folder does NOT work ("Disc Read Error").
* **Pressing to the title** (`_auto_title`): PRESS START takes only START and the notices only A, so until the save is
  read gBox alternates START / A every 1.2 s; the save I/O buffer gets the file (magic 0x12071800) when it was read, then
  5 more A (the storage notice; A does nothing on the title) and stop. Xenia's log can't be used (written in bursts).
  This Xenia build (May 2023) reads the physical keyboard only while it is the active window, so presses wait until then
  (fixed in xenia.py: a Xenia window docked in the gBox window reports itself as the foreground window).

## Not done / limits (honest)

* **Auto QTE** verified on the Mercenaries grab counter only; stick-rotate / mash grab escapes and cutscene prompts go
  through the same ButtonUnit code path (types listed above) but were not reached in a test (no campaign run).
* **Settings on the control plane**: `everything_unlocked` / `boot_to_title` are new keys of `/api/re6/settings`; the
  control plane only stores them after gbox.service is restarted with this code (not done: Spark sessions were running).
  Until then the worker keeps them in `runtime/re6/settings_local.json` (toggling through the re6 tool works).
* **First boot ever** (no save yet): the game creates the save; everything_unlocked applies from the next launch
  (or `unlock_all` live).
* **Ctrl+click world pickups** (identify + replace the clicked item): pickup classes are `uIt0000`, `uIt02xx-04xx`
  (DTI found), but no live pickup instance was captured and there is no camera projection for RE6 yet; not implemented.
* **Mario as Leon**: the swap mod `re6_mario` uses the SM64 Mario (collection slug `mario`, "Super Mario 64 (USA)"),
  verified in Mercenaries (frames). Speed: per-unit mDeltaTime is reset by the game every frame; scaling it every frame
  through a hook (factor 2-4) did not make the character faster (movement is animation root motion; measurements noisy,
  no speed-up). Mario's animation set: not feasible here — RE6 needs its own motion files (.lmt) for the Leon skeleton;
  SM64 animations would have to be retargeted and authored as MT Framework motions. Not done.
