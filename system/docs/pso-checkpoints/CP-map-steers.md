# The internalised Forest map now steers the bot

## What was added

`map_step(pad, tx, tz)` - the next waypoint from the character toward a target, computed by **A\* over the 90,986 safe cells** decoded from `Scene/map_forest01c.rel`. The box approach now prefers it:

```python
step = map_step(pad, bx, bz)          # route on the internalised Forest map when it knows the way
if step and ...:
    side_toward = 1 if step[0] >= x else -1
    hold(pad, "left" if side_toward > 0 else "right", 0.16)
    hold(pad, "up", 0.7)
    map_steps += 1
else:
    <the existing hill-climb>
```

**Three properties make this safe to add:**

* it returns `None` when the map cannot help - **target in another room** (PSO maps are rooms joined by trigger geometry, so a cross-room route legitimately fails), or **the character off the safe set** - and the caller then keeps exactly the behaviour it had before;
* the router is loaded **once** and cached;
* a missing or corrupt `forest-maps.json` **disables the feature instead of breaking the loop** (`except` returns `None`).

## Why it should reduce the wedging, not just look nice

Every wedging episode in this session was the character **walking into geometry**: `wedged at (426,29,-18)`, `wedged at (294,15,-31)`, `wedged at (76,16,407)`. The blind approach is turn-a-bit, step, hope. A route over **safe cells** - walkable surface, 3x3 eroded, no upper/lower ambiguity within a cell - only asks the character to stand where the geometry says it can. If it works as intended, the relocation machinery becomes the rare fallback instead of the constant crutch.

## Verified so far, and the honest limit

```
[23:39:42] === cycle 1 ===
[23:39:44]   walk_through : succeeded
[23:39:50]   survival : succeeded
[23:39:50]   difficulty: Normal (already, hp_max 68)
[23:39:52]   floor_rares: succeeded
[23:39:53]   enemy_drops: succeeded
[23:39:54]   gates: floor 1: gates already open
[23:39:54]   operator is playing - bot standing down
```

**The loop builds and runs with the change, pyflakes is clean, and the map itself is proven** (A\* returned 41-waypoint, 109-112 unit routes on the real grid). What is **not** yet observed is `map_steps` incrementing in a live window, because the operator has the controller and the bot is correctly standing down.

## The two things queued for when the operator lets go

1. **`clean_relaunch.py`** - relaunch for a clean inventory so the three weapons equip (they still fail with *"Not enough inventory slots"* on this hours-old session). It refuses to act while the pause flag is fresh; it has declined twice already, which is the permission working.
2. **The first end-to-end proof** - a session with weapons where the **sweeping attack** lands and the **map-steered approach** keeps the character out of walls. That combination is the thing that has never been observed: **a kill the loop performed by itself, reached by a route it computed**.
