# Handover: RE6 (Switch) model replacement + Smash cast + fast autoplay menus

Written at the end of the automation run on 2026-11-09. Everything below is measured in this repo unless marked
otherwise. The goal, the state, the systems, the failures, and the exact next steps are separated so the next owner can
pick up without re-deriving anything.

---

## 0. Update, same day, offline work (branch `wt-re6-switch-20261109`)

Done on a PC without the assets: the files were copied read-only from the game host (Leon's sets, all 51 body arcs,
the default costumes' parts and first texture set, 34 donors, the shader package; 0.35 GB). **Nothing below has been
loaded by the game.** It replaces §2.3, the "known defect" of §3.4, §4.5, §4.14 and §5.3; those are amended in place.

### 0.1 The colour path: the albedo is Y'CbCr, the VTF is not colour

- **`0x2B` is BC3 holding Y'CbCr + alpha.** The alpha block (bytes 0-7) is luma `Y'`; the colour block (bytes 8-15)
  holds `Cr` in red, `Cb` in blue (neutral = 5-bit code 15) and the opacity in green. Formula, gamma space, values 0..1:

  ```
  Y = alpha block     Cr = red - b     Cb = blue - b     opacity = green        (b = 15/31; the engine may use 0.5)
  R = Y + 1.402 Cr    G = Y - 0.34414 Cb - 0.71414 Cr    B = Y + 1.772 Cb
  material: albedo = RGB x CBMaterial.fDiffuseColor (1,1,1 on every player material measured)
            FColorMaskAlbedoMapModulate adds the blood tint CBColorMask.fColorMaskColor (0.45, 0.05, 0.09 on the
            jacket) where the blood mask passes thresholds that are 0 at rest
  ```

- The "constant second half" (`c0 = c1 = 0x7FEF`, indices `0xAAAAAAAA`) is a **neutral, opaque tile** (Cr = Cb = 15,
  opacity 63), not a missing colour. Measured over Leon's set: it fills 100 % of the black eye cover, 40 % of the
  shirt, 15 % of the head, 2 % of the jacket and **0 %** of the hand map; the hand's red code averages 17.8 and its
  blue 13.3 (Cr above neutral, Cb below: skin), and green runs 0..63 on hair and eyelashes (the cut-out).
- **Evidence for.** (1) Decoded this way the native maps are in their own colours: Leon's face (skin, pink lips,
  cream teeth), blue-grey iris, dirty-blond hair, orange fire on the effect sheets. (2) The same formula applied to
  the bytes of the installed `re6sw_sonic_leon_keep` (which wrote plain RGB into the colour block) gives teal quills
  (0, 0.48, 0.53) and pink gloves (1, 0.47, 1); the live frame measures hue 164 and 325. A swapped Cr/Cb gives orange
  quills, YCoCg gives yellow gloves, the old "RGB tint x luma" gives the intended blue. (3) The solid-red probe stays
  red (1, 0.11, 0), which is why it could not tell. (4) The title's `AppShaderPackage.mfx` holds exactly these
  constants (1.402, 0.34414, 0.71414, 1.772 with 0.5) in its Y'CbCr functions.
- **Not settled offline.** BT.601 against 709 and the bias (15/31 against 0.5) are second-order and the frames at
  hand do not separate them; where in the engine the `0x2B` decode runs was not located (the constants were found in
  `FSystemCacheDecodeCopy` / `FFilterComposite`, not in `FAlbedoMap`).
- **`pl_VTF` / `_MVTF` are the cloth's vertex displacement**, not colour: the jacket material binds `pl_VTF` to
  `tVtxDisplacement` and `pl0000_50_jacket_MVTF` to `tVtxDispMask` under `FVertexDisplacementCurveUV`
  (`CBVertexDisplacement.fVtxDispScale` 0 at rest). `pl_VTF` is 128x4 `float32`: rows 0 and 3 are smooth three-crest
  waves (values n/255, 0 at both ends, max 0.84 / 0.86), rows 1-2 zero. `_MVTF` is RGBA8, grey with alpha 255. "VTF"
  is vertex texture fetch. The hypothesis of §2.3 is refuted by the game's own bindings.
- The material binding is fully decoded (`re6_switch_tex.texture_set_materials`): 24-byte commands (kind, value,
  shader object), object id = 20-bit name hash over the package index, names from the `.mfx`. A one-mesh donor is
  drawn with **one** material and samples only that material's maps: on `uPl00LeonUsa` material 0 is `pl_cloth`
  (jacket), on `uPl00LeonAsia` it is `pl_skin1` (vest). The dirt variants `_0.._3` of a set bind **differently named**
  albedos (`pl0000_00jacket_BM` in `_0`, `pl0000_70jacket_d1_BM` in `_1`/`_2`), so a texture is resolved through each
  archive's own MRL (`re6_switch_models.material_texture_changes`).

### 0.2 Code

`re6_switch_tex`: numpy decoders (no `texture2ddecoder`), `Surface.albedo` / `.texels`, `encode_albedo` (Y'CbCr; a
grey tile is byte-for-byte the native constant block; `chroma=False` forces it), `pack_tex` (header + block-linear
layout from scratch), `rgba8_tex` (`0x09`), `float_tex` (`0x0E`), `replace_texels`, `shader_objects`. The storage
layout is the same GOB layout for every format, the unit being a 4x4 block or one texel, with zero padding: **351
native surfaces of five formats repack byte-identically**. `re6_switch_models`: `model_entries`, `slot_report`,
`body_materials`, `donor_material`, `texture_set_arcs`, `replace_textures`, `material_texture_changes`.
`re6_switch_cast`: `donor_check`, `pool_report`, `franchise`, `author_slot`, `plan(mix=)`, tiers.

### 0.3 Roster integrity (§4.14 settled, three other defects found)

- **Bone counts 36..89 are each costume's own skeleton**, not a wrong MOD. All 51 body arcs hold exactly one skinned
  MOD (`data\chara\pl\plNN00\model\plNNNN`, always with the 18 role ids) and two skeleton-less effect MODs
  (`md000c_02`, `md008c`); the seven `DebugId` arcs are one identical file (`pl9920`, 36 bones); Piers' cannon arm is
  89 bones with five roots. `_find_model` picked the right MOD by luck of entry order; it now picks by skeleton.
- **`blank_arc` blanked only the first MOD.** 23 accessory-head arcs hold two or three (`cs_plNN00/01/02`); the
  installed builds left 1510 + 3537 vertices drawn in Leon's. Fixed.
- **Material 0 was assumed for the donor.** On `uPl01HelenaUsa` and `uPl02ChrisAsia` it is `pl_nuki`, an alpha-tested
  patch material (`FTransparencyAlpha`): the donor would be cut out by a patch texture's alpha. `donor_material`
  picks the first opaque material without cloth displacement from the costume's texture set. The 51-slot
  `re6sw_smash_cast` on the build machine was built with material 0 throughout: rebuild it before testing.
- **The textured builds repainted `pl_Blood_BM`**, the shared blood mask, with the donor atlas. `texture_changes` now
  leaves `data\chara\textures\*` alone.
- **Which body is Mercenaries costume 1 is not measured.** The solid-colour probe held a donor on `uPl00LeonUsa.arc`
  and red albedos in both of Leon's sets; its frame shows a red *human* in the Asia outfit. So for Leon costume 1 is
  most likely `uPl00LeonAsia` (`pl0010`, set `uPlTex0010_n`), and `skin_swap.CHARACTER_ARCS` (Leon/Helena = Usa) may
  name a body Mercenaries never draws. The overlays below cover both of Leon's (and Helena's) campaign bodies.

### 0.4 Any franchise in the cast

The host library (`~/gBox_alt/gbox-cache/characters`, 1484 folders, 1447 with a `meta.json`) holds no Smash Ultimate
or Brawl donor (those are on the build machine). `re6_switch_cast` therefore casts **any** entry with the roles:

| tier | rule | usable entries | distinct characters | source games |
|---|---|---|---|---|
| `full` | all 18 roles on distinct joints | 519 | 385 | 20 |
| `core` | neck and clavicles may be absent (keep-bind only) | 984 | 803 | 37 |

`full` by game: Def Jam Vendetta 115, 007 Agent Under Fire 91, MGS Twin Snakes 52, Soul Calibur II 48, Stranglehold
39, MGS2 38, PSO Ep I&II 24 (+12 Return to Ragol), Smash Melee 23, SoulCalibur 19, GTA LCS 17, Crazy Taxi 2 8,
Render96 Mario 7, FF7 5, SM64 5, RE4 5, Parasite Eve 4, Nightfire 3, RE5 2, RE6 2. The rest: 325 rigs resolve 15/18
(no neck, no clavicles: WCW 137, Dead or Alive ++ 88, DOA2 15, Jet Set/Grind Radio 32, Sonic Adventure 1/2 21, FF7
11, PSO v2 9), 171 resolve 16/18 (no clavicles: WWF No Mercy 64, SmackDown 2 66, RE2 23), 179 are unskinned (Marvel
vs. Capcom 2), 117 resolve no role (PSO parts), 104 are sprite sheets (Tetris DS, Clay Fighter, 2D Sonic/Mario), 37
folders have no `meta.json`, 5 share a joint between two roles. `core` brings the 15/18 and 16/18 rigs in: keeping the
native bind needs no neck anchor (those vertices follow the next named ancestor); `reposition` still refuses them.

`plan(..., seed, mix=True)` is a seeded draw with no character twice in an overlay (the same character under two
slugs or two dumps of a game counts once) and no source game twice while unused games remain. `re6 op=switch_cast`
takes `mix=` and `tier=`.

**`keep` only fits a donor that rests in the native bind pose.** `bind_mode="keep"` leaves the donor surface in its
own rest pose and binds it to native bones that rest in a T-pose (arms along X, legs along -Y, identical on every
body measured). The native animations rotate those bones away from *their* rest, so a donor that rests with its arms
down carries that 90 degrees on both arms all round. The live-proven build was a T-posed donor. Measured gap of the
worst limb segment (`re6_switch_models.pose_deviation`): Melee fighters 2-19 degrees, RE5 Chris and Yunsung 0, 007
Agent Under Fire 5, Toni Cipriani 10 - but Solid Snake, Liquid Snake, Rock and the PSO hunters 90, Mario (Render96
and SM64) 77, Lei Fang 99, the Undertaker 96, Aerith 118, Aya Brea 135. `bind_mode="pose"` therefore turns the eight
limb segments of such a donor into the native bind directions first (`mtf_retarget.repose`, the RE5 writer's
routine; donor segment lengths kept, the native skeleton still byte-identical), and `author_slot(bind_mode="auto")`
uses `keep` up to 20 degrees and `pose` above. `pose` has never been loaded by the game; hands, feet and a twisted
torso (Lei Fang's stance) are not corrected.

### 0.5 What was built (offline, under `C:\_tools\gBox\.scratch-merc-recovery\assets\re6\`, each with `receipt.json`)

| overlay | files | what a live frame must show |
|---|---|---|
| `re6sw_probe_albedo_solid` | 7 | native Leon with one flat-coloured garment: blue jacket (USA body) or orange vest (Asia body) |
| `re6sw_probe_sonic_luma` | 17 | Sonic in greyscale (colour block neutral everywhere) |
| `re6sw_probe_sonic_vtf_white` | 17 | the same greyscale Sonic: `pl_VTF` = 1, `_MVTF` = white change no colour |
| `re6sw_sonic_leon_ycc` | 17 | Sonic in his own colours |
| `re6sw_roster_mix_s15` | 45 | Mario (Render96) on Leon, Liquid Snake, Aya Brea, Toni Cipriani, RE5 Chris, a 007 hostage, Aerith |
| `re6sw_roster_mix_s27` | 45 | Solid Snake (MGS2) on Leon, Yunsung, Liquid Snake (coat), HUmar, Nigel Bloch, Rock, a Nightfire grunt |
| `re6sw_roster_mix_core_s1` | 45 | Lei Fang (DOA++) on Leon, Liquid Snake, Yuffie, FOmarl, Goji (JGR), Mario (SM64), the Undertaker |

The Sonic probes reuse the installed build's bodies and parts byte for byte and change textures only; the rosters
are geometry-only with the native skeleton untouched (`keep` for the donors that rest in the bind pose, `pose` for
the others - each receipt says which), one donor per character on the seven bodies believed to be costume 1 plus
Leon's and Helena's USA bodies. Order to run them: `albedo_solid` first (it also says which body costume 1 is), then
`sonic_leon_ycc`; the two grey probes only if `ycc` is wrong.

---

## 1. The goal (as given)

> Expand the RE5 progress so RE6 becomes capable of model replacement. Extract Sonic from Smash Bros Ultimate and insert
> him into RE6. Extract all characters from Smash Bros Brawl/Ultimate and use them to replace RE6 characters, randomising
> them on rounds. The earlier work's problems were scale-related; create tools, agents and handler hooks that can execute
> these mods for the game, with live model replacement and character insertion.

Target platform is the **Nintendo Switch** edition of RE6 (No Mercy), **never** the Xbox 360/PS3 discs. Any X360 work must
be ported to Switch.

- Title id: `01002A000CD48000` (update v131072).
- gBox game id: `115f9cdbba115432`.
- RomFS overlay path inside builds: `romfs/nativeNXx64/arc/NX/…`.
- Emulator host: **lilspark** (worker name `lilspark`; its id changes every service restart — always resolve by name).
- Control plane: `http://10.89.1.246:8765` (this is the Spark). Token: `C:\_tools\gBox\system\gbox-data\api_token`
  (Bearer). From the automation node everything is driven through `POST /api/jobs` with `require_worker: "lilspark"` or
  direct endpoints (`/api/games/<id>/launch?node=lilspark&mod=<build>`, `/api/sessions/<sid>/frame.jpg`,
  `/api/sessions/<sid>/input`).

---

## 2. Status: what is done and proven

### 2.1 Model replacement works live (geometry)

- `re6sw_sonic_leon_keep_plain` (30 files, 33.5 MB) was installed on the Spark and played in Mercenaries No Mercy on
  Urban Chaos: the player was Sonic's mesh on Leon's native skeleton, camera and animations behaved (rounds played,
  score/kills advanced). Evidence: `docs/evidence/re6-scale/switch-live-autoplay-urban-chaos.jpg`,
  `docs/evidence/re6-scale/switch-live-sonic-leon.jpg`, offline render `docs/evidence/re6-scale/switch-sonic-on-leon.png`.
- The key fix for the earlier "distorted/giant/invisible" model was **not moving the native bind joints**. The live frame
  showed that `mtf_retarget.reposition_bind_pose` breaks the rest pose (native LMT animations carry absolute locals and
  are not rewritten). The default path is now `bind_mode="keep"`: the native skeleton is left byte-identical and the
  fitted donor surface is authored **in** that pose. `bind_mode="warp"` (keep skeleton, warp vertices onto native joints)
  exists as an alternative; `"reposition"` is kept only for A/B.

### 2.2 Smash roster is built (offline verified)

- Extracted library on the automation node: 74 SSBU fighters and 46 Brawl fighters (`D:\gBox\cache\characters`), with
  role-mapped rigs, e.g. Sonic `sonic_ssbu` 8,094 triangles, 18/18 roles.
- `re6sw_smash_cast` (255 arcs, 346 MB): all **51 native body slots** (7 characters × costumes + DebugId) authored with
  **51 distinct donor geometries**; 204 head/hand/AcHead part arcs are blanked to a degenerate triangle. Verified by
  parsing every arc: 51 body slots, 51 distinct `(vertex_count, face_count)` signatures, 204 part arcs.
- `re6sw_textured_cast` (298 files, 440 MB): the same roster with the donor atlas written into the `0x2B` albedos — built
  but **not** live-verified because the colour path is wrong (see §4.3).

### 2.3 Textures: path works, colour is wrong

> **Superseded by §0.1.** The second half is chroma (Cr, opacity, Cb), constant only on neutral tiles; `pl_VTF` /
> `_MVTF` are the cloth displacement inputs, not colour. The live observations below stand; the two explanations
> offered for them do not.

- The `0x2B` albedo replacement itself is live-proven: a **solid-red probe** rendered the character exactly red
  (`docs/evidence/re6-scale/switch-live-solid-colour-probe.jpg`), and a textured Sonic build runs in gameplay
  (`docs/evidence/re6-scale/switch-live-textured-sonic-urban-chaos.jpg`).
- But the textured build's **colours are wrong**: teal quills, pink gloves. Cause established: in native `0x2B` data the
  **second 8-byte half is a constant block in every 4×4 tile** (`c0 = c1 = 0x7FEF`, indices `0xAAAAAAAA`), i.e. not
  per-tile colour. Our `encode_albedo` writes per-tile colour there, so the engine's colour reconstruction does not match
  ours. The first half (BC4 greyscale detail) decodes correctly (`switch-native-albedo-detail-layer.png`).
- Strong lead for the real colour: `pl_VTF` is format `0x0E`, 128×4, and reads as **little-endian floats in 0..1**
  (0.039, 0.082, 0.129…), i.e. per-material colour parameters; `_MVTF` is `0x09` (RGBA8 mask). The shader most likely
  multiplies the `0x2B` detail by a VTF colour, which would tint any atlas written into the `0x2B`.
- The material → texture path binding is decoded (texture-set MRL v36, see §3.4): e.g. Leon's jacket =
  `pl0000_00jacket_NM/_BM/_MM` + `pl_VTF` + `pl0000_50_jacket_MVTF` + `pl_Blood_BM`; hands (`pl_skin`) =
  `pl0000_10Hand_NM/_BM/_MM` + `pl_Blood_BM`.

### 2.4 Fast menu automation: built, partly live-proven

- The RE6 Switch title driver (`gbox/mercs/titles/re6_switch.py`) already names every screen from RAM (`title`,
  `main_menu`, `play_game`, `extra_content`, `mercs_mode`, `select_stage`, `select_player`, `dead`, `results`,
  `loading`, plus dialogs).
- The bot now **selects and presses correctly**: live, the autoplay drove itself from the title to the campaign character
  select without any external input (after the deploy that fixed guest-memory reads); with plain D-pad keys a hand burst
  went PLAY GAME → EXTRA CONTENT → NO MERCY → SOLO → stage → character and reached a round in **~10 s of input**.
- New code in this run (all committed, see §6):
  - `fast_start()` / `fast_batch()` — one burst per screen: every cursor move at once plus the confirm, 25 ms polling,
    fixed deltas for the shipped menus, fallback to the confirmed Navigator if a screen does not move.
    Wired into `mercs_bot.Boot.tick` (burst on every menu screen it visits) and `mercs_bot.play`.
  - `gbox/mercs/menu_speed.py` — AIMD-learned cadence (`stable_s`, `retry_s`, `poll_s`), persisted per title, applied live
    through a shared `NAV_CURSOR` dict.
  - `eden_memory.guest_arena` now returns every **readable guest row**, and `re6_switch._rows` prefers them, so the
    main-module signature scan can find the title's mapping beside the memfd heap (the reason the bot previously never
    named a screen on the Spark).
  - Read robustness: a lost guest page now reports `unknown` instead of ending the run.

