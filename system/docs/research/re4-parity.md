# RE4 Switch parity with RE5 in MercMode: enemies, cast, greybox, rotation

2026-11-09, branch `wt-re4-parity-20261109` (base `97d538b8`). The operator's ask: "extend merc mode's customization to
RE4 doing the same thing, replacing the hosts and zombies with random characters from the database and converting the
level into a simplified grid visually ... let's get RE4 in rotation and capable of the same level of modification."
RE4 is the Switch edition (title `010099A00BC1E000`, gBox game id `270a15eb98dab4d7`, Mercenaries), never GameCube.

**Nothing here has been booted.** Every overlay below was built and checked offline on JAYBUILTFINALE from read-only
copies of the host's RomFS (`~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/`, 274 MB copied to
`C:\_tools\gBox\.scratch-merc-recovery\re4\inputs\`). The four earlier player candidates
(`re4-switch-model-replacement.md`) are also unbooted. A file that parses and rebuilds is not a working mod; each
receipt says `live_verified: false`, what a round must show and how it fails. The main session boots through
MercMode's queue; this branch does not touch the live system.

Three kinds of statement are kept apart below: **measured** (run on the real files in this pass), **live, earlier**
(seen in a running round by an earlier session, cited), **inferred** (neither).

| | |
|---|---|
| Code | `gbox/re4_switch_assets.py` (readers; rigid scene models and DXT1/3/5 added), `gbox/re4_switch_models.py` (player: per-character layouts, library donors, cast pool), `gbox/re4_switch_enemies.py` (new: roster, Ganado layout, enemy writer, enemy pool), `gbox/re4_stage_greybox.py` (new: room scene reader, greybox writer) |
| Tests | `tests/test_re4_switch_assets.py`, `test_re4_switch_models.py`, `test_re4_switch_enemies.py` (9), `test_re4_stage_greybox.py` (7): 55 tests, synthetic fixtures only |
| Shared RE5 code used as is | `re5_donor_pool.Donor / resolve / donors_of / plan` (the donor seam and the seeded deal), `re5_stage_greybox.grid_image / grid_cells / span_label / PALETTE / _rasterise` (the look and label rule) |
| Overlays (not in Git) | `C:\_tools\gBox\.scratch-merc-recovery\assets\re4\re4-enemy-pool-01\`, `re4-cast-pool-01\`, `re4-stage-greybox-v1\`, each `romfs\bio4\...` + `receipt.json` |
| Inputs (not in Git) | `.scratch-merc-recovery\re4\inputs\{em,etc,imagepackhd,st4}\` copied read-only from the host; the donor library `.scratch-merc-recovery\cast\inputs\library\` (1,483 entries) and its survey `cast\library-survey.json` (650 usable) |

## 1. Enemies: the roster, the Ganado pack layout, the writer, `re4-enemy-pool-01`

### 1.1 Which packs each Mercenaries stage spawns (measured)

`etc/omake01.esl` and `omake02.esl` are the Mercenaries enemy set lists; the Switch keeps the GameCube layout
(`re4_navmap`: 32-byte entries, +1 em id, +2 type, +8 u16 hp, +0xC three s16 coordinates / 10, +0x18 u16 room).
`re4_switch_enemies.roster` reads them; `re4_menus.STAGE_ROOMS` names the rooms.

| stage | room | ESL | spawns | packs (type: count) |
|---|---|---|---|---|
| Village | r400 | omake01 | 130 | `em16` {3: 49, 4: 39, 11: 21, 12: 15}, `em28` {0: 4, 1: 2} |
| Castle | r402 | omake01 | 117 | `em1c` {7: 87, 9: 27, 10: 2, 13: 1} |
| Base | r403 | omake02 | 164 | `em1d` {2: 5, 14..21: 16-17 each} |
| Waterworld | r404 | omake02 | 109 | `em20` {14..22: 5-12 each} |

`em28` is a 19-bone quadruped (head at y 515, legs 12-17): the Village dogs. No biped donor fits it; it stays native
(`NOT_WRITTEN`). The type byte's meaning is code in `main` and was not read: that a pack's body slots are its type
variants is **inferred** from the counts (em16 has four bodies and four types).

### 1.2 A Ganado pack (measured on em16, em1c, em1d, em20 - 698 slots each)

Every BIN slot of the four packs was decoded (skin bones, bounding box, texture indices). The pack holds several
**body groups** - a body BIN (the whole figure, headless and handless), its texture table in the next slot, its head
pieces after that - plus shared hand poses, gear pieces (vests, hoods, straps), the head parasite and items.

| pack | sha256 | bodies (slot: table) | heads hidden | hands hidden | gear hidden | stays native |
|---|---|---|---|---|---|---|
| `em16` | `5b8026bf…` | 453: 454, 457: 458, 472: 473, 476: 477 (1,920-2,139 vertices, 34 bones) | 455 456 459 460 461 463 474 475 478 479 480 | 444-452 | - | 629 (parasite, own 26-bone tree) |
| `em1c` | `00bd13ea…` | 504: 505, 537: 538, 541: 542, 543: 544 (1,613-5,892 vertices, 37-38 bones; 541/543 reach x 1,677: wide sleeves on bones 34/35) | 506 507 508 527 531 539 | 512-520 | 510 511 521 523 525 529 | 640 (31 bones, its own tree - the Garrador, inferred) |
| `em1d` | `a6163270…` | 551: 552, 555: 556, 579: 580 (551 has 6,614 vertices and reaches x -1,824: a weapon in the body mesh - J.J., inferred) | 557 559 571 573 581 583 585 587 | 394, 560-568 | 569 575 577 | 629 |
| `em20` | `6f3ccb89…` | 476: 477, 555: 556, 579: 580 (476: 4,747 vertices, 40 bones) | as em1d | as em1d | as em1d | 629 |

Facts the writer rests on, all measured:

* Every Ganado body lists its skeleton as ids 0..n-1 and **ids 0..25 are Leon's tree** (hip 0, spine 1-4, right arm
  5-10, left arm 11-16, pelvis 17, right leg 18-21, left leg 22-25), bind joints within 5.2 units of Leon's; the
  parasite (629) and em1c 640 do not share it. So the player writer's fit (`re4_switch_models.fit`) applies without a
  new role map. The Ganado and Leon T-poses coincide (arms along x at y 1,507.8 / 1,508).
* The native body skins never bind bone 0: hips go to bone 17 (pelvis; 326 vertices on em16 476), the belly to bone 1.
  The enemy writer therefore uses `ENEMY_ROLE_BONES = ROLE_BONES | {hip: 17}`; the player writer keeps hip = 0 so the
  four published Leon candidates still reproduce byte for byte (checked: `sonic-on-leon-v1` rebuilt to `611db614…`).
  Leon's own skin also binds the hips to 17, so hip = 0 is a known difference of the player candidates, not of the
  format; whether it matters is a thing to see in the first live frame.
* The texture join is the player's: a table image names `imagepackhd/000000XX.pack.fen` entry k. Image 0 of a body
  table is the face (the head pieces sample it), image 2 the skin the hand poses sample, image 1 the shirt - the body
  alone. `body_image` picks the body's most-drawn image that no model left native with the same table size samples;
  on em1c 504/537/543 none is free (slot 626, a 5-texture model, samples every image), so the body's own image is
  taken and the receipt names the sharer.
* The FCV joint lists (first bytes only) name bones 0-5, 7, 10, 11, 13, 16-18, 20-22, 24-25 in most Ganado clips; the
  reading is the earlier pass's and incomplete (23 is absent, which the native skin contradicts), so it is recorded,
  not relied on.

`measure_class` derives all of this from the bytes; `KNOWN` pins the measured result per pack (with the pack's
sha256) and `build_class` refuses a pack that measures differently unless told to trust the measurement.

### 1.3 The writer

`build_class(udas, archive, donors)`: for each body, the donor (a `re5_donor_pool.Donor` resolved to a record by
`re4_switch_models.library_donor`, 512x512 atlas) is fitted onto the body's own skeleton by `fit` (per-role rotate and
stretch onto the native bind joints, no bind joint moved), written by `HdBin.with_geometry` as one material naming the
chosen table image, the atlas appended to the pack's archive as DXT5 with a full mip chain, the table image pointed at
it; the group's head pieces are shrunk toward the donor's head, the shared hands and gear toward their own centre (the
same-topology position edit the earlier live rounds saw drawn). Every other slot is byte for byte the stock pack; the
output re-parses and rebuilds to itself; the receipt lists the slots changed.

### 1.4 `re4-enemy-pool-01` (built, not booted)

Dealt by `re5_donor_pool.plan` with seed `20261109-01`, slots `emXX:body` (14), history = the three RE5 cast pools and
`re4-cast-pool-01` (`avoid_last 4`), donors under 6,000 source vertices, the Sonic Adventure 1 rig and the Render96
pack left out by name. Five donors were set aside by the writer and the plan dealt again from the same seed:
`oot_km1`, `oot_kw1`, `sm64ds_bowser` (a zero-length role segment on this fit), `sc2_yoshimitsu`,
`stranglehold_gk_lieutenant_1` (over the vertex limit).

| file | bytes | sha256 |
|---|---|---|
| `romfs/bio4/em/em16.udas` | 4,789,888 | `f88190f24ef8c68fdbec62f9b6392861a2de03c02c0ee617e05b800e10afb9b4` |
| `romfs/bio4/imagepackhd/00000016.pack.fen` | 11,158,659 | `6719af2c2b124a4fc67beada60f648c268bf9c4545578c40f201bce7dfdb8c52` |
| `romfs/bio4/em/em1c.udas` | 5,088,672 | `98c7a901a00d8b8a4548638f6d541812f90f13cee335bd95b8e0d7f6c0b72012` |
| `romfs/bio4/imagepackhd/0000001c.pack.fen` | 10,678,728 | `d1ed1c439d80d20f6e3a6ae34f0bc4d4b564e93abca60cccf2ea90459af7a2f0` |
| `romfs/bio4/em/em1d.udas` | 5,068,032 | `93be6b469d634dc1613c948dcc9670538bb619261123023ab3a6296c88d753f4` |
| `romfs/bio4/imagepackhd/0000001d.pack.fen` | 9,573,920 | `f676096276e5ce5b2c721b51ff5695c0da35b9aa68ae1c36cc7b99d5b1a5f60c` |
| `romfs/bio4/em/em20.udas` | 4,538,976 | `7160f37103f110f18ee0f1aeb8513773e1e98df43db8222e6032f10ef53ea450` |
| `romfs/bio4/imagepackhd/00000020.pack.fen` | 10,041,850 | `72bccd1964c97f1d79f1695ce1c7ec89933f34454c79417b1450f9b7d46a9336` |

| stage | body | donor | game |
|---|---|---|---|
| Village `em16` | 453 | Mewtwo (`melee_mewtwo`) | Super Smash Bros. Melee |
| | 457 | Rival Ntank (`jgr_char12…`) | Jet Grind Radio |
| | 472 | Cloud Strife, field (`ff7_cloud_field`) | Final Fantasy VII |
| | 476 | Solid Snake (`mgs2_snake…`) | Metal Gear Solid 2 |
| Castle `em1c` | 504 | Hawk Hana (`rv_7_1_hawk_hana`) | WCW-nWo Revenge |
| | 537 | Astaroth (`sc_astaroth`) | SoulCalibur |
| | 541 | Proof (`djv_ps2_proof_1`) | Def Jam: Vendetta |
| | 543 | Kasumi, costume 3 (`doapp_kasumi_3…`) | Dead or Alive ++ |
| Base `em1d` | 551 | Toni Cipriani (`toni_plr15`) | GTA: Liberty City Stories |
| | 555 | Mario (`sm64ds_mario`) | Super Mario 64 DS |
| | 579 | Golden Kane pistol 1 (`stranglehold_gk_pistol_1`) | Stranglehold |
| Waterworld `em20` | 476 | HUcast (`pso_gc_hucast`) | Phantasy Star Online Ep. I & II |
| | 555 | HUNK (`re2gc_pl1_0c`) | Resident Evil 2 |
| | 579 | Bloch (`auf_zero_body`) | 007: Agent Under Fire |

**What a round must show**: in the Village, four different library characters at once, each a whole figure about
1.8 m tall with Ganado limb lengths, no Ganado head, hands or clothes on them; the dogs stock; a character keeps its
look while it walks, attacks, is shot and falls; a parasite that bursts from a head is the stock parasite on top of
the donor's head area. Castle, Base, Waterworld: four, three and three characters. **Failure signs**: stock Ganados
(overlay not applied, or the round draws from another pack than the ESL names); a figure that can be hit but is not
drawn (the composed body refused); a donor in a stock cloth texture (the appended entry not read); stock heads, hands
or vests floating on a donor (a shared piece drawn from a table other than measured - the receipt's `parts_shrunk`
names what was hidden); a hang at stage load (the rebuilt container; bisect by pack file); all four Village Ganados
alike (the type byte does not select bodies as inferred). Known weaknesses by design: human proportions on every
donor (the skeleton is pinned), rigid donors crease at joints, no fingers, no facial animation, J.J.'s gatling and the
leaders' sleeves vanish with the body mesh.

## 2. Player: the slot table and `re4-cast-pool-01`

### 2.1 Which pack each Mercenaries character loads

| roster name (`re4_menus.PLAYERS`) | pack | evidence |
|---|---|---|
| Leon | `pl08` | art + layout; a scale edit changed the player in a live round (earlier session) |
| HUNK | `pl06` | art (gas mask, black fatigues) + layout; measured here |
| Krauser | `pl0a` | art (camouflage, war paint, blade arm) + layout; measured here |
| Wesker | `pl0d` | art (sunglasses, black leather) + layout; measured here |
| Ada | `pl0b` | **inferred**: plain red dress; `pl0c` (tactical) and `pl16` (butterfly) have the same layout. Reading the character table out of `main` (names at 0x6c2000-0x6c3300 / 0x6c9254, `re4-switch-model-replacement.md` §6) was not done in this pass |

### 2.2 The per-character slot layouts (measured on the stock packs)

The body is not one slot in every pack; `re4_switch_models.LAYOUTS` records what the donor replaces and what is hidden:

| pack | body slot | table / atlas image | hidden (heads) | hidden (hands) | hidden (other body parts) |
|---|---|---|---|---|---|
| `pl08` Leon | 0 (6,591 vertices) | 1 / image 5, the shirt | 2 4 5 8 | 14-21 | - (slot 7, a 98-vertex collar, stays: the published candidates' layout) |
| `pl06` HUNK | 0 (9,849) | 1 / 0 | 2 (gas mask) 7 (collar) 8 | 14 16 17 | - |
| `pl0a` Krauser | 0 = the **legs** (bones 17-25, y -1..1240) | 1 / 1 | 2 7 8 | 14-17 | 4 (torso and arms), 6 (torso with the blade arm, x to 1,949), 10 (thigh piece), 20 (shoulder strap) |
| `pl0d` Wesker | 0 = the **upper body and coat** (y 888..1647) | 1 / 0 | 2 4 (face) 7 (glasses) 8 | 14 16 18 20 | 6 (legs) |
| `pl0b` Ada | 0 (10,293; 81 bones, bind joints up to 104 units from Leon's) | 1 / 4 | 2 4 5 (hair) 7 8 | 13-19 21 147 | - (slot 10, a wrist item on bone 10, stays) |

The atlas image per pack is the body's most-drawn diffuse image that no other model bound to the same-sized table
samples (Leon: 2, 5, 6, 7, 8 are free and 5 draws the most triangles; HUNK/Wesker: 0; Krauser: 1; Ada: 4). Which TPL a
BIN binds is decided by code; the measurement reads "same image count as the table" as the binding, which is an
inference (`re4-switch-model-replacement.md` §1).

`author_body(target, archive, donor, layout=LAYOUTS[pack])` writes any donor record on any of the five packs;
`library_donor(library, slug)` makes the record from a library entry through `re5_donor_pool.resolve` (or from a
survey row's roles without resolving again); `cast_pool(...)` deals donors to the five slots with
`re5_donor_pool.plan` and writes one overlay.

### 2.3 `re4-cast-pool-01` (built, not booted)

Seed `20261109-01`, no history, donors under 12,000 source vertices, 1024x1024 atlases. Because the seed and the
first slots match RE5's `cast-pool-01`, Leon's and HUNK's donors are the same two characters as that pool's Chris
(BSAA) and Chris (Safari); a second RE4 pool should pass the RE5 pool receipts as `--history`.

| slot | pack | donor | game | triangles | weight sets | archive entry |
|---|---|---|---|---|---|---|
| Leon | `pl08` | Alpine guard, inside (`auf_thug_alpine_inside`) | 007: Agent Under Fire | 1,629 | 63 | 30 of `01000008` |
| HUNK | `pl06` | Goji (`jgr_char05…`) | Jet Grind Radio | 732 | 15 | 19 of `01000006` |
| Krauser | `pl0a` | Lizardman (`sc_lizardman`) | SoulCalibur | 3,306 | 80 | 28 of `0100000a` |
| Wesker | `pl0d` | Vincent Valentine, field (`ff7_vincent_field`) | Final Fantasy VII | 560 | 15 | 22 of `0100000d` |
| Ada | `pl0b` | Razor (`djv_ps2_razor_1`) | Def Jam: Vendetta | 2,060 | 137 | 35 of `0100000b` |

| file | bytes | sha256 |
|---|---|---|
| `romfs/bio4/em/pl08.udas` | 1,440,128 | `90c896aa67615dbd8d2116992a466181fc2ab84bacdadb5016ea4976bb689625` |
| `romfs/bio4/imagepackhd/01000008.pack.fen` | 3,426,895 | `23bf97d139b85ef301fa9468b34d5fb429829c407463383524e09f0586b43336` |
| `romfs/bio4/em/pl06.udas` | 971,200 | `be4a888db4f636dcbea357d749adc125dddbc9b68365c40601abc7d5b96b4188` |
| `romfs/bio4/imagepackhd/01000006.pack.fen` | 2,151,229 | `59a755ad587a6df34a20644d2c4549e14996963d0b3a254e857ac93fb2ced5ef` |
| `romfs/bio4/em/pl0a.udas` | 1,958,048 | `210cbaaee5a8a279f850089fabf08e46487673209f90d622ac54c61294b5561a` |
| `romfs/bio4/imagepackhd/0100000a.pack.fen` | 4,062,429 | `b87fd643dce8f3a6ecad76ec50ae51fd71a3ebeadff7e96f87cd9ddbf49d40ad` |
| `romfs/bio4/em/pl0d.udas` | 1,120,320 | `35028a7d5bb35c337d7abfa65b74622d7e6cbe23d2cdc0c0efed57db251aa791` |
| `romfs/bio4/imagepackhd/0100000d.pack.fen` | 5,073,419 | `fb1120ad9b30c5599f77e2754cf811f5341f7cd46ca478d4c867131de1e65963` |
| `romfs/bio4/em/pl0b.udas` | 1,838,624 | `65ac461036a1855fff31e1ca242864c381f6c1a1b2e616ff51bdb6e4ceb29ee3` |
| `romfs/bio4/imagepackhd/0100000b.pack.fen` | 3,506,309 | `3e8504b42b259aec6ea57f5656091dad2b864fdbe8c55e3429ac16549440f7fe` |

**What a round must show**: as Leon, the Alpine guard about 2 m tall with Leon's limb lengths, standing on the
ground, no Leon head or hands, knife and sheath floating at the hip, moving with Leon's animations. The other four
slots are drawn only once the Select Player walk steers to a portrait (today it confirms the default, Leon; §4).
**Failure signs**: stock character (overlay not applied, or Ada loads `pl0c`/`pl16`); body invisible or black with
specks at head height (composed mesh or appended entry refused - the control and rewrite candidates answer this
first); donor shape in a stock texture (appended entry not read); native torso, legs or strap through the donor on
Krauser or Wesker (a hidden part drawn from another table than measured); a hang at stage load (bisect by pack file).

## 3. Greybox: the room format and `re4-stage-greybox-v1`

### 3.1 The room (measured on `st4/r400.udas`, `r402`, `r403`, `r404`)

A Mercenaries room is a UDAS pack whose DAT slot 4 is `SMD`, the scene (10.9 MB for r400); slot 8 `TEX` is 64 bytes,
so the room's pixels are not in the room. Inside the SMD:

* a 0x40 header: `u16 0x40, u16 count, u32 A, u32 B, u32 C`, floats; the **instance table** at 0x40, 0x48 bytes each,
  `count - 1` entries (the entry at `count - 1` would overlap region A), `+0x14 flags, +0x18 f32[3] position (mm),
  +0x24 f32[3] rotation (radians), +0x30 f32[3] scale, +0x3c u16 model index`; 222 instances in r400 (94 with a
  rotation about x or z; scale 1, 10, 0.8, 1.1 ...);
* region A: the u32 offsets of the GameCube-layout models in C (92 words for r400); region B: the GameCube TPL
  (magic 0x0020AF30, 115 images) with its pixels; region C: the scene models in the GameCube BIN layout (0x60
  header) - A, B, C are not read further;
* the **HD models**: one `HdBin` per model (92 / 92 / 136 / 142 for r400 / r402 / r403 / r404), one bone, **no weight
  sets** (the empty weight table's pointer is the next section's offset - `HdBin.parse` now accepts that and all 462
  rebuild byte for byte), version 0x20010801, every material naming the room TPL's images by index (byte 12 diffuse,
  byte 14 opacity);
* the **HD TPL** last: 115 images (r400) all naming `imagepackhd/44000400.pack.fen` (r402: `44000402`, 59 images;
  r403: `44000403`, 52; r404: `44000404`, 35). The instance's model index counts the HD models in file order
  (**inferred**: the distinct index count equals the model count in all four rooms; the GC-layout models in C have the
  same count).

The archives: `44000400` has 218 entries (the room TPL names 115; the rest belong to the room's item, enemy and effect
TPLs), DXT3 (216) and DXT5 (2), 7-11 mips, HD/nominal size ratio 2 for most. Every entry of the four archives
re-encodes at its native size, fourcc and mip count through `encode_dxt` / `replace_dds_pixels` (mean absolute pixel
difference 0.08-0.17 after a decode-encode-decode trip).

### 3.2 The writer

`re4_stage_greybox.build(room, archive)` places every HD model by its instances (scale, then rotation about x, y, z
- an assumption; rotations about y alone, which most are, agree under any order), charges each world-space triangle to
the archive entry its material binds as diffuse, and per entry measures the area shares of up-, side- and down-facing
triangles and the centimetres one UV tile spans (the UV-to-world Jacobian, area-weighted median and quartiles; 1 unit =
1 mm). `classify` uses the geometry alone (RE4 textures have no names): up >= 0.6 floor, side >= 0.6 wall, down >= 0.6
other, mixed other; an entry only bound as an opacity map or bound by nothing is kept native. The grid is RE5's
(`re5_stage_greybox.grid_image`, one major cell per metre of the tile span, floors blue with the pixel width and the
span in a corner, walls grey with the span, the rest checkered), drawn at the DDS size with the native alpha channel
(decoded from mip 0) and written into the native DDS header with `replace_dds_pixels`. Only the archive changes; the
room pack is read and never written.

### 3.3 `re4-stage-greybox-v1` (Village, built, not booted)

Room `r400.udas` sha256 `6d573d3e7777d97c018d2423f13389a58e03f199a815b735aa5fc011bf246037`; archive
`44000400.pack.fen` `c843032a…` (17,546,078 bytes) -> `romfs/bio4/imagepackhd/44000400.pack.fen`
`02b973ad26aae4daaa5f3d58b65c109788b0241002f95a5e300d565019df1b05` (8,695,982 bytes: the grids compress far better
than the photographs; the uncompressed body is the same size). 93 of the 115 entries the room draws were rewritten:
56 walls (geometry), 26 floors, 11 other (8 mixed, 2 down-facing, 1 diffuse with no placed geometry); 22 kept (21
opacity maps, 1 unbound). 183,068 triangles charged; `instances_skipped 0`. Previews (CPU, not the game):
`textures.png` (every written entry) and `stage-view.png` (the placed scene with the written entries).

**Known limits of the geometry-only rule**: roofs face up and are drawn as blue floors (RE5 catches `yane` by name;
RE4 has no names - an `--override entry=other` per roof texture is the tool); the big catch-all planes (entry 4, a 32x32
tiling every 166 m; entry 27, a down-facing 49 m sheet) get the 32-cell maximum grid. **What a round must show**:
the whole Village in grey and blue grid tiles with metre labels, lit as before; floors blue with the pixel size, walls
grey, props checkered; fences and foliage still cut out; Ganados, the player, items and effects unchanged.
**Failure signs**: black screen or hang at stage load (a DDS the game rejects; every entry keeps its native header,
size and mip count, so bisect by variant); a surface still showing a photo (an entry bound by an opacity-only
material, another TPL of the room, or the GC-layout models); solid slabs where fences were (alpha not kept); grid
lines of very different size on one surface class (the UV measurement is off for that texture; its tile quartiles are
in the receipt); every texture at one grid scale (the instance scale or the mm unit is wrong).

The other three stages build with the same command (`r402` + `44000402`, `r403` + `44000403`, `r404` + `44000404`);
their rooms and archives are copied and their scenes parse; they were not built in this pass.

## 4. Rotation: what MercMode needs to put RE4 beside RE5 on lilspark

Live state read from the Spark store (`gbox.sqlite3`, read-only, 2026-11-09): lilspark's MercMode is `enabled`,
`titles ['re5']`, `preferred_editions {re5: switch no_mercy}`, a 20-entry repeating RE5 queue on build
`recovery-greybox-s400-pool-test-20261109`, `keep_warm 0`. The control plane already accepts RE4 Switch; the gates are
settings and the bot.

| # | what | where | state / change |
|---|---|---|---|
| 1 | The RE4 edition is the Switch one | `re_switch.py:51-53` `EDITIONS['re4']`, `:69-92` `preferred_spec` | present: `preferred_editions.re4` must be exactly `{"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"}` (`normalize_preferences`, `:56-66`); without the pin RE4 resolves to the GameCube disc (`mercmode.py:106-118`). Set it with `job_mercmode op=configure` together with `titles` |
| 2 | RE4 in the title list | `mercmode.py:176-178` (`titles`: 1-3 distinct of re4/re5/re6/re3/merc3d) | lilspark has `['re5']`; set `['re4', 're5']` |
| 3 | The edition says playable | `re_switch.py:88-92` returns `playable: True`, `playbook: 're4switch_bot'`, `perception: 'screen-only'` | done since 2026-11-07; `inventory` (`mercmode.py:938-1003`) then needs the ROM receipt |
| 4 | ROM access receipt | `mercmode.py:881-904` `valid_preparation` (30 min), `:967-995`; `known_game_ids` (`:870-878`) carries `270a15eb98dab4d7` through `TITLES['re4']['backends']['switch']` | run `job_mercmode op=prepare` near the launch; a prior launch of the same game id on the same PC also counts (`:974-980`) |
| 5 | Queue entries | `mercmode.py:203-230` `queue_entry`; `catalog()` `:194-200` gives RE4 `modes {'mercenaries': ['Leon','Ada','Krauser','HUNK','Wesker']}`, stages `['Village','Castle','Base','Waterworld']` | an entry is `{"title": "re4", "mode": "mercenaries", "character": "Leon", "stage": 0, "mod": "<build>"}`; `mod` is one build folder name (`recovery-*` through `switch_mods op=write`, paths `romfs/bio4/...`, `switch_mods.py:450-459`); the queue holds 20 (`QUEUE_MAX`, `:88`) and lilspark's is full - drop RE5 entries to add RE4 ones |
| 6 | Build at boot, not at the menus | `screensaver.py:1529-1545` (`mod_rotate`: a queued build loads at boot), `:530-533` (`_start` passes `mod` + `local_build_ok`) | a `mod` entry for a title other than the running one is a cold switch; same build as the running session = no restart (`:1531-1538`) |
| 7 | One Switch emulator | `screensaver.py:797-803` `_switch_slot`, `:817-827` `_release_other_switch`, `:1253-1260` cold switch; `adapters.py:4873` `SWITCH_CITRON_TITLES = {RE4}` (RE4 on Citron, RE5/RE6 on Eden); `config.py:321` `switch_linux_emulator auto` | RE5 (Eden) -> RE4 (Citron) is a cold switch: Eden is stopped, Citron boots; `keep_warm` stays 0. The Eden<->Citron swap has not been exercised in MercMode ("what's needed to finish" §Risks) |
| 8 | Character and stage reach the game | `mercmode.py:306-315` `selection_job`: for `re4` it submits `re_mods op=mercs_select` (the GameCube tool); `re4_switch.py:393-407` `step`: `select_player` / `select_stage` are confirmed on their default; `re4switch_bot.py:112-125`: same walk | **not wired for RE4 Switch**: the DJ's `character` / `stage` are ignored; every round is Leon / Village. To honour them: in `re4_switch.step` move the Select Player cursor to the portrait index (`re4_menus.PLAYERS`) before confirming and pick the stage cell on the 2x2 grid (`re4_switch_screens` reads `select_player` by the pulsing portrait, not its index - the reader needs the cursor position), then route `selection_job('re4')` to the Switch path |
| 9 | The playbook that plays | `tools.py:3401` `PLAYBOOKS` order; `mercs_bot.matches` (`mercs_bot.py:478-481`) takes any title with a `mercs` block once the engine is `READY` (`mercs/engine.py:33`, False today) or the block says `ready: true`; `profiles/gamedata/010099A00BC1E000-ram.json:23` `ready: false` | so `re4switch_bot` plays RE4 Switch (`matches` by platform + game id, `re4switch_bot.py:32-38`). When `engine.READY` flips True, `mercs_bot` will take RE4 Switch with an empty snapshot - set the map's `ready` only with real anchors |
| 10 | Round boundaries | `tools.py:3487-3491`: `round_boundary` is passed only to a `play` whose signature names it; `re4switch_bot.play` (`:55-56`) does not; `mercmode.accept_boundary` (`:1091`), `ROUND_MIN_S 75` (`:1087`) | **RE4 Switch posts no boundaries**: `rounds_per_title` never counts, the DJ queue head never advances at a round end for RE4. The turn ends only by `_no_progress` after `NO_PROGRESS_S = 600` s (`screensaver.py:57`, `:1125-1160`: no boundary and no native kills/score progress - RE4 has neither) or by the operator. With RE4 in `titles`, expect 10-minute RE4 turns followed by a cold switch back to RE5 |
| 11 | Idle demo | `mercmode.py:322-334` `replaced_editions` | with `preferred_editions.re4` set, the GameCube RE4 ids are excluded from the idle demo, as RE5 PS3's were |
| 12 | Save | `re_switch.py:49` `RE4_UNLOCK_REASON` | Mercenaries needs the lilspark save past the village (backed up 2026-11-06, `13908f63f08a791f`); a reset save has no EXTRAS row |

Round boundary behaviour, honest: RE5 ends a round on the native terminal reader and MercMode rotates on it; RE4
Switch has no reader, so its "round" is a 600 s stall timer. A first RE4 entry in lilspark's queue therefore costs: a
cold Eden stop, a Citron boot (~40 s), the menu walk (proven 5/5), one Leon / Village round that the screen-only
playbook keeps moving in, then ten minutes before the switch back. For the overlay boots this is enough: a frame once
the bot is in the round answers each receipt.

### The RE4 bot, as it stands

* **Proven (live, earlier)**: boot on Citron, input, the menu walk to a live round from the capture frame (5 boots of
  5, commit 4591bb58, `re4-switch-anchors.md`), module base by signature (`0x3CA7C04000 + vaddr`), three A presses
  start the clock, the playbook advances / turns / fires on a cadence.
* **Cannot fight**: `re4_switch.snapshot` returns the empty round (`re4_switch.py:199-214`, every `S_*` anchor
  `None`), so `Bot.tick` (`:545-569`, face the nearest Ganado and fire through the operator's gates) never runs with a
  target; `own_screen` is `loading` forever and `screen()` reads the frame.
* **What the fight needs**: (a) the player: position (found by a 9 s scan, no fixed pointer), facing (the measured
  pair is probably the camera's yaw), health (the one reading, position - 0x2478, failed its cross-check; `unit+0x3C2`
  is not distinctive: 466 code users, 0 of 400 `u16 == 100` candidates start with a pointer); (b) the enemy table:
  `units()` returns 5 spawn markers; best lead class `0xaed3b0`, 26 objects at health 1000; (c) the round: the clock
  (float seconds from 120.0, found, unfixed), score and kills (`FUN_002cccc0` located, no live read). The map's
  `mercs.ready` stays false until (a) and (b) read at 20 Hz across two boots.
* **Shortest path** (`re4-switch-anchors.md` §"Round 45"): chase the clock and the position, not health - a float
  that decrements from 120.0 is unambiguous; a fixed pointer to it is the `S_MERC` anchor; the player object is the one
  the position lives in (`S_PLAYER`); then stride-scan around that unit for neighbours that read as units (`S_EMMGR`).
  Each step is a boot (~40 s) and a live round; the scans must finish inside the first 12 s of a round (the first
  Ganados arrive in 15-20 s and the player is defenceless while a scan runs). The measured `.bss` window is 7.6 MB of
  18.4 MB; a `decreased` filter emptied the candidate set once because no hit had landed - engage until damage is
  visible, then sample. When the player and enemies read, `Bot.tick` already turns with `lleft`/`lright` (tank
  controls; the d-pad is item select) and fires `zr` with `zl` held; closed-loop steering on the measured angle is the
  next piece (turn rates varied 16-42 deg/s).

## 5. Boot order, and what each boot must show

One MercMode queue entry per boot (`{"title": "re4", "mode": "mercenaries", "character": "Leon", "stage": 0,
"mod": "<recovery build>"}`), each build a separate `recovery-*` LayeredFS overlay written through `switch_mods
op=write` under game id `270a15eb98dab4d7` with the overlay's `romfs/bio4/...` files as artifacts; a frame once the
bot has walked into the round (the clock on screen); the receipt's prediction answered yes or no.

| # | build | one question | yes looks like | no looks like |
|---|---|---|---|---|
| 1 | `native-swap-v1-control` (`65b6ff3d…`) | does a rebuilt pack with a resized slot load, and does a table's pack id reach another archive | Leon in the dark R.P.D. uniform, his own head and hands | Leon unchanged (not applied); R.P.D. shape in scrambled dark texture (pack id ignored - textures must then go into `01000008`); hang (container refused) |
| 2 | `native-rewrite-v1` (`2fe0fe6c…`) | does a mesh written by the composer draw | exactly boot 1's picture | any difference: the writer |
| 3 | `native-swap-v1` (`187b9128…`) | does a body on a foreign skeleton draw | HUNK's body under Leon's head and hands, head pieces on ids 26+ misplaced | hang here but not in 1: the foreign skeleton |
| 4 | `sonic-on-leon-v1` (`611db614…` + `aa22281d…`) | does a donor surface with an appended archive entry draw | a tall thin blue Sonic, no Leon head or hands, knife and sheath floating | invisible or black with specks (composed mesh or entry refused); Sonic in the shirt texture (entry 30 not read) |
| 5 | `re4-enemy-pool-01` (§1.4) | do donor bodies draw on the Ganado skeletons, several at once, and do the type bytes select the bodies | four characters in the Village, whole, dogs stock | all alike; bodies missing; stock heads/hands floating; hang |
| 6 | `re4-cast-pool-01` (§2.3) | does the generic slot writer draw on Leon's pack from a library donor (and later, with the walk steering, on the other four) | the Alpine guard as the player | stock Leon; invisible; stock texture; Krauser/Wesker native parts through the donor (only once those slots are selectable) |
| 7 | `re4-stage-greybox-v1` (§3.3) | does the game accept rewritten DDS entries in a room archive | the Village in grid tiles, cut-outs kept, everything else unchanged | black screen or hang; photos still showing; solid fences |

Boots 1-4 are the earlier candidates in the order `re4-switch-model-replacement.md` gives; 5-7 are this pass. Boot 5
before 6 because the Ganado bodies are plain packs with heads hidden by the proven position edit, whereas boot 6 adds
the player's hands and items; boot 7 is independent of the others and may go first if the room format is the question
of the day. Combining builds (enemy pool + cast pool + greybox in one overlay) is a matter of putting the files in one
`switch_mods` build once each has drawn alone.

## 6. What was run, what was inferred, what blocked

**Run**: every reader on every copied file (63 packs round-trip byte-identically, 462 scene models, 609 DDS entries
re-encode at native length); the four Ganado packs measured and pinned; the roster from the two ESLs; the three
overlays built with their receipts; `sonic-on-leon-v1` rebuilt to its published hashes after the writer refactor; 55
tests. **Read-only on the host**: directory listings, file copies (274 MB), lilspark's MercMode settings from the
store. **Inferred**: type byte -> body slot; the BIN -> TPL binding by equal image count; the instance's model index
as HD-model file order; the rotation order; Ada's pack; the names J.J. / Garrador / dogs for the odd models.
**Not done**: no boot; the character table in `main`; the greybox of r402-r404 (one command each); CPU previews of the
enemy and cast pools (the RE5 writers have them; the RE4 ones render only the greybox); publishing the overlays as
artifacts and the `switch_mods` builds (the main session's queue does that); a second cast pool with the RE5 pools as
history. **Where the format did not block**: nothing here stopped on an undecoded structure; regions A-C of the SMD
and the FCV/SEQ/EFF formats were simply not needed.

## Reproduce

```powershell
cd C:\_tools\gBox-wt-re4-parity\system
$py = "C:\_tools\gBox\.venv-session-audit\Scripts\python.exe"
$in = "C:\_tools\gBox\.scratch-merc-recovery\re4\inputs"
$lib = "C:\_tools\gBox\.scratch-merc-recovery\cast\inputs\library"
$survey = "C:\_tools\gBox\.scratch-merc-recovery\cast\library-survey.json"
& $py -m gbox.re4_switch_enemies roster --etc $in\etc
& $py -m gbox.re4_switch_enemies measure --em $in\em em16 em1c em1d em20
& $py -m gbox.re4_switch_enemies pool --em $in\em --imagepack $in\imagepackhd --etc $in\etc --library $lib `
      --survey $survey --seed 20261109-01 --out OUT\re4-enemy-pool-01 --exclude <sa1_*,luigi_hd,mario_hd,yoshi_hd> `
      --max-vertices 6000 --history <RE5 cast-pool receipts>,<re4-cast-pool-01 receipt> --avoid-last 4
