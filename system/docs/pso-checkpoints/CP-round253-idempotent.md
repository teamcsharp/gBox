# Round 253: the editor self-test is idempotent

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (twenty-first round).

## The caveat from last round, fixed

Last round I recorded that each self-test run **appended a record** to the scratch file, so repeated runs grew it (10,200 -> 10,268 -> 10,336
-> ...). That made the test non-repeatable and the artefact ambiguous.

Now the test **clears the scratch file first**, so the accepted placement rebuilds it from the shipped original:

```
--- run 1 --- 11/11 checks passed
--- run 2 --- 11/11 checks passed
scratch size after both runs: 10268 bytes (151 records)
```

**The size is identical after two runs** - the test is idempotent, and the scratch file is always exactly "original + one placement" rather
than an ever-growing tail.

## Why that matters

An editor self-test that mutates its own fixture drifts: after ten runs nobody can say what the file should contain, and a real regression
looks the same as accumulated test state. Clearing first makes the expected state exact, so the last check - the structural validator against
the shipped original - is meaningful every time.

## State

* self-test: **11/11**, idempotent;
* CP3's second-model labelling: **44 of 82** and still running;
* no PSO session has run for twenty-one rounds.

## Files

* `editor_selftest.py` - clears its fixture, then runs the 11 checks
