# Lane-log text of `ds-pso-reconcile-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `d4398c44`.

----

## Reconciliation with main (2026-11-10, later still) — another session closed the PSO lane; here is what of mine still applies

While this session pushed the seventeen branches described above, **main moved on and a PSO close landed** (`befe7c3f`
"PSO close (round 60)", `8032491f` "gbox/pso_offset.py"): 138 PSO tests green across eighteen modules, the class
registry confirmed twice, an event-frame decode, a per-room offset solver, and a new hand-off addendum (the fifteen
`map_lobby_*` sets and the GUILD room). So several of my branches are now **duplicates of main** and must not be merged;
the rest are still additive. The honest map:

### Superseded by main - do not merge

| my branch | what main has instead |
|---|---|
| (local only, never pushed) `ds-pso-evt-format-20261110` | `system/gbox/pso_evt.py` on main - the same container decode (16-byte header `{16+20n, 0x10, n, 0}`, n x 20-byte records, script blob), independently reached, with tests. Mine round-tripped all 148 event files; theirs is the one to keep. **Deleted locally**, never pushed. |
| `ds-pso-class-registry-20261110` (mostly) | `system/gbox/pso_classes.py` + `test_pso_classes.py` on main derive the same table from an anchor (`TObjCityDoor_Shop` = slot 0x46) instead of a pinned address - a better design. Only two things in my module are still novel: `family()` (door/warp/switch/trap/sensor/sign/prop/decor/effects grouping) and the vtable census (`VTABLES`, `derive_vtables`, `verify_vtables`, the 38 instantiated classes and the correction that **no named placement class is a C++ object**). **Port those into `pso_classes.py`; do not add a second registry module.** |
| `ds-pso-floor-map-20261110` (partly) | main's `pso_offset.py` solves a room's local->world offset; the floor -> area/layout *name* resolver (`FUN_80207E88`, two 36-entry tables) is not on main, so that half is still additive. |

### Still additive - worth reviewing

* `ds-pso-steering-tests-20261110` (`5773d4be`) and `ds-pso-steer-tests2-20261110` (`275c0bdf`): the 9 red tests; unless
  main's close already fixed them, re-run them against current main before merging (they were green when pushed).
* `ds-pso-editor-page-20261110` (`262b117c`) and `ds-pso-swapfit-ui-20261110` (`e8ef1bb7`): P6b's page and the swap-fit
  gate - main's close explicitly says "P6b's page" is **not** claimed, so these are the novel UI work. They need a
  rebase: the page imports my `pso_class_registry`, which should become `pso_classes` + a small `family`/`label` helper.
* `ds-pso-floor-map` (the name resolver) and `ds-pso-floor-editor` (`.bss` record + `sets_for_floor`): no counterpart.
* `ds-pso-sda-20261110`, `ds-pso-memcard-20261110`, `ds-pso-actor-dump-20261110`: the small-data bases and global
  enumerator, the memory-card reader (and the finding that the lane's card has no PSO save data), and the one-call live
  actor dump - all still unique.
* `ds-pso-floor-warp-20261110` (`712f4a7f`): the dev `floor_warp` mods op - no counterpart.
* `ds-pso-travel-gate-20261110` / `ds-pso-vtables-20261110`: the travel-primitive and vtable notes (main's close says the
  same "no city event script exists", so these documents corroborate it).
* `ds-pso-gvr-write-20261110` (`e84af16c`), `ds-pso-tree-endian-20261110` (`8090217d`),
  `ds-pso-body-platform-20261110` (`e1abfc4b`), `ds-pso-swap-gc-20261110` (`8e967628`): the GVR writer, the big-endian
  tree proof, the platform-aware body helpers and `build_swap(platform="gc")` - main's close lists "P7a rigging" as
  **not** claimed, so this is the newest A8 work and still additive.
* `ds-pso-handover-20261110` (`448fbe45`): superseded by this note (keep this one, drop that branch).

**What I would do next, in order:** (1) port `family()` + the vtable census into `pso_classes.py` and rebase the page
branch onto `pso_classes`; (2) take the A8 stack (GVR writer -> tree proof -> body platform -> swap wiring) as one
series, since it is the only pre-P7a-rigging path and it is fully tested; (3) leave the duplicate event/registry/offset
work to main. Everything else in this lane now needs a live window, which the close document already states.
