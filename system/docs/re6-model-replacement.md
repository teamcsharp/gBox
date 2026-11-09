# RE6 model replacement: scale-exact fitting, a Smash cast roster, and the round hook

## Target platform: **RE6 on Switch** (No Mercy edition)

The deliverable is the Switch edition (`01002A000CD48000`, gBox game id `115f9cdbba115432`), never the Xbox 360
disc. The Switch game keeps the same role/character layout as the 360 edition but native little-endian MTF resources:
one body `.arc` per character **and costume** under `nativeNXx64/arc/NX` (`uPl00LeonUsa.arc`, `uPl00LeonAsia.arc`,
`uPl00LeonOmake00.arc`, ...), with the body's `data\chara\pl\plNNNN\model\plNNNN` entry holding an `MRL` (materials) and
a `MOD` (geometry + 54-bone skeleton). Heads, hands and hair are **separate** archives (`uPl00HeadLeonUsa.arc`,
`uPl00HandLeftLeonUsa.arc`, `uPl00HandRightLeonUsa.arc`, `uPl00AcHeadLeonUsa.arc`), and player textures live in
`uPlTex####_*.arc` files.

The Switch writer (`gbox/re6_switch_models.py`, measured 2026-11-09 on the extracted RomFS) parses the body arc with
`mt_arc`/`mt_model`, maps the 18 anatomical roles to native bone indices by the **RE6 global bone ids carried in the MTF
bone headers** (hip 1, chest 2, neck 3, head 4, right arm 5–8, left arm 10–13, right leg 16–18, left leg 20–22), fits
the donor uniformly into the native quantisation box (source proportions, feet on the floor, hip over the root), moves
the native bind joints to the donor's joints, authors the mesh with `mtf_author`, and replaces only the MOD entry. Head,
hand and accessory-head archives are replaced by a single degenerate triangle so the donor is the whole visible body.
Everything is emitted as a LayeredFS overlay through `switch_mods.write_files` (`romfs/nativeNXx64/arc/NX/...`), never a
disc edit.

Measured: SSBU Sonic (`sonic_ssbu`, 8,094 triangles, 18/18 roles) onto **all six Leon costumes** — 6 body arcs + 24
blanked part arcs = 30 overlay files, 33.5 MB, 53 s. Every authored body reads back as 4,981 vertices / 8,094 triangles
on the native 54-bone skeleton with the original parent list. A z-buffered render of the authored arc:

![SSBU Sonic authored onto the RE6 Switch Leon body](evidence/re6-scale/switch-sonic-on-leon.png)

The role ids are the same family **on every character**, but the bone *order* differs (Helena's head is index 13, Ada's
left clavicle 22), so `roles_for` always resolves them from the anim ids instead of hard-coding indices. The
`gbox.re6_switch_models.body_arcs` scan finds **51 native body slots** (9 characters including Carla and the helper,
every costume; `uPl01AcHeadHelenaAsia.arc`-style head/hand/accessory/texture archives are excluded) and every one maps
the 18 roles. The roster planner (`gbox.re6_switch_cast.plan`) puts a distinct library donor on each slot and
`gbox.re6_switch_cast.build` authors them all into one overlay, so the game's own per-round character/costume select
rotates the cast — `re6 op=switch_cast_plan` previews it, `re6 op=switch_cast` builds it, `re6 op=switch_cast_status`
reads it.

