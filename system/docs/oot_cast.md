# Ocarina of Time: the whole cast (`gbox/oot_cast.py`, `oot_swap.build_cast`)

The operator's ask: "I need to be able to replace the entire cast in OoT". The operator's ROM is the NTSC 1.0 USA
cartridge (game id `446e8e442d726e31`); the catalogue and the writer also read 1.1 and 1.2 (Rev B), and the
owned-ROM tests pass on both 1.0 and 1.2.

## Use it

* **Chat / agent**: "replace the entire cast of Ocarina of Time with Sonic Adventure 2 characters".
* **Tool**: `characters op=cast_swap target_game=446e8e442d726e31 source=SA2 [slots=all|main|npcs|sages|enemies|bosses|
  <slot list>] [mapping=auto|random|by_role] [seed] [assignments=[{slot, character}]] [strict_cutscenes=true]
  [plan_only=true] [launch=true]`.
* **Desktop / web**: right-click Ocarina of Time -> **Replace entire cast with...** (the cast swap dialog,
  `docs/cast_swap.md`).

The result is ONE file mod (`cast_ocarina_of_time_<source>_<digest>`): a rebuilt ROM with the same file name as the
operator's game, so the save file carries over. Each slot gets a row in the report: `built` (with `mode`, triangles,
bytes reused, growth), `failed` (with the reason), or `skipped` (a slot that can't be rebuilt, with the reason).

## The cast catalogue (`oot_cast.CAST`, measured in `gbox/oot_cast.json`)

Every slot names an object file (gObjectTable id), the skeleton inside it, and the actors that draw it. The names,
offsets and Flex / Normal types come from the zeldaret/oot decompilation (`assets/xml/objects/*.xml`,
`include/tables/actor_table.h`, `object_table.h`). They are used as documentation only. `python -m gbox.oot_cast ROM
--write` measures every slot on a ROM and stores the results in `gbox/oot_cast.json`:

* the skeleton header at the offset: its limb count, LOD spacing, the limbs that draw, and Flex or Normal (from the
  Flex `dListCount` byte). Every slot matches the decomp type.
* whether each actor's overlay names the skeleton (data words plus `lui`/`addiu` pairs);
* the humanoid roles the retarget uses, or why it falls back to the rigid ride;
* the bytes the old model frees: its lists, vertices and textures;
* every scene that loads the object.

The snapshot also has a `scan` section: every actor -> profile object -> skeleton in the ROM (102 skeletal objects).

`mode`:

* **retarget**: the donor is fitted limb by limb onto the slot's own skeleton (`sm64_swap.retarget` with the slot's
  roles). Every limb keeps its animation.
* **rigid**: a creature. Its wings, legs or leaves are not arms, so the donor rides the limb that draws most of the
  body, whole. It moves and turns with the body, but its limbs don't animate.
* **refused**: the slot is listed so the reason is on record, and the cast swap skips it.

`reuse KB` is the number of bytes the old model frees for the new one.

