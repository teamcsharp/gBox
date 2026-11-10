# CP11 (P6b): the editor page, end to end

Session identity: DeepSeek    Branch: ds-pso-cp11-editor-page-20261110    Commits: this branch
Goal: 2

## State when this checkpoint was taken

The page and its build API are written and are carried by **`ds-pso-swapfit-ui-20261110`** (the P6b work landed through
`262b117c`, which is an ancestor of both that branch and `ds-pso-class-registry-20261110`; the originally named
`ds-pso-editor-page-20261110` no longer exists on origin, but **nothing was lost** - the commit is reachable from those two
branches).

`gbox/pso_editor_api.py` (212 lines) provides, over `gbox.pso_editor`:

| route | what it does |
|---|---|
| `GET /pso/editor` | the page itself (`clients/web/pso-editor.html`) |
| `GET /api/pso/editor/sets` | every editable set (**603 measured**) |
| `GET /api/pso/editor/set/{name}` | one set's placements, each labelled by the class registry with a family and, where the room-local -> world offset is measured, the world position |
| `GET /api/pso/editor/set/{name}/svg` | a **server-rendered** top-down preview (no browser needed to test it) |
| `POST /api/pso/editor/preview` | normalise + preview an edit set without building an image |
| `POST /api/pso/editor/build` | build a mod image (proven by a real disc build in `262b117c`) |

**Why it is not merged:** a merge changes `server.py`, so the i9 plane needs a restart, and the operator's rule is that
gBox is never restarted while a session runs (and never by this lane at all). So CP11's remaining steps are a merge/restart
decision, not code.

## Round 78: the page's own views proven offline, and two real bugs fixed in `pso_editor`

Both server-side views were exercised **without the server and without a restart**, by calling the module functions:

* **SVG preview**: `pso_editor_api.svg_of(pso_editor.placements(disc, "map_ancient01_00_00o.dat"))` renders a
  29,246-byte SVG with **234 `<circle>` elements for 234 records** (`docs/research/pso-editor-set-preview.svg`);
* **ASCII map**: 27 rows for the same set, with `*` spawn, `T` pedestal, `W/M/G/S` door marks - and on the city set
  (`map_city00_00o.dat`) the map shows **`G` (Guild) and `S` (Shop)**, matching the known `TObjCityDoor_Guild` /
  `TObjCityDoor_Shop` classes.

Exercising the ASCII map found **two bugs** in `pso_editor._mark_for`, both fixed on this branch:

1. it referenced a bare **`CLASS_NAMES`**, which the module never imported (`NameError`);
2. qualifying it (`REG.CLASS_NAMES`) then failed because the registry's `CLASS_NAMES` is a **tuple of 240 slots**, not a
   dict (`.get` -> `AttributeError`). The correct accessor is `REG.name(index)`, which bounds-checks and returns `None` for
   an unnamed/out-of-range slot.

**Tests:** `tests/test_pso_editor_views.py` **4 passed** - the 603-set list, the SVG (one circle per record), the ASCII map
with the city's `G`/`S` door marks, and `_mark_for`'s fallback.

## What CP11 still needs

1. the RE session's merge of `ds-pso-swapfit-ui-20261110` (or a cherry-pick of `262b117c` plus this branch's fix);
2. a plane restart at a moment with **no operator session** - explicitly not this lane's decision or action;
3. then the three steps from the document: open the page, pick Forest 1's set and drag a marker, build.

Tests: 4 new, all green; no other suite touched.
