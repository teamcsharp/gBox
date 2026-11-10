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
