# Live picker (eyedropper) and pick whip

Status: **implemented on the client; identification and replacement grow with the backend tools.**

The pick whip is the one tool for pointing at something in the running game and doing something with it. Every game task should leave it stronger: a new profile, reader, writer or hot path makes the same menu do more without UI changes.

## What the operator can do

| Where | How | What happens |
| --- | --- | --- |
| Desktop app, any docked game | **Ctrl+I** (a global shortcut while a game is docked, so it works when the game has focus) or the status-bar dropper | The game pauses, the frame freezes, hovering outlines the character under the cursor and labels it (name, model, slot). Left click grabs it (extract + chat); right click opens the character menu. Esc closes and resumes the game. |
| Desktop app, any docked game | **Right-click a character** (`winembed.py` forwards right-clicks from the native game window) | The character menu opens at that point and the game pauses until the menu closes. "Game menu…" at the bottom opens the old game menu (autoplay, save states, settings). |
| Desktop app | **Alt+drag** (pick whip) or drag a collection card onto the game | The existing whip menus. "Replace live" now runs the same replacement chain as the character menu and streams it into the mini console. |
| Web viewer (streamed game) | **⌖** in the session bar, or right-click the picture | The same outline, label, menu and console on the MJPEG picture. |

### The character menu

* **Replace with…** opens a character browser with previews. Characters are filtered by compatibility: vehicles for vehicles, bodies for bodies. Ready-in-this-game characters come first, then previously fitted ones that need a rebuild, then everything else that has a model. Picking one runs `pick_replace` in live mode, then `pick_replace` in build mode if live did not take. Until `pick_replace` is registered, it runs `characters op=live_use`, and if that fails it files a rebuild request (`/api/requests/auto-mod-failure` with `needs_rebuild` and `replacement_requested`).
* **Copy to clipboard** puts the identification text on the OS clipboard. When the model can be extracted, it also puts the GLB on the gBox clipboard.
* **Copy to Blender** writes Blender's own clipboard on this PC with `blender_copy` (artifact = the extracted GLB, or the collection character), so you can press Ctrl+V in a 3D viewport. The Blender paste pop-up shows what was copied.
* **Open retarget editor…** asks for a donor in the same browser, then opens `GBoxRetargetEditor` for the donor, this game and the picked slot.
* **Identify** runs `pick_identify`, or `pick_preview` until `pick_identify` is registered. The entity, model, RAM, slot and evidence stream into the console.
* **Export to Blender (round trip)** puts the GLB on the gBox clipboard tagged with `round_trip`, `session_id`, `game_id`, `slot`, `name` and `pick`. In Blender, press Ctrl+Shift+V (gBox add-on) to import it, edit it, then use "Send to gBox"; the live link sends it back.
* **Show in Assets** opens the asset sidebar filtered to the model or name.
* Toggles: **Pause while picking** and **Cloud naming** (off by default; local only).

### Preselection outline

The outline uses the best evidence the picker returns, in this order (`outlineOf` in `clients/web/viz/pick-whip.js`):

1. `outline` / `silhouette`: a polygon from a screen-space mesh projection
2. `mask`: `{w, h, b64}` with one byte per pixel, nonzero meaning inside
3. `bounds` / `screen_box`: the entity's projected box. `gbox/entity_probe.py` returns pixels of the 640x480 picker frame, and these are scaled. The colour region inside the box is traced as the silhouette.
4. `screen`: the projected entity position, used with the colour region under the cursor when they agree; otherwise a character-sized box around the point
5. The colour region alone (flood fill on the frozen frame), when the game has no picker profile

Coordinates are in the picker's 4:3 picture unless `space: "window"` is set. They are mapped back through the window's letterbox or pillarbox. Hover requests use latest-wins scheduling: one `pick_preview` is in flight at a time, stale answers are dropped, and the outline eases toward its target, so moving the mouse never blocks the game or the UI.

### Emulation pausing

`POST /api/pickwhip/{sid}/hold {"op": "pause" | "renew" | "release", "holder", "ttl_s"}` (`gbox/pickwhip.py`):

* The game pauses with the first holder and resumes when the last holder releases. The eyedropper and the menu share one hold.
* A game the operator had already paused stays paused: the hold resumes only what it paused itself.
* Clients renew every 5 s, and the lease is 20 s. Three layers make sure a game is never left paused:
  1. The client releases on close or Esc.
  2. `clients/desktop/main.js` releases every hold it forwarded when the window crashes (`render-process-gone`), reloads, closes, or gBox quits.
  3. The server watchdog resumes any session whose leases have all expired.
