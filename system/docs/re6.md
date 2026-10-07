# Resident Evil 6 (Xbox 360, Xenia on the Windows PC)

Catalog id `0871eee3b68cdea3`, title 43430819, executable BH6MasterRelease. Tool: `re6` (gbox/re6_tool.py), offline
side in gbox/re6.py, item names/icons in gbox/re6_items.py, API in gbox/re6_api.py. Operator approved live memory work
on 2026-10-07 (offline / solo only, everything revertible: `re6 op=revert_all`). Status 2026-10-07; "verified" =
checked in the running game with frames.

## Tool ops

| op | what | status |
|---|---|---|
| `unlock` | save edit: forced prologue skipped, Campaign / The Mercenaries / Agent Hunt open | verified (earlier) |
| `give` / `set_loadout` / `auto` | Mercenaries start loadouts (table at 0x83C6B8F0, any item incl. story-only guns) | verified (earlier) |
| `infinite_health on=` | Life (uPlayer+0xF20) held at LifeMax (+0xF22) for every player, 20 Hz | **verified**: ~100 s among zombies, bar stays full, never died (died within ~60 s without) |
| `infinite_ammo on=` | every gun's mNum = mMax, ammo stacks full, carried grenades full (sprays/herbs untouched) | **verified**: 6 shots, count stays 18/18, reserve 150 |
| `give_now item= amount=` | the game's own `uPlayer::setItem` (0x82B1C1C8) called on the game thread | **verified** for ammo, herbs, grenades mid-match (case slots appear with the right counts). Guns: see below |
| `live_inventory` | the player's 24 inventory slots right now + Life | verified |
| `auto_qte on=` | every QTE prompt succeeds; ON by default at every boot through gBox | **verified** on the Mercenaries grab counter (RT prompt): 37 kills with no input in one match; off = 0 kills |
| `settings` | saved switches (`GET/POST /api/re6/settings`: auto_qte, infinite_health, infinite_ammo) | |
| `build_mod`, `replace_enemies`, `characters op=use` | swap mods (Leon -> collection character, enemy families) | verified (earlier) |

UI: the session's **Loadout** button opens the RE6 dialog: Loadout (with **Give now**), Replace enemies, **Switches**
(Auto QTE / Infinite health / Infinite ammo toggles; saved per game, applied live). The agent can also offer them as
`offer_controls` toggles (tool `re6`, input `{session_id, op:'infinite_ammo', on:'{value}'}`).

Ctrl+click picker: the RE6 item list is `profiles/gamedata/0871eee3b68cdea3-items.json` (served at
`/api/gamedata/0871eee3b68cdea3-items`, every carried item with its id); the picker sends "this game's item id N" and the
agent calls `give_now item=N`.

## Memory map (BH6MasterRelease)

* `sPlayer` = [0x83CA52FC]; +0x28.. player character pointers (+0x28 = player 1; Mercenaries and campaign).
* uPlayer: +0x18 cUnit mDeltaTime (reset by the game every frame), +0x50 position x/y/z, +0xF20 s16 Life, +0xF22
  s16 LifeMax, +0x3ED8 current weapon object, +0x3EE8 current slot, +0x3EF0 inventory: 24 `cItem` of 0x1C bytes
  (+4 active, +5 slot no, +6 u16 code = type<<8|id (1 weapon/grenade/recovery, 2 ammo = id-100, 3 herb = id-200),
  +8 mode, +9 mode max, +0xA u16 mNum[3], +0x10 u16 mMax[3], +0x18 weapon object). Slots 0-6 weapons, 7-12 grenade /
  recovery selectors, 15-23 case.
* Weapon classes: item code -> class via the class hash table at 0x83CE3B70 (key 7<<24 | code<<8): 0x103 uWp1012,
  0x104 uWp1020, 0x108 uWp1031 (Elephant Killer), 0x10B uWp1050 ...
* `sActionButton` = [0x83CA4380]: 8 ButtonMgr (0x330 bytes, at +0x3C), 2 ButtonUnit each (0x84 bytes at mgr+0x214):
  +8 active, +0xC prompt definition (def+0x24 type, def+0x30 id), +0x14 type, +0x1C button mask, +0x2C/+0x30 mash
  target / progress. Update = 0x82446078 (switch on type: press 0x82442180, hold 0x82442248, release 0x82442318, mash
  0x824423E8, timing 0x824424F0, ...).

## How the live parts work

* **Calling game code** (give_now): the player object gets a private copy of its vtable (at 0x83D6F000) whose slot 9
  (+0x24, called once per frame) points to a constant stub in the .text padding (0x83C17800). The stub restores the
  real vtable, calls the requested function with the player as `this` and args from 0x83D6FC00, then runs the original
  slot. Lessons: guest stores to .text pages fault (data must be in .bss: 0x83D6E000-0x83D70000 is unused), Xenia
  constant-folds loads from read-only pages, the vtable copy must cover the whole table (512 entries), and Xenia compiles
  guest code once (a stub's bytes must never change after first use).
* **Auto QTE**: a 1-word branch at 0x8244646C (the join after the per-type checks, r28 = success) to a stub at 0x83C16400
  that sets r28 = 1 unless [0x83D6FFF0] != 0 (runtime off switch) or the prompt is a context action (definition id
  0x1A-0x1F, 0x2A-0x2C, 0x79). Because Xenia compiles 0x82446078 the first time a prompt is processed, gBox writes the
  patch right after boot (`re6_tool.on_launch`, called by launch_game); switching on/off later is the memory flag. If the
  worker restarts while RE6 is already past its first prompt, the patch only takes effect at the next RE6 start (the op
  says so). Xenia's own patch files (`patches/*.patch.toml`) load ("Applying patch") but did not change memory on this
  build, so gBox doesn't use them.

## Not done / limits (honest)

* **Guns mid-match**: setItem creates the weapon object, but the stage only has the models of the chosen loadout; a gun
  that isn't loaded makes the game wait forever for its file (seen: Elephant Killer in Urban Chaos hung the game). So
  `give_now` only gives guns the player already carries; other guns go into the Mercenaries loadout table (pick the
  character again / Retry). In the campaign, guns the chapter loads would work but are not checked.
* **Auto QTE** verified on the Mercenaries grab counter only; stick-rotate / mash grab escapes and cutscene prompts go
  through the same ButtonUnit code path (types listed above) but were not reached in a test (no campaign run).
* **Mercenaries stage / character / costume unlocks**: in the save (ranks/scores per stage and character), layout not
  mapped yet; the 360 version has 3 stages on the disc menu (Urban Chaos + two "???"), characters Leon/Chris/Jake shown.
  No Mercy is PC-only (not on the 360 disc).
* **Ctrl+click world pickups** (identify + replace the clicked item): pickup classes are `uIt0000`, `uIt02xx-04xx`
  (DTI found), but no live pickup instance was captured and there is no camera projection for RE6 yet; not implemented.
* **Mario as Leon**: the swap mod `re6_mario` uses the SM64 Mario (collection slug `mario`, "Super Mario 64 (USA)"),
  verified in Mercenaries (frames). Speed: per-unit mDeltaTime is reset by the game every frame; scaling it every frame
  through a hook (factor 2-4) did not make the character faster (movement is animation root motion; measurements noisy,
  no speed-up). Mario's animation set: not feasible here — RE6 needs its own motion files (.lmt) for the Leon skeleton;
  SM64 animations would have to be retargeted and authored as MT Framework motions. Not done.
