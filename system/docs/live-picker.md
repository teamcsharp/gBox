# Live picker (eyedropper)

Status: **partially implemented**.

* `pick_preview` backend tool — fast, non-pausing semantic preview that returns the entity under the cursor, its live RAM, profile evidence (struct / table / model), and the nearest alternatives.
* Desktop game eyedropper (`clients/desktop/index.html`) now shows a live pre-selection PiP with pixel/region info, semantic entity details, RAM hex dump, reverse-engineering evidence, and the closest model mapping.
* Clicking a selection in the game eyedropper first runs a full `pick` extraction; if the backend finds a known model it is sent to the chat as an asset card and copied to the Blender clipboard. The vision/chat request still fires, but is primed with the semantic pick details so the agent can focus on identification and further extraction.

* Pick whip, collection card dropped on a game: for games with a slot resolver (`characters op=resolve_slot session_id
  x y`; today Metal Gear Solid VR Missions, `gbox/mgs_vr_tool.py` op=pick through the game's own view matrix) the menu
  names what is under the drop ("Put Sonic in place of Genome soldiers (every VR soldier)") and "Replace it in the
  running game" runs `characters op=live_use` with that slot: the disc is rebuilt with the replacement stacked on the
  session's current mod and applied through session_swap at the same moment. OoT keeps its in-RAM object swap
  (`oot_hot_swap`); other games answer unsupported and the menu keeps its generic choices.

Remaining work:
* Wire the same preview/extract path into the web viz overlay (`clients/web/viz`).
* Add hotkey affordance to `overlay_track.py` so Ctrl+I can be raised even when the game window has focus.
* Per-game profile `camera` and `models` mappings are still required for semantic picking to return anything; unsupported games fall back to vision-only extraction.