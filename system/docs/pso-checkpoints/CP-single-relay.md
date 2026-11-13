# One relay, a pause flag that expires, and the reticle rule firing

## The reticle rule works

```
[23:09:33]   acted on TItemEquipBase (6.9 units) - reticle rule
```

That is the operator's rule in action: **something actionable was within 12 units, so the bot pressed `b` then `a`** - enemies, objects and gates, with townsfolk excluded by class. It is not
following a list of distances any more; it is pressing at whatever is close enough for the game to act on.

## Three fixes, each for a fault observed rather than guessed

**1. Two relays were injecting every press twice.** Each `Start-Process` added another, and both read the same controller and posted the same events to the same session. `relay_singleton.py` now
holds a PID lock and refuses to start a second one - verified:

```
--- second launch attempt (should refuse) ---
another relay is already running (pid 39544) - exiting
```

Liveness is checked with `OpenProcess`/`GetExitCodeProcess` through `ctypes`, **not** `os.kill(pid, 0)`, because on Windows that call can terminate the process it asks about.

**2. The pause flag had no expiry.** The relay clears it after four idle seconds, which is correct - but if the relay dies or hangs with the flag set, the bot stands down **forever** with no recovery
except deleting the file by hand. The loop now ignores a flag older than `FLAG_STALE_S = 15.0` seconds. **A stale marker being trusted is exactly the failure class that has cost this session time**,
so it is worth the guard.

**3. `FLAG_STALE_S` was referenced before it was defined** - `pyflakes` caught it (`undefined name 'FLAG_STALE_S'`) before the loop ran, which is precisely why the linter is part of the workflow now.
An earlier edit had also replaced the `OPERATOR_PLAYING` path with the constant instead of adding to it; both are now present and correct:

```python
OPERATOR_PLAYING = pathlib.Path(r"D:\gBox\pso-ds\operator-playing.flag")
FLAG_STALE_S = 15.0
```

## The run after the fixes

```
[23:08:45]   walk_through : succeeded
[23:08:47]   give 009d00: succeeded      <- DARK FLOW
[23:08:48]   give 003200: succeeded      <- TSUMIKIRI J-SWORD
[23:08:50]   give 004400: succeeded      <- RED HANDGUN
[23:08:52]   survival : succeeded
[23:08:52]   difficulty: Normal (already, hp_max 68)
[23:08:53]   floor_rares: succeeded
[23:08:55]   enemy_drops: succeeded
[23:08:55]   gates: floor 1: gates already open
[23:08:55]   NOTE from operator: kill the wolves in this room
[23:08:55]   note internalized: prioritising enemies
[23:09:33]   acted on TItemEquipBase (6.9 units) - reticle rule
[23:09:57] unstick: left freed it (60.1 units)
[23:10:59] played 120s, 21.0 travel steps
```

**No stderr.** Every arming step succeeded, the note was read and classified, the reticle rule acted, and the unstuck freed the character three times (60.1, 30.8, 18.7 units).

## Operator state

The relay log shows the pad being used continuously - `relayed 5 event(s): ['up', 'down', 'left', 'right', 'up']` with `operator idle - bot may resume` between bursts - so the operator is driving
and the bot is yielding as designed.

## Still standing

* **UI text box** for notes: the file channel is proven, the control is not built.
* **Aggro switch**: needs the Ghidra read of the enemy AI; the entity struct has no field that flips on aggro.
* **Level-exit warp not reached** in an observed window yet; the recognition and approach code is in place and works when driven by hand.
* **Ultimate**: automatic at `hp_max >= 250`; currently 68, so Normal where the bot can actually kill.
