# CP12 (P7a): a correct (rigged) swap

Session identity: DeepSeek    Branch: ds-pso-cp12-rigged-swap-20261110    Commits: this branch
Goal: 3

## Round 78: the render step is unblocked - Blender is on this machine after all, and Cycles/OptiX works headless

An earlier note in this lane said Blender was absent. **That was wrong**: the operator pointed out the Blender Launcher on
the Desktop, and the install is at

```
C:\Users\maste\Desktop\Blender Builds\Builds\stable\blender-4.5.10-lts.6dc0b208d1b5\blender.exe
Blender 4.5.10 LTS   build date 2026-05-19
```

(The earlier search only looked under `C:\Program Files` and `D:`, which is why it missed a Desktop build.)

**The headless render path CP12 step 3 needs is proven:**

```
blender.exe --background --factory-startup --python <script>
```

with `render.engine = CYCLES`, `cycles.device = GPU`, `compute_device_type = OPTIX`. The device list the GPU backend reports:

| device | type |
|---|---|
| NVIDIA GeForce RTX 3090 | CUDA **and OPTIX** |
| NVIDIA GeForce RTX 2070 | CUDA and OPTIX |
| Intel Core i9-9980HK | CPU |

A smoke render (16 samples, 320x240, monkey + area light + camera) wrote
**`D:\gBox\pso-ds\renders\blender-smoke.png`** (68,675 bytes) and
`blender-smoke.json` (the engine/device record). The image shows the lit geometry with no missing-GPU fallback, so Cycles ran
on the GPUs. For the swap renders the device selection must be narrowed to the **3090 only** (both GPUs were enabled in the
smoke run).

## What CP12 still needs, in order

1. **A swap built behind `platform='gc'`** - the A8 pieces (`gvr_chunk`, the big-endian tree/body writers, `pso_gc_paths`)
   are already wired into `pso_player.build_swap` on the earlier branches and gated by `pso_swapfit.compare`; this step is
   re-verification against the current main, then a concrete donor -> host pair.
2. **The geometry for the render.** The swapped body is game data, not a Blender file, so the render needs the model's
   vertices/indices extracted to an interchange file (OBJ/PLY) that the headless Blender script can import - the same
   parsing the `pso_swapfit` model walk already does for centres, extended to the full point list.
3. **Render each candidate** (3090 only) before booting: the "no exploded polygons" check is the image.
4. **Boot only the clean ones** to character select (needs the CP4 window), and capture the frame.

## Accept status

- [ ] a swapped body that `pso_swapfit` marks safe - the gate exists and is tested (11 tests); a named donor/host pair for
      this checkpoint is not yet recorded here
- [ ] it renders without exploded polygons (image on `D:`) - the renderer is proven, the candidate render is next
- [ ] it shows at character select with no crash dialog (a frame) - needs the CP4 window

Tests: none changed this round (the render smoke is an artifact, not a unit test).

## Round 79: the swap build attempted - the blocker is endianness, and it is now pinned to the byte

**Inputs that exist:** the donor model **`D:\gBox\pso-ds\p7b\plAbdy00.nj`** (28,724 bytes) and the host body parts on the
disc (`PSO/PL<C>BDY00.NJ`). `pso_player.build_swap(disc, model, roles, work, name, cls, blender=...)` is the rigged-swap
pipeline on main, and `pso_swapfit` is the gate.

**The attempt fails at the first host-body parse:**

```
pso_player.build_swap -> ninja.tree_nodes(data, 0)
struct.error: unpack_from requires a buffer of at least 1209008136 bytes ... offset 1209008128
```

**The cause, measured:** the GameCube body part is a **`NJCM`** file whose tree is **big-endian**:

