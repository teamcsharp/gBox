# Two real bugs fixed in the box path, and the next one found

## Bug 1: the reticle catch-all was eating every box

The box branch sweeps three swings and rotates - **the only thing proven to break a container**. It was **never running**, because an earlier branch caught boxes first:

```python
if kind == "enemy" or kind == "object" or kind == "gate":     # containers are kind "object"
    ... actionables.append(...)                               # -> inside 12 units, this fires
```

A box within 12 units hit the **reticle catch-all**, which presses `b`+`a` **once** and moves on - one swing at one heading, exactly the pattern measured to destroy nothing. The sweeping branch below it
was unreachable. **That is why changing the distance threshold did nothing: the sweep was never being reached at any distance.**

Fixed: containers, capsules and traps are **excluded from the catch-all** so they fall through to the sweeping branch. Enemies, doors, keys, switches and barriers keep the single press, which is right
for them.

## Bug 2: the reach was outside the attack envelope

The loop swept from **14 units** and the successful test had the character at **7**. The game's own envelope is **~12 units** horizontal (`pso_coop_combat`), and the body blocks approach at ~16.7, so the
window where a swing connects is roughly **7-12 units** - **14 is outside it**. The enemy branch had the same flaw at **15.5**.

Fixed: boxes sweep only within **8 units**, enemies within **10** - both comfortably inside the envelope.

## And the next blocker, honestly

After both fixes the bot still destroys **0 of 59 containers**, and the log shows why: it is **not reaching them**. The window shows `closest approach 999.0` (no enemy either) and four unsticks freeing it by
**27.6, 63.5, 37.7 and 70.4 units** - it is moving, but not toward the boxes. The nearest box was **14 units** away at one sample and **79** at the next, so the approach is not converging: the
character wanders and gets wedged instead of closing.

**So the remaining bug is in the approach, not the attack.** The sweep and the range are now correct; what is missing is getting the character to stand next to a box. The `map_step()` route is supposed
to do that and is wired into the box approach - but the sample shows the character moving *away*, which suggests the route is returning `None` (target outside the safe set or the character off it) and
the fallback hill-climb is oscillating.

## What would settle it

Instrument the box approach the same way everything else was settled: log `bdist` each iteration alongside whether `map_step` returned a waypoint. Then it is visible whether the route is failing or the
hill-climb is, instead of inferring from an unchanged box count. **That is the next measurement, not another guess.**
