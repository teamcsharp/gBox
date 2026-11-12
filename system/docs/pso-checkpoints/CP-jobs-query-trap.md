# The `/api/jobs` trap, and the stuck worker

## The mistake I made twice

I kept concluding "the server is idle, 0 active jobs" from:

```python
S._call('/api/jobs')      # default
```

**The default query does not return queued or running jobs.** It returns the recent *completed* ones - 100 of them, newest first, all `succeeded` or
`failed`. So "0 active" was an artefact of the query, and I told the operator the launch was a stale client display when in fact **three jobs were queued and
never being processed**.

The launch bar uses the correct query:

```
GET /api/jobs?state=queued,running   ->  3 jobs: characters, characters, scan_library
GET /api/jobs                        ->  100 jobs, all older, newest session_op failed
```

That is the whole reason the launch sat at `state_transfer`: the worker had jobs it was not running, so a new launch queued behind them forever.

## The fix, applied

1. **Killed the two stuck `gbox` worker processes.** Nothing was running, so nothing was lost.
2. **They did not respawn**, so I started them: `python -m gbox --config ... serve` and `python -m gbox --config ... worker --server http://127.0.0.1:8765
   --name i9-NUC`. The CLI needs the subcommand and the worker needs `--server`; the earlier `gbox --config ...` line I had copied was truncated and
   failed with "the following arguments are required: cmd".
3. **Cancelled the three orphaned jobs** (`characters` ×2, `scan_library`) - they were queued against a worker that no longer existed and would never run.

Result: **queue 0**, **two workers online**, **health OK**.

## Pre-flight after the fix

```
OK  health
OK  a worker is online - 2 of 2
OK  cached image - Phantasy Star Online Episode I & II Plus (USA).gcz
OK  a memory card exists - 17 cards
OK  no live save state to restore
OK  BackgroundInput = True
OK  GCPad1 has a device line - Device = XInput/1/Gamepad
pre-flight clear - a launch has everything it needs
```

## The lesson, for the record

**Always query jobs with `?state=queued,running` when asking "is anything happening".** The default listing is a history, not a status. Two rounds of wrong
conclusions and a wrong message to the operator came from treating it as a status.
