# Metal Gear Solid 2: Substance (PS2): reader, cast writer, pick whip (`gbox/mgs2_*.py`)

Operator request (2026-10-13): replace Snake (and Raiden) and the soldiers in MGS2 with the Sonic Adventure 1 / 2
characters of the collection, on the fly and with the pick whip. Branch `mgs2-cast`.

## What the catalog owns (checked 2026-10-13)

| game id | catalog entry | what it is |
|---|---|---|
| `cb7aae71edb10cd3` | Metal Gear Solid 2: Substance (USA), **windows_native**, HyperSpin system "Microsoft XBOX" | **the PS2 DVD-9** `collections/Sony Playstation 2/roms/USA/Metal Gear Solid 2 - Substance (USA).chd` (4,410,047,336 B, CHD v5 createcd cdlz / cdzl / cdfl, one MODE1 track of 3,142,944 sectors, sha1 `5a69cb8b...`): `SYSTEM.CNF` BOOT2 `SLUS_205.54` VER 1.00, NTSC; ELF 852,772 B, sha256 `77de3383...` |

It is not a PC or an Xbox disc. The PC Games romlist row "Metal Gear Solid 2 - Substance" (`.bat`) has no file.

**Why the platform was wrong.** HyperSpin's `Microsoft XBOX.cfg` lists `collections\Microsoft XBOX\roms;collections\Sony
Playstation 2\roms\USA;...\Europe` as its rom paths, and its romlist names the PS2 disc. `catalog.scan_attract` reads
emulator configs in name order, so "Microsoft XBOX" claims the file before "Sony PlayStation 2", and
`systems.classify("Microsoft XBOX", ...)` said `windows_native` (core none: RocketLauncher, no mods, no save states).
The same happened to Enter the Matrix, Path of Neo and the Vice City CHD. **Fix** (`gbox/systems.py`): when a launcher
system (windows_native) scans another system's rom folder whose name maps to a platform with an emulator core, the
folder decides. The disc becomes `ps2` / core `pcsx2` (the libretro PCSX2 path: mods and session_swap work). The game
id does not change (library + relative path). The live catalog changes at the next `scan_library
{"libraries": ["hyperspin"]}` (an upsert of the same id); until then every MGS2 hook accepts both platforms.

## Disc layout

* **Two layers.** Layer 0's ISO9660 volume is 1,167,824 sectors: `SYSTEM.CNF`, `SLUS_205.54`, `MODULES/`, the
  skateboarding game `SKATE/`, `MGS2/STAGE2.DAT` (1.31 GB: VR / alternative missions, Snake Tales), `DEMO2.DAT`,
  `VOX2.DAT`, `MOVIEVR.DAT`. Layer 1 starts at sector 1,167,808. Its primary volume descriptor is at the layer break
  (sector 1,167,824), and it has its own tree with `MGS2/STAGE.DAT` (685 MB: Tanker + Plant), `DEMO.DAT`,
  `VOX.DAT`, `MOVIE.DAT`, `FACE.DAT`, `CODEC.DAT`. `gbox.chd.ChdDisc` only walks layer 0, so
  `mgs2_inventory.Disc` reads both layers from the CHD in place, or from an ISO.
* **ELF** (`SLUS_205.54`; one segment loaded at 0x100000; capstone disassembly, Ghidra was not available on this PC):
  the file table at `0x180b08` holds `{name, 0, flags}` rows for `stage.dat`, `codec.dat`, `face.dat`, `movie.dat`,
  `vox.dat`, `demo.dat`, `movievr.dat`, `stage2.dat`, `vox2.dat`, `demo2.dat`. They are opened as
  `cdrom0:\MGS2\%s;1`.

## STAGE.DAT / STAGE2.DAT (`gbox/mgs2_inventory.py`, verified on both archives: 129 + 165 stages, every page inflates)

* **Cipher** (`0x1007d8`): every u32 is xored with `k`, then `k = k * 0x02e90edd + step`.
* **TOC** (`0x100fa8` / `0x100f2c`): sector 0 holds `u32 key` (a build time stamp, in the clear), then 12 bytes plus
  `count` x `{char name[8], u32 sector}`, encrypted from `k = key, step = key ^ 0xf0f0`. The header u16s are 1, TOC
  sectors, count, 0x4010, ?, ?. STAGE.DAT keys `0x3db7b4da`, STAGE2.DAT keys `0x3db7b7db`.
* **Stage header** (state machine `0x101448` / `0x101878`): `u32 n` + n x `{u32 type << 24 | name hash, u32
  offset}`, encrypted from `k = key + 129 h + 0xa78925d9, step = 129 h + 0x7a88fb59`. Here `h` = the stage name's hash
  (`0x1424c8`: `h = rotl5(h) + c`, 24 bits). Rows form pages:
  * a `0x7f` row: the page id (`0x7f010000` = the stage program) and its decompressed size;
  * a `0x7e` row: the compressed size in the low 24 bits, and the data offset after the sector-aligned header;
  * then the page's files: `(type, name hash, offset in the page)`.
* **Page data** (`0x1008b0`, zlib 1.1.3 `0x160fd8`): a zlib stream encrypted with the same cipher. The seed is its
  first stored u16: `s = seed ^ 0x9385, k = s | (s ^ 0x6576) << 16, step = 0x116 s`. The first u16 is stored minus
  0x8f3, so `78 9c` decrypts to `85 93`. The game decrypts whole words, the tail word included.
* **File types** (row high byte; names are hashed, the type stands for the extension):
  * `0x01`: the stage program overlay, loaded at 0x1f6500 (its strings name models: `sna_def`, `rai_def`,
    `gbs_def`, ...).
  * `0x0a`: **kms** model.
  * `0x02`: per-mesh hull (float vertices + u16 indices, 3 levels; kept by the writer).
  * `0x13`: **texture pack**.
  * `0x0c` / `0x12`: motion banks / tables.
  * `0x07`: stage geometry; `0x0b`: script.
  * `0x04`, `0x06`, `0x0e`, `0x11`, `0x15`, `0x19`: not decoded.

## kms model and texture pack (`gbox/mgs2_models.py`)

* **kms**: a 0x40-byte header holds flags, bones, meshes, the texture pack's name hash (`<model>_mt`) and bounds.
  Each bone is a 0x40-byte record: flags, parts, bounds, offset from the parent (mm), parent, part table. Parts are
  0x30 bytes: flags, vertices (<= 32), three texture hashes, and position / normal / uv / uv2 offsets.
  * Vertices: s16 x, y, z plus a w word = the bone's weight in 1/4096 (the rest goes to the parent bone, flag bit 0).
  * Normals: s16 / 4096 plus a flag word (`0x8000` = strip restart).
  * UVs: s16 / 4096 of the texture's sub-rectangle.
  * Every part is one triangle strip. The game's parity, measured on Snake, Raiden and a soldier: an even triangle
    `(v_k, v_k+1, v_k+2)` is counter-clockwise (6,229 of 6,266 triangles agree).
  * The rest pose has no rotations, units are mm. The character faces +Z with its right at -X: Snake's holster is
    on the -X thigh. That is glTF's frame, so the GLB is only scaled to metres and stood on y = 0.
* **texture pack**: a header (pixel blocks, CLUT blocks, textures, data offsets) and 0xa0-byte texture records.
  * Each record holds the sub-rectangle in its page (u0, v0, du, dv), the name hash, and an A+D packet with CLAMP_1
    (region clamp), TEX2_1, TEX0_1 (TBP / TBW / PSM 0x13 PSMT8 or 0x14 PSMT4 / CBP / CSA, relative to the pack's VRAM),
    ALPHA_1 and NOP. Six floats follow: -du/2, -dv/2, 1, 1, and the centre.
  * The pixel and CLUT data are the pack's VRAM uploaded page-linearly as PSMCT32 (64 pixels wide). `gbox/ps2_gs.py`
    models GS memory for this: PSMCT32 / PSMT8 / PSMT4 swizzles, and the PSMT8 table derived from PSMCT32 and checked
    against the published table.
* **Names.** The roster below was identified by rendering every human-like kms on the disc (129 models with 18 body
  roles) and by name hashes the overlay spells.

| collection slug | model (hash) | name |
|---|---|---|
| `mgs2_snake` | `55ab65` (hi) / `sna_def` | Solid Snake (sneaking suit) |
| `mgs2_snake_bigshell` | `bfa829` | Snake in the Big Shell |
| `mgs2_pliskin` | `iro_def` (`1a1ab0`) | Iroquois Pliskin |
| `mgs2_raiden` | `b41e89` (hi) / `rai_def` | Raiden |
| `mgs2_raiden_naked` | `064e76` / `rai_naked` | Raiden (naked) |
| `mgs2_raiden_disguise` | `b709c9` / `ff6ab6` | Raiden in a soldier's uniform |
| `mgs2_gurlukovich_soldier` | `gbs_def` | Tanker soldier |
| `mgs2_gurlukovich_heavy` | `c9aaaf` | Tanker heavy soldier |
| `mgs2_plant_soldier` | `d83aaf` | Big Shell soldier |
| `mgs2_plant_soldier_heavy` | `d7aaaf` | Big Shell heavy soldier |
| `mgs2_hightech_soldier` | `fbbaaf` | High-tech soldier |
| `mgs2_navy_seal` | `sel_def` | Navy SEAL |
| `mgs2_marine` | `us_def_1` | US Marine |
| `mgs2_tengu` | `tng_high` | Tengu |
| `mgs2_olga` | `b3f701` (`org_mt`) | Olga Gurlukovich |
| `mgs2_ninja` | `c43f41` | Cyborg Ninja (Mr. X) |
| `mgs2_ocelot` | `9ba944` | Revolver Ocelot |
| `mgs2_solidus` | `f4b943` | Solidus Snake |
| `mgs2_otacon` | `b3f7f1` | Otacon |

## Reader (DEDICATED `mgs2`)

`characters op=collect game_id=cb7aae71edb10cd3` puts the 19 characters above into the collection. Each one is a rigged
GLB:
* the model's bones, with two-bone weights (bone + parent);
* one material per texture, decoded from the stage's texture packs;
* the 18 body roles.

The extraction steps: catalog CHD (or ISO) -> identity check (exact ELF sha256, both archives) -> stage headers index ->
the model from a resident stage (`r_*` first).

**Offline check against the owned disc:** all 19 verified (1,462 to 3,144 triangles, 1.77 to 2.15 m, no missing
textures). The previews show the characters upright, facing the camera, and textured.

CLI: `python -m gbox.mgs2_inventory <chd|iso> [stage ...]` and `python -m gbox.mgs2_models <chd|iso> <out_dir> [slug ...]`.

## Writer (`gbox/mgs2_swap.py`)

Slots (`SLOTS`; each slot names every kms it replaces, plus accessory models it collapses):

| slot | replaces | collapsed |
|---|---|---|
| `snake` | `sna_def`, `55ab65`, `bfa829`, `sna_shadow` | bandana tails `sna_mugen_bdn1/2`, `caed09` |
| `raiden` | `rai_def`, `b41e89`, `rai_def_mt`, `rai_shadow` | Raiden's hair `cad689` |
| `raiden_naked`, `raiden_disguise`, `pliskin` | their models | |
| `soldier_tanker`, `soldier_tanker_heavy` | `gbs_def`, `c9aaaf` | the `gbs` hand / eye models |
| `soldier_plant`, `soldier_plant_heavy` | `d83aaf`, `d7aaaf` | the `gps` hand / eye models |
| `soldier_hightech`, `seal`, `marine`, `tengu`, `olga`, `ninja`, `ocelot`, `solidus`, `otacon` | their models | |

Aggregates: `player` = snake + raiden, `soldiers` / `enemies` = every soldier slot.

Per slot and per stage that carries one of its models:

1. **Fit.** `sm64_swap.retarget` onto that model's own skeleton, using the kms body roles: rigid per limb, one bone
   per vertex, in the game's rest pose. A chibi head is shrunk to 1.8 x the cast's head, so Sonic stays big-headed but
   fits. The fit events are planned per slot (`FE.plan`), then scale / retarget / proportion (from the retarget),
   weights, decimate, encode and write.
2. **kms.** The original header and bone records are kept. Each bone gets the triangles whose deepest corner bone it
   is, as greedy strips in the game's parity (<= 32 vertices per part). A corner on the parent bone gets weight 0 in a
   blend part. The result is zero-padded to the original size, so nothing in the stage moves. Too big: the vertices
   are clustered per bone until the model fits.
3. **Texture.** The donor's textures go into one A x A 8-bit atlas (A = 512 / 256 / 128 / 64) in the model's texture
   pack.
   * Placement: a PSMT8 page region and a CLUT that no texture outside the slot touches (checked byte by byte in
     GS memory).
   * The slot's most used texture (the "hijacked" entry: TEX0 / TEX2 / CLAMP / rect / centre) points at the atlas.
   * One placement per pack and stage, shared by every model of the slot.
4. **Stage.** Pages with a changed file are re-deflated, re-encrypted and written back in place. A stage that no longer
   fits its sectors fails alone. The TOC and every other stage stay byte-identical.
5. **Disc.** The base ISO is unpacked once per game (`cache/modbase/<game>/`, 6.4 GB, ~9 min) and copied into the mod
   folder. Every written stage is read back from the image (archive, header, pages, file bytes).

`characters op=use character=<slug> game_id=cb7aae71edb10cd3 slot=<slot>`, `op=match pairs=[...]`, and
`op=cast_swap target_game=cb7aae71edb10cd3 source=sonic` (pairs builder `mgs2_swap.build_cast`) all build one mod:
`cache/mods/cb7aae71edb10cd3/<mod>/Metal Gear Solid 2 - Substance (USA).iso`.

CLI: `python -m gbox.mgs2_swap <chd|iso> <out.iso> snake=<donor>.glb soldiers=<donor>.glb ...` (roles from the donor's
collection `meta.json`).

## Pick whip and on the fly

* **Pick whip.** The desktop pick whip's **Try live replacement** sends `characters op=live_use character=<donor>
  session_id x y target=<identified name>`. The new `target` field carries the name from "Identify selected
  character", if the operator used it. For MGS2 this routes to `mgs2_swap.use`:
  * the session's current stage is read from EE RAM. The stage loader's state pointer is at `0x1b9300` and
    `+0x3c` holds the stage name hash (`current_stage`, mapped through the 283 stage names).
  * the target becomes a slot:
    * "Snake" / "Raiden" / "Olga" / "Ocelot" ... map to their slots;
    * "soldier" / "guard" maps to the soldier slot of that area (Tanker or Big Shell; "heavy" / "armored" picks
      the heavy one);
    * the player, or no name, maps to Snake on the Tanker and Raiden elsewhere.
  * the mod is built, then `@launch` with the session's node.
* **On the fly.** That `@launch` goes through the server's `session_swap`: save state -> the modded image on the same
  worker -> load state -> close the old copy. Requirement: the entry must launch through gBox's PCSX2 (libretro)
  path, which is the platform fix above. Until the hyperspin library is rescanned, the entry still launches through
  RocketLauncher, which takes no mod.
* **What the operator sees.** The loaded state holds the original models in RAM. The replaced models appear when the
  game next loads a stage: a door, an elevator, a cutscene, or Continue.

## Verified offline (this Windows PC, read-only on the catalog; no game launched)

* Identity, both layers, both TOCs, every stage header and page of both archives (scan of 294 stages in 48 s from
  the ISO).
* Reader: the 19 roster entries verified, with previews rendered.
* Writer, full builds on the unpacked base ISO, with donors fetched read-only from the live collection
  (`sonic`, `sa2_shadow`, `sa2_knuckles`, `sa1_e102`, `sa2_rouge`, `sa1_tails`, `sa2_dr_eggman`).
  * snake <- Sonic: 62 models in 33 stages (1,369 triangles, no clustering, 512 or 256 atlas).
  * raiden <- Shadow: 46 models (1,543 triangles).
  * soldier_tanker <- Knuckles, soldier_plant <- E-102: every built stage fit its sectors, and every written file
    read back.
  * Previews of the read-back models, rendered from the patched image's own kms + texture pack, show Sonic / Shadow /
    Knuckles / E-102 textured on the Snake / Raiden / soldier skeletons.
* Tests: `tests/test_mgs2.py` (17, synthetic two-layer DVD; the owned-disc test runs when the ISO / CHD is reachable).

## Live check (operator, on the PC that plays it)

1. Rescan HyperSpin so the entry becomes `ps2`: `scan_library {"libraries": ["hyperspin"]}`. Then check
   `GET /api/catalog/cb7aae71edb10cd3` -> `platform: ps2, core: pcsx2`.
2. `characters op=collect game_id=cb7aae71edb10cd3` (19 characters into the collection).
3. Start MGS2 from gBox, play into the Tanker deck (`w00a`), Alt-drag a Sonic card onto Snake -> **Try live
   replacement**. Or chat: "replace Snake with Sonic in MGS2" (`characters op=use character=sonic
   game_id=cb7aae71edb10cd3 slot=snake session_id=<sid>`).
4. After the swap, walk through a door (or Continue). Check that Snake is Sonic, animated, textured, with no floating
   bandana. Then Alt-drag Knuckles onto a soldier (`slot=soldier_tanker`).
5. Report: model drawn? strips / winding (holes = parity), texture (garbled = TEX0 / CLUT), crashes on stage load
   (memory / page budget), the shadow.

## Open items

* In-game verification (PCSX2): drawing, lighting, the atlas TEX0 / CLAMP changes, the second-texture flags (parts are
  written as plain `0x48` / `0x49`), the stencil shadow models, and memory.
* Some soldier stages fail atlas placement: the pack's other textures (gear, other soldier types) leave no 64 x 64
  PSMT8 region. Those stages keep their original model (reported per stage).
* The hull files (type 0x02) and motion banks are not rewritten. The donor uses the game's animations and the original
  hull.
* `current_stage` (EE RAM `0x1b9300`) was derived from the ELF and is not yet checked on a running session. If it reads
  nothing, the pick whip falls back to the target name / Snake.
* The live RAM hot-patch (replace the loaded kms in EE RAM without a stage load) is not built.