* The pause goes over the live session channel (3 s), then the `session_op` job queue. An older control plane without the route falls back to plain `session_op pause/resume` from the client.
* Setting: the character menu's "Pause while picking", or the game menu's "⏸ Pause the game while picking". Settings are stored per viewer in `localStorage` under `gbox_pickwhip` with the keys `pause`, `rclick`, `cloud` and `name`.

### Mini console

Each task the menu starts (naming, identify, copy, Blender, replace, the eyedropper's grab) gets a small floating panel next to the picked character. The panel shows the job's progress percentage, the last progress lines, fit events (`job.fitting`: model, stage, state), and the end state. For a grab handed to the chat agent, it shows the agent's last tool calls. Panels stack, collapse (▾) and close (✕), and the stack can be dragged.

### Local LLM tool handling

`pick_name` (`gbox/pickwhip.py`) names the pick on a local model. It runs on the Spark next to Ollama, using `require_os: "linux"` and `target_session` instead of `session_id`, so it never takes the gaming PC. The model is the one chosen in the app header (for example `gemma4:e4b`; Auto means the local default). The model gets OpenAI-style tools:

* `pick_preview`: fast, the entity under a point
* `pick_identify`: deeper, the model, RAM, Ghidra/REA evidence and slot
* `report_pick`: the final answer, with `name`, `kind`, `model`, `slot`, `confidence` and `why`

The tool calls run as ordinary jobs on the session's PC. Routing (`llm_routes`) tries endpoints in this order:

1. The header model on the agent's Ollama (`agent.llm_url`)
2. The header model on every `llm_endpoints` entry without an API key
3. Those entries' own models
4. Cloud endpoints, which are `llm_endpoints` entries with an `api_key_env` whose variable is set. These are used only when "Cloud naming" is allowed and no local model answered.

If no model is available, the answer falls back to the picker's own evidence (entity class or model mapping), so the pick whip never needs cloud credit. Vision-capable header models also get a crop of the frozen frame.

## Backend contracts the client is ready for

These tools are built by other work. The client calls them through `/api/jobs` and degrades gracefully while they are missing (404 "unknown tool").

* `pick_identify {session_id, x, y}` returns a result that may contain `entity` (`{name, class, kind, ptr, model, slot, outline | mask | bounds | screen}`), `model`, `ram`, `slot`, `evidence` / `ghidra` / `rea`, `package` (an extracted UAP), and `collection` (`{slug}`) for a known collection character.
* `pick_replace {session_id, pick, character, mode: "live" | "build"}` returns a job with fit events. `pick` carries `{x, y, window_aspect, entity, slot}`. A `result.status` matching `unsupported|failed|error|missing|blocked|reverted|no writer` counts as "did not take", and the client then tries the build mode.
* `pick_preview` and `pick` are unchanged. Probe-based picks (`picked.screen_box` in picker pixels) are outlined from their box.

## Files

* `clients/web/viz/pick-whip.js` is the shared logic and UI (geometry, hover scheduler, hold, tool fallbacks, menu, browser, console, and the web overlay `mountOverlay`).
* `clients/desktop/index.html` has the eyedropper (outline and label, hold), `pwRightClick`, `pwMenuAt` and `pwIO`, and whip "Replace live".
* `clients/desktop/main.js` releases holds on crash, reload, close or quit.
* `clients/web/index.html` has the ⌖ button, right-click on `#scr`, and the `mountOverlay` IO.
* `clients/web/viz/asset-sidebar.js` gained `reveal(q)` for "Show in Assets".
* `gbox/pickwhip.py` has the pause hold, the watchdog and `pick_name`. It is wired in `gbox/server.py` and listed in `gbox/tools.py` tool modules.
* Tests:
  * `tests/test_pick_whip_ui.cjs` covers geometry, the hover scheduler, the hold, the fallbacks and the menu flows on a fake DOM.
  * `tests/test_pickwhip_desktop.cjs` covers routing, holds and main's resume.
  * `tests/test_pickwhip_glue.py` covers the hold routes, the watchdog and the `pick_name` tool loop.

## Remaining work

* A live outline over the running (unpaused) native game would need a transparent overlay window like `overlay.js`. With pausing on, the frozen frame shows the same picture.
* Per-game profile `camera` and `models` mappings, and `pick_identify`, are still what make identification semantic. Unsupported games show the colour region and let the local model describe the crop.
