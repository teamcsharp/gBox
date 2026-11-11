# Lane-log text of `ds-pso-body-platform-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `e1abfc4b`.

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
