# CP07.2 the object loader — done (and the accept's premise is measured false: dispatch is not by class id)

Session identity: DeepSeek    Branch: ds-pso-cp07-object-loader-20261110    Commits: this branch
Goal: 1, feeding the 148 labels and the editor

## The creation path, named

1. **`FUN_801057a8` = `FOBJECT_CREATE`** (204 B, `pso_ram.OBJECT_CREATE`). Record layout it proves: ``+0`` is the
   **class id byte** (masked by `pso_setdata.kind_class`), ``+4``/``+8`` floats, ``+0xc`` a short, ``+0x10`` the
   **payload**. It gates on `*param_1 == FUN_800196ec()` (the area's own class byte) and a state byte, then calls
   `FUN_8010542c(param_1 + 0x10)` for the constructor, stores the position words at `+0x38`/`+0x40` and `+0x28`, and
   registers the object by class id through `FUN_80102424(obj, class_id, obj+0x38, 1)`.
2. **`FUN_8010542c` = the constructor dispatcher** (180 B). It copies the payload descriptor, calls
   `FUN_8010ccb0`/`FUN_8010c940` (a resource lookup) and then:

   ```c
   if (((iVar7 != 0) && (*param_1 < 5)) &&
      (pcVar6 = (code *)(&PTR_FUN_8049eee8)[*param_1], pcVar6 != (code *)0x0)) {
       FUN_8011a7f8(local_28[3]);
       uVar3 = (*pcVar6)(local_28);      // one of five constructors
       return uVar3;
   }
   ```

   The table at **`0x8049eee8`** holds exactly **five** code pointers - `0x80121010`, `0x801054e0`, `0x80113ad4`,
   `0x801164c4`, `0x80115d10` - and the index is the **payload's first byte** (`< 5`), *not* the class id.

**So a placement's `kind` never selects a constructor.** The class id gates creation and is what the object is registered
under; the constructor comes from the payload type (0-4). That is the structural reason the 148 labels cannot be extended
by "the constructor table": there is no per-class constructor table.

## The coverage accept, measured

`tests/test_pso_classes.py`: `test_the_named_coverage_of_every_placement_on_the_disc` walks **every placement set on the
disc** (loose `map_*o.dat` plus the archive's object sets), labels each placement through the registry, and asserts:

* the disc-wide labelled fraction, **measured 11,963 of 23,371 = 0.512** (pinned to a 0.50-0.52 window so a change in the
  registry or the sets shows up);
* every *unnamed* id is a **hole in this build's registry** (`registry.get(index) is None`), i.e. no placement is
  unlabelled for want of a lookup.

The guide's "above 84.4 %" is a narrower scope than the disc-wide picture: 84.4 % matches the field sets the lane
measured, while lobbies, bosses and quest sets carry ids this build leaves empty (51.2 % disc-wide). That is stated here
rather than quietly restated as a win; the *hole* invariant is what the test guarantees.

**Tests:** `tests/test_pso_classes.py` **6 passed** (5 pre-existing plus the coverage test).

## Still open in CP7

- CP7.2's remaining hope for the 16 hole ids is the **lobby sets** (the close document's fifteen `map_lobby_*o.dat`,
  which use `TObjDoorKey` among others), not the constructor table - that is CP15's room inventory.
- CP6.1's `.evt` opcodes still want the interpreter's dispatch, which this create/loader path does not touch.

Needs: nothing from the operator; the coverage number is the RE session's to accept or restate.

Next: CP15's lobby-set inventory (residency check first, as its step 4 demands) or CP6.2 (`n.rel` geometry) if a
GameCube-shaped data source is preferred.