& $py -m gbox.re4_switch_models layouts
& $py -m gbox.re4_switch_models cast-pool --em $in\em --imagepack $in\imagepackhd --library $lib --survey $survey `
      --seed 20261109-01 --out OUT\re4-cast-pool-01 --max-vertices 12000
& $py -m gbox.re4_switch_models author --em $in\em --imagepack $in\imagepackhd --target pl0a --library $lib --slug sc_lizardman --out OUT\one
& $py -m gbox.re4_stage_greybox survey $in\st4\r400.udas $in\imagepackhd\44000400.pack.fen
& $py -m gbox.re4_stage_greybox build $in\st4\r400.udas $in\imagepackhd\44000400.pack.fen --stage Village --out OUT\re4-stage-greybox-v1
& $py -m gbox.re4_stage_greybox verify --original $in\imagepackhd\44000400.pack.fen --candidate OUT\...\44000400.pack.fen --receipt OUT\...\receipt.json
```

Tests: from the repo root, `PYTHONPATH="system;system/tests"`, `-m pytest -q -p no:cacheprovider --disable-warnings
system/tests/test_re4_switch_assets.py system/tests/test_re4_switch_models.py system/tests/test_re4_switch_enemies.py
system/tests/test_re4_stage_greybox.py`.

## Decryption state (2026-11-10 00:25 UTC, measured)