| slot | character | kind | actors | object | skeleton | limbs | type | mode | reuse KB | appears in (first 3) |
|---|---|---|---|---|---|---|---|---|---|---|
| `player` | Link (adult and child) | player | Player | object_link_boy (+ object_link_child @0x2CF6C) | gLinkAdultSkel @0x377F4 | 21 | flex/LOD | retarget | 48 / 43 | everywhere |
| `kokiri_boy` | Kokiri boys (Know-It-All Brothers, shopkeeper) | npc | En_Ko | object_km1 | gKm1Skel @0xF0 | 15 | flex | retarget | 14 | Kokiri Forest, Know-It-All Brothers' House, Mido's House |
| `kokiri_girl` | Kokiri girls and Fado (Fado's head in object_fa) | npc | En_Ko | object_kw1 | gKw1Skel @0xF0 | 15 | flex | retarget | 7 | Kokiri Forest, Twins' House, Lost Woods |
| `saria` | Saria | sage | En_Sa, Demo_Sa | object_sa | gSariaSkel @0xB1A0 | 16 | flex | retarget | 24 | Saria's House, Sacred Forest Meadow, Chamber of the Sages |
| `mido` | Mido | npc | En_Md | object_md | gMidoSkel @0x7FB8 | 16 | flex | retarget | 21 | Mido's House, Kokiri Forest, Lost Woods |
| `zelda_child` | Princess Zelda (child, castle courtyard) | npc | En_Zl4 | object_zl4 | gChildZeldaSkel @0xE038 | 17 | flex | retarget | 37 | Temple of Time, Castle courtyard (Zelda), Hyrule Field |
| `zelda_child_escape` | Princess Zelda (child, escape and ocarina cutscenes) | npc | En_Zl1 | object_zl1 | gChildZelda1Skel @0xF5D8 | 17 | flex | retarget | 40 | Castle courtyard (Zelda) |
| `zelda_adult` | Princess Zelda (adult) | sage | En_Zl2, En_Zl3 | object_zl2 | gZelda2Skel @0x10D70 | 14 | flex | retarget | 34 | Ganon's Tower collapse, Ganondorf's lair |
| `sheik` | Sheik | npc | En_Xc | object_xc | gSheikSkel @0x13510 | 16 | flex | retarget | 38 | Ice Cavern, Temple of Time, Kakariko Village |
| `impa` | Impa | sage | Demo_Im | object_im | gImpaSkel @0xF788 | 16 | flex | retarget | 34 | Chamber of the Sages, Castle courtyard (Zelda) |
| `hyrule_soldier` | Hyrule soldiers and castle guards | npc | En_Heishi1-4 | object_sd | gEnHeishiSkel @0xBAC8 | 16 | normal | retarget | 23 | Market Entrance, Back Alley |
| `dampe` | Dampe (and his ghost) | npc | En_Tk, En_Po_Relay | object_tk | gDampeSkel @0xBE40 | 17 | flex | retarget | 20 | Graveyard, Windmill and Dampe's grave |
| `happy_mask_salesman` | Happy Mask Salesman | npc | En_Ossan | object_os | gHappyMaskSalesmanSkel @0x4658 | 8 | flex | retarget (no legs) | 3 | Happy Mask Shop |
| `running_man` | Running Man | npc | En_Mm, En_Mm2 | object_mm | gRunningManSkel @0x5E18 | 15 | flex | retarget | 7 | Hyrule Field, Lost Woods |
| `cucco_lady` | Anju, the Cucco Lady | npc | En_Niw_Lady | object_ane | gCuccoLadySkel @0xF0 | 15 | flex | retarget | 19 | Kakariko Village, Impa's House |
| `cucco_girl` | Market girl chasing the cucco | npc | En_Niw_Girl | object_gr | gNiwGirlSkel @0x9948 | 16 | flex | retarget | 31 | Market (day) |
| `windmill_man` | Guru-Guru | npc | En_Fu | object_fu | gWindmillManSkel @0x6C90 | 15 | flex | retarget | 20 | Windmill |
| `roof_man` | The man on the Kakariko roof | npc | En_Ani | object_ani | gRoofManSkel @0xF0 | 15 | flex | retarget | 17 | Kakariko Village |
| `graveyard_kid` | Graveyard kid | npc | En_Cs | object_cs | gGraveyardKidSkel @0x8540 | 15 | flex | retarget | 20 | Graveyard |
| `carpenter_boss` | Mutoh | npc | En_Toryo | object_toryo | object_toryo_Skel_007150 | 16 | flex | retarget | 24 | Kakariko Village, Gerudo Valley |
| `carpenters` | The carpenters | npc | En_Daiku, En_Daiku_Kakariko | object_daiku | object_daiku_Skel_007958 | 16 | flex | retarget | 20 | Thieves' Hideout, Kakariko |
| `carpenter_son` | Carpenter's son | npc | En_Hs, En_Hs2 | object_hs | gCarpenterSonSkel @0x6260 | 15 | flex | retarget (no legs) | 22 | Lost Woods, Kakariko |
| `shooting_gallery_man` | Shooting gallery owner | npc | En_Syateki_Man | object_ossan | gObjectOssanSkel @0x9B38 | 8 | flex | retarget (no legs) | 24 | Shooting Gallery |
| `bombchu_bowling_girl` | Bombchu Bowling girl | npc | En_Bom_Bowl_Man | object_bg | gBowlingGirlSkel @0x6EB0 | 10 | flex | retarget (no legs) | 19 | Bombchu Bowling Alley |
| `poe_collector` | Poe Collector | npc | En_Gb | object_ps | gPoeSellerSkel @0xC220 | 11 | flex | retarget (no legs) | 35 | Market guard house |
| `scientist` | Lake Hylia scientist | npc | En_Mk | object_mk | object_mk_Skel_005DF0 | 12 | flex | retarget (no legs) | 19 | Lakeside Laboratory |
| `carpet_merchant` | Carpet merchant | npc | En_Js | object_js | gCarpetMerchantSkel @0x5EA0 | 12 | flex | retarget (no legs) | 22 | Haunted Wasteland |
| `bean_salesman` | Bean salesman | npc | En_Ms | object_ms | gBeanSalesmanSkel @0x3DC0 | 8 | flex | retarget (no legs) | 13 | Zora's River |
| `fishing_pond_owner` | Fishing pond owner | npc | Fishing | object_fish | gFishingOwnerSkel @0x85F8 | 8 | flex | retarget (no legs) | 14 | Fishing Pond |
| `great_fairy` | Great Fairy | npc | Bg_Dy_Yoseizo | object_dy_obj | gGreatFairySkel @0x1C450 | 27 | flex | retarget | 37 | Great Fairy fountains |
| `malon_child` | Malon (child) | npc | En_Ma1 | object_ma1 | gMalonChildSkel @0x8460 | 18 | flex | retarget | 24 | Market, Hyrule Castle, Lon Lon Ranch |
| `malon_adult` | Malon (adult) | npc | En_Ma2, En_Ma3 | object_ma2 | gMalonAdultSkel @0x8D90 | 18 | flex | retarget | 26 | Lon Lon Ranch, Stable |
| `talon` | Talon | npc | En_Ta | object_ta | gTalonSkel @0xB7B8 | 16 | flex | retarget | 32 | Hyrule Castle, Lon Lon Ranch, Kakariko |
| `ingo` | Ingo | npc | En_In | object_in | gIngoSkel @0x13B88 | 19 | flex | retarget | 30 | Lon Lon Ranch |
| `darunia` | Darunia | sage | En_Du, Demo_Du | object_du | gDaruniaSkel @0x122A8 | 17 | flex | retarget | 30 | Goron City, Fire Temple, Chamber of the Sages |
| `goron` | Gorons (also Biggoron, Link the Goron) | npc | En_Go, En_Go2, Demo_Go | object_oF1d_map | gGoronSkel @0xFEF0 | 17 | flex | retarget | 24 | Goron City, Death Mountain |
| `zora` | Zoras | npc | En_Zo, En_Diving_Game | object_zo | gZoraSkel @0xBFA8 | 19 | flex | retarget | 29 | Zora's Domain, Lake Hylia |
| `king_zora` | King Zora | npc | En_Kz | object_kz | gKzSkel @0x86D0 | 11 | flex | retarget (no legs) | 10 | Zora's Domain |
| `ruto_child` | Princess Ruto (child) | npc | En_Ru1 | object_ru1 | gRutoChildSkel @0x12700 | 16 | flex | retarget | 25 | Jabu-Jabu's Belly, Zora's Domain |
| `ruto_adult` | Princess Ruto (adult) | sage | En_Ru2 | object_ru2 | gAdultRutoSkel @0xC700 | 22 | flex | retarget | 36 | Water Temple, Chamber of the Sages |
| `nabooru` | Nabooru | sage | En_Nb | object_nb | gNabooruSkel @0x181C8 | 18 | flex | retarget | 39 | Spirit Temple, Desert Colossus |
| `rauru` | Rauru | sage | En_Rl | object_rl | object_rl_Skel_007B38 | 10 | flex | retarget (no legs) | 25 | Chamber of the Sages |
| `gerudo_guard` | Gerudo guards (purple) | npc | En_Ge2 | object_gla | gGerudoPurpleSkel @0x8968 | 21 | flex | retarget | 24 | Gerudo's Fortress, Gerudo Valley |
| `gerudo_white` | Gerudo (white) | npc | En_Ge1 | object_ge1 | gGerudoWhiteSkel @0x330 | 15 | flex | retarget | 21 | Gerudo's Fortress, Training Ground |
| `koume` / `kotake` | Koume, Kotake | npc | En_Tr | object_tr (one object, two skeletons) | gKoumeSkel @0x11688 / gKotakeSkel @0xC530 | 26 | flex | retarget | 19 / 11 | Desert Colossus, Twinrova's lair |
| `skull_kid` | Skull Kid | npc | En_Skj | object_skj | gSkullKidSkel @0x5F40 | 18 | flex | retarget | 17 | Lost Woods |
| `kaepora_gaebora` | Kaepora Gaebora (perched) | npc | En_Owl | object_owl | gOwlPerchingSkel @0x100B0 | 15 | flex | rigid | 14 | Hyrule Field, Lake Hylia |
| `stalfos` | Stalfos | enemy | En_Test | object_sk2 | gStalfosSkel @0x7C28 | 60 | normal | retarget | 17 | Forest / Spirit / Shadow Temple |
| `stalchild` | Stalchild | enemy | En_Skb | object_skb | gStalchildSkel @0x41F8 | 19 | normal | retarget | 10 | Hyrule Field |
| `moblin_spear` / `moblin_club` | Moblins | enemy | En_Mb | object_mb (two skeletons) | gEnMbSpearSkel @0x8F38 / gEnMbClubSkel @0x14190 | 27 | flex | retarget | 16 / 11 | Sacred Forest Meadow |
| `iron_knuckle` | Iron Knuckle | enemy | En_Ik, Demo_Ik | object_ik | gIronKnuckleSkel @0x1E178 | 29 | flex | retarget | 0 | Spirit Temple, Ganon's Tower |
| `lizalfos` / `dinolfos` | Lizalfos, Dinolfos | enemy | En_Zf | object_zf (two skeletons) | gLizalfosSkel @0x104B8 / gDinolfosSkel @0x6690 | 48 | normal | retarget | 15 / 24 | Dodongo's Cavern, Spirit Temple |
| `wolfos` / `white_wolfos` | Wolfos | enemy | En_Wf | object_wf (two skeletons) | gWolfosGraySkel @0x9690 / gWolfosWhiteSkel @0x3BC0 | 21 | flex | retarget | 13 / 12 | Forest Temple, Ice Cavern |
| `redead` / `gibdo` | ReDead, Gibdo | enemy | En_Rd | object_rd (two skeletons) | gRedeadSkel @0xE778 / gGibdoSkel @0x3DD8 | 25 | flex | retarget | 23 / 10 | Shadow Temple, Bottom of the Well |
| `gerudo_fighter` | Gerudo fighter (red) | enemy | En_GeldB, En_Ge3 | object_geldb | gGerudoRedSkel @0xA458 | 23 | flex | retarget | 28 | Thieves' Hideout |
| `dark_link` | Dark Link | enemy | En_Torch2 | object_torch2 | gDarkLinkSkel @0x4764 | 21 | flex/LOD | retarget (Link's roles + idle) | 16 | Water Temple |
| `flare_dancer` | Flare Dancer | enemy | En_Fd, En_Fw | object_fw | gFlareDancerSkel @0x5810 | 26 | flex | retarget | 15 | Fire Temple |
| `deku_scrub` | Deku Scrub | enemy | En_Dekunuts | object_dekunuts | gDekuNutsSkel @0x3268 | 24 | normal | rigid | 1 | Deku Tree, Kokiri Forest |
| `business_scrub` | Business Scrub | npc | En_Dns, En_Shopnuts | object_shopnuts | gBusinessScrubSkel @0x41A8 | 17 | flex | retarget | 7 | Dodongo's Cavern, Jabu-Jabu's Belly |
| `skulltula` | Skulltula (and Gold Skulltula) | enemy | En_St, En_Sw | object_st | object_st_Skel_005298 | 29 | normal | rigid | 8 | Deku Tree, Dodongo's Cavern |
| `poe` / `poe_sisters` / `big_poe` | Poes | enemy | En_Poh / En_Po_Sisters / En_Po_Field | object_poh / object_po_sisters / object_po_field | gPoeSkel / gPoeSistersSkel / gPoeFieldSkel | 20 / 11 / 9 | normal | retarget (no legs) | 2 / 2 / 6 | Graveyard, Forest Temple, Hyrule Field |
| `armos` | Armos | enemy | En_Am | object_am | gArmosSkel @0x5948 | 13 | normal | retarget (no legs) | 20 | Dodongo's Cavern, Spirit Temple |
| `octorok`, `keese`, `tektite`, `peahat`, `dodongo`, `wallmaster`, `dead_hand`, `anubis`, `guay`, `deku_baba` | the creature enemies | enemy | their own actors | their own objects | see `gbox/oot_cast.json` | 7-37 | normal / flex | rigid | 1-16 | dungeons and fields |
| `ganondorf` | Ganondorf | boss | Boss_Ganon | object_ganon | gGanondorfSkel @0x100E8 | 25 | flex | retarget | 14 | Ganondorf's lair |
| `ganon` | Ganon | boss | Boss_Ganon2 | object_ganon2 | gGanonSkel @0x24570 | 46 | flex | retarget | 42 | Ganon's arena |
| `phantom_ganon` | Phantom Ganon | boss | Boss_Ganondrof | object_gnd | gPhantomGanonSkel @0xC710 | 25 | normal | retarget | 18 | Phantom Ganon's lair |
| `twinrova` | Twinrova (merged) | boss | Boss_Tw | object_tw | gTwinrovaSkel @0x30C20 | 43 | flex | retarget | 35 | Twinrova's lair |
| `king_dodongo`, `bongo_bongo_head` | King Dodongo, Bongo Bongo | boss | Boss_Dodongo, Boss_Sst | object_kingdodongo, object_sst | 48 / 44 limbs | 48 / 44 | normal / flex | rigid | 25 / 23 | their lairs |
| `epona` | Epona | npc | En_Horse | object_horse | gEponaSkel @0x9D74 | 47 | normal / **Skin** limbs | refused | - | Skin_Draw blends vertices between limbs every frame; the writer rebuilds Standard / LOD limb lists only |
| `navi` | Navi | npc | En_Elf | gameplay_keep | gFairySkel | - | - | refused | - | drawn from gameplay_keep, which every actor and Link share; `op=overlay` can still draw over her |
| `like_like` | Like Like | enemy | En_Rr | object_rr | none | - | - | refused | - | no skeleton: En_Rr builds the body from lists and matrices in code |
| `hylian_townsfolk` | Market / Kakariko people | npc | En_Hy | object_aob, ahg, boj, bba, bji, cne, cob | per type | - | flex | refused | - | En_Hy draws a head from one object on a body from another, per type; that table isn't catalogued yet |

Shared objects change everyone who draws them: all Kokiri boys, all Gorons (Biggoron is the same object scaled), all
Zoras, all soldiers, every Skulltula including the gold ones. Slots that share one object file are written into the
same file one after the other: Koume / Kotake, the two Moblins, Lizalfos / Dinolfos, Wolfos / White Wolfos, ReDead /
Gibdo. Each slot keeps the other skeleton's lists and textures.

## How a cast is built (`oot_swap.build_cast`)

1. **Targets** (`oot_cast.slot_spec` + `oot_swap.slot_target`):
   * Humanoids are posed with an animation from their own object (or the shared `object_os_anime` /
     `object_zl2_anime*`). Their roles come from `guess_roles` (joint positions). When that fails, `topo_roles` reads
     the limb tree: the chest is the limb with two arm chains and a head, and the hip is the nearest limb above it
     with two more chains (legs). Robe or counter NPCs have no legs, and their donor's legs fold into the hip.
   * Dark Link takes Link's roles and idle pose.
   * Creatures (`oot_cast.CREATURES`) take the rigid ride.
2. **Fit** (`fit`): the existing Link / NPC code. Blender decimates the model down to 1500 triangles (and steps lower
   if needed). Textures are RGBA16 at most 64x32, then smaller, then flattened, until the new data fits the budget.
3. **Bytes** (`oot_cast.npc_regions`): the old model's limb lists, vertices and textures are reused first. Anything
   in them is kept if another skeleton's lists, a list the actors' code names, or an address the code holds uses it.
   The actors' code is read from data words and `lui`/`addiu` pairs, which the older `npc_reclaim` missed. Lists that
   the actor's code draws in place of a limb's own are branched to that limb's new list (`alt_body_dls`: an open
   mouth, a turned head). This covers the En_Ko head lists. Fado's head lives in `object_fa`, so it gets the new head
   encoded into `object_fa` itself (`extra_heads`).
4. **Object space** (`oot_cast.contexts`, `growth_plan`):
   * Every (scene, layer, room) of the ROM is read from gSceneTable, the scene / room headers, their alternate
     headers and the object lists. The bytes left in the room's object space are computed from 1000 KB (1050 / 1150 KB
     in the boss rooms Object_InitContext names), minus gameplay_keep, the sub-keep, Link's object and the room's
     objects. This puts child Kokiri Forest at 128 KB free, as measured before.
   * Growth is shared out max-min fair. Every object grows by the same amount until a room is full or it reaches its
     cap (36 KB for an NPC, 40 KB for Link). Each slot then fits into its reusable bytes plus that share.
   * `_fit_into` re-fits smaller if the encoded lists overshoot, and rolls back a failed try.
   * Only gameplay layers count by default (child / adult, day / night). `strict_cutscenes=true` also fits the
     cutscene layers. The ending's Lon Lon Ranch, Death Mountain Trail and Chamber of the Sages shots load a dozen
     characters into 15-30 KB. Without strict mode the report lists every cutscene layer the build overfills
     (`cutscenes_over_budget`), because the game may crash there.
