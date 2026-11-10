# Lane-log text of `ds-pso-body-swap-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `8be37eb0`.

----

### Round 62 (2026-11-10, later session) — the platform-aware body read/write that `build_swap`'s GC path needs

Working locally; no lilspark, no live session.

`pso_player.build_swap` is the Dreamcast path: it parses the body little-endian, writes PVR textures and looks files up
as `PSO/PL...`. The swap's encode() step edits a *parsed* body and re-emits it, so the first mechanical piece is one
place that reads and writes a class body with the right endianness - now added to `gbox/pso_player.py`:

* `BODY_ENDIAN = {"dc": "<", "gc": ">"}` and `body_endian(platform)` (an unknown platform is a `ValueError`, not a
  guess);
* `read_body_payload(disc, cls, platform)` -> (whole file, NJCM payload, tail, struct format) - the NJCM *container* size
  stays little-endian on both platforms, which `pso_gc.njcm_payload` proves from the disc;
* `body_models(payload, nodes, e)` -> each node's vertex list, primitive list, centre and radius, with `chunk_list_len`
  in the same endianness;
* `rewrite_body(disc, cls, platform)` -> the body parsed and re-emitted with a fresh POF0 table.

**Verified on the real HUmar body (GC):** the rewrite is **21,308 bytes - the same size as the original**, with a
21,168-byte payload and a 132-byte `POF0` tail, and the emitted tree is **identical node for node** (flags, child/sibling,
the 36-byte `trs`) to the original's 64 nodes; every model's vertex list bytes still appear verbatim in the output. It is
not byte-identical to the original - `write_tree` lays the model blocks out in its own order - which is the same property
the Dreamcast path has relied on since round 34 (the game addresses everything through the tree and the POF0 table).

Tests (`tests/test_pso_body.py`, 3): the endianness mapping and the unknown-platform refusal; the same-size, same-tree
rewrite with the container size covering the payload and `POF0` at the tail; and a check that every model's vertex list
survives into the emitted payload. Player-texture and ninja suites stay green: **35 passed** across
`test_pso_player_textures`, `test_ninja_ripper` and the new file.

**Left for A8:** call these from `build_swap` behind a `platform="gc"` argument (the tree endianness is this round's
helpers), replace `ninja.pvr_like` with `gvr_write.gvr_chunk` preserving the entry's format (CMPR/RGBA8) and size, and
flatten the BML entry names to the GC ones; then `pso_swapfit.compare` gates a build before any boot.

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

### Round 63 (2026-11-10, later session) — `build_swap` is now a GC path too (A8 wiring done)

Working locally; no lilspark, no live session.

`pso_player.build_swap(..., platform="gc")` now runs the whole Dreamcast-to-GameCube adaptation, and every piece was
found and fixed against the real disc rather than assumed:

* **body/tree**: `tree_nodes(..., ">")`, `ninja.NJ(be=True)`, the material/strip scan and every pack/unpack in the
  encode step use the platform's endianness; `body_roles(..., platform)` parses the class's role map the same way;
* **BML**: the GC BML is **big-endian** (count at +4 read big-endian is 13, little-endian is nonsense) - `bml_files`
  and `bml_build` are called with `e=">"`, so the flat entry names (`plAbdy00.nj`, `plAcap06.nj`) are read and written
  correctly;
* **paths**: the GC disc stores the class parts as **loose flat files** (`plAbdy00.nj`, `plAnj.bml`, `plAtex.afs`), not
  under `PSO/PL...`, so the paths are resolved through `pso_gc_paths.gc_path` for GC and the emitted `files` map uses
  those names; the head/hair/cap speck loop matches the flat names too;
* **textures**: each AFS entry is a **GVR chunk (fmt 14, CMPR, 128x128)**; the atlas (a PIL image from `ninja_swap.fit`)
  is converted to RGBA and re-encoded with `gvr_write.gvr_chunk` in the entry's own format, gbix and palette fields,
  and only written when it fits the entry;
* dead code removed: two `bml_sec`/`nj_sec` lines were computed and never used.

**Proven end-to-end without Blender** by standing in for `ninja_swap.fit` (which only does the rigging) and letting the
real encode path run on the owned disc: the swap produces `plAbdy00.nj` (64 big-endian nodes, `POF0` tail, under the
64 KiB cap), `plAnj.bml` with the flat entries and the head/hair/cap parts replaced by specks, and `plAtex.afs` whose
entries are again GVR CMPR chunks that decode to the atlas (mean error under 8). The Dreamcast branch of every one of
those decisions is the previous behaviour (`e="<"`, `pvr_like`, `PSO/PL...`), so the DC path is unchanged.

Tests: `tests/test_pso_swap_gc.py` (3 - the end-to-end GC swap, the writer's refusal for a format it cannot write, an
unknown platform refused before any work). With `test_pso_body`, `test_gvr_write`, `test_pso_player_textures`,
`test_ninja_ripper` and `test_ninja_pvr_mips`: **84 passed**.

The branch stacks three A8 steps: `ds-pso-gvr-write-20261110` (the GVR writer) merged with
`ds-pso-body-platform-20261110` (the platform-aware body), plus this wiring. What A8 still needs is not code: a real
`build_swap(platform="gc")` run with Blender for the rigging, then `pso_swapfit.compare` gating and a boot.

## Round 67 (2026-11-10, later still) — the gated body swap (P7b's raw path, without Blender)

Working locally; no lilspark, no live session.

The P7a rigging item wants the swap gated before a build exists: "`build_swap` adapted for GC ..., gated by
`pso_swapfit.compare` so a donor that would crash is refused". The *body* half of that swap needs no Blender, and it is
the exact swap the lane measured live in round 35 (HUcast over HUmar renders deformed; HUnewearl crashes). New in
`gbox/pso_player.py`:

**`body_swap(disc, host="A", donor="C", *, platform="gc")`** - copies one class's whole `BDY00.NJ` over another's and
rewrites the host's BML entry, with `pso_swapfit.compare` as the gate:

* bucket mismatch -> **refused, `files` empty**, with the compare reason ("the donor mesh references materials the host
  does not have") - no file is written, which is the crash case stopped before a build;
* buckets equal with a different vertex count -> **allowed and reported `deforms: True`** ("311 vertices against the
  host's 269");
* same class or an unknown class letter -> `ValueError` before anything is read.
* platform-aware: flat GC part paths and big-endian BML (`e=">"`), Dreamcast names and little-endian otherwise.

**Checked on the owned disc:** `A <- C` (HUcast donor over HUmar) returns `{plAbdy00.nj: <donor bytes>, plAnj.bml}` with
`deforms: True`, and the rebuilt BML entry's compressed size 19,263 vs decompressed 24,732 = the donor body exactly;
`A <- B` (HUnewearl) is refused with the bucket list; `A <- A` is refused as the same class.

Tests: `tests/test_pso_body_swap.py` (3 - the allowed/deform case including the BML decompressed-size check, the bucket
refusal with no files, and the up-front refusals). With `test_pso_swap_gc` and `test_pso_body`: **9 passed**.

This is the second half of P7b's safety story next to the editor page's swap-fit endpoint: the page *shows* a verdict,
and `body_swap` *enforces* it before producing files. What remains for A8/P7a is the Blender rigging run for a
collection model (not installed on this machine), then a mod build and a boot.
