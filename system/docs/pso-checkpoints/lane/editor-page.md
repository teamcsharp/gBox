# Lane-log text of `ds-pso-editor-page-20261110` (moved here by CP0 from the shared lane log)

Tip before the rewrite: `262b117c`.

----

## Round 48 (2026-11-10, later session) — A3 solved: the object-class registry at `PsoV3.dol+0x805D3138`

Working locally on the i9; no lilspark, no live session, no service touched.

`docs/research/pso-gc-executable.md` §7.3 called this "the single highest-value decompile left for the editor": 315
`TObj*` names exist, and the table that maps a placement's class index (the low byte of its `kind`) to one of them was
not located. It is now located, pinned and verified.

**The table.** A flat array of class-name pointers in `.data` at **`0x805D3138`**, 4 bytes per slot, 240 slots, **148
named** in this build (the rest zero, plus one `0xFFFFFFFF` sentinel slot). `class_name(index)` is a plain
`cstr(table[index])`.

**How it was pinned.** The four room-10 door entities were walked live in rounds 22/29 and their kinds measured
(`0x46` Shop, `0x47` Guild, `0x48` Warp, `0x49` Med - `pso-gc-pioneer2-rooms.md`). Searching every 4-byte alignment
in the .data name-pointer sections for the one where those four indices land on exactly those four names gives this
base and stride **4/4**, and no other alignment in the search exceeds 1/4. That measurement is what makes the table
the registry rather than a coincidence.

**Coverage on the owned disc** (141 object-set files, 18,927 placements, 60 distinct class ids): it labels **44 ids,
15,975 placements (84.4%)** - `TORockCaveBL03` 7,438, `TOSensorAncient01` 4,436, `TOSymbolchatColli` 1,408,
`TObjAreaWarpForest` 308, the five city doors, the switches, the traps, the VS2 wrecks, the season objects - which is
what the editor's markers need ("door", "warp", "switch", "obstacle" rather than a number).

**The 16 holes** are real empty slots in this build: `0x05`, `0x06`, `0x08`, `0x0a`, `0x0c`, `0x0e`, `0x13`, `0x1e`,
`0x22`, `0x4b`, `0x61`, `0x67`, `0x74`, `0xc4`, `0xc5`, `0xc8` (`0x06` alone is 2,032 Ruins placements). The classes
exist - the sets spawn them - but their name slot is zero, so `label()` reports `class_0xNN` instead of inventing a
name. That is the honest half of A3: 84.4% labelled, the rest named by kind.

**Checked in:** `gbox/pso_class_registry.py` (the pinned table plus `name` / `label` / `class_index` / `index_of` /
`derive` / `verify`), `tools/verify_pso_classes.py <PsoV3.dol>` (**PASS** on the owned disc: 240 slots, all pinned
names match, doors correct), and `tests/test_pso_class_registry.py` (7): the four walked doors, the classes the editor
needs, holes reported not invented, the low-byte flag masking, a synthetic DOL in the executable's own layout, a
changed table reported instead of trusted, and an unmapped address raising instead of crashing. Registry + setdata +
areas + ram + editor suites: **45 passed**.

