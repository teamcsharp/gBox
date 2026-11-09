# RE5 Switch: the player cast pool — a generic slot writer, a shared donor survey and seeded overlays

2026-11-09. `gbox/re5_cast_writer.py` puts any usable library character onto any of the six Chris and Sheva
Mercenaries slots. `gbox/re5_donor_pool.py` decides which library characters are usable and deals them to slots from a
seed. It is shared with the enemy writer, so the same donor can be the player in one overlay and the zombie in another.

**Nothing here has been booted.** Every archive below passes the offline structural checks and has a CPU picture. None
has been loaded by the game, so none is known to load, to be drawn, or to look right. Do not describe any of them as a
character working in RE5. The accepted live Sonic is still v15 (`re5_sonic_writer`, `d96c9c9e…`), which this work does
not replace.

| | |
|---|---|
| Modules | `system/gbox/re5_cast_writer.py`, `system/gbox/re5_donor_pool.py` |
| Tests | `system/tests/test_re5_cast_writer.py` (16), `system/tests/test_re5_donor_pool.py` (14), synthetic fixtures only |
| Shared modules extended (opt-in, defaults unchanged) | `re5_mesh_import.build_archive`, `mtf_retarget.transfer`, `mtf_materials.source_mesh` |
| Outputs (not in Git) | `.scratch-merc-recovery/assets/sonic-compare-v1/`, `cast-a-v1/`, `cast-pool-01/`, `-02/`, `-03/` |
| Survey report (not in Git) | `.scratch-merc-recovery/cast/library-survey.json` |
| Registered | No. No `plan()` hook, no dispatch, `live_verified: false`, `replacement_scope.complete: false` |

## The six slots, read from the archives

`re5_char_swap.catalogue()` lists 41 player archives. The six Mercenaries classes are the ones the pinned player
vtables name (`mercs/native/re5_ebffdb22/vtables.py`), and each archive is named after its class. Which costume an
archive holds was read from the archive: its body model was decoded and drawn with its own textures.

| roster label | archive | SHA-256 | body models (MOD / MRL entry) | what the decoded model shows |
|---|---|---|---|---|
| Chris (BSAA) | `uPl00ChrisNormal.arc` | `8ab0dc18…` | `pl00\model\pl0000` 97 / 87 | BSAA tactical gear |
| Chris (Safari) | `uPl00ChrisCos1.arc` | `fa3f0a85…` | `pl10\model\pl0000` 140 / 129, base `pl00\model\pl0000` 134 / 123 | open patterned short-sleeved shirt |
| Chris (STARS) | `uPl00ChrisCos2.arc` | `4df4a987…` | `pl11\model\pl1100` 140 / 129, base 134 / 123 | green S.T.A.R.S. vest |
| Sheva (BSAA) | `uPl01ShebaNormal.arc` | `77e9ede6…` | `pl01\model\pl0100` 92 / 78 | purple top, BSAA gear |
| Sheva (Clubbin) | `uPl01ShebaCos2.arc` | `f63256a6…` | `pl13\model\pl0100` 126 / 111, base `pl01\model\pl0100` 121 / 106 | gold halter top, miniskirt, bob |
| Sheva (Tribal) | `uPl01ShebaCos1.arc` | `d550005e…` | `pl12\model\pl1200` 129 / 114, base 124 / 109 | leopard top, red loincloth, tooth necklace |

- **Sheva's costume numbers are crossed.** `Cos1` holds the tribal outfit and `Cos2` the club outfit. A table built from
  the file names alone would have put each donor on the other slot.
- **A costume archive holds two bodies.** It carries the costume's own model beside the base body, which is byte for
  byte the model of the `Normal` archive. The executable names both model paths. Which of the two the costume class
  draws was not determined offline, so the writer puts the donor in both. Two models share a basename in
  `uPl00ChrisCos1` and `uPl01ShebaCos2` (`pl0000`, `pl0100`), so every entry is addressed by index.
- **The same animation ids sit at other bone indices in other models.** The head is bone 4 in `pl00\pl0000` and bone 66
  in `pl10\pl0000`; the left hand is 81 and 45. Each model gets its own measured role map.
