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
