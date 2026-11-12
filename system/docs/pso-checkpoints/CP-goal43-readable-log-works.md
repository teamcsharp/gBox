# The readable log works

## Confirmed on disk

The app restarted at 04:25:47 and `D:\gBox\pso-ds\app-console.log` immediately began filling:

```
10:25:48.831 [worker] {"event": "desktop-local-config", "installation": "...", "authority": "http://127.0.0.1:18765", ...}
10:25:48.923 [main:warn] (electron) 'console-message' arguments are deprecated ...
10:25:48.925 [webview:info] GBOX:{"ev":"padtakeover","sid":null,...}
10:25:53.119 [worker] ... DeprecationWarning: on_event is deprecated ...
10:25:57.024 [worker] gBox: temp files go to D:\gBox\cache\.gbox-redirected\tmp ...
```

**36 lines, 2.5 KB, three sources** - `[worker]`, `[main:warn]`, `[webview:info]` - which is exactly what was invisible before. Both additions are doing their
job: `logPush` writes every line it collects, and `teeChild` tees the worker's own stdout and stderr into the same file.

## What this unblocks

Every question that could not be answered tonight is now answerable by reading a file:

* **whether a virtual pad is created at launch** - the app's own `_p(50, ...)` message appears there when it declines, and the worker's output when it succeeds;
* why a launch stalls at a particular step;
* what the worker does with each job.

## The next launch is the test

**Launch PSO.** Then the file will contain the server's account of it, and the vpad question is settled by a line rather than by racing processes or guessing at
gates.

## State

| item | state |
|---|---|
| readable log | **working** - worker, main and webview all captured |
| app | restarted 04:25:47 with the patch |
| server | healthy, no sessions |
| bot | complete, 54 checks, waiting for a session |
