# Lane-log text of `ds-pso-gvr-write-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `e84af16c`.

----

## Round 60 (2026-11-10, later session) — the GVR writer: A8's texture half, verified on a real disc texture

Working locally; no lilspark, no live session.

P7a's rigging (`build_swap` for GC) is three Dreamcast assumptions: the body parsed little-endian, PVR textures written
instead of GVR, and `PSO/PL...` file names. Two of the three are already solved elsewhere (`pso_gc_paths`,
`njcm_payload` - the GC NJCM container keeps a little-endian size). The texture half had **no writer at all**: the lane
could *read* GVR (`pso_gc.gvr_decode`, `decode_texture_entry`) but not write one, so `build_swap` still calls
`ninja.pvr_like` (PVR, the Dreamcast format).

**New `gbox/gvr_write.py`:** `gvr_chunk(rgba, gbx=..., fmt=6, pal_fmt=0, flags=0, palette=b"")` builds a GVR chunk in
the exact header layout `pso_gc.gvr_header` reads (`GVRT`, little-endian chunk size, pal/flags, format, big-endian W/H,
texels at +16) with an optional `GBIX` id, and encodes **RGBA8** (`fmt=6`) losslessly: 4x4 blocks, each texel two u16
(`A<<8|R`, `G<<8|B`) in block row-major - the inverse of the decoder's own fmt-6 branch.

**Verified by round trip through the existing decoder:**
* synthetic images at 8x8, 16x8, 32x32, 5x7 and 1x1 (`decode(encode(x)) == x` exactly, including the edge-clamped
  partial blocks);
* header fields (format, width, height, `GBIX` present/absent);
* **a real disc texture** - the first entry of the disc's first GVM, decoded, re-encoded and decoded again is
  bit-identical, so the writer is proven on data the game itself ships, not just on synthetic arrays.

Tests: `tests/test_gvr_write.py` (9). CMPR and the other block formats are deliberately not written yet and the writer
refuses them with a message rather than emitting something the game would misread.

**What this leaves for A8:** the texture half now has a writer; the remaining pieces are (a) wiring `gvr_chunk` into
`build_swap` where `pvr_like` is called today, (b) the big-endian node-tree write (`ninja.write_tree(..., e=">")`
already takes the endianness, as does `tree_nodes`), and (c) the flat GC file names - then a swapped body build can be
checked by `pso_swapfit.compare` before a boot.

### Round 60b (same session) — CMPR, the format class textures actually use

The RGBA8 writer proved the container; the class textures are mostly block-compressed, so the writer gained **CMPR**
(
only builds the 4-colour palette in that case) and the 16 2-bit indices packed from the top of the word, exactly the
inverse of the decoder's fmt-14 branch.

Verified: a flat 8x8 texture of RGB565-exact colours round-trips **bit-identically** in CMPR; a gradient stays within
block-compression bounds; and the disc's first GVM texture round-trips in CMPR with **mean absolute error 0.1** (max 6)
and identical alpha, next to an exact RGBA8 round trip. Tests: 	est_gvr_write.py **11 passed**.

With CMPR in place, uild_swap can replace a class texture in its own format and size (the pvr_like call's job), so
the texture half of A8 is complete: the remaining wiring is the call site, the big-endian tree write and the flat names.
