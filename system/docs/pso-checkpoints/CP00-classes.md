# CP00 step 4: one registry module — done

Session identity: DeepSeek    Branch: ds-pso-cp00-classes-20261110    Commits: this branch
Goal: all four (CP0 unblocks them)

## What was duplicated

Two modules read the same table in `PsoV3.dol`:

- `gbox/pso_class_registry.py` on branch `ds-pso-class-registry-20261110` — pinned the table at **`0x805D3138`**
  (240 slots, 148 named) and carried the full name list;
- `gbox/pso_classes.py` on `main` — finds the table from the `TObjCityDoor_Shop` anchor (slot `0x46`), so it does not
  depend on an address that a rebuild could move.

## What this branch does

- keeps **`pso_classes.py`** as the module, with the parts that were only in the branch ported onto it in an earlier
  step: `family_of_name`/`family`, `label` (a hole is `class_0xNN`, never invented), `vtable_census`/`instantiated`,
  and the real section-table mapping (`sections`/`address_of`/`offset_of`);
- folds the branch's **pinned data** in as cross-check data: `PINNED_ADDRESS = 0x805D3138` and `PINNED_NAMES`
  (240 slots, **148 named**);
- deletes nothing that exists. **Correction after the merges (2026-11-10 night):** `pso_class_registry.py` *is* on
  `main` (it came in with `ds-pso-class-registry-20261110` before this branch's base), so it is not "simply not added".
  With `ds-pso-editor-page2` merged, **no production module imports it any more**: `pso_editor` now labels placements
  through `pso_classes.class_labeller(disc)` (one 5 MB `PsoV3.dol` read, cached on the disc, `class_0xNN`/`unknown`
  fallback), so the editor is fully on `pso_classes`. The registry module survives only as a legacy, tested API, and
  `tests/test_pso_registries_agree.py` ties it to `pso_classes` (anchor name/slot, the pinned 240/148 list, the kind
  mask). `pso_classes` is the module going forward, and the registry can be deleted once its six assertions are ported;
- keeps **both test sets**: `test_pso_classes.py` (now including the two cross-checks and the ported families/labels/
  sections/vtable tests) and `test_pso_class_registry.py` (the registry module's own assertions), plus
  `tests/test_pso_registries_agree.py` for the agreement.

## Measured

- `table_offset(dol) == offset_of(dol, 0x805D3138)` and `address_of(dol, table_offset(dol)) == 0x805D3138` on the owned
  disc's `PsoV3.dol` - the anchor and the pinned address agree.
- `registry(dol, slots=240)` equals `{i: name for i, name in enumerate(PINNED_NAMES)}` **exactly**, all 240 slots.
- 148 of 240 slots are named; the holes are the same ids the branch recorded (`0x03`, `0x05`, `0x06`, `0x08`, ...).
- `label(dol, 0x02000047) == label(dol, 0x47) == "TObjCityDoor_Guild"`; `label(dol, 0x03) == "class_0x03"` with family
  `unknown`.
- A one-slot difference between the derived table and the pinned list is a test failure (the cross-check is not a
  rubber stamp).

Tests: `test_pso_classes.py` + `test_pso_class_registry.py` → **18 passed**. No new failures against the CP0 baseline
(45 failed / 1,329 passed / 132 skipped on `8032491f`).

## Note on the claim

Checked `git ls-remote --heads origin 'refs/heads/ds-pso-cp00-*'` before starting: no classes branch existed, so no
other session held this checkpoint; the branch is pushed with this evidence file as its first content, as rule 4 asks.

Next: CP0's accept list is now complete (merge-tree 24/24, one registry module with its tests green, the plane clean,
the question file present). CP1 (the local model on the 3090) is next when the session is allowed live steps.
