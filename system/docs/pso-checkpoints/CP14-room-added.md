# CP14 (P6c): one room added

Session identity: DeepSeek    Branch: ds-pso-cp14-room-added-20261110    Commits: this branch
Goal: 2

## What the checkpoint asks

> **Steps:** 1. Using CP8's room pieces, duplicate one Forest 1 room piece, joined to an existing door. 2. Collision included.
> 3. Build, and load it with CP5's warp.
> **If blocked:** first expand by adding records (objects and enemies), which the writer already does, and record it as
> "expansion by placements only".

## Round 122: the placements-only expansion, built and validated against CP8's room footprint

The room-geometry duplication is blocked twice over: Forest 1's room pieces are **Dreamcast-side** (no GC `r.rel` for Forest 1,
CP7.3), and the DC image is a CHD v4 no tool here can read (CP8). So this branch takes the fallback route the guide names - and
does it with a **measured position** instead of a guessed one, using CP8's room quad as the target.

**What was done** (`docs/research/pso-cp14-add-placement.py`):

1. read `Scene/map_aancient01_00r.rel` with `pso_rooms.room_quad` - a **200 x 300** footprint at origin `(0, 0, 0)`;
2. read the set `map_ancient01_00_00o.dat` - **234** records; the first record's **kind `0x8`** and `y` become the template, so
   the added record is constructible (CP7.2: the payload type selects the constructor, and a copied kind guarantees one);
3. place one record at the footprint's **centre** `(0, 0, 0)`;
4. validate through **`pso_editor.preview`** (the operator's own path):
   `{"ok": true, "edits": 1, "changes": {"gsl_set_object.gsl": 1683456}, "expect": [{"set": "map_ancient01_00_00o.dat", "index": 234, "x": 0.0, "y": 0.0, "z": 0.0, "op": "add"}]}`;
5. apply the same change with `pso_map_write.add_placement_change` and read the records back.

**Measured result:** records **234 -> 235**, the new record is **inside the room's footprint**, and **every original record is
byte-identical** (`after[:234] == before`). That is the expansion the checkpoint asks for, with the "does it load / stand on it /
can the walker reach it" lines still needing CP5's warp in a live session.

**Tests:** `tests/test_pso_cp14_expansion.py` **3 passed** (the add lands inside the room and keeps the others; the editor's
preview accepts the same op; the copied kind is a real placement's), and together with CP8's `test_pso_rooms.py` **9 passed**.

## What remains for CP14's accept

| accept line | state |
|---|---|
| the area loads without a crash | needs the live window (CP5's warp + the built image) |
| the player stands on the new piece (a stable `y` in RAM) | needs the live window: place the record where the room's floor is, then read `pso_ram.position` twice |
| the walker's position can reach it | CP17's walker (`pso_walk` route + `pso_steer` taps) plus the live window |

**Branch note:** this branch is **stacked on `ds-pso-cp08-room-pieces-20261110`** because it uses `pso_rooms.room_quad`; review
CP8 first.