### 2.5 Handler hooks / tools

- `re6` tool Switch ops (`gbox/re6_tool.py`): `op=switch_cast`, `op=switch_cast_plan`, `op=switch_cast_status` with
  `romfs`, `library`, `slots`, `textures`, `seed`, `height`, `host`, `mercmode_default`, `session_id`. They build the
  overlay from the worker's own RomFS and write it through `switch_mods`.
- `switch_mods` (`op=write/select/status`) is the overlay writer/linker on the worker; `re6sw_*` builds live in
  `~/gBox_alt/gbox-cache/mods/115f9cdbba115432/<build>/romfs`, the load dir is
  `…/eden-linux/data/eden/load/01002A000CD48000` (symlinks).
- MercMode (`/api/mercmode`, `gbox/mercmode.py`): hosts, per-host settings (`titles`, `queue`, `keep_warm`,
  `preferred_editions`, `skin_swap`, `cast_swap`, `coop_ratio`, `default_mods`), queue entries
  `{title, mode, character, stage(int), mod}`. **The control plane on the Spark runs an older build than this repo**:
  it rejects `default_mods` and `repeat_queue` as unknown; everything else above is accepted. `mercmode` was left
  **disabled** on lilspark to stop it competing with manual launches.

---

## 3. Systems in depth (files, entry points, how to use/expand)