Measured roster (`re6sw_smash_cast`, seed 7, 2026-11-09): **all 51 native body slots, 51 distinct donors** (SSBU and
Brawl mixed), **255 overlay files**, built in **47 s** once the per-slot body cache is warm (341 s cold). The five slots
whose native skeletons cannot take the measured joint moves (Piers' `Canon` has more than one root; four Sherry costumes
have anchor branches that cannot hold the donor's proportions) fall back to **`pose_mode=native_skeleton`**: the native
skeleton is kept, the donor surface rests at its own proportions and binds rigidly to the nearest native bone, so the
slot is filled and only animation deformation is approximate. The builder still skips (and reports) a donor that cannot
be authored at all. Rigid donor props (Robin's sword and tome, Dark Pit's bow) are placed with their node transform.
Every authored body reads back on its native skeleton; heights are 180 cm unless the native quantisation box forces a
smaller uniform fit (Sherry's Snow costume clamps to 97.5 cm, Incineroar on Piers to 163.2 cm).

| Robin on Leon (USA) | Peach on Ada (A) | Greninja on Chris (Europe) | Dark Pit on Sherry (Europe, skeleton fallback) |
|---|---|---|---|
| ![Robin](evidence/re6-scale/switch-robin-as-leon.png) | ![Peach](evidence/re6-scale/switch-peach-as-ada.png) | ![Greninja](evidence/re6-scale/switch-greninja-as-chris.png) | ![Dark Pit](evidence/re6-scale/switch-darkpit-as-sherry.png) |

All 51 slots, rendered from the built overlay (label = slot ← donor):

![RE6 Switch roster contact sheet](evidence/re6-scale/switch-roster-contact-sheet.png)

The round hook: `re6 op=switch_cast host=<PC> mercmode_default=true` sets `default_mods.re6` on that PC's MercMode, so
every RE6 round it plays boots the roster build; `session_id=<id>` also launches the title there with it. The build is a
LayeredFS overlay, so the worker running the emulator must hold `cache/mods/115f9cdbba115432/<build>` (copy it with the
usual mod delivery). `re6 op=switch_cast_plan` shows the assignment and the same `default_mods` hint without writing
anything.

The only remaining Switch gap is **donor textures**: RE6's body MRL has no embedded texture table (`uPlTex*.arc`
hold them), so the first port replaces geometry and the native material still samples its own textures. `gbox.re6_switch_tex`
parses the containers (TEX `v0xA1` revision `0x20`, 20-byte header + mip offsets) and decodes the measured formats:
BC4 `0x19` masks, BC5 `0x1F` normals, BC7 `0x30/0x31`, and the `0x2B` albedo. The albedo is **two channels per 16-byte
block**: bytes 0-7 are BC4 and decode to a real greyscale detail map (Leon's head map resolves to his face with the
mouth/teeth atlas), bytes 8-15 are BC1 and decode to a low-resolution per-4x4-tile colour that is nearly uniform inside
a tile. Decoding the detail layer is proven; whether the shader combines it with that colour half (and how) is not, so
`Surface.decode` returns the detail layer and `_albedo_layers` exposes both. The MRL v36 material records carry only a
name hash (five 72-byte records, identical except `0x6390b116`, `0x61c18195`, `0xa56925da`, `0xf8c8d02f`, `0x68b3d093`),
so the material→texture binding is still unnamed. New measurement (round 8): the body MOD carries the material **names**
themselves at offset `0x24D4` (`pl_cloth`, `pl_base2`, `pl_cloth1`, `pl_base1`, `pl_skin`, 128 bytes each), and the MRL
v36 hash is exactly `crc32(name) ^ 0xFFFFFFFF` — all five match (`0x6390b116`, `0x61c18195`, `0xa56925da`, `0xf8c8d02f`,
`0x68b3d093`). The MOD contains **no texture references** (every texture-name hash was searched in the file), so the
material→texture link is a runtime convention, not a stored table. The encoder side now exists:
`re6_switch_tex.replace_albedo` writes a new mip chain in that same two-half layout (BC4 detail plus a flat per-tile BC1
colour) and round-trips through a real TEX at **49.4 dB** detail PSNR, and `re6_switch_tex.export_textures` writes a
character's whole texture set (Leon: 272 surfaces, 241 PNGs) so the reader is exercised on every measured format.

The rest of this document describes the earlier **Xbox 360** analysis. It is kept because the scale/bind lessons are
platform-neutral and the 360 measurements are what the Switch fit reuses, but its writer and mods are **not** the
deliverable and are not exposed as RE6 Switch output.

2026-11-09. This continues the RE5 same-table work (`docs/research/re5-same-table-sonic.md`) on Resident Evil 6
(Xbox 360, Xenia; game id `0871eee3b68cdea3`, title 43430819). The RE5 review showed that the failures reported as
"the model does not load" were, after the zlib-6 and MRL fixes, mostly **scale and bind-pose** failures: fitting a
donor into the native bounding box made Sonic 70.9 units tall, and fitting each limb to the native bone lengths
stretched his proportions (arm/height 0.25 instead of 0.16). RE6's writer had the same second problem. This is the
port of the fix, plus the cast pipeline that uses it.

## The scale-exact fit (`re6_models.fit_source_proportions`)

RE6's player `.mod` (big-endian, version 0xD3) stores, per bone, a local 4x4, an inverse bind 4x4 and a 24-byte record
with the rest translation. Vertex positions are quantised against one uniform transform `D` (scale + offset) that is
folded into every inverse bind: `real = q / 32767 * D`. Animations were authored against that transform, in particular
the absolute root translations some bones carry, so a new `D` reinterprets every translation channel.

The segment retarget (`pose_mode='segment'`, the earlier path) matched each limb to the native bone lengths and
clamped the total height into 150..195 cm. Measured on the SA2 Sonic donor against Leon's body (`uPl00LeonUsa.arc`):

| build | decoded height | arm / height | triangle count |
|---|---|---|---|
| native Leon body (`pl0000`) | 162.2 cm (bbox -0.29..161.94) | — | — |
| `pose_mode='segment'` | 212.9 cm | 0.250 | 1369 |
| `pose_mode='source_proportions'` | 180.0 cm | 0.16153 | 1369 |
| donor surface (SA2 Sonic) | 10.805 units | 0.16152 | 1369 |

`source_proportions` works the other way round:

1. Scale the donor **uniformly** to the requested height (default 180 cm), centred on the donor hip when available,
   with its feet on the native floor and its hip above the native root.
2. Check every position against the native quantisation box (`quantisation_box`): translation is used first; only if
   the model cannot fit is it reduced uniformly (never stretched).
3. Move the **native bind joints** to the fitted donor's joint positions (`reposition_bind_pose`): rotations,
   hierarchy, root and the compression transform stay untouched; intermediate bones on an anchored path are placed by
   arc-length interpolation so a limb follows two measured joints instead of leaving a gap. Inverse binds are rebuilt
   from the resulting world matrices with the original `D`.
4. Bind every vertex rigidly to the bone of its nearest named ancestor (`_role_joint_resolver`), so a donor without a
   complete skeleton still maps onto the native one; unmapped vertices fall back to the root and are counted.

The result round-trips through the writer and decoder within 0.01 units and stays inside the quantisation box
(measured q range 0.0100..0.7338 for the 180 cm Sonic). Evidence:

![Sonic fitted with the segment retarget: stretched arms and legs, detached shoes](evidence/re6-scale/sanic-segment-fit.png)
![Sonic fitted with source proportions: the donor surface is preserved](evidence/re6-scale/sonic-source-proportions.png)

The write path is `re6 op=build_mod character=sonic target=leon scale={"pose": "source_proportions", "height": 180}`
(the `scale` dict also carries the Retarget editor profile). `re6_models.write_body(..., dequant=...)` keeps the
measured transform; without it the writer derives a new one, which is correct for the segment path only.

## The cast roster (`gbox/re6_cast.py`) and the round hook

RE6 keeps one body archive per native character: `nativeXenon/arc/X360/uPl00LeonUsa.arc`, `uPl01Helena*`,
`uPl02Chris*`, `uPl03Piers*`, `uPl04Jake*`, `uPl05Sherry*`, `uPl06Ada*` (+ `uPl00Head*`, `uPl00HandLeft/Right*` for
the head and hands, which the writer hides, and `uPlTex####_*` for the material textures). The Mercenaries character
select picks one of those native characters each round, and `gbox.mercs.round_controls.Controls.choose_character`
already randomises that choice and never repeats a family back to back.

So the roster is one mod that replaces **every** player slot with a different collection character:

```python
from gbox import re6_cast
assignment = re6_cast.plan(entries, seed=7)      # {leon: mario, helena: sonic, ...}
rotation = re6_cast.rotation(assignment)          # [{select_id: 0, native: leon, cast: mario}, ...]
```

Because each native slot now shows a different cast member, the game's own round rotation shows a different Smash
character every round **without a relaunch per round**: the archive is loaded at boot, and the round-to-round change
is the game's native select. `re6 op=cast` builds the roster (all costumes per slot) and `re6 op=cast_status` reports
the installed assignment; `re6 op=cast_plan` previews it. A DJ round (MercMode `queue[].mod`) can also name the
roster build explicitly for one round, which is the documented per-round override. To make every round of the title
boot with the roster, set MercMode's per-title build — `POST /api/mercmode`
`{"host": "<pc>", "default_mods": {"re6": "re6_smash_roster"}}` (`gbox.mercmode.choose` attaches it to the round
selection; a DJ entry's own `mod` still wins). `re6 op=cast host=<pc>` returns that patch and, with
`mercmode_default=true`, applies it.

Measured roster build on the i9-NUC (2026-11-09, `re6_cast.build`, source-proportion fit, 180 cm): the seven SA2 /
Mario collection characters went into one `re6_smash_roster` mod in 168 s — 217 changed arcs, one per body/head/hand
and texture archive of every slot:

| select id | native slot | cast member |
|---|---|---|
| 0 | Leon | Tails |
| 1 | Helena | Sonic |
| 2 | Chris | Shadow |
| 3 | Piers | Mario |
| 4 | Jake | Rouge |
| 5 | Sherry | Amy Rose |
| 6 | Ada | Knuckles |

![Tails fitted into RE6's Leon slot by the roster build (source proportions)](evidence/re6-scale/roster-tails-as-leon.png)

Honest limits: this is **not** real-time in-memory model swapping. Loading a different body archive mid-round is not
supported by the engine's resource system, so a *different* build (for example a new cast assignment) still needs a
relaunch; what rotates per round is the native character, and with it the cast member. The same applies to the PC,
PS3 and PS4 editions: only the Xbox 360 writer is measured.

## Tools and hooks

| hook | what it does |
|---|---|
| `re6 op=capabilities` | lists the writer targets, the two pose modes, the cast slots and the honesty limits |
| `re6 op=build_mod character=… [target=…] [scale={…}]` | one native character (all costumes) |
| `re6 op=cast [cast=slug,slug] [seed=N] [height=180] [launch=true]` | the whole roster mod, optionally launched |
| `re6 op=cast_plan` / `cast_status` | preview the assignment / report the installed one |
| `re6_cast.plan / rotation / current` | deterministic assignment, select-id mapping, which cast member a round shows |
| `gbox.mercs.round_controls` | the existing native per-round character rotation the roster rides on |
| `gbox.re6_tool.build_character` / `build_combined` | the per-target and enemy-family writers (unchanged) |

## Smash Ultimate Sonic inserted into RE6 (measured 2026-11-09)

`gbox.ssbu_arc` reads the base game's `data.arc` (14,460,050,172 bytes) and returns the four model files
(`model.numdlb` references the geometry in `model.numshb`; `model.nusktb`/`model.numatb` are the skeleton and
materials) plus the material textures `<name>.nutexb`; the container facts are in the module docstring.
`gbox.ssbu_models` decodes the SSBH `MODL`/`SKEL`/`MATL`/`MESH` payloads into a skinned glTF (Sonic: 8,294 triangles,
5,098 vertices, 115 joints, 7 textures, 18/18 body roles), and `roles_from_bones` maps the fighter chain onto the
collection body roles. The collection entry `sonic_ssbu` ("Sonic (Smash Ultimate)") was registered and the writer
built `re6_ssbu_sonic` — 27 changed arcs, SSBU Sonic on Leon's slot with the source-proportion fit (10.8 -> 180.0 cm,
uniform scale 16.66, inside the quantisation box):

![SSBU Sonic fitted into RE6's Leon slot by the source-proportion writer](evidence/re6-scale/ssbu-sonic-as-leon.png)

This is the model-insertion half of the objective: the extracted Smash Ultimate Sonic is what RE6's Leon archive now
contains. Gameplay verification of this exact build (a live Mercenaries round) is still pending; the image is the
writer's read-back through the RE6 reader.

## The Brawl cast, one character per costume (measured 2026-11-09)

`gbox.ssbb_models` reads the Brawl fighter PACs (ARC container -> BRRES -> MDL0 v9 + TEX0/PLT0) and extracted
**all 46 fighter directories** of the operator's own disc (39 playable roster entries plus Giga Bowser, Wario-Man,
Pokemon Trainer and the four Sandbag props; 313,114 triangles, 60 MB of GLBs, every GLB round-trips through
`characters.rig_from_gltf`). `roles_from_bones` maps the Brawl `HipN/WaistN/BustN/NeckN/HeadN/...` chain to the
collection roles. Known role gaps (measured, never invented): Brawl Sonic has no Head bone (15/18), Kirby / Meta
Knight / Jigglypuff have no neck/head (15/18), Pikachu has no head (17/18), and R.O.B.'s non-standard bone names
(Bane/Fjiku/Nemoto/DummyLegJCon...) map only 6/18, so it is extracted and registered but stays out of the automatic
cast until a role map is supplied.

RE6 stores one body archive **per costume** (`uPl00LeonUsa.arc`, `...Asia.arc`, ...), and the Mercenaries character
select randomises the costume too, so `re6_cast.plan_per_costume` puts a different collection character on **every
costume of every slot**. The roster `re6_brawl_cast` therefore covers all 44 costume slots with 41 distinct Brawl
fighters (the 41 with a complete role map; three repeats fill the last slots):

| select id | native slot | costumes (Brawl characters) |
|---|---|---|
| 0 | Leon | Kirby, Mr. Game & Watch, Luigi, Giga Bowser, Ivysaur |
| 1 | Helena | Squirtle, Sheik, Meta Knight, Ganondorf, Lucario, Wario-Man |
| 2 | Chris | Pit, Sonic, Pikachu, Charizard, Pokemon Trainer, Mario |
| 3 | Piers | Captain Falcon, Fox, Wolf, Yoshi, Ness, King Dedede, Princess Peach |
| 4 | Jake | Pikmin & Olimar, Marth, Diddy Kong, Falco, Ike, Lucas, Donkey Kong |
| 5 | Sherry | Zero Suit Samus, Samus, Wario, Bowser, Link, Solid Snake, Zelda |
| 6 | Ada | Jigglypuff, Toon Link, Ice Climber (Popo), Kirby, Mr. Game & Watch, Luigi |

With MercMode's per-title build set to `re6_brawl_cast`, every RE6 round boots that mod and the title's own
character/costume pick shows a different Brawl fighter; `re6 op=cast per_costume=true` rebuilds it with another seed.
`re6 op=cast_plan per_costume=true` prints the 44-row plan without building.

Measured build (i9-NUC, 2026-11-09, seed 11, source-proportion fit): `re6_brawl_cast` in **256 s** — 217 changed arcs,
44 costume slots, 41 distinct fighters. The uniform fit lands most fighters at 180.0 cm; a T-posed donor wider than the
native box is shrunk uniformly (recorded as `height_clamped`), e.g. Diddy Kong at 155.7 cm, Kirby at 176.5 cm — never
stretched. Previews of three slots:

| Pit as Chris (Europe) | Diddy Kong as Jake (Monitor) | Jigglypuff as Ada (A) |
|---|---|---|
| ![Pit](evidence/re6-scale/brawl-pit-as-chris.png) | ![Diddy](evidence/re6-scale/brawl-diddy-as-jake.png) | ![Jigglypuff](evidence/re6-scale/brawl-jigglypuff-as-ada.png) |

(The preview is the repo's painter's-order rasteriser, so dense overlapping meshes like Kirby's body and face show
some mottling; the geometry and textures are the game's own.)

## What is not done yet

- **Gameplay verification of the source-proportion builds.** The offline read-back and previews are checked for every
  donor; the two live Mercenaries frames for Mario-as-Leon predate this fit and do not verify it. Neither
  `re6_ssbu_sonic` nor `re6_brawl_cast` has been captured in a live round yet.
- **R.O.B.** is extracted and registered but its non-standard bone names map only 6/18 roles, so it is left out of the
  automatic cast until a role map is supplied. Brawl Sonic (no Head bone) and Kirby / Meta Knight / Jigglypuff (no
  neck/head) keep their mapped roles; their head geometry binds to the nearest named ancestor.
- **SSBU texture payload**: the GLBs carry 512x512 BC7 textures with full mip chains (Link's is 12.6 MB); shrinking
  them to the 1024² atlas the RE6 writer uses would make a full SSBU roster practical. Three SSBU eye/base textures
  have no entry in the base-game archive and fall back to a material colour (documented by the extractor).
- **Multi-weight skinning**: the writer binds rigidly (one bone per vertex), which is why live limbs deform rigidly.
  `mtf_retarget.map_weights` already produces up to four influences and the RE6 vertex format carries four; only the
  author path is missing.
- **Animation retargeting**: RE6's `.lmt` motions are native; donors reuse RE6's animations (rigid bind), not their
  own.
