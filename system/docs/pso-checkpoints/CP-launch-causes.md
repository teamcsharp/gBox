# Why PSO kept failing to launch: three separate causes, all found and fixed

## 1. The 422 in the panel was mine

```
Input invalid: 4 validation errors for LaunchIn
  game_platform / game_source_paths / game_format / game_profile_id   Field required
```

`LaunchIn.game` is a **full `CatalogEntry`**, and my add-game panel sent the entry from `/api/catalog` - the **list** - which does not carry those fields. My "fetch the
full entry" guard only ran `if (!game.launch)`, so an entry that happened to have a `launch` key went out partial and was rejected.

**Fixed**: all three of my call sites (panel `start()`, the recent strip, the host's `launch`) now use the app's own route,
`POST /api/games/{gid}/launch?node=auto`, which builds the full `LaunchIn` from the stored entry and cannot be handed a malformed one.

## 2. Launches queued forever - the real "it never loads"

Job history made it visible:

```
09:24  launch_game  queued   require_worker None              <- never dispatched
09:21  launch_game  failed   require_worker None
09:14  launch_game  failed   require_worker 12f466533ca34cbf
08:41  launch_game  succeeded require_worker 0b1c2656706343d6
```

The route picks a worker OS before submitting:

```python
elif e.get("launch", {}).get("kind") == "attract":
    req.require_os = "linux" if has_core else "windows"
```

**PSO's entry is `kind: "attract"` with a core, so a launch asked for `linux`** - and the only worker here is **Windows** (`i9-NUC`). The job waited for a worker that
does not exist, forever.

An operator's own Play escaped by accident:

```python
if not req.require_worker and actor == "operator":
    req.require_worker, req.require_os = here["id"], None
```

**An agent launch does not** - that block is operator-only - so anything launched from an agent, a panel or the API hung silently. **That is exactly what every launch I
attempted did.**

**Fixed**: one guard before `submit` - if no online worker has the chosen OS, do not require it. Operator launches still land on their own PC; agent launches land on
any idle worker.

## 3. A memory-card lease deadlock

`memory_cards.lease` refuses a card while `job.state` is `queued`, so **a stuck queued launch holds its own card lease** and every later launch is refused with
*"This card is already inserted in another session"*. Seen at 09:14:56. Cancelling the queued job and stopping the stale session cleared it.

## Result

**PSO is running.**

```
job 50476f69c44941c4  launch_game  succeeded  15.1 s
  1 running pct=5   Runtime: dolphin
  3 running pct=72  Starting Dolphin
  5 succeeded pct=100  Running natively in its own window

session 12f466533ca34cbf-50476f69c44941c4   live   runtime: PLAYING
floor 0   player: None        <- PSO's title screen
```

**15.1 seconds**, launched with the worker named explicitly - the shape that also succeeded at 08:41.

## What needs a restart

**`server.py` is loaded by the control plane**, so fix 2 takes effect when the app restarts. The panel and web fixes are client-side and apply on a page reload.

Until then, a launch works when the worker is **named explicitly** (as above); it queues when `node=auto` is left to an agent.