### 3.1 `system/gbox/re6_switch_models.py` — the RE6 Switch MTF writer

- `body_arcs(romfs)` → `{(character, costume): Path}` for the 51 body slots (excludes head/hand/AcHead/TEX archives).
- `buildable_slots(romfs)`, `roles_for(model)` — the 18 anatomy roles resolved from native bone headers
  (hip 1, chest 2, neck 3, head 4, right arm 5–8, left arm 10–13, right leg 16–18, left leg 20–22).
- `build_body(archive, source, *, source_roles, height=180, material_index=0, template_index=0, margin=0.01,
  atlas_size, textures=False, source_geometry=None, reverse_bones=False, bind_mode="keep") -> (payload, receipt)`:
  - parses the body arc, finds the MOD, fits the donor uniformly into the native quantisation box (feet on floor, hip
    over root), authors one mesh with `mtf_author`, replaces only the MOD entry.
  - `bind_mode="keep"` (default, live-proven): native skeleton untouched; donor surface authored in the native pose.
  - `"warp"`: same skeleton, vertices warped so mapped joints land on native joints (stretch, for proportion tests).
  - `"reposition"`: moves native bind joints to donor joints (breaks the rest pose live; A/B only).
  - `textures=True` takes atlas UVs from `mtf_materials.source_mesh`; pass the same atlas to `texture_changes`.
  - receipt keys: `pose_mode`, `bind_mode`, `fitted_height`, `uniform_scale`, `height_clamped`, `box_usage`, `roles`,
    `root_index`, `bind`, `skin`, `bones_reversed`, `triangle_count`, `vertex_count`, `model_entry`, `mrl_entry`,
    `archive_sha256`, `live_verified`.
