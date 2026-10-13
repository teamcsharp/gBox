# Live picker (eyedropper)

Status: **partially implemented**.

* `pick_preview` backend tool — fast, non-pausing semantic preview that returns the entity under the cursor, its live RAM, profile evidence (struct / table / model), and the nearest alternatives.
* Desktop game eyedropper (`clients/desktop/index.html`) now shows a live pre-selection PiP with pixel/region info, semantic entity details, RAM hex dump, reverse-engineering evidence, and the closest model mapping.
* Clicking a selection in the game eyedropper first runs a full `pick` extraction; if the backend finds a known model it is sent to the chat as an asset card and copied to the Blender clipboard. The vision/chat request still fires, but is primed with the semantic pick details so the agent can focus on identification and further extraction.

Remaining work:
* Wire the same preview/extract path into the web viz overlay (`clients/web/viz`).
* Add hotkey affordance to `overlay_track.py` so Ctrl+I can be raised even when the game window has focus.
* Per-game profile `camera` and `models` mappings are still required for semantic picking to return anything; unsupported games fall back to vision-only extraction.

## Identify and replace backend

`pick_identify` and `pick_replace` (docs/live-inject.md) are the pick whip's backend.

* `pick_identify {session_id, x, y, region?}` returns the entity under the point, its writer slot, and its RAM: the entity struct, model / node tree, display lists, vertex buffers, skeleton and textures. It also returns evidence (profile, `oot_live`, `doa2_context`, pointer walk, learned paths, Ghidra), a confidence, and `replaceable {live, build, reason}`.
* `pick_replace {session_id, pick, character, mode: live|build}` emits fit events for the slot. `live` writes the fitted model into the running game's RAM: paused, verified, and restored on failure. `build` (also live's fallback) builds the writer's mod and swaps the session to it, keeping the moment.

Each pick teaches the game's learned profile (`/api/profiles/{game_id}/pick`), so the next one is faster.