# Build notifications

Every build a worker finishes (usually the Spark) shows up in the header bell tray of the desktop app and the web
client, with a picture, a one-line summary and a Play button. Nobody has to call `/api/notify`: the control plane posts
the entry itself when a job ends (`gbox/build_notify.py`).

## What posts an entry

| Job | Entry | Example |
| --- | --- | --- |
| A job whose result names a mod / build: `result.mod`, `result.build.mod`, a result folder under `<cache>/mods/<game>/<mod>`, or a build op (`use`, `match`, `cast_swap`, `build`, `export`, `stage` ...) that succeeded | `kind: "build"` | "Sonic Adventure: cast as Sonic Heroes is ready" · "4/4 slots built · Sonic, Knuckles, Amy, Gamma" |
| The same jobs failing, or answering a failure status (`unsupported`, `needs_source`, `overlay`, `failed` ...); also a build job rejected at submit or lost to a worker restart | `kind: "error"` with the reason | "Build failed: characters use" · "writer crashed: too many bones" |
| `characters op=collect` | `kind: "collect"` | "12 characters collected from Sonic Adventure" |
| A new build folder the built-mods index finds that no job reported (built in the last 2 hours) | `kind: "build"` | "new build folder ..." |

Detection reads the job's input op and result fields, never a list of writers, so a new builder is covered as soon as
its result names its mod (or its folder). Launches, frames, session ops, task lists, plans (`plan_only`), reuse of an
existing build (`status: ready / launched`), live changes to a running game and operator-cancelled jobs post nothing.

## One entry per pass

One notification per job, and a pass that queues many jobs does not flood the tray. An entry collects:

* jobs queued within 10 s of each other (Special builds "Rebuild all", a showcase): for up to 6 hours,
* jobs of one parent request: while they keep finishing within 30 minutes of each other,
* same-kind jobs finishing within 60 s of each other.

The entry then reads "3 builds ready, 1 failed" with one row per build (its own picture, Play, ▾ and Open in Mods, or
the failure reason and Retry build). A result delivered twice replaces its row; a job's row replaces the row the index
posted for the same folder.

## The record

`GET /api/notify` returns the old fields (`id, title, text, session_id, kind, ts, read, by`) plus, for these entries,
`auto: "build"`, `count`, `items` and the first item's fields at the top level:

```
{ "kind": "build", "game_id": "sadx", "game_title": "Sonic Adventure DX", "mod": "cast_sadx_heroes",
  "mod_title": "...", "job_id": "...", "summary": "4/4 slots built · Sonic, Knuckles, Amy, Gamma",
  "thumbnail": "/api/notify/<id>/thumb?i=0&v=..", "thumbnail_source": "capture",
  "launch": [ {"id": "here", "label": "This PC", "default": true, "call": {"method": "POST",
              "path": "/api/games/sadx/launch?node=auto&mod=cast_sadx_heroes"}}, ... ],
  "items": [ {kind, job_id, tool, op, game_id, mod, summary, node, launch, thumbnail, thumbnail_source,
              error?, retry?, request_id?, collected?, total?}, ... ] }
```

`launch` is `gbox.special_builds.launch_options`: Play on this PC (default), each online PC, the saved moment when
the mod card links one, the Spark debugger. It is recomputed on every read for the PCs online now. `retry` is the call
that builds it again (characters: the Special builds recipe, `launch: false, rebuild: true`, on the Spark).

`POST /api/notify` still takes `{title, text, session_id, kind}`; a builder may add `game_id, mod, thumbnail, launch,
job_id, summary` (a `kind: "build"` entry with a mod gets launch options filled in). `POST /api/notify/read_all` marks
everything read.

## The picture ("a moment it captured")

`GET /api/notify/{id}/thumb?i=<item>` resolves the best picture now and redirects (307, keeping the token) to its
authenticated URL, so a capture that arrives after the build replaces the preview:

1. **capture**: a frame of the build running: the mod card's thumb / in-game shots (Screenshot after launch, a verified
   boot), a `screenshot` / `capture` / `boot` picture in the build folder, an image artifact of the job named like a
   frame or screenshot.
2. **fitting**: the fitting preview pictures the writer streamed for the replaced characters (`gbox.fit_events`).
3. **preview**: the build folder's own preview pictures (`preview.png`, `frames_preview.png`, `atlas.png` ...), then
   the job's image artifacts.
4. **donor**: the donors' collection previews (`/api/characters/{slug}/preview`).
5. **boxart**: the game's box art (`/api/media/{game}/best?w=360`).

No game session or emulator is ever started to take the picture. (There is no headless build-capture tool on the Spark
today; when one exists it can add its frame as a mod card shot and the thumbnail picks it up.)

## The tray

`clients/web/viz/build-notes.js` renders the entries in the bell tray (the desktop app shows the same web view):

* **build**: picture, title, summary, time, **▶ Play** (this PC's worker, through the game menu's launch, the path
  Special builds and the Mods page use: the mod is staged / fetched there, swapped into the game if it is running),
  **▾** for the other launch options, **Open in Mods**.
* **error**: the reason, **Open request** (the request the job belonged to or the auto failure report), **⟳ Retry
  build** when a recipe exists.
* **collect**: **Open models**.

The bell shows the unread count; **Mark all read** clears it. A new entry (or a group that grew) shows a toast with
Play; in the desktop app the view also asks the shell (`GBOX:{"ev":"buildnote"}`) for an OS notification when gBox is
not in front, and clicking it brings the window back with the tray open. A plain browser uses the Notification API
once the operator allowed it (asked on the first bell click). The tray reads `/api/notify` on its existing 5 s poll.

Toasts are cards in one stack (`clients/web/viz/toast-stack.js`, both shells): top-right, right under the header as
measured (the page's header wraps to two rows in the desktop app's narrower view; a toast fixed 52 px from the top sat
over it and lost the first line of its title), newest first, at most six, capped to the room left in the window so the
stack scrolls inside itself, laid out again on resize and when the header changes height. Titles and text wrap. The
desktop shell's own toasts (`toast()`, build notes while another page is in front) use the same stack below its title
bar and chat bar, and a docked game window cuts `#gbox-toasts` out of itself. The bell tray, the process pop-up, the
pick whip's mini console and the last-played pop-up are kept inside the window and below the header the same way; the
launch bar's failure line wraps instead of cutting off.

Tests: `tests/test_build_notify.py` (server), `tests/test_build_notes.cjs` (tray rendering and Play wiring),
`tests/test_toast_stack.cjs` (toasts clamped in small and large windows, stacking, scrolling, resize).