RE4 Switch is fully decrypted on lilspark. The library's `Resident Evil 4 [UPDATE 1.0.2] [010099a00bc1e000].nsp` is not
a delta: it holds one 12,974,144,512-byte program NCA (`97920e35d665773caf9c075e3e0a53e8.nca`), a control NCA and the
CNMT. That program NCA is byte-for-byte the `~/gBox_alt/switch/work/game-010099A00BC1E000-12974144512.nca` the RomFS
was extracted from on 2026-11-05 (SHA-256 of 16 MiB slices at offsets 0, 6,487,072,256 and 12,957,367,296 identical:
`6814eca0…`, `f4950afc…`, `c8025671…`). So `~/gBox_alt/switch/romfs/010099A00BC1E000/bio4/` (5,275 files, 13 GB) is the
launched image's own RomFS; there is no BKTR patch layer for RE4 as there is for RE6. `gbox.switch_extract` cannot open
this NSP ("no ticket in the container"): its NCA uses the key area, not a title key.

## 7. The fight, the round clock and the rotation (2026-11-09, branch `wt-re4-fight-20261109`)

The ask: the RE4 Switch bot plays Mercenaries rounds as well as the RE5 Switch bot - fights, keeps the combo, never
stands, finds enemies by the map - and reports round boundaries so MercMode rotates. Same three kinds of statement as
above: **measured** (this pass, live or on recorded bytes), **live, earlier** (cited), **inferred**.