- `blank_arc(archive)`, `part_stems(body)`, `donor_atlas(source)`, `export_preview(archive, gltf, png, texture=None)`.
- `texture_changes(romfs, character, image, formats=(0x2B,))` → LayeredFS changes replacing every `0x2B` in that
  character's `uPlTex*` arcs.
- `character_changes(romfs, character, source, roles, ...)` — one-character pass over all its costumes + parts.

**How to expand:** to add a donor, extract it into `D:\gBox\cache\characters/<slug>` with `name.glb` + metadata whose
`rig.roles` map the 18 roles; then use `re6_switch_cast.plan`/`build`. To change the fit, pass `height`
(or use `source_proportions` from the receipt); to change the mesh target, `template_index` selects the native mesh record
whose metadata is cloned.

### 3.2 `system/gbox/re6_switch_cast.py` — roster planner/builder

- `donor_pool(library)` → 18 distinct-joint donors (one per role signature) used for the per-character textured plan.
- `plan(romfs, library, *, per_character=False)` → assignment `{(char, costume): donor}`; `per_character=True` picks one
  donor per character (7 donors), else one per slot (51 distinct donors).
- `build(cfg, romfs, library, assignment, name, height=180, textures=False, seed=…)` → writes through `switch_mods` with
  per-slot caching under `cache/re6sw_cast_cache/<name>[_tex]`, skipping failing slots and reusing per-donor atlases.

