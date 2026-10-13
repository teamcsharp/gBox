# Sonic Adventure (Dreamcast) character reader

`gbox/sa1_chars.py` reads the playable cast of **Sonic Adventure (USA)** (catalog `1a3f4cd416db9ffd`, the owned GD-ROM)
straight off the disc and exports each one as a rigged, textured GLB with body roles. It is registered in
`characters.DEDICATED` as `sa1`, so `characters op=collect game_id=1a3f4cd416db9ffd` fills the collection with
`sa1_*` entries, and those entries pass the whole-cast swap's donor gate (`gbox/cast_swap.py`): the operator request
"replace the Crazy Taxi drivers with Sonic characters from Sonic Adventure 1" is one `characters op=cast_swap`.

## File layout (what is read)

* **SA1 uses basic Ninja models, not chunk models.** SA2 (gbox/sa2_chars.py) stores NJCM chunk models in
  `SONIC2/<CHAR>MDL.PRS`; SA1 has no per-character model file. Its characters are trees of classic 0x34-byte
  `NJS_OBJECT`s whose `NJS_MODEL`s are 0x28-byte *basic* models: points, normals, `nbPoint`, 0x18-byte `NJS_MESHSET`s
  (type in the top 2 bits of `type_matId`: 0 triangles, 1 quads, 2 n-gons, 3 strips with bit 15 of each strip count
  flipping its winding; per-corner `vertuv` as s16 / 255), and 0x14-byte `NJS_MATERIAL`s (texture id in the low bits
  of `attr_texId`, `NJD_FLAG_USE_TEXTURE` 0x00200000 in `attrflags`; colour-only materials keep their diffuse ARGB).
  `sa1_chars.basic_model` decodes one model, `sa1_chars.Tree` walks a tree into bind-pose, model-space vertices bound
  rigidly to their node's bone (one bone per node, named `node000`...), the shape `gbox.ninja.to_manifest` writes.
* **`1ST_READ.BIN`** (load address 0x8C010000, USA sha256 `45bc5d3c...367a`): the six playable characters. Their tree
  roots are proven from the executable's own code by `gbox.sa1_analysis.character_map` (the character's PVM row
  `{name, NJS_TEXLIST *}` -> the `njSetTexture` call that loads that texlist -> the draw routine -> a node of the tree);
  on the verified USA executable the reader uses the pinned roots (the same values), on any other build it runs the
  analysis.
* **PRS overlay modules** (`SONICADV/*.PRS` that decompress to SH-4 code + data, pointers absolute in the 0x0Cxxxxxx
  cached range): Super Sonic is in the Perfect Chaos boss module `B_CHAOS7.PRS`, Tikal in `TIKAL_PROG.PRS`.
  `sa1_chars.overlay_key` recovers the load address from the module's own PVM table (the word pointing at the
  `"SUPERSONIC"` string, followed by a valid `NJS_TEXLIST *`) or, when the module has none (`TIKAL_PROG`), from the
  4 KB base under which most of its pointers land inside the module; `pick_tree` then takes the largest player-sized
  tree whose texture ids all fit the character's archive.
* **Textures**: `SONICADV/<PVM>.PRS` -> PRS (`gbox.ninja.prs_decompress`) -> PVM (`ninja.pvm`), texture id = archive
  order; each character's `NJS_TEXLIST` has exactly the archive's entry count. Decoded with `ninja.pvr_decode` to
  `textures/*.png` and embedded in the GLB.
* **Orientation**: SA1 characters face -X like SA2's; the root bone carries `FACE_Z` ((x, y, z) -> (z, y, -x)) so the
  GLB faces +Z with left = +X, the convention of `characters.tree_roles` and the swap writers.
* Not read (yet): motions (by their names `S_MOT.PRS`, `K_MOT.PRS`, `E_MOT.PRS`, `A_MOT.PRS`, `B_MOT.PRS` are the
  NJM motion banks of Sonic, Knuckles, Gamma, Amy and Big). The GLBs are bind pose only, like the SA2 entries.

## Roster

| slug | name | source | root | nodes | triangles | PVM (textures) | height |
|---|---|---|---|---|---|---|---|
| `sa1_sonic` | Sonic (Sonic Adventure) | `1ST_READ.BIN` | 0x8C1CE76C | 73 | 1001 | `SONIC` (28) | 10.1 |
| `sa1_tails` | Tails | `1ST_READ.BIN` | 0x8C25F968 | 68 | 997 | `MILES` (24) | 8.7 |
| `sa1_knuckles` | Knuckles | `1ST_READ.BIN` | 0x8C35B094 | 73 | 981 | `KNUCKLES` (22) | 11.0 |
| `sa1_amy` | Amy Rose | `1ST_READ.BIN` | 0x8C4C7C3C | 78 | 1000 | `AMY` (53) | 9.2 |
| `sa1_big` | Big the Cat | `1ST_READ.BIN` | 0x8C52F298 | 73 | 1134 | `BIG` (36) | 21.0 |
| `sa1_e102` | E-102 Gamma | `1ST_READ.BIN` | 0x8C42CC34 | 77 | 970 | `E102` (35) | 21.3 |
| `sa1_super_sonic` | Super Sonic | `B_CHAOS7.PRS` @ 0x0C900000 | 0x0C909D2C | 73 | 1046 | `SUPERSONIC` (73) | 11.0 |
| `sa1_tikal` | Tikal | `TIKAL_PROG.PRS` @ 0x0CB00000 | 0x0CB09818 | 103 | 948 | `TIKAL` (18) | 9.2 |

