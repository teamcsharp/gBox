# Sprite capture (2D animation extraction)

`sprite_capture` (gbox/sprite_capture.py) lifts a sprite's animation out of a **running 2D game** from the point or
box the operator highlighted with the pick whip (#1438 scope b; #1384 animation extraction). The game is never
paused, stopped or sent input: the tool only watches the session's picture for a few seconds.

## What comes out

One job (`op=capture`) returns these artifacts (the result carries their sha256s under `artifacts`; fetch any of them
with `GET /api/artifacts/<sha>`):

| artifact | what |
|---|---|
| `frame_0000.png` ... | the PNG sequence: RGBA, transparent background, all frames on one canvas anchored on the sprite's centroid, consecutive identical frames merged |
| `sheet.png` | the frames on a grid (cell = canvas, no padding) |
| `sheet.json` | the index: each frame's box on the sheet, `duration_ms`, which source frames it came from, its tracked box in the picture; the `loop` found by frame similarity; fps, canvas, anchor, background mode |
| `preview.apng` (+ `preview.webp` when Pillow has libwebp) | a looping preview the app can show as an `<img>` |
| `clip.mp4` | H.264 through ffmpeg when ffmpeg is on the worker's PATH; otherwise the result says `mp4: "unavailable"` with `mp4_reason`, and the job still succeeds |
| `frames.zip` | the sequence and the index in one download |

The result also carries `frames` (unique frames), `source_frames`, `durations_ms`, `loop`
(`{start, length, repeats, frames}` or null), `boxes` (the tracked box per source frame, `[x, y, w, h]` in picture
pixels, null where the sprite was lost), `background` (`static` / `scrolling` / `flat`), `captured_fps` and `stored`
(the capture directory on the worker). With `save=true` (the default) the clip is also filed in the character
collection; see below.

## How it works

1. **Frames** are pulled at `fps` for `seconds` (default 4, max 20) from the session: its live MJPEG stream when the
   session has one (Spark sessions), else the adapter's `get_frame` (the emulator window on the operator's PC). A
   budget of 900 frames / 512 MB lowers the rate, never the length. The game's rate is the default when it is known
   (50 for PAL releases, 60 for consoles), else 30.
2. **Background estimate**: the per-pixel median of a sample of frames. When the camera scrolls, consecutive frames
   are registered first (phase correlation over the whole picture) and the median is taken in world coordinates, so
   the sprite is what differs from the scenery whether it moves across the screen or the camera follows it. When the
   scenery around the seed is one flat colour, that colour is the background instead.
3. **Tracking**: the connected component of "differs from the background" pixels at the seed (the nearest such pixel
   within a radius; inside the box when a box was given), then the component nearest the previous centroid in every
   later frame. Frames where nothing is found are listed in `lost_frames` and skipped.
4. **Cut-out**: every frame is cropped to the tracked box plus `margin`; pixels equal to the background estimate
   within `tolerance` (sum of RGB differences, default 24) are transparent. All crops share one canvas and are placed
   by the sprite's centroid, so a walk cycle lines up frame to frame.
5. **Dedup and loop**: consecutive identical crops become one frame with a longer `duration_ms`; the shortest period
   the unique sequence repeats with (seen for at least two frames and half a period) is the `loop`.

## Limits

- The sprite must **move against its scenery** during the capture (about its own width over the few seconds) or
  **stand on a flat colour**. An idle sprite over textured scenery is indistinguishable from the scenery by pixels
  alone; the tool says so instead of returning a smudge. Idle animations: capture them over a flat area (sky, a menu).
- Scenery that scrolls while a large HUD stays put can confuse the registration; parallax layers are not modelled.
- Sprites that overlap another sprite, or that stand on textured ground while the seed sits on flat sky, pull the
  neighbour's pixels into the cut-out.
- Frame rates: `get_frame` on a Windows worker is a window grab (tens of ms per frame), so `captured_fps` is what was
  actually achieved; the durations are computed from the nominal rate. MJPEG streams add JPEG noise: raise
  `tolerance` (48) when the edges come out speckled.
- Loop search covers the first 240 unique frames.

## Ops

- `capture`: `session_id`, `x`/`y` (the highlighted point) **or** `box` `[x, y, w, h]`; values all within 0..1 are
  fractions of the game picture (what the desktop app's whip reports), anything else is pixels. `seconds`, `fps`,
  `name` (the character: the collection entry), `clip` (the animation: `walk`, `jump`), `margin`, `tolerance`, `save`.
- `list`: the captures on this worker (`capture` ids, names, loop, where they are stored). `name` filters.
- `export`: `capture` id, `fmt` `mp4 | gif | webp | apng`, `scale` 1..8 (nearest neighbour), `loops` (gif/webp/apng:
  loop count, 0 = forever; mp4: how many times the detected loop plays). Returns the artifact sha.

## The collection entry

`save=true` files the clip in the character collection (gbox/characters.py) as a 2D entry: `kind: "sprites"`, the
model is the sprite sheet (`sheet.png`, previewed scaled up as pixel art), `picture: "2d"`, and `animations[]` lists
every clip captured for that name: `{clip, name, dir, sheet, index, preview, webp, mp4, frames, fps, loop, canvas}`
with paths relative to the entry (`clips/<clip>/...`, served by `GET /api/characters/<slug>/file/<path>`). A second
capture with the same `name` and another `clip` appends to the same entry. The model view can play
`clips/<clip>/preview.apng` directly or step the sheet with `sheet.json`. The library is written where the job runs
(`characters.library_root`), the same convention as `characters op=add`; a worker without the shared cache keeps the
capture directory and `capture.json` as the record, and the result's `collection` / `collection_error` say which.

## How the pick whip menu calls it

Drop the whip on the sprite, choose "Capture animation". The client posts one job; the server routes it to the
worker that owns the session (jobs carrying a `session_id` always run there):

```json
POST /api/jobs
{"tool": "sprite_capture",
 "input": {"op": "capture", "session_id": "<EMB.sid>", "x": 0.42, "y": 0.61,
           "seconds": 4, "name": "<what the operator typed>", "clip": "walk"}}
```

A box selection sends `"box": [x, y, w, h]` (fractions of the picture) instead of `x`/`y`. Poll
`GET /api/jobs/<id>` until `succeeded`; `output.result.artifacts.preview` is the looping APNG to show in the card,
`artifacts.mp4` the download (or `output.result.mp4 == "unavailable"`), `artifacts.zip` the PNG sequence.
Re-export at another size: `{"tool": "sprite_capture", "input": {"op": "export", "capture": "<id>", "fmt": "gif",
"scale": 4, "loops": 0}}` on the same worker (`require_worker`).