### 3.3 `system/gbox/mtf_author.py`, `mtf_retarget.py` — the generic MTF authoring layer

- `build_one_mesh(model, vertices, triangles, *, material_index, template_index, mesh_count, four_weights,
  reverse_bones=False)`: clones a native mesh record, packs native vertex formats (four-weight format `0x2000D414`,
  stride 28: position short3, w0 SNORM16@6, normal@8, tangent@12, joints u8[4]@16, uv@20, w1/w2 half@24, w3 implicit),
  builds the index buffer, per-bone weight envelopes, bounds. `reverse_bones=True` stores joints least-important-first
  (X360 convention) — an opt-in A/B probe, default off.
- `bone_local_points(model, bone, points)` for envelope bounds; `replace_archive_model(archive, index, payload)`.
- `mtf_retarget.reposition_bind_pose(model, anchors, retarget_root_translation=False)` — **experimental**, rewrites
  bind joins by arc-length interpolation; its own docstring says it does not rewrite animation channels. Do not use it
  for live builds (see §2.1).
- `mtf_retarget.map_weights(vertices, parents, roles)` — maps donor joint influences through named ancestors onto native
  bone indices (≤4 influences, normalised); raises instead of silently dropping.

### 3.4 `system/gbox/re6_switch_tex.py` — textures

- `Surface` parses a TEX (`TEX\0`, version/revision, packed dims/mips, format, 4-byte payload size at +16, mip offsets at
  +20, payload at `20 + 4*mip_count`), `linear_blocks`, `_albedo_layers` (BC4 detail + second 8 bytes), `decode`.
- `texture_set_mrl(arc)`, `texture_set_materials(arc)` → per-material name hash, region size, referenced texture indices
  **and full paths** (`_BM` albedo `0x2B`, `_NM` normal `0x1F`, `_MM` mask `0x19`, `_VTF`/`_MVTF`).
- `body_albedo_paths`, `export_textures`, `encode_albedo(image)` (`0x2B`: BC4 luminance + BC1 per-tile average),
  `replace_albedo(template, image)` (keeps dims/mips, regenerates every mip in the Tegra layout, rewrites size/offsets),
  `describe_arc`.
- **Defect, fixed offline (§0.1, §0.2):** `encode_albedo` wrote a per-tile RGB colour into the second half, which the
  engine reads as (Cr, opacity, Cb). It now writes Y'CbCr. Textured builds made before `ec6445db` carry the old
  bytes and must be rebuilt; the corrected encoder is not live-verified yet.

