# Builds view

The top bar's **Builds** tab (web shell `clients/web/index.html`, so also the desktop app, which shows the web shell)
lists every custom / modified build and the build jobs that are queued or running. View: `clients/web/viz/builds.js`;
server: `gbox/builds.py`; build record helper: `gbox/build_record.py`.

## Custom builds

One row per build, newest first:

| Column | From |
| --- | --- |
| thumbnail | the mod card's in-game shot, else the build folder's preview picture, else the first donor's collection preview |
| name | the display name (double-click to rename), else the writer's title; the folder name is in the tooltip |
| game | the catalog title |
| kind | every kind the build is (the first one is its primary kind): cast swap, character swap, file mod, cheats, ROM hack, decomp / compile, showcase, test |
| built | the marker's build time (full date in the tooltip) |
| size | the build's own bytes (hard links to a shared base copy left out); `sizing…` until the index has walked the folder |
| lives on | `Spark collection` and each PC that has it: `<PC> (local copy)`, `<PC> (staged copy)`, or `<PC> (local only)` for a build that has not reached the Spark yet |
| ▶ Launch / ▾ | the Special builds launch options: this PC (default), each online PC, the saved moment, the Spark debugger |

Search matches name, display name, writer title, game, writer, kind, donors, slots and `#request`. The game and kind
filters narrow the list.

**Where builds come from.** The Spark's central collection is the built-mods index (`gbox/built_mods.py`, no disk scan
on request). Each PC's worker reports its own builds with its heartbeat (`WorkerInfo.local_builds`:
`{game_id, name, built, staged_of?}`, newest 400, from `gbox.filemods.local_builds`: two directory levels and one stat
per build, cached 60 s). A staging copy (`<mod>~<build>` or a folder with `.gbox-staged-of`) counts for the build it
mirrors and is never listed on its own. A build only a PC has shows as `local only` and launches on that PC. The worker
uploads it to the Spark the next time it starts.

**Kinds.** A marker `kind` wins. Otherwise the kind is derived. `showcase` comes from a `showcase` record or a
`showcase_` name. `cast swap` comes from `cast` rows, and `character swap` from donor → slot rows. `decomp / compile`
comes from a `compile` record or compiler keys. `ROM hack` comes from byte patches in `file_changes`. `cheats` comes
from codes in the marker or extra calls on the mod card. `test` comes from linked requests, `test: true` or a
`test_`/`tmp_` name. Anything else is a `file mod`.

## Renaming

Double-click a name, type, then press Enter (or click away). Escape cancels. An empty name restores the writer's title.

`PATCH /api/builds/{game_id}/{name}` `{display_name}` (≤ 120 characters) stores it in the store (kind `build_name`,
key `game_id/name`). The built-mods gallery joins it as `mod_title`, with `display_name` and `original_title`, so the
Mods page, the game menu's Special builds and build notifications all show the new name.

**The folder and its `.gbox-mod.json` are never renamed or rewritten.** The marker is part of the build's pinned file
manifest (`gbox.filemods.stage` compares every file). Changing it would make every PC stage the whole build (a full
disc image) again.

Since #1656 a build can also be renamed from:

* the **Mods page** card: click the name or ✎, or ⋯ / right-click the card and pick Rename…;
* the **Builds** tab: ✎ next to the name, or ▾ / right-click the row and pick Rename…;
* the game's right-click **Special builds** section: ⋯ on a build, then ✎ Rename….

Every one of these opens an inline field: Enter saves, Escape cancels, and an empty name restores the writer's title.
The field carries `data-nomic` because the web shell's dictation wrapper moves text fields, which blurs them, and a
blur saves and closes the field. `POST` to the same path renames too, since the desktop app's IPC `api()` used to post
every body.

