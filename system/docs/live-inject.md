# Live inject: identify the character under the pick whip, replace it in RAM

Status: **backend written and tested on synthetic RAM images and fake sessions; not yet run against a live
emulator.** The steps for the first live check are at the end of this page.

The pick whip (docs/live-picker.md) calls two tools. `pick_identify` works out what is under the cursor and where it
is in emulated RAM. `pick_replace` then puts a collection character into that slot. The character goes into the
running game's RAM when the game allows it. Otherwise the game's swap writer builds a mod and the session is swapped
to it at the same moment.

Both tools run as jobs on the worker that hosts the session (dispatch them with `require_worker` set to the
session's worker). Code: `gbox/pick_tool.py` (the tools), `gbox/pick_ram.py` (RAM analysis), `gbox/live_inject.py`
(the injection engine), `gbox/pick_learn.py` (what each pick teaches).

## Contract

### `pick_identify`

Input:

| field | default | meaning |
|---|---|---|
| `session_id` | | the running session |
| `x`, `y` | | the click, 0..1 across and down the game window |
| `region` | null | the selection: `{x, y, w, h}`, `{x0, y0, x1, y1}` or `[x0, y0, x1, y1]` (window fractions). Entities inside it win over the click point. |
| `window_aspect` | 4/3 | width / height of the window the click was in (pillar / letter boxes are removed) |
| `capture` | false | also capture the frame with RenderDoc (Windows sessions started with Examine 3D): the draws under the point, their textures found in RAM |
| `deep` | true | RAM snapshot + pointer walk. `false` = the entity only (fast hover) |
| `analyze` | `auto` | Ghidra on static roots: `auto` (once per root, cached), `never`, `always` |

Output (top-level fields):

```json
{
  "entity": {"class": "TObjEneBm5Wolf", "kind": "enemy", "ptr": "0x8C4A1230", "x": 1.0, "y": 0.0, "z": 30.0, "screen": [0.51, 0.62], "miss": 0.02},
  "game_id": "daba7a3b195dcf6b",
  "slot": "enemy:wolf",
  "model": "pso_wolf",
  "ram": {
    "entity_struct": "0x8C4A1230", "struct_size": "0x00000340",
    "model": "0x8C5F0000", "model_detail": {"kind": "ninja_object", "nodes": 51, "chunk_models": 22, "span": ["0x8C5F0000", "0x8C5F8A40"]},
    "model_path": [["0x8C4A1230", "0x00000034"]],
    "skeleton": "0x8C601000", "display_list": null, "vertex_buffer": "0x8C5F2000",
    "structures": [{"at": "0x8C5F0000", "kind": "ninja_object", "via": "0x00000034", "detail": {}}],
    "textures": [{"texture": "tex0", "addr": "0x80F41000", "format": "gx_rgb5a3"}],
    "model_images": [{"name": "PSO/BM_ENE_BM5_WOLF_A.BML:bm5_s_kem_body.nj#NJCM", "base": "0x8C5F0000", "bytes": 35392}]
  },
  "evidence": [{"step": "entity", "ok": true, "detail": "...", "source": "profile.camera projection (tools.project_point)"}],
  "confidence": 0.8,
  "replaceable": {"live": true, "build": true, "reason": "live: ...; build: ...", "live_reason": "...", "build_reason": "...", "writer": "gbox.pso_player"},
  "backend": "profile", "session_id": "...", "title": "...", "platform": "dreamcast", "click": [0.5, 0.6],
  "draws": [], "slot_guess": false, "seconds": 1.4
}
```

`ram` carries only the keys that were found. The roles are `entity_struct`, `model` (node tree / object / CHR),
`skeleton` (pose or limb matrices, the OoT limb table), `display_list`, `vertex_buffer`, `textures` and
`model_images` (the writer's model images located by learned signatures). Each found role also has `<role>_detail`
and `<role>_path` (the pointer path from the entity). `slot` is the writer slot that `characters op=use` and
`pick_replace` accept. `slot_guess` is true when the game has no entity mapping and the writer's `player` slot was
assumed; the UI should ask the operator to confirm. `evidence` lists every step in order with its source.

### `pick_replace`

Input: `{session_id, pick (the pick_identify result, unchanged), character (collection slug or name), mode: "live" |
"build", fallback = true, rebuild = false, refresh_ram = true, revert_on_fail = true, allow_arena = false}`.

The job emits fit events for the slot. The model key is the slot, so the Fitting pop-up shows "<character> -> <game>
(<slot>)" with the writer's stages (scale, retarget, proportion, weights, decimate, encode) and a final `write`
stage. For live mode the `write` data is `{target: "RAM", bytes, writes}`; for build mode it is
`{target: "session swap", mod, session}`. When the writer runs on another node (the collection lives on the
Spark), the sub-job's stages and snapshot GLBs are relayed onto this job.

Output `result`:

| field | meaning |
|---|---|
| `status` | `live` (in RAM, same session), `swapped` (build + session swap), `live_failed` (live impossible and `fallback=false`), `failed`, `not_replaceable` |
| `mode_used` | `live` or `build` |
| `fell_back`, `fallback_reason` | live was asked for and wasn't possible: why |
| `live` | method, plan (assets, instances, bytes), apply report (verified, rolled_back, pause_preserved, frame_check) |
| `build` | the prepared mod, the swap job, the new `session_id`, `ram_refresh` |
| `session_id` | the session that shows the character now (a new one after a swap) |

## How identify works

1. **Entity.** The game's own view of the point:
   - OoT: `oot_live.pick` (actors projected through `play->viewProjectionMtxF`), the actor's object segment
     and its SkelAnime (limb table, joint table).
   - DOA2: `doa2_context.inspect_actor` (actor -> cached CHR, model and texture tables; pinned to the owned
     executable). DOA2 actor positions aren't mapped, so with two fighters on screen the screen half chooses one.
     The evidence flags this, and confidence drops.
   - SM64: Mario (the writer's only slot). His segment-04 model is found byte-exact in RDRAM.
   - Profile games (`system/profiles/*.json` with `camera`): every entity, the player included, is projected through
     the look-at camera. AUF-style `pos_angles_fov` cameras use `gbox.entity_probe`.
2. **Draw** (`capture=true`, Windows + RenderDoc). `scene_capture` captures the frame and `characters.cut_scene`
   cuts out the object at the point. Its draw calls (draw index, event id, vertex / triangle counts) are matched to the
   RAM structures by exact count. Its textures are re-encoded losslessly in the console formats (GX RGB5A3 / RGB565 /
   IA8 / I8 / RGBA8 tiles, N64 RGBA16 / RGBA32 rows) and searched in RAM. The owners of a texture found in RAM are
   followed back by pointer chains. The capture's own vertices are post-transform (view or screen space), so they
   can't be searched in RAM directly. `pick_ram.find_vertices` is there for model-space data.
3. **RAM.** A main-RAM snapshot is taken in one paused moment; the operator's own pause is kept. N64 word-swapped
   RDRAM is normalised. Learned pointer paths are tried first, so a later pick is instant. Otherwise a pointer walk
   runs from the entity struct (two levels, pointer aliases such as DC 0x0C/0x8C/0xAC or GC 0x80/0xC0) through the
   platform's detectors:
   - Ninja `NJS_OBJECT` trees with chunk models
   - N64 F3D / F3DEX2 display lists
   - GX display-list heads
   - vertex arrays (f32 / s16 / N64 Vtx)
   - 3x4 / 4x4 matrix arrays (skeletons)

   Learned model signatures (from a previous replace of the slot) locate the model image itself.
4. **Slot, model, replaceable.**
   - Slot: the writer's slot comes from `char_coverage.cast_slots`, matched by the profile's `models` file/entry or
     by name.
   - Model: the collection entry ripped from this game, matched by name.
   - Replaceable: `live` / `build` with the reason for each (the matrix below).
5. **Static analysis** (`analyze=auto`). Static roots are collected: profile tables, and words in the executable's
   data (GC: below OSArenaLo; DC: the 1ST_READ area) that point at the entity. They go to `pick_ghidra` as a
   background job on a node with Ghidra. That job loads the RAM image as an ELF, runs `FindRefs.java` on the roots
   and `ExplainAddresses.java` on the referencing functions (the loader / renderer). The findings land in the
   learned profile, plus hypothesis edges in the knowledge graph (promote them with runtime evidence). REA's Ghidra
   provider can run the same analysis (docs/rea.md) when a node has REA rather than a bare Ghidra.
6. **Learning.** For each class, the learned profile keeps the slot, the model slug, the struct size and the pointer
   paths to the model / skeleton / display list / vertex buffer. For each slot it keeps the model signatures and the
   last replace outcome. It also keeps the Ghidra findings per root.

## How live injection works (`gbox/live_inject.py`)

1. **Build the fit** (`pick_prepare`, on the control plane). The game's writer runs exactly as
   `characters op=use launch=false` runs it: retarget onto the slot's skeleton, re-rig, the writer's budgets, fit
   events. The files it changed (the mod's marker, or a bounded compare of the two disc images: GD-ROM, GameCube,
   ISO9660, PS1 raw / CHD) are turned into what the game keeps in RAM:
   - PRS and Yaz0 are decompressed.
   - AFS archives and PSO BML packs are split into members.
   - Ninja files become their NJCM data plus the POF0 pointer list.

   Executables are refused (code patches are only safe from boot). Texture archives that live in VRAM (PVR / PVM /
   GVR) are left out and named in `notes`.
2. **Locate** each changed window in a fresh paused snapshot. A match must be exact, or differ only in pointer words
   moved by one constant (the loader's relocation). With POF0 the pointer words are known exactly. Without it they
   are learned from the loaded instance itself. All windows of an asset must agree on one base; every agreeing base
   is a loaded instance, and up to 4 are written.
3. **Plan.** The new bytes are relocated by that base.
   - Same layout: only the changed words are written.
   - Changed layout (a Ninja tree with a new pointer list): the whole image is replaced in its own footprint. If it
     is larger, it goes into a declared free arena: zero, unowned, with guard bands. Its owners are re-pointed, and
     the alias form of each pointer is kept.

   An instance is refused when:
   - a replaced byte was changed by the game at runtime (animated / deformed geometry)
   - a new pointer appears where the format has no pointer table
   - another structure points into a model whose layout changes
   - the model outgrows its footprint and no arena is declared

   The model must be placeable everywhere or nothing is written.
4. **Apply.** Paused, every expected byte is re-read and checked before any write. The writes go in 512-byte chunks
   (RetroArch's command limit) and are all read back. On any mismatch every written byte is restored and the
   rollback is read back too. If the rollback can't be verified, the game is left paused and the error says so.
   Afterwards the operator's pause state is restored. A running game gets a frame check (picture not black, still
   animating). A failed frame check restores the RAM.
5. **Build fallback.** The prepared mod goes through `POST /api/sessions/{sid}/swap` with `keep_state: true` (save
   state, prepare, launch, load state). The restored state still holds the old model in RAM
   (docs/model-replacement-state.md), so the same in-RAM images are injected into the new session when it runs on
   this worker (`refresh_ram`). Without that refresh the model only changes at the next load of that character.

Arenas are never guessed. Zeroed bss is often a buffer the game fills later. Declare one when an analysis or the
operator has shown it to be free:
`POST /api/profiles/<game_id>/pick {"arenas": [["0x8CE00000", "0x8CF00000"]]}`, then replace with `allow_arena=true`.

## Which games go live

Verification: everything below is checked on synthetic RAM / fake sessions only (tests listed at the end). Nothing
has been injected into a running game by this backend yet.

| Game (writer) | identify | live | notes |
|---|---|---|---|
| Ocarina of Time, NTSC 1.2 (oot_swap) | actor, object, SkelAnime, limb + joint tables | **NPCs: yes** (characters `live_use`, `oot_hot_swap`: a bounded object replacement, verified byte by byte) | Link: build. All loaded actors that share the object change. |
| Super Mario 64 on RetroArch (sm64_swap) | Mario's segment 04 in RDRAM | **yes** (`live_link` hot swap: segment 04 + display-list pointers) | Other emulators: build. |
| PSO Ver.2 DC (pso_player: enemies) | profile camera + entity table, Ninja tree via pointer walk, slot from `profile.models` | generic, attempted | NJ + POF0, so relocation is exact. The enemy writer grows the model (new vertex chunks + strips), so it needs a declared arena, else build. The PVM atlas lives in VRAM and isn't injected (old textures until the next load). The player slot is marked not working by the writer. |
| Jet Grind Radio DC (jgr_swap) | player slot guess / learned signatures | generic, likely | PLAYER.AFS keeps its length and every other entry. Members are diffed in place. |
| Sonic Adventure 2 DC (sa2_chars) | player slot guess / learned signatures | generic, likely build | The writer re-points nodes in SONICMDL (no POF0 there), so it is refused as a pointer-layout change. The texture lives in VRAM. |
| Crazy Taxi GC (crazy_taxi_swap) | player slot guess / learned signatures | generic, likely | `ct/polDC0.all` blobs keep size and order. Works if the bank is resident as loaded. |
| 007 Agent Under Fire GC (auf_swap) | `entity_probe` (gclient camera), records, `modelindex` | generic, attempted | Rebuilt `maps/*.ngc`. The level's models must be resident as loaded. |
| Metal Arms GC, RE4 GC | slot guess / learned | generic, attempted | |
| PS2 (GTA III, GTA LCS, Def Jam Vendetta, Enter the Matrix) | slot guess / learned | generic, attempted | ISO9660 images. GS textures are not injected. |
| PS1 (SmackDown! 2, Parasite Eve 1/2, FF7) | slot guess / learned | generic, attempted | Models in main RAM are diffed. Textures / CLUTs live in VRAM and are not injected. |
| Dead or Alive 2 LE (doa2_swap) | actor -> CHR / model / texture tables (doa2_context) | **no** | The CHR geometry is deformed in RAM every frame (SUP/APV/ACS) and the writer patches 1ST_READ.BIN. Build + swap. |
| No Mercy, Clay Fighter SC (N64 ROM writers) | slot guess | no | ROM mods aren't file images. Build. |
| RE6 X360, GTA VC PC, DOA++ arcade | | no | Build. |
| MGS VR / MGS1 | | (out of scope here) | Owned by another agent. |

"Generic" means `pick_replace` decides from RAM at replace time. If the rebuilt images are found, they are written
and verified; otherwise it falls back to build with the reason, and the learned profile remembers structural
refusals.

## Live verification (for the operator)

Nothing in this procedure stops or starts a session by itself: the build fallback only runs if you ask for it.

1. **Deploy.** The branch is merged and the cron deploy has run. The workers have reloaded tool modules, and
   `GET /api/tools` lists `pick_identify`, `pick_replace`, `pick_prepare` (Spark only) and `pick_ghidra` (nodes with
   Ghidra).
2. **OoT NPC (expected live).** Launch Ocarina of Time NTSC 1.2, stand near Saria / a Kokiri, and pause.
   1. Run `pick_identify {session_id, x, y}` on the NPC. Check `backend: oot`, `slot: En_...`, `ram.skeleton`, and
      `replaceable.live: true`.
   2. Run `pick_replace {session_id, pick, character: <slug>, mode: "live"}`. Check `status: live` and that the NPC
      changes on resume.
3. **SM64 (expected live on RetroArch).** Launch SM64 (RetroArch).
   1. Run `pick_identify` anywhere on Mario. Check `ram.model` (segment 04 found).
   2. Run `pick_replace mode=live`. Check `status: live` and `live.result.reload.verified`.
4. **PSO DC enemy (expected build fallback unless an arena is declared).** In Forest 1 near a Savage Wolf:
   1. Run `pick_identify` on the wolf. Check `entity.class: TObjEneBm5Wolf`, `slot: enemy:wolf`, `ram.model` (Ninja
      tree, `model_detail.nodes`) and `evidence`.
   2. Run `pick_replace mode=live`. Expected: `fell_back: true`, `fallback_reason` "... larger than the loaded one
      ... no declared free arena", then `status: swapped` with `build.ram_refresh`.
   3. Check the wolf in the swapped session. `ram_refresh.ok` means it changed without walking away. If it didn't,
      the new model appears at the next room load.
5. **Crazy Taxi GC / JGR DC (expected live if the files are resident as loaded).**
   1. Run `pick_identify` (slot `player`, `slot_guess: true`), then `pick_replace mode=live`.
   2. If `status: live`, the driver / skater changes in place. Note `live.plan.assets[*].instances[*].base`.
   3. If it fell back, `fallback_reason` says why: not in RAM / runtime-modified / pointer layout.
6. **Second pick.** Pick the same thing again: `evidence` shows `learned model` / `model image` steps and
   `seconds` drops.
7. **Ghidra.** After a profile-game pick, the `pick_ghidra` job finishes on a Ghidra node.
   `GET /api/profiles/<game_id>/pick` shows `ghidra.<root>.functions`, and `/api/knowledge` has hypothesis edges.

Report each game's `status`, `fallback_reason` and whether the picture changed. Successful live games then get
`live_ok: true` in the learned profile.

## Tests

- `tests/test_pick_ram.py`: Ninja trees through aliased pointers, pointer scans and back chains, N64 display lists
  in both dialects and word-swapped RDRAM, vertex / matrix arrays, relocation-tolerant search, GX texture
  re-encoding, free arenas.
- `tests/test_live_inject.py`: verified write with the pause state kept, a stale snapshot never written, read-back
  failure rolled back, an unverifiable rollback left paused, runtime-modified bytes refused, executables refused,
  learned relocation, a new pointer without a pointer table refused, Ninja POF0 in place / into an arena with the
  owner re-pointed / refused when something points inside, PRS and AFS containers, patch pack and signatures, folder
  / ISO9660 mod diffs, word-swapped N64 writes.
- `tests/test_pick_tool.py`:
  - identify on a profile game: entity, slot from the model map, Ninja model via the walk, learned path on the
    second pick, Ghidra roots
  - OoT backend
  - capture: texture found in RAM, draw matched to a vertex array
  - live replace with fit events and learning
  - live -> build fallback with the session swap and the new session's RAM refresh
  - frame-check revert
  - refusals
  - fit-event relay
  - `pick_ghidra` parsing
  - the `/api/profiles/{gid}/pick` endpoints