### 3.5 `system/gbox/re6_tool.py` — the Switch ops

`switch_cast` builds and writes an overlay from the worker's RomFS (`host` optional, `textures`, `slots`, `seed`,
`height`, `mercmode_default` writes the MercMode per-title default); `switch_cast_plan` returns the plan without building;
`switch_cast_status` lists builds/selection. Capabilities are declared in the tool registry.

### 3.6 Menu automation stack

- `gbox/mercs/titles/re6_switch.py` — the title driver. Important entries: `screen(m, merc=None, now=None)` (RAM state
  machine, wrapped so a lost page returns `unknown`), `step(scr)` (one key toward the cursor target then A),
  `fast_batch(scr)` (whole-segment burst; fixed downward deltas for `play_game`/`extra_content`/`mercs_mode`),
  `fast_start(m, send, stopped, stats, screen_fn, sleep, clock)` (burst segments until `playing`/`loading`, records
  `stats["fast_start"]`), `wandered`, `pressed` (feeds the learned cadence), `module_base`, `snapshot`, `continue_prompt`,
  plus the combat-side readers (player/camera/laser/navmesh) used by the Mercenaries engine.
- `gbox/mercs_bot.py` — `Navigator` (closed-loop presses with `NAV_CURSOR` knobs, confirmation chains, retries),
  `Boot` (RAM walk over the title's menus, hooks, save-moment), `play()` (the Mercenaries playbook: boot to a round, hand
  the round to the engine, back to the menus; runs `fast_start` when the title provides it).
- `gbox/mercs/menu_speed.py` — `Speed`/`for_title(map_id, data_dir)`: EMA of confirmation latency + AIMD on
  `stable_s`/`retry_s`/`poll_s` (×0.92 confirmed, ×1.45 missed, clamped); persists to
  `<data dir>/mercs/learned/<title>/menu_speed.json`; `stats()` feeds receipts.