5. **One ROM** (`oot_writer.Rom.build`): changed files go uncompressed after the ROM data. A grown object gets a fresh
   VROM range, and both the DMA table and gObjectTable follow it. The CIC-6105 CRC is recomputed. The build reads the
   new ROM back and checks three things: the CRC, each skeleton's limb count, and that every limb list ends and reads
   only inside its object (`oot_cast.check_object`).

## Limits

* Creatures don't animate their limbs with the donor (rigid ride), and the donor is scaled to the creature's height.
* NPCs without legs (robes, counters) fold the donor's legs into the hip.
* Objects shared by several characters change all of them (see above). En_Hy townsfolk, Epona, Navi and the Like Like
  are refused.
* Cutscene layers may overflow without `strict_cutscenes` (listed in the report). The game's own scene / room tables
  are not edited.
* The ROM grows to 64 MB (the moved objects sit past the 32 MB of retail data). The existing Link mods already do the
  same.
* Equipment and hand tables are Link-only. NPC props drawn from the NPC's own object (Saria's ocarina, Talon's
  bottle) keep their old look if the actor draws them in its own code without body materials.

## Tests

`tests/test_oot_cast.py` covers the following.

* **Catalogue**: slots are unique, objects and actors are real, and the snapshot agrees with the catalogue (types,
  offsets, creature modes, at least 60 retargets).
