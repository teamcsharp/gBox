# Round 199: 141 units from the door - the closest yet - and the drift that keeps pulling back

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1 (character returned to Pioneer 2 at the end)

## The best run of the night

The final integrated run (warp -> `B x2` -> boosted ATP -> flat route rebuilt from the live position -> walk, with kill-on-stall):

```
start (541.7, 447.5)
wp12 (439,438)  wp24 (397,522)  wp36 (297,544)  wp48 (221,501)  wp60 (194,410)
wp72 (193,277)  wp84 (252,211)  wp96 (260,118)  wp108 (236,108)  done (266,107)
```

**141 units from the key door** - the closest any run has come. It covered the whole 111-waypoint flat route in about 15 minutes
without a single terrain trap, which is the navigation problem confirmed solved.

## What pulled it back

1. **Drift**: `pso_kbwalk.walk_path` overshoots each waypoint by a few units; over 111 waypoints the accumulated error left the
   character 141 units off the goal, and the "rebuild a short route" step then walked it the wrong way (final 200 units, then the
   receding-horizon navigator regressed all the way to (535, 567)).
2. **The battle at 10 HP**: at several points a Booma engaged and the character could not finish a kill at 10/40 (measured
   repeatedly: strikes at 3-13 units with good alignment, enemy HP unchanged; HP hovering 10-20).
3. **Heal**: no quick heal exists - `stat` writes the shown stat only, warps do not restore, the item-menu cursor never moved, and a
   level-up (the one working heal) needs a kill.

## Where CP17 stands

- **Navigation: done.** Flat-only routing plus the calibrated walker crosses Forest 1 reliably (~600 units, twice, no traps).
- **The last 141 units: a fight and a heal problem.** The character is Lv 1 at 10/40 with 15/50 EXP; a single Booma kill would both
  clear the path and level it (full heal).

## Concrete next steps

1. **re-plan every few waypoints** (receding horizon) with the flat-route collision instead of the full grid, so drift cannot
   accumulate - the one navigator that converged (round 172) re-planned every round;
2. **raise max HP** so the fight is winnable: `pso_controls stat name=hp` cannot, but a level-up or an HP unit can - or take the
   death-and-revive (partial HP) and fight immediately after;
3. then the door: A once, push, and read `0x805D5FC0`.

Randomizer still running (cycles >15), CP18 done, both input paths fine with the `B x2` pad rule.