**For the editor / survey:** a placement can now be labelled offline from the disc alone:
`label(kind)` -> `TObjCityDoor_Guild`, `TOSwitchAttack`, `class_0x06`. The next natural step is the page (P6b's UI)
and the area survey's class histogram, both of which now have names.

## Round 49 (2026-11-10, later session) — P6b's page: the placement editor over the real disc

Working locally on the i9; no lilspark, no live session, no service touched.

The lane's own status said "P6b: backend done, no page". This is the page, built on A3's class registry (previous
round) so a marker reads as a class instead of a number.

**What exists now**

* `gbox/pso_editor_api.py` - the web layer:
  - `GET /pso/editor` - the page (`clients/web/pso-editor.html`);
  - `GET /api/pso/editor/sets` - every editable set (603 on the owned disc: loose `.dat` sets + the three set archives);
  - `GET /api/pso/editor/set/{name}` - one set's placements, each with the registry's **class name and family**, the
    local position, and (where the room-local -> world offset is measured, i.e. the Pioneer 2 lobby) the world
    position;
  - `GET /api/pso/editor/set/{name}/svg` - a **server-rendered** top-down SVG of the set: one dot per placement,
    coloured by family, doors and warps named, a family legend. Server-side so it is testable without a browser;
  - `POST /api/pso/editor/preview` - normalise + preview an edit set (delegates to `pso_editor.edits`/`preview`).
* `clients/web/pso-editor.html` - the page: the set list, the SVG preview, the record table (class, family, kind,
  x/y/z, world), a family filter, and a "preview move" form that posts an op and reports what would change without
  building an image.
* Registered in `server.py` beside `pso_api`.
* `pso_editor` now labels with `pso_class_registry.label()/family()` (the old placeholder map is gone), so every
  consumer of the backend - the CLI included - gets real class names.
* `pso_class_registry.family()` groups by name prefix: door, warp, switch, trap, sensor, sign, prop, decor, effects,
  collision, object (or unknown for the 16 empty slots).

**Checked against the real disc** (TestClient, `D:\gBox\cache` mods image):
* 603 sets listed; `map_city00_00o.dat`: 28 placements - `{effects: 7, prop: 11, unknown: 6, door: 4}`, with the four
  doors labelled `TObjCityDoor_Shop/Guild/Warp/Med`, world positions from the measured (+228, +291) offset
  (`TORockCaveBL02` at world `(229.0, 254.0)`), 28 circles in the SVG and the door names drawn on it; the page serves
  5.5 KB.

**Tests** (`tests/test_pso_editor_api.py`, 10): the page, the sets/placements labelling and family counts, the SVG as
a real image with markers and a legend, the family filter, world positions present/absent, an unknown set as a 404,
an empty edit set refused with 400, a preview reporting the change, and the renderer alone (z-up orientation, empty
set message). `pso_editor` + `pso_class_registry` + the API: **30 passed**.

**Not in the page:** the build. `pso_editor.build(cfg, game_id, rom, name, ops)` needs the rom/config the page does
not own, so building stays on the CLI (`python -m gbox.pso_editor build ...`); the page previews and reports the files
and edit counts. Wiring build into the page is the next step when the mods/rom selection for it is decided.

**Needs from the RE session (per the hand-off's restart rule):** pso_editor_api is a new module and server.py gained
its registration, so the page appears at /pso/editor only after a gbox.service restart at a gap. Nothing else in
this step needs a restart; the page reads the disc image directly (PSO_GC_ISO, or the cache's gc/mods image) and
never touches a live session.

### Round 49b (same session) — the page's build, proven on a real disc build

* `POST /api/pso/editor/build {name, ops}` builds a mod image through `pso_editor.build` (the writer's own
  `filemods.build_image` + post-build `verify`), with the mod name validated and the server's resolved rom. The page
  gained a "build mod" button beside the preview.
* **The CLI's `build` command had never run**: it used `pathlib.Path` without importing `pathlib`, so
  `python -m gbox.pso_editor <disc> build <name>` died with `NameError: pathlib` before doing anything. Fixed with the
  import (the new endpoint calls `pso_editor.build` directly, so it was unaffected).
* **Real build receipt** (the evidence this step needed):
  - op: `move` `map_city00_00o.dat` record 7 from `(4.997, 0.0, -61.997)` to `(120.5, 1.0, -40.5)`;
  - image: `D:\gBox\cache\mods\436e0bb84d5337d1\ds_editor_page_t1\Phantasy Star Online Episode I & II Plus (USA).iso`
    (1,459,978,240 bytes);
  - the build record: `files: [gsl_set_object.gsl]`, one edit, and `verification: {verified: true, failures: [],
    edits_checked: 1, records_per_set: {map_city00_00o.dat: 28}}` - the writer re-opened the built image and proved
    the move landed with nothing else changed.

Tests: `test_pso_editor_api.py` (14) + `test_pso_editor.py` + `test_pso_class_registry.py` = **34 passed**.

**Still open on A6 (the 0x8028f508 decompile):** the address is inside `FUN_8028f2a0` (1,024 bytes), instruction
`lfs f0,0x8(r4)`: the function blends three vectors read from `*(part+4)+8/+0xc/+0x10` for five parts into a
destination's transform, with parts located through a 0x28-byte table at `0x8051C110` and three indices from
`FUN_8028fb74`. The fault is a bad part pointer, so the crash is a **part-table mismatch**, not literally a material
lookup - `pso_swapfit`'s texture-bucket rule still predicts it from the two observations, and proving the
per-class part count from code needs the class table that feeds `FUN_8028fb74`. Recorded for the next P2b round
rather than claimed as solved.