* **Roles and skeleton facts**: limb-tree roles with and without legs, the refusal of a non-humanoid tree, Flex vs
  Normal detection, texture ranges.
* **Synthetic NTSC 1.0 ROM**: dmadata, `code` with gObjectTable and gSceneTable, 101 scenes with a Kokiri Forest room,
  and humanoid objects at the real catalogue offsets. On it the tests check:
  * scenes / rooms / free space;
  * the fair growth plan;
  * `slot_spec`, and the refusals of Epona and of a missing object;
  * a full `build_cast` with the retarget, the rigid ride and a refusal. The grown objects get fresh VROM ranges in
    the DMA table and gObjectTable, the CRC equals `crc6105`, the lists stay inside their objects, the Flex
    dListCount is untouched, and the other files are unchanged;
  * a full object space, where the slot is refused with "doesn't fit" and the rest still build;
  * `fit_budget` flattening and then refusing.
* **Cast swap for OoT**: slots, filters (`enemies`, `bosses`, `main`), the deterministic pairs plan with the skip
  reasons, and `CS.build` through `BUILDERS["gbox.oot_swap"]` with a per-slot partial report.
* **Owned ROM** (skips unless `GBOX_OOT_ROM` or the cached ROM exists): every catalogued skeleton's limb count and
  type, and child Kokiri Forest's free object space with Fado's head object. It passes on NTSC 1.0 and 1.2.

## Live check

The live check is: build OoT cast <- SA2 characters, launch it on the test PC, and capture Kokiri Forest frames.
**It was not run.** This session may not launch game sessions, so the in-game check is still to do. To run it:

1. `characters op=cast_swap target_game=446e8e442d726e31 source=SA2 launch=true`, or the cast dialog.
2. Load a child save and warp: `oot_live goto kokiri forest`.
3. Capture frames near Mido, the Know-It-All Brothers, the Kokiri girls and the Deku Scrubs in the Kokiri Forest area.

What ran instead, offline on the operator's NTSC 1.0 ROM (nothing launched), was the full cast build from the SA2
collection entries (see the results below). The rebuilt objects were also rendered with the game's own skeleton and
animation frame (`characters.render_preview` of `object_mesh` read back from the built ROM). The Kokiri boy as Sonic
and Saria as Shadow stand in their animation poses, and the Deku Scrub carries Knuckles (rigid).