The display name is the build's "official name" everywhere it shows: the Mods page, Builds, Special builds, the
game menu's "Boot with a mod" (`GET /api/mods` adds `display_name` next to the card's own `title`, and the saved card is
never rewritten), the launch screen, the launch bar (`launch_game` / `session_swap` jobs carry `mod_title`),
notifications, and the desktop Mini window title (`GET /api/sessions` adds `mod_title`).

## Favorites

☆ / ★ on each Mods card and Builds row stars a build: `PUT /api/builds/{game_id}/{name}/favorite` `{favorite: true |
false}` (POST does the same), and `DELETE` un-stars it. The star is kept in the store (kind `build_favorite`, key
`game_id/name`) and the folder is never touched.

* Favorites list first on the Mods page and in Builds. A **★ Favorites** checkbox filters to them, and
  `GET /api/builds?favorite=true` / `GET /api/mods/built?favorite=true` do the same.
* The game's Special builds section puts them in a **Favorites** group at the top. The group is shown only when there
  are favorites. Each build keeps a `home` group, so "Rebuild all confirmation builds" still includes a favorited
  confirmation build.
* The game menu's "Boot with a mod" lists ★ builds first.
* Favorites are never evicted. `gbox.built_mods.protected(store, game_id, mod)` names the reason, and a disk-budget
  sweep (the Sonic showcase's LRU eviction on the `sonic-showcase` branch) must skip any build it names. The cache's
  own eviction (`catalog.evict`) never touches `mods/` at all.

## Details ▸

`GET /api/builds/{game_id}/{name}/details` loads when the row opens:

* **Modifications**: the marker's `file_changes` (path, change: replaced / patched / new / image, size, base size,
  byte patches). Older builds derive these from `files` / `image`. The sizes of the named files are stat'ed (at most
  64). Base sizes and the kind of each change were not recorded then, and the view says so.
* **Characters inserted**: slot ← donor with the status and reason. Each slot has two 360° viewers:
  * *Who they are*: the donor as fitted. The source is, in order: a fitted model the writer kept under
    `<slug>/targets/` in the collection (`sm64_mario.gltf` and the like), then the build job's fitting snapshot
    (`/api/jobs/{id}/fitting/files/…`, kept 3 days), then the donor's collection model, labelled "not fitted".
  * *Who they're replacing*: the target game's own character from the collection, matched by the slot name (the cast
    record's `slot_name`, else the slot's last part) against the names, slugs and aliases of characters extracted
    from that game. When no match exists, the viewer says to extract the game's cast.
* **Codes, cheats & hacks**: the marker's `codes` / `cheats` / `unlocks` / `patches` / `ram_writes` / `hacks` /
  `changeset` entries, plus every call besides `@launch` on the build's mod card. These are cheat codes, `re_mods`
  code patches, `write_memory` / `poke` / `freeze_memory` / `game_link` RAM writes, `mgs_vr` unlocks, `re6` hacks
  and `*_mods` change sets.
* **Compile changes**: the marker's `compile` record or compiler keys (`compiler`, `compiler_flags`, `flags`,
  `toolchain`, `defines`, `source_patches`, `decomp`, `recomp` …).
* **Build recipe**: the Special builds recipe (recorded, or inferred from the marker) with **⟳ Rebuild** (queued on
  the Spark, never launches). Below it is the exact call recorded at build time (`build_call`).
* **Jobs & receipts**: the recorded `job_id` and the jobs whose result names the build. Each job opens its
  investigation. Receipts show validation and artifact links.
* **Verification**: verified, or *unverified in game until launched*, plus the launch history (sessions that ran the
  build) and the last failed launch.

### The 360° viewers

The GLBs load only while the details are open and only once a viewer is on screen (an IntersectionObserver with a
120 px margin). Until then, and whenever a model can't load, the viewer shows the collection preview picture. One shared
WebGL renderer draws every visible viewer and copies each frame into that viewer's own 2D canvas. A whole cast fits
without hitting the browser's WebGL context limit. Off-screen viewers are not drawn. Each model turns once every 9 s.
Collapsing the row disposes its models (geometry, materials, textures) and stops observing them. Leaving the tab frees
everything.

