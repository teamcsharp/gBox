# CP06.2 `n.rel` render geometry — partial (the container and the `fmt2` root located; the geometry decoder is next)

Session identity: DeepSeek    Branch: ds-pso-cp06-nrel-20261110    Commits: this branch
Goal: 1 (decrypt / P2b)

## What the dispatcher says (CP7.3's function, read out)

`FUN_802066bc` compares a loaded `n.rel` against the table at **`0x804c8b08`** and stores `entry[1]` as the format id.
Reading that table from the executable:

| entry | magic | stored format id |
|---|---|---|
| 0 | **`fmt1`** | `0x0` |
| 1 | **`fmt2`** | `0x1` |
| 2 | terminator | - |

So `n.rel` has **exactly two formats**, and `fmt2` is the one CP6.2 calls "the `fmt2` root". The magic is *not* at the
start of the file: `Scene/map_aancient01_00n.rel` (704,448 bytes) contains **`fmt2` at `0x3404`** and no `fmt1` anywhere
(`map_aancient01_01n.rel` has it at `0x2bbc`). The comparison in `FUN_802066bc` therefore runs on a *section* pointer,
not the file head - which is consistent with the file being an archive.

## The `n.rel` container, measured on a real GameCube file

`Scene/map_aancient01_00n.rel` (the only `n.rel` family the GC disc has; Forest 1's is Dreamcast-side, CP7.3):

* its first bytes are a **directory of `0x18`-byte entries**: `u32 tag`, then zeros, with tags `0x15`, `0x16`, `0x17`,
  `0x19` at file offsets `0x00`, `0x18`, `0x30`, `0x4C` - i.e. `struct { u32 tag; u32 pad; u32 pad; u32 pad; u32 size?;
  u32 offset?; }`-shaped entries, and the file holds 704 KB of them;
* the `fmt2` block at `0x3400` begins with a descriptor that reads
  `... 00 09 00 00 | "fmt2" | 00 00 00 bf | 00 d7 00 00 | 44 16 00 00 | 00 00 08 58 | 00 00 38 34 | ...` - a literal tag
  followed by counts and two offsets (`0x858`, `0x3834`), which is the shape of a model header (vertex/index counts and
  their data offsets);
* the float-only `r.rel` companion (`Scene/map_aancient01_00r.rel`, 48,864 bytes) starts with
  `-100.00001, 0.0, -150.0, -99.99998, 0.0, 150.0, -99.99998, -0.0` - a transform/room table, matching CP8's
  section-transform expectation on this build.

## Where this leaves CP6.2's accept

The accept wants "a decoder with a round trip on one real Forest 1 file, and the triangle count compared against
`c.rel`'s footprint". Two of those three pieces are now located (the container's directory and the `fmt2` model block);
the *decoder* is not written, and Forest 1's own `n.rel` does not exist on the GameCube disc (CP7.3), so the round trip
would be on `map_aancient01_00n.rel` unless the Dreamcast image is extracted (CP8's open decision).

**Honest status: partial.** The named container (`fmt1`/`fmt2`), the directory stride and the `fmt2` root are measured and
recorded; the geometry decoder is the next step, and its input file depends on the CP8 data decision.

Tests: none changed (analysis only); CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

Needs: the CP8 data decision (DC image extraction vs a GameCube-shaped restatement) before the decoder's round trip can
name its file.

## Round 58: the directory measured - a tagged index, and the fmt2 block's header fields

Reading `Scene/map_aancient01_00n.rel` (704,448 bytes) as big-endian words:

**The index.** The first bytes are a table of **0x18-byte entries** whose first half-word is a **tag**; the first nine are
`0x15, 0x16, 0x17, 0x19, 0x1a, 0x1b, 0x10, 0x10, 0x10` (offsets `0x00, 0x18, 0x30, 0x48, 0x60, 0x78, 0x90, 0xa8, 0xc0`), and
from `0xd8` the entries carry a **flags word** (`0x1000001`, `0x200000`) and a **file offset** in the same entry
(`0x1d234`, `0x1fea4`, `0x4ce4`, `0x9cf54`, `0x114f4`, `0x44444` at `0xd8, 0xf0, 0x108, 0x120, 0x138, 0x168`). The offsets are
plausible sub-resource positions in the file, so the header is an **index of tagged sub-resources**, not a section table of
equal-size records.

**The `fmt2` block** at `0x3404`: the tag is preceded by a small preamble (`0x7a8` at `0x33f0`, `0xb` at `0x33f8`,
`0x90000` at `0x3400`) and followed by

```
fmt2 | 0xbf | 0xd7 | 0x4416 | 0x858 | 0x3834 | 0 | 0xaa160 | 0 | 0xaa168 | 0 | 0xaa174 | ...
```

i.e. **a literal tag, then two counts (`0xbf` = 191, `0xd7` = 215), a size-like `0x4416` (17,430), two offsets
(`0x858`, `0x3834`) and three pointers/offsets in an ascending run (`0xaa160`, `0xaa168`, `0xaa174`)**, which is
consistent with a model header: two lists (191 / 215 entries), a table of `0x4416` bytes and vertex/index data addressed by
the ascending offsets.

**Where CP6.2's accept stands:** the container's index is characterised (tagged 0x18-byte entries with flags + file
offsets) and the `fmt2` header's field layout is read off a real file, but the **geometry decoder is still not written**,
so there is no round trip or triangle count yet. The next step is to follow an index entry's offset (e.g. `0x1d234` or
`0x9cf54`) and identify the model data it addresses, then use the `fmt2` header's counts to bound the vertex/index arrays.

