# Round 225: the boss fight is armed, and the speedrun shortcuts are found

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d` - the operator is on **floor 11, the Dragon arena**

## Assists enabled for the fight

```
survival    {"permanent_scape": true, "note": "Virtual Scape Doll: native revival on death, no inventory slot or consumable required"}
crit        {"crit_always": true, "scope": "every melee hit by a local player is a critical; enemies unchanged"}
always_hit  {"always_hit": true, "scope": "local offline player accuracy rolls; targets must still be in range and hittable"}
```

Infinite Scape Dolls with native revival on death, always-critical melee, always-hit accuracy. The Dragon cannot kill the player and cannot
survive long.

## The speedrun shortcuts in the plane

`pso_live.OPS` carries two travel ops that were never used in this session:

* **`floor_warp target=<floor>`** - the native SET_TARGET / BEGIN_TRAVEL / WARP path, exposed for the editor and the area survey. It is
  **labelled "reached by warp (dev)" in any evidence it produces and explicitly never counts for P1/P3/P5 acceptance**, but it works.
* **`boss_warp target=<id>`** - loads a boss area directly.
* **`bosses`** - lists the destinations for the current episode:

```
episode 1, default dragon:
  dragon      Dragon / Sil Dragon         floor 11
  de_rol_le   De Rol Le / Dal Ra Lie      floor 12
  vol_opt     Vol Opt                     floor 13
  dark_falz   Dark Falz                   floor 14
```

The operator is already on floor 11, which is where `TObjWarpBossMulti (155,-501)` - the warp the learner found in Forest 2 - leads.

## Why this matters for the PM's CP17/CP18/CP19

* CP18 (Dragon defeated) is happening now, with the assists above;
* CP19 (Episode I unattended) becomes reachable through `boss_warp` between fights, with the caveat that a warp-reached run is **dev-labelled
  and does not count as P1 acceptance** - so a walk-reached run still needs the learned route to (133,-48) executed on Forest 1;
* CP17's walking requirement is unchanged: `floor_warp` can *reach* Forest 1, but the exit must be walked to.

## State

Operator on the controller throughout, so no input was sent. Assists applied through `pso_controls` (not the pad). Player HP 27.
