# CP13 (P7b): library donors, per boot and then hot

Session identity: DeepSeek    Branch: ds-pso-cp13-library-donors-20261110    Commits: this branch
Goal: 3

## Round 84: the per-boot donor list runs through CP12's path - one clean, one donor-specific defect

CP13's first step is "a donor from gBox's character library, retargeted to PSO's 64-bone skeleton by CP12's path, built, and
shown at character select". The build half of that now runs offline for **every** library donor, because CP12's path is
proven end to end (`build_swap` -> `pso_swapfit` gate -> body export -> headless Blender render on the 3090). Two donors were
run through it:

| donor | model | source -> baked triangles | scale | gate | body | render |
|---|---|---|---|---|---|---|
| **Daisy** (`daisy_ssbu`) | 10.2 MB | 23,635 -> **788** | 1.3466 | **SAFE**, subset buckets (518 vertices against the host's 311) | 44,424 B, 582 vertices, 673 triangles in the render, bounds x -8.81..8.80 / y -12.01..7.14 / z 0.03..25.51 | **coherent figure in a full dress** (`D:\\gBox\\pso-ds\\renders\\cp13-daisy.png`) |
| **Cloud** (`cloud_ssbu`) | 16.4 MB | build completed | - | **not reached** | 50,608 B, **unparsable** | - |

**Cloud's defect, isolated:** the build writes the body, but `ninja.NJ(body, be=True)` desynchronises while walking two nodes'
polygon lists - node **0** and node **39** - running off the 50,460-byte payload (node 0's walk reaches offset 0x20960, node
39's 0xfaca, against a payload of 0xc51c). The other 62 nodes' lists walk cleanly, so this is data-dependent, not a general
writer break: the two nodes whose lists overrun are exactly the kind that carry the host's kept vertex chunks
(`keep_vlist`) plus new geometry, and their chunk stream stops looking like chunks (bogus types 52/20/46 and 32/48 at the
last positions). The diagnosis script is kept as `docs/research/pso-cp13-cloud-body-walk.py`; the next step is a
node-by-node byte comparison against Daisy's clean body, which keeps the same shape but smaller chunks.

**The render for Daisy** was produced with the same headless path as CP12: Cycles, 64 samples, 900x900, **RTX 3090 only**
(`devices_enabled: ["NVIDIA GeForce RTX 3090"]`), importing the OBJ exported from the *game* body (per-corner snapshots), so
the image shows what the game will draw, not the donor source.

## What CP13 still needs

1. **the fix for Cloud-style donors** (nodes with both kept host vertex chunks and new geometry);
2. **the "per boot" half in game**: pick a donor from the library in the character menu and see it at character select - needs
   the CP4 window;
3. **the "then hot" half**: swap the donor without returning to the menu - the same window, after the per-boot case works.

Tests: no new unit tests this round (both donors are end-to-end artifacts); the CP12 snapshot test (`1 passed`) guards the
export that produced the Daisy render.
