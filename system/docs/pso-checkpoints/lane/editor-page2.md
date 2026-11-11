# Lane-log text of `ds-pso-editor-page2-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `061901c4`.

----

## Round 65 (2026-11-10, later still) — `family()` and the vtable census ported into main's `pso_classes.py` (reconciliation item 1)

Working locally; no lilspark, no live session.

Main's own registry module (`gbox/pso_classes.py`, anchor-calibrated from `TObjCityDoor_Shop` = slot 0x46) is the one to
keep, so this session's duplicated `pso_class_registry.py` is **not** being added. What was novel in it went into
`pso_classes.py` instead:

* **`family_of_name` / `family(dol, kind)`** - the grouping the editor page colours markers by: door, warp, switch, trap,
  sensor, sign, prop, decor, effects, collision, object (and `unknown` for an empty slot). Name-prefix derived, so an
  unseen class still lands somewhere sensible.
* **`label(dol, kind)`** - the class name, or `class_0xNN` for a slot this build leaves empty (never an invented name).
* **`vtable_census(dol)` / `instantiated(dol)`** - the class ids whose vtable header exists: a vtable starts with a
  pointer to its registry slot, so a word anywhere in the image equal to slot *i*'s address is class *i*'s vtable header
  (the registry array's own slots are excluded). Measured: **38 instantiated classes**, none of the named `TObj*`
  placement classes among them (doors, sensor, switch, the whole warp family) - i.e. the executable's C++ objects are
  engine classes, which is why the pad's handler cannot be found through a class vtable.

**And a mapping correction that matters beyond this step:** `pso_dol` documents a *flat* offset/address mapping (file
0x100 = image base, contiguous). That holds for the first two sections only - the real triples jump from file 0x2620
(address 0x8000F740) to file 0x426E00 (address 0x8000E520), so past 0x8000F740 the flat map is off by hundreds of
kilobytes and puts the class registry at 0x804FEB58 instead of its real **0x805D3138**. `pso_classes` now parses the
DOL's actual 18 `(offset, address, size)` triples (`sections`, `address_of`, `offset_of`) and the census uses them; the
census also skips the DOL header, which is not code or data. With the real table the census reproduces the Ghidra-side
finding exactly (38 classes, 0x804B4280 as the first vtable = file 0x4A8380).

Tests: `tests/test_pso_classes.py` gained five (family/label, the census finding a header and skipping the registry, the
section-table mapping, and the real disc asserting 38 classes and no named placement class among them): **10 passed**;
with the setdata/editor/offset/areas suites: **46 passed**.

The reconciliation's next item is the editor page: it must import `pso_classes` (plus these two helpers) instead of the
duplicated module when it is rebased onto current main.

## Round 66 (2026-11-10, later still) — the editor page rebased onto main and `pso_classes` (reconciliation item 2)

Working locally; no lilspark, no live session.

The page now lives on top of current main instead of the old tree, with no duplicate registry module:

* `pso_editor.placements` labels through **`pso_classes`**: `class_labeller(disc)` loads `PsoV3.dol` once, keeps the
  registry on the disc object, and returns `(name, family)` per `kind`; a disc without an executable (every synthetic
  test disc) falls back to `class_0xNN`/`unknown` instead of inventing a name or raising.
* `pso_editor_api` imports `pso_classes` (the doc line says so), and `server.py` gained the one registration line on
  current main.
* the page, its API and the build endpoint are unchanged otherwise (sets, placements, SVG preview, preview, build).

**Checked on the owned disc:** `map_city00_00o.dat` lists 28 placements with families `{effects: 7, prop: 11, unknown:
6, door: 4}`, the four door classes named (`TObjCityDoor_Guild/Med/Shop/Warp`), the SVG preview and `/pso/editor` both
200 - the same result the old branch produced, now through main's own module.

Tests: `test_pso_editor.py` (17, including a new real-disc case that the four city doors come out named with family
`door`), `test_pso_editor_api.py` (14), `test_pso_classes.py` (10), setdata and offset - **54 passed**.

This branch stacks `ds-pso-classes-family-20261110` (main + the ported `family`/`label`/vtable census), so it is the
complete P6b unit: registry helpers, backend, page, build endpoint and the swap-fit gate belong on this line.
