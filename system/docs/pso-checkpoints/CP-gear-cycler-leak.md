# The gear cycler leaks two inventory slots per cycle — paused, with the fix named

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: mastery / operator feature

## The bug

The five-minute random-gear cycle calls `pso_controls op=equip` for a weapon and a mag. That operation is **give + equip**: it creates
a *new* item in the inventory and equips it. The previous weapon and mag are **not removed** - they stay in the pack. One cycle
therefore costs two slots, forever.

Measured consequence: `pso_controls op=give {"code": "010100"}` now answers
`{"detail": "ValueError: Not enough inventory slots"}`, and there is no room for a healing item - which is why the character sits at
HP 6/54 in Pioneer 2 with a full pack.

## Why the obvious fix is not available

`pso_loadouts op=drop` is **not** a discard: it resolves item *codes* and calls `pso_controls op=floor_spawn`, i.e. it **spawns items
on the ground** (pso_loadouts.py:215-224). There is no operation anywhere in the plane that removes an item from the inventory, and
no item-code writer either: `pso_gc_inventory` only reads (`inventory()`), and `pso_gc_live` only creates (`F_CREATE`).

## What the fix should be

The operator asked for *"replace the weapon that's in my inventory"*, and the honest implementation of that is **rewrite the equipped
item's code in place**, so the pack never grows. Second best is a true `discard` op (zero the slot). Either way it is a new operation
in the inventory layer, and it belongs next to `mag_set` (which already rewrites the equipped mag's properties at `+0x198` and is
proven).

Until then the cycle is **paused** (`job pwsh-d66c797b97af49d8` killed) so the pack stops filling. The two stale watchers bound to
ended sessions were stopped at the same time.

## State

Character BQF, **Lv 3, 371 EXP**, in Pioneer 2 (floor 0), HP 6/54, `survival` on, menus closed, inventory full (weapons and mags from
the cycle). Healing needs either the hospital walk (`TObjCityDoor_Med` at `(193.5, -93.5)`, then a `TObjNpcNurseBase`) or a working
discard to free a slot for a mate.