### 7.1 What was measured, and why the in-round fields were not

One live RE4 session this pass: `ae02be4bd9974915-03aacc170e184c15` on lilspark (Citron, launched by MercMode,
`agent_owned: true`), up 17:17:43 local to its no-progress cut about ten minutes later. Everything was read-only:
`GET /ram/hex`, `read_memory` jobs (actor `agent`), `frame.jpg`. No input, write, launch or stop.

| what | how | result |
|---|---|---|
| module base | 64 bytes at `0x3CA7C04000 + 0x100000` | the signature, exact: **base `0x3CA7C04000`**, the same as 2026-11-05, and again on 2026-11-10 after the service restart (session `47420892ccbd4f6c-b43422ca5fb64631`, with `module + 0xb25d78` again `0x3ca871ee08`). Module offsets are fixed addresses on this host (`re4_switch.KNOWN_BASES`; `module_base()` still checks and re-finds) |
| bss layout | 4 KiB reads every 64 KiB over `0xb00000..0x1cd0000`, then `read_memory` jobs bisected to the row edges | every page readable; Citron maps it as **11 host rows** (`re4_switch.BSS_ROWS`: cuts at `0x127d000 0x1280000 0x1286000 0x1386000 0x138b000 0x148b000 0x1491000 0x1591000 0x1bb6000 0x1cb6000`). An adapter read must stay inside one row (the 18.4 MB single read failed "not mapped"); a whole dump is 11 parallel jobs, **3.9 s**, 2.6 s between the first and last row |
| heap windows | 4 KiB reads every 64 MiB from `0x5c00000000` | readable `0x5d2c000000-0x5dac000000`, `0x5db0000000-0x5dbc000000`, `0x5dc4000000-0x5dec000000` (`HEAP_WINDOWS`); the 2026-11-05 player and unit addresses (`0x5d559cafe0`, `0x5d55a77ad0`) lie in the first |
| pointers into the heap | the main-menu bss dump | 1,289 qwords (801 into `0x5d34xxxxxx`, 61 into `0x5d55xxxxxx`) |
| the score routine's game state | `module + 0xb25d78` | `0x3ca871ee08` at the menus: a pointer back into main's data (`module + 0xb1ae08`), as the 2026-11-05 pass read in a round |
| no clock at the menus | two full bss dumps 2-3 min apart (title, main menu) | **0** f32 in 2..121 that fell by a wall-rate amount, for any gap 0.8-8 s; a menu timer at `module + 0x113dcf8` moved 30.02 -> 30.00. Slices kept as `tests/fixtures/re4sw_bss_menu.json` |
| **why there was no round** | frames 1 s apart, classified by `re4_switch_screens` | the main-menu walk went cursor 1 -> 5 in 11 s, then `unknown` -> **title** -> main menu cursor 1 again, three times (17:27:58-17:28:27 and before). `re4switch_bot`'s stall escape fires 12 s after the last *named-screen* change; a cursor move never reset it, LOAD -> EXTRAS is four steps at the walk's 3 s gap, and its first press is `b`, which on the main menu is "back to the title". The playbook could not reach a round on any boot; fixed in 7.2 |
| the same, after the 00:03 UTC service restart | session `47420892ccbd4f6c-b43422ca5fb64631` (2026-11-10, worker `47420892ccbd4f6c`), frames 1 s apart | the identical loop **five times in 100 s** (18:11:14-18:12:52 local): cursor 1 -> 5, `unknown`, `title`, every ~19 s. The deployed code does not carry the fix, so every RE4 turn ends at its no-progress cut |

