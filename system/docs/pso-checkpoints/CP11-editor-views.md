# CP11 (editor page): the views test that main lacks

Session identity: DeepSeek    Branch: ds-pso-editor-views-20261110    Commits: this branch
Goal: 2

## What this branch is

`origin/main` already carries the editor page (`clients/web/pso-editor.html`), its API (`gbox/pso_editor_api.py`, with
`svg_of`/`routes`/`rom_for`) and a working `_mark_for`. What it does **not** have is a test for the page's two server-side views -
the SVG preview and the ASCII map - and those are exactly where the editor's bugs surfaced in this lane:

* `_mark_for` once used a bare `CLASS_NAMES` (NameError) and then `.get` on the registry's tuple (AttributeError);
* main's own version avoids both by testing `class_index == 0` directly, which is why this branch does **not** touch it.

So this branch is the missing **regression test**, forward-ported from `ds-pso-cp11-editor-page-20261110` and verified against
main's current code rather than rebased through the stale CP11 history:

`tests/test_pso_editor_views.py` - **4 passed** on main's `e3774109`:

1. the set list is available (**603** editable sets, and `map_ancient01_00_00o.dat` is one of them);
2. `svg_of` renders one `<circle>` per record (234 records -> 234 circles) and valid `<svg>` open/close tags;
3. `ascii_map` renders 27 rows and the city set shows **`G` and `S`** - the Guild and Shop doors - i.e. the door-to-glyph mapping a
   reader actually uses to orient in a room;
4. `_mark_for`'s fallback returns `o` for an unknown record.

**Why it is worth merging:** the editor's views are the part an operator reads (the preview and the text map), and main has no test
that would notice if either stopped rendering. This one exercises both against the real disc.

Tests: 4 new, green against main. No other file touched.