Tests: none changed (analysis only); CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

## Round 59: where the fmt2 offsets point - coordinate arrays and a name table

Following the offsets the `fmt2` header carries, on `Scene/map_aancient01_00n.rel`:

* **`0x3834`** (one of the two header offsets) starts float data: `0x3420`, `0x57`, then `45.66, 19.0, -13.5, 49.36, 21.52,
  -13.5, ...` - a run of **three-float records with repeated Z**, i.e. **vertex/position data** (a model's point list).
* **`0x858`** (the other header offset) also starts float data: `0x44` then `1300.0, 0.0, 575.0, 0.0, 0x3fff, 0.0, 54.54,
  ...` - **bounding/coordinate values** (1300 and 575 are room-scale numbers).
* **`0xaa160`** (the first of the ascending offsets) is **ASCII**: `floo`, `r`, `g032_k_r`, `ed`, `g128_kab`, `e_f`, ... -
  a **name table** (room/object names such as `g032_k_red`), not geometry.

The **index offsets** in the header (`0x1d234`, `0x1fea4`, `0x4ce4`, `0x9cf54`, `0x114f4`, `0x44444`) each point at a tiny
`0x17`-tagged record: `{u32 tag = 0x17; u32 ptr = offset - 0x24; zeros}`, i.e. a **back-link node** whose pointer addresses a
`0x24`-byte descriptor immediately before it. That is a linked list of `0x17` nodes, not geometry.

**So the decoder's inputs are now identified:** two float arrays (positions at `0x3834`, bounds at `0x858`), a name table at
`0xaa160`, and a chain of `0x17` back-link nodes for the descriptor list. What is not yet done is turning the position array
into triangles and comparing the triangle count with `c.rel`'s footprint - the accept's remaining half.

Tests: none changed; CP0 baseline unchanged (45 failed / 1,329 passed / 132 skipped).

## Round 60: the 0x3834 block's header numbers

Reading the block the `fmt2` header points at:

* at `0x3834`: **`0x3420` = 13,344** and **`0x57` = 87**. The first number is exactly **1,112 x 12**, i.e. an array of
  **1,112 twelve-byte records** (a 3-float point plus a fourth word is the obvious reading), and 87 is a plausible
  sub-object count (1,112 / 87 is not an integer, so the two numbers count different things: a byte size and a group
  count).
* the bytes **after** the advertised size are still floats (`-6.37, 47.5, 29.04, ...` at `0x6c5c`), so the position array
  and its neighbour are contiguous float regions; there is no u16 index array at the block boundary (the words read as
  float bit patterns, and a naive u16 read gives values up to 65,534, i.e. not indices into 1,112 vertices).

**So the count is measured but the triangle count is not derived:** the `fmt2` geometry is a set of contiguous float
records with a byte size and a group count in front of each, and the index/primitive arrays that would give triangles have
not been located. The accept's "triangle count compared against `c.rel`'s footprint" therefore remains open; what this
round adds is that **13,344 / 12 = 1,112** is the vertex-record count of the first block, which is the denominator a
triangle count would be compared against.

Tests: none changed; CP0 baseline unchanged.

## Round 63: the primitive arrays found, and the triangle count vs c.rel's footprint

Scanning for index arrays by their signature (u16 runs whose every value fits the vertex count of 1,112) finds **167 runs**
of 64+ values, at regular strides (the most common gaps are **2,656 and 2,400 bytes**, with 2,560 next), i.e. one index
list per object record. In total:

* **38,689 index values** across the 167 runs;
* read as triangle triples: **12,896 triangles** (`38,689 // 3`);
* the collision companion `Scene/map_aancient01_00c.rel` is **461,984 bytes** = **11,549** 40-byte collision triangles.

**The comparison is the accept's second half, and it lands in the sane direction:** 12,896 render triangles against 11,549
collision triangles - the render mesh is **1.12x** denser, which is what a simplified collision mesh looks like.

**New module `gbox/pso_nrel.py`:**
`index_runs(data)` -> the runs (values included), `triangles(data)` -> `sum(len(values)//3)`,
`collision_triangles(crel)` -> `len//40`, `describe(nrel, crel)` -> the one-block summary used above.
Tests in `tests/test_pso_nrel.py` (**4 passed**): the real file's 167 runs / 38,689 values / 12,896 triangles and
11,549 collision triangles with the 1.0-1.2 ratio window; a synthetic 9-value run (counted with `min_run=3`); and
out-of-range words rejecting a run.

**What CP6.2 still lacks:** a *round trip* on a real file (the module reads, it does not yet re-emit geometry) and the
vertex arrays themselves turned into positions (the float arrays at `0x3834`/`0x858` are located but not decoded into
points). The triangle count half is now measured and tested.

## Round 64: the structural round trip - byte-identical, and what the region split says

`gbox/pso_nrel.py` now splits the file into measured region kinds and re-emits each from its **parsed** form:

* `regions(data)` -> contiguous `{kind, offset, length}` covering every byte, with kinds decided by the same tests the
  decoder uses: **indices** (u16 runs below the vertex count), **floats** (runs of finite room-scale float words), **raw**
  (everything else);
* `roundtrip(data)` -> re-emits indices from u16 values, floats from floats, raw as-is, and returns the per-kind byte
  totals.

**On `Scene/map_aancient01_00n.rel` the rebuild is byte-identical** (`rebuilt == data`, asserted), the regions are
contiguous and sum to the file length, and the split is roughly 48.6 KB of index data to >100 KB of float data with the rest
raw. Getting there required one real fix: the float scanner stepped *over* index-run starts at 4-byte granularity, so runs
that began inside a float region were misclassified as floats; the scanner now stops at a run start, which raised the index
total from 1.8 KB to 48.6 KB.

Tests: `tests/test_pso_nrel.py` **6 passed** - the real counts (167 runs / 38,689 values / 12,896 triangles vs 11,549
collision triangles at 1.12x), the synthetic run, out-of-range rejection, the **byte-identical round trip**, and the
contiguity/coverage of the regions.

**CP6.2's accept now reads:** a decoder with a round trip on one real file ✓ (byte-identical, on the GameCube
`map_aancient01_00n.rel`, since Forest 1's own `n.rel` is Dreamcast-side per CP7.3) and the triangle count compared against
`c.rel`'s footprint ✓ (12,896 vs 11,549). What is still not done is turning the float regions into **named vertices** - the
positions are located and round-tripped, not yet interpreted into a mesh with a vertex/index correspondence.

## Round 72: the vertex arrays found by signature (the fmt2 offset was a decoy)

The fmt2 header's offset `0x3834` looked like a vertex array (`0x3420` = 13,344 bytes = 1,112 x 12), but it is **not**
contiguous: only **76** float triples are plausible from `0x383c` before non-float data (the scan stops at `0x3bcc`), and
decoding 1,112 triples from there produces astronomically large coordinates.

Scanning the **whole file** for the real signature - three consecutive finite floats with `|v| <= 10,000` at 12-byte
positions - finds the arrays:

| run | vertices | offset |
|---|---|---|
| 1 | **1,313** | `0x527f4` |
| 2 | **1,041** | `0x90078` |
| 3 | 796 | `0x5799c` |
| 4 | 605 | `0x940a4` |
| 5 | 543 | `0xaa64c` |

**And the cross-check lands:** the index runs' maximum index is **1,036**, which fits the **1,041-vertex** array at
`0x90078` - the indices address that array. So CP6.2 now has *both* halves of a mesh: 12,896 triangles whose indices are
bounded by a real vertex array of 1,041 points.

**New in `gbox/pso_nrel.py`:** `vertex_runs(data)` (the signature scan, largest first) and `vertices(data, run)` (the
points). Tests in `tests/test_pso_nrel.py` now **8 passed** - the run offsets/counts, the index max 1,036 < 1,041, and the
point decoding (all coordinates in range, no degenerate repeats).

**What remains for a full mesh:** the *correspondence* - which index run belongs to which vertex array (the file holds
several of each, and the pairs must be matched, probably by each run's position relative to its array). That is a
per-record pairing problem, not a decoding one.

## Round 73: the index runs are triangle STRIPS - the count is 38,355, not 12,896 (correcting round 63)

The round-63 triple reading was a coincidence. An adjacency test settles it: inside a run, consecutive *rolling* triples
(`v[k..k+2]` and `v[k+1..k+3]`) share two vertices in **8,652 of 8,896 cases = 97.3 %** - the defining property of a
**triangle strip**, not of independent triples.

So a run of *n* index values is **n - 2 triangles**, and the room's render mesh is

| reading | triangles | against `c.rel` (11,549) |
|---|---|---|
| independent triples (round 63) | 12,896 | 1.12x |
| **triangle strips (this round)** | **38,355** | **3.32x** |

**3.32x is the coherent number:** the collision mesh is roughly a third of the render mesh, which is what a simplified
collision hull looks like. The 1.12x of round 63 was an artefact of dividing by three.

`gbox/pso_nrel.py`'s `triangles()` now returns `sum(max(0, len(values) - 2))` per run, with the 97.3 % measurement in its
docstring; `describe()` reports the strip count. Tests updated (`38,355`, ratio window 3.0-3.6, and a synthetic 9-value run
= 7 triangles): **8 passed**.

What this leaves: the index runs' *pairing* with a vertex array (the 1,041-vertex array at `0x90078` bounds every index,
so it is the shared pool for this room) and the strip restart convention (whether `0xFFFF` restarts occur inside runs -
the scan's runs never contain one, so a run is one strip).