So the in-round fields - the clock's address this boot, the player, the Ganados, kills / combo / score - were **not
measured**: no round was reachable without sending input, which this pass does not do. They are built to measure
themselves (the clock) or to be measured by one probe run (the rest), 7.4.

### 7.2 What the code does now

| piece | file | behaviour | evidence |
|---|---|---|---|
| walk: the escape | `re4switch_bot.py` | a cursor move (or a select screen's steering step) on the same named screen restarts the stall clock, at most `CURSOR_PROGRESS_MAX = 12` times per screen | the live loop above, replayed in `test_the_main_menu_walk_reaches_extras_without_the_escape_backing_it_out`; a cursor that never settles still escapes |
| walk: the pace (2026-11-10) | `re4_switch.Pace`, `next_is_move`; `re4switch_bot.py` | a cursor move every 0.8 s once the read cursor shows the last one (2 s without: again); a confirm after its screen has been named 1 s and, on the main menu / EXTRAS, two reads on the target; the per-screen confirm gaps still guard a fading screen; the driver's gaps run on the playbook's clock. An unnamed picture right after the stage confirm is the fade: the round starts on the HUD, after the intro was paged, or after 6 s unnamed (the entry presses used to sleep through the load's black, so the intro was never armed). Stats: `walk_s`, `menu_presses`, `title_returns` | the live loop's cause, from its telemetry: session `47420892ccbd4f6c-b43422ca5fb64631` ended with `story_recoveries` 31, `rounds` 0 after about 10 minutes - the escape's first `b` once per ~19 s loop, not the game's idle return. `test_the_walk_reaches_a_round_fast_and_never_backs_out`: a closed-loop menu simulation (fades drop presses, a 30 s idle return to the title, A on LOAD opens the story list) reaches the round in 19.5 s, no `b`, no story screen; `Pace` unit tests |
| walk: the HUD | `re4switch_bot.py` | a frame the classifier names `playing` (the HUD) is in the round; before, it went to the menu branch where `step()` returns nothing, so the cadence ran only on frames it could *not* read | tests |
| DJ pick | `re4_switch.py` (`request`, `SELECTION`, `selection_moves`, `step`, `press_gap`), `re4_switch_screens.py` (`Reader` steering), `re4switch_bot.py` (`selection_of`) | the launch's `game.launch.mercmode.selection` is steered to: `dright` x portrait index on Select Player, `STAGE_MOVES` on the 2x2 stage grid (Village 0 TL, Castle 1 TR, Base 2 BL, Waterworld 3 BR), one move per `STEER_GAP_S = 1.0`, then confirm. The reader keeps the moved (now unmatched) picture named as the select screen with `moved` counted, until the confirm or another screen | **inferred**: the grid and one portrait per press are the GameCube layout (`re4_menus`); no frame of a moved cursor exists yet |
| `selection_job` | `mercmode.py`, `screensaver.py` (passes `pick['map_id']`) | RE4 Switch -> `None` (the pick rides the launch, as RE6 Switch's does); GameCube RE4 unchanged (`re_mods mercs_select`) | `test_an_re4_switch_pick_rides_the_launch_not_the_gamecube_select_tool` |
| the round clock | `re4_switch.py` `ClockFinder`, `clock_candidates`, `pick_clock` | per boot: two reads of the bss (hints `CLOCK_HINTS` = the 2026-11-05 cluster `module + 0x1274710`, stride 0x30, read first, then every row) >= 0.8 s apart; keeps an f32 that read 2..121 and **fell by 0.6-1.4 x the wall time**; the cluster's copy nearest the median, lowest address on a tie; then one f32 a read. A value that holds 4 s is re-confirmed by its fall (a pause); a non-finite read starts the search again | synthetic cluster tests; recorded menu bytes give 0 candidates |
| units | `re4_switch.py` `UnitCensus`, `unit_addresses`, `read_unit` | the objects of `PLAYER_CLASS` / `ENEMY_CLASSES` by their vtable word (`module + class`) in `HEAP_WINDOWS` (16 MiB reads, numpy), re-scanned every 4 s inside the pool the first scan found; health `u16 +0x3c2`, type `+0x3ce` (code-derived), id `+0x110`, position `U_POS`, facing `U_YAW`; duplicates (two mappings) collapsed by id + health + type | synthetic heap tests. **PENDING**: the class and offset constants are `None` |
| snapshot | `re4_switch.snapshot(m, now, search)` | re5_switch's shape: `timer`, `clock_addr`, `player`, `enemies`, `kills/combo/score` (from `MERC_*`, pending); `search=False` from the menus' `screen()` | tests |
| the fight | `re4_switch.Bot` | per tick, in order: own hazard underfoot -> step off; 3 Ganados within 2 m -> the quick turn (`ldown` + `b`) and away; a target inside the 12 m engage range (the nearest; in a mob of 4 within 6 m the one nearest the gun's line; once a kill is owed the quickest kill) -> turn with the left stick and the gun down past 0.35 rad, raise (`zl`) and fine-turn with the **right** stick inside it, tap `zr` inside 0.12 rad once the gun has been up 0.25 s, every >= 0.25 s, through the operator's gates (range; line of sight = the stage mesh's `floor_segment` when `snap["nav"]` exists; no own hazard); after 8 shots and nobody within 3.5 m -> reload (`zl` + `b`); nobody in range -> run to the nearest Ganado (`lup` + `b`, steered by an attached mesh walker, else the mesh's `route`, else straight); nobody known -> sweep (walk, turning 3 s each way). Never stand: 1.5 s without 40 cm of ground and without aiming -> a 0.8 s step with a turn. Kills: the game's counter once mapped, else census units whose health fell to 0; the combo is owed 3 s after a kill (doctrine `KILL_PACE_S`). The doctrine `Director` measures every tick and its commands come back through `doctrine.Reader` | `test_re4_switch_fight.py` (24), `test_re4_switch_brain.py` |
| the playbook's fight | `re4switch_bot.py` | in a round, with the player in RAM: `Bot.tick` through `Keys` (a held key down once, up when let go; a tap down + up); the frame every 5th tick. Without the player: the blunt cadence as before, its action press now Y (the manual's action button; it was A), `stats["fight"] = "frame"` | `test_with_the_player_in_ram_the_bot_fights_through_holds_and_taps` |
| round boundaries | `re4switch_bot.py` (`round_boundary` param, `Round`, `_boundary`, `_report`), `mercmode.accept_boundary` | `tools._start_playbook` now passes `round_boundary` (play's signature names it). One boundary per round id: **results** when the clock was seen counting, read >= 60 s at some point, then read 0 for 1 s with at least that many seconds / 1.4 of wall time between (`tally_ready`, `timer: 0`, `clock_high`; a short countdown taken by mistake cannot end a round), **dead** when the player was read alive and then at 0 health. The witness carries `clock_verified`, `player_verified`, `kills`/`kills_source`, `clock_addr`, `hud_seen`; character and stage are the *requested* ones (`character_source: requested`). `accept_boundary` takes `clock_verified` in place of `player_verified` for **RE4 Switch results only** (a death still needs the player's health) | `test_re4_switch_results_count_on_the_clock_witness`, `test_the_clock_witness_is_re4_switch_only`, `test_the_re4_switch_playbook_boundary_shape_is_accepted`, playbook boundary tests |
| mercs_bot | `mercs_bot.py` | an RE4 Switch pick goes to `re4_switch.request` too, for when the engine path takes the title (`mercs.ready` stays false) | - |
| the probe | `scripts/re4sw_round_probe.py` | one live round, read-only: waits for the HUD, two bss dumps -> the clock (the driver's own finder); `memory_search` for each class lead's vtable word in a heap window, each object read twice -> moving f32 triples (U_POS votes), health; bss dumps every ~4 s -> monotonic small-step u32 / u16 (kills, combo, score shapes). Refuses a session not `agent_owned` | smoke-tested on synthetic dumps only |

Controls (Capcom's official RE4 Switch manual, `docs/research/mercenaries-character-specials.md` 1.1 on main, source
S37; not yet exercised by this bot live): ready weapon ZL, aiming with the right stick while it is held; fire ZL + ZR;
**reload ZL + B** (the first cut had `RELOAD_BTN = "r"`, but R is "Give orders" - Krauser's Plaga arm in Mercenaries;
now `SPECIAL_BTN`); knife L + ZR; action Y (every melee prompt, "(Y) KICK"); run B + stick up; 180 turn B + stick down.
Inferred and flagged in the code: that an error > 0 turns right (the first cut's contract; no live facing read exists);
the stage grid layout and one portrait per cursor press.

### 7.3 Control plane vs worker

| needs | files |
|---|---|
| **gbox.service restart** (control plane) | `gbox/mercmode.py` (`selection_job`, `accept_boundary`), `gbox/screensaver.py` (the `selection_job` call) |
| **the worker's bot code** (lilspark's worker: a bot reload covers only modules loaded at worker start - memory note *hot reload traps*; a restart is the safe way, and on lilspark it is the same `gbox.service`) | `gbox/re4switch_bot.py`, `gbox/mercs/titles/re4_switch.py`, `gbox/mercs/titles/re4_switch_screens.py`, `gbox/mercs_bot.py` |
| nothing | `profiles/gamedata/010099A00BC1E000-ram.json` (a note; `mercs.ready` stays false), the probe, tests, this doc |

Without the worker files deployed, every RE4 turn keeps looping on the main menu until its no-progress cut.

### 7.4 What you must verify live, in order

1. **The walk reaches a round** (deploy first). Frames: title -> main menu (cursor steps down to EXTRAS) -> EXTRAS ->
   THE MERCENARIES -> Select Player -> Select Stage -> loading -> the round. No `b` on the main menu
   (`stats.stall_steps` stays 0). Failure looks like today's loop.
2. **The clock**: within ~2 s of the clock starting, `stats.timer` follows the HUD clock and `stats.clock_addr` is set
   (expect near `0x3ca8e78710`). Failure: `timer` stays `None` (no float fell by the wall time: emulation far off
   100 %, or the clock is not in the bss this build - widen `CLOCK_RATE`, or the probe's candidates say where).
3. **The boundary**: at the round's end (clock 0) `stats.last_boundary` and `stats.boundaries_posted == 1`, then
   `mercmode_rotate_requested` when the turn's rounds are done; MercMode's log shows the round counted (not a
   no-progress cut). Failure: `mercmode_boundary_error` names the refusal.
4. **The probe** in that round (`python system/scripts/re4sw_round_probe.py --out <dir>`, the bot walking): from
   `report.json` set `PLAYER_CLASS` (the class with one object that moves as he walks), `ENEMY_CLASSES` (objects that
   move and lose health at `+0x3c2`), `U_POS` (the top position vote), and the `MERC_*` counters (kills step by 1 per
   kill, score by the kill score); then find `U_YAW` (a float that turns with `lleft`/`lright`) - the 2026-11-05
   sin/cos pairs were the camera's. Check the turn sign: `err > 0` must turn him toward the target.
5. **The fight**: `stats.fight == "ram"`, shots and kills_seen climbing, `doctrine_idle_s` near 0, `stand_breaks`
   small, no long-range fire through walls (12 m gate).
6. **A DJ pick**: queue Ada / Castle; frames on Select Player and Select Stage show the cursor on Ada and the Castle
   cell before the confirm. Failure: Leon / Village (steps not taken), the wrong portrait (one press is not one
   portrait, or a locked character is skipped) - adjust `selection_moves`.
7. Then `mercs.ready` (two boots at 20 Hz), and `perception` in `re_switch.preferred_spec` can drop "screen-only".

### 7.5 The snapshot contract (for the RE4 map, the mesh walker and live mods)

`re4_switch.snapshot(m)` returns re5_switch's shape, so the tactical map and the RE4 room-collision mesh walker (branch
`wt-re4-map-20261110`) plug in unchanged: `player = {"pos": (x, y, z) cm, "rot": rad (0 = +z, + toward +x), "hp",
"hp_max", "ptr", "class", "id"}`, `enemies = [{"slot", "ptr", "pos", "rot", "hp", "hp_max", "class", "id"}]`, `timer`,
`clock_addr`, `kills`, `combo`, `combo_timer`, `score`, `module_base`. `room` is not read (no room id is measured on
this build); the map fills `snap["nav"]`, which the fight uses for line of sight (`floor_segment`) and the run
(`route`), and `Bot.walker` (`approach(goal) -> stick keys`) takes over the run when attached.

### 7.6 Fields for live mods ("RE4 dynamically adjusted on the fly")

| field | where | state | what a mod could do |
|---|---|---|---|
| the round clock | f32 seconds, module + ~`0x1274710` (2026-11-05 cluster, copies every 0x30; found per boot by `ClockFinder`, `stats.clock_addr`) | found live 2026-11-05; the finder is offline-tested; **not read this pass** (no round) | freeze / add / cut time (write every copy of the cluster, read back) |
| unit health | `u16` at unit + `0x3c2` (code: the damage routine writes it) | offset from code; **which unit is the player, which are Ganados: pending** (`PLAYER_CLASS`, `ENEMY_CLASSES`) | player god mode / heal, enemy one-shot or armour |
| unit type | `u8` at unit + `0x3ce` (the damage table's index) | from code | enemy kind swaps (risky: the type picks the damage row) |
| the game state | pointer at module + `0xb25d78` -> main's data (`0x3ca871ee08` this boot); fields `+0x5037` difficulty, `+0x503c` mode (score x10/x5/x2), `+0x84f0`, `+0x984` (decompiled score routine) | pointer read live; fields from code, not read | difficulty / score-multiplier mods |
| kills, combo, combo window, score | `MERC_*` | **pending** (the probe lists monotonic small-step counters) | combo-window extension, score boosts |
| ammo | - | **not looked for** | infinite ammo |

Tests: `test_re4switch_bot.py` (20), `test_re4_switch_menus.py` (40), `test_re4_switch_brain.py` (3),
`test_re4_switch_fight.py` (24), `test_re4_switch_anchors.py` (19), `test_mercmode.py` (+4).
