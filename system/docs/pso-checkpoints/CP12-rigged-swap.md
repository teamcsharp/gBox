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
