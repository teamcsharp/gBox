# Spark2 / Hermes task dashboard — evidence (#7526)

Opened from the gBox PiP right-click menu → **Spark2 tasks** (also File ▸ Spark2 tasks,
`Ctrl+Shift+T`). A separate sandboxed popup window (`clients/desktop/task-window.*`), same
security model as the Mercenaries window: no API credential in the renderer, a read-only
GET-only whitelist, Three.js vendored locally for the CSP-locked (`default-src 'none'`) page.

## Files
- `dashboard.png` / `dashboard.svg` — the whole dashboard. **The 3D pane is the actual live
  WebGL frame** (`webgl-frame.png`, read straight off the GL buffer via `canvas.toDataURL`).
  The surrounding layout (tiles, node lanes, tray, expanded card) is rendered to SVG from the
  **real `/api/tasks` Hermes feed schema** captured from the Spark (`http://10.89.1.246:8765`),
  populated with representative sparkDeux agent runs so every panel is exercised. The live
  snapshot at capture time was 24 runs (11 running / 12 done / 1 failed).
- `webgl-frame.png` — the raw Three.js render: an extruded 3D donut of tasks-by-state (blue =
  in flight, green = done, red = failed) and a bubble field, one sphere per task, grouped into
  node lanes, sized by tokens, coloured by status.

## How it was produced
The real page (`task-window.html` + `task-window.js`) was loaded headless (software-GL) against
a stubbed read-only bridge serving the captured feed; the page rendered 24 cards, state "Live",
the expanded card's 3-step tool trace, the correspondence messages and the attached image. The
3D canvas pixels were read in-page (the headless build's compositor screenshot is broken, so the
full page is composited as SVG around the real GL frame).

## Not a game frame
This is a tool/analytics UI, so there is no in-game screenshot — the 3D pane is a genuine live
WebGL frame; the rest is a faithful layout render from the real feed.
