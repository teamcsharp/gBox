# Mastery block status against the PM contract (CP17 / CP18 / CP19)

Measured 2026-11-11 ~14:20 CST. No game is running right now (the operator's app instance was closed so they could start an
operator-owned session), so nothing below is a live claim.

## The contract

| # | Requirement | Accept test |
|---|---|---|
| CP17 | Forest 1 -> Forest 2 **by walking the collision graph**, both players | **the floor id changes by walking, no warp** |
| CP18 | the Dragon defeated | **the boss's HP reaches 0 from RAM, both players alive** |
| CP19 | Episode I unattended with `pso_master_build` | (a full unattended run) |

## Where each one actually stands

**CP17 - route built, walk not performed. NOT MET.**
The pieces are real and measured: `psomap.collision` + `pso_floor_map` give 5,701 free cells on Forest 1 and 6,145 on Forest 2,
`nav_fast.plan` turns a cell route into 9-12 straight legs (149 raw waypoints -> 9), `run2` moves at a measured **27 units/s**, and the
operator's own demonstrations pin Forest 1's exits at **(133,-48)** and **(536,-566)** with a 10-leg / 999-unit route to the first.
But the walk has **never been executed end to end**, and the accept test needs the **floor id to change while walking** - which no run has
yet produced. Both players is also untested: everything this session was single-player.
Also relevant: the one time a floor change *was* observed live, it came from a warp (the operator's), which the contract explicitly refuses
as evidence.

**CP18 - Dragon fought by the operator, no RAM evidence captured. NOT MET.**
The operator reached floor 11 and fought the Dragon while `survival` (virtual Scape Doll), `crit_always` and `always_hit` were enabled, and
the entity table showed `TBoss1Dragon` alive during the fight. What is missing is exactly the accept test: **the boss's HP reaching 0 read
from RAM**, with both players alive. The fight happened without that capture, and the game has since been closed - so the evidence does not
exist and cannot be reconstructed.

**CP19 - not started. NOT MET.**
`pso_master_build` applied crit/always-hit/TP-max/5x-equip earlier in the session, but an unattended Episode I run needs both of the above
first.

## What is genuinely ready for the next attempt

* **navigation**: free-cell planner with string-pulled legs, floor-aware for forest 1 and 2, plus the learned exit routes from the
  operator's own play;
* **movement**: 27 units/s measured (8x the previous controller), stops the moment the operator touches the pad;
* **input**: `pso_input` is the only key path and it enforces the operator lock; the polite send path exists for docked windows;
* **memory**: `write_memory` / `freeze_memory` / `poke` all work on a session the running worker owns, with rollback receipts;
* **observation**: `learn_live` records position/HP/entities/damage every second, and `poi` accumulates warps, switches, doors and
  containers per floor - this is the machinery that would capture the CP18 HP evidence automatically if it were running during the fight.

## The one change that would make CP17/CP18 passable

The evidence has to be captured **while the event happens**, by the agents that already know where to look:

1. start the game **from the app** (operator-owned, controller works);
2. load the character, then run `learn_live` for the session, so every HP change and the boss's HP are recorded as they occur;
3. walk the learned 10-leg route to (133,-48) with `run2`, and record the **floor id transition** as the CP17 proof;
4. for CP18, read the Dragon's HP from the entity struct each second during the fight, and store the series that ends at 0.

Nobody has to trust a narration: each of those steps writes a timestamped series that either contains the transition or does not.