- Every entry of the six archives is a wrapped zlib stream that recompresses byte-identically at level 6 with tag
  `0x40000000 | size`, and `mt_arc.build(parse(x)) == x`.
- The body lives in option group 0 (62 to 189 records); the native skin weights root bone 0 almost nowhere and hangs
  the hips off the pelvis, animation id 15, as on the Majini.
- Not replaced: the other body variants in each archive (`pl0500`, `pl0900`, `pl0a00`, `pl0600`, `pl0b00`, `pl0c00`),
  the one-bone and head models (`pl0001`, `pl0002`, `pl0101`) and the `evf` face models. The live Sonic v15 replaced
  only `pl0000` and Mercenaries drew it, which is the evidence that the others are not the Mercenaries body.

## Role map of a slot

`measure_roles()` reads the fifteen role bones from the bind pose alone. A player skeleton carries face, hair, gear
and twist bones, so a chain is followed by where it leads: the root's two trunks are the pelvis (reaches the floor)
and the spine (reaches the top); the chest is the first spine joint with a far-reaching branch on each side; the neck
is the chest's midline branch that reaches the top; along an arm the next joint is the child that reaches farthest
out, along a leg the child that reaches lowest. `role_map()` accepts the result only when it names the same bones as
the RE5 animation ids. Both agree on all ten body models of the six archives.

| role | animation id | Chris `pl00\pl0000`, `pl11\pl1100` | Chris `pl10\pl0000` | Sheva (all three models) |
|---|---|---|---|---|
| hip | 15 | 111 | 111 | 1 |
| chest | 2 | 2 | 2 | 21 |
| head | 4 | 4 | 66 | 23 |
| l_upper / l_fore / l_hand | 11 / 12 / 14 | 77 / 79 / 81 | 36 / 41 / 45 | 108 / 112 / 115 |
| r_upper / r_fore / r_hand | 6 / 7 / 9 | 46 / 50 / 54 | 7 / 12 / 14 | 79 / 85 / 88 |
| l_thigh / l_shin / l_foot | 20 / 21 / 22 | 117 / 119 / 120 | 114 / 116 / 117 | 8 / 9 / 10 |
| r_thigh / r_shin / r_foot | 16 / 17 / 18 | 112 / 113 / 114 | 119 / 120 / 121 | 2 / 3 / 4 |
| lower spine (waist-jointed donors) | 1 | 1 | 1 | 20 |

Bind positions are the same in every Chris model (hip 0, 114, 0; chest 0, 132, −1.34; head 0, 165, −2.34; wrists
±70.4, 150.78; ankles ±9.2, 13.5) and in every Sheva model (hip 0, 104.5, 0; head 0, 152.3, 0; ankles ±7.5, 13).

## Fit: the donor in the native pose, at the native height

The fitted surface comes from `re5_mesh_import.build_archive(pose_mode='native_segments')`: each donor joint lands on
its native bind joint and no bind joint, inverse bind or motion resource is edited. The weapon stays in the native
hand and the camera on the native head. Limbs and the spine stretch to the native segment lengths.

- **Scale.** Every donor is brought to the slot's native height with its soles on the floor
  (`native_height_scales`). One body scale is solved so the top of the fitted head reaches the native model's top
  (186.6 cm for Chris, 169.8 to 170.3 cm for Sheva). Each foot keeps that scale across and takes its own scale upward
  so its lowest vertex lands on model y 0. Both numbers are in every receipt (`fit.scale`). A metadata field `size`
  (`large`, `small` or a factor) changes the target height; **no library entry sets one today**, so all 650 usable
  donors are built at native height. The words "large" or "short" in free-text notes are not parsed.
- **Proportions are native, not the donor's.** A human-proportioned donor (Snake, a DOA or Def Jam character, a
  PSO android) comes out looking like itself. A mascot with a large head and short limbs comes out tall and thin: its
  head is scaled down to fit the native height and its limbs are stretched to human length. SA2 Sonic's body scale is
  4.6 cm per source unit and his limbs are about 2 cm thick. This is the price of leaving the bind pose and the motion
  alone; v15 pays a different price (moved joints, scaled root motion, hands below the camera).