- `gbox/eden_memory.py` — `guest_arena()` returns `{lo, hi, base, mapped, rows, readable}`; `readable` is every readable
  row in the guest span (used by the title's `module_base` scan). `host_address`, `mapped` do the direct/offset mapping.
- `gbox/auto-play` entry: `autoplay` tool (`op=start|stop|status|prepare`, `mode=auto|playbook|mission|replay|learned|
  vision`). `op=status` returns `steps = len(driver.trace)` (0 for playbook runs is normal), `mission`, `running`,
  `reaped`, `recovery`.
- Keys: the Eden adapter delivers **plain** `up/down/left/right`, `a/b/x/y`, `l/r`, `zl/zr`, `plus/minus`, `lstick`
  directions (`SWITCH_KEYS` in `gbox/yuzu_runtime.py`). The `ddown`/`dup`/`dleft`/`dright` aliases were **not delivered**
  live (a burst with `ddown` confirmed CAMPAIGN, a single `down` moved the same cursor) — use the plain names.

**How to expand menus to another title:** implement `matches`, `screen`, `step`, `pressed`, `NAV_CURSOR`, optionally
`fast_start`/`FAST_SEGMENTS`/`fast_batch`, and `BOOT_KEY`; the Navigator/Boot/menu_speed machinery is generic. For RE6
Switch the route constants are `MAIN_PLAY_GAME=0`, `PLAY_EXTRA_CONTENT=3`, `MERCS_SOLO=0`, `MODE_NO_MERCY=2`, and the
menus wrap at their edges.

### 3.7 Builds on disk (automation node)

`D:\gBox\cache\mods\115f9cdbba115432\` — `re6sw_sonic_leon_keep_plain` (30 files/33.5 MB, live-proven),
`re6sw_sonic_leon_keep` and `re6sw_sonic_leon_tex` (37–38 files/46–48 MB, colours wrong), `re6sw_sonic_leon` (30/33.5,
first geometry build), `re6sw_smash_cast` (255 arcs/346 MB), `re6sw_textured_cast` (298/440 MB), `re6sw_probe_red`,
`re6sw_probe_quad` (12 files each). Install/launch helper: `C:\_tools\gBox\.tmp\install_switch_build.py <build> --launch`
(uploads every file as an artifact, `switch_mods write/select`, then launch). Other scratch scripts worth keeping:
`build_keep_variant.py`, `build_keep_plain.py`, `build_tex_probe.py`, `re6_keep_playing.py` (plain input driver),
`re6_autoplay.py` (frame-size guesser — **unreliable**, do not use), `textured_check.py`.

### 3.8 Tests

`system/tests/`: `test_re6_switch_models.py`, `test_re6_switch_cast.py`, `test_re6_switch_tex.py`,
`test_re6_fast_menus.py`, `test_menu_speed.py`, `test_mtf_author.py` and the rest of the MTF suite. Run from the repo
root with `python -m pytest system/tests/<file> -q`; modules that import sibling test helpers need
`$env:PYTHONPATH='C:\_tools\gBox\system\tests'`. At hand-off: 27 passed across the RE6 model/author/menu-cadence suites
and 22 across the fast-menu/cadence/mercs-bot suites.

---

## 4. Problems hit during the run (and their resolution state)

1. **Wrong platform initially (X360).** Resolved: all work targets the Switch romfs; X360 code is legacy.
2. **Scale/fit bugs.** `fit_source_proportions` box overflow → uniform limiting-axis scale (`height_clamped`,
   `box_usage`). The final fit is inside the native quantisation box.
3. **Mesh distortion / giant spikes / camera inside the model.** Root cause found live: moving the native bind joints
   (`reposition_bind_pose`) while the title's animations keep absolute locals. Resolved by `bind_mode="keep"` (native
   skeleton untouched). `warp` exists as an alternative; keep is the shipped default.
4. **"Textured build crashes the game."** Wrong conclusion: a **vanilla** launch later crashed identically. The real
   cause was emulator/save state on the Spark (see 6–8). The solid-red probe and the textured gameplay frame prove the
   texture path itself runs.
5. **`0x2B` colour mismatch.** Explained offline, fix built, not live-verified (§0.1): the format is BC3 Y'CbCr and
   the encoder wrote RGB where chroma belongs. `pl_VTF` is the cloth displacement curve, not a colour ramp.
6. **The Spark ran MercMode in parallel** with manual launches (it had its own RE6 queue and was launching/stopping its
   own game), which made sessions end in black frames. Resolved by disabling MercMode on lilspark (`POST /api/mercmode
   {"host":"lilspark","enabled":false,...}`); note the control-plane build rejects `default_mods`/`repeat_queue`.
7. **Orphaned Eden/Vulkan processes.** After several crashes, no launch can present frames: the box boots, draws a few
   frames, goes black and exits — even vanilla. `systemctl restart gbox.service` (and `rebuild_node`) does **not** reap
   orphaned Eden children. Needs `pkill -f eden` (or a reboot).
8. **Save corruption from scripted menu driving.** The game shows "Now saving… Do not turn off your Nintendo Switch
   console"; a hand-driven burst pressed A through it and every later stage load crashes (Mercenaries **and** campaign,
   vanilla too). The bot's `step()` deliberately returns no key on saving/loading screens — that is the correct
   behaviour. Recovery: move the save dir aside (see §7.1).
9. **Bot never named a screen / `steps: 0`.** Two causes: (a) `module_base` scanned only memfd heap rows → fixed by
   `guest_arena.readable` + `_rows` preferring it; (b) the D-pad alias keys were not delivered → fixed by using plain
   `up/down/left/right`, and by fixed downward deltas for the shipped menus.
10. **Bot confirmed CAMPAIGN instead of EXTRA CONTENT.** Fixed: `fast_batch` presses the known deltas
    (PLAY GAME → down×3 → A; EXTRA CONTENT → down×2 → A; NO MERCY → A) and verifies the next screen.
11. **EIO ending the run.** Fixed: `_screen` catches `ValueError/OSError/struct.error` and returns `unknown`.
12. **Lobby models are separate.** The Mercenaries/Campaign "system settings / START GAME" lobbies render a human Leon
    even with the Sonic overlay active; only gameplay shows the replacement. Do not use lobby frames as evidence.
13. **Deploy gate.** The Spark runs gBox from a share, not a git checkout: `repo_update` reports "not a git checkout".
    Code reaches it only via the operator's `~/bin/deploy_main.sh --deploy` (main branch). `rebuild_node` restarts the
    service (and runs pip); it does not fetch code. At hand-off the Spark runs `6f15828c` while main is `1672c0ad`.
14. **Roster skeleton/integrity caveat.** Settled offline (§0.3): the 36..89 bone counts are each costume's own
    skeleton (one skinned MOD per body arc, all with the 18 role ids; 54 bones is Leon's USA body only). The roster
    had three other defects instead - one blanked MOD of three in the accessory heads, material 0 assumed for the
    donor (an alpha-tested patch material on Helena USA and Chris Asia), and an unmeasured costume-1 body - so
    `re6sw_smash_cast` must be rebuilt with the current code before it is spot-tested in-game.

---

## 5. What is left, in priority order

### 5.1 Recover the Spark (blocker for everything live)

```bash
SAVE=~/gBox/system/gbox-data/runtime-linux-aarch64/eden-linux/data/eden/nand/user/save/0000000000000000/01002A000CD48000
mv "$SAVE" "$SAVE.bak-$(date +%s)" 2>/dev/null || true
pkill -f eden 2>/dev/null || true
pkill -f gbox 2>/dev/null || true
sleep 2
sudo systemctl start gbox.service
```

Then `~/bin/deploy_main.sh --deploy` (main `1672c0ad`). Acceptance: one launch boots to the title (frame ~7.5-8 KB) and
stays up; a Mercenaries stage load does not end the session (test with no mod first).

### 5.2 Autoplay: make the bot drive and measure it

Start `autoplay op=start` at the title (`mode=auto`); status must show `running: true`, and the frames must move from the
title through the boot notices to the main menu on their own. Acceptance: the bot reaches `playing` and
`stats["fast_start"]` shows `{segments, presses, s, reached: "playing"/"loading", ok: true}`; target is single-digit
seconds from the main menu. Tune `menu_speed` thresholds (`MIN/MAX_*`, `FAST`, `SLOW`) if it overshoots or gets noisy.
`autoplay op=prepare` is a different thing (warm/paused games) and is not needed for a running title.

### 5.3 Textures: find and neutralise the colour source

> **Replaced by the four probes of §0.5.** Run `re6sw_probe_albedo_solid`, then `re6sw_sonic_leon_ycc`; each
> `receipt.json` says what the frame must show and what every other outcome means. A white `_MVTF` is not neutral:
> it is a displacement mask of 1 everywhere. The original plan is kept below for the record.

1. First probe (cheap): replace only `pl0000_00jacket_BM` with a solid known colour and see whether that material shows
   it exactly (it should, like the red probe) — confirms per-material targeting.
2. Then neutralise the colour multiplier: `_VTF` is `0x0E` 128×4 (float ramp), `_MVTF` is `0x09` 128×128 (RGBA8). Write a
   **neutral white** version of each (needs small encoders for those two formats in `re6_switch_tex`, reusing the TEX
   header/mip writer; the Tegra layout for non-BC texel sizes is the only unknown — inspect a native `MVTF` (uniform
   `00 00 00 FF`) to derive it). If the textured Sonic then renders the atlas's own colours, wire the neutralisation into
   the textured build path and rebuild `re6sw_sonic_leon_keep` (+ the textured roster).
3. Only then judge the atlas UVs; the offline preview already renders Sonic correctly from the same atlas, so UVs are
   believed correct.

### 5.4 Roster: verify and ship

0. First boot: one of the three small mixed-franchise overlays of §0.5 (45 files, 26-27 MB each), every character
   with COSTUME 1. A native human on a covered character settles which body costume 1 is (§0.3).
1. The bone-count caveat is resolved (§4.14). Rebuild `re6sw_smash_cast` with the current code (vetted material, all
   accessory-head MODs blanked), then spot-check 3–5 slots (255 files, ~346 MB — upload in batches) by playing rounds
   with different drawn characters/costumes.
2. For "randomising on rounds", either use the roster build as the per-title mod (each round's native character/costume
   picks its assigned Smash fighter), or queue rounds with different `mod` entries in MercMode's queue. Note the
   control-plane build rejects `default_mods`, so queue entries with `mod` are the working route there.
3. Capture at least 3 rounds showing different fighters as evidence; file under `docs/evidence/re6-scale/`.

### 5.5 Clean-up before hand-off to the operator

- Remove the probe builds (`re6sw_probe_*`) from the mods cache; keep `keep_plain` (stable) and the roster.
- Re-enable MercMode only after the autoplay/bot is trusted again; leave `skin_swap`/`cast_swap` off until the roster is
  validated.
- Keep `mercs_team`/MercMode disabled while testing manually so two games do not compete.

---

## 6. Useful operational recipes

- Session frame: `GET /api/sessions/<sid>/frame.jpg` (Bearer). Title ≈ 7.5-8 KB JPEG, menus 17-40 KB, gameplay 50-80 KB
  — size is only a rough signal; **always look at the frame**.
- Input: `POST /api/sessions/<sid>/input {"events":[{"key":"a","down":true},{"key":"a","down":false}]}`. Hold ~0.05-0.5 s,
  gap ~0.25 s; **never press while "Now saving…" or a loading spinner is up**.
- Swap a running game to another build: `POST /api/sessions/<sid>/swap {"mod": "<build>", "keep_state": true}` (Eden has
  no save states; it reboots the title). Swaps/launches are refused while a stream/PiP is watching the title
  ("Close that view before loading another game on this PC").
- Launch: `POST /api/games/115f9cdbba115432/launch?node=lilspark&mod=<build>`; without `mod` the load entries are
  disabled (vanilla).
- Worker restart: `POST /api/jobs {"tool":"rebuild_node","require_worker":"lilspark","input":{"restart":true,"force":true}}`
  (service only; see §5.1 for orphans).
- Learned cadence lives at `<worker data dir>/mercs/learned/01002A000CD48000/menu_speed.json`.

---

## 7. Glossary / paths

- ROMFS extraction used for offline work: `C:\_tools\gBox\.tmp\re6sw_romfs` (body arcs at
  `nativeNXx64/arc/NX/uPl00<Name><Costume>.arc`; textures `uPlTex00<XX>_<n>.arc`).
- Character library: `D:\gBox\cache\characters\<slug>\<model>.glb` + metadata in the index (74 SSBU, 46 Brawl).
- Evidence: `system/docs/evidence/re6-scale/` — `switch-sonic-on-leon.png`, `switch-robin-as-leon.png`,
  `switch-peach-as-ada.png`, `switch-greninja-as-chris.png`, `switch-darkpit-as-sherry.png`,
  `switch-bowser-chris-textured.png`, `switch-live-sonic-leon.jpg`, `switch-live-autoplay-urban-chaos.jpg`,
  `switch-live-textured-sonic-urban-chaos.jpg`, `switch-live-solid-colour-probe.jpg`,
  `switch-native-albedo-detail-layer.png`, `switch-native-albedo-decoded.png`, `switch-roster-contact-sheet.png`.
- Docs in this directory: this handover, `re6-model-replacement.md` (the measured narrative, formats, binding, blockers),
  `re6-switch-live-runbook.md` (step-by-step live procedure), `re6-switch-mod-guide.md` (operator how-to for the builds).
- Main branch state at hand-off: docs + systems above committed through `1672c0ad`; working tree clean apart from
  `.scratch-deepseek/`.