```
PSO/PLCBDY00.NJ  4e 4a 43 4d  10 60 00 00 ...      # "NJCM", size 0x6010 = 24,592 (little-endian)
tree at +0x00:  BE 0x00000007 0x00001030 ...       # flags 7, offset 0x1030 - sensible big-endian
tree at +0x20:  BE 0x3f800000 = 1.0f               # the identity scale; as LE it is 5.6e-41 nonsense
```

`build_swap` slices the tree correctly (`body_file[8:8+size]`) but then reads it with `struct.unpack_from("<...")` throughout
(`ninja.tree_nodes`, and every `<` unpack in `build_swap` itself), so the first child offset it reads is 0x30100000 /
0x07000000-sized garbage and the unpack runs off the buffer.

**The fix, precisely scoped:** make the host-body path endianness-aware - detect `body_file[:4] == b"NJCM"` and parse the tree
and the model chunks with `>` instead of `<` (a `ninja.tree_nodes(..., endian=">")` parameter, and `>` for the material /
texture / strip reads inside `build_swap`). The GC *writer* (`pso_gc_paths`, `ninja.write_tree`'s big-endian tree writer) is
already the target format, so this is a reader-side change on the same branch.

**Note on the "tree endian" branch:** `ds-pso-tree-endian-20261110`'s tip is a docs move only - `git diff origin/main
origin/ds-pso-tree-endian-20261110 -- system/gbox/ninja.py system/gbox/pso_player.py` is **empty**, so that branch does not
carry the reader either; the fix belongs here.

Tests: none changed (the diagnosis is from a real build attempt with the real Blender path recorded above).

## Round 80: the endianness fixed - the build now reads the whole GameCube host body

The round-79 blocker is fixed on this branch, in three places that each assumed little-endian GameCube data:

1. **`build_swap`'s own body parse**: `e = ">" if body_file[:4] == b"NJCM" else "<"` (the container header itself stays
   little-endian, as `ninja` documents), then `ninja.tree_nodes(data, 0, e)`, `ninja.NJ(body_file, be=be)`,
   `ninja.chunk_list_len(..., e)`, and `e`-prefixed reads for the model pointer, the chunk word/size, the material, the
   texture flags, the vertex list pointer and the node model centres.
2. **`body_roles`** re-parses the same tree (it verifies the class's role map against its own body), so it got the same
   `e`/`be` treatment.
3. **`bml_files(bml)` -> `bml_files(bml, e)`**: the BML entry count and its five-word headers are big-endian on the GameCube;
   read little-endian the count is garbage, which overran the table (`struct.error ... offset 34848, buffer 34816`).

Also fixed: `bml_sec`/`nj_sec` were computed from `disc.files[path][1]`, a **GDRom-only** `(offset, size)` table that a
`GCDisc` does not have (`KeyError: 'PSO/PLCNJ.BML'`). They now use the part sizes directly
(`len(pso_gc_paths.read_part(disc, mpath))`), which is what the sector counts mean anyway.

**Where the build now stops:** `ninja_swap.fit` -> `sm64_swap.load_rig(Path(model), src_roles)` -> `_gltf_load`, i.e. the
**donor must be a rigged GLB/glTF**, not a Ninja file. The `.nj` in `D:\gBox\pso-ds\p7b\` is a *game* file
(`plAbdy00.nj`, 28,724 B, next to `plAnj.bml`), not a library donor; there is no `.glb`/`.gltf` anywhere under
`D:\gBox\pso-ds`. The donor seam is the character library (`characters.library_root` / `re5_donor_pool`), which is CP13's
subject as well.

**Tests:** the PSO suites around the touched code all pass - `test_pso_swapfit.py` + `test_pso_classes.py` **12 passed**,
`test_pso_gc_swap.py` + `test_pso_player_textures.py` + `test_pso_player_equipment.py` **36 passed**.

**Next step, precise:** build (or find) a rigged GLB donor, run `build_swap` with the roles from `model_roles(path)`, gate
with `pso_swapfit.compare`, export the swapped body's geometry and render it with the proven headless Blender path.