- **Torso.** A donor with a spine of its own follows hip, chest and head. A donor whose torso hangs on one joint at the
  waist (PSO, Jet Grind Radio, RE2, Sonic Adventure and others) follows the native lower spine, animation id 1,
  instead of the chest and is stretched from there to the head. Its shoulders then follow the native chest while its
  torso follows the lower spine, so a strong upper-body twist can open a seam at the shoulders.
- **Normals** are the donor's own, carried through the fit. A donor without normals is faceted.
- **Winding.** A donor exported with clockwise fronts (Melee, some SoulCalibur II) has each triangle turned.
- **Record.** One mesh record replaces the whole body: option group 0, LOD mask `0xFF`, mesh id 1, the four-weight
  layout, fifteen envelope records. Option group 0's sphere is rewritten around the donor, as the Sonic recipe does.
- **Material.** Each model uses a native material with the measured standard shader of the one material a donor has
  been drawn with (Chris's Gear, material 108): the same render-state words and the same forty commands. Between 43
  and 133 materials per model qualify. The one whose shader constants are nearest to Gear is taken, the larger albedo
  breaking ties: Gear itself for the base Chris body (512×256), Knife for Safari (256×512), Head for STARS
  (1024×1024), arm skin for Sheva BSAA and Clubbin (1024×1024), hand for Tribal (1024×512). Its albedo receives the
  donor atlas, its normal map becomes flat and its mask zero. The MRL entries are untouched.

## Donor survey

`re5_donor_pool.survey()` resolved all 1,483 folders of the host library (models and metadata copied read-only).

**650 usable, 833 refused.** A folder is usable when a role profile passes `rig_check`: fifteen distinct joints,
limbs in order, left on +X, facing +Z, every skinned joint a role or below one, every role followed by some vertex,
consistent winding, a torso with length. The profile is the folder's own metadata in 638 cases and that metadata with
a measured repair in 12 (a hip, chest or foot role moved onto the joint that carries the skin).

| franchise | usable | refused | games (usable / entries) |
|---|---|---|---|
| Wrestling | 174 | 93 | WCW-nWo Revenge 91/92, WWF No Mercy 64/64, WCW vs. nWo World Tour 19/45, WWF SmackDown! 2 0/66 |
| Def Jam | 112 | 4 | Def Jam: Vendetta 112/116 |
| Metal Gear | 62 | 30 | MGS2: Substance 38/38, The Twin Snakes 23/52, VR Missions 1/2 |
| Dead or Alive | 58 | 45 | Dead or Alive ++ 58/88, Dead or Alive 2 0/15 |
| 007 | 42 | 52 | Agent Under Fire 42/91, Nightfire 0/3 |
| Stranglehold | 39 | 0 | 39/39 |
| Jet Set Radio | 30 | 2 | Jet Grind Radio 30/32 |
| Resident Evil | 23 | 9 | RE2 21/23, RE5 Gold 2/2, RE4 0/5, RE6 0/2 |
| Smash Bros. | 22 | 8 | Melee 22/30 (Mario, Luigi, Peach, Bowser and others) |
| Phantasy Star Online | 20 | 133 | PSO Ver. 2 9/9, Episode I & II Plus 11/144 |
| Sonic | 20 | 10 | Sonic Adventure 2 12/13, Sonic Adventure 8/8, 2D games 0/9 |
| SoulCalibur | 16 | 51 | SoulCalibur 12/19, Soul Calibur II 4/48 |
| Grand Theft Auto | 13 | 8 | GTA III 3/3, Liberty City Stories 10/18 |
| Final Fantasy | 7 | 20 | Final Fantasy VII 7/27 |
| Mario | 6 | 31 | Super Mario 64 DS 4/26, Super Mario 64 2/8, 2D games 0/3 |
| Render96 model pack | 3 | 4 | 3/7 (a model pack, not an extracted game) |
| Zelda | 2 | 5 | Ocarina of Time 2/7 |
| Shenmue | 1 | 0 | 1/1 |
| none usable | 0 | 328 | Marvel vs. Capcom 2 (177), Tetris DS (76), Clay Fighter (16), Crazy Taxi (9), Metal Arms (8), Parasite Eve (5), no metadata (37) |

Refusals by reason:

| reason | entries | what it is | mostly |
|---|---|---|---|
| `rig_refused` | 233 | a role profile exists but the measured rig refuses it | SmackDown! 2 (63, normals disagree with half the faces), SoulCalibur (47, mostly Soul Calibur II: about three quarters of the triangles are wound against their normals), World Tour (26) and DOA++ (14) face −Z or cross their feet, DOA++ (16) sides swapped |
| `no_rig` | 214 | the model has no skin | Marvel vs. Capcom 2 (177), RE4 PS2 exports without metadata (36) |
| `no_roles` | 132 | no complete role profile in the metadata, and the joint tree gives none | PSO Episode I & II (105), Super Mario 64 DS creatures (18) |
| `no_model` | 107 | a 2D sprite sheet, not a model | Tetris DS, Clay Fighter, 2D Sonic and Mario |
| `duplicate` | 95 | the same model bytes as another entry | second dumps of 007, MGS2, The Twin Snakes, PSO |
| `unsupported_surface` | 51 | the bounded atlas importer cannot pack the surface | a clamped or mirrored sampler used outside 0..1 (DOA2 15, 007 8, FF7 6), vertex colours (Parasite Eve, RE4 remake), tiling beyond the atlas budget |
| `no_textures` | 1 | no texture image | Mr. Game & Watch |

Three groups look recoverable and are not attempted here: turning each triangle to its own normal (Soul Calibur II,
Crazy Taxi 2, GTA: about 60), recomputing normals where the donor's are unusable (SmackDown! 2: 63), and turning a
model that faces −Z (about 46).

"Usable" means the rig resolves. It does not mean the fit looks right: the eight Sonic Adventure donors resolve, and
the CPU picture of `sa1_sonic` shows his legs detached from his one-piece torso. They were left out of the pool
overlays by name. A slot can also refuse a usable donor (its surface does not fit that slot's atlas, or its head joint
gives no height to solve); the pool then sets the donor aside and deals again from the same seed.

## Seeded assignment

`re5_donor_pool.plan(seed, slots, donors, history=…, avoid_last=3, games=…, exclude=…)` returns `{slot: donor}`:

- a donor at most once per overlay;
- donors of the last `avoid_last` overlays in `history` are dealt only when nothing else is left;
- franchises are taken in turn, so 174 wrestlers do not crowd out 6 Mario donors;
- `games` keeps donors of the named game titles or franchises;
- the same seed, slots, donors and history always give the same plan.

## Alternative Sonics in the Chris (BSAA) slot

`python -m gbox.re5_cast_writer compare` built every 3D Sonic-like donor of the library into `uPl00ChrisNormal.arc`
with the same path and drew them under one light and one pose (`sonic-compare-v1/contact-sheet.png`, one PNG per
donor, `comparison.json`). The 2D entries (`s3k_sonic`, `sk_sonic`, `sonic2_sonic`, `sonic1_shadow`) are sprite
sheets and cannot be donors.

| rank | donor | source | triangles / vertices | skin | textures | what the picture shows |
|---|---|---|---|---|---|---|
| 1 | `sonic` | SA2, `SONICMDL.PRS` | 1,369 / 1,422 | 7 % blended, 29 skinned joints | 4, 32 to 128 px | whole and connected, smooth shading, the reference |
| 2 | `sa2_super_sonic` | SA2, `SSONICMDL.PRS` | 1,369 / 1,316 | 8 % blended | 4, 32 to 128 px | the same mesh with raised quills; its extracted textures are blue, not gold |
| 3 | `sa2_shadow` | SA2, `TERIOSMDL.PRS` | 1,543 / 1,818 | 10 % blended | 5, 32 to 64 px | whole and connected; a different character, dark on a dark stage |
| 4 | `sa2_super_shadow` | SA2, `SSHADOWMDL.PRS` | 1,543 / 1,916 | 9 % blended | 4 | as Shadow |
| 5 | `sa2_metal_sonic` | SA2, `METALSONICMDL.PRS` | 1,312 / 974 | 20 % blended | 8, 16 to 64 px | rigid leg plates leave a gap at each knee once the legs are stretched |
| 6 | `sa1_sonic` | SA1, `SONIC.PRS` | 1,001 / 1,074 | rigid, torso on one waist joint | 16, 8 to 64 px | legs detached from the torso |
| 7 | `sa1_super_sonic` | SA1, `SUPERSONIC.PRS` | 1,046 / 1,140 | rigid, torso on one waist joint | 15, 8 to 64 px | legs detached from the torso |

All seven carry their own normals, so none is faceted. All are Dreamcast models with textures of 128 pixels or less;
texture resolution does not separate them. Every one is a tall, thin figure in this fit (body scale 4.2 to 5.0 cm per
unit), and each glove is one rigid piece of about 6 cm on the native hand bone, with no fingers.

Top three: **SA2 Sonic**, **SA2 Super Sonic**, **SA2 Shadow**. SA2 Sonic is also the v15 donor, and v15 with its
source proportions and articulated fingers is still the better-looking Sonic we have; this comparison picks the donor,
not the recipe.

Not judged offline: how the Gear material shades any of them, whether quills hide the aim line from the game camera,
how the stretched limbs look in motion, and whether the gloves meet the weapon.

## Overlays

Each folder holds `romfs/nativeNXx64/ImgNX/Archive/<archive>.arc` for all six slots, `receipt.json`, a
`contact-sheet.png` and one PNG per slot. One boot carries all six; the bot shows another character by picking another
roster slot.

### `cast-a-v1` — the Sonic family and Mario, assigned by name

| slot | donor | source game | triangles / vertices | body scale, feet upward | atlas scale | SHA-256 |
|---|---|---|---|---|---|---|
| Chris (BSAA) | `sonic` Sonic | Sonic Adventure 2 | 1,369 / 1,422 | 4.6, ×1.3 | 1 | `d23d3002f3549d963bee72f804acd94477773261630a4af39dfb537abc5c287f` |
| Chris (Safari) | `sa2_tails` Tails | Sonic Adventure 2 | 1,180 / 1,087 | 6.12, ×1.4 | 1 / 1 | `619acdc284c33b580377aa2e520beff9f0bced2e6f3ef1c36b1c90efb1742298` |
| Chris (STARS) | `sa2_knuckles` Knuckles | Sonic Adventure 2 | 1,241 / 1,254 | 5.86, ×1 | 1 / 1 | `53c758f5fec3216b9d70348c9740831ed5ef658e4452ecd75225844f6bef3393` |
| Sheva (BSAA) | `sa2_shadow` Shadow | Sonic Adventure 2 | 1,543 / 1,818 | 3.46, ×1.9 | 1 | `9843d1ef2d5ecbe7ab9ea3c475f53ed91fa7b583d9709fa2565ce74ed6d16804` |
| Sheva (Clubbin) | `sa2_rouge` Rouge | Sonic Adventure 2 | 1,280 / 1,303 | 4.23, ×1.6 | 1 / 1 | `959e9b75cf05f1084b6d25f9b71345d91d20d966afa88397da73933c01ad302d` |
| Sheva (Tribal) | `melee_mario` Mario | Super Smash Bros. Melee | 4,718 / 3,880 | 37.5, ×7.7 | 0.25 / 0.5 | `5e0c8511d432a85ea537765710fe6f50cd7d632c8b0d5f2914465811de3ed1a7` |

### `cast-pool-01` — seed `20261109-01`

Dealt from 650 usable donors. 8 donors were left out by name (the Sonic Adventure rig) and 6 were set aside because a slot refused them; the plan was dealt again from the same seed each time.

| slot | donor | source game | triangles / vertices | body scale, feet upward | atlas scale | SHA-256 |
|---|---|---|---|---|---|---|
| Chris (BSAA) | `auf_thug_alpine_inside` Alpine guard | 007: Agent Under Fire | 1,629 / 1,297 | 1.89, ×1.7 | 1 | `323d873c1a3b3afcd19f1db3e3350afbc1b78ee42dace925df9649bb8b193846` |
| Chris (Safari) | `jgr_char05_bd43233f27d78508` Goji | Jet Grind Radio | 732 / 947 | 8.04, ×0.54 | 0.5 / 0.5 | `8bef21e255ebe9eacc9d0d8a7f6a6cad39277aae74d6cb9ca03f7aeac4f0c280` |
| Chris (STARS) | `sc_voldo` Voldo | SoulCalibur | 3,699 / 4,250 | 105, ×0.95 | 1 / 0.25 | `3b6e2af9d6807b5dadfed681ea7c68ea173036331247603084695999726611ef` |
| Sheva (BSAA) | `ff7_vincent_field` Vincent Valentine | Final Fantasy VII | 560 / 1,672 | 0.0562, ×4.3 | 1 | `11609de7424d66b1713f09721f1be34b5d147cea5f79e8d3b1cba9bad657da32` |
| Sheva (Clubbin) | `djv_ps2_razor_1` Razor | Def Jam: Vendetta | 2,060 / 1,573 | 84.3, ×1.1 | 1 / 1 | `9d552becf8f8fc70c143ca977226761ccc0e0001c64f505e66a1318600d71c48` |
| Sheva (Tribal) | `melee_younglink` Young Link | Super Smash Bros. Melee | 4,724 / 3,758 | 52.4, ×1.7 | 0.5 / 1 | `043ac0c33555579571a077294b11d0fe9b2c26549001930a038220feb5a1ddfc` |

### `cast-pool-02` — seed `20261109-02`, history: pool 01

Dealt from 650 usable donors. 8 donors were left out by name (the Sonic Adventure rig) and 1 were set aside because a slot refused them; the plan was dealt again from the same seed each time.

| slot | donor | source game | triangles / vertices | body scale, feet upward | atlas scale | SHA-256 |
|---|---|---|---|---|---|---|
| Chris (BSAA) | `auf_malprave_suit` Malprave | 007: Agent Under Fire | 1,785 / 1,384 | 2.13, ×0.91 | 0.5 | `8019481b88dfd56d5907fd8f0bdb8ed62c48a8ee8825e0860d3144b801449b5b` |
| Chris (Safari) | `sc2_necrid` Necrid | Soul Calibur II | 8,012 / 6,364 | 115, ×0.83 | 0.125 / 0.125 | `9cd891dd630fe0c300f325401a50831f91b1bc29163c23cee1a808ff1a308295` |
| Chris (STARS) | `yoshi_hd` Yoshi | Render96 ModelPack | 8,407 / 4,698 | 38.4, ×1.5 | 1 / 0.25 | `8d3c4068c4c9805fb8f6fe164f5ced7f943d50abb9cc40b5749c260cb77e28bb` |
| Sheva (BSAA) | `doapp_kasumi_2_59c55e95af61abbe` Kasumi | Dead Or Alive ++ | 750 / 1,024 | 68.2, ×1.5 | 1 | `35398b6734b0d4f44facc91a398da3a40d36b3acd79740f448d3a8a754a124d8` |
| Sheva (Clubbin) | `gta3_claude_prison` Claude, prison outfit | Grand Theft Auto III | 1,362 / 1,236 | 92.4, ×0.84 | 1 / 1 | `da927710958f97d05c71896b1d8a6d9dde496ca5ea4111a01729d470d8acc04f` |
| Sheva (Tribal) | `pso_gc_fonewearl` FOnewearl | Phantasy Star Online Episode I & II Plus | 1,031 / 903 | 5.72, ×1 | 1 / 1 | `d092dbd7d9898f9656405724bccda87eb6611d6142d1ae747322e1d8128a79f5` |

### `cast-pool-03` — seed `20261109-03`, history: pools 01 and 02

Dealt from 650 usable donors. 8 donors were left out by name (the Sonic Adventure rig) and 0 were set aside because a slot refused them; the plan was dealt again from the same seed each time.

| slot | donor | source game | triangles / vertices | body scale, feet upward | atlas scale | SHA-256 |
|---|---|---|---|---|---|---|
| Chris (BSAA) | `mario_hd` Mario | Render96 ModelPack | 19,312 / 10,055 | 49, ×2 | 0.125 | `0a6df5630977f5ec6776a77824c81f1cde1732ba0c262e206cdf8c5b36736701` |
| Chris (Safari) | `tts_in_gus_blue_def_bf3675da8955e248` Genome Soldier | Metal Gear Solid: The Twin Snakes | 1,785 / 1,691 | 124, ×0.59 | 0.125 / 0.125 | `49791fcd155193046dc9bc2a5ab2826aa2ccb9463b307027bd221823f91cff29` |
| Chris (STARS) | `ryo` Ryo Hazuki | Shenmue | 1,793 / 1,498 | 79.8, ×1.5 | 1 / 0.5 | `2aa24afc9c7d8aec661791f0b255452366bb5834d80834b238d236b8ce825b04` |
| Sheva (BSAA) | `re5ps3_chris_normal` Chris Redfield | Resident Evil 5: Gold Edition | 15,584 / 14,240 | 82, ×1.1 | 0.25 | `1ce789098001944e33cd27fc418ececf1dfe8a654ba3fa43cd15b088ade14fbf` |
| Sheva (Clubbin) | `sm64ds_luigi` Luigi | Super Mario 64 DS | 455 / 1,356 | 2.15, ×4.4 | 1 / 1 | `452a3c27bb72db04f013a60df982108d882461aed4d3cc32c52f3be37bf5738c` |
| Sheva (Tribal) | `stranglehold_rm_lieutenant_3` Russian mob lieutenant 3 | John Woo Presents Stranglehold | 7,720 / 5,387 | 102, ×0.95 | 0.25 / 0.5 | `735bcb18403d562f99fd7b458b371be3620ec0bc20ff0bcdfb490271eb0b544d` |

The body scale is centimetres per source unit, so it says nothing by itself: source units differ by game. "Feet
upward" is how much more the feet are scaled vertically than the body to reach the floor; far from 1 means the donor's
ankle joint sits far from where a native ankle sits (`ff7_vincent_field` ×4.3, `sm64ds_luigi` ×4.4, `melee_mario`
×7.7). An atlas scale below 1 means the donor's textures were reduced to fit that slot's atlas; ×0.125 on the two small
Chris atlases (512×256 and 256×512) will look blurred.

In `cast-a-v1` the sixth donor is Melee's Mario rather than Luigi or an SM64 Mario: 61 joints and 18 % blended skin
against 17 to 21 rigid joints, and its own normals where the DS model has none. Rouge is taken over Amy for the same
reason (23 % blended skin against 18 %).

Two donors of the pool overlays are not extracted from an owned game: `yoshi_hd` (pool 02) and `mario_hd` (pool 03)
come from the Render96 model pack, and their receipts say so. `--exclude` or `--games` keeps them out.
`re5ps3_chris_normal` (pool 03) is the PS3 edition's Chris fitted as a donor onto Sheva's skeleton, not a native swap.

## Checks that were run

`verify()` runs inside every build. It was run again on every written file of the four overlays from a fresh process
(`python -m gbox.re5_cast_writer verify`), and each file's SHA-256 matched its receipt:

- entry count unchanged, names and hashes unchanged, every entry outside the reviewed indices byte-identical,
  `mt_arc.build(parse(x)) == x`;
- each replaced entry is a wrapped zlib stream equal to `zlib.compress(raw, 6)` with tag `0x40000000 | size`;
- each model: skeleton, material names, LOD distances and file trailer are the native bytes; the option-group table is
  native apart from group 0's sphere, which holds the donor; one record; the packed word re-derives as group 12 /
  material 12 / LOD 8; `(vertex_buffer − meshes − 56) = 144 · count` and the header count at `0xA0` equals it; vertex
  and face accounting close; every index lies in the vertex window; vertices inside the written bounds; skin bones in
  range and among the slot's role bones; weights sum to one; unit normals; atlas UVs inside 0..1;
- textures keep their TEX container, dimensions, format and mip layout; MRL entries are untouched;
- the same inputs gave the same SHA-256 in separate processes (`sonic` on Chris BSAA: `d23d3002…` in four separate runs).

The shared-module changes are byte-neutral for the existing recipes: on this branch `build_grip_candidate` still gives
`d96c9c9e…` and `re5_enemy_writer.build` still gives `322c58a1…`.

The pictures decode the written MOD and the written BC7 atlas. The posed columns sample `wp00` clip 25, frame 30,
through `mtf_motion.sample_compare`; that clip needs no engine IK. They are not the game's material, lighting, IK,
clip layering or camera.

## Reproduce

```powershell
cd system
$py = "..\.venv-session-audit\Scripts\python.exe"
& $py -m gbox.re5_cast_writer survey  --library LIBRARY --out survey.json
& $py -m gbox.re5_cast_writer compare --archive ROMFS\nativeNXx64\ImgNX\Archive\uPl00ChrisNormal.arc `
      --library LIBRARY --donors sonic,sa2_super_sonic,sa2_metal_sonic --out OUT
& $py -m gbox.re5_cast_writer pool    --romfs ROMFS --library LIBRARY --survey survey.json --seed 20261109-01 --out OUT1
& $py -m gbox.re5_cast_writer pool    --romfs ROMFS --library LIBRARY --survey survey.json --seed 20261109-02 `
      --history OUT1\receipt.json --out OUT2
& $py -m gbox.re5_cast_writer cast    --romfs ROMFS --library LIBRARY --assign chris_bsaa=sonic,sheva_bsaa=mgs2_snake --out OUT
& $py -m gbox.re5_cast_writer verify  --original ORIGINAL.arc --candidate WRITTEN.arc
```

`LIBRARY` is a character library folder (`<slug>/meta.json` and the model), `ROMFS` the extracted RomFS root. `--games`
restricts a pool to game titles or franchises; `--exclude` leaves donors out by name.

## For the enemy writer

`re5_donor_pool` has no player-specific code. `resolve(folder)` returns a `Donor` (slug, game, franchise, model file,
SHA-256, fifteen role joints, where the profile came from, size) and the measured rig; `rig_check` is the judge;
`survey` and `plan` work on any slot list. The enemy writer still carries its own Mario role table; taking a `Donor`
instead is a change to that module, which this branch does not make.

Three things the enemy fit would need from here, because they are what made arbitrary donors hold together on the
player: the spine segments (`hip → chest → head`; with limb segments alone the torso tears and the head floats on a
donor whose spine is short), the per-role scales of `mtf_retarget.transfer`, and the waist-joint mapping.

## Before and during a first live round

Install only as a separate `recovery-*` overlay through `switch_mods`, never into the live v15 build. Boot one slot
before all six: Chris (BSAA) first, since `pl0000` with a one-record table and the Gear material is the only
combination a donor has been drawn with.

What can go wrong, by slot, and how it would show:

1. **Chris (BSAA).** The record shape, material and textures are v15's. New here: the native bind pose, hips on the
   pelvis bone (v15 used root 0), group 0's sphere around a different shape. A donor torso that stays behind while the
   legs walk, or a model that pops out at the screen edge, points at those two.
2. **Chris (Safari), Chris (STARS), Sheva (Clubbin), Sheva (Tribal).** Two unknowns each. If the slot shows the native
   costume, the class draws a model this overlay did not replace. If it shows the donor twice, slightly apart, it draws
   both bodies. The atlas material is also new on each: too dark, glossy, see-through or skin-toned means the material
   does not suit a body. STARS uses a head material.
3. **Sheva (BSAA) and both Sheva costumes.** No donor has been drawn on the Sheva skeleton at all. A load hang, black
   screen or frozen first frame here and not on Chris points at the Sheva models; bisect by slot.
4. **Any slot, any donor.** Stretched limbs that look wrong in motion; a rigid glove that does not meet the weapon;
   feet scaled upward that read as stilts (Melee Mario's are scaled seven times upward); a shoulder seam on a
   waist-jointed donor; faceted shading on a donor without normals; a head or hair that hides the aim line.
5. **Roster order.** The bot's labels name roster entries by index. That index 4 loads `uPl01ShebaCos2` and index 5
   `uPl01ShebaCos1` follows from the costumes read here and the game's own names; it was not observed.

Acceptance needs what the handover asks for any replacement: build and session ids, the loaded overlay hash, frames in
which the slot visibly is the donor while fighting, advancing score, and which of the points above were seen. A boot is
not acceptance and a title screen is not gameplay.
