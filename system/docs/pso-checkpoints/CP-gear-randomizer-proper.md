# The gear randomizer already exists in the plane — and so does the discard primitive

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: mastery / operator feature

## Two things the plane already had, which my external cycler reimplemented badly

**1. The primitive: `Extras.remove_generated(item_id)`** (`pso_gc_extras.py:138`)

```
def remove_generated(self,item_id):
  from .pso_gc_live import ID_BASE
  if not ID_BASE<=item_id<ID_BASE+0x100000: raise ValueError('Only gBox-generated equipment can be removed')
  ... self.call([(REMOVE,inv,p,self.ptr(node,32)),(0x801B63AC,p)]) ...
  if any(r['id']==item_id for r in self.inventory()): raise RuntimeError('Generated item removal was not acknowledged')
```

It removes exactly the kind of item the gear cycle creates (ids are `ID_BASE = 0x00F00000` and above), and it verifies the removal by
re-reading the inventory. Callers: `gameplay_demo.py`, `pso_master_build.py` and `pso_modes.py`.

**2. The feature: `pso_modes`, exposed as `pso_controls op=randomized`**

A session-owned equipment randomizer with the properties my cycler lacked:

- `interval` 5..300 s and `categories` (weapon / armor / shield / mag);
- it rolls **rare** items from the owned-disc catalog for the character's class (`pso_modes.tick`);
- **it removes the item it replaces** (`m.remove_generated(old)`) whenever the inventory is at 30, so the pack never grows;
- it tracks an *epoch* token in memory so a state load stops it safely instead of deleting the wrong item;
- `cleanup` restores the original equipment and removes every generated id it owned.

`ModsIn` already carries `interval` and `categories`, so the whole feature is one call away.

## The one blocker

`pso_modes.configure` refuses to start while the pack is full:

```
if len(m.inventory())>=30: raise ValueError('Free one inventory slot before starting Randomized')
```

and the pack is full *because* of the old cycler (its last attempt, 02:22:51, answered `"Not enough inventory slots"` on both items).
Freeing one slot needs the game's own Drop/Toss, and the menu's cursor will not move in my key path: **A works**, **R pages the right
panel** (technique stats, page 3/3), but neither a d-pad tap nor a main-stick hold moves the left-hand category cursor
(Item Pack / Equip / Items / MAG ...). The menu is reachable, the cursor is not - yet.

## Ways forward, cheapest first

1. **Operator does one Drop** (ten seconds in the item list) - then `op=randomized on=true interval=300 categories=["weapon","mag"]
   character_class="HUmar"` starts, and the plane manages the pack for the rest of the session.
2. **Find the cursor key** for that left column - the C-stick (keys K/I) is the untested candidate; the d-pad and the main stick both
   failed while A and R worked.
3. **Expose `remove_generated`** as an op (`op=discard {item_id}`) - needs a worker restart, so it costs the session.