Slugs are `sa1_<key>`: SA2's Sonic already owns the plain `sonic` slug. `sa1_sonic` carries `native_player`, so the
cast planner treats him as the game's lead. Not on the Dreamcast disc: **Metal Sonic** (added by Sonic Adventure DX).
Left out: Dr. Eggman (an NPC; his 24-node tree at 0x8C57A6BC was not checked as a rig) and the Chaos forms.

## Body roles and the chest bone

`characters.tree_roles` expects a hip -> chest -> shoulders hierarchy; SA1's trees are flat: a centre-line body node
hangs every part off itself (head, arms, legs, the one rigid torso mesh, tails), each limb a joint chain with its
meshes on side nodes (Big and Gamma add an upper-body hub, Tikal a pelvis hub). `Tree.body_roles` (H = model height):

* limb candidates: the first off-centre joint (|x| > 2% H) below a centre-line joint, with geometry and 3+ joint
  position groups on the path to its lowest vertex (eyes, ears and quills are single leaves);
* per side the **leg** is the lowest-anchored candidate reaching the floor, the **arm** the candidate anchored above
  it whose geometry spans the most height (Big's fishing rod and Amy's hammer stay in the hand); the position groups
  give upper / fore / hand and thigh / shin / foot;
* **hip** = the deepest common ancestor of the four limbs; **head** = the highest ancestor of the topmost vertex that
  holds no limb, moved down to its first branching joint;
* **chest**: SA1 has no chest joint, so a `chest` bone is added under the hip halfway between the leg and shoulder
  anchors; the arms and head re-parent to it (world positions unchanged) and every other vertex above it (upper torso)
  is bound to it.

All 15 roles (`hip chest head l/r_upper l/r_fore l/r_hand l/r_thigh l/r_shin l/r_foot`) come out for all eight, and
every Crazy Taxi part (`crazy_taxi.donor_segments`) gets geometry, left and right alike.

## Cast swap

* `cast_swap` sources: `source="Sonic Adventure"` / `"Sonic Adventure 1"` / `sa1` / the game id select the SA1
  entries only (a title match now drops sequels the request doesn't number, so SA2 stays out); `source=sonic` is the
  new **Sonic** group (SA1 + SA2); SA1 also joins the **Sega** group.
* Crazy Taxi: `slots=drivers` keeps the four drivers. The `player` alias names `driver:axel`, so the lead donor
  (`sa1_sonic`) goes to Axel; the rest are dealt by height (driver size hints measured from their parts in
  `polDC0.all`: Gus 1.15, Axel / Gena 1.0, B.D. Joe 0.97). Planned with the real entries: **Axel <- Sonic,
  B.D. Joe <- Super Sonic, Gena <- Big, Gus <- E-102 Gamma**; edit the plan with `assignments=[{slot, character}]`
  for a different line-up (e.g. Knuckles, Tails, Amy).
* Fix that came with it: `crazy_taxi.donor_segments` indexed every glTF primitive's triangles into the first
  primitive's vertices (the offset was always 0); multi-material donors (one primitive per texture: SA1, SA2, PSO)
  now cut into the right parts.

## Checks

Offline (this branch, Windows, the owned disc read over the share): every roster entry through
`characters.extract_dedicated` into a scratch library -> `verify_entry` ok for all 8, `collection_status` complete,
the cast-swap gate accepts 8 / refuses 0, the drivers plan as above, and the four donors chain through
`crazy_taxi_swap.swap_bank` on the real `polDC0.all` (42 parts fitted per driver).

Tests: `python -m pytest tests/test_sa1_chars.py tests/test_cast_swap.py -q -p no:cacheprovider`

* `tests/test_sa1_chars.py`: PRS round trip; basic meshsets (tris, quads, flipped strips, per-corner UVs, textured /
  colour-only materials); a synthetic flat humanoid -> bones, `FACE_Z`, all 15 roles, the chest bone (re-parented
  arms and head, upper torso rebound, joints unmoved), GLB + Crazy Taxi segments; overlay load addresses; the
  `DEDICATED` row (matches SA1, not SA2). Owned disc (skipped unless `GBOX_SA1_GDI`, `~/gbox-cache/dc/<id>/disc.gdi`
  or the share's `//10.89.1.246/ehm_eckx/samples/gbox-cache/dc/<id>/disc.gdi` is readable): all 8 characters export
  with the roots, node and triangle counts above, textures on disk, and every Crazy Taxi part non-empty.
* `tests/test_cast_swap.py`: synthetic SA1 donors -> sources (`Sonic Adventure`, `sa1`, id; the `sonic` group), the
  gate (no hip refused), Crazy Taxi driver sizes / lead slot, and the four-driver plan by height.

## Live check (after the branch is merged and the deploy cron has put main on the share)

1. Collect on the deployed Spark (the collection lives there; no game session):
   `characters op=collect game_id=1a3f4cd416db9ffd`
   Expect `status: complete`, `collected: 8`, `retargetable: 8`, entries `sa1_sonic` ... `sa1_tikal`; the previews
   are the eight characters standing, facing the camera.
2. Plan, then build the Crazy Taxi driver cast and launch it on the test PC (run from the test PC: the build is a job
   on the Spark, the launch goes to the PC that asked):
   `characters op=cast_swap target_game=bc02bb68790ce2e7 source="Sonic Adventure" slots=drivers plan_only=true`
   `characters op=cast_swap target_game=bc02bb68790ce2e7 source="Sonic Adventure" slots=drivers launch=true`
   Expect four rows built (Axel <- Sonic, B.D. Joe <- Super Sonic, Gena <- Big, Gus <- E-102 Gamma) in one mod
   `cast_crazy_taxi_usa_sonic_adventure_<...>_<hash>`; at driver select each driver is the SA1 character in the
   driver's pose.
