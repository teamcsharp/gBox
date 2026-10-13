# Sonic showcase

A background service on the control plane (the Spark) that keeps a **test version** of the operator's favorite and
recently played titles with their key people replaced by the **Sonic Adventure 1 + 2 cast** (`source=sonic`), and
pushes every title gBox can't write yet into Hermes's readiness queue so the Ghidra / REA work on it proceeds.

Code: `gbox/sonic_showcase.py` (service, API), `gbox/cast_swap.py` (`mod_name=`, `showcase=`, `plan_digest`,
`link_tree`), `gbox/hermes_work_queue.py` (`ensure_item`, `item_state`), `gbox/built_mods.py` (the Mods page
filter), `clients/web/viz/mods-gallery.js`, `clients/web/viz/game-menu.js` (Special builds),
`clients/desktop/index.html` (Settings card). Tests: `tests/test_sonic_showcase.py`.

## Turning it on

* gBox app: **Settings > Sonic showcase**, tick *Build Sonic showcase versions in the background*. The card shows
  the phase, the current title and stage, disk used vs the budget, builds this hour, the queue and the last results;
  *Paused* stops new work, *Run a pass now* starts one immediately.
* API: `PUT /api/showcase {"enabled": true}` (POST works the same for clients without PUT).
* gbox.toml (default for a fresh data dir; the Settings card's saved values win):

```toml
[showcase]
enabled = false              # off until turned on
paused = false
favorites = 25               # favorites per pass (starred titles first)
recent = 10                  # then this many recently played titles
budget_gb = 50               # disk cap for showcase builds (LRU eviction of showcase builds only)
builds_per_hour = 3
whole_cast_max_slots = 16    # whole cast when it has at most this many slots, else player + main cast
interval_s = 300
recheck_hours = 6            # an up-to-date title is planned again after this long
retry_failed_hours = 24      # a failed plan is not retried before this unless the plan changes
hdd_root = { linux = "/home/ehm_eckx/samples" }   # builds only when the mod cache is under this mount
require_hdd = true
min_free_gb = 50
dedupe = true
dedupe_min_mb = 4
pause_while_playing_anywhere = false   # true: also wait while a game runs on a Windows PC
```

`hdd_root`, `require_hdd`, `min_free_gb`, `recheck_hours`, `retry_failed_hours` and `dedupe_min_mb` are
gbox.toml-only (the API refuses them), so a client can't point builds at the NVMe.

## What a pass does

Every `interval_s` (or at once after a settings change / `POST /api/showcase/run`), one pass:

1. **Gate.** Nothing new starts while the operator plays on the Spark (a running session on the Linux worker: the
   deploy cron's session rule from `gbox.hermes_activation.idle_reason`, "Waiting for the Spark game session to
   finish."), while a launch (`launch_game`, `session_swap`) is queued or running anywhere (it stages the disc on the
   same HDD), while paused, or when disabled. A session on an unknown worker counts as the Spark's. If the gate
   closes while the showcase's own job is **queued**, the job is dropped (record stage `deferred`, not counted
   against the rate); if it is **running**, it is asked to stop (`cancel`), and the title is planned again later.
2. **Titles.** Favorites in the catalog first (most recently played first, then most recently starred), then
   recently played titles that are not favorites; `favorites` / `recent` cap each list. Sonic Adventure 1 / 2
   themselves are skipped (`donor_game`).
3. **Title with a routed writer** (`char_coverage.writer_for(...).routed`):
   * **Donors.** The SA1 / SA2 entries must be in the collection. A missing one gets a `characters op=collect` job
     on the Spark for that disc (one job at a time; the pass waits for it). A donor game that collected nothing, or
     isn't in the catalog, is noted and the build goes ahead with the donors there are.
   * **Slots.** The whole cast when the writer lists at most `whole_cast_max_slots` usable slots, else
     `slots=main` (player + fighters / drivers / cast members), else the player and the first slots up to the cap.
     One-slot writers build the player only (the cast-swap planner's rule).
   * **Plan.** `cast_swap.plan(game, collection, source="sonic", mapping="auto", seed="showcase")` on the control
     plane. Its hash (`cast_swap.plan_digest`: which donor on which slot - the same digest `cast_<...>_<digest>` mods
     carry) is compared with the build on disk: an unchanged plan is **never rebuilt** (stage `unchanged`); a plan
     whose build was evicted for the budget isn't rebuilt either until the plan changes; a plan that failed waits
     `retry_failed_hours`.
   * **Budget.** The next build's size (the title's last build, else the median showcase build, else 2 GB) must fit
     `budget_gb`; older showcase builds are evicted first (see below). If it can't fit: stage `over_budget`.
   * **Build.** One job:
     `characters op=cast_swap target_game=<id> source=sonic mapping=auto seed=showcase slots=<spec>
     assignments=<the plan> mod_name=showcase_sonic_<title> showcase=true launch=false`, `require_os=linux`,
     `low_priority=true` (workers claim it after every other queued job). It never launches a game. The cast-swap
     build writes the plan hash (`cast_plan`) and a `showcase` record into the mod's marker and, for a showcase,
     posts no Play-as character targets (an evicted test build leaves nothing pointing at a missing folder). Writers
     that name their own build (the DOA2 roster, one-slot `characters op=use` writers) keep it under that name; the
     showcase folder is a hard-linked copy (`cast_swap.link_tree`, no extra bytes).
   * At most one build per pass, `builds_per_hour` per rolling hour.
