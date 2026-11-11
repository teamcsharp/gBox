# Lane-log text of `ds-pso-tree-endian-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `8090217d`.

----

### Round 61 (2026-11-10, later session) — A8's tree half verified on a real body, so both halves are now proven

Working locally; no lilspark, no live session.

`ninja.write_tree` already takes an endianness parameter (`e="<"` Dreamcast, `e=">"` GameCube), but nothing had ever
verified that the big-endian path produces a tree the game's own parser reads back. Now it does - on a real body:

* **`pso_gc.player_body_nj(disc, "A")`** (the HUmar body, 21,308 bytes) splits into a 21,168-byte NJCM payload and a
  132-byte POF0 tail; `tree_nodes(payload, 0, ">")` yields **64 nodes** (flags 7, model offset 3,572 for the root),
  and every node's model header (two pointers, centre xyz, radius) unpacks coherently.
* **Writing that tree back** with `write_tree(nodes, models, 0, ">")` and parsing it again gives **every node
  identical** - flags, child/sibling links, the 36-byte `trs` block, the model centre/radius, and the vertex-list bytes
  themselves - across all 64 nodes. So the writer's big-endian layout is the game's layout, not an approximation.

A byte-for-byte reproduction of the original payload is deliberately *not* the invariant: `write_tree` lays the model
blocks out itself (after the node array, in node order), so a writer-produced payload reorders them while the tree and
every pointed-to chunk stay identical. That is what a swap needs.

**Tests** (`tests/test_ninja_endian.py`, 4): a synthetic tree round-trips in **both** endiannesses (flags, `trs`,
child/sibling, model header floats, the vlist/plist bytes at the reported pointers); the pointer fields the writer fills
are all inside the output and `pof0` encodes them (`POF0` magic, non-trivial table); and the real disc body's 64-node
round trip above.

**Where A8 stands now:** both halves are proven against real data - textures (`gvr_write` RGBA8 exact, CMPR mean error
0.1 on a disc texture) and the tree (this round). The remaining work is the *wiring*, and it needs a platform split in
`pso_player.build_swap` (the function is the Dreamcast path today: little-endian reads, `pvr_like`, `PSO/PL...` names).
The plan is a `platform="gc"` argument that switches those four call sites (read/tree endianness, the texture writer, the
BML entry names) with the Dreamcast behaviour unchanged, then `pso_swapfit.compare` gates a build before any boot.
