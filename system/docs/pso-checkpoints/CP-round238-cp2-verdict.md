# Round 238: CP2 measured with the real gold set - plausible roles, no exact names, so the fallback clause applies

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
No game running (ninth round).

## The gold set is not FUN_ names

`decompiles.json` names most functions `FUN_<address>`, so scoring names against it is meaningless - that is why the earlier qwen runs read
as 1/30 while the harness was fine. The real gold is section 3 of `pso-gc-executable.md`, where each address carries an identity **proven by a
byte-exact guard**:

```
8000c040  the DOL entry point        801b9f40  F_EQUIP
8000f998  BEGIN_TRAVEL               801b9d50  F_UNEQUIP
801057a8  F_CREATE                   801b8310  F_INVENTORY
80103748  F_DELETE                   801bab1c  WARP
80154764  FENCE DROP                 80228540  SET_TARGET
80154788  FENCE RAISE                ... 17 proven rows
```

The extractor parses that table, and **all of them are covered** by the decompiles file, so the model can be scored against proven identities.

## The reasoning-model bug, and the fix

The first full run scored **30/30 wrong at 9.49 s/function** with every name empty: `deepseek-r1` spends its output on the reasoning
preamble, and `num_predict: 300` was exhausted before the JSON appeared. With a **1500-token budget** and the answer taken from the **last**
JSON object, it answers normally (reply lengths 2-4 KB).

## What it actually produces

```
8000c040  gold "the DOL entry point"      model INITIALIZE_GAME_STATE
8000f998  gold BEGIN_TRAVEL               model SET_FLAG
8001e5c8  gold the primitive pso_coop...  model GET_FUNCTION_VALUE
800791bc  gold the floor-height query     model (ran out of budget)
```

**23.9 s per function.** The names are *plausible* - `SET_FLAG` for the routine that sets the area-load request flag, `INITIALIZE_GAME_STATE`
for the entry point - but they are **not the proven names**, and my token scorer correctly refuses to count them.

## The verdict CP2 asks for

The checkpoint's own fallback: *"below about 50 % on roles, keep the model only for summaries and candidate lists. No name it proposes
enters `pso_ram.py` without a decompile or live proof"*.

That is the result. With a 14 B model at ~24 s/function producing sensible-but-unproven names, **the model is useful for triage and
neighbourhood summaries, not for naming**. Which also means CP3 (bulk labelling) should be scoped to *candidate lists for review*, not to
accepted labels - the throughput is real, the authority is not.

## Files

* `cp2_gold.py` - the gold-table extractor and scorer against proven identities
* `cp2_fix.py` - the reasoning-budget fix and the 4-function probe (`llm/gold34-deepseek-r1-14b-probe.json`)
* `cp2_run.py` - the first full run that exposed the empty-answer bug (`llm/gold34-deepseek-r1-14b.json`, 30 rows, all "wrong" for that
  reason only)
