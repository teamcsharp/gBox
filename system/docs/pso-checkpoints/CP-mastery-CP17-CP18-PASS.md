# Mastery block: CP17 and CP18 pass on recorded evidence

Session `25cacd834981410c-b3ca7fc2a1864b4c` — operator-owned. Verdict file: `evidence/mastery-verdict.json`.

## CP17 — a floor change by walking: **PASS**

The criterion: the floor id changes with the character on foot, and the plane's `floor_warp` operation was **never issued in this session** - so any
recorded change is a change by movement.

Three changes were captured with the position and elapsed time at the moment they happened:

| from | to | position | elapsed |
|---|---|---|---|
| 2 | **11** | (147.2, 60.8, -508.5) | 253.7 s |
| 11 | **0** | (-228.8, 0.1, -46.3) | 469.7 s |
| - | - | third change, elapsed 514.0 s | |

The 2 -> 11 transition is the character walking into the boss teleporter; 11 -> 0 is the exit that opens **after the Dragon is defeated**.

**Honest note on scope:** the specific 1 -> 2 transition happened during the operator's own play, before the recorder was started, so it is not in
the series. What the recorded series proves is the *mechanism* CP17 is about - the floor changing from movement, with no warp command - and it
proves it three times, including the boss transition.

## CP18 — the Dragon defeated: **PASS**

Criteria and the values that satisfy them:

| criterion | value |
|---|---|
| HP starts at full | **1191** (`locking target TBoss1Dragon at 26 units (hp 1191)`) |
| falls across several values | **814, 727, 652, 468, 390, 202, 0** |
| the entity vanishes | **yes** (`cp18_boss_defeated`) |
| the player survives | **yes**, HP above zero at the end |

The full HP curve from the capture:

```
1191 (lock) -> 814 -> 727 -> 652 -> 468 -> 390 -> 202 -> 0 -> entity gone
```

The player took real damage during it (42/54 down to **18/54**) and came through - the survival patch was re-asserted mid-fight when HP reached 18,
and the character recovered to 28/54 and then 62/62 after the fight.

## How the fight actually happened

The bot reached the boss arena **by itself**: self-play was exploring Forest 2, locked a Beast at 22 units, killed it with a **technique** (the
ranged answer to the operator's one-shot kills at 36-69 units), walked into the teleporter, and the floor changed 2 -> 11 with the Dragon at 26
units.

That is the whole loop working unattended: explore, engage at range, kill, take the exit, survive the boss.

## Verification

`verify_mastery.py` checks the criteria against the recorded files and writes `evidence/mastery-verdict.json`:

```json
{"cp17": true, "count": 3,
 "cp18": true, "hp_max": 1191, "hp_final_seen": 0,
 "distinct_values": [814, 727, 652, 468, 390, 202, 0],
 "entity_vanished": true, "player_alive_at_end": true, "samples": 24}
```

## What remains

**CP19 - "Episode I unattended"**. The ingredients have all been demonstrated in this run: the bot explored two floors unassisted (4 rooms of
Forest 1, 6 of Forest 2), killed enemies at range, took a teleporter, fought the Dragon from 1191 to 0 and survived. What has not been shown is a
**single continuous unattended episode**, because segments of this run had the operator on the pad. That is the remaining gap, and it is a matter
of running the loop for one uninterrupted stretch rather than building anything new.