4. **Title without a writer:** `hermes_work_queue.ensure_item` puts it in the readiness queue's favorite lane with
   the assimilate fingerprint attached (`assimilate.ticket_fingerprint`; at most two titles per pass, each at most
   every `recheck_hours`). A favorite is already there; a recently played one is added with `showcase: true`, which
   `candidates()` admits and `choose()` ranks after the starred favorites. Hermes then works inventory -> analysis
   (Ghidra / REA) -> reader -> writer -> runtime as for any favorite; stages and tickets are never reset. The record
   lists what is missing: the writer (none / not routed), the dedicated model reader, the capability backlog's first
   tasks and the readiness queue's next stage. While Hermes's own tick holds the queue lock the title is retried on
   the next pass (`readiness_pending`).
5. **Result.** When the job ends the record gets the stage (`built` / `failed` / `deferred`), the mod, build time,
   the slots replaced (per-slot status and reason), and preview pictures from the job's fitting record
   (`gbox.fit_events`: each slot's fitted preview / snapshot, with the donor's collection preview). The previews and
   the slot report also go into the build's marker, so the Mods page shows them.

## Disk: the HDD only, a budget, LRU eviction, dedupe

* Builds go to `<cache>/mods/<game_id>/showcase_sonic_<title>/` - the writers' usual place. The service refuses to
  build (`waiting_storage`) unless the mod cache resolves under `hdd_root` (the Elements HDD at
  `/home/ehm_eckx/samples`), that path is a mount point, and at least `min_free_gb` is free. It never fills the NVMe.
* **Usage** counts the bytes only showcase builds hold: a file whose every hard link is inside showcase builds
  counts once; a file linked to a base copy or another mod costs nothing (deleting the showcase frees nothing).
* **Eviction** deletes least-recently-used showcase builds (by build time or the newest session that played them)
  until the next build fits. Only folders named `showcase_sonic_*` whose marker carries the `showcase` record are
  candidates - never another mod, never the operator's files, never a build a running game uses, never one the
  operator saved a mod card for, never the build being made. The deleted folder's auto-registered gallery card goes
  with it; the title's record says `evicted`. Every eviction is in the audit log (`showcase.evict`).
* **Dedupe**: after a build, each file of at least `dedupe_min_mb` that is byte-identical (size, then SHA-256) to a
  file of the game's base copy (`<cache>/modbase/<game_id>`), its unpacked disc (`<cache>/dc/<game_id>`) or another
  showcase build on the same disk is replaced by a hard link to it (`os.link` + `os.replace`, inside the new build
  only; the marker is never linked). GD-ROM writers already hard-link unchanged tracks when the source is on the same
  disk (`gdrom.patch_gdi`); this catches the copies made from the NAS.

## Where it shows

* **Mods page**: the *Sonic showcase* builds filter (and a chip on each card); the fitting previews join the card's
  pictures. `GET /api/mods/built?kind=showcase` filters on the server.
* **Game right-click menu > Special builds**: the title's showcase stage, the build (selectable as the boot mod),
  the slots replaced, previews, and for a title without a writer what is missing.

## API

| | |
|---|---|
| `GET /api/showcase` | settings, phase, message, idle reason, current title / stage / job, queue (each title's stage), disk (used, budget, free, storage problem), builds this hour, last results, records |
| `PUT /api/showcase` (or `POST`) | `enabled`, `paused`, `favorites`, `recent`, `budget_gb`, `builds_per_hour`, `whole_cast_max_slots`, `interval_s`, `dedupe`, `pause_while_playing_anywhere` (clamped) |
| `POST /api/showcase/run` | run a pass now |
| `GET /api/showcase/{game_id}` | that title's record and readiness row (Special builds) |

Record stages: `building`, `built`, `unchanged`, `failed`, `deferred`, `evicted`, `over_budget`, `rate_limited`,
`waiting_storage`, `collecting_donors`, `no_donors`, `no_plan`, `readiness_queued`, `readiness_pending`,
`donor_game`. Builds are unverified in game until launched (the Mods page's Play / Screenshot after launch).
