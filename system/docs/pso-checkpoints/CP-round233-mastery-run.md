# Round 233: the unattended mastery run is assembled, and it refuses to fake a pass

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (fifth round without a session), so this is the pipeline, not a result.

## `mastery_run.py` - one command, evidence-producing stages

The PM contract asks for CP17 (walk to Forest 2), CP18 (Dragon's HP to 0) and CP19 (Episode I unattended). This assembles those into
stages that **write the evidence as they go**, so the report is a series of timestamped observations rather than a narration:

```
stage 1  verify the session
stage 2  start the observers
stage 3  CP17: run the certified route and watch for the FLOOR ID CHANGE
stage 4  CP18: warp to the Dragon, fight, record the boss HP series and every player's HP
stage 5  write mastery-report.json
```

## Stage 1 refuses to produce a meaningless result

```
session: {"running": false}
REFUSED: no running session
ready: False
```

It also refuses an **agent-owned** session, because that is the state this session spent four rounds in - the emulator accepts no input at
all, so any "pass" produced against it would be fiction. The refusal is the most valuable line in the file.

## Stage 3 is the CP17 accept test, literally

It plans to `(133,-48)`, walks the legs with the fast runner, and **after every leg** writes a row with the current floor id. The accept
signal is the row where `floor` differs from the starting floor:

```
{"event":"cp17_ACCEPT","from":1,"to":2}
```

No warp is used in that stage, because a warp is explicitly not acceptance. The floor series is `evidence/cp17-floor-series.jsonl`.

## Stage 4 is the CP18 accept test, with the co-op half included

`boss_warp dragon` (a dev shortcut, allowed for developing the fight), then `boss_both.py` records the boss's HP **and every player's HP**
each second while the bot attacks whenever the operator is off the pad. The accept condition is evaluated in the series: boss hp reaches 0
with both players alive.

## What is still missing is not code

Every stage exists, compiles, and refuses correctly. The blockage for CP17-CP19 is that **no game has been running for five rounds**, so no
stage has ever been allowed to execute. The moment an operator-owned session exists, `python mastery_run.py --all` either produces the two
accept rows or states precisely which condition failed.

## Files

* `mastery_run.py` - `--check`, `--cp17`, `--cp18`, `--all`; writes `evidence/*.jsonl` and `evidence/mastery-report.json`
