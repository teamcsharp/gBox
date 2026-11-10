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

## Round 85: the Cloud diagnosis above is wrong, and here is why (correction)

The round-84 claim that "Cloud's nodes 0 and 39 overrun their polygon lists" does **not** survive a byte-level look. The
model struct is `{u32 vlist, u32 plist, float centre x3, float radius}`, and for both bodies node 0's model at `0xd00` reads

```
vlist 0x0   plist 0xd18   centre (6.14.., 0.00.., ...) radius ...
0xd18:  ff 00 | 00 00 00 00 0d 34 | 40 c4 ac 73 ...     <- 0xFF is an EMPTY polygon list, then the floats
```

i.e. `plist` addresses an **empty list** (a lone end chunk) and everything after it is the model's centre/radius floats. My
round-84 walker started at `plist`, read the end chunk, then kept walking into those floats and pinned the "overrun" on
arbitrary float bytes - which is exactly what it also did on **Daisy** (it reported `unknown 0x3c` / `unknown 0x78` /
`unknown 0xc` for Daisy's nodes 0, 26 and 39). So the comparison was measuring my own walker, not the bodies.

**What is actually known about Cloud:** `ninja.NJ(cloud_body, be=True)` raises in `_polys` with an offset beyond the payload,
and the body is 50,608 bytes with 64 nodes, **18 non-empty polygon lists**, and every model pointer in range. The failure is
therefore inside one of those 18 lists, and the next step is to instrument `NJ._polys` itself (record the node and offset
when the walk overruns) rather than reimplementing it - a walker outside the class cannot know where a list legitimately
ends.

That correction is the round's real result: it stops the next session from chasing a defect that the evidence never showed,
and it narrows Cloud to "one of 18 lists, found by instrumenting the parser".
