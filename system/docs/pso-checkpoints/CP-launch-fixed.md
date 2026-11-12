# The launch never worked: wrong tool name, and my guard was killing it

## Two faults, both proven by the log and by direct test

**1. The tool name.** The panel posted `{tool: '@launch'}`. The server answered:

```
pip add: launch failed 404 {"detail":"not found"}
```

`/api/jobs?tool=@launch` returns **401**, not 404 - so the route exists and the **tool name** was not found. The registered tool is **`launch_game`**, which takes
a full `CatalogEntry` in `input.game`. Tested directly:

```
job: 807bb5d815c34236 | tool: launch_game
  5: succeeded
live after: 1
VERDICT: a session started
```

**A real launch, from zero sessions to one running.**

**2. My orphan guard was cancelling launches.** The first test job reported `failed: cancelled by the operator` with no operator involved, and the guard's own log
names it:

```
orphan launch_game 647c333b9d has no worker - cancelled
```

`orphan_guard.py` cancelled **any** queued job with no `require_worker` - and a `launch_game` job from the panel legitimately has none. **The guard I wrote to
unblock launches was killing them**, which is worse than the stall it fixed.

It is now scoped to the exact thing that caused that stall: a **`characters`** job with no worker **and** empty inputs. Everything else is left alone.

## Also fixed in the same pass

**`recent 0` against `owned 12`.** The list resolved each session's `game_id` through the catalog page of 100, and those ids are not in it, so every entry was
skipped - which is why your last game never appeared. Both the strip and the dropdown now build their entries **from the sessions themselves** (which carry
`title`), and resolve the full `CatalogEntry` **on click** via `/api/catalog/<id>` - which always works for a game you have run.

## What this means for what you reported

* **"I keep loading PSO, but it's not loading"** - the tool name was wrong, and then the guard cancelled it. Both fixed; verified end to end.
* **"it's not showing that it's the last game that I loaded"** - the list required a catalog lookup that could not succeed. Fixed.

## Verified

```
picker node check:      OK
no '@launch' left:      True
guard scoped:           True
launch job:             succeeded, one session started
```

## Still to do

**The loading transition and focus** - your previous request. The app has `GBoxMercModeTransition` mounted as `#compact-transition`; the panel's launch should
raise it and switch the PiP to the new session. That is the next piece, and it is a UI change rather than a broken launch.