## Scheduled & running

`GET /api/builds/scheduled` lists queued, claimed (running, no progress yet) and running build jobs, running first.
The last 12 finished in the past 6 hours are listed too. Build jobs are:

* `characters` `cast_swap` (or `showcase` with a `showcase_` mod name)
* `characters` `use` / `match` (character swaps; rebuilds are marked)
* `characters` `collect`
* `file_mod build`, `rom_export export`, `n64recomp run`, `um_mod stage` and `*_mods build|export`

Plans (`plan_only`), launches and live changes are not build jobs.

Each row shows the state, the worker (or what it waits for), progress, the last message and an ETA. The ETA is the
elapsed time × remaining / done, once the job passes 2 %.

* **Cancel**: `POST /api/jobs/{id}/cancel` (a queued job is dropped; a running one stops at its next progress report).
* **Edit** (queued only): a form with the job's input. Scalars are fields; lists and objects (assignments, pairs,
  changes) are JSON. **Save & requeue** sends only what changed to `POST /api/builds/scheduled/{id}/edit` `{input}`.
  Under one store lock, the server queues the same tool with the merged input. The new job keeps the old job's OS / PC
  pinning, parent request and agent flag, and records `edited_from`. Once the new job is accepted, the old one is
  cancelled (`replaced_by`). The `op` can't change. A rejected or invalid edit leaves the old job queued. The queue is
  first come, first served, so the edited job runs after the jobs already waiting.
* **Investigate**: `GET /api/builds/scheduled/{id}` shows the log tail (the progress messages while it runs), the
  receipt with its validation problems, artifact links, the fitting events per model and the result's per-slot
  report.
* **Details ▸**: a three.js flowchart in the Tasks window's task-network style:
  `queued → claimed → stages → write → verify → done`. The stages are the fitting stages folded over every model
  (`stages: [{name, state, done, total}]`). Jobs without fitting events show their last distinct progress messages
  (`steps`). Done nodes are green and pending ones grey. The current node pulses with a spark running into it. A failed
  job turns the node where it stopped red, and the last node reads `failed` or `cancelled`. The same chain is printed
  as text under the canvas.

## The build record (going forward)

`gbox/build_record.py` is the small shared helper the build paths use to write these facts into the marker at build
time (`stamp(meta, **fields)`, `stamp_marker(folder, **fields)`):

| Field | Written by |
| --- | --- |
| `kind` | cast swap builds (`cast`), the characters build path (`character` / `cast`), `filemods.build` / `build_image` (`file`, or `romhack` when bytes were patched) |
| `job_id`, `built_on {worker_id, os, host}` | the characters build path (`special_builds.record_call`), cast swap, `file_mod` |
| `build_call {tool, input}` | the characters build path, `file_mod` (bounded: file bytes become `<n bytes>`) |
| `slots [{slot, slot_name, donor, donor_name, source}]` | cast swap |
| `file_changes [{path, change, size, base_size, patches, what}]` | `filemods.build` / `build_image` |
| `codes`, `compile` | available to writers: cheats, code patches, unlocks, RAM writes; toolchain, flags, source patches |

A build reused as it is (`status: ready / launched`) keeps its marker byte for byte. Writers that write their own
marker can call `build_record.stamp(meta, kind=…, codes=[…], compile={…})` before writing it.

## Tests

* `tests/test_builds.py`: the list, kinds, PC builds and staged copies, filters, rename (store only, marker untouched,
  shown on the Mods page and in Special builds), details derivation, scheduled jobs, edit, investigate and the build
  record.
* `tests/test_builds_view.cjs`: rows, rename, launch, details content, the turntables' lazy load and dispose on a
  three.js stub with a fake IntersectionObserver, the flowchart, Cancel, Edit, Investigate and the web shell tab.
