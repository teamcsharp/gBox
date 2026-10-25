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
mirrors and is never listed on its own. A build only a PC has shows as `local only` and launches on that PC.
Startup does not upload its files. `sync_mod_builds_on_startup = true` explicitly enables that worker's background
uploads to its configured control plane; the default is `false`. Operator-triggered build downloads, exports,
and launch staging remain available. Heartbeats report build metadata without sending the build's files.

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

## What this changes

Every Mods card, Builds row (one line, and the full block in Details ▸) and Special builds row says what the build does
(`what` on every listing, from `gbox/build_summary.py`):

1. **Recorded**: the marker's own text (`what`, `summary`, `description`, `notes`, ...), its cast rows, its donor → slot
   rows, its codes, cheats and patches (plus the mod card's extra calls), its compile facts, and its file changes. When
   none of these exist, the mod card's own description is used (not the stand-in text the gallery writes).
2. **Compared**: when nothing is recorded, the build's files are compared with the game's base copy
   (`modbase/<game_id>`). The background sizer of the built-mods index runs `built_mods.base_diff` once per marker. A
   hard link or equal bytes count as the same file, and an equal-size file over 8 MB counts as "may differ". If nothing
   differs, the badge **"No changes from the original game found: this looks like a test build"** shows.
3. **Inferred**: read from the build name using a writer's vocabulary. For AUF this is the maps, mission levels and
   body keys of `auf_swap`, so `auf_dm1_bondcombat_uwbthug` reads as "multiplayer map dm1; characters Bond (combat) and
   Underwater base thug". The first sentence of the writer module's docstring is added too (parsed, never imported).
   Every inferred line is labelled **inferred**.
4. Otherwise the badge reads **"Changes not recorded"**.

**Where to look in game** comes from the marker (`where_to_look`, `where`, `level`, `map`, `stage`, `mode`, ...), the
slot names, the recipe's slot, or the name: "Multiplayer > map dm1 > play as Bond (combat)", marked inferred.

## 🗑 Delete

The 🗑 button sits at the bottom right of a Mods card, next to ▶ Launch / ▾ on a Builds row, and in every options menu
(Mods ⋯ or a right-click, Builds ▾ or a right-click, Special builds ⋯). It opens a dialog (`viz/build-actions.js`)
showing the name, folder, game, size and where the build lives, with three choices: **Delete everywhere** (the Spark
collection plus every PC's copy; the default), **Only this PC**, or **Attached computers (keep Spark collection)**.
The attached-computer choice lists each PC reporting a local or staged copy (for example i9-NUC and
JAYBUILTFINALE). Check one or more PCs explicitly; no PC is preselected.

`DELETE /api/builds/{game_id}/{name}?scope=all|node&node=<PC>`, or `POST .../delete {scope, node}` for clients whose
api() only posts:

* `scope=all` removes the Spark's folder and its staged copies (`<name>~<build>` or a folder whose staging mark names it)
  with their hash sidecars. It also drops the build from the built-mods index (`Index.forget`), clears its display name,
  favorite and report mark and the stand-in mod card the gallery registered, and marks a showcase record as deleted.
  It then queues `file_mod op=delete_build` on every online PC whose heartbeat lists a copy. Offline PCs are listed as
  skipped, with a reason.
* `scope=node` deletes only that PC's copy (the Spark's copy when the node is the Spark).
* `POST .../delete {scope: "pcs", nodes: ["i9-NUC", "JAYBUILTFINALE"]}` queues deletion only on selected
  attached PCs. Spark files, display names, favorites and build cards remain. Every target is validated and checked
  for running games before any job is queued. Unknown PCs, Spark/Linux targets, empty selections and stale copy
  inventories are rejected. Offline PCs are reported as skipped; they are not silently scheduled or counted as deleted.
  The selected names are retained in the response, audit and deletion log. Broken-build investigation protection
  still applies, so evidence cannot be removed before its investigation finishes.
* The request is refused (409) while a running game uses the build or one of its staged copies. The worker checks
  again before deleting (`filemods.delete_build`).
* The base copy (`modbase/`) and other builds are never touched. A build that only shares a name prefix, such as
  `bb` next to `b`, is another build.
* Every delete is written to the audit log (`build.delete`) and to the recently deleted list (`GET
  /api/builds/deleted`: the marker facts, size, scope, jobs). There is no undo.

## ⬇ On this PC: download, export (#1639)

Every Mods card (top-right corner of its picture) and every Builds row (right end) has a download icon for the PC the
view runs on (the desktop app's worker; a plain browser shows it greyed out):

| Icon | Means | A click |
| --- | --- | --- |
| filled check | the build is in this PC's cache (its heartbeat's `local_builds`, a staged copy counts): it plays at once, offline | opens the menu |
| download arrow | not on this PC | downloads it: `build_local op=download` stages it into this PC's cache (`filemods.stage`, the pinned manifest, resumable); nothing is launched |
| ring with a percent | downloading | - |

Right-click the icon (or its ▾): **Download to this PC**, **Export…**, **Open folder** (this PC's cache folder of the
build, in Explorer) and **Delete from this PC** (the Delete dialog limited to this PC's copy: `scope=node`).

**Export…** writes the build into `<chosen folder>/<game title> - <build name>/` on this PC (never over the original),
as a `build_local op=export` job on this PC's worker (it downloads the build first when needed); the desktop app picks
the folder (Electron dialog through the preload bridge; inside the embedded view through the `GBOX:` console bridge),
shows the job's progress, the final path and **Show in folder**. Formats (`gbox/build_export.py`):

| Format | What is written |
| --- | --- |
| Same format as the original (default) | the catalog file's own container, keeping its file name: `.iso` / `.gcm` / `.bin` / `.cue` + tracks / `.gdi` + tracks / `.z64` / `.zip` as built; `.gcz` and `.cso` written by gBox; `.n64` / `.v64` byte order; a `.zip` original zips the image under its inner name; `.chd` with `chdman` (`createcd` for cue / gdi / CD images, `createdvd` for DVD images); `.rvz` / `.wia` with dolphin-tool; `.wbfs` with `wit`; folder games keep their disc folder; a Wii tree is rebuilt with dolphin-tool. A missing program never fails it: the plain image is exported and the result says which program would make the original format |
| Plain image | the uncompressed image the build boots |
| Patch only | BPS (+ IPS up to 16 MiB, + xdelta when `xdelta3` is installed) against the operator's original on this PC (`romexport`'s writers); a folder build: a patch kit |
| Zip | the plain files in one `.zip` |

`GET /api/builds/local?node=<PC>` lists that PC's builds, `GET /api/builds/{game}/{name}/formats` the dialog's
choices, `POST /api/builds/{game}/{name}/local {op: download | locate | export, node, dest, format, label}` queues the
job on that PC (409 when its worker has no `build_local` yet, 422 for the Spark or an unknown PC).

## ⚑ Report

**⚑ Report** sits at the bottom right of every Mods card. It is also ⚑ on Builds rows and "Report a problem…" in each
options menu. It opens a dialog with quick reasons ("Doesn't show the expected change", "Character looks broken or
garbled", "Game crashes or freezes", "Other") and a text field.

`POST /api/builds/{game_id}/{name}/report {reason, note}` files the report through the issue flow
(`/api/requests/issue`, no game session involved). The report is titled "Build report: `<name>` (`<game>`): `<reason>`".
Its body holds the game, the build, the writer, the slots and donors, What this changes and where to look, the build
recipe and the last launch. The card's newest in-game frame is the report's screenshot, and that frame plus the build's
preview / fit pictures are attached. The report is then sent to the investigation queue that the launch failure reports
use (`_lf_investigate`, docs/launch-failure-reports.md): it goes to the top of the Hermes work queue and, in Hermes task
mode, is dispatched at once as "gBox build report #N". The card shows a purple **⚑ Build report #N** badge (store kind
`build_report`). It sits in the same badge row as a launch failure's "⚠ Reported as #N, being investigated" or "✓ Fixed,
verified" badge, and both open their request.

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
* `tests/test_build_local.py` / `tests/test_build_local.cjs` (#1639): the export format choice, the GCZ / CSO / byte
  order / zip writers, chdman present or missing, patch / plain / zip, the `build_local` op, the routes; the icon's
  states, its menu, the download flow, the Export dialog and where the icon shows.
